"""
Tests for DegradationDetector - image problem detection.

Covers:
- Total black / total white detection
- Low contrast detection
- Heavy noise detection
- Focus blur and motion blur
- Color shift
- Partial frame (incomplete capture)
- Low resolution
- Frozen frame (identical to previous)
- Occlusion (center blocked)
- Severity ordering
- Recovery action suggestions
- Edge cases
"""

import pytest
import numpy as np
import cv2

from agent_core.vision.models import DegradationType
from agent_core.vision.preprocessing.degradation import (
    Degradation,
    DegradationSeverity,
    RecoveryAction,
    detect_degradations,
)
from agent_core.vision.preprocessing.quality import (
    QualityAssessment,
    assess_quality,
)


# --- Helpers ---

def _detect(image, previous=None):
    """Shortcut: assess quality then detect degradations."""
    q = assess_quality(image)
    return detect_degradations(image, q, previous_image=previous)

def _has_type(degradations, dtype):
    return any(d.type == dtype for d in degradations)


# --- Total Black ---

class TestTotalBlack:
    def test_black_image_detected(self):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        degs = _detect(img)
        assert _has_type(degs, DegradationType.TOTAL_BLACK)

    def test_nearly_black(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 3
        degs = _detect(img)
        assert _has_type(degs, DegradationType.TOTAL_BLACK)

    def test_dark_but_not_black(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 30
        degs = _detect(img)
        assert not _has_type(degs, DegradationType.TOTAL_BLACK)

    def test_black_is_severe(self):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        degs = _detect(img)
        black = [d for d in degs if d.type == DegradationType.TOTAL_BLACK]
        assert black[0].severity == DegradationSeverity.SEVERE

    def test_black_suggests_increase_exposure(self):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        degs = _detect(img)
        black = [d for d in degs if d.type == DegradationType.TOTAL_BLACK]
        assert black[0].recovery == RecoveryAction.INCREASE_EXPOSURE


# --- Total White ---

class TestTotalWhite:
    def test_white_image_detected(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 255
        degs = _detect(img)
        assert _has_type(degs, DegradationType.TOTAL_WHITE)

    def test_nearly_white(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 252
        degs = _detect(img)
        assert _has_type(degs, DegradationType.TOTAL_WHITE)

    def test_bright_but_not_white(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 200
        degs = _detect(img)
        assert not _has_type(degs, DegradationType.TOTAL_WHITE)

    def test_white_suggests_decrease_exposure(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 255
        degs = _detect(img)
        white = [d for d in degs if d.type == DegradationType.TOTAL_WHITE]
        assert white[0].recovery == RecoveryAction.DECREASE_EXPOSURE


# --- Low Contrast ---

class TestLowContrast:
    def test_flat_image_detected(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 127
        degs = _detect(img)
        assert _has_type(degs, DegradationType.LOW_CONTRAST)

    def test_gradient_no_low_contrast(self):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        row = np.linspace(0, 255, 640, dtype=np.uint8)
        img[:, :, :] = row[np.newaxis, :, np.newaxis]
        degs = _detect(img)
        assert not _has_type(degs, DegradationType.LOW_CONTRAST)


# --- Heavy Noise ---

class TestHeavyNoise:
    def test_noise_image_detected(self):
        np.random.seed(42)
        img = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
        degs = _detect(img)
        assert _has_type(degs, DegradationType.HEAVY_NOISE)

    def test_clean_image_no_noise(self):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        row = np.linspace(0, 255, 640, dtype=np.uint8)
        img[:, :, :] = row[np.newaxis, :, np.newaxis]
        degs = _detect(img)
        assert not _has_type(degs, DegradationType.HEAVY_NOISE)


# --- Focus Blur ---

class TestFocusBlur:
    def test_blurry_image_detected(self):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        row = np.linspace(0, 255, 640, dtype=np.uint8)
        img[:, :, :] = row[np.newaxis, :, np.newaxis]
        blurred = cv2.GaussianBlur(img, (31, 31), 10)
        degs = _detect(blurred)
        assert _has_type(degs, DegradationType.FOCUS_BLUR)

    def test_sharp_image_no_blur(self):
        # Checkerboard pattern
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        for y in range(480):
            for x in range(0, 640, 32):
                if (x // 32 + y // 32) % 2 == 0:
                    img[y, x:min(x+32, 640)] = 255
        degs = _detect(img)
        assert not _has_type(degs, DegradationType.FOCUS_BLUR)


# --- Color Shift ---

class TestColorShift:
    def test_blue_shifted_detected(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 100
        img[:, :, 0] = 200  # Blue much higher
        degs = _detect(img)
        assert _has_type(degs, DegradationType.COLOR_SHIFT)

    def test_balanced_no_shift(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 127
        degs = _detect(img)
        assert not _has_type(degs, DegradationType.COLOR_SHIFT)


# --- Partial Frame ---

class TestPartialFrame:
    def test_half_black_detected(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 127
        img[:240, :, :] = 0  # Top half is black
        degs = _detect(img)
        assert _has_type(degs, DegradationType.PARTIAL_FRAME)

    def test_full_image_no_partial(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 127
        degs = _detect(img)
        assert not _has_type(degs, DegradationType.PARTIAL_FRAME)


# --- Low Resolution ---

class TestLowResolution:
    def test_tiny_image_detected(self):
        img = np.ones((60, 80, 3), dtype=np.uint8) * 127
        degs = _detect(img)
        assert _has_type(degs, DegradationType.LOW_RESOLUTION)

    def test_normal_res_no_flag(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 127
        degs = _detect(img)
        assert not _has_type(degs, DegradationType.LOW_RESOLUTION)


# --- Frozen Frame ---

class TestFrozenFrame:
    def test_identical_frames_detected(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 127
        degs = _detect(img, previous=img.copy())
        assert _has_type(degs, DegradationType.FROZEN)

    def test_different_frames_no_frozen(self):
        img1 = np.ones((480, 640, 3), dtype=np.uint8) * 127
        img2 = np.ones((480, 640, 3), dtype=np.uint8) * 128
        degs = _detect(img2, previous=img1)
        assert not _has_type(degs, DegradationType.FROZEN)

    def test_no_previous_no_frozen(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 127
        degs = _detect(img, previous=None)
        assert not _has_type(degs, DegradationType.FROZEN)

    def test_frozen_is_severe(self):
        img = np.ones((480, 640, 3), dtype=np.uint8) * 127
        degs = _detect(img, previous=img.copy())
        frozen = [d for d in degs if d.type == DegradationType.FROZEN]
        assert frozen[0].severity == DegradationSeverity.SEVERE


# --- Occlusion ---

class TestOcclusion:
    def test_center_blocked_detected(self):
        """Uniform center but varied edges suggests occlusion."""
        np.random.seed(42)
        img = np.random.randint(50, 200, (480, 640, 3), dtype=np.uint8)
        # Make center completely uniform
        img[120:360, 160:480, :] = 100
        degs = _detect(img)
        assert _has_type(degs, DegradationType.OCCLUSION)

    def test_normal_image_no_occlusion(self):
        np.random.seed(42)
        img = np.random.randint(50, 200, (480, 640, 3), dtype=np.uint8)
        degs = _detect(img)
        assert not _has_type(degs, DegradationType.OCCLUSION)


# --- Sorting and Serialization ---

class TestDegradationMeta:
    def test_severity_ordering(self):
        """Degradations should be sorted severe first."""
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        degs = _detect(img)
        if len(degs) >= 2:
            severity_order = {
                DegradationSeverity.SEVERE: 0,
                DegradationSeverity.MODERATE: 1,
                DegradationSeverity.MILD: 2,
            }
            for i in range(len(degs) - 1):
                assert severity_order[degs[i].severity] <= severity_order[degs[i+1].severity]

    def test_degradation_to_dict(self):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        degs = _detect(img)
        assert len(degs) > 0
        d = degs[0].to_dict()
        assert "type" in d
        assert "severity" in d
        assert "confidence" in d
        assert "recovery" in d

    def test_empty_image(self):
        degs = _detect(np.array([], dtype=np.uint8))
        assert len(degs) == 1
        assert degs[0].type == DegradationType.TOTAL_BLACK

    def test_grayscale_input(self):
        gray = np.ones((480, 640), dtype=np.uint8) * 127
        q = assess_quality(gray)
        degs = detect_degradations(gray, q)
        # Should work without crashing
        assert isinstance(degs, list)
