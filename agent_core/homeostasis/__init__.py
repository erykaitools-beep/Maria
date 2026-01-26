"""
Homeostasis Core Module

Implements the central homeostasis system from homeostasis_spec.md Part 2.

Components:
- sensors/: Raw metric collection (resource, cognitive, thermal, power, time)
- state_model.py: Dataclasses for metrics and system state
- interpreter.py: Raw → semantic state conversion with EMA smoothing
- constraints.py: ConstraintValidator with threshold checks
- mode_regulator.py: Mode enum and transition logic
- actions.py: CorrectiveActionGenerator and AlarmDispatcher
- core.py: HomeostasisCore main loop (1s ticks)
- pulse.py: High-frequency pulse thread (100ms)
- api.py: Public interface and event bus
- snapshot.py: Atomic snapshot and recovery protocol

Spec reference: homeostasis_spec.md sections 2-9
"""

from .state_model import Mode, ResourceMetrics, CognitiveMetrics, SystemState
from .core import HomeostasisCore
from .api import HomeostasisInterface, HomeostasisEventBus

__all__ = [
    "Mode",
    "ResourceMetrics",
    "CognitiveMetrics",
    "SystemState",
    "HomeostasisCore",
    "HomeostasisInterface",
    "HomeostasisEventBus",
]
