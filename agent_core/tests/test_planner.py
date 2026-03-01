"""Tests for Planner (Warstwa 2, Kontrakt K5)."""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from agent_core.planner.planner_model import (
    Plan, PlanStatus, ActionType, PlannerState, create_plan,
)
from agent_core.planner.planner_guard import (
    PlannerGuard, MIN_HEALTH_SCORE, MIN_RETENTION_RATE,
)
from agent_core.planner.goal_selector import (
    GoalSelector, AGING_FACTOR_PER_HOUR, MAX_AGING,
)
from agent_core.planner.action_executor import ActionExecutor
from agent_core.planner.planner_core import (
    PlannerCore, ROUTINE_INTERVAL_TICKS, EVALUATION_INTERVAL_SEC,
    HIGH_PRIORITY_EVENTS,
)
from agent_core.perception.event import PerceptionSource, create_event


# ── Helpers ────────────────────────────────────────────


@dataclass
class MockGoal:
    """Minimal goal for testing (mimics agent_core.goals.goal_model.Goal)."""
    id: str
    type: "MockGoalType"
    description: str
    priority: float
    status: "MockGoalStatus"
    progress: float
    created_at: float
    created_by: str = "system"
    parent_goal_id: Optional[str] = None
    updated_at: float = 0.0
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.updated_at == 0.0:
            self.updated_at = self.created_at


@dataclass
class MockGoalType:
    value: str


@dataclass
class MockGoalStatus:
    value: str


def _make_goal(
    goal_id="goal-test",
    goal_type="learning",
    description="Test goal",
    priority=0.8,
    status="active",
    progress=0.0,
    created_at=None,
    metadata=None,
):
    return MockGoal(
        id=goal_id,
        type=MockGoalType(goal_type),
        description=description,
        priority=priority,
        status=MockGoalStatus(status),
        progress=progress,
        created_at=created_at or time.time(),
        metadata=metadata or {},
    )


def _make_mock_core(mode="active", health=0.9, idle=0):
    """Create a mock HomeostasisCore."""
    core = MagicMock()
    state = MagicMock()
    state.mode = MagicMock()
    state.mode.value = mode
    state.health_score = health
    state.idle_seconds = idle
    core.get_state.return_value = state
    core._teacher_thread = None
    core.push_external_event = MagicMock()
    return core


def _make_mock_observer(metrics=None, recommendations=None):
    """Create a mock EvaluationObserver."""
    observer = MagicMock()
    report = MagicMock()
    report.report_id = "eval-test"
    report.metrics = metrics or {
        "learning_velocity": 2.0,
        "retention_rate": 0.85,
        "knowledge_coverage": 0.5,
        "system_stability": 0.9,
        "personality_growth": 0.1,
    }
    report.recommendations = recommendations or []
    observer.generate_report.return_value = report
    observer.get_recent_reports.return_value = [report]
    return observer


def _make_mock_teacher(chunks=1, exams=0, strategies=1):
    """Create a mock TeacherAgent."""
    teacher = MagicMock()
    teacher.run_session.return_value = {
        "stats": {
            "chunks_learned": chunks,
            "exams_run": exams,
            "exams_passed": exams,
            "strategies_executed": strategies,
        }
    }
    return teacher


def _make_mock_goal_store(goals=None):
    """Create a mock GoalStore."""
    store = MagicMock()
    store.get_active.return_value = goals or []
    store.get.return_value = None
    store.save.return_value = None
    return store


# ═══════════════════════════════════════════════════════
# PlannerModel Tests
# ═══════════════════════════════════════════════════════


class TestPlanStatus:
    def test_all_statuses(self):
        assert len(PlanStatus) == 5
        values = {s.value for s in PlanStatus}
        assert values == {"pending", "executing", "completed", "failed", "skipped"}


class TestActionType:
    def test_all_types(self):
        assert len(ActionType) == 6
        values = {a.value for a in ActionType}
        assert values == {"learn", "exam", "review", "evaluate", "maintenance", "noop"}


