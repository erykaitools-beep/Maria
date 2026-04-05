"""
Tests for frame normalizer - resolution, format, corrections.

Covers:
- Resize to target resolution
- Grayscale to BGR conversion
- dtype conversion (float -> uint8)
- White balance correction
- Exposure correction (CLAHE)
- Edge cases (empty, tiny, large)
"""

import pytest
import numpy as np
import cv2

from agent_core.vision.preprocessing.normalizer import normalize_frame


class TestNormalizeFormat:
    """Format normalization tests."""

    def test_grayscale_to_bgr(self):
        gray = np.ones((480, 640), dtype=np.uint8) * 127
        result = normalize_frame(gray)
        assert result.ndim == 3
        assert result.shape[2] == 3

    def test_bgr_stays_bgr(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 127
        result = normalize_frame(img)
        assert result.ndim == 3
        assert result.shape[2] == 3

    def test_float_to_uint8(self):
        img = np.ones((480, 640, 3), dtype=np.float32) * 0.5
        result = normalize_frame(img)
        assert result.dtype == np.uint8
        assert result.max() > 100  # 0.5 * 255 = 127

    def test_float_large_to_uint8(self):
        img = np.ones((480, 640, 3), dtype=np.float32) * 200.0
        result = normalize_frame(img)
        assert result.dtype == np.uint8

    def test_empty_image_passthrough(self):
        empty = np.array([], dtype=np.uint8)
        result = normalize_frame(empty)
        assert result.size == 0


class TestNormalizeResolution:
    """Resolution normalization tests."""

    def test_resize_down(self):
        img = np.ones((1080, 1920, 3), dtype=np.uint8) * 127
        result = normalize_frame(img, target_resolution=(640, 480))
        assert result.shape == (480, 640, 3)

    def test_resize_up(self):
        img = np.ones((240, 320, 3), dtype=np.uint8) * 127
        result = normalize_frame(img, target_resolution=(640, 480))
        assert result.shape == (480, 640, 3)

    def test_no_resize_when_matching(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 127
        result = normalize_frame(img, target_resolution=(640, 480))
        assert result.shape == (480, 640, 3)

    def test_no_resize_when_none(self):
        img = np.ones((720, 1280, 3), dtype=np.uint8) * 127
        result = normalize_frame(img, target_resolution=None)
        assert result.shape == (720, 1280, 3)


class TestWhiteBalance:
    """White balance correction tests."""

    def test_white_balance_reduces_shift(self):
        # Blue-shifted image
        img = np.ones((480, 640, 3), dtype=np.uint8) * 100
        img[:, :, 0] = 200  # Blue much higher

        result = normalize_frame(img, auto_white_balance=True)

        # After WB, channels should be more balanced
        means = [float(np.mean(result[:, :, c])) for c in range(3)]
        deviation = max(means) - min(means)
        original_deviation = 100  # 200 - 100
        assert deviation < original_deviation

    def test_white_balance_no_change_balanced(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 127
        result = normalize_frame(img, auto_white_balance=True)
        # Already balanced, should be nearly identical
        assert np.allclose(result, img, atol=2)

    def test_white_balance_disabled(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 100
        img[:, :, 0] = 200
        result = normalize_frame(img, auto_white_balance=False)
        assert np.array_equal(result, img)


class TestExposureCorrection:
    """Exposure correction (CLAHE) tests."""

    def test_exposure_improves_dark_image(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 30
        # Add some structure
        img[100:200, 100:200, :] = 60
        result = normalize_frame(img, auto_exposure=True)
        # Should brighten
        assert float(np.mean(result)) > float(np.mean(img))

    def test_exposure_disabled(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 30
        result = normalize_frame(img, auto_exposure=False)
        assert np.array_equal(result, img)


class TestCombined:
    """Combined normalization tests."""

    def test_full_pipeline(self):
        """Grayscale float image -> resized BGR uint8 with corrections."""
        img = np.random.rand(720, 1280).astype(np.float32)
        result = normalize_frame(
            img,
            target_resolution=(640, 480),
            auto_white_balance=True,
            auto_exposure=True,
        )
        assert result.shape == (480, 640, 3)
        assert result.dtype == np.uint8
