"""
SalienceFilter (Faza 3) - Unified "is this worth telling the operator?" gate.

Default = do NOT tell. Every channel must justify salience.
Respects quiet hours, DND context, and operator preferences.
"""

import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Context keywords that suppress non-critical notifications
_DND_KEYWORDS = ("urlop", "nie przeszkadza", "vacation", "dnd", "busy")


class SalienceFilter:
    """Unified salience gate for all perception channels."""

    def __init__(self, operator_model=None):
        self._operator_model = operator_model

    def set_operator_model(self, om) -> None:
        self._operator_model = om

    def is_worth_telling(self, channel: str, payload: dict) -> bool:
        """Central gate: should this information reach the operator?

        Args:
            channel: "weather", "holiday", "system", "workspace"
            payload: channel-specific data dict

        Returns:
            True if worth telling, False to suppress.
        """
        # Step 1: Check DND context (suppresses everything non-critical)
        if self._is_dnd():
            priority = payload.get("priority", 0.0)
            if priority < 0.9:
                return False

        # Step 2: Check quiet hours (only critical passes)
        if self._is_quiet_hours():
            priority = payload.get("priority", 0.0)
            if priority < 0.9:
                return False

        # Step 3: Channel-specific rules
        return self._check_channel(channel, payload)

    def _check_channel(self, channel: str, payload: dict) -> bool:
        """Channel-specific salience rules. Default = suppress."""
        if channel == "weather":
            # Delegate to existing weather salience
            return payload.get("salient", False)

        elif channel == "holiday":
            # Today's holiday = always salient
            if payload.get("is_today"):
                return True
            # Upcoming within 2 days = salient
            days_until = payload.get("days_until", 999)
            return days_until <= 2

        elif channel == "system":
            # Only salient if something is wrong
            if not payload.get("ollama_alive", True):
                return True
            if payload.get("service_restarts", 0) > 0:
                return True
            if payload.get("storage_warning", False):
                return True
            return False

        elif channel == "workspace":
            # Only new files in input/ are salient
            return payload.get("new_input_files", 0) > 0

        # Unknown channel = suppress
        return False

    def _is_dnd(self) -> bool:
        """Check if operator set a DND context."""
        if not self._operator_model:
            return False
        try:
            context = self._operator_model.get_context()
            if context:
                return any(kw in context.lower() for kw in _DND_KEYWORDS)
        except Exception:
            pass
        return False

    def _is_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours."""
        if not self._operator_model:
            return False
        try:
            quiet = self._operator_model.get_preference("quiet_hours", None)
            if not quiet or len(quiet) < 2:
                return False
            start, end = quiet[0], quiet[1]
            hour = datetime.now().hour
            if start > end:
                # Wraps midnight: e.g. 23-6
                return hour >= start or hour < end
            else:
                return start <= hour < end
        except Exception:
            return False