class TestPlan:
    def test_create_plan(self):
        p = create_plan("goal-1", "Test goal", ActionType.LEARN)
        assert p.plan_id.startswith("plan-")
        assert p.goal_id == "goal-1"
        assert p.goal_description == "Test goal"
        assert p.action_type == ActionType.LEARN
        assert p.status == PlanStatus.PENDING
        assert p.timestamp > 0
        assert p.result == {}
        assert p.trace_id is None

    def test_create_plan_with_params(self):
        p = create_plan(
            "goal-2", "Eval", ActionType.EVALUATE,
            action_params={"period_hours": 2.0},
            trace_id="trace-abc",
        )
        assert p.action_params == {"period_hours": 2.0}
        assert p.trace_id == "trace-abc"

    def test_to_dict(self):
        p = create_plan("g1", "desc", ActionType.NOOP)
        d = p.to_dict()
        assert d["plan_id"] == p.plan_id
        assert d["goal_id"] == "g1"
        assert d["action_type"] == "noop"
        assert d["status"] == "pending"
        assert "timestamp" in d

    def test_from_dict(self):
        d = {
            "plan_id": "plan-test123",
            "timestamp": 1000.0,
            "goal_id": "g1",
            "goal_description": "Test",
            "action_type": "learn",
            "action_params": {},
            "status": "completed",
            "result": {"success": True},
            "trace_id": None,
            "duration_ms": 42.0,
        }
        p = Plan.from_dict(d)
        assert p.plan_id == "plan-test123"
        assert p.action_type == ActionType.LEARN
        assert p.status == PlanStatus.COMPLETED
        assert p.duration_ms == 42.0

    def test_roundtrip(self):
        original = create_plan("g1", "Round trip test", ActionType.EXAM)
        original.result = {"success": True, "exams_run": 1}
        original.duration_ms = 123.4
        d = original.to_dict()
        restored = Plan.from_dict(d)
        assert restored.plan_id == original.plan_id
        assert restored.goal_description == original.goal_description
        assert restored.action_type == original.action_type
        assert restored.result == original.result
        assert restored.duration_ms == original.duration_ms

    def test_create_plan_none_goal(self):
        p = create_plan(None, "No goal", ActionType.EVALUATE)
        assert p.goal_id is None


class TestPlannerState:
    def test_defaults(self):
        s = PlannerState()
        assert s.last_cycle_tick == 0
        assert s.total_cycles == 0
        assert s.total_plans_executed == 0
        assert s.current_plan_id is None

    def test_to_dict(self):
        s = PlannerState(total_cycles=5, total_plans_executed=3)
        d = s.to_dict()
        assert d["total_cycles"] == 5
        assert d["total_plans_executed"] == 3

    def test_from_dict(self):
        d = {"total_cycles": 10, "last_cycle_tick": 500}
        s = PlannerState.from_dict(d)
        assert s.total_cycles == 10
        assert s.last_cycle_tick == 500
        assert s.total_plans_executed == 0  # default

    def test_roundtrip(self):
        original = PlannerState(
            last_cycle_tick=100,
            total_cycles=50,
            total_plans_executed=25,
            current_plan_id="plan-abc",
        )
        d = original.to_dict()
        restored = PlannerState.from_dict(d)
        assert restored.last_cycle_tick == original.last_cycle_tick
        assert restored.total_cycles == original.total_cycles
        assert restored.current_plan_id == original.current_plan_id


# ═══════════════════════════════════════════════════════
# PlannerGuard Tests
# ═══════════════════════════════════════════════════════


