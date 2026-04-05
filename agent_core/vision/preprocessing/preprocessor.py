"""
VisionPreprocessor - main preprocessing pipeline.

Takes a raw Frame from a sensor and produces a ProcessedFrame with:
- Normalized image (consistent resolution and format)
- Quality assessment (6 metrics)
- Detected degradations (with recovery suggestions)
- Processing time

Like the retina: normalize first, assess quality, flag problems.

Phase 2: Preprocessing Layer (VISION_SPEC.md)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from agent_core.vision.models import DegradationType, Frame
from agent_core.vision.preprocessing.degradation import (
    Degradation,
    detect_degradations,
)
from agent_core.vision.preprocessing.normalizer import normalize_frame
from agent_core.vision.preprocessing.quality import (
    QualityAssessment,
    assess_quality,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessedFrame:
    """A frame after preprocessing.

    Contains the normalized image plus quality metrics and
    any detected degradations. This is what vision modules receive.
    """

    image: np.ndarray
    quality: QualityAssessment
    degradations: Tuple[Degradation, ...] = ()
    processing_time_ms: float = 0.0
    original_resolution: Tuple[int, int] = (0, 0)
    timestamp: float = 0.0
    sensor_id: str = ""
    sequence_number: int = 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProcessedFrame):
            return NotImplemented
        return (
            np.array_equal(self.image, other.image)
            and self.sensor_id == other.sensor_id
            and self.sequence_number == other.sequence_number
        )

    def __hash__(self) -> int:
        return hash((self.sensor_id, self.sequence_number, self.timestamp))

    @property
    def is_usable(self) -> bool:
        """Frame has sufficient quality for at least some analysis."""
        return self.quality.overall > 0.15

    @property
    def is_good(self) -> bool:
        """Frame has good quality for most analysis modules."""
        return self.quality.overall > 0.5

    @property
    def has_severe_degradation(self) -> bool:
        """At least one severe degradation detected."""
        from agent_core.vision.preprocessing.degradation import DegradationSeverity
        return any(d.severity == DegradationSeverity.SEVERE for d in self.degradations)

    @property
    def degradation_types(self) -> List[DegradationType]:
        """List of degradation types detected."""
        return [d.type for d in self.degradations]

    def to_dict(self) -> dict:
        return {
            "quality": self.quality.to_dict(),
            "degradations": [d.to_dict() for d in self.degradations],
            "processing_time_ms": round(self.processing_time_ms, 2),
            "original_resolution": list(self.original_resolution),
            "is_usable": self.is_usable,
            "is_good": self.is_good,
            "sensor_id": self.sensor_id,
            "sequence_number": self.sequence_number,
        }


class VisionPreprocessor:
    """Main preprocessing pipeline.

    Pipeline:
    1. Normalize frame (resolution, format)
    2. Assess quality (6 metrics)
    3. Detect degradations (12+ types)
    4. Return ProcessedFrame

    Keeps track of previous frame for frozen detection.

    Usage:
        preprocessor = VisionPreprocessor()
        processed = preprocessor.process(frame)
        if processed.is_usable:
            # pass to vision modules
    """

    def __init__(
        self,
        target_resolution: Optional[Tuple[int, int]] = None,
        auto_white_balance: bool = False,
        auto_exposure: bool = False,
    ):
        self._target_resolution = target_resolution
        self._auto_white_balance = auto_white_balance
        self._auto_exposure = auto_exposure
        self._previous_image: Optional[np.ndarray] = None

    def process(self, frame: Frame) -> ProcessedFrame:
        """Process a raw frame through the full pipeline.

        Args:
            frame: Raw frame from a sensor

        Returns:
            ProcessedFrame with quality metrics and degradations.
        """
        t0 = time.monotonic()

        if not frame.is_valid:
            return ProcessedFrame(
                image=np.array([], dtype=np.uint8),
                quality=QualityAssessment(
                    sharpness=0.0, brightness=0.0, contrast=0.0,
                    noise_level=0.0, color_balance=0.0, motion_blur=0.0,
                ),
                processing_time_ms=0.0,
                original_resolution=frame.resolution,
                timestamp=frame.timestamp,
                sensor_id=frame.sensor_id,
                sequence_number=frame.sequence_number,
            )

        # 1. Normalize
        normalized = normalize_frame(
            frame.image,
            target_resolution=self._target_resolution,
            auto_white_balance=self._auto_white_balance,
            auto_exposure=self._auto_exposure,
        )

        # 2. Assess quality
        quality = assess_quality(normalized)

        # 3. Detect degradations
        degradations = detect_degradations(
            normalized,
            quality,
            previous_image=self._previous_image,
        )

        # Store for frozen detection
        self._previous_image = normalized.copy()

        elapsed_ms = (time.monotonic() - t0) * 1000.0

        return ProcessedFrame(
            image=normalized,
            quality=quality,
            degradations=tuple(degradations),
            processing_time_ms=elapsed_ms,
            original_resolution=frame.resolution,
            timestamp=frame.timestamp,
            sensor_id=frame.sensor_id,
            sequence_number=frame.sequence_number,
        )

    def reset(self) -> None:
        """Reset internal state (previous frame)."""
        self._previous_image = None
