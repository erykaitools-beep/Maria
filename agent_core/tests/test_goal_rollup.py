"""Tests for parent-goal rollup -- sub-goal tree completion (Etap B).

REAL GoalStore + tmp_path throughout (MagicMock would swallow bad kwargs and
hide a missing _mark_dirty). Each persistence assertion reloads a fresh store
from disk to catch a silent dirty-mark regression.
"""

import pytest

from agent_core.goals.goal_model import (
    GoalType,
    GoalStatus,
    create_goal,
)
from agent_core.goals.store import GoalStore
from agent_core.goals import rollup as rollup_mod
from agent_core.planner.planner_core import PlannerCore


def _store(tmp_path):
    return GoalStore(tmp_path / "goals.jsonl")


def _parent(store, status=GoalStatus.ACTIVE, gid="proj", progress=0.0):
    g = create_goal(GoalType.USER, "Project", 0.8, status=status, goal_id=gid)
    g.progress = progress
    store.create(g)
    return g


def _child(store, parent_id, status, gid, gtype=GoalType.USER):
    g = create_goal(gtype, f"child-{gid}", 0.7, status=status,
                    parent_goal_id=parent_id, goal_id=gid)
    store.create(g)
    return g


# --------------------------------------------------------------------------- #
# rollup_mode parser
# --------------------------------------------------------------------------- #
class TestRollupMode:
    @pytest.mark.parametrize("val,expected", [
        (None, "off"), ("", "off"), ("off", "off"), ("0", "off"),
        ("false", "off"), ("nonsense", "off"),
        ("observe", "observe"), ("OBSERVE", "observe"), (" observe ", "observe"),
        ("cutover", "cutover"), ("on", "cutover"), ("1", "cutover"),
        ("true", "cutover"), ("armed", "cutover"),
    ])
    def test_parse(self, val, expected):
        assert rollup_mod.rollup_mode(val) == expected


# --------------------------------------------------------------------------- #
# compute_rollups (pure, read-only)
# --------------------------------------------------------------------------- #
class TestComputeRollups:
    def test_all_achieved_decides_achieved(self, tmp_path):
        store = _store(tmp_path)
        _parent(store)
        _child(store, "proj", GoalStatus.ACHIEVED, "c1")
        _child(store, "proj", GoalStatus.ACHIEVED, "c2")
        decisions = rollup_mod.compute_rollups(store)
        assert len(decisions) == 1
        d = decisions[0]
        assert d.parent_id == "proj"
        assert d.target_status == GoalStatus.ACHIEVED
        assert d.reason == "all_children_achieved"
        assert d.ratio == 1.0
        assert d.children_achieved == 2

    def test_partial_decides_progress_only(self, tmp_path):
        store = _store(tmp_path)
        _parent(store)
        _child(store, "proj", GoalStatus.ACHIEVED, "c1")
        _child(store, "proj", GoalStatus.ACTIVE, "c2")
        decisions = rollup_mod.compute_rollups(store)
        assert len(decisions) == 1
        d = decisions[0]
        assert d.target_status is None
        assert d.ratio == 0.5

    def test_any_failed_decides_failed(self, tmp_path):
        store = _store(tmp_path)
        _parent(store)
        _child(store, "proj", GoalStatus.ACHIEVED, "c1")
        _child(store, "proj", GoalStatus.FAILED, "c2")
        decisions = rollup_mod.compute_rollups(store)
        assert len(decisions) == 1
        d = decisions[0]
        assert d.target_status == GoalStatus.FAILED
        assert "c2" in d.reason
        assert d.children_failed == 1

    def test_maintenance_parent_skipped(self, tmp_path):
        # The live seed tree: health (MAINTENANCE) <- ram/cpu. Even with both
        # children at progress 1.0, rollup must NOT complete health.
        store = _store(tmp_path)
        health = create_goal(GoalType.MAINTENANCE, "Health", 1.0,
                             status=GoalStatus.ACTIVE, goal_id="goal-maint-health")
        store.create(health)
        ram = _child(store, "goal-maint-health", GoalStatus.ACHIEVED, "ram",
                     gtype=GoalType.MAINTENANCE)
        cpu = _child(store, "goal-maint-health", GoalStatus.ACHIEVED, "cpu",
                     gtype=GoalType.MAINTENANCE)
        decisions = rollup_mod.compute_rollups(store)
        assert decisions == []

    def test_terminal_parent_skipped(self, tmp_path):
        store = _store(tmp_path)
        _parent(store, status=GoalStatus.ACHIEVED)
        _child(store, "proj", GoalStatus.ACHIEVED, "c1")
        assert rollup_mod.compute_rollups(store) == []

    def test_no_children_skipped(self, tmp_path):
        store = _store(tmp_path)
        _parent(store)
        assert rollup_mod.compute_rollups(store) == []

    def test_progress_noop_suppressed(self, tmp_path):
        # Parent already records the exact terminal fraction -> no decision.
        store = _store(tmp_path)
        _parent(store, progress=0.5)
        _child(store, "proj", GoalStatus.ACHIEVED, "c1")
        _child(store, "proj", GoalStatus.ACTIVE, "c2")
        assert rollup_mod.compute_rollups(store) == []


