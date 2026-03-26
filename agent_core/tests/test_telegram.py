"""
Tests for Telegram integration (bot, notifier, bridge).

All HTTP calls mocked - zero external dependencies.
"""

import time
import pytest
from unittest.mock import patch, MagicMock

from agent_core.telegram.bot import TelegramBot, MAX_MESSAGE_LENGTH
from agent_core.telegram.notifier import TelegramNotifier, ALERT_COOLDOWNS
from agent_core.telegram import TelegramBridge


# ─── TelegramBot ───────────────────────────────────────────


class TestTelegramBot:
    """Tests for low-level Telegram Bot API client."""

    def test_not_configured_without_token(self):
        bot = TelegramBot(token="", chat_id=0)
        assert not bot.configured

    def test_configured_with_valid_params(self):
        bot = TelegramBot(token="test-token", chat_id=12345)
        assert bot.configured

    def test_send_message_when_not_configured(self):
        bot = TelegramBot(token="", chat_id=0)
        assert bot.send_message("test") is False

    @patch("agent_core.telegram.bot.requests.post")
    def test_send_message_success(self, mock_post):
        mock_post.return_value = MagicMock(
            json=lambda: {"ok": True, "result": {"message_id": 1}}
        )
        bot = TelegramBot(token="test-token", chat_id=12345)
        assert bot.send_message("hello") is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["text"] == "hello"
        assert call_kwargs[1]["json"]["chat_id"] == 12345

    @patch("agent_core.telegram.bot.requests.post")
    def test_send_message_api_error(self, mock_post):
        mock_post.return_value = MagicMock(
            json=lambda: {"ok": False, "description": "Bad Request"}
        )
        bot = TelegramBot(token="test-token", chat_id=12345)
        assert bot.send_message("hello", parse_mode=None) is False

    @patch("agent_core.telegram.bot.requests.post")
    def test_send_message_markdown_fallback(self, mock_post):
        """If Markdown parse fails, retry without parse_mode."""
        responses = [
            MagicMock(json=lambda: {"ok": False, "description": "can't parse entities"}),
            MagicMock(json=lambda: {"ok": True, "result": {"message_id": 2}}),
        ]
        mock_post.side_effect = responses
        bot = TelegramBot(token="test-token", chat_id=12345)
        assert bot.send_message("*bad markdown") is True
        assert mock_post.call_count == 2

    @patch("agent_core.telegram.bot.requests.post")
    def test_send_message_truncates_long_text(self, mock_post):
        mock_post.return_value = MagicMock(
            json=lambda: {"ok": True, "result": {"message_id": 1}}
        )
        bot = TelegramBot(token="test-token", chat_id=12345)
        long_text = "x" * 5000
        bot.send_message(long_text)
        sent_text = mock_post.call_args[1]["json"]["text"]
        assert len(sent_text) <= MAX_MESSAGE_LENGTH

    @patch("agent_core.telegram.bot.requests.post")
    def test_send_message_network_error(self, mock_post):
        import requests as req
        mock_post.side_effect = req.RequestException("timeout")
        bot = TelegramBot(token="test-token", chat_id=12345)
        assert bot.send_message("hello") is False

    def test_get_updates_when_not_configured(self):
        bot = TelegramBot(token="", chat_id=0)
        assert bot.get_updates() == []

    @patch("agent_core.telegram.bot.requests.get")
    def test_get_updates_returns_messages(self, mock_get):
        mock_get.return_value = MagicMock(json=lambda: {
            "ok": True,
            "result": [
                {
                    "update_id": 100,
                    "message": {
                        "text": "status",
                        "from": {"username": "TestUser"},
                        "chat": {"id": 12345},
                        "date": 1000000,
                        "message_id": 5,
                    }
                }
            ]
        })
        bot = TelegramBot(token="test-token", chat_id=12345)
        msgs = bot.get_updates()
        assert len(msgs) == 1
        assert msgs[0]["text"] == "status"
        assert msgs[0]["from"] == "TestUser"
        assert bot._last_update_id == 100

    @patch("agent_core.telegram.bot.requests.get")
    def test_get_updates_advances_offset(self, mock_get):
        mock_get.return_value = MagicMock(json=lambda: {
            "ok": True,
            "result": [
                {"update_id": 200, "message": {"text": "a", "from": {}, "chat": {"id": 1}, "date": 0, "message_id": 1}},
                {"update_id": 201, "message": {"text": "b", "from": {}, "chat": {"id": 1}, "date": 0, "message_id": 2}},
            ]
        })
        bot = TelegramBot(token="test-token", chat_id=12345)
        bot.get_updates()
        assert bot._last_update_id == 201

    @patch("agent_core.telegram.bot.requests.get")
    def test_get_updates_network_error(self, mock_get):
        import requests as req
        mock_get.side_effect = req.RequestException("connection refused")
        bot = TelegramBot(token="test-token", chat_id=12345)
        assert bot.get_updates() == []

    def test_get_status(self):
        bot = TelegramBot(token="test-token", chat_id=12345)
        status = bot.get_status()
        assert status["configured"] is True
        assert status["chat_id"] == 12345

    @patch("agent_core.telegram.bot.requests.post")
    def test_send_message_custom_chat_id(self, mock_post):
        mock_post.return_value = MagicMock(
            json=lambda: {"ok": True, "result": {"message_id": 1}}
        )
        bot = TelegramBot(token="test-token", chat_id=12345)
        bot.send_message("hello", chat_id=99999)
        assert mock_post.call_args[1]["json"]["chat_id"] == 99999


