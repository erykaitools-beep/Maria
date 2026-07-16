"""
Tests for mode regulation and transitions.

Spec reference: homeostasis_spec.md section 5 (lines 550-700)
"""

import pytest
import time
from unittest.mock import patch

from agent_core.homeostasis.mode_regulator import ModeRegulator, TransitionResult
from agent_core.homeostasis.state_model import Mode


class TestModeRegulator:
    """Tests for ModeRegulator - spec lines 550-700."""

    @pytest.fixture
    def regulator(self):
        """Create regulator instance."""
        return ModeRegulator()

    def test_initial_mode_is_active(self, regulator):
        """Default initial mode should be ACTIVE."""
        assert regulator.current_mode == Mode.ACTIVE


class TestValidTransitions:
    """Tests for valid mode transitions - spec lines 600-650."""

    @pytest.fixture
    def regulator(self):
        return ModeRegulator()

    # ACTIVE transitions
    def test_active_to_reduced(self, regulator):
        """ACTIVE -> REDUCED is valid."""
        result = regulator.transition_to(Mode.REDUCED)
        assert result == TransitionResult.SUCCESS
        assert regulator.current_mode == Mode.REDUCED

    def test_active_to_sleep(self, regulator):
        """ACTIVE -> SLEEP is valid."""
        result = regulator.transition_to(Mode.SLEEP)
        assert result == TransitionResult.SUCCESS
        assert regulator.current_mode == Mode.SLEEP

    def test_active_to_survival(self, regulator):
        """ACTIVE -> SURVIVAL is valid (emergency)."""
        result = regulator.transition_to(Mode.SURVIVAL)
        assert result == TransitionResult.SUCCESS
        assert regulator.current_mode == Mode.SURVIVAL

    # REDUCED transitions
    def test_reduced_to_active(self, regulator):
        """REDUCED -> ACTIVE is valid (recovery)."""
        regulator.transition_to(Mode.REDUCED)
        result = regulator.transition_to(Mode.ACTIVE)
        assert result == TransitionResult.SUCCESS
        assert regulator.current_mode == Mode.ACTIVE

    def test_reduced_to_sleep(self, regulator):
        """REDUCED -> SLEEP is valid."""
        regulator.transition_to(Mode.REDUCED)
        result = regulator.transition_to(Mode.SLEEP)
        assert result == TransitionResult.SUCCESS
        assert regulator.current_mode == Mode.SLEEP

    def test_reduced_to_survival(self, regulator):
        """REDUCED -> SURVIVAL is valid (emergency)."""
        regulator.transition_to(Mode.REDUCED)
        result = regulator.transition_to(Mode.SURVIVAL)
        assert result == TransitionResult.SUCCESS
        assert regulator.current_mode == Mode.SURVIVAL

    # SLEEP transitions
    def test_sleep_to_active(self, regulator):
        """SLEEP -> ACTIVE is valid."""
        regulator.transition_to(Mode.SLEEP)
        result = regulator.transition_to(Mode.ACTIVE)
        assert result == TransitionResult.SUCCESS
        assert regulator.current_mode == Mode.ACTIVE

    def test_sleep_to_survival(self, regulator):
        """SLEEP -> SURVIVAL is valid (emergency)."""
        regulator.transition_to(Mode.SLEEP)
        result = regulator.transition_to(Mode.SURVIVAL)
        assert result == TransitionResult.SUCCESS
        assert regulator.current_mode == Mode.SURVIVAL

    # SURVIVAL transitions
    def test_survival_to_active(self, regulator):
        """SURVIVAL -> ACTIVE is valid (recovery)."""
        regulator.transition_to(Mode.SURVIVAL)
        result = regulator.transition_to(Mode.ACTIVE)
        assert result == TransitionResult.SUCCESS
        assert regulator.current_mode == Mode.ACTIVE


class TestForbiddenTransitions:
    """Tests for forbidden transitions - spec lines 650-680."""

    @pytest.fixture
    def regulator(self):
        return ModeRegulator()

    def test_sleep_to_reduced_forbidden(self, regulator):
        """SLEEP -> REDUCED is forbidden."""
        regulator.transition_to(Mode.SLEEP)
        result = regulator.transition_to(Mode.REDUCED)
        assert result == TransitionResult.FORBIDDEN
        assert regulator.current_mode == Mode.SLEEP  # Unchanged

    def test_survival_to_reduced_forbidden(self, regulator):
        """SURVIVAL -> REDUCED is forbidden."""
        regulator.transition_to(Mode.SURVIVAL)
        result = regulator.transition_to(Mode.REDUCED)
        assert result == TransitionResult.FORBIDDEN
        assert regulator.current_mode == Mode.SURVIVAL  # Unchanged

    def test_survival_to_sleep_forbidden(self, regulator):
        """SURVIVAL -> SLEEP is forbidden."""
        regulator.transition_to(Mode.SURVIVAL)
        result = regulator.transition_to(Mode.SLEEP)
        assert result == TransitionResult.FORBIDDEN
        assert regulator.current_mode == Mode.SURVIVAL  # Unchanged


