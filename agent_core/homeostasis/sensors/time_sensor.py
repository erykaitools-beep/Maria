"""
Time Sensor - Circadian rhythms and idle tracking

Monitors (spec section 1.1.C):
- Hour of day, day of week (for circadian mode changes)
- Session duration (continuous operation time)
- Last human interaction timestamp
- Idle streak duration

Spec reference: homeostasis_spec.md lines 67-78
"""

import time
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass


@dataclass
class TimeMetrics:
    """Time sensor readings."""
    timestamp: float
    hour_of_day: int
    day_of_week: int  # 0=Monday, 6=Sunday
    session_duration_sec: float
    last_interaction_sec: float  # Seconds since last interaction
    idle_streak_sec: float


class TimeSensor:
    """
    Tracks time-based metrics for homeostasis.

    Manages:
    - Circadian rhythm awareness
    - Idle detection for SLEEP mode transition
    - Session duration tracking
    """

    # Thresholds from spec
    IDLE_THRESHOLD_FOR_SLEEP_SEC = 1800  # 30 minutes

    def __init__(self):
        """Initialize time sensor."""
        self._session_start = time.time()
        self._last_interaction = time.time()
        self._idle_streak_start = time.time()

    def read_metrics(self) -> TimeMetrics:
        """
        Read time-related metrics.

        Returns:
            TimeMetrics with current values
        """
        now = time.time()
        dt = datetime.now()

        return TimeMetrics(
            timestamp=now,
            hour_of_day=dt.hour,
            day_of_week=dt.weekday(),
            session_duration_sec=now - self._session_start,
            last_interaction_sec=now - self._last_interaction,
            idle_streak_sec=now - self._idle_streak_start,
        )

    def record_interaction(self) -> None:
        """
        Record a user interaction.

        Resets idle streak counter.
        """
        now = time.time()
        self._last_interaction = now
        self._idle_streak_start = now

    def record_activity(self) -> None:
        """
        Record system activity (non-user).

        Does not reset last_interaction but resets idle streak.
        """
        self._idle_streak_start = time.time()

    def get_idle_seconds(self) -> float:
        """Get seconds since last interaction."""
        return time.time() - self._last_interaction

    def get_idle_streak_seconds(self) -> float:
        """Get seconds since last activity of any kind."""
        return time.time() - self._idle_streak_start

    def get_session_duration_seconds(self) -> float:
        """Get total session duration in seconds."""
        return time.time() - self._session_start

    def should_enter_sleep(self) -> bool:
        """
        Check if idle threshold for SLEEP mode is reached.

        Returns:
            True if idle > 30 minutes (spec threshold)
        """
        return self.get_idle_seconds() >= self.IDLE_THRESHOLD_FOR_SLEEP_SEC

    def is_night_hours(self) -> bool:
        """
        Check if current time is in night hours.

        Night hours: 20:00 - 06:00
        Used for scheduled SLEEP mode.
        """
        hour = datetime.now().hour
        return hour >= 20 or hour < 6

    def is_weekend(self) -> bool:
        """Check if today is weekend."""
        return datetime.now().weekday() >= 5

    def reset_session(self) -> None:
        """Reset session start time (e.g., after recovery)."""
        self._session_start = time.time()
        self._last_interaction = time.time()
        self._idle_streak_start = time.time()

    def get_time_until_scheduled_sleep(self) -> Optional[float]:
        """
        Get seconds until scheduled SLEEP time (20:00).

        Returns:
            Seconds until 20:00, or None if already past
        """
        now = datetime.now()
        sleep_time = now.replace(hour=20, minute=0, second=0, microsecond=0)

        if now >= sleep_time:
            # Already past today's sleep time
            return None

        return (sleep_time - now).total_seconds()

    def get_time_until_scheduled_wake(self) -> Optional[float]:
        """
        Get seconds until scheduled wake time (06:00).

        Returns:
            Seconds until 06:00, or None if already past
        """
        now = datetime.now()
        wake_time = now.replace(hour=6, minute=0, second=0, microsecond=0)

        if now.hour >= 6:
            # Already past today's wake time, calculate for tomorrow
            wake_time += timedelta(days=1)

        return (wake_time - now).total_seconds()
