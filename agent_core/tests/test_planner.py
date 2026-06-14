"""Tests for Planner (Warstwa 2, Kontrakt K5)."""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from agent_core.tests.spec_helpers import specced
from agent_core.homeostasis.core import HomeostasisCore
from agent_core.evaluation.observer import EvaluationObserver
from agent_core.teacher.teacher_agent import TeacherAgent
from agent_core.goals.store import GoalStore
from agent_core.bulletin.bulletin_store import BulletinStore
from agent_core.world_model import WorldModel
from agent_core.registry.shared_context import SharedContext
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
    HIGH_PRIORITY_EVENTS, NONPRODUCTIVE_REPEAT_THRESHOLD,
    GOAL_CYCLE_THRESHOLD, OFF_WINDOW_LEARN_BUDGET,
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
    core = specced(HomeostasisCore)
    state = MagicMock()
    state.mode = MagicMock()
    state.mode.value = mode
    state.health_score = health
    state.idle_seconds = idle
    core.get_state.return_value = state
    core._teacher_thread = None
    return core


def _make_mock_observer(metrics=None, recommendations=None):
    """Create a mock EvaluationObserver."""
    observer = specced(EvaluationObserver)
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
    teacher = specced(TeacherAgent)
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
    store = specced(GoalStore)
    store.get_active.return_value = goals or []
    store.get.return_value = None
    store.save.return_value = None
    return store


# ═══════════════════════════════════════════════════════
# PlannerModel Tests
# ═══════════════════════════════════════════════════════


class TestPlanStatus:
    def test_all_statuses(self):
        assert len(PlanStatus) == 6
        values = {s.value for s in PlanStatus}
        assert values == {"pending", "executing", "completed", "failed", "skipped", "awaiting_approval"}


class TestActionType:
    def test_all_types(self):
        assert len(ActionType) == 15
        values = {a.value for a in ActionType}
        assert values == {"learn", "exam", "review", "evaluate", "maintenance", "noop", "fetch", "experiment", "effector", "self_analyze", "creative", "ask_expert", "validate", "critique", "fs_write"}


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

    def test_belief_build_ts_roundtrip(self):
        """K6 belief build throttle field must survive persistence."""
        original = PlannerState(last_belief_build_ts=12345.6)
        restored = PlannerState.from_dict(original.to_dict())
        assert restored.last_belief_build_ts == 12345.6

    def test_belief_build_ts_default(self):
        """Default is 0.0 so the first EVALUATE always rebuilds."""
        s = PlannerState()
        assert s.last_belief_build_ts == 0.0


class TestBeliefRebuildThrottle:
    """Regression: EVALUATE must not trigger a belief rebuild every cycle.

    2026-04-17: The original code rebuilt after every EVALUATE success,
    which on a REDUCED-mode loop meant the builder ran once a minute.
    Each run enumerated ~22k concepts, cap=2000 pruned ~20k, and the
    next cycle recreated them (dedup misses pruned entries). CPU burn
    for zero progress. Throttle: hourly for EVALUATE, always for LEARN.
    """

    def _make_planner(self, tmp_path):
        return PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )

    def _make_plan(self, action_type):
        from agent_core.planner.planner_model import create_plan
        plan = create_plan(None, "test", action_type)
        plan.result = {"success": True}
        return plan

    def test_evaluate_rebuilds_once_then_throttles(self, tmp_path):
        planner = self._make_planner(tmp_path)
        wm = specced(WorldModel)
        wm.build.return_value = {"topics": 1, "files": 1, "concepts": 1}
        planner.set_world_model(wm)
        ok = {"success": True}

        # First EVALUATE: cooldown is 0, so rebuild fires.
        planner._maybe_rebuild_beliefs(self._make_plan(ActionType.EVALUATE), ok)
        assert wm.build.call_count == 1
        first_ts = planner._state.last_belief_build_ts
        assert first_ts > 0

        # Second EVALUATE moments later: throttle blocks rebuild.
        planner._maybe_rebuild_beliefs(self._make_plan(ActionType.EVALUATE), ok)
        assert wm.build.call_count == 1
        assert planner._state.last_belief_build_ts == first_ts

    def test_evaluate_rebuilds_again_after_cooldown(self, tmp_path):
        planner = self._make_planner(tmp_path)
        wm = specced(WorldModel)
        wm.build.return_value = {"topics": 1, "files": 1, "concepts": 1}
        planner.set_world_model(wm)

        # Fake first rebuild 2h ago so cooldown is already satisfied.
        planner._state.last_belief_build_ts = time.time() - 7200
        planner._maybe_rebuild_beliefs(
            self._make_plan(ActionType.EVALUATE), {"success": True}
        )
        assert wm.build.call_count == 1

    def test_learn_always_rebuilds_ignoring_cooldown(self, tmp_path):
        planner = self._make_planner(tmp_path)
        wm = specced(WorldModel)
        wm.build.return_value = {"topics": 1, "files": 0, "concepts": 5}
        planner.set_world_model(wm)

        # Recent build — well within cooldown.
        planner._state.last_belief_build_ts = time.time() - 60
        planner._maybe_rebuild_beliefs(
            self._make_plan(ActionType.LEARN), {"success": True}
        )
        assert wm.build.call_count == 1  # LEARN bypasses throttle

    def test_unsuccessful_plan_does_not_rebuild(self, tmp_path):
        planner = self._make_planner(tmp_path)
        wm = specced(WorldModel)
        planner.set_world_model(wm)

        planner._maybe_rebuild_beliefs(
            self._make_plan(ActionType.EVALUATE), {"success": False}
        )
        assert wm.build.call_count == 0

    def test_other_action_types_do_not_rebuild(self, tmp_path):
        """NOOP / EXAM / REVIEW etc. must not trigger a rebuild — only
        LEARN (always) and EVALUATE (throttled) are allowed paths."""
        planner = self._make_planner(tmp_path)
        wm = specced(WorldModel)
        planner.set_world_model(wm)

        for action in (ActionType.NOOP, ActionType.EXAM, ActionType.REVIEW,
                       ActionType.FETCH, ActionType.MAINTENANCE):
            planner._maybe_rebuild_beliefs(
                self._make_plan(action), {"success": True}
            )
        assert wm.build.call_count == 0


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
        can, reasons = self.guard.can_plan(0.3, "active", False, 0.8)
        assert can is False
        assert any("health_score" in r for r in reasons)

    def test_health_exactly_threshold(self):
        can, reasons = self.guard.can_plan(MIN_HEALTH_SCORE, "active", False, 0.8)
        assert can is True  # >= threshold

    def test_health_just_below_threshold(self):
        can, reasons = self.guard.can_plan(MIN_HEALTH_SCORE - 0.01, "active", False, 0.8)
        assert can is False

    def test_reduced_mode_allowed(self):
        """REDUCED allows lightweight planning (Phase 3: degradation routing)."""
        can, reasons = self.guard.can_plan(0.9, "reduced", False, 0.8)
        assert can is True

    def test_reduced_blocks_heavy_actions(self):
        """REDUCED blocks heavy LLM actions."""
        allowed, reason = PlannerGuard.is_heavy_action_allowed("reduced", 0.9)
        assert allowed is False
        assert "heavy" in reason.lower() or "reduced" in reason.lower()

    def test_active_allows_heavy_actions(self):
        """ACTIVE allows heavy LLM actions."""
        allowed, reason = PlannerGuard.is_heavy_action_allowed("active", 0.9)
        assert allowed is True

    def test_sleep_mode_allowed(self):
        """SLEEP allows autonomous learning/consolidation."""
        can, reasons = self.guard.can_plan(0.9, "sleep", False, 0.8)
        assert can is True

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

    def test_retention_zero_means_no_data(self):
        """retention_rate=0.0 means no exams taken, not bad retention."""
        can, reasons = self.guard.can_plan(0.9, "active", False, 0.0)
        assert can is True
        assert not any("retention" in r for r in reasons)

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

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_fetch_handoff_goal_preempts_older_meta_goal(self, _mock):
        old_meta = _make_goal(
            goal_id="meta",
            goal_type="meta",
            description="Autonomiczna nauka wiedzy",
            priority=1.0,
            created_at=self.now - 24 * 3600,
        )
        handoff = _make_goal(
            goal_id="handoff",
            goal_type="learning",
            priority=0.8,
            created_at=self.now,
            metadata={
                "source": "fetch_handoff",
                "file_ids": ["web_wiki_alpha.txt"],
            },
        )
        snapshot = {
            "files_by_status": {"new": [{"id": "web_wiki_alpha.txt"}]},
            "new_files_available": [{"id": "web_wiki_alpha.txt"}],
        }

        selected = self.selector.select_goal(
            [old_meta, handoff], {}, knowledge_snapshot=snapshot, now=self.now,
        )
        assert selected.id == "handoff"

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

    def test_learn_idle_session(self):
        """Truly idle session (no chunks, no exams, no strategies) -> failure."""
        self.executor.set_teacher_agent(_make_mock_teacher(chunks=0, strategies=0))
        plan = create_plan("g1", "learn", ActionType.LEARN)
        result = self.executor.execute(plan)
        assert result["success"] is False

    def test_learn_requires_new_chunks_strict(self):
        """Strict semantics: learn without new chunks is NOT success,
        even if teacher ran a review/exam strategy. Matches handlers.make_learn_handler
        (single source of truth via CapabilityRouter in production)."""
        self.executor.set_teacher_agent(_make_mock_teacher(chunks=0, exams=1, strategies=1))
        plan = create_plan("g1", "learn", ActionType.LEARN)
        result = self.executor.execute(plan)
        assert result["success"] is False
        assert result["chunks_learned"] == 0
        assert result["exams_run"] == 1  # stats still reported, just not counted as success

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
        teacher = specced(TeacherAgent)
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

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_fetch_fallback_binds_learn_handoff(self, _window, tmp_path):
        # P2: the no-router fallback path must bind the SAME durable learn-
        # handoff the CapabilityRouter path binds (ADR D1.5b single source of
        # truth) -- otherwise a fetch here orphans bytes with no obligation to
        # learn. errors > 0 in the mock also exercises P1 on this path: written
        # files bind even when the session hit an error elsewhere.
        from agent_core.goals.store import GoalStore
        from agent_core.goals.goal_model import GoalType

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "web_rss_fallback.txt").write_text(
            "# Tytul: test\n# ---\n\n" + ("material edukacyjny " * 30),
            encoding="utf-8",
        )
        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        analyzer = specced(
            KnowledgeAnalyzer,
            input_dir=input_dir,
            index_path=tmp_path / "memory" / "knowledge_index.jsonl",
        )
        self.executor.set_knowledge_analyzer(analyzer)

        goals_path = tmp_path / "meta_data" / "goals.jsonl"
        self.executor.set_goal_store(GoalStore(goals_path))

        with patch("agent_core.web_source.run_fetch_session") as mock_fetch:
            mock_fetch.return_value = {
                "articles_fetched": 1,
                "fetched_files": ["web_rss_fallback.txt"],
                "topics_searched": 2,
                "errors": 1,
            }
            plan = create_plan("g1", "fetch", ActionType.FETCH)
            result = self.executor._exec_fetch(plan)

        assert result["learn_handoff_files"] == ["web_rss_fallback.txt"]

        reloaded = GoalStore(goals_path)
        reloaded.load()
        handoffs = [
            g for g in reloaded.get_active(GoalType.LEARNING)
            if g.metadata.get("source") == "fetch_handoff"
        ]
        assert len(handoffs) == 1
        assert handoffs[0].metadata["file_ids"] == ["web_rss_fallback.txt"]


# ═══════════════════════════════════════════════════════
# PlannerCore Tests
# ═══════════════════════════════════════════════════════


@pytest.fixture
def planner_env(tmp_path, monkeypatch):
    """Create planner with tmp paths for state/decisions.

    Hermetic env: clear the toggle flags PlannerCore reads at __init__ so the
    construction defaults are deterministic (all OFF) regardless of os.environ.
    Without this, maria_core.sys.config's load_dotenv() (triggered by some other
    test's lazy import during a full-file run) pulls .env into the process --
    and once STRATEGIC_PLANNER_DRIVES=1 was armed in prod .env, fresh planners
    defaulted to True, so TestStrategicRuntimeControl failed in full-file runs
    but passed in isolation (order-dependent pollution)."""
    for _flag in ("STRATEGIC_PLANNER_DRIVES", "FS_WRITE_ENABLED", "HELDOUT_GRADER_ENABLED"):
        monkeypatch.delenv(_flag, raising=False)
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

    def test_tick_discontinuity_after_restart(self, planner_env):
        """After daemon restart, tick resets to 0 but state has old value."""
        planner, _ = planner_env
        planner._state.last_cycle_tick = 5000  # Old daemon tick
        # New daemon starts from tick 0 - ticks_since is negative
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


class TestStrategicWireA:
    """#9 Wire A: strategist blocked_goals filter (flag-gated, subtractive)."""

    @staticmethod
    def _attach_plan(planner, blocked_goals):
        from agent_core.planner.strategic_planner import StrategicPlanner
        from agent_core.planner.strategic_plan import StrategicPlan
        sp = StrategicPlanner()
        sp._current_plan = StrategicPlan(
            valid_until=time.time() + 600,
            blocked_goals=blocked_goals,
        )
        sp._last_plan_ts = time.time()
        planner._strategic_planner = sp

    def test_blocked_goal_dropped_when_driving(self, planner_env):
        planner, _ = planner_env
        planner._state.last_evaluation_ts = time.time()
        keep = _make_goal(goal_id="goal-keep", goal_type="meta", priority=1.0)
        block = _make_goal(goal_id="goal-block", goal_type="meta", priority=0.9)
        planner.set_goal_store(_make_mock_goal_store([keep, block]))
        self._attach_plan(planner, {"goal-block": "backed off, review first"})
        planner._strategic_drives = True

        ranked_ids = [g.id for g in planner._select_ranked_goals({})]
        assert "goal-keep" in ranked_ids
        assert "goal-block" not in ranked_ids
        # reason surfaced so a no_goals cycle can still explain itself (8a)
        assert any(
            r["goal_id"] == "goal-block" and "strategist_blocked" in r["reason"]
            for r in planner._last_skip_reasons
        )

    def test_blocked_goal_kept_when_flag_off(self, planner_env):
        planner, _ = planner_env
        planner._state.last_evaluation_ts = time.time()
        keep = _make_goal(goal_id="goal-keep", goal_type="meta", priority=1.0)
        block = _make_goal(goal_id="goal-block", goal_type="meta", priority=0.9)
        planner.set_goal_store(_make_mock_goal_store([keep, block]))
        self._attach_plan(planner, {"goal-block": "backed off"})
        planner._strategic_drives = False  # default -> wiring dormant

        ranked_ids = [g.id for g in planner._select_ranked_goals({})]
        assert "goal-block" in ranked_ids  # no effect when not driving

    def test_no_current_plan_is_noop(self, planner_env):
        planner, _ = planner_env
        planner._state.last_evaluation_ts = time.time()
        goal = _make_goal(goal_id="goal-x", goal_type="meta", priority=1.0)
        planner.set_goal_store(_make_mock_goal_store([goal]))
        # driving, but strategist has produced no plan yet
        planner._strategic_drives = True
        ranked_ids = [g.id for g in planner._select_ranked_goals({})]
        assert "goal-x" in ranked_ids


class TestStrategicWireB:
    """#9 Wire B: next_action focus + loop closure (flag-gated)."""

    @staticmethod
    def _attach(planner, actions, drives=True):
        from agent_core.planner.strategic_planner import StrategicPlanner
        from agent_core.planner.strategic_plan import StrategicPlan, PlannedAction
        sp = StrategicPlanner()
        sp._current_plan = StrategicPlan(
            valid_until=time.time() + 600,
            action_queue=[
                PlannedAction(action_type=a[0], goal_id=a[1]) for a in actions
            ],
        )
        sp._last_plan_ts = time.time()
        planner._strategic_planner = sp
        planner._strategic_drives = drives
        return sp

    def test_focus_brings_next_action_goal_to_front(self, planner_env):
        planner, _ = planner_env
        high = _make_goal(goal_id="goal-high", goal_type="meta", priority=1.0)
        low = _make_goal(goal_id="goal-low", goal_type="meta", priority=0.5)
        self._attach(planner, [("review", "goal-low")])
        focused = planner._apply_strategic_focus([high, low])
        assert [g.id for g in focused] == ["goal-low", "goal-high"]

    def test_focus_noop_when_flag_off(self, planner_env):
        planner, _ = planner_env
        high = _make_goal(goal_id="goal-high", goal_type="meta", priority=1.0)
        low = _make_goal(goal_id="goal-low", goal_type="meta", priority=0.5)
        self._attach(planner, [("review", "goal-low")], drives=False)
        focused = planner._apply_strategic_focus([high, low])
        assert [g.id for g in focused] == ["goal-high", "goal-low"]  # unchanged

    def test_focus_skips_infeasible_target_and_advances(self, planner_env):
        planner, _ = planner_env
        high = _make_goal(goal_id="goal-high", goal_type="meta", priority=1.0)
        sp = self._attach(
            planner, [("learn", "goal-gone"), ("review", "goal-high")]
        )
        focused = planner._apply_strategic_focus([high])
        # target infeasible -> order unchanged, but the dead action is skipped
        # so the plan advances to the next reachable action
        assert [g.id for g in focused] == ["goal-high"]
        assert sp.current_plan.next_action.goal_id == "goal-high"

    def test_record_outcome_completed_advances_plan(self, planner_env):
        planner, _ = planner_env
        goal = _make_goal(goal_id="goal-x", goal_type="meta", priority=1.0)
        sp = self._attach(planner, [("review", "goal-x"), ("exam", "goal-x")])
        assert sp.current_plan.next_action.action_type == "review"
        planner._record_strategic_outcome(goal, completed=True)
        assert sp.current_plan.next_action.action_type == "exam"

    def test_record_outcome_ignores_goal_mismatch(self, planner_env):
        planner, _ = planner_env
        other = _make_goal(goal_id="goal-other", goal_type="meta", priority=1.0)
        sp = self._attach(planner, [("review", "goal-x")])
        planner._record_strategic_outcome(other, completed=True)
        assert sp.current_plan.next_action.goal_id == "goal-x"
        assert sp.current_plan.next_action.completed is False

    def test_run_cycle_routes_through_focus_step(self, planner_env):
        """Integration: run_cycle actually invokes the Wire B focus step once
        (guards the call site against accidental removal)."""
        planner, _ = planner_env
        planner.set_homeostasis_core(_make_mock_core(health=0.9))
        goal = _make_goal(
            goal_type="maintenance", priority=1.0,
            metadata={"metric": "health_score", "threshold": 0.7},
        )
        planner.set_goal_store(_make_mock_goal_store([goal]))
        planner._state.last_evaluation_ts = time.time()  # prevent periodic eval
        seen = []
        orig = planner._apply_strategic_focus
        planner._apply_strategic_focus = lambda ranked: (
            seen.append(1) or orig(ranked)
        )
        result = planner.run_cycle(60)
        assert seen == [1]  # focus step ran exactly once
        assert result is not None
        assert result.action_type == ActionType.MAINTENANCE