# --------------------------------------------------------------------------- #
# apply_rollup (real store, persistence)
# --------------------------------------------------------------------------- #
class TestApplyRollup:
    def test_all_achieved_completes_parent_and_persists(self, tmp_path):
        path = tmp_path / "goals.jsonl"
        store = GoalStore(path)
        _parent(store)
        _child(store, "proj", GoalStatus.ACHIEVED, "c1")
        _child(store, "proj", GoalStatus.ACHIEVED, "c2")
        for d in rollup_mod.compute_rollups(store):
            rollup_mod.apply_rollup(store, d)
        store.save()

        reloaded = GoalStore(path)
        reloaded.load()
        parent = reloaded.get("proj")
        assert parent.status == GoalStatus.ACHIEVED
        assert parent.progress == 1.0
        assert parent.outcome["closed_by"] == "rollup"
        assert parent.outcome["children_achieved"] == 2
        # audit entry recorded the rollup actor
        assert any(a.actor == "goal_rollup" for a in parent.audit_trail)

    def test_partial_persists_fraction(self, tmp_path):
        path = tmp_path / "goals.jsonl"
        store = GoalStore(path)
        _parent(store)
        _child(store, "proj", GoalStatus.ACHIEVED, "c1")
        _child(store, "proj", GoalStatus.ACTIVE, "c2")
        for d in rollup_mod.compute_rollups(store):
            rollup_mod.apply_rollup(store, d)
        store.save()

        reloaded = GoalStore(path)
        reloaded.load()
        parent = reloaded.get("proj")
        assert parent.status == GoalStatus.ACTIVE
        assert parent.progress == 0.5

    def test_failed_child_fails_parent_not_achieved(self, tmp_path):
        # The ratio==1.0 trap: all children terminal but one FAILED. Status must
        # be set FIRST so update_progress(1.0) cannot auto-ACHIEVE the parent.
        store = _store(tmp_path)
        _parent(store)
        _child(store, "proj", GoalStatus.ACHIEVED, "c1")
        _child(store, "proj", GoalStatus.FAILED, "c2")
        for d in rollup_mod.compute_rollups(store):
            rollup_mod.apply_rollup(store, d)
        parent = store.get("proj")
        assert parent.status == GoalStatus.FAILED
        assert parent.status != GoalStatus.ACHIEVED

    def test_pending_parent_achieved_explicitly(self, tmp_path):
        # update_progress only auto-achieves ACTIVE goals; a PENDING parent needs
        # the explicit transition (which apply_rollup makes via update_status).
        store = _store(tmp_path)
        _parent(store, status=GoalStatus.PENDING)
        _child(store, "proj", GoalStatus.ACHIEVED, "c1")
        for d in rollup_mod.compute_rollups(store):
            rollup_mod.apply_rollup(store, d)
        assert store.get("proj").status == GoalStatus.ACHIEVED

    def test_idempotent_rerun(self, tmp_path):
        store = _store(tmp_path)
        _parent(store)
        _child(store, "proj", GoalStatus.ACHIEVED, "c1")
        for d in rollup_mod.compute_rollups(store):
            rollup_mod.apply_rollup(store, d)
        # Parent is now terminal -> second pass yields no decisions.
        assert rollup_mod.compute_rollups(store) == []


# --------------------------------------------------------------------------- #
# planner phase _rollup_subgoals (mode gating)
# --------------------------------------------------------------------------- #
class TestPlannerRollupPhase:
    def _planner(self, tmp_path, store):
        p = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        p.set_goal_store(store)
        return p

    def test_off_does_not_mutate(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GOAL_ROLLUP_ENABLED", raising=False)
        store = _store(tmp_path)
        _parent(store)
        _child(store, "proj", GoalStatus.ACHIEVED, "c1")
        planner = self._planner(tmp_path, store)
        planner._rollup_subgoals({})
        assert store.get("proj").status == GoalStatus.ACTIVE

    def test_observe_does_not_mutate(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GOAL_ROLLUP_ENABLED", "observe")
        store = _store(tmp_path)
        _parent(store)
        _child(store, "proj", GoalStatus.ACHIEVED, "c1")
        planner = self._planner(tmp_path, store)
        planner._rollup_subgoals({})
        # observe logs the intended transition but writes nothing.
        assert store.get("proj").status == GoalStatus.ACTIVE
        assert store.get("proj").progress == 0.0

    def test_cutover_mutates_and_persists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GOAL_ROLLUP_ENABLED", "cutover")
        path = tmp_path / "goals.jsonl"
        store = GoalStore(path)
        _parent(store)
        _child(store, "proj", GoalStatus.ACHIEVED, "c1")
        _child(store, "proj", GoalStatus.ACHIEVED, "c2")
        planner = self._planner(tmp_path, store)
        planner._rollup_subgoals({})

        reloaded = GoalStore(path)
        reloaded.load()
        assert reloaded.get("proj").status == GoalStatus.ACHIEVED
