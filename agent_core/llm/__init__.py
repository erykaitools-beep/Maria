"""
LLM Module - Language model interface

Components:
- manager.py: LLMManager interface for homeostasis
- latency_probe.py: Quick latency measurement

Adapter for: models/ollama_brain.py
"""

from .manager import LLMManager
from .latency_probe import LatencyProbe

__all__ = [
    "LLMManager",
    "LatencyProbe",
]
