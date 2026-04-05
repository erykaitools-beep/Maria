"""
Frame normalizer - resolution, format, and basic corrections.

Ensures downstream modules always receive consistent frame format:
- Target resolution (default 640x480)
- BGR 3-channel
- Optional white balance and exposure correction

Phase 2: Preprocessing Layer (VISION_SPEC.md)
"""

import logging
from typing import Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

DEFAULT_TARGET_RESOLUTION = (640, 480)  # (width, height)


def normalize_frame(
    image: np.ndarray,
    target_resolution: Optional[Tuple[int, int]] = None,
    auto_white_balance: bool = False,
    auto_exposure: bool = False,
) -> np.ndarray:
    """Normalize a frame to consistent format.

    Args:
        image: Input image (any shape/type)
        target_resolution: (width, height) to resize to, None = keep original
        auto_white_balance: Apply simple white balance correction
        auto_exposure: Apply histogram equalization for exposure

    Returns:
        Normalized BGR image as uint8 numpy array.
    """
    if image is None or image.size == 0:
        return image

    result = image

    # Ensure uint8
    if result.dtype != np.uint8:
        if result.max() <= 1.0:
            result = (result * 255).astype(np.uint8)
        else:
            result = result.astype(np.uint8)

    # Convert grayscale to BGR
    if result.ndim == 2:
        if cv2 is not None:
            result = cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)
        else:
            result = np.stack([result, result, result], axis=2)

    # Resize if needed
    if target_resolution is not None and cv2 is not None:
        target_w, target_h = target_resolution
        current_h, current_w = result.shape[:2]
        if current_w != target_w or current_h != target_h:
            # Use AREA for downscale, LINEAR for upscale
            if current_w > target_w or current_h > target_h:
                interp = cv2.INTER_AREA
            else:
                interp = cv2.INTER_LINEAR
            result = cv2.resize(result, (target_w, target_h), interpolation=interp)

    # White balance (simple gray world assumption)
    if auto_white_balance and cv2 is not None:
        result = _apply_white_balance(result)

    # Exposure correction (histogram equalization on luminance)
    if auto_exposure and cv2 is not None:
        result = _apply_exposure_correction(result)

    return result


def _apply_white_balance(image: np.ndarray) -> np.ndarray:
    """Simple white balance via gray world assumption.

    Scales each channel so its mean equals the overall mean.
    """
    means = np.mean(image, axis=(0, 1)).astype(np.float32)
    overall_mean = np.mean(means)
    if overall_mean < 1.0:
        return image

    scales = overall_mean / np.maximum(means, 1.0)
    result = image.astype(np.float32)
    for c in range(3):
        result[:, :, c] *= scales[c]

    return np.clip(result, 0, 255).astype(np.uint8)


def _apply_exposure_correction(image: np.ndarray) -> np.ndarray:
    """Exposure correction via CLAHE on luminance channel.

    Converts to LAB, applies CLAHE to L channel, converts back.
    """
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_channel = lab[:, :, 0]

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lab[:, :, 0] = clahe.apply(l_channel)

    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
