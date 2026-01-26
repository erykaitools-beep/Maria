"""
Meta Controller - Higher-level reasoning control

Provides:
- Goal stack management
- Priority override requests
- Reasoning interruption

Adapter for: maria_core/meta/meta_controller.py

Spec reference: homeostasis_spec.md section 2.2.B (lines 182-198)
"""

import time
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class MetaController:
    """
    Meta-controller interface for homeostasis.

    Higher-level than homeostasis - handles reasoning,
    goals, and strategic decisions.

    Homeostasis = lower level (biological)
    MetaController = higher level (reflection, planning)
    """

    # From spec: goal stack max depth before intervention
    MAX_GOAL_DEPTH = 25

    def __init__(self):
        """Initialize meta controller."""
        self._goal_stack: List[Dict[str, Any]] = []
        self._current_priority = "normal"
        self._paused = False

        # Try to wrap legacy module
        self._init_legacy_adapter()

    def _init_legacy_adapter(self) -> None:
        """Initialize adapter for legacy MetaController."""
        try:
            from maria_core.meta.meta_controller import MetaController as LegacyMeta
            self._legacy_meta = LegacyMeta()
        except ImportError:
            self._legacy_meta = None
            logger.debug("Legacy MetaController not available")

    # ─────────────────────────────────────────────
    # HOMEOSTASIS INTERFACE
    # ─────────────────────────────────────────────

    def get_goal_stack_depth(self) -> int:
        """
        Get current goal stack depth.

        Used by homeostasis to detect runaway refinement.

        Returns:
            Number of goals on stack
        """
        return len(self._goal_stack)

    def interrupt_goal_refinement(self) -> Dict[str, Any]:
        """
        Interrupt current goal refinement.

        Called by homeostasis when goal stack is too deep.

        Spec: homeostasis_spec.md lines 533-539

        Returns:
            Result of interruption
        """
        logger.warning("Goal refinement interrupted by homeostasis")

        interrupted_goals = len(self._goal_stack)

        # Keep only root goal
        if self._goal_stack:
            root = self._goal_stack[0]
            self._goal_stack = [root]

        return {
            "success": True,
            "interrupted_count": interrupted_goals - 1,
            "remaining_depth": len(self._goal_stack),
        }

    def pause(self) -> None:
        """Pause meta-controller operations."""
        self._paused = True
        logger.info("MetaController paused")

    def resume(self) -> None:
        """Resume meta-controller operations."""
        self._paused = False
        logger.info("MetaController resumed")

    def is_paused(self) -> bool:
        """Check if paused."""
        return self._paused

    # ─────────────────────────────────────────────
    # GOAL MANAGEMENT
    # ─────────────────────────────────────────────

    def push_goal(self, goal: Dict[str, Any]) -> bool:
        """
        Push goal onto stack.

        Args:
            goal: Goal dictionary with 'description', 'priority', etc.

        Returns:
            True if pushed, False if stack at limit
        """
        if len(self._goal_stack) >= self.MAX_GOAL_DEPTH:
            logger.warning("Goal stack at max depth, refusing new goal")
            return False

        goal["pushed_at"] = time.time()
        self._goal_stack.append(goal)
        return True

    def pop_goal(self) -> Optional[Dict[str, Any]]:
        """
        Pop and return top goal.

        Returns:
            Top goal or None if empty
        """
        if self._goal_stack:
            return self._goal_stack.pop()
        return None

    def peek_goal(self) -> Optional[Dict[str, Any]]:
        """
        Peek at top goal without removing.

        Returns:
            Top goal or None
        """
        if self._goal_stack:
            return self._goal_stack[-1]
        return None

    def clear_goals(self) -> int:
        """
        Clear all goals.

        Returns:
            Number of goals cleared
        """
        count = len(self._goal_stack)
        self._goal_stack.clear()
        return count

    def get_goals(self) -> List[Dict[str, Any]]:
        """Get all goals (bottom to top)."""
        return self._goal_stack.copy()

    # ─────────────────────────────────────────────
    # HOMEOSTASIS NEGOTIATION (spec lines 188-198)
    # ─────────────────────────────────────────────

    def request_mode_override(
        self,
        desired_mode: str,
        reason: str,
        duration_hours: float = 2.0,
    ) -> Dict[str, Any]:
        """
        Request mode override from homeostasis.

        MetaController can request ACTIVE mode despite
        resource constraints for critical goals.

        Args:
            desired_mode: Requested mode
            reason: Why override needed
            duration_hours: How long needed

        Returns:
            Request that should be sent to homeostasis
        """
        return {
            "type": "mode_override_request",
            "desired_mode": desired_mode,
            "reason": reason,
            "duration_seconds": int(duration_hours * 3600),
            "requested_by": "metacontroller",
            "current_goal": self.peek_goal(),
        }

    def acknowledge_mode_change(
        self,
        old_mode: str,
        new_mode: str,
        reason: str,
    ) -> None:
        """
        Acknowledge mode change from homeostasis.

        MetaController should adjust behavior based on mode.

        Args:
            old_mode: Previous mode
            new_mode: New mode
            reason: Why changed
        """
        logger.info(f"MetaController acknowledging mode change: {old_mode} → {new_mode}")

        # Adjust behavior based on new mode
        if new_mode == "reduced":
            # Simplify current goals
            logger.info("Simplifying goals for REDUCED mode")
        elif new_mode == "sleep":
            # Pause non-essential goals
            self.pause()
        elif new_mode == "survival":
            # Emergency: clear non-critical goals
            self._keep_critical_goals_only()
        elif new_mode == "active":
            # Resume normal operation
            if self._paused:
                self.resume()

    def _keep_critical_goals_only(self) -> None:
        """Keep only critical priority goals."""
        self._goal_stack = [
            g for g in self._goal_stack
            if g.get("priority") == "critical"
        ]

    # ─────────────────────────────────────────────
    # SHUTDOWN
    # ─────────────────────────────────────────────

    def shutdown_prepare(self, grace_period_seconds: int = 30) -> Dict[str, Any]:
        """
        Prepare for shutdown.

        Args:
            grace_period_seconds: Time available

        Returns:
            Acknowledgment
        """
        logger.info(f"MetaController preparing for shutdown")

        return {
            "ready_shutdown": True,
            "goals_pending": len(self._goal_stack),
        }
