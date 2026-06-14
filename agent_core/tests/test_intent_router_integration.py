"""T-IR-002 integration tests for /do telegram command + IntentRouter wire-up.

Verifies that:
- When ctx.intent_router routes to "local" path, /do executes the handler
  immediately and bypasses ApprovalQueue.
- When the router returns an openclaw_* path, /do falls through to the
  legacy ApprovalQueue + TaskIntentDetector flow unchanged.
- When ctx.intent_router is None (legacy behaviour, flag off equivalent),
  /do uses the original ApprovalQueue path.
- Router exceptions during route() are logged and fall through gracefully.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent_core.autonomy.approval_queue import ApprovalQueue
from agent_core.modules.homeostasis_telegram_commands import register_telegram_commands as _register_telegram_commands
from agent_core.routing import IntentRouter
from agent_core.telegram import TelegramBridge
from agent_core.telegram.bot import TelegramBot
from agent_core.telegram.notifier import TelegramNotifier
from agent_core.tests.spec_helpers import specced


@pytest.fixture
def bridge():
    bot = specced(TelegramBot, configured=False)
    notifier = specced(TelegramNotifier)
    return TelegramBridge(bot=bot, notifier=notifier)


@pytest.fixture
def base_ctx():
    """Minimal ctx with attributes referenced in /do closure."""
    ctx = SimpleNamespace()
    ctx.intent_router = None
    ctx.approval_queue = None
    ctx.telegram_notifier = None
    return ctx


def _do_handler(bridge):
    return bridge._command_handlers["do"]


class _StubMemoryQuery:
    """Stub matching the MemoryQuery surface used by routing/handlers/memory.py."""

    def get_knowledge_gaps(self, top_k: int = 5):
        return [
            SimpleNamespace(topic="paddleboard", gap_score=0.8),
            SimpleNamespace(topic="rust", gap_score=0.6),
        ]

    def get_topic_summary(self, topic: str):
        return f"[STUB summary] {topic}"

    def query_topic(self, topic: str, top_k: int = 5):
        return []


class TestCmdDoWithIntentRouter:
    def test_local_handler_short_circuits_queue(self, bridge, base_ctx, monkeypatch):
        """Flag on, memory query → IntentRouter handles locally, no queue."""
        monkeypatch.setenv("INTENT_ROUTER_ENABLED", "true")
        base_ctx.intent_router = IntentRouter(
            memory_query=_StubMemoryQuery(),
            enabled=True,
        )
        base_ctx.approval_queue = specced(ApprovalQueue)
        _register_telegram_commands(bridge, base_ctx)

        result = _do_handler(bridge)("co wiesz o paddleboard")

        assert isinstance(result, str) and result
        base_ctx.approval_queue.submit.assert_not_called()

    def test_openclaw_path_falls_through_to_queue(self, bridge, base_ctx, monkeypatch):
        """Flag on, file write task → router returns openclaw_*, legacy queue runs."""
        monkeypatch.setenv("INTENT_ROUTER_ENABLED", "true")
        base_ctx.intent_router = IntentRouter(enabled=True)

        queue = specced(ApprovalQueue)
        queue.submit.return_value = SimpleNamespace(
            status="pending",
            request_id="abc1234567890",
            tool_name="write",
            goal_description="[/do] napisz plik /tmp/x z trescia hi",
            authority_level="operator_request",
        )
        base_ctx.approval_queue = queue

        _register_telegram_commands(bridge, base_ctx)

        result = _do_handler(bridge)("napisz plik /tmp/x z trescia hi")

        queue.submit.assert_called_once()
        assert "Zgloszono" in result

    def test_router_none_uses_legacy_path(self, bridge, base_ctx):
        """ctx.intent_router=None preserves byte-identical legacy behaviour."""
        queue = specced(ApprovalQueue)
        queue.submit.return_value = SimpleNamespace(
            status="pending",
            request_id="def4567890123",
            tool_name="write",
            goal_description="[/do] zapisz plik /tmp/y z trescia hello",
            authority_level="operator_request",
        )
        base_ctx.approval_queue = queue

        _register_telegram_commands(bridge, base_ctx)

        result = _do_handler(bridge)("zapisz plik /tmp/y z trescia hello")

        queue.submit.assert_called_once()
        assert "Zgloszono" in result

    def test_router_exception_falls_through(self, bridge, base_ctx):
        """If router.route() raises, fall through to legacy queue path."""
        broken_router = specced(IntentRouter)
        broken_router.route.side_effect = RuntimeError("router boom")
        base_ctx.intent_router = broken_router

        queue = specced(ApprovalQueue)
        queue.submit.return_value = SimpleNamespace(
            status="pending",
            request_id="ghi7890123456",
            tool_name="write",
            goal_description="[/do] napisz plik /tmp/z z trescia x",
            authority_level="operator_request",
        )
        base_ctx.approval_queue = queue

        _register_telegram_commands(bridge, base_ctx)

        result = _do_handler(bridge)("napisz plik /tmp/z z trescia x")

        broken_router.route.assert_called_once()
        queue.submit.assert_called_once()
        assert "Zgloszono" in result

    def test_router_flag_off_never_returns_local(self, bridge, base_ctx, monkeypatch):
        """Flag off (default): router.route() returns openclaw_raw → legacy path runs."""
        monkeypatch.delenv("INTENT_ROUTER_ENABLED", raising=False)
        base_ctx.intent_router = IntentRouter(
            memory_query=_StubMemoryQuery(),
            enabled=False,
        )

        queue = specced(ApprovalQueue)
        queue.submit.return_value = SimpleNamespace(
            status="pending",
            request_id="jkl0123456789",
            tool_name="write",
            goal_description="[/do] napisz plik /tmp/w z trescia y",
            authority_level="operator_request",
        )
        base_ctx.approval_queue = queue

        _register_telegram_commands(bridge, base_ctx)

        # Even with memory query in router, flag off → openclaw_raw → falls through.
        result = _do_handler(bridge)("co wiesz o paddleboard")

        # Legacy TaskIntentDetector will reject this (not a write/read pattern),
        # so the response is the "Nie rozumiem zadania" branch, NOT a queue submit.
        # Either way, the local-handler short-circuit must NOT happen.
        assert "[INTENT_ROUTER]" not in result
