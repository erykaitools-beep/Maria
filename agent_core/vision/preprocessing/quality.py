"""
QualityAssessment - image quality metrics for vision frames.

Measures sharpness, brightness, contrast, noise level, color balance,
and motion blur using lightweight OpenCV operations. All metrics are
normalized to 0.0-1.0 range.

Target: < 10ms per frame at 640x480.

Phase 2: Preprocessing Layer (VISION_SPEC.md)
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Thresholds calibrated for typical webcam at 640x480
_SHARPNESS_MAX = 500.0        # Laplacian variance above this = perfectly sharp
_BRIGHTNESS_IDEAL = 127.0     # Ideal mean luminance (mid-range)
_BRIGHTNESS_RANGE = 100.0     # Acceptable deviation from ideal
_CONTRAST_MAX = 80.0          # Std dev of luminance above this = high contrast
_NOISE_THRESHOLD = 15.0       # Estimated noise std above this = noisy
_COLOR_BALANCE_MAX = 30.0     # Max acceptable channel mean deviation
_MOTION_BLUR_THRESHOLD = 0.3  # Directional variance ratio below this = motion blur


@dataclass(frozen=True)
class QualityAssessment:
    """Image quality metrics, all normalized to 0.0-1.0.

    Higher values mean better quality.
    """

    sharpness: float = 1.0       # Focus quality (Laplacian variance)
    brightness: float = 1.0      # Exposure correctness (proximity to ideal)
    contrast: float = 1.0        # Tonal range (luminance std dev)
    noise_level: float = 1.0     # Noise-free quality (1=clean, 0=noisy)
    color_balance: float = 1.0   # Channel balance (1=balanced, 0=shifted)
    motion_blur: float = 1.0     # Motion blur absence (1=sharp, 0=blurred)

    @property
    def overall(self) -> float:
        """Weighted overall quality score.

        Sharpness and brightness are most important for downstream modules.
        """
        return max(0.0, min(1.0,
            0.25 * self.sharpness
            + 0.20 * self.brightness
            + 0.15 * self.contrast
            + 0.15 * self.noise_level
            + 0.10 * self.color_balance
            + 0.15 * self.motion_blur
        ))

    def to_dict(self) -> dict:
        return {
            "overall": round(self.overall, 3),
            "sharpness": round(self.sharpness, 3),
            "brightness": round(self.brightness, 3),
            "contrast": round(self.contrast, 3),
            "noise_level": round(self.noise_level, 3),
            "color_balance": round(self.color_balance, 3),
            "motion_blur": round(self.motion_blur, 3),
        }


def assess_quality(image: np.ndarray) -> QualityAssessment:
    """Assess image quality using lightweight OpenCV operations.

    Args:
        image: BGR image (numpy array, shape HxWx3 or HxW)

    Returns:
        QualityAssessment with all metrics normalized to 0.0-1.0.
    """
    if image is None or image.size == 0:
        return QualityAssessment(
            sharpness=0.0, brightness=0.0, contrast=0.0,
            noise_level=0.0, color_balance=0.0, motion_blur=0.0,
        )

    if cv2 is None:
        return QualityAssessment()

    # Convert to grayscale for most metrics
    if image.ndim == 3 and image.shape[2] == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    elif image.ndim == 2:
        gray = image
    else:
        return QualityAssessment(
            sharpness=0.0, brightness=0.0, contrast=0.0,
            noise_level=0.0, color_balance=0.0, motion_blur=0.0,
        )

    sharpness = _measure_sharpness(gray)
    brightness = _measure_brightness(gray)
    contrast = _measure_contrast(gray)
    noise_level = _measure_noise(gray)
    color_balance = _measure_color_balance(image)
    motion_blur = _measure_motion_blur(gray)

    return QualityAssessment(
        sharpness=sharpness,
        brightness=brightness,
        contrast=contrast,
        noise_level=noise_level,
        color_balance=color_balance,
        motion_blur=motion_blur,
    )


def _measure_sharpness(gray: np.ndarray) -> float:
    """Sharpness via Laplacian variance.

    Higher variance = sharper image (more edges).
    """
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    variance = float(laplacian.var())
    return min(1.0, variance / _SHARPNESS_MAX)


def _measure_brightness(gray: np.ndarray) -> float:
    """Brightness as proximity to ideal mean luminance.

    Score 1.0 when mean is near 127 (ideal), drops toward 0/255.
    """
    mean_lum = float(np.mean(gray))
    deviation = abs(mean_lum - _BRIGHTNESS_IDEAL)
    return max(0.0, 1.0 - (deviation / _BRIGHTNESS_RANGE))


def _measure_contrast(gray: np.ndarray) -> float:
    """Contrast via standard deviation of luminance.

    Higher std dev = better contrast (wider tonal range).
    """
    std_dev = float(np.std(gray))
    return min(1.0, std_dev / _CONTRAST_MAX)


def _measure_noise(gray: np.ndarray) -> float:
    """Noise estimation via high-frequency energy.

    Uses difference between image and its Gaussian blur.
    Higher difference = more noise = lower score.
    """
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    diff = gray.astype(np.float32) - blurred.astype(np.float32)
    noise_std = float(np.std(diff))
    return max(0.0, 1.0 - (noise_std / _NOISE_THRESHOLD))


def _measure_color_balance(image: np.ndarray) -> float:
    """Color balance via channel mean deviation.

    Balanced image has similar means across B, G, R channels.
    """
    if image.ndim != 3 or image.shape[2] != 3:
        return 1.0  # Grayscale is "balanced" by definition

    means = [float(np.mean(image[:, :, c])) for c in range(3)]
    overall_mean = sum(means) / 3.0
    if overall_mean < 1.0:
        return 0.0  # Nearly black image

    max_dev = max(abs(m - overall_mean) for m in means)
    return max(0.0, 1.0 - (max_dev / _COLOR_BALANCE_MAX))


def _measure_motion_blur(gray: np.ndarray) -> float:
    """Motion blur detection via directional gradient analysis.

    Compares horizontal and vertical Sobel gradients.
    Strong directional bias suggests motion blur.
    """
    sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)

    var_x = float(np.var(sobel_x))
    var_y = float(np.var(sobel_y))

    if var_x + var_y < 1.0:
        return 0.5  # Featureless image, can't determine

    ratio = min(var_x, var_y) / max(var_x, var_y)
    # ratio close to 1.0 = balanced (no motion blur)
    # ratio close to 0.0 = one direction dominates (motion blur)
    if ratio < _MOTION_BLUR_THRESHOLD:
        return ratio / _MOTION_BLUR_THRESHOLD  # Scale to 0-1
    return 1.0
