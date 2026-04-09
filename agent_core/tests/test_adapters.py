"""
Tests for agent_core/adapters/ - legacy wrappers.

All legacy modules (maria_core) are mocked. Tests verify:
- Simple (non-legacy) mode works standalone
- Cognitive metrics, goal stack, perception processing
- Graph operations, JSONL serialization, BFS traversal
- Memory append/load, error tracking, coherence
- Resource watchdog thread lifecycle
"""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock


# ───────────────────────────────────────────────────
# BrainMemoryAdapter
# ───────────────────────────────────────────────────

class TestBrainMemoryAdapter:

    def _make(self):
        from agent_core.adapters.brain_adapter import BrainMemoryAdapter
        adapter = BrainMemoryAdapter(
            semantic_memory=MagicMock(),
            episodic_memory=[],
            maria_brain=MagicMock(),
            use_legacy=False,
        )
        return adapter

    def test_init_simple(self):
        adapter = self._make()
        assert adapter._legacy_loop is None
        assert adapter._goal_stack == []

    def test_cognitive_metrics_empty(self):
        adapter = self._make()
        m = adapter.get_cognitive_metrics()
        assert "context_coherence" in m
        assert "error_count_1h" in m
        assert m["context_coherence"] >= 0.0

    def test_goal_stack_push_pop(self):
        adapter = self._make()
        adapter._add_goal("learn physics")
        adapter._add_goal("run exam")
        assert len(adapter.get_goal_stack()) == 2
        top = adapter.pop_goal()
        assert top["goal"] == "run exam"
        assert len(adapter.get_goal_stack()) == 1

    def test_goal_stack_limit(self):
        adapter = self._make()
        for i in range(25):
            adapter._add_goal(f"goal-{i}")
        # Should be capped at 20
        assert len(adapter.get_goal_stack()) == 20

    def test_pop_empty(self):
        adapter = self._make()
        assert adapter.pop_goal() is None

    def test_process_simple(self):
        adapter = self._make()
        result = adapter._process_simple("test input", {"source": "user"})
        assert result["status"] == "completed_simple"
        assert "episode" in result

    def test_process_perception_without_legacy(self):
        adapter = self._make()
        result = adapter.process_perception("hello", {"source": "user"})
        assert isinstance(result, dict)
        assert "status" in result

    def test_cognitive_metrics_with_errors(self):
        adapter = self._make()
        adapter._error_timestamps = [time.time() - 10, time.time() - 5]
        m = adapter.get_cognitive_metrics()
        assert m["error_count_1h"] == 2

    def test_cognitive_metrics_error_cleanup(self):
        """Errors older than 1h should be cleaned."""
        adapter = self._make()
        adapter._error_timestamps = [time.time() - 7200, time.time() - 10]
        m = adapter.get_cognitive_metrics()
        assert m["error_count_1h"] == 1

    def test_get_episodes_empty(self):
        adapter = self._make()
        eps = adapter.get_episodes(5)
        assert eps == []

    def test_factory_function(self):
        from agent_core.adapters.brain_adapter import get_adapted_brain_loop
        with patch("agent_core.adapters.brain_adapter.BrainMemoryAdapter") as MockAdapter:
            MockAdapter.return_value = MagicMock()
            result = get_adapted_brain_loop(MagicMock(), MagicMock(), MagicMock())
            MockAdapter.assert_called_once()


# ───────────────────────────────────────────────────
# SemanticGraphAdapter
# ───────────────────────────────────────────────────

