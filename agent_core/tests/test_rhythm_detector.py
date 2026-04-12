"""Tests for RhythmDetector (K14.2)."""

from datetime import datetime

import pytest

from agent_core.operator.operator_model import DayRhythm
from agent_core.operator.rhythm_detector import RhythmDetector


def _ts(hour: int, weekday: int = 0, day: int = None) -> float:
    """Create timestamp for a given hour on a specific weekday.

    weekday: 0=Mon, 1=Tue, ..., 5=Sat, 6=Sun
    Maps to dates in April 2026 (April 6=Mon, April 11=Sat, April 12=Sun).
    """
    if day is not None:
        return datetime(2026, 4, day, hour, 30).timestamp()
    # Map weekday to a date in April 2026
    # April 6 = Monday (weekday 0)
    base_day = 6 + weekday
    return datetime(2026, 4, base_day, hour, 30).timestamp()


class TestRhythmDetector:
    @pytest.fixture
    def detector(self):
        return RhythmDetector()

    def test_insufficient_data_returns_defaults(self, detector):
        result = detector.analyze([_ts(10), _ts(14)])
        assert result.confidence == 0.0
        assert result.typical_wake_hour == 7
        assert result.sample_count == 2

    def test_empty_returns_defaults(self, detector):
        result = detector.analyze([])
        assert result.confidence == 0.0
        assert result.sample_count == 0

    def test_detects_wake_hour(self, detector):
        # Activity starts at 6am consistently
        timestamps = [
            _ts(6, day=d) for d in range(6, 13)
        ] + [
            _ts(10, day=d) for d in range(6, 13)
        ]
        result = detector.analyze(timestamps)
        assert result.typical_wake_hour == 6

    def test_detects_sleep_hour(self, detector):
        # Activity ends around 22
        timestamps = [
            _ts(22, day=d) for d in range(6, 13)
        ] + [
            _ts(10, day=d) for d in range(6, 13)
        ]
        result = detector.analyze(timestamps)
        assert result.typical_sleep_hour == 23

    def test_detects_work_hours(self, detector):
        # Weekday activity 8-16
        timestamps = []
        for day in range(6, 11):  # Mon-Fri (April 6-10)
            for hour in [8, 9, 12, 15, 16]:
                timestamps.append(_ts(hour, day=day))
        result = detector.analyze(timestamps)
        assert result.work_hours[0] == 8
        assert result.work_hours[1] >= 16

    def test_detects_weekend(self, detector):
        # Heavy weekday activity, minimal weekend
        timestamps = []
        for day in range(6, 11):  # Mon-Fri
            for hour in [9, 12, 18]:
                timestamps.append(_ts(hour, day=day))
        # Just 1 weekend message
        timestamps.append(_ts(14, day=11))  # Saturday
        result = detector.analyze(timestamps)
        assert 5 in result.weekend_days  # Saturday

    def test_confidence_scales_with_samples(self, detector):
        # 5 samples -> low confidence
        ts5 = [_ts(10, day=d) for d in range(6, 11)]
        r5 = detector.analyze(ts5)

        # 14 samples -> high confidence
        ts14 = [_ts(10, day=d) for d in range(6, 20)]
        r14 = detector.analyze(ts14)

        assert r5.confidence < r14.confidence
        assert r14.confidence >= 0.9

    def test_confidence_capped_at_09(self, detector):
        timestamps = [_ts(10, day=d) for d in range(1, 30)]
        result = detector.analyze(timestamps)
        assert result.confidence <= 0.9

    def test_result_is_day_rhythm(self, detector):
        timestamps = [_ts(10, day=d) for d in range(6, 13)]
        result = detector.analyze(timestamps)
        assert isinstance(result, DayRhythm)

    def test_last_analyzed_set(self, detector):
        timestamps = [_ts(10, day=d) for d in range(6, 13)]
        result = detector.analyze(timestamps)
        assert result.last_analyzed != ""


class TestActiveHours:
    @pytest.fixture
    def detector(self):
        return RhythmDetector()

    def test_default_active_hours(self, detector):
        active = detector.detect_active_hours([])
        assert active == list(range(7, 23))

    def test_learned_active_hours(self, detector):
        timestamps = []
        for day in range(6, 20):
            for hour in [8, 9, 10, 18, 19, 20]:
                timestamps.append(_ts(hour, day=day))
        active = detector.detect_active_hours(timestamps)
        assert 9 in active
        assert 19 in active
        assert 3 not in active

    def test_should_contact_now_default(self, detector):
        # With no data, 10am should be OK
        assert detector.should_contact_now(
            [], now=datetime(2026, 4, 12, 10, 0)
        ) is True
        # 3am should not
        assert detector.should_contact_now(
            [], now=datetime(2026, 4, 12, 3, 0)
        ) is False

    def test_should_contact_learned(self, detector):
        timestamps = [_ts(20, day=d) for d in range(6, 20)]
        # 20:00 should be fine (we have data there)
        assert detector.should_contact_now(
            timestamps, now=datetime(2026, 4, 12, 20, 0)
        ) is True
