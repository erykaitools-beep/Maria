"""
VisionModule protocol - base interface for all analysis modules.

Each module (Motion, Scene, OCR, Face) implements this protocol.
Modules declare their quality requirements and can operate in
degraded mode when image quality is insufficient.

Phase 3: Vision Modules (VISION_SPEC.md)
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from typing import Protocol, runtime_checkable
except ImportError:
    from typing_extensions import Protocol, runtime_checkable

from agent_core.vision.preprocessing.preprocessor import ProcessedFrame


@dataclass
class ModuleOutput:
    """Base output from a vision module.

    Each module subclasses this with specific fields.
    Common fields track confidence and processing metadata.
    """

    module_name: str
    timestamp: float = field(default_factory=time.time)
    confidence: float = 0.0
    is_degraded: bool = False
    processing_time_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "module_name": self.module_name,
            "confidence": round(self.confidence, 3),
            "is_degraded": self.is_degraded,
            "processing_time_ms": round(self.processing_time_ms, 2),
            "details": self.details,
        }


@runtime_checkable
class VisionModule(Protocol):
    """Abstract interface for vision analysis modules.

    Each module declares:
    - module_name: unique identifier
    - required_quality: minimum image quality to operate (0.0-1.0)
    - can_work_degraded: whether it can produce partial results

    The VisionCortex uses these to decide which modules to run.
    """

    @property
    def module_name(self) -> str:
        """Unique module identifier (e.g. 'motion', 'scene', 'face')."""
        ...

    @property
    def required_quality(self) -> float:
        """Minimum image quality needed for full analysis (0.0-1.0)."""
        ...

    @property
    def can_work_degraded(self) -> bool:
        """Whether this module can produce partial results with low quality."""
        ...

    def analyze(self, frame: ProcessedFrame) -> Optional[ModuleOutput]:
        """Analyze a preprocessed frame.

        Returns None if quality is too low and module can't work degraded.
        Returns ModuleOutput (possibly with is_degraded=True) otherwise.
        """
        ...
