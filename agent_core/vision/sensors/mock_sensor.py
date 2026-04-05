"""
MockSensor - simulates vision sensor behavior for testing.

Can simulate any degradation level, specific issues, and failure modes.
Used extensively in unit tests and for development without a real camera.

Phase 1: Sensor Abstraction Layer (VISION_SPEC.md)
"""

import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from agent_core.vision.models import (
    DiagnosticReport,
    Frame,
    SensorIssue,
    VisionMode,
)
from agent_core.vision.sensors.base import SensorCapabilities
from agent_core.vision.sensors.health import SensorHealth


class MockSensor:
    """Mock vision sensor for testing.

    Implements VisionSensor protocol. Generates synthetic frames and
    allows injecting specific health states and failure modes.

    Usage:
        # Healthy sensor
        sensor = MockSensor()
        frame = sensor.capture_frame()

        # Sensor with problems
        sensor = MockSensor(
            health_override=SensorHealth(focus=0.3, noise=0.4),
        )

        # Completely broken sensor
        sensor = MockSensor(fail_capture=True)
    """

    def __init__(
        self,
        sensor_id: str = "mock-0",
        resolution: Tuple[int, int] = (640, 480),
        fps: float = 30.0,
        health_override: Optional[SensorHealth] = None,
        fail_capture: bool = False,
        fail_open: bool = False,
        generate_noise: bool = False,
        frozen_frame: bool = False,
    ):
        self._sensor_id = sensor_id
        self._resolution = resolution
        self._fps = fps
        self._health_override = health_override
        self._fail_capture = fail_capture
        self._fail_open = fail_open
        self._generate_noise = generate_noise
        self._frozen_frame = frozen_frame

        self._is_open = False
        self._sequence = 0
        self._mode = VisionMode.AUTO
        self._last_frame: Optional[np.ndarray] = None

        self._capabilities = SensorCapabilities(
            max_resolution=resolution,
            supported_resolutions=(resolution, (320, 240)),
            max_fps=fps,
            supported_fps=(fps, 15.0),
            supported_modes=(
                VisionMode.DAYLIGHT,
                VisionMode.LOWLIGHT,
                VisionMode.AUTO,
            ),
            has_autofocus=False,
            color_depth=8,
        )

    @property
    def sensor_id(self) -> str:
        return self._sensor_id

    @property
    def capabilities(self) -> SensorCapabilities:
        return self._capabilities

    @property
    def health(self) -> SensorHealth:
        if self._health_override is not None:
            return self._health_override
        if not self._is_open:
            return SensorHealth.disconnected()
        return SensorHealth.perfect()

    @property
    def is_open(self) -> bool:
        return self._is_open

    def open(self) -> bool:
        if self._fail_open:
            return False
        self._is_open = True
        self._sequence = 0
        return True

    def close(self) -> None:
        self._is_open = False
        self._last_frame = None

    def capture_frame(self) -> Optional[Frame]:
        if not self._is_open or self._fail_capture:
            return None

        w, h = self._resolution
        self._sequence += 1

        if self._frozen_frame and self._last_frame is not None:
            image = self._last_frame.copy()
        elif self._generate_noise:
            image = np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)
        else:
            # Generate a deterministic test pattern (color gradient)
            image = self._generate_test_pattern(w, h)

        self._last_frame = image

        return Frame(
            image=image,
            timestamp=time.time(),
            sensor_id=self._sensor_id,
            sequence_number=self._sequence,
            resolution=(w, h),
            mode=self._mode,
        )

    def set_mode(self, mode: VisionMode) -> bool:
        if mode in self._capabilities.supported_modes:
            self._mode = mode
            return True
        return False

    def set_resolution(self, width: int, height: int) -> bool:
        if (width, height) in self._capabilities.supported_resolutions:
            self._resolution = (width, height)
            return True
        return False

    def diagnose(self) -> DiagnosticReport:
        h = self.health
        return DiagnosticReport(
            sensor_id=self._sensor_id,
            is_connected=self._is_open and not self._fail_capture,
            can_capture=self._is_open and not self._fail_capture,
            current_resolution=self._resolution,
            current_fps=self._fps if self._is_open else 0.0,
            issues=tuple(h.issues),
            details={
                "type": "mock",
                "health_overall": round(h.overall, 3),
                "degradation_level": h.degradation_level.value,
            },
        )

    # --- Mock-specific methods (not part of VisionSensor protocol) ---

    def set_health(self, health: SensorHealth) -> None:
        """Inject a specific health state for testing."""
        self._health_override = health

    def set_fail_capture(self, fail: bool) -> None:
        """Toggle capture failure."""
        self._fail_capture = fail

    def _generate_test_pattern(self, width: int, height: int) -> np.ndarray:
        """Generate a deterministic color gradient test pattern."""
        # Horizontal blue gradient, vertical green gradient
        image = np.zeros((height, width, 3), dtype=np.uint8)
        for y in range(height):
            for x in range(min(width, 4)):
                pass  # Skip per-pixel loop for performance
        # Fast vectorized fill
        row = np.linspace(0, 255, width, dtype=np.uint8)
        col = np.linspace(0, 255, height, dtype=np.uint8)
        image[:, :, 0] = row[np.newaxis, :]          # Blue channel
        image[:, :, 1] = col[:, np.newaxis]           # Green channel
        image[:, :, 2] = 128                          # Red channel constant
        return image
