"""Goal-related inference rules — dependency tracking."""

import time

from agent_core.symbolic.edge_model import SymbolicEdge
from agent_core.symbolic.graph import SymbolicGraph
from agent_core.symbolic.rules import rule

BLOCKED_BY_BELIEF_CONFIDENCE_THRESHOLD = 0.5


@rule(priority=70, name="derive_goal_blocks")
def derive_goal_blocks(graph: SymbolicGraph) -> None:
    """Goal z dependency na low-confidence belief → blocks_on edge.

    Reads goal nodes z properties.depends_on (list of belief entity names),
    finds matching belief nodes, emits blocks_on edge gdy confidence < 0.5.
    """
    now = time.time()

    for goal_node in graph.nodes_with(type="goal"):
        if goal_node.properties.get("status") != "ACTIVE":
            continue

        depends_on = goal_node.properties.get("depends_on", [])
        if not isinstance(depends_on, list):
            continue

        for dep_entity in depends_on:
            # Find belief node with matching entity (label-based lookup)
            for belief_node in graph.nodes_with(type="belief"):
                if belief_node.label != dep_entity:
                    continue
                confidence = belief_node.properties.get("confidence", 1.0)
                if confidence >= BLOCKED_BY_BELIEF_CONFIDENCE_THRESHOLD:
                    continue

                # Idempotence: skip if blocks_on edge already exists
                existing = [
                    e for e in graph.edges_from(goal_node.node_id, type="blocks_on")
                    if e.to_node == belief_node.node_id
                ]
                if existing:
                    continue

                graph.add_edge(SymbolicEdge(
                    type="blocks_on",
                    from_node=goal_node.node_id,
                    to_node=belief_node.node_id,
                    properties={"belief_confidence": confidence},
                    confidence=0.8,
                    derived_by="rule:derive_goal_blocks",
                    created_at=now,
                ))
                break  # one blocks_on per dep_entity
