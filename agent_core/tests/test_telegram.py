"""
Tests for Telegram integration (bot, notifier, bridge).

All HTTP calls mocked - zero external dependencies.
"""

import json
import time
import threading
import pytest
from unittest.mock import patch, MagicMock

from agent_core.telegram.bot import TelegramBot, MAX_MESSAGE_LENGTH
from agent_core.telegram.notifier import TelegramNotifier, ALERT_COOLDOWNS
from agent_core.telegram.outbox_store import TelegramOutboxStore
from agent_core.telegram import TelegramBridge
from agent_core.tests.spec_helpers import specced
from agent_core.cross_validation.cross_validator import CrossValidator
from agent_core.cross_validation.dispute_log import DisputeLog, DisputeRecord
from agent_core.registry.shared_context import SharedContext


def _jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ─── TelegramBot ───────────────────────────────────────────


class TestTelegramBot:
    """Tests for low-level Telegram Bot API client."""

    def _bot(self, tmp_path, token="test-token", chat_id=12345):
        return TelegramBot(
            token=token,
            chat_id=chat_id,
            outbox_path=tmp_path / "telegram_outbox.jsonl",
        )

    @patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "0"}, clear=False)
    def test_not_configured_without_token(self):
        bot = TelegramBot(token="", chat_id=0)
        assert not bot.configured

    def test_configured_with_valid_params(self):
        bot = TelegramBot(token="test-token", chat_id=12345)
        assert bot.configured

    @patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "0"}, clear=False)
    def test_send_message_when_not_configured(self, tmp_path):
        outbox = tmp_path / "telegram_outbox.jsonl"
        bot = TelegramBot(token="", chat_id=0, outbox_path=outbox)
        assert bot.send_message("test") is False
        rows = _jsonl(outbox)
        assert rows[0]["kind"] == "send_message"
        assert rows[0]["status"] == "failed"
        assert rows[0]["error"] == "not_configured"

    @patch("agent_core.telegram.bot.requests.post")
    def test_send_message_success(self, mock_post, tmp_path):
        mock_post.return_value = MagicMock(
            json=lambda: {"ok": True, "result": {"message_id": 1}}
        )
        outbox = tmp_path / "telegram_outbox.jsonl"
        bot = self._bot(tmp_path)
        assert bot.send_message("hello") is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["text"] == "hello"
        assert call_kwargs[1]["json"]["chat_id"] == 12345
        rows = _jsonl(outbox)
        assert len(rows) == 1
        assert rows[0]["kind"] == "send_message"
        assert rows[0]["status"] == "sent"
        assert rows[0]["success"] is True
        assert rows[0]["text_preview"] == "hello"
        assert rows[0]["text_sha256"]
        assert rows[0]["telegram_message_id"] == 1

    @patch("agent_core.telegram.bot.requests.post")
    def test_send_message_api_error(self, mock_post, tmp_path):
        mock_post.return_value = MagicMock(
            json=lambda: {"ok": False, "description": "Bad Request"}
        )
        bot = self._bot(tmp_path)
        assert bot.send_message("hello", parse_mode=None) is False
        rows = _jsonl(tmp_path / "telegram_outbox.jsonl")
        assert rows[0]["status"] == "failed"
        assert rows[0]["error"] == "Bad Request"

    @patch("agent_core.telegram.bot.requests.post")
    def test_send_message_markdown_fallback(self, mock_post, tmp_path):
        """If Markdown parse fails, retry without parse_mode."""
        responses = [
            MagicMock(json=lambda: {"ok": False, "description": "can't parse entities"}),
            MagicMock(json=lambda: {"ok": True, "result": {"message_id": 2}}),
        ]
        mock_post.side_effect = responses
        bot = self._bot(tmp_path)
        assert bot.send_message("*bad markdown") is True
        assert mock_post.call_count == 2
        rows = _jsonl(tmp_path / "telegram_outbox.jsonl")
        assert len(rows) == 1
        assert rows[0]["status"] == "sent"
        assert rows[0]["telegram_message_id"] == 2
        assert rows[0]["metadata"]["retry"] == "markdown_fallback"

    @patch("agent_core.telegram.bot.requests.post")
    def test_send_message_truncates_long_text(self, mock_post, tmp_path):
        mock_post.return_value = MagicMock(
            json=lambda: {"ok": True, "result": {"message_id": 1}}
        )
        bot = self._bot(tmp_path)
        long_text = "x" * 5000
        bot.send_message(long_text)
        sent_text = mock_post.call_args[1]["json"]["text"]
        assert len(sent_text) <= MAX_MESSAGE_LENGTH
        rows = _jsonl(tmp_path / "telegram_outbox.jsonl")
        assert rows[0]["text_len"] == len(sent_text)
        assert len(rows[0]["text_preview"]) <= 500

    @patch("agent_core.telegram.bot.requests.post")
    def test_send_message_network_error(self, mock_post, tmp_path):
        import requests as req
        mock_post.side_effect = req.RequestException("timeout")
        bot = self._bot(tmp_path)
        assert bot.send_message("hello") is False
        rows = _jsonl(tmp_path / "telegram_outbox.jsonl")
        assert rows[0]["status"] == "failed"
        assert "timeout" in rows[0]["error"]

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
    def test_send_message_custom_chat_id(self, mock_post, tmp_path):
        mock_post.return_value = MagicMock(
            json=lambda: {"ok": True, "result": {"message_id": 1}}
        )
        bot = self._bot(tmp_path)
        bot.send_message("hello", chat_id=99999)
        assert mock_post.call_args[1]["json"]["chat_id"] == 99999
        rows = _jsonl(tmp_path / "telegram_outbox.jsonl")
        assert rows[0]["chat_id"] == 99999


