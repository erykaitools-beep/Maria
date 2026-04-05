"""
SceneModule - scene description via LLaVA or basic statistics.

Primary backend: LLaVA (multimodal LLM) via Ollama /api/generate.
Fallback: basic image statistics (brightness, dominant color, complexity).

Maria uses this to describe what she sees in natural language:
"Widze jasny pokoj z biurkiem i monitorem."

Phase 3: Vision Modules (VISION_SPEC.md)
"""

import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore[assignment]

from agent_core.vision.modules.base import ModuleOutput
from agent_core.vision.preprocessing.preprocessor import ProcessedFrame

logger = logging.getLogger(__name__)

# LLaVA prompt for scene description
_SCENE_PROMPT = (
    "Describe what you see in this image in 1-2 sentences. "
    "Focus on: the type of room or space, main objects, "
    "people if present, lighting conditions. Be concise."
)

_SCENE_PROMPT_PL = (
    "Opisz co widzisz na tym obrazie w 1-2 zdaniach po polsku. "
    "Skup sie na: typ pomieszczenia, glowne przedmioty, "
    "osoby jesli sa, warunki oswietlenia. Badz zwiezly."
)


@dataclass
class SceneOutput(ModuleOutput):
    """Output from scene analysis module."""

    description: str = ""           # Natural language description
    lighting: str = "unknown"       # bright, dim, dark, mixed
    dominant_colors: List[str] = field(default_factory=list)
    complexity: float = 0.0         # 0-1, how complex the scene is
    backend_used: str = "none"      # llava, statistics

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "description": self.description,
            "lighting": self.lighting,
            "dominant_colors": self.dominant_colors,
            "complexity": round(self.complexity, 3),
            "backend_used": self.backend_used,
        })
        return d


# LLaVA function type: (prompt, base64_image) -> str
LLaVAFunction = Callable[[str, str], Optional[str]]


class SceneModule:
    """Scene analysis - describes what Maria sees.

    Implements VisionModule protocol. Uses LLaVA when available,
    falls back to basic image statistics.

    Usage:
        module = SceneModule()
        # Or with LLaVA:
        module = SceneModule(llava_fn=my_llava_function)
        output = module.analyze(processed_frame)
        print(output.description)
    """

    def __init__(
        self,
        llava_fn: Optional[LLaVAFunction] = None,
        use_polish: bool = True,
    ):
        self._llava_fn = llava_fn
        self._prompt = _SCENE_PROMPT_PL if use_polish else _SCENE_PROMPT

    @property
    def module_name(self) -> str:
        return "scene"

    @property
    def required_quality(self) -> float:
        return 0.3  # Can work with fairly poor quality

    @property
    def can_work_degraded(self) -> bool:
        return True

    def set_llava_fn(self, fn: LLaVAFunction) -> None:
        """Set LLaVA function for scene description."""
        self._llava_fn = fn

    def analyze(self, frame: ProcessedFrame) -> Optional[SceneOutput]:
        """Analyze a frame and describe the scene."""
        if frame.image is None or frame.image.size == 0:
            return None

        t0 = time.monotonic()
        is_degraded = frame.quality.overall < 0.5

        # Always compute basic statistics
        lighting = _detect_lighting(frame.image)
        dominant_colors = _detect_dominant_colors(frame.image)
        complexity = _estimate_complexity(frame.image)

        # Try LLaVA for natural language description
        description = ""
        backend = "statistics"

        if self._llava_fn is not None and frame.quality.overall >= 0.3:
            try:
                b64 = _image_to_base64(frame.image)
                llava_result = self._llava_fn(self._prompt, b64)
                if llava_result:
                    description = llava_result.strip()
                    backend = "llava"
            except Exception:
                logger.warning("LLaVA scene analysis failed, using statistics")

        # Fallback description from statistics
        if not description:
            description = _generate_stats_description(lighting, dominant_colors, complexity)

        elapsed = (time.monotonic() - t0) * 1000.0

        return SceneOutput(
            module_name=self.module_name,
            confidence=0.8 if backend == "llava" else 0.3,
            is_degraded=is_degraded,
            processing_time_ms=elapsed,
            description=description,
            lighting=lighting,
            dominant_colors=dominant_colors,
            complexity=complexity,
            backend_used=backend,
        )


