"""Transforms approved Creative outputs into GoalStore-compatible records.

This is the bridge between Creative module and the K3 Goal System.
Creative PROPOSES, GoalStore STORES, Planner EXECUTES.
"""

import logging
from typing import Any, Dict, List, Optional

from agent_core.creative.creative_model import (
    MetaGoal, MetaGoalType,
)

logger = logging.getLogger(__name__)

# Mapping from MetaGoalType to GoalType string
# GoalType enum: META, USER, LEARNING, MAINTENANCE
_META_GOAL_TYPE_TO_GOAL_TYPE = {
    MetaGoalType.EPISTEMIC_META: "meta",
    MetaGoalType.CAPABILITY_META: "meta",
    MetaGoalType.RESILIENCE_META: "meta",
    MetaGoalType.EXPLORATION_META: "meta",
    MetaGoalType.ARCHITECTURAL_META: "meta",
    MetaGoalType.OPERATOR_META: "meta",
    MetaGoalType.PERSONALITY_META: "meta",
}


class GoalAdapter:
    """Adapts Creative meta-goals into GoalStore records."""

    def __init__(self, goal_store=None, bulletin_store=None):
        """
        Args:
            goal_store: GoalStore instance (deprecated since R1, kept for compat).
            bulletin_store: BulletinStore instance (wired later).
        """
        # goal_store kept for backward-compat wiring; unused since R1
        # (2026-05-29) - creative meta-goals post IMPROVEMENT advisories.
        self._goal_store = goal_store
        self._bulletin_store = bulletin_store

    def set_goal_store(self, goal_store) -> None:
        self._goal_store = goal_store

    def set_bulletin_store(self, store) -> None:
        self._bulletin_store = store

    def adapt_and_propose(self, meta_goal: MetaGoal) -> Optional[str]:
        """
        Post a Creative meta-goal to the bulletin as an IMPROVEMENT advisory.

        R1 (2026-05-29): meta-goals used to become PROPOSED goals, but 217
        creative goals aged to ABANDONED without ever going ACTIVE. They are
        exploratory upgrade proposals, not actionable goals - IMPROVEMENT
        advisories on the bulletin are their proper home (dedup by topic+type).

        Returns:
            Bulletin entry ID if posted, None if no bulletin store or on error.
        """
        if self._bulletin_store is None:
            logger.warning("[CREATIVE] No bulletin_store, cannot post meta-goal")
            return None

        try:
            from agent_core.bulletin.bulletin_model import EntryType

            summary = (
                meta_goal.why_now[:200] if meta_goal.why_now else meta_goal.title
            )
            entry = self._bulletin_store.create_and_post(
                entry_type=EntryType.IMPROVEMENT,
                topic=meta_goal.title,
                reason_code=f"creative_{meta_goal.goal_type.value}",
                summary=summary,
                requested_by="creative",
                priority=meta_goal.priority,
                metadata={
                    "meta_goal_id": meta_goal.goal_id,
                    "meta_goal_type": meta_goal.goal_type.value,
                    "risk_level": meta_goal.risk_level.value,
                    "evidence_refs": meta_goal.evidence_refs,
                    "expected_value": meta_goal.expected_value,
                    "decomposition_hint": meta_goal.decomposition_hint,
                },
            )
            logger.info(
                f"[CREATIVE] Meta-goal posted as IMPROVEMENT: "
                f"{meta_goal.goal_id} -> {entry.entry_id}"
            )
            return entry.entry_id

        except Exception as e:
            logger.warning(f"[CREATIVE] Failed to post meta-goal: {e}")
            return None

    def adapt_batch(self, meta_goals: List[MetaGoal]) -> Dict[str, Any]:
        """
        Propose multiple meta-goals.

        Returns:
            Summary dict with counts.
        """
        proposed = 0
        rejected = 0

        for mg in meta_goals:
            result = self.adapt_and_propose(mg)
            if result:
                proposed += 1
            else:
                rejected += 1

        return {
            "proposed": proposed,
            "rejected": rejected,
            "total": len(meta_goals),
        }
