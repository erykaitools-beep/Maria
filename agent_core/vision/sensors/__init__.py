"""
Vision sensors - camera abstraction layer.

Provides VisionSensor protocol and concrete implementations:
    USBWebcamSensor - USB cameras via OpenCV
    MockSensor      - for testing
"""

from agent_core.vision.sensors.base import SensorCapabilities, VisionSensor
from agent_core.vision.sensors.health import (
    DegradationLevel,
    SensorHealth,
    classify_degradation_level,
)
from agent_core.vision.sensors.mock_sensor import MockSensor
from agent_core.vision.sensors.usb_webcam import USBWebcamSensor

__all__ = [
    "VisionSensor",
    "SensorCapabilities",
    "SensorHealth",
    "DegradationLevel",
    "classify_degradation_level",
    "MockSensor",
    "USBWebcamSensor",
]
