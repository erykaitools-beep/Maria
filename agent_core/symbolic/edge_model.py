"""SymbolicEdge dataclass — directed edge in property graph."""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict


def _gen_edge_id() -> str:
    """Generate short edge id."""
    return f"edge-{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class SymbolicEdge:
    """Directed edge in symbolic property graph.

    derived_by traces provenance: "rule:<name>" for inference rules,
    "direct:<source>" for builder-derived, "manual" for ad-hoc.
    """

    edge_id: str = field(default_factory=_gen_edge_id)
    type: str = ""
    from_node: str = ""
    to_node: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    derived_by: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "type": self.type,
            "from_node": self.from_node,
            "to_node": self.to_node,
            "properties": dict(self.properties),
            "confidence": self.confidence,
            "derived_by": self.derived_by,
            "created_at": self.created_at,
            "_kind": "edge",
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "SymbolicEdge":
        return SymbolicEdge(
            edge_id=d.get("edge_id", _gen_edge_id()),
            type=d.get("type", ""),
            from_node=d.get("from_node", ""),
            to_node=d.get("to_node", ""),
            properties=dict(d.get("properties", {})),
            confidence=d.get("confidence", 1.0),
            derived_by=d.get("derived_by", ""),
            created_at=d.get("created_at", time.time()),
        )
