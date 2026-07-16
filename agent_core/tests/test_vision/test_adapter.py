"""
Tests for VisionPerceptionAdapter - K1 integration.

Covers:
- Regular vision_percept events
- Motion events
- Alert events (danger level)
- Health change events
- Event structure (PerceptionEvent fields)
- Edge cases (None percept, no motion)
"""

import pytest

from agent_core.perception.event import PerceptionEvent, PerceptionSource
from agent_core.vision.adapter import VisionPerceptionAdapter
from agent_core.vision.modules.motion.detector import (
    AlertLevel,
    MotionClassification,
    MotionOutput,
)
from agent_core.vision.modules.scene.analyzer import SceneOutput
from agent_core.vision.percept import VisionPercept
from agent_core.vision.sensors.health import SensorHealth


# --- Helpers ---

def _percept(
    quality=0.8,
    motion_detected=False,
    motion_class=MotionClassification.NONE,
    alert_level=AlertLevel.NONE,
    health_overall=None,
):
    health = SensorHealth() if health_overall is None else SensorHealth(
        connection=health_overall, stream=health_overall,
    )
    motion = MotionOutput(
        module_name="motion",
        motion_detected=motion_detected,
        motion_level=0.3 if motion_detected else 0.0,
        classification=motion_class,
        alert_level=alert_level,
    ) if motion_detected or motion_class != MotionClassification.NONE else None

    return VisionPercept(
        vision_health=health,
        quality=quality,
        motion=motion,
        summary="Test summary",
        sensor_id="test-0",
    )


# --- Basic Events ---

class TestAdapterBasicEvents:
    def test_always_emits_percept_event(self):
        adapter = VisionPerceptionAdapter()
        events = adapter.adapt(_percept())

        assert len(events) >= 1
        assert events[0].event_type == "vision_percept"

    def test_percept_event_structure(self):
        adapter = VisionPerceptionAdapter()
        events = adapter.adapt(_percept())
        e = events[0]

        assert isinstance(e, PerceptionEvent)
        assert e.source == PerceptionSource.SENSOR
        assert e.event_type == "vision_percept"
        assert "quality" in e.payload
        assert "summary" in e.payload
        assert "sensor_id" in e.payload
        assert len(e.event_id) > 0

    def test_none_percept_returns_empty(self):
        adapter = VisionPerceptionAdapter()
        events = adapter.adapt(None)
        assert events == []


# --- Motion Events ---

class TestAdapterMotionEvents:
    def test_motion_emits_event(self):
        adapter = VisionPerceptionAdapter()
        events = adapter.adapt(_percept(
            motion_detected=True,
            motion_class=MotionClassification.PERSON_MOVEMENT,
            alert_level=AlertLevel.ATTENTION,
        ))

        types = [e.event_type for e in events]
        assert "vision_motion" in types

    def test_motion_event_payload(self):
        adapter = VisionPerceptionAdapter()
        events = adapter.adapt(_percept(
            motion_detected=True,
            motion_class=MotionClassification.PERSON_MOVEMENT,
            alert_level=AlertLevel.WARNING,
        ))

        motion_events = [e for e in events if e.event_type == "vision_motion"]
        assert len(motion_events) == 1
        e = motion_events[0]
        assert e.payload["classification"] == "person_movement"
        assert e.payload["alert_level"] == "warning"

    def test_ambient_motion_no_event(self):
        adapter = VisionPerceptionAdapter()
        events = adapter.adapt(_percept(
            motion_detected=True,
            motion_class=MotionClassification.AMBIENT,
            alert_level=AlertLevel.NONE,
        ))

        types = [e.event_type for e in events]
        assert "vision_motion" not in types

    def test_camera_shake_no_event(self):
        """Wind/foliage/sensor noise (shake) must not ping the operator."""
        adapter = VisionPerceptionAdapter()
        events = adapter.adapt(_percept(
            motion_detected=True,
            motion_class=MotionClassification.CAMERA_SHAKE,
            alert_level=AlertLevel.ATTENTION,
        ))

        types = [e.event_type for e in events]
        assert "vision_motion" not in types

    def test_object_movement_emits_event(self):
        adapter = VisionPerceptionAdapter()
        events = adapter.adapt(_percept(
            motion_detected=True,
            motion_class=MotionClassification.OBJECT_MOVEMENT,
            alert_level=AlertLevel.ATTENTION,
        ))

        types = [e.event_type for e in events]
        assert "vision_motion" in types

    def test_no_motion_no_event(self):
        adapter = VisionPerceptionAdapter()
        events = adapter.adapt(_percept(motion_detected=False))

        types = [e.event_type for e in events]
        assert "vision_motion" not in types


# --- Alert Events ---

class TestAdapterAlertEvents:
    def test_danger_emits_alert(self):
        adapter = VisionPerceptionAdapter()
        events = adapter.adapt(_percept(
            motion_detected=True,
            motion_class=MotionClassification.PERSON_MOVEMENT,
            alert_level=AlertLevel.DANGER,
        ))

        types = [e.event_type for e in events]
        assert "vision_alert" in types

    def test_alert_high_priority(self):
        adapter = VisionPerceptionAdapter()
        events = adapter.adapt(_percept(
            motion_detected=True,
            motion_class=MotionClassification.PERSON_MOVEMENT,
            alert_level=AlertLevel.DANGER,
        ))

        alerts = [e for e in events if e.event_type == "vision_alert"]
        assert alerts[0].priority >= 0.8

    def test_warning_no_alert_event(self):
        adapter = VisionPerceptionAdapter()
        events = adapter.adapt(_percept(
            motion_detected=True,
            motion_class=MotionClassification.PERSON_MOVEMENT,
            alert_level=AlertLevel.WARNING,
        ))

        types = [e.event_type for e in events]
        assert "vision_alert" not in types


# --- Health Events ---

class TestAdapterHealthEvents:
    def test_health_change_emits_event(self):
        adapter = VisionPerceptionAdapter()

        # First call sets baseline
        adapter.adapt(_percept(health_overall=1.0))

        # Significant drop
        events = adapter.adapt(_percept(health_overall=0.3))

        types = [e.event_type for e in events]
        assert "vision_health" in types

    def test_small_health_change_no_event(self):
        adapter = VisionPerceptionAdapter()
        adapter.adapt(_percept(health_overall=1.0))

        events = adapter.adapt(_percept(health_overall=0.9))

        types = [e.event_type for e in events]
        assert "vision_health" not in types

    def test_first_call_no_health_event(self):
        adapter = VisionPerceptionAdapter()
        events = adapter.adapt(_percept())

        types = [e.event_type for e in events]
        assert "vision_health" not in types
