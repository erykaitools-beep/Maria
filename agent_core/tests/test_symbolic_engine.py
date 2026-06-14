"""Tests for ForwardChainingEngine + @rule decorator + 3 bootstrap rules."""

import time

import pytest

from agent_core.symbolic import ForwardChainingEngine, SymbolicEdge, SymbolicGraph, SymbolicNode
from agent_core.symbolic.rules import _REGISTERED_RULES, clear_registry, get_registered_rules, rule
from agent_core.symbolic.rules.goal_rules import derive_goal_blocks
from agent_core.symbolic.rules.learning_rules import detect_topic_needs_intervention
from agent_core.symbolic.rules.planner_rules import detect_stuck_loop


@pytest.fixture
def graph(tmp_path):
    return SymbolicGraph(tmp_path / "g.jsonl")


# =============================================================================
# @rule decorator
# =============================================================================


class TestRuleDecorator:
    def setup_method(self):
        # Snapshot registry to restore after each test
        self._snapshot = list(_REGISTERED_RULES)

    def teardown_method(self):
        clear_registry()
        _REGISTERED_RULES.extend(self._snapshot)

    def test_decorator_registers_function(self):
        clear_registry()

        @rule(priority=42)
        def my_rule(graph):
            pass

        registered = get_registered_rules()
        assert len(registered) == 1
        priority, name, fn = registered[0]
        assert priority == 42
        assert name == "my_rule"
        assert fn is my_rule

    def test_decorator_custom_name(self):
        clear_registry()

        @rule(priority=1, name="custom")
        def some_function(graph):
            pass

        _, name, _ = get_registered_rules()[0]
        assert name == "custom"

    def test_registry_sorted_by_priority_desc(self):
        clear_registry()

        @rule(priority=10)
        def low(graph):
            pass

        @rule(priority=50)
        def high(graph):
            pass

        @rule(priority=30)
        def mid(graph):
            pass

        names = [name for _, name, _ in get_registered_rules()]
        assert names == ["high", "mid", "low"]


# =============================================================================
# ForwardChainingEngine
# =============================================================================


class TestForwardChainingEngine:
    def test_single_rule_applies(self, graph):
        graph.add_node(SymbolicNode(node_id="a", type="goal"))

        def add_marker(g):
            if not any(g.edges_from("a", type="marker")):
                g.add_edge(SymbolicEdge(type="marker", from_node="a", to_node="marker_sink"))

        engine = ForwardChainingEngine(graph, rules=[(50, "add_marker", add_marker)])
        stats = engine.apply_all()
        assert stats["edges_added_total"] == 1
        assert stats["rule_fires"]["add_marker"] == 1

    def test_iterates_to_fixpoint(self, graph):
        # Rule that adds N edges per fire, but idempotent (only if missing)
        graph.add_node(SymbolicNode(node_id="a", type="goal"))
        fired = {"count": 0}

        def chain_rule(g):
            fired["count"] += 1
            existing = list(g.edges_from("a", type="step"))
            if len(existing) < 3:
                g.add_edge(SymbolicEdge(type="step", from_node="a", to_node=f"s{len(existing)}"))

        engine = ForwardChainingEngine(graph, rules=[(50, "chain_rule", chain_rule)])
        stats = engine.apply_all()
        # After 3 fires no new edges → fixpoint on iteration 4
        assert stats["iterations"] <= 4
        step_edges = list(graph.edges_from("a", type="step"))
        assert len(step_edges) == 3

    def test_max_iterations_safeguard(self, graph):
        # Non-idempotent rule that always adds new edge → engine stops at MAX_ITERATIONS
        graph.add_node(SymbolicNode(node_id="a", type="goal"))
        counter = {"i": 0}

        def runaway(g):
            counter["i"] += 1
            g.add_node(SymbolicNode(node_id=f"new-{counter['i']}", type="synth"))
            g.add_edge(SymbolicEdge(type="link", from_node="a", to_node=f"new-{counter['i']}"))

        engine = ForwardChainingEngine(graph, rules=[(50, "runaway", runaway)])
        stats = engine.apply_all()
        from agent_core.symbolic.engine import MAX_ITERATIONS
        assert stats["iterations"] == MAX_ITERATIONS

    def test_rule_exception_does_not_break_engine(self, graph):
        graph.add_node(SymbolicNode(node_id="a", type="goal"))

        def good_rule(g):
            if not any(g.edges_from("a", type="ok")):
                g.add_edge(SymbolicEdge(type="ok", from_node="a", to_node="sink"))

        def bad_rule(g):
            raise RuntimeError("intentional")

        engine = ForwardChainingEngine(
            graph,
            rules=[(80, "bad", bad_rule), (50, "good", good_rule)],
        )
        stats = engine.apply_all()
        assert stats["edges_added_total"] >= 1
        assert "good" in stats["rule_fires"]

    def test_empty_graph_no_errors(self, graph):
        engine = ForwardChainingEngine(graph, rules=[])
        stats = engine.apply_all()
        assert stats["iterations"] == 1
        assert stats["edges_added_total"] == 0


