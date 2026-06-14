"""Tests for StrategicPlanner - Planner v2 Phase B."""

import json
import time
from unittest.mock import MagicMock, patch
from datetime import datetime

import pytest

from agent_core.goals.store import GoalStore
from agent_core.tests.spec_helpers import specced
from agent_core.planner.strategic_planner import (
    StrategicPlanner,
    _parse_llm_response,
    _build_context_prompt,
    REPLAN_INTERVAL_SEC,
)
from agent_core.planner.strategic_plan import StrategicPlan, PlannedAction
from agent_core.planner.time_context import TimeContext


# ============================================================
# StrategicPlan model
# ============================================================

class TestStrategicPlan:

    def test_next_action(self):
        plan = StrategicPlan(action_queue=[
            PlannedAction(action_type="learn", reason="test"),
            PlannedAction(action_type="exam", reason="test2"),
        ])
        assert plan.next_action.action_type == "learn"

    def test_next_action_skips_completed(self):
        plan = StrategicPlan(action_queue=[
            PlannedAction(action_type="learn", completed=True),
            PlannedAction(action_type="exam", reason="test"),
        ])
        assert plan.next_action.action_type == "exam"

    def test_next_action_skips_skipped(self):
        plan = StrategicPlan(action_queue=[
            PlannedAction(action_type="learn", skipped=True),
            PlannedAction(action_type="exam", reason="test"),
        ])
        assert plan.next_action.action_type == "exam"

    def test_exhausted_when_all_done(self):
        plan = StrategicPlan(action_queue=[
            PlannedAction(action_type="learn", completed=True),
            PlannedAction(action_type="exam", skipped=True),
        ])
        assert plan.is_exhausted is True

    def test_not_exhausted(self):
        plan = StrategicPlan(action_queue=[
            PlannedAction(action_type="learn"),
        ])
        assert plan.is_exhausted is False

    def test_expired(self):
        plan = StrategicPlan(valid_until=time.time() - 10)
        assert plan.is_expired is True

    def test_not_expired(self):
        plan = StrategicPlan(valid_until=time.time() + 3600)
        assert plan.is_expired is False

    def test_mark_completed(self):
        plan = StrategicPlan(action_queue=[
            PlannedAction(action_type="learn"),
        ])
        plan.mark_completed(0)
        assert plan.action_queue[0].completed is True

    def test_mark_skipped(self):
        plan = StrategicPlan(action_queue=[
            PlannedAction(action_type="learn"),
        ])
        plan.mark_skipped(0, "backed off")
        assert plan.action_queue[0].skipped is True

    def test_to_dict(self):
        plan = StrategicPlan(
            action_queue=[PlannedAction(action_type="learn", goal_id="g-1", reason="test")],
            idle_strategy="creative",
            notes="test plan",
        )
        d = plan.to_dict()
        assert len(d["action_queue"]) == 1
        assert d["idle_strategy"] == "creative"

    def test_summary(self):
        plan = StrategicPlan(
            action_queue=[
                PlannedAction(action_type="learn", goal_id="g-123456789", reason="window open"),
                PlannedAction(action_type="exam", reason="test knowledge"),
            ],
        )
        s = plan.summary()
        assert "learn" in s
        assert "2 remaining" in s


# ============================================================
# LLM response parsing
# ============================================================

class TestParseResponse:

    def test_valid_json(self):
        raw = json.dumps({
            "plan": [{"action": "learn", "reason": "test"}],
            "idle_strategy": "creative",
        })
        result = _parse_llm_response(raw)
        assert result is not None
        assert len(result["plan"]) == 1

    def test_json_in_markdown(self):
        raw = '```json\n{"plan": [{"action": "learn"}], "idle_strategy": "wait"}\n```'
        result = _parse_llm_response(raw)
        assert result is not None

    def test_json_with_text_around(self):
        raw = 'Here is my plan:\n{"plan": [{"action": "exam"}], "idle_strategy": "wait"}\nDone!'
        result = _parse_llm_response(raw)
        assert result is not None
        assert result["plan"][0]["action"] == "exam"

    def test_garbage_returns_none(self):
        result = _parse_llm_response("This is not JSON at all")
        assert result is None

    def test_empty_string(self):
        result = _parse_llm_response("")
        assert result is None


# ============================================================
# StrategicPlanner
# ============================================================

