"""
Mode Detector - auto-detect appropriate environment mode.

Uses time-of-day, day-of-week, operator rhythm, and system state.
Default = stay in current mode (stability over switching).
"""

import logging
import time
from datetime import datetime
from typing import Any, Optional

from agent_core.environment.environment_model import (
    EnvironmentMode,
    EnvironmentProfile,
    ENVIRONMENT_PROFILES,
)

logger = logging.getLogger(__name__)

# Minimum time between auto-switches (prevent flapping)
MIN_SWITCH_INTERVAL_SEC = 1800  # 30 minutes


class ModeDetector:
    """
    Detects appropriate environment mode from context.

    Priority order:
    1. Operator manual override (always wins)
    2. Homeostasis degradation (REDUCED/SLEEP -> QUIET)
    3. Time-based auto-trigger (from profile.auto_trigger_hours/days)
    4. Current mode (stability - don't switch without reason)
    """

    def __init__(self):
        self._operator_model = None
        self._homeostasis_core = None
        self._last_switch_ts: float = 0.0

    def set_operator_model(self, model: Any) -> None:
        self._operator_model = model

    def set_homeostasis_core(self, core: Any) -> None:
        self._homeostasis_core = core

    def detect(
        self,
        current_mode: EnvironmentMode,
        now: Optional[datetime] = None,
    ) -> Optional[EnvironmentMode]:
        """
        Detect if mode should change. Returns new mode or None (keep current).

        None = no change recommended. Only returns a mode if there's a
        clear reason to switch.
        """
        if now is None:
            now = datetime.now()

        # Anti-flap guard
        if time.time() - self._last_switch_ts < MIN_SWITCH_INTERVAL_SEC:
            return None

        # Check homeostasis degradation
        degraded = self._check_homeostasis_degradation()
        if degraded is not None:
            if degraded != current_mode:
                return degraded

        # Check time-based triggers
        time_mode = self._check_time_triggers(now, current_mode)
        if time_mode is not None and time_mode != current_mode:
            return time_mode

        # Check operator quiet hours
        quiet = self._check_operator_quiet_hours(now)
        if quiet is not None and quiet != current_mode:
            return quiet

        return None

    def record_switch(self) -> None:
        """Record that a switch happened (for anti-flap)."""
        self._last_switch_ts = time.time()

    def _check_homeostasis_degradation(self) -> Optional[EnvironmentMode]:
        """If homeostasis is in REDUCED/SLEEP/SURVIVAL, switch to QUIET."""
        if self._homeostasis_core is None:
            return None
        try:
            mode = getattr(self._homeostasis_core, "_current_mode", None)
            if mode is None:
                return None
            mode_name = mode if isinstance(mode, str) else mode.value
            if mode_name in ("REDUCED", "SLEEP", "SURVIVAL"):
                return EnvironmentMode.QUIET
        except Exception:
            pass
        return None

    def _check_time_triggers(
        self, now: datetime, current_mode: EnvironmentMode
    ) -> Optional[EnvironmentMode]:
        """Check if any profile's time trigger matches current time."""
        hour = now.hour
        day = now.weekday()  # 0=Monday

        for mode, profile in ENVIRONMENT_PROFILES.items():
            if mode == current_mode:
                continue
            if not profile.auto_trigger_hours:
                continue
            if hour in profile.auto_trigger_hours:
                if not profile.auto_trigger_days or day in profile.auto_trigger_days:
                    return mode
        return None

    def _check_operator_quiet_hours(self, now: datetime) -> Optional[EnvironmentMode]:
        """If operator has quiet hours configured, switch to QUIET."""
        if self._operator_model is None:
            return None
        try:
            prefs = getattr(self._operator_model, "get_preferences", lambda: {})()
            quiet_start = prefs.get("quiet_hours_start")
            quiet_end = prefs.get("quiet_hours_end")
            if quiet_start is not None and quiet_end is not None:
                hour = now.hour
                if quiet_start <= quiet_end:
                    # Simple range: e.g., 22-7
                    if quiet_start <= hour or hour < quiet_end:
                        return EnvironmentMode.QUIET
                else:
                    # Wrap around midnight: e.g., 22-7
                    if hour >= quiet_start or hour < quiet_end:
                        return EnvironmentMode.QUIET
        except Exception:
            pass
        return None
