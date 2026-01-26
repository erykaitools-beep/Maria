"""
Tests for mode regulation and transitions.

Spec reference: homeostasis_spec.md section 5 (lines 550-700)
"""

import pytest
import time

from agent_core.homeostasis.mode_regulator import ModeRegulator
from agent_core.homeostasis.state_model import Mode
from agent_core.homeostasis.constraints import ConstraintViolation, ConstraintLevel


class TestModeRegulator:
    """Tests for ModeRegulator - spec lines 550-700."""

    @pytest.fixture
    def regulator(self):
        """Create regulator instance."""
        return ModeRegulator()

    def test_initial_mode_is_active(self, regulator):
        """Default initial mode should be ACTIVE."""
        # When no violations, should stay/recommend ACTIVE
        recommendation = regulator.recommend_mode(
            current_mode=Mode.ACTIVE,
            violations=[],
            interpreted_state={},
        )

        assert recommendation == Mode.ACTIVE


class TestValidTransitions:
    """Tests for valid mode transitions - spec lines 600-650."""

    @pytest.fixture
    def regulator(self):
        return ModeRegulator()

    # ACTIVE transitions
    def test_active_to_reduced(self, regulator):
        """ACTIVE -> REDUCED is valid."""
        assert regulator.is_valid_transition(Mode.ACTIVE, Mode.REDUCED) == True

    def test_active_to_sleep(self, regulator):
        """ACTIVE -> SLEEP is valid."""
        assert regulator.is_valid_transition(Mode.ACTIVE, Mode.SLEEP) == True

    def test_active_to_survival(self, regulator):
        """ACTIVE -> SURVIVAL is valid (emergency)."""
        assert regulator.is_valid_transition(Mode.ACTIVE, Mode.SURVIVAL) == True

    # REDUCED transitions
    def test_reduced_to_active(self, regulator):
        """REDUCED -> ACTIVE is valid (recovery)."""
        assert regulator.is_valid_transition(Mode.REDUCED, Mode.ACTIVE) == True

    def test_reduced_to_sleep(self, regulator):
        """REDUCED -> SLEEP is valid."""
        assert regulator.is_valid_transition(Mode.REDUCED, Mode.SLEEP) == True

    def test_reduced_to_survival(self, regulator):
        """REDUCED -> SURVIVAL is valid (emergency)."""
        assert regulator.is_valid_transition(Mode.REDUCED, Mode.SURVIVAL) == True

    # SLEEP transitions
    def test_sleep_to_reduced(self, regulator):
        """SLEEP -> REDUCED is valid (wake up)."""
        assert regulator.is_valid_transition(Mode.SLEEP, Mode.REDUCED) == True

    def test_sleep_to_survival(self, regulator):
        """SLEEP -> SURVIVAL is valid (emergency)."""
        assert regulator.is_valid_transition(Mode.SLEEP, Mode.SURVIVAL) == True

    # SURVIVAL transitions
    def test_survival_to_reduced(self, regulator):
        """SURVIVAL -> REDUCED is valid (controlled recovery)."""
        assert regulator.is_valid_transition(Mode.SURVIVAL, Mode.REDUCED) == True


class TestForbiddenTransitions:
    """Tests for forbidden transitions - spec lines 650-680."""

    @pytest.fixture
    def regulator(self):
        return ModeRegulator()

    def test_sleep_to_active_forbidden(self, regulator):
        """SLEEP -> ACTIVE is forbidden (must go through REDUCED).

        Spec: line 655 - skip transitions forbidden
        """
        assert regulator.is_valid_transition(Mode.SLEEP, Mode.ACTIVE) == False

    def test_survival_to_active_forbidden(self, regulator):
        """SURVIVAL -> ACTIVE is forbidden.

        Spec: line 656 - must recover through REDUCED
        """
        assert regulator.is_valid_transition(Mode.SURVIVAL, Mode.ACTIVE) == False

    def test_survival_to_sleep_forbidden(self, regulator):
        """SURVIVAL -> SLEEP is forbidden.

        Spec: line 657 - cannot go dormant from survival
        """
        assert regulator.is_valid_transition(Mode.SURVIVAL, Mode.SLEEP) == False