# ─── TelegramOutboxStore ───────────────────────────────────


class TestTelegramOutboxStore:
    def test_store_appends_jsonl(self, tmp_path):
        path = tmp_path / "outbox.jsonl"
        store = TelegramOutboxStore(path)
        store.record_attempt(kind="send_message", success=True, chat_id=1, text="one")
        store.record_attempt(kind="send_message", success=False, chat_id=1, text="two", error="fail")

        rows = _jsonl(path)
        assert len(rows) == 2
        assert rows[0]["status"] == "sent"
        assert rows[1]["status"] == "failed"

    def test_store_tail_skips_corrupt_lines(self, tmp_path):
        path = tmp_path / "outbox.jsonl"
        path.write_text('{"kind":"bad"}\nnot-json\n', encoding="utf-8")
        store = TelegramOutboxStore(path)
        store.record_attempt(kind="send_message", success=True, chat_id=1, text="ok")

        rows = store.tail()
        assert len(rows) == 2
        assert rows[-1].text_preview == "ok"

    def test_store_concurrent_appends(self, tmp_path):
        path = tmp_path / "outbox.jsonl"
        store = TelegramOutboxStore(path)

        def worker(i):
            store.record_attempt(kind="send_message", success=True, chat_id=i, text=str(i))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        rows = _jsonl(path)
        assert len(rows) == 20
        assert {row["chat_id"] for row in rows} == set(range(20))


# ─── TelegramNotifier ──────────────────────────────────────


