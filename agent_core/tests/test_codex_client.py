"""
Tests for Codex CLI Client (ChatGPT encyclopedia).

All subprocess calls mocked - zero external dependencies.
"""

import json
import time
from unittest.mock import patch, MagicMock

from agent_core.llm.codex_client import (
    CodexClient, MAX_CALLS_PER_HOUR, RATE_WINDOW_SEC,
)
from agent_core.tests.spec_helpers import specced


class TestCodexClientAvailability:
    """Tests for CLI availability detection."""

    @patch("agent_core.llm.codex_client.shutil.which")
    def test_default_binary_uses_path_at_runtime(self, mock_which):
        mock_which.return_value = "/opt/bin/codex"
        client = CodexClient()
        assert client._codex_bin == "/opt/bin/codex"

    @patch("agent_core.llm.codex_client.shutil.which")
    def test_available_when_installed(self, mock_which):
        mock_which.return_value = "/usr/local/bin/codex"
        client = CodexClient()
        assert client.is_available() is True

    @patch("agent_core.llm.codex_client.shutil.which")
    def test_not_available_when_missing(self, mock_which):
        mock_which.return_value = None
        client = CodexClient()
        assert client.is_available() is False


class TestCodexClientAsk:
    """Tests for ask() method."""

    @patch("agent_core.llm.codex_client.shutil.which", return_value="/usr/local/bin/codex")
    @patch("agent_core.llm.codex_client.subprocess.run")
    def test_ask_success(self, mock_run, mock_which, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Fotosynteza to proces biologiczny...",
            stderr="",
        )
        client = CodexClient(log_path=tmp_path / "log.jsonl")
        result = client.ask("Co to jest fotosynteza?", source="test")
        assert result == "Fotosynteza to proces biologiczny..."
        assert client._total_calls == 1
        assert client._total_errors == 0

    @patch("agent_core.llm.codex_client.shutil.which", return_value="/usr/local/bin/codex")
    @patch("agent_core.llm.codex_client.subprocess.run")
    def test_ask_failure(self, mock_run, mock_which, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error: not authenticated",
        )
        client = CodexClient(log_path=tmp_path / "log.jsonl")
        result = client.ask("test")
        assert result is None
        assert client._total_errors == 1

    @patch("agent_core.llm.codex_client.shutil.which", return_value="/usr/local/bin/codex")
    @patch("agent_core.llm.codex_client.subprocess.run")
    def test_ask_timeout(self, mock_run, mock_which, tmp_path):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("codex", 120)
        client = CodexClient(log_path=tmp_path / "log.jsonl")
        result = client.ask("test")
        assert result is None
        assert client._total_errors == 1

    @patch("agent_core.llm.codex_client.shutil.which", return_value=None)
    def test_ask_not_available(self, mock_which, tmp_path):
        client = CodexClient(log_path=tmp_path / "log.jsonl")
        result = client.ask("test")
        assert result is None


class TestCodexCliFlags:
    """Guard Codex exec flags used by Maria automation."""

    def _captured_run(self, tmp_path, *, impl_mode=False, **client_kwargs):
        client = CodexClient(
            codex_bin="/usr/local/bin/codex",
            log_path=tmp_path / "log.jsonl",
            **client_kwargs,
        )
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            result = MagicMock()
            result.returncode = 0
            result.stdout = "ok"
            result.stderr = ""
            return result

        cwd = tmp_path / "repo"
        cwd.mkdir()
        with patch("agent_core.llm.codex_client.subprocess.run", fake_run):
            assert client._invoke("test prompt", cwd=cwd, impl_mode=impl_mode) == "ok"
        return captured

    def test_read_mode_is_noninteractive_and_read_only(self, tmp_path):
        captured = self._captured_run(tmp_path)
        cmd = captured["cmd"]
        assert cmd[:2] == ["/usr/local/bin/codex", "exec"]
        assert "--color" in cmd
        assert cmd[cmd.index("--color") + 1] == "never"
        assert "--sandbox" in cmd
        assert cmd[cmd.index("--sandbox") + 1] == "read-only"
        assert 'approval_policy="never"' in cmd
        assert cmd[-1] == "-"
        assert captured["kwargs"]["input"].endswith("test prompt")

    def test_impl_mode_is_noninteractive_and_workspace_writable(self, tmp_path):
        captured = self._captured_run(tmp_path, impl_mode=True)
        cmd = captured["cmd"]
        assert "--sandbox" in cmd
        assert cmd[cmd.index("--sandbox") + 1] == "workspace-write"
        assert 'approval_policy="never"' in cmd
        assert "--cd" in cmd
        assert cmd[cmd.index("--cd") + 1] == str(tmp_path / "repo")

    def test_impl_sandbox_is_configurable(self, tmp_path):
        captured = self._captured_run(
            tmp_path,
            impl_mode=True,
            impl_sandbox="danger-full-access",
        )
        cmd = captured["cmd"]
        assert cmd[cmd.index("--sandbox") + 1] == "danger-full-access"

    def test_empty_query_sandbox_fails_closed_to_read_only(self, tmp_path):
        # Fail closed: an empty flag value must NOT omit --sandbox (that would
        # fall through to codex's writable trusted-dir default in Maria's repo).
        captured = self._captured_run(tmp_path, query_sandbox="")
        cmd = captured["cmd"]
        assert "--sandbox" in cmd
        assert cmd[cmd.index("--sandbox") + 1] == "read-only"

    def test_empty_impl_sandbox_fails_closed_to_workspace_write(self, tmp_path):
        captured = self._captured_run(
            tmp_path, impl_mode=True, impl_sandbox=""
        )
        cmd = captured["cmd"]
        assert "--sandbox" in cmd
        assert cmd[cmd.index("--sandbox") + 1] == "workspace-write"


