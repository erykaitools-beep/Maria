"""
GoalSelector - Rule-based goal selection with aging factor.

Selects the highest-priority feasible goal from GoalStore.
Kontrakt: docs/CONTRACTS.md - Kontrakt 5: Planner
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Aging: priority multiplier grows linearly with time pending
# After 1h pending: 1.0 + 0.1 = 1.1x
# After 24h pending: 1.0 + 2.4 = 3.4x
AGING_FACTOR_PER_HOUR = 0.1

# Max aging multiplier (clamp) to prevent runaway
MAX_AGING = 4.0


class GoalSelector:
    """
    Selects the best goal to work on in this planner cycle.

    Scoring: effective_priority = priority * (1 + aging_factor)
    Feasibility: can this goal make progress right now?
    """

    def select_goal(
        self,
        active_goals: list,
        evaluation_metrics: Dict[str, float],
        knowledge_snapshot: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> Optional[Any]:
        """
        Select the highest effective-priority feasible goal.

        Args:
            active_goals: Active goals from GoalStore (PENDING + ACTIVE)
            evaluation_metrics: Latest K4 metrics
            knowledge_snapshot: From KnowledgeAnalyzer (optional)
            now: Current time (for testing)

        Returns:
            Selected Goal or None
        """
        if not active_goals:
            return None

        if now is None:
            now = time.time()

        scored = []
        for goal in active_goals:
            score = self._compute_effective_priority(goal, now)
            feasible, reason = self._check_feasibility(
                goal, evaluation_metrics, knowledge_snapshot
            )
            if feasible:
                scored.append((score, goal))
            else:
                logger.debug(
                    f"Goal {goal.id} not feasible: {reason}"
                )

        if not scored:
            return None

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def _compute_effective_priority(self, goal, now: float) -> float:
        """
        Compute priority with aging factor.

        effective_priority = priority * (1 + hours_pending * AGING_FACTOR_PER_HOUR)
        Clamped to max aging of 4.0 to prevent runaway.
        """
        hours_pending = (now - goal.created_at) / 3600.0
        aging = hours_pending * AGING_FACTOR_PER_HOUR
        effective = goal.priority * (1.0 + min(aging, MAX_AGING))
        return effective

    def _check_feasibility(
        self,
        goal,
        evaluation_metrics: Dict[str, float],
        knowledge_snapshot: Optional[Dict[str, Any]],
    ) -> Tuple[bool, str]:
        """
        Check if a goal can make progress right now.

        Returns:
            (is_feasible, reason_if_not)
        """
        goal_type = goal.type.value

        # MAINTENANCE goals are always feasible
        if goal_type == "maintenance":
            return True, ""

        # META goals are always feasible
        if goal_type == "meta":
            return True, ""

        # USER goals are always feasible
        if goal_type == "user":
            return True, ""

        # LEARNING goals: need materials to learn
        if goal_type == "learning":
            if knowledge_snapshot:
                by_status = knowledge_snapshot.get("files_by_status", {})
                new_files = knowledge_snapshot.get("new_files_available", [])
                in_progress = by_status.get("learning", [])
                if not new_files and not in_progress:
                    return False, "no files to learn"
            return True, ""

        return True, ""

    def rank_goals(
        self,
        active_goals: list,
        evaluation_metrics: Dict[str, float],
        now: Optional[float] = None,
    ) -> List[Tuple[float, Any]]:
        """
        Rank all goals by effective priority (for /plan goals display).

        Returns:
            List of (effective_priority, goal) sorted descending
        """
        if now is None:
            now = time.time()

        ranked = []
        for goal in active_goals:
            score = self._compute_effective_priority(goal, now)
            ranked.append((score, goal))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return ranked
