"""
USBWebcamSensor - USB camera implementation via OpenCV.

Wraps cv2.VideoCapture with graceful degradation, health monitoring,
and automatic flip correction (camera mounted upside-down).

Hardware: Innomaker U20CAM-1080PD&N-S1 (USB 2.0 UVC)
- /dev/video0 (primary), /dev/video1 (metadata)
- 640x480@30fps (default), 1920x1080@5fps (USB 2.0 YUYV limit)
- Mounted upside-down -> cv2.flip(frame, -1)

Phase 1: Sensor Abstraction Layer (VISION_SPEC.md)
"""

import logging
import time
from typing import Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore[assignment]

from agent_core.vision.models import (
    DiagnosticReport,
    Frame,
    SensorIssue,
    VisionMode,
)
from agent_core.vision.sensors.base import SensorCapabilities
from agent_core.vision.sensors.health import SensorHealth

logger = logging.getLogger(__name__)

# Defaults for Innomaker U20CAM
DEFAULT_DEVICE = 0  # /dev/video0
DEFAULT_RESOLUTION = (640, 480)
DEFAULT_FPS = 30.0
CAPTURE_TIMEOUT_S = 5.0

# Health monitoring
_CONSECUTIVE_FAIL_THRESHOLD = 3
_LATENCY_WARNING_MS = 500.0


