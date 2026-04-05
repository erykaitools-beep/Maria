"""
Tests for USBWebcamSensor - USB camera via OpenCV.

All tests mock cv2.VideoCapture so they run without a real camera.
Tests with real hardware should be run manually.

Covers:
- Protocol compliance
- Open/close lifecycle
- Frame capture with flip
- Health monitoring (failure tracking)
- Mode and resolution changes
- Diagnostics
- Graceful degradation on capture failures
"""

import time
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from agent_core.vision.models import SensorIssue, VisionMode
from agent_core.vision.sensors.base import VisionSensor
from agent_core.vision.sensors.health import DegradationLevel, SensorHealth
from agent_core.vision.sensors.usb_webcam import USBWebcamSensor


def _make_mock_cap(
    is_opened: bool = True,
    read_ok: bool = True,
    width: int = 640,
    height: int = 480,
    fps: float = 30.0,
):
    """Create a mock cv2.VideoCapture."""
    cap = MagicMock()
    cap.isOpened.return_value = is_opened

    if read_ok:
        img = np.zeros((height, width, 3), dtype=np.uint8)
        cap.read.return_value = (True, img)
    else:
        cap.read.return_value = (False, None)

    def mock_get(prop):
        # cv2 prop IDs: WIDTH=3, HEIGHT=4, FPS=5
        if prop == 3:
            return float(width)
        elif prop == 4:
            return float(height)
        elif prop == 5:
            return fps
        return 0.0

    cap.get.side_effect = mock_get
    return cap


# --- Protocol Compliance ---

class TestUSBWebcamProtocol:
    """USBWebcamSensor must satisfy VisionSensor protocol."""

    def test_is_vision_sensor(self):
        sensor = USBWebcamSensor()
        assert isinstance(sensor, VisionSensor)

    def test_has_sensor_id(self):
        sensor = USBWebcamSensor(device=2, sensor_id="usb-test")
        assert sensor.sensor_id == "usb-test"

    def test_default_sensor_id(self):
        sensor = USBWebcamSensor(device=0)
        assert sensor.sensor_id == "usb-0"


# --- Lifecycle ---

class TestUSBWebcamLifecycle:
    """Open/close lifecycle tests."""

    def test_initially_closed(self):
        sensor = USBWebcamSensor()
        assert sensor.is_open is False

    @patch("agent_core.vision.sensors.usb_webcam.cv2")
    def test_open_success(self, mock_cv2):
        mock_cv2.VideoCapture.return_value = _make_mock_cap()
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
        mock_cv2.CAP_PROP_FPS = 5

        sensor = USBWebcamSensor()
        assert sensor.open() is True
        assert sensor.is_open is True
        sensor.close()

    @patch("agent_core.vision.sensors.usb_webcam.cv2")
    def test_open_failure(self, mock_cv2):
        cap = _make_mock_cap(is_opened=False)
        mock_cv2.VideoCapture.return_value = cap

        sensor = USBWebcamSensor()
        assert sensor.open() is False
        assert sensor.is_open is False

    @patch("agent_core.vision.sensors.usb_webcam.cv2")
    def test_close_releases_cap(self, mock_cv2):
        cap = _make_mock_cap()
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
        mock_cv2.CAP_PROP_FPS = 5

        sensor = USBWebcamSensor()
        sensor.open()
        sensor.close()
        cap.release.assert_called_once()
        assert sensor.is_open is False

    @patch("agent_core.vision.sensors.usb_webcam.cv2")
    def test_health_disconnected_when_closed(self, mock_cv2):
        sensor = USBWebcamSensor()
        h = sensor.health
        assert h.degradation_level == DegradationLevel.BLIND


# --- Frame Capture ---

class TestUSBWebcamCapture:
    """Frame capture tests."""

    @patch("agent_core.vision.sensors.usb_webcam.cv2")
    def test_capture_frame(self, mock_cv2):
        cap = _make_mock_cap()
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
        mock_cv2.CAP_PROP_FPS = 5
        mock_cv2.flip.side_effect = lambda img, code: img

        sensor = USBWebcamSensor()
        sensor.open()
        frame = sensor.capture_frame()

        assert frame is not None
        assert frame.is_valid
        assert frame.sensor_id == "usb-0"
        sensor.close()

    @patch("agent_core.vision.sensors.usb_webcam.cv2")
    def test_capture_calls_flip(self, mock_cv2):
        """Camera is mounted upside-down, so flip(-1) should be called."""
        cap = _make_mock_cap()
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
        mock_cv2.CAP_PROP_FPS = 5
        mock_cv2.flip.return_value = np.zeros((480, 640, 3), dtype=np.uint8)

        sensor = USBWebcamSensor(flip=True)
        sensor.open()
        sensor.capture_frame()

        mock_cv2.flip.assert_called_once()
        args = mock_cv2.flip.call_args
        assert args[0][1] == -1  # flip code -1 = both axes
        sensor.close()

    @patch("agent_core.vision.sensors.usb_webcam.cv2")
    def test_capture_no_flip(self, mock_cv2):
        """When flip=False, no flip should occur."""
        cap = _make_mock_cap()
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
        mock_cv2.CAP_PROP_FPS = 5

        sensor = USBWebcamSensor(flip=False)
        sensor.open()
        sensor.capture_frame()

        mock_cv2.flip.assert_not_called()
        sensor.close()

    @patch("agent_core.vision.sensors.usb_webcam.cv2")
    def test_capture_failure_returns_none(self, mock_cv2):
        cap = _make_mock_cap(read_ok=False)
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
        mock_cv2.CAP_PROP_FPS = 5

        sensor = USBWebcamSensor()
        sensor.open()
        frame = sensor.capture_frame()
        assert frame is None
        sensor.close()

    def test_capture_when_closed_returns_none(self):
        sensor = USBWebcamSensor()
        assert sensor.capture_frame() is None

    @patch("agent_core.vision.sensors.usb_webcam.cv2")
    def test_sequence_increments(self, mock_cv2):
        cap = _make_mock_cap()
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
        mock_cv2.CAP_PROP_FPS = 5
        mock_cv2.flip.side_effect = lambda img, code: img

        sensor = USBWebcamSensor()
        sensor.open()
        f1 = sensor.capture_frame()
        f2 = sensor.capture_frame()
        assert f2.sequence_number == f1.sequence_number + 1
        sensor.close()


