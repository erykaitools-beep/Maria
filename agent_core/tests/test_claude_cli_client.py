"""Tests for ClaudeCLIClient."""

import time
from unittest.mock import MagicMock, patch

import pytest

from agent_core.self_analysis.claude_cli_client import (
    ClaudeCLIClient,
    MAX_CALLS_PER_DAY,
)


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
        mock_oc = MagicMock()
        mock_oc.invoke_tool.return_value = {"success": True}
        client.set_openclaw_client(mock_oc)
        assert client.is_available() is True
        mock_oc.invoke_tool.assert_called_once()

    @patch("shutil.which", return_value=None)
    def test_not_available_openclaw_fails(self, mock_which, client):
        mock_oc = MagicMock()
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
        mock_oc = MagicMock()
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
        mock_oc = MagicMock()
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
