"""Tests for model warm-up (agent_core/llm/warmup.py).

Cold-start exam fix (2026-06-04): on daemon start, warm the exam models
(student=llama3.1, grader=qwen3) with one small real generation each so the
first exam doesn't pay the cold-start inference penalty. See module docstring.
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

from agent_core.llm import warmup
from agent_core.llm.warmup import (
    warm_up_models,
    start_background_warmup,
    DEFAULT_WARMUP_MODELS,
)


def _ok_client():
    """A mock ollama client whose generate() returns a load-like response."""
    client = MagicMock()
    client.generate.return_value = {"response": "OK", "done": True, "eval_count": 2}
    return client


# ---------------------------------------------------------------------------
# warm_up_models
# ---------------------------------------------------------------------------
class TestWarmUpModels:
    def test_calls_generate_for_each_model_with_keep_alive(self):
        client = _ok_client()
        with patch.object(warmup, "get_ollama_client", return_value=client):
            results = warm_up_models(
                model_tags=["a:1", "b:2"], keep_alive="30m", num_predict=16
            )

        assert client.generate.call_count == 2
        called_models = {c.kwargs["model"] for c in client.generate.call_args_list}
        assert called_models == {"a:1", "b:2"}
        for c in client.generate.call_args_list:
            assert c.kwargs["keep_alive"] == "30m"
            assert c.kwargs["options"]["num_predict"] == 16
            assert c.kwargs["stream"] is False
        assert all(r["ok"] for r in results.values())
        assert set(results) == {"a:1", "b:2"}

    def test_default_models_are_student_and_grader(self):
        client = _ok_client()
        with patch.object(warmup, "get_ollama_client", return_value=client):
            results = warm_up_models()
        assert set(results) == set(DEFAULT_WARMUP_MODELS)
        assert "llama3.1:8b" in results
        assert "qwen3:8b" in results

    def test_one_model_failure_does_not_abort_the_others(self):
        client = MagicMock()
        # First model raises, second succeeds.
        client.generate.side_effect = [
            RuntimeError("cold load timeout"),
            {"response": "OK", "done": True},
        ]
        with patch.object(warmup, "get_ollama_client", return_value=client):
            results = warm_up_models(model_tags=["bad:1", "good:2"])

        assert client.generate.call_count == 2  # second still attempted
        assert results["bad:1"]["ok"] is False
        assert "cold load timeout" in results["bad:1"]["error"]
        assert results["good:2"]["ok"] is True

    def test_no_ollama_client_is_graceful(self):
        with patch.object(warmup, "get_ollama_client", return_value=None):
            results = warm_up_models(model_tags=["a:1"])
        assert results["a:1"]["ok"] is False
        assert "no ollama client" in results["a:1"]["error"]

    def test_records_latency(self):
        client = _ok_client()
        with patch.object(warmup, "get_ollama_client", return_value=client):
            results = warm_up_models(model_tags=["a:1"])
        assert results["a:1"]["latency_s"] >= 0.0


# ---------------------------------------------------------------------------
# start_background_warmup
# ---------------------------------------------------------------------------
class TestStartBackgroundWarmup:
    def test_disabled_via_env_returns_none(self, monkeypatch):
        monkeypatch.setenv("MARIA_WARMUP", "0")
        client = _ok_client()
        with patch.object(warmup, "get_ollama_client", return_value=client):
            t = start_background_warmup(delay_sec=0)
        assert t is None
        client.generate.assert_not_called()

    def test_runs_warmup_in_background_thread(self, monkeypatch):
        monkeypatch.setenv("MARIA_WARMUP", "1")
        client = _ok_client()
        with patch.object(warmup, "get_ollama_client", return_value=client):
            t = start_background_warmup(model_tags=["a:1", "b:2"], delay_sec=0)
            assert isinstance(t, threading.Thread)
            t.join(timeout=5)
        assert not t.is_alive()
        assert client.generate.call_count == 2

    def test_env_overrides_model_list(self, monkeypatch):
        monkeypatch.setenv("MARIA_WARMUP", "1")
        monkeypatch.setenv("MARIA_WARMUP_MODELS", "x:9, y:9")
        client = _ok_client()
        with patch.object(warmup, "get_ollama_client", return_value=client):
            t = start_background_warmup(delay_sec=0)
            t.join(timeout=5)
        called_models = {c.kwargs["model"] for c in client.generate.call_args_list}
        assert called_models == {"x:9", "y:9"}

    def test_env_overrides_delay(self, monkeypatch):
        monkeypatch.setenv("MARIA_WARMUP", "1")
        monkeypatch.setenv("MARIA_WARMUP_DELAY", "0")
        client = _ok_client()
        with patch.object(warmup, "get_ollama_client", return_value=client):
            t = start_background_warmup(model_tags=["a:1"])
            t.join(timeout=5)
        assert client.generate.call_count == 1