class TestStrategicPlanMarkAction:
    """#9: StrategicPlan.mark_action marks by identity, not equality."""

    def test_mark_action_by_identity(self):
        from agent_core.planner.strategic_plan import StrategicPlan, PlannedAction
        a1 = PlannedAction(action_type="learn", goal_id="g1")
        a2 = PlannedAction(action_type="learn", goal_id="g1")  # equal fields
        plan = StrategicPlan(action_queue=[a1, a2])
        assert plan.mark_action(a2, completed=True) is True
        assert a2.completed is True
        assert a1.completed is False  # identity, not equality
        assert plan.mark_action(PlannedAction(action_type="x")) is False


class TestStrategicWireC:
    """#9 Wire C: idle_strategy biases the STEP 5 idle fallback (flag-gated)."""

    @staticmethod
    def _attach_idle(planner, idle_strategy, drives=True):
        from agent_core.planner.strategic_planner import StrategicPlanner
        from agent_core.planner.strategic_plan import StrategicPlan
        sp = StrategicPlanner()
        sp._current_plan = StrategicPlan(
            valid_until=time.time() + 600, idle_strategy=idle_strategy,
        )
        sp._last_plan_ts = time.time()
        planner._strategic_planner = sp
        planner._strategic_drives = drives

    @staticmethod
    def _stub_maybes(planner, creative_fires):
        sentinel = create_plan(
            goal_id=None, goal_description="creative",
            action_type=ActionType.CREATIVE,
        )
        order = []

        def none_for(name):
            def f(ctx):
                order.append(name)
                return None
            return f

        def creative(ctx):
            order.append("creative")
            return sentinel if creative_fires else None

        planner._maybe_evaluate = none_for("evaluate")
        planner._maybe_validate = none_for("validate")
        planner._maybe_critique = none_for("critique")
        planner._maybe_self_analyze = none_for("self_analyze")
        planner._maybe_experiment_scan = none_for("experiment")
        planner._maybe_creative = creative
        return sentinel, order

    def test_creative_idle_tries_creative_first(self, planner_env):
        planner, _ = planner_env
        self._attach_idle(planner, "creative")
        sentinel, order = self._stub_maybes(planner, creative_fires=True)
        assert planner._fallback_action({}) is sentinel
        assert order == ["creative"]  # ahead of the analytical cascade

    def test_wait_idle_skips_trailing_creative(self, planner_env):
        planner, _ = planner_env
        self._attach_idle(planner, "wait")
        _, order = self._stub_maybes(planner, creative_fires=True)
        assert planner._fallback_action({}) is None  # creative skipped
        assert "creative" not in order
        assert order == ["evaluate", "validate", "critique",
                         "self_analyze", "experiment"]

    def test_evaluate_idle_keeps_default_order(self, planner_env):
        planner, _ = planner_env
        self._attach_idle(planner, "evaluate")
        sentinel, order = self._stub_maybes(planner, creative_fires=True)
        assert planner._fallback_action({}) is sentinel
        assert order == ["evaluate", "validate", "critique",
                         "self_analyze", "experiment", "creative"]

    def test_flag_off_keeps_default_order(self, planner_env):
        planner, _ = planner_env
        self._attach_idle(planner, "wait", drives=False)  # would skip if driving
        sentinel, order = self._stub_maybes(planner, creative_fires=True)
        assert planner._fallback_action({}) is sentinel
        assert order[-1] == "creative"  # not driving -> idle_strategy ignored


class TestStrategicRuntimeControl:
    """#9: runtime toggle + status text behind the Telegram /strategic command."""

    def test_set_strategic_drives_runtime_toggle(self, planner_env):
        planner, _ = planner_env
        assert planner._strategic_drives is False  # env default
        planner.set_strategic_drives(True)
        assert planner._strategic_drives is True
        planner.set_strategic_drives(False)
        assert planner._strategic_drives is False

    def test_strategic_status_text_no_strategist(self, planner_env):
        planner, _ = planner_env
        txt = planner.strategic_status_text()
        assert "OFF" in txt
        assert "nie wired" in txt

    def test_strategic_status_text_with_plan(self, planner_env):
        from agent_core.planner.strategic_planner import StrategicPlanner
        from agent_core.planner.strategic_plan import StrategicPlan, PlannedAction
        planner, _ = planner_env
        sp = StrategicPlanner()
        sp._current_plan = StrategicPlan(
            valid_until=time.time() + 600,
            action_queue=[PlannedAction(action_type="review", goal_id="g1")],
            model_used="qwen3:8b",
        )
        planner._strategic_planner = sp
        planner.set_strategic_drives(True)
        txt = planner.strategic_status_text()
        assert "ON" in txt
        assert "qwen3:8b" in txt


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
        planner._world_model = None
        planner._expert_fn = None
        planner._knowledge_analyzer = None
        snapshot = {"files_by_status": {}, "new_files_available": []}
        action = planner._decide_learning_action(snapshot, {"retention_rate": 0.95})
        assert action == ActionType.NOOP

    def test_no_snapshot_defaults_to_learn(self):
        planner = PlannerCore.__new__(PlannerCore)
        planner._world_model = None
        planner._expert_fn = None
        planner._knowledge_analyzer = None
        action = planner._decide_learning_action(None, {})
        assert action == ActionType.LEARN


class TestAutonomousNeverEmitsEffector:
    """K7 reconciliation 2026-06-07 drift-guard.

    The autonomous planner must NEVER select ActionType.EFFECTOR. The only
    effector plans are created by _execute_approved_effector -- the operator
    path (/do -> /efapprove), which carries already_approved=True. This is the
    invariant that makes the resting authority level (OBSERVE) sufficient: if a
    future change wired autonomous effector emission, the effector would run
    under whatever level happens to be set. These assertions fail loudly on such
    a change, forcing a conscious authority decision before it ships.
    """

    def test_decide_learning_action_never_effector(self):
        planner = PlannerCore.__new__(PlannerCore)
        planner._world_model = None
        planner._expert_fn = None
        planner._knowledge_analyzer = None
        snapshots = [
            None,
            {"files_by_status": {"learning": ["f1.txt"]}},
            {"files_by_status": {"learned": ["f1.txt"]}},
            {"files_by_status": {"completed": ["f1.txt"]}},
            {"files_by_status": {}, "new_files_available": ["f2.txt"]},
            {"files_by_status": {}, "new_files_available": []},
        ]
        metrics_variants = [{}, {"retention_rate": 0.6}, {"retention_rate": 0.95}]
        for snap in snapshots:
            for metrics in metrics_variants:
                action = planner._decide_learning_action(snap, metrics)
                assert action != ActionType.EFFECTOR, (
                    f"autonomous learning decision emitted EFFECTOR for "
                    f"snapshot={snap}, metrics={metrics}"
                )

    def test_decide_non_learning_action_never_effector(self):
        planner = PlannerCore.__new__(PlannerCore)
        # Cover both the first-candidate branch (nothing rate-limited) and the
        # NOOP fallback (everything rate-limited) by stubbing the rate check.
        allowed = {
            ActionType.CREATIVE, ActionType.SELF_ANALYZE, ActionType.CRITIQUE,
            ActionType.EVALUATE, ActionType.VALIDATE, ActionType.NOOP,
        }
        for rate_limited in (False, True):
            planner._is_action_rate_limited = lambda name, _r=rate_limited: _r
            action = planner._decide_non_learning_action({})
            assert action != ActionType.EFFECTOR
            assert action in allowed


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


class TestNonProductiveLoopDetection:
    """Detects same (goal, reflection-action) repeated without progress.

    Regression: 628x evaluate:completed on mg-a0128 (2026-04-17/18) —
    stuck_history only tracked FAILED, so COMPLETED loops went unnoticed.
    """

    def _feed(self, planner, goal_id, action_type, count):
        """Invoke the non-productive tracker directly N times."""
        plan = create_plan(goal_id, "desc", action_type)
        plan.status = PlanStatus.COMPLETED
        for _ in range(count):
            planner._track_nonproductive_repeat(plan)

    def test_abandons_after_threshold(self, planner_env):
        planner, _ = planner_env
        goal = _make_goal(goal_id="g1")
        store = _make_mock_goal_store([goal])
        planner.set_goal_store(store)

        self._feed(planner, "g1", ActionType.EVALUATE,
                   NONPRODUCTIVE_REPEAT_THRESHOLD)

        store.update_status.assert_called_once()
        call = store.update_status.call_args
        assert call.args[0] == "g1"
        assert call.args[1].value == "abandoned"
        assert "non-productive loop" in call.kwargs["reason"]
        store.save.assert_called()
        # Counter resets after abandon
        assert planner._state.goal_action_repeat_count == 0

    def test_below_threshold_no_abandon(self, planner_env):
        planner, _ = planner_env
        store = _make_mock_goal_store([_make_goal(goal_id="g1")])
        planner.set_goal_store(store)

        self._feed(planner, "g1", ActionType.EVALUATE,
                   NONPRODUCTIVE_REPEAT_THRESHOLD - 1)

        store.update_status.assert_not_called()
        assert planner._state.goal_action_repeat_count == \
            NONPRODUCTIVE_REPEAT_THRESHOLD - 1

    def test_productive_action_not_tracked(self, planner_env):
        planner, _ = planner_env
        store = _make_mock_goal_store([_make_goal(goal_id="g1")])
        planner.set_goal_store(store)

        # LEARN repeated 100× should never abandon the goal
        self._feed(planner, "g1", ActionType.LEARN, 100)

        store.update_status.assert_not_called()
        assert planner._state.goal_action_repeat_count == 0

    def test_goal_change_resets_counter(self, planner_env):
        planner, _ = planner_env
        store = _make_mock_goal_store(
            [_make_goal(goal_id="g1"), _make_goal(goal_id="g2")]
        )
        planner.set_goal_store(store)

        self._feed(planner, "g1", ActionType.EVALUATE, 15)
        self._feed(planner, "g2", ActionType.EVALUATE, 15)

        store.update_status.assert_not_called()
        assert planner._state.goal_action_repeat_count == 15

    def test_action_change_resets_counter(self, planner_env):
        planner, _ = planner_env
        store = _make_mock_goal_store([_make_goal(goal_id="g1")])
        planner.set_goal_store(store)

        self._feed(planner, "g1", ActionType.EVALUATE, 15)
        self._feed(planner, "g1", ActionType.CRITIQUE, 4)

        store.update_status.assert_not_called()
        assert planner._state.goal_action_repeat_count == 4

    def test_no_goal_id_not_tracked(self, planner_env):
        planner, _ = planner_env
        store = _make_mock_goal_store([])
        planner.set_goal_store(store)

        plan = create_plan(None, "periodic", ActionType.EVALUATE)
        plan.status = PlanStatus.COMPLETED
        for _ in range(NONPRODUCTIVE_REPEAT_THRESHOLD + 5):
            planner._track_nonproductive_repeat(plan)

        store.update_status.assert_not_called()
        assert planner._state.goal_action_repeat_count == 0

    def test_missing_goal_store_no_crash(self, planner_env):
        planner, _ = planner_env
        # No goal_store set
        self._feed(planner, "g1", ActionType.EVALUATE,
                   NONPRODUCTIVE_REPEAT_THRESHOLD)
        # Just shouldn't crash; counter still resets past threshold in handler
        assert planner._state.last_goal_action_key is None


class TestGoalCycleDetection:
    """Detects mixed action cycles on one goal without measurable progress."""

    def _plan(self, goal_id="g1", action_type=ActionType.LEARN):
        plan = create_plan(goal_id, "Test goal", action_type)
        plan.status = PlanStatus.FAILED
        return plan

    def _wire_stores(self, planner, goals=None):
        goal_store = _make_mock_goal_store(goals or [_make_goal(goal_id="g1")])
        if goals:
            goal_store.get.side_effect = {
                goal.id: goal for goal in goals
            }.get
        else:
            goal_store.get.return_value = _make_goal(goal_id="g1")
        bulletin_store = specced(BulletinStore)
        planner.set_goal_store(goal_store)
        planner.set_bulletin_store(bulletin_store)
        return goal_store, bulletin_store

    def test_goal_cycle_escalates_after_threshold(self, planner_env):
        planner, _ = planner_env
        _, bulletin_store = self._wire_stores(planner)
        plan = self._plan()

        for _ in range(GOAL_CYCLE_THRESHOLD):
            planner._track_goal_cycle(plan, {"success": False})

        bulletin_store.post.assert_called_once()
        assert planner._state.actions_since_progress.get("g1", 0) == 0
        assert "g1" in planner._state.stuck_cooldowns
        entry = bulletin_store.post.call_args.args[0]
        assert entry.entry_type.value == "improvement"
        assert entry.priority == 0.85
        assert entry.metadata["category"] == "goal_exhausted_cycle"
        assert entry.metadata["actions_attempted"] == GOAL_CYCLE_THRESHOLD
        assert entry.metadata["threshold"] == GOAL_CYCLE_THRESHOLD
        assert entry.metadata["action_hint"] == "self_analyze"

    def test_goal_cycle_resets_on_progress(self, planner_env):
        planner, _ = planner_env
        _, bulletin_store = self._wire_stores(planner)
        plan = self._plan()

        for _ in range(GOAL_CYCLE_THRESHOLD - 1):
            planner._track_goal_cycle(plan, {"success": False})
        planner._track_goal_cycle(plan, {"success": True, "chunks_learned": 2})
        planner._track_goal_cycle(plan, {"success": False})

        bulletin_store.post.assert_not_called()
        assert planner._state.actions_since_progress["g1"] == 1

    def test_goal_cycle_independent_per_goal(self, planner_env):
        planner, _ = planner_env
        goals = [_make_goal(goal_id="g1"), _make_goal(goal_id="g2")]
        _, bulletin_store = self._wire_stores(planner, goals)
        plan_g1 = self._plan("g1")
        plan_g2 = self._plan("g2")

        for _ in range(GOAL_CYCLE_THRESHOLD - 1):
            planner._track_goal_cycle(plan_g1, {"success": False})
            planner._track_goal_cycle(plan_g2, {"success": False})
        planner._track_goal_cycle(plan_g2, {"success": False})

        bulletin_store.post.assert_called_once()
        assert planner._state.actions_since_progress["g1"] == \
            GOAL_CYCLE_THRESHOLD - 1
        assert planner._state.actions_since_progress.get("g2", 0) == 0
        assert bulletin_store.post.call_args.args[0].goal_id == "g2"

    def test_goal_cycle_skipped_does_not_progress(self, planner_env):
        planner, _ = planner_env
        _, bulletin_store = self._wire_stores(planner)
        plan = self._plan()

        for _ in range(GOAL_CYCLE_THRESHOLD):
            planner._track_goal_cycle(
                plan, {"success": False, "skipped": True},
            )

        bulletin_store.post.assert_called_once()
        assert planner._state.actions_since_progress.get("g1", 0) == 0

    def test_goal_cycle_empty_goal_id_noop(self, planner_env):
        planner, _ = planner_env
        _, bulletin_store = self._wire_stores(planner)
        plan = self._plan(goal_id=None, action_type=ActionType.EVALUATE)

        for _ in range(GOAL_CYCLE_THRESHOLD + 2):
            planner._track_goal_cycle(plan, {"success": False})

        bulletin_store.post.assert_not_called()
        assert planner._state.actions_since_progress == {}

    def test_goal_cycle_persists(self):
        state = PlannerState(actions_since_progress={"g1": 4, "g2": 1})

        restored = PlannerState.from_dict(state.to_dict())

        assert restored.actions_since_progress == {"g1": 4, "g2": 1}

    def test_plan_made_progress(self, planner_env):
        planner, _ = planner_env
        cases = [
            (ActionType.LEARN, {"success": True, "chunks_learned": 1}, True),
            (ActionType.LEARN, {"success": True, "chunks_learned": 0}, False),
            (ActionType.EXAM, {"success": True, "exams_passed": 1}, True),
            (ActionType.REVIEW, {"success": True, "reviews_done": 1}, True),
            (ActionType.FETCH, {"success": True}, True),
            (ActionType.FETCH, {"success": False}, False),
            (ActionType.FETCH, {"success": True, "skipped": True}, False),
        ]

        for action_type, result, expected in cases:
            plan = self._plan(action_type=action_type)
            assert planner._plan_made_progress(plan, result) is expected