class TestPlannerGuard:
    def setup_method(self):
        self.guard = PlannerGuard()

    def test_all_ok(self):
        can, reasons = self.guard.can_plan(0.9, "active", False, 0.8)
        assert can is True
        assert reasons == []

    def test_low_health(self):
        can, reasons = self.guard.can_plan(0.5, "active", False, 0.8)
        assert can is False
        assert any("health_score" in r for r in reasons)

    def test_health_exactly_threshold(self):
        can, reasons = self.guard.can_plan(MIN_HEALTH_SCORE, "active", False, 0.8)
        assert can is True  # >= threshold

    def test_health_just_below_threshold(self):
        can, reasons = self.guard.can_plan(MIN_HEALTH_SCORE - 0.01, "active", False, 0.8)
        assert can is False

    def test_not_active_mode(self):
        can, reasons = self.guard.can_plan(0.9, "reduced", False, 0.8)
        assert can is False
        assert any("mode" in r for r in reasons)

    def test_sleep_mode_blocked(self):
        can, reasons = self.guard.can_plan(0.9, "sleep", False, 0.8)
        assert can is False

    def test_survival_mode_blocked(self):
        can, reasons = self.guard.can_plan(0.9, "survival", False, 0.8)
        assert can is False

    def test_sandbox_active(self):
        can, reasons = self.guard.can_plan(0.9, "active", True, 0.8)
        assert can is False
        assert any("sandbox" in r for r in reasons)

    def test_low_retention(self):
        can, reasons = self.guard.can_plan(0.9, "active", False, 0.3)
        assert can is False
        assert any("retention" in r for r in reasons)

    def test_retention_none_ok(self):
        """None retention (no data) should not block."""
        can, reasons = self.guard.can_plan(0.9, "active", False, None)
        assert can is True

    def test_retention_exactly_threshold(self):
        can, reasons = self.guard.can_plan(0.9, "active", False, MIN_RETENTION_RATE)
        assert can is True  # >= threshold

    def test_teacher_running(self):
        can, reasons = self.guard.can_plan(0.9, "active", False, 0.8, is_teacher_running=True)
        assert can is False
        assert any("teacher" in r for r in reasons)

    def test_multiple_blocks(self):
        can, reasons = self.guard.can_plan(0.3, "reduced", True, 0.2, is_teacher_running=True)
        assert can is False
        assert len(reasons) >= 4


# ═══════════════════════════════════════════════════════
# GoalSelector Tests
# ═══════════════════════════════════════════════════════


class TestGoalSelector:
    def setup_method(self):
        self.selector = GoalSelector()
        self.now = time.time()

    def test_select_highest_priority(self):
        goals = [
            _make_goal(goal_id="g1", priority=0.5, created_at=self.now),
            _make_goal(goal_id="g2", priority=0.9, created_at=self.now),
            _make_goal(goal_id="g3", priority=0.3, created_at=self.now),
        ]
        selected = self.selector.select_goal(goals, {}, now=self.now)
        assert selected.id == "g2"

    def test_aging_factor(self):
        """Older low-priority goal should beat newer high-priority goal."""
        old_goal = _make_goal(
            goal_id="old", priority=0.3,
            created_at=self.now - 48 * 3600,  # 48h ago
        )
        new_goal = _make_goal(
            goal_id="new", priority=0.5,
            created_at=self.now,
        )
        selected = self.selector.select_goal([old_goal, new_goal], {}, now=self.now)
        # old: 0.3 * (1 + min(48*0.1, 4.0)) = 0.3 * 5.0 = 1.5
        # new: 0.5 * (1 + 0) = 0.5
        assert selected.id == "old"

    def test_aging_clamp(self):
        """Aging should be clamped to MAX_AGING."""
        goal = _make_goal(
            goal_id="ancient", priority=0.2,
            created_at=self.now - 1000 * 3600,  # 1000h ago
        )
        score = self.selector._compute_effective_priority(goal, self.now)
        # 0.2 * (1 + 4.0) = 1.0 (clamped at 4.0)
        assert score == pytest.approx(0.2 * (1.0 + MAX_AGING))

    def test_no_goals_returns_none(self):
        selected = self.selector.select_goal([], {})
        assert selected is None

    def test_meta_always_feasible(self):
        goal = _make_goal(goal_type="meta", created_at=self.now)
        selected = self.selector.select_goal([goal], {}, now=self.now)
        assert selected is not None

    def test_maintenance_always_feasible(self):
        goal = _make_goal(goal_type="maintenance", created_at=self.now)
        selected = self.selector.select_goal([goal], {}, now=self.now)
        assert selected is not None

    def test_user_always_feasible(self):
        goal = _make_goal(goal_type="user", created_at=self.now)
        selected = self.selector.select_goal([goal], {}, now=self.now)
        assert selected is not None

    def test_learning_infeasible_no_files(self):
        goal = _make_goal(goal_type="learning", created_at=self.now)
        snapshot = {
            "files_by_status": {},
            "new_files_available": [],
        }
        selected = self.selector.select_goal([goal], {}, knowledge_snapshot=snapshot, now=self.now)
        assert selected is None

    def test_learning_feasible_with_files(self):
        goal = _make_goal(goal_type="learning", created_at=self.now)
        snapshot = {
            "files_by_status": {"learning": ["file1.txt"]},
            "new_files_available": [],
        }
        selected = self.selector.select_goal([goal], {}, knowledge_snapshot=snapshot, now=self.now)
        assert selected is not None

    def test_learning_feasible_no_snapshot(self):
        """Without snapshot, learning goals are feasible (optimistic)."""
        goal = _make_goal(goal_type="learning", created_at=self.now)
        selected = self.selector.select_goal([goal], {}, now=self.now)
        assert selected is not None

    def test_rank_goals(self):
        goals = [
            _make_goal(goal_id="g1", priority=0.3, created_at=self.now),
            _make_goal(goal_id="g2", priority=0.9, created_at=self.now),
        ]
        ranked = self.selector.rank_goals(goals, {}, now=self.now)
        assert len(ranked) == 2
        assert ranked[0][1].id == "g2"  # Higher priority first


