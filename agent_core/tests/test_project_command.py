"""Tests for the /project + /projects operator commands (Etap B "kran").

The operator producer that makes the dormant sub-goal tree + deadline machinery
live: /project creates a parent USER goal owning child USER goals (parent_goal_id
set, deadline inherited). REAL GoalStore throughout.
"""

import time
from types import SimpleNamespace

import pytest

from agent_core.goals.store import GoalStore
from agent_core.goals.goal_model import GoalType, GoalStatus
from agent_core.goals import rollup as rollup_mod
from agent_core.modules.homeostasis_telegram_commands import (
    register_telegram_commands as _register,
    _parse_project_deadline,
    _parse_project_args,
    MAX_PROJECT_SUBGOALS,
)


class FakeBridge:
    def __init__(self):
        self.handlers = {}

    def register_command(self, command, handler):
        self.handlers[command] = handler


def _harness(tmp_path):
    store = GoalStore(tmp_path / "goals.jsonl")
    ctx = SimpleNamespace(goal_store=store)
    bridge = FakeBridge()
    _register(bridge, ctx)
    return bridge, store


# --------------------------------------------------------------------------- #
# module-level parsers
# --------------------------------------------------------------------------- #
class TestParseDeadline:
    def test_blank_is_none(self):
        assert _parse_project_deadline("") is None
        assert _parse_project_deadline("   ") is None
        assert _parse_project_deadline(None) is None

    def test_relative_days(self):
        ts = _parse_project_deadline("za 30 dni")
        assert ts > time.time() + 29 * 86400

    def test_iso_date(self):
        ts = _parse_project_deadline("2026-07-15")
        assert ts == pytest.approx(
            time.mktime(time.strptime("2026-07-15 23:59", "%Y-%m-%d %H:%M")), abs=120)

    def test_iso_datetime(self):
        ts = _parse_project_deadline("2026-07-15 18:00")
        assert ts == pytest.approx(
            time.mktime(time.strptime("2026-07-15 18:00", "%Y-%m-%d %H:%M")), abs=120)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_project_deadline("kiedys tam")


class TestParseArgs:
    def test_name_only(self):
        name, dl, subs = _parse_project_args("Moj projekt")
        assert name == "Moj projekt"
        assert dl == ""
        assert subs == []

    def test_name_and_deadline(self):
        name, dl, subs = _parse_project_args("Projekt | za 30 dni")
        assert name == "Projekt"
        assert dl == "za 30 dni"
        assert subs == []

    def test_full(self):
        name, dl, subs = _parse_project_args("P | jutro 9:00 | a ; b ; c")
        assert name == "P"
        assert dl == "jutro 9:00"
        assert subs == ["a", "b", "c"]

    def test_newline_subgoals(self):
        name, dl, subs = _parse_project_args("P |  | a\nb\n c ")
        assert subs == ["a", "b", "c"]

    def test_blank_subgoals_dropped(self):
        _, _, subs = _parse_project_args("P | | a ; ; ; b")
        assert subs == ["a", "b"]