# =============================================================================
# Bootstrap rules — planner stuck-loop
# =============================================================================


class TestPlannerStuckLoopRule:
    def test_emits_stuck_loop_after_5_evals(self, graph):
        graph.add_node(SymbolicNode(node_id="g1", type="goal"))
        now = time.time()
        for i in range(5):
            graph.add_edge(SymbolicEdge(
                type="evaluated_again",
                from_node="g1",
                to_node=f"eval-{i}",
                created_at=now - 100,
            ))

        detect_stuck_loop(graph)
        stuck_edges = list(graph.edges_from("g1", type="stuck_loop_detected"))
        assert len(stuck_edges) == 1
        assert stuck_edges[0].to_node == "planner"
        assert stuck_edges[0].properties["eval_count"] == 5

    def test_no_stuck_when_fewer_than_threshold(self, graph):
        graph.add_node(SymbolicNode(node_id="g1", type="goal"))
        now = time.time()
        for i in range(4):
            graph.add_edge(SymbolicEdge(
                type="evaluated_again",
                from_node="g1",
                to_node=f"eval-{i}",
                created_at=now - 100,
            ))

        detect_stuck_loop(graph)
        assert list(graph.edges_from("g1", type="stuck_loop_detected")) == []

    def test_no_stuck_when_evals_outside_window(self, graph):
        from agent_core.symbolic.rules.planner_rules import STUCK_LOOP_WINDOW_SEC

        graph.add_node(SymbolicNode(node_id="g1", type="goal"))
        old_ts = time.time() - STUCK_LOOP_WINDOW_SEC - 100  # outside window
        for i in range(5):
            graph.add_edge(SymbolicEdge(
                type="evaluated_again",
                from_node="g1",
                to_node=f"eval-{i}",
                created_at=old_ts,
            ))

        detect_stuck_loop(graph)
        assert list(graph.edges_from("g1", type="stuck_loop_detected")) == []

    def test_idempotent_no_duplicate_emit(self, graph):
        graph.add_node(SymbolicNode(node_id="g1", type="goal"))
        now = time.time()
        for i in range(5):
            graph.add_edge(SymbolicEdge(
                type="evaluated_again", from_node="g1", to_node=f"e{i}", created_at=now,
            ))

        detect_stuck_loop(graph)
        detect_stuck_loop(graph)
        detect_stuck_loop(graph)
        assert len(list(graph.edges_from("g1", type="stuck_loop_detected"))) == 1


# =============================================================================
# Bootstrap rules — exam failure → K12
# =============================================================================


