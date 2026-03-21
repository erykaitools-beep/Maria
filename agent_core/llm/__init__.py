"""
LLM Module - Language model interface

Components:
- manager.py: LLMManager interface for homeostasis
- latency_probe.py: Quick latency measurement
- nim_client.py: NVIDIA NIM API client
- token_budget.py: Token budget management
- router.py: LLM routing (NIM vs Ollama, multi-organ)
- model_registry.py: Static model configuration (MODEL_REGISTRY.md -> code)
- model_scheduler.py: Model lifecycle management (load/unload, RAM guard, mutex)
- routing_rules.py: Task-to-role mapping (rule-based)

Adapter for: models/ollama_brain.py
"""

from .manager import LLMManager
from .latency_probe import LatencyProbe
from .nim_client import NIMClient, NIMAPIError
from .token_budget import TokenBudget
from .router import LLMRouter
from .model_registry import ModelRole, ModelSpec, ConcurrencyClass, WarmState
from .model_scheduler import ModelScheduler, EnsureResult
from .routing_rules import TaskType, route_task, heuristic_classify

__all__ = [
    "LLMManager",
    "LatencyProbe",
    "NIMClient",
    "NIMAPIError",
    "TokenBudget",
    "LLMRouter",
    "ModelRole",
    "ModelSpec",
    "ConcurrencyClass",
    "WarmState",
    "ModelScheduler",
    "EnsureResult",
    "TaskType",
    "route_task",
    "heuristic_classify",
]
