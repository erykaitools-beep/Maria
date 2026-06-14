"""Learning-related inference rules — exam failure pattern → K12 intervention."""

import time

from agent_core.symbolic.edge_model import SymbolicEdge
from agent_core.symbolic.graph import SymbolicGraph
from agent_core.symbolic.rules import rule

TOPIC_INTERVENTION_FAIL_THRESHOLD = 3
TOPIC_INTERVENTION_WINDOW_SEC = 7 * 86400  # 7 days


@rule(priority=80, name="detect_topic_needs_intervention")
def detect_topic_needs_intervention(graph: SymbolicGraph) -> None:
    """Topic z 3+ failed exams w 7d → topic_needs_intervention edge.

    Reads topic nodes + edges to exam nodes (populated by builder).
    Failed exam = exam node properties.success is False.
    """
    now = time.time()
    cutoff = now - TOPIC_INTERVENTION_WINDOW_SEC

    for topic_node in graph.nodes_with(type="topic"):
        failed_exam_count = 0
        for exam_node in graph.neighbors(topic_node.node_id, edge_type="examined"):
            if exam_node.type != "exam":
                continue
            if exam_node.properties.get("success") is False:
                if exam_node.created_at >= cutoff:
                    failed_exam_count += 1

        if failed_exam_count < TOPIC_INTERVENTION_FAIL_THRESHOLD:
            continue

        # Idempotence: skip if already emitted
        existing = [
            e for e in graph.edges_from(topic_node.node_id, type="topic_needs_intervention")
            if e.to_node == "k12_proposed_goal_target"
        ]
        if existing:
            continue

        graph.add_edge(SymbolicEdge(
            type="topic_needs_intervention",
            from_node=topic_node.node_id,
            to_node="k12_proposed_goal_target",
            properties={
                "failed_count": failed_exam_count,
                "window_sec": TOPIC_INTERVENTION_WINDOW_SEC,
            },
            confidence=0.9,
            derived_by="rule:detect_topic_needs_intervention",
            created_at=now,
        ))
