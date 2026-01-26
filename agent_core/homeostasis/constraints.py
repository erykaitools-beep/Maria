"""
Constraint Validator - Threshold checks and invariant validation

Validates system state against:
- Hard constraints (CRITICAL alerts -> SURVIVAL)
- Soft constraints (WARNING alerts -> consider REDUCED)
- Invariant violations

Spec reference: homeostasis_spec.md lines 1086-1139
"""

from typing import Dict, Any, List, Tuple
from dataclasses import dataclass


@dataclass
class Thresholds:
    """
    Threshold configuration for constraint validation.

    All values from homeostasis_spec.md section 1.1.D and 5.1
    """
    # RAM thresholds (MB free)
    ram_critical_mb: float = 100      # → SURVIVAL
    ram_orange_mb: float = 200        # → REDUCED
    ram_yellow_mb: float = 500        # → consider REDUCED

    # CPU thresholds (%)
    cpu_orange_pct: float = 80        # → throttle warning
    cpu_critical_pct: float = 95      # → REDUCED

    # Temperature thresholds (°C)
    temp_critical_c: float = 95       # → shutdown prep
    temp_orange_c: float = 85         # → REDUCED

    # Disk thresholds (%)
    disk_critical_pct: float = 95     # → alert
    disk_orange_pct: float = 90       # → warning

    # LLM thresholds
    inference_timeout_ms: float = 120000  # 120 seconds → CRITICAL
    inference_slow_ms: float = 5000       # 5 seconds → warning

    # Cognitive thresholds
    coherence_low: float = 0.80       # → alert
    errors_high_rate: int = 20        # per hour → alert
    goal_stack_max: int = 25          # → interrupt
    contradiction_max: int = 10       # → semantic check

    # Memory fragmentation (%)
    memory_fragmentation_high: float = 40

    # Context degradation
    context_degradation_rate: float = 0.30  # 30% incoherent/hour


class ConstraintValidator:
    """
    Validates system state against constraints.

    Returns list of alerts categorized by severity:
    - CRITICAL: Immediate action required (SURVIVAL mode)
    - ALERT: High priority issue (REDUCED mode)
    - WARNING: Should be addressed soon

    Spec: homeostasis_spec.md section 6 (lines 1089-1139)
    """

    def __init__(self, thresholds: Thresholds = None):
        """
        Initialize constraint validator.

        Args:
            thresholds: Custom thresholds or use defaults from spec
        """
        self.thresholds = thresholds or Thresholds()

    def validate(self, state: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate state against all constraints.

        Args:
            state: Interpreted state dictionary from StateInterpreter

        Returns:
            (all_ok, alerts) where:
            - all_ok: True if no alerts
            - alerts: List of alert strings with severity prefix

        Spec: homeostasis_spec.md lines 1104-1139
        """
        alerts = []

        # === CRITICAL CONSTRAINTS (trigger SURVIVAL) ===

        # RAM critical
        ram_available_mb = state.get("ram_available_mb", 0)
        if ram_available_mb < self.thresholds.ram_critical_mb:
            alerts.append(
                f"CRITICAL: RAM pressure imminent OOM ({ram_available_mb:.0f}MB free)"
            )

        # Temperature critical
        temp_c = state.get("temp_c", 50)
        if temp_c > self.thresholds.temp_critical_c:
            alerts.append(
                f"CRITICAL: Temperature critical ({temp_c:.1f}°C), shutdown imminent"
            )

        # LLM hang
        inference_latency = state.get("inference_latency_ms", 0)
        if inference_latency > self.thresholds.inference_timeout_ms:
            alerts.append(
                f"CRITICAL: LLM hang detected ({inference_latency/1000:.1f}s latency)"
            )

        # Disk full
        disk_pct = state.get("disk_used_pct", 0)
        if disk_pct > self.thresholds.disk_critical_pct:
            alerts.append(
                f"CRITICAL: Disk full ({disk_pct:.1f}%)"
            )

        # === ALERT CONSTRAINTS (trigger REDUCED) ===

        # RAM orange
        if ram_available_mb < self.thresholds.ram_orange_mb:
            alerts.append(
                f"ALERT: RAM pressure critical ({ram_available_mb:.0f}MB free)"
            )

        # CPU saturated
        cpu_load = state.get("cpu_load", 0)
        if cpu_load > self.thresholds.cpu_critical_pct:
            alerts.append(
                f"ALERT: CPU saturated ({cpu_load:.1f}%)"
            )

        # Temperature orange
        if temp_c > self.thresholds.temp_orange_c:
            alerts.append(
                f"ALERT: Temperature high ({temp_c:.1f}°C), consider REDUCED mode"
            )

        # Disk orange
        if disk_pct > self.thresholds.disk_orange_pct:
            alerts.append(
                f"ALERT: Disk usage high ({disk_pct:.1f}%)"
            )

        # Goal stack runaway
        if state.get("goal_stack_runaway", False):
            goal_depth = state.get("goal_stack_depth", 0)
            alerts.append(
                f"ALERT: Goal stack depth excessive ({goal_depth})"
            )

        # === WARNING CONSTRAINTS ===

        # RAM yellow
        if ram_available_mb < self.thresholds.ram_yellow_mb:
            # Only add if not already alerted at higher level
            if not any("RAM" in a for a in alerts):
                alerts.append(
                    f"WARNING: RAM getting low ({ram_available_mb:.0f}MB free)"
                )

        # CPU orange
        if cpu_load > self.thresholds.cpu_orange_pct:
            if not any("CPU" in a for a in alerts):
                alerts.append(
                    f"WARNING: CPU load elevated ({cpu_load:.1f}%)"
                )

        # Coherence degraded
        if not state.get("coherence_ok", True):
            coherence = state.get("context_coherence", 1.0)
            alerts.append(
                f"WARNING: Semantic coherence degraded ({coherence:.2f})"
            )

        # Error rate elevated
        if state.get("errors_high", False):
            error_count = state.get("error_count_1h", 0)
            alerts.append(
                f"WARNING: Error rate elevated ({error_count}/hour)"
            )

        # Contradictions
        contradiction_count = state.get("contradiction_count", 0)
        if contradiction_count > self.thresholds.contradiction_max:
            alerts.append(
                f"WARNING: Contradictions in memory ({contradiction_count})"
            )

        # Inference slow
        if inference_latency > self.thresholds.inference_slow_ms:
            if not any("LLM" in a for a in alerts):
                alerts.append(
                    f"WARNING: Inference slow ({inference_latency:.0f}ms)"
                )

        # Attention fragmented
        if state.get("attention_dispersed", False):
            alerts.append("WARNING: Attention fragmented across multiple topics")

        return (len(alerts) == 0, alerts)

    def has_critical(self, alerts: List[str]) -> bool:
        """Check if any CRITICAL alerts exist."""
        return any("CRITICAL" in alert for alert in alerts)

    def has_alert(self, alerts: List[str]) -> bool:
        """Check if any ALERT (non-warning) exists."""
        return any("ALERT" in alert or "CRITICAL" in alert for alert in alerts)

    def get_severity(self, alerts: List[str]) -> str:
        """
        Get highest severity from alerts.

        Returns:
            'critical', 'alert', 'warning', or 'ok'
        """
        if any("CRITICAL" in a for a in alerts):
            return "critical"
        if any("ALERT" in a for a in alerts):
            return "alert"
        if any("WARNING" in a for a in alerts):
            return "warning"
        return "ok"

    def filter_by_severity(self, alerts: List[str], severity: str) -> List[str]:
        """Filter alerts by severity level."""
        severity_upper = severity.upper()
        return [a for a in alerts if severity_upper in a]