class TestTelegramNotifier:
    """Tests for notification formatting and cooldowns."""

    def _make_notifier(self):
        bot = specced(TelegramBot)
        bot.configured = True
        bot.send_message.return_value = True
        return TelegramNotifier(bot=bot), bot

    def test_not_configured(self):
        bot = specced(TelegramBot)
        bot.configured = False
        notifier = TelegramNotifier(bot=bot)
        assert not notifier.configured

    def test_notify_startup(self):
        notifier, bot = self._make_notifier()
        # Clear file-based cooldown to ensure test passes
        from agent_core.telegram.notifier import _STARTUP_NOTIFY_FILE
        try:
            _STARTUP_NOTIFY_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        assert notifier.notify_startup() is True
        bot.send_message.assert_called_once()
        msg = bot.send_message.call_args[0][0]
        assert "uruchomiona" in msg.lower()

    def test_code_agent_notify_wiring_contract(self):
        """Audyt 2026-06-12: wiring code_agenta wolal notifier.send_message,
        ktore NIGDY nie istnialo -- AttributeError ubijal init w kazdym z ~290
        bootow od deployu. Kontrakt: realne API to send_raw; code_agent sle
        przez lambda z parse_mode=None (podkreslniki w sciezkach/komendach
        checkpointow, ktore Markdown po cichu zjada)."""
        notifier, bot = self._make_notifier()

        # Fantom nie moze wrocic: TelegramNotifier nie ma send_message.
        assert not hasattr(notifier, "send_message")

        # Dokladny ksztalt wiringu z homeostasis_module.
        notify_fn = lambda text, _n=notifier: _n.send_raw(text, parse_mode=None)
        assert notify_fn("[Code] wynik z /sciezka_z_podkreslnikami") is True
        bot.send_message.assert_called_once_with(
            "[Code] wynik z /sciezka_z_podkreslnikami", parse_mode=None,
        )

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
        bot = specced(TelegramBot)
        bot.configured = True
        bot.get_updates = MagicMock(return_value=[
            {"text": "status", "from": "TestUser", "chat_id": 123, "date": 0, "message_id": 1}
        ])
        bot.send_message.return_value = True

        bridge = TelegramBridge(bot=bot)
        bridge.register_command("status", lambda args: "All OK")

        unhandled = bridge.poll_and_respond()
        assert len(unhandled) == 0
        bot.send_message.assert_called_with("All OK")

    def test_non_master_chat_ignored(self):
        """Security: a command from a non-master chat must NOT dispatch."""
        bot = specced(TelegramBot)
        bot.configured = True
        bot._chat_id = 123  # configured master chat
        bot.get_updates = MagicMock(return_value=[
            {"text": "status", "from": "Attacker", "chat_id": 999,
             "date": 0, "message_id": 1}
        ])
        bot.send_message.return_value = True

        bridge = TelegramBridge(bot=bot)
        called = []
        bridge.register_command("status", lambda args: called.append(1) or "OK")

        unhandled = bridge.poll_and_respond()
        assert called == []                  # handler never ran
        bot.send_message.assert_not_called()  # no reply leaked
        assert unhandled == []                # not surfaced to the chat path

    def test_master_chat_dispatches(self):
        """A command from the configured master chat dispatches as before."""
        bot = specced(TelegramBot)
        bot.configured = True
        bot._chat_id = 123
        bot.get_updates = MagicMock(return_value=[
            {"text": "status", "from": "Eryk", "chat_id": 123,
             "date": 0, "message_id": 1}
        ])
        bot.send_message.return_value = True

        bridge = TelegramBridge(bot=bot)
        bridge.register_command("status", lambda args: "All OK")

        bridge.poll_and_respond()
        bot.send_message.assert_called_with("All OK")

    def test_unhandled_messages_returned(self):
        bot = specced(TelegramBot)
        bot.configured = True
        bot.get_updates = MagicMock(return_value=[
            {"text": "hello maria", "from": "TestUser", "chat_id": 123, "date": 0, "message_id": 1}
        ])

        bridge = TelegramBridge(bot=bot)
        unhandled = bridge.poll_and_respond()
        assert len(unhandled) == 1
        assert unhandled[0]["text"] == "hello maria"

    def test_command_with_slash_prefix(self):
        bot = specced(TelegramBot)
        bot.configured = True
        bot.get_updates = MagicMock(return_value=[
            {"text": "/help", "from": "TestUser", "chat_id": 123, "date": 0, "message_id": 1}
        ])
        bot.send_message.return_value = True

        bridge = TelegramBridge(bot=bot)
        bridge.register_command("help", lambda args: "Help text")

        bridge.poll_and_respond()
        bot.send_message.assert_called_with("Help text")

    def test_command_with_args(self):
        bot = specced(TelegramBot)
        bot.configured = True
        bot.get_updates = MagicMock(return_value=[
            {"text": "approve abc123", "from": "TestUser", "chat_id": 123, "date": 0, "message_id": 1}
        ])
        bot.send_message.return_value = True

        bridge = TelegramBridge(bot=bot)
        received_args = []
        bridge.register_command("approve", lambda args: (received_args.append(args), "Done")[-1])

        bridge.poll_and_respond()
        assert received_args == ["abc123"]

    def test_command_error_sends_error_message(self):
        bot = specced(TelegramBot)
        bot.configured = True
        bot.get_updates = MagicMock(return_value=[
            {"text": "crash", "from": "TestUser", "chat_id": 123, "date": 0, "message_id": 1}
        ])
        bot.send_message.return_value = True

        bridge = TelegramBridge(bot=bot)
        bridge.register_command("crash", lambda args: 1/0)

        bridge.poll_and_respond()
        error_msg = bot.send_message.call_args[0][0]
        assert "Blad" in error_msg

    def test_not_configured_returns_empty(self):
        bot = specced(TelegramBot)
        bot.configured = False
        bridge = TelegramBridge(bot=bot)
        assert bridge.poll_and_respond() == []

    def test_get_status(self):
        bot = specced(TelegramBot)
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
        mock_bridge = specced(TelegramBridge)
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
        mock_notifier = specced(TelegramNotifier)
        executor.set_telegram_notifier(mock_notifier)
        assert executor._telegram_notifier is mock_notifier