class TestCreativeCooldown:
    """Planner-level cooldown on K13 creative reflection.

    Background 2026-04-18: two back-to-back reflections (3.3 min each) fired
    despite facade.should_reflect()'s 2h cooldown — origin of the second
    call unclear. This planner-level check guarantees at least the planner
    path respects 2h spacing regardless of upstream state.
    """

    def _setup(self, planner, last_ts):
        from agent_core.creative.facade import CreativeModule
        creative = specced(CreativeModule)
        creative.should_reflect.return_value = True
        planner._creative_module = creative
        planner._state.last_creative_ts = last_ts
        return creative

    def test_fires_when_cooldown_elapsed(self, planner_env):
        planner, _ = planner_env
        # last creative 3h ago (cooldown is 2h)
        creative = self._setup(planner, time.time() - 3 * 3600)

        plan = planner._maybe_creative({})

        assert plan is not None
        assert plan.action_type == ActionType.CREATIVE
        creative.should_reflect.assert_called_once()
        # last_creative_ts bumped to now (approx)
        assert abs(planner._state.last_creative_ts - time.time()) < 1

    def test_blocked_within_cooldown(self, planner_env):
        planner, _ = planner_env
        # last creative 30 min ago (cooldown 2h)
        last = time.time() - 30 * 60
        creative = self._setup(planner, last)

        plan = planner._maybe_creative({})

        assert plan is None
        creative.should_reflect.assert_not_called()
        # Timestamp not updated
        assert planner._state.last_creative_ts == last

    def test_respects_facade_should_reflect(self, planner_env):
        planner, _ = planner_env
        # Cooldown elapsed but facade says no
        creative = self._setup(planner, time.time() - 3 * 3600)
        creative.should_reflect.return_value = False

        plan = planner._maybe_creative({})

        assert plan is None
        creative.should_reflect.assert_called_once()

    def test_no_creative_module(self, planner_env):
        planner, _ = planner_env
        planner._creative_module = None

        plan = planner._maybe_creative({})

        assert plan is None


class TestStaleGoalCleanup:
    """Per-type stale threshold (learning=3d, meta=5d, user=14d, maintenance=30d).

    Background: K12/critic mass-produce LEARNING goals and K13/creative
    produces META goals. A 7d uniform threshold let ~90 stale goals accumulate.
    """

    def _make_real_goal(self, gid, gtype, status, age_days, progress=0.0,
                        metadata=None):
        from agent_core.goals.goal_model import Goal, GoalType, GoalStatus
        return Goal(
            id=gid,
            type=GoalType(gtype),
            description="test",
            priority=0.5,
            status=GoalStatus(status),
            progress=progress,
            parent_goal_id=None,
            created_by="test",
            created_at=time.time() - age_days * 86400,
            updated_at=time.time() - age_days * 86400,
            metadata=metadata or {},
        )

    def test_learning_goal_abandoned_after_3d(self, planner_env):
        planner, _ = planner_env
        g = self._make_real_goal("g1", "learning", "pending", age_days=3.5)
        store = _make_mock_goal_store([g])
        planner.set_goal_store(store)

        planner._cleanup_stale_goals()

        store.update_status.assert_called_once()
        assert store.update_status.call_args.args[0] == "g1"
        assert store.update_status.call_args.args[1].value == "abandoned"

    def test_learning_goal_kept_under_3d(self, planner_env):
        planner, _ = planner_env
        g = self._make_real_goal("g1", "learning", "pending", age_days=2.5)
        store = _make_mock_goal_store([g])
        planner.set_goal_store(store)

        planner._cleanup_stale_goals()

        store.update_status.assert_not_called()

    def test_meta_goal_threshold_is_5d(self, planner_env):
        planner, _ = planner_env
        # 4d: under meta threshold (5d), kept
        # 6d: over meta threshold, abandoned
        under = self._make_real_goal("m1", "meta", "pending", age_days=4)
        over = self._make_real_goal("m2", "meta", "pending", age_days=6)
        store = _make_mock_goal_store([under, over])
        planner.set_goal_store(store)

        planner._cleanup_stale_goals()

        assert store.update_status.call_count == 1
        assert store.update_status.call_args.args[0] == "m2"

    def test_user_goal_threshold_is_14d(self, planner_env):
        planner, _ = planner_env
        # User goals: conservative — don't abandon at 10d
        g = self._make_real_goal("u1", "user", "pending", age_days=10)
        store = _make_mock_goal_store([g])
        planner.set_goal_store(store)

        planner._cleanup_stale_goals()

        store.update_status.assert_not_called()

    def test_maintenance_goal_threshold_is_30d(self, planner_env):
        planner, _ = planner_env
        # Maintenance: system goals, very conservative
        g = self._make_real_goal("sys1", "maintenance", "pending", age_days=20)
        store = _make_mock_goal_store([g])
        planner.set_goal_store(store)

        planner._cleanup_stale_goals()

        store.update_status.assert_not_called()

    def test_recent_active_goal_spared(self, planner_env):
        """ACTIVE goals under the stuck threshold are spared (planner working)."""
        planner, _ = planner_env
        g = self._make_real_goal("g1", "learning", "active", age_days=5)
        store = _make_mock_goal_store([g])
        planner.set_goal_store(store)

        planner._cleanup_stale_goals()

        store.update_status.assert_not_called()

    def test_wedged_active_learning_abandoned(self, planner_env):
        """Plank 3: a zero-progress ACTIVE learning goal stuck past the 7d
        threshold is reaped -- the wedge Plank 1 introduced (ACTIVE goals
        escape the PENDING-only net and the cycle detector never terminates)."""
        planner, _ = planner_env
        g = self._make_real_goal("g1", "learning", "active", age_days=8)
        store = _make_mock_goal_store([g])
        planner.set_goal_store(store)

        planner._cleanup_stale_goals()

        store.update_status.assert_called_once()
        assert store.update_status.call_args.args[0] == "g1"
        assert store.update_status.call_args.args[1].value == "abandoned"
        assert (store.update_status.call_args.kwargs.get("actor")
                == "planner_active_stuck_cleanup")

    def test_fetch_handoff_pending_kept_past_learning_threshold(self, planner_env):
        """P3 (#4): a fetch_handoff goal points at real downloaded bytes, so it
        is NOT reaped at the 3d learning PENDING threshold -- the live handoff
        cleared the old 3d reaper by only 2.5h."""
        planner, _ = planner_env
        g = self._make_real_goal(
            "g1", "learning", "pending", age_days=5,
            metadata={"source": "fetch_handoff"},
        )
        store = _make_mock_goal_store([g])
        planner.set_goal_store(store)

        planner._cleanup_stale_goals()

        store.update_status.assert_not_called()

    def test_fetch_handoff_active_kept_past_stuck_threshold(self, planner_env):
        """P3 (#4): Plank 1 promotes handoffs to ACTIVE early, so the 30d window
        must cover the ACTIVE-stuck branch too -- a zero-progress ACTIVE handoff
        is NOT reaped at the 7d _ACTIVE_STUCK_SEC threshold."""
        planner, _ = planner_env
        g = self._make_real_goal(
            "g1", "learning", "active", age_days=10,
            metadata={"source": "fetch_handoff"},
        )
        store = _make_mock_goal_store([g])
        planner.set_goal_store(store)

        planner._cleanup_stale_goals()

        store.update_status.assert_not_called()

    def test_fetch_handoff_abandoned_past_30d(self, planner_env):
        """P3 (#4): the 30d window is a longer leash, not an exemption -- a
        handoff whose files genuinely can't be learned is still eventually
        reaped past 30d."""
        planner, _ = planner_env
        g = self._make_real_goal(
            "g1", "learning", "pending", age_days=31,
            metadata={"source": "fetch_handoff"},
        )
        store = _make_mock_goal_store([g])
        planner.set_goal_store(store)

        planner._cleanup_stale_goals()

        store.update_status.assert_called_once()
        assert store.update_status.call_args.args[0] == "g1"
        assert store.update_status.call_args.args[1].value == "abandoned"

    def test_active_goal_with_progress_spared(self, planner_env):
        """A progressing ACTIVE goal is never reaped, however long it's stuck
        (reactivation-in-spirit: don't trash goals that are still moving)."""
        planner, _ = planner_env
        g = self._make_real_goal(
            "g1", "learning", "active", age_days=60, progress=0.5,
        )
        store = _make_mock_goal_store([g])
        planner.set_goal_store(store)

        planner._cleanup_stale_goals()

        store.update_status.assert_not_called()

    def test_wedged_active_non_learning_spared(self, planner_env):
        """Plank 3 targets LEARNING only -- meta seeds / user goals keep
        their own lifecycle and are not reaped from ACTIVE."""
        planner, _ = planner_env
        g = self._make_real_goal("m1", "meta", "active", age_days=60)
        store = _make_mock_goal_store([g])
        planner.set_goal_store(store)

        planner._cleanup_stale_goals()

        store.update_status.assert_not_called()

    def test_goal_with_progress_not_abandoned(self, planner_env):
        """Even stale goals with any progress are kept."""
        planner, _ = planner_env
        g = self._make_real_goal(
            "g1", "learning", "pending", age_days=30, progress=0.1,
        )
        store = _make_mock_goal_store([g])
        planner.set_goal_store(store)

        planner._cleanup_stale_goals()

        store.update_status.assert_not_called()

    def test_bulk_cleanup_saves_once(self, planner_env):
        planner, _ = planner_env
        goals = [
            self._make_real_goal(f"g{i}", "learning", "pending", age_days=5)
            for i in range(10)
        ]
        store = _make_mock_goal_store(goals)
        planner.set_goal_store(store)

        planner._cleanup_stale_goals()

        assert store.update_status.call_count == 10
        store.save.assert_called_once()


class TestPlannerCoreEventEmission:
    def test_emits_perception_event(self, planner_env):
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)

        goal = _make_goal(goal_type="maintenance", metadata={"metric": "health_score", "threshold": 0.7})
        planner.set_goal_store(_make_mock_goal_store([goal]))

        result = planner.run_cycle(60)
        assert result is not None
        # 2 events: planner_decision + planner_cycle_complete
        assert core.push_external_event.call_count == 2

        calls = core.push_external_event.call_args_list
        decision_event = calls[0][0][0]
        assert decision_event.source == PerceptionSource.PLANNER
        assert decision_event.event_type == "planner_decision"

        cycle_event = calls[1][0][0]
        assert cycle_event.event_type == "planner_cycle_complete"

    def test_no_core_no_crash(self, planner_env):
        planner, _ = planner_env
        plan = create_plan("g1", "test", ActionType.NOOP)
        plan.result = {"success": True}
        plan.status = PlanStatus.COMPLETED
        # Should not crash
        planner._emit_decision_event(plan)


class TestPlannerCoreIdleReset:
    """Bug 5: Planner must call record_activity() after actions
    so Maria doesn't stay in SLEEP forever in daemon mode."""

    def test_record_activity_called_after_learning(self, planner_env):
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)
        planner._state.last_evaluation_ts = time.time()

        goal = _make_goal(goal_type="learning")
        planner.set_goal_store(_make_mock_goal_store([goal]))

        planner.run_cycle(60)
        core.record_activity.assert_called()

    def test_record_activity_called_after_maintenance(self, planner_env):
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)
        planner._state.last_evaluation_ts = time.time()

        goal = _make_goal(goal_type="maintenance",
                          metadata={"metric": "health_score", "threshold": 0.7})
        planner.set_goal_store(_make_mock_goal_store([goal]))

        planner.run_cycle(60)
        core.record_activity.assert_called()

    def test_record_activity_not_called_for_noop(self, planner_env):
        """NOOP should not reset idle - no real work was done."""
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)
        planner._state.last_evaluation_ts = time.time()

        # Force NOOP: goal with no files to learn and high retention
        observer = _make_mock_observer(metrics={
            "learning_velocity": 0, "retention_rate": 0.95,
            "knowledge_coverage": 1.0, "system_stability": 0.9,
            "personality_growth": 0.1,
        })
        planner.set_evaluation_observer(observer)

        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_knowledge_snapshot.return_value = {
            "files_by_status": {}, "new_files_available": [],
        }
        planner.set_knowledge_analyzer(analyzer)

        goal = _make_goal(goal_type="meta")
        planner.set_goal_store(_make_mock_goal_store([goal]))

        planner.run_cycle(60)
        core.record_activity.assert_not_called()

    def test_no_core_no_crash_on_activity(self, planner_env):
        """record_activity should not crash when no core is set."""
        planner, _ = planner_env
        # No core set - finalize should still work
        goal = _make_goal(goal_type="maintenance",
                          metadata={"metric": "health_score", "threshold": 0.7})
        planner.set_goal_store(_make_mock_goal_store([goal]))

        result = planner.run_cycle(60)
        assert result is not None


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
        ctx = specced(SharedContext)
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


# ===============================================================
# Observability Tests (format_message, rich payload, cycle_complete)
# ===============================================================


class TestFormatMessage:
    """Test _format_message() generates human-readable Polish messages."""

    def _make_planner(self, tmp_path):
        return PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )

    def test_learn_with_goal(self, tmp_path):
        planner = self._make_planner(tmp_path)
        plan = create_plan("g1", "Nauka fizyki", ActionType.LEARN)
        plan.result = {"success": True}
        msg = planner._format_message(plan)
        assert "Ucze sie" in msg
        assert "fizyki" in msg

    def test_learn_without_goal(self, tmp_path):
        planner = self._make_planner(tmp_path)
        plan = create_plan("g1", "", ActionType.LEARN)
        plan.result = {"success": True}
        msg = planner._format_message(plan)
        assert "Ucze sie" in msg

    def test_exam(self, tmp_path):
        planner = self._make_planner(tmp_path)
        plan = create_plan("g1", "Chemia organiczna", ActionType.EXAM)
        plan.result = {"success": True}
        msg = planner._format_message(plan)
        assert "Egzamin" in msg
        assert "Chemia" in msg

    def test_review_with_retention(self, tmp_path):
        planner = self._make_planner(tmp_path)
        plan = create_plan("g1", "Matematyka", ActionType.REVIEW,
                           action_params={"retention": 0.72})
        plan.result = {"success": True}
        msg = planner._format_message(plan)
        assert "Powtorka" in msg
        assert "72%" in msg

    def test_review_without_retention(self, tmp_path):
        planner = self._make_planner(tmp_path)
        plan = create_plan("g1", "Historia", ActionType.REVIEW)
        plan.result = {"success": True}
        msg = planner._format_message(plan)
        assert "Powtorka" in msg
        assert "Historia" in msg

    def test_evaluate(self, tmp_path):
        planner = self._make_planner(tmp_path)
        plan = create_plan(None, "Periodic evaluation", ActionType.EVALUATE)
        plan.result = {"success": True}
        msg = planner._format_message(plan)
        assert "Ewaluacja" in msg

    def test_maintenance(self, tmp_path):
        planner = self._make_planner(tmp_path)
        plan = create_plan("g1", "Health check", ActionType.MAINTENANCE,
                           action_params={"metric": "health_score"})
        plan.result = {"success": True}
        msg = planner._format_message(plan)
        assert "Konserwacja" in msg
        assert "health_score" in msg

    def test_noop(self, tmp_path):
        planner = self._make_planner(tmp_path)
        plan = create_plan("g1", "Idle", ActionType.NOOP)
        plan.result = {"success": True}
        msg = planner._format_message(plan)
        assert "czekam" in msg.lower()


class TestRichPayload:
    """Test that _emit_decision_event() has enriched payload with message."""

    def test_decision_event_has_message(self, planner_env):
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)
        planner._state.last_evaluation_ts = time.time()

        goal = _make_goal(goal_type="maintenance",
                          metadata={"metric": "health_score", "threshold": 0.7})
        planner.set_goal_store(_make_mock_goal_store([goal]))

        result = planner.run_cycle(60)
        assert result is not None

        # Find planner_decision event
        calls = core.push_external_event.call_args_list
        decision_events = [c[0][0] for c in calls
                           if c[0][0].event_type == "planner_decision"]
        assert len(decision_events) == 1

        payload = decision_events[0].payload
        assert "message" in payload
        assert len(payload["message"]) > 0
        assert "goal_description" in payload
        assert "duration_ms" in payload
        assert "result_details" in payload

    def test_plan_has_message_field(self, planner_env):
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)
        planner._state.last_evaluation_ts = time.time()

        goal = _make_goal(goal_type="learning", description="Nauka chemii")
        planner.set_goal_store(_make_mock_goal_store([goal]))

        result = planner.run_cycle(60)
        assert result is not None
        assert hasattr(result, "message")
        assert len(result.message) > 0

    def test_plan_to_dict_has_message(self, tmp_path):
        plan = create_plan("g1", "Test goal", ActionType.LEARN)
        plan.message = "Ucze sie: Test goal"
        d = plan.to_dict()
        assert d["message"] == "Ucze sie: Test goal"

    def test_plan_from_dict_preserves_message(self):
        d = {
            "plan_id": "plan-abc",
            "timestamp": time.time(),
            "goal_id": "g1",
            "goal_description": "Test",
            "action_type": "learn",
            "status": "completed",
            "message": "Ucze sie: Test",
        }
        plan = Plan.from_dict(d)
        assert plan.message == "Ucze sie: Test"


