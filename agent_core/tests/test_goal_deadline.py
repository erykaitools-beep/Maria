"""Tests for deadline urgency in goal selection (Etap B).

REAL Goal objects (create_goal carries the deadline field) + a real
GoalSelector. USER goals are used for selection tests because they are always
feasible, isolating the urgency ordering from feasibility gates.
"""

import logging
import time

import pytest

from agent_core.goals.goal_model import GoalType, GoalStatus, create_goal
from agent_core.goals.store import GoalStore
from agent_core.planner.planner_core import PlannerCore
from agent_core.planner.goal_selector import (
    GoalSelector,
    deadline_mode,
    deadline_multiplier,
    DEADLINE_URGENT_WINDOW_SEC,
    DEADLINE_OVERDUE_BOOST,
    DEADLINE_BOOST_CAP,
)

NOW = 1_700_000_000.0


def _goal(gid, priority=0.5, deadline=None, created_at=NOW):
    g = create_goal(GoalType.USER, gid, priority, status=GoalStatus.ACTIVE,
                    deadline=deadline, goal_id=gid)
    g.created_at = created_at
    return g


class TestDeadlineMode:
    @pytest.mark.parametrize("val,expected", [
        (None, "off"), ("", "off"), ("off", "off"), ("false", "off"),
        ("observe", "observe"), (" OBSERVE ", "observe"),
        ("cutover", "cutover"), ("on", "cutover"), ("1", "cutover"),
        ("armed", "cutover"),
    ])
    def test_parse(self, val, expected):
        assert deadline_mode(val) == expected


class TestDeadlineMultiplier:
    def test_none_deadline(self):
        assert deadline_multiplier(_goal("g"), NOW) == 1.0

    def test_overdue(self):
        g = _goal("g", deadline=NOW - 3600)  # 1h past
        assert deadline_multiplier(g, NOW) == DEADLINE_OVERDUE_BOOST

    def test_due_now_ramps_to_two(self):
        g = _goal("g", deadline=NOW + 1)  # essentially due
        assert deadline_multiplier(g, NOW) == pytest.approx(2.0, abs=0.01)

    def test_half_window(self):
        g = _goal("g", deadline=NOW + DEADLINE_URGENT_WINDOW_SEC / 2)
        # 1.0 + (1.0 - 0.5) = 1.5
        assert deadline_multiplier(g, NOW) == pytest.approx(1.5)

    def test_far_deadline(self):
        g = _goal("g", deadline=NOW + 10 * DEADLINE_URGENT_WINDOW_SEC)
        assert deadline_multiplier(g, NOW) == 1.0

    def test_clamped_to_cap(self):
        g = _goal("g", deadline=NOW - 100 * 3600)  # very overdue
        assert deadline_multiplier(g, NOW) <= DEADLINE_BOOST_CAP


