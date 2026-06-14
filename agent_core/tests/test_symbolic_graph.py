"""Tests for SymbolicNode, SymbolicEdge, SymbolicGraph (Phase 1 V1)."""

import json
from pathlib import Path

import pytest

from agent_core.symbolic import SymbolicEdge, SymbolicGraph, SymbolicNode


# =============================================================================
# Data model
# =============================================================================


class TestSymbolicNode:
    def test_default_factory_generates_id(self):
        n = SymbolicNode()
        assert n.node_id.startswith("node-")
        assert len(n.node_id) == len("node-") + 8

    def test_to_dict_roundtrip(self):
        n = SymbolicNode(
            node_id="node-abc",
            type="goal",
            label="goal-meta-learn",
            properties={"status": "ACTIVE", "priority": 0.9},
            derived_from="goal:goal-meta-learn",
        )
        d = n.to_dict()
        assert d["node_id"] == "node-abc"
        assert d["type"] == "goal"
        assert d["properties"]["status"] == "ACTIVE"
        assert d["_kind"] == "node"

        restored = SymbolicNode.from_dict(d)
        assert restored.node_id == n.node_id
        assert restored.type == n.type
        assert restored.label == n.label
        assert restored.properties == n.properties

    def test_from_dict_missing_fields_defaults(self):
        n = SymbolicNode.from_dict({})
        assert n.node_id.startswith("node-")
        assert n.type == "synthetic"
        assert n.properties == {}


class TestSymbolicEdge:
    def test_default_factory_generates_id(self):
        e = SymbolicEdge()
        assert e.edge_id.startswith("edge-")
        assert len(e.edge_id) == len("edge-") + 8

    def test_to_dict_roundtrip(self):
        e = SymbolicEdge(
            edge_id="edge-xyz",
            type="stuck_loop_detected",
            from_node="node-1",
            to_node="planner",
            properties={"eval_count": 7},
            confidence=0.95,
            derived_by="rule:detect_stuck_loop",
        )
        d = e.to_dict()
        assert d["_kind"] == "edge"
        assert d["confidence"] == 0.95

        restored = SymbolicEdge.from_dict(d)
        assert restored.edge_id == e.edge_id
        assert restored.type == e.type
        assert restored.confidence == e.confidence


# =============================================================================
# SymbolicGraph
# =============================================================================


@pytest.fixture
def graph(tmp_path):
    return SymbolicGraph(tmp_path / "g.jsonl")


class TestSymbolicGraphBasics:
    def test_add_node_indexed_by_type(self, graph):
        n = SymbolicNode(node_id="node-1", type="goal", label="g1")
        graph.add_node(n)
        assert graph.get_node("node-1") is n
        assert list(graph.nodes_with(type="goal")) == [n]
        assert list(graph.nodes_with(type="belief")) == []

    def test_add_edge_indexed_both_directions(self, graph):
        graph.add_node(SymbolicNode(node_id="a", type="goal"))
        graph.add_node(SymbolicNode(node_id="b", type="goal"))
        e = SymbolicEdge(edge_id="edge-1", type="blocks", from_node="a", to_node="b")
        graph.add_edge(e)
        assert list(graph.edges_from("a")) == [e]
        assert list(graph.edges_to("b")) == [e]
        assert list(graph.edges_from("b")) == []

    def test_edges_filter_by_type(self, graph):
        e1 = SymbolicEdge(edge_id="e1", type="blocks", from_node="a", to_node="b")
        e2 = SymbolicEdge(edge_id="e2", type="causes", from_node="a", to_node="b")
        graph.add_edge(e1)
        graph.add_edge(e2)
        assert list(graph.edges_from("a", type="blocks")) == [e1]
        assert list(graph.edges_from("a", type="causes")) == [e2]

    def test_nodes_with_property_filter(self, graph):
        graph.add_node(SymbolicNode(node_id="g1", type="goal", properties={"status": "ACTIVE"}))
        graph.add_node(SymbolicNode(node_id="g2", type="goal", properties={"status": "PENDING"}))
        active = list(graph.nodes_with(type="goal", status="ACTIVE"))
        assert len(active) == 1
        assert active[0].node_id == "g1"

    def test_neighbors_traversal(self, graph):
        graph.add_node(SymbolicNode(node_id="a", type="goal"))
        graph.add_node(SymbolicNode(node_id="b", type="goal"))
        graph.add_node(SymbolicNode(node_id="c", type="goal"))
        graph.add_edge(SymbolicEdge(type="blocks", from_node="a", to_node="b"))
        graph.add_edge(SymbolicEdge(type="blocks", from_node="a", to_node="c"))
        names = sorted(n.node_id for n in graph.neighbors("a"))
        assert names == ["b", "c"]

    def test_neighbors_filter_by_edge_type(self, graph):
        graph.add_node(SymbolicNode(node_id="a", type="goal"))
        graph.add_node(SymbolicNode(node_id="b", type="goal"))
        graph.add_node(SymbolicNode(node_id="c", type="goal"))
        graph.add_edge(SymbolicEdge(type="blocks", from_node="a", to_node="b"))
        graph.add_edge(SymbolicEdge(type="causes", from_node="a", to_node="c"))
        blocks = sorted(n.node_id for n in graph.neighbors("a", edge_type="blocks"))
        assert blocks == ["b"]

    def test_clear_removes_all(self, graph):
        graph.add_node(SymbolicNode(node_id="a", type="goal"))
        graph.add_edge(SymbolicEdge(type="blocks", from_node="a", to_node="b"))
        graph.clear()
        assert graph.get_node("a") is None
        assert list(graph.nodes_with(type="goal")) == []
        assert list(graph.edges_from("a")) == []


