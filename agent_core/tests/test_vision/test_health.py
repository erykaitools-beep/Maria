"""
Tests for SensorHealth and graceful degradation.

Covers:
- Degradation level classification (7 levels)
- Overall health score computation
- Human descriptions (Polish)
- Factory methods (perfect, disconnected)
- Issue hints in descriptions
- Edge cases (boundary values, zero connection)
"""

import pytest

from agent_core.vision.models import SensorIssue
from agent_core.vision.sensors.health import (
    DegradationLevel,
    SensorHealth,
    classify_degradation_level,
)


# --- Degradation Level Classification ---

class TestClassifyDegradationLevel:
    """Tests for classify_degradation_level()."""

    def test_full_vision(self):
        assert classify_degradation_level(1.0) == DegradationLevel.FULL_VISION

    def test_full_vision_threshold(self):
        assert classify_degradation_level(0.85) == DegradationLevel.FULL_VISION

    def test_grayscale(self):
        assert classify_degradation_level(0.75) == DegradationLevel.GRAYSCALE

    def test_grayscale_threshold(self):
        assert classify_degradation_level(0.65) == DegradationLevel.GRAYSCALE

    def test_low_res(self):
        assert classify_degradation_level(0.55) == DegradationLevel.LOW_RES

    def test_low_res_threshold(self):
        assert classify_degradation_level(0.45) == DegradationLevel.LOW_RES

    def test_blur(self):
        assert classify_degradation_level(0.35) == DegradationLevel.BLUR

    def test_blur_threshold(self):
        assert classify_degradation_level(0.25) == DegradationLevel.BLUR

    def test_frame_by_frame(self):
        assert classify_degradation_level(0.15) == DegradationLevel.FRAME_BY_FRAME

    def test_frame_by_frame_threshold(self):
        assert classify_degradation_level(0.10) == DegradationLevel.FRAME_BY_FRAME

    def test_light_dark(self):
        assert classify_degradation_level(0.05) == DegradationLevel.LIGHT_DARK

    def test_light_dark_threshold(self):
        assert classify_degradation_level(0.01) == DegradationLevel.LIGHT_DARK

    def test_blind(self):
        assert classify_degradation_level(0.0) == DegradationLevel.BLIND

    def test_above_max_clamped(self):
        assert classify_degradation_level(1.5) == DegradationLevel.FULL_VISION

    def test_below_min_clamped(self):
        assert classify_degradation_level(-0.5) == DegradationLevel.BLIND


# --- SensorHealth Overall Score ---

class TestSensorHealthOverall:
    """Tests for SensorHealth.overall property."""

    def test_perfect_health(self):
        h = SensorHealth.perfect()
        assert h.overall >= 0.95

    def test_disconnected_health(self):
        h = SensorHealth.disconnected()
        assert h.overall == 0.0

    def test_zero_connection_kills_score(self):
        """Connection=0 means sensor is dead regardless of other values."""
        h = SensorHealth(connection=0.0, stream=1.0, focus=1.0)
        assert h.overall == 0.0

    def test_partial_health(self):
        h = SensorHealth(
            connection=1.0,
            stream=0.5,
            focus=0.5,
            noise=0.5,
        )
        score = h.overall
        assert 0.3 < score < 0.9

    def test_all_half(self):
        h = SensorHealth(
            connection=0.5,
            stream=0.5,
            resolution=0.5,
            color=0.5,
            focus=0.5,
            exposure=0.5,
            noise=0.5,
            latency_ms=0.0,
        )
        score = h.overall
        assert 0.4 < score < 0.6

    def test_high_latency_reduces_score(self):
        h_low = SensorHealth(latency_ms=10.0)
        h_high = SensorHealth(latency_ms=4000.0)
        assert h_low.overall > h_high.overall

    def test_score_clamped_0_1(self):
        h = SensorHealth(
            connection=1.0, stream=1.0, resolution=1.0,
            color=1.0, focus=1.0, exposure=1.0, noise=1.0,
            latency_ms=0.0,
        )
        assert 0.0 <= h.overall <= 1.0


# --- Degradation Level Property ---

