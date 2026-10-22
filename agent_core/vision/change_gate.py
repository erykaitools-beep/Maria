"""Public scene-change gate selection, without models or external processes.

OpenCV compares spatial image changes; it does not recognize people or infer
meaning. ``observe`` measures without suppressing notifications, while ``on``
acts on the decision. Thresholds belong to ``light_change_gate`` and must be
calibrated for the actual camera and lighting. Importing this module is cheap;
OpenCV/NumPy are needed only when the optional gate is constructed/evaluated.
"""
from dataclasses import dataclass
import os
from typing import Optional

FLAG = "VISION_CHANGE_GATE"


@dataclass(frozen=True)
class GateDecision:
    """Image comparison evidence, not semantic verification of the scene."""
    is_new: bool
    similarity: Optional[float]
    seconds: float
    reason: str

    def to_dict(self) -> dict:
        return {"is_new": self.is_new, "similarity": self.similarity,
                "seconds": round(self.seconds, 2), "reason": self.reason}


def gate_mode() -> str:
    """Return off/observe/on; reject mistyped configuration explicitly."""
    value = os.environ.get(FLAG, "off").strip().lower()
    if value in ("", "0", "false", "no", "off"):
        return "off"
    if value in ("1", "true", "yes", "on"):
        return "on"
    if value == "observe":
        return "observe"
    raise ValueError("VISION_CHANGE_GATE must be off, observe or on")


def change_gate_backend() -> str:
    """The public distribution supports the lightweight OpenCV backend only."""
    value = os.environ.get("VISION_CHANGE_BACKEND", "opencv").strip().lower()
    if value != "opencv":
        raise ValueError("VISION_CHANGE_BACKEND must be opencv")
    return value


def create_change_gate():
    """Lazily construct the selected gate; never substitute a dummy gate."""
    change_gate_backend()
    from agent_core.vision.light_change_gate import OpenCVSceneChangeGate
    return OpenCVSceneChangeGate()
