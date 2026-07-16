"""Tests for the 2026-06-02 freeze root-cause fix: HTTP-timeout in OllamaBrain.

The 2026-06-02 tick-loop freeze (10.5h) was first hardened at the router layer
(cf7283f: bounded fallbacks + watchdog). But the actual primitive that hangs --
models/ollama_brain.py:_chat() -> ollama.chat() -- still used the module-level
ollama client, which carries NO socket timeout. A stalled inference there hangs
forever:
  * call_with_timeout() unblocks the *caller* after the role deadline, but it
    cannot cancel the in-flight HTTP request (its own docstring admits this).
  * The orphaned request keeps running, holding one of the 2 worker slots in the
    execution-budget pool. Enough zombies starve the pool and re-freeze the loop.
  * Legacy chat paths (main.py REPL, conversation_memory) call _chat with NO
    call_with_timeout wrapper at all, so they had no timeout whatsoever.

Fix: route every ollama.chat()/ollama.list() through a timeout-aware
ollama.Client(timeout=OLLAMA_HTTP_TIMEOUT). A real httpx read-timeout tears the
socket down, so the call raises instead of hanging -- the zombie dies and frees
its pool slot. The timeout is sized above the per-role execution budgets
(graceful degrade fires first) and below the 300s watchdog (degrade before a
hard restart).
"""

import os
import time
import inspect
from unittest.mock import MagicMock, patch

import pytest

import ollama
from models import ollama_brain
from maria_core.sys.config import OLLAMA_HTTP_TIMEOUT, OLLAMA_KEEP_ALIVE
from agent_core.llm.execution_budget import (
    get_timeout_for_role,
    get_ollama_client,
    DEFAULT_TIMEOUTS,
)
from agent_core.llm import router as router_mod
from agent_core.llm import model_scheduler as scheduler_mod
from agent_core.llm.model_scheduler import ModelScheduler, EnsureResult
from agent_core.llm.nim_client import NIMClient
from agent_core.tests.spec_helpers import specced


def _make_brain():
    """OllamaBrain without touching the network (verify_model defaults off)."""
    return ollama_brain.OllamaBrain(model="llama3.1:8b", log_fn=lambda *_: None)


# ---------------------------------------------------------------------------
# The brain builds a timeout-aware client (not the bare module API)
# ---------------------------------------------------------------------------
class TestClientHasTimeout:
    def test_client_is_ollama_client_instance(self):
        brain = _make_brain()
        assert isinstance(brain._client, ollama.Client), (
            "brain must use a dedicated ollama.Client, not the module-level API"
        )

    def test_client_carries_the_configured_http_timeout(self):
        brain = _make_brain()
        # ollama.Client wraps an httpx.Client whose .timeout reflects our value.
        httpx_timeout = brain._client._client.timeout
        # httpx Timeout exposes per-phase values; read defeats the namedtuple-ish API.
        assert httpx_timeout.read == float(OLLAMA_HTTP_TIMEOUT)
        assert httpx_timeout.connect == float(OLLAMA_HTTP_TIMEOUT)

    def test_falls_back_to_module_api_on_old_lib(self):
        # An older ollama lib without Client(timeout=...) must not crash __init__.
        with patch.object(ollama, "Client", side_effect=TypeError("no timeout kwarg")):
            brain = _make_brain()
        assert brain._client is ollama, "fallback should be the module-level API"


# ---------------------------------------------------------------------------
# Every inference goes through the timeout-aware client
# ---------------------------------------------------------------------------
class TestChatUsesClient:
    def test_chat_calls_client_not_module(self):
        brain = _make_brain()
        brain._client = MagicMock()
        brain._client.chat.return_value = {"message": {"content": "  hi  "}}

        with patch.object(ollama, "chat", side_effect=AssertionError("module chat() must not be used")):
            out = brain._chat([{"role": "user", "content": "q"}])

        assert out == "hi"
        brain._client.chat.assert_called_once()

    def test_verify_model_uses_client_not_module(self):
        brain = _make_brain()
        brain._client = MagicMock()
        brain._client.list.return_value = {"models": [{"model": "llama3.1:8b"}]}

        with patch.object(ollama, "list", side_effect=AssertionError("module list() must not be used")):
            brain._verify_model_exists()

        brain._client.list.assert_called_once()


# ---------------------------------------------------------------------------
# A stall now raises fast instead of hanging forever
# ---------------------------------------------------------------------------
class TestTimeoutPropagates:
    def test_chat_propagates_timeout_without_hanging(self):
        import httpx

        brain = _make_brain()
        brain._client = MagicMock()
        brain._client.chat.side_effect = httpx.ReadTimeout("simulated stall")

        start = time.time()
        with pytest.raises(httpx.TimeoutException):
            brain._chat([{"role": "user", "content": "q"}])
        # The point of the fix: it returns control immediately, it does not block.
        assert time.time() - start < 1.0

    def test_think_swallows_timeout_and_degrades(self):
        # think() already wraps _chat in try/except -> a timeout must degrade to ""
        # (not propagate up the legacy chat path).
        import httpx

        brain = _make_brain()
        brain._client = MagicMock()
        brain._client.chat.side_effect = httpx.ReadTimeout("simulated stall")
        # Disable the grounded pipeline so we hit the plain chat path.
        brain._query_router = None
        brain._evidence_collector = None
        brain._response_builder = None

        out = brain.think("czesc")
        assert out == ""


