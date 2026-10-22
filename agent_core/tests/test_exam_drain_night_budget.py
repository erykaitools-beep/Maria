"""Off-window drain bonus for the exam_failed backlog (2026-08-12).

Measured motivation: on 2026-08-12 the planner issued 8 night `learn` actions
(exactly OFF_WINDOW_LEARN_BUDGET) and ZERO exams between 00:00 and 09:00 while
the CPU idled at 41-45C. The exam relay is idle-bound, not compute-bound -- one
stage costs 2-4 min of CPU, then TEACHER_COOLDOWN=900 paces 13-15 min of
nothing -- so the coldest hours of the day were doing no drain work at all.

The bonus MUST be self-reverting: when exam_failed reaches zero it disappears
with no flag to unset.
"""

import json

import pytest

from agent_core.planner.planner_core import (
    PlannerCore,
    OFF_WINDOW_LEARN_BUDGET,
    OFF_WINDOW_EXAM_DRAIN_BONUS,
)
from agent_core.planner.planner_model import ActionType, PlannerState
from agent_core.teacher import exam_backlog


@pytest.fixture(autouse=True)
def _clean_backlog_cache():
    exam_backlog.reset_cache()
    yield
    exam_backlog.reset_cache()


def _index(tmp_path, exam_failed=0, completed=0):
    path = tmp_path / "knowledge_index.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for i in range(exam_failed):
            f.write(json.dumps({"id": f"f{i}.txt", "status": "exam_failed"}) + "\n")
        for i in range(completed):
            f.write(json.dumps({"id": f"c{i}.txt", "status": "completed"}) + "\n")
    return path


def _at(monkeypatch, stamp: str):
    """Pin Berlin wall-clock time for the drain pool's stretch key.

    Patches the SSoT (`environment_model.berlin_now`) rather than the planner
    helper, so the test exercises the real hour -> stretch mapping instead of
    trusting a stubbed answer.
    """
    from datetime import datetime

    from agent_core.environment import environment_model

    fixed = datetime.strptime(stamp, "%Y-%m-%d %H:%M")
    monkeypatch.setattr(environment_model, "berlin_now", lambda: fixed)


def _planner(monkeypatch, index_path, day="2026-08-12"):
    pc = PlannerCore()
    pc._state = PlannerState()
    monkeypatch.setattr(PlannerCore, "_berlin_date_key", staticmethod(lambda: day))
    monkeypatch.setattr(
        exam_backlog, "_resolve_index_path", lambda p=None: index_path)
    return pc


class TestBacklogCounter:

    def test_counts_only_exam_failed(self, tmp_path):
        path = _index(tmp_path, exam_failed=3, completed=17)
        assert exam_backlog.exam_failed_count(path) == 3

    def test_missing_index_fails_closed_to_zero(self, tmp_path):
        assert exam_backlog.exam_failed_count(tmp_path / "nope.jsonl") == 0

    def test_survives_a_corrupt_line(self, tmp_path):
        path = tmp_path / "knowledge_index.jsonl"
        path.write_text(
            json.dumps({"id": "a", "status": "exam_failed"}) + "\n"
            "{ this is not json\n"
            + json.dumps({"id": "b", "status": "exam_failed"}) + "\n",
            encoding="utf-8")
        assert exam_backlog.exam_failed_count(path) == 2