class TestSemanticGraphAdapter:

    def _make(self, tmp_path=None):
        from agent_core.adapters.semantic_adapter import SemanticGraphAdapter
        adapter = SemanticGraphAdapter(
            data_dir=str(tmp_path) if tmp_path else "/tmp",
            use_legacy=False,
        )
        return adapter

    def test_init_simple(self):
        adapter = self._make()
        assert adapter._legacy_graph is None
        stats = adapter.get_stats()
        assert stats["total_nodes"] == 0
        assert stats["total_edges"] == 0

    def test_add_get_node(self):
        adapter = self._make()
        adapter.add_node("n1", "fizyka kwantowa", "concept")
        node = adapter.get_node("n1")
        assert node is not None
        assert node["content"] == "fizyka kwantowa"
        assert node["type"] == "concept"

    def test_get_nonexistent_node(self):
        adapter = self._make()
        assert adapter.get_node("missing") is None

    def test_add_get_edge(self):
        adapter = self._make()
        adapter.add_node("a", "alpha", "concept")
        adapter.add_node("b", "beta", "concept")
        adapter.add_edge("a", "b", "related_to", weight=0.8)
        edges = adapter.get_edges("a")
        assert len(edges) == 1
        assert edges[0]["target"] == "b"
        assert edges[0]["relation"] == "related_to"

    def test_get_edges_empty(self):
        adapter = self._make()
        assert adapter.get_edges("missing") == []

    def test_search(self):
        adapter = self._make()
        adapter.add_node("n1", "fizyka kwantowa", "concept")
        adapter.add_node("n2", "chemia organiczna", "concept")
        adapter.add_node("n3", "fizyka atomowa", "concept")
        results = adapter.search("fizyka", limit=10)
        assert len(results) == 2
        ids = [r["id"] for r in results]
        assert "n1" in ids
        assert "n3" in ids

    def test_search_limit(self):
        adapter = self._make()
        for i in range(20):
            adapter.add_node(f"n{i}", f"fizyka temat {i}", "concept")
        results = adapter.search("fizyka", limit=5)
        assert len(results) == 5

    def test_bfs_query(self):
        adapter = self._make()
        adapter.add_node("a", "root", "concept")
        adapter.add_node("b", "child1", "concept")
        adapter.add_node("c", "child2", "concept")
        adapter.add_edge("a", "b", "has_part")
        adapter.add_edge("b", "c", "has_part")
        visited = adapter.query("a", max_depth=3)
        ids = [v["id"] for v in visited]
        # BFS excludes start node
        assert "b" in ids
        assert "c" in ids

    def test_bfs_depth_limit(self):
        adapter = self._make()
        adapter.add_node("a", "root", "concept")
        adapter.add_node("b", "child", "concept")
        adapter.add_node("c", "grandchild", "concept")
        adapter.add_edge("a", "b", "link")
        adapter.add_edge("b", "c", "link")
        visited = adapter.query("a", max_depth=1)
        ids = [v["id"] for v in visited]
        assert "b" in ids
        assert "c" not in ids

    def test_bfs_relation_filter(self):
        adapter = self._make()
        adapter.add_node("a", "root", "concept")
        adapter.add_node("b", "yes", "concept")
        adapter.add_node("c", "no", "concept")
        adapter.add_edge("a", "b", "has_part")
        adapter.add_edge("a", "c", "contradicts")
        visited = adapter.query("a", max_depth=2, allowed_relations=["has_part"])
        ids = [v["id"] for v in visited]
        assert "b" in ids
        assert "c" not in ids

    def test_save_load_jsonl(self, tmp_path):
        adapter = self._make(tmp_path)
        adapter.add_node("n1", "test", "concept")
        adapter.add_edge("n1", "n1", "self_ref")

        jsonl_path = tmp_path / "graph.jsonl"
        adapter.save_to_jsonl(jsonl_path)
        assert jsonl_path.exists()

        # Reload into fresh adapter
        adapter2 = self._make(tmp_path)
        adapter2.rebuild_from_jsonl(jsonl_path)
        assert adapter2.get_node("n1") is not None
        assert adapter2.get_stats()["total_nodes"] == 1

    def test_rebuild_malformed_jsonl(self, tmp_path):
        """Should skip malformed lines."""
        jsonl_path = tmp_path / "bad.jsonl"
        jsonl_path.write_text('{"record_type":"node","node_id":"n1","content":"ok","node_type":"c"}\nNOT JSON\n')
        adapter = self._make(tmp_path)
        adapter.rebuild_from_jsonl(jsonl_path)
        assert adapter.get_stats()["total_nodes"] == 1

    def test_stats(self):
        adapter = self._make()
        adapter.add_node("a", "x", "concept")
        adapter.add_node("b", "y", "concept")
        adapter.add_edge("a", "b", "link")
        stats = adapter.get_stats()
        assert stats["total_nodes"] == 2
        assert stats["total_edges"] == 1

    def test_detect_contradictions_empty(self):
        adapter = self._make()
        assert adapter.detect_contradictions() == []

    def test_to_dict(self):
        adapter = self._make()
        adapter.add_node("n1", "test", "concept")
        d = adapter.to_dict()
        assert "nodes" in d
        assert "edges" in d

    def test_factory_function(self):
        from agent_core.adapters.semantic_adapter import get_adapted_semantic_graph
        with patch("agent_core.adapters.semantic_adapter.SemanticGraphAdapter") as Mock:
            Mock.return_value = MagicMock()
            get_adapted_semantic_graph("/tmp")
            Mock.assert_called_once()


# ───────────────────────────────────────────────────
# MemoryStoreAdapter
# ───────────────────────────────────────────────────

