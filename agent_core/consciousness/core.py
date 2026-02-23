"""
ConsciousnessCore - Orchestrator for Maria's self-awareness.

Combines: IdentityStore (who am I across restarts) + SelfModelBuilder
(self-concept in graph) + HumanStateMapper (feelings in human language).

This is the main entry point for consciousness features.
"""

import logging
from typing import Optional, Dict, Any

from agent_core.consciousness.identity_store import IdentityStore
from agent_core.consciousness.self_model import SelfModelBuilder
from agent_core.consciousness.human_state import HumanStateMapper

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
        print(greeting)  # "Witaj Eryk! To moja 25. sesja..."

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
        self._initialized = False

    def initialize(self) -> None:
        """
        Full initialization: start session, ensure self-model.

        Call once at startup after creating ConsciousnessCore.
        """
        # Start new session (increments counter)
        self.identity.start_session()

        # Ensure self-model exists in graph
        self.self_model.ensure_self_model()

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

        # Build context for greeting generation
        context_parts = [
            f"To jest moja {session_num}. sesja.",
            f"Moj operator to {user}.",
            f"Moj calkowity uptime to {uptime_h:.1f} godzin.",
        ]
        if last_summary:
            context_parts.append(
                f"W ostatniej sesji: {last_summary}."
            )

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

    def checkpoint(self, summary: str = "") -> None:
        """
        Save state before shutdown.

        Args:
            summary: Brief summary of what happened this session.
        """
        self.identity.end_session(summary=summary)
        logger.info("Consciousness checkpoint saved")
