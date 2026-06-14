"""Tests for SymbolicBuilder — beliefs + goals + action audit → graph."""

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_core.symbolic import SymbolicBuilder, SymbolicGraph


@pytest.fixture
def graph(tmp_path):
    return SymbolicGraph(tmp_path / "g.jsonl")


def make_belief(belief_id, entity, entity_type="file", confidence=0.8,
                related_entities=None, content="", source="learning",
                belief_type="fact", created_at=None, updated_at=None):
    """Duck-type belief object matching BeliefStore.get_current() shape."""
    now = time.time()
    return SimpleNamespace(
        belief_id=belief_id,
        entity=entity,
        entity_type=SimpleNamespace(value=entity_type),
        belief_type=SimpleNamespace(value=belief_type),
        confidence=confidence,
        content=content,
        source=SimpleNamespace(value=source),
        related_entities=related_entities or [],
        created_at=created_at or now,
        updated_at=updated_at or now,
    )


def make_goal(goal_id, description="g", status="ACTIVE", goal_type="learning",
              priority=0.5, parent_goal_id=None, metadata=None,
              created_at=None, updated_at=None):
    now = time.time()
    return SimpleNamespace(
        goal_id=goal_id,
        description=description,
        status=SimpleNamespace(value=status),
        goal_type=SimpleNamespace(value=goal_type),
        priority=priority,
        parent_goal_id=parent_goal_id,
        metadata=metadata or {},
        created_at=created_at or now,
        updated_at=updated_at or now,
    )


def make_belief_store(beliefs, path=None):
    """Duck-type BeliefStore z get_current()."""
    return SimpleNamespace(
        get_current=lambda: beliefs,
        _path=path,
    )


def make_goal_store(goals, path=None):
    return SimpleNamespace(
        get_all=lambda: goals,
        _path=path,
    )


# =============================================================================
# Beliefs → nodes + edges
# =============================================================================


class TestBuildBeliefs:
    def test_beliefs_become_nodes(self, graph):
        beliefs = [
            make_belief("b1", "file_x", confidence=0.7),
            make_belief("b2", "file_y", confidence=0.4),
        ]
        builder = SymbolicBuilder(graph, belief_store=make_belief_store(beliefs))
        stats = builder.rebuild()
        assert stats["nodes_belief"] == 2
        nodes = list(graph.nodes_with(type="belief"))
        labels = sorted(n.label for n in nodes)
        assert labels == ["file_x", "file_y"]

    def test_belief_properties_carried(self, graph):
        beliefs = [make_belief("b1", "fact_z", confidence=0.95)]
        builder = SymbolicBuilder(graph, belief_store=make_belief_store(beliefs))
        builder.rebuild()
        node = next(graph.nodes_with(type="belief"))
        assert node.properties["confidence"] == 0.95
        assert node.properties["source"] == "learning"

    def test_related_entities_become_edges(self, graph):
        beliefs = [
            make_belief("b1", "A", related_entities=["B"]),
            make_belief("b2", "B"),
        ]
        builder = SymbolicBuilder(graph, belief_store=make_belief_store(beliefs))
        stats = builder.rebuild()
        assert stats["edges_related"] == 1
        # Verify edge present from A's node to B's node
        a_node = next(graph.nodes_with(type="belief", source="learning"))
        # find node with label A
        a_node = next(n for n in graph.nodes_with(type="belief") if n.label == "A")
        edges = list(graph.edges_from(a_node.node_id, type="related_to"))
        assert len(edges) == 1

    def test_related_entity_pointing_to_unknown_skipped(self, graph):
        beliefs = [make_belief("b1", "A", related_entities=["ghost"])]
        builder = SymbolicBuilder(graph, belief_store=make_belief_store(beliefs))
        stats = builder.rebuild()
        assert stats["edges_related"] == 0

    def test_self_reference_skipped(self, graph):
        beliefs = [make_belief("b1", "A", related_entities=["A"])]
        builder = SymbolicBuilder(graph, belief_store=make_belief_store(beliefs))
        stats = builder.rebuild()
        assert stats["edges_related"] == 0


# =============================================================================
# Goals → nodes + edges
# =============================================================================


