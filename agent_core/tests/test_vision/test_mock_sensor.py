"""
Tests for MockSensor - simulated vision sensor.

Covers:
- Protocol compliance (VisionSensor)
- Open/close lifecycle
- Frame capture (test pattern, noise, frozen)
- Health injection and degradation
- Failure simulation
- Mode and resolution changes
- Diagnostics
"""

import pytest
import numpy as np

from agent_core.vision.models import (
    SensorIssue,
    VisionMode,
)
from agent_core.vision.sensors.base import VisionSensor
from agent_core.vision.sensors.health import DegradationLevel, SensorHealth
from agent_core.vision.sensors.mock_sensor import MockSensor


# --- Protocol Compliance ---

class TestMockSensorProtocol:
    """MockSensor must satisfy VisionSensor protocol."""

    def test_is_vision_sensor(self):
        sensor = MockSensor()
        assert isinstance(sensor, VisionSensor)

    def test_has_sensor_id(self):
        sensor = MockSensor(sensor_id="test-1")
        assert sensor.sensor_id == "test-1"

    def test_has_capabilities(self):
        sensor = MockSensor()
        caps = sensor.capabilities
        assert caps.max_resolution == (640, 480)
        assert caps.max_fps == 30.0

    def test_has_health(self):
        sensor = MockSensor()
        h = sensor.health
        assert isinstance(h, SensorHealth)

    def test_has_is_open(self):
        sensor = MockSensor()
        assert sensor.is_open is False


# --- Lifecycle ---

class TestMockSensorLifecycle:
    """Open/close lifecycle tests."""

    def test_initially_closed(self):
        sensor = MockSensor()
        assert sensor.is_open is False

    def test_open_success(self):
        sensor = MockSensor()
        assert sensor.open() is True
        assert sensor.is_open is True

    def test_open_failure(self):
        sensor = MockSensor(fail_open=True)
        assert sensor.open() is False
        assert sensor.is_open is False

    def test_close(self):
        sensor = MockSensor()
        sensor.open()
        sensor.close()
        assert sensor.is_open is False

    def test_health_disconnected_when_closed(self):
        sensor = MockSensor()
        h = sensor.health
        assert h.degradation_level == DegradationLevel.BLIND

    def test_health_perfect_when_open(self):
        sensor = MockSensor()
        sensor.open()
        h = sensor.health
        assert h.degradation_level == DegradationLevel.FULL_VISION
        sensor.close()


# --- Frame Capture ---

class TestMockSensorCapture:
    """Frame capture tests."""

    def test_capture_returns_none_when_closed(self):
        sensor = MockSensor()
        assert sensor.capture_frame() is None

    def test_capture_returns_frame_when_open(self):
        sensor = MockSensor()
        sensor.open()
        frame = sensor.capture_frame()
        assert frame is not None
        assert frame.is_valid
        sensor.close()

    def test_frame_has_correct_resolution(self):
        sensor = MockSensor(resolution=(320, 240))
        sensor.open()
        frame = sensor.capture_frame()
        assert frame.width == 320
        assert frame.height == 240
        sensor.close()

    def test_frame_has_3_channels(self):
        sensor = MockSensor()
        sensor.open()
        frame = sensor.capture_frame()
        assert frame.channels == 3
        sensor.close()

    def test_frame_has_sensor_id(self):
        sensor = MockSensor(sensor_id="cam-test")
        sensor.open()
        frame = sensor.capture_frame()
        assert frame.sensor_id == "cam-test"
        sensor.close()

    def test_frame_sequence_increments(self):
        sensor = MockSensor()
        sensor.open()
        f1 = sensor.capture_frame()
        f2 = sensor.capture_frame()
        assert f2.sequence_number == f1.sequence_number + 1
        sensor.close()

    def test_frame_has_timestamp(self):
        sensor = MockSensor()
        sensor.open()
        frame = sensor.capture_frame()
        assert frame.timestamp > 0
        sensor.close()

    def test_fail_capture_returns_none(self):
        sensor = MockSensor(fail_capture=True)
        sensor.open()
        assert sensor.capture_frame() is None
        sensor.close()


# --- Noise Generation ---

class TestMockSensorNoise:
    """Tests for noise frame generation."""

    def test_noise_frames_are_random(self):
        sensor = MockSensor(generate_noise=True)
        sensor.open()
        f1 = sensor.capture_frame()
        f2 = sensor.capture_frame()
        # Random frames should differ (extremely unlikely to be equal)
        assert not np.array_equal(f1.image, f2.image)
        sensor.close()

    def test_noise_frame_valid(self):
        sensor = MockSensor(generate_noise=True)
        sensor.open()
        frame = sensor.capture_frame()
        assert frame.is_valid
        assert frame.image.dtype == np.uint8
        sensor.close()


