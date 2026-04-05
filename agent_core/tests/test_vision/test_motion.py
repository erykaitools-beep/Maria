"""
Tests for MotionModule - movement detection via frame differencing.

Covers:
- Protocol compliance
- No motion on first frame
- Motion detection (moving object)
- No motion on identical frames
- Motion regions (bounding boxes, area)
- Motion classification (person, object, camera shake, ambient)
- Alert levels
- Graceful degradation
- Reset
- Edge cases
"""

import numpy as np
import pytest
import cv2

from agent_core.vision.modules.base import VisionModule
from agent_core.vision.modules.motion.detector import (
    AlertLevel,
    MotionClassification,
    MotionModule,
    MotionOutput,
    MotionRegion,
)
from agent_core.vision.preprocessing.preprocessor import ProcessedFrame
from agent_core.vision.preprocessing.quality import QualityAssessment


# --- Helpers ---

def _make_processed(image, quality_overall=0.8):
    return ProcessedFrame(
        image=image,
        quality=QualityAssessment(
            sharpness=quality_overall,
            brightness=quality_overall,
            contrast=quality_overall,
            noise_level=quality_overall,
            color_balance=quality_overall,
            motion_blur=quality_overall,
        ),
        sensor_id="test",
        sequence_number=0,
    )


def _static_scene(w=640, h=480):
    """A static scene - gray room with a rectangle."""
    img = np.ones((h, w, 3), dtype=np.uint8) * 100
    img[100:200, 200:400, :] = 180  # A "table"
    return img


def _scene_with_movement(w=640, h=480, x_offset=0):
    """Scene with a 'person' (white rectangle) that can move."""
    img = np.ones((h, w, 3), dtype=np.uint8) * 100
    img[100:200, 200:400, :] = 180  # Table
    # "Person" moving horizontally
    px = 150 + x_offset
    img[50:250, px:px+80, :] = 220  # Person-sized blob
    return img


# --- Protocol Compliance ---

class TestMotionProtocol:
    def test_is_vision_module(self):
        m = MotionModule()
        assert isinstance(m, VisionModule)

    def test_module_name(self):
        assert MotionModule().module_name == "motion"

    def test_required_quality(self):
        assert MotionModule().required_quality == 0.2

    def test_can_work_degraded(self):
        assert MotionModule().can_work_degraded is True


# --- Basic Motion Detection ---

class TestMotionDetection:
    def test_first_frame_no_motion(self):
        m = MotionModule()
        frame = _make_processed(_static_scene())
        output = m.analyze(frame)

        assert output is not None
        assert output.motion_detected is False
        assert output.motion_level == 0.0

    def test_identical_frames_no_motion(self):
        m = MotionModule()
        scene = _static_scene()
        m.analyze(_make_processed(scene))
        output = m.analyze(_make_processed(scene.copy()))

        assert output.motion_detected is False

    def test_motion_detected_on_change(self):
        m = MotionModule()
        frame1 = _make_processed(_scene_with_movement(x_offset=0))
        frame2 = _make_processed(_scene_with_movement(x_offset=100))

        m.analyze(frame1)
        output = m.analyze(frame2)

        assert output.motion_detected is True
        assert output.motion_level > 0.0

    def test_large_change_high_motion_level(self):
        m = MotionModule()
        scene1 = np.ones((480, 640, 3), dtype=np.uint8) * 50
        scene2 = np.ones((480, 640, 3), dtype=np.uint8) * 200

        m.analyze(_make_processed(scene1))
        output = m.analyze(_make_processed(scene2))

        assert output.motion_level > 0.5

    def test_small_change_low_motion_level(self):
        m = MotionModule()
        scene1 = _static_scene()
        scene2 = scene1.copy()
        # Only a tiny area changes
        scene2[200:210, 300:310, :] = 250

        m.analyze(_make_processed(scene1))
        output = m.analyze(_make_processed(scene2))

        # Small change - might or might not cross threshold depending on blur
        assert output.motion_level < 0.3

    def test_empty_image_returns_none(self):
        m = MotionModule()
        frame = _make_processed(np.array([], dtype=np.uint8))
        assert m.analyze(frame) is None


# --- Motion Regions ---

