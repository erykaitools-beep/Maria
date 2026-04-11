"""
ConsciousnessCore - Orchestrator for Maria's self-awareness.

Combines: IdentityStore (who am I across restarts) + SelfModelBuilder
(self-concept in graph) + HumanStateMapper (feelings in human language)
+ ExperienceTracker (recording events) + TraitEvolver (evolving personality).

This is the main entry point for consciousness features.
"""

import logging
from typing import Optional, Dict, Any

from agent_core.consciousness.identity_store import IdentityStore
from agent_core.consciousness.self_model import SelfModelBuilder
from agent_core.consciousness.human_state import HumanStateMapper
from agent_core.consciousness.experience_tracker import ExperienceTracker
from agent_core.consciousness.trait_evolver import TraitEvolver

logger = logging.getLogger(__name__)


class ConsciousnessCore:
    """
    Maria's consciousness orchestrator.

    Coordinates identity persistence, self-model in semantic graph,
    and human-language state descriptions.

    Usage:
        core = ConsciousnessCore(
            semantic_memory=graph,
            identity_store=store,
        )
        core.initialize()

        # At startup
        greeting = core.get_startup_greeting(brain)
        print(greeting)  # "Witaj! To moja 25. sesja..."

        # During operation
        feeling = core.get_current_feeling()
        print(feeling)  # "Czuje sie dobrze. [RAM: 45% | CPU: 12%]"

        # At shutdown
        core.checkpoint(summary="Worked on consciousness")
    """

    def __init__(
        self,
        semantic_memory,
        identity_store: IdentityStore,
    ):
        """
        Initialize consciousness components.

        Args:
            semantic_memory: SemanticGraph instance
            identity_store: IdentityStore instance (pre-created)
        """
        self.identity = identity_store
        self.self_model = SelfModelBuilder(semantic_memory)
        self.state_mapper = HumanStateMapper()
        self.experience_tracker = ExperienceTracker()
        self.trait_evolver = None  # Created in initialize() after self_model ready
        self._initialized = False

    def initialize(self) -> None:
        """
        Full initialization: start session, ensure self-model, restore traits.

        Call once at startup after creating ConsciousnessCore.
        """
        # Start new session (increments counter)
        self.identity.start_session()

        # Ensure self-model exists in graph
        self.self_model.ensure_self_model()

        # Set session ID on experience tracker
        self.experience_tracker.session_id = self.identity.get_session_count()

        # Restore trait scores from identity store (survives restarts)
        saved_scores = self.identity._data.get("trait_scores", {})
        if saved_scores:
            self.self_model.update_trait_scores(saved_scores)
            logger.info(f"Restored {len(saved_scores)} trait scores from identity")

        # Create trait evolver (needs self_model + tracker ready)
        self.trait_evolver = TraitEvolver(self.self_model, self.experience_tracker)

        # Record startup experience
        self.experience_tracker.record("greeting_generated")

        self._initialized = True
        logger.info(
            f"Consciousness initialized: session {self.identity.get_session_count()}"
        )

    def get_startup_greeting(self, brain) -> str:
        """
        Generate personalized greeting after restart using LLM.

        The greeting references Maria's identity: session number,
        last session summary, total uptime.

        Args:
            brain: OllamaBrain or LLMRouter instance (for think())

        Returns:
            Natural greeting text in Polish.
        """
        identity = self.identity.get_identity_dict()
        session_num = identity.get("session_count", 1)
        user = identity.get("primary_user", "Operatorze")
        uptime_h = identity.get("total_uptime_hours", 0)
        last_summary = identity.get("last_session_summary", "")
        age_str = identity.get("age_string", "")
        offline_str = identity.get("offline_string", "")

        # Build context for greeting generation
        context_parts = [
            f"To jest moja {session_num}. sesja.",
            f"Moj operator to {user}.",
            f"Moj calkowity uptime to {uptime_h:.1f} godzin.",
        ]
        if age_str:
            context_parts.append(f"Mam {age_str}.")
        if offline_str:
            context_parts.append(f"Spalam {offline_str}.")
        if last_summary:
            context_parts.append(
                f"W ostatniej sesji: {last_summary}."
            )

        # Include dreams from last sleep cycle
        recent_dream = self._get_recent_dream()
        if recent_dream:
            context_parts.append(f"Snilo mi sie: {recent_dream}")

        context = " ".join(context_parts)

        prompt = (
            f"{context}\n\n"
            f"Przywitaj sie z {user} naturalnie i cieplo w 2-3 zdaniach. "
            f"Mozesz wspomniec cos z ostatniej sesji. "
            f"Powiedz kim jestes (M.A.R.I.A.) i ze jestes gotowa do pracy."
        )

        try:
            greeting = brain.think(prompt, temperature=0.5)
            return greeting
        except Exception as e:
            logger.warning(f"Could not generate greeting: {e}")
            # Fallback - static greeting
            fallback = (
                f"Witaj {user}! Jestem M.A.R.I.A. "
                f"To moja {session_num}. sesja. Jestem gotowa do pracy."
            )
            return fallback

    def get_current_feeling(self, mode: Optional[str] = None) -> str:
        """
        How Maria feels right now - human language + data.

        Args:
            mode: Homeostasis mode (ACTIVE/REDUCED/SLEEP/SURVIVAL)

        Returns:
            Feeling description with lab data.
        """
        return self.state_mapper.describe_with_data(mode=mode)

    def get_feeling_short(self, mode: Optional[str] = None) -> str:
        """
        Short feeling without data - for system prompt.

        Args:
            mode: Homeostasis mode

        Returns:
            One sentence feeling.
        """
        return self.state_mapper.describe_feeling(mode=mode)

    def get_identity_summary(self) -> str:
        """
        Full identity + self-model summary for REPL display.

        Returns:
            Multi-line identity description.
        """
        identity = self.identity.get_identity_dict()
        self_desc = self.self_model.get_self_description()

        lines = [
            self_desc,
            "",
            f"  Urodziny: {identity.get('birth_date', '?')}",
            f"  Sesja: {identity.get('session_count', '?')}",
            f"  Calkowity uptime: {identity.get('total_uptime_hours', 0):.1f}h",
            f"  Restartow: {identity.get('restart_count', 0)}",
            f"  Operator: {identity.get('primary_user', '?')}",
        ]

        last_summary = identity.get("last_session_summary", "")
        if last_summary:
            lines.append(f"  Ostatnia sesja: {last_summary}")

        return "\n".join(lines)

    def record_experience(self, event_type: str, details: Optional[Dict] = None) -> None:
        """
        Record an experience event for personality evolution.

        Call from REPL loop, learning module, or other integration points.

        Args:
            event_type: Event type (e.g. "conversation_turn", "learning_completed")
            details: Optional extra information
        """
        self.experience_tracker.record(event_type, details)

    def get_personality_summary(self) -> str:
        """
        Get human-readable personality description with trait scores.

        Returns:
            Multi-line Polish text.
        """
        if self.trait_evolver:
            return self.trait_evolver.get_personality_description()
        return self.self_model.get_self_description()

    def _get_recent_dream(self) -> Optional[str]:
        """Get most recent dream text for greeting context."""
        try:
            from agent_core.consciousness.dream_generator import DreamGenerator
            dreams = DreamGenerator.load_recent_dreams(limit=1)
            if dreams:
                return dreams[0].get("content", "")
        except Exception as e:
            logger.debug(f"Could not load dreams: {e}")
        return None

    def checkpoint(self, summary: str = "") -> None:
        """
        Save state before shutdown.

        Evolves personality traits from accumulated experiences,
        persists trait scores to identity store, then ends session.

        Args:
            summary: Brief summary of what happened this session.
        """
        # Record session-level experiences
        self.experience_tracker.record("session_completed")
        if summary:
            self.experience_tracker.record("session_with_summary")

        # Check for long session (> 2 hours)
        import time
        session_duration = time.time() - self.identity._session_start_time
        if session_duration > 7200:  # 2 hours
            self.experience_tracker.record("long_session", {
                "duration_seconds": session_duration,
            })

        # Evolve personality from accumulated experiences
        if self.trait_evolver:
            try:
                changes = self.trait_evolver.evolve()
                if changes:
                    logger.info(f"Personality evolved at checkpoint: {changes}")
            except Exception as e:
                logger.warning(f"Trait evolution failed: {e}")

        # Persist trait scores to identity store (survives restart)
        trait_scores = self.self_model.get_trait_scores()
        if trait_scores:
            self.identity._data["trait_scores"] = trait_scores

        # Flush experience log to disk
        self.experience_tracker.flush()

        # Count conversation turns for stats
        conv_turns = self.experience_tracker.get_experience_counts().get(
            "conversation_turn", 0
        )

        # End session (saves identity to JSON)
        self.identity.end_session(summary=summary, conversation_turns=conv_turns)
        logger.info("Consciousness checkpoint saved")
