"""
Memory Store Adapter

Bridges legacy maria_core.memory_engine.memory_store to agent_core MemoryManager.
The legacy MemoryStore handles JSONL files directly.
This adapter wraps it for homeostasis integration.

Legacy: maria_core/memory_engine/memory_store.py
"""

import logging
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class MemoryStoreAdapter:
    """
    Adapter that wraps legacy MemoryStore for homeostasis integration.

    The legacy MemoryStore:
    - Reads/writes JSONL files
    - Cross-platform file locking
    - Basic append/load/save operations

    This adapter:
    - Provides stats for CognitiveSensor
    - Tracks error counts
    - Supports coherence estimation
    - Integrates with episodic/semantic split
    """

    def __init__(
        self,
        memory_dir: Optional[Path] = None,
        use_legacy: bool = True,
    ):
        """
        Initialize adapter.

        Args:
            memory_dir: Directory for memory files
            use_legacy: If True, wrap legacy MemoryStore; if False, use new implementation
        """
        self._memory_dir = memory_dir
        self._use_legacy = use_legacy
        self._legacy_store = None
        self._error_count_1h: List[float] = []  # Timestamps of errors in last hour
        self._operation_count = 0
        self._success_count = 0

        if use_legacy:
            self._init_legacy()

    def _init_legacy(self) -> None:
        """Initialize legacy MemoryStore."""
        try:
            from maria_core.memory_engine.memory_store import MemoryStore, MEMORY_INDEX_PATH

            if self._memory_dir:
                filepath = self._memory_dir / "memory_index.json"
            else:
                filepath = MEMORY_INDEX_PATH

            self._legacy_store = MemoryStore(filepath)
            logger.info(f"[Adapter] Legacy MemoryStore initialized: {filepath}")

        except ImportError as e:
            logger.warning(f"[Adapter] Legacy MemoryStore not available: {e}")
            self._use_legacy = False

    def get_stats(self) -> Dict[str, Any]:
        """
        Get memory statistics for CognitiveSensor.

        Returns:
            Dictionary with coherence, error counts, totals
        """
        # Clean old error timestamps (keep only last hour)
        cutoff = time.time() - 3600
        self._error_count_1h = [t for t in self._error_count_1h if t > cutoff]

        # Calculate coherence estimate
        # Based on success rate of recent operations
        if self._operation_count > 0:
            coherence = self._success_count / self._operation_count
        else:
            coherence = 1.0  # No operations = assume coherent

        # Get total memories
        total = self.count()

        return {
            "coherence_score": coherence,
            "error_count_1h": len(self._error_count_1h),
            "total_memories": total,
            "operation_count": self._operation_count,
            "success_rate": coherence,
        }

    def append(self, record: Dict[str, Any]) -> bool:
        """
        Append record to memory.

        Args:
            record: Record to append

        Returns:
            True if successful
        """
        self._operation_count += 1

        try:
            if self._use_legacy and self._legacy_store:
                result = self._legacy_store.append(record)
            else:
                # Fallback: simple file append
                result = self._append_simple(record)

            if result:
                self._success_count += 1
            else:
                self._error_count_1h.append(time.time())

            return result

        except Exception as e:
            logger.error(f"[Adapter] Append error: {e}")
            self._error_count_1h.append(time.time())
            return False

    def _append_simple(self, record: Dict[str, Any]) -> bool:
        """Simple append without legacy store."""
        import json

        if not self._memory_dir:
            return False

        filepath = self._memory_dir / "memory_index.json"
        filepath.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
            return True
        except Exception as e:
            logger.error(f"[Adapter] Simple append error: {e}")
            return False

    def load_all(self) -> List[Dict[str, Any]]:
        """
        Load all records.

        Returns:
            List of all memory records
        """
        self._operation_count += 1

        try:
            if self._use_legacy and self._legacy_store:
                records = self._legacy_store.load_all()
            else:
                records = self._load_simple()

            self._success_count += 1
            return records

        except Exception as e:
            logger.error(f"[Adapter] Load error: {e}")
            self._error_count_1h.append(time.time())
            return []

    def _load_simple(self) -> List[Dict[str, Any]]:
        """Simple load without legacy store."""
        import json

        if not self._memory_dir:
            return []

        filepath = self._memory_dir / "memory_index.json"
        if not filepath.exists():
            return []

        records = []
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        return records

    def count(self) -> int:
        """
        Get total memory count.

        Returns:
            Number of records
        """
        if self._use_legacy and self._legacy_store:
            return self._legacy_store.count()
        else:
            return len(self._load_simple())

    def flush(self) -> bool:
        """
        Flush any pending writes.

        For JSONL, writes are immediate, so this is a no-op.
        Included for interface compatibility.

        Returns:
            True (always succeeds for JSONL)
        """
        logger.debug("[Adapter] Flush called (no-op for JSONL)")
        return True

    def get_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get most recent records.

        Args:
            limit: Maximum records to return

        Returns:
            List of recent records (newest first)
        """
        records = self.load_all()
        return records[-limit:][::-1]  # Last N, reversed

    def find(self, filter_func) -> List[Dict[str, Any]]:
        """
        Find records matching filter.

        Args:
            filter_func: Function that takes record and returns bool

        Returns:
            Matching records
        """
        if self._use_legacy and self._legacy_store:
            return self._legacy_store.find(filter_func)
        else:
            records = self._load_simple()
            return [r for r in records if filter_func(r)]


def get_adapted_memory_store(memory_dir: Optional[Path] = None) -> MemoryStoreAdapter:
    """
    Get adapted memory store instance.

    This is a drop-in replacement for the legacy global memory_store.

    Args:
        memory_dir: Optional custom directory

    Returns:
        MemoryStoreAdapter instance
    """
    return MemoryStoreAdapter(memory_dir=memory_dir)