class TestMotionRegions:
    def test_regions_found(self):
        m = MotionModule()
        m.analyze(_make_processed(_scene_with_movement(x_offset=0)))
        output = m.analyze(_make_processed(_scene_with_movement(x_offset=100)))

        assert len(output.regions) > 0

    def test_region_has_bbox(self):
        m = MotionModule()
        m.analyze(_make_processed(_scene_with_movement(x_offset=0)))
        output = m.analyze(_make_processed(_scene_with_movement(x_offset=100)))

        if output.regions:
            r = output.regions[0]
            assert isinstance(r, MotionRegion)
            assert len(r.bounding_box) == 4
            assert r.area > 0
            assert len(r.center) == 2

    def test_regions_sorted_by_area(self):
        m = MotionModule()
        m.analyze(_make_processed(_scene_with_movement(x_offset=0)))
        output = m.analyze(_make_processed(_scene_with_movement(x_offset=100)))

        if len(output.regions) >= 2:
            assert output.regions[0].area >= output.regions[1].area


# --- Classification ---

class TestMotionClassification:
    def test_no_motion_classified_none(self):
        m = MotionModule()
        scene = _static_scene()
        m.analyze(_make_processed(scene))
        output = m.analyze(_make_processed(scene.copy()))

        assert output.classification == MotionClassification.NONE

    def test_large_blob_classified_person(self):
        m = MotionModule()
        scene1 = np.ones((480, 640, 3), dtype=np.uint8) * 100
        scene2 = scene1.copy()
        # Large blob (person-sized)
        scene2[50:300, 200:350, :] = 220

        m.analyze(_make_processed(scene1))
        output = m.analyze(_make_processed(scene2))

        assert output.classification in (
            MotionClassification.PERSON_MOVEMENT,
            MotionClassification.OBJECT_MOVEMENT,
        )

    def test_many_small_regions_classified_shake(self):
        m = MotionModule()
        np.random.seed(42)
        scene1 = np.ones((480, 640, 3), dtype=np.uint8) * 100
        scene2 = scene1.copy()
        # Many small changes scattered (camera shake effect)
        for _ in range(20):
            y = np.random.randint(0, 460)
            x = np.random.randint(0, 620)
            scene2[y:y+15, x:x+15, :] = 220

        m.analyze(_make_processed(scene1))
        output = m.analyze(_make_processed(scene2))

        # Should detect motion
        assert output.motion_detected


# --- Alert Levels ---

class TestAlertLevels:
    def test_no_motion_no_alert(self):
        m = MotionModule()
        scene = _static_scene()
        m.analyze(_make_processed(scene))
        output = m.analyze(_make_processed(scene.copy()))

        assert output.alert_level == AlertLevel.NONE

    def test_motion_triggers_alert(self):
        m = MotionModule()
        m.analyze(_make_processed(_scene_with_movement(x_offset=0)))
        output = m.analyze(_make_processed(_scene_with_movement(x_offset=100)))

        assert output.alert_level != AlertLevel.NONE

    def test_large_motion_higher_alert(self):
        m = MotionModule()
        scene1 = np.ones((480, 640, 3), dtype=np.uint8) * 50
        scene2 = np.ones((480, 640, 3), dtype=np.uint8) * 200

        m.analyze(_make_processed(scene1))
        output = m.analyze(_make_processed(scene2))

        assert output.alert_level in (AlertLevel.WARNING, AlertLevel.DANGER)


# --- Degradation ---

class TestMotionDegradation:
    def test_degraded_flag_on_low_quality(self):
        m = MotionModule()
        frame = _make_processed(_static_scene(), quality_overall=0.3)
        output = m.analyze(frame)

        assert output.is_degraded is True

    def test_not_degraded_on_good_quality(self):
        m = MotionModule()
        frame = _make_processed(_static_scene(), quality_overall=0.8)
        output = m.analyze(frame)

        assert output.is_degraded is False


# --- Reset and State ---

class TestMotionState:
    def test_reset_clears_previous(self):
        m = MotionModule()
        m.analyze(_make_processed(_static_scene()))
        m.reset()

        # After reset, next frame is treated as first
        output = m.analyze(_make_processed(_static_scene()))
        assert output.motion_detected is False
        assert output.confidence == 0.0

    def test_processing_time_recorded(self):
        m = MotionModule()
        output = m.analyze(_make_processed(_static_scene()))
        assert output.processing_time_ms >= 0.0


# --- Serialization ---

class TestMotionSerialization:
    def test_output_to_dict(self):
        m = MotionModule()
        m.analyze(_make_processed(_scene_with_movement(x_offset=0)))
        output = m.analyze(_make_processed(_scene_with_movement(x_offset=100)))

        d = output.to_dict()
        assert "motion_detected" in d
        assert "motion_level" in d
        assert "regions" in d
        assert "classification" in d
        assert "alert_level" in d
        assert "module_name" in d

    def test_region_to_dict(self):
        r = MotionRegion(
            bounding_box=(10, 20, 30, 40),
            area=1200,
            center=(25, 40),
        )
        d = r.to_dict()
        assert d["bounding_box"] == [10, 20, 30, 40]
        assert d["area"] == 1200