# --- Frozen Frame ---

class TestMockSensorFrozen:
    """Tests for frozen frame simulation."""

    def test_frozen_frames_identical(self):
        sensor = MockSensor(frozen_frame=True)
        sensor.open()
        f1 = sensor.capture_frame()
        f2 = sensor.capture_frame()
        assert np.array_equal(f1.image, f2.image)
        sensor.close()


# --- Health Injection ---

class TestMockSensorHealthInjection:
    """Tests for injecting health states."""

    def test_custom_health(self):
        custom = SensorHealth(focus=0.3, noise=0.4)
        sensor = MockSensor(health_override=custom)
        sensor.open()
        h = sensor.health
        assert h.focus == 0.3
        assert h.noise == 0.4
        sensor.close()

    def test_set_health_after_creation(self):
        sensor = MockSensor()
        sensor.open()
        assert sensor.health.degradation_level == DegradationLevel.FULL_VISION

        sensor.set_health(SensorHealth(connection=0.2, stream=0.1))
        level = sensor.health.degradation_level
        assert level != DegradationLevel.FULL_VISION
        sensor.close()

    def test_health_with_issues(self):
        custom = SensorHealth(
            focus=0.3,
            issues=[SensorIssue.BLURRY, SensorIssue.NOISY],
        )
        sensor = MockSensor(health_override=custom)
        sensor.open()
        h = sensor.health
        assert SensorIssue.BLURRY in h.issues
        assert SensorIssue.NOISY in h.issues
        sensor.close()

    def test_set_fail_capture_toggle(self):
        sensor = MockSensor()
        sensor.open()
        assert sensor.capture_frame() is not None

        sensor.set_fail_capture(True)
        assert sensor.capture_frame() is None

        sensor.set_fail_capture(False)
        assert sensor.capture_frame() is not None
        sensor.close()


# --- Mode and Resolution ---

class TestMockSensorMode:
    """Tests for mode and resolution changes."""

    def test_set_supported_mode(self):
        sensor = MockSensor()
        assert sensor.set_mode(VisionMode.DAYLIGHT) is True

    def test_set_unsupported_mode(self):
        sensor = MockSensor()
        assert sensor.set_mode(VisionMode.NIGHT) is False

    def test_set_supported_resolution(self):
        sensor = MockSensor()
        assert sensor.set_resolution(320, 240) is True

    def test_set_unsupported_resolution(self):
        sensor = MockSensor()
        assert sensor.set_resolution(1920, 1080) is False

    def test_mode_reflected_in_frame(self):
        sensor = MockSensor()
        sensor.open()
        sensor.set_mode(VisionMode.DAYLIGHT)
        frame = sensor.capture_frame()
        assert frame.mode == VisionMode.DAYLIGHT
        sensor.close()


# --- Diagnostics ---

class TestMockSensorDiagnostics:
    """Tests for diagnose()."""

    def test_diagnose_when_closed(self):
        sensor = MockSensor()
        report = sensor.diagnose()
        assert report.is_connected is False
        assert report.can_capture is False

    def test_diagnose_when_open(self):
        sensor = MockSensor()
        sensor.open()
        report = sensor.diagnose()
        assert report.is_connected is True
        assert report.can_capture is True
        assert report.sensor_id == "mock-0"
        assert report.details["type"] == "mock"
        sensor.close()

    def test_diagnose_when_failing(self):
        sensor = MockSensor(fail_capture=True)
        sensor.open()
        report = sensor.diagnose()
        assert report.can_capture is False
        sensor.close()

    def test_diagnose_resolution(self):
        sensor = MockSensor(resolution=(320, 240))
        sensor.open()
        report = sensor.diagnose()
        assert report.current_resolution == (320, 240)
        sensor.close()


# --- Test Pattern ---

class TestMockSensorTestPattern:
    """Tests for the generated test pattern."""

    def test_pattern_is_deterministic(self):
        sensor = MockSensor()
        sensor.open()
        f1 = sensor.capture_frame()
        # Reset sequence
        sensor.close()
        sensor.open()
        f2 = sensor.capture_frame()
        assert np.array_equal(f1.image, f2.image)
        sensor.close()

    def test_pattern_has_color(self):
        sensor = MockSensor()
        sensor.open()
        frame = sensor.capture_frame()
        # Test pattern should have non-zero values in all channels
        assert frame.image[:, :, 0].max() > 0  # Blue
        assert frame.image[:, :, 1].max() > 0  # Green
        assert frame.image[:, :, 2].max() > 0  # Red
        sensor.close()
