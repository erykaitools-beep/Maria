"""
Vision preprocessing - image quality assessment and degradation detection.

Maria knows WHAT is wrong with her vision, not just THAT something is wrong.

Modules:
    quality      - QualityAssessment (6 metrics)
    degradation  - DegradationDetector (12+ types) + RecoveryAction
    normalizer   - Frame normalization (resolution, format, corrections)
    preprocessor - VisionPreprocessor pipeline
"""

from agent_core.vision.preprocessing.preprocessor import (
    ProcessedFrame,
    VisionPreprocessor,
)
from agent_core.vision.preprocessing.quality import (
    QualityAssessment,
    assess_quality,
)
from agent_core.vision.preprocessing.degradation import (
    Degradation,
    DegradationSeverity,
    RecoveryAction,
    detect_degradations,
)

__all__ = [
    "ProcessedFrame",
    "VisionPreprocessor",
    "QualityAssessment",
    "assess_quality",
    "Degradation",
    "DegradationSeverity",
    "RecoveryAction",
    "detect_degradations",
]
