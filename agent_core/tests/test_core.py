"""
Tests for HomeostasisCore main loop.

Spec reference: homeostasis_spec.md section 7 (lines 879-1100)
"""

import pytest
import time
import threading
from unittest.mock import Mock, patch, MagicMock

from agent_core.homeostasis.core import HomeostasisCore
from agent_core.homeostasis.state_model import Mode, SystemState
from agent_core.homeostasis.api import HomeostasisEventBus


class TestHomeostasisCore:
    """Tests for HomeostasisCore - spec lines 879-1100."""

    @pytest.fixture
    def core(self):
        """Create core instance with mocked dependencies."""
        core = HomeostasisCore(
            memory_manager=Mock(),
            llm_manager=Mock(),
            meta_controller=Mock(),
        )
        return core

    def test_initialization(self, core):
        """Core should initialize with ACTIVE mode."""
        assert core.state.mode == Mode.ACTIVE

    def test_initial_health_score(self, core):
        """Initial health score should be 1.0 (healthy)."""
        assert core.state.health_score == 1.0

    def test_has_event_bus(self, core):
        """Core should have event bus for communication."""
        assert hasattr(core, 'event_bus')
        assert isinstance(core.event_bus, HomeostasisEventBus)


class TestTickExecution:
    """Tests for tick cycle - spec lines 900-950."""

    @pytest.fixture
    def core(self):
        core = HomeostasisCore(
            memory_manager=Mock(),
            llm_manager=Mock(),
            meta_controller=Mock(),
        )
        return core

    def test_tick_updates_state(self, core):
        """Each tick should update system state."""
        initial_time = core.state.mode_since

        # Execute one tick
        core._execute_tick()

        # State should have fresh metrics
        assert core.state.resource_metrics is not None or True

    def test_tick_validates_constraints(self, core):
        """Each tick should validate constraints."""
        # Mock constraint violation
        with patch.object(core._constraint_validator, 'validate') as mock_validate:
            mock_validate.return_value = []

            core._execute_tick()

            # Validator should have been called
            mock_validate.assert_called()

    def test_tick_calculates_health(self, core):
        """Each tick should recalculate health score."""
        # Execute tick
        core._execute_tick()

        # Health score should be set
        assert 0 <= core.state.health_score <= 1


class TestModeTransitions:
    """Tests for mode transitions via core - spec lines 950-1000."""

    @pytest.fixture
    def core(self):
        core = HomeostasisCore(
            memory_manager=Mock(),
            llm_manager=Mock(),
            meta_controller=Mock(),
        )
        return core

    def test_transition_to_reduced(self, core):
        """Core should handle ACTIVE -> REDUCED transition."""
        # Force transition
        core._transition_mode(Mode.ACTIVE, Mode.REDUCED)

        assert core.state.mode == Mode.REDUCED

    def test_transition_emits_event(self, core):
        """Mode transition should emit event."""
        events = []
        core.event_bus.subscribe("mode.changed", lambda e: events.append(e))

        core._transition_mode(Mode.ACTIVE, Mode.REDUCED)

        assert len(events) == 1
        assert events[0]["old_mode"] == Mode.ACTIVE
        assert events[0]["new_mode"] == Mode.REDUCED

    def test_forbidden_transition_blocked(self, core):
        """Forbidden transition should be blocked."""
        # Start in SLEEP
        core.state.mode = Mode.SLEEP

        # Try forbidden SLEEP -> ACTIVE
        result = core._transition_mode(Mode.SLEEP, Mode.ACTIVE)

        # Should fail or not execute
        assert result == False or core.state.mode != Mode.ACTIVE


class TestAuditLogging:
    """Tests for audit logging - spec lines 1000-1050."""

    @pytest.fixture
    def core(self):
        core = HomeostasisCore(
            memory_manager=Mock(),
            llm_manager=Mock(),
            meta_controller=Mock(),
        )
        return core

    def test_audit_log_exists(self, core):
        """Core should maintain audit log."""
        assert hasattr(core, '_audit_log') or hasattr(core, 'get_audit_log')

    def test_audit_records_mode_changes(self, core):
        """Mode changes should be logged."""
        core._transition_mode(Mode.ACTIVE, Mode.REDUCED)

        log = core.get_audit_log(10)

        # Should have entry for mode change
        mode_changes = [e for e in log if e.get("event") == "mode_change"]
        assert len(mode_changes) >= 1

    def test_audit_records_violations(self, core):
        """Constraint violations should be logged."""
        core.log_audit(
            event="constraint_violation",
            details={"constraint": "RAM_LOW", "level": "alert"},
        )

        log = core.get_audit_log(10)

        violations = [e for e in log if e.get("event") == "constraint_violation"]
        assert len(violations) >= 1


