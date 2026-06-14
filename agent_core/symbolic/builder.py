"""SymbolicBuilder — derives property graph from BeliefStore + GoalStore + action audit.

Phase 1 V1: full rebuild on dirty flag. Reads source mtimes to skip work when
nothing changed. Phase 2+ may move to incremental updates.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from agent_core.symbolic.edge_model import SymbolicEdge
from agent_core.symbolic.graph import SymbolicGraph
from agent_core.symbolic.node_model import SymbolicNode

logger = logging.getLogger(__name__)


# Audit window — actions older than this are ignored during build.
DEFAULT_ACTION_WINDOW_SEC = 7 * 86400  # 7 days


class SymbolicBuilder:
    """Build symbolic graph from K6 beliefs + K3 goals + audit actions."""

    def __init__(
        self,
        graph: SymbolicGraph,
        belief_store=None,
        goal_store=None,
        action_audit_path: Optional[Path] = None,
        action_window_sec: float = DEFAULT_ACTION_WINDOW_SEC,
    ):
        self._graph = graph
        self._belief_store = belief_store
        self._goal_store = goal_store
        self._audit_path = Path(action_audit_path) if action_audit_path else None
        self._action_window_sec = action_window_sec
        self._last_build_ts: float = 0.0

    @property
    def last_build_ts(self) -> float:
        return self._last_build_ts

    def is_dirty(self) -> bool:
        """Check if any source has mtime > last build."""
        return self._max_source_mtime() > self._last_build_ts

    def _max_source_mtime(self) -> float:
        """Max mtime across belief/goal store files + audit. 0 if none exist."""
        candidates: List[Path] = []
        for src in (self._belief_store, self._goal_store):
            if src is None:
                continue
            path = getattr(src, "_path", None) or getattr(src, "path", None)
            if path:
                candidates.append(Path(path))
        if self._audit_path:
            candidates.append(self._audit_path)

        max_mtime = 0.0
        for p in candidates:
            try:
                if p.exists():
                    max_mtime = max(max_mtime, p.stat().st_mtime)
            except OSError:
                continue
        return max_mtime

    def rebuild(self) -> Dict[str, int]:
        """Full rebuild: clear graph, iterate sources, populate nodes + edges."""
        stats = {"nodes_belief": 0, "nodes_goal": 0, "nodes_action": 0,
                 "nodes_topic": 0, "nodes_exam": 0,
                 "edges_related": 0, "edges_child": 0, "edges_for_goal": 0,
                 "edges_evaluated_again": 0, "edges_examined": 0}

        self._graph.clear()

        self._build_beliefs(stats)
        self._build_goals(stats)
        self._build_actions(stats)

        self._last_build_ts = time.time()
        return stats

    def rebuild_if_dirty(self) -> Optional[Dict[str, int]]:
        """Rebuild only if any source has newer mtime. Returns stats or None."""
        if self.is_dirty():
            return self.rebuild()
        return None

    # =========================================================================
    # Beliefs
    # =========================================================================

    def _build_beliefs(self, stats: Dict[str, int]) -> None:
        if self._belief_store is None:
            return
        try:
            beliefs = self._belief_store.get_current()
        except Exception as e:
            logger.warning(f"[SymbolicBuilder] belief_store.get_current() failed: {e}")
            return

        # First pass — create nodes
        entity_to_node: Dict[str, str] = {}
        for belief in beliefs:
            node_id = f"node-belief-{belief.belief_id[-8:]}"
            node = SymbolicNode(
                node_id=node_id,
                type="belief",
                label=str(belief.entity),
                properties={
                    "entity_type": getattr(belief.entity_type, "value", str(belief.entity_type)),
                    "belief_type": getattr(belief.belief_type, "value", str(belief.belief_type)),
                    "confidence": belief.confidence,
                    "content": (belief.content or "")[:200],
                    "source": getattr(belief.source, "value", str(belief.source)),
                },
                derived_from=f"belief:{belief.belief_id}",
                created_at=belief.created_at,
                updated_at=belief.updated_at,
            )
            self._graph.add_node(node)
            entity_to_node[str(belief.entity)] = node_id
            stats["nodes_belief"] += 1

        # Second pass — related_entities → related_to edges
        for belief in beliefs:
            src_id = entity_to_node.get(str(belief.entity))
            if not src_id:
                continue
            for related in (belief.related_entities or []):
                tgt_id = entity_to_node.get(str(related))
                if not tgt_id or tgt_id == src_id:
                    continue
                self._graph.add_edge(SymbolicEdge(
                    type="related_to",
                    from_node=src_id,
                    to_node=tgt_id,
                    properties={"derived_via": "belief.related_entities"},
                    confidence=belief.confidence,
                    derived_by="builder:beliefs",
                ))
                stats["edges_related"] += 1

    # =========================================================================
    # Goals
    # =========================================================================

    def _build_goals(self, stats: Dict[str, int]) -> None:
        if self._goal_store is None:
            return
        try:
            goals = list(self._goal_store.get_all())
        except Exception as e:
            logger.warning(f"[SymbolicBuilder] goal_store.get_all() failed: {e}")
            return

        goal_id_to_node: Dict[str, str] = {}
        topic_to_node: Dict[str, str] = {}

        for goal in goals:
            node_id = f"node-goal-{getattr(goal, 'goal_id', '')[-8:]}"
            metadata = getattr(goal, "metadata", {}) or {}
            depends_on = list(metadata.get("depends_on", []))
            self._graph.add_node(SymbolicNode(
                node_id=node_id,
                type="goal",
                label=getattr(goal, "description", "")[:100],
                properties={
                    "goal_type": getattr(getattr(goal, "goal_type", None), "value",
                                         str(getattr(goal, "goal_type", ""))),
                    "status": getattr(getattr(goal, "status", None), "value",
                                      str(getattr(goal, "status", ""))),
                    "priority": getattr(goal, "priority", 0.5),
                    "depends_on": depends_on,
                },
                derived_from=f"goal:{getattr(goal, 'goal_id', '')}",
                created_at=getattr(goal, "created_at", time.time()),
                updated_at=getattr(goal, "updated_at", time.time()),
            ))
            goal_id_to_node[getattr(goal, "goal_id", "")] = node_id
            stats["nodes_goal"] += 1

            # Topic node z metadata.topic (gdy istnieje)
            topic = metadata.get("topic")
            if topic and isinstance(topic, str):
                if topic not in topic_to_node:
                    topic_node_id = f"node-topic-{abs(hash(topic)) % (10**8):08d}"
                    self._graph.add_node(SymbolicNode(
                        node_id=topic_node_id,
                        type="topic",
                        label=topic,
                        properties={},
                        derived_from=f"goal_metadata:{getattr(goal, 'goal_id', '')}",
                    ))
                    topic_to_node[topic] = topic_node_id
                    stats["nodes_topic"] += 1

        # parent_goal_id → child_of edge
        for goal in goals:
            parent_id = getattr(goal, "parent_goal_id", None)
            if not parent_id:
                continue
            child_node = goal_id_to_node.get(getattr(goal, "goal_id", ""))
            parent_node = goal_id_to_node.get(parent_id)
            if child_node and parent_node:
                self._graph.add_edge(SymbolicEdge(
                    type="child_of",
                    from_node=child_node,
                    to_node=parent_node,
                    derived_by="builder:goals",
                ))
                stats["edges_child"] += 1

        # Save mappings for actions phase (instance-scoped, set as attrs)
        self._goal_id_to_node = goal_id_to_node
        self._topic_to_node = topic_to_node

    # =========================================================================
    # Actions (from audit JSONL)
    # =========================================================================

    def _build_actions(self, stats: Dict[str, int]) -> None:
        if not self._audit_path or not self._audit_path.exists():
            return

        goal_id_to_node = getattr(self, "_goal_id_to_node", {})
        topic_to_node = getattr(self, "_topic_to_node", {})
        cutoff = time.time() - self._action_window_sec

        # Track evaluate counts per goal — used to derive evaluated_again edges
        evaluated_counts: Dict[str, int] = {}

        try:
            with self._audit_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = rec.get("timestamp", 0)
                    if not isinstance(ts, (int, float)) or ts < cutoff:
                        continue

                    action_type = rec.get("action_type", "")
                    goal_id = rec.get("goal_id", "")
                    record_id = rec.get("record_id", "")
                    success = rec.get("success", False)

                    action_node_id = f"node-action-{record_id[-12:]}" if record_id else f"node-action-{int(ts)}"
                    self._graph.add_node(SymbolicNode(
                        node_id=action_node_id,
                        type="action",
                        label=action_type,
                        properties={
                            "action_type": action_type,
                            "success": bool(success),
                            "goal_id": goal_id,
                        },
                        derived_from=f"action:{record_id}",
                        created_at=float(ts),
                    ))
                    stats["nodes_action"] += 1

                    goal_node = goal_id_to_node.get(goal_id)
                    if goal_node:
                        self._graph.add_edge(SymbolicEdge(
                            type="for_goal",
                            from_node=action_node_id,
                            to_node=goal_node,
                            derived_by="builder:actions",
                            created_at=float(ts),
                        ))
                        stats["edges_for_goal"] += 1

                        if action_type == "evaluate":
                            evaluated_counts[goal_node] = evaluated_counts.get(goal_node, 0) + 1
                            # Emit evaluated_again edge from goal to action (counts read by rule)
                            self._graph.add_edge(SymbolicEdge(
                                type="evaluated_again",
                                from_node=goal_node,
                                to_node=action_node_id,
                                derived_by="builder:actions",
                                created_at=float(ts),
                            ))
                            stats["edges_evaluated_again"] += 1

                    # Exam topic linkage
                    if action_type == "exam":
                        exam_topic = (
                            rec.get("action_params", {}).get("topic")
                            or rec.get("metadata", {}).get("topic")
                        )
                        # Convert action node into exam node by adding exam_topic property
                        # (We already added the node; in V1 we keep action node and emit
                        # examined edge from topic if topic node exists.)
                        if exam_topic and isinstance(exam_topic, str):
                            # Ensure exam node has distinct type for rule readability
                            # — add a duplicate-typed exam node OR keep action node and
                            # use topic→action examined edge. Simpler: add exam-typed node.
                            exam_node_id = f"node-exam-{record_id[-12:]}" if record_id else f"node-exam-{int(ts)}"
                            self._graph.add_node(SymbolicNode(
                                node_id=exam_node_id,
                                type="exam",
                                label=exam_topic,
                                properties={"success": bool(success), "topic": exam_topic},
                                derived_from=f"action:{record_id}",
                                created_at=float(ts),
                            ))
                            stats["nodes_exam"] += 1

                            topic_node = topic_to_node.get(exam_topic)
                            if topic_node:
                                self._graph.add_edge(SymbolicEdge(
                                    type="examined",
                                    from_node=topic_node,
                                    to_node=exam_node_id,
                                    derived_by="builder:actions",
                                    created_at=float(ts),
                                ))
                                stats["edges_examined"] += 1
        except OSError as e:
            logger.warning(f"[SymbolicBuilder] audit read failed: {e}")
