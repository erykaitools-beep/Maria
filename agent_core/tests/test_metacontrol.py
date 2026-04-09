"""
Tests for MetaController - goal stack, mode negotiation, shutdown.
"""

import time
import pytest
from unittest.mock import patch, MagicMock

from agent_core.metacontrol.controller import MetaController


class TestInit:
    """Initialization and legacy adapter fallback."""

    def test_init_defaults(self):
        mc = MetaController()
        assert mc._goal_stack == []
        assert mc._current_priority == "normal"
        assert mc._paused is False

    def test_legacy_adapter_missing(self):
        """Should work without legacy maria_core."""
        with patch(
            "agent_core.metacontrol.controller.MetaController._init_legacy_adapter"
        ):
            mc = MetaController()
            mc._legacy_meta = None
        assert mc._legacy_meta is None


class TestGoalStack:
    """Push, pop, peek, clear, get operations."""

    def test_push_and_get(self):
        mc = MetaController()
        mc.push_goal({"description": "learn physics"})
        mc.push_goal({"description": "run exam"})
        goals = mc.get_goals()
        assert len(goals) == 2
        assert goals[0]["description"] == "learn physics"
        assert goals[1]["description"] == "run exam"

    def test_push_adds_timestamp(self):
        mc = MetaController()
        before = time.time()
        mc.push_goal({"description": "test"})
        after = time.time()
        goal = mc.get_goals()[0]
        assert before <= goal["pushed_at"] <= after

    def test_push_at_max_depth_rejected(self):
        mc = MetaController()
        for i in range(MetaController.MAX_GOAL_DEPTH):
            assert mc.push_goal({"description": f"goal-{i}"}) is True
        assert mc.push_goal({"description": "overflow"}) is False
        assert mc.get_goal_stack_depth() == MetaController.MAX_GOAL_DEPTH

    def test_pop_returns_top(self):
        mc = MetaController()
        mc.push_goal({"description": "first"})
        mc.push_goal({"description": "second"})
        top = mc.pop_goal()
        assert top["description"] == "second"
        assert mc.get_goal_stack_depth() == 1

    def test_pop_empty_returns_none(self):
        mc = MetaController()
        assert mc.pop_goal() is None

    def test_peek_returns_top_without_removing(self):
        mc = MetaController()
        mc.push_goal({"description": "only"})
        top = mc.peek_goal()
        assert top["description"] == "only"
        assert mc.get_goal_stack_depth() == 1

    def test_peek_empty_returns_none(self):
        mc = MetaController()
        assert mc.peek_goal() is None

    def test_clear_returns_count(self):
        mc = MetaController()
        mc.push_goal({"description": "a"})
        mc.push_goal({"description": "b"})
        count = mc.clear_goals()
        assert count == 2
        assert mc.get_goal_stack_depth() == 0

    def test_clear_empty(self):
        mc = MetaController()
        assert mc.clear_goals() == 0

    def test_get_goals_returns_copy(self):
        mc = MetaController()
        mc.push_goal({"description": "x"})
        copy = mc.get_goals()
        copy.append({"description": "injected"})
        assert mc.get_goal_stack_depth() == 1


class TestInterruptGoalRefinement:
    """Homeostasis-triggered interruption."""

    def test_interrupt_keeps_root(self):
        mc = MetaController()
        mc.push_goal({"description": "root"})
        mc.push_goal({"description": "sub1"})
        mc.push_goal({"description": "sub2"})
        result = mc.interrupt_goal_refinement()
        assert result["success"] is True
        assert result["interrupted_count"] == 2
        assert result["remaining_depth"] == 1
        assert mc.get_goals()[0]["description"] == "root"

    def test_interrupt_empty_stack(self):
        mc = MetaController()
        result = mc.interrupt_goal_refinement()
        assert result["success"] is True
        assert result["interrupted_count"] == -1
        assert result["remaining_depth"] == 0


class TestPauseResume:
    """Pause/resume lifecycle."""

    def test_pause_resume_cycle(self):
        mc = MetaController()
        assert mc.is_paused() is False
        mc.pause()
        assert mc.is_paused() is True
        mc.resume()
        assert mc.is_paused() is False


class TestModeNegotiation:
    """Mode override requests and acknowledgments."""

    def test_request_mode_override(self):
        mc = MetaController()
        mc.push_goal({"description": "critical task"})
        req = mc.request_mode_override("active", "critical goal", duration_hours=1.5)
        assert req["type"] == "mode_override_request"
        assert req["desired_mode"] == "active"
        assert req["reason"] == "critical goal"
        assert req["duration_seconds"] == 5400
        assert req["requested_by"] == "metacontroller"
        assert req["current_goal"]["description"] == "critical task"

    def test_request_mode_override_empty_stack(self):
        mc = MetaController()
        req = mc.request_mode_override("active", "test")
        assert req["current_goal"] is None

    def test_acknowledge_sleep_pauses(self):
        mc = MetaController()
        assert mc.is_paused() is False
        mc.acknowledge_mode_change("active", "sleep", "low activity")
        assert mc.is_paused() is True

    def test_acknowledge_active_resumes(self):
        mc = MetaController()
        mc.pause()
        mc.acknowledge_mode_change("sleep", "active", "resources available")
        assert mc.is_paused() is False

    def test_acknowledge_active_no_resume_if_not_paused(self):
        """Active acknowledgment should not crash if not paused."""
        mc = MetaController()
        mc.acknowledge_mode_change("reduced", "active", "resources ok")
        assert mc.is_paused() is False

    def test_acknowledge_survival_keeps_critical_only(self):
        mc = MetaController()
        mc.push_goal({"description": "normal", "priority": "normal"})
        mc.push_goal({"description": "critical", "priority": "critical"})
        mc.push_goal({"description": "low", "priority": "low"})
        mc.acknowledge_mode_change("reduced", "survival", "overheating")
        goals = mc.get_goals()
        assert len(goals) == 1
        assert goals[0]["priority"] == "critical"

    def test_acknowledge_reduced_does_not_crash(self):
        """Reduced mode just logs, should not error."""
        mc = MetaController()
        mc.acknowledge_mode_change("active", "reduced", "high cpu")


class TestShutdown:
    """Graceful shutdown preparation."""

    def test_shutdown_prepare(self):
        mc = MetaController()
        mc.push_goal({"description": "in-progress"})
        result = mc.shutdown_prepare(grace_period_seconds=10)
        assert result["ready_shutdown"] is True
        assert result["goals_pending"] == 1

    def test_shutdown_empty(self):
        mc = MetaController()
        result = mc.shutdown_prepare()
        assert result["goals_pending"] == 0
