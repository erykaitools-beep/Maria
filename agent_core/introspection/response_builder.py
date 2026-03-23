"""
Response Builder for State-Grounded Operator Responses.

Builds structured answers from Evidence facts. Works WITHOUT LLM.
LLM formatting is optional (layer 3b in the pipeline).

The grounded text is always available as fallback - even if LLM
halluccinates or fails, the operator gets data-based answer.
"""

from dataclasses import dataclass, field
from typing import List

from agent_core.introspection.evidence_collector import Evidence
from agent_core.introspection.query_router import ResponseMode


@dataclass
class GroundedResponse:
    """Response built from operational evidence."""
    mode: ResponseMode
    evidence: List[Evidence]
    text: str = ""              # Structured answer (no LLM, always works)
    formatted_text: str = ""    # LLM-formatted version (optional, nicer)
    sources: List[str] = field(default_factory=list)


class ResponseBuilder:
    """
    Builds grounded responses from evidence.

    Each response mode has a dedicated builder that formats
    evidence into structured Polish text with sources and confidence.

    LLM formatting is NOT done here - that's the caller's job (OllamaBrain).
    """

    def build(
        self,
        mode: ResponseMode,
        evidence: List[Evidence],
        user_question: str = "",
    ) -> GroundedResponse:
        """
        Build a grounded response from evidence.

        Returns GroundedResponse with text (always) and empty formatted_text
        (to be filled by optional LLM formatter).
        """
        if not evidence:
            return GroundedResponse(
                mode=mode,
                evidence=[],
                text="Brak danych operacyjnych do wyswietlenia.",
                sources=[],
            )

        builders = {
            ResponseMode.GROUNDED_STATUS: self._build_status,
            ResponseMode.GROUNDED_ERROR: self._build_error,
            ResponseMode.GROUNDED_LEARNING: self._build_learning,
            ResponseMode.GROUNDED_PLANNER: self._build_planner,
        }

        builder_fn = builders.get(mode, self._build_status)
        text = builder_fn(evidence)

        # Collect unique sources
        sources = list(dict.fromkeys(e.source for e in evidence))

        # Append sources
        if sources:
            text += f"\nZrodlo: {', '.join(sources)}"

        return GroundedResponse(
            mode=mode,
            evidence=evidence,
            text=text,
            sources=sources,
        )

    def _build_status(self, evidence: List[Evidence]) -> str:
        """Build general status response."""
        lines = []

        mode = self._find(evidence, "homeostasis.mode")
        health = self._find(evidence, "homeostasis.health")
        if mode or health:
            parts = []
            if mode:
                parts.append(f"Tryb: {mode.value}")
            if health:
                parts.append(f"zdrowie: {health.value}")
            lines.append(". ".join(parts) + ".")

        action = self._find(evidence, "planner.last_action")
        goal = self._find(evidence, "planner.last_goal")
        if action:
            line = f"Ostatnia akcja planner: {action.value}"
            if goal:
                line += f" (cel: {goal.value})"
            lines.append(line + ".")

        files = self._find(evidence, "learning.total_files")
        completed = self._find(evidence, "learning.completed")
        if files:
            line = f"Pliki naukowe: {files.value}"
            if completed:
                line += f" ({completed.value} ukonczonych)"
            lines.append(line + ".")

        calls = self._find(evidence, "llm.total_calls_24h")
        if calls:
            lines.append(f"LLM: {calls.value} wywolan/24h.")

        return "\n".join(lines) if lines else "Stan: brak danych."

    def _build_error(self, evidence: List[Evidence]) -> str:
        """Build error diagnostic response."""
        lines = []

        # Repeated failures are the most important
        failures = [e for e in evidence if "repeated_failure" in e.key]
        if failures:
            for f in failures:
                lines.append(f"Problem: {f.key.split('.')[-1]} - {f.value}.")

        # Autonomy blocks
        blocks = [e for e in evidence if "autonomy.block" in e.key]
        if blocks:
            for b in blocks:
                rule = b.key.split(".")[-1]
                lines.append(f"Blokada K7: {rule} - {b.value}.")

        # LLM errors
        llm_errors = [e for e in evidence if e.key == "llm.error"]
        if llm_errors:
            lines.append(f"Bledy LLM ({len(llm_errors)}):")
            for err in llm_errors[:3]:
                lines.append(f"  - {err.value}")

        # Homeostasis context
        mode = self._find(evidence, "homeostasis.mode")
        health = self._find(evidence, "homeostasis.health")
        if mode or health:
            parts = []
            if mode:
                parts.append(f"tryb: {mode.value}")
            if health:
                parts.append(f"zdrowie: {health.value}")
            lines.append(f"Kontekst: {', '.join(parts)}.")

        # Confidence assessment
        high_confidence = [e for e in evidence if e.confidence == "high"]
        confidence = "wysoka" if len(high_confidence) > len(evidence) // 2 else "srednia"
        lines.append(f"Pewnosc: {confidence}.")

        return "\n".join(lines) if lines else "Brak wykrytych problemow."

    def _build_learning(self, evidence: List[Evidence]) -> str:
        """Build learning progress response."""
        lines = []

        files = self._find(evidence, "learning.total_files")
        completed = self._find(evidence, "learning.completed")
        if files:
            line = f"Pliki naukowe: {files.value}"
            if completed:
                line += f" ({completed.value} ukonczonych)"
            lines.append(line + ".")

        exam = self._find(evidence, "learning.last_exam")
        if exam:
            lines.append(f"Ostatni egzamin: {exam.value}.")

        retention = self._find(evidence, "evaluation.retention_rate")
        if retention:
            lines.append(f"Retention rate: {retention.value}.")

        velocity = self._find(evidence, "evaluation.learning_velocity")
        if velocity:
            lines.append(f"Predkosc nauki: {velocity.value}.")

        action = self._find(evidence, "planner.last_action")
        goal = self._find(evidence, "planner.last_goal")
        if action:
            line = f"Aktualna akcja: {action.value}"
            if goal:
                line += f" ({goal.value})"
            lines.append(line + ".")

        return "\n".join(lines) if lines else "Brak danych o nauce."

    def _build_planner(self, evidence: List[Evidence]) -> str:
        """Build planner status response."""
        lines = []

        action = self._find(evidence, "planner.last_action")
        goal = self._find(evidence, "planner.last_goal")
        status = self._find(evidence, "planner.last_status")
        if action:
            line = f"Ostatnia akcja: {action.value}"
            if status:
                line += f" (status: {status.value})"
            lines.append(line + ".")
        if goal:
            lines.append(f"Cel: {goal.value}.")

        # Failures
        failures = [e for e in evidence if "repeated_failure" in e.key]
        if failures:
            for f in failures:
                lines.append(f"Powtarzajacy sie problem: {f.key.split('.')[-1]} - {f.value}.")

        # Goals
        goals = [e for e in evidence if e.key.startswith("goal.")]
        if goals:
            lines.append(f"Aktywne cele ({len(goals)}):")
            for g in goals:
                lines.append(f"  - {g.value}")

        return "\n".join(lines) if lines else "Brak danych o plannerze."

    @staticmethod
    def _find(evidence: List[Evidence], key: str):
        """Find first evidence with matching key."""
        for e in evidence:
            if e.key == key:
                return e
        return None
