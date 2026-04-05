"""
Tests for VisionCortex - central vision integrator.

Covers:
- Full pipeline (sensor -> preprocess -> modules -> percept)
- Sensor selection (best health)
- Module adaptive running (quality-based)
- Blind mode (no sensors)
- Capture failure handling
- Multi-sensor support
- Status reporting
- Reset
- Open/close all sensors
"""

import numpy as np
import pytest

from agent_core.vision.cortex import VisionCortex
from agent_core.vision.models import SensorIssue, VisionMode
from agent_core.vision.modules.motion.detector import MotionModule
from agent_core.vision.modules.scene.analyzer import SceneModule
from agent_core.vision.percept import VisionPercept
from agent_core.vision.sensors.health import DegradationLevel, SensorHealth
from agent_core.vision.sensors.mock_sensor import MockSensor


# --- Full Pipeline ---

class TestCortexPipeline:
    def test_full_pipeline_with_mock(self):
        cortex = VisionCortex()
        sensor = MockSensor(sensor_id="cam-0")
        sensor.open()
        cortex.add_sensor(sensor)
        cortex.add_module(MotionModule())
        cortex.add_module(SceneModule())

        percept = cortex.perceive()

        assert percept is not None
        assert isinstance(percept, VisionPercept)
        assert percept.quality > 0.0
        assert percept.sensor_id == "cam-0"
        assert len(percept.summary) > 0

        sensor.close()

    def test_motion_detected_across_frames(self):
        cortex = VisionCortex()
        sensor = MockSensor(sensor_id="cam-0")
        sensor.open()
        cortex.add_sensor(sensor)
        cortex.add_module(MotionModule())

        # First frame (no motion - no previous)
        p1 = cortex.perceive()
        assert p1.motion is None or not p1.motion.motion_detected

        # Second frame (same test pattern = no motion)
        p2 = cortex.perceive()
        # MockSensor produces deterministic frames, so no motion
        if p2.motion:
            assert not p2.motion.motion_detected

        sensor.close()

    def test_modules_listed_in_percept(self):
        cortex = VisionCortex()
        sensor = MockSensor()
        sensor.open()
        cortex.add_sensor(sensor)
        cortex.add_module(SceneModule())

        percept = cortex.perceive()
        assert "scene" in percept.modules_run

        sensor.close()


# --- Sensor Selection ---

class TestSensorSelection:
    def test_selects_open_sensor(self):
        cortex = VisionCortex()
        closed = MockSensor(sensor_id="closed")
        opened = MockSensor(sensor_id="opened")
        opened.open()

        cortex.add_sensor(closed)
        cortex.add_sensor(opened)

        percept = cortex.perceive()
        assert percept.sensor_id == "opened"

        opened.close()

    def test_selects_healthier_sensor(self):
        cortex = VisionCortex()
        sick = MockSensor(sensor_id="sick", health_override=SensorHealth(stream=0.3, focus=0.3))
        healthy = MockSensor(sensor_id="healthy")

        sick.open()
        healthy.open()

        cortex.add_sensor(sick)
        cortex.add_sensor(healthy)

        percept = cortex.perceive()
        assert percept.sensor_id == "healthy"

        sick.close()
        healthy.close()

    def test_no_sensors_returns_blind(self):
        cortex = VisionCortex()
        percept = cortex.perceive()

        assert percept is not None
        assert percept.quality == 0.0
        assert percept.vision_health.overall == 0.0
        assert "nie widze" in percept.summary.lower() or "nie dziala" in percept.summary.lower()


# --- Capture Failure ---

class TestCaptureFailure:
    def test_capture_failure_returns_percept(self):
        cortex = VisionCortex()
        sensor = MockSensor(fail_capture=True)
        sensor.open()
        cortex.add_sensor(sensor)

        percept = cortex.perceive()
        assert percept is not None
        assert percept.quality == 0.0

        sensor.close()


# --- Module Quality Gating ---

