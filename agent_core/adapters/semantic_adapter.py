"""
Semantic Graph Adapter

Bridges legacy maria_core.memory_engine.semantic.semantic_graph to agent_core.
The legacy SemanticGraph is a rich knowledge graph implementation.
This adapter integrates it with homeostasis and new memory architecture.

Legacy: maria_core/memory_engine/semantic/semantic_graph.py

Note: ADR-004 establishes JSONL as source of truth with graph as derived cache.
This adapter supports rebuilding from JSONL.
"""

import logging
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


class SemanticGraphAdapter:
    """
    Adapter that wraps legacy SemanticGraph for homeostasis integration.

    The legacy SemanticGraph:
    - Rich node/edge graph structure
    - Cosine similarity search with embeddings
    - BFS/DFS traversal
    - Contradiction detection
    - Consolidation (merge similar, prune low importance)
    - JSON serialization

    This adapter:
    - Provides rebuild_from_jsonl (ADR-004)
    - Tracks graph health metrics
    - Supports snapshot/recovery
    - Integrates with homeostasis event bus
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        use_legacy: bool = True,
    ):
        """
        Initialize adapter.

        Args:
            data_dir: Directory for persistence
            use_legacy: If True, wrap legacy SemanticGraph
        """
        self._data_dir = data_dir
        self._use_legacy = use_legacy
        self._legacy_graph = None
        self._stats_cache: Dict[str, Any] = {}

        if use_legacy:
            self._init_legacy()
        else:
            self._init_simple()

    def _init_legacy(self) -> None:
        """Initialize legacy SemanticGraph."""
        try:
            from maria_core.memory_engine.semantic.semantic_graph import SemanticGraph

            self._legacy_graph = SemanticGraph()
            logger.info("[Adapter] Legacy SemanticGraph initialized")

        except ImportError as e:
            logger.warning(f"[Adapter] Legacy SemanticGraph not available: {e}")
            self._use_legacy = False
            self._init_simple()

    def _init_simple(self) -> None:
        """Initialize simple in-memory graph."""
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._edges: List[Dict[str, Any]] = []
        self._next_node_id = 0

    # ==================== Node Operations ====================

    def add_node(
        self,
        node_id: str,
        content: str,
        node_type: str = "concept",
        **kwargs
    ) -> str:
        """
        Add node to graph.

        Args:
            node_id: Unique node identifier
            content: Node content/label
            node_type: Type of node
            **kwargs: Additional attributes

        Returns:
            Node ID
        """
        if self._use_legacy and self._legacy_graph:
            return self._legacy_graph.add_node(
                label=content,
                node_type=node_type,
                attributes=kwargs,
            )
        else:
            self._nodes[node_id] = {
                "id": node_id,
                "content": content,
                "type": node_type,
                **kwargs,
            }
            return node_id

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """
        Get node by ID.

        Args:
            node_id: Node identifier

        Returns:
            Node dict or None
        """
        if self._use_legacy and self._legacy_graph:
            return self._legacy_graph.nodes.get(node_id)
        else:
            return self._nodes.get(node_id)

    # ==================== Edge Operations ====================

    def add_edge(
        self,
        source: str,
        target: str,
        relation: str,
        **kwargs
    ) -> None:
        """
        Add edge between nodes.

        Args:
            source: Source node ID
            target: Target node ID
            relation: Relationship type
            **kwargs: Additional attributes
        """
        if self._use_legacy and self._legacy_graph:
            self._legacy_graph.add_edge(
                from_id=source,
                relation=relation,
                to_id=target,
                **kwargs,
            )
        else:
            self._edges.append({
                "source": source,
                "target": target,
                "relation": relation,
                **kwargs,
            })

    def get_edges(self, node_id: str) -> List[Dict[str, Any]]:
        """
        Get edges from a node.

        Args:
            node_id: Node identifier

        Returns:
            List of edge dicts
        """
        if self._use_legacy and self._legacy_graph:
            edges = []
            for (from_id, relation, to_id), edge in self._legacy_graph.edges.items():
                if from_id == node_id:
                    edges.append({
                        "source": from_id,
                        "target": to_id,
                        "relation": relation,
                        **edge,
                    })
            return edges
        else:
            return [e for e in self._edges if e["source"] == node_id]

    # ==================== Search Operations ====================

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Search nodes by content.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of matching nodes
        """
        if self._use_legacy and self._legacy_graph:
            # Use label index for search
            results = []
            query_lower = query.lower()

            for label, node_ids in self._legacy_graph.node_index_by_label.items():
                if query_lower in label.lower():
                    for node_id in node_ids:
                        results.append(self._legacy_graph.nodes[node_id])

            return results[:limit]
        else:
            results = []
            query_lower = query.lower()

            for node in self._nodes.values():
                content = node.get("content", "")
                if query_lower in content.lower():
                    results.append(node)

            return results[:limit]

    def query(
        self,
        start_node_id: str,
        max_depth: int = 2,
        allowed_relations: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Traverse graph from start node.

        Args:
            start_node_id: Starting node ID
            max_depth: Maximum traversal depth
            allowed_relations: Filter by relation types

        Returns:
            List of reachable nodes
        """
        if self._use_legacy and self._legacy_graph:
            return self._legacy_graph.query(
                start_node_id=start_node_id,
                max_depth=max_depth,
                allowed_relations=allowed_relations,
            )
        else:
            # Simple BFS for non-legacy
            visited = set()
            results = []
            queue = [(start_node_id, 0)]

            while queue:
                node_id, depth = queue.pop(0)

                if node_id in visited or depth > max_depth:
                    continue

                visited.add(node_id)

                if node_id != start_node_id and node_id in self._nodes:
                    results.append(self._nodes[node_id])

                for edge in self._edges:
                    if edge["source"] == node_id:
                        if allowed_relations and edge["relation"] not in allowed_relations:
                            continue
                        queue.append((edge["target"], depth + 1))

            return results

    # ==================== JSONL Integration (ADR-004) ====================

    def rebuild_from_jsonl(self, jsonl_path: Path) -> int:
        """
        Rebuild graph from JSONL source of truth.

        ADR-004: JSONL is source of truth, graph is derived cache.

        Args:
            jsonl_path: Path to JSONL file

        Returns:
            Number of records processed
        """
        if not jsonl_path.exists():
            logger.warning(f"[Adapter] JSONL file not found: {jsonl_path}")
            return 0

        count = 0

        # Clear existing data
        if self._use_legacy and self._legacy_graph:
            self._legacy_graph.nodes.clear()
            self._legacy_graph.edges.clear()
            self._legacy_graph.node_index_by_label.clear()
            self._legacy_graph.node_index_by_type.clear()
        else:
            self._nodes.clear()
            self._edges.clear()

        # Load from JSONL
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    record = json.loads(line)

                    # Extract node info
                    node_id = record.get("id", f"node_{count}")
                    content = record.get("content", record.get("label", ""))
                    node_type = record.get("type", "concept")

                    self.add_node(node_id, content, node_type)

                    # Extract relationships if present
                    if "related_to" in record:
                        related = record["related_to"]
                        if isinstance(related, str):
                            related = [related]
                        for target in related:
                            self.add_edge(node_id, target, "related_to")

                    count += 1

                except json.JSONDecodeError as e:
                    logger.warning(f"[Adapter] JSON error in JSONL: {e}")
                except Exception as e:
                    logger.warning(f"[Adapter] Error processing record: {e}")

        logger.info(f"[Adapter] Rebuilt graph from JSONL: {count} records")
        return count

    def save_to_jsonl(self, jsonl_path: Path) -> int:
        """
        Save graph to JSONL format.

        Args:
            jsonl_path: Output path

        Returns:
            Number of records saved
        """
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)

        count = 0

        with open(jsonl_path, 'w', encoding='utf-8') as f:
            # Get nodes
            if self._use_legacy and self._legacy_graph:
                nodes = self._legacy_graph.nodes.values()
            else:
                nodes = self._nodes.values()

            for node in nodes:
                # Find relationships for this node
                related = []
                if self._use_legacy and self._legacy_graph:
                    for (from_id, rel, to_id) in self._legacy_graph.edges.keys():
                        if from_id == node.get("id"):
                            related.append(to_id)
                else:
                    for edge in self._edges:
                        if edge["source"] == node.get("id"):
                            related.append(edge["target"])

                record = {
                    "id": node.get("id"),
                    "content": node.get("content", node.get("label", "")),
                    "type": node.get("type", "concept"),
                }

                if related:
                    record["related_to"] = related

                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1

        logger.info(f"[Adapter] Saved graph to JSONL: {count} records")
        return count

    # ==================== Statistics ====================

    def get_stats(self) -> Dict[str, Any]:
        """
        Get graph statistics.

        Returns:
            Statistics dictionary
        """
        if self._use_legacy and self._legacy_graph:
            return {
                "total_nodes": len(self._legacy_graph.nodes),
                "total_edges": len(self._legacy_graph.edges),
                "conflicts_detected": self._legacy_graph.stats.get("conflicts_detected", 0),
                "last_consolidation": (
                    self._legacy_graph.last_consolidation.isoformat()
                    if self._legacy_graph.last_consolidation else None
                ),
            }
        else:
            return {
                "total_nodes": len(self._nodes),
                "total_edges": len(self._edges),
                "conflicts_detected": 0,
                "last_consolidation": None,
            }

    # ==================== Maintenance ====================

    def consolidate(self) -> None:
        """
        Run graph consolidation (merge similar, prune low importance).
        """
        if self._use_legacy and self._legacy_graph:
            self._legacy_graph.consolidate()
            logger.info("[Adapter] Graph consolidated")

    def detect_contradictions(self) -> List[Dict[str, Any]]:
        """
        Detect contradictions in the graph.

        Returns:
            List of contradiction reports
        """
        if self._use_legacy and self._legacy_graph:
            return self._legacy_graph.detect_contradictions()
        else:
            return []  # Simple graph doesn't support contradiction detection

    # ==================== Serialization ====================

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        if self._use_legacy and self._legacy_graph:
            return self._legacy_graph.to_dict()
        else:
            return {
                "nodes": self._nodes,
                "edges": self._edges,
            }

    def save_to_json(self, filepath: Path) -> None:
        """Save to JSON file."""
        if self._use_legacy and self._legacy_graph:
            self._legacy_graph.save_to_json(str(filepath))
        else:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def load_from_json(self, filepath: Path) -> None:
        """Load from JSON file."""
        if self._use_legacy and self._legacy_graph:
            self._legacy_graph.load_from_json(str(filepath))
        else:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._nodes = data.get("nodes", {})
            self._edges = data.get("edges", [])


def get_adapted_semantic_graph(
    data_dir: Optional[Path] = None,
) -> SemanticGraphAdapter:
    """
    Get adapted semantic graph instance.

    Args:
        data_dir: Data directory

    Returns:
        SemanticGraphAdapter instance
    """
    return SemanticGraphAdapter(data_dir=data_dir)