# ─── TelegramNotifier ──────────────────────────────────────


class TestTelegramNotifier:
    """Tests for notification formatting and cooldowns."""

    def _make_notifier(self):
        bot = MagicMock()
        bot.configured = True
        bot.send_message = MagicMock(return_value=True)
        return TelegramNotifier(bot=bot), bot

    def test_not_configured(self):
        bot = MagicMock()
        bot.configured = False
        notifier = TelegramNotifier(bot=bot)
        assert not notifier.configured

    def test_notify_startup(self):
        notifier, bot = self._make_notifier()
        assert notifier.notify_startup() is True
        bot.send_message.assert_called_once()
        msg = bot.send_message.call_args[0][0]
        assert "uruchomiona" in msg.lower()

    def test_notify_creative_tensions(self):
        notifier, bot = self._make_notifier()
        tensions = [
            {"category": "repetition", "severity": 0.85, "evidence": "NOOP loop"},
            {"category": "misalignment", "severity": 0.6, "evidence": "stuck goals"},
        ]
        assert notifier.notify_creative_tensions(tensions) is True
        msg = bot.send_message.call_args[0][0]
        assert "repetition" in msg
        assert "misalignment" in msg

    def test_notify_creative_tensions_cooldown(self):
        notifier, bot = self._make_notifier()
        tensions = [{"category": "test", "severity": 0.5}]
        assert notifier.notify_creative_tensions(tensions) is True
        # Second call within cooldown should be blocked
        assert notifier.notify_creative_tensions(tensions) is False
        assert bot.send_message.call_count == 1

    def test_notify_creative_empty_tensions(self):
        notifier, bot = self._make_notifier()
        assert notifier.notify_creative_tensions([]) is False

    def test_notify_creative_meta_goals(self):
        notifier, bot = self._make_notifier()
        goals = [
            {"description": "Break NOOP loop", "risk_level": "low"},
        ]
        assert notifier.notify_creative_meta_goals(goals) is True
        msg = bot.send_message.call_args[0][0]
        assert "Break NOOP" in msg

    def test_notify_self_analysis(self):
        notifier, bot = self._make_notifier()
        assert notifier.notify_self_analysis(
            "System analysis summary",
            ["Increase fetch rate", "Lower thresholds"],
        ) is True
        msg = bot.send_message.call_args[0][0]
        assert "K12" in msg
        assert "Increase fetch" in msg

    def test_notify_needs_human(self):
        notifier, bot = self._make_notifier()
        assert notifier.notify_needs_human("Low confidence") is True
        msg = bot.send_message.call_args[0][0]
        assert "K9" in msg

    def test_notify_health_drop(self):
        notifier, bot = self._make_notifier()
        assert notifier.notify_health_drop(0.5, "reduced", ["RAM critical"]) is True
        msg = bot.send_message.call_args[0][0]
        assert "50%" in msg
        assert "RAM critical" in msg

    def test_notify_mode_change_degradation(self):
        notifier, bot = self._make_notifier()
        assert notifier.notify_mode_change("active", "reduced", "RAM pressure") is True
        msg = bot.send_message.call_args[0][0]
        assert "reduced" in msg

    def test_notify_mode_change_recovery_suppressed(self):
        """Recovery back to ACTIVE should NOT trigger notification."""
        notifier, bot = self._make_notifier()
        assert notifier.notify_mode_change("reduced", "active") is False

    def test_notify_consecutive_failures(self):
        notifier, bot = self._make_notifier()
        assert notifier.notify_consecutive_failures("fetch", 3) is True
        msg = bot.send_message.call_args[0][0]
        assert "fetch" in msg
        assert "3" in msg

    def test_send_raw_no_cooldown(self):
        notifier, bot = self._make_notifier()
        assert notifier.send_raw("test 1") is True
        assert notifier.send_raw("test 2") is True
        assert bot.send_message.call_count == 2

    def test_get_status(self):
        notifier, _ = self._make_notifier()
        status = notifier.get_status()
        assert "cooldowns" in status
        assert "creative_tension" in status["cooldowns"]

    def test_cooldown_expires(self):
        notifier, bot = self._make_notifier()
        tensions = [{"category": "test", "severity": 0.5}]
        notifier.notify_creative_tensions(tensions)

        # Fast-forward past cooldown
        notifier._last_sent["creative_tension"] = time.time() - 8000
        assert notifier.notify_creative_tensions(tensions) is True
        assert bot.send_message.call_count == 2


# ─── TelegramBridge ────────────────────────────────────────


