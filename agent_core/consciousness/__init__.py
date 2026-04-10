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
]