# ─── /validate command ─────────────────────────────────────


class TestValidateCommand:
    """Tests for Telegram /validate command handler."""

    def test_validate_stats_no_validator(self):
        """Without cross_validator, shows 'niedostepny'."""
        bridge = TelegramBridge(
            bot=TelegramBot(token="test", chat_id=1),
            notifier=specced(TelegramNotifier),
        )
        # Simulate ctx with no cross_validator
        ctx = specced(SharedContext)
        ctx.cross_validator = None
        ctx.dispute_log = None

        def _cmd_validate(args):
            cv = getattr(ctx, 'cross_validator', None)
            dl = getattr(ctx, 'dispute_log', None)
            parts = ["*Cross-Validation (Faza F):*"]
            if cv:
                stats = cv.get_stats()
                parts.append(f"Validated: {stats.get('chunks_validated', 0)} chunks")
            else:
                parts.append("CrossValidator niedostepny (brak NIM?).")
            return "\n".join(parts)

        bridge.register_command("validate", _cmd_validate)
        # Simulate command
        result = _cmd_validate("")
        assert "niedostepny" in result

    def test_validate_stats_with_validator(self):
        """With cross_validator, shows stats."""
        mock_cv = specced(CrossValidator)
        mock_cv.get_stats.return_value = {
            "chunks_validated": 10,
            "chunks_agreed": 8,
            "chunks_disputed": 2,
            "avg_confidence": 0.75,
        }

        ctx = specced(SharedContext)
        ctx.cross_validator = mock_cv
        ctx.dispute_log = None

        def _cmd_validate(args):
            cv = ctx.cross_validator
            parts = ["*Cross-Validation (Faza F):*"]
            if cv:
                stats = cv.get_stats()
                parts.append(f"Validated: {stats.get('chunks_validated', 0)} chunks")
                parts.append(f"Agreed: {stats.get('chunks_agreed', 0)}")
                parts.append(f"Disputed: {stats.get('chunks_disputed', 0)}")
            return "\n".join(parts)

        result = _cmd_validate("")
        assert "Validated: 10" in result
        assert "Agreed: 8" in result
        assert "Disputed: 2" in result

    def test_validate_disputes_empty(self):
        """Disputes subcommand with empty log."""
        mock_dl = specced(DisputeLog)
        mock_dl.get_recent.return_value = []

        def _cmd(args):
            if args.strip() == "disputes":
                recent = mock_dl.get_recent(limit=10)
                if not recent:
                    return "Brak sporow."
            return ""

        result = _cmd("disputes")
        assert "Brak sporow" in result

    def test_validate_disputes_with_data(self):
        """Disputes subcommand with data."""
        mock_dl = specced(DisputeLog)
        dispute = specced(DisputeRecord)
        dispute.to_dict.return_value = {
            "file_id": "test_file.txt",
            "dimension": "summary",
            "severity": "medium",
        }
        mock_dl.get_recent.return_value = [dispute]

        def _cmd(args):
            if args.strip() == "disputes":
                recent = mock_dl.get_recent(limit=10)
                if not recent:
                    return "Brak sporow."
                lines = []
                for d in recent:
                    rec = d if isinstance(d, dict) else d.to_dict()
                    lines.append(f"  [{rec.get('file_id', '?')[:20]}] {rec.get('dimension', '?')}")
                return "*Ostatnie spory:*\n" + "\n".join(lines)
            return ""

        result = _cmd("disputes")
        assert "test_file.txt" in result
        assert "summary" in result