class TestCycleCompleteEvent:
    """Test that planner_cycle_complete event is emitted in all paths."""

    def test_cycle_complete_on_guard_block(self, planner_env):
        planner, _ = planner_env
        core = _make_mock_core(health=0.1)  # Low health blocks guard
        planner.set_homeostasis_core(core)

        result = planner.run_cycle(60)
        assert result is None

        calls = core.push_external_event.call_args_list
        cycle_events = [c[0][0] for c in calls
                        if c[0][0].event_type == "planner_cycle_complete"]
        assert len(cycle_events) == 1
        assert cycle_events[0].payload["guard_blocked"] is True
        assert "Planowanie wstrzymane" in cycle_events[0].payload["message"]

    def test_cycle_complete_on_no_goals(self, planner_env):
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)
        planner._state.last_evaluation_ts = time.time()  # Prevent periodic eval
        # No goal store = no goals
        planner._goal_store = None

        result = planner.run_cycle(60)
        assert result is None

        calls = core.push_external_event.call_args_list
        cycle_events = [c[0][0] for c in calls
                        if c[0][0].event_type == "planner_cycle_complete"]
        assert len(cycle_events) == 1
        assert cycle_events[0].payload["no_goals"] is True
        assert "Brak" in cycle_events[0].payload["message"]

    def test_cycle_complete_on_successful_plan(self, planner_env):
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)
        planner._state.last_evaluation_ts = time.time()

        goal = _make_goal(goal_type="learning")
        planner.set_goal_store(_make_mock_goal_store([goal]))

        result = planner.run_cycle(60)
        assert result is not None

        calls = core.push_external_event.call_args_list
        cycle_events = [c[0][0] for c in calls
                        if c[0][0].event_type == "planner_cycle_complete"]
        assert len(cycle_events) == 1
        assert cycle_events[0].payload["guard_blocked"] is False
        assert cycle_events[0].payload["no_goals"] is False
        assert "plan_id" in cycle_events[0].payload


# ══════════════════════════════════════════════════════
# Topic-Aware Learning - ActionExecutor
# ══════════════════════════════════════════════════════


class TestActionExecutorTopics:
    """Tests for topic resolution in ActionExecutor."""

    def test_exec_learn_with_topics_resolves_file_ids(self):
        """ActionExecutor resolves topics to file_ids via analyzer."""
        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        executor = ActionExecutor()
        teacher = _make_mock_teacher(chunks=1)
        executor.set_teacher_agent(teacher)

        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_files_for_topics.return_value = [
            ("fizyka.txt", 3.0), ("fizyka2.txt", 2.0),
        ]
        executor.set_knowledge_analyzer(analyzer)

        plan = create_plan(
            "goal-1", "Nauka fizyki", ActionType.LEARN,
            action_params={"topics": ["fizyka"]},
        )
        result = executor.execute(plan)

        # Check that teacher was called with filter
        teacher.run_session.assert_called_once()
        call_kwargs = teacher.run_session.call_args
        assert call_kwargs[1]["filter_file_ids"] == ["fizyka.txt", "fizyka2.txt"]

        # Check resolution report was stored in plan
        assert "resolved_file_ids" in plan.action_params
        assert "resolution_report" in plan.action_params
        assert plan.action_params["resolution_report"]["matches"] == 2

    def test_exec_learn_with_topics_zero_matches(self):
        """ActionExecutor with topics but 0 matching files."""
        executor = ActionExecutor()
        teacher = _make_mock_teacher(chunks=0, strategies=0)
        executor.set_teacher_agent(teacher)

        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_files_for_topics.return_value = []
        executor.set_knowledge_analyzer(analyzer)

        plan = create_plan(
            "goal-1", "Nauka fizyki", ActionType.LEARN,
            action_params={"topics": ["nonexistent"]},
        )
        result = executor.execute(plan)

        # Teacher called with None (empty -> None)
        call_kwargs = teacher.run_session.call_args
        assert call_kwargs[1]["filter_file_ids"] is None

    def test_exec_learn_without_topics_backward_compatible(self):
        """Without topics, Teacher called without filter."""
        executor = ActionExecutor()
        teacher = _make_mock_teacher(chunks=1)
        executor.set_teacher_agent(teacher)

        plan = create_plan("goal-1", "Test", ActionType.LEARN)
        executor.execute(plan)

        call_kwargs = teacher.run_session.call_args
        assert call_kwargs[1]["filter_file_ids"] is None


# ══════════════════════════════════════════════════════
# Topic-Aware Learning - PlannerCore
# ══════════════════════════════════════════════════════


class TestPlannerTopics:
    """Tests for topic awareness in PlannerCore."""

    def test_create_plan_with_topic_metadata(self, tmp_path):
        """LEARNING goal with topics -> plan.action_params has topics."""
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )

        goal = _make_goal(
            goal_type="learning",
            description="Nauka fizyki",
            metadata={"topics": ["fizyka"]},
        )

        context = {
            "knowledge_snapshot": {
                "files_by_status": {"new": [{"id": "fizyka.txt"}]},
                "new_files_available": [{"id": "fizyka.txt"}],
            },
            "evaluation_metrics": {},
        }

        plan = planner._create_plan_for_goal(goal, context)
        assert plan.action_params.get("topics") == ["fizyka"]

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_fetch_handoff_scope_forces_learn_over_exam(self, _mock, tmp_path):
        """Explicit fetch handoff files should beat generic exam/review."""
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )

        goal = _make_goal(
            goal_type="learning",
            description="Naucz sie pobranych materialow",
            metadata={
                "source": "fetch_handoff",
                "file_ids": ["web_wiki_alpha.txt", "web_wiki_beta.txt"],
            },
        )

        context = {
            "knowledge_snapshot": {
                "files_by_status": {
                    "learned": [{"id": "ready_for_exam.txt"}],
                    "new": [{"id": "web_wiki_alpha.txt"}],
                },
                "new_files_available": [{"id": "web_wiki_alpha.txt"}],
            },
            "evaluation_metrics": {},
        }

        plan = planner._create_plan_for_goal(goal, context)
        assert plan.action_type == ActionType.LEARN
        assert plan.action_params["resolved_file_ids"] == [
            "web_wiki_alpha.txt", "web_wiki_beta.txt",
        ]

    def test_create_plan_without_topics(self, tmp_path):
        """META goal without topics -> empty action_params."""
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )

        goal = _make_goal(goal_type="meta", description="Meta")

        context = {
            "knowledge_snapshot": {
                "files_by_status": {"new": [{"id": "file.txt"}]},
                "new_files_available": [{"id": "file.txt"}],
            },
            "evaluation_metrics": {},
        }

        plan = planner._create_plan_for_goal(goal, context)
        assert plan.action_params.get("topics") is None

    def test_auto_create_learning_goal(self, tmp_path):
        """Planner auto-creates LEARNING goal with best topic."""
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )

        # Wire mock dependencies
        core = _make_mock_core(mode="active")
        planner.set_homeostasis_core(core)

        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        mock_analyzer = specced(KnowledgeAnalyzer)
        mock_analyzer.get_topic_file_map.return_value = {
            "fizyka": ["fizyka1.txt", "fizyka2.txt"],
            "logika": ["logika1.txt"],
        }
        planner._knowledge_analyzer = mock_analyzer

        # GoalStore that stores created goals
        created_goals = []
        goal_store = specced(GoalStore)
        goal_store.get_active.return_value = []  # No existing learning goals
        goal_store.create.side_effect = lambda g: created_goals.append(g)
        planner._goal_store = goal_store

        context = {
            "knowledge_snapshot": {
                "files_by_status": {"new": [{"id": "fizyka1.txt"}]},
                "new_files_available": [{"id": "fizyka1.txt"}],
                "learning_in_progress": [],
            },
            "evaluation_metrics": {"retention_rate": 0.85},
        }

        result = planner._auto_create_learning_goal(context)
        assert result is True
        assert len(created_goals) == 1
        assert created_goals[0].metadata["topics"] == ["fizyka"]
        assert created_goals[0].metadata["source"] == "auto"

    def test_auto_create_skips_when_learning_goals_exist(self, tmp_path):
        """Don't create auto-goal if LEARNING goals already active."""
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )

        existing = _make_goal(goal_type="learning")
        existing2 = _make_goal(goal_type="learning", goal_id="g2")
        existing3 = _make_goal(goal_type="learning", goal_id="g3")

        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        goal_store = specced(GoalStore)
        goal_store.get_active.return_value = [existing, existing2, existing3]
        planner._goal_store = goal_store
        planner._knowledge_analyzer = specced(KnowledgeAnalyzer)

        context = {
            "knowledge_snapshot": {
                "files_by_status": {"new": [{"id": "f.txt"}]},
                "new_files_available": [{"id": "f.txt"}],
                "learning_in_progress": [],
            },
            "evaluation_metrics": {},
        }

        assert planner._auto_create_learning_goal(context) is False

    def test_auto_create_skips_low_retention(self, tmp_path):
        """Don't create new topics when retention is low."""
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        core = _make_mock_core(mode="active")
        planner.set_homeostasis_core(core)

        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        goal_store = specced(GoalStore)
        goal_store.get_active.return_value = []
        planner._goal_store = goal_store
        planner._knowledge_analyzer = specced(KnowledgeAnalyzer)

        context = {
            "knowledge_snapshot": {
                "files_by_status": {"new": [{"id": "f.txt"}]},
                "new_files_available": [{"id": "f.txt"}],
                "learning_in_progress": [],
            },
            "evaluation_metrics": {"retention_rate": 0.4},
        }

        assert planner._auto_create_learning_goal(context) is False


class TestOrphanFetchSweep:
    """P4 (#4): bind unlearned fetched files that reached the index with no
    handoff goal (the live web_rss_* leak), tightly scoped to avoid sweeping
    re-study seeds the operator let decay."""

    def _make_planner(self, tmp_path):
        from agent_core.goals.store import GoalStore
        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        analyzer = specced(
            KnowledgeAnalyzer,
            input_dir=input_dir,
            index_path=tmp_path / "memory" / "knowledge_index.jsonl",
        )
        planner.set_knowledge_analyzer(analyzer)
        planner.set_goal_store(GoalStore(tmp_path / "meta_data" / "goals.jsonl"))
        return planner

    def _handoffs(self, tmp_path):
        from agent_core.goals.store import GoalStore
        from agent_core.goals.goal_model import GoalType
        store = GoalStore(tmp_path / "meta_data" / "goals.jsonl")
        store.load()
        return [
            g for g in store.get_active(GoalType.LEARNING)
            if g.metadata.get("source") == "fetch_handoff"
        ]

    def test_sweep_binds_orphans_excludes_restudy_and_examined(self, tmp_path):
        planner = self._make_planner(tmp_path)
        context = {"knowledge_snapshot": {"files_by_status": {"new": [
            {"id": "web_rss_orphan.txt", "exam_attempts": 0},     # SWEEP
            {"id": "codex_orphan.txt", "exam_attempts": 0},       # SWEEP
            {"id": "expert_fizyka.txt", "exam_attempts": 14},     # SKIP: re-study seed
            {"id": "web_wiki_examined.txt", "exam_attempts": 3},  # SKIP: already examined
            {"id": "manual_notes.txt", "exam_attempts": 0},       # SKIP: not fetched
        ]}}}

        planner._sweep_orphan_fetches(context)

        handoffs = self._handoffs(tmp_path)
        assert len(handoffs) == 1
        assert handoffs[0].metadata.get("backfill") is True
        assert set(handoffs[0].metadata["file_ids"]) == {
            "web_rss_orphan.txt", "codex_orphan.txt",
        }

    def test_sweep_noop_when_no_orphans(self, tmp_path):
        planner = self._make_planner(tmp_path)
        context = {"knowledge_snapshot": {"files_by_status": {"new": [
            {"id": "expert_fizyka.txt", "exam_attempts": 14},
        ]}}}

        planner._sweep_orphan_fetches(context)

        assert self._handoffs(tmp_path) == []

    def test_sweep_skips_already_bound_files(self, tmp_path):
        from agent_core.goals.goal_model import (
            GoalType, GoalStatus, create_goal,
        )
        planner = self._make_planner(tmp_path)
        existing = create_goal(
            goal_type=GoalType.LEARNING,
            description="Naucz sie pobranych materialow",
            priority=1.0,
            status=GoalStatus.PENDING,
            metadata={
                "source": "fetch_handoff",
                "file_ids": ["web_rss_orphan.txt"],
            },
        )
        planner._goal_store.create(existing)
        planner._goal_store.save()

        context = {"knowledge_snapshot": {"files_by_status": {"new": [
            {"id": "web_rss_orphan.txt", "exam_attempts": 0},  # already obligated
        ]}}}

        planner._sweep_orphan_fetches(context)

        handoffs = self._handoffs(tmp_path)
        assert len(handoffs) == 1  # no duplicate goal created
        assert handoffs[0].id == existing.id


# ══════════════════════════════════════════════════════
# Topic-Aware Learning - REPL commands
# ══════════════════════════════════════════════════════


class TestPlannerModuleTopics:
    """Tests for /plan learn and /plan topics commands."""

    def test_cmd_learn_topic_creates_goal(self):
        """'/plan learn fizyka' creates a LEARNING goal with topic."""
        from agent_core.modules.planner_module import PlannerModule
        from agent_core.registry.shared_context import SharedContext
        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        from agent_core.planner.planner_core import PlannerCore

        module = PlannerModule()

        # Mock context
        ctx = specced(SharedContext)
        created_goals = []
        ctx.goal_store = specced(GoalStore)
        ctx.goal_store.create.side_effect = lambda g: created_goals.append(g)

        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_files_for_topics.return_value = [("fizyka.txt", 3.0)]
        ctx.knowledge_analyzer = analyzer
        ctx.planner_core = specced(PlannerCore)

        module.ctx = ctx
        module._cmd_learn_topic("fizyka")

        assert len(created_goals) == 1
        assert created_goals[0].type.value == "learning"
        assert created_goals[0].metadata["topics"] == ["fizyka"]
        assert created_goals[0].metadata["source"] == "user"
        assert created_goals[0].priority == 0.9

    def test_cmd_topics_shows_topics(self, capsys):
        """'/plan topics' prints available topics."""
        from agent_core.modules.planner_module import PlannerModule

        module = PlannerModule()

        from agent_core.registry.shared_context import SharedContext
        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        ctx = specced(SharedContext)
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_topic_file_map.return_value = {
            "fizyka": ["f1.txt", "f2.txt"],
            "logika": ["l1.txt"],
        }
        ctx.knowledge_analyzer = analyzer

        module.ctx = ctx
        module._cmd_topics()

        output = capsys.readouterr().out
        assert "fizyka" in output
        assert "logika" in output
        assert "2 plikow" in output


# ═══════════════════════════════════════════════════════
# Rate Limit Pre-Check Tests
# ═══════════════════════════════════════════════════════


class TestRateLimitPreCheck:
    """Test that planner skips rate-limited actions instead of spamming K7."""

    def test_is_action_rate_limited_no_policy(self, tmp_path):
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        assert planner._is_action_rate_limited("fetch") is False

    def test_is_action_rate_limited_allowed(self, tmp_path):
        from agent_core.autonomy import AutonomyPolicy
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        planner.set_autonomy_policy(AutonomyPolicy())
        assert planner._is_action_rate_limited("fetch") is False

    def test_is_action_rate_limited_blocked(self, tmp_path):
        from agent_core.autonomy import AutonomyPolicy
        from agent_core.autonomy.rate_limiter import ActionRateLimiter
        # Fill up rate limit (1 allowed, 1 recorded -> blocked)
        limiter = ActionRateLimiter(limits={"fetch": 1})
        limiter.record("fetch")
        policy = AutonomyPolicy(rate_limiter=limiter)
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        planner.set_autonomy_policy(policy)
        assert planner._is_action_rate_limited("fetch") is True

    def test_decide_learning_action_skips_fetch_when_rate_limited(self, tmp_path):
        from agent_core.autonomy import AutonomyPolicy
        from agent_core.autonomy.rate_limiter import ActionRateLimiter
        limiter = ActionRateLimiter(limits={"fetch": 1})
        limiter.record("fetch")
        policy = AutonomyPolicy(rate_limiter=limiter)
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        planner.set_autonomy_policy(policy)

        # Snapshot where only FETCH would be chosen (all completed, good retention)
        snapshot = {
            "files_by_status": {"completed": [{"id": "f1"}]},
            "new_files_available": [],
        }
        action = planner._decide_learning_action(snapshot, {"retention_rate": 0.9})
        # Should be NOOP, not FETCH (because fetch is rate-limited)
        assert action == ActionType.NOOP

    def test_decide_learning_action_allows_fetch_when_not_limited(self, tmp_path):
        from agent_core.autonomy import AutonomyPolicy
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        planner.set_autonomy_policy(AutonomyPolicy())

        snapshot = {
            "files_by_status": {"completed": [{"id": "f1"}]},
            "new_files_available": [],
        }
        action = planner._decide_learning_action(snapshot, {"retention_rate": 0.9})
        assert action == ActionType.FETCH


# ══════════════════════════════════════════════════════
# K7 Block Fallthrough to K12/Evaluate
# ══════════════════════════════════════════════════════


