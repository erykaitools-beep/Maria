"""Stores operator-dialogue memories relevant to growth and direction.

Separate from consciousness ConversationMemory - this stores STRATEGIC
dialogue about development direction, operator preferences, and decisions.

Uses selective retrieval: store raw dialogue, derive compact summaries,
retrieve only memory relevant to the current strategic question.
"""

import logging
from typing import List

from agent_core.creative.creative_model import (
    ConversationMemoryEntry, ConversationMemoryType, Speaker,
)
from agent_core.creative.creative_store import CreativeStore

logger = logging.getLogger(__name__)


class CreativeConversationMemory:
    """Manages operator-dialogue memories for Creative module."""

    def __init__(self, store: CreativeStore):
        self._store = store

    def record(self, session_id: str, speaker: Speaker, content: str,
               memory_type: ConversationMemoryType,
               importance: float = 0.5, summary: str = "") -> ConversationMemoryEntry:
        """Record a development-relevant dialogue fragment."""
        entry = ConversationMemoryEntry.create(
            source_session=session_id,
            speaker=speaker,
            content=content,
            memory_type=memory_type,
            importance=importance,
            summary=summary,
        )
        self._store.save_conversation_memory(entry)
        return entry

    def retrieve_relevant(self, keywords: List[str],
                          min_importance: float = 0.3,
                          limit: int = 5) -> List[dict]:
        """Retrieve memories relevant to given keywords.

        Simple keyword-based matching. Future: semantic similarity.
        """
        all_memories = self._store.load_conversation_memories()

        scored = []
        for mem in all_memories:
            if mem.get("importance", 0) < min_importance:
                continue

            # Simple keyword matching in content and summary
            content = (mem.get("content", "") + " " + mem.get("summary", "")).lower()
            score = sum(1 for kw in keywords if kw.lower() in content)

            if score > 0:
                scored.append((score + mem.get("importance", 0), mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [mem for _, mem in scored[:limit]]

    def get_operator_preferences(self) -> List[dict]:
        """Get all recorded operator preferences."""
        return self._store.get_memories_by_type(ConversationMemoryType.PREFERENCE.value)

    def get_operator_decisions(self) -> List[dict]:
        """Get all recorded operator decisions."""
        return self._store.get_memories_by_type(ConversationMemoryType.DECISION.value)

    def get_high_importance(self, limit: int = 10) -> List[dict]:
        """Get most important memories regardless of type."""
        return self._store.get_memories_by_importance(min_importance=0.7)[:limit]
