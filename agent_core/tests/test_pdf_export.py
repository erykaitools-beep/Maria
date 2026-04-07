"""
Tests for PDF export and Telegram send_document.

Covers: PDF generation, Polish chars, code blocks, send_document API.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_core.telegram.pdf_export import generate_task_pdf


class TestPDFGeneration:
    """PDF generation from task results."""

    def test_generates_pdf_file(self):
        path = generate_task_pdf(
            task_id="abc123def456",
            backend="claude",
            task_text="analyze planner",
            result="The planner is well structured.",
        )
        assert path is not None
        assert os.path.exists(path)
        assert path.endswith(".pdf")
        assert os.path.getsize(path) > 100

    def test_filename_contains_backend_and_id(self):
        path = generate_task_pdf(
            task_id="test12345678",
            backend="codex",
            task_text="test",
            result="result",
        )
        assert "codex" in path
        assert "test12345678" in path

    def test_polish_characters(self):
        path = generate_task_pdf(
            task_id="pol123456789",
            backend="claude",
            task_text="Przeanalizuj modul zrodlowy",
            result="Znaleziono problemy ze srodowiskiem. Zolw jest szybki.",
        )
        assert path is not None
        assert os.path.getsize(path) > 100

    def test_code_blocks_in_result(self):
        result = (
            "Here is the analysis:\n\n"
            "```python\n"
            "def hello():\n"
            "    print('world')\n"
            "```\n\n"
            "The function works correctly."
        )
        path = generate_task_pdf(
            task_id="code12345678",
            backend="codex",
            task_text="review code",
            result=result,
        )
        assert path is not None
        assert os.path.getsize(path) > 100

    def test_long_result(self):
        """PDF handles very long results without crashing."""
        result = "Line of text.\n" * 500
        path = generate_task_pdf(
            task_id="long12345678",
            backend="claude",
            task_text="big analysis",
            result=result,
        )
        assert path is not None
        assert os.path.getsize(path) > 1000

    def test_headers_and_bullets(self):
        result = (
            "# Summary\n\n"
            "**Key findings:**\n"
            "- First item\n"
            "- Second item\n"
            "* Third item\n\n"
            "## Details\n"
            "Some details here."
        )
        path = generate_task_pdf(
            task_id="head12345678",
            backend="codex",
            task_text="structured output",
            result=result,
        )
        assert path is not None

    def test_with_duration_and_timestamp(self):
        path = generate_task_pdf(
            task_id="meta12345678",
            backend="claude",
            task_text="timed task",
            result="Done in record time.",
            duration_ms=15432.0,
            timestamp=1712345678.0,
        )
        assert path is not None

    def test_empty_result(self):
        path = generate_task_pdf(
            task_id="empt12345678",
            backend="codex",
            task_text="empty",
            result="",
        )
        assert path is not None


class TestTelegramSendDocument:
    """TelegramBot.send_document() method."""

    def test_send_document_calls_api(self):
        from agent_core.telegram.bot import TelegramBot

        bot = TelegramBot(token="test_token", chat_id=12345)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}

        # Create a temp file to send
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"fake pdf content")
            tmp_path = f.name

        try:
            with patch("requests.post", return_value=mock_resp) as mock_post:
                result = bot.send_document(tmp_path, caption="Test doc")
                assert result is True
                mock_post.assert_called_once()
                call_args = mock_post.call_args
                assert "sendDocument" in call_args[0][0]
                assert call_args[1]["data"]["chat_id"] == 12345
                assert call_args[1]["data"]["caption"] == "Test doc"
        finally:
            os.unlink(tmp_path)

    def test_send_document_not_configured(self):
        from agent_core.telegram.bot import TelegramBot
        bot = TelegramBot(token="", chat_id=0)
        result = bot.send_document("/tmp/fake.pdf")
        assert result is False

    def test_send_document_file_not_found(self):
        from agent_core.telegram.bot import TelegramBot
        bot = TelegramBot(token="test", chat_id=123)
        result = bot.send_document("/nonexistent/path.pdf")
        assert result is False

    def test_send_document_truncates_caption(self):
        from agent_core.telegram.bot import TelegramBot
        bot = TelegramBot(token="test", chat_id=123)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"content")
            tmp_path = f.name

        try:
            with patch("requests.post", return_value=mock_resp) as mock_post:
                long_caption = "x" * 2000
                bot.send_document(tmp_path, caption=long_caption)
                call_args = mock_post.call_args
                assert len(call_args[1]["data"]["caption"]) <= 1024
        finally:
            os.unlink(tmp_path)


class TestStartupCooldown:
    """Verify startup cooldown value."""

    def test_cooldown_is_6h(self):
        from agent_core.telegram.notifier import _STARTUP_COOLDOWN_SEC
        assert _STARTUP_COOLDOWN_SEC == 21600
