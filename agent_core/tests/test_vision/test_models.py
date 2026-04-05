"""
Tests for vision data models - Frame, VisionMode, DiagnosticReport.

Covers:
- Frame creation and properties
- Frame validity checks
- Frame equality and hashing
- DiagnosticReport creation
- VisionMode enum values
- SensorIssue enum values
- DegradationType enum values
"""

import pytest
import numpy as np

from agent_core.vision.models import (
    DegradationType,
    DiagnosticReport,
    Frame,
    SensorIssue,
    VisionMode,
)


# --- Frame ---

class TestFrame:
    """Tests for the Frame dataclass."""

    def test_create_frame(self):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        frame = Frame(image=img, sensor_id="test")
        assert frame.sensor_id == "test"
        assert frame.is_valid

    def test_frame_dimensions(self):
        img = np.zeros((240, 320, 3), dtype=np.uint8)
        frame = Frame(image=img)
        assert frame.width == 320
        assert frame.height == 240
        assert frame.channels == 3

    def test_grayscale_frame(self):
        img = np.zeros((480, 640), dtype=np.uint8)
        frame = Frame(image=img)
        assert frame.is_grayscale
        assert frame.channels == 1

    def test_frame_not_grayscale(self):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        frame = Frame(image=img)
        assert not frame.is_grayscale

    def test_empty_frame_invalid(self):
        img = np.array([], dtype=np.uint8)
        frame = Frame(image=img)
        assert not frame.is_valid

    def test_frame_has_timestamp(self):
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        frame = Frame(image=img)
        assert frame.timestamp > 0

    def test_frame_default_mode(self):
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        frame = Frame(image=img)
        assert frame.mode == VisionMode.AUTO

    def test_frame_equality(self):
        img = np.ones((10, 10, 3), dtype=np.uint8) * 42
        f1 = Frame(image=img, sensor_id="a", sequence_number=1)
        f2 = Frame(image=img.copy(), sensor_id="a", sequence_number=1)
        assert f1 == f2

    def test_frame_inequality_different_image(self):
        img1 = np.zeros((10, 10, 3), dtype=np.uint8)
        img2 = np.ones((10, 10, 3), dtype=np.uint8)
        f1 = Frame(image=img1, sensor_id="a", sequence_number=1)
        f2 = Frame(image=img2, sensor_id="a", sequence_number=1)
        assert f1 != f2

    def test_frame_hash(self):
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        f = Frame(image=img, sensor_id="a", sequence_number=1, timestamp=100.0)
        assert isinstance(hash(f), int)

    def test_frame_not_equal_to_non_frame(self):
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        f = Frame(image=img)
        assert f != "not a frame"


# --- DiagnosticReport ---

class TestDiagnosticReport:
    """Tests for DiagnosticReport."""

    def test_create_report(self):
        report = DiagnosticReport(sensor_id="test-0")
        assert report.sensor_id == "test-0"
        assert report.is_connected is False
        assert report.can_capture is False

    def test_report_with_issues(self):
        report = DiagnosticReport(
            sensor_id="test",
            is_connected=True,
            can_capture=True,
            issues=(SensorIssue.BLURRY,),
        )
        assert SensorIssue.BLURRY in report.issues

    def test_report_has_timestamp(self):
        report = DiagnosticReport(sensor_id="test")
        assert report.timestamp > 0

    def test_report_equality(self):
        r1 = DiagnosticReport(sensor_id="a", is_connected=True, can_capture=True)
        r2 = DiagnosticReport(sensor_id="a", is_connected=True, can_capture=True)
        assert r1 == r2

    def test_report_hash(self):
        r = DiagnosticReport(sensor_id="a", is_connected=True, can_capture=True)
        assert isinstance(hash(r), int)


# --- Enums ---

class TestVisionEnums:
    """Tests for enum completeness."""

    def test_vision_modes(self):
        assert len(VisionMode) == 7
        assert VisionMode.DAYLIGHT.value == "daylight"
        assert VisionMode.AUTO.value == "auto"

    def test_sensor_issues(self):
        assert len(SensorIssue) == 11
        assert SensorIssue.DISCONNECTED.value == "disconnected"
        assert SensorIssue.DRIVER_ERROR.value == "driver_error"

    def test_degradation_types(self):
        assert len(DegradationType) == 12
        assert DegradationType.TOTAL_BLACK.value == "total_black"
        assert DegradationType.OCCLUSION.value == "occlusion"