class TestK7FallthroughToK12:
    """When K7 blocks a goal's plan, planner should fall through to evaluate/self_analyze."""

    def test_k7_blocked_noop_falls_through_to_self_analyze(self, planner_env):
        """When goal maps to NOOP (e.g. FETCH rate-limited), K12 should trigger."""
        planner, tmp_path = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)
        planner._state.last_evaluation_ts = time.time()  # Skip evaluate

        # Goal exists -> will map to NOOP (all completed, fetch rate-limited)
        goal = _make_goal(goal_type="learning")
        planner.set_goal_store(_make_mock_goal_store([goal]))

        # Mock K12 self_analysis with proper return value
        from agent_core.self_analysis import SelfAnalysis
        mock_sa = specced(SelfAnalysis)
        mock_report = MagicMock()
        mock_report.error = None
        mock_report.report_id = "report-test"
        mock_report.recommendations = []
        mock_report.goals_created = []
        mock_report.duration_ms = 100
        mock_sa.run_analysis.return_value = mock_report
        planner.set_self_analysis(mock_sa)
        planner._state.last_self_analysis_ts = 0.0  # Never analyzed

        # Real KnowledgeAnalyzer with empty input dir (all completed scenario)
        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        import json
        index_path = tmp_path / "ki.jsonl"
        with open(index_path, "w") as f:
            f.write(json.dumps({"id": "f1.txt", "file": "f1.txt", "status": "completed",
                                "priority": 50, "chunks_learned": 1, "total_chunks": 1}) + "\n")
        input_dir = tmp_path / "input"
        input_dir.mkdir(exist_ok=True)
        analyzer = KnowledgeAnalyzer(
            knowledge_index_path=index_path, input_dir=input_dir,
        )
        planner.set_knowledge_analyzer(analyzer)

        result = planner.run_cycle(60)
        assert result is not None
        # Should be self_analyze (K12) since NOOP fell through
        assert result.action_type == ActionType.SELF_ANALYZE

    def test_k7_blocked_fetch_falls_through(self, planner_env):
        """When K7 blocks FETCH, planner should try evaluate/self_analyze."""
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)
        planner._state.last_evaluation_ts = time.time()

        goal = _make_goal(goal_type="learning")
        planner.set_goal_store(_make_mock_goal_store([goal]))

        # K7: block LEARN but allow SELF_ANALYZE
        from agent_core.autonomy import AutonomyPolicy
        from agent_core.self_analysis import SelfAnalysis
        mock_k7 = specced(AutonomyPolicy)
        blocked = MagicMock()
        blocked.allowed = False
        blocked.blocked_result = {"success": False, "blocked_by": "autonomy_policy"}
        allowed = MagicMock()
        allowed.allowed = True
        mock_k7.check.side_effect = lambda **kw: (
            allowed if kw.get("action_type") == "self_analyze" else blocked
        )
        planner.set_autonomy_policy(mock_k7)

        # K12: ready to analyze
        mock_sa = specced(SelfAnalysis)
        mock_report = MagicMock()
        mock_report.error = None
        mock_report.report_id = "report-test"
        mock_report.recommendations = []
        mock_report.goals_created = []
        mock_report.duration_ms = 100
        mock_sa.run_analysis.return_value = mock_report
        planner.set_self_analysis(mock_sa)
        planner._state.last_self_analysis_ts = 0.0

        result = planner.run_cycle(60)
        assert result is not None
        assert result.action_type == ActionType.SELF_ANALYZE


# ═══════════════════════════════════════════════════════
# Faza F: Cross-Validation Trigger Tests
# ═══════════════════════════════════════════════════════


class TestPlannerStatValidation:
    def test_last_validation_ts_default(self):
        s = PlannerState()
        assert s.last_validation_ts == 0.0

    def test_last_validation_ts_roundtrip(self):
        s = PlannerState(last_validation_ts=12345.0)
        d = s.to_dict()
        assert d["last_validation_ts"] == 12345.0
        restored = PlannerState.from_dict(d)
        assert restored.last_validation_ts == 12345.0

    def test_from_dict_missing_validation_ts(self):
        """Backward compatibility: old state files without last_validation_ts."""
        d = {"total_cycles": 5}
        s = PlannerState.from_dict(d)
        assert s.last_validation_ts == 0.0


class TestMaybeValidate:
    def test_triggers_when_cooldown_expired(self, planner_env):
        from agent_core.cross_validation.cross_validator import CrossValidator
        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        planner, _ = planner_env
        mock_validator = specced(CrossValidator)
        mock_analyzer = specced(KnowledgeAnalyzer)
        mock_analyzer.get_knowledge_snapshot.return_value = {
            "files_by_status": {"completed": ["test_file.txt"]},
        }
        planner.executor._cross_validator = mock_validator
        planner.executor._knowledge_analyzer = mock_analyzer
        planner._state.last_validation_ts = 0.0  # Long ago

        result = planner._maybe_validate({})
        assert result is not None
        assert result.action_type == ActionType.VALIDATE
        assert result.action_params["file_id"] == "test_file.txt"

    def test_no_trigger_within_cooldown(self, planner_env):
        from agent_core.cross_validation.cross_validator import CrossValidator
        planner, _ = planner_env
        mock_validator = specced(CrossValidator)
        planner.executor._cross_validator = mock_validator
        planner._state.last_validation_ts = time.time()  # Just now

        result = planner._maybe_validate({})
        assert result is None

    def test_no_trigger_without_validator(self, planner_env):
        planner, _ = planner_env
        result = planner._maybe_validate({})
        assert result is None

    def test_no_trigger_no_completed_files(self, planner_env):
        from agent_core.cross_validation.cross_validator import CrossValidator
        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        planner, _ = planner_env
        mock_validator = specced(CrossValidator)
        mock_analyzer = specced(KnowledgeAnalyzer)
        mock_analyzer.get_knowledge_snapshot.return_value = {
            "files_by_status": {"completed": []},
        }
        planner.executor._cross_validator = mock_validator
        planner.executor._knowledge_analyzer = mock_analyzer
        planner._state.last_validation_ts = 0.0

        result = planner._maybe_validate({})
        assert result is None

    def test_no_trigger_when_k7_rate_limited(self, planner_env):
        from agent_core.cross_validation.cross_validator import CrossValidator
        from agent_core.autonomy import AutonomyPolicy
        planner, _ = planner_env
        mock_validator = specced(CrossValidator)
        planner.executor._cross_validator = mock_validator
        planner._state.last_validation_ts = 0.0

        mock_k7 = specced(AutonomyPolicy)
        check_result = MagicMock()
        check_result.allowed = False
        mock_k7.check.return_value = check_result
        planner.set_autonomy_policy(mock_k7)

        result = planner._maybe_validate({})
        assert result is None

    def test_updates_last_validation_ts(self, planner_env):
        from agent_core.cross_validation.cross_validator import CrossValidator
        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        planner, _ = planner_env
        mock_validator = specced(CrossValidator)
        mock_analyzer = specced(KnowledgeAnalyzer)
        mock_analyzer.get_knowledge_snapshot.return_value = {
            "files_by_status": {"completed": ["file_a.txt"]},
        }
        planner.executor._cross_validator = mock_validator
        planner.executor._knowledge_analyzer = mock_analyzer
        planner._state.last_validation_ts = 0.0

        before = time.time()
        planner._maybe_validate({})
        assert planner._state.last_validation_ts >= before


class TestValidateInDecisionCycle:
    def test_validate_triggers_as_fallback(self, planner_env):
        """VALIDATE fires when no goals and evaluate/creative already done."""
        planner, _ = planner_env
        core = _make_mock_core(mode="active", health=0.9)
        planner.set_homeostasis_core(core)
        planner.set_goal_store(_make_mock_goal_store([]))

        # No evaluation needed (recent)
        planner._state.last_evaluation_ts = time.time()

        # Wire validator with completed file
        from agent_core.cross_validation.cross_validator import CrossValidator
        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        mock_validator = specced(CrossValidator)
        mock_validator.validate_file.return_value = {
            "chunks_validated": 3,
            "chunks_agreed": 2,
            "chunks_disputed": 1,
            "avg_confidence": 0.75,
        }
        planner.set_cross_validator(mock_validator)

        mock_analyzer = specced(KnowledgeAnalyzer)
        mock_analyzer.get_knowledge_snapshot.return_value = {
            "files_by_status": {"completed": ["validated_file.txt"]},
            "total_files": 1, "total_chunks": 5,
        }
        planner.executor.set_knowledge_analyzer(mock_analyzer)
        planner._state.last_validation_ts = 0.0

        result = planner.run_cycle(60)
        assert result is not None
        assert result.action_type == ActionType.VALIDATE


class TestBeliefConfidenceUpdate:
    def test_update_beliefs_from_validation(self):
        """Beliefs linked to validated file get confidence updated."""
        from agent_core.world_model.belief_store import BeliefStore
        executor = ActionExecutor()

        # Create mock world model with belief store
        mock_store = specced(BeliefStore)
        mock_belief = MagicMock()
        mock_belief.source_id = "test_file.txt"
        mock_belief.belief_id = "belief-001"
        mock_belief.confidence = 0.5
        mock_belief.belief_type = MagicMock(value="observation")
        mock_belief.belief_type.name = "OBSERVATION"
        # Import for type comparison
        from agent_core.world_model.belief_model import BeliefType
        mock_belief.belief_type = BeliefType.OBSERVATION
        mock_store.get_current.return_value = [mock_belief]
        mock_store.revise.return_value = MagicMock()

        mock_wm = specced(WorldModel, store=mock_store)
        executor.set_world_model(mock_wm)

        count = executor._update_beliefs_from_validation("test_file.txt", 0.8)
        assert count == 1
        mock_store.revise.assert_called_once()
        # Verify confidence blend: 0.5*0.6 + 0.8*0.4 = 0.62
        call_args = mock_store.revise.call_args
        assert call_args[0][0] == "belief-001"
        new_conf = call_args[0][1]
        assert abs(new_conf - 0.62) < 0.01
        # High validation -> promoted to FACT
        assert call_args[0][2] == BeliefType.FACT
        # save(), NOT flush(): the old assertion enshrined a method that
        # never existed on BeliefStore -- the MagicMock invented it while
        # production raised AttributeError (mock-hidden bug, fixed
        # 2026-06-11; real-store coverage lives in
        # TestUpdateBeliefsFromValidationPersistence).
        mock_store.save.assert_called_once()

    def test_no_update_without_world_model(self):
        executor = ActionExecutor()
        count = executor._update_beliefs_from_validation("file.txt", 0.8)
        assert count == 0

    def test_low_confidence_demotes_to_hypothesis(self):
        """Low validation score demotes belief to HYPOTHESIS."""
        from agent_core.world_model.belief_store import BeliefStore
        executor = ActionExecutor()
        from agent_core.world_model.belief_model import BeliefType

        mock_store = specced(BeliefStore)
        mock_belief = MagicMock()
        mock_belief.source_id = "bad_file.txt"
        mock_belief.belief_id = "belief-002"
        mock_belief.confidence = 0.6
        mock_belief.belief_type = BeliefType.FACT
        mock_store.get_current.return_value = [mock_belief]
        mock_store.revise.return_value = MagicMock()

        mock_wm = specced(WorldModel, store=mock_store)
        executor.set_world_model(mock_wm)

        count = executor._update_beliefs_from_validation("bad_file.txt", 0.2)
        assert count == 1
        call_args = mock_store.revise.call_args
        # confidence: 0.6*0.6 + 0.2*0.4 = 0.44
        assert abs(call_args[0][1] - 0.44) < 0.01
        assert call_args[0][2] == BeliefType.HYPOTHESIS

    def test_skips_unrelated_beliefs(self):
        """Only beliefs matching file_id are updated."""
        from agent_core.world_model.belief_store import BeliefStore
        executor = ActionExecutor()
        from agent_core.world_model.belief_model import BeliefType

        mock_store = specced(BeliefStore)
        other_belief = MagicMock()
        other_belief.source_id = "other_file.txt"
        mock_store.get_current.return_value = [other_belief]

        mock_wm = specced(WorldModel, store=mock_store)
        executor.set_world_model(mock_wm)

        count = executor._update_beliefs_from_validation("target.txt", 0.9)
        assert count == 0
        mock_store.revise.assert_not_called()


# ═══════════════════════════════════════════════════════
# CDL Feedback Loop: _update_learning_goal
# ═══════════════════════════════════════════════════════


class TestUpdateLearningGoal:
    def test_updates_progress_on_learn(self):
        """Learning goal progress updated after successful LEARN."""
        executor = ActionExecutor()

        mock_goal = MagicMock()
        mock_goal.type = MagicMock(value="learning")
        mock_goal.progress = 0.0
        mock_goal.metadata = {"topic": "genetyka", "topics": ["genetyka"]}
        mock_goal.description = "Nauka: genetyka"
        mock_goal.status = MagicMock(value="active")

        mock_store = specced(GoalStore)
        mock_store.get.return_value = mock_goal
        executor.set_goal_store(mock_store)

        plan = create_plan("goal-123", "learn", ActionType.LEARN)
        result = {"success": True, "chunks_learned": 2}

        executor._update_learning_goal(plan, result)
        mock_store.update_progress.assert_called_once()

    def test_no_update_without_goal_store(self):
        """No crash when goal_store is None."""
        executor = ActionExecutor()
        plan = create_plan("goal-123", "learn", ActionType.LEARN)
        executor._update_learning_goal(plan, {"success": True})
        # Should not raise

    def test_no_update_for_non_learning_goal(self):
        """Non-learning goals are skipped."""
        executor = ActionExecutor()

        mock_goal = MagicMock()
        mock_goal.type = MagicMock(value="maintenance")

        mock_store = specced(GoalStore)
        mock_store.get.return_value = mock_goal
        executor.set_goal_store(mock_store)

        plan = create_plan("goal-123", "maint", ActionType.MAINTENANCE)
        executor._update_learning_goal(plan, {"success": True})
        mock_store.update_progress.assert_not_called()

    def test_sets_outcome_on_achieved(self):
        """When goal transitions to achieved, outcome is set."""
        executor = ActionExecutor()

        mock_goal = MagicMock()
        mock_goal.type = MagicMock(value="learning")
        mock_goal.progress = 0.8
        mock_goal.metadata = {"topic": "fizyka"}
        mock_goal.description = "Nauka: fizyka"

        # After update_progress, goal status becomes achieved
        mock_goal_achieved = MagicMock()
        mock_goal_achieved.status = MagicMock(value="achieved")

        mock_store = specced(GoalStore)
        mock_store.get.side_effect = [mock_goal, mock_goal_achieved]
        executor.set_goal_store(mock_store)

        plan = create_plan("goal-123", "exam", ActionType.EXAM)
        result = {"success": True, "exams_passed": 1, "score": 0.85}

        executor._update_learning_goal(plan, result)
        mock_store.set_outcome.assert_called_once()
        outcome = mock_store.set_outcome.call_args[0][1]
        assert outcome["final_score"] == 0.85
        assert outcome["exams_passed"] == 1


# ═══════════════════════════════════════════════════════
# Goal Pivot Tests (NOOP loop fix)
# ═══════════════════════════════════════════════════════


class TestGoalPivot:
    """When top goal maps to NOOP, planner should try next goal."""

    def test_pivot_to_second_goal_on_noop(self, planner_env):
        """First goal -> NOOP (all completed), second goal -> LEARN."""
        planner, tmp_path = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)
        planner.set_teacher_agent(_make_mock_teacher())
        planner._state.last_evaluation_ts = time.time()

        # Goal 1: high priority, will NOOP (no files)
        goal1 = _make_goal(
            goal_id="goal-high", priority=1.1, goal_type="learning",
            metadata={"source": "conversation"},
        )
        # Goal 2: lower priority, has files to learn
        goal2 = _make_goal(
            goal_id="goal-low", priority=0.8, goal_type="learning",
        )
        planner.set_goal_store(_make_mock_goal_store([goal1, goal2]))

        # Knowledge: no files in learning/new for goal1, but new files exist
        import json
        index_path = tmp_path / "ki.jsonl"
        with open(index_path, "w") as f:
            f.write(json.dumps({
                "id": "f1.txt", "file": "f1.txt", "status": "new",
                "priority": 50, "chunks_learned": 0, "total_chunks": 1,
            }) + "\n")
        input_dir = tmp_path / "input"
        input_dir.mkdir(exist_ok=True)
        (input_dir / "f1.txt").write_text("test content")

        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        analyzer = KnowledgeAnalyzer(
            knowledge_index_path=index_path, input_dir=input_dir,
        )
        planner.set_knowledge_analyzer(analyzer)

        # Goal1 has no topic files -> NOOP, goal2 has files -> LEARN
        # But since both share same analyzer, we need goal1 to NOOP
        # Force: goal1 already completed (override snapshot for first call)
        # Simpler: just make goal1 a maintenance goal with progress=1.0 (infeasible)
        # Actually let's test the real scenario: both feasible but goal1 returns NOOP
        # The simplest way: goal1 conversation source, all files completed
        index_path2 = tmp_path / "ki2.jsonl"
        with open(index_path2, "w") as f:
            f.write(json.dumps({
                "id": "f1.txt", "file": "f1.txt", "status": "completed",
                "priority": 50, "chunks_learned": 1, "total_chunks": 1,
            }) + "\n")
        analyzer2 = KnowledgeAnalyzer(
            knowledge_index_path=index_path2, input_dir=input_dir,
        )
        planner.set_knowledge_analyzer(analyzer2)

        result = planner.run_cycle(60)
        assert result is not None
        # Should not be NOOP - should have pivoted or fallen through
        # (may be evaluate/self_analyze/creative, but NOT stuck NOOP)
        # The key: it tried beyond goal1

    def test_select_ranked_goals_returns_ordered_list(self, planner_env):
        """_select_ranked_goals returns goals sorted by effective priority."""
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)

        goal_low = _make_goal(goal_id="g-low", priority=0.3)
        goal_high = _make_goal(goal_id="g-high", priority=0.9)
        goal_mid = _make_goal(goal_id="g-mid", priority=0.6)
        planner.set_goal_store(_make_mock_goal_store([goal_low, goal_high, goal_mid]))

        context = planner._gather_context()
        ranked = planner._select_ranked_goals(context)
        assert len(ranked) == 3
        assert ranked[0].id == "g-high"
        assert ranked[1].id == "g-mid"
        assert ranked[2].id == "g-low"

    def test_select_ranked_goals_empty(self, planner_env):
        """_select_ranked_goals returns empty list when no goals."""
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)
        planner.set_goal_store(_make_mock_goal_store([]))

        context = planner._gather_context()
        ranked = planner._select_ranked_goals(context)
        assert ranked == []

    def test_select_ranked_goals_filters_infeasible(self, planner_env):
        """_select_ranked_goals skips infeasible goals (e.g. satisfied maintenance)."""
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)

        goal_ok = _make_goal(goal_id="g-ok", priority=0.5, goal_type="learning")
        goal_done = _make_goal(
            goal_id="g-done", priority=0.9, goal_type="maintenance",
            progress=1.0,  # satisfied -> infeasible
        )
        planner.set_goal_store(_make_mock_goal_store([goal_ok, goal_done]))

        context = planner._gather_context()
        ranked = planner._select_ranked_goals(context)
        assert len(ranked) == 1
        assert ranked[0].id == "g-ok"

    def test_select_ranked_goals_filters_stuck_cooled(self, planner_env):
        """Goals in stuck cooldown should be filtered out."""
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)

        goal1 = _make_goal(goal_id="g-stuck", priority=1.0, goal_type="learning")
        goal2 = _make_goal(goal_id="g-ok", priority=0.5, goal_type="learning")
        planner.set_goal_store(_make_mock_goal_store([goal1, goal2]))

        # Put goal1 in stuck cooldown
        planner._state.stuck_cooldowns["g-stuck"] = time.time() + 1800

        context = planner._gather_context()
        ranked = planner._select_ranked_goals(context)
        assert len(ranked) == 1
        assert ranked[0].id == "g-ok"

    def test_stuck_cooldown_expires(self, planner_env):
        """Expired stuck cooldown should no longer filter goals."""
        planner, _ = planner_env
        core = _make_mock_core()
        planner.set_homeostasis_core(core)

        goal = _make_goal(goal_id="g-was-stuck", priority=1.0, goal_type="learning")
        planner.set_goal_store(_make_mock_goal_store([goal]))

        # Expired cooldown
        planner._state.stuck_cooldowns["g-was-stuck"] = time.time() - 1

        context = planner._gather_context()
        ranked = planner._select_ranked_goals(context)
        assert len(ranked) == 1
        assert ranked[0].id == "g-was-stuck"
        # Expired entry should be cleaned up
        assert "g-was-stuck" not in planner._state.stuck_cooldowns


