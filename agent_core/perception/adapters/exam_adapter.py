"""
Exam Adapter - mapuje wyniki egzaminow na PerceptionEvent.

Obsluguje:
- exam_result - wynik egzaminu

Kontrakt: docs/CONTRACTS.md - Event Type Registry
"""

from typing import Optional

from agent_core.perception.event import (
    PerceptionEvent,
    PerceptionSource,
    create_event,
)


class ExamAdapter:
    """Konwertuje wyniki egzaminow na PerceptionEvent."""

    @staticmethod
    def from_exam_result(
        file_id: str,
        score: float,
        passed: bool,
        attempt: int,
        num_questions: Optional[int] = None,
        parent_event_id: Optional[str] = None,
    ) -> PerceptionEvent:
        """
        Wynik run_exam_if_ready() -> PerceptionEvent(exam_result).

        Args:
            file_id: Identyfikator pliku
            score: Wynik egzaminu (0.0-1.0)
            passed: Czy zdany
            attempt: Numer proby
            num_questions: opcjonalna liczba pytan
            parent_event_id: opcjonalny event_id przyczyny (np. teacher_decision)
        """
        payload = {
            "file_id": file_id,
            "score": score,
            "passed": passed,
            "attempt": attempt,
        }
        if num_questions is not None:
            payload["num_questions"] = num_questions

        return create_event(
            source=PerceptionSource.EXAM,
            event_type="exam_result",
            payload=payload,
            parent_event_id=parent_event_id,
        )
