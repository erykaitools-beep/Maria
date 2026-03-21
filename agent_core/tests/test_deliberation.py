"""
Tests for K8 Deliberation / Strategic Planning.

Tests cover:
- Strategy + Step dataclasses (serialization, properties)
- Strategy Templates (3 templates, registry)
- IntentTracker (record, query, persistence)
- Deliberator (select strategy, advance, fallback, abandon)
- Deliberation facade
- PlannerCore integration (deliberation -> plan creation, outcome reporting)
"""

import json
import time
from pathlib import Path

import pytest

from agent_core.deliberation.strategy import (
    Step,
    StepOutcome,
    StepStatus,
    Strategy,
    StrategyStatus,
    create_step,
    create_strategy,
)
from agent_core.deliberation.strategy_templates import (
    TEMPLATE_REGISTRY,
    build_consolidate,
    build_explore_new,
    build_learn_topic,
    get_template,
    list_templates,
)
from agent_core.deliberation.intent_tracker import IntentRecord, IntentTracker
from agent_core.deliberation.deliberator import Deliberator
from agent_core.deliberation import Deliberation


# ===================== Strategy + Step =====================


class TestStep:
    def test_create_step(self):
        step = create_step(order=0, action_type="learn", description="Test")
        assert step.order == 0
        assert step.action_type == "learn"
        assert step.status == StepStatus.PENDING
        assert step.step_id.startswith("step-")

    def test_step_serialization(self):
        step = create_step(
            order=1,
            action_type="exam",
            description="Egzamin",
            action_params={"topics": ["math"]},
            max_retries=3,
            fallback_step_order=0,
        )
        d = step.to_dict()
        restored = Step.from_dict(d)
        assert restored.order == 1
        assert restored.action_type == "exam"
        assert restored.max_retries == 3
        assert restored.fallback_step_order == 0
        assert restored.action_params == {"topics": ["math"]}

    def test_step_default_values(self):
        step = create_step(order=0, action_type="learn")
        assert step.max_retries == 1
        assert step.retries_used == 0
        assert step.fallback_step_order is None
        assert step.result == {}


class TestStrategy:
    def test_create_strategy(self):
        steps = [
            create_step(order=0, action_type="learn"),
            create_step(order=1, action_type="exam"),
        ]
        s = create_strategy(
            goal_id="goal-1",
            template_name="test",
            steps=steps,
            intent="Test intent",
        )
        assert s.goal_id == "goal-1"
        assert s.strategy_id.startswith("strat-")
        assert len(s.steps) == 2
        assert s.status == StrategyStatus.ACTIVE
        assert s.created_at > 0

    def test_current_step(self):
        steps = [
            create_step(order=0, action_type="learn"),
            create_step(order=1, action_type="exam"),
        ]
        s = create_strategy(goal_id="g", template_name="t", steps=steps)
        assert s.current_step.action_type == "learn"
        s.current_step_order = 1
        assert s.current_step.action_type == "exam"
        s.current_step_order = 99
        assert s.current_step is None

    def test_is_terminal(self):
        s = create_strategy(goal_id="g", template_name="t", steps=[])
        assert not s.is_terminal
        s.status = StrategyStatus.COMPLETED
        assert s.is_terminal
        s.status = StrategyStatus.ABANDONED
        assert s.is_terminal

    def test_progress(self):
        steps = [
            create_step(order=0, action_type="learn"),
            create_step(order=1, action_type="exam"),
        ]
        s = create_strategy(goal_id="g", template_name="t", steps=steps)
        assert s.progress == 0.0
        steps[0].status = StepStatus.COMPLETED
        assert s.progress == 0.5
        steps[1].status = StepStatus.COMPLETED
        assert s.progress == 1.0

    def test_progress_empty(self):
        s = create_strategy(goal_id="g", template_name="t", steps=[])
        assert s.progress == 0.0

    def test_serialization_roundtrip(self):
        steps = [
            create_step(order=0, action_type="learn", description="Nauka"),
            create_step(order=1, action_type="exam", description="Egzamin"),
        ]
        s = create_strategy(
            goal_id="g-1",
            template_name="learn_topic",
            steps=steps,
            intent="Test",
            metadata={"topic": "fizyka"},
        )
        d = s.to_dict()
        restored = Strategy.from_dict(d)
        assert restored.strategy_id == s.strategy_id
        assert restored.goal_id == "g-1"
        assert len(restored.steps) == 2
        assert restored.metadata == {"topic": "fizyka"}
        assert restored.intent == "Test"


