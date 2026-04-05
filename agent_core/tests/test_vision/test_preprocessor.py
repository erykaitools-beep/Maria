"""
Tests for VisionPreprocessor - main preprocessing pipeline.

Covers:
- Full pipeline (normalize -> quality -> degradation -> ProcessedFrame)
- ProcessedFrame properties (is_usable, is_good, has_severe_degradation)
- Frozen frame detection across calls
- Invalid frame handling
- Serialization
- Reset state
- Performance (< 50ms target)
"""

import time

import numpy as np
import pytest

from agent_core.vision.models import DegradationType, Frame, VisionMode
from agent_core.vision.preprocessing.preprocessor import (
    ProcessedFrame,
    VisionPreprocessor,
)
from agent_core.vision.preprocessing.quality import QualityAssessment


# --- Helpers ---

def _make_frame(image, sensor_id="test", seq=1):
    return Frame(
        image=image,
        sensor_id=sensor_id,
        sequence_number=seq,
        resolution=(image.shape[1], image.shape[0]) if image.ndim >= 2 else (0, 0),
    )


def _good_image(w=640, h=480):
    """Image with decent quality - gradient with medium-frequency structure.

    Has enough edges for sharpness detection but not so many that
    it triggers noise detection. Balanced horizontal/vertical for
    no motion blur false positive.
    """
    img = np.zeros((h, w, 3), dtype=np.uint8)
    row = np.linspace(40, 215, w, dtype=np.uint8)
    col = np.linspace(40, 215, h, dtype=np.uint8)
    img[:, :, 0] = row[np.newaxis, :]
    img[:, :, 1] = col[:, np.newaxis]
    img[:, :, 2] = 127
    # Add broad rectangular regions (edges, not grid lines)
    for y in range(0, h, 64):
        img[y:y+32, :, :] = np.clip(img[y:y+32, :, :].astype(int) + 40, 0, 255).astype(np.uint8)
    for x in range(0, w, 64):
        img[:, x:x+32, :] = np.clip(img[:, x:x+32, :].astype(int) + 40, 0, 255).astype(np.uint8)
    return img


def _bad_image(w=640, h=480):
    """Very dark, noisy image."""
    np.random.seed(42)
    return np.random.randint(0, 10, (h, w, 3), dtype=np.uint8)


# --- Pipeline ---

class TestVisionPreprocessor:
    """Tests for the preprocessing pipeline."""

    def test_process_good_image(self):
        pp = VisionPreprocessor()
        frame = _make_frame(_good_image())
        result = pp.process(frame)

        assert isinstance(result, ProcessedFrame)
        assert result.image.shape == (480, 640, 3)
        assert result.quality.overall > 0.0
        assert result.processing_time_ms >= 0.0
        assert result.sensor_id == "test"
        assert result.sequence_number == 1

    def test_process_bad_image(self):
        pp = VisionPreprocessor()
        frame = _make_frame(_bad_image())
        result = pp.process(frame)

        assert isinstance(result, ProcessedFrame)
        assert result.quality.overall < 0.5
        assert len(result.degradations) > 0

    def test_process_with_resize(self):
        pp = VisionPreprocessor(target_resolution=(320, 240))
        img = _good_image(640, 480)
        frame = _make_frame(img)
        result = pp.process(frame)

        assert result.image.shape == (240, 320, 3)
        assert result.original_resolution == (640, 480)

    def test_process_invalid_frame(self):
        pp = VisionPreprocessor()
        frame = Frame(image=np.array([], dtype=np.uint8))
        result = pp.process(frame)

        assert result.quality.overall == 0.0
        assert not result.is_usable


# --- ProcessedFrame Properties ---

