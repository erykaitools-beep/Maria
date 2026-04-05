"""
Motion detection module - detects and classifies movement.

Uses frame differencing (lightweight, no ML dependencies).
Works even with very poor image quality (required_quality=0.2).
"""

from agent_core.vision.modules.motion.detector import (
    MotionModule,
    MotionOutput,
    MotionRegion,
    MotionClassification,
    AlertLevel,
)

__all__ = [
    "MotionModule",
    "MotionOutput",
    "MotionRegion",
    "MotionClassification",
    "AlertLevel",
]
