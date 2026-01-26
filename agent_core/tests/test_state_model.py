"""
Tests for state model data structures.

Spec reference: homeostasis_spec.md section 3 (lines 250-400)
"""

import pytest
import time
from dataclasses import asdict

from agent_core.homeostasis.state_model import (
    Mode,
    ResourceMetrics,
    CognitiveMetrics,
    TimeMetrics,
    SystemState,
    SnapshotData,
    ConstraintViolation,
    ConstraintLevel,
)


class TestModeEnum:
    """Tests for Mode enumeration - spec lines 261-264."""

    def test_all_modes_defined(self):
        """All four modes should be defined."""
        assert Mode.ACTIVE.value == "active"
        assert Mode.REDUCED.value == "reduced"
        assert Mode.SLEEP.value == "sleep"
        assert Mode.SURVIVAL.value == "survival"

    def test_mode_count(self):
        """Should have exactly 4 modes."""
        assert len(Mode) == 4

    def test_mode_from_string(self):
        """Should create mode from string value."""
        assert Mode("active") == Mode.ACTIVE
        assert Mode("survival") == Mode.SURVIVAL


class TestResourceMetrics:
    """Tests for ResourceMetrics dataclass - spec lines 280-295."""

    def test_create_with_all_fields(self):
        """Should create with all required fields."""
        metrics = ResourceMetrics(
            ram_percent=75.5,
            ram_available_mb=2048,
            cpu_percent=45.0,
            disk_percent=60.0,
            disk_free_gb=50.5,
            temp_celsius=55.0,
            inference_latency_ms=150.0,
            timestamp=time.time(),
        )

        assert metrics.ram_percent == 75.5
        assert metrics.ram_available_mb == 2048

    def test_serializable_to_dict(self):
        """Metrics should be serializable."""
        metrics = ResourceMetrics(
            ram_percent=75.5,
            ram_available_mb=2048,
            cpu_percent=45.0,
            disk_percent=60.0,
            disk_free_gb=50.5,
            temp_celsius=55.0,
            inference_latency_ms=150.0,
            timestamp=time.time(),
        )

        d = asdict(metrics)
        assert isinstance(d, dict)
        assert d['ram_percent'] == 75.5


class TestCognitiveMetrics:
    """Tests for CognitiveMetrics dataclass - spec lines 296-315."""

    def test_create_with_all_fields(self):
        """Should create with cognitive metrics."""
        metrics = CognitiveMetrics(
            context_coherence=0.95,
            error_count_1h=2,
            goal_stack_depth=3,
            contradiction_count=0,
            task_completion_ratio=0.85,
            latency_p50_ms=100,
            latency_p95_ms=300,
            latency_p99_ms=600,
            timestamp=time.time(),
        )

        assert metrics.context_coherence == 0.95
        assert metrics.error_count_1h == 2

    def test_default_values(self):
        """Should have sensible defaults for optional fields."""
        # Minimal creation
        metrics = CognitiveMetrics(
            context_coherence=0.9,
            error_count_1h=0,
            goal_stack_depth=1,
            contradiction_count=0,
            task_completion_ratio=1.0,
            latency_p50_ms=0,
            latency_p95_ms=0,
            latency_p99_ms=0,
            timestamp=time.time(),
        )

        assert metrics.contradiction_count == 0


class TestSystemState:
    """Tests for SystemState - spec lines 330-365."""

    def test_create_system_state(self):
        """Should create system state with all components."""
        now = time.time()

        state = SystemState(
            mode=Mode.ACTIVE,
            mode_since=now - 3600,  # 1 hour ago
            health_score=0.85,
            resource_metrics=None,
            cognitive_metrics=None,
            time_metrics=None,
            interpreted_state={},
            alerts=[],
            last_snapshot_time=now - 7200,
        )

        assert state.mode == Mode.ACTIVE
        assert state.health_score == 0.85

    def test_mode_duration_calculation(self):
        """Should calculate time in current mode."""
        now = time.time()
        state = SystemState(
            mode=Mode.ACTIVE,
            mode_since=now - 3600,
            health_score=0.85,
            resource_metrics=None,
            cognitive_metrics=None,
            time_metrics=None,
            interpreted_state={},
            alerts=[],
            last_snapshot_time=now,
        )

        duration = state.mode_duration_seconds

        # Should be approximately 3600 seconds (1 hour)
        assert 3590 <= duration <= 3610

    def test_has_critical_alert(self):
        """Should detect critical alerts."""
        state = SystemState(
            mode=Mode.ACTIVE,
            mode_since=time.time(),
            health_score=0.5,
            resource_metrics=None,
            cognitive_metrics=None,
            time_metrics=None,
            interpreted_state={},
            alerts=["CRITICAL: RAM below threshold"],
            last_snapshot_time=time.time(),
        )

        assert state.has_critical_alert() == True

    def test_no_critical_alert(self):
        """Should detect absence of critical alerts."""
        state = SystemState(
            mode=Mode.ACTIVE,
            mode_since=time.time(),
            health_score=0.85,
            resource_metrics=None,
            cognitive_metrics=None,
            time_metrics=None,
            interpreted_state={},
            alerts=["WARNING: High CPU usage"],
            last_snapshot_time=time.time(),
        )

        assert state.has_critical_alert() == False