class TestEffectivePriorityModes:
    def setup_method(self):
        self.sel = GoalSelector()

    def test_off_ignores_deadline(self):
        g = _goal("g", priority=0.5, deadline=NOW - 3600)  # overdue
        base = 0.5  # fresh -> aging 0
        assert self.sel._compute_effective_priority(g, NOW, "off") == pytest.approx(base)

    def test_observe_does_not_apply(self):
        g = _goal("g", priority=0.5, deadline=NOW - 3600)
        # observe computes+logs the multiplier but must NOT change the score
        assert self.sel._compute_effective_priority(g, NOW, "observe") == pytest.approx(0.5)

    def test_cutover_applies(self):
        g = _goal("g", priority=0.5, deadline=NOW - 3600)  # overdue -> x3.0
        assert self.sel._compute_effective_priority(g, NOW, "cutover") == pytest.approx(1.5)

    def test_default_dmode_reads_env(self, monkeypatch):
        # No explicit dmode -> the scorer reads the flag itself, so a future
        # call site that forgets to pass it can never silently disable the
        # deadline path again (the 03-31..07-06 dead-wire regression class).
        g = _goal("g", priority=0.5, deadline=NOW - 3600)
        monkeypatch.delenv("GOAL_DEADLINE_ENABLED", raising=False)
        assert self.sel._compute_effective_priority(g, NOW) == pytest.approx(0.5)
        monkeypatch.setenv("GOAL_DEADLINE_ENABLED", "cutover")
        assert self.sel._compute_effective_priority(g, NOW) == pytest.approx(1.5)

    def test_mark_resets_when_deadline_extended(self, caplog):
        # Ramp -> log; extension out of the ramp clears the mark; re-entry
        # must log a fresh line (observe evidence must not be suppressed).
        g = _goal("g", priority=0.5, deadline=NOW + 3600)
        with caplog.at_level(logging.INFO):
            self.sel._compute_effective_priority(g, NOW, "observe")
            self.sel._compute_effective_priority(g, NOW, "observe")  # dedup
            g.deadline = NOW + 10 * 86400  # extended far out -> mult 1.0
            self.sel._compute_effective_priority(g, NOW, "observe")
            g.deadline = NOW + 3600  # re-enters the ramp
            self.sel._compute_effective_priority(g, NOW, "observe")
        assert caplog.text.count("[DEADLINE/observe] goal g") == 2

    def test_prune_deadline_marks(self):
        self.sel._deadline_log_marks = {"gone": 1.5, "alive": 2.0}
        self.sel.prune_deadline_marks({"alive"})
        assert self.sel._deadline_log_marks == {"alive": 2.0}

    def test_no_deadline_unchanged_in_cutover(self):
        # The deadline=None majority must score identically regardless of mode.
        g = _goal("g", priority=0.7)
        off = self.sel._compute_effective_priority(g, NOW, "off")
        cut = self.sel._compute_effective_priority(g, NOW, "cutover")
        assert off == cut == pytest.approx(0.7)


class TestSelectionReorders:
    def setup_method(self):
        self.sel = GoalSelector()

    def test_near_deadline_wins_in_cutover(self, monkeypatch):
        monkeypatch.setenv("GOAL_DEADLINE_ENABLED", "cutover")
        near = _goal("near", priority=0.5, deadline=NOW + 3600)   # 1h left -> boosted
        far = _goal("far", priority=0.5, deadline=NOW + 30 * 86400)  # far -> x1.0
        selected = self.sel.select_goal([far, near], {}, now=NOW)
        assert selected.id == "near"

    def test_order_unchanged_when_off(self, monkeypatch):
        monkeypatch.delenv("GOAL_DEADLINE_ENABLED", raising=False)
        near = _goal("near", priority=0.5, deadline=NOW + 3600)
        higher = _goal("higher", priority=0.6)  # no deadline, higher base
        selected = self.sel.select_goal([near, higher], {}, now=NOW)
        # off -> deadline ignored -> plain priority wins
        assert selected.id == "higher"

    def test_observe_does_not_reorder(self, monkeypatch):
        monkeypatch.setenv("GOAL_DEADLINE_ENABLED", "observe")
        near = _goal("near", priority=0.5, deadline=NOW + 3600)
        higher = _goal("higher", priority=0.6)
        selected = self.sel.select_goal([near, higher], {}, now=NOW)
        # observe logs urgency but ranking stays priority-based
        assert selected.id == "higher"


