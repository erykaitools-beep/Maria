"""
Capability/Task Router - unified registry-based action dispatch.

Replaces the 13-way if/elif chain in ActionExecutor with a
registry where each cognitive organ self-registers its handler.

Usage:
    from agent_core.routing import CapabilityRouter, CapabilitySpec

    router = CapabilityRouter()
    router.register("learn", learn_handler, learn_spec)
    result = router.dispatch(plan)
"""

from agent_core.routing.capability_router import CapabilityRouter
from agent_core.routing.capability_spec import CapabilitySpec, DEFAULT_CAPABILITY_SPECS
from agent_core.routing.intent_router import IntentMatch, IntentRouter

__all__ = [
    "CapabilityRouter",
    "CapabilitySpec",
    "DEFAULT_CAPABILITY_SPECS",
    "IntentMatch",
    "IntentRouter",
]
