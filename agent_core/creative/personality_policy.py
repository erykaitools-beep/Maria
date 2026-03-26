"""Growth-style rules derived from personality traits.

Maps current personality trait scores to cognitive development preferences.
Outputs PersonalitySignal objects and evaluation weight adjustments.
Zero LLM - pure rule-based mapping.
"""

import logging
from typing import Dict, List, Optional

from agent_core.creative.creative_model import (
    DetectedTension, PersonalityDimension, PersonalitySignal, TensionCategory,
)
from agent_core.creative.identity_profile import CognitiveProfile

logger = logging.getLogger(__name__)

# Default evaluation weights (from creative_evaluator.py)
DEFAULT_WEIGHTS = {
    "strategic_value": 0.30,
    "feasibility": 0.25,
    "novelty": 0.20,
    "risk": 0.15,
    "operator_relevance": 0.10,
}


class PersonalityPolicy:
    """Maps personality traits to cognitive development preferences."""

    def evaluate(
        self,
        profile: CognitiveProfile,
        tensions: List[DetectedTension],
    ) -> List[PersonalitySignal]:
        """
        Generate personality signals based on profile and tensions.

        Args:
            profile: Current cognitive profile snapshot
            tensions: Currently detected tensions

        Returns:
            List of PersonalitySignal adjustments
        """
        signals = []
        traits = self._get_traits_from_profile(profile)

        # ciekawska > 0.6 -> exploration bias
        if traits.get("ciekawska", 0) > 0.6:
            signals.append(PersonalitySignal.create(
                dimension=PersonalityDimension.EXPLORATION_VS_ORDER,
                direction="exploration",
                reason="Wysoka ciekawosc sprzyja eksploracji nowych tematow",
                magnitude=0.05,
            ))

        # systematyczna > 0.6 -> epistemic/consolidation bias
        if traits.get("systematyczna", 0) > 0.6:
            signals.append(PersonalitySignal.create(
                dimension=PersonalityDimension.DEPTH_VS_BREADTH,
                direction="depth",
                reason="Wysoka systematycznosc sprzyja poglebionej nauce",
                magnitude=0.05,
            ))

        # refleksyjna > 0.6 -> more reframes
        if traits.get("refleksyjna", 0) > 0.6:
            signals.append(PersonalitySignal.create(
                dimension=PersonalityDimension.REFRAME_BIAS,
                direction="increase",
                reason="Wysoka refleksyjnosc sprzyja przeformulowaniu problemow",
                magnitude=0.05,
            ))

        # wytrwala > 0.4 -> tolerate higher risk
        if traits.get("wytrwala", 0) > 0.4:
            signals.append(PersonalitySignal.create(
                dimension=PersonalityDimension.CAUTION_VS_BOLDNESS,
                direction="boldness",
                reason="Wytrwalosc pozwala na wyzsze ryzyko w meta-celach",
                magnitude=0.03,
            ))

        # cierpliwa > 0.4 + stagnation tension -> reduce urgency
        has_stagnation = any(
            t.category == TensionCategory.STAGNATION for t in tensions
        )
        if traits.get("cierpliwa", 0) > 0.4 and has_stagnation:
            signals.append(PersonalitySignal.create(
                dimension=PersonalityDimension.CAUTION_VS_BOLDNESS,
                direction="caution",
                reason="Cierpliwosc pozwala tolerowac chwilowa stagnacje",
                magnitude=0.02,
            ))

        # operator_sensitivity based on how many operator decisions are recorded
        if traits.get("spoleczna", 0) > 0.5:
            signals.append(PersonalitySignal.create(
                dimension=PersonalityDimension.OPERATOR_SENSITIVITY,
                direction="increase",
                reason="Spolecznosc zwieksza wage preferencji operatora",
                magnitude=0.03,
            ))

        return signals

    def adjust_evaluation_weights(
        self,
        base_weights: Optional[Dict[str, float]] = None,
        signals: Optional[List[PersonalitySignal]] = None,
    ) -> Dict[str, float]:
        """
        Adjust meta-goal evaluation weights based on personality signals.

        Args:
            base_weights: Starting weights (default: DEFAULT_WEIGHTS)
            signals: PersonalitySignals to apply

        Returns:
            Adjusted weights dict (sums to 1.0)
        """
        weights = dict(base_weights or DEFAULT_WEIGHTS)
        if not signals:
            return weights

        for signal in signals:
            dim = signal.dimension
            mag = signal.magnitude

            if dim == PersonalityDimension.EXPLORATION_VS_ORDER:
                if signal.direction == "exploration":
                    weights["novelty"] = weights.get("novelty", 0.2) + mag
                    weights["feasibility"] = weights.get("feasibility", 0.25) - mag

            elif dim == PersonalityDimension.DEPTH_VS_BREADTH:
                if signal.direction == "depth":
                    weights["strategic_value"] = weights.get("strategic_value", 0.3) + mag
                    weights["novelty"] = weights.get("novelty", 0.2) - mag

            elif dim == PersonalityDimension.CAUTION_VS_BOLDNESS:
                if signal.direction == "boldness":
                    weights["risk"] = weights.get("risk", 0.15) - mag
                    weights["novelty"] = weights.get("novelty", 0.2) + mag
                elif signal.direction == "caution":
                    weights["risk"] = weights.get("risk", 0.15) + mag
                    weights["novelty"] = weights.get("novelty", 0.2) - mag

            elif dim == PersonalityDimension.OPERATOR_SENSITIVITY:
                if signal.direction == "increase":
                    weights["operator_relevance"] = weights.get("operator_relevance", 0.1) + mag
                    weights["strategic_value"] = weights.get("strategic_value", 0.3) - mag

        # Clamp negatives first
        for k in weights:
            if weights[k] < 0.01:
                weights[k] = 0.01

        # Normalize to sum=1.0
        total = sum(weights.values())
        if total > 0:
            weights = {k: max(v / total, 0.01) for k, v in weights.items()}

        # Final re-normalize after clamping
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

        return weights

    def _get_traits_from_profile(self, profile: CognitiveProfile) -> Dict[str, float]:
        """Extract trait name -> score from profile's dominant_traits + full data."""
        # Profile stores dominant_traits as names only, we need scores
        # But we can infer: if a trait is in dominant_traits, it's > 0.5
        # For now, use a simple heuristic based on position
        traits: Dict[str, float] = {}
        for i, name in enumerate(profile.dominant_traits):
            # Approximate score: top trait = 0.7, second = 0.6, third = 0.5
            traits[name] = 0.7 - (i * 0.1)
        return traits
