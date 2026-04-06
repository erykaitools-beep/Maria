"""
PerceptionEvent - Uniwersalny format zdarzenia percepcji.

Jeden format dla WSZYSTKICH bodzcow w systemie M.A.R.I.A.:
sensory, user input, nauka, egzaminy, swiadomosc, teacher, system.

Kontrakt: docs/CONTRACTS.md - Kontrakt 1: Unified Perception
ADR-009: Tick Aggregator (zdarzenia przechodza przez tick loop, nie event bus)
"""

import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class PerceptionSource(Enum):
    """Zrodlo zdarzenia percepcji."""
    SENSOR = "sensor"                # Homeostasis sensors (5x)
    USER = "user"                    # REPL input, Web UI chat
    LEARNING = "learning"            # learn_next_chunk results, file scan
    EXAM = "exam"                    # run_exam_if_ready results
    CONSCIOUSNESS = "consciousness"  # trait evolution, sleep, dreams
    TEACHER = "teacher"              # TeacherAgent decisions
    PLANNER = "planner"              # PlannerCore decisions (Warstwa 2)
    SYSTEM = "system"                # Mode changes, alerts, startup/shutdown


# Domyslne wartosci per event_type (z Event Type Registry w CONTRACTS.md)
# Format: event_type -> (default_priority, default_ttl, dedupable)
EVENT_TYPE_DEFAULTS: Dict[str, tuple] = {
    # SENSOR events
    "resource_reading":          (0.3, 5.0, True),
    "cognitive_reading":         (0.3, 5.0, True),
    "thermal_reading":           (0.3, 5.0, True),
    "power_reading":             (0.3, 5.0, True),
    "time_reading":              (0.3, 5.0, True),
    # USER events
    "user_message":              (0.9, 0.0, False),
    "user_command":              (0.9, 0.0, False),
    # LEARNING events
    "chunk_learned":             (0.7, 300.0, False),
    "file_scan_result":          (0.5, 300.0, True),
    "sandbox_promoted":          (0.7, 300.0, False),
    "sandbox_discarded":         (0.3, 300.0, False),
    # EXAM events
    "exam_result":               (0.8, 300.0, False),
    # TEACHER events
    "teacher_decision":          (0.5, 300.0, False),
    "teacher_session_complete":  (0.5, 300.0, False),
    # CONSCIOUSNESS events
    "trait_emerged":             (0.5, 300.0, False),
    "trait_faded":               (0.5, 300.0, False),
    "dream_generated":           (0.5, 300.0, False),
    "sleep_cycle":               (0.5, 300.0, False),
    # PLANNER events (Warstwa 2)
    "planner_decision":          (0.5, 300.0, False),
    "planner_cycle_complete":    (0.3, 60.0, True),
    # VISION events (Phase 8.5 - VisionPerceptionAdapter)
    "vision_percept":            (0.3, 5.0, True),   # Regular tick, dedupable
    "vision_motion":             (0.7, 60.0, False),  # Motion detected
    "vision_alert":              (0.9, 0.0, False),   # Danger alert, high priority
    "vision_health":             (0.4, 30.0, True),   # Health status change, dedupable
    # SYSTEM events
    "mode_change":               (0.8, 0.0, False),
    "alert":                     (1.0, 0.0, False),
    "goal_created":              (0.5, 0.0, False),
    "goal_achieved":             (0.5, 0.0, False),
}


@dataclass(frozen=True)
class PerceptionEvent:
    """
    Uniwersalny format zdarzenia percepcji.

    Frozen dataclass - zdarzenia sa niemutowalne po utworzeniu.
    Kazde zdarzenie ma unikalny event_id (UUID4).
    Lancuchy przyczynowe sledzime przez parent_event_id.
    """
    event_id: str                    # UUID4 - unikalny identyfikator
    source: PerceptionSource         # Kto wygenerwal zdarzenie
    event_type: str                  # np. "resource_reading", "user_message"
    priority: float                  # 0.0 (ignoruj) do 1.0 (reaguj natychmiast)
    timestamp: float                 # time.time()
    payload: Dict[str, Any]          # Dane zrodlowe (struktura wg Event Type Registry)
    ttl: float                       # Sekundy do wygasniecia (0 = bez limitu)
    parent_event_id: Optional[str]   # event_id zdarzenia-przyczyny (lancuch kauzalny)

    def is_expired(self, now: Optional[float] = None) -> bool:
        """Sprawdz czy zdarzenie wygaslo (ttl > 0 i czas minal)."""
        if self.ttl <= 0:
            return False
        if now is None:
            now = time.time()
        return (now - self.timestamp) > self.ttl

    @property
    def is_dedupable(self) -> bool:
        """Sprawdz czy event_type pozwala na deduplikacje."""
        defaults = EVENT_TYPE_DEFAULTS.get(self.event_type)
        if defaults is None:
            return False
        return defaults[2]


def create_event(
    source: PerceptionSource,
    event_type: str,
    payload: Dict[str, Any],
    priority: Optional[float] = None,
    ttl: Optional[float] = None,
    parent_event_id: Optional[str] = None,
    timestamp: Optional[float] = None,
    event_id: Optional[str] = None,
) -> PerceptionEvent:
    """
    Fabryka zdarzen percepcji.

    Uzywa domyslnych wartosci priority i ttl z Event Type Registry
    jesli nie podano jawnie. Generuje event_id i timestamp automatycznie.

    Args:
        source: Zrodlo zdarzenia (PerceptionSource enum)
        event_type: Typ zdarzenia (z Event Type Registry)
        payload: Dane zdarzenia
        priority: Priorytet 0.0-1.0 (domyslny z registry)
        ttl: Czas zycia w sekundach (domyslny z registry, 0 = bez limitu)
        parent_event_id: event_id zdarzenia-przyczyny
        timestamp: Czas zdarzenia (domyslnie time.time())
        event_id: Identyfikator (domyslnie uuid4)

    Returns:
        PerceptionEvent z wypelnionymi polami
    """
    defaults = EVENT_TYPE_DEFAULTS.get(event_type, (0.5, 0.0, False))
    default_priority, default_ttl, _ = defaults

    return PerceptionEvent(
        event_id=event_id or str(uuid.uuid4()),
        source=source,
        event_type=event_type,
        priority=priority if priority is not None else default_priority,
        timestamp=timestamp if timestamp is not None else time.time(),
        payload=payload,
        ttl=ttl if ttl is not None else default_ttl,
        parent_event_id=parent_event_id,
    )