class TestSensorHealthDegradationLevel:
    """Tests for SensorHealth.degradation_level property."""

    def test_perfect_is_full_vision(self):
        assert SensorHealth.perfect().degradation_level == DegradationLevel.FULL_VISION

    def test_disconnected_is_blind(self):
        assert SensorHealth.disconnected().degradation_level == DegradationLevel.BLIND

    def test_low_stream_degrades(self):
        h = SensorHealth(stream=0.2, focus=0.2, noise=0.2)
        level = h.degradation_level
        assert level in (
            DegradationLevel.BLUR,
            DegradationLevel.FRAME_BY_FRAME,
            DegradationLevel.LOW_RES,
        )


# --- Human Descriptions ---

class TestSensorHealthHumanDescription:
    """Tests for to_human_description() - Polish descriptions."""

    def test_perfect_description(self):
        desc = SensorHealth.perfect().to_human_description()
        assert "wyraznie" in desc or "ostro" in desc

    def test_disconnected_description(self):
        desc = SensorHealth.disconnected().to_human_description()
        assert "nie dziala" in desc.lower() or "nie widze" in desc.lower()

    def test_overexposed_hint(self):
        h = SensorHealth(issues=[SensorIssue.OVEREXPOSED])
        desc = h.to_human_description()
        assert "jasno" in desc.lower()

    def test_underexposed_hint(self):
        h = SensorHealth(issues=[SensorIssue.UNDEREXPOSED])
        desc = h.to_human_description()
        assert "ciemno" in desc.lower()

    def test_blurry_hint(self):
        h = SensorHealth(issues=[SensorIssue.BLURRY])
        desc = h.to_human_description()
        assert "rozmyty" in desc.lower()

    def test_noisy_hint(self):
        h = SensorHealth(issues=[SensorIssue.NOISY])
        desc = h.to_human_description()
        assert "szum" in desc.lower()

    def test_frozen_hint(self):
        h = SensorHealth(issues=[SensorIssue.FROZEN])
        desc = h.to_human_description()
        assert "zamrozony" in desc.lower() or "nie zmienia" in desc.lower()

    def test_disconnected_hint(self):
        h = SensorHealth(issues=[SensorIssue.DISCONNECTED])
        desc = h.to_human_description()
        assert "polaczeni" in desc.lower() or "kamera" in desc.lower()

    def test_multiple_issues(self):
        h = SensorHealth(
            issues=[SensorIssue.BLURRY, SensorIssue.NOISY],
        )
        desc = h.to_human_description()
        assert "rozmyty" in desc.lower()
        assert "szum" in desc.lower()


# --- Serialization ---

class TestSensorHealthSerialization:
    """Tests for to_dict()."""

    def test_to_dict_keys(self):
        d = SensorHealth.perfect().to_dict()
        expected_keys = {
            "overall", "connection", "stream", "resolution",
            "color", "focus", "exposure", "noise",
            "latency_ms", "degradation_level", "issues",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_values_perfect(self):
        d = SensorHealth.perfect().to_dict()
        assert d["connection"] == 1.0
        assert d["degradation_level"] == "full_vision"
        assert d["issues"] == []

    def test_to_dict_with_issues(self):
        h = SensorHealth(issues=[SensorIssue.BLURRY, SensorIssue.NOISY])
        d = h.to_dict()
        assert "blurry" in d["issues"]
        assert "noisy" in d["issues"]

    def test_to_dict_disconnected(self):
        d = SensorHealth.disconnected().to_dict()
        assert d["overall"] == 0.0
        assert d["degradation_level"] == "blind"
        assert "disconnected" in d["issues"]


# --- Factory Methods ---

class TestSensorHealthFactories:
    """Tests for perfect() and disconnected() factory methods."""

    def test_perfect_all_ones(self):
        h = SensorHealth.perfect()
        assert h.connection == 1.0
        assert h.stream == 1.0
        assert h.resolution == 1.0
        assert h.color == 1.0
        assert h.focus == 1.0
        assert h.exposure == 1.0
        assert h.noise == 1.0
        assert h.latency_ms == 0.0
        assert h.issues == []

    def test_disconnected_all_zeros(self):
        h = SensorHealth.disconnected()
        assert h.connection == 0.0
        assert h.stream == 0.0
        assert SensorIssue.DISCONNECTED in h.issues
