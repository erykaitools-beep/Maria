"""
RhythmDetector - Temporal pattern extraction from operator interaction history.

Analyzes Telegram message timestamps and proactive contact history
to detect: wake time, sleep time, work hours, weekend patterns.

Uses LOCAL time (Europe/Warsaw default), not UTC.
All analysis is median/histogram-based - no ML, no LLM.
"""

import logging
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from agent_core.operator.operator_model import DayRhythm

logger = logging.getLogger(__name__)

# Minimum samples to produce confident results
MIN_SAMPLES_CONFIDENT = 14  # ~2 weeks of daily contact
MIN_SAMPLES_BASIC = 5  # enough for rough estimate


class RhythmDetector:
    """
    Detects operator daily rhythm from interaction timestamps.

    Supports both stateless (analyze(list)) and stateful (record_contact) usage.

    Usage:
        detector = RhythmDetector()
        detector.record_contact(time.time())  # accumulate
        rhythm = detector.get_rhythm()        # analyze accumulated

        # or stateless:
        rhythm = detector.analyze(timestamps)
    """

    def __init__(self):
        self._timestamps: List[float] = []

    def record_contact(self, timestamp: float) -> None:
        """Record a single operator contact timestamp."""
        self._timestamps.append(timestamp)
        # Cap at 1000 most recent
        if len(self._timestamps) > 1000:
            self._timestamps = self._timestamps[-1000:]

    def seed(self, timestamps: List[float]) -> None:
        """Bulk-load historical timestamps (e.g. from JSONL at startup)."""
        self._timestamps.extend(timestamps)
        if len(self._timestamps) > 1000:
            self._timestamps = self._timestamps[-1000:]

    def get_rhythm(self) -> DayRhythm:
        """Analyze accumulated timestamps and return DayRhythm."""
        return self.analyze(self._timestamps)

    @property
    def sample_count(self) -> int:
        return len(self._timestamps)

    def analyze(self, timestamps: List[float]) -> DayRhythm:
        """
        Analyze timestamps and return DayRhythm.

        Args:
            timestamps: Unix timestamps of operator interactions

        Returns:
            DayRhythm with detected patterns and confidence score
        """
        if len(timestamps) < MIN_SAMPLES_BASIC:
            return DayRhythm(
                confidence=0.0,
                sample_count=len(timestamps),
                last_analyzed=datetime.now().isoformat(),
            )

        hours = [datetime.fromtimestamp(ts).hour for ts in timestamps]
        weekdays = [datetime.fromtimestamp(ts).weekday() for ts in timestamps]

        wake = self._detect_wake_hour(hours)
        sleep = self._detect_sleep_hour(hours)
        work_start, work_end = self._detect_work_hours(hours, weekdays)
        weekend = self._detect_weekend_days(weekdays, hours)

        confidence = min(len(timestamps) / MIN_SAMPLES_CONFIDENT, 1.0)
        # Cap at 0.9 - never fully certain from timestamps alone
        confidence = round(min(confidence, 0.9), 2)

        return DayRhythm(
            typical_wake_hour=wake,
            typical_sleep_hour=sleep,
            work_hours=[work_start, work_end],
            weekend_days=weekend,
            confidence=confidence,
            sample_count=len(timestamps),
            last_analyzed=datetime.now().isoformat(),
        )

    def detect_active_hours(self, timestamps: List[float]) -> List[int]:
        """Return list of hours where operator is typically active."""
        if len(timestamps) < MIN_SAMPLES_BASIC:
            return list(range(7, 23))  # default: 7-22

        hours = [datetime.fromtimestamp(ts).hour for ts in timestamps]
        counter = Counter(hours)

        if not counter:
            return list(range(7, 23))

        max_count = max(counter.values())
        threshold = max(1, int(max_count * 0.3))

        return sorted(h for h in range(24) if counter.get(h, 0) >= threshold)

    def should_contact_now(
        self, timestamps: List[float], now: Optional[datetime] = None
    ) -> bool:
        """Check if now is a good time to contact the operator."""
        if now is None:
            now = datetime.now()

        hour = now.hour
        active = self.detect_active_hours(timestamps)
        return hour in active

    # ── Internal detection methods ───────────────────────────

    @staticmethod
    def _detect_wake_hour(hours: List[int]) -> int:
        """Detect typical wake hour (earliest frequent activity)."""
        counter = Counter(hours)
        if not counter:
            return 7

        max_count = max(counter.values())
        threshold = max(1, int(max_count * 0.2))

        # Find earliest hour with significant activity
        for h in range(4, 14):  # reasonable wake range
            if counter.get(h, 0) >= threshold:
                return h
        return 7

    @staticmethod
    def _detect_sleep_hour(hours: List[int]) -> int:
        """Detect typical sleep hour (latest frequent activity + 1)."""
        counter = Counter(hours)
        if not counter:
            return 23

        max_count = max(counter.values())
        threshold = max(1, int(max_count * 0.2))

        # Find latest hour with significant activity
        latest = 23
        for h in range(23, 17, -1):  # reasonable sleep range
            if counter.get(h, 0) >= threshold:
                latest = h + 1
                break

        return min(latest, 24) if latest <= 24 else 23

    @staticmethod
    def _detect_work_hours(
        hours: List[int], weekdays: List[int]
    ) -> Tuple[int, int]:
        """Detect work hours from weekday-only activity."""
        # Filter to weekdays only (Mon-Fri = 0-4)
        weekday_hours = [
            h for h, wd in zip(hours, weekdays) if wd < 5
        ]

        if len(weekday_hours) < 3:
            return 9, 17  # default

        counter = Counter(weekday_hours)
        if not counter:
            return 9, 17

        max_count = max(counter.values())
        threshold = max(1, int(max_count * 0.3))

        active = sorted(
            h for h in range(5, 22) if counter.get(h, 0) >= threshold
        )

        if not active:
            return 9, 17

        return active[0], active[-1] + 1

    @staticmethod
    def _detect_weekend_days(
        weekdays: List[int], hours: List[int]
    ) -> List[int]:
        """Detect weekend days (days with significantly less activity)."""
        day_counts = Counter(weekdays)

        if len(day_counts) < 5:
            return [5, 6]  # default Sat+Sun

        # Average contacts per weekday vs weekend
        weekday_avg = sum(
            day_counts.get(d, 0) for d in range(5)
        ) / 5.0
        weekend_avg = sum(
            day_counts.get(d, 0) for d in (5, 6)
        ) / 2.0

        # If weekend activity is < 50% of weekday, it's weekend
        if weekday_avg > 0 and weekend_avg / weekday_avg < 0.5:
            return [5, 6]

        # Check individual days
        if weekday_avg == 0:
            return [5, 6]

        weekend = []
        for d in (5, 6):
            if day_counts.get(d, 0) / weekday_avg < 0.5:
                weekend.append(d)

        return weekend if weekend else [5, 6]
