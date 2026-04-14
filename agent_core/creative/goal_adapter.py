"""Transforms approved Creative outputs into GoalStore-compatible records.

This is the bridge between Creative module and the K3 Goal System.
Creative PROPOSES, GoalStore STORES, Planner EXECUTES.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from agent_core.creative.creative_model import (
    MetaGoal, MetaGoalStatus, MetaGoalType,
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

    def __init__(self, goal_store=None):
        """
        Args:
            goal_store: GoalStore instance (optional, wired later).
        """
        self._goal_store = goal_store

    def set_goal_store(self, goal_store) -> None:
        self._goal_store = goal_store

    def adapt_and_propose(self, meta_goal: MetaGoal) -> Optional[str]:
        """
        Transform a meta-goal into a GoalStore PROPOSED record.

        Returns:
            Goal ID if successfully proposed, None if store is full or unavailable.
        """
        if self._goal_store is None:
            logger.warning("[CREATIVE] GoalStore not available, cannot propose meta-goal")
            return None

        try:
            # Import here to avoid circular dependency
            from agent_core.goals.goal_model import Goal, GoalType, GoalStatus, AuditEntry

            goal = Goal(
                id=meta_goal.goal_id,
                type=GoalType.META,
                description=meta_goal.title,
                priority=meta_goal.priority,
                status=GoalStatus.PROPOSED,
                progress=0.0,
                parent_goal_id=None,
                created_by="creative",
                created_at=time.time(),
                updated_at=time.time(),
                deadline=None,
                audit_trail=[
                    AuditEntry(
                        timestamp=time.time(),
                        old_status=None,
                        new_status="proposed",
                        reason=meta_goal.why_now[:200],
                        actor="creative",
                    )
                ],
                metadata={
                    "source": "creative",
                    "meta_goal_type": meta_goal.goal_type.value,
                    "risk_level": meta_goal.risk_level.value,
                    "evidence_refs": meta_goal.evidence_refs,
                    "expected_value": meta_goal.expected_value,
                    "decomposition_hint": meta_goal.decomposition_hint,
                },
            )

            result = self._goal_store.propose(goal)
            if result:
                try:
                    self._goal_store.save()
                except Exception:
                    pass
                logger.info(
                    f"[CREATIVE] Meta-goal promoted to GoalStore: "
                    f"{meta_goal.goal_id} -> {meta_goal.title}"
                )
                return result
            else:
                logger.info(
                    f"[CREATIVE] GoalStore proposal rejected (at limit): {meta_goal.title}"
                )
                return None

        except Exception as e:
            logger.warning(f"[CREATIVE] Failed to propose meta-goal: {e}")
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