class TestModeRecommendation:
    """Tests for mode recommendation logic - spec lines 680-700."""

    @pytest.fixture
    def regulator(self):
        return ModeRegulator()

    def test_critical_violation_forces_survival(self, regulator):
        """CRITICAL violation should force SURVIVAL mode.

        Spec: line 685 - CRITICAL always triggers SURVIVAL
        """
        violation = ConstraintViolation(
            constraint_name="RAM_CRITICAL",
            level=ConstraintLevel.CRITICAL,
            current_value=5,
            threshold=10,
            message="RAM critically low",
        )

        mode = regulator.recommend_mode(
            current_mode=Mode.ACTIVE,
            violations=[violation],
            interpreted_state={},
        )

        assert mode == Mode.SURVIVAL

    def test_alert_in_active_suggests_reduced(self, regulator):
        """ALERT in ACTIVE should suggest REDUCED.

        Spec: line 688 - ALERT triggers step-down
        """
        violation = ConstraintViolation(
            constraint_name="COHERENCE_LOW",
            level=ConstraintLevel.ALERT,
            current_value=0.6,
            threshold=0.7,
            message="Coherence below threshold",
        )

        mode = regulator.recommend_mode(
            current_mode=Mode.ACTIVE,
            violations=[violation],
            interpreted_state={},
        )

        assert mode == Mode.REDUCED

    def test_no_violations_stay_current(self, regulator):
        """No violations should maintain current mode."""
        mode = regulator.recommend_mode(
            current_mode=Mode.REDUCED,
            violations=[],
            interpreted_state={},
        )

        # May stay or suggest upgrade, but won't downgrade
        assert mode in (Mode.REDUCED, Mode.ACTIVE)

    def test_healthy_in_reduced_suggests_active(self, regulator):
        """Healthy state in REDUCED should suggest ACTIVE.

        Spec: line 692 - upgrade when stable
        """
        mode = regulator.recommend_mode(
            current_mode=Mode.REDUCED,
            violations=[],
            interpreted_state={
                "stable_ticks": 60,  # Stable for 60 ticks
            },
        )

        assert mode == Mode.ACTIVE

    def test_night_time_suggests_sleep(self, regulator):
        """Night time with low activity should suggest SLEEP.

        Spec: line 695 - circadian sleep
        """
        mode = regulator.recommend_mode(
            current_mode=Mode.REDUCED,
            violations=[],
            interpreted_state={
                "is_night": True,
                "idle_seconds": 1800,  # 30 minutes idle
            },
        )

        assert mode == Mode.SLEEP


class TestModeMinimumDuration:
    """Tests for minimum mode duration - spec lines 700-720."""

    @pytest.fixture
    def regulator(self):
        return ModeRegulator()

    def test_survival_minimum_duration(self, regulator):
        """SURVIVAL has minimum duration before upgrade.

        Spec: line 705 - min 5 minutes in SURVIVAL
        """
        # Just entered SURVIVAL
        can_upgrade = regulator.can_upgrade_from_survival(
            time_in_mode_seconds=60  # Only 1 minute
        )

        assert can_upgrade == False

        # After 5 minutes
        can_upgrade = regulator.can_upgrade_from_survival(
            time_in_mode_seconds=310  # 5+ minutes
        )

        assert can_upgrade == True

    def test_reduced_minimum_before_active(self, regulator):
        """REDUCED has minimum duration before ACTIVE.

        Spec: line 708 - min 2 minutes stability
        """
        can_upgrade = regulator.can_upgrade_to_active(
            time_in_mode_seconds=60,  # 1 minute
            stable_ticks=60,
        )

        assert can_upgrade == False

        can_upgrade = regulator.can_upgrade_to_active(
            time_in_mode_seconds=130,  # 2+ minutes
            stable_ticks=120,
        )

        assert can_upgrade == True


class TestMultipleViolations:
    """Tests for handling multiple simultaneous violations."""

    @pytest.fixture
    def regulator(self):
        return ModeRegulator()

    def test_critical_overrides_all(self, regulator):
        """CRITICAL overrides lower-level violations."""
        violations = [
            ConstraintViolation(
                constraint_name="CPU_HIGH",
                level=ConstraintLevel.WARNING,
                current_value=80,
                threshold=70,
                message="CPU warning",
            ),
            ConstraintViolation(
                constraint_name="RAM_CRITICAL",
                level=ConstraintLevel.CRITICAL,
                current_value=5,
                threshold=10,
                message="RAM critical",
            ),
            ConstraintViolation(
                constraint_name="COHERENCE",
                level=ConstraintLevel.ALERT,
                current_value=0.6,
                threshold=0.7,
                message="Coherence alert",
            ),
        ]

        mode = regulator.recommend_mode(
            current_mode=Mode.ACTIVE,
            violations=violations,
            interpreted_state={},
        )

        # CRITICAL should force SURVIVAL regardless of others
        assert mode == Mode.SURVIVAL

    def test_multiple_alerts_more_aggressive(self, regulator):
        """Multiple ALERT violations may trigger more aggressive response."""
        violations = [
            ConstraintViolation(
                constraint_name="COHERENCE",
                level=ConstraintLevel.ALERT,
                current_value=0.65,
                threshold=0.7,
                message="Coherence alert",
            ),
            ConstraintViolation(
                constraint_name="ERRORS",
                level=ConstraintLevel.ALERT,
                current_value=12,
                threshold=10,
                message="Error rate alert",
            ),
            ConstraintViolation(
                constraint_name="DISK",
                level=ConstraintLevel.ALERT,
                current_value=3,
                threshold=5,
                message="Disk alert",
            ),
        ]

        mode = regulator.recommend_mode(
            current_mode=Mode.ACTIVE,
            violations=violations,
            interpreted_state={},
        )

        # Multiple alerts should at least trigger REDUCED
        assert mode in (Mode.REDUCED, Mode.SLEEP, Mode.SURVIVAL)

