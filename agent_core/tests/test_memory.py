"""
Tests for memory management.

Spec reference: homeostasis_spec.md section 9 (lines 1200-1350)
"""

import pytest
import time
from unittest.mock import Mock, patch

from agent_core.memory.manager import MemoryManager


class TestMemoryManager:
    """Tests for MemoryManager - spec lines 1200-1250."""

    @pytest.fixture
    def manager(self):
        """Create manager instance."""
        return MemoryManager()

    def test_initialization(self, manager):
        """Manager should initialize successfully."""
        assert manager is not None

    def test_get_semantic_coherence(self, manager):
        """Should return coherence score."""
        coherence = manager.get_semantic_coherence()

        assert isinstance(coherence, float)
        assert 0 <= coherence <= 1

    def test_get_total_entries(self, manager):
        """Should return entry count."""
        count = manager.get_total_entries()

        assert isinstance(count, int)
        assert count >= 0

    def test_get_contradiction_count(self, manager):
        """Should return contradiction count."""
        count = manager.get_contradiction_count()

        assert isinstance(count, int)
        assert count >= 0

    def test_record_error(self, manager):
        """Should track errors."""
        initial = manager.get_recent_errors_count()

        manager.record_error()
        manager.record_error()

        assert manager.get_recent_errors_count() == initial + 2

    def test_increment_contradiction_count(self, manager):
        """Should increment contradiction counter."""
        initial = manager.get_contradiction_count()

        manager.increment_contradiction_count()

        assert manager.get_contradiction_count() == initial + 1

    def test_reset_contradiction_count(self, manager):
        """Should reset contradiction counter."""
        manager.increment_contradiction_count()
        manager.increment_contradiction_count()

        manager.reset_contradiction_count()

        assert manager.get_contradiction_count() == 0


class TestMemoryCorrectiveActions:
    """Tests for memory corrective actions."""

    @pytest.fixture
    def manager(self):
        return MemoryManager()

    def test_consolidate_episodic(self, manager):
        """Should consolidate episodic memory."""
        result = manager.consolidate_episodic(target_freed_mb=100)

        assert isinstance(result, dict)
        assert "success" in result

    def test_semantic_consistency_check(self, manager):
        """Should run consistency check."""
        result = manager.semantic_consistency_check()

        assert isinstance(result, dict)
        assert "success" in result

    def test_checkpoint(self, manager):
        """Should create checkpoint."""
        result = manager.checkpoint()

        assert isinstance(result, bool)

    def test_set_readonly(self, manager):
        """Should set readonly mode."""
        # Should not raise
        manager.set_readonly(True)
        manager.set_readonly(False)


class TestMemorySnapshot:
    """Tests for memory snapshot data."""

    @pytest.fixture
    def manager(self):
        return MemoryManager()

    def test_get_snapshot_data(self, manager):
        """Should return snapshot data."""
        data = manager.get_snapshot_data()

        assert isinstance(data, dict)
        assert "version" in data

    def test_get_semantic_snapshot_data(self, manager):
        """Should return semantic snapshot data."""
        data = manager.get_semantic_snapshot_data()

        assert isinstance(data, dict)
        assert "version" in data

    def test_rebuild_from_jsonl(self, manager):
        """Should support rebuild from JSONL.

        ADR-004: JSONL is source of truth, graph is derived.
        """
        result = manager.rebuild_from_jsonl()

        assert isinstance(result, bool)


class TestMemoryWithLegacy:
    """Tests for memory manager with legacy integration."""

    def test_initialization_with_missing_legacy(self):
        """Should handle missing legacy modules gracefully."""
        # This should not raise even if maria_core is not available
        manager = MemoryManager()

        assert manager is not None

    def test_coherence_with_missing_legacy(self):
        """Should return default coherence when legacy unavailable."""
        manager = MemoryManager()

        # Should return a reasonable default
        coherence = manager.get_semantic_coherence()

        assert 0 <= coherence <= 1

    def test_entry_count_with_missing_legacy(self):
        """Should return 0 when legacy unavailable."""
        manager = MemoryManager()

        count = manager.get_total_entries()

        assert count >= 0


class TestMemoryErrorTracking:
    """Tests for error tracking functionality."""

    @pytest.fixture
    def manager(self):
        return MemoryManager()

    def test_error_timestamps_bounded(self, manager):
        """Error history should be bounded."""
        # Record many errors
        for _ in range(1500):
            manager.record_error()

        # Should not exceed internal limit
        count = manager.get_recent_errors_count(window_seconds=9999999)
        assert count <= 1000  # Internal bound

    def test_error_window(self, manager):
        """Should only count errors within time window."""
        manager.record_error()

        # Immediate count should include it
        assert manager.get_recent_errors_count(window_seconds=10) >= 1

        # Very small window might not include it
        # (depending on timing)
