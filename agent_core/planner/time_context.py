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
)

logger = logging.getLogger(__name__)

# Learning window hours (Berlin time). LEARN_HOURS_ALL is DERIVED from the SSoT
# (environment_model.PROFILE_LEARNING) so this advisory view can never drift
# from the enforcing gate (P2 #5).
LEARN_HOURS_MORNING = (9, 10)   # 9:00-10:59
LEARN_HOURS_AFTERNOON = (14, 15)  # 14:00-15:59
LEARN_HOURS_ALL = set(PROFILE_LEARNING.auto_trigger_hours)

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
        # P2 (#5): + Mon-Fri so this advisory view matches the enforcing gate's
        # verdict. Was hour-only -> logged "in window" on weekends while the gate
        # blocked, producing contradictory traces.
        return self.hour in LEARN_HOURS_ALL and self.is_weekday

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
        h = self.hour
        m = self.berlin_now.minute
        # Morning window: closes at 11:00
        if h in (9, 10):
            return (10 - h) * 60 + (60 - m)
        # Afternoon window: closes at 16:00
        if h in (14, 15):
            return (15 - h) * 60 + (60 - m)
        return None

    @property
    def minutes_to_next_window(self) -> Optional[int]:
        """Minutes until next learning window opens. None if already in window."""
        if self.is_learning_window:
            return None
        h = self.hour
        m = self.berlin_now.minute
        now_min = h * 60 + m

        # Check today's remaining windows
        candidates = []
        if now_min < 9 * 60:
            candidates.append(9 * 60 - now_min)
        if now_min < 14 * 60:
            candidates.append(14 * 60 - now_min)

        if candidates:
            return min(candidates)

        # Next window is tomorrow 9:00
        return (24 * 60 - now_min) + 9 * 60

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