class USBWebcamSensor:
    """USB webcam sensor via OpenCV VideoCapture.

    Implements VisionSensor protocol. Handles:
    - Opening/closing the camera device
    - Frame capture with timeout detection
    - Automatic flip correction (upside-down mount)
    - Health monitoring based on capture success rate
    - Graceful degradation on partial failures

    Usage:
        sensor = USBWebcamSensor(device=0)
        if sensor.open():
            frame = sensor.capture_frame()
            sensor.close()
    """

    def __init__(
        self,
        device: int = DEFAULT_DEVICE,
        sensor_id: str = "",
        resolution: Tuple[int, int] = DEFAULT_RESOLUTION,
        fps: float = DEFAULT_FPS,
        flip: bool = True,  # Camera mounted upside-down
    ):
        self._device = device
        self._sensor_id = sensor_id or f"usb-{device}"
        self._target_resolution = resolution
        self._target_fps = fps
        self._flip = flip

        self._cap: Optional["cv2.VideoCapture"] = None
        self._is_open = False
        self._sequence = 0
        self._mode = VisionMode.AUTO

        # Health tracking
        self._consecutive_failures = 0
        self._total_captures = 0
        self._total_failures = 0
        self._last_capture_latency_ms = 0.0
        self._last_frame_shape: Optional[Tuple[int, ...]] = None

    @property
    def sensor_id(self) -> str:
        return self._sensor_id

    @property
    def capabilities(self) -> SensorCapabilities:
        return SensorCapabilities(
            max_resolution=(1920, 1080),
            supported_resolutions=(
                (1920, 1080),
                (1280, 720),
                (640, 480),
                (320, 240),
            ),
            max_fps=30.0,
            supported_fps=(30.0, 15.0, 5.0),
            supported_modes=(VisionMode.DAYLIGHT, VisionMode.AUTO),
            has_autofocus=False,
            color_depth=8,
        )

    @property
    def health(self) -> SensorHealth:
        if not self._is_open or self._cap is None:
            return SensorHealth.disconnected()

        issues = []

        # Connection health
        connection = 1.0 if self._cap.isOpened() else 0.0

        # Stream health based on failure rate
        if self._total_captures == 0:
            stream = 1.0
        else:
            success_rate = 1.0 - (self._total_failures / self._total_captures)
            stream = max(0.0, success_rate)

        if self._consecutive_failures >= _CONSECUTIVE_FAIL_THRESHOLD:
            stream = max(0.0, stream - 0.3)
            issues.append(SensorIssue.FROZEN)

        # Resolution health
        resolution = 1.0
        if self._last_frame_shape is not None:
            actual_w = self._last_frame_shape[1]
            target_w = self._target_resolution[0]
            if target_w > 0:
                resolution = min(1.0, actual_w / target_w)
            if resolution < 0.5:
                issues.append(SensorIssue.PARTIAL_FRAME)

        # Latency
        latency = self._last_capture_latency_ms
        if latency > _LATENCY_WARNING_MS:
            issues.append(SensorIssue.LOW_FPS)

        return SensorHealth(
            connection=connection,
            stream=stream,
            resolution=resolution,
            color=1.0,  # Can't assess without preprocessing
            focus=1.0,  # Can't assess without preprocessing
            exposure=1.0,  # Can't assess without preprocessing
            noise=1.0,  # Can't assess without preprocessing
            latency_ms=latency,
            issues=issues,
        )

    @property
    def is_open(self) -> bool:
        return self._is_open and self._cap is not None and self._cap.isOpened()

    def open(self) -> bool:
        """Open the USB camera device."""
        if cv2 is None:
            logger.error("OpenCV (cv2) not installed - cannot open USB camera")
            return False

        try:
            self._cap = cv2.VideoCapture(self._device)
            if not self._cap.isOpened():
                logger.error("Failed to open camera device %d", self._device)
                self._cap = None
                return False

            # Set resolution
            w, h = self._target_resolution
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            self._cap.set(cv2.CAP_PROP_FPS, self._target_fps)

            # Verify actual settings
            actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            actual_fps = self._cap.get(cv2.CAP_PROP_FPS)

            logger.info(
                "Opened USB camera %d: %dx%d @ %.1f fps (requested %dx%d @ %.1f)",
                self._device, actual_w, actual_h, actual_fps,
                w, h, self._target_fps,
            )

            self._is_open = True
            self._sequence = 0
            self._consecutive_failures = 0
            self._total_captures = 0
            self._total_failures = 0
            return True

        except Exception:
            logger.exception("Error opening camera device %d", self._device)
            self._cap = None
            return False

    def close(self) -> None:
        """Release the camera device."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                logger.exception("Error releasing camera device %d", self._device)
            self._cap = None
        self._is_open = False

    def capture_frame(self) -> Optional[Frame]:
        """Capture a single frame from the USB camera.

        Returns None only if the camera is completely non-functional.
        Tracks health metrics for graceful degradation.
        """
        if not self.is_open or self._cap is None:
            return None

        self._total_captures += 1
        t0 = time.monotonic()

        try:
            ret, image = self._cap.read()
        except Exception:
            logger.exception("Exception during frame capture")
            self._consecutive_failures += 1
            self._total_failures += 1
            return None

        elapsed_ms = (time.monotonic() - t0) * 1000.0
        self._last_capture_latency_ms = elapsed_ms

        if not ret or image is None or image.size == 0:
            self._consecutive_failures += 1
            self._total_failures += 1
            if self._consecutive_failures >= _CONSECUTIVE_FAIL_THRESHOLD:
                logger.warning(
                    "Camera %d: %d consecutive capture failures",
                    self._device, self._consecutive_failures,
                )
            return None

        # Success - reset failure counter
        self._consecutive_failures = 0

        # Flip if camera is mounted upside-down
        if self._flip:
            image = cv2.flip(image, -1)

        self._last_frame_shape = image.shape
        self._sequence += 1

        return Frame(
            image=image,
            timestamp=time.time(),
            sensor_id=self._sensor_id,
            sequence_number=self._sequence,
            resolution=(image.shape[1], image.shape[0]),
            mode=self._mode,
        )

    def set_mode(self, mode: VisionMode) -> bool:
        """USB webcams only support DAYLIGHT and AUTO."""
        if mode in (VisionMode.DAYLIGHT, VisionMode.AUTO):
            self._mode = mode
            return True
        return False

    def set_resolution(self, width: int, height: int) -> bool:
        """Change capture resolution."""
        if not self.is_open or self._cap is None:
            return False

        if (width, height) not in self.capabilities.supported_resolutions:
            return False

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        # Verify
        actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if actual_w == width and actual_h == height:
            self._target_resolution = (width, height)
            return True

        logger.warning(
            "Resolution change failed: requested %dx%d, got %dx%d",
            width, height, actual_w, actual_h,
        )
        return False

    def diagnose(self) -> DiagnosticReport:
        """Full diagnostic report."""
        h = self.health
        details = {
            "type": "usb_webcam",
            "device": self._device,
            "flip": self._flip,
            "health_overall": round(h.overall, 3),
            "degradation_level": h.degradation_level.value,
            "total_captures": self._total_captures,
            "total_failures": self._total_failures,
            "consecutive_failures": self._consecutive_failures,
            "last_latency_ms": round(self._last_capture_latency_ms, 1),
        }

        actual_res = self._target_resolution
        actual_fps = self._target_fps
        if self._cap is not None and self._cap.isOpened():
            actual_res = (
                int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            )
            actual_fps = self._cap.get(cv2.CAP_PROP_FPS)

        return DiagnosticReport(
            sensor_id=self._sensor_id,
            is_connected=self.is_open,
            can_capture=self.is_open and self._consecutive_failures < _CONSECUTIVE_FAIL_THRESHOLD,
            current_resolution=actual_res,
            current_fps=actual_fps,
            issues=tuple(h.issues),
            details=details,
        )
