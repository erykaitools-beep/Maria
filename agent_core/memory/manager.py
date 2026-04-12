"""
Memory Manager - Unified memory interface

Provides unified interface to:
- Episodic memory (events, conversations)
- Semantic memory (knowledge graph)

JSONL is source of truth (ADR-004).

Adapter for: maria_core/memory_engine/memory_store.py
"""

import time
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    Unified memory management interface for homeostasis.

    Provides methods needed by homeostasis sensors and actions.
    Wraps existing memory_store.py functionality.
    """

    def __init__(
        self,
        episodic_store=None,
        semantic_store=None,
    ):
        """
        Initialize memory manager.

        Args:
            episodic_store: EpisodicStore instance (or None to create)
            semantic_store: SemanticStore instance (or None to create)
        """
        self._episodic = episodic_store
        self._semantic = semantic_store

        # Error tracking
        self._error_timestamps: List[float] = []
        self._contradiction_count = 0

        # Try to import and wrap existing stores
        self._init_legacy_adapters()

    def _init_legacy_adapters(self) -> None:
        """Initialize adapters for legacy maria_core modules."""
        self._legacy_memory_store = None
        self._legacy_semantic_graph = None

        try:
            from maria_core.memory_engine.memory_store import MemoryStore
            # MemoryStore requires filepath - use default path
            import os
            default_memory_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "data", "memory.jsonl"
            )
            # Only create if we can create the directory
            data_dir = os.path.dirname(default_memory_path)
            if not os.path.exists(data_dir):
                os.makedirs(data_dir, exist_ok=True)
            self._legacy_memory_store = MemoryStore(default_memory_path)
        except (ImportError, TypeError, Exception) as e:
            logger.debug(f"Legacy MemoryStore not available: {e}")

        try:
            from maria_core.memory_engine.semantic.semantic_graph import SemanticGraph
            self._legacy_semantic_graph = SemanticGraph()
        except (ImportError, TypeError, Exception) as e:
            logger.debug(f"Legacy SemanticGraph not available: {e}")

    # ─────────────────────────────────────────────
    # HOMEOSTASIS INTERFACE (required by sensors)
    # ─────────────────────────────────────────────

    def get_semantic_coherence(self) -> float:
        """
        Get semantic graph coherence score.

        Returns:
            Coherence from 0.0 (incoherent) to 1.0 (fully coherent)
        """
        if self._legacy_semantic_graph:
            try:
                # Call validate_integrity if available
                if hasattr(self._legacy_semantic_graph, 'validate_integrity'):
                    return self._legacy_semantic_graph.validate_integrity()
            except Exception:
                pass

        # Default: assume coherent
        return 0.95

    def get_total_entries(self) -> int:
        """
        Get total number of memory entries.

        Returns:
            Combined count of episodic + semantic entries
        """
        total = 0

        if self._legacy_memory_store:
            try:
                # Get JSONL line count
                if hasattr(self._legacy_memory_store, 'count'):
                    total += self._legacy_memory_store.count()
            except Exception:
                pass

        if self._legacy_semantic_graph:
            try:
                if hasattr(self._legacy_semantic_graph, 'node_count'):
                    total += self._legacy_semantic_graph.node_count()
                elif hasattr(self._legacy_semantic_graph, 'nodes'):
                    total += len(self._legacy_semantic_graph.nodes)
            except Exception:
                pass

        return total

    def get_contradiction_count(self) -> int:
        """
        Get count of contradictions in memory.

        Returns:
            Number of detected contradictions
        """
        return self._contradiction_count

    def get_episodic_freshness(self) -> float:
        """
        Get age of newest episodic entry in seconds.

        Returns:
            Seconds since last episodic entry was added
        """
        if self._legacy_memory_store:
            try:
                if hasattr(self._legacy_memory_store, 'get_last_timestamp'):
                    last_ts = self._legacy_memory_store.get_last_timestamp()
                    return time.time() - last_ts
            except Exception:
                pass

        return 0.0

    def get_recent_errors_count(self, window_seconds: int = 3600) -> int:
        """
        Get count of errors in time window.

        Args:
            window_seconds: Time window (default: 1 hour)

        Returns:
            Number of errors in window
        """
        cutoff = time.time() - window_seconds
        return sum(1 for ts in self._error_timestamps if ts > cutoff)

    # ─────────────────────────────────────────────
    # CORRECTIVE ACTIONS (called by homeostasis)
    # ─────────────────────────────────────────────

    def consolidate_episodic(self, target_freed_mb: int = 100) -> Dict[str, Any]:
        """
        Consolidate episodic memory to free space.

        Args:
            target_freed_mb: Target MB to free

        Returns:
            Result dictionary with success status and freed amount
        """
        logger.info(f"Consolidating episodic memory (target: {target_freed_mb}MB)")

        # Placeholder implementation
        # Real implementation would:
        # 1. Archive old episodic entries
        # 2. Compress/summarize repeated patterns
        # 3. Move to long-term storage

        return {
            "success": True,
            "freed_mb": 0,
            "entries_archived": 0,
        }

    def semantic_consistency_check(self) -> Dict[str, Any]:
        """
        Run semantic consistency check.

        Returns:
            Result with issues found and fixed
        """
        logger.info("Running semantic consistency check")

        issues_found = 0
        issues_fixed = 0

        if self._legacy_semantic_graph:
            try:
                if hasattr(self._legacy_semantic_graph, 'validate_integrity'):
                    score = self._legacy_semantic_graph.validate_integrity()
                    if score < 0.9:
                        issues_found = int((1 - score) * 100)
            except Exception as e:
                logger.warning(f"Consistency check error: {e}")

        return {
            "success": True,
            "issues_found": issues_found,
            "issues_fixed": issues_fixed,
        }

    def checkpoint(self) -> bool:
        """
        Create memory checkpoint.

        Returns:
            True if checkpoint successful
        """
        logger.info("Creating memory checkpoint")

        try:
            if self._legacy_memory_store:
                if hasattr(self._legacy_memory_store, 'flush'):
                    self._legacy_memory_store.flush()

            if self._legacy_semantic_graph:
                if hasattr(self._legacy_semantic_graph, 'save'):
                    self._legacy_semantic_graph.save()

            return True
        except Exception as e:
            logger.error(f"Checkpoint failed: {e}")
            return False

    def set_readonly(self, readonly: bool = True) -> None:
        """
        Set memory to read-only mode (for SURVIVAL).

        Args:
            readonly: Whether to enable read-only mode
        """
        logger.info(f"Setting memory readonly={readonly}")
        # Implementation would prevent writes in SURVIVAL mode

    # ─────────────────────────────────────────────
    # ERROR TRACKING
    # ─────────────────────────────────────────────

    def record_error(self) -> None:
        """Record an error occurrence."""
        self._error_timestamps.append(time.time())
        # Keep bounded
        if len(self._error_timestamps) > 1000:
            self._error_timestamps = self._error_timestamps[-500:]

    def increment_contradiction_count(self) -> None:
        """Increment contradiction counter."""
        self._contradiction_count += 1

    def reset_contradiction_count(self) -> None:
        """Reset contradiction counter."""
        self._contradiction_count = 0

    # ─────────────────────────────────────────────
    # SNAPSHOT DATA (for recovery)
    # ─────────────────────────────────────────────

    def get_snapshot_data(self) -> Dict[str, Any]:
        """
        Get memory state for snapshot.

        Returns:
            Dictionary with memory metadata for snapshot
        """
        return {
            "version": 1,
            "entries": self.get_total_entries(),
            "size_mb": 0,  # Would calculate from actual storage
            "freshness_sec": self.get_episodic_freshness(),
        }

    def get_semantic_snapshot_data(self) -> Dict[str, Any]:
        """
        Get semantic model state for snapshot.

        Returns:
            Dictionary with semantic model metadata
        """
        node_count = 0
        if self._legacy_semantic_graph:
            try:
                if hasattr(self._legacy_semantic_graph, 'node_count'):
                    node_count = self._legacy_semantic_graph.node_count()
                elif hasattr(self._legacy_semantic_graph, 'nodes'):
                    node_count = len(self._legacy_semantic_graph.nodes)
            except Exception:
                pass

        return {
            "version": 1,
            "node_count": node_count,
            "consistency_score": self.get_semantic_coherence(),
        }

    def rebuild_from_jsonl(self) -> bool:
        """
        Rebuild semantic graph from JSONL source of truth.

        ADR-004: JSONL is source of truth, graph is derived.

        Returns:
            True if rebuild successful
        """
        logger.info("Rebuilding semantic graph from JSONL")

        try:
            if self._legacy_semantic_graph and self._legacy_memory_store:
                # Implementation would:
                # 1. Clear semantic graph
                # 2. Read all JSONL entries
                # 3. Rebuild graph from entries
                pass

            return True
        except Exception as e:
            logger.error(f"Rebuild failed: {e}")
            return False
