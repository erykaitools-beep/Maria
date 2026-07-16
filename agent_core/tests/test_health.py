"""Regression guard: the shared health helper must match the original inline
formula that lived in HomeostasisCore._compute_health, so the API breakdown can
never silently drift from the real score."""

import pytest

from agent_core.homeostasis.health import (
    compute_health_breakdown,
    compute_health_score,
    count_alert_severities,
)


def _original_formula(alerts, memory_pressure, cpu_load):
    """The exact pre-refactor implementation, kept here as the oracle."""
    score = 1.0
    for alert in alerts:
        if "CRITICAL" in alert:
            score -= 0.5
        elif "ALERT" in alert:
            score -= 0.15
        elif "WARNING" in alert:
            score -= 0.05
    score *= (1.0 - memory_pressure / 100 * 0.3)
    score *= (1.0 - cpu_load / 100 * 0.2)
    return max(0.0, min(1.0, score))


ALERT_SETS = [
    [],
    ["RAM CRITICAL"],
    ["CPU ALERT"],
    ["disk WARNING"],
    ["RAM CRITICAL", "CPU ALERT", "disk WARNING"],
    ["CRITICAL a", "CRITICAL b", "CRITICAL c"],  # drives score toward 0/clamp
    ["WARNING x"] * 4,
]


@pytest.mark.parametrize("alerts", ALERT_SETS)
@pytest.mark.parametrize("mem", [0, 25, 50, 100])
@pytest.mark.parametrize("cpu", [0, 40, 95, 100])
def test_helper_matches_original_formula(alerts, mem, cpu):
    # compute_health_score is unrounded (like the original); equal to float noise.
    expected = _original_formula(alerts, mem, cpu)
    assert compute_health_score(alerts, mem, cpu) == pytest.approx(expected, abs=1e-9)


def test_breakdown_components_reconstruct_score():
    counts = {"CRITICAL": 1, "ALERT": 2, "WARNING": 1}  # 0.5 + 0.30 + 0.05 = 0.85
    bd = compute_health_breakdown(counts, memory_pressure=50, cpu_load=40)
    assert bd["alert_penalty"] == pytest.approx(0.85, abs=1e-9)
    assert bd["memory_factor"] == pytest.approx(1 - 0.5 * 0.3, abs=1e-9)  # 0.85
    assert bd["cpu_factor"] == pytest.approx(1 - 0.4 * 0.2, abs=1e-9)     # 0.92
    # (1 - 0.85) * 0.85 * 0.92 = 0.11730
    assert bd["score"] == pytest.approx(0.117, abs=1e-3)
    assert bd["weights"]["CRITICAL"] == 0.5


def test_count_alert_severities_one_per_alert():
    counts = count_alert_severities(["RAM CRITICAL", "x WARNING", "y ALERT", "z ALERT"])
    assert counts == {"CRITICAL": 1, "ALERT": 2, "WARNING": 1}


def test_clamped_to_unit_interval():
    bd = compute_health_breakdown({"CRITICAL": 5}, memory_pressure=0, cpu_load=0)
    assert bd["score"] == 0.0
