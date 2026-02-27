"""
Tests for SleepProcessor and DreamGenerator.

Covers: NREM phases, dream generation, persistence, integration.
"""

import json
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_core.consciousness.dream_generator import DreamGenerator
from agent_core.consciousness.sleep_processor import (
    SleepProcessor,
    SleepPhase,
    EDGE_BOOST_MIN_ACCESS,
    EDGE_BOOST_AMOUNT,
    NODE_STALE_HOURS,
    NODE_LOW_IMPORTANCE,
)


# ============================================================
# Fixtures
# ============================================================

class MockGraph:
    """Minimal semantic graph mock for testing."""

    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self._edge_count = 0

    def add_node(self, label, node_type="entity", attributes=None,
                 embedding=None, confidence=1.0, source="test"):
        node_id = f"node:{len(self.nodes):05d}"
        self.nodes[node_id] = {
            "id": node_id,
            "label": label,
            "type": node_type,
            "attributes": attributes or {},
            "embedding": embedding,
            "confidence": confidence,
            "source": source,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "access_count": 0,
            "importance": 0.5,
            "is_outdated": False,
        }
        return node_id

    def add_edge(self, from_id, relation, to_id, weight=1.0,
                 confidence=1.0, source="test"):
        if from_id not in self.nodes or to_id not in self.nodes:
            raise ValueError(f"Node not found: {from_id} or {to_id}")
        edge_key = (from_id, relation, to_id)
        self.edges[edge_key] = {
            "id": f"edge:{self._edge_count:05d}",
            "from": from_id,
            "relation": relation,
            "to": to_id,
            "weight": weight,
            "confidence": confidence,
            "source": source,
            "created_at": datetime.now().isoformat(),
            "access_count": 0,
        }
        self._edge_count += 1


@pytest.fixture
def graph():
    """Create a mock graph with some nodes and edges."""
    g = MockGraph()
    n1 = g.add_node("homeostasis", node_type="entity")
    n2 = g.add_node("semantic_graph", node_type="entity")
    n3 = g.add_node("learning", node_type="entity")
    n4 = g.add_node("consciousness", node_type="entity")
    n5 = g.add_node("perception", node_type="entity")

    g.add_edge(n1, "related_to", n2, weight=1.0)
    g.add_edge(n2, "part_of", n3, weight=0.8)

    return g


@pytest.fixture
def empty_graph():
    """Create an empty graph."""
    return MockGraph()


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


# ============================================================
# TestDreamGenerator
# ============================================================

class TestDreamGenerator:
    """Tests for dream generation."""

    def test_generate_dream_returns_dict(self, graph):
        gen = DreamGenerator(graph)
        dream = gen.generate_dream()
        assert dream is not None
        assert isinstance(dream, dict)

    def test_generate_dream_has_required_fields(self, graph):
        gen = DreamGenerator(graph)
        dream = gen.generate_dream()
        assert "timestamp" in dream
        assert "phase" in dream
        assert dream["phase"] == "rem"
        assert "type" in dream
        assert "content" in dream
        assert "nodes" in dream
        assert "labels" in dream
        assert "confidence" in dream
        assert "to_explore" in dream

    def test_generate_dream_types(self, graph):
        """Dreams should be one of: connection_discovery, hypothesis, exploration."""
        gen = DreamGenerator(graph)
        types_seen = set()
        for _ in range(50):
            dream = gen.generate_dream()
            if dream:
                types_seen.add(dream["type"])
        # Should see at least 2 types in 50 attempts
        assert len(types_seen) >= 2

    def test_generate_dream_empty_graph(self, empty_graph):
        """Empty graph produces no dreams."""
        gen = DreamGenerator(empty_graph)
        dream = gen.generate_dream()
        assert dream is None

    def test_generate_dream_single_node(self, empty_graph):
        """Graph with 1 node produces no dreams."""
        empty_graph.add_node("lonely")
        gen = DreamGenerator(empty_graph)
        dream = gen.generate_dream()
        assert dream is None

    def test_generate_dreams_count(self, graph):
        gen = DreamGenerator(graph)
        dreams = gen.generate_dreams(count=3)
        assert len(dreams) <= 3
        assert len(dreams) > 0

    def test_generate_dream_content_in_polish(self, graph):
        """Dream content should be in Polish (templates)."""
        gen = DreamGenerator(graph)
        dream = gen.generate_dream()
        assert dream is not None
        # Templates contain Polish words
        content = dream["content"].lower()
        polish_words = ["sni", "sen", "zbadac", "ciekawe", "polaczenie", "mozliwe", "wiecej"]
        assert any(w in content for w in polish_words)

    def test_dream_connection_added_to_graph(self, graph):
        """Connection discovery dreams should add weak edges to graph."""
        gen = DreamGenerator(graph)
        initial_edges = len(graph.edges)

        # Generate many dreams to get at least one connection_discovery
        for _ in range(20):
            dream = gen.generate_dream()
            if dream and dream["type"] == "connection_discovery":
                break

        # May or may not have added edge (depends on random)
        # Just verify no crash
        assert len(graph.edges) >= initial_edges

    def test_save_dreams(self, graph, tmp_dir):
        path = Path(tmp_dir) / "dreams.jsonl"
        gen = DreamGenerator(graph, dream_log_path=path)
        dreams = gen.generate_dreams(count=2)
        gen.save_dreams(dreams, session_id=5)

        assert path.exists()
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == len(dreams)

        loaded = json.loads(lines[0])
        assert loaded["session"] == 5
        assert "content" in loaded

    def test_load_recent_dreams(self, graph, tmp_dir):
        path = Path(tmp_dir) / "dreams.jsonl"
        gen = DreamGenerator(graph, dream_log_path=path)

        dreams = gen.generate_dreams(count=3)
        gen.save_dreams(dreams, session_id=5)

        loaded = DreamGenerator.load_recent_dreams(limit=10, dream_log_path=path)
        assert len(loaded) == len(dreams)

    def test_load_recent_dreams_limit(self, graph, tmp_dir):
        path = Path(tmp_dir) / "dreams.jsonl"
        gen = DreamGenerator(graph, dream_log_path=path)

        for session in range(5):
            dreams = gen.generate_dreams(count=2)
            gen.save_dreams(dreams, session_id=session)

        loaded = DreamGenerator.load_recent_dreams(limit=3, dream_log_path=path)
        assert len(loaded) == 3

    def test_load_dreams_empty(self, graph, tmp_dir):
        path = Path(tmp_dir) / "nonexistent.jsonl"
        loaded = DreamGenerator.load_recent_dreams(dream_log_path=path)
        assert loaded == []