class TestDrainBonus:

    def test_exam_gets_bonus_on_top_of_base_budget(self, monkeypatch, tmp_path):
        pc = _planner(monkeypatch, _index(tmp_path, exam_failed=163))
        allowed = pc._off_window_budget_remaining(ActionType.EXAM)
        assert allowed == OFF_WINDOW_LEARN_BUDGET + OFF_WINDOW_EXAM_DRAIN_BONUS
        # Not just "base + constant" -- the bonus must be a real increase, or
        # this assertion would pass with the feature switched off.
        assert allowed > OFF_WINDOW_LEARN_BUDGET

    def test_bonus_vanishes_when_queue_is_empty(self, monkeypatch, tmp_path):
        """The whole point: no flag to unset, it switches itself off."""
        pc = _planner(monkeypatch, _index(tmp_path, exam_failed=0, completed=50))
        assert (pc._off_window_budget_remaining(ActionType.EXAM)
                == OFF_WINDOW_LEARN_BUDGET)

    def test_learn_gets_the_bonus_because_it_drives_the_teacher(
            self, monkeypatch, tmp_path):
        """The measured reality this whole feature hangs on: off-window the
        planner emits `learn`, NEVER `exam` (8/8 on 2026-08-11..12), yet those
        learn actions ran exam stages -- the executor routes LEARN/EXAM/REVIEW
        into the same run_session and the teacher picks the stage itself.
        Gating on EXAM alone would be a producer nothing consumes."""
        pc = _planner(monkeypatch, _index(tmp_path, exam_failed=163))
        allowed = pc._off_window_budget_remaining(ActionType.LEARN)
        assert allowed == OFF_WINDOW_LEARN_BUDGET + OFF_WINDOW_EXAM_DRAIN_BONUS
        assert allowed > OFF_WINDOW_LEARN_BUDGET

    def test_fetch_and_ask_expert_keep_the_plain_budget(self, monkeypatch, tmp_path):
        """The bonus must not put extra FETCH on the link at night -- the Kimi
        download runs then (cron pauses it only 04:45-06:20). These reach the
        link and an external LLM, not the teacher."""
        pc = _planner(monkeypatch, _index(tmp_path, exam_failed=163))
        for action in (ActionType.FETCH, ActionType.ASK_EXPERT):
            assert (pc._off_window_budget_remaining(action)
                    == OFF_WINDOW_LEARN_BUDGET), action

    def test_teacher_actions_spend_the_drain_pool_first(self, monkeypatch, tmp_path):
        """A night of exams must leave the base 8 intact for FETCH/ASK_EXPERT."""
        pc = _planner(monkeypatch, _index(tmp_path, exam_failed=163))
        for _ in range(5):
            assert pc._consume_off_window_budget(ActionType.LEARN) is True
        assert pc._state.off_window_drain_used == 5
        assert pc._state.off_window_learn_used == 0
        assert (pc._off_window_budget_remaining(ActionType.FETCH)
                == OFF_WINDOW_LEARN_BUDGET)

    def test_exam_falls_back_to_base_once_drain_pool_is_dry(
            self, monkeypatch, tmp_path):
        pc = _planner(monkeypatch, _index(tmp_path, exam_failed=163))
        for _ in range(OFF_WINDOW_EXAM_DRAIN_BONUS):
            pc._consume_off_window_budget(ActionType.EXAM)
        assert pc._drain_budget_remaining() == 0
        assert pc._consume_off_window_budget(ActionType.EXAM) is False
        assert pc._state.off_window_learn_used == 1

    def test_total_off_window_exams_are_still_bounded(self, monkeypatch, tmp_path):
        """Bounded, not unlimited -- a failing exam loop must not hammer all night."""
        pc = _planner(monkeypatch, _index(tmp_path, exam_failed=163))
        allowed = 0
        while pc._off_window_budget_remaining(ActionType.EXAM) > 0:
            pc._consume_off_window_budget(ActionType.EXAM)
            allowed += 1
            assert allowed <= 100, "budget never ran out - unbounded night"
        assert allowed == OFF_WINDOW_LEARN_BUDGET + OFF_WINDOW_EXAM_DRAIN_BONUS
        assert allowed > OFF_WINDOW_LEARN_BUDGET

    def test_midnight_resets_the_base_budget_but_NOT_the_drain_pool(
        self, monkeypatch, tmp_path
    ):
        """The two counters run on different clocks, on purpose (2026-08-15).

        This test used to assert that BOTH reset on a new Berlin day. That was
        pinning the bug: midnight lands in the middle of a night's drain work,
        so resetting the pool there hands the morning a pool the evening will
        need -- and the evening then starts empty. The base budget keeps its
        calendar day; the drain pool follows the dark stretch.
        """
        path = _index(tmp_path, exam_failed=163)
        pc = _planner(monkeypatch, path, day="2026-08-12")
        _at(monkeypatch, "2026-08-12 21:00")
        pc._consume_off_window_budget(ActionType.EXAM)
        pc._consume_off_window_budget(ActionType.FETCH)
        assert (pc._state.off_window_drain_used,
                pc._state.off_window_learn_used) == (1, 1)

        # Same night, past midnight: new calendar day, SAME dark stretch.
        monkeypatch.setattr(
            PlannerCore, "_berlin_date_key", staticmethod(lambda: "2026-08-13"))
        _at(monkeypatch, "2026-08-13 01:00")
        pc._consume_off_window_budget(ActionType.EXAM)
        assert pc._state.off_window_learn_used == 0, "base budget resets at midnight"
        assert pc._state.off_window_drain_used == 2, (
            "the drain pool must carry across midnight -- it is one night's work"
        )

    def test_unreadable_index_grants_no_bonus(self, monkeypatch, tmp_path):
        """Fail-closed: a broken read may withdraw the bonus, never grant one."""
        pc = _planner(monkeypatch, tmp_path / "missing.jsonl")
        assert (pc._off_window_budget_remaining(ActionType.EXAM)
                == OFF_WINDOW_LEARN_BUDGET)