class TestModeDecision:
    """Tests for mode decision logic - spec lines 680-700."""

    @pytest.fixture
    def regulator(self):
        return ModeRegulator()

    def test_critical_alert_forces_survival(self, regulator):
        """CRITICAL alert should force SURVIVAL mode."""
        state = {}
        alerts = ["CRITICAL: RAM pressure imminent OOM"]

        mode = regulator.decide_mode(state, alerts)

        assert mode == Mode.SURVIVAL

    def test_alert_in_active_suggests_reduced(self, regulator):
        """ALERT in ACTIVE should suggest REDUCED."""
        state = {
            "ram_available_pct": 15,  # Low RAM
        }
        alerts = ["ALERT: RAM pressure critical"]

        mode = regulator.decide_mode(state, alerts)

        assert mode == Mode.REDUCED

    def test_no_alerts_maintains_active(self, regulator):
        """No alerts should maintain ACTIVE."""
        state = {
            "ram_available_pct": 60,
            "cpu_load": 30,
        }
        alerts = []

        mode = regulator.decide_mode(state, alerts)

        assert mode == Mode.ACTIVE

    def test_night_idle_suggests_sleep(self, regulator):
        """Long idle should suggest SLEEP when RAM is good.

        Spec: IDLE_FOR_SLEEP_SEC = 1800 (30 min), needs ram > 60%
        """
        state = {
            "is_night": True,
            "idle_seconds": 2000,  # > 30 minutes (1800)
            "ram_available_pct": 70,  # > 60% threshold
            "cpu_load": 30,
        }
        alerts = []

        with patch.object(ModeRegulator, '_is_learning_window', return_value=False):
            mode = regulator.decide_mode(state, alerts)

        assert mode == Mode.SLEEP

    def test_learning_window_prevents_sleep(self, regulator):
        """Maria should not go to SLEEP during learning windows."""
        state = {
            "idle_seconds": 5000,
            "ram_available_pct": 80,
            "cpu_load": 20,
        }
        with patch.object(ModeRegulator, '_is_learning_window', return_value=True):
            mode = regulator.decide_mode(state, [])
        assert mode == Mode.ACTIVE

    def test_learning_window_recovers_from_reduced_not_trapped(self, regulator):
        """Regression (2026-06-15): a CPU-spike demote to REDUCED during a
        learning window must still recover to ACTIVE.

        The no-sleep branch used to ``return self.current_mode``, which
        short-circuited the REDUCED->ACTIVE recovery below. A healthy idle box
        therefore sat in REDUCED (light-only) for the whole window -- the
        afternoon 14-16 window had 11/12 learns blocked by mode=reduced. After
        the fix the branch falls through so recovery can engage."""
        regulator.transition_to(Mode.REDUCED)
        state = {
            "idle_seconds": 5000,      # > IDLE_FOR_SLEEP_SEC: would otherwise sleep
            "ram_available_pct": 80,   # healthy
            "cpu_load": 20,            # healthy: the CPU spike is over
        }
        with patch.object(ModeRegulator, "_is_learning_window", return_value=True):
            # First tick must reach the recovery branch and start the stability
            # timer (the bug never got here -- it froze in REDUCED).
            regulator.decide_mode(state, [])
            assert regulator._stable_since is not None, (
                "recovery timer never started -- still trapped in REDUCED"
            )
            # Once the stability window elapses, it must lift back to ACTIVE.
            regulator._stable_since = time.time() - (
                regulator.STABLE_TIME_FOR_ACTIVE_SEC + 5
            )
            recovered = regulator.decide_mode(state, [])
        assert recovered == Mode.ACTIVE

    def test_learning_window_wakes_from_sleep(self, regulator):
        """Maria should auto-wake from SLEEP when learning window starts."""
        regulator.transition_to(Mode.SLEEP)
        state = {
            "idle_seconds": 50000,
            "ram_available_pct": 80,
            "cpu_load": 20,
        }
        with patch.object(ModeRegulator, '_is_learning_window', return_value=True):
            mode = regulator.decide_mode(state, [])
        assert mode == Mode.ACTIVE

    def test_user_override_respected(self, regulator):
        """User override should be respected if not critical."""
        state = {}
        alerts = ["WARNING: Something minor"]

        mode = regulator.decide_mode(state, alerts, user_override=Mode.REDUCED)

        assert mode == Mode.REDUCED

    def test_user_override_ignored_on_critical(self, regulator):
        """User override should be ignored when CRITICAL."""
        state = {}
        alerts = ["CRITICAL: Temperature critical"]

        mode = regulator.decide_mode(state, alerts, user_override=Mode.ACTIVE)

        # Should force SURVIVAL despite override
        assert mode == Mode.SURVIVAL