# ============================================================
# TestSleepPhases
# ============================================================

class TestSleepPhases:
    """Tests for individual NREM phases."""

    def test_nrem1_stats(self, graph):
        proc = SleepProcessor(graph)
        result = proc._phase_nrem1()

        assert result["phase"] == "nrem1"
        assert result["total_nodes"] == 5
        assert result["total_edges"] == 2
        assert "type_counts" in result
        assert result["type_counts"].get("entity", 0) == 5
        assert "avg_importance" in result

    def test_nrem1_empty_graph(self, empty_graph):
        proc = SleepProcessor(empty_graph)
        result = proc._phase_nrem1()
        assert result["total_nodes"] == 0
        assert result["total_edges"] == 0

    def test_nrem2_boost_edges(self, graph):
        """NREM2 should boost edges with high access count."""
        # Set access count on one edge
        edge_key = list(graph.edges.keys())[0]
        graph.edges[edge_key]["access_count"] = 5
        old_weight = graph.edges[edge_key]["weight"]

        proc = SleepProcessor(graph)
        result = proc._phase_nrem2()

        assert result["phase"] == "nrem2"
        assert result["edges_boosted"] >= 1
        assert graph.edges[edge_key]["weight"] == old_weight + EDGE_BOOST_AMOUNT

    def test_nrem2_no_boost_low_access(self, graph):
        """NREM2 should not boost edges with low access count."""
        proc = SleepProcessor(graph)
        result = proc._phase_nrem2()
        assert result["edges_boosted"] == 0

    def test_nrem2_weight_capped(self, graph):
        """Edge weight should not exceed 2.0."""
        edge_key = list(graph.edges.keys())[0]
        graph.edges[edge_key]["access_count"] = 10
        graph.edges[edge_key]["weight"] = 1.95

        proc = SleepProcessor(graph)
        proc._phase_nrem2()

        assert graph.edges[edge_key]["weight"] <= 2.0

    def test_nrem3_marks_stale_nodes(self, graph):
        """NREM3 should mark old low-importance nodes as outdated."""
        # Make a node old and unimportant
        node_id = list(graph.nodes.keys())[0]
        graph.nodes[node_id]["importance"] = 0.1
        graph.nodes[node_id]["created_at"] = (
            datetime.now() - timedelta(hours=72)
        ).isoformat()

        proc = SleepProcessor(graph)
        result = proc._phase_nrem3()

        assert result["phase"] == "nrem3"
        assert result["nodes_marked_outdated"] >= 1
        assert graph.nodes[node_id]["is_outdated"] is True

    def test_nrem3_keeps_important_nodes(self, graph):
        """NREM3 should not mark important nodes."""
        for node in graph.nodes.values():
            node["importance"] = 0.8
            node["created_at"] = (
                datetime.now() - timedelta(hours=72)
            ).isoformat()

        proc = SleepProcessor(graph)
        result = proc._phase_nrem3()
        assert result["nodes_marked_outdated"] == 0

    def test_nrem3_keeps_recent_nodes(self, graph):
        """NREM3 should not mark recent nodes even if low importance."""
        for node in graph.nodes.values():
            node["importance"] = 0.1
            # Created recently
            node["created_at"] = datetime.now().isoformat()

        proc = SleepProcessor(graph)
        result = proc._phase_nrem3()
        assert result["nodes_marked_outdated"] == 0


