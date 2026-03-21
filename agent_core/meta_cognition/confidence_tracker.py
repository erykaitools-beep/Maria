"""
ConfidenceTracker - Per-action and per-topic confidence tracking.

Computes confidence scores from reflection history.
Zero LLM, pure arithmetic. No separate persistence (computed from ReflectionStore).

Kontrakt: docs/CONTRACTS.md - Kontrakt 9: Meta-Cognition
"""

import logging
from typing import Dict, List

from agent_core.meta_cognition.reflection_model import Reflection

logger = logging.getLogger(__name__)

# Confidence parameters
DEFAULT_CONFIDENCE = 0.5
LOW_CONFIDENCE_THRESHOLD = 0.3
MIN_SAMPLES = 3
DECAY_WEIGHT = 0.85          # Exponential decay: recent results weighted more
ACTION_WEIGHT = 0.6           # Weight for action_type confidence in combined score
TOPIC_WEIGHT = 0.4            # Weight for topic confidence in combined score


class ConfidenceTracker:
    """
    Computes confidence scores from reflection history.

    Two dimensions:
    - Per action_type: "how well do learn/exam/fetch/review actions succeed?"
    - Per topic: "how confident are we about topic X?"

    Combined into a single score for a (action_type, topic) pair.
    Uses exponential decay weighting (recent results matter more).
    """

    def __init__(self, store):
        """
        Args:
            store: ReflectionStore instance.
        """
        self._store = store

    def get_action_confidence(self, action_type: str) -> float:
        """
        Success rate for an action type (0.0 to 1.0).

        Uses exponential decay weighting.
        Returns DEFAULT_CONFIDENCE if fewer than MIN_SAMPLES reflections.
        """
        reflections = self._store.get_by_action_type(action_type, limit=50)
        reflected = [r for r in reflections if r.is_reflected]
        return self._compute_weighted_confidence(reflected)

    def get_topic_confidence(self, topic: str) -> float:
        """
        Success rate for a topic across all action types.

        Returns DEFAULT_CONFIDENCE if fewer than MIN_SAMPLES.
        """
        if not topic:
            return DEFAULT_CONFIDENCE
        reflections = self._store.get_by_topic(topic, limit=50)
        reflected = [r for r in reflections if r.is_reflected]
        return self._compute_weighted_confidence(reflected)

    def get_decision_confidence(
        self, action_type: str, topic: str = ""
    ) -> float:
        """
        Combined confidence for a specific (action_type, topic) pair.

        Formula: ACTION_WEIGHT * action_conf + TOPIC_WEIGHT * topic_conf
        If topic is empty, uses only action_confidence.
        """
        action_conf = self.get_action_confidence(action_type)

        if not topic:
            return action_conf

        topic_conf = self.get_topic_confidence(topic)
        return ACTION_WEIGHT * action_conf + TOPIC_WEIGHT * topic_conf

    def is_low_confidence(
        self, action_type: str, topic: str = ""
    ) -> bool:
        """Check if confidence is below LOW_CONFIDENCE_THRESHOLD."""
        return (
            self.get_decision_confidence(action_type, topic)
            < LOW_CONFIDENCE_THRESHOLD
        )

    def get_confidence_map(self) -> Dict[str, float]:
        """Full map of {action_type: confidence} for status display."""
        recent = self._store.get_reflected(limit=100)
        action_types = set(r.action_type for r in recent)
        return {
            at: self.get_action_confidence(at)
            for at in sorted(action_types)
        }

    def get_topic_confidence_map(self) -> Dict[str, float]:
        """Full map of {topic: confidence} for status display."""
        recent = self._store.get_reflected(limit=100)
        topics = set(r.topic for r in recent if r.topic)
        return {
            t: self.get_topic_confidence(t)
            for t in sorted(topics)
        }

    @staticmethod
    def _compute_weighted_confidence(
        reflections: List[Reflection],
    ) -> float:
        """
        Compute exponential-decay-weighted success rate.

        reflections should be newest-first (as returned by store queries).
        Oldest reflections get lower weight.

        Uses outcome_match for nuanced scoring:
        - match: 1.0 (prediction correct)
        - partial: 0.5 (partial success)
        - mismatch: 0.0 (prediction wrong)
        - If outcome_match not set, falls back to binary success.
        """
        if len(reflections) < MIN_SAMPLES:
            return DEFAULT_CONFIDENCE

        # Reverse to oldest-first for decay calculation
        ordered = list(reversed(reflections))
        n = len(ordered)

        weight_sum = 0.0
        score_sum = 0.0

        for i, r in enumerate(ordered):
            weight = DECAY_WEIGHT ** (n - 1 - i)
            weight_sum += weight

            # Use outcome_match for nuanced scoring if available
            match_val = r.outcome_match.value if hasattr(r.outcome_match, 'value') else str(r.outcome_match)
            if match_val == "match":
                score_sum += weight * 1.0
            elif match_val == "partial":
                score_sum += weight * 0.5
            elif match_val in ("mismatch", "surprising"):
                pass  # 0.0
            else:
                # UNKNOWN or not reflected yet: fallback to binary success
                if r.actual_success:
                    score_sum += weight

        if weight_sum == 0:
            return DEFAULT_CONFIDENCE

        return score_sum / weight_sum
