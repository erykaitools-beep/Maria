"""
Teacher Adapter - mapuje decyzje TeacherAgent na PerceptionEvent.

Obsluguje:
- teacher_decision - decyzja o strategii nauki
- teacher_session_complete - zakonczenie sesji nauki

Kontrakt: docs/CONTRACTS.md - Event Type Registry
"""

from typing import Any, Dict, List, Optional

from agent_core.perception.event import (
    PerceptionEvent,
    PerceptionSource,
    create_event,
)


class TeacherAdapter:
    """Konwertuje decyzje TeacherAgent na PerceptionEvent."""

    @staticmethod
    def from_decision(
        strategy_type: str,
        target_file_id: str,
        reason: Optional[str] = None,
        iteration: Optional[int] = None,
        parent_event_id: Optional[str] = None,
    ) -> PerceptionEvent:
        """
        Decyzja o strategii -> PerceptionEvent(teacher_decision).

        Args:
            strategy_type: Typ strategii (np. "continue", "new_file", "review", "retry")
            target_file_id: Plik docelowy
            reason: opcjonalny powod decyzji
            iteration: opcjonalny numer iteracji w sesji
            parent_event_id: opcjonalny event_id przyczyny
        """
        payload: Dict[str, Any] = {
            "strategy_type": strategy_type,
            "target_file_id": target_file_id,
        }
        if reason is not None:
            payload["reason"] = reason
        if iteration is not None:
            payload["iteration"] = iteration

        return create_event(
            source=PerceptionSource.TEACHER,
            event_type="teacher_decision",
            payload=payload,
            parent_event_id=parent_event_id,
        )

    @staticmethod
    def from_session_complete(
        chunks_learned: int,
        exams_run: int,
        exams_passed: int,
        errors: Optional[List[str]] = None,
        parent_event_id: Optional[str] = None,
    ) -> PerceptionEvent:
        """
        Zakonczenie sesji nauki -> PerceptionEvent(teacher_session_complete).

        Args:
            chunks_learned: Liczba nauczonych chunkow
            exams_run: Liczba przeprowadzonych egzaminow
            exams_passed: Liczba zdanych egzaminow
            errors: opcjonalna lista bledow
            parent_event_id: opcjonalny event_id przyczyny
        """
        payload: Dict[str, Any] = {
            "chunks_learned": chunks_learned,
            "exams_run": exams_run,
            "exams_passed": exams_passed,
        }
        if errors:
            payload["errors"] = errors

        return create_event(
            source=PerceptionSource.TEACHER,
            event_type="teacher_session_complete",
            payload=payload,
            parent_event_id=parent_event_id,
        )
