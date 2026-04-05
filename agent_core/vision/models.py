"""
Vision data models - shared types for the vision subsystem.

Frame, VisionMode, and supporting enums used across sensors,
preprocessing, modules, and cortex layers.

Phase 1: Sensor Abstraction Layer (VISION_SPEC.md)
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


class VisionMode(Enum):
    """Operating mode for the vision system."""
    DAYLIGHT = "daylight"
    LOWLIGHT = "lowlight"
    NIGHT = "night"
    HDR = "hdr"
    AUTO = "auto"
    MOTION_PRIORITY = "motion"
    DETAIL_PRIORITY = "detail"


class DegradationType(Enum):
    """Types of image degradation detected."""
    TOTAL_BLACK = "total_black"
    TOTAL_WHITE = "total_white"
    FROZEN = "frozen"
    PARTIAL_FRAME = "partial_frame"
    HEAVY_NOISE = "heavy_noise"
    MOTION_BLUR = "motion_blur"
    FOCUS_BLUR = "focus_blur"
    COLOR_SHIFT = "color_shift"
    LOW_CONTRAST = "low_contrast"
    ARTIFACTS = "artifacts"
    OCCLUSION = "occlusion"
    LOW_RESOLUTION = "low_resolution"


class SensorIssue(Enum):
    """Problems that a sensor can report."""
    DISCONNECTED = "disconnected"
    LOW_FPS = "low_fps"
    OVEREXPOSED = "overexposed"
    UNDEREXPOSED = "underexposed"
    BLURRY = "blurry"
    NOISY = "noisy"
    FROZEN = "frozen"
    COLOR_SHIFT = "color_shift"
    PARTIAL_FRAME = "partial_frame"
    TIMEOUT = "timeout"
    DRIVER_ERROR = "driver_error"


@dataclass(frozen=True)
class Frame:
    """A single captured frame from a vision sensor.

    The image data is a numpy array in BGR format (OpenCV default).
    Shape: (height, width, channels) or (height, width) for grayscale.
    """

    image: np.ndarray
    timestamp: float = field(default_factory=time.time)
    sensor_id: str = ""
    sequence_number: int = 0
    resolution: Tuple[int, int] = (0, 0)  # (width, height)
    mode: VisionMode = VisionMode.AUTO

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Frame):
            return NotImplemented
        return (
            np.array_equal(self.image, other.image)
            and self.sensor_id == other.sensor_id
            and self.sequence_number == other.sequence_number
        )

    def __hash__(self) -> int:
        return hash((self.sensor_id, self.sequence_number, self.timestamp))

    @property
    def width(self) -> int:
        if self.image.ndim >= 2:
            return self.image.shape[1]
        return 0

    @property
    def height(self) -> int:
        if self.image.ndim >= 2:
            return self.image.shape[0]
        return 0

    @property
    def channels(self) -> int:
        if self.image.ndim == 3:
            return self.image.shape[2]
        return 1

    @property
    def is_grayscale(self) -> bool:
        return self.channels == 1

    @property
    def is_valid(self) -> bool:
        """Frame has actual image data."""
        return self.image is not None and self.image.size > 0


@dataclass(frozen=True)
class DiagnosticReport:
    """Full diagnostic report from a sensor."""

    sensor_id: str
    timestamp: float = field(default_factory=time.time)
    is_connected: bool = False
    can_capture: bool = False
    current_resolution: Tuple[int, int] = (0, 0)
    current_fps: float = 0.0
    issues: Tuple[SensorIssue, ...] = ()
    details: Dict[str, Any] = field(default_factory=dict)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DiagnosticReport):
            return NotImplemented
        return (
            self.sensor_id == other.sensor_id
            and self.is_connected == other.is_connected
            and self.can_capture == other.can_capture
            and self.issues == other.issues
        )

    def __hash__(self) -> int:
        return hash((self.sensor_id, self.is_connected, self.can_capture))
