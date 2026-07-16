"""Tests for the 2026-06-08 fix: Web UI chat degrades gracefully on a model stall.

Observed live 2026-06-08 ~17:55: the operator sent a chat message, llama3.1:8b
hit the 240s HTTP read-timeout, OllamaBrain.think() caught the exception and
returned "" -- and the Web UI showed NOTHING back. Two problems:
  1. think() collapsed a *timeout* (model alive but busy/cold) into the same ""
     as a normal empty reply, so the caller could not tell them apart.
  2. the chat brain shared the 240s learning timeout, so the operator waited a
     full 4 minutes before any feedback.

Fix:
  * BrainTimeout: think(raise_on_timeout=True) re-raises a real read-timeout as a
    typed error; default callers keep the historical degrade-to-"" contract.
  * _is_timeout_error: names httpx.TimeoutException explicitly (it is NOT a
    builtin TimeoutError) plus a bare-message backstop.
  * OllamaBrain(http_timeout=...): per-instance timeout; the UI brain wires the
    shorter CHAT_HTTP_TIMEOUT so an interactive turn fails fast.
  * The UI chat handler opts in, catches BrainTimeout, and emits a clear busy
    message instead of silence.
"""

import os
import importlib
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from models import ollama_brain
from models.ollama_brain import OllamaBrain, BrainTimeout, _is_timeout_error


def _make_brain(http_timeout=None):
    """OllamaBrain without touching the network (verify_model defaults off)."""
    return OllamaBrain(
        model="llama3.1:8b", log_fn=lambda *_: None, http_timeout=http_timeout
    )


def _wedge(brain, exc):
    """Make the plain chat path raise `exc` (no grounding pipeline)."""
    brain._query_router = None
    brain._evidence_collector = None
    brain._response_builder = None
    brain._chat = MagicMock(side_effect=exc)


# ---------------------------------------------------------------------------
# think() can now distinguish a timeout from an empty reply
# ---------------------------------------------------------------------------
class TestBrainTimeoutContract:
    def test_raises_braintimeout_when_opted_in(self):
        brain = _make_brain()
        _wedge(brain, httpx.ReadTimeout("timed out"))
        with pytest.raises(BrainTimeout):
            brain.think("czesc", raise_on_timeout=True)

    def test_default_still_degrades_to_empty(self):
        # Every existing caller (router, REPL, daemon) relies on this: a stall is
        # swallowed to "" unless the caller explicitly opts in. Zero blast radius.
        brain = _make_brain()
        _wedge(brain, httpx.ReadTimeout("timed out"))
        assert brain.think("czesc") == ""

    def test_non_timeout_error_returns_empty_even_when_opted_in(self):
        # Only a *timeout* is special. A bad reply / parse error still degrades to
        # "" so we never raise the busy message on an unrelated failure.
        brain = _make_brain()
        _wedge(brain, ValueError("bad reply"))
        assert brain.think("czesc", raise_on_timeout=True) == ""

    def test_timeout_records_failed_tape(self):
        # The stall must still be recorded as a failed turn for the tape/trace.
        brain = _make_brain()
        _wedge(brain, httpx.ReadTimeout("timed out"))
        brain._record_tape = MagicMock()
        with pytest.raises(BrainTimeout):
            brain.think("czesc", raise_on_timeout=True)
        brain._record_tape.assert_called_once()
        assert brain._record_tape.call_args.kwargs.get("success") is False


# ---------------------------------------------------------------------------
# _is_timeout_error: the httpx-vs-builtin gotcha, named explicitly
# ---------------------------------------------------------------------------
class TestIsTimeoutError:
    def test_recognizes_httpx_timeout(self):
        assert _is_timeout_error(httpx.ReadTimeout("x")) is True
        assert _is_timeout_error(httpx.ConnectTimeout("x")) is True

    def test_recognizes_builtin_timeout(self):
        assert _is_timeout_error(TimeoutError("x")) is True

    def test_recognizes_bare_timed_out_message(self):
        # The live 2026-06-08 case logged a plain "timed out" with no typed class.
        assert _is_timeout_error(Exception("timed out")) is True

    def test_rejects_unrelated_error(self):
        assert _is_timeout_error(ValueError("bad json")) is False
        assert _is_timeout_error(KeyError("missing")) is False

    def test_httpx_timeout_is_not_builtin_timeouterror(self):
        # The whole reason _is_timeout_error names httpx explicitly: an
        # `except TimeoutError` would let an HTTP read-timeout slip through.
        assert not issubclass(httpx.TimeoutException, TimeoutError)


