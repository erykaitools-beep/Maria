"""
Memory Module - JSONL-based memory management

JSONL is the source of truth (ADR-004).
Semantic graph is a derived cache rebuilt from JSONL.

Components:
- manager.py: MemoryManager interface
- episodic_store.py: Episodic memory operations
- semantic_store.py: Semantic graph operations
- snapshot_backend.py: CoW snapshot implementation

Adapter for:
- maria_core/memory_engine/memory_store.py
- maria_core/memory_engine/semantic/semantic_graph.py
- maria_core/memory_engine/brain_memory_integration.py
"""

from .manager import MemoryManager
from .episodic_store import EpisodicStore
from .semantic_store import SemanticStore
from .query import MemoryQuery, MemoryResult, MemorySource

__all__ = [
    "MemoryManager",
    "EpisodicStore",
    "SemanticStore",
    "MemoryQuery",
    "MemoryResult",
    "MemorySource",
]
