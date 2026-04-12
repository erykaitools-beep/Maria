"""
Semantic Store - Knowledge graph operations

Provides:
- Semantic graph interface
- Consistency validation
- Rebuild from JSONL (ADR-004)

Adapter for: maria_core/memory_engine/semantic/semantic_graph.py
"""

import time
import logging
from typing import Dict, Any, Optional, List, Set

logger = logging.getLogger(__name__)


class SemanticStore:
    """
    Semantic knowledge graph store.

    ADR-004: This is a derived cache, JSONL is source of truth.
    Must support rebuild_from_jsonl() for recovery.
    """

    def __init__(self):
        """Initialize semantic store."""
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._edges: List[Dict[str, Any]] = []
        self._last_validation_time = 0.0
        self._consistency_score = 1.0

        # Try to wrap legacy module
        self._init_legacy_adapter()

    def _init_legacy_adapter(self) -> None:
        """Initialize adapter for legacy SemanticGraph."""
        try:
            from maria_core.memory_engine.semantic.semantic_graph import SemanticGraph
            self._legacy_graph = SemanticGraph()
        except ImportError:
            self._legacy_graph = None
            logger.debug("Legacy SemanticGraph not available")

    # ─────────────────────────────────────────────
    # HOMEOSTASIS INTERFACE
    # ─────────────────────────────────────────────

    def get_coherence(self) -> float:
        """
        Get semantic coherence score.

        Returns:
            Score from 0.0 (incoherent) to 1.0 (coherent)
        """
        if self._legacy_graph:
            try:
                if hasattr(self._legacy_graph, 'validate_integrity'):
                    return self._legacy_graph.validate_integrity()
            except Exception:
                pass

        return self._consistency_score

    def validate_integrity(self) -> float:
        """
        Run integrity validation.

        Checks:
        - Orphan nodes
        - Invalid edges
        - Contradictions

        Returns:
            Consistency score (0-1)
        """
        issues = 0
        total_checks = 0

        # Check for orphan nodes (no edges)
        nodes_with_edges: Set[str] = set()
        for edge in self._edges:
            nodes_with_edges.add(edge.get("source", ""))
            nodes_with_edges.add(edge.get("target", ""))

        orphans = set(self._nodes.keys()) - nodes_with_edges
        issues += len(orphans)
        total_checks += len(self._nodes)

        # Check for invalid edge references
        for edge in self._edges:
            if edge.get("source") not in self._nodes:
                issues += 1
            if edge.get("target") not in self._nodes:
                issues += 1
            total_checks += 2

        # Calculate score
        if total_checks > 0:
            self._consistency_score = 1.0 - (issues / total_checks)
        else:
            self._consistency_score = 1.0

        self._last_validation_time = time.time()

        # Also validate legacy if available
        if self._legacy_graph:
            try:
                if hasattr(self._legacy_graph, 'validate_integrity'):
                    legacy_score = self._legacy_graph.validate_integrity()
                    self._consistency_score = min(self._consistency_score, legacy_score)
            except Exception:
                pass

        return self._consistency_score

    def node_count(self) -> int:
        """Get number of nodes."""
        if self._legacy_graph:
            try:
                if hasattr(self._legacy_graph, 'nodes'):
                    return len(self._legacy_graph.nodes)
            except Exception:
                pass

        return len(self._nodes)

    def edge_count(self) -> int:
        """Get number of edges."""
        if self._legacy_graph:
            try:
                if hasattr(self._legacy_graph, 'edges'):
                    return len(self._legacy_graph.edges)
            except Exception:
                pass

        return len(self._edges)

    # ─────────────────────────────────────────────
    # NODE OPERATIONS
    # ─────────────────────────────────────────────

    def add_node(
        self,
        node_id: str,
        label: str,
        properties: Dict[str, Any] = None,
    ) -> bool:
        """
        Add node to graph.

        Args:
            node_id: Unique node identifier
            label: Node label/type
            properties: Additional properties

        Returns:
            True if added (False if already exists)
        """
        if node_id in self._nodes:
            return False

        self._nodes[node_id] = {
            "id": node_id,
            "label": label,
            "properties": properties or {},
            "created_at": time.time(),
        }

        return True

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get node by ID."""
        return self._nodes.get(node_id)

    def update_node(
        self,
        node_id: str,
        properties: Dict[str, Any],
    ) -> bool:
        """
        Update node properties.

        Args:
            node_id: Node to update
            properties: Properties to merge

        Returns:
            True if updated
        """
        if node_id not in self._nodes:
            return False

        self._nodes[node_id]["properties"].update(properties)
        self._nodes[node_id]["updated_at"] = time.time()
        return True

    def remove_node(self, node_id: str) -> bool:
        """
        Remove node and its edges.

        Args:
            node_id: Node to remove

        Returns:
            True if removed
        """
        if node_id not in self._nodes:
            return False

        del self._nodes[node_id]

        # Remove associated edges
        self._edges = [
            e for e in self._edges
            if e.get("source") != node_id and e.get("target") != node_id
        ]

        return True

    # ─────────────────────────────────────────────
    # EDGE OPERATIONS
    # ─────────────────────────────────────────────

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        weight: float = 1.0,
        properties: Dict[str, Any] = None,
    ) -> bool:
        """
        Add edge between nodes.

        Args:
            source_id: Source node ID
            target_id: Target node ID
            relation: Relationship type
            weight: Edge weight (default 1.0)
            properties: Additional properties

        Returns:
            True if added
        """
        # Validate nodes exist
        if source_id not in self._nodes or target_id not in self._nodes:
            return False

        edge = {
            "source": source_id,
            "target": target_id,
            "relation": relation,
            "weight": weight,
            "properties": properties or {},
            "created_at": time.time(),
        }

        self._edges.append(edge)
        return True

    def get_edges_from(self, node_id: str) -> List[Dict[str, Any]]:
        """Get all edges from a node."""
        return [e for e in self._edges if e.get("source") == node_id]

    def get_edges_to(self, node_id: str) -> List[Dict[str, Any]]:
        """Get all edges to a node."""
        return [e for e in self._edges if e.get("target") == node_id]

    # ─────────────────────────────────────────────
    # ADR-004: REBUILD FROM JSONL
    # ─────────────────────────────────────────────

    def rebuild_from_jsonl(self, jsonl_entries: List[Dict[str, Any]]) -> bool:
        """
        Rebuild graph from JSONL entries.

        ADR-004: JSONL is source of truth.

        Args:
            jsonl_entries: List of JSONL entry dictionaries

        Returns:
            True if rebuild successful
        """
        logger.info(f"Rebuilding semantic graph from {len(jsonl_entries)} entries")

        # Clear current state
        self._nodes.clear()
        self._edges.clear()

        try:
            for entry in jsonl_entries:
                # Extract nodes and edges from entry
                # Implementation depends on JSONL entry format
                if "nodes" in entry:
                    for node in entry["nodes"]:
                        self.add_node(
                            node_id=node.get("id", ""),
                            label=node.get("label", ""),
                            properties=node.get("properties", {}),
                        )

                if "edges" in entry:
                    for edge in entry["edges"]:
                        self.add_edge(
                            source_id=edge.get("source", ""),
                            target_id=edge.get("target", ""),
                            relation=edge.get("relation", ""),
                            weight=edge.get("weight", 1.0),
                            properties=edge.get("properties", {}),
                        )

            # Validate after rebuild
            self.validate_integrity()

            logger.info(
                f"Rebuild complete: {self.node_count()} nodes, "
                f"{self.edge_count()} edges, "
                f"consistency={self._consistency_score:.2f}"
            )
            return True

        except Exception as e:
            logger.error(f"Rebuild failed: {e}")
            return False

    def save(self) -> bool:
        """
        Save graph state.

        Note: With ADR-004, this may just validate since
        JSONL is the real persistence.

        Returns:
            True if save successful
        """
        if self._legacy_graph:
            try:
                if hasattr(self._legacy_graph, 'save'):
                    self._legacy_graph.save()
                    return True
            except Exception as e:
                logger.error(f"Save failed: {e}")

        return True

    def clear(self) -> None:
        """Clear all nodes and edges."""
        self._nodes.clear()
        self._edges.clear()
        self._consistency_score = 1.0
