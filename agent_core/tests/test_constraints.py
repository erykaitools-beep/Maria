"""
Tests for constraint validation.

Spec reference: homeostasis_spec.md section 4 (lines 450-550)
"""

import pytest
import time

from agent_core.homeostasis.constraints import (
    ConstraintValidator,
    ConstraintViolation,
    ConstraintLevel,
)
from agent_core.homeostasis.state_model import Mode


class TestConstraintValidator:
    """Tests for ConstraintValidator - spec lines 450-550."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return ConstraintValidator()

    def test_no_violations_when_healthy(self, validator):
        """Healthy state should produce no violations."""
        healthy_state = {
            "ram_available_pct": 50,
            "cpu_load": 30,
            "disk_free_pct": 40,
            "temp_c": 55,
            "context_coherence": 0.95,
            "error_count_1h": 2,
            "goal_stack_depth": 3,
        }

        violations = validator.validate(healthy_state)

        assert len(violations) == 0

    def test_critical_ram_violation(self, validator):
        """Low RAM should trigger CRITICAL violation.

        Spec: line 463 - RAM < 10% is CRITICAL
        """
        low_ram_state = {
            "ram_available_pct": 5,
            "cpu_load": 30,
            "disk_free_pct": 40,
            "temp_c": 55,
            "context_coherence": 0.95,
            "error_count_1h": 0,
            "goal_stack_depth": 1,
        }

        violations = validator.validate(low_ram_state)

        # Should have at least one CRITICAL violation for RAM
        critical = [v for v in violations if v.level == ConstraintLevel.CRITICAL]
        assert len(critical) >= 1
        assert any("ram" in v.constraint_name.lower() for v in critical)

    def test_alert_ram_violation(self, validator):
        """Medium-low RAM should trigger ALERT violation.

        Spec: line 464 - RAM 10-20% is ALERT
        """
        medium_ram_state = {
            "ram_available_pct": 15,
            "cpu_load": 30,
            "disk_free_pct": 40,
            "temp_c": 55,
            "context_coherence": 0.95,
            "error_count_1h": 0,
            "goal_stack_depth": 1,
        }

        violations = validator.validate(medium_ram_state)

        # Should have ALERT for RAM (not CRITICAL)
        alerts = [v for v in violations if v.level == ConstraintLevel.ALERT]
        assert len(alerts) >= 1

    def test_warning_ram_violation(self, validator):
        """Slightly low RAM should trigger WARNING.

        Spec: line 465 - RAM 20-30% is WARNING
        """
        warning_ram_state = {
            "ram_available_pct": 25,
            "cpu_load": 30,
            "disk_free_pct": 40,
            "temp_c": 55,
            "context_coherence": 0.95,
            "error_count_1h": 0,
            "goal_stack_depth": 1,
        }

        violations = validator.validate(warning_ram_state)

        # Should have WARNING for RAM
        warnings = [v for v in violations if v.level == ConstraintLevel.WARNING]
        assert len(warnings) >= 1

    def test_critical_temperature(self, validator):
        """High temperature should trigger CRITICAL.

        Spec: line 480 - temp > 85C is CRITICAL
        """
        hot_state = {
            "ram_available_pct": 50,
            "cpu_load": 30,
            "disk_free_pct": 40,
            "temp_c": 90,
            "context_coherence": 0.95,
            "error_count_1h": 0,
            "goal_stack_depth": 1,
        }

        violations = validator.validate(hot_state)

        critical = [v for v in violations if v.level == ConstraintLevel.CRITICAL]
        assert len(critical) >= 1
        assert any("temp" in v.constraint_name.lower() for v in critical)

    def test_coherence_violation(self, validator):
        """Low coherence should trigger ALERT.

        Spec: line 490 - coherence < 0.7 is ALERT
        """
        incoherent_state = {
            "ram_available_pct": 50,
            "cpu_load": 30,
            "disk_free_pct": 40,
            "temp_c": 55,
            "context_coherence": 0.5,
            "error_count_1h": 0,
            "goal_stack_depth": 1,
        }

        violations = validator.validate(incoherent_state)

        alerts = [v for v in violations if v.level == ConstraintLevel.ALERT]
        assert len(alerts) >= 1
        assert any("coherence" in v.constraint_name.lower() for v in alerts)

    def test_goal_stack_runaway(self, validator):
        """Deep goal stack should trigger WARNING.

        Spec: line 495 - goal_stack > 10 is WARNING (potential runaway)
        """
        runaway_state = {
            "ram_available_pct": 50,
            "cpu_load": 30,
            "disk_free_pct": 40,
            "temp_c": 55,
            "context_coherence": 0.95,
            "error_count_1h": 0,
            "goal_stack_depth": 15,
        }

        violations = validator.validate(runaway_state)

        warnings = [v for v in violations if v.level == ConstraintLevel.WARNING]
        assert len(warnings) >= 1
        assert any("goal" in v.constraint_name.lower() for v in warnings)

    def test_error_rate_alert(self, validator):
        """High error rate should trigger ALERT.

        Spec: line 500 - errors > 10/hour is ALERT
        """
        error_state = {
            "ram_available_pct": 50,
            "cpu_load": 30,
            "disk_free_pct": 40,
            "temp_c": 55,
            "context_coherence": 0.95,
            "error_count_1h": 15,
            "goal_stack_depth": 1,
        }

        violations = validator.validate(error_state)

        alerts = [v for v in violations if v.level == ConstraintLevel.ALERT]
        assert len(alerts) >= 1
        assert any("error" in v.constraint_name.lower() for v in alerts)

    def test_disk_critical(self, validator):
        """Very low disk should trigger CRITICAL.

        Spec: line 475 - disk < 1% is CRITICAL
        """
        no_disk_state = {
            "ram_available_pct": 50,
            "cpu_load": 30,
            "disk_free_pct": 0.5,
            "temp_c": 55,
            "context_coherence": 0.95,
            "error_count_1h": 0,
            "goal_stack_depth": 1,
        }

        violations = validator.validate(no_disk_state)

        critical = [v for v in violations if v.level == ConstraintLevel.CRITICAL]
        assert len(critical) >= 1

    def test_multiple_violations(self, validator):
        """Multiple issues should produce multiple violations."""
        bad_state = {
            "ram_available_pct": 5,      # CRITICAL
            "cpu_load": 95,               # WARNING
            "disk_free_pct": 2,           # ALERT
            "temp_c": 90,                 # CRITICAL
            "context_coherence": 0.5,     # ALERT
            "error_count_1h": 20,         # ALERT
            "goal_stack_depth": 15,       # WARNING
        }

        violations = validator.validate(bad_state)

        # Should have multiple violations
        assert len(violations) >= 3

        # Should have at least 2 CRITICAL
        critical = [v for v in violations if v.level == ConstraintLevel.CRITICAL]
        assert len(critical) >= 2


class TestConstraintLevels:
    """Tests for constraint level priority."""

    def test_critical_is_highest(self):
        """CRITICAL should be highest priority."""
        # Implicit test - critical constraints force SURVIVAL mode
        from agent_core.homeostasis.mode_regulator import ModeRegulator

        regulator = ModeRegulator()

        violation = ConstraintViolation(
            constraint_name="TEST",
            level=ConstraintLevel.CRITICAL,
            current_value=0,
            threshold=10,
            message="Test critical",
        )

        # CRITICAL should recommend SURVIVAL mode
        recommendation = regulator.recommend_mode(
            current_mode=Mode.ACTIVE,
            violations=[violation],
            interpreted_state={},
        )

        assert recommendation == Mode.SURVIVAL

    def test_alert_suggests_reduced(self):
        """ALERT should suggest REDUCED mode."""
        from agent_core.homeostasis.mode_regulator import ModeRegulator

        regulator = ModeRegulator()

        violation = ConstraintViolation(
            constraint_name="TEST",
            level=ConstraintLevel.ALERT,
            current_value=5,
            threshold=10,
            message="Test alert",
        )

        recommendation = regulator.recommend_mode(
            current_mode=Mode.ACTIVE,
            violations=[violation],
            interpreted_state={},
        )

        # Should recommend reduced operation
        assert recommendation in (Mode.REDUCED, Mode.SLEEP)

    def test_warning_keeps_active(self):
        """WARNING alone should not change from ACTIVE."""
        from agent_core.homeostasis.mode_regulator import ModeRegulator

        regulator = ModeRegulator()

        violation = ConstraintViolation(
            constraint_name="TEST",
            level=ConstraintLevel.WARNING,
            current_value=8,
            threshold=10,
            message="Test warning",
        )

        recommendation = regulator.recommend_mode(
            current_mode=Mode.ACTIVE,
            violations=[violation],
            interpreted_state={},
        )

        # Single warning should not force mode change
        assert recommendation == Mode.ACTIVE