class TestCodexClientRateLimit:
    """Tests for rate limiting."""

    @patch("agent_core.llm.codex_client.shutil.which", return_value="/usr/local/bin/codex")
    @patch("agent_core.llm.codex_client.subprocess.run")
    def test_rate_limit_blocks_after_max(self, mock_run, mock_which, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        client = CodexClient(log_path=tmp_path / "log.jsonl")

        # Fill up rate limit
        for _ in range(MAX_CALLS_PER_HOUR):
            client.ask("test", source="test")

        # Next call should be blocked
        result = client.ask("test", source="test")
        assert result is None
        assert mock_run.call_count == MAX_CALLS_PER_HOUR

    @patch("agent_core.llm.codex_client.shutil.which", return_value="/usr/local/bin/codex")
    @patch("agent_core.llm.codex_client.subprocess.run")
    def test_rate_limit_window_expiry(self, mock_run, mock_which, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        client = CodexClient(log_path=tmp_path / "log.jsonl")

        # Fill up rate limit with old timestamps
        old_time = time.time() - RATE_WINDOW_SEC - 10
        for _ in range(MAX_CALLS_PER_HOUR):
            client._call_timestamps.append(old_time)

        # Should be allowed (old calls expired)
        result = client.ask("test", source="test")
        assert result == "ok"

    def test_rate_limit_constant(self):
        assert MAX_CALLS_PER_HOUR == 10
        assert RATE_WINDOW_SEC == 3600


class TestCodexClientLogging:
    """Tests for JSONL interaction logging."""

    @patch("agent_core.llm.codex_client.shutil.which", return_value="/usr/local/bin/codex")
    @patch("agent_core.llm.codex_client.subprocess.run")
    def test_success_logged(self, mock_run, mock_which, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="Answer", stderr="")
        log_path = tmp_path / "log.jsonl"
        client = CodexClient(log_path=log_path)
        client.ask("Question?", source="creative", context={"topic": "AI"})

        assert log_path.exists()
        lines = log_path.read_text().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["success"] is True
        assert record["source"] == "creative"
        assert record["prompt_summary"] == "Question?"
        assert record["response_summary"] == "Answer"
        assert "context" in record
        assert record["context"]["topic"] == "AI"

    @patch("agent_core.llm.codex_client.shutil.which", return_value="/usr/local/bin/codex")
    @patch("agent_core.llm.codex_client.subprocess.run")
    def test_failure_logged(self, mock_run, mock_which, tmp_path):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="err")
        log_path = tmp_path / "log.jsonl"
        client = CodexClient(log_path=log_path)
        client.ask("test")

        lines = log_path.read_text().splitlines()
        record = json.loads(lines[0])
        assert record["success"] is False
        assert record["error"] == "invoke_failed"

    @patch("agent_core.llm.codex_client.shutil.which", return_value="/usr/local/bin/codex")
    @patch("agent_core.llm.codex_client.subprocess.run")
    def test_rate_limited_logged(self, mock_run, mock_which, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        log_path = tmp_path / "log.jsonl"
        client = CodexClient(log_path=log_path)

        # Fill rate limit
        for _ in range(MAX_CALLS_PER_HOUR):
            client.ask("test")

        # This should log a rate_limited entry
        client.ask("blocked")
        lines = log_path.read_text().splitlines()
        last = json.loads(lines[-1])
        assert last["error"] == "rate_limited"
        assert last["success"] is False

    @patch("agent_core.llm.codex_client.shutil.which", return_value="/usr/local/bin/codex")
    @patch("agent_core.llm.codex_client.subprocess.run")
    def test_prompt_truncated_in_log(self, mock_run, mock_which, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        log_path = tmp_path / "log.jsonl"
        client = CodexClient(log_path=log_path)
        long_prompt = "x" * 1000
        client.ask(long_prompt)

        record = json.loads(log_path.read_text().splitlines()[0])
        assert len(record["prompt_summary"]) == 200
        assert record["prompt_length"] == 1000


class TestCodexClientStats:
    """Tests for get_stats() and get_recent_interactions()."""

    @patch("agent_core.llm.codex_client.shutil.which", return_value=None)
    def test_stats_not_available(self, mock_which):
        client = CodexClient()
        stats = client.get_stats()
        assert stats["available"] is False
        assert stats["total_calls"] == 0
        assert stats["remaining"] == MAX_CALLS_PER_HOUR

    @patch("agent_core.llm.codex_client.shutil.which", return_value="/usr/local/bin/codex")
    @patch("agent_core.llm.codex_client.subprocess.run")
    def test_stats_after_calls(self, mock_run, mock_which, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        client = CodexClient(log_path=tmp_path / "log.jsonl")
        client.ask("q1")
        client.ask("q2")

        stats = client.get_stats()
        assert stats["total_calls"] == 2
        assert stats["calls_this_hour"] == 2
        assert stats["remaining"] == MAX_CALLS_PER_HOUR - 2

    @patch("agent_core.llm.codex_client.shutil.which", return_value="/usr/local/bin/codex")
    @patch("agent_core.llm.codex_client.subprocess.run")
    def test_get_recent_interactions(self, mock_run, mock_which, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="answer", stderr="")
        log_path = tmp_path / "log.jsonl"
        client = CodexClient(log_path=log_path)
        client.ask("q1", source="test")
        client.ask("q2", source="test")

        recent = client.get_recent_interactions(limit=5)
        assert len(recent) == 2
        assert recent[0]["prompt_summary"] == "q1"
        assert recent[1]["prompt_summary"] == "q2"

    def test_get_recent_no_file(self, tmp_path):
        client = CodexClient(log_path=tmp_path / "nonexistent.jsonl")
        assert client.get_recent_interactions() == []


class TestModelRegistryEncyclopedia:
    """Verify ModelRole.ENCYCLOPEDIA exists in registry."""

    def test_encyclopedia_role_exists(self):
        from agent_core.llm.model_registry import ModelRole, _REGISTRY
        assert hasattr(ModelRole, "ENCYCLOPEDIA")
        assert ModelRole.ENCYCLOPEDIA in _REGISTRY

    def test_encyclopedia_spec(self):
        from agent_core.llm.model_registry import ModelRole, _REGISTRY, ConcurrencyClass, WarmState
        spec = _REGISTRY[ModelRole.ENCYCLOPEDIA]
        assert spec.model_id == "codex-chatgpt"
        assert spec.ram_estimate_gb == 0.0
        assert spec.concurrency_class == ConcurrencyClass.NONE
        assert spec.warm_state == WarmState.EXTERNAL
        assert spec.fallback_role == ModelRole.EXTERNAL


class TestRouterEncyclopedia:
    """Tests for LLMRouter.ask_encyclopedia()."""

    def _make_router(self, codex_available=True, codex_result="ChatGPT answer"):
        ollama = MagicMock()
        ollama.model = "llama3.1:8b"
        ollama._ask_once = MagicMock(return_value="Ollama fallback")

        router_module = __import__("agent_core.llm.router", fromlist=["LLMRouter"])
        router = router_module.LLMRouter(ollama_brain=ollama)

        codex = specced(CodexClient)
        codex.is_available.return_value = codex_available
        codex.ask.return_value = codex_result if codex_available else None
        codex.get_stats.return_value = {"available": codex_available}
        router.set_codex_client(codex)

        return router, codex, ollama

    def test_ask_encyclopedia_uses_codex(self):
        router, codex, ollama = self._make_router()
        result = router.ask_encyclopedia("What is DNA?", source="test")
        assert result == "ChatGPT answer"
        codex.ask.assert_called_once()
        ollama._ask_once.assert_not_called()

    def test_ask_encyclopedia_fallback_to_ollama(self):
        router, codex, ollama = self._make_router(codex_result=None)
        result = router.ask_encyclopedia("What is DNA?")
        assert result == "Ollama fallback"
        ollama._ask_once.assert_called_once()

    def test_ask_encyclopedia_no_codex(self):
        ollama = MagicMock()
        ollama.model = "llama3.1:8b"
        ollama._ask_once = MagicMock(return_value="Ollama answer")

        router_module = __import__("agent_core.llm.router", fromlist=["LLMRouter"])
        router = router_module.LLMRouter(ollama_brain=ollama)

        result = router.ask_encyclopedia("test")
        assert result == "Ollama answer"

    def test_stats_include_codex(self):
        router, codex, _ = self._make_router()
        router.ask_encyclopedia("test")
        stats = router.get_stats()
        assert "codex" in stats
        assert stats["codex_calls"] == 1


class TestSharedContextCodex:
    """Verify SharedContext has codex_client field."""

    def test_shared_context_has_codex_field(self):
        from agent_core.registry.shared_context import SharedContext
        ctx = SharedContext()
        assert hasattr(ctx, "codex_client")
        assert ctx.codex_client is None