# ═══════════════════════════════════════════════════════
# ActionExecutor Tests
# ═══════════════════════════════════════════════════════


class TestActionExecutor:
    def setup_method(self):
        self.executor = ActionExecutor()

    def test_noop(self):
        plan = create_plan(None, "noop", ActionType.NOOP)
        result = self.executor.execute(plan)
        assert result["success"] is True
        assert "duration_ms" in result

    def test_learn_no_teacher(self):
        plan = create_plan("g1", "learn", ActionType.LEARN)
        result = self.executor.execute(plan)
        assert result["success"] is False
        assert "error" in result

    def test_learn_success(self):
        self.executor.set_teacher_agent(_make_mock_teacher(chunks=2))
        plan = create_plan("g1", "learn", ActionType.LEARN)
        result = self.executor.execute(plan)
        assert result["success"] is True
        assert result["chunks_learned"] == 2

    def test_learn_no_chunks(self):
        self.executor.set_teacher_agent(_make_mock_teacher(chunks=0))
        plan = create_plan("g1", "learn", ActionType.LEARN)
        result = self.executor.execute(plan)
        assert result["success"] is False

    def test_exam_success(self):
        teacher = _make_mock_teacher()
        teacher.run_session.return_value = {
            "stats": {"exams_run": 1, "exams_passed": 1, "chunks_learned": 0, "strategies_executed": 1}
        }
        self.executor.set_teacher_agent(teacher)
        plan = create_plan("g1", "exam", ActionType.EXAM)
        result = self.executor.execute(plan)
        assert result["success"] is True
        assert result["exams_run"] == 1

    def test_review_success(self):
        self.executor.set_teacher_agent(_make_mock_teacher(strategies=1))
        plan = create_plan("g1", "review", ActionType.REVIEW)
        result = self.executor.execute(plan)
        assert result["success"] is True

    def test_evaluate_success(self):
        self.executor.set_evaluation_observer(_make_mock_observer())
        plan = create_plan(None, "eval", ActionType.EVALUATE, action_params={"period_hours": 1.0})
        result = self.executor.execute(plan)
        assert result["success"] is True
        assert "metrics" in result

    def test_evaluate_no_observer(self):
        plan = create_plan(None, "eval", ActionType.EVALUATE)
        result = self.executor.execute(plan)
        assert result["success"] is False

    def test_maintenance_no_core(self):
        plan = create_plan("g1", "maint", ActionType.MAINTENANCE)
        result = self.executor.execute(plan)
        assert result["success"] is True
        assert result["action"] == "maintenance_noop"

    def test_maintenance_with_core(self):
        core = _make_mock_core(health=0.95)
        self.executor.set_homeostasis_core(core)
        plan = create_plan("g1", "maint", ActionType.MAINTENANCE)
        result = self.executor.execute(plan)
        assert result["success"] is True
        assert result["health_score"] == 0.95

    def test_maintenance_updates_goal_progress(self):
        core = _make_mock_core(health=0.85)
        self.executor.set_homeostasis_core(core)

        goal = _make_goal(
            goal_id="goal-maint",
            goal_type="maintenance",
            metadata={"metric": "health_score", "threshold": 0.7},
        )
        store = _make_mock_goal_store()
        store.get.return_value = goal
        self.executor.set_goal_store(store)

        plan = create_plan("goal-maint", "health", ActionType.MAINTENANCE)
        result = self.executor.execute(plan)
        assert result["success"] is True
        store.update_progress.assert_called_once()
        store.save.assert_called_once()

    def test_exception_handling(self):
        teacher = MagicMock()
        teacher.run_session.side_effect = RuntimeError("boom")
        self.executor.set_teacher_agent(teacher)
        plan = create_plan("g1", "learn", ActionType.LEARN)
        result = self.executor.execute(plan)
        assert result["success"] is False
        assert "boom" in result["error"]

    def test_duration_tracking(self):
        plan = create_plan(None, "noop", ActionType.NOOP)
        result = self.executor.execute(plan)
        assert "duration_ms" in result
        assert result["duration_ms"] >= 0


