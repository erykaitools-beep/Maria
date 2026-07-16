"""Health-score math as a single source of truth.

The aggregate health score (0..1) and its human-readable breakdown are computed
here so the live tick path (`HomeostasisCore._compute_health`) and the Web/UI API
(`/api/status/full`) can never drift apart. The constants below are the spec
(homeostasis_spec.md lines 1450-1466).
"""

from typing import Any, Dict, Iterable, List

# Per-alert penalty by severity token contained in the alert string.
ALERT_PENALTIES: Dict[str, float] = {
    "CRITICAL": 0.5,
    "ALERT": 0.15,
    "WARNING": 0.05,
}

# Resource-utilization multipliers: score *= (1 - pressure/100 * weight).
MEMORY_WEIGHT = 0.3
CPU_WEIGHT = 0.2

# Severity check order matters: an alert is counted once, by its highest
# severity (matches the original elif-chain in _compute_health).
_SEVERITY_ORDER: List[str] = ["CRITICAL", "ALERT", "WARNING"]


def count_alert_severities(alerts: Iterable[str]) -> Dict[str, int]:
    """Count alert strings by severity token, one severity per alert."""
    counts = {sev: 0 for sev in _SEVERITY_ORDER}
    for alert in alerts:
        for sev in _SEVERITY_ORDER:
            if sev in alert:
                counts[sev] += 1
                break
    return counts


def _raw_score(alert_penalty: float, memory_factor: float, cpu_factor: float) -> float:
    """The aggregate score, clamped to [0, 1], unrounded."""
    return max(0.0, min(1.0, (1.0 - alert_penalty) * memory_factor * cpu_factor))


def compute_health_breakdown(
    alert_counts: Dict[str, int],
    memory_pressure: float = 0.0,
    cpu_load: float = 0.0,
) -> Dict[str, Any]:
    """Compute the health score AND its components from alert counts + load.

    Returns a dict the API can ship verbatim so the mobile client can explain
    "where the number comes from":
        {score, base, alert_penalty, alerts{}, memory_pressure, memory_factor,
         cpu_load, cpu_factor, weights{}}

    The ``score`` here is rounded for display; the live tick path uses
    :func:`compute_health_score`, which returns the unrounded value.
    """
    counts = {sev: int(alert_counts.get(sev, 0)) for sev in _SEVERITY_ORDER}
    alert_penalty = sum(counts[sev] * ALERT_PENALTIES[sev] for sev in _SEVERITY_ORDER)

    memory_factor = 1.0 - (float(memory_pressure) / 100.0) * MEMORY_WEIGHT
    cpu_factor = 1.0 - (float(cpu_load) / 100.0) * CPU_WEIGHT

    return {
        "score": round(_raw_score(alert_penalty, memory_factor, cpu_factor), 3),
        "base": 1.0,
        "alert_penalty": round(alert_penalty, 3),
        "alerts": counts,
        "memory_pressure": round(float(memory_pressure), 1),
        "memory_factor": round(memory_factor, 3),
        "cpu_load": round(float(cpu_load), 1),
        "cpu_factor": round(cpu_factor, 3),
        "weights": {
            "CRITICAL": ALERT_PENALTIES["CRITICAL"],
            "ALERT": ALERT_PENALTIES["ALERT"],
            "WARNING": ALERT_PENALTIES["WARNING"],
            "memory": MEMORY_WEIGHT,
            "cpu": CPU_WEIGHT,
        },
    }


def compute_health_score(
    alerts: Iterable[str],
    memory_pressure: float = 0.0,
    cpu_load: float = 0.0,
) -> float:
    """Aggregate health score (0..1) from alert strings + resource load.

    The function the live tick path uses. Returns the UNROUNDED clamped score
    (callers such as the event logger round for storage), matching the original
    inline formula to float precision.
    """
    counts = count_alert_severities(alerts)
    alert_penalty = sum(counts[sev] * ALERT_PENALTIES[sev] for sev in _SEVERITY_ORDER)
    memory_factor = 1.0 - (float(memory_pressure) / 100.0) * MEMORY_WEIGHT
    cpu_factor = 1.0 - (float(cpu_load) / 100.0) * CPU_WEIGHT
    return _raw_score(alert_penalty, memory_factor, cpu_factor)
