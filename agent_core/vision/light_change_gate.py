"""Spatial frame comparison using OpenCV, with no model or subprocess.

This filters repeated *images* before a description/notification. It does not
identify people, objects or meaning: continuous YOLO detection does that.
Global exposure changes are normalized, but shadows, camera movement and tiny
changes remain limitations. Thresholds need room-specific observation.
"""

import logging
import math
import os
import threading
import time
from typing import Optional

import numpy as np

from agent_core.vision.change_gate import GateDecision

logger = logging.getLogger(__name__)


def _fraction(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
    except (ValueError, TypeError):
        return default
    return value if math.isfinite(value) and 0.0 < value < 1.0 else default


class OpenCVSceneChangeGate:
    """Compare a small exposure-normalized spatial image to the accepted one.

    Only accepted changes move the reference, preventing slow cumulative drift
    from disappearing. Measurement failures allow description; thermal cooling
    refuses work and must never be reported as an unchanged image.
    """

    def __init__(self, coordinator=None):
        self._coordinator = coordinator
        self._reference: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._pixel_delta = _fraction("VISION_CHANGE_PIXEL_DELTA", 0.15)
        self._min_area = _fraction("VISION_CHANGE_MIN_AREA", 0.02)

    @property
    def has_reference(self) -> bool:
        return self._reference is not None

    def _cooling(self) -> bool:
        if self._coordinator is None:
            from agent_core.llm.local_compute import get_local_compute_coordinator
            self._coordinator = get_local_compute_coordinator()
        return self._coordinator.cooling

    def evaluate(self, image_path: str, *, remember: bool = True) -> GateDecision:
        started = time.monotonic()

        def result(is_new, similarity, reason):
            return GateDecision(is_new, similarity,
                                time.monotonic() - started, reason)

        with self._lock:
            if self._cooling():
                return result(False, None, "chlodzenie")
            try:
                import cv2

                image = cv2.imread(image_path, cv2.IMREAD_COLOR)
                if image is None or not image.size:
                    return result(True, None, "blad_pomiaru")
                small = cv2.resize(image, (96, 72), interpolation=cv2.INTER_AREA)
                small = small.astype(np.float32)
                brightness = float(small.mean())
                # A nearly black frame cannot support a reliable comparison.
                if brightness < 1.0:
                    return result(True, None, "blad_pomiaru")
                signature = small / brightness
            except Exception as exc:
                logger.warning("[ChangeGate/OpenCV] image comparison failed: %s", exc)
                return result(True, None, "blad_pomiaru")

            if self._cooling():
                return result(False, None, "chlodzenie")
            if self._reference is None:
                if remember:
                    self._reference = signature
                return result(True, None, "brak_odniesienia")

            # Spatial comparison notices rearrangements which a global colour
            # histogram cannot. Similarity is an unchanged-pixel fraction, not
            # Kimi cosine similarity; its historical threshold does not apply.
            delta = np.max(np.abs(signature - self._reference), axis=2)
            changed_area = float(np.mean(delta >= self._pixel_delta))
            is_new = changed_area >= self._min_area
            if remember and is_new:
                self._reference = signature
            return result(is_new, 1.0 - changed_area,
                          "inna_scena" if is_new else "ta_sama_scena")
