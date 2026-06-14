"""Tests for StuckHandler - self-diagnosis and repair (Levels 4-6)."""

import time
from unittest.mock import MagicMock

import pytest

from agent_core.planner.stuck_handler import (
    StuckHandler,
    StuckDiagnosis,
    StuckCause,
    RepairAction,
)
from agent_core.tests.spec_helpers import specced
from agent_core.goals.store import GoalStore
from agent_core.goals.goal_model import Goal
from agent_core.autonomy import AutonomyPolicy
from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
from agent_core.telegram.bot import TelegramBot


@pytest.fixture
def handler():
    return StuckHandler()


@pytest.fixture
def handler_with_deps():
    """StuckHandler with mock dependencies."""
    h = StuckHandler()
    goal_store = specced(GoalStore)
    autonomy = specced(AutonomyPolicy)
    analyzer = specced(KnowledgeAnalyzer)
    h.set_goal_store(goal_store)
    h.set_autonomy_policy(autonomy)
    h.set_knowledge_analyzer(analyzer)
    return h, goal_store, autonomy, analyzer


# -- Level 4: Diagnosis --

class TestDiagnosis:
    def test_material_exists(self, handler):
        fp = {"action": "ask_expert", "goal_id": "g-1", "reason": "expert_material_already_exists"}
        result = {"topic": "logika formalna"}
        diag = handler.diagnose(fp, result)
        assert diag.cause == StuckCause.MATERIAL_EXISTS
        assert diag.repair_action == RepairAction.SWITCH_TO_LEARN
        assert "logika formalna" in diag.detail

    def test_topic_well_covered(self, handler):
        fp = {"action": "ask_expert", "goal_id": "g-1", "reason": "topic_well_covered"}
        diag = handler.diagnose(fp, {"topic": "fizyka"})
        assert diag.cause == StuckCause.MATERIAL_EXISTS
        assert diag.repair_action == RepairAction.SWITCH_TO_LEARN

    def test_rate_limited(self, handler):
        fp = {"action": "fetch", "goal_id": "g-1", "reason": "rate_limited"}
        diag = handler.diagnose(fp, {})
        assert diag.cause == StuckCause.RATE_LIMITED
        assert "rate limit" in diag.detail

    def test_consecutive_failures(self, handler):
        fp = {"action": "learn", "goal_id": "g-1", "reason": "consecutive_failures"}
        diag = handler.diagnose(fp, {})
        assert diag.cause == StuckCause.CONSECUTIVE_FAILURES
        assert diag.repair_action == RepairAction.RESET_FAILURES

    def test_missing_subsystem(self, handler):
        fp = {"action": "learn", "goal_id": "g-1", "reason": "No teacher agent configured"}
        diag = handler.diagnose(fp, {})
        assert diag.cause == StuckCause.MISSING_SUBSYSTEM

    def test_llm_error(self, handler):
        fp = {"action": "ask_expert", "goal_id": "g-1", "reason": "llm_error"}
        diag = handler.diagnose(fp, {})
        assert diag.cause == StuckCause.LLM_ERROR

    def test_timeout(self, handler):
        fp = {"action": "ask_expert", "goal_id": "g-1", "reason": "Timeout after 45s"}
        diag = handler.diagnose(fp, {})
        assert diag.cause == StuckCause.LLM_ERROR

    def test_no_files(self, handler):
        fp = {"action": "learn", "goal_id": "g-1", "reason": "idle"}
        result = {"idle_reason": "no_files_to_learn"}
        diag = handler.diagnose(fp, result)
        assert diag.cause == StuckCause.NO_FILES
        assert diag.repair_action == RepairAction.TRIGGER_FETCH

    def test_unknown_cause(self, handler):
        fp = {"action": "learn", "goal_id": "g-1", "reason": "something_weird"}
        diag = handler.diagnose(fp, {})
        assert diag.cause == StuckCause.UNKNOWN
        assert "zdiagnozowac" in diag.detail


# -- Level 5: Self-repair --

