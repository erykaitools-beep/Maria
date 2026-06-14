"""SymbolicGraph — in-memory property graph z JSONL persistence."""

import json
import logging
import os
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set

from agent_core.symbolic.edge_model import SymbolicEdge
from agent_core.symbolic.node_model import SymbolicNode

logger = logging.getLogger(__name__)


class SymbolicGraph:
    """In-memory property graph z atomic JSONL persistence.

    Single file format z type discriminator (`_kind: node` lub `_kind: edge`)
    per Q3 decision A (atomic save, jeden mtime dla dirty flag).

    Thread-safe via RLock (per ADR pattern: BeliefStore uses similar lock).
    Indexes maintained lazily, rebuilt on load.
    """

    def __init__(self, graph_path: Path):
        self._path = Path(graph_path)
        self._lock = threading.RLock()
        self._nodes: Dict[str, SymbolicNode] = {}
        self._edges: Dict[str, SymbolicEdge] = {}
        self._nodes_by_type: Dict[str, Set[str]] = defaultdict(set)
        self._edges_from: Dict[str, Set[str]] = defaultdict(set)
        self._edges_to: Dict[str, Set[str]] = defaultdict(set)

    def add_node(self, node: SymbolicNode) -> None:
        with self._lock:
            self._nodes[node.node_id] = node
            self._nodes_by_type[node.type].add(node.node_id)

    def add_edge(self, edge: SymbolicEdge) -> None:
        with self._lock:
            self._edges[edge.edge_id] = edge
            self._edges_from[edge.from_node].add(edge.edge_id)
            self._edges_to[edge.to_node].add(edge.edge_id)

    def get_node(self, node_id: str) -> Optional[SymbolicNode]:
        return self._nodes.get(node_id)

    def get_edge(self, edge_id: str) -> Optional[SymbolicEdge]:
        return self._edges.get(edge_id)

    def clear(self) -> None:
        with self._lock:
            self._nodes.clear()
            self._edges.clear()
            self._nodes_by_type.clear()
            self._edges_from.clear()
            self._edges_to.clear()

    def nodes_with(self, type: Optional[str] = None, **props: Any) -> Iterator[SymbolicNode]:
        """Filter nodes by type and property equality."""
        with self._lock:
            if type is not None:
                ids = list(self._nodes_by_type.get(type, set()))
            else:
                ids = list(self._nodes.keys())

        for node_id in ids:
            node = self._nodes.get(node_id)
            if node is None:
                continue
            if all(node.properties.get(k) == v for k, v in props.items()):
                yield node

    def edges_from(self, node_id: str, type: Optional[str] = None) -> Iterator[SymbolicEdge]:
        with self._lock:
            edge_ids = list(self._edges_from.get(node_id, set()))
        for eid in edge_ids:
            edge = self._edges.get(eid)
            if edge is None:
                continue
            if type is None or edge.type == type:
                yield edge

    def edges_to(self, node_id: str, type: Optional[str] = None) -> Iterator[SymbolicEdge]:
        with self._lock:
            edge_ids = list(self._edges_to.get(node_id, set()))
        for eid in edge_ids:
            edge = self._edges.get(eid)
            if edge is None:
                continue
            if type is None or edge.type == type:
                yield edge

    def neighbors(self, node_id: str, edge_type: Optional[str] = None) -> Iterator[SymbolicNode]:
        """Outgoing neighbors via edges from node_id."""
        for edge in self.edges_from(node_id, type=edge_type):
            target = self._nodes.get(edge.to_node)
            if target is not None:
                yield target

    def shortest_path(self, n1: str, n2: str, max_depth: int = 10) -> Optional[List[str]]:
        """BFS shortest path between two node ids (returns list of node ids or None)."""
        if n1 not in self._nodes or n2 not in self._nodes:
            return None
        if n1 == n2:
            return [n1]
        visited = {n1}
        queue: List[List[str]] = [[n1]]
        while queue:
            path = queue.pop(0)
            if len(path) > max_depth:
                continue
            for edge in self.edges_from(path[-1]):
                if edge.to_node == n2:
                    return path + [n2]
                if edge.to_node not in visited:
                    visited.add(edge.to_node)
                    queue.append(path + [edge.to_node])
        return None

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            by_node_type = {t: len(ids) for t, ids in self._nodes_by_type.items()}
            by_edge_type: Dict[str, int] = defaultdict(int)
            for edge in self._edges.values():
                by_edge_type[edge.type] += 1
        return {
            "nodes": len(self._nodes),
            "edges": len(self._edges),
            "by_node_type": by_node_type,
            "by_edge_type": dict(by_edge_type),
        }

    def save(self) -> None:
        """Atomic write — tmp file + rename."""
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                for node in self._nodes.values():
                    f.write(json.dumps(node.to_dict(), ensure_ascii=False) + "\n")
                for edge in self._edges.values():
                    f.write(json.dumps(edge.to_dict(), ensure_ascii=False) + "\n")
            os.replace(tmp_path, self._path)

    def load(self) -> int:
        """Load nodes + edges from JSONL. Returns count."""
        if not self._path.exists():
            return 0
        with self._lock:
            self.clear()
            count = 0
            with self._path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("[SymbolicGraph] skip malformed line")
                        continue
                    kind = d.get("_kind")
                    if kind == "node":
                        self.add_node(SymbolicNode.from_dict(d))
                        count += 1
                    elif kind == "edge":
                        self.add_edge(SymbolicEdge.from_dict(d))
                        count += 1
        return count