# --- Health Monitoring ---

class TestUSBWebcamHealth:
    """Health monitoring based on capture success/failure."""

    @patch("agent_core.vision.sensors.usb_webcam.cv2")
    def test_healthy_after_open(self, mock_cv2):
        cap = _make_mock_cap()
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
        mock_cv2.CAP_PROP_FPS = 5

        sensor = USBWebcamSensor()
        sensor.open()
        h = sensor.health
        assert h.overall >= 0.9
        sensor.close()

    @patch("agent_core.vision.sensors.usb_webcam.cv2")
    def test_health_degrades_on_failures(self, mock_cv2):
        cap = _make_mock_cap(read_ok=False)
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
        mock_cv2.CAP_PROP_FPS = 5

        sensor = USBWebcamSensor()
        sensor.open()

        # Trigger multiple failures
        for _ in range(5):
            sensor.capture_frame()

        h = sensor.health
        assert h.overall < 0.9
        assert SensorIssue.FROZEN in h.issues
        sensor.close()

    @patch("agent_core.vision.sensors.usb_webcam.cv2")
    def test_consecutive_failures_tracked(self, mock_cv2):
        cap = _make_mock_cap(read_ok=False)
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
        mock_cv2.CAP_PROP_FPS = 5

        sensor = USBWebcamSensor()
        sensor.open()

        for _ in range(3):
            sensor.capture_frame()

        assert sensor._consecutive_failures == 3
        sensor.close()

    @patch("agent_core.vision.sensors.usb_webcam.cv2")
    def test_success_resets_consecutive_failures(self, mock_cv2):
        cap = _make_mock_cap()
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
        mock_cv2.CAP_PROP_FPS = 5
        mock_cv2.flip.side_effect = lambda img, code: img

        sensor = USBWebcamSensor()
        sensor.open()

        # Simulate some failures then success
        sensor._consecutive_failures = 5
        sensor._total_failures = 5
        sensor._total_captures = 5

        sensor.capture_frame()  # success
        assert sensor._consecutive_failures == 0
        sensor.close()


# --- Mode and Resolution ---

class TestUSBWebcamMode:
    """Mode and resolution change tests."""

    def test_set_daylight_mode(self):
        sensor = USBWebcamSensor()
        assert sensor.set_mode(VisionMode.DAYLIGHT) is True

    def test_set_auto_mode(self):
        sensor = USBWebcamSensor()
        assert sensor.set_mode(VisionMode.AUTO) is True

    def test_set_unsupported_mode(self):
        sensor = USBWebcamSensor()
        assert sensor.set_mode(VisionMode.NIGHT) is False

    def test_set_resolution_when_closed(self):
        sensor = USBWebcamSensor()
        assert sensor.set_resolution(320, 240) is False

    @patch("agent_core.vision.sensors.usb_webcam.cv2")
    def test_set_resolution_success(self, mock_cv2):
        cap = _make_mock_cap(width=320, height=240)
        # After setting, get() should return new values
        cap.get.side_effect = lambda p: {3: 320.0, 4: 240.0, 5: 30.0}.get(p, 0.0)
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
        mock_cv2.CAP_PROP_FPS = 5

        sensor = USBWebcamSensor()
        sensor.open()
        assert sensor.set_resolution(320, 240) is True
        sensor.close()


# --- Diagnostics ---

class TestUSBWebcamDiagnostics:
    """Tests for diagnose()."""

    def test_diagnose_when_closed(self):
        sensor = USBWebcamSensor()
        report = sensor.diagnose()
        assert report.is_connected is False
        assert report.sensor_id == "usb-0"

    @patch("agent_core.vision.sensors.usb_webcam.cv2")
    def test_diagnose_when_open(self, mock_cv2):
        cap = _make_mock_cap()
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
        mock_cv2.CAP_PROP_FPS = 5

        sensor = USBWebcamSensor()
        sensor.open()
        report = sensor.diagnose()

        assert report.is_connected is True
        assert report.can_capture is True
        assert report.details["type"] == "usb_webcam"
        assert report.details["device"] == 0
        assert report.details["flip"] is True
        sensor.close()

    @patch("agent_core.vision.sensors.usb_webcam.cv2")
    def test_diagnose_after_failures(self, mock_cv2):
        cap = _make_mock_cap(read_ok=False)
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
        mock_cv2.CAP_PROP_FPS = 5

        sensor = USBWebcamSensor()
        sensor.open()
        for _ in range(3):
            sensor.capture_frame()

        report = sensor.diagnose()
        assert report.can_capture is False
        assert report.details["consecutive_failures"] == 3
        sensor.close()


# --- cv2 not installed ---

class TestUSBWebcamNoCv2:
    """Tests for behavior when OpenCV is not installed."""

    @patch("agent_core.vision.sensors.usb_webcam.cv2", None)
    def test_open_fails_without_cv2(self):
        sensor = USBWebcamSensor()
        assert sensor.open() is False