class TestGoalActivation:
    """Plank 1: planner promotes a goal PENDING -> ACTIVE the moment it commits
    real (non-NOOP) work to it. Without this, learning goals stayed PENDING
    forever and update_progress()'s auto-ACHIEVED (ACTIVE-only) never fired ->
    1118 abandoned, 0 autonomous completions.
    """

    def _real_goal(self, gid, status):
        from agent_core.goals.goal_model import Goal, GoalType, GoalStatus
        return Goal(
            id=gid, type=GoalType("learning"), description="Nauka: test",
            priority=0.9, status=GoalStatus(status), progress=0.0,
            parent_goal_id=None, created_by="test", created_at=time.time(),
            updated_at=time.time(), metadata={"source": "conversation"},
        )

    def _wire(self, planner, goal):
        """Wire planner with a mock store and a deterministic non-NOOP plan."""
        planner.set_homeostasis_core(_make_mock_core())
        planner.set_teacher_agent(_make_mock_teacher())
        planner._state.last_evaluation_ts = time.time()
        store = _make_mock_goal_store([goal])
        planner.set_goal_store(store)
        return store

    def _force_plan(self, planner, goal_id, action_type):
        from agent_core.planner.planner_model import create_plan, PlanStatus
        plan = create_plan(goal_id, "Nauka: test", action_type)
        planner._create_plan_for_goal = lambda g, ctx: plan
        result = MagicMock()
        result.status = PlanStatus.COMPLETED
        result.result = {"success": True}
        planner._finalize_plan = lambda p: result

    def _activation_calls(self, store):
        from agent_core.goals.goal_model import GoalStatus
        return [
            c for c in store.update_status.call_args_list
            if c.args and c.args[1] == GoalStatus.ACTIVE
        ]

    def test_pending_goal_activated_on_real_action(self, planner_env):
        """PENDING goal + non-NOOP plan -> promoted to ACTIVE by 'planner'."""
        from agent_core.planner.planner_model import ActionType
        planner, _ = planner_env
        goal = self._real_goal("goal-pend", "pending")
        store = self._wire(planner, goal)
        self._force_plan(planner, "goal-pend", ActionType.LEARN)

        planner.run_cycle(60)

        acts = self._activation_calls(store)
        assert len(acts) == 1, store.update_status.call_args_list
        assert acts[0].args[0] == "goal-pend"
        assert acts[0].args[3] == "planner"  # actor
        store.save.assert_called()

    def test_active_goal_not_reactivated(self, planner_env):
        """Already-ACTIVE goal must not be re-activated (no redundant churn)."""
        from agent_core.planner.planner_model import ActionType
        planner, _ = planner_env
        goal = self._real_goal("goal-act", "active")
        store = self._wire(planner, goal)
        self._force_plan(planner, "goal-act", ActionType.LEARN)

        planner.run_cycle(60)

        assert self._activation_calls(store) == []

    def test_noop_plan_does_not_activate(self, planner_env):
        """NOOP means no work committed -> goal stays PENDING (pivot), no activation."""
        from agent_core.planner.planner_model import ActionType
        planner, _ = planner_env
        goal = self._real_goal("goal-noop", "pending")
        store = self._wire(planner, goal)
        # NOOP plan; no _finalize_plan stub needed (pivot continues past it)
        from agent_core.planner.planner_model import create_plan
        planner._create_plan_for_goal = lambda g, ctx: create_plan(
            "goal-noop", "Nauka: test", ActionType.NOOP
        )

        planner.run_cycle(60)

        assert self._activation_calls(store) == []


class TestReconcileLearningGoals:
    """Plank 2b: goals whose owned files are all INDEPENDENTLY exam-verified are
    harvested to ACHIEVED, independent of any learn/exam action -- the backlog
    of already-mastered goals that could otherwise never close. (Hardened
    2026-06-01: a self-graded 'completed' status no longer force-closes a goal.)
    """

    @pytest.fixture(autouse=True)
    def _treat_completed_as_verified(self, monkeypatch):
        # These tests isolate the harvest/fraction logic; treat every
        # 'completed' file in the context snapshot as independently verified.
        # The "self-graded does NOT close" path has its own dedicated test.
        self._verified_ids = set()
        monkeypatch.setattr(
            "agent_core.goals.success_criteria.independently_verified_file_ids",
            lambda *a, **k: self._verified_ids,
        )

    def _store(self, tmp_path):
        from agent_core.goals.store import GoalStore
        return GoalStore(tmp_path / "goals.jsonl")

    def _goal(self, gid, status, metadata, progress=0.0):
        from agent_core.goals.goal_model import Goal, GoalType, GoalStatus
        return Goal(
            id=gid, type=GoalType.LEARNING, description="Nauka: " + gid,
            priority=0.5, status=GoalStatus(status), progress=progress,
            parent_goal_id=None, created_by="test", created_at=time.time(),
            updated_at=time.time(), metadata=metadata,
        )

    def _ctx(self, completed_ids):
        self._verified_ids = set(completed_ids)
        return {"knowledge_snapshot": {"files_by_status": {
            "completed": [{"id": f, "file": f} for f in completed_ids],
        }}}

    def _analyzer(self, topic_files=None):
        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        analyzer = specced(KnowledgeAnalyzer)
        if topic_files is not None:
            analyzer.get_files_for_topics.return_value = [
                (f, 1.0) for f in topic_files
            ]
        return analyzer

    def test_active_goal_all_completed_achieved(self, planner_env):
        from agent_core.goals.goal_model import GoalStatus
        planner, tmp_path = planner_env
        store = self._store(tmp_path)
        store.create(self._goal("g-active", "active", {"file_ids": ["a.txt", "b.txt"]}))
        planner.set_goal_store(store)
        planner.set_knowledge_analyzer(self._analyzer())

        planner._reconcile_learning_goals(self._ctx(["a.txt", "b.txt"]))

        assert store.get("g-active").status == GoalStatus.ACHIEVED

    def test_pending_goal_all_completed_achieved(self, planner_env):
        """PENDING goals don't auto-achieve via update_progress -> explicit."""
        from agent_core.goals.goal_model import GoalStatus
        planner, tmp_path = planner_env
        store = self._store(tmp_path)
        store.create(self._goal("g-pend", "pending", {"file_ids": ["a.txt"]}))
        planner.set_goal_store(store)
        planner.set_knowledge_analyzer(self._analyzer())

        planner._reconcile_learning_goals(self._ctx(["a.txt"]))

        assert store.get("g-pend").status == GoalStatus.ACHIEVED

    def test_partial_completion_not_achieved(self, planner_env):
        from agent_core.goals.goal_model import GoalStatus
        planner, tmp_path = planner_env
        store = self._store(tmp_path)
        store.create(self._goal("g-part", "active", {"file_ids": ["a.txt", "b.txt"]}))
        planner.set_goal_store(store)
        planner.set_knowledge_analyzer(self._analyzer())

        planner._reconcile_learning_goals(self._ctx(["a.txt"]))  # 1 of 2

        g = store.get("g-part")
        assert g.status == GoalStatus.ACTIVE
        assert g.progress == 0.5

    def test_topic_goal_resolved_and_achieved(self, planner_env):
        """No explicit file_ids -> resolve via topic, then harvest."""
        from agent_core.goals.goal_model import GoalStatus
        planner, tmp_path = planner_env
        store = self._store(tmp_path)
        store.create(self._goal("g-topic", "active", {"topics": ["chemia"]}))
        planner.set_goal_store(store)
        planner.set_knowledge_analyzer(self._analyzer(topic_files=["chem.txt"]))

        planner._reconcile_learning_goals(self._ctx(["chem.txt"]))

        assert store.get("g-topic").status == GoalStatus.ACHIEVED

    def test_self_graded_completed_does_not_close(self, planner_env):
        """Audit 2026-06-01 #1: a goal whose owned files are all 'completed' but
        only SELF-graded (no independent pass) must NOT be force-closed -- the
        bypass that made the 'closes on independently-verified knowledge' claim
        false on the path that runs."""
        from agent_core.goals.goal_model import GoalStatus
        planner, tmp_path = planner_env
        store = self._store(tmp_path)
        store.create(self._goal("g-self", "active", {"file_ids": ["a.txt", "b.txt"]}))
        planner.set_goal_store(store)
        planner.set_knowledge_analyzer(self._analyzer())

        ctx = self._ctx(["a.txt", "b.txt"])   # both 'completed'...
        self._verified_ids = set()            # ...but NONE independently verified
        planner._reconcile_learning_goals(ctx)

        g = store.get("g-self")
        assert g.status == GoalStatus.ACTIVE   # stays open, not ACHIEVED
        assert g.progress == 0.0

    def test_goal_without_files_untouched(self, planner_env):
        from agent_core.goals.goal_model import GoalStatus
        planner, tmp_path = planner_env
        store = self._store(tmp_path)
        store.create(self._goal("g-none", "active", {}))
        planner.set_goal_store(store)
        planner.set_knowledge_analyzer(self._analyzer())

        planner._reconcile_learning_goals(self._ctx(["a.txt"]))

        g = store.get("g-none")
        assert g.status == GoalStatus.ACTIVE
        assert g.progress == 0.0


class TestStuckDetection:
    """Stuck loop detection in planner (Level 2)."""

    def test_stuck_detected_after_threshold(self, planner_env):
        """3 consecutive identical failures should trigger stuck cooldown."""
        planner, _ = planner_env
        from agent_core.planner.planner_core import STUCK_THRESHOLD

        # Simulate 3 identical failures
        for _ in range(STUCK_THRESHOLD):
            planner._state.stuck_history.append({
                "action": "ask_expert",
                "goal_id": "g-test",
                "reason": "expert_material_already_exists",
            })

        # Create a plan that triggers _handle_stuck check
        plan = create_plan(
            goal_id="g-test",
            goal_description="Test goal",
            action_type=ActionType.ASK_EXPERT,
        )
        plan.status = PlanStatus.FAILED
        plan.result = {"error": "expert_material_already_exists"}

        # Manually trigger _handle_stuck
        fingerprint = {
            "action": "ask_expert",
            "goal_id": "g-test",
            "reason": "expert_material_already_exists",
        }
        planner._handle_stuck(plan, fingerprint, STUCK_THRESHOLD)

        assert "g-test" in planner._state.stuck_cooldowns
        assert planner._state.stuck_cooldowns["g-test"] > time.time()
        # History should be cleared after stuck
        assert len(planner._state.stuck_history) == 0

    def test_no_stuck_below_threshold(self, planner_env):
        """Fewer than threshold failures should not trigger stuck."""
        planner, _ = planner_env

        # Only 2 failures (threshold is 3)
        planner._state.stuck_history = [
            {"action": "ask_expert", "goal_id": "g-test", "reason": "err"},
            {"action": "ask_expert", "goal_id": "g-test", "reason": "err"},
        ]
        assert "g-test" not in planner._state.stuck_cooldowns

    def test_different_errors_no_stuck(self, planner_env):
        """Different error reasons should not trigger stuck."""
        planner, _ = planner_env

        planner._state.stuck_history = [
            {"action": "ask_expert", "goal_id": "g-test", "reason": "error_a"},
            {"action": "ask_expert", "goal_id": "g-test", "reason": "error_b"},
            {"action": "ask_expert", "goal_id": "g-test", "reason": "error_c"},
        ]
        # No cooldown should exist
        assert "g-test" not in planner._state.stuck_cooldowns

    def test_success_clears_stuck_history(self, planner_env):
        """A successful plan should clear stuck history."""
        planner, _ = planner_env

        planner._state.stuck_history = [
            {"action": "ask_expert", "goal_id": "g-test", "reason": "err"},
            {"action": "ask_expert", "goal_id": "g-test", "reason": "err"},
        ]
        assert len(planner._state.stuck_history) == 2

        # Simulate the success path (from _finalize_plan)
        planner._state.stuck_history.clear()
        assert len(planner._state.stuck_history) == 0

    def test_stuck_sends_telegram(self, planner_env):
        """Stuck detection should call Telegram notifier with diagnosis."""
        from agent_core.telegram.notifier import TelegramNotifier
        planner, _ = planner_env

        mock_notifier = specced(TelegramNotifier)
        planner._telegram_notifier = mock_notifier

        plan = create_plan(
            goal_id="g-test",
            goal_description="Nauka logiki",
            action_type=ActionType.ASK_EXPERT,
        )
        plan.result = {"topic": "logika", "error": "expert_material_already_exists"}
        fingerprint = {
            "action": "ask_expert",
            "goal_id": "g-test",
            "reason": "expert_material_already_exists",
        }

        planner._handle_stuck(plan, fingerprint, 3)

        # Should call notify_stuck with formatted diagnosis message
        mock_notifier.notify_stuck.assert_called_once()
        msg = mock_notifier.notify_stuck.call_args[0][0]
        assert "Utknelam" in msg
        assert "Diagnoza:" in msg

    def test_stuck_state_persists(self):
        """Stuck fields should survive to_dict/from_dict round-trip."""
        state = PlannerState()
        state.stuck_history = [
            {"action": "learn", "goal_id": "g-1", "reason": "err"},
        ]
        state.stuck_cooldowns = {"g-1": time.time() + 1800}

        d = state.to_dict()
        restored = PlannerState.from_dict(d)

        assert restored.stuck_history == state.stuck_history
        assert restored.stuck_cooldowns == state.stuck_cooldowns

    def test_stuck_state_defaults_on_old_json(self):
        """Old planner_state.json without stuck fields should load cleanly."""
        old_dict = {
            "last_cycle_tick": 100,
            "total_cycles": 50,
        }
        state = PlannerState.from_dict(old_dict)
        assert state.stuck_history == []
        assert state.stuck_cooldowns == {}


class TestHandlerSkipLogic:
    """Level 1: CapabilityRouter handler skip logic for ask_expert."""

    def test_expert_already_exists_returns_success(self):
        """expert_material_already_exists should return success=True, skipped=True."""
        from agent_core.routing.handlers import make_ask_expert_handler
        from agent_core.bulletin.expert_bridge import ExpertBridge
        from agent_core.llm.router import LLMRouter

        mock_bridge = specced(ExpertBridge)
        mock_resp = MagicMock()
        mock_resp.success = False
        mock_resp.reason = "expert_material_already_exists"
        mock_resp.gap_action = ""
        mock_bridge.ask_about_topic.return_value = mock_resp

        handler = make_ask_expert_handler(
            llm_router=specced(LLMRouter),
            expert_bridge=mock_bridge,
        )

        plan = create_plan(
            goal_id="g-test",
            goal_description="Test",
            action_type=ActionType.ASK_EXPERT,
            action_params={"topic": "logika formalna"},
        )

        result = handler(plan)
        assert result["success"] is True
        assert result["skipped"] is True
        assert result.get("error") is None

    def test_topic_well_covered_returns_success(self):
        """topic_well_covered should also be a skip (success=True)."""
        from agent_core.routing.handlers import make_ask_expert_handler
        from agent_core.bulletin.expert_bridge import ExpertBridge
        from agent_core.llm.router import LLMRouter

        mock_bridge = specced(ExpertBridge)
        mock_resp = MagicMock()
        mock_resp.success = False
        mock_resp.reason = "topic_well_covered"
        mock_resp.gap_action = ""
        mock_bridge.ask_about_topic.return_value = mock_resp

        handler = make_ask_expert_handler(
            llm_router=specced(LLMRouter),
            expert_bridge=mock_bridge,
        )

        plan = create_plan(
            goal_id="g-test",
            goal_description="Test",
            action_type=ActionType.ASK_EXPERT,
            action_params={"topic": "fizyka"},
        )

        result = handler(plan)
        assert result["success"] is True
        assert result["skipped"] is True

    def test_real_failure_returns_failure(self):
        """Non-skip reasons should still return success=False."""
        from agent_core.routing.handlers import make_ask_expert_handler
        from agent_core.bulletin.expert_bridge import ExpertBridge
        from agent_core.llm.router import LLMRouter

        mock_bridge = specced(ExpertBridge)
        mock_resp = MagicMock()
        mock_resp.success = False
        mock_resp.reason = "llm_error"
        mock_resp.gap_action = ""
        mock_bridge.ask_about_topic.return_value = mock_resp

        handler = make_ask_expert_handler(
            llm_router=specced(LLMRouter),
            expert_bridge=mock_bridge,
        )

        plan = create_plan(
            goal_id="g-test",
            goal_description="Test",
            action_type=ActionType.ASK_EXPERT,
            action_params={"topic": "chemia"},
        )

        result = handler(plan)
        assert result["success"] is False
        assert result["error"] == "llm_error"


