"""
VisionPercept - unified visual perception output.

This is what Maria "sees" - integrates results from all modules
into one coherent representation with a natural language summary.

Phase 4: Vision Cortex (VISION_SPEC.md)
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agent_core.vision.models import VisionMode
from agent_core.vision.modules.base import ModuleOutput
from agent_core.vision.modules.motion.detector import MotionOutput
from agent_core.vision.modules.scene.analyzer import SceneOutput
from agent_core.vision.preprocessing.preprocessor import ProcessedFrame
from agent_core.vision.sensors.health import SensorHealth


@dataclass
class VisionPercept:
    """Unified visual perception - what Maria sees.

    Integrates sensor health, preprocessing quality, and module outputs
    into a single representation for consciousness.
    """

    timestamp: float = field(default_factory=time.time)

    # Sensor state
    vision_health: SensorHealth = field(default_factory=SensorHealth.perfect)
    vision_mode: VisionMode = VisionMode.AUTO
    quality: float = 0.0

    # Module outputs (None = module didn't run or quality too low)
    motion: Optional[MotionOutput] = None
    scene: Optional[SceneOutput] = None

    # Summary
    summary: str = ""

    # Processing
    total_processing_time_ms: float = 0.0
    modules_run: List[str] = field(default_factory=list)
    sensor_id: str = ""

    def to_consciousness_input(self) -> Dict[str, Any]:
        """Format for Maria Consciousness (dual format: human + technical)."""
        return {
            "human": self.summary,
            "technical": {
                "quality": round(self.quality, 3),
                "mode": self.vision_mode.value,
                "health": self.vision_health.to_dict(),
                "motion": self.motion.to_dict() if self.motion else None,
                "scene": self.scene.to_dict() if self.scene else None,
                "modules_run": self.modules_run,
                "processing_ms": round(self.total_processing_time_ms, 1),
            },
        }

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "quality": round(self.quality, 3),
            "vision_mode": self.vision_mode.value,
            "health_overall": round(self.vision_health.overall, 3),
            "summary": self.summary,
            "motion": self.motion.to_dict() if self.motion else None,
            "scene": self.scene.to_dict() if self.scene else None,
            "modules_run": self.modules_run,
            "total_processing_time_ms": round(self.total_processing_time_ms, 1),
            "sensor_id": self.sensor_id,
        }


def generate_summary(
    health: SensorHealth,
    quality: float,
    motion: Optional[MotionOutput],
    scene: Optional[SceneOutput],
) -> str:
    """Generate natural language summary of what Maria sees (Polish).

    Combines sensor health, scene description, and motion detection
    into one coherent sentence Maria can use.
    """
    parts = []

    # Health-based prefix
    if health.overall < 0.3:
        return health.to_human_description()

    if health.overall < 0.6:
        parts.append("Widze niewyraznie, ale")

    # Scene description (from LLaVA or statistics)
    if scene and scene.description:
        if parts:
            parts.append(scene.description[0].lower() + scene.description[1:])
        else:
            parts.append(scene.description)

    # Motion info
    if motion and motion.motion_detected:
        from agent_core.vision.modules.motion.detector import (
            AlertLevel,
            MotionClassification,
        )

        motion_descs = {
            MotionClassification.PERSON_MOVEMENT: "Wykrylam ruch osoby",
            MotionClassification.OBJECT_MOVEMENT: "Cos sie poruszylo",
            MotionClassification.CAMERA_SHAKE: "Kamera sie trzesie",
            MotionClassification.AMBIENT: "Niewielki ruch w tle",
        }
        motion_desc = motion_descs.get(motion.classification, "Wykrylam ruch")

        if motion.alert_level == AlertLevel.DANGER:
            motion_desc += " - duzy, nagly ruch!"
        elif motion.alert_level == AlertLevel.WARNING:
            motion_desc += " - znaczacy ruch."

        if parts:
            parts.append(motion_desc + ".")
        else:
            parts.append(motion_desc + ".")

    if not parts:
        if quality > 0.5:
            parts.append("Widze, ale nic szczegolnego sie nie dzieje.")
        else:
            parts.append(health.to_human_description())

    return " ".join(parts)
