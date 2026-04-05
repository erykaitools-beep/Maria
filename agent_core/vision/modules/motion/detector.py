"""
MotionModule - movement detection via frame differencing.

Lightweight motion detection that works even with very low quality images.
Uses OpenCV background subtraction and contour analysis.

Features:
- Motion level (0.0-1.0)
- Motion regions with bounding boxes
- Classification (person_movement, object_movement, camera_shake, ambient)
- Alert levels (none, attention, warning, danger)
- Graceful degradation: works at quality >= 0.2

Phase 3: Vision Modules (VISION_SPEC.md)
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore[assignment]

from agent_core.vision.modules.base import ModuleOutput
from agent_core.vision.preprocessing.preprocessor import ProcessedFrame

logger = logging.getLogger(__name__)


class MotionClassification(Enum):
    """What kind of motion was detected."""
    NONE = "none"
    PERSON_MOVEMENT = "person_movement"    # Large, centered region
    OBJECT_MOVEMENT = "object_movement"    # Medium region
    CAMERA_SHAKE = "camera_shake"          # Many small regions everywhere
    AMBIENT = "ambient"                    # Small, peripheral changes (light, shadows)


class AlertLevel(Enum):
    """How urgent is the detected motion."""
    NONE = "none"
    ATTENTION = "attention"    # Something moved
    WARNING = "warning"        # Significant movement
    DANGER = "danger"          # Large, sudden movement


@dataclass(frozen=True)
class MotionRegion:
    """A region where motion was detected."""
    bounding_box: Tuple[int, int, int, int]  # (x, y, w, h)
    area: int
    center: Tuple[int, int]

    def to_dict(self) -> dict:
        return {
            "bounding_box": list(self.bounding_box),
            "area": self.area,
            "center": list(self.center),
        }


@dataclass
class MotionOutput(ModuleOutput):
    """Output from the motion detection module."""

    motion_detected: bool = False
    motion_level: float = 0.0     # 0.0-1.0
    regions: List[MotionRegion] = field(default_factory=list)
    classification: MotionClassification = MotionClassification.NONE
    alert_level: AlertLevel = AlertLevel.NONE
    total_changed_pixels: int = 0
    frame_diff_mean: float = 0.0

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "motion_detected": self.motion_detected,
            "motion_level": round(self.motion_level, 3),
            "regions": [r.to_dict() for r in self.regions],
            "classification": self.classification.value,
            "alert_level": self.alert_level.value,
            "total_changed_pixels": self.total_changed_pixels,
        })
        return d


# Thresholds
_MIN_CONTOUR_AREA = 500       # Ignore tiny contours (noise)
_DIFF_THRESHOLD = 25          # Pixel difference threshold
_MOTION_LEVEL_SCALE = 0.15    # Fraction of pixels that counts as max motion
_LARGE_REGION_RATIO = 0.05    # Region this big relative to frame = significant
_PERSON_REGION_RATIO = 0.02   # Region this big = probably a person
_SHAKE_REGION_COUNT = 10      # This many small regions = camera shake
_ALERT_WARNING = 0.15         # Motion level for WARNING
_ALERT_DANGER = 0.35          # Motion level for DANGER


class MotionModule:
    """Motion detection via frame differencing.

    Implements VisionModule protocol. Compares current frame to previous
    to detect movement. Classifies motion type and assigns alert level.

    Usage:
        module = MotionModule()
        output = module.analyze(processed_frame)
        if output and output.motion_detected:
            print(f"Motion: {output.classification.value}")
    """

    def __init__(
        self,
        diff_threshold: int = _DIFF_THRESHOLD,
        min_contour_area: int = _MIN_CONTOUR_AREA,
    ):
        self._diff_threshold = diff_threshold
        self._min_contour_area = min_contour_area
        self._previous_gray: Optional[np.ndarray] = None

    @property
    def module_name(self) -> str:
        return "motion"

    @property
    def required_quality(self) -> float:
        return 0.2  # Works even with very poor quality

    @property
    def can_work_degraded(self) -> bool:
        return True

    def analyze(self, frame: ProcessedFrame) -> Optional[MotionOutput]:
        """Analyze frame for motion.

        First call always returns no motion (no previous frame to compare).
        """
        if frame.image is None or frame.image.size == 0:
            return None

        # Quality gate
        if frame.quality.overall < self.required_quality and not self.can_work_degraded:
            return None

        t0 = time.monotonic()

        # Convert to grayscale
        if cv2 is not None and frame.image.ndim == 3:
            gray = cv2.cvtColor(frame.image, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)
        elif frame.image.ndim == 2:
            gray = frame.image
        else:
            # No cv2 - manual grayscale
            gray = np.mean(frame.image, axis=2).astype(np.uint8)

        is_degraded = frame.quality.overall < 0.5

        if self._previous_gray is None or self._previous_gray.shape != gray.shape:
            self._previous_gray = gray
            elapsed = (time.monotonic() - t0) * 1000.0
            return MotionOutput(
                module_name=self.module_name,
                confidence=0.0,
                is_degraded=is_degraded,
                processing_time_ms=elapsed,
                motion_detected=False,
                motion_level=0.0,
            )

        # Frame differencing
        diff = cv2.absdiff(self._previous_gray, gray) if cv2 is not None else np.abs(
            self._previous_gray.astype(np.int16) - gray.astype(np.int16)
        ).astype(np.uint8)

        # Threshold
        if cv2 is not None:
            _, thresh = cv2.threshold(diff, self._diff_threshold, 255, cv2.THRESH_BINARY)
        else:
            thresh = (diff > self._diff_threshold).astype(np.uint8) * 255

        # Calculate motion level
        total_pixels = gray.shape[0] * gray.shape[1]
        changed_pixels = int(np.sum(thresh > 0))
        motion_level = min(1.0, changed_pixels / (total_pixels * _MOTION_LEVEL_SCALE))
        diff_mean = float(np.mean(diff))

        # Find motion regions
        regions = []
        if cv2 is not None:
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = cv2.contourArea(contour)
                if area >= self._min_contour_area:
                    x, y, w, h = cv2.boundingRect(contour)
                    cx, cy = x + w // 2, y + h // 2
                    regions.append(MotionRegion(
                        bounding_box=(x, y, w, h),
                        area=int(area),
                        center=(cx, cy),
                    ))

        # Sort by area (largest first)
        regions.sort(key=lambda r: r.area, reverse=True)

        # Classify motion
        classification = self._classify_motion(regions, total_pixels, motion_level)

        # Determine alert level
        alert_level = self._determine_alert(motion_level, classification)

        # Confidence based on quality and motion strength
        confidence = min(1.0, frame.quality.overall * 1.2) if motion_level > 0.01 else 0.0

        # Store for next comparison
        self._previous_gray = gray

        elapsed = (time.monotonic() - t0) * 1000.0

        return MotionOutput(
            module_name=self.module_name,
            confidence=confidence,
            is_degraded=is_degraded,
            processing_time_ms=elapsed,
            motion_detected=motion_level > 0.01,
            motion_level=motion_level,
            regions=regions,
            classification=classification,
            alert_level=alert_level,
            total_changed_pixels=changed_pixels,
            frame_diff_mean=diff_mean,
        )

    def reset(self) -> None:
        """Clear previous frame (e.g. after sensor switch)."""
        self._previous_gray = None

    def _classify_motion(
        self,
        regions: List[MotionRegion],
        total_pixels: int,
        motion_level: float,
    ) -> MotionClassification:
        """Classify what kind of motion was detected."""
        if motion_level < 0.01:
            return MotionClassification.NONE

        if not regions:
            if motion_level < 0.05:
                return MotionClassification.AMBIENT
            return MotionClassification.CAMERA_SHAKE

        # Many small regions scattered = camera shake
        small_regions = [r for r in regions if r.area < total_pixels * 0.005]
        if len(small_regions) >= _SHAKE_REGION_COUNT:
            return MotionClassification.CAMERA_SHAKE

        # Check largest region
        largest = regions[0]
        region_ratio = largest.area / total_pixels

        if region_ratio >= _PERSON_REGION_RATIO:
            return MotionClassification.PERSON_MOVEMENT
        elif region_ratio >= _LARGE_REGION_RATIO * 0.5:
            return MotionClassification.OBJECT_MOVEMENT
        else:
            return MotionClassification.AMBIENT

    def _determine_alert(
        self,
        motion_level: float,
        classification: MotionClassification,
    ) -> AlertLevel:
        """Determine alert level based on motion level and type."""
        if classification == MotionClassification.NONE:
            return AlertLevel.NONE
        if classification == MotionClassification.AMBIENT:
            return AlertLevel.NONE
        if classification == MotionClassification.CAMERA_SHAKE:
            return AlertLevel.ATTENTION

        if motion_level >= _ALERT_DANGER:
            return AlertLevel.DANGER
        elif motion_level >= _ALERT_WARNING:
            return AlertLevel.WARNING
        else:
            return AlertLevel.ATTENTION
