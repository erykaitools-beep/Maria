"""
MotionModule - movement detection via MOG2 background subtraction.

Lightweight motion detection that works even with very low quality images.
Uses OpenCV's adaptive background model (MOG2) with shadow detection, falling
back to naive frame differencing only when cv2 is unavailable.

Why MOG2 (not plain frame-diff): a cheap "compare this frame to the previous
one" detector treats ANY pixel change as motion -- so a cloud crossing the sun,
a sudden glint off a car, or gusty light all flip the whole frame and read as a
huge "person/danger" event. MOG2 instead learns a statistical model of the
background and adapts to gradual lighting, while detect_shadows marks darkening
(cloud shadows) as shadow rather than foreground. A global-change guard
suppresses the residual SUDDEN full-frame illumination jumps that the model has
not yet absorbed. Net effect: Maria reacts to objects that move, not to light
that changes.

Features:
- Motion level (0.0-1.0)
- Motion regions with bounding boxes
- Classification (person_movement, object_movement, camera_shake, ambient)
- Alert levels (none, attention, warning, danger)
- Illumination robustness: gradual light absorbed, sudden global light suppressed
- Graceful degradation: works at quality >= 0.2

Phase 3: Vision Modules (VISION_SPEC.md)
Illumination-robust rewrite: 2026-06-21 (operator: false pings on clouds/glare).
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
_DIFF_THRESHOLD = 25          # Pixel difference threshold (legacy fallback only)
_MOTION_LEVEL_SCALE = 0.15    # Fraction of pixels that counts as max motion
_LARGE_REGION_RATIO = 0.05    # Region this big relative to frame = significant
_PERSON_REGION_RATIO = 0.02   # Region this big = probably a person
_SHAKE_REGION_COUNT = 10      # This many small regions = camera shake
_ALERT_WARNING = 0.15         # Motion level for WARNING
_ALERT_DANGER = 0.35          # Motion level for DANGER

# MOG2 background subtraction (primary path).
_MOG2_HISTORY = 500           # Frames blended into the background model
_MOG2_VAR_THRESHOLD = 16      # Mahalanobis^2 cutoff for foreground (OpenCV default)
_MOG2_DETECT_SHADOWS = True   # Mark darkening (e.g. cloud shadow) as shadow, not motion
_MOG2_LEARNING_RATE = -1.0    # -1 = auto (fast early, ~1/history at steady state)
_MORPH_KERNEL_SIZE = 5        # Opening kernel to drop speckle noise from the mask
# If this fraction of the frame turns foreground at once it is a global lighting
# change (cloud/sun/glare), not an object -- suppress it. A person fills ~10-15%
# of an outdoor frame, a sudden global flip fills ~100%, so 0.6 separates cleanly.
_GLOBAL_CHANGE_RATIO = 0.6
# First frame(s) only seed the model; report no motion regardless.
_WARMUP_FRAMES = 1


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
        history: int = _MOG2_HISTORY,
        var_threshold: float = _MOG2_VAR_THRESHOLD,
        detect_shadows: bool = _MOG2_DETECT_SHADOWS,
        learning_rate: float = _MOG2_LEARNING_RATE,
        global_change_ratio: float = _GLOBAL_CHANGE_RATIO,
        warmup_frames: int = _WARMUP_FRAMES,
    ):
        self._diff_threshold = diff_threshold
        self._min_contour_area = min_contour_area
        self._previous_gray: Optional[np.ndarray] = None  # legacy fallback only

        # MOG2 config (kept so reset() can rebuild an identical model).
        self._history = history
        self._var_threshold = var_threshold
        self._detect_shadows = detect_shadows
        self._learning_rate = learning_rate
        self._global_change_ratio = global_change_ratio
        self._warmup_frames = warmup_frames
        self._frames_seen = 0
        self._bg_subtractor = self._make_subtractor()
        self._morph_kernel = (
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (_MORPH_KERNEL_SIZE, _MORPH_KERNEL_SIZE)
            )
            if cv2 is not None
            else None
        )

    def _make_subtractor(self):
        """Create a MOG2 subtractor, or None if cv2 is unavailable."""
        if cv2 is None:
            return None
        try:
            return cv2.createBackgroundSubtractorMOG2(
                history=self._history,
                varThreshold=self._var_threshold,
                detectShadows=self._detect_shadows,
            )
        except Exception:  # pragma: no cover - defensive, cv2 build without MOG2
            return None

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

        First frame(s) only seed the background model and report no motion.
        Uses MOG2 when cv2 is available, else naive frame differencing.
        """
        if frame.image is None or frame.image.size == 0:
            return None

        # Quality gate
        if frame.quality.overall < self.required_quality and not self.can_work_degraded:
            return None

        t0 = time.monotonic()

        # Convert to grayscale (blur smooths sensor noise before differencing)
        if cv2 is not None and frame.image.ndim == 3:
            gray = cv2.cvtColor(frame.image, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)
        elif frame.image.ndim == 2:
            gray = frame.image
        else:
            # No cv2 - manual grayscale
            gray = np.mean(frame.image, axis=2).astype(np.uint8)

        is_degraded = frame.quality.overall < 0.5

        if self._bg_subtractor is not None:
            return self._analyze_mog2(frame, gray, is_degraded, t0)
        return self._analyze_framediff(frame, gray, is_degraded, t0)

    def _quiet_output(self, is_degraded: bool, t0: float) -> MotionOutput:
        """A no-motion result (warmup, seeded frame, or suppressed lighting)."""
        return MotionOutput(
            module_name=self.module_name,
            confidence=0.0,
            is_degraded=is_degraded,
            processing_time_ms=(time.monotonic() - t0) * 1000.0,
            motion_detected=False,
            motion_level=0.0,
        )

    def _analyze_mog2(
        self,
        frame: ProcessedFrame,
        gray: np.ndarray,
        is_degraded: bool,
        t0: float,
    ) -> MotionOutput:
        """Primary path: adaptive background subtraction, illumination-robust."""
        # Always apply() so the model keeps learning, even when we suppress output.
        fgmask = self._bg_subtractor.apply(gray, learningRate=self._learning_rate)

        # foreground == 255; shadows == 127 (darkening, e.g. cloud shadow) excluded.
        foreground = (fgmask == 255).astype(np.uint8) * 255

        total_pixels = gray.shape[0] * gray.shape[1]
        raw_changed = int(np.count_nonzero(foreground))
        fg_fraction = raw_changed / total_pixels if total_pixels else 0.0

        # Warmup: first frame(s) just seed the model.
        self._frames_seen += 1
        if self._frames_seen <= self._warmup_frames:
            return self._quiet_output(is_degraded, t0)

        # Global-change guard: a sudden full-frame flip is light, not an object.
        if fg_fraction >= self._global_change_ratio:
            return self._quiet_output(is_degraded, t0)

        # Drop speckle noise (opening: erode then dilate).
        if self._morph_kernel is not None:
            foreground = cv2.morphologyEx(foreground, cv2.MORPH_OPEN, self._morph_kernel)

        changed_pixels = int(np.count_nonzero(foreground))
        motion_level = min(1.0, changed_pixels / (total_pixels * _MOTION_LEVEL_SCALE))

        # Find motion regions
        regions: List[MotionRegion] = []
        contours, _ = cv2.findContours(
            foreground, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
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
        regions.sort(key=lambda r: r.area, reverse=True)

        classification = self._classify_motion(regions, total_pixels, motion_level)
        alert_level = self._determine_alert(motion_level, classification)
        confidence = min(1.0, frame.quality.overall * 1.2) if motion_level > 0.01 else 0.0

        return MotionOutput(
            module_name=self.module_name,
            confidence=confidence,
            is_degraded=is_degraded,
            processing_time_ms=(time.monotonic() - t0) * 1000.0,
            motion_detected=motion_level > 0.01,
            motion_level=motion_level,
            regions=regions,
            classification=classification,
            alert_level=alert_level,
            total_changed_pixels=changed_pixels,
            frame_diff_mean=float(fg_fraction),
        )

    def _analyze_framediff(
        self,
        frame: ProcessedFrame,
        gray: np.ndarray,
        is_degraded: bool,
        t0: float,
    ) -> MotionOutput:
        """Fallback path (cv2 unavailable): naive previous-frame differencing.

        Kept only for environments without OpenCV; lacks the MOG2 path's
        illumination robustness.
        """
        if self._previous_gray is None or self._previous_gray.shape != gray.shape:
            self._previous_gray = gray
            return self._quiet_output(is_degraded, t0)

        diff = np.abs(
            self._previous_gray.astype(np.int16) - gray.astype(np.int16)
        ).astype(np.uint8)
        thresh = (diff > self._diff_threshold).astype(np.uint8) * 255

        total_pixels = gray.shape[0] * gray.shape[1]
        changed_pixels = int(np.sum(thresh > 0))
        motion_level = min(1.0, changed_pixels / (total_pixels * _MOTION_LEVEL_SCALE))
        diff_mean = float(np.mean(diff))

        # Contour detection (when cv2 is present but MOG2 failed to construct).
        # Without it _classify_motion never sees regions -> everything reads as
        # AMBIENT/CAMERA_SHAKE and the adapter filters out real person movement.
        regions: List[MotionRegion] = []
        if cv2 is not None:
            contours, _ = cv2.findContours(
                thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
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
            regions.sort(key=lambda r: r.area, reverse=True)

        classification = self._classify_motion(regions, total_pixels, motion_level)
        alert_level = self._determine_alert(motion_level, classification)
        confidence = min(1.0, frame.quality.overall * 1.2) if motion_level > 0.01 else 0.0

        self._previous_gray = gray

        return MotionOutput(
            module_name=self.module_name,
            confidence=confidence,
            is_degraded=is_degraded,
            processing_time_ms=(time.monotonic() - t0) * 1000.0,
            motion_detected=motion_level > 0.01,
            motion_level=motion_level,
            regions=regions,
            classification=classification,
            alert_level=alert_level,
            total_changed_pixels=changed_pixels,
            frame_diff_mean=diff_mean,
        )

    def reset(self) -> None:
        """Clear background model (e.g. after sensor switch)."""
        self._previous_gray = None
        self._frames_seen = 0
        self._bg_subtractor = self._make_subtractor()

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