class TestBuildGoals:
    def test_goals_become_nodes(self, graph):
        goals = [
            make_goal("g1", description="learn"),
            make_goal("g2", description="exam", status="PENDING"),
        ]
        builder = SymbolicBuilder(graph, goal_store=make_goal_store(goals))
        stats = builder.rebuild()
        assert stats["nodes_goal"] == 2

    def test_parent_child_edge(self, graph):
        goals = [
            make_goal("parent"),
            make_goal("child", parent_goal_id="parent"),
        ]
        builder = SymbolicBuilder(graph, goal_store=make_goal_store(goals))
        stats = builder.rebuild()
        assert stats["edges_child"] == 1
        child_node = next(n for n in graph.nodes_with(type="goal")
                          if n.derived_from == "goal:child")
        edges = list(graph.edges_from(child_node.node_id, type="child_of"))
        assert len(edges) == 1

    def test_topic_node_from_metadata(self, graph):
        goals = [
            make_goal("g1", metadata={"topic": "logika_formalna"}),
            make_goal("g2", metadata={"topic": "logika_formalna"}),  # same topic, dedup
        ]
        builder = SymbolicBuilder(graph, goal_store=make_goal_store(goals))
        stats = builder.rebuild()
        assert stats["nodes_topic"] == 1

    def test_depends_on_propagated_to_properties(self, graph):
        goals = [make_goal("g1", metadata={"depends_on": ["fact_x", "fact_y"]})]
        builder = SymbolicBuilder(graph, goal_store=make_goal_store(goals))
        builder.rebuild()
        node = next(graph.nodes_with(type="goal"))
        assert node.properties["depends_on"] == ["fact_x", "fact_y"]


# =============================================================================
# Actions → nodes + edges
# =============================================================================


def write_audit(path: Path, records: list) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


class TestBuildActions:
    def test_actions_become_nodes(self, graph, tmp_path):
        audit_path = tmp_path / "audit.jsonl"
        now = time.time()
        write_audit(audit_path, [
            {"record_id": "ar-1", "action_type": "review", "goal_id": "g1",
             "success": True, "timestamp": now - 100},
            {"record_id": "ar-2", "action_type": "noop", "goal_id": "g1",
             "success": True, "timestamp": now - 50},
        ])
        builder = SymbolicBuilder(graph, action_audit_path=audit_path)
        stats = builder.rebuild()
        assert stats["nodes_action"] == 2

    def test_for_goal_edge_when_goal_exists(self, graph, tmp_path):
        audit_path = tmp_path / "audit.jsonl"
        now = time.time()
        write_audit(audit_path, [
            {"record_id": "ar-1", "action_type": "review", "goal_id": "g1",
             "success": True, "timestamp": now - 10},
        ])
        goals = [make_goal("g1")]
        builder = SymbolicBuilder(
            graph,
            goal_store=make_goal_store(goals),
            action_audit_path=audit_path,
        )
        stats = builder.rebuild()
        assert stats["edges_for_goal"] == 1

    def test_evaluate_action_emits_evaluated_again(self, graph, tmp_path):
        audit_path = tmp_path / "audit.jsonl"
        now = time.time()
        records = [
            {"record_id": f"ar-{i}", "action_type": "evaluate", "goal_id": "g1",
             "success": True, "timestamp": now - i}
            for i in range(3)
        ]
        write_audit(audit_path, records)
        goals = [make_goal("g1")]
        builder = SymbolicBuilder(
            graph,
            goal_store=make_goal_store(goals),
            action_audit_path=audit_path,
        )
        stats = builder.rebuild()
        assert stats["edges_evaluated_again"] == 3

    def test_old_actions_skipped(self, graph, tmp_path):
        audit_path = tmp_path / "audit.jsonl"
        old_ts = time.time() - 30 * 86400  # 30 days ago
        write_audit(audit_path, [
            {"record_id": "ar-old", "action_type": "review", "goal_id": "g1",
             "success": True, "timestamp": old_ts},
        ])
        builder = SymbolicBuilder(graph, action_audit_path=audit_path,
                                  action_window_sec=7 * 86400)
        stats = builder.rebuild()
        assert stats["nodes_action"] == 0

    def test_exam_creates_exam_node_and_examined_edge(self, graph, tmp_path):
        audit_path = tmp_path / "audit.jsonl"
        now = time.time()
        write_audit(audit_path, [
            {"record_id": "ar-exam", "action_type": "exam", "goal_id": "g1",
             "success": False, "timestamp": now - 10,
             "action_params": {"topic": "fizyka"}},
        ])
        goals = [make_goal("g1", metadata={"topic": "fizyka"})]
        builder = SymbolicBuilder(
            graph,
            goal_store=make_goal_store(goals),
            action_audit_path=audit_path,
        )
        stats = builder.rebuild()
        assert stats["nodes_exam"] == 1
        assert stats["edges_examined"] == 1

    def test_malformed_audit_line_skipped(self, graph, tmp_path):
        audit_path = tmp_path / "audit.jsonl"
        now = time.time()
        with audit_path.open("w") as f:
            f.write(json.dumps({"record_id": "ok", "action_type": "review",
                                 "goal_id": "", "success": True, "timestamp": now}) + "\n")
            f.write("garbage non-json line\n")
            f.write(json.dumps({"record_id": "ok2", "action_type": "noop",
                                 "goal_id": "", "success": True, "timestamp": now}) + "\n")
        builder = SymbolicBuilder(graph, action_audit_path=audit_path)
        stats = builder.rebuild()
        assert stats["nodes_action"] == 2


