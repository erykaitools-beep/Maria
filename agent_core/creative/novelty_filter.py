"""Rejects duplicate, pseudo-novel, or overly broad meta-goals.

Filters:
1. Exact title dedup against recent accepted/rejected
2. Category dedup (same type within cooldown period)
3. Overly broad detection (title too generic)
4. Goal-flood protection (cap per period)
"""

import logging
import time
from typing import Any, Dict, List, Tuple

from agent_core.creative.creative_model import MetaGoal, MetaGoalStatus
from agent_core.creative.creative_store import CreativeStore

logger = logging.getLogger(__name__)

# Limits
MAX_PROPOSALS_PER_PERIOD = 3     # Max new meta-goals per reflection cycle
CATEGORY_COOLDOWN_HOURS = 12     # Same type can't repeat within 12h
TITLE_SIMILARITY_THRESHOLD = 0.7  # Fuzzy title match threshold

# Generic titles that should be rejected
_OVERLY_BROAD = {
    "nowy kierunek", "rozwoj", "poprawa", "lepsze dzialanie",
    "ogolna poprawa", "nowe mozliwosci",
}


class NoveltyFilter:
    """Filters out duplicate and low-value meta-goals."""

    def __init__(self, store: CreativeStore):
        self._store = store

    def filter(self, candidates: List[MetaGoal]) -> Tuple[List[MetaGoal], List[MetaGoal]]:
        """
        Filter candidates for novelty.

        Returns:
            (accepted, rejected) tuple of MetaGoal lists.
        """
        recent = self._store.get_recent_meta_goals(hours=CATEGORY_COOLDOWN_HOURS)
        recent_titles = [mg.get("title", "").lower() for mg in recent]
        recent_types = [mg.get("goal_type", "") for mg in recent]

        accepted: List[MetaGoal] = []
        rejected: List[MetaGoal] = []

        for mg in candidates:
            reason = self._check_rejection(mg, recent_titles, recent_types, len(accepted))
            if reason:
                rejected.append(mg.with_status(MetaGoalStatus.REJECTED))
                logger.info(f"[CREATIVE] Filtered out: {mg.title} ({reason})")
            else:
                accepted.append(mg)

        return accepted, rejected

    def _check_rejection(self, mg: MetaGoal, recent_titles: List[str],
                         recent_types: List[str], accepted_so_far: int) -> str:
        """Check if a meta-goal should be rejected. Returns reason or empty string."""

        # 1. Goal-flood protection
        if accepted_so_far >= MAX_PROPOSALS_PER_PERIOD:
            return "goal_flood_cap"

        # 2. Exact title dedup
        title_lower = mg.title.lower()
        if title_lower in recent_titles:
            return "exact_duplicate"

        # 3. Fuzzy title dedup (simple word overlap)
        for recent_title in recent_titles:
            if self._title_similar(title_lower, recent_title):
                return "similar_duplicate"

        # 4. Category cooldown
        type_value = mg.goal_type.value
        if type_value in recent_types:
            return "category_cooldown"

        # 5. Overly broad
        if self._is_overly_broad(title_lower):
            return "overly_broad"

        # 6. Missing evidence
        if not mg.evidence_refs:
            return "no_evidence"

        return ""

    def _title_similar(self, a: str, b: str) -> bool:
        """Simple word-overlap similarity check."""
        words_a = set(a.split())
        words_b = set(b.split())
        if not words_a or not words_b:
            return False
        overlap = len(words_a & words_b)
        total = max(len(words_a), len(words_b))
        return (overlap / total) >= TITLE_SIMILARITY_THRESHOLD

    def _is_overly_broad(self, title: str) -> bool:
        """Check if title is too generic to be useful."""
        for broad_phrase in _OVERLY_BROAD:
            if title == broad_phrase:
                return True
        # Also reject very short titles
        return len(title.split()) < 3
