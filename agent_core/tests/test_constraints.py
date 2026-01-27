"""
Tests for constraint validation.

Spec reference: homeostasis_spec.md section 4 (lines 450-550)
"""

import pytest
import time

from agent_core.homeostasis.constraints import (
    ConstraintValidator,
    Thresholds,
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
            "ram_available_mb": 2000,
            "cpu_load": 30,
            "disk_used_pct": 40,
            "temp_c": 55,
            "context_coherence": 0.95,
            "coherence_ok": True,
            "error_count_1h": 2,
            "errors_high": False,
            "goal_stack_depth": 3,
            "goal_stack_runaway": False,
        }

        all_ok, alerts = validator.validate(healthy_state)

        assert all_ok
        assert len(alerts) == 0

    def test_critical_ram_violation(self, validator):
        """Low RAM should trigger CRITICAL violation."""
        low_ram_state = {
            "ram_available_mb": 50,  # Below 100MB critical
            "cpu_load": 30,
            "disk_used_pct": 40,
            "temp_c": 55,
            "coherence_ok": True,
        }

        all_ok, alerts = validator.validate(low_ram_state)

        assert not all_ok
        critical = [a for a in alerts if "CRITICAL" in a]
        assert len(critical) >= 1
        assert any("RAM" in a for a in critical)

    def test_alert_ram_violation(self, validator):
        """Medium-low RAM should trigger ALERT violation."""
        medium_ram_state = {
            "ram_available_mb": 150,  # Between 100 and 200 (ALERT)
            "cpu_load": 30,
            "disk_used_pct": 40,
            "temp_c": 55,
            "coherence_ok": True,
        }

        all_ok, alerts = validator.validate(medium_ram_state)

        assert not all_ok
        alert_msgs = [a for a in alerts if "ALERT" in a]
        assert len(alert_msgs) >= 1

    def test_warning_ram_violation(self, validator):
        """Slightly low RAM should trigger WARNING."""
        warning_ram_state = {
            "ram_available_mb": 400,  # Between 200 and 500 (WARNING)
            "cpu_load": 30,
            "disk_used_pct": 40,
            "temp_c": 55,
            "coherence_ok": True,
        }

        all_ok, alerts = validator.validate(warning_ram_state)

        warnings = [a for a in alerts if "WARNING" in a]
        assert len(warnings) >= 1

    def test_critical_temperature(self, validator):
        """High temperature should trigger CRITICAL."""
        hot_state = {
            "ram_available_mb": 2000,
            "cpu_load": 30,
            "disk_used_pct": 40,
            "temp_c": 96,  # Above 95C critical
            "coherence_ok": True,
        }

        all_ok, alerts = validator.validate(hot_state)

        critical = [a for a in alerts if "CRITICAL" in a]
        assert len(critical) >= 1
        assert any("Temperature" in a or "temp" in a.lower() for a in critical)

    def test_coherence_violation(self, validator):
        """Low coherence should trigger WARNING."""
        incoherent_state = {
            "ram_available_mb": 2000,
            "cpu_load": 30,
            "disk_used_pct": 40,
            "temp_c": 55,
            "context_coherence": 0.5,
            "coherence_ok": False,
        }

        all_ok, alerts = validator.validate(incoherent_state)

        warnings = [a for a in alerts if "WARNING" in a]
        assert len(warnings) >= 1
        assert any("coherence" in a.lower() for a in warnings)

    def test_goal_stack_runaway(self, validator):
        """Deep goal stack should trigger ALERT."""
        runaway_state = {
            "ram_available_mb": 2000,
            "cpu_load": 30,
            "disk_used_pct": 40,
            "temp_c": 55,
            "coherence_ok": True,
            "goal_stack_depth": 30,
            "goal_stack_runaway": True,
        }

        all_ok, alerts = validator.validate(runaway_state)

        alert_msgs = [a for a in alerts if "ALERT" in a]
        assert len(alert_msgs) >= 1
        assert any("stack" in a.lower() or "goal" in a.lower() for a in alert_msgs)

    def test_error_rate_alert(self, validator):
        """High error rate should trigger WARNING."""
        error_state = {
            "ram_available_mb": 2000,
            "cpu_load": 30,
            "disk_used_pct": 40,
            "temp_c": 55,
            "coherence_ok": True,
            "error_count_1h": 25,
            "errors_high": True,
        }

        all_ok, alerts = validator.validate(error_state)

        warnings = [a for a in alerts if "WARNING" in a]
        assert len(warnings) >= 1
        assert any("error" in a.lower() for a in warnings)

    def test_disk_critical(self, validator):
        """Very high disk usage should trigger CRITICAL."""
        no_disk_state = {
            "ram_available_mb": 2000,
            "cpu_load": 30,
            "disk_used_pct": 96,  # Above 95% critical
            "temp_c": 55,
            "coherence_ok": True,
        }

        all_ok, alerts = validator.validate(no_disk_state)

        critical = [a for a in alerts if "CRITICAL" in a]
        assert len(critical) >= 1

    def test_multiple_violations(self, validator):
        """Multiple issues should produce multiple alerts."""
        bad_state = {
            "ram_available_mb": 50,      # CRITICAL
            "cpu_load": 96,               # ALERT
            "disk_used_pct": 96,          # CRITICAL
            "temp_c": 96,                 # CRITICAL
            "context_coherence": 0.5,     # WARNING
            "coherence_ok": False,
            "error_count_1h": 25,         # WARNING
            "errors_high": True,
            "goal_stack_depth": 30,       # ALERT
            "goal_stack_runaway": True,
        }

        all_ok, alerts = validator.validate(bad_state)

        assert not all_ok
        assert len(alerts) >= 3

        critical = [a for a in alerts if "CRITICAL" in a]
        assert len(critical) >= 2


class TestConstraintSeverity:
    """Tests for constraint severity methods."""

    @pytest.fixture
    def validator(self):
        return ConstraintValidator()

    def test_has_critical(self, validator):
        """Should detect CRITICAL alerts."""
        alerts = ["CRITICAL: RAM low", "WARNING: CPU high"]
        assert validator.has_critical(alerts) == True

        alerts_no_critical = ["ALERT: Something", "WARNING: Something"]
        assert validator.has_critical(alerts_no_critical) == False

    def test_get_severity(self, validator):
        """Should return highest severity."""
        assert validator.get_severity(["CRITICAL: Test"]) == "critical"
        assert validator.get_severity(["ALERT: Test"]) == "alert"
        assert validator.get_severity(["WARNING: Test"]) == "warning"
        assert validator.get_severity([]) == "ok"

    def test_filter_by_severity(self, validator):
        """Should filter alerts by severity."""
        alerts = [
            "CRITICAL: RAM",
            "ALERT: CPU",
            "WARNING: Disk",
            "CRITICAL: Temp",
        ]

        critical = validator.filter_by_severity(alerts, "critical")
        assert len(critical) == 2

        warnings = validator.filter_by_severity(alerts, "warning")
        assert len(warnings) == 1