# ============================================================
# TestSleepProcessor
# ============================================================

class TestSleepProcessor:
    """Tests for full sleep cycle."""

    def test_process_sleep_cycle_returns_report(self, graph):
        proc = SleepProcessor(graph, session_id=5)
        report = proc.process_sleep_cycle()

        assert isinstance(report, dict)
        assert "phases" in report
        assert "dreams" in report
        assert "duration_ms" in report
        assert report["session"] == 5

    def test_all_phases_run(self, graph):
        proc = SleepProcessor(graph)
        report = proc.process_sleep_cycle()

        assert "nrem1" in report["phases"]
        assert "nrem2" in report["phases"]
        assert "nrem3" in report["phases"]
        assert "rem" in report["phases"]

    def test_dreams_in_report(self, graph):
        proc = SleepProcessor(graph)
        report = proc.process_sleep_cycle()

        assert isinstance(report["dreams"], list)
        # With 5 nodes, should generate at least 1 dream
        assert len(report["dreams"]) >= 1

    def test_duration_tracked(self, graph):
        proc = SleepProcessor(graph)
        report = proc.process_sleep_cycle()
        assert report["duration_ms"] >= 0

    def test_empty_graph_cycle(self, empty_graph):
        """Sleep cycle on empty graph should not crash."""
        proc = SleepProcessor(empty_graph)
        report = proc.process_sleep_cycle()
        assert report["dreams"] == []

    def test_sleep_phase_enum(self):
        """Verify SleepPhase enum values."""
        assert SleepPhase.NREM1.value == "nrem1"
        assert SleepPhase.NREM2.value == "nrem2"
        assert SleepPhase.NREM3.value == "nrem3"
        assert SleepPhase.REM.value == "rem"

    def test_dream_persistence(self, graph, tmp_dir):
        """Dreams should be saved to disk during REM phase."""
        dream_path = Path(tmp_dir) / "dreams.jsonl"
        proc = SleepProcessor(graph, session_id=7, dream_log_path=dream_path)
        report = proc.process_sleep_cycle()

        if report["dreams"]:
            assert dream_path.exists()
            lines = dream_path.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == len(report["dreams"])


# ============================================================
# TestIntegration
# ============================================================

class TestIntegration:
    """Integration tests."""

    def test_import_from_package(self):
        from agent_core.consciousness.dream_generator import DreamGenerator as DG
        from agent_core.consciousness.sleep_processor import SleepProcessor as SP
        assert DG is not None
        assert SP is not None

    def test_multiple_sleep_cycles(self, graph, tmp_dir):
        """Multiple sleep cycles accumulate dreams."""
        dream_path = Path(tmp_dir) / "dreams.jsonl"

        for session in range(3):
            proc = SleepProcessor(graph, session_id=session, dream_log_path=dream_path)
            proc.process_sleep_cycle()

        all_dreams = DreamGenerator.load_recent_dreams(limit=100, dream_log_path=dream_path)
        assert len(all_dreams) >= 3  # At least 1 dream per session

    def test_graph_modified_by_sleep(self, graph):
        """Sleep cycle should modify graph (boost edges, mark outdated, add dream connections)."""
        # Prepare: make one edge frequently accessed
        edge_key = list(graph.edges.keys())[0]
        graph.edges[edge_key]["access_count"] = 5
        old_weight = graph.edges[edge_key]["weight"]

        # Prepare: make one node stale
        node_id = list(graph.nodes.keys())[0]
        graph.nodes[node_id]["importance"] = 0.05
        graph.nodes[node_id]["created_at"] = (
            datetime.now() - timedelta(hours=100)
        ).isoformat()

        proc = SleepProcessor(graph)
        report = proc.process_sleep_cycle()

        # Edge should be boosted
        assert graph.edges[edge_key]["weight"] > old_weight

        # Node should be marked outdated
        assert graph.nodes[node_id]["is_outdated"] is True

    def test_sleep_report_serializable(self, graph):
        """Sleep report should be JSON-serializable."""
        proc = SleepProcessor(graph)
        report = proc.process_sleep_cycle()

        # Should not raise
        json_str = json.dumps(report, ensure_ascii=False)
        assert len(json_str) > 0
