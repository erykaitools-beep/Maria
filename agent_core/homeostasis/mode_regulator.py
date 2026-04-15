"""
Mode Regulator - Operating mode management and transitions

Manages four operating modes:
- ACTIVE: Full capability
- REDUCED: Throttled resources
- SLEEP: LLM unloaded, consolidation only
- SURVIVAL: Emergency, core loop only

Handles mode transitions with:
- Pre-transition validation
- Forbidden transition prevention
- User override handling

Spec reference: homeostasis_spec.md section 3 (lines 239-361)
"""

import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum

from .state_model import Mode

logger = logging.getLogger(__name__)


class TransitionResult(Enum):
    """Result of mode transition attempt."""
    SUCCESS = "success"
    FORBIDDEN = "forbidden"
    VALIDATION_FAILED = "validation_failed"
    ALREADY_IN_MODE = "already_in_mode"


class ModeRegulator:
    """
    Manages system operating mode.

    Decision logic from homeostasis_spec.md section 3.1-3.3:
    - ACTIVE: Default when resources OK
    - REDUCED: When memory pressure or CPU high
    - SLEEP: When idle > 30 min
    - SURVIVAL: On CRITICAL alerts

    Spec: homeostasis_spec.md lines 1145-1216
    """

    # Transition thresholds from spec
    IDLE_FOR_SLEEP_SEC = 1800  # 30 minutes
    RAM_FOR_REDUCED_PCT = 20   # Below 20% available → REDUCED
    RAM_FOR_ACTIVE_PCT = 30    # Above 30% available → can be ACTIVE
    CPU_FOR_REDUCED_PCT = 75   # Above 75% → REDUCED
    CPU_FOR_ACTIVE_PCT = 60    # Below 60% → can be ACTIVE
    STABLE_TIME_FOR_ACTIVE_SEC = 120  # 2 minutes stable before returning to ACTIVE

    # Forbidden transitions from spec
    FORBIDDEN_TRANSITIONS = {
        (Mode.SLEEP, Mode.REDUCED),    # Must go through ACTIVE
        (Mode.SURVIVAL, Mode.REDUCED), # Must go through ACTIVE (with operator)
        (Mode.SURVIVAL, Mode.SLEEP),   # Must go through ACTIVE (with operator)
    }

    def __init__(self):
        """Initialize mode regulator."""
        self.current_mode = Mode.ACTIVE
        self.mode_change_time = time.time()
        self._stable_since: Optional[float] = None
        self._operator_override: Optional[Tuple[Mode, float]] = None  # (mode, until_timestamp)

    def decide_mode(
        self,
        state: Dict[str, Any],
        alerts: List[str],
        user_override: Optional[Mode] = None,
    ) -> Mode:
        """
        Determine appropriate mode based on state and constraints.

        Decision tree (spec lines 1153-1193):
        1. If CRITICAL alert → SURVIVAL
        2. If user override and system not critical → override
        3. Apply automatic decision rules

        Args:
            state: Interpreted state dictionary
            alerts: List of current alerts
            user_override: Optional mode override request

        Returns:
            Recommended mode
        """
        # EMERGENCY: CRITICAL alerts override everything
        if any("CRITICAL" in alert for alert in alerts):
            return Mode.SURVIVAL

        # Check operator override (time-limited)
        if self._operator_override:
            override_mode, until = self._operator_override
            if time.time() < until:
                # Override still active, but not if we need SURVIVAL
                return override_mode
            else:
                # Override expired
                self._operator_override = None

        # User/meta-controller override (if system permits)
        if user_override and user_override != self.current_mode:
            if self._can_transition_to(user_override, state, alerts):
                return user_override

        # Automatic mode decisions
        ram_available_pct = state.get("ram_available_pct", 50)
        cpu_load = state.get("cpu_load", 0)
        idle_time = state.get("idle_seconds", 0)

        # WAKE UP: If in SLEEP but it's learning window time, wake up
        if self.current_mode == Mode.SLEEP and self._is_learning_window():
            logger.info("Auto-wake: learning window active, transitioning SLEEP -> ACTIVE")
            return Mode.ACTIVE

        # SLEEP: If idle long enough and resources OK
        if idle_time > self.IDLE_FOR_SLEEP_SEC and ram_available_pct > 60:
            # Don't go to sleep during learning windows
            if self._is_learning_window():
                return self.current_mode  # Stay in current mode
            return Mode.SLEEP

        # REDUCED: If resource pressure
        if ram_available_pct < self.RAM_FOR_REDUCED_PCT or cpu_load > self.CPU_FOR_REDUCED_PCT:
            # Track when resources became stable
            self._stable_since = None
            return Mode.REDUCED

        # ACTIVE: Default when healthy
        if ram_available_pct > self.RAM_FOR_ACTIVE_PCT and cpu_load < self.CPU_FOR_ACTIVE_PCT:
            # If coming from REDUCED, check stability
            if self.current_mode == Mode.REDUCED:
                if self._stable_since is None:
                    self._stable_since = time.time()
                    return Mode.REDUCED  # Stay in REDUCED, start stability timer

                elapsed = time.time() - self._stable_since
                if elapsed < self.STABLE_TIME_FOR_ACTIVE_SEC:
                    return Mode.REDUCED  # Not stable long enough

            self._stable_since = None
            return Mode.ACTIVE

        # Fallback: stay in current mode if borderline
        return self.current_mode

    @staticmethod
    def _is_learning_window() -> bool:
        """Check if current time is within a learning window (reuses environment config)."""
        try:
            from agent_core.environment.environment_model import is_learning_window
            return is_learning_window()
        except Exception:
            return False

    def _can_transition_to(
        self,
        target_mode: Mode,
        state: Dict[str, Any],
        alerts: List[str],
    ) -> bool:
        """
        Check if transition to target mode is allowed.

        Spec: homeostasis_spec.md lines 1195-1216

        Rules:
        - SURVIVAL ← from anything: always allowed
        - anything ← SURVIVAL: only if operator confirms
        - SLEEP ← ACTIVE: only if idle confirmed
        - REDUCED ↔ ACTIVE: if resources allow
        """
        # SURVIVAL: always allowed (emergency exit)
        if target_mode == Mode.SURVIVAL:
            return True

        # From SURVIVAL: requires explicit operator approval
        if self.current_mode == Mode.SURVIVAL:
            # This should be handled by explicit operator API
            return False

        # Forbidden transitions
        if (self.current_mode, target_mode) in self.FORBIDDEN_TRANSITIONS:
            return False

        # SLEEP: only from ACTIVE, and only if idle
        if target_mode == Mode.SLEEP:
            if self.current_mode != Mode.ACTIVE:
                return False
            idle = state.get("idle_seconds", 0)
            return idle > 60  # At least 1 minute idle

        # REDUCED: from ACTIVE or SLEEP
        if target_mode == Mode.REDUCED:
            return self.current_mode in [Mode.ACTIVE, Mode.SLEEP]

        # ACTIVE: from REDUCED or SLEEP
        if target_mode == Mode.ACTIVE:
            return self.current_mode in [Mode.REDUCED, Mode.SLEEP]

        return True

    def request_mode_override(
        self,
        desired_mode: Mode,
        duration_seconds: int,
        reason: str,
        state: Dict[str, Any],
        alerts: List[str],
    ) -> Tuple[bool, str]:
        """
        Request mode override from meta-controller or operator.

        Spec: homeostasis_spec.md lines 786-798

        Args:
            desired_mode: Requested mode
            duration_seconds: How long to maintain override
            reason: Why override is needed
            state: Current interpreted state
            alerts: Current alerts

        Returns:
            (allowed, message)
        """
        # Never allow override if CRITICAL
        if any("CRITICAL" in a for a in alerts):
            return (False, "Cannot override: system has CRITICAL alerts")

        # SURVIVAL override only by explicit operator action
        if desired_mode == Mode.SURVIVAL:
            return (False, "SURVIVAL mode cannot be requested as override")

        # Check if transition is valid
        if not self._can_transition_to(desired_mode, state, alerts):
            return (False, f"Transition from {self.current_mode.value} to {desired_mode.value} not allowed")

        # Apply override
        until = time.time() + duration_seconds
        self._operator_override = (desired_mode, until)

        return (True, f"Override to {desired_mode.value} approved for {duration_seconds}s")

    def cancel_override(self) -> None:
        """Cancel any active mode override."""
        self._operator_override = None

    def get_override_status(self) -> Optional[Dict[str, Any]]:
        """Get current override status if any."""
        if self._operator_override:
            mode, until = self._operator_override
            remaining = until - time.time()
            if remaining > 0:
                return {
                    "mode": mode.value,
                    "remaining_seconds": remaining,
                }
        return None

    def transition_to(self, new_mode: Mode) -> TransitionResult:
        """
        Execute mode transition.

        Updates internal state. Caller is responsible for
        pre-transition actions (snapshot, signals).

        Args:
            new_mode: Target mode

        Returns:
            TransitionResult indicating success or failure reason
        """
        if new_mode == self.current_mode:
            return TransitionResult.ALREADY_IN_MODE

        # Check forbidden transitions
        if (self.current_mode, new_mode) in self.FORBIDDEN_TRANSITIONS:
            return TransitionResult.FORBIDDEN

        # Record transition
        self.current_mode = new_mode
        self.mode_change_time = time.time()
        self._stable_since = None

        return TransitionResult.SUCCESS

    def get_mode_duration_seconds(self) -> float:
        """Get time spent in current mode."""
        return time.time() - self.mode_change_time

    def get_allowed_transitions(self) -> List[Mode]:
        """Get list of modes we can currently transition to."""
        allowed = []
        for mode in Mode:
            if mode == self.current_mode:
                continue
            # Simple check without full state
            if (self.current_mode, mode) not in self.FORBIDDEN_TRANSITIONS:
                allowed.append(mode)
        return allowed
