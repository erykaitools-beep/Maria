"""
Consciousness - Maria's self-awareness and identity continuity.

Components:
- IdentityStore: Persistent identity across restarts (JSON)
- SelfModelBuilder: Self-concept nodes in semantic graph
- HumanStateMapper: Technical state -> human language
- ConsciousnessCore: Orchestrator combining all above

Usage:
    from agent_core.consciousness import ConsciousnessCore, IdentityStore

    store = IdentityStore(data_dir="meta_data")
    core = ConsciousnessCore(semantic_memory=graph, identity_store=store)
    core.initialize()
"""

from agent_core.consciousness.identity_store import IdentityStore
from agent_core.consciousness.self_model import SelfModelBuilder
from agent_core.consciousness.human_state import HumanStateMapper
from agent_core.consciousness.core import ConsciousnessCore

__all__ = [
    "IdentityStore",
    "SelfModelBuilder",
    "HumanStateMapper",
    "ConsciousnessCore",
]
