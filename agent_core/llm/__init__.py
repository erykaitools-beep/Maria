"""
LLM Module - Language model interface

Components:
- manager.py: LLMManager interface for homeostasis
- latency_probe.py: Quick latency measurement
- nim_client.py: NVIDIA NIM API client
- token_budget.py: Token budget management
- router.py: LLM routing (NIM vs Ollama)

Adapter for: models/ollama_brain.py
"""

from .manager import LLMManager
from .latency_probe import LatencyProbe
from .nim_client import NIMClient, NIMAPIError
from .token_budget import TokenBudget
from .router import LLMRouter

__all__ = [
    "LLMManager",
    "LatencyProbe",
    "NIMClient",
    "NIMAPIError",
    "TokenBudget",
    "LLMRouter",
]
