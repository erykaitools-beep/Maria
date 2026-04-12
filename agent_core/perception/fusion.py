"""
PerceptionFusion (Faza 3) - Combines all sensor channels into one snapshot.

Single entry point for morning brief and other consumers.
All data filtered through SalienceFilter before inclusion.
"""

import logging
import time
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PerceptionFusion:
    """Aggregates all perception channels into a filtered snapshot."""

    def __init__(self):
        self._weather_fn = None  # -> Optional[str] (formatted weather line)
        self._holiday_sensor = None
        self._system_sensor = None
        self._workspace_sensor = None
        self._salience_filter = None

    # -- DI setters --

    def set_weather_fn(self, fn) -> None:
        self._weather_fn = fn

    def set_holiday_sensor(self, sensor) -> None:
        self._holiday_sensor = sensor

    def set_system_sensor(self, sensor) -> None:
        self._system_sensor = sensor

    def set_workspace_sensor(self, sensor) -> None:
        self._workspace_sensor = sensor

    def set_salience_filter(self, sf) -> None:
        self._salience_filter = sf

    # -- Core API --

    def snapshot_for_brief(self) -> Dict[str, Any]:
        """Build a filtered snapshot dict for morning brief / evening recap.

        Only includes information that passes salience filter.
        Returns dict with string values ready for display.
        """
        result: Dict[str, Any] = {}

        # Weather (already filtered by weather salience in accessor)
        weather_line = self._safe_call(self._weather_fn)
        if weather_line:
            result["weather"] = weather_line

        # Holidays
        self._add_holiday_data(result)

        # System health
        self._add_system_data(result)

        # Workspace changes
        self._add_workspace_data(result)

        return result

    def format_for_brief(self) -> List[str]:
        """Format snapshot as Polish text lines for morning brief."""
        data = self.snapshot_for_brief()
        lines = []

        if data.get("holiday_today"):
            lines.append(data["holiday_today"])
        elif data.get("holiday_upcoming"):
            lines.append(data["holiday_upcoming"])

        if data.get("system_alerts"):
            for alert in data["system_alerts"]:
                lines.append(f"System: {alert}")

        if data.get("new_input_files"):
            count = data["new_input_files"]
            if count == 1:
                lines.append("Nowy plik w input/ czeka na nauke")
            else:
                lines.append(f"{count} nowych plikow w input/ czeka na nauke")

        return lines

    # -- Internal --

    def _add_holiday_data(self, result: Dict) -> None:
        """Add holiday info if salient."""
        if not self._holiday_sensor:
            return
        try:
            # Check today
            today = self._holiday_sensor.get_today()
            if today:
                payload = {"is_today": True, "days_until": 0}
                if self._passes_filter("holiday", payload):
                    result["holiday_today"] = self._holiday_sensor.format_today()
                return

            # Check upcoming
            upcoming_text = self._holiday_sensor.format_upcoming(days=3)
            if upcoming_text:
                upcoming = self._holiday_sensor.get_upcoming(3)
                if upcoming:
                    days = (upcoming[0].holiday_date - date.today()).days
                    payload = {"is_today": False, "days_until": days}
                    if self._passes_filter("holiday", payload):
                        result["holiday_upcoming"] = upcoming_text
        except Exception as e:
            logger.debug("PerceptionFusion: holiday error: %s", e)

    def _add_system_data(self, result: Dict) -> None:
        """Add system health alerts if salient."""
        if not self._system_sensor:
            return
        try:
            health = self._system_sensor.read_health()
            payload = {
                "ollama_alive": health.ollama_alive,
                "service_restarts": health.service_restarts,
                "storage_warning": health.storage_warning,
            }
            if self._passes_filter("system", payload):
                alerts = health.format_alerts()
                if alerts:
                    result["system_alerts"] = alerts
        except Exception as e:
            logger.debug("PerceptionFusion: system error: %s", e)

    def _add_workspace_data(self, result: Dict) -> None:
        """Add workspace changes if salient."""
        if not self._workspace_sensor:
            return
        try:
            snapshot = self._workspace_sensor.scan()
            payload = {"new_input_files": snapshot.new_input_files}
            if self._passes_filter("workspace", payload):
                result["new_input_files"] = snapshot.new_input_files
        except Exception as e:
            logger.debug("PerceptionFusion: workspace error: %s", e)

    def _passes_filter(self, channel: str, payload: dict) -> bool:
        """Run through salience filter. Default = allow (backward compat)."""
        if not self._salience_filter:
            return True
        try:
            return self._salience_filter.is_worth_telling(channel, payload)
        except Exception:
            return True  # fail open

    @staticmethod
    def _safe_call(fn, *args, **kwargs):
        if fn is None:
            return None
        try:
            return fn(*args, **kwargs)
        except Exception:
            return None