class TestTelegramStuckNotification:
    """Level 3: Telegram stuck planner notification."""

    def test_notify_stuck_sends_message(self):
        """notify_stuck_planner should send formatted message."""
        from agent_core.telegram.notifier import TelegramNotifier
        from agent_core.telegram.bot import TelegramBot

        mock_bot = specced(TelegramBot)
        mock_bot.configured = True
        mock_bot.send_message.return_value = True
        notifier = TelegramNotifier(bot=mock_bot)

        ok = notifier.notify_stuck_planner(
            action="ask_expert",
            goal_id="g-test",
            goal_description="Nauka logiki",
            count=3,
            reason="expert_material_already_exists",
            cooldown_minutes=30,
        )

        assert ok is True
        mock_bot.send_message.assert_called_once()
        msg = mock_bot.send_message.call_args[0][0]
        assert "Utknelam" in msg
        assert "ask_expert" in msg
        assert "30 min" in msg

    def test_notify_stuck_respects_cooldown(self):
        """Second call within 2h should be suppressed."""
        from agent_core.telegram.notifier import TelegramNotifier
        from agent_core.telegram.bot import TelegramBot

        mock_bot = specced(TelegramBot)
        mock_bot.configured = True
        mock_bot.send_message.return_value = True
        notifier = TelegramNotifier(bot=mock_bot)

        # First call - should send
        ok1 = notifier.notify_stuck_planner(
            action="ask_expert", goal_id="g-1", count=3, reason="err",
        )
        assert ok1 is True

        # Second call - should be suppressed (cooldown 2h)
        ok2 = notifier.notify_stuck_planner(
            action="ask_expert", goal_id="g-1", count=3, reason="err",
        )
        assert ok2 is False
        assert mock_bot.send_message.call_count == 1


class TestPickExpertTopicDedup:
    """_pick_expert_topic should skip topics with existing expert material."""

    def test_has_expert_material_true(self):
        """Topic with expert file should be detected via mock."""
        from agent_core.planner.planner_core import PlannerCore
        planner = PlannerCore.__new__(PlannerCore)

        # Mock Path resolution to control file checks
        with patch("agent_core.planner.planner_core.Path") as MockPath:
            mock_input = MagicMock()
            mock_input.exists.return_value = True
            # expert_logika_formalna.txt exists with >5000 bytes
            mock_expert = MagicMock()
            mock_expert.exists.return_value = True
            mock_expert.stat.return_value = MagicMock(st_size=8000)
            # web_wiki_ doesn't exist
            mock_wiki = MagicMock()
            mock_wiki.exists.return_value = False
            mock_input.__truediv__ = lambda self, name: (
                mock_expert if "expert_logika" in name else mock_wiki
            )
            MockPath.return_value.resolve.return_value.parents.__getitem__ = lambda s, i: MagicMock(
                __truediv__=lambda s, name: mock_input if name == "input" else MagicMock()
            )

        # Simpler: just patch the method directly for integration test
        with patch.object(PlannerCore, "_has_expert_material", side_effect=lambda t: t == "logika formalna"):
            assert planner._has_expert_material("logika formalna") is True
            assert planner._has_expert_material("nowy temat") is False

    def test_pick_expert_topic_skips_existing(self):
        """_pick_expert_topic should skip topics that already have material."""
        from agent_core.planner.planner_core import PlannerCore
        planner = PlannerCore.__new__(PlannerCore)
        planner._knowledge_analyzer = None

        mock_wm = specced(WorldModel, query=MagicMock())
        mock_wm.query.get_knowledge_gaps.return_value = [
            {"topic": "logika formalna"},
            {"topic": "algebra liniowa"},
        ]
        planner._world_model = mock_wm

        with patch.object(
            PlannerCore, "_has_expert_material",
            side_effect=lambda t: t == "logika formalna",
        ):
            result = planner._pick_expert_topic()
            assert result == "algebra liniowa"

    def test_pick_expert_topic_all_covered_returns_none(self):
        """When all gap topics have material, return None."""
        from agent_core.planner.planner_core import PlannerCore
        planner = PlannerCore.__new__(PlannerCore)
        planner._knowledge_analyzer = None

        mock_wm = specced(WorldModel, query=MagicMock())
        mock_wm.query.get_knowledge_gaps.return_value = [
            {"topic": "fizyka"},
        ]
        planner._world_model = mock_wm

        with patch.object(
            PlannerCore, "_has_expert_material",
            return_value=True,
        ):
            result = planner._pick_expert_topic()
            assert result is None

    def test_pick_expert_topic_fallback_skips_covered(self):
        """Fallback to analyzer should also skip covered topics."""
        from agent_core.planner.planner_core import PlannerCore
        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        planner = PlannerCore.__new__(PlannerCore)
        planner._world_model = None

        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_topic_file_map.return_value = {"chemia": ["f1"], "biologia": ["f2"]}
        planner._knowledge_analyzer = analyzer

        with patch.object(
            PlannerCore, "_has_expert_material",
            side_effect=lambda t: t == "chemia",
        ):
            result = planner._pick_expert_topic()
            assert result == "biologia"


class TestGapLearnableGoalFilter:
    """Warstwa 1: block strategy/meta goals from gap-pipeline."""

    def _mk_planner(self):
        from agent_core.planner.planner_core import PlannerCore
        p = PlannerCore.__new__(PlannerCore)
        p._goal_store = None
        return p

    def test_no_goal_id_allows(self):
        p = self._mk_planner()
        assert p._is_gap_learnable_goal(None) is True

    def test_no_goal_store_allows(self):
        p = self._mk_planner()
        p._goal_store = None
        assert p._is_gap_learnable_goal("g1") is True

    def test_learning_goal_allowed(self):
        p = self._mk_planner()
        store = specced(GoalStore)
        g = MagicMock(); g.goal_type = MagicMock(value="learning")
        store.get.return_value = g
        p._goal_store = store
        assert p._is_gap_learnable_goal("g1") is True

    def test_user_goal_allowed(self):
        p = self._mk_planner()
        store = specced(GoalStore)
        g = MagicMock(); g.goal_type = MagicMock(value="user")
        store.get.return_value = g
        p._goal_store = store
        assert p._is_gap_learnable_goal("g1") is True

    def test_meta_goal_blocked(self):
        p = self._mk_planner()
        store = specced(GoalStore)
        g = MagicMock(); g.goal_type = MagicMock(value="meta")
        store.get.return_value = g
        p._goal_store = store
        assert p._is_gap_learnable_goal("g1") is False

    def test_maintenance_goal_blocked(self):
        p = self._mk_planner()
        store = specced(GoalStore)
        g = MagicMock(); g.goal_type = MagicMock(value="maintenance")
        store.get.return_value = g
        p._goal_store = store
        assert p._is_gap_learnable_goal("g1") is False

    def test_capability_meta_blocked(self):
        """Creative module's capability_meta goals must not hit gap pipeline."""
        p = self._mk_planner()
        store = specced(GoalStore)
        g = MagicMock(); g.goal_type = MagicMock(value="capability_meta")
        store.get.return_value = g
        p._goal_store = store
        assert p._is_gap_learnable_goal("g1") is False

    def test_raw_string_goal_type(self):
        """goal_type may be raw string (not Enum) — handle both."""
        p = self._mk_planner()
        store = specced(GoalStore)
        g = MagicMock(spec=["goal_type"]); g.goal_type = "meta"
        store.get.return_value = g
        p._goal_store = store
        assert p._is_gap_learnable_goal("g1") is False

    def test_missing_goal_allows(self):
        """goal_store.get returning None should not block (allow by default)."""
        p = self._mk_planner()
        store = specced(GoalStore)
        store.get.return_value = None
        p._goal_store = store
        assert p._is_gap_learnable_goal("g1") is True

    def test_store_exception_allows(self):
        """Exceptions from goal_store must not break planner."""
        p = self._mk_planner()
        store = specced(GoalStore)
        store.get.side_effect = RuntimeError("boom")
        p._goal_store = store
        assert p._is_gap_learnable_goal("g1") is True


class TestK9TopicFromFileIds:
    """Regression: K9 record_before must derive a meaningful topic for LEARN
    actions that only carry file_ids, not explicit topics. Without a topic,
    confidence tracker cannot segment by subject.

    Historical: every live learn reflection had topic='' because action_params
    only had file_ids. The derivation is inline in _finalize_plan — test the
    algorithm here to prevent regression.
    """

    def _derive(self, file_id):
        """Mirror the fallback 4 algorithm."""
        import re as _re
        stem = file_id.replace(".txt", "").replace(".md", "")
        for pref in ("input_", "expert_", "web_wiki_", "web_rss_"):
            if stem.startswith(pref):
                stem = stem[len(pref):]
                break
        stem = _re.sub(r"^\d+_", "", stem)
        return stem.replace("_", " ").strip()

    def test_input_numbered_prefix(self):
        assert self._derive("input_008_logika_formalna.txt") == "logika formalna"

    def test_expert_prefix(self):
        assert self._derive("expert_fizyka.txt") == "fizyka"

    def test_web_wiki_prefix(self):
        assert self._derive("web_wiki_astrofizyka.txt") == "astrofizyka"

    def test_no_known_prefix(self):
        assert self._derive("custom_topic.txt") == "custom topic"

    def test_compound_topic_in_filename(self):
        assert self._derive("expert_przyczynowo_skutek.txt") == "przyczynowo skutek"


class TestLearningWindowEnforcement:
    """D1 fix (2026-04-21): planner-level guard redirects learn-family
    actions to NOOP when outside the learning window, instead of letting
    them reach the executor and fail as `outside_learning_window`.

    See project_glm51_architecture_findings.md for the data that motivated
    this fix: 848/889 learn actions failed in 72h (95%) because K8
    Deliberation issued them past the window.
    """

    # -- GoalSelector pattern widening ------------------------------------

    def setup_method(self):
        self.selector = GoalSelector()
        self.now = time.time()

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=False)
    def test_meta_explore_goal_blocked_outside_window(self, _mock):
        """Meta goal whose description mentions knowledge exploration must
        be blocked outside the learning window even though it doesn't
        contain the literal 'nauk'/'learn' token."""
        goal = _make_goal(
            goal_type="meta",
            description="Przeorientowanie na eksploracja poza obecna domena wiedzy",
            created_at=self.now,
        )
        selected = self.selector.select_goal([goal], {}, now=self.now)
        assert selected is None

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_meta_explore_goal_feasible_inside_window(self, _mock):
        goal = _make_goal(
            goal_type="meta",
            description="Przeorientowanie na eksploracja poza obecna domena wiedzy",
            created_at=self.now,
        )
        selected = self.selector.select_goal([goal], {}, now=self.now)
        assert selected is not None

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=False)
    def test_meta_unrelated_goal_still_feasible_outside_window(self, _mock):
        """Meta goals without learning keywords stay feasible — the window
        guard only targets knowledge-acquisition meta goals."""
        goal = _make_goal(
            goal_type="meta",
            description="Zredukowanie zmeczenia operatora",
            created_at=self.now,
        )
        selected = self.selector.select_goal([goal], {}, now=self.now)
        assert selected is not None

    # -- D1.5d/D1.5c: meta learning goals + library saturation -----------

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_meta_learning_goal_feasible_when_library_saturated(self, _mock):
        """D1.5c (2026-04-22): saturated meta-learning goal stays feasible
        so the planner can route it to FETCH. Previously D1.5d blocked it,
        which killed Maria's only autonomous path to pull new materials."""
        goal = _make_goal(
            goal_type="meta",
            description="Autonomiczna nauka i strukturyzacja wiedzy",
            created_at=self.now,
        )
        snapshot = {
            "files_by_status": {"completed": ["a.txt", "b.txt"]},
            "new_files_available": [],
        }
        selected = self.selector.select_goal(
            [goal], {}, knowledge_snapshot=snapshot, now=self.now,
        )
        assert selected is goal

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_meta_learning_goal_feasible_with_new_files(self, _mock):
        goal = _make_goal(
            goal_type="meta",
            description="Eksploracja poza obecna domena wiedzy",
            created_at=self.now,
        )
        snapshot = {
            "files_by_status": {},
            "new_files_available": [{"file": "new1.txt"}],
        }
        selected = self.selector.select_goal(
            [goal], {}, knowledge_snapshot=snapshot, now=self.now,
        )
        assert selected is not None

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_meta_learning_goal_feasible_with_in_progress(self, _mock):
        """In-progress learning files also count as 'materials available'."""
        goal = _make_goal(
            goal_type="meta",
            description="Aktualizacja struktur wiedzy",
            created_at=self.now,
        )
        snapshot = {
            "files_by_status": {"learning": ["partial.txt"]},
            "new_files_available": [],
        }
        selected = self.selector.select_goal(
            [goal], {}, knowledge_snapshot=snapshot, now=self.now,
        )
        assert selected is not None

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_meta_non_learning_goal_not_gated_by_materials(self, _mock):
        """Meta goals without learning keywords ignore snapshot entirely."""
        goal = _make_goal(
            goal_type="meta",
            description="Zredukowanie zmeczenia operatora",
            created_at=self.now,
        )
        snapshot = {
            "files_by_status": {},
            "new_files_available": [],
        }
        selected = self.selector.select_goal(
            [goal], {}, knowledge_snapshot=snapshot, now=self.now,
        )
        assert selected is not None

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=False)
    def test_meta_learning_window_check_beats_materials_check(self, _mock):
        """Window check short-circuits before materials check."""
        goal = _make_goal(
            goal_type="meta",
            description="Autonomiczna nauka",
            created_at=self.now,
        )
        snapshot = {
            "files_by_status": {},
            "new_files_available": [{"file": "new1.txt"}],
        }
        selected = self.selector.select_goal(
            [goal], {}, knowledge_snapshot=snapshot, now=self.now,
        )
        assert selected is None

    # -- PlannerCore._enforce_learning_window ----------------------------

    @staticmethod
    def _bare_planner(off_window_used=0):
        planner = PlannerCore.__new__(PlannerCore)
        planner._deliberation = None
        planner._state = PlannerState()
        if off_window_used:
            planner._state.off_window_learn_date = time.strftime(
                "%Y-%m-%d", time.localtime())
            planner._state.off_window_learn_used = off_window_used
        return planner

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=False)
    def test_learn_redirected_to_noop_when_offwindow_budget_exhausted(self, _mock):
        """8b: once the daily off-window budget is spent, learn-family actions
        are again redirected to NOOP outside the window (throttle preserved)."""
        planner = self._bare_planner(off_window_used=OFF_WINDOW_LEARN_BUDGET)
        goal = _make_goal(goal_type="learning")
        action, reason = planner._enforce_learning_window(goal, ActionType.LEARN)
        assert action == ActionType.NOOP
        assert reason == "outside_learning_window"

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=False)
    def test_learn_allowed_offwindow_within_budget(self, _mock):
        """8b: outside the window the planner still allows a bounded number of
        learn-family actions per day (rhythm/budget), consuming one per call."""
        planner = self._bare_planner()  # full off-window budget
        goal = _make_goal(goal_type="learning")
        action, reason = planner._enforce_learning_window(goal, ActionType.LEARN)
        assert action == ActionType.LEARN
        assert reason is None
        assert planner._state.off_window_learn_used == 1
        assert planner._last_off_window_approved is True  # marks plan for executor

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=False)
    def test_offwindow_budget_not_spent_when_mode_blocks_heavy(self, _mock):
        """8b: in REDUCED / low health the degradation gate blocks heavy work,
        so the off-window budget must NOT be spent on an action that cannot
        run -- otherwise the daily allowance drains on no-ops."""
        planner = self._bare_planner()  # full off-window budget
        core = specced(HomeostasisCore)
        state = MagicMock()
        state.mode.value = "reduced"
        state.health_score = 0.5
        core.get_state.return_value = state
        planner._homeostasis_core = core
        planner.guard = specced(PlannerGuard)
        planner.guard.is_heavy_action_allowed.return_value = (False, "reduced")
        goal = _make_goal(goal_type="learning")
        action, reason = planner._enforce_learning_window(goal, ActionType.LEARN)
        assert action == ActionType.NOOP
        assert reason == "outside_learning_window"
        assert planner._state.off_window_learn_used == 0  # budget preserved

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=False)
    def test_executor_honors_off_window_approved_flag(self, _mock):
        """8b: the action executor's own window gate must honor a plan the
        planner already approved off-window (metadata off_window_approved),
        instead of re-blocking it as outside_learning_window (the 3rd gate that
        the in-vivo test caught wasting budget on a blocked learn)."""
        from agent_core.planner.action_executor import ActionExecutor
        ex = ActionExecutor()
        unmarked = create_plan(goal_id="g", goal_description="d",
                               action_type=ActionType.LEARN, action_params={})
        assert ex._is_outside_learning_window(unmarked) is True
        marked = create_plan(goal_id="g", goal_description="d",
                             action_type=ActionType.LEARN, action_params={},
                             metadata={"off_window_approved": True})
        assert ex._is_outside_learning_window(marked) is False

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_learn_preserved_inside_window(self, _mock):
        planner = self._bare_planner()
        goal = _make_goal(goal_type="learning")
        action, reason = planner._enforce_learning_window(goal, ActionType.LEARN)
        assert action == ActionType.LEARN
        assert reason is None

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=False)
    def test_user_goal_bypasses_window(self, _mock):
        planner = self._bare_planner()
        goal = _make_goal(goal_type="user")
        action, reason = planner._enforce_learning_window(goal, ActionType.LEARN)
        assert action == ActionType.LEARN
        assert reason is None

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=False)
    def test_forced_action_bypasses_window(self, _mock):
        planner = self._bare_planner()
        goal = _make_goal(
            goal_type="learning",
            metadata={"forced_action_type": "learn"},
        )
        action, reason = planner._enforce_learning_window(goal, ActionType.LEARN)
        assert action == ActionType.LEARN
        assert reason is None

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=False)
    def test_non_learning_action_untouched(self, _mock):
        """EVALUATE / CREATIVE / MAINTENANCE are never blocked."""
        planner = self._bare_planner()
        goal = _make_goal(goal_type="learning")
        for act in (ActionType.EVALUATE, ActionType.CREATIVE,
                    ActionType.MAINTENANCE, ActionType.NOOP):
            action, reason = planner._enforce_learning_window(goal, act)
            assert action == act
            assert reason is None

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=False)
    def test_k8_strategy_abandoned_on_redirect(self, _mock):
        """When K8 proposed the blocked action, its strategy is abandoned
        so deliberation rethinks instead of re-issuing the same step."""
        from agent_core.deliberation import Deliberation
        planner = self._bare_planner(off_window_used=OFF_WINDOW_LEARN_BUDGET)
        delib = specced(Deliberation)
        planner._deliberation = delib
        goal = _make_goal(goal_type="meta")
        delib_action = {"strategy_id": "strat-xyz", "step_order": 2}
        action, reason = planner._enforce_learning_window(
            goal, ActionType.LEARN, delib_action=delib_action,
        )
        assert action == ActionType.NOOP
        delib.abandon_strategy.assert_called_once()
        call_kwargs = delib.abandon_strategy.call_args.kwargs
        assert call_kwargs.get("reason") == "outside_learning_window"