# ---------------------------------------------------------------------------
# The timeout value is sized to cooperate with the other safety layers
# ---------------------------------------------------------------------------
class TestTimeoutSizing:
    def test_default_is_240(self):
        # When unset, mirrors the legacy learning path's requests timeout.
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OLLAMA_HTTP_TIMEOUT", None)
            import importlib
            from maria_core.sys import config as cfg
            importlib.reload(cfg)
            assert cfg.OLLAMA_HTTP_TIMEOUT == 240
            # restore for any later reloader
            importlib.reload(cfg)

    def test_above_execution_budgets_so_graceful_degrade_fires_first(self):
        # If the HTTP timeout fired before call_with_timeout, the router could not
        # degrade gracefully -- the socket would die mid-call. It must be larger.
        assert OLLAMA_HTTP_TIMEOUT >= get_timeout_for_role("executor")
        assert OLLAMA_HTTP_TIMEOUT >= get_timeout_for_role("planner")

    def test_below_watchdog_so_degrade_beats_hard_restart(self):
        watchdog = float(os.environ.get("WATCHDOG_STALL_SEC", "300"))
        assert OLLAMA_HTTP_TIMEOUT < watchdog

    def test_env_override(self):
        import importlib
        from maria_core.sys import config as cfg
        with patch.dict(os.environ, {"OLLAMA_HTTP_TIMEOUT": "90"}):
            importlib.reload(cfg)
            assert cfg.OLLAMA_HTTP_TIMEOUT == 90
        # Restore module state OUTSIDE the patch so cfg.OLLAMA_HTTP_TIMEOUT returns
        # to its real value (240). Reloading while the env is still patched leaves
        # cfg polluted at 90 and breaks every later test that reads the timeout
        # (e.g. test_http_timeout_defaults_to_shared_when_none).
        importlib.reload(cfg)


# ---------------------------------------------------------------------------
# Source-level guard: no bare module-level ollama.chat/list left behind
# ---------------------------------------------------------------------------
def _bare_ollama_calls(module, var_name):
    """AST scan: live calls of var_name.{chat,generate,list,ps,embeddings}.

    AST-based so string literals (e.g. a log message mentioning "ollama.list()")
    are not mistaken for live calls. `var_name` is the local binding for the bare
    module: "ollama" in ollama_brain, "ollama_lib" in router/model_scheduler.
    """
    import ast

    forbidden = ("chat", "generate", "list", "ps", "embeddings")
    tree = ast.parse(inspect.getsource(module))
    offenders = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == var_name
            and node.func.attr in forbidden
        ):
            offenders.append(f"{var_name}.{node.func.attr}() @ line {node.lineno}")
    return offenders


class TestNoBareModuleCalls:
    """Regression guard: every daemon-path ollama inference must route through a
    timeout-aware client, never the bare module (the 2026-06-02 freeze primitive).
    Covers all three subsystems the fix touched -- if anyone reintroduces a bare
    ollama_lib.chat/generate/ps, this goes red."""

    def test_ollama_brain_has_no_bare_module_calls(self):
        assert _bare_ollama_calls(ollama_brain, "ollama") == []

    def test_router_has_no_bare_module_calls(self):
        # router.py:469 used to call the bare ollama_lib.chat() -> the HIGH finding.
        assert _bare_ollama_calls(router_mod, "ollama_lib") == []

    def test_model_scheduler_has_no_bare_module_calls(self):
        # load/unload/ps on the tick thread used bare ollama_lib.generate()/ps().
        assert _bare_ollama_calls(scheduler_mod, "ollama_lib") == []


# ---------------------------------------------------------------------------
# The shared timeout-aware client (SSoT for router + scheduler)
# ---------------------------------------------------------------------------
class TestSharedClientHelper:
    def test_returns_timeout_aware_client(self):
        c = get_ollama_client()
        assert isinstance(c, ollama.Client)
        assert c._client.timeout.read == float(OLLAMA_HTTP_TIMEOUT)

    def test_is_a_singleton(self):
        assert get_ollama_client() is get_ollama_client()


