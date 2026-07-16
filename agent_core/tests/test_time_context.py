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

    def test_learning_window_open_on_weekend(self):
        # 2026-06-20: window is 7-day, so a Saturday learning HOUR is now OPEN
        # (advisory view delegates to the SSoT gate, which allows all days).
        tc = TimeContext(now=_berlin(10, 0, weekday=5))  # Saturday 10:00
        assert tc.is_learning_window is True

    def test_midday_now_in_window_but_slot_unchanged(self):
        # 2026-06-20: window widened to 08-21, so midday is now a learning window.
        # The time-of-day SLOT label is independent of the window and stays MIDDAY.
        tc = TimeContext(now=_berlin(12, 0))
        assert tc.is_learning_window is True
        assert tc.time_slot == SLOT_MIDDAY

    def test_evening_slot(self):
        # Evening (18:30) is now inside the widened window; slot label stays EVENING.
        tc = TimeContext(now=_berlin(18, 30))
        assert tc.is_learning_window is True
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
        assert 565 <= remaining <= 575  # ~570 min to 19:00 close

    def test_minutes_to_window_close_afternoon(self):
        tc = TimeContext(now=_berlin(15, 45))
        remaining = tc.minutes_to_window_close
        assert remaining is not None
        assert 190 <= remaining <= 200  # ~195 min to 19:00 close

    def test_minutes_to_window_close_outside(self):
        tc = TimeContext(now=_berlin(23, 0))  # night, outside 09-19 window
        assert tc.minutes_to_window_close is None

    def test_minutes_to_next_window_before_open(self):
        tc = TimeContext(now=_berlin(7, 0))
        minutes = tc.minutes_to_next_window
        assert minutes is not None
        assert 115 <= minutes <= 125  # ~120 min to 09:00 open

    def test_minutes_to_next_window_in_window(self):
        tc = TimeContext(now=_berlin(9, 30))
        assert tc.minutes_to_next_window is None

    def test_minutes_to_next_window_after_close(self):
        tc = TimeContext(now=_berlin(23, 0))
        minutes = tc.minutes_to_next_window
        assert minutes is not None
        # Next window tomorrow 09:00 = 10h = 600min
        assert 595 <= minutes <= 605

    def test_good_for_heavy_action_in_window(self):
        tc = TimeContext(now=_berlin(9, 30))
        assert tc.is_good_for_heavy_action is True

    def test_not_good_for_heavy_near_close(self):
        tc = TimeContext(now=_berlin(18, 57))
        assert tc.is_good_for_heavy_action is False  # 3 min to 19:00 close

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
