"""
DegradationDetector - detects and classifies image problems.

Maria knows WHAT is wrong, not just THAT something is wrong.
Each degradation has a severity, affected area, and suggested recovery.

Phase 2: Preprocessing Layer (VISION_SPEC.md)
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore[assignment]

from agent_core.vision.models import DegradationType
from agent_core.vision.preprocessing.quality import QualityAssessment

logger = logging.getLogger(__name__)


class RecoveryAction(Enum):
    """Suggested action to fix a detected degradation."""
    RETRY_CAPTURE = "retry_capture"
    SWITCH_MODE = "switch_mode"
    REDUCE_RESOLUTION = "reduce_resolution"
    INCREASE_EXPOSURE = "increase_exposure"
    DECREASE_EXPOSURE = "decrease_exposure"
    CLEAN_LENS = "clean_lens"
    RESTART_SENSOR = "restart_sensor"
    FALLBACK_SENSOR = "fallback_sensor"
    ACCEPT_DEGRADED = "accept_degraded"


class DegradationSeverity(Enum):
    """How bad is this degradation."""
    MILD = "mild"         # Noticeable but usable
    MODERATE = "moderate" # Affects analysis quality
    SEVERE = "severe"     # Most analysis will fail


@dataclass(frozen=True)
class Degradation:
    """A detected image degradation."""
    type: DegradationType
    severity: DegradationSeverity
    confidence: float  # 0.0-1.0 how sure we are
    description: str
    recovery: RecoveryAction
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "severity": self.severity.value,
            "confidence": round(self.confidence, 3),
            "description": self.description,
            "recovery": self.recovery.value,
        }


# Detection thresholds
_TOTAL_BLACK_MEAN = 5.0
_TOTAL_WHITE_MEAN = 250.0
_LOW_CONTRAST_STD = 15.0
_HEAVY_NOISE_STD = 12.0
_BLUR_LAPLACIAN_VAR = 50.0
_PARTIAL_FRAME_ZERO_RATIO = 0.3
_COLOR_SHIFT_DEVIATION = 25.0
_LOW_RES_THRESHOLD = 160  # pixels (width below this)


def detect_degradations(
    image: np.ndarray,
    quality: QualityAssessment,
    previous_image: Optional[np.ndarray] = None,
) -> List[Degradation]:
    """Detect all degradations in an image.

    Args:
        image: BGR image (HxWx3 or HxW)
        quality: Pre-computed quality assessment
        previous_image: Previous frame for frozen detection

    Returns:
        List of detected degradations, sorted by severity (worst first).
    """
    if image is None or image.size == 0:
        return [Degradation(
            type=DegradationType.TOTAL_BLACK,
            severity=DegradationSeverity.SEVERE,
            confidence=1.0,
            description="Brak danych obrazu.",
            recovery=RecoveryAction.RESTART_SENSOR,
        )]

    degradations = []

    # Grayscale for analysis
    if image.ndim == 3 and image.shape[2] == 3:
        if cv2 is not None:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = np.mean(image, axis=2).astype(np.uint8)
    elif image.ndim == 2:
        gray = image
    else:
        return []

    mean_lum = float(np.mean(gray))
    std_lum = float(np.std(gray))

    # Total black
    if mean_lum < _TOTAL_BLACK_MEAN:
        degradations.append(Degradation(
            type=DegradationType.TOTAL_BLACK,
            severity=DegradationSeverity.SEVERE,
            confidence=min(1.0, (1.0 - mean_lum / _TOTAL_BLACK_MEAN)),
            description="Obraz jest calkowicie ciemny.",
            recovery=RecoveryAction.INCREASE_EXPOSURE,
            details={"mean_luminance": round(mean_lum, 1)},
        ))

    # Total white
    if mean_lum > _TOTAL_WHITE_MEAN:
        degradations.append(Degradation(
            type=DegradationType.TOTAL_WHITE,
            severity=DegradationSeverity.SEVERE,
            confidence=min(1.0, (mean_lum - _TOTAL_WHITE_MEAN) / (255.0 - _TOTAL_WHITE_MEAN)),
            description="Obraz jest przeswietlony.",
            recovery=RecoveryAction.DECREASE_EXPOSURE,
            details={"mean_luminance": round(mean_lum, 1)},
        ))

    # Low contrast
    if std_lum < _LOW_CONTRAST_STD:
        severity = DegradationSeverity.SEVERE if std_lum < 5.0 else DegradationSeverity.MODERATE
        degradations.append(Degradation(
            type=DegradationType.LOW_CONTRAST,
            severity=severity,
            confidence=min(1.0, 1.0 - std_lum / _LOW_CONTRAST_STD),
            description="Niski kontrast - obraz jest plaski.",
            recovery=RecoveryAction.SWITCH_MODE,
            details={"std_luminance": round(std_lum, 1)},
        ))

    # Heavy noise (from quality assessment)
    if quality.noise_level < 0.5:
        severity = DegradationSeverity.SEVERE if quality.noise_level < 0.2 else DegradationSeverity.MODERATE
        degradations.append(Degradation(
            type=DegradationType.HEAVY_NOISE,
            severity=severity,
            confidence=1.0 - quality.noise_level,
            description="Duzo szumu w obrazie.",
            recovery=RecoveryAction.REDUCE_RESOLUTION,
            details={"noise_score": round(quality.noise_level, 3)},
        ))

    # Focus blur (from quality assessment)
    if quality.sharpness < 0.3:
        severity = DegradationSeverity.SEVERE if quality.sharpness < 0.1 else DegradationSeverity.MODERATE
        degradations.append(Degradation(
            type=DegradationType.FOCUS_BLUR,
            severity=severity,
            confidence=1.0 - quality.sharpness,
            description="Obraz jest nieoostry - problem z fokusem.",
            recovery=RecoveryAction.RETRY_CAPTURE,
            details={"sharpness_score": round(quality.sharpness, 3)},
        ))

    # Motion blur (from quality assessment)
    if quality.motion_blur < 0.4:
        severity = DegradationSeverity.MODERATE if quality.motion_blur > 0.15 else DegradationSeverity.SEVERE
        degradations.append(Degradation(
            type=DegradationType.MOTION_BLUR,
            severity=severity,
            confidence=1.0 - quality.motion_blur,
            description="Rozmycie ruchowe - cos sie poruszalo podczas zdjecia.",
            recovery=RecoveryAction.RETRY_CAPTURE,
            details={"motion_blur_score": round(quality.motion_blur, 3)},
        ))

    # Color shift
    if image.ndim == 3 and image.shape[2] == 3:
        channel_means = [float(np.mean(image[:, :, c])) for c in range(3)]
        overall_mean = sum(channel_means) / 3.0
        if overall_mean > 1.0:
            max_dev = max(abs(m - overall_mean) for m in channel_means)
            if max_dev > _COLOR_SHIFT_DEVIATION:
                degradations.append(Degradation(
                    type=DegradationType.COLOR_SHIFT,
                    severity=DegradationSeverity.MILD,
                    confidence=min(1.0, max_dev / (2 * _COLOR_SHIFT_DEVIATION)),
                    description="Kolory sa przesuniete - balans bieli jest bledny.",
                    recovery=RecoveryAction.SWITCH_MODE,
                    details={"channel_means": [round(m, 1) for m in channel_means]},
                ))

    # Partial frame (large black regions)
    if image.ndim >= 2:
        zero_ratio = float(np.sum(gray == 0)) / gray.size
        if zero_ratio > _PARTIAL_FRAME_ZERO_RATIO and mean_lum > _TOTAL_BLACK_MEAN:
            degradations.append(Degradation(
                type=DegradationType.PARTIAL_FRAME,
                severity=DegradationSeverity.MODERATE,
                confidence=min(1.0, zero_ratio),
                description="Czesc obrazu jest pusta - niekompletna klatka.",
                recovery=RecoveryAction.RETRY_CAPTURE,
                details={"zero_ratio": round(zero_ratio, 3)},
            ))

    # Low resolution
    h, w = gray.shape[:2]
    if w < _LOW_RES_THRESHOLD:
        degradations.append(Degradation(
            type=DegradationType.LOW_RESOLUTION,
            severity=DegradationSeverity.MILD if w > 80 else DegradationSeverity.MODERATE,
            confidence=min(1.0, 1.0 - w / _LOW_RES_THRESHOLD),
            description="Rozdzielczosc jest bardzo niska.",
            recovery=RecoveryAction.ACCEPT_DEGRADED,
            details={"width": w, "height": h},
        ))

    # Frozen frame (identical to previous)
    if previous_image is not None and previous_image.shape == image.shape:
        if np.array_equal(image, previous_image):
            degradations.append(Degradation(
                type=DegradationType.FROZEN,
                severity=DegradationSeverity.SEVERE,
                confidence=1.0,
                description="Obraz jest zamrozony - identyczny jak poprzedni.",
                recovery=RecoveryAction.RESTART_SENSOR,
            ))

    # Occlusion detection (large uniform region covering center)
    if gray.shape[0] > 10 and gray.shape[1] > 10:
        center_h, center_w = gray.shape[0] // 2, gray.shape[1] // 2
        margin_h, margin_w = gray.shape[0] // 4, gray.shape[1] // 4
        center_region = gray[
            center_h - margin_h:center_h + margin_h,
            center_w - margin_w:center_w + margin_w,
        ]
        center_std = float(np.std(center_region))
        if center_std < 3.0 and std_lum > _LOW_CONTRAST_STD:
            degradations.append(Degradation(
                type=DegradationType.OCCLUSION,
                severity=DegradationSeverity.SEVERE,
                confidence=max(0.5, 1.0 - center_std / 3.0),
                description="Cos zaslania obiektyw - centrum jest jednolite.",
                recovery=RecoveryAction.CLEAN_LENS,
                details={"center_std": round(center_std, 2)},
            ))

    # Sort by severity (worst first)
    severity_order = {
        DegradationSeverity.SEVERE: 0,
        DegradationSeverity.MODERATE: 1,
        DegradationSeverity.MILD: 2,
    }
    degradations.sort(key=lambda d: severity_order.get(d.severity, 9))

    return degradations
