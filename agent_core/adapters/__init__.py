"""
Adapters - Bridge between agent_core and legacy maria_core

Provides adapter classes that wrap existing maria_core functionality
to conform to the new agent_core interfaces.

This allows gradual migration without breaking existing code.
"""

from .resource_adapter import ResourceWatchdogAdapter
from .memory_adapter import MemoryStoreAdapter
from .brain_adapter import BrainMemoryAdapter
from .semantic_adapter import SemanticGraphAdapter

__all__ = [
    "ResourceWatchdogAdapter",
    "MemoryStoreAdapter",
    "BrainMemoryAdapter",
    "SemanticGraphAdapter",
]

