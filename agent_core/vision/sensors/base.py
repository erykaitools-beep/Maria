"""
VisionSensor protocol and SensorCapabilities.

Abstract interface that all vision sensors must implement.
USB webcams, IP cameras, and mock sensors all follow this contract.

Phase 1: Sensor Abstraction Layer (VISION_SPEC.md)
"""

from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Tuple

try:
    from typing import Protocol, runtime_checkable
except ImportError:
    from typing_extensions import Protocol, runtime_checkable

from agent_core.vision.models import (
    DiagnosticReport,
    Frame,
    VisionMode,
)
from agent_core.vision.sensors.health import SensorHealth


@dataclass(frozen=True)
class SensorCapabilities:
    """What a vision sensor can do.

    Describes hardware/software capabilities so the cortex can make
    informed decisions about which sensor to use and how.
    """

    # Resolution
    max_resolution: Tuple[int, int] = (640, 480)  # (width, height)
    supported_resolutions: Tuple[Tuple[int, int], ...] = ((640, 480),)

    # Framerate
    max_fps: float = 30.0
    supported_fps: Tuple[float, ...] = (30.0,)

    # Modes
    supported_modes: Tuple[VisionMode, ...] = (VisionMode.DAYLIGHT,)

    # Features
    has_autofocus: bool = False
    has_zoom: bool = False
    zoom_range: Optional[Tuple[float, float]] = None
    has_pan_tilt: bool = False

    # Quality characteristics
    dynamic_range_db: float = 60.0
    low_light_sensitivity: float = 0.3  # 0-1
    color_depth: int = 8  # bits per channel


@runtime_checkable
class VisionSensor(Protocol):
    """Abstract interface for all vision sensors.

    Every sensor (USB webcam, IP camera, mock) implements this protocol.
    The VisionCortex uses this interface exclusively - it never knows
    what kind of sensor it's talking to.
    """

    @property
    def sensor_id(self) -> str:
        """Unique sensor identifier (e.g. 'usb-0', 'ip-192.168.1.50')."""
        ...

    @property
    def capabilities(self) -> SensorCapabilities:
        """What this sensor can do (resolution, FPS, modes)."""
        ...

    @property
    def health(self) -> SensorHealth:
        """Current health state (0.0-1.0 per component)."""
        ...

    @property
    def is_open(self) -> bool:
        """Whether the sensor connection is currently open."""
        ...

    def open(self) -> bool:
        """Open the sensor connection. Returns True on success."""
        ...

    def close(self) -> None:
        """Close the sensor connection and release resources."""
        ...

    def capture_frame(self) -> Optional[Frame]:
        """Capture a single frame.

        Returns None if the sensor is completely non-functional.
        Even degraded sensors should return a frame when possible.
        """
        ...

    def set_mode(self, mode: VisionMode) -> bool:
        """Change the operating mode. Returns True on success."""
        ...

    def set_resolution(self, width: int, height: int) -> bool:
        """Change capture resolution. Returns True on success."""
        ...

    def diagnose(self) -> DiagnosticReport:
        """Full diagnostic report of sensor state."""
        ...
