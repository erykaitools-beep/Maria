"""
Episodic Store - Event and conversation memory

Handles:
- Storing episodic events (conversations, actions, outcomes)
- Freshness tracking
- Archival of old entries
- FIFO with optional cap (ADR-005 pending)

Adapter for: maria_core/memory_engine/brain_memory_integration.py
"""

import time
import logging
from typing import Dict, Any, Optional, List
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EpisodicEntry:
    """A single episodic memory entry."""
    timestamp: float
    event_type: str  # 'conversation', 'action', 'observation', etc.
    content: Dict[str, Any]
    success: bool = True
    importance: float = 0.5  # 0-1

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "content": self.content,
            "success": self.success,
            "importance": self.importance,
        }


class EpisodicStore:
    """
    Episodic memory store.

    Stores events, conversations, and outcomes.
    ADR-005 (pending): May implement cap with pruning.
    """

    # Default cap (ADR-005 proposes options)
    DEFAULT_MAX_ENTRIES = 10000

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES):
        """
        Initialize episodic store.

        Args:
            max_entries: Maximum entries to keep (FIFO)
        """
        self.max_entries = max_entries
        self._entries: deque = deque(maxlen=max_entries)
        self._last_entry_time = time.time()

        # Try to wrap legacy module
        self._init_legacy_adapter()

    def _init_legacy_adapter(self) -> None:
        """Initialize adapter for legacy brain_memory_integration."""
        try:
            from maria_core.memory_engine.brain_memory_integration import episodic_memory
            self._legacy_episodic = episodic_memory
        except ImportError:
            self._legacy_episodic = None
            logger.debug("Legacy episodic_memory not available")

    def add_entry(
        self,
        event_type: str,
        content: Dict[str, Any],
        success: bool = True,
        importance: float = 0.5,
    ) -> EpisodicEntry:
        """
        Add new episodic entry.

        Args:
            event_type: Type of event
            content: Event content/data
            success: Whether event was successful
            importance: Importance score (0-1)

        Returns:
            Created entry
        """
        entry = EpisodicEntry(
            timestamp=time.time(),
            event_type=event_type,
            content=content,
            success=success,
            importance=importance,
        )

        self._entries.append(entry)
        self._last_entry_time = entry.timestamp

        # Also add to legacy if available
        if self._legacy_episodic is not None:
            try:
                self._legacy_episodic.append(entry.to_dict())
            except Exception:
                pass

        return entry

    def get_recent(self, limit: int = 100) -> List[EpisodicEntry]:
        """
        Get recent entries.

        Args:
            limit: Maximum entries to return

        Returns:
            List of recent entries (newest last)
        """
        return list(self._entries)[-limit:]

    def get_by_type(self, event_type: str, limit: int = 100) -> List[EpisodicEntry]:
        """
        Get entries by event type.

        Args:
            event_type: Type to filter by
            limit: Maximum entries

        Returns:
            Matching entries
        """
        matching = [e for e in self._entries if e.event_type == event_type]
        return matching[-limit:]

    def get_freshness_seconds(self) -> float:
        """
        Get age of newest entry.

        Returns:
            Seconds since last entry was added
        """
        return time.time() - self._last_entry_time

    def count(self) -> int:
        """Get total entry count."""
        return len(self._entries)

    def count_by_success(self) -> Dict[str, int]:
        """
        Get counts by success status.

        Returns:
            Dictionary with 'success' and 'failure' counts
        """
        success = sum(1 for e in self._entries if e.success)
        return {
            "success": success,
            "failure": len(self._entries) - success,
        }

    def get_success_rate(self, window_entries: int = 100) -> float:
        """
        Get success rate for recent entries.

        Args:
            window_entries: Number of entries to consider

        Returns:
            Success rate from 0.0 to 1.0
        """
        recent = list(self._entries)[-window_entries:]
        if not recent:
            return 1.0
        return sum(1 for e in recent if e.success) / len(recent)

    def archive_old(self, older_than_hours: int = 24) -> int:
        """
        Archive entries older than threshold.

        Args:
            older_than_hours: Archive entries older than this

        Returns:
            Number of entries archived
        """
        cutoff = time.time() - (older_than_hours * 3600)
        archived = 0

        new_entries = deque(maxlen=self.max_entries)
        for entry in self._entries:
            if entry.timestamp >= cutoff:
                new_entries.append(entry)
            else:
                archived += 1

        self._entries = new_entries
        logger.info(f"Archived {archived} episodic entries")
        return archived

    def prune_by_importance(self, keep_ratio: float = 0.8) -> int:
        """
        Prune low-importance entries.

        Args:
            keep_ratio: Ratio of entries to keep (0-1)

        Returns:
            Number of entries pruned
        """
        if not self._entries:
            return 0

        target_count = int(len(self._entries) * keep_ratio)
        if target_count >= len(self._entries):
            return 0

        # Sort by importance, keep most important
        sorted_entries = sorted(self._entries, key=lambda e: e.importance, reverse=True)
        kept = sorted_entries[:target_count]

        # Restore chronological order
        kept.sort(key=lambda e: e.timestamp)

        pruned = len(self._entries) - len(kept)
        self._entries = deque(kept, maxlen=self.max_entries)

        logger.info(f"Pruned {pruned} low-importance entries")
        return pruned

    def clear(self) -> None:
        """Clear all entries."""
        self._entries.clear()

    def to_jsonl_lines(self) -> List[str]:
        """
        Export entries as JSONL lines.

        Returns:
            List of JSON strings (one per entry)
        """
        import json
        return [json.dumps(e.to_dict()) for e in self._entries]