class TestTelegramBridge:
    """Tests for the facade combining bot + notifier + commands."""

    def test_register_and_dispatch_command(self):
        bot = MagicMock()
        bot.configured = True
        bot.get_updates = MagicMock(return_value=[
            {"text": "status", "from": "TestUser", "chat_id": 123, "date": 0, "message_id": 1}
        ])
        bot.send_message = MagicMock(return_value=True)

        bridge = TelegramBridge(bot=bot)
        bridge.register_command("status", lambda args: "All OK")

        unhandled = bridge.poll_and_respond()
        assert len(unhandled) == 0
        bot.send_message.assert_called_with("All OK")

    def test_unhandled_messages_returned(self):
        bot = MagicMock()
        bot.configured = True
        bot.get_updates = MagicMock(return_value=[
            {"text": "hello maria", "from": "TestUser", "chat_id": 123, "date": 0, "message_id": 1}
        ])

        bridge = TelegramBridge(bot=bot)
        unhandled = bridge.poll_and_respond()
        assert len(unhandled) == 1
        assert unhandled[0]["text"] == "hello maria"

    def test_command_with_slash_prefix(self):
        bot = MagicMock()
        bot.configured = True
        bot.get_updates = MagicMock(return_value=[
            {"text": "/help", "from": "TestUser", "chat_id": 123, "date": 0, "message_id": 1}
        ])
        bot.send_message = MagicMock(return_value=True)

        bridge = TelegramBridge(bot=bot)
        bridge.register_command("help", lambda args: "Help text")

        bridge.poll_and_respond()
        bot.send_message.assert_called_with("Help text")

    def test_command_with_args(self):
        bot = MagicMock()
        bot.configured = True
        bot.get_updates = MagicMock(return_value=[
            {"text": "approve abc123", "from": "TestUser", "chat_id": 123, "date": 0, "message_id": 1}
        ])
        bot.send_message = MagicMock(return_value=True)

        bridge = TelegramBridge(bot=bot)
        received_args = []
        bridge.register_command("approve", lambda args: (received_args.append(args), "Done")[-1])

        bridge.poll_and_respond()
        assert received_args == ["abc123"]

    def test_command_error_sends_error_message(self):
        bot = MagicMock()
        bot.configured = True
        bot.get_updates = MagicMock(return_value=[
            {"text": "crash", "from": "TestUser", "chat_id": 123, "date": 0, "message_id": 1}
        ])
        bot.send_message = MagicMock(return_value=True)

        bridge = TelegramBridge(bot=bot)
        bridge.register_command("crash", lambda args: 1/0)

        bridge.poll_and_respond()
        error_msg = bot.send_message.call_args[0][0]
        assert "Blad" in error_msg

    def test_not_configured_returns_empty(self):
        bot = MagicMock()
        bot.configured = False
        bridge = TelegramBridge(bot=bot)
        assert bridge.poll_and_respond() == []

    def test_get_status(self):
        bot = MagicMock()
        bot.configured = True
        bot.get_status = MagicMock(return_value={"configured": True})

        bridge = TelegramBridge(bot=bot)
        status = bridge.get_status()
        assert "bot" in status
        assert "notifier" in status


# ─── SharedContext integration ──────────────────────────────


class TestSharedContextTelegram:
    """Verify SharedContext has telegram_bridge field."""

    def test_shared_context_has_telegram_field(self):
        from agent_core.registry.shared_context import SharedContext
        ctx = SharedContext()
        assert hasattr(ctx, "telegram_bridge")
        assert ctx.telegram_bridge is None


# ─── HomeostasisCore integration ────────────────────────────


class TestCoreIntegration:
    """Verify HomeostasisCore has telegram bridge setter."""

    def test_core_has_telegram_setter(self):
        from agent_core.homeostasis.core import HomeostasisCore
        core = HomeostasisCore()
        assert hasattr(core, "set_telegram_bridge")
        assert hasattr(core, "_telegram_bridge")
        assert core._telegram_bridge is None

    def test_core_set_telegram_bridge(self):
        from agent_core.homeostasis.core import HomeostasisCore
        core = HomeostasisCore()
        mock_bridge = MagicMock()
        core.set_telegram_bridge(mock_bridge)
        assert core._telegram_bridge is mock_bridge

    def test_check_telegram_skips_when_no_bridge(self):
        """_check_telegram should not crash when bridge is None."""
        from agent_core.homeostasis.core import HomeostasisCore
        core = HomeostasisCore()
        core._check_telegram()  # Should not raise


# ─── ActionExecutor integration ─────────────────────────────


class TestExecutorTelegramNotifier:
    """Verify ActionExecutor has telegram_notifier setter."""

    def test_executor_has_telegram_setter(self):
        from agent_core.planner.action_executor import ActionExecutor
        executor = ActionExecutor()
        assert hasattr(executor, "set_telegram_notifier")
        assert executor._telegram_notifier is None

    def test_executor_set_telegram_notifier(self):
        from agent_core.planner.action_executor import ActionExecutor
        executor = ActionExecutor()
        mock_notifier = MagicMock()
        executor.set_telegram_notifier(mock_notifier)
        assert executor._telegram_notifier is mock_notifier
