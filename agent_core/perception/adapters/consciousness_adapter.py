"""
Consciousness Adapter - mapuje zdarzenia swiadomosci na PerceptionEvent.

Obsluguje:
- trait_emerged - cecha osobowosci pojawila sie (score >= EMERGENCE_THRESHOLD)
- trait_faded - cecha osobowosci zniknela (score < EMERGENCE_THRESHOLD)
- dream_generated - wygenerowane sny podczas SLEEP
- sleep_cycle - zakonczony cykl snu

Kontrakt: docs/CONTRACTS.md - Event Type Registry
"""

from typing import Any, Dict, List, Optional

from agent_core.perception.event import (
    PerceptionEvent,
    PerceptionSource,
    create_event,
)


class ConsciousnessAdapter:
    """Konwertuje zdarzenia swiadomosci na PerceptionEvent."""

    @staticmethod
    def from_trait_emerged(
        trait: str,
        score: float,
        previous_score: Optional[float] = None,
        parent_event_id: Optional[str] = None,
    ) -> PerceptionEvent:
        """
        Cecha przekroczyla EMERGENCE_THRESHOLD -> PerceptionEvent(trait_emerged).

        Args:
            trait: Nazwa cechy (np. "ciekawska", "wytrwala")
            score: Aktualny wynik cechy (0.0-1.0)
            previous_score: opcjonalny poprzedni wynik
            parent_event_id: opcjonalny event_id przyczyny
        """
        payload: Dict[str, Any] = {
            "trait": trait,
            "score": score,
        }
        if previous_score is not None:
            payload["previous_score"] = previous_score

        return create_event(
            source=PerceptionSource.CONSCIOUSNESS,
            event_type="trait_emerged",
            payload=payload,
            parent_event_id=parent_event_id,
        )

    @staticmethod
    def from_trait_faded(
        trait: str,
        score: float,
        previous_score: Optional[float] = None,
        parent_event_id: Optional[str] = None,
    ) -> PerceptionEvent:
        """
        Cecha spadla ponizej EMERGENCE_THRESHOLD -> PerceptionEvent(trait_faded).

        Args:
            trait: Nazwa cechy
            score: Aktualny wynik cechy (0.0-1.0)
            previous_score: opcjonalny poprzedni wynik
            parent_event_id: opcjonalny event_id przyczyny
        """
        payload: Dict[str, Any] = {
            "trait": trait,
            "score": score,
        }
        if previous_score is not None:
            payload["previous_score"] = previous_score

        return create_event(
            source=PerceptionSource.CONSCIOUSNESS,
            event_type="trait_faded",
            payload=payload,
            parent_event_id=parent_event_id,
        )

    @staticmethod
    def from_dream_generated(
        dream_count: int,
        session_id: str,
        themes: Optional[List[str]] = None,
        parent_event_id: Optional[str] = None,
    ) -> PerceptionEvent:
        """
        Sny wygenerowane w fazie REM -> PerceptionEvent(dream_generated).

        Args:
            dream_count: Liczba wygenerowanych snow
            session_id: Identyfikator sesji snu
            themes: opcjonalna lista tematow snow
            parent_event_id: opcjonalny event_id przyczyny (np. sleep_cycle)
        """
        payload: Dict[str, Any] = {
            "dream_count": dream_count,
            "session_id": session_id,
        }
        if themes is not None:
            payload["themes"] = themes

        return create_event(
            source=PerceptionSource.CONSCIOUSNESS,
            event_type="dream_generated",
            payload=payload,
            parent_event_id=parent_event_id,
        )

    @staticmethod
    def from_sleep_cycle(
        phases_completed: int,
        dream_count: Optional[int] = None,
        parent_event_id: Optional[str] = None,
    ) -> PerceptionEvent:
        """
        Zakonczony cykl snu -> PerceptionEvent(sleep_cycle).

        Args:
            phases_completed: Liczba zakonczonych faz (nrem1, nrem2, nrem3, rem)
            dream_count: opcjonalna liczba snow z fazy REM
            parent_event_id: opcjonalny event_id przyczyny
        """
        payload: Dict[str, Any] = {
            "phases_completed": phases_completed,
        }
        if dream_count is not None:
            payload["dream_count"] = dream_count

        return create_event(
            source=PerceptionSource.CONSCIOUSNESS,
            event_type="sleep_cycle",
            payload=payload,
            parent_event_id=parent_event_id,
        )
