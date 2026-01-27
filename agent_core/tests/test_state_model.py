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
    SystemState,
    SnapshotData,
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
            timestamp=time.time(),
            ram_used_mb=6000,
            ram_total_mb=8000,
            ram_available_mb=2000,
            swap_used_pct=10.0,
            cpu_percent=45.0,
            load_avg_1m=1.5,
            load_avg_5m=1.2,
            load_avg_15m=1.0,
            disk_used_pct=60.0,
            disk_io_queue_depth=2,
            process_count=150,
            temp_c=55.0,
            inference_latency_ms=150.0,
        )

        assert metrics.ram_available_mb == 2000
        assert metrics.cpu_percent == 45.0

    def test_ram_available_pct_property(self):
        """Should calculate available RAM percentage."""
        metrics = ResourceMetrics(
            timestamp=time.time(),
            ram_used_mb=6000,
            ram_total_mb=8000,
            ram_available_mb=2000,
            swap_used_pct=10.0,
            cpu_percent=45.0,
            load_avg_1m=1.5,
            load_avg_5m=1.2,
            load_avg_15m=1.0,
            disk_used_pct=60.0,
            disk_io_queue_depth=2,
            process_count=150,
            temp_c=55.0,
            inference_latency_ms=150.0,
        )

        # 2000/8000 = 25%
        assert metrics.ram_available_pct == 25.0

    def test_serializable_to_dict(self):
        """Metrics should be serializable."""
        metrics = ResourceMetrics(
            timestamp=time.time(),
            ram_used_mb=6000,
            ram_total_mb=8000,
            ram_available_mb=2000,
            swap_used_pct=10.0,
            cpu_percent=45.0,
            load_avg_1m=1.5,
            load_avg_5m=1.2,
            load_avg_15m=1.0,
            disk_used_pct=60.0,
            disk_io_queue_depth=2,
            process_count=150,
            temp_c=55.0,
            inference_latency_ms=150.0,
        )

        d = asdict(metrics)
        assert isinstance(d, dict)
        assert d['ram_available_mb'] == 2000


class TestCognitiveMetrics:
    """Tests for CognitiveMetrics dataclass - spec lines 296-315."""

    def test_create_with_all_fields(self):
        """Should create with cognitive metrics."""
        metrics = CognitiveMetrics(
            timestamp=time.time(),
            context_coherence=0.95,
            context_tokens=1500,
            inference_latency_ms=200.0,
            latency_p50_ms=100.0,
            latency_p99_ms=600.0,
            error_count_1h=2,
            goal_stack_depth=3,
            memory_entries=100,
            contradiction_count=0,
            episodic_freshness_sec=60.0,
            attention_fragmentation=0.2,
            task_completion_ratio=0.9,
        )

        assert metrics.context_coherence == 0.95
        assert metrics.error_count_1h == 2

    def test_coherence_ok_property(self):
        """Should check if coherence is acceptable."""
        metrics = CognitiveMetrics(
            timestamp=time.time(),
            context_coherence=0.95,
            context_tokens=1500,
            inference_latency_ms=200.0,
            latency_p50_ms=100.0,
            latency_p99_ms=600.0,
            error_count_1h=2,
            goal_stack_depth=3,
            memory_entries=100,
            contradiction_count=0,
            episodic_freshness_sec=60.0,
            attention_fragmentation=0.2,
            task_completion_ratio=0.9,
        )

        assert metrics.coherence_ok == True

        # Low coherence
        metrics2 = CognitiveMetrics(
            timestamp=time.time(),
            context_coherence=0.5,
            context_tokens=1500,
            inference_latency_ms=200.0,
            latency_p50_ms=100.0,
            latency_p99_ms=600.0,
            error_count_1h=2,
            goal_stack_depth=3,
            memory_entries=100,
            contradiction_count=0,
            episodic_freshness_sec=60.0,
            attention_fragmentation=0.2,
            task_completion_ratio=0.9,
        )

        assert metrics2.coherence_ok == False

    def test_errors_high_property(self):
        """Should detect high error rate."""
        low_errors = CognitiveMetrics(
            timestamp=time.time(),
            context_coherence=0.95,
            context_tokens=1500,
            inference_latency_ms=200.0,
            latency_p50_ms=100.0,
            latency_p99_ms=600.0,
            error_count_1h=5,
            goal_stack_depth=3,
            memory_entries=100,
            contradiction_count=0,
            episodic_freshness_sec=60.0,
            attention_fragmentation=0.2,
            task_completion_ratio=0.9,
        )
        assert low_errors.errors_high == False

        high_errors = CognitiveMetrics(
            timestamp=time.time(),
            context_coherence=0.95,
            context_tokens=1500,
            inference_latency_ms=200.0,
            latency_p50_ms=100.0,
            latency_p99_ms=600.0,
            error_count_1h=30,
            goal_stack_depth=3,
            memory_entries=100,
            contradiction_count=0,
            episodic_freshness_sec=60.0,
            attention_fragmentation=0.2,
            task_completion_ratio=0.9,
        )
        assert high_errors.errors_high == True