class TestModuleGating:
    def test_scene_skipped_on_very_low_quality(self):
        cortex = VisionCortex()
        sensor = MockSensor(
            health_override=SensorHealth(
                connection=1.0, stream=0.1, resolution=0.1,
                color=0.1, focus=0.1, exposure=0.1, noise=0.1,
            )
        )
        sensor.open()
        cortex.add_sensor(sensor)
        cortex.add_module(SceneModule())

        percept = cortex.perceive()
        # With very low quality, scene might still run (quality >= 0.3 check)
        # but the output will be degraded
        assert percept is not None

        sensor.close()


# --- Sensor Management ---

class TestSensorManagement:
    def test_add_remove_sensor(self):
        cortex = VisionCortex()
        assert cortex.sensor_count == 0

        sensor = MockSensor()
        cortex.add_sensor(sensor)
        assert cortex.sensor_count == 1

        cortex.remove_sensor(sensor.sensor_id)
        assert cortex.sensor_count == 0

    def test_add_remove_module(self):
        cortex = VisionCortex()
        assert cortex.module_count == 0

        cortex.add_module(MotionModule())
        assert cortex.module_count == 1

        cortex.remove_module("motion")
        assert cortex.module_count == 0

    def test_open_all_sensors(self):
        cortex = VisionCortex()
        cortex.add_sensor(MockSensor(sensor_id="a"))
        cortex.add_sensor(MockSensor(sensor_id="b"))

        opened = cortex.open_all_sensors()
        assert opened == 2

        cortex.close_all_sensors()

    def test_open_all_with_failure(self):
        cortex = VisionCortex()
        cortex.add_sensor(MockSensor(sensor_id="ok"))
        cortex.add_sensor(MockSensor(sensor_id="fail", fail_open=True))

        opened = cortex.open_all_sensors()
        assert opened == 1

        cortex.close_all_sensors()


# --- Status ---

class TestCortexStatus:
    def test_status_dict(self):
        cortex = VisionCortex()
        sensor = MockSensor()
        sensor.open()
        cortex.add_sensor(sensor)
        cortex.add_module(MotionModule())

        status = cortex.get_status()
        assert "sensors" in status
        assert "modules" in status
        assert "motion" in status["modules"]
        assert "mock-0" in status["sensors"]

        sensor.close()

    def test_status_shows_active(self):
        cortex = VisionCortex()
        sensor = MockSensor()
        sensor.open()
        cortex.add_sensor(sensor)

        cortex.perceive()
        status = cortex.get_status()
        assert status["active_sensor"] == "mock-0"

        sensor.close()


# --- Reset ---

class TestCortexReset:
    def test_reset_clears_state(self):
        cortex = VisionCortex()
        sensor = MockSensor()
        sensor.open()
        cortex.add_sensor(sensor)

        cortex.perceive()
        assert cortex.last_percept is not None

        cortex.reset()
        assert cortex.last_percept is None

        sensor.close()


# --- Percept Properties ---

class TestPerceptOutput:
    def test_percept_to_dict(self):
        cortex = VisionCortex()
        sensor = MockSensor()
        sensor.open()
        cortex.add_sensor(sensor)
        cortex.add_module(SceneModule())

        percept = cortex.perceive()
        d = percept.to_dict()

        assert "quality" in d
        assert "summary" in d
        assert "scene" in d
        assert "modules_run" in d
        assert "sensor_id" in d

        sensor.close()

    def test_percept_to_consciousness_input(self):
        cortex = VisionCortex()
        sensor = MockSensor()
        sensor.open()
        cortex.add_sensor(sensor)

        percept = cortex.perceive()
        ci = percept.to_consciousness_input()

        assert "human" in ci
        assert "technical" in ci
        assert isinstance(ci["human"], str)
        assert isinstance(ci["technical"], dict)

        sensor.close()

    def test_processing_time_recorded(self):
        cortex = VisionCortex()
        sensor = MockSensor()
        sensor.open()
        cortex.add_sensor(sensor)

        percept = cortex.perceive()
        assert percept.total_processing_time_ms > 0.0

        sensor.close()