# ===================== Strategy Templates =====================


class TestStrategyTemplates:
    def test_registry_has_4_templates(self):
        assert len(TEMPLATE_REGISTRY) == 4
        assert set(TEMPLATE_REGISTRY.keys()) == {"learn_topic", "explore_new", "consolidate", "experiment"}

    def test_list_templates(self):
        names = list_templates()
        assert "learn_topic" in names
        assert "explore_new" in names
        assert "consolidate" in names

    def test_get_template(self):
        assert get_template("learn_topic") is build_learn_topic
        assert get_template("nonexistent") is None

    def test_build_learn_topic(self):
        s = build_learn_topic(goal_id="g-1", topic="fizyka")
        assert s.template_name == "learn_topic"
        assert len(s.steps) == 4
        assert s.steps[0].action_type == "learn"
        assert s.steps[1].action_type == "exam"
        assert s.steps[2].action_type == "review"
        assert s.steps[3].action_type == "exam"
        # First exam falls back to review (step 2)
        assert s.steps[1].fallback_step_order == 2
        # Second exam falls back to review (step 2)
        assert s.steps[3].fallback_step_order == 2
        assert s.metadata == {"topic": "fizyka"}

    def test_build_learn_topic_no_topic(self):
        s = build_learn_topic(goal_id="g-1")
        assert s.steps[0].description == "Nauka nowego materialu"
        assert s.metadata == {}

    def test_build_explore_new(self):
        s = build_explore_new(goal_id="g-2")
        assert s.template_name == "explore_new"
        assert len(s.steps) == 3
        assert s.steps[0].action_type == "fetch"
        assert s.steps[1].action_type == "learn"
        assert s.steps[2].action_type == "exam"
        assert s.steps[2].fallback_step_order == 1

    def test_build_consolidate(self):
        s = build_consolidate(goal_id="g-3", topic="chemia")
        assert s.template_name == "consolidate"
        assert len(s.steps) == 3
        assert s.steps[0].action_type == "review"
        assert s.steps[1].action_type == "exam"
        assert s.steps[2].action_type == "evaluate"
        assert s.steps[1].fallback_step_order == 0


# ===================== IntentTracker =====================


