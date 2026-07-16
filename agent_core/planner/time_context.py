"""
TimeContext - Time-of-day awareness for planner decisions.

Knows: current Berlin time, learning window status, time slots,
minutes to window close, next window start.

Used by tactical loop to make time-aware decisions without LLM.
"""

import logging
from datetime import datetime
from typing import Optional

from agent_core.environment.environment_model import (
    PROFILE_LEARNING,
    berlin_now as _env_berlin_now,
    is_learning_window as _env_is_learning_window,
)

logger = logging.getLogger(__name__)

# Learning window hours (Berlin time). LEARN_HOURS_ALL is DERIVED from the SSoT
# (environment_model.PROFILE_LEARNING) so this advisory view can never drift
# from the enforcing gate (P2 #5).
LEARN_HOURS_ALL = set(PROFILE_LEARNING.auto_trigger_hours)
# Contiguous span of the (now full-day) window, for the advisory "minutes to
# open/close" helpers. Derived from the SSoT so it tracks any config change.
_LEARN_OPEN_HOUR = min(LEARN_HOURS_ALL) if LEARN_HOURS_ALL else 0
_LEARN_CLOSE_HOUR = (max(LEARN_HOURS_ALL) + 1) if LEARN_HOURS_ALL else 24

# Quiet hours (Berlin time) - no heavy actions
QUIET_START = 22
QUIET_END = 7

# Time slots
SLOT_MORNING_LEARN = "morning_learn"      # 9-11 Berlin
SLOT_MIDDAY = "midday"                     # 11-14 Berlin
SLOT_AFTERNOON_LEARN = "afternoon_learn"   # 14-16 Berlin
SLOT_EVENING = "evening"                   # 16-22 Berlin
SLOT_QUIET = "quiet"                       # 22-7 Berlin


class TimeContext:
    """Time-of-day awareness for planner decisions."""

    def __init__(self, now: Optional[datetime] = None):
        """
        Args:
            now: Override current time (for testing). If None, uses real time.
        """
        self._override = now

    @property
    def berlin_now(self) -> datetime:
        if self._override:
            return self._override
        # P2 (#5): use the one Berlin-pinned clock (DST-correct). The old
        # hardcoded UTC+2 was an hour wrong every winter (CET).
        return _env_berlin_now()

    @property
    def hour(self) -> int:
        return self.berlin_now.hour

    @property
    def is_learning_window(self) -> bool:
        # Delegate to the SSoT gate (environment_model) so this advisory view can
        # never drift from the enforcing window -- hours AND days both come from
        # PROFILE_LEARNING. (2026-06-20: window is now 7-day, so the old hardcoded
        # Mon-Fri `and self.is_weekday` would have wrongly closed weekends here.)
        return _env_is_learning_window(self.berlin_now)

    @property
    def is_quiet_hours(self) -> bool:
        h = self.hour
        return h >= QUIET_START or h < QUIET_END

    @property
    def is_weekday(self) -> bool:
        return self.berlin_now.weekday() < 5

    @property
    def time_slot(self) -> str:
        h = self.hour
        if h >= QUIET_START or h < QUIET_END:
            return SLOT_QUIET
        if 9 <= h <= 10:
            return SLOT_MORNING_LEARN
        if 11 <= h <= 13:
            return SLOT_MIDDAY
        if 14 <= h <= 15:
            return SLOT_AFTERNOON_LEARN
        return SLOT_EVENING

    @property
    def minutes_to_window_close(self) -> Optional[int]:
        """Minutes until current learning window closes. None if not in window."""
        if not self.is_learning_window:
            return None
        now_min = self.hour * 60 + self.berlin_now.minute
        return _LEARN_CLOSE_HOUR * 60 - now_min

    @property
    def minutes_to_next_window(self) -> Optional[int]:
        """Minutes until next learning window opens. None if already in window."""
        if self.is_learning_window:
            return None
        now_min = self.hour * 60 + self.berlin_now.minute
        open_min = _LEARN_OPEN_HOUR * 60
        if now_min < open_min:
            return open_min - now_min
        # Past today's window -> tomorrow's open (advisory; ignores weekend gap,
        # matching the prior behaviour).
        return (24 * 60 - now_min) + open_min

    @property
    def is_good_for_heavy_action(self) -> bool:
        """Is this a good time for heavy LLM work?"""
        if self.is_quiet_hours:
            return False
        # Don't start heavy work less than 5 min before window closes
        remaining = self.minutes_to_window_close
        if remaining is not None and remaining < 5:
            return False
        return True

    def summary(self) -> str:
        """Human-readable time context for logs/traces."""
        slot = self.time_slot
        now = self.berlin_now
        parts = [f"{now.strftime('%H:%M')} Berlin ({now.strftime('%A')})"]
        parts.append(f"slot={slot}")
        if self.is_learning_window:
            parts.append(f"window_closes_in={self.minutes_to_window_close}min")
        else:
            parts.append(f"next_window_in={self.minutes_to_next_window}min")
        return ", ".join(parts)
