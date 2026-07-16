"""Tests for CorrectiveActionGenerator cooldown throttling.

Regression guard for the CPU-pause corrective (Action 2): the pause signal is
idempotent (learning stays paused between re-issues), so the corrective must NOT
be re-emitted on every tick while CPU is chronically saturated -- that only spams
the event log (~5000+ identical lines/day observed in production). A cooldown
gates re-emission, mirroring Action 1 (memory consolidation).
"""

import time

from agent_core.homeostasis.actions import CorrectiveActionGenerator


def _pause_actions(actions):
    """Extract learning_engine pause correctives from a generated batch."""
    return [
        a for a in actions
        if a.target == "learning_engine" and a.action == "pause"
    ]


def test_cpu_pause_emitted_when_saturated():
    """First saturation tick emits exactly one pause corrective."""
    gen = CorrectiveActionGenerator()
    actions = gen.generate_actions({"cpu_load": 95}, alerts=[])
    assert len(_pause_actions(actions)) == 1


def test_cpu_pause_not_emitted_below_threshold():
    """No pause corrective when CPU is below the pause threshold."""
    gen = CorrectiveActionGenerator()
    actions = gen.generate_actions({"cpu_load": 50}, alerts=[])
    assert _pause_actions(actions) == []


def test_cpu_pause_throttled_within_cooldown():
    """Back-to-back saturated ticks emit the pause only once (the fix)."""
    gen = CorrectiveActionGenerator()
    first = gen.generate_actions({"cpu_load": 99}, alerts=[])
    second = gen.generate_actions({"cpu_load": 99}, alerts=[])
    assert len(_pause_actions(first)) == 1
    assert _pause_actions(second) == []  # gated by cooldown


def test_cpu_pause_re_emitted_after_cooldown():
    """Once the cooldown elapses, a still-saturated CPU re-emits the pause."""
    gen = CorrectiveActionGenerator()
    gen.generate_actions({"cpu_load": 99}, alerts=[])
    # Simulate the cooldown window having elapsed.
    gen._last_cpu_pause_request = time.time() - gen._cpu_pause_cooldown - 1
    actions = gen.generate_actions({"cpu_load": 99}, alerts=[])
    assert len(_pause_actions(actions)) == 1


# ─────────────────────────────────────────────────────────────
# Action 6: ALERT checkpoint snapshot (same spam mechanism --
# 830 identical trigger_snapshot events / 45 min on 2026-07-12)
# ─────────────────────────────────────────────────────────────

def _snapshot_actions(actions):
    """Extract checkpoint snapshot correctives from a generated batch."""
    return [
        a for a in actions
        if a.action_type.value == "trigger_snapshot" and a.action == "checkpoint"
    ]


def test_alert_snapshot_emitted_on_alert():
    """First ALERT tick emits exactly one checkpoint snapshot."""
    gen = CorrectiveActionGenerator()
    actions = gen.generate_actions({}, alerts=["ALERT: RAM pressure high"])
    assert len(_snapshot_actions(actions)) == 1


def test_alert_snapshot_not_emitted_without_alert():
    """No checkpoint corrective when there is no ALERT-severity alert."""
    gen = CorrectiveActionGenerator()
    actions = gen.generate_actions({}, alerts=["WARNING: something mild"])
    assert _snapshot_actions(actions) == []


def test_alert_snapshot_throttled_within_cooldown():
    """Back-to-back ALERT ticks emit the snapshot only once."""
    gen = CorrectiveActionGenerator()
    first = gen.generate_actions({}, alerts=["ALERT: RAM pressure high"])
    second = gen.generate_actions({}, alerts=["ALERT: RAM pressure high"])
    assert len(_snapshot_actions(first)) == 1
    assert _snapshot_actions(second) == []  # gated by cooldown


def test_alert_snapshot_re_emitted_after_cooldown():
    """A persisting ALERT re-emits the snapshot after the cooldown elapses."""
    gen = CorrectiveActionGenerator()
    gen.generate_actions({}, alerts=["ALERT: RAM pressure high"])
    gen._last_alert_snapshot_request = (
        time.time() - gen._alert_snapshot_cooldown - 1
    )
    actions = gen.generate_actions({}, alerts=["ALERT: RAM pressure high"])
    assert len(_snapshot_actions(actions)) == 1


# ─────────────────────────────────────────────────────────────
# Action 7: thermal throttling pair (36 duplicate events during
# the same 2026-07-12 episode; both signals are idempotent)
# ─────────────────────────────────────────────────────────────

def _thermal_actions(actions):
    """Extract thermal correctives (reason mentions thermal stress)."""
    return [a for a in actions if "Thermal stress" in a.reason]


def test_thermal_pair_emitted_when_hot():
    """First hot tick emits the reduce-batch + pause-learning pair."""
    gen = CorrectiveActionGenerator()
    actions = gen.generate_actions({"temp_c": 90}, alerts=[])
    thermal = _thermal_actions(actions)
    assert len(thermal) == 2
    assert {a.target for a in thermal} == {"llm", "learning_engine"}


def test_thermal_not_emitted_below_threshold():
    """No thermal correctives below the 85 degree threshold."""
    gen = CorrectiveActionGenerator()
    actions = gen.generate_actions({"temp_c": 80}, alerts=[])
    assert _thermal_actions(actions) == []


def test_thermal_throttled_within_cooldown():
    """Back-to-back hot ticks emit the thermal pair only once."""
    gen = CorrectiveActionGenerator()
    first = gen.generate_actions({"temp_c": 90}, alerts=[])
    second = gen.generate_actions({"temp_c": 91}, alerts=[])
    assert len(_thermal_actions(first)) == 2
    assert _thermal_actions(second) == []  # gated by cooldown


def test_thermal_re_emitted_after_cooldown():
    """Still-hot CPU re-emits the thermal pair after the cooldown elapses."""
    gen = CorrectiveActionGenerator()
    gen.generate_actions({"temp_c": 90}, alerts=[])
    gen._last_thermal_request = time.time() - gen._thermal_cooldown - 1
    actions = gen.generate_actions({"temp_c": 90}, alerts=[])
    assert len(_thermal_actions(actions)) == 2