class TestDeadlineReaper:
    def _planner(self, tmp_path, store):
        p = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        p.set_goal_store(store)
        return p

    def _store_with(self, tmp_path, *goals):
        store = GoalStore(tmp_path / "goals.jsonl")
        for g in goals:
            store.create(g)
        return store

    def _mk(self, gid, gtype, deadline, status=GoalStatus.ACTIVE):
        return create_goal(gtype, gid, 0.6, status=status, deadline=deadline,
                           goal_id=gid)

    def test_flag_off_no_reap(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GOAL_DEADLINE_REAP_ENABLED", raising=False)
        store = self._store_with(
            tmp_path, self._mk("g", GoalType.USER, NOW - 3600))
        planner = self._planner(tmp_path, store)
        n = planner._reap_overdue_deadlines(NOW)
        assert n == 0
        assert store.get("g").status == GoalStatus.ACTIVE

    def test_overdue_user_reaped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GOAL_DEADLINE_REAP_ENABLED", "on")
        store = self._store_with(
            tmp_path, self._mk("g", GoalType.USER, NOW - 7200))
        planner = self._planner(tmp_path, store)
        n = planner._reap_overdue_deadlines(NOW)
        assert n == 1
        g = store.get("g")
        assert g.status == GoalStatus.FAILED
        assert "deadline_overdue" in g.audit_trail[-1].reason
        assert g.audit_trail[-1].actor == "deadline_reaper"

    def test_maintenance_exempt(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GOAL_DEADLINE_REAP_ENABLED", "on")
        store = self._store_with(
            tmp_path, self._mk("m", GoalType.MAINTENANCE, NOW - 3600))
        planner = self._planner(tmp_path, store)
        assert planner._reap_overdue_deadlines(NOW) == 0
        assert store.get("m").status == GoalStatus.ACTIVE

    def test_meta_exempt(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GOAL_DEADLINE_REAP_ENABLED", "on")
        store = self._store_with(
            tmp_path, self._mk("meta", GoalType.META, NOW - 3600))
        planner = self._planner(tmp_path, store)
        assert planner._reap_overdue_deadlines(NOW) == 0
        assert store.get("meta").status == GoalStatus.ACTIVE

    def test_future_deadline_not_reaped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GOAL_DEADLINE_REAP_ENABLED", "on")
        store = self._store_with(
            tmp_path, self._mk("g", GoalType.USER, NOW + 86400))
        planner = self._planner(tmp_path, store)
        assert planner._reap_overdue_deadlines(NOW) == 0

    def test_no_deadline_not_reaped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GOAL_DEADLINE_REAP_ENABLED", "on")
        g = create_goal(GoalType.USER, "g", 0.6, status=GoalStatus.ACTIVE,
                        goal_id="g")
        store = self._store_with(tmp_path, g)
        planner = self._planner(tmp_path, store)
        assert planner._reap_overdue_deadlines(NOW) == 0

    def test_reap_persists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GOAL_DEADLINE_REAP_ENABLED", "on")
        path = tmp_path / "goals.jsonl"
        store = GoalStore(path)
        store.create(self._mk("g", GoalType.USER, NOW - 3600))
        planner = self._planner(tmp_path, store)
        planner._reap_overdue_deadlines(NOW)
        reloaded = GoalStore(path)
        reloaded.load()
        assert reloaded.get("g").status == GoalStatus.FAILED

    def test_wired_into_cleanup(self, tmp_path, monkeypatch):
        # Confirm the reaper is reached via the live _cleanup_stale_goals path.
        monkeypatch.setenv("GOAL_DEADLINE_REAP_ENABLED", "on")
        store = self._store_with(
            tmp_path, self._mk("g", GoalType.USER, NOW - 3600))
        planner = self._planner(tmp_path, store)
        planner._cleanup_stale_goals()
        assert store.get("g").status == GoalStatus.FAILED


class TestLiveRankedPath:
    """The daemon ranks goals via PlannerCore._select_ranked_goals -- NOT via
    select_goal() (zero callers since the 03-31 ranked rewrite) nor
    rank_goals() (REPL display only). The original 06-22 wiring read
    GOAL_DEADLINE_ENABLED only on those dead entrypoints, so the live daemon
    never saw the flag (wrong-component-tested; fixed 2026-07-06). These
    tests drive the REAL ranked path with a REAL GoalStore to keep it wired.
    """

    def _planner(self, tmp_path, store):
        p = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        p.set_goal_store(store)
        return p

    def _mk(self, gid, priority, deadline=None, created_at=None):
        g = create_goal(GoalType.USER, gid, priority,
                        status=GoalStatus.ACTIVE, deadline=deadline,
                        goal_id=gid)
        # Equal, fresh created_at -> aging identical for every goal, so the
        # ranking difference under test comes from the deadline alone.
        g.created_at = created_at if created_at is not None else time.time()
        return g

    def _store_with(self, tmp_path, *goals):
        store = GoalStore(tmp_path / "goals.jsonl")
        for g in goals:
            store.create(g)
        return store

    def _ranked_ids(self, planner):
        ranked = planner._select_ranked_goals(
            {"evaluation_metrics": {}, "knowledge_snapshot": None})
        return [g.id for g in ranked]

    def test_flag_absent_no_boost_no_log(self, tmp_path, monkeypatch, caplog):
        monkeypatch.delenv("GOAL_DEADLINE_ENABLED", raising=False)
        monkeypatch.delenv("GOAL_DEADLINE_REAP_ENABLED", raising=False)
        now = time.time()
        store = self._store_with(
            tmp_path,
            self._mk("near", 0.5, deadline=now + 3600),
            self._mk("higher", 0.6),
        )
        planner = self._planner(tmp_path, store)
        with caplog.at_level(logging.INFO):
            ids = self._ranked_ids(planner)
        assert ids[0] == "higher"
        assert "[DEADLINE/" not in caplog.text

    def test_observe_logs_but_ranking_unchanged(self, tmp_path, monkeypatch,
                                                caplog):
        monkeypatch.setenv("GOAL_DEADLINE_ENABLED", "observe")
        monkeypatch.delenv("GOAL_DEADLINE_REAP_ENABLED", raising=False)
        now = time.time()
        store = self._store_with(
            tmp_path,
            self._mk("near", 0.5, deadline=now + 3600),  # <24h -> ~x1.96
            self._mk("higher", 0.6),
        )
        planner = self._planner(tmp_path, store)
        with caplog.at_level(logging.INFO):
            ids = self._ranked_ids(planner)
        # observe: urgency is logged but must NOT re-order
        assert ids[0] == "higher"
        assert "[DEADLINE/observe] goal near" in caplog.text

    def test_cutover_reorders_live_path(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setenv("GOAL_DEADLINE_ENABLED", "cutover")
        monkeypatch.delenv("GOAL_DEADLINE_REAP_ENABLED", raising=False)
        now = time.time()
        store = self._store_with(
            tmp_path,
            self._mk("near", 0.5, deadline=now + 3600),  # 0.5*~1.96 > 0.6
            self._mk("higher", 0.6),
        )
        planner = self._planner(tmp_path, store)
        with caplog.at_level(logging.INFO):
            ids = self._ranked_ids(planner)
        assert ids[0] == "near"
        assert "[DEADLINE/cutover] goal near" in caplog.text

    def test_observe_log_dedup_across_cycles(self, tmp_path, monkeypatch,
                                             caplog):
        # The live planner re-ranks every ~60s; without dedup a goal inside
        # its 24h ramp logs ~1440 near-identical lines/day (the
        # ROLLUP/observe spam class). Same rounded multiplier -> one line.
        monkeypatch.setenv("GOAL_DEADLINE_ENABLED", "observe")
        monkeypatch.delenv("GOAL_DEADLINE_REAP_ENABLED", raising=False)
        now = time.time()
        store = self._store_with(
            tmp_path, self._mk("near", 0.5, deadline=now + 3600))
        planner = self._planner(tmp_path, store)
        with caplog.at_level(logging.INFO):
            self._ranked_ids(planner)
            self._ranked_ids(planner)
            self._ranked_ids(planner)
        assert caplog.text.count("[DEADLINE/observe] goal near") == 1