class TestSaturationMetaFetch:
    """D1.5c (2026-04-22): when the library is saturated (no new files,
    nothing in progress), META-learning goals route to FETCH directly
    instead of being blocked (D1.5d original behavior) or wasted on LEARN
    (K8's default pick for goals with a topic).

    This restores Maria's autonomous path to pull new materials from the
    web when she has consumed everything locally.
    """

    def _saturated_context(self):
        return {
            "knowledge_snapshot": {
                "files_by_status": {"completed": ["a.txt", "b.txt"]},
                "new_files_available": [],
            },
            "evaluation_metrics": {},
        }

    def test_is_saturation_meta_goal_helper(self):
        """Helper returns True only when all conditions align."""
        from agent_core.planner.goal_selector import is_saturation_meta_goal

        saturated = {
            "files_by_status": {"completed": ["x"]},
            "new_files_available": [],
        }
        meta_learn = _make_goal(
            goal_type="meta",
            description="Eksploracja poza obecna domena wiedzy",
        )
        assert is_saturation_meta_goal(meta_learn, saturated) is True

        # Non-saturated snapshot -> False
        with_new = {
            "files_by_status": {},
            "new_files_available": [{"id": "n.txt"}],
        }
        assert is_saturation_meta_goal(meta_learn, with_new) is False

        # Non-meta goal -> False
        learning = _make_goal(goal_type="learning", description="Nauka")
        assert is_saturation_meta_goal(learning, saturated) is False

        # Meta goal without learning keyword -> False
        meta_other = _make_goal(goal_type="meta", description="Odpoczynek")
        assert is_saturation_meta_goal(meta_other, saturated) is False

        # No snapshot -> False (cannot determine saturation)
        assert is_saturation_meta_goal(meta_learn, None) is False

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_saturation_meta_routes_to_fetch_in_window(self, _mock, tmp_path):
        """Saturated meta-learning goal + in-window -> FETCH plan."""
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        goal = _make_goal(
            goal_type="meta",
            description="Eksploracja poza obecna domena wiedzy",
        )
        plan = planner._create_plan_for_goal(goal, self._saturated_context())
        assert plan.action_type == ActionType.FETCH
        assert plan.metadata.get("trigger") == "saturation_meta_fetch"

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_saturation_meta_propagates_topics(self, _mock, tmp_path):
        """Goal topics flow into FETCH action_params."""
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        goal = _make_goal(
            goal_type="meta",
            description="Ekspansja wiedzy",
            metadata={"topics": ["logika", "teoria mnogosci"]},
        )
        plan = planner._create_plan_for_goal(goal, self._saturated_context())
        assert plan.action_type == ActionType.FETCH
        assert plan.action_params.get("topics") == ["logika", "teoria mnogosci"]

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=False)
    def test_saturation_meta_blocked_outside_window_when_budget_exhausted(
        self, _mock, tmp_path
    ):
        """8b defense in depth: once the off-window budget is spent, the window
        guard again redirects the saturation-FETCH path to NOOP."""
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        planner._state.off_window_learn_date = time.strftime(
            "%Y-%m-%d", time.localtime())
        planner._state.off_window_learn_used = OFF_WINDOW_LEARN_BUDGET
        goal = _make_goal(
            goal_type="meta",
            description="Eksploracja poza obecna domena wiedzy",
        )
        plan = planner._create_plan_for_goal(goal, self._saturated_context())
        assert plan.action_type == ActionType.NOOP
        assert "outside_learning_window" in plan.action_params.get("reason", "")

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=False)
    def test_saturation_meta_fetch_allowed_offwindow_within_budget(
        self, _mock, tmp_path
    ):
        """8b: with off-window budget remaining, the saturation path still
        routes to FETCH so Maria can pull materials on weekends/nights."""
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        goal = _make_goal(
            goal_type="meta",
            description="Eksploracja poza obecna domena wiedzy",
        )
        plan = planner._create_plan_for_goal(goal, self._saturated_context())
        assert plan.action_type == ActionType.FETCH
        assert planner._state.off_window_learn_used == 1

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_non_saturation_meta_skips_fetch_bypass(self, _mock, tmp_path):
        """Meta goal with materials available falls through to normal path
        (K8 Deliberation or _decide_learning_action), not the FETCH bypass."""
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        goal = _make_goal(
            goal_type="meta",
            description="Eksploracja poza obecna domena wiedzy",
        )
        context = {
            "knowledge_snapshot": {
                "files_by_status": {"new": [{"id": "n.txt"}]},
                "new_files_available": [{"id": "n.txt"}],
            },
            "evaluation_metrics": {},
        }
        plan = planner._create_plan_for_goal(goal, context)
        # Should NOT have saturation trigger
        assert plan.metadata.get("trigger") != "saturation_meta_fetch"


# =============================================================================
# D2 (2026-04-26): K12 -> bulletin -> planner advisory layer
# Phase 1 is advisory-only: matching IMPROVEMENT entry annotates plan +
# trace, but execution is NOT blocked.
# =============================================================================


class TestPlannerBulletinAdvisory:

    def _make_planner(self, tmp_path):
        from agent_core.bulletin import BulletinStore
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        bulletin = BulletinStore(
            path=tmp_path / "cognitive_bulletin.jsonl"
        )
        planner.set_bulletin_store(bulletin)
        return planner, bulletin

    def _post_advisory(self, bulletin, action_hint, priority=0.9, summary="bad"):
        from agent_core.bulletin.bulletin_model import EntryType
        return bulletin.create_and_post(
            entry_type=EntryType.IMPROVEMENT,
            topic=f"Akcja '{action_hint}'",
            reason_code="k12_strategy_change",
            summary=summary,
            requested_by="self_analysis",
            priority=priority,
            metadata={"action_hint": action_hint},
        )

    def test_advisory_annotates_plan_when_action_matches(self, tmp_path):
        planner, bulletin = self._make_planner(tmp_path)
        entry = self._post_advisory(
            bulletin, "learn", priority=0.95,
            summary="learn 0% success - mechanism broken",
        )
        plan = create_plan(
            goal_id="g1",
            goal_description="naucz sie X",
            action_type=ActionType.LEARN,
        )
        planner._apply_bulletin_advisory(plan, trace=None)

        adv = plan.metadata.get("bulletin_advisory")
        assert adv is not None
        assert adv["entry_id"] == entry.entry_id
        assert adv["match_count"] == 1
        assert adv["priority"] == pytest.approx(0.95)

    def test_advisory_no_match_for_different_action(self, tmp_path):
        planner, bulletin = self._make_planner(tmp_path)
        self._post_advisory(bulletin, "fetch")
        plan = create_plan(
            goal_id="g1",
            goal_description="x",
            action_type=ActionType.LEARN,
        )
        planner._apply_bulletin_advisory(plan, trace=None)
        assert "bulletin_advisory" not in plan.metadata

    def test_advisory_silent_when_bulletin_unwired(self, tmp_path):
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        plan = create_plan(
            goal_id="g1", goal_description="x", action_type=ActionType.LEARN,
        )
        planner._apply_bulletin_advisory(plan, trace=None)
        assert "bulletin_advisory" not in plan.metadata

    def test_advisory_picks_highest_priority_when_multiple(self, tmp_path):
        planner, bulletin = self._make_planner(tmp_path)
        # Two open advisories for the same action; need different topics to
        # avoid bulletin dedup (find_open dedups on topic+type).
        from agent_core.bulletin.bulletin_model import EntryType
        bulletin.create_and_post(
            entry_type=EntryType.IMPROVEMENT,
            topic="Akcja 'learn' (slow)",
            reason_code="k12",
            summary="weak",
            requested_by="self_analysis",
            priority=0.6,
            metadata={"action_hint": "learn"},
        )
        top = bulletin.create_and_post(
            entry_type=EntryType.IMPROVEMENT,
            topic="Akcja 'learn' (broken)",
            reason_code="k12",
            summary="strong",
            requested_by="self_analysis",
            priority=0.95,
            metadata={"action_hint": "learn"},
        )
        plan = create_plan(
            goal_id="g1", goal_description="x", action_type=ActionType.LEARN,
        )
        planner._apply_bulletin_advisory(plan, trace=None)

        adv = plan.metadata["bulletin_advisory"]
        assert adv["entry_id"] == top.entry_id
        assert adv["match_count"] == 2

    def test_advisory_does_not_block_execution(self, tmp_path):
        """Phase 1 is advisory-only: plan keeps its action_type
        even when a matching warning is present."""
        planner, bulletin = self._make_planner(tmp_path)
        self._post_advisory(bulletin, "learn", priority=1.0)
        plan = create_plan(
            goal_id="g1", goal_description="x", action_type=ActionType.LEARN,
        )
        planner._apply_bulletin_advisory(plan, trace=None)
        # Plan kept the original action_type; only metadata was annotated.
        assert plan.action_type == ActionType.LEARN

    def test_advisory_resolved_entries_ignored(self, tmp_path):
        planner, bulletin = self._make_planner(tmp_path)
        entry = self._post_advisory(bulletin, "learn", priority=0.9)
        bulletin.resolve(entry.entry_id, "operator_dismissed")

        plan = create_plan(
            goal_id="g1", goal_description="x", action_type=ActionType.LEARN,
        )
        planner._apply_bulletin_advisory(plan, trace=None)
        assert "bulletin_advisory" not in plan.metadata

    def test_advisory_writes_trace_step(self, tmp_path):
        planner, bulletin = self._make_planner(tmp_path)
        self._post_advisory(bulletin, "learn", priority=0.9, summary="broken")

        class _StubTrace:
            def __init__(self):
                self.steps = []

            def add_step(self, source, action, status, payload):
                self.steps.append((source, action, status, payload))

        trace = _StubTrace()
        plan = create_plan(
            goal_id="g1", goal_description="x", action_type=ActionType.LEARN,
        )
        planner._apply_bulletin_advisory(plan, trace=trace)

        assert len(trace.steps) == 1
        source, action, status, payload = trace.steps[0]
        assert source == "bulletin"
        assert action == "advisory_match"
        assert status == "noted"
        assert payload["action"] == "learn"
        assert payload["match_count"] == 1


class TestMaintenanceThemeRouting:
    """Routing table for K12-escalator MAINTENANCE goals (BUG fix 2026-05-25).

    validate_failures must NOT route to VALIDATE (looping) — it routes to
    EVALUATE. exam_failures routes to REVIEW (re-study, not no-op MAINTENANCE).
    """

    def _make_maintenance_goal(self, theme: str):
        return _make_goal(
            goal_type="maintenance",
            priority=1.0,
            metadata={"theme_tag": theme, "metric": ""},
        )

    def test_validate_failures_routes_to_evaluate(self, planner_env):
        """validate_failures must not loop back to VALIDATE."""
        planner, _ = planner_env
        planner.set_homeostasis_core(_make_mock_core())
        planner.set_evaluation_observer(_make_mock_observer())
        planner._state.last_evaluation_ts = time.time()

        goal = self._make_maintenance_goal("validate_failures")
        planner.set_goal_store(_make_mock_goal_store([goal]))

        result = planner.run_cycle(60)
        assert result is not None
        assert result.action_type == ActionType.EVALUATE, (
            f"validate_failures must route to EVALUATE, got {result.action_type}"
        )

    def test_exam_failures_routes_to_review(self, planner_env):
        """exam_failures should trigger a review pass, not a silent MAINTENANCE no-op."""
        planner, _ = planner_env
        planner.set_homeostasis_core(_make_mock_core())
        planner.set_evaluation_observer(_make_mock_observer())
        planner._state.last_evaluation_ts = time.time()

        goal = self._make_maintenance_goal("exam_failures")
        planner.set_goal_store(_make_mock_goal_store([goal]))

        result = planner.run_cycle(60)
        assert result is not None
        assert result.action_type == ActionType.REVIEW, (
            f"exam_failures must route to REVIEW, got {result.action_type}"
        )


class TestNoGoalsObservability:
    """8a: a no_goals skip must record WHY each active goal was infeasible
    (per-goal reasons), instead of the historical empty reasons list that hid
    the cause behind 87% of cycles."""

    def _planner(self, tmp_path, goals):
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        planner._cleanup_stale_goals = lambda: None

        class _Store:
            def get_active(self_inner):
                return goals

        planner._goal_store = _Store()
        return planner

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=False)
    def test_infeasible_reasons_captured(self, _mock, tmp_path):
        planner = self._planner(tmp_path, [
            _make_goal(goal_type="learning", description="Nauka tematu: x"),
        ])
        # exhaust the off-window budget so the learning goal is infeasible
        planner._state.off_window_learn_date = time.strftime(
            "%Y-%m-%d", time.localtime())
        planner._state.off_window_learn_used = OFF_WINDOW_LEARN_BUDGET
        ranked = planner._select_ranked_goals(
            {"evaluation_metrics": {}, "knowledge_snapshot": None})
        assert ranked == []
        assert len(planner._last_skip_reasons) == 1
        assert planner._last_skip_reasons[0]["reason"] == "outside learning window"
        assert planner._last_skip_reasons[0]["type"] == "learning"

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=False)
    def test_offwindow_goal_feasible_within_budget(self, _mock, tmp_path):
        planner = self._planner(tmp_path, [
            _make_goal(goal_type="learning", description="Nauka tematu: x"),
        ])
        ranked = planner._select_ranked_goals(
            {"evaluation_metrics": {}, "knowledge_snapshot": None})
        assert len(ranked) == 1  # off-window budget available -> feasible
        assert planner._last_skip_reasons == []


class TestOffWindowBudget:
    """8b: the daily off-window learn budget resets at Berlin midnight (P3 #5)."""

    def test_budget_resets_on_new_day(self, tmp_path):
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        assert planner._off_window_budget_remaining() == OFF_WINDOW_LEARN_BUDGET
        for _ in range(OFF_WINDOW_LEARN_BUDGET):
            planner._consume_off_window_budget()
        assert planner._off_window_budget_remaining() == 0
        # a stale date from a previous day -> budget resets
        planner._state.off_window_learn_date = "2000-01-01"
        assert planner._off_window_budget_remaining() == OFF_WINDOW_LEARN_BUDGET

    def test_budget_date_key_is_berlin(self, tmp_path):
        # P3 (#5): "today" is computed in Europe/Berlin (the same zone as the
        # window), not naive OS-local time, so a future OS re-zone cannot desync
        # the budget reset from the window it throttles.
        from agent_core.environment.environment_model import berlin_now
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        assert planner._berlin_date_key() == berlin_now().strftime("%Y-%m-%d")
        planner._consume_off_window_budget()
        assert (planner._state.off_window_learn_date
                == berlin_now().strftime("%Y-%m-%d"))


# ═══════════════════════════════════════════════════════
# _update_beliefs_from_validation persistence (dead flush regression)
# ═══════════════════════════════════════════════════════


class TestUpdateBeliefsFromValidationPersistence:
    """Dead store.flush() regression (found 2026-06-10): BeliefStore
    persists via save(), flush() never existed -- the AttributeError fell
    into the broad except, so the method reported 0 despite applying
    revisions in memory. MUST use a REAL BeliefStore: a MagicMock
    world_model invents flush() and hides the bug (mock-hidden)."""

    def test_revisions_counted_and_persisted(self, tmp_path):
        from types import SimpleNamespace

        from agent_core.world_model.belief_model import (
            BeliefSource,
            BeliefType,
            EntityType,
            create_belief,
        )
        from agent_core.world_model.belief_store import BeliefStore

        file_id = "input_042_fotosynteza.txt"
        beliefs_path = tmp_path / "beliefs.jsonl"
        store = BeliefStore(beliefs_path)
        store.add(create_belief(
            entity="fotosynteza",
            entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION,
            content="Roslina przetwarza swiatlo w energie",
            confidence=0.5,
            source=BeliefSource.LEARNING,
            source_id=file_id,
        ))
        store.save()

        executor = ActionExecutor()
        executor.set_world_model(SimpleNamespace(store=store))

        updated = executor._update_beliefs_from_validation(file_id, 0.83)

        assert updated == 1            # was 0 with the dead flush()
        assert store._dirty == set()   # save() ran inside the method

        # The revision survives a cold reload -- it reached the JSONL.
        reloaded = BeliefStore(beliefs_path)
        reloaded.load()
        current = [
            b for b in reloaded.get_current() if b.source_id == file_id
        ]
        assert len(current) == 1
        assert current[0].confidence == pytest.approx(0.5 * 0.6 + 0.83 * 0.4)
        assert current[0].belief_type == BeliefType.FACT  # 0.83 promotes
