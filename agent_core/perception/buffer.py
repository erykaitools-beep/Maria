"""
PerceptionBuffer - Sliding window ostatnich zdarzen percepcji.

Bufor oparty na collections.deque(maxlen=200). Nie kolejka (FIFO z konsumpcja),
lecz okno slizgowe (sliding window) - zdarzenia sa dostepne do odczytu
dopoki nie wypadna z okna.

Kontrakt: docs/CONTRACTS.md - Kontrakt 1: Unified Perception
ADR-009: Tick Aggregator (bufor jest czescia tick loop, nie event bus)
"""

import time
from collections import deque
from typing import Deque, List, Optional

from agent_core.perception.event import PerceptionEvent, PerceptionSource


class PerceptionBuffer:
    """
    Sliding window ostatnich zdarzen percepcji.

    Thread-safety: deque z maxlen jest thread-safe dla append/popleft w CPython
    (GIL gwarantuje atomowosc). Iteracja po buforze NIE jest thread-safe,
    ale bufor jest czytany TYLKO z watku tick loop (ADR-009).
    """

    def __init__(self, maxlen: int = 200):
        """
        Args:
            maxlen: Maksymalna liczba zdarzen w buforze (domyslnie 200 wg kontraktu).
        """
        self._buffer: Deque[PerceptionEvent] = deque(maxlen=maxlen)
        self._maxlen = maxlen

    @property
    def maxlen(self) -> int:
        """Maksymalny rozmiar bufora."""
        return self._maxlen

    def __len__(self) -> int:
        """Liczba zdarzen w buforze."""
        return len(self._buffer)

    def push(self, event: PerceptionEvent) -> None:
        """
        Dodaj zdarzenie do bufora.

        Jesli bufor jest pelny, najstarsze zdarzenie wypada automatycznie (deque maxlen).
        """
        self._buffer.append(event)

    def push_many(self, events: List[PerceptionEvent]) -> None:
        """Dodaj wiele zdarzen naraz (zachowuje kolejnosc)."""
        for event in events:
            self._buffer.append(event)

    def get_recent(
        self,
        n: int = 10,
        source: Optional[PerceptionSource] = None,
        event_type: Optional[str] = None,
    ) -> List[PerceptionEvent]:
        """
        Pobierz N ostatnich zdarzen, opcjonalnie filtruj po zrodle lub typie.

        Args:
            n: Maksymalna liczba zdarzen do zwrocenia
            source: Filtruj po zrodle (opcjonalnie)
            event_type: Filtruj po typie zdarzenia (opcjonalnie)

        Returns:
            Lista zdarzen (najnowsze ostatnie) posortowana chronologicznie
        """
        result = []
        # Iterujemy od konca (najnowsze najpierw)
        for event in reversed(self._buffer):
            if source is not None and event.source != source:
                continue
            if event_type is not None and event.event_type != event_type:
                continue
            result.append(event)
            if len(result) >= n:
                break
        # Zwracamy w kolejnosci chronologicznej (najstarsze pierwsze)
        result.reverse()
        return result

    def get_by_priority(self, min_priority: float = 0.5) -> List[PerceptionEvent]:
        """
        Pobierz zdarzenia o priorytecie >= min_priority.

        Args:
            min_priority: Minimalny priorytet (domyslnie 0.5)

        Returns:
            Lista zdarzen posortowana chronologicznie
        """
        return [e for e in self._buffer if e.priority >= min_priority]

    def get_by_event_type(self, event_type: str) -> List[PerceptionEvent]:
        """
        Pobierz wszystkie zdarzenia danego typu z bufora.

        Args:
            event_type: Typ zdarzenia (np. "resource_reading")

        Returns:
            Lista zdarzen posortowana chronologicznie
        """
        return [e for e in self._buffer if e.event_type == event_type]

    def get_children(self, parent_event_id: str) -> List[PerceptionEvent]:
        """
        Pobierz zdarzenia bedace bezposrednimi potomkami danego zdarzenia.

        Args:
            parent_event_id: event_id zdarzenia-rodzica

        Returns:
            Lista zdarzen-potomkow
        """
        return [e for e in self._buffer if e.parent_event_id == parent_event_id]

    def drain_expired(self, now: Optional[float] = None) -> int:
        """
        Usun wygasle zdarzenia (ttl > 0 i czas minal).

        Uwaga: tworzy nowy deque bez wygaslych (deque nie wspiera usuwania ze srodka).

        Args:
            now: Czas odniesienia (domyslnie time.time())

        Returns:
            Liczba usunietych zdarzen
        """
        if now is None:
            now = time.time()

        original_len = len(self._buffer)
        alive = [e for e in self._buffer if not e.is_expired(now)]
        self._buffer.clear()
        self._buffer.extend(alive)
        return original_len - len(self._buffer)

    def get_all(self) -> List[PerceptionEvent]:
        """Pobierz wszystkie zdarzenia z bufora (kopia listy)."""
        return list(self._buffer)

    def clear(self) -> None:
        """Wyczysc bufor."""
        self._buffer.clear()

    def latest(self) -> Optional[PerceptionEvent]:
        """Pobierz najnowsze zdarzenie lub None jesli bufor pusty."""
        if not self._buffer:
            return None
        return self._buffer[-1]

    def stats(self) -> dict:
        """
        Statystyki bufora (do diagnostyki / /homeostasis command).

        Returns:
            Slownik ze statystykami
        """
        by_source: dict = {}
        by_type: dict = {}
        for event in self._buffer:
            src = event.source.value
            by_source[src] = by_source.get(src, 0) + 1
            by_type[event.event_type] = by_type.get(event.event_type, 0) + 1

        return {
            "size": len(self._buffer),
            "maxlen": self._maxlen,
            "by_source": by_source,
            "by_type": by_type,
        }
