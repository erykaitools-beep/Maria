"""
Expert Bridge - targeted LLM queries using knowledge audit context.

Phase 4 of Learning Upgrade. Uses context_prompt from GapPlanner
("Maria wie X, potrzebuje Y") instead of generic questions.

Pipeline: topic -> audit -> gap plan -> enhanced prompt -> LLM -> response.

Cascade: the caller provides llm_fn (typically LLMRouter.ask_encyclopedia
which cascades Codex -> NIM -> Ollama).

Zero side effects: ExpertBridge only generates the response.
Saving to input/ and bulletin updates are done by the caller (Phase 5).
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from agent_core.bulletin.knowledge_auditor import AuditReport, KnowledgeAuditor
from agent_core.bulletin.gap_planner import GapAction, GapPlan, GapPlanner

logger = logging.getLogger(__name__)

# Minimum useful response length (chars)
MIN_RESPONSE_LENGTH = 100

# Maximum prompt length to avoid token overflow
MAX_PROMPT_LENGTH = 3000


@dataclass
class ExpertResponse:
    """Result of an expert bridge query."""
    success: bool
    topic: str
    response: str = ""
    context_prompt: str = ""     # The prompt that was sent
    gap_action: str = ""         # GapAction that triggered this
    reason: str = ""             # Why this action was chosen
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "topic": self.topic,
            "response_length": len(self.response),
            "context_prompt_length": len(self.context_prompt),
            "gap_action": self.gap_action,
            "reason": self.reason,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


# System wrapper for educational output
_SYSTEM_WRAPPER = (
    "Jestes ekspertem edukacyjnym. Twoje zadanie to przygotowac "
    "material edukacyjny dla systemu uczacego sie (M.A.R.I.A.).\n\n"
    "Zasady:\n"
    "- Pisz po polsku, jasno i precyzyjnie\n"
    "- Uzywaj faktow, nie opinii\n"
    "- Podaj definicje, przyklady, kluczowe pojecia\n"
    "- Ustrukturyzuj tekst (naglowki, punkty)\n"
    "- Dlugosc: 500-2000 slow\n\n"
)


class ExpertBridge:
    """
    Sends targeted knowledge requests to strong LLMs.

    Uses audit context from GapPlanner to build precise prompts
    instead of generic "explain topic X" queries.

    The caller provides llm_fn which should accept (prompt: str) -> str.
    Typically this is LLMRouter.ask_encyclopedia or a wrapped version.
    """

    def __init__(self):
        self._llm_fn: Optional[Callable[[str], str]] = None
        self._auditor: Optional[KnowledgeAuditor] = None
        self._gap_planner: Optional[GapPlanner] = None

    def set_llm_fn(self, fn: Callable[[str], str]) -> None:
        """Set the LLM function (prompt -> response)."""
        self._llm_fn = fn

    def set_auditor(self, auditor: KnowledgeAuditor) -> None:
        self._auditor = auditor

    def set_gap_planner(self, planner: GapPlanner) -> None:
        self._gap_planner = planner

    # ----------------------------------------------------------
    # Main API
    # ----------------------------------------------------------

    def ask_about_topic(
        self,
        topic: str,
        goal_description: str = "",
    ) -> ExpertResponse:
        """
        Full pipeline: audit -> gap plan -> expert query -> response.

        If audit shows no gaps, returns success=False (no action needed).
        If gap plan recommends ASK_EXPERT or FETCH_MATERIAL, sends
        a targeted prompt to the LLM.

        Args:
            topic: Normalized topic string
            goal_description: Optional goal context

        Returns:
            ExpertResponse with the LLM answer (or failure reason).
        """
        if not self._llm_fn:
            return ExpertResponse(
                success=False, topic=topic, reason="no_llm_fn",
            )

        # Step 0: Check if expert material already exists for this topic
        if self._expert_file_exists(topic):
            return ExpertResponse(
                success=False, topic=topic,
                reason="expert_material_already_exists",
            )

        # Step 1: Audit (if auditor available)
        audit = None
        if self._auditor:
            try:
                audit = self._auditor.audit_topic(topic)
            except Exception as e:
                logger.debug(f"[ExpertBridge] Audit failed for '{topic}': {e}")

        # Step 2: Gap plan (if planner available + audit succeeded)
        gap_plan = None
        if audit and self._gap_planner:
            try:
                gap_plan = self._gap_planner.plan_for_topic(audit, goal_description)
            except Exception as e:
                logger.debug(f"[ExpertBridge] Gap plan failed: {e}")

        # Step 3: Decide whether to proceed
        if gap_plan and gap_plan.action == GapAction.NO_ACTION:
            return ExpertResponse(
                success=False, topic=topic,
                reason="topic_well_covered",
                gap_action=gap_plan.action.value,
            )

        # Step 4: Build prompt
        if gap_plan and gap_plan.context_prompt:
            # Use the targeted prompt from gap planner
            prompt = self._enhance_prompt(gap_plan.context_prompt, topic)
            context_prompt = gap_plan.context_prompt
        elif audit and not audit.known:
            # No knowledge at all - ask from scratch
            prompt = self._build_from_scratch_prompt(topic, goal_description)
            context_prompt = prompt
        else:
            # Fallback: generic but still structured prompt
            prompt = self._build_generic_prompt(topic, goal_description)
            context_prompt = prompt

        # Step 5: Call LLM
        start = time.time()
        try:
            response = self._llm_fn(prompt)
            duration_ms = (time.time() - start) * 1000
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            return ExpertResponse(
                success=False, topic=topic,
                reason=f"llm_error: {e}",
                context_prompt=context_prompt,
                duration_ms=duration_ms,
                gap_action=gap_plan.action.value if gap_plan else "",
            )

        if not response or len(response.strip()) < MIN_RESPONSE_LENGTH:
            return ExpertResponse(
                success=False, topic=topic,
                reason="response_too_short",
                response=response or "",
                context_prompt=context_prompt,
                duration_ms=duration_ms,
                gap_action=gap_plan.action.value if gap_plan else "",
            )

        # Step 6: Return structured response
        return ExpertResponse(
            success=True,
            topic=topic,
            response=response.strip(),
            context_prompt=context_prompt,
            gap_action=gap_plan.action.value if gap_plan else "direct",
            reason=gap_plan.reason if gap_plan else "direct_query",
            duration_ms=duration_ms,
            metadata={
                "audit_known": audit.known if audit else None,
                "audit_confidence": audit.avg_confidence if audit else None,
                "audit_files": audit.files_count if audit else None,
                "gap_count": len(audit.gaps) if audit else 0,
            },
        )

    def ask_with_context(
        self,
        topic: str,
        context_prompt: str,
    ) -> ExpertResponse:
        """
        Direct call with a pre-built context prompt (skip audit).

        Use when the caller already has a context_prompt from GapPlanner
        (e.g., from a bulletin entry's metadata).
        """
        if not self._llm_fn:
            return ExpertResponse(
                success=False, topic=topic, reason="no_llm_fn",
            )

        prompt = self._enhance_prompt(context_prompt, topic)

        start = time.time()
        try:
            response = self._llm_fn(prompt)
            duration_ms = (time.time() - start) * 1000
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            return ExpertResponse(
                success=False, topic=topic,
                reason=f"llm_error: {e}",
                context_prompt=context_prompt,
                duration_ms=duration_ms,
            )

        if not response or len(response.strip()) < MIN_RESPONSE_LENGTH:
            return ExpertResponse(
                success=False, topic=topic,
                reason="response_too_short",
                response=response or "",
                context_prompt=context_prompt,
                duration_ms=duration_ms,
            )

        return ExpertResponse(
            success=True,
            topic=topic,
            response=response.strip(),
            context_prompt=context_prompt,
            gap_action="direct",
            reason="direct_context_query",
            duration_ms=duration_ms,
        )

    # ----------------------------------------------------------
    # Dedup
    # ----------------------------------------------------------

    @staticmethod
    def _expert_file_exists(topic: str) -> bool:
        """Check if input/expert_{topic}.txt already has substantial content."""
        import re
        from pathlib import Path

        slug = re.sub(r'[^a-z0-9]+', '_', topic.lower().strip())[:60].strip('_')
        filepath = Path(__file__).resolve().parents[2] / "input" / f"expert_{slug}.txt"
        try:
            if filepath.exists() and filepath.stat().st_size > 5000:
                logger.info(
                    f"[ExpertBridge] Skipping '{topic}': expert file "
                    f"already has {filepath.stat().st_size} bytes"
                )
                return True
        except OSError:
            pass
        return False

    # ----------------------------------------------------------
    # Prompt builders
    # ----------------------------------------------------------

    def _enhance_prompt(self, context_prompt: str, topic: str) -> str:
        """Wrap gap planner's context_prompt with system instructions."""
        prompt = (
            f"{_SYSTEM_WRAPPER}"
            f"Kontekst:\n{context_prompt}\n\n"
            f"Przygotuj material edukacyjny o temacie: {topic}\n"
            f"Uwzglednij powyzszy kontekst - skup sie na lukach w wiedzy."
        )
        return prompt[:MAX_PROMPT_LENGTH]

    def _build_from_scratch_prompt(
        self, topic: str, goal_description: str
    ) -> str:
        """Build prompt for a topic Maria knows nothing about."""
        parts = [
            _SYSTEM_WRAPPER,
            f"Maria nie ma zadnej wiedzy o temacie: '{topic}'.\n",
            "Przygotuj kompletny material edukacyjny od podstaw:\n",
            "1. Definicja i kluczowe pojecia\n",
            "2. Podstawowe zasady/mechanizmy\n",
            "3. Przyklady zastosowania\n",
            "4. Powiazania z innymi dziedzinami\n",
        ]
        if goal_description:
            parts.append(f"\nCel nauki: {goal_description}\n")
        return "".join(parts)[:MAX_PROMPT_LENGTH]

    def _build_generic_prompt(
        self, topic: str, goal_description: str
    ) -> str:
        """Fallback prompt when audit/gap planner are unavailable."""
        parts = [
            _SYSTEM_WRAPPER,
            f"Przygotuj material edukacyjny o temacie: '{topic}'.\n",
            "Uwzglednij:\n",
            "- Definicje i kluczowe pojecia\n",
            "- Najwazniejsze fakty\n",
            "- Przyklady\n",
        ]
        if goal_description:
            parts.append(f"\nCel nauki: {goal_description}\n")
        return "".join(parts)[:MAX_PROMPT_LENGTH]