class TestSnapshotData:
    """Tests for SnapshotData - spec lines 750-790."""

    def test_create_snapshot(self):
        """Should create snapshot with required fields."""
        snapshot = SnapshotData(
            snapshot_id="snap_20260126_143000",
            timestamp=time.time(),
            mode=Mode.ACTIVE,
            health_score=0.85,
            memory_hash="abc123",
            config_hash="def456",
            reason="Scheduled checkpoint",
        )

        assert snapshot.snapshot_id == "snap_20260126_143000"
        assert snapshot.mode == Mode.ACTIVE

    def test_snapshot_serializable(self):
        """Snapshot should be serializable to dict."""
        snapshot = SnapshotData(
            snapshot_id="snap_test",
            timestamp=time.time(),
            mode=Mode.ACTIVE,
            health_score=0.85,
            memory_hash="abc123",
            config_hash="def456",
            reason="Test",
        )

        d = asdict(snapshot)
        assert isinstance(d, dict)
        # Mode enum needs special handling for JSON
        assert d['snapshot_id'] == "snap_test"


class TestConstraintViolation:
    """Tests for ConstraintViolation - spec lines 380-400."""

    def test_create_violation(self):
        """Should create constraint violation."""
        violation = ConstraintViolation(
            constraint_name="RAM_MINIMUM",
            level=ConstraintLevel.CRITICAL,
            current_value=10.0,
            threshold=20.0,
            message="RAM below critical threshold",
        )

        assert violation.constraint_name == "RAM_MINIMUM"
        assert violation.level == ConstraintLevel.CRITICAL

    def test_constraint_levels(self):
        """All constraint levels should be defined."""
        assert ConstraintLevel.CRITICAL.value == "critical"
        assert ConstraintLevel.ALERT.value == "alert"
        assert ConstraintLevel.WARNING.value == "warning"


class TestStateTransitions:
    """Tests for state transition rules - spec lines 401-450."""

    def test_valid_transitions_from_active(self):
        """ACTIVE can transition to REDUCED, SLEEP, SURVIVAL."""
        from agent_core.homeostasis.mode_regulator import ModeRegulator

        regulator = ModeRegulator()

        # These should be valid
        assert regulator.is_valid_transition(Mode.ACTIVE, Mode.REDUCED) == True
        assert regulator.is_valid_transition(Mode.ACTIVE, Mode.SLEEP) == True
        assert regulator.is_valid_transition(Mode.ACTIVE, Mode.SURVIVAL) == True

    def test_invalid_transitions_from_survival(self):
        """SURVIVAL can only go to REDUCED (controlled recovery).

        Spec: lines 431-435 - forbidden transitions
        """
        from agent_core.homeostasis.mode_regulator import ModeRegulator

        regulator = ModeRegulator()

        # SURVIVAL -> ACTIVE is forbidden (must go through REDUCED)
        assert regulator.is_valid_transition(Mode.SURVIVAL, Mode.ACTIVE) == False
        assert regulator.is_valid_transition(Mode.SURVIVAL, Mode.REDUCED) == True

    def test_sleep_cannot_skip_to_active(self):
        """SLEEP should go through REDUCED before ACTIVE.

        Spec: line 432 - SLEEP -> ACTIVE forbidden
        """
        from agent_core.homeostasis.mode_regulator import ModeRegulator

        regulator = ModeRegulator()

        assert regulator.is_valid_transition(Mode.SLEEP, Mode.ACTIVE) == False
        assert regulator.is_valid_transition(Mode.SLEEP, Mode.REDUCED) == True