# ═══════════════════════════════════════════════════════
# PlannerCore Tests
# ═══════════════════════════════════════════════════════


@pytest.fixture
def planner_env(tmp_path):
    """Create planner with tmp paths for state/decisions."""
    planner = PlannerCore(
        state_path=tmp_path / "planner_state.json",
        decisions_path=tmp_path / "planner_decisions.jsonl",
    )
    return planner, tmp_path


class TestPlannerCoreShouldRun:
    def test_routine_interval(self, planner_env):
        planner, _ = planner_env
        planner._state.last_cycle_tick = 0
        assert planner.should_run(ROUTINE_INTERVAL_TICKS) is True

    def test_under_interval_no_run(self, planner_env):
        planner, _ = planner_env
        planner._state.last_cycle_tick = 0
        assert planner.should_run(30) is False

    def test_exact_interval(self, planner_env):
        planner, _ = planner_env
        planner._state.last_cycle_tick = 100
        assert planner.should_run(100 + ROUTINE_INTERVAL_TICKS) is True

    def test_high_priority_event_triggers(self, planner_env):
        planner, _ = planner_env
        from agent_core.perception.buffer import PerceptionBuffer

        buffer = PerceptionBuffer()
        planner.set_perception_buffer(buffer)
        planner._state.last_cycle_tick = 50

        # Push a high-priority event with recent timestamp
        event = create_event(
            source=PerceptionSource.EXAM,
            event_type="exam_result",
            payload={"score": 0.9},
            timestamp=time.time(),
        )
        buffer.push(event)

        assert planner.should_run(51) is True

    def test_no_buffer_routine_only(self, planner_env):
        planner, _ = planner_env
        planner._state.last_cycle_tick = 0
        assert planner.should_run(10) is False
        assert planner.should_run(60) is True


class TestPlannerCoreGuard:
    def test_guard_blocks_when_unhealthy(self, planner_env):
        planner, _ = planner_env
        core = _make_mock_core(health=0.3)
        planner.set_homeostasis_core(core)
        planner.set_goal_store(_make_mock_goal_store([
            _make_goal(goal_type="meta", priority=1.0)
        ]))

        result = planner.run_cycle(60)
        assert result is None  # Blocked by guard

    def test_guard_passes_when_healthy(self, planner_env):
        planner, _ = planner_env
        core = _make_mock_core(health=0.9)
        planner.set_homeostasis_core(core)
        planner.set_goal_store(_make_mock_goal_store([
            _make_goal(goal_type="maintenance", priority=1.0, metadata={"metric": "health_score", "threshold": 0.7})
        ]))

        # Should not crash, may return a plan
        result = planner.run_cycle(60)
        # Result depends on what executor does, but cycle should complete