class TestRepair:
    def test_switch_to_learn_with_goal_store(self, handler_with_deps):
        h, goal_store, _, _ = handler_with_deps
        mock_goal = specced(Goal, metadata={})
        goal_store.get.return_value = mock_goal

        diag = StuckDiagnosis(
            cause=StuckCause.MATERIAL_EXISTS,
            detail="test",
            repair_action=RepairAction.SWITCH_TO_LEARN,
            context={"topic": "fizyka", "goal_id": "g-1"},
        )
        result = h.try_repair(diag)

        assert result.repair_succeeded is True
        assert mock_goal.metadata.get("prefer_learn") is True
        goal_store.save.assert_called_once()

    def test_switch_to_learn_without_goal_store(self, handler):
        diag = StuckDiagnosis(
            cause=StuckCause.MATERIAL_EXISTS,
            detail="test",
            repair_action=RepairAction.SWITCH_TO_LEARN,
            context={"topic": "fizyka"},
        )
        result = handler.try_repair(diag)
        # Should still "succeed" with fallback message
        assert result.repair_succeeded is True

    def test_reset_failures(self, handler_with_deps):
        h, _, autonomy, _ = handler_with_deps

        diag = StuckDiagnosis(
            cause=StuckCause.CONSECUTIVE_FAILURES,
            detail="test",
            repair_action=RepairAction.RESET_FAILURES,
            context={"action": "learn"},
        )
        result = h.try_repair(diag)

        assert result.repair_succeeded is True
        autonomy.record_execution.assert_called_once_with("learn", True)

    def test_reset_failures_without_policy(self, handler):
        diag = StuckDiagnosis(
            cause=StuckCause.CONSECUTIVE_FAILURES,
            detail="test",
            repair_action=RepairAction.RESET_FAILURES,
            context={"action": "learn"},
        )
        result = handler.try_repair(diag)
        assert result.repair_succeeded is False

    def test_trigger_fetch(self, handler_with_deps):
        h, goal_store, _, _ = handler_with_deps
        mock_goal = specced(Goal, metadata={})
        goal_store.get.return_value = mock_goal

        diag = StuckDiagnosis(
            cause=StuckCause.NO_FILES,
            detail="test",
            repair_action=RepairAction.TRIGGER_FETCH,
            context={"goal_id": "g-1"},
        )
        result = h.try_repair(diag)

        assert result.repair_succeeded is True
        assert mock_goal.metadata.get("needs_fetch") is True

    def test_no_repair_action(self, handler):
        diag = StuckDiagnosis(
            cause=StuckCause.LLM_ERROR,
            detail="Backend down",
            repair_action=RepairAction.NONE,
        )
        result = handler.try_repair(diag)
        assert result.repair_succeeded is False
        assert "Brak" in result.repair_detail

    def test_repair_exception_handled(self, handler_with_deps):
        h, goal_store, _, _ = handler_with_deps
        goal_store.get.side_effect = RuntimeError("DB error")

        diag = StuckDiagnosis(
            cause=StuckCause.MATERIAL_EXISTS,
            detail="test",
            repair_action=RepairAction.SWITCH_TO_LEARN,
            context={"topic": "x", "goal_id": "g-1"},
        )
        result = h.try_repair(diag)
        # Should not raise, just mark as failed
        assert "nie powiodla" in result.repair_detail.lower() or "DB error" in result.repair_detail


# -- Level 6: Escalation --

class TestEscalation:
    def test_resolved_message(self, handler):
        diag = StuckDiagnosis(
            cause=StuckCause.MATERIAL_EXISTS,
            detail="Material o 'fizyka' juz istnieje.",
            repair_action=RepairAction.SWITCH_TO_LEARN,
            repair_succeeded=True,
            repair_detail="Przestawiam na LEARN.",
        )
        fp = {"action": "ask_expert", "goal_id": "g-123456", "reason": "exists"}

        msg = handler.format_escalation(diag, fp, count=3, cooldown_minutes=30)

        assert "Utknelam" in msg
        assert "Diagnoza:" in msg
        assert "Naprawa [OK]" in msg
        # No "Potrzebuje pomocy" since resolved
        assert "Potrzebuje pomocy" not in msg

    def test_unresolved_message_has_hints(self, handler):
        diag = StuckDiagnosis(
            cause=StuckCause.LLM_ERROR,
            detail="Backend LLM nie odpowiada.",
            repair_action=RepairAction.NONE,
            repair_succeeded=False,
        )
        fp = {"action": "ask_expert", "goal_id": "g-abc", "reason": "timeout"}

        msg = handler.format_escalation(diag, fp, count=5, cooldown_minutes=30)

        assert "Potrzebuje pomocy" in msg
        assert "Sugestie:" in msg
        assert "Ollama" in msg or "health" in msg

    def test_unknown_cause_hints(self, handler):
        diag = StuckDiagnosis(
            cause=StuckCause.UNKNOWN,
            detail="Nie moge zdiagnozowac.",
            repair_action=RepairAction.NONE,
        )
        fp = {"action": "learn", "goal_id": "g-x", "reason": "weird"}

        msg = handler.format_escalation(diag, fp, count=3, cooldown_minutes=30)

        assert "/trace" in msg or "/status" in msg

    def test_message_contains_metadata(self, handler):
        diag = StuckDiagnosis(
            cause=StuckCause.RATE_LIMITED,
            detail="Rate limit.",
        )
        fp = {"action": "fetch", "goal_id": "g-long-id-here", "reason": "rate"}

        msg = handler.format_escalation(diag, fp, count=7, cooldown_minutes=30)

        assert "Powtorzen: 7" in msg
        assert "Cooldown: 30 min" in msg
        assert "g-long-id-he" in msg  # truncated to 12


class TestNotifierStuck:
    def test_notify_stuck_sends_raw_message(self):
        from agent_core.telegram.notifier import TelegramNotifier

        mock_bot = specced(TelegramBot)
        mock_bot.configured = True
        mock_bot.send_message.return_value = True
        notifier = TelegramNotifier(bot=mock_bot)

        msg = "*Utknelam*\nDiagnoza: test\nNaprawa: ok"
        ok = notifier.notify_stuck(msg)

        assert ok is True
        mock_bot.send_message.assert_called_once_with(msg)

    def test_notify_stuck_shares_cooldown_with_planner(self):
        """notify_stuck and notify_stuck_planner share same cooldown."""
        from agent_core.telegram.notifier import TelegramNotifier

        mock_bot = specced(TelegramBot)
        mock_bot.configured = True
        mock_bot.send_message.return_value = True
        notifier = TelegramNotifier(bot=mock_bot)

        # First: notify_stuck
        notifier.notify_stuck("msg1")
        # Second: notify_stuck_planner should be blocked by same cooldown
        ok = notifier.notify_stuck_planner(
            action="x", goal_id="g-1", count=3, reason="y",
        )
        assert ok is False
        assert mock_bot.send_message.call_count == 1