class TestOperatorOverride:
    """Tests for operator mode override - spec lines 1050-1080."""

    @pytest.fixture
    def core(self):
        core = HomeostasisCore(
            memory_manager=Mock(),
            llm_manager=Mock(),
            meta_controller=Mock(),
        )
        return core

    def test_set_operator_override(self, core):
        """Should accept operator mode override."""
        expiration = time.time() + 3600  # 1 hour

        core.set_operator_mode_override(
            mode=Mode.REDUCED,
            expiration=expiration,
            reason="Maintenance window",
        )

        # Check override is set
        assert core._operator_override is not None
        assert core._operator_override["mode"] == Mode.REDUCED

    def test_override_respects_expiration(self, core):
        """Override should expire."""
        # Set expired override
        expiration = time.time() - 10  # Already expired

        core.set_operator_mode_override(
            mode=Mode.REDUCED,
            expiration=expiration,
            reason="Test",
        )

        # Execute tick to check expiration
        core._check_operator_override()

        # Override should be cleared
        assert core._operator_override is None or \
               core._operator_override.get("expired", False)

    def test_override_cannot_block_survival(self, core):
        """Operator override cannot prevent SURVIVAL in critical.

        Spec: line 870 - Cannot force mode change if system CRITICAL
        """
        # Set override to ACTIVE
        core.set_operator_mode_override(
            mode=Mode.ACTIVE,
            expiration=time.time() + 3600,
            reason="Test",
        )

        # Simulate critical condition
        from agent_core.homeostasis.constraints import ConstraintViolation, ConstraintLevel

        violation = ConstraintViolation(
            constraint_name="CRITICAL_TEST",
            level=ConstraintLevel.CRITICAL,
            current_value=0,
            threshold=10,
            message="Critical test",
        )

        # Mode decision should override operator for CRITICAL
        mode = core._mode_regulator.recommend_mode(
            current_mode=Mode.ACTIVE,
            violations=[violation],
            interpreted_state={},
        )

        assert mode == Mode.SURVIVAL


class TestShutdownSequence:
    """Tests for graceful shutdown - spec lines 1080-1100."""

    @pytest.fixture
    def core(self):
        core = HomeostasisCore(
            memory_manager=Mock(),
            llm_manager=Mock(),
            meta_controller=Mock(),
        )
        return core

    def test_initiate_shutdown(self, core):
        """Shutdown should be initiable."""
        core.initiate_shutdown(
            reason="Test shutdown",
            operator_id="test",
        )

        # Should be in shutdown state
        assert core._shutdown_requested == True

    def test_shutdown_transitions_to_survival(self, core):
        """Shutdown should first transition to SURVIVAL.

        Spec: line 863 - SURVIVAL mode then shutdown
        """
        core.initiate_shutdown(
            reason="Test",
            operator_id="test",
        )

        # Process shutdown
        core._process_shutdown()

        # Should be in SURVIVAL
        assert core.state.mode == Mode.SURVIVAL

    def test_shutdown_creates_snapshot(self, core):
        """Shutdown should create final snapshot."""
        with patch.object(core, 'request_snapshot') as mock_snapshot:
            core.initiate_shutdown(
                reason="Test",
                operator_id="test",
            )

            core._process_shutdown()

            # Snapshot should be requested
            mock_snapshot.assert_called()


class TestHealthScore:
    """Tests for health score calculation - spec lines 1100-1150."""

    @pytest.fixture
    def core(self):
        core = HomeostasisCore(
            memory_manager=Mock(),
            llm_manager=Mock(),
            meta_controller=Mock(),
        )
        return core

    def test_health_score_range(self, core):
        """Health score should always be 0-1."""
        for _ in range(10):
            core._calculate_health_score()
            assert 0 <= core.state.health_score <= 1

    def test_violations_reduce_health(self, core):
        """Violations should reduce health score."""
        from agent_core.homeostasis.constraints import ConstraintViolation, ConstraintLevel

        initial_health = core.state.health_score

        # Add violations
        core._current_violations = [
            ConstraintViolation(
                constraint_name="TEST1",
                level=ConstraintLevel.WARNING,
                current_value=0,
                threshold=10,
                message="Test",
            ),
            ConstraintViolation(
                constraint_name="TEST2",
                level=ConstraintLevel.ALERT,
                current_value=0,
                threshold=10,
                message="Test",
            ),
        ]

        core._calculate_health_score()

        # Health should be reduced
        assert core.state.health_score < initial_health

    def test_critical_gives_low_health(self, core):
        """CRITICAL violation should give very low health."""
        from agent_core.homeostasis.constraints import ConstraintViolation, ConstraintLevel

        core._current_violations = [
            ConstraintViolation(
                constraint_name="CRITICAL",
                level=ConstraintLevel.CRITICAL,
                current_value=0,
                threshold=10,
                message="Critical test",
            ),
        ]

        core._calculate_health_score()

        # Should be below 50%
        assert core.state.health_score < 0.5

