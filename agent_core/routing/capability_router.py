"""
CapabilityRouter - registry-based action dispatch.

Replaces the 13-way if/elif chain in ActionExecutor with a dict lookup.
Adding a new capability = one register() call.

Usage:
    router = CapabilityRouter()
    router.register("learn", learn_handler, learn_spec)
    result = router.dispatch(plan)
"""

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from agent_core.routing.capability_spec import CapabilitySpec

logger = logging.getLogger(__name__)


class CapabilityRouter:
    """Registry-based action dispatch replacing if/elif chain."""

    def __init__(self):
        self._handlers: Dict[str, Callable] = {}
        self._specs: Dict[str, CapabilitySpec] = {}

    def register(
        self,
        name: str,
        handler: Callable,
        spec: CapabilitySpec,
    ) -> None:
        """
        Register a capability with its handler and metadata.

        Args:
            name: Action type value, e.g. 'learn'
            handler: Callable that takes a Plan and returns result dict
            spec: CapabilitySpec with metadata

        Raises:
            ValueError: If name is already registered or spec.name mismatches
        """
        if name in self._handlers:
            raise ValueError(f"Capability already registered: {name}")
        if spec.name != name:
            raise ValueError(
                f"Spec name mismatch: spec.name={spec.name!r} != name={name!r}"
            )
        self._handlers[name] = handler
        self._specs[name] = spec
        logger.debug(f"[CapabilityRouter] Registered: {name}")

    def unregister(self, name: str) -> bool:
        """
        Remove a registered capability. Returns True if removed.

        Primarily for testing.
        """
        removed = name in self._handlers
        self._handlers.pop(name, None)
        self._specs.pop(name, None)
        return removed

    def dispatch(self, plan) -> Dict[str, Any]:
        """
        Dispatch a plan to the registered handler.

        Looks up handler by plan.action_type.value, calls it,
        wraps in timing and error handling.

        Args:
            plan: Plan object with action_type and action_params

        Returns:
            Dict with at least {"success": bool, ...}
        """
        action_name = plan.action_type.value
        handler = self._handlers.get(action_name)

        if handler is None:
            return {
                "success": False,
                "error": f"No handler registered for action: {action_name}",
            }

        start = time.time()
        try:
            result = handler(plan)
        except Exception as e:
            logger.warning(f"[CapabilityRouter] Handler error for {action_name}: {e}")
            result = {"success": False, "error": str(e)}

        result["duration_ms"] = (time.time() - start) * 1000
        return result

    def get_spec(self, name: str) -> Optional[CapabilitySpec]:
        """Get metadata for a registered capability, or None."""
        return self._specs.get(name)

    def list_capabilities(self) -> List[CapabilitySpec]:
        """List all registered capabilities (sorted by name)."""
        return sorted(self._specs.values(), key=lambda s: s.name)

    def is_available(self, name: str) -> bool:
        """Check if a capability is registered and has a handler."""
        return name in self._handlers

    def get_k7_classification(self, name: str) -> str:
        """
        Get K7 autonomy classification for an action type.

        Returns 'restricted' for unknown actions (safe-by-default).
        """
        spec = self._specs.get(name)
        if spec is not None:
            return spec.k7_classification
        return "restricted"

    @property
    def registered_count(self) -> int:
        """Number of registered capabilities."""
        return len(self._handlers)

    def get_status(self) -> Dict[str, Any]:
        """Status summary for diagnostics."""
        return {
            "registered": self.registered_count,
            "capabilities": [
                {
                    "name": s.name,
                    "classification": s.k7_classification,
                    "tags": list(s.tags),
                }
                for s in self.list_capabilities()
            ],
        }
