"""Tests for TimeContext - Planner v2 Phase A."""

from datetime import datetime, timezone, timedelta
import pytest

from agent_core.planner.time_context import (
    TimeContext,
    SLOT_MORNING_LEARN, SLOT_AFTERNOON_LEARN,
    SLOT_MIDDAY, SLOT_EVENING, SLOT_QUIET,
)


def _berlin(hour, minute=0, weekday=0):
    """Create a Berlin datetime for testing. weekday: 0=Mon."""
    # 2026-04-13 is a Monday
    base = datetime(2026, 4, 13 + weekday, hour, minute)
    return base


class TestTimeContext:

    def test_learning_window_morning(self):
        tc = TimeContext(now=_berlin(9, 30))
        assert tc.is_learning_window is True
        assert tc.time_slot == SLOT_MORNING_LEARN

    def test_learning_window_afternoon(self):
        tc = TimeContext(now=_berlin(14, 15))
        assert tc.is_learning_window is True
        assert tc.time_slot == SLOT_AFTERNOON_LEARN

    def test_learning_window_closed_on_weekend(self):
        # P2 (#5): a learning HOUR on a weekend is NOT a learning window -- the
        # advisory view now matches the gate (Mon-Fri), vs the old hour-only
        # "True on Saturday" that contradicted the gate.
        tc = TimeContext(now=_berlin(10, 0, weekday=5))  # Saturday 10:00
        assert tc.is_learning_window is False

    def test_outside_learning_window_midday(self):
        tc = TimeContext(now=_berlin(12, 0))
        assert tc.is_learning_window is False
        assert tc.time_slot == SLOT_MIDDAY

    def test_evening_slot(self):
        tc = TimeContext(now=_berlin(18, 30))
        assert tc.is_learning_window is False
        assert tc.time_slot == SLOT_EVENING

    def test_quiet_hours_night(self):
        tc = TimeContext(now=_berlin(23, 0))
        assert tc.is_quiet_hours is True
        assert tc.time_slot == SLOT_QUIET

    def test_quiet_hours_early_morning(self):
        tc = TimeContext(now=_berlin(5, 0))
        assert tc.is_quiet_hours is True

    def test_not_quiet_during_day(self):
        tc = TimeContext(now=_berlin(10, 0))
        assert tc.is_quiet_hours is False

    def test_minutes_to_window_close_morning(self):
        tc = TimeContext(now=_berlin(9, 30))
        remaining = tc.minutes_to_window_close
        assert remaining is not None
        assert 85 <= remaining <= 95  # ~90 min to 11:00

    def test_minutes_to_window_close_afternoon(self):
        tc = TimeContext(now=_berlin(15, 45))
        remaining = tc.minutes_to_window_close
        assert remaining is not None
        assert 10 <= remaining <= 20  # ~15 min to 16:00

    def test_minutes_to_window_close_outside(self):
        tc = TimeContext(now=_berlin(12, 0))
        assert tc.minutes_to_window_close is None

    def test_minutes_to_next_window_midday(self):
        tc = TimeContext(now=_berlin(12, 0))
        minutes = tc.minutes_to_next_window
        assert minutes is not None
        assert 115 <= minutes <= 125  # ~120 min to 14:00

    def test_minutes_to_next_window_in_window(self):
        tc = TimeContext(now=_berlin(9, 30))
        assert tc.minutes_to_next_window is None

    def test_minutes_to_next_window_evening(self):
        tc = TimeContext(now=_berlin(18, 0))
        minutes = tc.minutes_to_next_window
        assert minutes is not None
        # Next window tomorrow 9:00 = 15h = 900min
        assert 890 <= minutes <= 910

    def test_good_for_heavy_action_in_window(self):
        tc = TimeContext(now=_berlin(9, 30))
        assert tc.is_good_for_heavy_action is True

    def test_not_good_for_heavy_near_close(self):
        tc = TimeContext(now=_berlin(10, 57))
        assert tc.is_good_for_heavy_action is False  # 3 min to close

    def test_not_good_for_heavy_quiet(self):
        tc = TimeContext(now=_berlin(23, 0))
        assert tc.is_good_for_heavy_action is False

    def test_weekday(self):
        tc = TimeContext(now=_berlin(10, 0, weekday=0))  # Monday
        assert tc.is_weekday is True

    def test_weekend(self):
        tc = TimeContext(now=_berlin(10, 0, weekday=5))  # Saturday
        assert tc.is_weekday is False

    def test_summary(self):
        tc = TimeContext(now=_berlin(9, 30))
        s = tc.summary()
        assert "09:30" in s
        assert "Berlin" in s
        assert "morning_learn" in s


class TestActionBackoff:
    """Test failure memory in PlannerCore."""

    def test_no_backoff_initially(self):
        from agent_core.planner.planner_core import PlannerCore
        pc = PlannerCore()
        assert pc.is_action_backed_off("learn", "g-1") is False

    def test_backoff_after_3_failures(self):
        from agent_core.planner.planner_core import PlannerCore
        pc = PlannerCore()
        pc.record_action_failure("learn", "g-1")
        pc.record_action_failure("learn", "g-1")
        assert pc.is_action_backed_off("learn", "g-1") is False
        pc.record_action_failure("learn", "g-1")
        assert pc.is_action_backed_off("learn", "g-1") is True

    def test_success_clears_backoff(self):
        from agent_core.planner.planner_core import PlannerCore
        pc = PlannerCore()
        for _ in range(3):
            pc.record_action_failure("learn", "g-1")
        assert pc.is_action_backed_off("learn", "g-1") is True
        pc.record_action_success("learn", "g-1")
        assert pc.is_action_backed_off("learn", "g-1") is False

    def test_different_goals_independent(self):
        from agent_core.planner.planner_core import PlannerCore
        pc = PlannerCore()
        for _ in range(3):
            pc.record_action_failure("learn", "g-1")
        assert pc.is_action_backed_off("learn", "g-1") is True
        assert pc.is_action_backed_off("learn", "g-2") is False

    def test_ttl_expires_backoff(self):
        import time as _time
        from agent_core.planner.planner_core import PlannerCore
        pc = PlannerCore()
        pc._FAILURE_MEMORY_TTL = 0.01  # 10ms for test
        for _ in range(3):
            pc.record_action_failure("learn", "g-1")
        assert pc.is_action_backed_off("learn", "g-1") is True
        _time.sleep(0.02)
        assert pc.is_action_backed_off("learn", "g-1") is False