def _detect_lighting(image: np.ndarray) -> str:
    """Detect lighting conditions from image brightness."""
    if image.ndim == 3:
        if cv2 is not None:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = np.mean(image, axis=2).astype(np.uint8)
    else:
        gray = image

    mean_lum = float(np.mean(gray))

    if mean_lum < 40:
        return "dark"
    elif mean_lum < 100:
        return "dim"
    elif mean_lum < 200:
        return "bright"
    else:
        return "very_bright"


def _detect_dominant_colors(image: np.ndarray, top_n: int = 3) -> List[str]:
    """Detect dominant colors using simple histogram analysis."""
    if image.ndim != 3 or image.shape[2] != 3:
        return ["gray"]

    if cv2 is None:
        return ["unknown"]

    # Convert to HSV for better color detection
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    h = hsv[:, :, 0]  # Hue channel (0-179 in OpenCV)
    s = hsv[:, :, 1]  # Saturation
    v = hsv[:, :, 2]  # Value

    # Mask out very dark and very desaturated pixels
    mask = (v > 30) & (s > 30)

    colors = []

    if np.sum(mask) < image.shape[0] * image.shape[1] * 0.1:
        # Mostly dark or desaturated
        mean_v = float(np.mean(v))
        if mean_v < 50:
            return ["black"]
        elif mean_v > 200:
            return ["white"]
        else:
            return ["gray"]

    # Analyze hue histogram of valid pixels
    hue_vals = h[mask]
    hist, _ = np.histogram(hue_vals, bins=12, range=(0, 180))

    # Map bins to color names
    color_names = [
        "red", "orange", "yellow", "yellow-green",
        "green", "cyan-green", "cyan", "blue-cyan",
        "blue", "purple", "magenta", "red-magenta",
    ]

    # Get top colors by frequency
    sorted_indices = np.argsort(hist)[::-1]
    for idx in sorted_indices[:top_n]:
        if hist[idx] > 0:
            colors.append(color_names[idx])

    return colors if colors else ["gray"]


def _estimate_complexity(image: np.ndarray) -> float:
    """Estimate scene complexity from edge density.

    More edges = more complex scene (more objects, details).
    """
    if cv2 is None:
        return 0.5

    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(np.sum(edges > 0)) / edges.size
    return min(1.0, edge_density * 10.0)  # Scale so 10% edges = max complexity


def _image_to_base64(image: np.ndarray) -> str:
    """Encode image as base64 JPEG for LLaVA."""
    if cv2 is None:
        return ""
    _, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buffer).decode("utf-8")


def _generate_stats_description(
    lighting: str, colors: List[str], complexity: float,
) -> str:
    """Generate a simple description from statistics (Polish)."""
    parts = []

    # Lighting
    lighting_pl = {
        "dark": "Jest ciemno",
        "dim": "Jest slabo oswietlone",
        "bright": "Jest jasno",
        "very_bright": "Jest bardzo jasno",
    }
    parts.append(lighting_pl.get(lighting, "Widze cos"))

    # Complexity
    if complexity > 0.5:
        parts.append("i widze wiele szczegulow")
    elif complexity > 0.2:
        parts.append("i widze kilka obiektow")
    else:
        parts.append("i scena jest prosta")

    # Colors
    color_pl = {
        "red": "czerwieni", "orange": "pomaranczu", "yellow": "zolci",
        "green": "zieleni", "cyan": "turkusu", "blue": "blekit",
        "purple": "fioletu", "magenta": "rozu",
        "black": "ciemnosci", "white": "bieli", "gray": "szarosci",
    }
    if colors:
        main = colors[0]
        color_name = color_pl.get(main, main)
        parts.append(f"z przewaga {color_name}")

    return ", ".join(parts) + "."