class TestModeTimings:
    """Tests for mode timing constraints."""

    @pytest.fixture
    def regulator(self):
        return ModeRegulator()

    def test_mode_change_updates_timestamp(self, regulator):
        """Mode change should update change time."""
        initial_time = regulator.mode_change_time

        time.sleep(0.01)  # Small delay

        regulator.transition_to(Mode.REDUCED)

        assert regulator.mode_change_time > initial_time

    def test_same_mode_returns_already_in_mode(self, regulator):
        """Transitioning to same mode should indicate already there."""
        result = regulator.transition_to(Mode.ACTIVE)

        assert result == TransitionResult.ALREADY_IN_MODE


class TestMultipleAlerts:
    """Tests for handling multiple simultaneous alerts."""

    @pytest.fixture
    def regulator(self):
        return ModeRegulator()

    def test_critical_overrides_all(self, regulator):
        """CRITICAL should override lower-level concerns."""
        state = {
            "is_night": True,  # Would normally suggest SLEEP
            "idle_seconds": 2000,
        }
        alerts = [
            "WARNING: CPU high",
            "CRITICAL: RAM pressure imminent OOM",
            "ALERT: Disk space low",
        ]

        mode = regulator.decide_mode(state, alerts)

        # CRITICAL should force SURVIVAL
        assert mode == Mode.SURVIVAL

    def test_multiple_alerts_trigger_reduced(self, regulator):
        """Multiple ALERT violations with bad metrics should trigger REDUCED."""
        # ALERT messages alone don't trigger mode changes
        # Mode is determined by actual metrics in state
        state = {
            "ram_available_pct": 15,  # Below RAM_FOR_REDUCED_PCT (20)
            "cpu_load": 95,           # Above CPU_FOR_REDUCED_PCT (90)
        }
        alerts = [
            "ALERT: RAM pressure critical",
            "ALERT: CPU saturated",
            "ALERT: Disk usage high",
        ]

        mode = regulator.decide_mode(state, alerts)

        # Bad metrics should trigger REDUCED
        assert mode == Mode.REDUCED

    def test_cpu_single_spike_does_not_trigger_reduced(self, regulator):
        """Single CPU spike should NOT demote to REDUCED (avoids flapping during LLM inference)."""
        state = {
            "ram_available_pct": 60,
            "cpu_load": 95,  # Above threshold, but just one tick
        }
        mode = regulator.decide_mode(state, [])
        assert mode == Mode.ACTIVE

    def test_cpu_sustained_spike_triggers_reduced(self, regulator):
        """CPU above threshold for CPU_SPIKE_TICKS_FOR_REDUCED consecutive ticks triggers REDUCED."""
        # Expire startup grace period so CPU demote is active
        regulator._startup_time = time.time() - regulator.STARTUP_GRACE_PERIOD_SEC - 1
        state = {
            "ram_available_pct": 60,
            "cpu_load": 95,  # Above threshold
        }
        # Need N consecutive high-CPU ticks
        for _ in range(regulator.CPU_SPIKE_TICKS_FOR_REDUCED):
            mode = regulator.decide_mode(state, [])
        assert mode == Mode.REDUCED

    def test_cpu_spike_counter_resets_on_low_cpu(self, regulator):
        """CPU spike counter should reset when CPU drops below threshold."""
        high = {"ram_available_pct": 60, "cpu_load": 95}
        low = {"ram_available_pct": 60, "cpu_load": 30}
        # Two high ticks, then one low - counter should reset
        regulator.decide_mode(high, [])
        regulator.decide_mode(high, [])
        regulator.decide_mode(low, [])  # Reset counter
        # Now another high tick alone should not trigger REDUCED
        mode = regulator.decide_mode(high, [])
        assert mode == Mode.ACTIVE

    def test_startup_grace_period_prevents_cpu_demote(self, regulator):
        """During startup grace period, sustained CPU spikes should NOT demote (Ollama model load)."""
        high = {"ram_available_pct": 60, "cpu_load": 99}
        # Even many consecutive high-CPU ticks should not demote during grace
        for _ in range(10):
            mode = regulator.decide_mode(high, [])
        assert mode == Mode.ACTIVE

    def test_startup_grace_does_not_block_ram_pressure(self, regulator):
        """RAM pressure must still demote even during startup grace (memory leak safety)."""
        state = {"ram_available_pct": 15, "cpu_load": 30}  # Low RAM
        mode = regulator.decide_mode(state, [])
        assert mode == Mode.REDUCED

    def test_startup_grace_does_not_block_survival(self, regulator):
        """CRITICAL alerts must still force SURVIVAL even during startup grace."""
        state = {"ram_available_pct": 60, "cpu_load": 99}
        mode = regulator.decide_mode(state, ["CRITICAL: RAM pressure imminent OOM"])
        assert mode == Mode.SURVIVAL

    def test_cpu_demote_works_after_grace_expires(self, regulator):
        """After grace period expires, sustained CPU should demote normally."""
        # Simulate grace period expired
        regulator._startup_time = time.time() - regulator.STARTUP_GRACE_PERIOD_SEC - 1
        high = {"ram_available_pct": 60, "cpu_load": 95}
        for _ in range(regulator.CPU_SPIKE_TICKS_FOR_REDUCED):
            mode = regulator.decide_mode(high, [])
        assert mode == Mode.REDUCED