class TestSystemState:
    """Tests for SystemState - spec lines 330-365."""

    def test_create_system_state(self):
        """Should create system state with all components."""
        now = time.time()

        state = SystemState(
            mode=Mode.ACTIVE,
            health_score=0.85,
            last_mode_change_time=now - 3600,  # 1 hour ago
            alerts=[],
            idle_seconds=100,
        )

        assert state.mode == Mode.ACTIVE
        assert state.health_score == 0.85

    def test_mode_duration_calculation(self):
        """Should calculate time in current mode."""
        now = time.time()
        state = SystemState(
            mode=Mode.ACTIVE,
            health_score=0.85,
            last_mode_change_time=now - 3600,
            alerts=[],
            idle_seconds=0,
        )

        duration = state.mode_duration_seconds

        # Should be approximately 3600 seconds (1 hour)
        assert 3590 <= duration <= 3610

    def test_has_critical_alert(self):
        """Should detect critical alerts."""
        state = SystemState(
            mode=Mode.ACTIVE,
            health_score=0.5,
            last_mode_change_time=time.time(),
            alerts=["CRITICAL: RAM below threshold"],
            idle_seconds=0,
        )

        assert state.has_critical_alert() == True

    def test_no_critical_alert(self):
        """Should detect absence of critical alerts."""
        state = SystemState(
            mode=Mode.ACTIVE,
            health_score=0.85,
            last_mode_change_time=time.time(),
            alerts=["WARNING: High CPU usage"],
            idle_seconds=0,
        )

        assert state.has_critical_alert() == False

    def test_has_warning(self):
        """Should detect warnings."""
        state = SystemState(
            mode=Mode.ACTIVE,
            health_score=0.85,
            last_mode_change_time=time.time(),
            alerts=["WARNING: High CPU usage"],
            idle_seconds=0,
        )

        assert state.has_warning() == True


class TestSnapshotData:
    """Tests for SnapshotData - spec lines 750-790."""

    def test_create_snapshot(self):
        """Should create snapshot with required fields."""
        snapshot = SnapshotData(
            timestamp=time.time(),
            uptime_seconds=3600,
            mode=Mode.ACTIVE,
            episodic_memory_version=1,
            episodic_memory_size_mb=100,
            episodic_memory_hash="abc123",
            episodic_memory_entries=1000,
            episodic_freshness_sec=60,
            semantic_model_version=1,
            semantic_node_count=500,
            semantic_model_hash="def456",
            semantic_consistency_score=0.95,
            health_score=0.85,
        )

        assert snapshot.mode == Mode.ACTIVE
        assert snapshot.episodic_memory_hash == "abc123"

    def test_snapshot_to_dict(self):
        """Snapshot should be serializable to dict."""
        snapshot = SnapshotData(
            timestamp=time.time(),
            uptime_seconds=3600,
            mode=Mode.ACTIVE,
            episodic_memory_version=1,
            episodic_memory_size_mb=100,
            episodic_memory_hash="abc123",
            episodic_memory_entries=1000,
            episodic_freshness_sec=60,
            semantic_model_version=1,
            semantic_node_count=500,
            semantic_model_hash="def456",
            semantic_consistency_score=0.95,
            health_score=0.85,
        )

        d = snapshot.to_dict()
        assert isinstance(d, dict)
        assert d['mode'] == "active"
        assert d['episodic_memory']['hash'] == "abc123"

    def test_snapshot_from_dict(self):
        """Should create snapshot from dict."""
        data = {
            "timestamp": time.time(),
            "uptime_seconds": 3600,
            "mode": "active",
            "episodic_memory": {
                "version": 1,
                "size_mb": 100,
                "hash": "abc123",
                "entries": 1000,
                "freshness_seconds": 60,
            },
            "semantic_model": {
                "version": 1,
                "node_count": 500,
                "hash": "def456",
                "consistency_score": 0.95,
            },
            "context_snapshot": {
                "active_goal_stack": [],
                "current_topic_embedding": [],
                "error_rate_recent": 0.0,
            },
            "homeostasis_state": {
                "mode": "active",
                "health_score": 0.85,
                "resource_headroom": {},
                "last_mode_transition": 0.0,
            },
        }

        snapshot = SnapshotData.from_dict(data)
        assert snapshot.mode == Mode.ACTIVE
        assert snapshot.episodic_memory_hash == "abc123"


class TestStateTransitions:
    """Tests for state transition rules - spec lines 401-450."""

    def test_valid_transitions_from_active(self):
        """ACTIVE can transition to REDUCED, SLEEP, SURVIVAL."""
        from agent_core.homeostasis.mode_regulator import ModeRegulator, TransitionResult

        regulator = ModeRegulator()

        # Test actual transitions
        result = regulator.transition_to(Mode.REDUCED)
        assert result == TransitionResult.SUCCESS

    def test_forbidden_transitions(self):
        """Some transitions should be forbidden."""
        from agent_core.homeostasis.mode_regulator import ModeRegulator, TransitionResult

        regulator = ModeRegulator()

        # Go to SURVIVAL
        regulator.transition_to(Mode.SURVIVAL)

        # SURVIVAL -> REDUCED is forbidden (only ACTIVE allowed)
        result = regulator.transition_to(Mode.REDUCED)
        # Should be FORBIDDEN
        assert result == TransitionResult.FORBIDDEN
        # Should still be in SURVIVAL
        assert regulator.current_mode == Mode.SURVIVAL