class TestMemoryStoreAdapter:

    def _make(self, tmp_path):
        from agent_core.adapters.memory_adapter import MemoryStoreAdapter
        return MemoryStoreAdapter(memory_dir=tmp_path, use_legacy=False)

    def test_init_simple(self, tmp_path):
        adapter = self._make(tmp_path)
        assert adapter._legacy_store is None

    def test_append_and_count(self, tmp_path):
        adapter = self._make(tmp_path)
        adapter.append({"id": "r1", "text": "hello"})
        adapter.append({"id": "r2", "text": "world"})
        assert adapter.count() == 2

    def test_load_all(self, tmp_path):
        adapter = self._make(tmp_path)
        adapter.append({"id": "r1", "text": "hello"})
        records = adapter.load_all()
        assert len(records) >= 1
        assert records[0]["id"] == "r1"

    def test_get_recent(self, tmp_path):
        adapter = self._make(tmp_path)
        for i in range(10):
            adapter.append({"id": f"r{i}"})
        recent = adapter.get_recent(3)
        assert len(recent) == 3
        # Most recent first
        assert recent[0]["id"] == "r9"

    def test_find(self, tmp_path):
        adapter = self._make(tmp_path)
        adapter.append({"id": "r1", "type": "fact"})
        adapter.append({"id": "r2", "type": "question"})
        adapter.append({"id": "r3", "type": "fact"})
        found = adapter.find(lambda r: r.get("type") == "fact")
        assert len(found) == 2

    def test_stats_coherence(self, tmp_path):
        adapter = self._make(tmp_path)
        adapter.append({"id": "r1"})
        stats = adapter.get_stats()
        assert "coherence_score" in stats
        assert stats["operation_count"] >= 1

    def test_stats_error_tracking(self, tmp_path):
        adapter = self._make(tmp_path)
        adapter._error_count_1h = [time.time()]
        stats = adapter.get_stats()
        assert stats["error_count_1h"] == 1

    def test_stats_old_errors_cleaned(self, tmp_path):
        adapter = self._make(tmp_path)
        adapter._error_count_1h = [time.time() - 7200]
        stats = adapter.get_stats()
        assert stats["error_count_1h"] == 0

    def test_flush_noop(self, tmp_path):
        """Flush should not crash (no-op for JSONL)."""
        adapter = self._make(tmp_path)
        adapter.flush()

    def test_factory_function(self):
        from agent_core.adapters.memory_adapter import get_adapted_memory_store
        with patch("agent_core.adapters.memory_adapter.MemoryStoreAdapter") as Mock:
            Mock.return_value = MagicMock()
            get_adapted_memory_store("/tmp")
            Mock.assert_called_once()


# ───────────────────────────────────────────────────
# ResourceWatchdogAdapter
# ───────────────────────────────────────────────────

class TestResourceWatchdogAdapter:

    def _make(self):
        from agent_core.adapters.resource_adapter import ResourceWatchdogAdapter
        with patch("agent_core.adapters.resource_adapter.ResourceSensor"):
            adapter = ResourceWatchdogAdapter(
                limit_percent=80,
                check_interval_sec=1,
            )
        return adapter

    def test_init(self):
        adapter = self._make()
        assert adapter.is_running is False

    def test_start_stop(self):
        adapter = self._make()
        mock_metrics = MagicMock()
        mock_metrics.memory_pressure = 50.0
        adapter._sensor = MagicMock()
        adapter._sensor.read_metrics.return_value = mock_metrics
        adapter._check_interval = 0.05

        thread = adapter.start()
        assert adapter.is_running is True
        assert thread.daemon is True

        time.sleep(0.15)
        adapter.stop()
        time.sleep(0.1)
        assert adapter.is_running is False

    def test_threshold_callback(self):
        from agent_core.adapters.resource_adapter import ResourceWatchdogAdapter
        callback = MagicMock()

        with patch("agent_core.adapters.resource_adapter.ResourceSensor"):
            adapter = ResourceWatchdogAdapter(
                limit_percent=50,
                check_interval_sec=1,
                on_threshold_exceeded=callback,
            )

        mock_metrics = MagicMock()
        mock_metrics.memory_pressure = 90.0  # Over threshold
        adapter._sensor = MagicMock()
        adapter._sensor.read_metrics.return_value = mock_metrics
        adapter._check_interval = 0.05

        adapter.start()
        time.sleep(0.2)
        adapter.stop()
        time.sleep(0.1)

        assert callback.called
        callback.assert_called_with(90.0)

    def test_get_current_metrics(self):
        adapter = self._make()
        mock_metrics = MagicMock()
        adapter._sensor = MagicMock()
        adapter._sensor.read_metrics.return_value = mock_metrics

        result = adapter.get_current_metrics()
        assert result is not None

    def test_factory_function(self):
        from agent_core.adapters.resource_adapter import start_watchdog_adapted
        with patch("agent_core.adapters.resource_adapter.ResourceWatchdogAdapter") as Mock:
            mock_adapter = MagicMock()
            mock_adapter.start.return_value = MagicMock()
            Mock.return_value = mock_adapter
            result = start_watchdog_adapted(80, 1)
            assert result is not None

    def test_class_factory(self):
        from agent_core.adapters.resource_adapter import ResourceWatchdogAdapter
        with patch("agent_core.adapters.resource_adapter.ResourceSensor"):
            adapter = ResourceWatchdogAdapter.from_legacy(85, 2)
        assert adapter is not None


# ───────────────────────────────────────────────────
# __init__ imports
# ───────────────────────────────────────────────────

class TestAdaptersInit:

    def test_imports(self):
        from agent_core.adapters import (
            BrainMemoryAdapter,
            SemanticGraphAdapter,
            MemoryStoreAdapter,
            ResourceWatchdogAdapter,
        )
        assert BrainMemoryAdapter is not None
        assert SemanticGraphAdapter is not None
        assert MemoryStoreAdapter is not None
        assert ResourceWatchdogAdapter is not None