# --------------------------------------------------------------------------- #
# /project handler
# --------------------------------------------------------------------------- #
class TestProjectCommand:
    def test_registered(self, tmp_path):
        bridge, _ = _harness(tmp_path)
        assert "project" in bridge.handlers
        assert "projects" in bridge.handlers

    def test_creates_parent_and_children(self, tmp_path):
        bridge, store = _harness(tmp_path)
        out = bridge.handlers["project"](
            "Hiszpanski | za 30 dni | slownictwo ; gramatyka ; rozmowki")
        assert "Projekt utworzony" in out

        parents = [g for g in store.get_all() if g.metadata.get("project")]
        assert len(parents) == 1
        parent = parents[0]
        assert parent.type == GoalType.USER
        assert parent.status == GoalStatus.ACTIVE
        assert parent.deadline is not None
        assert parent.created_by == "operator"

        children = store.get_children(parent.id)
        assert len(children) == 3
        assert {c.description for c in children} == {
            "slownictwo", "gramatyka", "rozmowki"}
        # children inherit parent_goal_id + the deadline (urgency boosts leaves)
        for c in children:
            assert c.parent_goal_id == parent.id
            assert c.deadline == parent.deadline
            # topics tap: sub-goal name feeds the learn filter + B2 FETCH pump
            assert c.metadata["topics"] == [c.description]

    def test_no_name_returns_usage(self, tmp_path):
        bridge, store = _harness(tmp_path)
        out = bridge.handlers["project"]("")
        assert "Uzycie" in out
        assert store.get_all() == []

    def test_bad_deadline_rejected_no_goal_created(self, tmp_path):
        bridge, store = _harness(tmp_path)
        out = bridge.handlers["project"]("Projekt | kiedys tam | a ; b")
        assert "Termin" in out
        # strict upfront validation: nothing persisted on a bad deadline
        assert store.get_all() == []

    def test_too_many_subgoals_rejected(self, tmp_path):
        bridge, store = _harness(tmp_path)
        subs = " ; ".join(f"s{i}" for i in range(MAX_PROJECT_SUBGOALS + 1))
        out = bridge.handlers["project"](f"Projekt | | {subs}")
        assert "Za duzo" in out
        assert store.get_all() == []

    def test_project_without_subgoals(self, tmp_path):
        bridge, store = _harness(tmp_path)
        out = bridge.handlers["project"]("Sam cel | jutro 18:00")
        assert "Projekt utworzony" in out
        parents = [g for g in store.get_all() if g.metadata.get("project")]
        assert len(parents) == 1
        assert store.get_children(parents[0].id) == []

    def test_persisted_across_reload(self, tmp_path):
        bridge, store = _harness(tmp_path)
        bridge.handlers["project"]("P | za 10 dni | a ; b")
        reloaded = GoalStore(tmp_path / "goals.jsonl")
        reloaded.load()
        parents = [g for g in reloaded.get_all() if g.metadata.get("project")]
        assert len(parents) == 1
        assert len(reloaded.get_children(parents[0].id)) == 2


# --------------------------------------------------------------------------- #
# /projects view + end-to-end rollup
# --------------------------------------------------------------------------- #
class TestProjectsView:
    def test_empty(self, tmp_path):
        bridge, _ = _harness(tmp_path)
        assert "Brak projektow" in bridge.handlers["projects"]("")

    def test_lists_tree(self, tmp_path):
        bridge, store = _harness(tmp_path)
        bridge.handlers["project"]("Hiszpanski | za 30 dni | a ; b")
        out = bridge.handlers["projects"]("")
        assert "Hiszpanski" in out
        assert "0/2" in out  # nothing terminal yet

    def test_rollup_closes_parent_visible_in_view(self, tmp_path):
        bridge, store = _harness(tmp_path)
        bridge.handlers["project"]("P | | a ; b")
        parent = [g for g in store.get_all() if g.metadata.get("project")][0]
        # operator/agent finishes both sub-goals
        for c in store.get_children(parent.id):
            store.update_status(c.id, GoalStatus.ACHIEVED, "done", "operator")
        # rollup completes the parent
        for d in rollup_mod.compute_rollups(store):
            rollup_mod.apply_rollup(store, d)
        store.save()
        assert store.get(parent.id).status == GoalStatus.ACHIEVED

        # The operator-driven rollup must SURVIVE a restart: reload from disk and
        # confirm the parent closure + the /projects view both hold.
        reloaded = GoalStore(tmp_path / "goals.jsonl")
        reloaded.load()
        assert reloaded.get(parent.id).status == GoalStatus.ACHIEVED
        bridge2 = FakeBridge()
        _register(bridge2, SimpleNamespace(goal_store=reloaded))
        out = bridge2.handlers["projects"]("")
        assert "achieved" in out
        assert "2/2" in out


