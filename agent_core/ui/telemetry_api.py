"""
Telemetry API - Read-only dashboard data

Provides read-only access to system state for UI/dashboard.

Spec reference: homeostasis_spec.md section 6.2 (lines 820-875)
"""

import time
from typing import Dict, Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..homeostasis.core import HomeostasisCore


class TelemetryAPI:
    """
    Read-only telemetry API for operator dashboard.

    Provides system overview, resource status, cognitive state,
    and alert information.
    """

    def __init__(self, homeostasis_core: Optional["HomeostasisCore"] = None):
        """
        Initialize telemetry API.

        Args:
            homeostasis_core: Reference to homeostasis core
        """
        self._core = homeostasis_core

    def set_core(self, core: "HomeostasisCore") -> None:
        """Set homeostasis core reference."""
        self._core = core

    def get_overview(self) -> Dict[str, Any]:
        """
        Get system overview.

        Spec: homeostasis_spec.md lines 825-829

        Returns:
            Overview dictionary with mode, health, uptime
        """
        if not self._core:
            return {"error": "Homeostasis core not available"}

        state = self._core.state
        uptime = state.mode_duration_seconds

        return {
            "mode": state.mode.value,
            "health_score": round(state.health_score * 100),  # As percentage
            "health_score_raw": state.health_score,
            "uptime_seconds": uptime,
            "uptime_formatted": self._format_uptime(uptime),
            "alerts_count": len(state.alerts),
            "has_critical": state.has_critical_alert(),
        }

    def get_resources(self) -> Dict[str, Any]:
        """
        Get resource status.

        Spec: homeostasis_spec.md lines 831-836

        Returns:
            Resource utilization dictionary
        """
        if not self._core or not self._core.state.interpreted_state:
            return {}

        state = self._core.state.interpreted_state

        return {
            "ram": {
                "percent_used": round(100 - state.get("ram_available_pct", 0)),
                "percent_available": round(state.get("ram_available_pct", 0)),
                "available_mb": round(state.get("ram_available_mb", 0)),
                "status": self._get_status(state.get("ram_available_pct", 100), thresholds=(20, 30)),
            },
            "cpu": {
                "percent_used": round(state.get("cpu_load", 0)),
                "status": self._get_status(100 - state.get("cpu_load", 0), thresholds=(25, 40)),
            },
            "disk": {
                "percent_used": round(state.get("disk_used_pct", 0)),
                "percent_available": round(100 - state.get("disk_used_pct", 0)),
                "status": self._get_status(100 - state.get("disk_used_pct", 0), thresholds=(5, 10)),
            },
            "temperature": {
                "celsius": round(state.get("temp_c", 50)),
                "status": self._get_status(95 - state.get("temp_c", 50), thresholds=(10, 25)),
            },
            "inference_latency_ms": round(state.get("inference_latency_ms", 0)),
        }

    def get_cognitive_state(self) -> Dict[str, Any]:
        """
        Get cognitive state.

        Spec: homeostasis_spec.md lines 838-843

        Returns:
            Cognitive metrics dictionary
        """
        if not self._core or not self._core.state.interpreted_state:
            return {}

        state = self._core.state.interpreted_state

        return {
            "context_coherence": round(state.get("context_coherence", 1.0), 2),
            "coherence_ok": state.get("coherence_ok", True),
            "error_count_1h": state.get("error_count_1h", 0),
            "errors_high": state.get("errors_high", False),
            "goal_stack_depth": state.get("goal_stack_depth", 0),
            "goal_stack_runaway": state.get("goal_stack_runaway", False),
            "contradiction_count": state.get("contradiction_count", 0),
            "task_completion_ratio": round(state.get("task_completion_ratio", 1.0), 2),
            "idle_seconds": round(state.get("idle_seconds", 0)),
        }

    def get_alerts(self) -> List[Dict[str, Any]]:
        """
        Get current alerts.

        Returns:
            List of alert dictionaries with severity and message
        """
        if not self._core:
            return []

        alerts = []
        for alert_text in self._core.state.alerts:
            severity = "warning"
            if "CRITICAL" in alert_text:
                severity = "critical"
            elif "ALERT" in alert_text:
                severity = "alert"

            alerts.append({
                "severity": severity,
                "message": alert_text,
                "timestamp": time.time(),
            })

        return alerts

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get recent audit log entries.

        Args:
            limit: Maximum entries to return

        Returns:
            List of audit log entries
        """
        if not self._core:
            return []

        return self._core.get_audit_log(limit)

    def get_mode_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get mode transition history.

        Args:
            limit: Maximum transitions to return

        Returns:
            List of mode transitions
        """
        if not self._core:
            return []

        log = self._core.get_audit_log(1000)
        transitions = [
            entry for entry in log
            if entry.get("event") == "mode_change"
        ]
        return transitions[-limit:]

    def get_full_telemetry(self) -> Dict[str, Any]:
        """
        Get complete telemetry snapshot.

        Returns:
            Full telemetry dictionary
        """
        return {
            "timestamp": time.time(),
            "overview": self.get_overview(),
            "resources": self.get_resources(),
            "cognitive": self.get_cognitive_state(),
            "alerts": self.get_alerts(),
        }

    def _get_status(
        self,
        value: float,
        thresholds: tuple = (20, 40),
    ) -> str:
        """
        Get status string based on value.

        Args:
            value: Current value (higher = better)
            thresholds: (critical, warning) thresholds

        Returns:
            'critical', 'warning', or 'ok'
        """
        critical, warning = thresholds
        if value < critical:
            return "critical"
        elif value < warning:
            return "warning"
        return "ok"

    def _format_uptime(self, seconds: float) -> str:
        """Format uptime as human-readable string."""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)

        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