class TestLearningRule:
    def test_emits_intervention_after_3_failed_exams(self, graph):
        graph.add_node(SymbolicNode(node_id="t1", type="topic", label="topic_x"))
        now = time.time()
        for i in range(3):
            exam_id = f"exam-{i}"
            graph.add_node(SymbolicNode(
                node_id=exam_id,
                type="exam",
                properties={"success": False},
                created_at=now - 100,
            ))
            graph.add_edge(SymbolicEdge(
                type="examined", from_node="t1", to_node=exam_id, created_at=now,
            ))

        detect_topic_needs_intervention(graph)
        edges = list(graph.edges_from("t1", type="topic_needs_intervention"))
        assert len(edges) == 1
        assert edges[0].to_node == "k12_proposed_goal_target"

    def test_no_intervention_when_exams_succeeded(self, graph):
        graph.add_node(SymbolicNode(node_id="t1", type="topic", label="topic_x"))
        now = time.time()
        for i in range(5):
            exam_id = f"exam-{i}"
            graph.add_node(SymbolicNode(
                node_id=exam_id,
                type="exam",
                properties={"success": True},
                created_at=now - 100,
            ))
            graph.add_edge(SymbolicEdge(
                type="examined", from_node="t1", to_node=exam_id, created_at=now,
            ))

        detect_topic_needs_intervention(graph)
        assert list(graph.edges_from("t1", type="topic_needs_intervention")) == []

    def test_idempotent(self, graph):
        graph.add_node(SymbolicNode(node_id="t1", type="topic", label="topic_x"))
        now = time.time()
        for i in range(3):
            exam_id = f"exam-{i}"
            graph.add_node(SymbolicNode(
                node_id=exam_id, type="exam", properties={"success": False}, created_at=now,
            ))
            graph.add_edge(SymbolicEdge(
                type="examined", from_node="t1", to_node=exam_id, created_at=now,
            ))

        detect_topic_needs_intervention(graph)
        detect_topic_needs_intervention(graph)
        assert len(list(graph.edges_from("t1", type="topic_needs_intervention"))) == 1


# =============================================================================
# Bootstrap rules — goal dependency blocks
# =============================================================================


class TestGoalDependencyRule:
    def test_emits_blocks_on_for_low_confidence_belief(self, graph):
        graph.add_node(SymbolicNode(
            node_id="g1",
            type="goal",
            properties={"status": "ACTIVE", "depends_on": ["fact_x"]},
        ))
        graph.add_node(SymbolicNode(
            node_id="b1",
            type="belief",
            label="fact_x",
            properties={"confidence": 0.3},
        ))

        derive_goal_blocks(graph)
        edges = list(graph.edges_from("g1", type="blocks_on"))
        assert len(edges) == 1
        assert edges[0].to_node == "b1"

    def test_no_blocks_when_high_confidence(self, graph):
        graph.add_node(SymbolicNode(
            node_id="g1",
            type="goal",
            properties={"status": "ACTIVE", "depends_on": ["fact_x"]},
        ))
        graph.add_node(SymbolicNode(
            node_id="b1",
            type="belief",
            label="fact_x",
            properties={"confidence": 0.8},
        ))

        derive_goal_blocks(graph)
        assert list(graph.edges_from("g1", type="blocks_on")) == []

    def test_no_blocks_for_inactive_goal(self, graph):
        graph.add_node(SymbolicNode(
            node_id="g1",
            type="goal",
            properties={"status": "PENDING", "depends_on": ["fact_x"]},
        ))
        graph.add_node(SymbolicNode(
            node_id="b1", type="belief", label="fact_x", properties={"confidence": 0.3},
        ))

        derive_goal_blocks(graph)
        assert list(graph.edges_from("g1", type="blocks_on")) == []

    def test_idempotent(self, graph):
        graph.add_node(SymbolicNode(
            node_id="g1", type="goal",
            properties={"status": "ACTIVE", "depends_on": ["fact_x"]},
        ))
        graph.add_node(SymbolicNode(
            node_id="b1", type="belief", label="fact_x",
            properties={"confidence": 0.3},
        ))

        derive_goal_blocks(graph)
        derive_goal_blocks(graph)
        assert len(list(graph.edges_from("g1", type="blocks_on"))) == 1


# =============================================================================
# Integration — engine + auto-registered rules
# =============================================================================


class TestEngineWithAutoRegisteredRules:
    def test_three_bootstrap_rules_registered(self):
        """Importing agent_core.symbolic auto-registers 3 bootstrap rules."""
        # Force re-import to ensure registration ran
        import agent_core.symbolic  # noqa: F401

        registered = get_registered_rules()
        names = [name for _, name, _ in registered]
        assert "detect_stuck_loop" in names
        assert "detect_topic_needs_intervention" in names
        assert "derive_goal_blocks" in names

    def test_engine_uses_registry_when_no_explicit_rules(self, graph):
        """ForwardChainingEngine without explicit rules uses module registry."""
        engine = ForwardChainingEngine(graph)
        # Empty graph, no firing expected
        stats = engine.apply_all()
        assert stats["edges_added_total"] == 0