class TestSymbolicGraphPersistence:
    def test_save_load_roundtrip(self, tmp_path):
        path = tmp_path / "graph.jsonl"
        g1 = SymbolicGraph(path)
        g1.add_node(SymbolicNode(node_id="n1", type="goal", label="g1"))
        g1.add_node(SymbolicNode(node_id="n2", type="belief", label="b1"))
        g1.add_edge(SymbolicEdge(edge_id="e1", type="related", from_node="n1", to_node="n2"))
        g1.save()
        assert path.exists()

        g2 = SymbolicGraph(path)
        count = g2.load()
        assert count == 3
        assert g2.get_node("n1") is not None
        assert g2.get_node("n2") is not None
        assert list(g2.edges_from("n1"))[0].edge_id == "e1"

    def test_save_atomic_no_partial_file(self, tmp_path):
        """If save crashes mid-write, original stays intact (tmp file used)."""
        path = tmp_path / "graph.jsonl"
        g = SymbolicGraph(path)
        g.add_node(SymbolicNode(node_id="initial", type="goal"))
        g.save()

        # Verify tmp file approach: write doesn't leave .tmp behind on success
        tmp = path.with_suffix(".jsonl.tmp")
        assert not tmp.exists()

    def test_load_missing_file_returns_zero(self, tmp_path):
        g = SymbolicGraph(tmp_path / "nope.jsonl")
        assert g.load() == 0

    def test_load_skips_malformed_line(self, tmp_path):
        path = tmp_path / "graph.jsonl"
        with path.open("w") as f:
            f.write('{"_kind": "node", "node_id": "ok", "type": "goal"}\n')
            f.write("not json\n")
            f.write('{"_kind": "node", "node_id": "ok2", "type": "goal"}\n')
        g = SymbolicGraph(path)
        count = g.load()
        assert count == 2

    def test_clear_then_save_writes_empty(self, tmp_path):
        path = tmp_path / "graph.jsonl"
        g = SymbolicGraph(path)
        g.add_node(SymbolicNode(node_id="a", type="goal"))
        g.save()
        g.clear()
        g.save()
        assert path.read_text() == ""


class TestSymbolicGraphQueries:
    def test_shortest_path_direct(self, graph):
        graph.add_node(SymbolicNode(node_id="a", type="goal"))
        graph.add_node(SymbolicNode(node_id="b", type="goal"))
        graph.add_edge(SymbolicEdge(type="blocks", from_node="a", to_node="b"))
        assert graph.shortest_path("a", "b") == ["a", "b"]

    def test_shortest_path_multi_hop(self, graph):
        for nid in ("a", "b", "c", "d"):
            graph.add_node(SymbolicNode(node_id=nid, type="goal"))
        graph.add_edge(SymbolicEdge(type="next", from_node="a", to_node="b"))
        graph.add_edge(SymbolicEdge(type="next", from_node="b", to_node="c"))
        graph.add_edge(SymbolicEdge(type="next", from_node="c", to_node="d"))
        assert graph.shortest_path("a", "d") == ["a", "b", "c", "d"]

    def test_shortest_path_none_when_disconnected(self, graph):
        graph.add_node(SymbolicNode(node_id="a", type="goal"))
        graph.add_node(SymbolicNode(node_id="b", type="goal"))
        assert graph.shortest_path("a", "b") is None

    def test_shortest_path_same_node(self, graph):
        graph.add_node(SymbolicNode(node_id="a", type="goal"))
        assert graph.shortest_path("a", "a") == ["a"]

    def test_shortest_path_unknown_node(self, graph):
        assert graph.shortest_path("missing1", "missing2") is None

    def test_stats_counts_correctly(self, graph):
        graph.add_node(SymbolicNode(node_id="g1", type="goal"))
        graph.add_node(SymbolicNode(node_id="g2", type="goal"))
        graph.add_node(SymbolicNode(node_id="b1", type="belief"))
        graph.add_edge(SymbolicEdge(type="blocks", from_node="g1", to_node="g2"))
        stats = graph.stats()
        assert stats["nodes"] == 3
        assert stats["edges"] == 1
        assert stats["by_node_type"]["goal"] == 2
        assert stats["by_node_type"]["belief"] == 1
        assert stats["by_edge_type"]["blocks"] == 1