class TestIntentTracker:
    def test_record_and_query(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        rec = tracker.record(
            goal_id="g-1",
            strategy_id="s-1",
            template_name="learn_topic",
            reason="new_files_available",
        )
        assert rec.goal_id == "g-1"
        assert rec.outcome == "in_progress"

        results = tracker.query_by_goal("g-1")
        assert len(results) == 1
        assert results[0].strategy_id == "s-1"

    def test_update_outcome(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        tracker.record("g-1", "s-1", "learn_topic", "test")
        assert tracker.update_outcome("s-1", "completed")
        results = tracker.query_by_goal("g-1")
        assert results[0].outcome == "completed"

    def test_update_outcome_not_found(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        assert not tracker.update_outcome("nonexistent", "completed")

    def test_query_recent(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        for i in range(5):
            tracker.record(f"g-{i}", f"s-{i}", "learn_topic", "test")
        recent = tracker.query_recent(3)
        assert len(recent) == 3
        assert recent[-1].goal_id == "g-4"

    def test_count_failed_template(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        tracker.record("g-1", "s-1", "learn_topic", "test")
        tracker.update_outcome("s-1", "abandoned")
        tracker.record("g-1", "s-2", "learn_topic", "test")
        tracker.update_outcome("s-2", "abandoned")
        tracker.record("g-1", "s-3", "explore_new", "test")
        tracker.update_outcome("s-3", "abandoned")

        assert tracker.count_failed_template("g-1", "learn_topic") == 2
        assert tracker.count_failed_template("g-1", "explore_new") == 1

    def test_persistence(self, tmp_path):
        path = tmp_path / "intents.jsonl"
        tracker1 = IntentTracker(path=path)
        tracker1.record("g-1", "s-1", "learn_topic", "test")

        # New instance loads from file
        tracker2 = IntentTracker(path=path)
        results = tracker2.query_by_goal("g-1")
        assert len(results) == 1
        assert results[0].strategy_id == "s-1"

    def test_bounded_read(self, tmp_path):
        path = tmp_path / "intents.jsonl"
        # Write more than MAX_RECORDS
        with open(path, "w") as f:
            for i in range(600):
                rec = IntentRecord(
                    goal_id=f"g-{i}", strategy_id=f"s-{i}",
                    template_name="t", reason="r", timestamp=time.time(),
                )
                f.write(json.dumps(rec.to_dict()) + "\n")

        tracker = IntentTracker(path=path)
        assert len(tracker.query_recent(1000)) == 500  # bounded


class TestIntentRecord:
    def test_serialization(self):
        rec = IntentRecord(
            goal_id="g-1", strategy_id="s-1",
            template_name="learn_topic", reason="test",
            timestamp=1234.5, outcome="completed",
            metadata={"key": "val"},
        )
        d = rec.to_dict()
        restored = IntentRecord.from_dict(d)
        assert restored.goal_id == "g-1"
        assert restored.outcome == "completed"
        assert restored.metadata == {"key": "val"}


# ===================== Deliberator =====================


class TestDeliberator:
    def test_select_strategy_new_files(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)

        # new_files_available -> learn_topic (learn local files first)
        action = d.get_next_action("g-1", {
            "new_files_available": True,
            "intent": "Eksploracja",
        })
        assert action is not None
        assert action["action_type"] == "learn"  # learn_topic starts with learn
        assert "strategy_id" in action

    def test_select_strategy_explore_new_when_nothing_to_do(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)

        # No new files, no weak topics -> explore_new (fetch from web)
        action = d.get_next_action("g-1", {
            "new_files_available": False,
            "weak_topics": [],
            "intent": "Szukam nowych materialow",
            "goal_type": "META",
        })
        assert action is not None
        assert action["action_type"] == "fetch"  # explore_new starts with fetch
        assert "strategy_id" in action

    def test_select_strategy_weak_topics(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)

        # weak_topics with low confidence -> consolidate
        action = d.get_next_action("g-1", {
            "weak_topics": ["fizyka", "chemia"],
            "_knowledge_gaps": [
                {"topic": "fizyka", "confidence": 0.2},
                {"topic": "chemia", "confidence": 0.3},
            ],
            "intent": "Konsolidacja",
        })
        assert action is not None
        assert action["action_type"] == "review"  # consolidate starts with review

    def test_select_strategy_weak_topics_high_confidence_skipped(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)

        # weak_topics but with high confidence (>= 0.5) -> NOT consolidate
        action = d.get_next_action("g-1", {
            "weak_topics": ["fizyka", "chemia"],
            "_knowledge_gaps": [
                {"topic": "fizyka", "confidence": 0.7},
                {"topic": "chemia", "confidence": 0.8},
            ],
            "new_files_available": False,
            "intent": "Konsolidacja",
            "goal_type": "META",
        })
        assert action is not None
        assert action["action_type"] == "fetch"  # explore_new (nothing truly weak)

    def test_select_strategy_with_topic(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)

        action = d.get_next_action("g-1", {
            "topic": "biologia",
            "intent": "Nauka biologii",
        })
        assert action is not None
        assert action["action_type"] == "learn"  # learn_topic starts with learn

    def test_select_strategy_default_learning(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)

        action = d.get_next_action("g-1", {
            "goal_type": "LEARNING",
            "intent": "Nauka",
        })
        assert action is not None
        assert action["action_type"] == "learn"

    def test_no_strategy_matches(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)

        # Exhaust all templates for this goal (limit is 5 abandons per template)
        for name in ["learn_topic", "explore_new", "consolidate"]:
            for i in range(5):
                tracker.record(f"g-1", f"s-{name}-{i}", name, "test")
                tracker.update_outcome(f"s-{name}-{i}", "abandoned")

        action = d.get_next_action("g-1", {"goal_type": "LEARNING"})
        assert action is None

    def test_advance_on_success(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)

        # Start with explore_new: FETCH -> LEARN -> EXAM
        action1 = d.get_next_action("g-1", {"new_files_available": False, "weak_topics": [], "goal_type": "META"})
        assert action1["action_type"] == "fetch"
        strategy_id = action1["strategy_id"]

        # Report success
        status = d.report_step_outcome(strategy_id, "pass", {"success": True})
        assert status == "active"

        # Get next action (should be learn now)
        action2 = d.get_next_action("g-1", {})
        assert action2["action_type"] == "learn"
        assert action2["strategy_id"] == strategy_id

    def test_advance_to_completion(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)

        action = d.get_next_action("g-1", {"new_files_available": False, "weak_topics": [], "goal_type": "META"})
        sid = action["strategy_id"]

        # Complete all 3 steps
        d.report_step_outcome(sid, "pass")
        d.report_step_outcome(sid, "pass")
        status = d.report_step_outcome(sid, "pass")
        assert status == "completed"

        strategy = d.get_strategy(sid)
        assert strategy.status == StrategyStatus.COMPLETED

    def test_failure_with_retry(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)

        action = d.get_next_action("g-1", {"new_files_available": False, "weak_topics": [], "goal_type": "META"})
        sid = action["strategy_id"]

        # Fetch step has max_retries=2, first fail should retry
        status = d.report_step_outcome(sid, "fail")
        assert status == "active"

        # Same step should still be active
        strategy = d.get_strategy(sid)
        step = strategy.current_step
        assert step.action_type == "fetch"
        assert step.retries_used == 1

    def test_failure_with_fallback(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)

        # explore_new: FETCH -> LEARN -> EXAM (exam fallback_step_order=1)
        action = d.get_next_action("g-1", {"new_files_available": False, "weak_topics": [], "goal_type": "META"})
        sid = action["strategy_id"]

        # Pass fetch and learn
        d.report_step_outcome(sid, "pass")
        d.report_step_outcome(sid, "pass")

        # Fail exam -> should fallback to learn (step 1)
        status = d.report_step_outcome(sid, "fail")
        assert status == "active"

        strategy = d.get_strategy(sid)
        assert strategy.current_step_order == 1  # back to learn

    def test_failure_abandon(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)

        # learn_topic with topic
        action = d.get_next_action("g-1", {"topic": "math"})
        sid = action["strategy_id"]

        # learn step has max_retries=1, no fallback -> abandon
        status = d.report_step_outcome(sid, "fail")
        assert status == "abandoned"

    def test_abandon_strategy(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)

        action = d.get_next_action("g-1", {"topic": "test"})
        sid = action["strategy_id"]

        assert d.abandon_strategy(sid, "manual cancel")
        strategy = d.get_strategy(sid)
        assert strategy.status == StrategyStatus.ABANDONED

        # Can't abandon again
        assert not d.abandon_strategy(sid)

    def test_max_active_strategies(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)
        d.MAX_ACTIVE_STRATEGIES = 3

        for i in range(3):
            d.get_next_action(f"g-{i}", {"topic": f"topic-{i}"})

        # 4th should return None
        action = d.get_next_action("g-99", {"topic": "overflow"})
        assert action is None

    def test_get_status(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)

        d.get_next_action("g-1", {"topic": "test"})
        status = d.get_status()
        assert status["total_strategies"] == 1
        assert status["active_strategies"] == 1
        assert len(status["active_details"]) == 1
        assert "templates_available" in status

    def test_reuse_active_strategy(self, tmp_path):
        """If active strategy exists, get_next_action returns its current step."""
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)

        action1 = d.get_next_action("g-1", {"topic": "test"})
        sid = action1["strategy_id"]

        # Calling again should return same strategy's current step
        action2 = d.get_next_action("g-1", {"topic": "different"})
        assert action2["strategy_id"] == sid

    def test_report_unknown_strategy(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)
        assert d.report_step_outcome("nonexistent", "pass") is None

    def test_trim_goal_strategies(self, tmp_path):
        tracker = IntentTracker(path=tmp_path / "intents.jsonl")
        d = Deliberator(intent_tracker=tracker)
        d.MAX_STRATEGIES_PER_GOAL = 2

        # Create and abandon several strategies for same goal
        for i in range(4):
            action = d.get_next_action("g-1", {"topic": f"t-{i}"})
            if action:
                d.abandon_strategy(action["strategy_id"])

        # Should have at most 2 strategies for this goal
        assert len(d._goal_strategies.get("g-1", [])) <= 2


# ===================== Deliberation Facade =====================


class TestDeliberation:
    def test_facade_basic(self, tmp_path):
        delib = Deliberation(intent_path=tmp_path / "intents.jsonl")

        action = delib.get_next_action("g-1", {"topic": "test"})
        assert action is not None
        assert action["action_type"] == "learn"

        status = delib.report_step_outcome(action["strategy_id"], "pass")
        assert status == "active"

    def test_facade_get_active_strategy(self, tmp_path):
        delib = Deliberation(intent_path=tmp_path / "intents.jsonl")

        assert delib.get_active_strategy("g-1") is None
        delib.get_next_action("g-1", {"topic": "test"})
        s = delib.get_active_strategy("g-1")
        assert s is not None
        assert s.goal_id == "g-1"

    def test_facade_abandon(self, tmp_path):
        delib = Deliberation(intent_path=tmp_path / "intents.jsonl")
        action = delib.get_next_action("g-1", {"topic": "test"})
        assert delib.abandon_strategy(action["strategy_id"], "test")

    def test_facade_get_status(self, tmp_path):
        delib = Deliberation(intent_path=tmp_path / "intents.jsonl")
        status = delib.get_status()
        assert "total_strategies" in status
        assert "templates_available" in status


# ===================== PlannerCore Integration =====================


class TestPlannerDeliberationIntegration:
    """Test K8 wiring into PlannerCore."""

    def test_set_deliberation(self):
        from agent_core.planner.planner_core import PlannerCore
        planner = PlannerCore(
            state_path=Path("/tmp/test_state.json"),
            decisions_path=Path("/tmp/test_decisions.jsonl"),
        )
        delib = Deliberation(intent_path=Path("/tmp/test_intents.jsonl"))
        planner.set_deliberation(delib)
        assert planner._deliberation is delib

    def test_plan_metadata_field(self):
        from agent_core.planner.planner_model import create_plan, ActionType
        plan = create_plan(
            goal_id="g-1",
            goal_description="Test",
            action_type=ActionType.LEARN,
            metadata={"strategy_id": "strat-123", "step_order": 0},
        )
        assert plan.metadata["strategy_id"] == "strat-123"
        d = plan.to_dict()
        assert d["metadata"]["strategy_id"] == "strat-123"

    def test_plan_metadata_default_empty(self):
        from agent_core.planner.planner_model import create_plan, ActionType
        plan = create_plan(
            goal_id="g-1",
            goal_description="Test",
            action_type=ActionType.LEARN,
        )
        assert plan.metadata == {}

    def test_plan_metadata_serialization(self):
        from agent_core.planner.planner_model import Plan, ActionType, PlanStatus
        plan = Plan(
            plan_id="p-1", timestamp=1.0, goal_id="g-1",
            goal_description="Test", action_type=ActionType.LEARN,
            action_params={}, status=PlanStatus.PENDING,
            metadata={"strategy_id": "s-1"},
        )
        d = plan.to_dict()
        restored = Plan.from_dict(d)
        assert restored.metadata == {"strategy_id": "s-1"}


class TestSharedContextDeliberation:
    def test_deliberation_field(self):
        from agent_core.registry.shared_context import SharedContext
        ctx = SharedContext()
        assert ctx.deliberation is None
        ctx.deliberation = "test"
        assert ctx.deliberation == "test"
