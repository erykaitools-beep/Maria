"""Selective memory retrieval for reflection sessions.

Extracts keywords from tensions and context, then delegates to
CreativeConversationMemory.retrieve_relevant() for keyword matching.

When semantic_memory is set, uses embedding similarity search
as primary retrieval, with keyword matching as fallback.
"""

import logging
import re
from typing import Any, Dict, List

from agent_core.creative.creative_model import DetectedTension, TensionCategory
from agent_core.creative.creative_store import CreativeStore
from agent_core.creative.conversation_memory import CreativeConversationMemory

logger = logging.getLogger(__name__)

# Category -> related keywords (Polish)
_TENSION_KEYWORDS = {
    TensionCategory.REPETITION: ["powtarzanie", "noop", "stagnacja", "kolko"],
    TensionCategory.STAGNATION: ["postep", "nauka", "blokada", "velocity"],
    TensionCategory.UNDER_EXPLORATION: ["eksploracja", "nowe", "tematy", "zakres"],
    TensionCategory.EPISTEMIC_GAP: ["retencja", "wiedza", "egzamin", "luki"],
    TensionCategory.OVER_RESTRICTION: ["blokada", "k7", "polityka", "ograniczenie"],
    TensionCategory.MISALIGNMENT: ["cele", "dopasowanie", "priorytet", "stale"],
    TensionCategory.FRAGILE_COORDINATION: ["bledy", "koordynacja", "pipeline", "fail"],
}


class MemoryRetriever:
    """Retrieves relevant memories for creative reflection sessions."""

    def __init__(self, store: CreativeStore):
        self._conv_memory = CreativeConversationMemory(store)
        self._semantic_memory = None  # Late-wired SemanticMemory

    def set_semantic_memory(self, semantic_memory) -> None:
        """Wire SemanticMemory for embedding-based retrieval."""
        self._semantic_memory = semantic_memory

    def retrieve_for_session(
        self,
        tensions: List[DetectedTension],
        context: Dict[str, Any],
        limit: int = 10,
    ) -> List[dict]:
        """
        Retrieve memories relevant to current tensions and context.

        Uses semantic search when available, falls back to keyword matching.

        Args:
            tensions: Detected tensions in this cycle
            context: Strategic context dict
            limit: Max memories to return

        Returns:
            List of conversation memory dicts, ranked by relevance
        """
        # Try semantic search first
        if self._semantic_memory and tensions:
            semantic_results = self._semantic_retrieve(tensions, limit)
            if semantic_results:
                return semantic_results

        # Fallback: keyword-based
        keywords = self.extract_keywords(tensions, context)
        if not keywords:
            return []

        return self._conv_memory.retrieve_relevant(
            keywords=keywords,
            min_importance=0.3,
            limit=limit,
        )

    def _semantic_retrieve(
        self,
        tensions: List[DetectedTension],
        limit: int,
    ) -> List[dict]:
        """Retrieve memories using semantic similarity to tension descriptions."""
        try:
            sm = self._semantic_memory
            all_results = []
            per_tension = max(limit // len(tensions), 2)

            for tension in tensions:
                query = tension.description
                results = sm.search(
                    query, namespace="memories",
                    top_k=per_tension, threshold=0.4,
                )
                for r in results:
                    all_results.append({
                        "content": r.entry.text,
                        "similarity": r.score,
                        "metadata": r.entry.metadata,
                        "source": "semantic",
                    })

            # Deduplicate by entry ID and sort by similarity
            seen = set()
            unique = []
            for r in sorted(all_results, key=lambda x: x["similarity"], reverse=True):
                key = r["content"][:100]
                if key not in seen:
                    seen.add(key)
                    unique.append(r)

            return unique[:limit]

        except Exception as e:
            logger.warning(f"[MEMORY_RETRIEVER] Semantic retrieval failed: {e}")
            return []

    def extract_keywords(
        self,
        tensions: List[DetectedTension],
        context: Dict[str, Any],
    ) -> List[str]:
        """
        Extract search keywords from tensions and context.

        Sources:
        - Tension categories -> predefined keyword lists
        - Tension descriptions -> content words
        - Context stale goals -> goal descriptions
        - Context learning state -> struggling topic names
        """
        keywords = []

        # From tension categories
        for tension in tensions:
            cat_keywords = _TENSION_KEYWORDS.get(tension.category, [])
            keywords.extend(cat_keywords)

            # Extract content words from description (>3 chars, no stopwords)
            words = self._extract_content_words(tension.description)
            keywords.extend(words)

        # From stale goals
        stale = context.get("goal_state", {}).get("stale_goals", [])
        for desc in stale[:3]:
            keywords.extend(self._extract_content_words(str(desc)))

        # From learning state statuses
        statuses = context.get("learning_state", {}).get("statuses", {})
        if statuses.get("exam_failed", 0) > 0:
            keywords.append("egzamin")
            keywords.append("trudne")

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for kw in keywords:
            lower = kw.lower()
            if lower not in seen:
                seen.add(lower)
                unique.append(lower)

        return unique[:30]  # Cap at 30 keywords

    def _extract_content_words(self, text: str) -> List[str]:
        """Extract meaningful words from text (>3 chars, alpha only)."""
        words = re.findall(r'[a-zA-Za-zA-Z\u0080-\u024F]+', text)
        return [w for w in words if len(w) > 3]
