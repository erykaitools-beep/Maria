"""
Unified Perception - Warstwa 1

Wspolny format zdarzen (PerceptionEvent) i bufor percepcji (PerceptionBuffer)
dla WSZYSTKICH strumieni danych w systemie.

Kontrakt: docs/CONTRACTS.md - Kontrakt 1: Unified Perception
"""

from agent_core.perception.event import PerceptionEvent, PerceptionSource
from agent_core.perception.buffer import PerceptionBuffer

__all__ = ["PerceptionEvent", "PerceptionSource", "PerceptionBuffer"]