# ---------------------------------------------------------------------------
# Router: the primary live path (scheduler-success) no longer hangs
# ---------------------------------------------------------------------------
class TestRouterUsesSharedClient:
    def _router(self):
        # ollama_brain/nim_client are our own classes -> specced, so a phantom
        # method or a wrong signature on the fallback path goes red.
        r = router_mod.LLMRouter(
            specced(ollama_brain.OllamaBrain), specced(NIMClient)
        )
        r.ollama.model = "llama3.1:8b"
        return r

    def test_scheduler_path_degrades_on_http_timeout_without_hanging(self):
        import httpx

        r = self._router()
        # Force the scheduler-success branch (not NIM, not no-scheduler).
        r._is_nim_primary_role = lambda role: False
        scheduler = specced(ModelScheduler)
        scheduler.ensure_ready.return_value = EnsureResult(success=True, ollama_tag="llama3.1:8b")
        r.set_model_scheduler(scheduler)

        # The shared client wedges: chat raises a real HTTP read-timeout.
        stub_client = MagicMock()
        stub_client.chat.side_effect = httpx.ReadTimeout("wedged ollama")
        # Fallback path (_bounded_ask_once -> self.ollama._ask_once) degrades cleanly.
        r.ollama._ask_once.return_value = "degraded"

        start = time.time()
        with patch.object(router_mod, "get_ollama_client", return_value=stub_client):
            out = r.ask_as_role("executor", "ping")
        # It must NOT hang and must NOT propagate httpx -- it degrades to the fallback.
        assert time.time() - start < 2.0
        assert out == "degraded"
        stub_client.chat.assert_called_once()


# ---------------------------------------------------------------------------
# Exception contract: httpx.TimeoutException is caught by the freeze guards
# ---------------------------------------------------------------------------
class TestExceptionContract:
    def test_bounded_ask_once_catches_httpx_timeout(self):
        # httpx.TimeoutException is a sibling, not a subclass, of builtin
        # TimeoutError -- if the guard only caught TimeoutError it would escape.
        import httpx

        r = router_mod.LLMRouter(
            specced(ollama_brain.OllamaBrain), specced(NIMClient)
        )
        r.ollama.model = "llama3.1:8b"
        r.ollama._ask_once.side_effect = httpx.ReadTimeout("inner http timeout")

        # Goes through real call_with_timeout, which re-raises non-Futures errors;
        # the widened `except _OLLAMA_TIMEOUT_EXC` must catch it and degrade to "".
        out = r._bounded_ask_once("ping", 0.3, "executor")
        assert out == ""

    def test_timeout_exc_tuple_includes_httpx(self):
        import httpx

        assert httpx.TimeoutException in router_mod._OLLAMA_TIMEOUT_EXC
        # Guard against a regression to the builtin-only contract.
        assert not issubclass(httpx.TimeoutException, TimeoutError)


# ---------------------------------------------------------------------------
# ModelScheduler load/unload/ps go through the timeout-aware client
# ---------------------------------------------------------------------------
class TestSchedulerUsesSharedClient:
    def _sched(self):
        # Bypass the heavy __init__; the ollama helpers don't touch instance state.
        return scheduler_mod.ModelScheduler.__new__(scheduler_mod.ModelScheduler)

    def test_load_uses_shared_client(self):
        s = self._sched()
        client = MagicMock()
        with patch.object(scheduler_mod, "get_ollama_client", return_value=client):
            ok = s._ollama_load("llama3.1:8b")
        assert ok is True
        client.generate.assert_called_once()

    def test_unload_uses_shared_client(self):
        s = self._sched()
        client = MagicMock()
        with patch.object(scheduler_mod, "get_ollama_client", return_value=client):
            ok = s._ollama_unload("llama3.1:8b")
        assert ok is True
        client.generate.assert_called_once()

    def test_list_running_uses_shared_client(self):
        s = self._sched()
        client = MagicMock()
        client.ps.return_value = {"models": [{"name": "llama3.1:8b"}]}
        with patch.object(scheduler_mod, "get_ollama_client", return_value=client):
            running = s._ollama_list_running()
        assert running == ["llama3.1:8b"]
        client.ps.assert_called_once()

    def test_load_returns_false_when_lib_absent(self):
        s = self._sched()
        with patch.object(scheduler_mod, "get_ollama_client", return_value=None):
            assert s._ollama_load("x") is False


# ---------------------------------------------------------------------------
# The sizing invariant that keeps finding #2 latent
# ---------------------------------------------------------------------------
class TestTimeoutInvariant:
    def test_http_timeout_exceeds_every_role_budget(self):
        # If any role budget were >= the HTTP timeout, call_with_timeout could
        # NOT fire first, and a raw httpx.ReadTimeout could surface where callers
        # expect a TimeoutError. Keep the HTTP timeout strictly the largest.
        worst = max(DEFAULT_TIMEOUTS.values())
        assert OLLAMA_HTTP_TIMEOUT > worst, (
            f"OLLAMA_HTTP_TIMEOUT ({OLLAMA_HTTP_TIMEOUT}) must exceed the largest "
            f"role budget ({worst}) so graceful degrade always fires first"
        )


# ---------------------------------------------------------------------------
# keep_alive pins the brain model warm (finding #4)
# ---------------------------------------------------------------------------
class TestBrainKeepAlive:
    def test_chat_passes_keep_alive(self):
        brain = _make_brain()
        brain._client = MagicMock()
        brain._client.chat.return_value = {"message": {"content": "x"}}
        brain._chat([{"role": "user", "content": "q"}])
        _, kwargs = brain._client.chat.call_args
        assert kwargs.get("keep_alive") == OLLAMA_KEEP_ALIVE