# ---------------------------------------------------------------------------
# Per-instance chat timeout: the UI brain fails fast
# ---------------------------------------------------------------------------
class TestChatHttpTimeout:
    def test_http_timeout_param_overrides_client_timeout(self):
        brain = _make_brain(http_timeout=75)
        assert brain._http_timeout == 75
        # ollama.Client wraps an httpx.Client whose .timeout reflects our value.
        assert brain._client._client.timeout.read == 75.0
        assert brain._client._client.timeout.connect == 75.0

    def test_http_timeout_defaults_to_shared_when_none(self):
        from maria_core.sys.config import OLLAMA_HTTP_TIMEOUT
        brain = _make_brain(http_timeout=None)
        assert brain._http_timeout == OLLAMA_HTTP_TIMEOUT

    def test_chat_timeout_config_default_is_75(self):
        from maria_core.sys import config as cfg
        with pytest.MonkeyPatch.context() as mp:
            # config.py calls load_dotenv() at import, and importlib.reload re-runs
            # it -> it would re-inject CHAT_TIMEOUT from the live .env (150) and
            # defeat the delenv below. No-op load_dotenv for the reload so we
            # measure the CODE default (75), not the operator's armed value.
            mp.setattr("dotenv.load_dotenv", lambda *a, **k: None)
            mp.delenv("CHAT_TIMEOUT", raising=False)
            importlib.reload(cfg)
            assert cfg.CHAT_HTTP_TIMEOUT == 75
        # Restore real module state (load_dotenv + .env active) OUTSIDE the patch,
        # so later tests see the deployed CHAT_TIMEOUT, not the stripped reload.
        importlib.reload(cfg)

    def test_chat_timeout_env_override(self):
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("CHAT_TIMEOUT", "90")
            from maria_core.sys import config as cfg
            importlib.reload(cfg)
            assert cfg.CHAT_HTTP_TIMEOUT == 90
            importlib.reload(cfg)  # restore module state

    def test_chat_timeout_is_shorter_than_learning_timeout(self):
        # The point of a separate knob: interactive chat must fail well before the
        # learning-sized OLLAMA_HTTP_TIMEOUT (240s) so the operator gets feedback.
        from maria_core.sys.config import CHAT_HTTP_TIMEOUT, OLLAMA_HTTP_TIMEOUT
        assert CHAT_HTTP_TIMEOUT < OLLAMA_HTTP_TIMEOUT


# ---------------------------------------------------------------------------
# Source-level lock on the UI handler (importing Flask/socketio is too heavy)
# ---------------------------------------------------------------------------
class TestUiHandlerSurfacesTimeout:
    @property
    def _app_src(self):
        app_py = Path(__file__).resolve().parents[2] / "maria_ui" / "app.py"
        return app_py.read_text(encoding="utf-8")

    def test_handler_opts_into_raise_on_timeout(self):
        assert "raise_on_timeout=True" in self._app_src

    def test_handler_catches_braintimeout(self):
        assert "except BrainTimeout" in self._app_src

    def test_handler_emits_busy_message_not_silence(self):
        # The clear user-facing message that replaces the dead chat.
        assert "ciezkim mysleniem" in self._app_src

    def test_handler_wires_chat_specific_timeout(self):
        assert "CHAT_HTTP_TIMEOUT" in self._app_src


# ---------------------------------------------------------------------------
# BrainTimeout is part of the module's public surface
# ---------------------------------------------------------------------------
def test_braintimeout_is_importable_and_is_exception():
    assert issubclass(ollama_brain.BrainTimeout, Exception)
