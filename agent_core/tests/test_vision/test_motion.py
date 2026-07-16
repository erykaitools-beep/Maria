"""
Tests for MotionModule - movement detection via MOG2 background subtraction.

Covers:
- Protocol compliance
- No motion on first frame / warmup
- Motion detection (object appears against learned background)
- No motion on identical frames
- Illumination robustness: sudden global light change is suppressed
- Motion regions (bounding boxes, area)
- Motion classification (person, object, camera shake, ambient)
- Alert levels
- Graceful degradation
- Reset
- Edge cases

MOG2 learns a background model, so tests prime it with a few background frames
before introducing the object under test (mirrors a real "someone walks into a
static scene" event).
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


def _flat(value, w=640, h=480):
    """A uniform frame at a given brightness (simulates global lighting)."""
    return np.ones((h, w, 3), dtype=np.uint8) * value


def _prime(module, scene, frames=6):
    """Feed background frames so MOG2 establishes the scene as background."""
    for _ in range(frames):
        module.analyze(_make_processed(scene))


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
        _prime(m, scene)
        output = m.analyze(_make_processed(scene.copy()))

        assert output.motion_detected is False

    def test_motion_detected_on_change(self):
        m = MotionModule()
        # Establish the table-only scene as background, then a person appears.
        _prime(m, _static_scene())
        output = m.analyze(_make_processed(_scene_with_movement(x_offset=100)))

        assert output.motion_detected is True
        assert output.motion_level > 0.0

    def test_large_localized_blob_high_motion(self):
        """A big LOCALIZED object (not a light change) reads as strong motion."""
        m = MotionModule()
        bg = _flat(100)
        _prime(m, bg)
        moved = bg.copy()
        moved[50:300, 150:400, :] = 220  # ~20% of frame, localized
        output = m.analyze(_make_processed(moved))

        assert output.motion_detected is True
        assert output.motion_level > 0.3

    def test_small_change_low_motion_level(self):
        m = MotionModule()
        scene = _static_scene()
        _prime(m, scene)
        scene2 = scene.copy()
        # Only a tiny area changes
        scene2[200:210, 300:310, :] = 250
        output = m.analyze(_make_processed(scene2))

        assert output.motion_level < 0.3

    def test_empty_image_returns_none(self):
        m = MotionModule()
        frame = _make_processed(np.array([], dtype=np.uint8))
        assert m.analyze(frame) is None


# --- Illumination Robustness (the reason for MOG2) ---

class TestIlluminationRobustness:
    def test_sudden_global_brightening_suppressed(self):
        """Sun glare / cloud clearing flips the whole frame -> NOT motion."""
        m = MotionModule()
        _prime(m, _flat(60))
        output = m.analyze(_make_processed(_flat(200)))

        assert output.motion_detected is False
        assert output.motion_level == 0.0
        assert output.alert_level == AlertLevel.NONE

    def test_sudden_global_darkening_suppressed(self):
        """Cloud shadow drops the whole frame -> NOT motion."""
        m = MotionModule()
        _prime(m, _flat(200))
        output = m.analyze(_make_processed(_flat(60)))

        assert output.motion_detected is False
        assert output.motion_level == 0.0

    def test_gradual_light_change_absorbed(self):
        """A slow fade (cloud rolling in over seconds) is learned, not flagged."""
        m = MotionModule()
        for value in (100, 100, 100, 95, 88, 80, 72, 65, 60):
            output = m.analyze(_make_processed(_flat(value)))

        assert output.motion_detected is False


# --- Motion Regions ---

class TestMotionRegions:
    def test_regions_found(self):
        m = MotionModule()
        _prime(m, _static_scene())
        output = m.analyze(_make_processed(_scene_with_movement(x_offset=100)))

        assert len(output.regions) > 0

    def test_region_has_bbox(self):
        m = MotionModule()
        _prime(m, _static_scene())
        output = m.analyze(_make_processed(_scene_with_movement(x_offset=100)))

        if output.regions:
            r = output.regions[0]
            assert isinstance(r, MotionRegion)
            assert len(r.bounding_box) == 4
            assert r.area > 0
            assert len(r.center) == 2

    def test_regions_sorted_by_area(self):
        m = MotionModule()
        bg = _flat(100)
        _prime(m, bg)
        scene2 = bg.copy()
        scene2[50:300, 100:250, :] = 220   # big blob
        scene2[400:440, 500:540, :] = 220  # small blob
        output = m.analyze(_make_processed(scene2))

        if len(output.regions) >= 2:
            assert output.regions[0].area >= output.regions[1].area


# --- Classification ---

class TestMotionClassification:
    def test_no_motion_classified_none(self):
        m = MotionModule()
        scene = _static_scene()
        _prime(m, scene)
        output = m.analyze(_make_processed(scene.copy()))

        assert output.classification == MotionClassification.NONE

    def test_large_blob_classified_person(self):
        m = MotionModule()
        bg = _flat(100)
        _prime(m, bg)
        scene2 = bg.copy()
        # Large blob (person-sized), localized
        scene2[50:300, 200:350, :] = 220
        output = m.analyze(_make_processed(scene2))

        assert output.classification in (
            MotionClassification.PERSON_MOVEMENT,
            MotionClassification.OBJECT_MOVEMENT,
        )

    def test_many_small_regions_still_detected(self):
        m = MotionModule()
        np.random.seed(42)
        bg = _flat(100)
        _prime(m, bg)
        scene2 = bg.copy()
        # Many small changes scattered (camera shake / foliage effect)
        for _ in range(20):
            y = np.random.randint(0, 460)
            x = np.random.randint(0, 620)
            scene2[y:y+15, x:x+15, :] = 220
        output = m.analyze(_make_processed(scene2))

        # Should detect motion (classification may be shake/ambient)
        assert output.motion_detected


# --- Alert Levels ---

class TestAlertLevels:
    def test_no_motion_no_alert(self):
        m = MotionModule()
        scene = _static_scene()
        _prime(m, scene)
        output = m.analyze(_make_processed(scene.copy()))

        assert output.alert_level == AlertLevel.NONE

    def test_motion_triggers_alert(self):
        m = MotionModule()
        _prime(m, _static_scene())
        output = m.analyze(_make_processed(_scene_with_movement(x_offset=100)))

        assert output.alert_level != AlertLevel.NONE

    def test_large_localized_motion_higher_alert(self):
        m = MotionModule()
        bg = _flat(100)
        _prime(m, bg)
        scene2 = bg.copy()
        scene2[50:400, 150:500, :] = 220  # ~40% of frame, localized
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
    def test_reset_clears_background(self):
        m = MotionModule()
        _prime(m, _static_scene())
        m.reset()

        # After reset, next frame is treated as first (warmup)
        output = m.analyze(_make_processed(_static_scene()))
        assert output.motion_detected is False
        assert output.confidence == 0.0

    def test_processing_time_recorded(self):
        m = MotionModule()
        output = m.analyze(_make_processed(_static_scene()))
        assert output.processing_time_ms >= 0.0

    def test_framediff_fallback_finds_regions_with_cv2(self):
        """Regression (adversarial review 2026-06-21): when MOG2 fails to build
        but cv2 is present, the frame-diff fallback must still find contours --
        otherwise a real person reads as AMBIENT and the adapter filters it out."""
        m = MotionModule()
        m._bg_subtractor = None  # force the fallback path (MOG2 absent, cv2 present)
        bg = _flat(100)
        m.analyze(_make_processed(bg))            # seed previous frame
        moved = bg.copy()
        moved[50:300, 200:350, :] = 220           # localized person-sized blob
        out = m.analyze(_make_processed(moved))

        assert out.motion_detected
        assert len(out.regions) > 0
        assert out.classification in (
            MotionClassification.PERSON_MOVEMENT,
            MotionClassification.OBJECT_MOVEMENT,
        )


# --- Serialization ---

class TestMotionSerialization:
    def test_output_to_dict(self):
        m = MotionModule()
        _prime(m, _static_scene())
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
