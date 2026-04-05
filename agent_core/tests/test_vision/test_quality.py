"""
Tests for QualityAssessment - image quality metrics.

Covers:
- Individual metrics (sharpness, brightness, contrast, noise, color, motion blur)
- Overall score computation and weighting
- Edge cases (empty image, grayscale, tiny image)
- Serialization
- Known image patterns (all black, all white, gradient, noise)
"""

import pytest
import numpy as np
import cv2

from agent_core.vision.preprocessing.quality import (
    QualityAssessment,
    assess_quality,
)


# --- Helper image generators ---

def _black_image(w=640, h=480):
    return np.zeros((h, w, 3), dtype=np.uint8)

def _white_image(w=640, h=480):
    return np.ones((h, w, 3), dtype=np.uint8) * 255

def _mid_gray_image(w=640, h=480):
    return np.ones((h, w, 3), dtype=np.uint8) * 127

def _noise_image(w=640, h=480):
    return np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)

def _gradient_image(w=640, h=480):
    """Horizontal gradient - good contrast, sharp edges."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    row = np.linspace(0, 255, w, dtype=np.uint8)
    img[:, :, 0] = row
    img[:, :, 1] = row
    img[:, :, 2] = row
    return img

def _sharp_edges_image(w=640, h=480):
    """Checkerboard pattern - very sharp."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        for x in range(w):
            if (x // 16 + y // 16) % 2 == 0:
                img[y, x] = 255
    return img

def _blurry_image(w=640, h=480):
    """Heavily blurred gradient."""
    img = _gradient_image(w, h)
    return cv2.GaussianBlur(img, (31, 31), 10)

def _color_shifted_image(w=640, h=480):
    """Image with strong blue shift."""
    img = np.ones((h, w, 3), dtype=np.uint8) * 100
    img[:, :, 0] = 200  # Blue much higher
    return img


# --- QualityAssessment Dataclass ---

class TestQualityAssessment:
    """Tests for QualityAssessment properties."""

    def test_default_perfect(self):
        q = QualityAssessment()
        assert q.overall == 1.0

    def test_all_zero(self):
        q = QualityAssessment(
            sharpness=0.0, brightness=0.0, contrast=0.0,
            noise_level=0.0, color_balance=0.0, motion_blur=0.0,
        )
        assert q.overall == 0.0

    def test_overall_clamped(self):
        q = QualityAssessment()
        assert 0.0 <= q.overall <= 1.0

    def test_to_dict_keys(self):
        q = QualityAssessment()
        d = q.to_dict()
        assert "overall" in d
        assert "sharpness" in d
        assert "brightness" in d
        assert "contrast" in d
        assert "noise_level" in d
        assert "color_balance" in d
        assert "motion_blur" in d

    def test_to_dict_values(self):
        q = QualityAssessment(sharpness=0.5, brightness=0.8)
        d = q.to_dict()
        assert d["sharpness"] == 0.5
        assert d["brightness"] == 0.8


# --- assess_quality() ---

class TestAssessQuality:
    """Tests for the assess_quality function."""

    def test_empty_image(self):
        q = assess_quality(np.array([], dtype=np.uint8))
        assert q.overall == 0.0
        assert q.sharpness == 0.0

    def test_none_image(self):
        q = assess_quality(None)
        assert q.overall == 0.0

    def test_black_image_low_brightness(self):
        q = assess_quality(_black_image())
        assert q.brightness < 0.2

    def test_white_image_low_brightness(self):
        """White image is overexposed - also low brightness score."""
        q = assess_quality(_white_image())
        assert q.brightness < 0.2

    def test_mid_gray_good_brightness(self):
        q = assess_quality(_mid_gray_image())
        assert q.brightness > 0.7

    def test_gradient_good_contrast(self):
        q = assess_quality(_gradient_image())
        assert q.contrast > 0.5

    def test_flat_image_low_contrast(self):
        q = assess_quality(_mid_gray_image())
        assert q.contrast < 0.2

    def test_sharp_edges_high_sharpness(self):
        q = assess_quality(_sharp_edges_image())
        assert q.sharpness > 0.5

    def test_blurry_image_low_sharpness(self):
        q = assess_quality(_blurry_image())
        assert q.sharpness < 0.3

    def test_noise_image_low_noise_score(self):
        np.random.seed(42)
        q = assess_quality(_noise_image())
        assert q.noise_level < 0.5

    def test_clean_image_high_noise_score(self):
        q = assess_quality(_mid_gray_image())
        assert q.noise_level > 0.8

    def test_color_shifted_low_balance(self):
        q = assess_quality(_color_shifted_image())
        assert q.color_balance < 0.5

    def test_balanced_color_high_score(self):
        q = assess_quality(_mid_gray_image())
        assert q.color_balance > 0.8

    def test_grayscale_input(self):
        gray = np.ones((480, 640), dtype=np.uint8) * 127
        q = assess_quality(gray)
        assert q.brightness > 0.5
        # Grayscale is balanced by definition
        assert q.color_balance == 1.0

    def test_small_image(self):
        img = np.ones((10, 10, 3), dtype=np.uint8) * 127
        q = assess_quality(img)
        assert 0.0 <= q.overall <= 1.0

    def test_overall_in_range(self):
        """Overall score should always be 0.0-1.0."""
        for img_fn in [_black_image, _white_image, _gradient_image, _noise_image]:
            q = assess_quality(img_fn())
            assert 0.0 <= q.overall <= 1.0, f"Overall out of range for {img_fn.__name__}"


# --- Motion Blur Detection ---

class TestMotionBlur:
    """Tests for motion blur detection."""

    def test_horizontal_blur_detected(self):
        """Horizontal motion blur should be detected."""
        # Use a vertical-edge image so horizontal blur creates real asymmetry
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        for x in range(0, 640, 32):
            img[:, x:x+16, :] = 255  # Vertical stripes
        # Apply strong horizontal blur
        kernel = np.zeros((1, 31), dtype=np.float32)
        kernel[0, :] = 1.0 / 31.0
        blurred = cv2.filter2D(img, -1, kernel)
        q = assess_quality(blurred)
        assert q.motion_blur < 0.8

    def test_no_motion_blur_on_symmetric(self):
        """Symmetric image should not trigger motion blur."""
        q = assess_quality(_noise_image())
        # Random noise has balanced gradients
        assert q.motion_blur > 0.5