class TestGoalFilterSeesTheBonus:
    """_off_window_any_allowed feeds the goal-ranking filter, which runs BEFORE
    an action type exists. If it reported only the base budget, learning goals
    would be filtered out once the plain 8 were spent and the bonus would never
    be reachable."""

    def test_still_allowed_after_base_budget_is_exhausted(
            self, monkeypatch, tmp_path):
        pc = _planner(monkeypatch, _index(tmp_path, exam_failed=163))
        for _ in range(OFF_WINDOW_LEARN_BUDGET):
            pc._consume_off_window_budget(ActionType.FETCH)
        assert pc._off_window_budget_remaining() == 0
        assert pc._off_window_any_allowed() is True

    def test_blocked_when_base_exhausted_and_no_backlog(self, monkeypatch, tmp_path):
        pc = _planner(monkeypatch, _index(tmp_path, exam_failed=0, completed=9))
        for _ in range(OFF_WINDOW_LEARN_BUDGET):
            pc._consume_off_window_budget(ActionType.FETCH)
        assert pc._off_window_any_allowed() is False

    def test_blocked_when_everything_is_spent(self, monkeypatch, tmp_path):
        pc = _planner(monkeypatch, _index(tmp_path, exam_failed=163))
        for _ in range(OFF_WINDOW_EXAM_DRAIN_BONUS):
            pc._consume_off_window_budget(ActionType.LEARN)
        for _ in range(OFF_WINDOW_LEARN_BUDGET):
            pc._consume_off_window_budget(ActionType.FETCH)
        assert pc._off_window_any_allowed() is False


