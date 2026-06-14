"""Tests for ClaudeCLIClient."""

import time
from unittest.mock import MagicMock, patch

import pytest

from agent_core.self_analysis.claude_cli_client import (
    ClaudeCLIClient,
    MAX_CALLS_PER_DAY,
)
from agent_core.effector.openclaw_client import OpenClawClient
from agent_core.tests.spec_helpers import specced


@pytest.fixture
def client():
    return ClaudeCLIClient(claude_bin="claude", timeout_s=10)


# -- is_available --

class TestIsAvailable:
    @patch("shutil.which", return_value="/usr/bin/claude")
    def test_available_direct(self, mock_which, client):
        assert client.is_available() is True

    @patch("shutil.which", return_value=None)
    def test_not_available_no_binary(self, mock_which, client):
        assert client.is_available() is False

    @patch("shutil.which", return_value=None)
    def test_available_via_openclaw(self, mock_which, client):
        mock_oc = specced(OpenClawClient)
        mock_oc.invoke_tool.return_value = {"success": True}
        client.set_openclaw_client(mock_oc)
        assert client.is_available() is True
        mock_oc.invoke_tool.assert_called_once()

    @patch("shutil.which", return_value=None)
    def test_not_available_openclaw_fails(self, mock_which, client):
        mock_oc = specced(OpenClawClient)
        mock_oc.invoke_tool.return_value = {"success": False}
        client.set_openclaw_client(mock_oc)
        assert client.is_available() is False


# -- analyze direct --

class TestAnalyzeDirect:
    @patch("shutil.which", return_value="/usr/bin/claude")
    @patch("subprocess.run")
    def test_successful_analysis(self, mock_run, mock_which, client):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"recommendations": []}',
            stderr="",
        )
        result = client.analyze("test prompt")
        assert result == '{"recommendations": []}'
        mock_run.assert_called_once()

    @patch("shutil.which", return_value="/usr/bin/claude")
    @patch("subprocess.run")
    def test_empty_response(self, mock_run, mock_which, client):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr="",
        )
        result = client.analyze("test")
        assert result is None

    @patch("shutil.which", return_value="/usr/bin/claude")
    @patch("subprocess.run")
    def test_nonzero_exit(self, mock_run, mock_which, client):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Error",
        )
        result = client.analyze("test")
        assert result is None

    @patch("shutil.which", return_value="/usr/bin/claude")
    @patch("subprocess.run")
    def test_timeout(self, mock_run, mock_which, client):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("claude", 10)
        result = client.analyze("test")
        assert result is None

    @patch("shutil.which", return_value=None)
    def test_no_binary_falls_to_openclaw(self, mock_which, client):
        # No direct binary, no openclaw
        result = client.analyze("test")
        assert result is None


# -- analyze via OpenClaw --

class TestAnalyzeOpenClaw:
    @patch("shutil.which", return_value=None)
    def test_openclaw_success(self, mock_which, client):
        mock_oc = specced(OpenClawClient)
        mock_oc.invoke_tool.return_value = {
            "success": True,
            "output": '{"recommendations": ["learn more"]}',
        }
        client.set_openclaw_client(mock_oc)
        result = client.analyze("analyze this")
        assert result is not None
        assert "recommendations" in result

    @patch("shutil.which", return_value=None)
    def test_openclaw_failure(self, mock_which, client):
        mock_oc = specced(OpenClawClient)
        mock_oc.invoke_tool.return_value = {"success": False}
        client.set_openclaw_client(mock_oc)
        result = client.analyze("test")
        assert result is None


# -- Rate limiting --

class TestRateLimit:
    @patch("shutil.which", return_value="/usr/bin/claude")
    @patch("subprocess.run")
    def test_rate_limit_blocks(self, mock_run, mock_which, client):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="response", stderr="",
        )

        # Fill up rate limit
        for _ in range(MAX_CALLS_PER_DAY):
            result = client.analyze("test")
            assert result is not None

        # Next call should be blocked
        result = client.analyze("test")
        assert result is None

    def test_rate_limit_expires(self, client):
        # Add old timestamps (> 24h ago)
        old_ts = time.time() - 90000  # 25 hours ago
        client._call_timestamps = [old_ts] * MAX_CALLS_PER_DAY
        assert client._check_rate_limit() is True

    def test_rate_limit_fresh(self, client):
        assert client._check_rate_limit() is True


# -- get_stats --

class TestGetStats:
    @patch("shutil.which", return_value=None)
    def test_stats_empty(self, mock_which, client):
        stats = client.get_stats()
        assert stats["calls_24h"] == 0
        assert stats["remaining"] == MAX_CALLS_PER_DAY
        assert stats["available"] is False

    @patch("shutil.which", return_value="/usr/bin/claude")
    def test_stats_with_calls(self, mock_which, client):
        client._call_timestamps = [time.time()]
        stats = client.get_stats()
        assert stats["calls_24h"] == 1
        assert stats["remaining"] == MAX_CALLS_PER_DAY - 1
        assert stats["available"] is True


class TestUserPathFallback:
    """Regression: user-level install paths checked before OpenClaw fallback.

    Historical bug: systemd's minimal PATH omits ~/.npm-global/bin where
    Claude Code CLI lives after `npm install -g`. Every is_available()
    call then tripped the OpenClaw fallback, waking qwen2.5:3b (~3GB RAM)
    just to run `which claude`. Over 7 days: 41 wake-ups for zero
    effector actions.
    """

    def test_user_path_hit_avoids_openclaw(self):
        """If claude is in a common user path, don't touch OpenClaw."""
        from unittest.mock import patch
        client = ClaudeCLIClient()
        mock_oc = specced(OpenClawClient)
        client.set_openclaw_client(mock_oc)

        # shutil.which returns None for bare "claude", but finds it at
        # the first user path we check.
        def which_side_effect(arg):
            if arg == "claude":
                return None
            if arg.endswith("/claude"):
                return arg  # Pretend it's there and executable
            return None

        with patch("shutil.which", side_effect=which_side_effect):
            assert client.is_available() is True

        # Crucial: OpenClaw was NOT called
        mock_oc.invoke_tool.assert_not_called()
        # _claude_bin upgraded to full path
        assert client._claude_bin.endswith("/claude")

    def test_openclaw_fallback_still_works_when_user_paths_miss(self):
        """If no user path hits and OpenClaw is enabled, fallback kicks in."""
        from unittest.mock import patch
        client = ClaudeCLIClient()
        mock_oc = specced(OpenClawClient)
        mock_oc.invoke_tool.return_value = {"success": True}
        client.set_openclaw_client(mock_oc)

        with patch("shutil.which", return_value=None):
            assert client.is_available() is True

        mock_oc.invoke_tool.assert_called_once()

    def test_opt_out_env_disables_openclaw_fallback(self, monkeypatch):
        """OPENCLAW_CLAUDE_FALLBACK=0 disables the fallback entirely."""
        monkeypatch.setenv("OPENCLAW_CLAUDE_FALLBACK", "0")
        # Force reload of the module so the env var is re-read
        import importlib
        import agent_core.self_analysis.claude_cli_client as mod
        importlib.reload(mod)
        client = mod.ClaudeCLIClient()
        mock_oc = specced(OpenClawClient)
        mock_oc.invoke_tool.return_value = {"success": True}
        client.set_openclaw_client(mock_oc)

        from unittest.mock import patch
        with patch("shutil.which", return_value=None):
            assert client.is_available() is False

        mock_oc.invoke_tool.assert_not_called()
        # Reset for other tests
        monkeypatch.delenv("OPENCLAW_CLAUDE_FALLBACK", raising=False)
        importlib.reload(mod)
