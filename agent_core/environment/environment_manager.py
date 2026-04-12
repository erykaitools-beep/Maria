"""
Environment Manager - facade for environment adaptation.

Manages active mode, applies profiles to system behavior,
provides context for master prompt injection.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from agent_core.environment.environment_model import (
    EnvironmentMode,
    EnvironmentProfile,
    EnvironmentState,
    ENVIRONMENT_PROFILES,
)
from agent_core.environment.mode_detector import ModeDetector

logger = logging.getLogger(__name__)

STATE_PATH = os.path.join("meta_data", "environment_state.json")


class EnvironmentManager:
    """
    Manages environment mode switching and profile application.

    Provides:
    - Manual mode switching (operator command)
    - Auto-detection (time/context-based)
    - Profile context for master prompt injection
    - Action priority/block information for planner
    """

    def __init__(
        self,
        detector: Optional[ModeDetector] = None,
        state_path: str = STATE_PATH,
    ):
        self._detector = detector or ModeDetector()
        self._state_path = state_path
        self._state = self._load_state()
        self._switch_listeners: List[Any] = []

    # --- Mode switching ---

    def switch(
        self,
        mode: EnvironmentMode,
        by: str = "operator",
        duration_hours: Optional[float] = None,
    ) -> bool:
        """
        Switch to a new environment mode.

        Args:
            mode: Target mode
            by: Who initiated ("operator", "auto", "system")
            duration_hours: If set, auto-revert to DEFAULT after N hours
        """
        if mode == self._state.active_mode:
            return False

        old_mode = self._state.active_mode
        self._state.active_mode = mode
        self._state.switched_at = time.time()
        self._state.switched_by = by

        if duration_hours is not None:
            self._state.override_until = time.time() + duration_hours * 3600
        else:
            self._state.override_until = None

        if by == "operator":
            # Manual override disables auto-detect until next manual switch to DEFAULT
            self._state.auto_detect_enabled = (mode == EnvironmentMode.DEFAULT)

        self._detector.record_switch()
        self._save_state()

        # Notify listeners
        for listener in self._switch_listeners:
            try:
                listener(old_mode, mode, by)
            except Exception as e:
                logger.warning("Switch listener error: %s", e)

        logger.info("Environment switched: %s -> %s (by: %s)",
                     old_mode.value, mode.value, by)
        return True

    def maybe_auto_switch(self) -> Optional[EnvironmentMode]:
        """
        Check if auto-switch is needed. Called from tick loop.
        Returns new mode if switched, None if not.
        """
        if not self._state.auto_detect_enabled:
            return None

        # Check if manual override has expired
        if self._state.override_until is not None:
            if time.time() >= self._state.override_until:
                self._state.override_until = None
                self._state.auto_detect_enabled = True
                self.switch(EnvironmentMode.DEFAULT, by="system")
                return EnvironmentMode.DEFAULT

        detected = self._detector.detect(self._state.active_mode)
        if detected is not None:
            self.switch(detected, by="auto")
            return detected

        return None

    def add_switch_listener(self, listener: Any) -> None:
        """Add callback: (old_mode, new_mode, by) -> None."""
        self._switch_listeners.append(listener)

    # --- Query ---

    def get_active_mode(self) -> EnvironmentMode:
        """Get current environment mode."""
        return self._state.active_mode

    def get_active_profile(self) -> EnvironmentProfile:
        """Get current environment profile."""
        return ENVIRONMENT_PROFILES.get(
            self._state.active_mode,
            ENVIRONMENT_PROFILES[EnvironmentMode.DEFAULT],
        )

    def get_context(self) -> Dict[str, Any]:
        """
        Get environment context for master prompt injection.
        Called by master_prompt.py to enrich LLM context.
        """
        profile = self.get_active_profile()
        return {
            "mode": self._state.active_mode.value,
            "description": profile.description,
            "prompt_addition": profile.prompt_addition,
            "notification_level": profile.notification_level,
            "switched_at": self._state.switched_at,
            "switched_by": self._state.switched_by,
            "auto_detect": self._state.auto_detect_enabled,
        }

    def get_status(self) -> Dict[str, Any]:
        """Full status for REPL/Telegram."""
        profile = self.get_active_profile()
        return {
            "mode": self._state.active_mode.value,
            "description": profile.description,
            "switched_at": self._state.switched_at,
            "switched_by": self._state.switched_by,
            "auto_detect_enabled": self._state.auto_detect_enabled,
            "override_until": self._state.override_until,
            "notification_level": profile.notification_level,
            "llm_budget_multiplier": profile.llm_budget_multiplier,
            "priority_actions": list(profile.priority_actions),
            "blocked_actions": list(profile.blocked_actions),
        }

    def is_action_blocked(self, action: str) -> bool:
        """Check if an action is blocked in current environment."""
        profile = self.get_active_profile()
        return action in profile.blocked_actions

    def get_action_priority_boost(self, action: str) -> float:
        """
        Get priority adjustment for an action in current environment.
        Returns: >0 for priority boost, <0 for deprioritization, 0 for neutral.
        """
        profile = self.get_active_profile()
        if action in profile.priority_actions:
            return 0.15
        if action in profile.deprioritized_actions:
            return -0.1
        return 0.0

    def list_modes(self) -> List[Dict[str, Any]]:
        """List all available modes with descriptions."""
        return [
            {
                "mode": mode.value,
                "description": profile.description,
                "active": mode == self._state.active_mode,
            }
            for mode, profile in ENVIRONMENT_PROFILES.items()
        ]

    # --- Persistence ---

    def _load_state(self) -> EnvironmentState:
        """Load state from JSON file."""
        if not os.path.exists(self._state_path):
            return EnvironmentState()
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                d = json.load(f)
                return EnvironmentState.from_dict(d)
        except (json.JSONDecodeError, OSError, ValueError) as e:
            logger.warning("Failed to load environment state: %s", e)
            return EnvironmentState()

    def _save_state(self) -> None:
        """Save state to JSON file."""
        try:
            os.makedirs(os.path.dirname(self._state_path) or ".", exist_ok=True)
            with open(self._state_path, "w", encoding="utf-8") as f:
                json.dump(self._state.to_dict(), f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error("Failed to save environment state: %s", e)