class TestThermalDoesNotBurnBudget:
    """A budget unit must only be spent on an action that can actually work.

    Measured 2026-08-12, the night the drain bonus shipped: the unit granted at
    19:40:42 was followed 1 second later by "[EXAM] Thermal cooling active;
    deferring exam stage" -- one of the first five units burned on nothing.
    _heavy_action_mode_ok already encodes this rationale for mode/health; the
    thermal latch (added 2026-08-10) was simply not wired into it.
    """

    def _goal(self):
        class _T:
            value = "learning"

        class _G:
            id = "goal-1"
            type = _T()
            metadata: dict = {}
        return _G()

    def test_cooling_defers_without_spending_a_unit(self, monkeypatch, tmp_path):
        pc = _planner(monkeypatch, _index(tmp_path, exam_failed=163))
        monkeypatch.setattr(pc, "_thermal_allows_heavy", lambda: False)
        monkeypatch.setattr(
            "agent_core.environment.environment_model.is_learning_window",
            lambda *a, **k: False)

        action, reason = pc._enforce_learning_window(self._goal(), ActionType.LEARN)

        assert action == ActionType.NOOP
        assert reason == "thermal_cooling"
        assert pc._state.off_window_drain_used == 0
        assert pc._state.off_window_learn_used == 0

    def test_budget_is_spent_once_cooling_clears(self, monkeypatch, tmp_path):
        pc = _planner(monkeypatch, _index(tmp_path, exam_failed=163))
        monkeypatch.setattr(pc, "_thermal_allows_heavy", lambda: True)
        monkeypatch.setattr(pc, "_heavy_action_mode_ok", lambda: True)
        monkeypatch.setattr(
            "agent_core.environment.environment_model.is_learning_window",
            lambda *a, **k: False)

        action, reason = pc._enforce_learning_window(self._goal(), ActionType.LEARN)

        assert action == ActionType.LEARN
        assert reason is None
        assert pc._state.off_window_drain_used == 1

    def test_thermal_probe_fails_open(self, monkeypatch, tmp_path):
        """An unwired coordinator must not block every off-window action."""
        pc = _planner(monkeypatch, _index(tmp_path, exam_failed=163))
        import agent_core.llm.local_compute as lc
        monkeypatch.setattr(
            lc, "get_local_compute_coordinator",
            lambda: (_ for _ in ()).throw(RuntimeError("not wired")))
        assert pc._thermal_allows_heavy() is True


class TestDrainCapSizing:
    """The cap is a tuning number, so these pin the RULES it has to satisfy --
    not the number itself. An assertion that merely restates the constant would
    pass at any value (the trap that made the first version of this file's
    bonus tests green with the feature switched off)."""

    OBSERVED_PER_STRETCH = 24   # grants consumed 2026-08-12 19:04-21:47 and
                                # again 2026-08-13 00:00-02:xx, both to zero

    def test_cap_covers_both_halves_of_one_dark_stretch(self):
        """One pool serves a whole night: 19:00-24:00 plus 00:00-09:00 of the
        NEXT day, which is what _drain_stretch_key() now keys on. Both halves
        were measured at 24 grants apiece (Aug 12 19:04-21:47 and Aug 13
        00:00-02:xx, the two ends of one night), so a cap sized for one half
        starves the other."""
        assert OFF_WINDOW_EXAM_DRAIN_BONUS >= 2 * self.OBSERVED_PER_STRETCH

    def test_cap_stays_bounded(self):
        """Still a throttle, not an open tap: a failing exam loop must not be
        able to hammer the CPU all night. Sanity ceiling well under the
        observed 8 grants/h across 14 unlit hours (~112)."""
        assert OFF_WINDOW_EXAM_DRAIN_BONUS <= 112

    def test_a_whole_stretch_fits_without_running_dry(self, monkeypatch, tmp_path):
        """Behavioural form of the sizing rule: spend one stretch's worth and
        the pool must still have room for the day's other stretch."""
        pc = _planner(monkeypatch, _index(tmp_path, exam_failed=146))
        for _ in range(self.OBSERVED_PER_STRETCH):
            assert pc._consume_off_window_budget(ActionType.LEARN) is True
        assert pc._drain_budget_remaining() >= self.OBSERVED_PER_STRETCH
        assert pc._off_window_any_allowed() is True


