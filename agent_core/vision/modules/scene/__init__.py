"""
Scene analysis module - describes what Maria sees.

Uses LLaVA (multimodal LLM) via Ollama for natural language scene description.
Fallback: basic image statistics when LLM is unavailable.
"""

from agent_core.vision.modules.scene.analyzer import (
    SceneModule,
    SceneOutput,
)

__all__ = ["SceneModule", "SceneOutput"]
