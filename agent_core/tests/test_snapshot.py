"""
Tests for snapshot data structures and serialization.

Spec reference: homeostasis_spec.md section 8 (lines 750-850)

Note: SnapshotManager and ShutdownManager classes are planned but
not yet implemented. These tests cover the SnapshotData dataclass
which is implemented in state_model.py.
"""

import pytest
import time
import json

from agent_core.homeostasis.state_model import Mode, SnapshotData


class TestSnapshotData:
    """Tests for SnapshotData dataclass - spec lines 750-800."""

    def test_create_snapshot(self):
        """Should create snapshot with all required data."""
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

        assert snapshot is not None
        assert snapshot.mode == Mode.ACTIVE
        assert snapshot.health_score == 0.85

    def test_snapshot_has_timestamp(self):
        """Snapshot should have valid timestamp."""
        now = time.time()
        snapshot = SnapshotData(
            timestamp=now,
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
        )

        assert snapshot.timestamp == now

    def test_snapshot_to_dict(self):
        """Snapshot should be convertible to dict."""
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
        )

        d = snapshot.to_dict()

        assert isinstance(d, dict)
        assert d['mode'] == "active"
        assert d['episodic_memory']['hash'] == "abc123"

    def test_snapshot_json_serializable(self):
        """Snapshot dict should be JSON serializable."""
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
        )

        d = snapshot.to_dict()

        # Should not raise
        json_str = json.dumps(d)
        assert isinstance(json_str, str)

    def test_snapshot_from_dict(self):
        """Should reconstruct snapshot from dict."""
        original = SnapshotData(
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

        d = original.to_dict()
        restored = SnapshotData.from_dict(d)

        assert restored.mode == original.mode
        assert restored.episodic_memory_hash == original.episodic_memory_hash
        assert restored.health_score == original.health_score


class TestSnapshotModes:
    """Tests for snapshot with different modes."""

    def test_active_mode_snapshot(self):
        """Should create snapshot in ACTIVE mode."""
        snapshot = SnapshotData(
            timestamp=time.time(),
            uptime_seconds=3600,
            mode=Mode.ACTIVE,
            episodic_memory_version=1,
            episodic_memory_size_mb=100,
            episodic_memory_hash="abc",
            episodic_memory_entries=100,
            episodic_freshness_sec=10,
            semantic_model_version=1,
            semantic_node_count=50,
            semantic_model_hash="def",
            semantic_consistency_score=0.95,
        )

        assert snapshot.mode == Mode.ACTIVE

    def test_reduced_mode_snapshot(self):
        """Should create snapshot in REDUCED mode."""
        snapshot = SnapshotData(
            timestamp=time.time(),
            uptime_seconds=3600,
            mode=Mode.REDUCED,
            episodic_memory_version=1,
            episodic_memory_size_mb=100,
            episodic_memory_hash="abc",
            episodic_memory_entries=100,
            episodic_freshness_sec=10,
            semantic_model_version=1,
            semantic_node_count=50,
            semantic_model_hash="def",
            semantic_consistency_score=0.95,
        )

        assert snapshot.mode == Mode.REDUCED

    def test_survival_mode_snapshot(self):
        """Should create snapshot in SURVIVAL mode."""
        snapshot = SnapshotData(
            timestamp=time.time(),
            uptime_seconds=3600,
            mode=Mode.SURVIVAL,
            episodic_memory_version=1,
            episodic_memory_size_mb=100,
            episodic_memory_hash="abc",
            episodic_memory_entries=100,
            episodic_freshness_sec=10,
            semantic_model_version=1,
            semantic_node_count=50,
            semantic_model_hash="def",
            semantic_consistency_score=0.95,
        )

        assert snapshot.mode == Mode.SURVIVAL


class TestSnapshotOptionalFields:
    """Tests for optional snapshot fields."""

    def test_default_goal_stack(self):
        """Should have empty default goal stack."""
        snapshot = SnapshotData(
            timestamp=time.time(),
            uptime_seconds=3600,
            mode=Mode.ACTIVE,
            episodic_memory_version=1,
            episodic_memory_size_mb=100,
            episodic_memory_hash="abc",
            episodic_memory_entries=100,
            episodic_freshness_sec=10,
            semantic_model_version=1,
            semantic_node_count=50,
            semantic_model_hash="def",
            semantic_consistency_score=0.95,
        )

        assert snapshot.active_goal_stack == []

    def test_custom_goal_stack(self):
        """Should accept custom goal stack."""
        goals = ["main_task", "sub_task_1", "sub_task_2"]
        snapshot = SnapshotData(
            timestamp=time.time(),
            uptime_seconds=3600,
            mode=Mode.ACTIVE,
            episodic_memory_version=1,
            episodic_memory_size_mb=100,
            episodic_memory_hash="abc",
            episodic_memory_entries=100,
            episodic_freshness_sec=10,
            semantic_model_version=1,
            semantic_node_count=50,
            semantic_model_hash="def",
            semantic_consistency_score=0.95,
            active_goal_stack=goals,
        )

        assert snapshot.active_goal_stack == goals

    def test_default_resource_headroom(self):
        """Should have empty default resource headroom."""
        snapshot = SnapshotData(
            timestamp=time.time(),
            uptime_seconds=3600,
            mode=Mode.ACTIVE,
            episodic_memory_version=1,
            episodic_memory_size_mb=100,
            episodic_memory_hash="abc",
            episodic_memory_entries=100,
            episodic_freshness_sec=10,
            semantic_model_version=1,
            semantic_node_count=50,
            semantic_model_hash="def",
            semantic_consistency_score=0.95,
        )

        assert snapshot.resource_headroom == {}

    def test_custom_resource_headroom(self):
        """Should accept custom resource headroom."""
        headroom = {"ram_pct": 50, "cpu_pct": 70}
        snapshot = SnapshotData(
            timestamp=time.time(),
            uptime_seconds=3600,
            mode=Mode.ACTIVE,
            episodic_memory_version=1,
            episodic_memory_size_mb=100,
            episodic_memory_hash="abc",
            episodic_memory_entries=100,
            episodic_freshness_sec=10,
            semantic_model_version=1,
            semantic_node_count=50,
            semantic_model_hash="def",
            semantic_consistency_score=0.95,
            resource_headroom=headroom,
        )

        assert snapshot.resource_headroom == headroom


class TestSnapshotRoundTrip:
    """Tests for snapshot serialization round-trip."""

    def test_full_roundtrip(self):
        """Snapshot should survive full JSON roundtrip."""
        original = SnapshotData(
            timestamp=1234567890.123,
            uptime_seconds=3600,
            mode=Mode.REDUCED,
            episodic_memory_version=2,
            episodic_memory_size_mb=150.5,
            episodic_memory_hash="hash123",
            episodic_memory_entries=2000,
            episodic_freshness_sec=120.5,
            semantic_model_version=3,
            semantic_node_count=750,
            semantic_model_hash="hash456",
            semantic_consistency_score=0.88,
            active_goal_stack=["goal1", "goal2"],
            current_topic_embedding=[0.1, 0.2, 0.3],
            error_rate_recent=0.05,
            health_score=0.75,
            resource_headroom={"ram_pct": 40},
            last_mode_transition=1234567800.0,
        )

        # To dict
        d = original.to_dict()

        # To JSON
        json_str = json.dumps(d)

        # From JSON
        d2 = json.loads(json_str)

        # From dict
        restored = SnapshotData.from_dict(d2)

        # Compare key fields
        assert restored.timestamp == original.timestamp
        assert restored.mode == original.mode
        assert restored.episodic_memory_hash == original.episodic_memory_hash
        assert restored.semantic_node_count == original.semantic_node_count
        assert restored.health_score == original.health_score