class TestDarkStretchPool:
    """The drain pool belongs to a NIGHT, not to a calendar day (2026-08-15).

    Raising the cap 24 -> 48 on 2026-08-13 did not remove the starvation, it
    relocated it: with one pool per Berlin date, the morning half of a night
    spends the pool that the SAME date's evening -- a different night -- will
    need. Keying on the dark stretch pairs the halves that actually belong
    together.
    """

    def test_evening_and_the_small_hours_share_one_pool(self, monkeypatch):
        _at(monkeypatch, "2026-08-12 21:00")
        evening = PlannerCore._drain_stretch_key()
        _at(monkeypatch, "2026-08-13 02:00")
        small_hours = PlannerCore._drain_stretch_key()
        assert evening == small_hours, (
            "00:00-09:00 closes the night that opened the previous evening"
        )

    def test_the_next_evening_opens_a_new_pool(self, monkeypatch):
        _at(monkeypatch, "2026-08-13 02:00")
        old_night = PlannerCore._drain_stretch_key()
        _at(monkeypatch, "2026-08-13 20:00")
        new_night = PlannerCore._drain_stretch_key()
        assert old_night != new_night, (
            "a fresh evening is a fresh night and must not inherit an empty pool"
        )

    def test_key_follows_the_window_ssot_not_a_hardcoded_hour(self, monkeypatch):
        """Widen the learning window and the boundary must move with it."""
        from agent_core.environment import environment_model

        _at(monkeypatch, "2026-08-13 07:00")
        assert PlannerCore._drain_stretch_key() == "2026-08-12", (
            "07:00 is before the 09:00 window: still last night"
        )
        import dataclasses

        monkeypatch.setattr(
            environment_model, "PROFILE_LEARNING",
            dataclasses.replace(
                environment_model.PROFILE_LEARNING,
                auto_trigger_hours=tuple(range(6, 19)),
            ),
        )
        assert PlannerCore._drain_stretch_key() == "2026-08-13", (
            "with the window opening at 06:00, 07:00 is daytime -- new stretch"
        )

    def test_a_drained_night_does_not_starve_the_next_evening(
        self, monkeypatch, tmp_path
    ):
        """The regression itself, in the shape it was measured.

        Aug 12 evening and Aug 13 small hours burn the whole pool. Under
        date-keying the Aug 13 evening then found the Aug 13 pool already
        empty and issued nothing at all.
        """
        path = _index(tmp_path, exam_failed=163)
        pc = _planner(monkeypatch, path, day="2026-08-12")

        _at(monkeypatch, "2026-08-12 20:00")
        for _ in range(OFF_WINDOW_EXAM_DRAIN_BONUS // 2):
            pc._consume_off_window_budget(ActionType.EXAM)

        monkeypatch.setattr(
            PlannerCore, "_berlin_date_key", staticmethod(lambda: "2026-08-13"))
        _at(monkeypatch, "2026-08-13 01:00")
        while pc._drain_budget_remaining() > 0:
            pc._consume_off_window_budget(ActionType.EXAM)
        assert pc._drain_budget_remaining() == 0, "the night really ran dry"

        _at(monkeypatch, "2026-08-13 20:00")
        assert pc._drain_budget_remaining() == OFF_WINDOW_EXAM_DRAIN_BONUS, (
            "the next evening opens a new night and must get a full pool"
        )

    def test_upgrade_from_a_state_without_the_stretch_field(self, monkeypatch):
        """Older persisted state carries drain_used but no stretch key.

        It must read as a fresh pool rather than as a spent one -- worst case
        one extra pool once, never a night silently starved after a restart.
        """
        state = PlannerState.from_dict({"off_window_drain_used": 48})
        assert state.off_window_drain_stretch == ""
        pc = PlannerCore()
        pc._state = state
        _at(monkeypatch, "2026-08-13 20:00")
        assert pc._drain_budget_remaining() == OFF_WINDOW_EXAM_DRAIN_BONUS

    def test_state_round_trips_through_disk(self):
        """to_dict/from_dict must carry the new field, or every restart resets
        the pool -- the same starvation by a different route."""
        state = PlannerState()
        state.off_window_drain_stretch = "2026-08-12"
        state.off_window_drain_used = 7
        restored = PlannerState.from_dict(state.to_dict())
        assert restored.off_window_drain_stretch == "2026-08-12"
        assert restored.off_window_drain_used == 7
