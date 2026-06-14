"""
Consciousness - Maria's self-awareness and identity continuity.

Components:
- IdentityStore: Persistent identity across restarts (JSON)
- SelfModelBuilder: Self-concept nodes in semantic graph
- HumanStateMapper: Technical state -> human language
- ExperienceTracker: Records events for personality evolution
- TraitEvolver: Evolves traits from accumulated experiences
- ConsciousnessCore: Orchestrator combining all above

Usage:
    from agent_core.consciousness import ConsciousnessCore, IdentityStore

    store = IdentityStore(data_dir="meta_data")
    core = ConsciousnessCore(semantic_memory=graph, identity_store=store)
    core.initialize()

    # Record experiences during operation
    core.record_experience("conversation_turn")
    core.record_experience("learning_completed", {"file": "quantum.txt"})

    # At shutdown - evolves personality and persists
    core.checkpoint(summary="Learned about quantum physics")
"""

import logging
from typing import Any, Dict, Optional

from agent_core.consciousness.identity_store import IdentityStore
from agent_core.consciousness.self_model import SelfModelBuilder
from agent_core.consciousness.human_state import HumanStateMapper
from agent_core.consciousness.experience_tracker import ExperienceTracker
from agent_core.consciousness.trait_evolver import TraitEvolver
from agent_core.consciousness.core import ConsciousnessCore
from agent_core.consciousness.conversation_memory import ConversationMemory
from agent_core.consciousness.sleep_processor import SleepProcessor
from agent_core.consciousness.dream_generator import DreamGenerator
from agent_core.consciousness.user_profile import UserProfile

_logger = logging.getLogger(__name__)

# Process-wide consciousness reference, set by maria.py after init.
# Allows subsystems running in the same process (e.g. Web UI handlers) to
# emit experience events without threading the dependency through every
# call site. None when consciousness is not wired (tests, REPL-only).
_global_consciousness: Optional[ConsciousnessCore] = None


def set_global_consciousness(core: Optional[ConsciousnessCore]) -> None:
    """Register the process-wide ConsciousnessCore (or clear with None)."""
    global _global_consciousness
    _global_consciousness = core


def get_global_consciousness() -> Optional[ConsciousnessCore]:
    """Return the process-wide ConsciousnessCore, or None if unset."""
    return _global_consciousness


def record_experience(
    consciousness: Any,
    event_type: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Record an experience event on a consciousness-like object, safely.

    Falls back to the process-wide consciousness when ``consciousness`` is None,
    so call sites without direct access can still emit signals. Any failure is
    swallowed and logged at debug level — trait scoring is non-critical.

    Args:
        consciousness: ConsciousnessCore (or anything exposing
            ``record_experience``). If None, the global accessor is consulted.
        event_type: Catalogued event name from trait_catalog.
        details: Optional payload (kept on disk in personality_experiences.jsonl).
    """
    target = consciousness if consciousness is not None else _global_consciousness
    if target is None:
        return
    try:
        target.record_experience(event_type, details)
    except Exception as exc:
        _logger.debug("record_experience(%s) skipped: %s", event_type, exc)


__all__ = [
    "IdentityStore",
    "SelfModelBuilder",
    "HumanStateMapper",
    "ExperienceTracker",
    "TraitEvolver",
    "ConsciousnessCore",
    "ConversationMemory",
    "SleepProcessor",
    "DreamGenerator",
    "UserProfile",
    "record_experience",
    "set_global_consciousness",
    "get_global_consciousness",
]