class TestPlannerCoreGoalSelection:
    def test_no_goals_returns_none(self, planner_env):
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)
        planner.set_goal_store(_make_mock_goal_store([]))
        # Set recent evaluation so it doesn't trigger periodic eval
        planner._state.last_evaluation_ts = time.time()

        result = planner.run_cycle(60)
        assert result is None

    def test_maintenance_goal_produces_plan(self, planner_env):
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)
        planner._state.last_evaluation_ts = time.time()  # Prevent periodic eval

        goal = _make_goal(
            goal_type="maintenance", priority=1.0,
            metadata={"metric": "health_score", "threshold": 0.7}
        )
        planner.set_goal_store(_make_mock_goal_store([goal]))

        result = planner.run_cycle(60)
        assert result is not None
        assert result.action_type == ActionType.MAINTENANCE

    def test_learning_goal_with_teacher(self, planner_env):
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)
        planner.set_teacher_agent(_make_mock_teacher(chunks=1))
        planner._state.last_evaluation_ts = time.time()  # Prevent periodic eval

        goal = _make_goal(goal_type="meta", priority=1.0)
        planner.set_goal_store(_make_mock_goal_store([goal]))

        result = planner.run_cycle(60)
        assert result is not None
        assert result.action_type == ActionType.LEARN


class TestPlannerCoreLearningAction:
    def setup_method(self):
        self.core_fn = PlannerCore._decide_learning_action

    def test_partial_learning_continues(self):
        planner = PlannerCore.__new__(PlannerCore)
        snapshot = {"files_by_status": {"learning": ["f1.txt"]}}
        action = planner._decide_learning_action(snapshot, {})
        assert action == ActionType.LEARN

    def test_exam_ready_triggers_exam(self):
        planner = PlannerCore.__new__(PlannerCore)
        snapshot = {"files_by_status": {"learned": ["f1.txt"]}}
        action = planner._decide_learning_action(snapshot, {})
        assert action == ActionType.EXAM

    def test_new_files_trigger_learn(self):
        planner = PlannerCore.__new__(PlannerCore)
        snapshot = {
            "files_by_status": {},
            "new_files_available": ["f2.txt"],
        }
        action = planner._decide_learning_action(snapshot, {})
        assert action == ActionType.LEARN

    def test_low_retention_triggers_review(self):
        planner = PlannerCore.__new__(PlannerCore)
        snapshot = {"files_by_status": {}, "new_files_available": []}
        action = planner._decide_learning_action(snapshot, {"retention_rate": 0.6})
        assert action == ActionType.REVIEW

    def test_nothing_to_do_noop(self):
        planner = PlannerCore.__new__(PlannerCore)
        snapshot = {"files_by_status": {}, "new_files_available": []}
        action = planner._decide_learning_action(snapshot, {"retention_rate": 0.95})
        assert action == ActionType.NOOP

    def test_no_snapshot_defaults_to_learn(self):
        planner = PlannerCore.__new__(PlannerCore)
        action = planner._decide_learning_action(None, {})
        assert action == ActionType.LEARN


class TestPlannerCoreEvaluation:
    def test_periodic_evaluation_trigger(self, planner_env):
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)
        observer = _make_mock_observer()
        planner.set_evaluation_observer(observer)
        planner.set_goal_store(_make_mock_goal_store([]))

        # Force evaluation by setting last_evaluation_ts far in past
        planner._state.last_evaluation_ts = time.time() - EVALUATION_INTERVAL_SEC - 1

        result = planner.run_cycle(60)
        assert result is not None
        assert result.action_type == ActionType.EVALUATE

    def test_evaluation_not_triggered_if_recent(self, planner_env):
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)
        planner.set_goal_store(_make_mock_goal_store([]))

        # Set recent evaluation
        planner._state.last_evaluation_ts = time.time()

        result = planner.run_cycle(60)
        # Should return None (no goals, no eval needed)
        assert result is None


