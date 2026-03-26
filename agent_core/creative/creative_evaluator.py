"""Scores strategic value, feasibility, novelty, risk, and operator relevance.

Rule-based evaluation of meta-goals before promotion to GoalStore.
Zero LLM - deterministic scoring.

Scoring dimensions (0.0-1.0):
- strategic_value: How important is this for development?
- feasibility: Can the system actually act on this?
- novelty: How different is this from current activities?
- risk: What's the downside? (lower is better)
- operator_relevance: How aligned with known operator preferences?

Final score = weighted average, threshold for promotion.
"""

import logging
from typing import Any, Dict, List, Optional

from agent_core.creative.creative_model import (
    MetaGoal, MetaGoalType, RiskLevel,
)

logger = logging.getLogger(__name__)

# Promotion threshold (0.0-1.0) - meta-goals below this are not promoted
PROMOTION_THRESHOLD = 0.4

# Weights for scoring dimensions
WEIGHTS = {
    "strategic_value": 0.30,
    "feasibility": 0.25,
    "novelty": 0.20,
    "risk": 0.15,
    "operator_relevance": 0.10,
}

# Meta-goal types that are more feasible (system can act on them)
_HIGH_FEASIBILITY_TYPES = {
    MetaGoalType.EXPLORATION_META,
    MetaGoalType.EPISTEMIC_META,
}

# Meta-goal types that require operator involvement
_OPERATOR_DEPENDENT_TYPES = {
    MetaGoalType.OPERATOR_META,
    MetaGoalType.ARCHITECTURAL_META,
}


class CreativeEvaluator:
    """Evaluates meta-goals for promotion to GoalStore."""

    def evaluate(self, meta_goal: MetaGoal,
                 context: Dict[str, Any] = None,
                 weights: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """
        Score a meta-goal across multiple dimensions.

        Args:
            meta_goal: The meta-goal to evaluate
            context: Strategic context dict
            weights: Custom weights (from PersonalityPolicy). Default: WEIGHTS.

        Returns:
            Dict with dimension scores and final_score.
        """
        context = context or {}
        w = weights or WEIGHTS

        scores = {
            "strategic_value": self._score_strategic_value(meta_goal, context),
            "feasibility": self._score_feasibility(meta_goal, context),
            "novelty": self._score_novelty(meta_goal, context),
            "risk": self._score_risk(meta_goal),
            "operator_relevance": self._score_operator_relevance(meta_goal, context),
        }

        # Weighted average
        final = sum(
            scores[dim] * w.get(dim, WEIGHTS.get(dim, 0))
            for dim in WEIGHTS
        )

        scores["final_score"] = round(final, 3)
        scores["promoted"] = final >= PROMOTION_THRESHOLD
        scores["goal_id"] = meta_goal.goal_id

        return scores

    def evaluate_batch(self, meta_goals: List[MetaGoal],
                       context: Dict[str, Any] = None,
                       weights: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
        """Evaluate multiple meta-goals, return sorted by final_score."""
        results = [self.evaluate(mg, context, weights) for mg in meta_goals]
        results.sort(key=lambda r: r["final_score"], reverse=True)
        return results

    def _score_strategic_value(self, mg: MetaGoal,
                               context: Dict[str, Any]) -> float:
        """How important is this for system development?"""
        score = mg.priority  # Start from insight confidence

        # Boost if addressing high-coverage stagnation
        learning = context.get("learning_state", {})
        coverage = learning.get("coverage", 0)
        if coverage > 0.9 and mg.goal_type == MetaGoalType.EXPLORATION_META:
            score = min(score + 0.2, 1.0)

        # Boost if addressing system instability
        health = context.get("system_health", {})
        stability = health.get("system_stability")
        if stability is not None and stability < 0.8:
            if mg.goal_type == MetaGoalType.RESILIENCE_META:
                score = min(score + 0.15, 1.0)

        return round(score, 3)

    def _score_feasibility(self, mg: MetaGoal,
                           context: Dict[str, Any]) -> float:
        """Can the system actually act on this?"""
        if mg.goal_type in _HIGH_FEASIBILITY_TYPES:
            score = 0.8
        elif mg.goal_type in _OPERATOR_DEPENDENT_TYPES:
            score = 0.3  # Needs operator
        else:
            score = 0.5

        # Has decomposition hint? More feasible
        if mg.decomposition_hint:
            score = min(score + 0.1, 1.0)

        return round(score, 3)

    def _score_novelty(self, mg: MetaGoal,
                       context: Dict[str, Any]) -> float:
        """How different is this from what system is already doing?"""
        recent_titles = context.get("recent_meta_goals", [])

        if not recent_titles:
            return 0.8  # No prior creative output = novel

        # Check if any recent goal has similar type
        # (simple heuristic - if there are few recent goals, novelty is higher)
        novelty = max(0.3, 1.0 - len(recent_titles) * 0.15)
        return round(min(novelty, 1.0), 3)

    def _score_risk(self, mg: MetaGoal) -> float:
        """Score risk inversely (lower risk = higher score)."""
        risk_scores = {
            RiskLevel.LOW: 0.9,
            RiskLevel.MEDIUM: 0.5,
            RiskLevel.HIGH: 0.2,
        }
        return risk_scores.get(mg.risk_level, 0.5)

    def _score_operator_relevance(self, mg: MetaGoal,
                                  context: Dict[str, Any]) -> float:
        """How aligned with operator preferences?"""
        # For now: default moderate relevance
        # Future: check conversation_memory for operator preferences
        if mg.goal_type == MetaGoalType.OPERATOR_META:
            return 0.9
        return 0.5