# =============================================================================
# Rebuild + dirty flag
# =============================================================================


class TestRebuild:
    def test_rebuild_clears_old_state(self, graph):
        beliefs1 = [make_belief("b1", "old")]
        builder = SymbolicBuilder(graph, belief_store=make_belief_store(beliefs1))
        builder.rebuild()
        assert len(list(graph.nodes_with(type="belief"))) == 1

        # Replace source with different beliefs and rebuild
        beliefs2 = [make_belief("b2", "new"), make_belief("b3", "new2")]
        builder._belief_store = make_belief_store(beliefs2)
        builder.rebuild()
        labels = sorted(n.label for n in graph.nodes_with(type="belief"))
        assert labels == ["new", "new2"]

    def test_empty_sources_produce_empty_graph(self, graph):
        builder = SymbolicBuilder(graph)
        stats = builder.rebuild()
        assert stats["nodes_belief"] == 0
        assert stats["nodes_goal"] == 0
        assert stats["nodes_action"] == 0

    def test_is_dirty_initially_false_when_no_sources(self, graph):
        builder = SymbolicBuilder(graph)
        assert builder.is_dirty() is False

    def test_is_dirty_when_source_newer_than_last_build(self, graph, tmp_path):
        audit_path = tmp_path / "audit.jsonl"
        now = time.time()
        write_audit(audit_path, [
            {"record_id": "ar-1", "action_type": "review", "goal_id": "g1",
             "success": True, "timestamp": now},
        ])
        builder = SymbolicBuilder(graph, action_audit_path=audit_path)
        assert builder.is_dirty() is True

    def test_rebuild_if_dirty_returns_stats_when_dirty(self, graph, tmp_path):
        audit_path = tmp_path / "audit.jsonl"
        now = time.time()
        write_audit(audit_path, [
            {"record_id": "ar-1", "action_type": "review", "goal_id": "",
             "success": True, "timestamp": now},
        ])
        builder = SymbolicBuilder(graph, action_audit_path=audit_path)
        stats = builder.rebuild_if_dirty()
        assert stats is not None
        assert stats["nodes_action"] == 1

    def test_rebuild_if_dirty_returns_none_when_clean(self, graph, tmp_path):
        audit_path = tmp_path / "audit.jsonl"
        now = time.time()
        write_audit(audit_path, [
            {"record_id": "ar-1", "action_type": "review", "goal_id": "",
             "success": True, "timestamp": now},
        ])
        builder = SymbolicBuilder(graph, action_audit_path=audit_path)
        builder.rebuild()
        # No mtime change → clean
        result = builder.rebuild_if_dirty()
        assert result is None
