"""
TraitEvolver - Evolves Maria's personality traits from accumulated experiences.

Pure logic, no LLM calls, deterministic. Runs at checkpoint time
(session end) or periodically during long sessions.

Usage:
    evolver = TraitEvolver(self_model, experience_tracker)
    changes = evolver.evolve()
    # {"wytrwala": +0.04, "ciekawska": +0.06}
"""

import time
import logging
from typing import Dict, Optional

from agent_core.consciousness.trait_catalog import (
    TRAIT_CATALOG,
    EMERGENCE_THRESHOLD,
    DECAY_PER_SESSION,
    SCORE_MIN,
    SCORE_MAX,
)

logger = logging.getLogger(__name__)


class TraitEvolver:
    """
    Processes accumulated experiences and updates trait scores.

    Called by ConsciousnessCore at checkpoint (session end).
    Does NOT call any LLM. Deterministic given the same inputs.
    """

    def __init__(self, self_model, experience_tracker):
        """
        Initialize trait evolver.

        Args:
            self_model: SelfModelBuilder instance
            experience_tracker: ExperienceTracker instance
        """
        self.self_model = self_model
        self.tracker = experience_tracker
        self._last_evolution_time = 0.0

    def evolve(self) -> Dict[str, float]:
        """
        Process experiences and update trait scores.

        Steps:
        1. Get experience counts from tracker
        2. Load current trait scores (or initialize from catalog)
        3. For each trait: compute delta from matching signals
        4. Apply per-session decay
        5. Clamp scores to [0, 1]
        6. Update self_model node
        7. Log milestone experiences for significant changes

        Returns:
            Dict of trait changes: {"trait_name": delta_float}
        """
        experience_counts = self.tracker.get_experience_counts()

        # Load current scores or initialize
        current_scores = self.self_model.get_trait_scores()
        if not current_scores:
            if not experience_counts:
                logger.debug("TraitEvolver: no scores and no experiences, skipping")
                return {}
            current_scores = self._initialize_scores()

        # Compute deltas
        changes = {}
        for trait_name, trait_def in TRAIT_CATALOG.items():
            delta = self._compute_trait_delta(trait_def, experience_counts)
            if delta != 0:
                changes[trait_name] = delta

        # Apply changes + decay
        for trait_name in TRAIT_CATALOG:
            if trait_name not in current_scores:
                current_scores[trait_name] = {
                    "score": TRAIT_CATALOG[trait_name]["initial_score"],
                    "evidence_count": 0,
                    "last_updated": "",
                }

            entry = current_scores[trait_name]
            old_score = entry["score"]

            # Apply delta
            delta = changes.get(trait_name, 0)
            new_score = old_score + delta

            # Apply decay
            new_score *= DECAY_PER_SESSION

            # Clamp
            new_score = max(SCORE_MIN, min(SCORE_MAX, new_score))

            entry["score"] = round(new_score, 4)
            if delta != 0:
                entry["evidence_count"] += sum(
                    count for event, count in experience_counts.items()
                    if self._event_affects_trait(event, trait_name)
                )
                entry["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")

            # Log emergence/disappearance
            was_emerged = old_score >= EMERGENCE_THRESHOLD
            is_emerged = new_score >= EMERGENCE_THRESHOLD
            if is_emerged and not was_emerged:
                logger.info(f"Trait emerged: {trait_name} ({new_score:.2f})")
                self.self_model.add_milestone_experience({
                    "event": "trait_emerged",
                    "trait": trait_name,
                    "score": new_score,
                })
            elif was_emerged and not is_emerged:
                logger.info(f"Trait faded: {trait_name} ({new_score:.2f})")

        # Update self_model
        self.self_model.update_trait_scores(current_scores)
        self._last_evolution_time = time.time()

        if changes:
            logger.info(f"Personality evolved: {changes}")

        return changes

    def _initialize_scores(self) -> Dict[str, Dict]:
        """Create initial trait scores from catalog."""
        scores = {}
        for name, definition in TRAIT_CATALOG.items():
            scores[name] = {
                "score": definition["initial_score"],
                "evidence_count": 0,
                "last_updated": "",
            }
        return scores

    def _compute_trait_delta(self, trait_def: Dict, experience_counts: Dict) -> float:
        """
        Compute score change for one trait based on experience counts.

        Args:
            trait_def: Trait definition from catalog
            experience_counts: {event_type: count}

        Returns:
            Total delta (positive or negative float)
        """
        delta = 0.0

        for event_type, score_change in trait_def.get("positive_signals", []):
            count = experience_counts.get(event_type, 0)
            delta += count * score_change

        for event_type, score_change in trait_def.get("negative_signals", []):
            count = experience_counts.get(event_type, 0)
            delta += count * score_change  # score_change is already negative

        return round(delta, 4)

    def _event_affects_trait(self, event_type: str, trait_name: str) -> bool:
        """Check if an event type affects a specific trait."""
        trait_def = TRAIT_CATALOG.get(trait_name, {})
        for evt, _ in trait_def.get("positive_signals", []):
            if evt == event_type:
                return True
        for evt, _ in trait_def.get("negative_signals", []):
            if evt == event_type:
                return True
        return False

    def get_personality_description(self) -> str:
        """
        Human-readable personality description (delegates to self_model).

        Returns:
            Polish text with trait scores.
        """
        return self.self_model.get_personality_description()