class TestPlannerCorePersistence:
    def test_state_save_load_roundtrip(self, planner_env):
        planner, tmp_path = planner_env
        planner._state.total_cycles = 42
        planner._state.total_plans_executed = 10
        planner._save_state()

        # Create new planner from same path
        planner2 = PlannerCore(
            state_path=tmp_path / "planner_state.json",
            decisions_path=tmp_path / "planner_decisions.jsonl",
        )
        assert planner2._state.total_cycles == 42
        assert planner2._state.total_plans_executed == 10

    def test_decisions_jsonl_append(self, planner_env):
        planner, tmp_path = planner_env
        p1 = create_plan("g1", "first", ActionType.LEARN)
        p1.status = PlanStatus.COMPLETED
        p1.result = {"success": True}
        planner._log_decision(p1)

        p2 = create_plan("g2", "second", ActionType.EXAM)
        p2.status = PlanStatus.FAILED
        p2.result = {"success": False}
        planner._log_decision(p2)

        history = planner.get_history(limit=10)
        assert len(history) == 2
        assert history[0]["goal_description"] == "first"
        assert history[1]["goal_description"] == "second"

    def test_missing_state_file_ok(self, tmp_path):
        planner = PlannerCore(
            state_path=tmp_path / "nonexistent.json",
            decisions_path=tmp_path / "nonexistent.jsonl",
        )
        assert planner._state.total_cycles == 0

    def test_corrupt_state_file_handled(self, tmp_path):
        state_path = tmp_path / "planner_state.json"
        state_path.write_text("CORRUPT JSON{{{")
        planner = PlannerCore(
            state_path=state_path,
            decisions_path=tmp_path / "decisions.jsonl",
        )
        assert planner._state.total_cycles == 0  # Default

    def test_empty_history(self, planner_env):
        planner, _ = planner_env
        history = planner.get_history()
        assert history == []


class TestPlannerCoreEventEmission:
    def test_emits_perception_event(self, planner_env):
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)

        goal = _make_goal(goal_type="maintenance", metadata={"metric": "health_score", "threshold": 0.7})
        planner.set_goal_store(_make_mock_goal_store([goal]))

        result = planner.run_cycle(60)
        assert result is not None
        core.push_external_event.assert_called_once()

        event = core.push_external_event.call_args[0][0]
        assert event.source == PerceptionSource.PLANNER
        assert event.event_type == "planner_decision"

    def test_no_core_no_crash(self, planner_env):
        planner, _ = planner_env
        plan = create_plan("g1", "test", ActionType.NOOP)
        plan.result = {"success": True}
        plan.status = PlanStatus.COMPLETED
        # Should not crash
        planner._emit_decision_event(plan)


class TestPlannerCoreStatus:
    def test_get_status(self, planner_env):
        planner, _ = planner_env
        planner._state.total_cycles = 100
        planner._state.total_plans_executed = 50
        status = planner.get_status()
        assert status["total_cycles"] == 100
        assert status["total_plans_executed"] == 50
        assert "last_cycle_tick" in status


# ═══════════════════════════════════════════════════════
# PlannerModule Tests
# ═══════════════════════════════════════════════════════


class TestPlannerModule:
    def test_init(self):
        from agent_core.modules.planner_module import PlannerModule
        module = PlannerModule()
        ctx = MagicMock()
        assert module.init(ctx) is True

    def test_get_commands(self):
        from agent_core.modules.planner_module import PlannerModule
        module = PlannerModule()
        commands = module.get_commands()
        assert len(commands) == 1
        assert commands[0].name == "/plan"

    def test_command_name(self):
        from agent_core.modules.planner_module import PlannerModule
        module = PlannerModule()
        assert module.name == "planner"


# ═══════════════════════════════════════════════════════
# PerceptionEvent PLANNER source Tests
# ═══════════════════════════════════════════════════════


class TestPerceptionSourcePlanner:
    def test_planner_source_exists(self):
        assert PerceptionSource.PLANNER.value == "planner"

    def test_planner_event_types_registered(self):
        from agent_core.perception.event import EVENT_TYPE_DEFAULTS
        assert "planner_decision" in EVENT_TYPE_DEFAULTS
        assert "planner_cycle_complete" in EVENT_TYPE_DEFAULTS

    def test_planner_decision_defaults(self):
        from agent_core.perception.event import EVENT_TYPE_DEFAULTS
        priority, ttl, dedup = EVENT_TYPE_DEFAULTS["planner_decision"]
        assert priority == 0.5
        assert ttl == 300.0
        assert dedup is False

    def test_create_planner_event(self):
        event = create_event(
            source=PerceptionSource.PLANNER,
            event_type="planner_decision",
            payload={"plan_id": "test"},
        )
        assert event.source == PerceptionSource.PLANNER
        assert event.event_type == "planner_decision"
        assert event.priority == 0.5
