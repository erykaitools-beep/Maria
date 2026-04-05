"""
Tests for SceneModule - scene description and analysis.

Covers:
- Protocol compliance
- Statistics-based analysis (no LLM)
- LLaVA backend integration (mocked)
- Lighting detection (dark, dim, bright)
- Dominant color detection
- Scene complexity estimation
- Fallback descriptions (Polish)
- Degraded mode
- Edge cases
"""

import numpy as np
import pytest

from agent_core.vision.modules.base import VisionModule
from agent_core.vision.modules.scene.analyzer import (
    SceneModule,
    SceneOutput,
    _detect_dominant_colors,
    _detect_lighting,
    _estimate_complexity,
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


def _bright_room(w=640, h=480):
    """Bright room with objects."""
    img = np.ones((h, w, 3), dtype=np.uint8) * 170
    img[100:300, 200:500, :] = [200, 180, 150]  # Table
    img[50:150, 400:500, :] = [100, 100, 200]    # Red object
    return img


def _dark_room(w=640, h=480):
    return np.ones((h, w, 3), dtype=np.uint8) * 20


def _blue_room(w=640, h=480):
    img = np.ones((h, w, 3), dtype=np.uint8)
    img[:, :, 0] = 200  # Blue channel (BGR)
    img[:, :, 1] = 50
    img[:, :, 2] = 50
    return img


# --- Protocol ---

class TestSceneProtocol:
    def test_is_vision_module(self):
        m = SceneModule()
        assert isinstance(m, VisionModule)

    def test_module_name(self):
        assert SceneModule().module_name == "scene"

    def test_required_quality(self):
        assert SceneModule().required_quality == 0.3

    def test_can_work_degraded(self):
        assert SceneModule().can_work_degraded is True


# --- Statistics-based Analysis ---

class TestSceneStatistics:
    def test_bright_room_detected(self):
        m = SceneModule()
        output = m.analyze(_make_processed(_bright_room()))

        assert output is not None
        assert output.lighting == "bright"
        assert output.backend_used == "statistics"

    def test_dark_room_detected(self):
        m = SceneModule()
        output = m.analyze(_make_processed(_dark_room()))

        assert output.lighting == "dark"

    def test_description_not_empty(self):
        m = SceneModule()
        output = m.analyze(_make_processed(_bright_room()))
        assert len(output.description) > 0

    def test_description_in_polish(self):
        m = SceneModule(use_polish=True)
        output = m.analyze(_make_processed(_bright_room()))
        # Polish description should contain Polish words
        has_polish = any(w in output.description.lower() for w in [
            "jasno", "ciemno", "widze", "jest", "scena",
        ])
        assert has_polish

    def test_dominant_colors(self):
        m = SceneModule()
        output = m.analyze(_make_processed(_blue_room()))
        assert len(output.dominant_colors) > 0

    def test_complexity_score(self):
        m = SceneModule()
        output = m.analyze(_make_processed(_bright_room()))
        assert 0.0 <= output.complexity <= 1.0

    def test_empty_image_returns_none(self):
        m = SceneModule()
        frame = _make_processed(np.array([], dtype=np.uint8))
        assert m.analyze(frame) is None


# --- LLaVA Backend ---

class TestSceneLLaVA:
    def test_llava_called(self):
        calls = []
        def mock_llava(prompt, b64):
            calls.append((prompt, b64))
            return "Widze jasny pokoj z biurkiem."

        m = SceneModule(llava_fn=mock_llava)
        output = m.analyze(_make_processed(_bright_room()))

        assert len(calls) == 1
        assert output.description == "Widze jasny pokoj z biurkiem."
        assert output.backend_used == "llava"
        assert output.confidence > 0.5

    def test_llava_failure_falls_back(self):
        def failing_llava(prompt, b64):
            raise RuntimeError("LLM unavailable")

        m = SceneModule(llava_fn=failing_llava)
        output = m.analyze(_make_processed(_bright_room()))

        assert output.backend_used == "statistics"
        assert len(output.description) > 0

    def test_llava_returns_none_falls_back(self):
        def null_llava(prompt, b64):
            return None

        m = SceneModule(llava_fn=null_llava)
        output = m.analyze(_make_processed(_bright_room()))

        assert output.backend_used == "statistics"

    def test_set_llava_fn(self):
        m = SceneModule()
        assert m._llava_fn is None

        def mock_llava(prompt, b64):
            return "Test"

        m.set_llava_fn(mock_llava)
        output = m.analyze(_make_processed(_bright_room()))
        assert output.backend_used == "llava"

    def test_llava_skipped_on_low_quality(self):
        calls = []
        def mock_llava(prompt, b64):
            calls.append(1)
            return "Description"

        m = SceneModule(llava_fn=mock_llava)
        output = m.analyze(_make_processed(_bright_room(), quality_overall=0.2))

        # Quality too low for LLaVA
        assert len(calls) == 0
        assert output.backend_used == "statistics"


# --- Lighting Detection ---

class TestLightingDetection:
    def test_dark(self):
        assert _detect_lighting(np.ones((100, 100, 3), dtype=np.uint8) * 10) == "dark"

    def test_dim(self):
        assert _detect_lighting(np.ones((100, 100, 3), dtype=np.uint8) * 70) == "dim"

    def test_bright(self):
        assert _detect_lighting(np.ones((100, 100, 3), dtype=np.uint8) * 150) == "bright"

    def test_very_bright(self):
        assert _detect_lighting(np.ones((100, 100, 3), dtype=np.uint8) * 220) == "very_bright"

    def test_grayscale_input(self):
        gray = np.ones((100, 100), dtype=np.uint8) * 150
        assert _detect_lighting(gray) == "bright"


# --- Color Detection ---

class TestColorDetection:
    def test_blue_image(self):
        colors = _detect_dominant_colors(_blue_room(100, 100))
        assert "blue" in colors or "blue-cyan" in colors or "cyan" in colors

    def test_dark_image_returns_black(self):
        img = np.ones((100, 100, 3), dtype=np.uint8) * 5
        colors = _detect_dominant_colors(img)
        assert "black" in colors

    def test_grayscale_returns_gray(self):
        gray = np.ones((100, 100), dtype=np.uint8) * 127
        colors = _detect_dominant_colors(gray)
        assert "gray" in colors

    def test_returns_list(self):
        colors = _detect_dominant_colors(_bright_room(100, 100))
        assert isinstance(colors, list)
        assert len(colors) > 0


# --- Complexity ---

class TestComplexity:
    def test_simple_scene_low_complexity(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 127
        c = _estimate_complexity(img)
        assert c < 0.2

    def test_complex_scene_higher(self):
        np.random.seed(42)
        img = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
        c = _estimate_complexity(img)
        assert c > 0.3

    def test_range_0_1(self):
        img = _bright_room()
        c = _estimate_complexity(img)
        assert 0.0 <= c <= 1.0


# --- Serialization ---

class TestSceneSerialization:
    def test_output_to_dict(self):
        m = SceneModule()
        output = m.analyze(_make_processed(_bright_room()))

        d = output.to_dict()
        assert "description" in d
        assert "lighting" in d
        assert "dominant_colors" in d
        assert "complexity" in d
        assert "backend_used" in d
        assert "module_name" in d


# --- Degradation ---

class TestSceneDegradation:
    def test_degraded_on_low_quality(self):
        m = SceneModule()
        output = m.analyze(_make_processed(_bright_room(), quality_overall=0.3))
        assert output.is_degraded is True

    def test_not_degraded_on_good_quality(self):
        m = SceneModule()
        output = m.analyze(_make_processed(_bright_room(), quality_overall=0.8))
        assert output.is_degraded is False
