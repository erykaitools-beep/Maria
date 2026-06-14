"""Planner-related inference rules — stuck-loop detection."""

import time

from agent_core.symbolic.edge_model import SymbolicEdge
from agent_core.symbolic.graph import SymbolicGraph
from agent_core.symbolic.rules import rule

STUCK_LOOP_EVAL_THRESHOLD = 5
STUCK_LOOP_WINDOW_SEC = 3600  # 1 hour


@rule(priority=90, name="detect_stuck_loop")
def detect_stuck_loop(graph: SymbolicGraph) -> None:
    """Goal evaluated_again >= 5 times in last hour → stuck_loop_detected edge to planner.

    Reads existing evaluated_again edges from goal nodes (populated by builder).
    Emits one stuck_loop_detected edge per goal that crosses threshold.
    Idempotent: re-running does not duplicate if same evidence (engine uses
    edge addition count as fixpoint detector; downstream consumers should
    dedupe by (from_node, to_node, type)).
    """
    now = time.time()
    cutoff = now - STUCK_LOOP_WINDOW_SEC

    for goal_node in graph.nodes_with(type="goal"):
        eval_edges = [
            e for e in graph.edges_from(goal_node.node_id, type="evaluated_again")
            if e.created_at >= cutoff
        ]
        if len(eval_edges) < STUCK_LOOP_EVAL_THRESHOLD:
            continue

        # Idempotence: skip if already emitted for this goal
        existing = [
            e for e in graph.edges_from(goal_node.node_id, type="stuck_loop_detected")
            if e.to_node == "planner"
        ]
        if existing:
            continue

        graph.add_edge(SymbolicEdge(
            type="stuck_loop_detected",
            from_node=goal_node.node_id,
            to_node="planner",
            properties={"eval_count": len(eval_edges), "window_sec": STUCK_LOOP_WINDOW_SEC},
            confidence=0.95,
            derived_by="rule:detect_stuck_loop",
            created_at=now,
        ))