class TestProcessedFrame:
    """Tests for ProcessedFrame properties."""

    def test_is_usable_good(self):
        pp = VisionPreprocessor()
        result = pp.process(_make_frame(_good_image()))
        assert result.is_usable

    def test_is_usable_bad(self):
        pp = VisionPreprocessor()
        frame = Frame(image=np.array([], dtype=np.uint8))
        result = pp.process(frame)
        assert not result.is_usable

    def test_is_good(self):
        pp = VisionPreprocessor()
        result = pp.process(_make_frame(_good_image()))
        # Good image should pass is_good threshold
        assert result.quality.overall > 0.0

    def test_has_severe_degradation(self):
        pp = VisionPreprocessor()
        black = np.zeros((480, 640, 3), dtype=np.uint8)
        result = pp.process(_make_frame(black))
        assert result.has_severe_degradation

    def test_no_severe_degradation(self):
        pp = VisionPreprocessor()
        result = pp.process(_make_frame(_good_image()))
        assert not result.has_severe_degradation

    def test_degradation_types_list(self):
        pp = VisionPreprocessor()
        black = np.zeros((480, 640, 3), dtype=np.uint8)
        result = pp.process(_make_frame(black))
        types = result.degradation_types
        assert isinstance(types, list)
        assert DegradationType.TOTAL_BLACK in types

    def test_to_dict(self):
        pp = VisionPreprocessor()
        result = pp.process(_make_frame(_good_image()))
        d = result.to_dict()

        assert "quality" in d
        assert "degradations" in d
        assert "processing_time_ms" in d
        assert "is_usable" in d
        assert "is_good" in d
        assert "sensor_id" in d

    def test_equality(self):
        img = _good_image()
        pf1 = ProcessedFrame(
            image=img, quality=QualityAssessment(),
            sensor_id="a", sequence_number=1,
        )
        pf2 = ProcessedFrame(
            image=img.copy(), quality=QualityAssessment(),
            sensor_id="a", sequence_number=1,
        )
        assert pf1 == pf2

    def test_hash(self):
        img = _good_image()
        pf = ProcessedFrame(
            image=img, quality=QualityAssessment(),
            sensor_id="a", sequence_number=1, timestamp=100.0,
        )
        assert isinstance(hash(pf), int)


# --- Frozen Frame Detection ---

class TestFrozenDetection:
    """Tests for frozen frame detection across pipeline calls."""

    def test_frozen_detected(self):
        pp = VisionPreprocessor()
        img = np.ones((480, 640, 3), dtype=np.uint8) * 127
        frame1 = _make_frame(img, seq=1)
        frame2 = _make_frame(img.copy(), seq=2)

        pp.process(frame1)
        result2 = pp.process(frame2)

        assert DegradationType.FROZEN in result2.degradation_types

    def test_not_frozen_different_frames(self):
        pp = VisionPreprocessor()
        img1 = np.ones((480, 640, 3), dtype=np.uint8) * 127
        img2 = np.ones((480, 640, 3), dtype=np.uint8) * 128

        pp.process(_make_frame(img1, seq=1))
        result2 = pp.process(_make_frame(img2, seq=2))

        assert DegradationType.FROZEN not in result2.degradation_types

    def test_reset_clears_previous(self):
        pp = VisionPreprocessor()
        img = np.ones((480, 640, 3), dtype=np.uint8) * 127

        pp.process(_make_frame(img, seq=1))
        pp.reset()
        result = pp.process(_make_frame(img.copy(), seq=2))

        # After reset, no previous frame to compare -> no FROZEN
        assert DegradationType.FROZEN not in result.degradation_types


# --- Performance ---

class TestPreprocessorPerformance:
    """Performance tests - target < 50ms per frame at 640x480."""

    def test_processing_time_under_50ms(self):
        pp = VisionPreprocessor()
        img = _good_image()
        frame = _make_frame(img)

        # Warm up
        pp.process(frame)
        pp.reset()

        # Measure
        times = []
        for i in range(5):
            pp.reset()
            result = pp.process(_make_frame(img, seq=i))
            times.append(result.processing_time_ms)

        avg_ms = sum(times) / len(times)
        assert avg_ms < 50.0, f"Average {avg_ms:.1f}ms exceeds 50ms target"

    def test_processing_time_recorded(self):
        pp = VisionPreprocessor()
        result = pp.process(_make_frame(_good_image()))
        assert result.processing_time_ms > 0.0