class TestProjectCapacityAndDeadlineGuards:
    def test_past_deadline_rejected(self, tmp_path):
        bridge, store = _harness(tmp_path)
        out = bridge.handlers["project"]("P | 2020-01-01 | a ; b")
        assert "przeszlosci" in out
        assert store.get_all() == []

    def test_capacity_overflow_rejected_nothing_created(self, tmp_path):
        from agent_core.goals.goal_model import MAX_ACTIVE_GOALS, create_goal
        bridge, store = _harness(tmp_path)
        # Fill the active set with ACTIVE goals (not reclaimable by abandon_lowest).
        for i in range(MAX_ACTIVE_GOALS - 1):
            store.create(create_goal(GoalType.USER, f"g{i}", 0.5,
                                     status=GoalStatus.ACTIVE, goal_id=f"g{i}"))
        before = len(store.get_all())
        # Need 1 parent + 3 children = 4 > 1 free slot -> reject, create nothing.
        out = bridge.handlers["project"]("P | za 10 dni | a ; b ; c")
        assert "Za malo miejsca" in out
        assert len(store.get_all()) == before  # no overflow, no partial tree

    def test_capacity_exact_fit_allowed(self, tmp_path):
        from agent_core.goals.goal_model import MAX_ACTIVE_GOALS, create_goal
        bridge, store = _harness(tmp_path)
        # Leave exactly room for parent + 1 child (2 slots).
        for i in range(MAX_ACTIVE_GOALS - 2):
            store.create(create_goal(GoalType.USER, f"g{i}", 0.5,
                                     status=GoalStatus.ACTIVE, goal_id=f"g{i}"))
        out = bridge.handlers["project"]("P | za 10 dni | jedyny")
        assert "Projekt utworzony" in out
        active = sum(1 for g in store.get_all()
                     if g.status == GoalStatus.ACTIVE)
        assert active <= MAX_ACTIVE_GOALS


# --------------------------------------------------------------------------- #
# C6 (Option C, 2026-07-12): /project heldout <N> ...
# --------------------------------------------------------------------------- #

class TestProjectHeldoutMode:
    def test_heldout_prefix_stamps_children(self, tmp_path):
        bridge, store = _harness(tmp_path)
        out = bridge.handlers["project"](
            "heldout 7 Kronika srebra | za 14 dni | zebrac ; timeline")
        assert "Kronika srebra" in out
        assert "HELDOUT" in out
        children = [g for g in store.get_all()
                    if (g.metadata or {}).get("project_parent")]
        assert len(children) == 2
        for c in children:
            assert c.metadata["source_kind"] == "market"
            assert c.metadata["provenance_target_n"] == 7
            assert c.metadata["verification_mode"] == "heldout"
        parents = [g for g in store.get_all()
                   if (g.metadata or {}).get("project")]
        assert parents[0].metadata["verification_mode"] == "heldout"
        assert parents[0].description == "Kronika srebra"

    def test_heldout_default_n_is_12(self, tmp_path):
        bridge, store = _harness(tmp_path)
        bridge.handlers["project"]("heldout Kronika | za 14 dni | zebrac")
        child = [g for g in store.get_all()
                 if (g.metadata or {}).get("project_parent")][0]
        assert child.metadata["provenance_target_n"] == 12

    def test_heldout_requires_name(self, tmp_path):
        bridge, store = _harness(tmp_path)
        out = bridge.handlers["project"]("heldout 12 | za 14 dni | zebrac")
        assert "wymaga nazwy" in out
        assert store.get_all() == []

    def test_heldout_n_out_of_range(self, tmp_path):
        bridge, store = _harness(tmp_path)
        out = bridge.handlers["project"]("heldout 500 Kronika | za 14 dni | a")
        assert "poza zakresem" in out
        assert store.get_all() == []

    def test_plain_project_unchanged(self, tmp_path):
        bridge, store = _harness(tmp_path)
        bridge.handlers["project"]("Hiszpanski | za 30 dni | slownictwo")
        child = [g for g in store.get_all()
                 if (g.metadata or {}).get("project_parent")][0]
        assert "verification_mode" not in child.metadata
        assert "source_kind" not in child.metadata