class TestStrategicPlanner:

    def test_no_llm_returns_none(self):
        sp = StrategicPlanner()
        assert sp.plan() is None

    def test_should_replan_no_llm(self):
        sp = StrategicPlanner()
        assert sp.should_replan() is False

    def test_should_replan_after_interval(self):
        sp = StrategicPlanner()
        sp.set_llm_fn(lambda role, prompt: "")
        sp._last_plan_ts = time.time() - REPLAN_INTERVAL_SEC - 10
        assert sp.should_replan() is True

    def test_should_replan_on_event(self):
        sp = StrategicPlanner()
        sp.set_llm_fn(lambda role, prompt: "")
        sp._last_plan_ts = time.time()  # Just planned
        assert sp.should_replan(event="goal_achieved") is True

    def test_should_not_replan_too_soon(self):
        sp = StrategicPlanner()
        sp.set_llm_fn(lambda role, prompt: "")
        sp._last_plan_ts = time.time()
        assert sp.should_replan() is False

    def test_plan_with_llm(self):
        response = json.dumps({
            "plan": [
                {"action": "learn", "goal_id": None, "reason": "window open"},
                {"action": "exam", "reason": "test after learn"},
            ],
            "blocked_until": {},
            "idle_strategy": "creative",
            "notes": "Morning learning session",
        })
        sp = StrategicPlanner()
        sp.set_llm_fn(lambda role, prompt: response)

        plan = sp.plan()
        assert plan is not None
        assert len(plan.action_queue) == 2
        assert plan.action_queue[0].action_type == "learn"
        assert plan.idle_strategy == "creative"
        assert plan.model_used == "qwen3:8b"

    def test_plan_validates_goal_ids(self):
        response = json.dumps({
            "plan": [
                {"action": "learn", "goal_id": "g-hallucinated", "reason": "test"},
            ],
            "idle_strategy": "wait",
        })
        mock_store = specced(GoalStore)
        mock_store.get.return_value = None  # Goal doesn't exist

        sp = StrategicPlanner()
        sp.set_llm_fn(lambda role, prompt: response)
        sp.set_goal_store(mock_store)

        plan = sp.plan()
        assert plan.action_queue[0].goal_id is None  # Hallucinated ID dropped

    def test_plan_llm_failure_uses_fallback(self):
        def failing_llm(role, prompt):
            raise RuntimeError("Connection refused")

        sp = StrategicPlanner()
        sp.set_llm_fn(failing_llm)

        plan = sp.plan()
        assert plan is not None
        assert plan.model_used == "rules"

    def test_plan_unparseable_uses_fallback(self):
        sp = StrategicPlanner()
        sp.set_llm_fn(lambda role, prompt: "I don't know what to do")

        plan = sp.plan()
        assert plan is not None
        assert plan.model_used == "rules"

    def test_rule_fallback_learning_window(self):
        sp = StrategicPlanner()
        sp._time_ctx = TimeContext(now=datetime(2026, 4, 13, 9, 30))  # Monday 9:30

        plan = sp._rule_based_fallback()
        action_types = [a.action_type for a in plan.action_queue]
        assert "learn" in action_types

    def test_rule_fallback_evening(self):
        sp = StrategicPlanner()
        sp._time_ctx = TimeContext(now=datetime(2026, 4, 13, 19, 0))  # Monday evening

        plan = sp._rule_based_fallback()
        action_types = [a.action_type for a in plan.action_queue]
        assert "creative" in action_types

    def test_rule_fallback_quiet(self):
        sp = StrategicPlanner()
        sp._time_ctx = TimeContext(now=datetime(2026, 4, 13, 23, 0))  # Night

        plan = sp._rule_based_fallback()
        assert plan.idle_strategy == "wait"
        assert len(plan.action_queue) == 0

    def test_record_action(self):
        sp = StrategicPlanner()
        sp.record_action("learn", "g-1", success=True)
        sp.record_action("exam", "g-1", success=False)
        assert len(sp._recent_actions) == 2

    def test_current_plan_expired(self):
        sp = StrategicPlanner()
        sp._current_plan = StrategicPlan(valid_until=time.time() - 10)
        assert sp.current_plan is None

    def test_current_plan_valid(self):
        sp = StrategicPlanner()
        sp._current_plan = StrategicPlan(valid_until=time.time() + 3600)
        assert sp.current_plan is not None

    def test_should_replan_when_exhausted(self):
        sp = StrategicPlanner()
        sp.set_llm_fn(lambda role, prompt: "")
        sp._last_plan_ts = time.time()  # Just planned
        sp._current_plan = StrategicPlan(
            valid_until=time.time() + 3600,
            action_queue=[PlannedAction(action_type="learn", completed=True)],
        )
        assert sp.should_replan() is True


class TestContextPrompt:

    def test_builds_valid_json(self):
        tc = TimeContext(now=datetime(2026, 4, 13, 10, 0))
        result = _build_context_prompt(
            time_ctx=tc,
            active_goals=[{"id": "g-1", "type": "learning", "description": "test", "progress": 0.5, "age_hours": 2}],
            recent_actions=[{"action_type": "learn", "success": True, "ago_min": 5, "ts": time.time()}],
            knowledge_gaps=["fizyka"],
            retention_rate=0.75,
            available_materials=3,
            beliefs_weak=5,
            action_failures={},
        )
        parsed = json.loads(result)
        assert parsed["learning_window"] is True
        assert parsed["retention_rate"] == 0.75