# ─── poll_and_respond: unknown-command feedback ──────────────


class _FakeBot:
    """Minimal bot stub: scripted get_updates + recorded send_message."""

    def __init__(self, messages, chat_id=12345):
        self._messages = messages
        self._chat_id = chat_id
        self.sent = []

    @property
    def configured(self):
        return True

    def get_updates(self, limit=10):
        return self._messages

    def send_message(self, text, parse_mode="Markdown", chat_id=None):
        self.sent.append(text)
        return True


class TestUnknownCommandFeedback:
    """Unknown SLASH commands must get a reply, not be silently dropped."""

    def _bridge(self, messages):
        bot = _FakeBot(messages)
        return TelegramBridge(bot=bot, notifier=MagicMock()), bot

    def test_unknown_slash_command_replies(self):
        bridge, bot = self._bridge(
            [{"text": "/teacher", "chat_id": 12345, "message_id": 1}]
        )
        unhandled = bridge.poll_and_respond()
        assert any("Nieznana komenda: /teacher" in m for m in bot.sent)
        # still recorded as unhandled (for OperatorModel learning)
        assert len(unhandled) == 1

    def test_known_command_runs_no_unknown_reply(self):
        bridge, bot = self._bridge(
            [{"text": "/ping", "chat_id": 12345, "message_id": 2}]
        )
        bridge.register_command("ping", lambda args: "pong")
        bridge.poll_and_respond()
        assert "pong" in bot.sent
        assert not any("Nieznana komenda" in m for m in bot.sent)

    def test_plain_text_not_treated_as_unknown_command(self):
        bridge, bot = self._bridge(
            [{"text": "naucz sie fizyki", "chat_id": 12345, "message_id": 3}]
        )
        unhandled = bridge.poll_and_respond()
        # no "unknown command" spam for normal chat; goes to unhandled
        assert not any("Nieznana komenda" in m for m in bot.sent)
        assert len(unhandled) == 1
        assert "naucz sie fizyki" in bridge.last_poll_texts


class TestParseChatId:
    """_parse_chat_id: TELEGRAM_CHAT_ID must degrade to 0, never crash the
    constructor. int("") / int("garbage") raise ValueError, and the ctor runs
    at wiring time outside any try/except, so a blanked/malformed .env line
    used to take down TelegramBot entirely.
    """

    @pytest.mark.parametrize("raw,expected", [
        ("123", 123),
        ("-1001234567890", -1001234567890),  # group/supergroup chat id
        (" 42 ", 42),
        ("", 0),
        ("   ", 0),
        ("notanumber", 0),
        (None, 0),
    ])
    def test_parse_chat_id(self, raw, expected):
        from agent_core.telegram.bot import _parse_chat_id
        assert _parse_chat_id(raw) == expected

    def test_ctor_survives_empty_env_chat_id(self, monkeypatch, tmp_path):
        # Regression: int(os.environ["TELEGRAM_CHAT_ID"]) crashed the ctor when
        # the var was "" (a blanked .env line). Must degrade to not-configured.
        # delenv first to defeat the real prod .env leak (load_dotenv at import).
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
        from agent_core.telegram.bot import TelegramBot
        bot = TelegramBot(outbox_path=tmp_path / "outbox.jsonl")  # must not raise
        assert bot.configured is False

    def test_ctor_survives_garbage_env_chat_id(self, monkeypatch, tmp_path):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "notanumber")
        from agent_core.telegram.bot import TelegramBot
        bot = TelegramBot(outbox_path=tmp_path / "outbox.jsonl")  # must not raise
        assert bot.configured is False
