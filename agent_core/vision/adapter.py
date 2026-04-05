"""
VisionPerceptionAdapter - integrates Vision with K1 Unified Perception.

Converts VisionPercept into PerceptionEvents that flow through
the homeostasis tick loop like all other sensory data.

Event types:
- vision_percept: Regular perception tick (dedupable)
- vision_motion: Motion detected (not dedupable)
- vision_alert: Significant event (high priority)
- vision_health: Vision health changed (dedupable)

Phase 4: Vision Cortex (VISION_SPEC.md)
"""

import time
import uuid
from typing import List, Optional

from agent_core.perception.event import PerceptionEvent, PerceptionSource
from agent_core.vision.modules.motion.detector import AlertLevel, MotionClassification
from agent_core.vision.percept import VisionPercept


# Register new event types (to be added to EVENT_TYPE_DEFAULTS if wired)
VISION_EVENT_TYPES = {
    "vision_percept":  (0.3, 5.0, True),   # Regular tick, low priority, dedupable
    "vision_motion":   (0.7, 60.0, False),  # Motion detected, medium priority
    "vision_alert":    (0.9, 0.0, False),   # Alert (danger), high priority
    "vision_health":   (0.4, 30.0, True),   # Health status, dedupable
}


class VisionPerceptionAdapter:
    """Converts VisionPercept to K1 PerceptionEvents.

    Usage:
        adapter = VisionPerceptionAdapter()
        events = adapter.adapt(percept)
        for event in events:
            perception_buffer.add(event)
    """

    def __init__(self):
        self._last_health_overall: Optional[float] = None
        self._last_motion_alert: Optional[str] = None

    def adapt(self, percept: VisionPercept) -> List[PerceptionEvent]:
        """Convert a VisionPercept to PerceptionEvents.

        May produce multiple events from one percept (e.g., regular tick
        + motion alert). Returns empty list for None input.
        """
        if percept is None:
            return []

        events = []

        # Always emit regular perception tick
        events.append(self._make_percept_event(percept))

        # Motion event (if motion detected)
        if percept.motion and percept.motion.motion_detected:
            if percept.motion.classification != MotionClassification.AMBIENT:
                events.append(self._make_motion_event(percept))

            # High-priority alert for danger
            if percept.motion.alert_level == AlertLevel.DANGER:
                events.append(self._make_alert_event(percept, "motion_danger"))

        # Health change event
        health_now = round(percept.vision_health.overall, 1)
        if self._last_health_overall is not None:
            health_delta = abs(health_now - self._last_health_overall)
            if health_delta >= 0.2:
                events.append(self._make_health_event(percept))
        self._last_health_overall = health_now

        return events

    def _make_percept_event(self, percept: VisionPercept) -> PerceptionEvent:
        defaults = VISION_EVENT_TYPES["vision_percept"]
        return PerceptionEvent(
            event_id=str(uuid.uuid4()),
            source=PerceptionSource.SENSOR,
            event_type="vision_percept",
            priority=defaults[0],
            timestamp=percept.timestamp,
            payload={
                "summary": percept.summary,
                "quality": round(percept.quality, 3),
                "health": round(percept.vision_health.overall, 3),
                "modules_run": percept.modules_run,
                "sensor_id": percept.sensor_id,
            },
            ttl=defaults[1],
            parent_event_id=None,
        )

    def _make_motion_event(self, percept: VisionPercept) -> PerceptionEvent:
        defaults = VISION_EVENT_TYPES["vision_motion"]
        motion = percept.motion
        return PerceptionEvent(
            event_id=str(uuid.uuid4()),
            source=PerceptionSource.SENSOR,
            event_type="vision_motion",
            priority=defaults[0],
            timestamp=percept.timestamp,
            payload={
                "motion_level": round(motion.motion_level, 3),
                "classification": motion.classification.value,
                "alert_level": motion.alert_level.value,
                "regions_count": len(motion.regions),
                "summary": percept.summary,
            },
            ttl=defaults[1],
            parent_event_id=None,
        )

    def _make_alert_event(self, percept: VisionPercept, alert_type: str) -> PerceptionEvent:
        defaults = VISION_EVENT_TYPES["vision_alert"]
        return PerceptionEvent(
            event_id=str(uuid.uuid4()),
            source=PerceptionSource.SENSOR,
            event_type="vision_alert",
            priority=defaults[0],
            timestamp=percept.timestamp,
            payload={
                "alert_type": alert_type,
                "summary": percept.summary,
                "quality": round(percept.quality, 3),
            },
            ttl=defaults[1],
            parent_event_id=None,
        )

    def _make_health_event(self, percept: VisionPercept) -> PerceptionEvent:
        defaults = VISION_EVENT_TYPES["vision_health"]
        return PerceptionEvent(
            event_id=str(uuid.uuid4()),
            source=PerceptionSource.SENSOR,
            event_type="vision_health",
            priority=defaults[0],
            timestamp=percept.timestamp,
            payload={
                "health": percept.vision_health.to_dict(),
                "description": percept.vision_health.to_human_description(),
            },
            ttl=defaults[1],
            parent_event_id=None,
        )
