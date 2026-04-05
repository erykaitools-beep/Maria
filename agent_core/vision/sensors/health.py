"""
SensorHealth - graceful degradation for vision sensors.

Instead of binary "works / doesn't work", the sensor reports a spectrum
of health states. Maria says "widze slabo" instead of "kamera nie dziala".

7 degradation levels from FULL_VISION (100%) down to BLIND (0%).

Phase 1: Sensor Abstraction Layer (VISION_SPEC.md)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Tuple

from agent_core.vision.models import SensorIssue


class DegradationLevel(Enum):
    """Vision degradation levels - biological inspiration.

    FULL_VISION  (100%) -> everything works perfectly
    GRAYSCALE    ( 80%) -> color issues but still functional
    LOW_RES      ( 60%) -> resolution reduced
    BLUR         ( 40%) -> focus/sharpness problems
    FRAME_BY_FRAME (20%) -> intermittent capture
    LIGHT_DARK   (  5%) -> can only detect light vs darkness
    BLIND        (  0%) -> no vision at all
    """
    FULL_VISION = "full_vision"
    GRAYSCALE = "grayscale"
    LOW_RES = "low_res"
    BLUR = "blur"
    FRAME_BY_FRAME = "frame_by_frame"
    LIGHT_DARK = "light_dark"
    BLIND = "blind"


# Maps overall health score ranges to degradation levels
_LEVEL_THRESHOLDS: List[Tuple[float, DegradationLevel]] = [
    (0.85, DegradationLevel.FULL_VISION),
    (0.65, DegradationLevel.GRAYSCALE),
    (0.45, DegradationLevel.LOW_RES),
    (0.25, DegradationLevel.BLUR),
    (0.10, DegradationLevel.FRAME_BY_FRAME),
    (0.01, DegradationLevel.LIGHT_DARK),
    (0.00, DegradationLevel.BLIND),
]

# Human descriptions for Maria's self-reports (Polish)
_HUMAN_DESCRIPTIONS = {
    DegradationLevel.FULL_VISION: "Widze wyraznie i ostro.",
    DegradationLevel.GRAYSCALE: "Widze, ale mam problemy z kolorami.",
    DegradationLevel.LOW_RES: "Widze, ale obraz jest nieostry i maly.",
    DegradationLevel.BLUR: "Widze bardzo slabo, obraz jest rozmyty.",
    DegradationLevel.FRAME_BY_FRAME: "Widze urywkowo, tylko pojedyncze klatki.",
    DegradationLevel.LIGHT_DARK: "Ledwo rozpoznaje swiatlo od ciemnosci.",
    DegradationLevel.BLIND: "Nie widze nic - moje oko nie dziala.",
}


def classify_degradation_level(overall_health: float) -> DegradationLevel:
    """Map overall health score (0.0-1.0) to a degradation level."""
    clamped = max(0.0, min(1.0, overall_health))
    for threshold, level in _LEVEL_THRESHOLDS:
        if clamped >= threshold:
            return level
    return DegradationLevel.BLIND


@dataclass
class SensorHealth:
    """Health state of a vision sensor - key to graceful degradation.

    Each component is a 0.0-1.0 score (0 = broken, 1 = perfect).
    The overall score is derived from individual components.
    """

    # Individual component health (0.0-1.0 each)
    connection: float = 1.0
    stream: float = 1.0
    resolution: float = 1.0
    color: float = 1.0
    focus: float = 1.0
    exposure: float = 1.0
    noise: float = 1.0  # 1 = no noise, 0 = all noise
    latency_ms: float = 0.0

    # Active issues
    issues: List[SensorIssue] = field(default_factory=list)

    # Component weights for overall score
    _WEIGHTS = {
        "connection": 0.25,
        "stream": 0.20,
        "resolution": 0.10,
        "color": 0.05,
        "focus": 0.15,
        "exposure": 0.10,
        "noise": 0.10,
        "latency": 0.05,
    }

    @property
    def overall(self) -> float:
        """Weighted overall health score (0.0-1.0).

        Connection and stream are weighted highest because without them
        nothing else works. Focus is next most important.
        """
        # Connection=0 means sensor is dead
        if self.connection <= 0.0:
            return 0.0

        latency_score = max(0.0, 1.0 - (self.latency_ms / 5000.0))

        raw = (
            self._WEIGHTS["connection"] * self.connection
            + self._WEIGHTS["stream"] * self.stream
            + self._WEIGHTS["resolution"] * self.resolution
            + self._WEIGHTS["color"] * self.color
            + self._WEIGHTS["focus"] * self.focus
            + self._WEIGHTS["exposure"] * self.exposure
            + self._WEIGHTS["noise"] * self.noise
            + self._WEIGHTS["latency"] * latency_score
        )
        return max(0.0, min(1.0, raw))

    @property
    def degradation_level(self) -> DegradationLevel:
        """Current degradation level based on overall health."""
        return classify_degradation_level(self.overall)

    def to_human_description(self) -> str:
        """How Maria describes her current vision state (Polish)."""
        level = self.degradation_level
        base = _HUMAN_DESCRIPTIONS.get(level, "Stan wzroku nieznany.")

        # Add specific issue hints for actionable problems
        hints = []
        if SensorIssue.OVEREXPOSED in self.issues:
            hints.append("Jest za jasno.")
        if SensorIssue.UNDEREXPOSED in self.issues:
            hints.append("Jest za ciemno.")
        if SensorIssue.BLURRY in self.issues:
            hints.append("Obraz jest rozmyty.")
        if SensorIssue.NOISY in self.issues:
            hints.append("Duzo szumu w obrazie.")
        if SensorIssue.FROZEN in self.issues:
            hints.append("Obraz sie nie zmienia - chyba jest zamrozony.")
        if SensorIssue.DISCONNECTED in self.issues:
            hints.append("Nie mam polaczenia z kamera.")

        if hints:
            return base + " " + " ".join(hints)
        return base

    def to_dict(self) -> dict:
        """Serialize for JSONL / API."""
        return {
            "overall": round(self.overall, 3),
            "connection": round(self.connection, 3),
            "stream": round(self.stream, 3),
            "resolution": round(self.resolution, 3),
            "color": round(self.color, 3),
            "focus": round(self.focus, 3),
            "exposure": round(self.exposure, 3),
            "noise": round(self.noise, 3),
            "latency_ms": round(self.latency_ms, 1),
            "degradation_level": self.degradation_level.value,
            "issues": [i.value for i in self.issues],
        }

    @classmethod
    def disconnected(cls) -> "SensorHealth":
        """Factory for a completely disconnected sensor."""
        return cls(
            connection=0.0,
            stream=0.0,
            resolution=0.0,
            color=0.0,
            focus=0.0,
            exposure=0.0,
            noise=0.0,
            issues=[SensorIssue.DISCONNECTED],
        )

    @classmethod
    def perfect(cls) -> "SensorHealth":
        """Factory for a perfectly healthy sensor."""
        return cls()
