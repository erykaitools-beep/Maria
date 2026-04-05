"""
ExecutionRouter (V3 Phase D, Module 10)

User-facing execution dispatch that wraps CapabilityRouter with
cost, time, and resource enrichment. Provides a single execute()
method that validates, estimates, and dispatches actions.

Wraps V2: CapabilityRouter (14 capabilities), K7 autonomy policy.

Usage:
    router = ExecutionRouter(ctx)
    result = router.execute("learn", {"topics": ["fizyka"]})
    # result = {"success": True, "cost": ..., "time": ..., ...}
    available = router.list_available()
"""

import logging
import time
from typing import Any, Dict, List, Optional

from agent_core.orchestrator.cost_estimator import CostEstimator
from agent_core.orchestrator.time_estimator import TimeEstimator

logger = logging.getLogger(__name__)


class ExecutionRouter:
    """User-facing execution dispatch with cost/time awareness."""

    def __init__(self, ctx):
        self._ctx = ctx
        self._cost_estimator = CostEstimator(ctx)
        self._time_estimator = TimeEstimator(ctx)

    def can_execute(self, action: str) -> Dict[str, Any]:
        """
        Check if an action can be executed right now.

        Returns:
            Dict with can_execute, reason, cost, time estimates.
        """
        available = self._is_available(action)
        blocked, block_reason = self._is_blocked(action)
        cost = self._cost_estimator.estimate_action(action)
        time_est = self._time_estimator.estimate_action(action)

        can = available and not blocked

        return {
            "action": action,
            "can_execute": can,
            "available": available,
            "blocked": blocked,
            "block_reason": block_reason,
            "cost": cost.to_dict(),
            "time_estimate": time_est.to_dict(),
        }

    def execute(self, action: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Execute an action through CapabilityRouter with enrichment.

        Args:
            action: Action name (learn, exam, fetch, etc.)
            params: Action parameters

        Returns:
            Result dict with success, cost, timing, and action-specific data.
        """
        check = self.can_execute(action)
        if not check["can_execute"]:
            return {
                "success": False,
                "action": action,
                "error": check["block_reason"] or "Action not available",
                "cost": check["cost"],
            }

        router = self._get_capability_router()
        if not router:
            return {
                "success": False,
                "action": action,
                "error": "CapabilityRouter not initialized",
            }

        # Build a minimal Plan-like object for dispatch
        plan = _MinimalPlan(action, params or {})

        start = time.time()
        result = router.dispatch(plan)
        elapsed_ms = (time.time() - start) * 1000

        result["action"] = action
        result["elapsed_ms"] = elapsed_ms
        result["cost"] = check["cost"]
        result["time_estimate"] = check["time_estimate"]

        return result

    def list_available(self) -> List[Dict[str, Any]]:
        """
        List all available actions with their current status.

        Returns:
            List of action dicts with availability, cost, time.
        """
        router = self._get_capability_router()
        if not router:
            return []

        results = []
        for spec in router.list_capabilities():
            cost = self._cost_estimator.estimate_action(spec.name)
            time_est = self._time_estimator.estimate_action(spec.name)
            blocked, reason = self._is_blocked(spec.name)

            results.append({
                "name": spec.name,
                "description": spec.description,
                "available": router.is_available(spec.name),
                "blocked": blocked,
                "block_reason": reason,
                "k7_classification": spec.k7_classification,
                "tags": list(spec.tags),
                "cost": cost.to_dict(),
                "time_estimate": time_est.to_dict(),
            })

        return results

    def get_status(self) -> Dict[str, Any]:
        """Execution router status summary."""
        router = self._get_capability_router()
        available_count = 0
        total_count = 0

        if router:
            for spec in router.list_capabilities():
                total_count += 1
                if router.is_available(spec.name):
                    available_count += 1

        return {
            "total_capabilities": total_count,
            "available_capabilities": available_count,
            "budget": self._cost_estimator.get_budget_status().to_dict(),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_capability_router(self):
        return getattr(self._ctx, "capability_router", None)

    def _is_available(self, action: str) -> bool:
        router = self._get_capability_router()
        if router:
            return router.is_available(action)
        return False

    def _is_blocked(self, action: str) -> tuple:
        policy = self._ctx.autonomy_policy
        if not policy:
            return (False, "")
        try:
            classification = policy.classify_action(action)
            level = getattr(classification, "level", str(classification))
            if level == "forbidden":
                return (True, f"K7: {action} is FORBIDDEN")
        except Exception:
            pass
        return (False, "")


class _MinimalPlan:
    """Minimal Plan-like object for CapabilityRouter dispatch."""

    def __init__(self, action: str, params: Dict):
        from enum import Enum

        # Create a minimal action_type with .value
        class _ActionType:
            def __init__(self, val):
                self.value = val
        self.action_type = _ActionType(action)
        self.action_params = params
