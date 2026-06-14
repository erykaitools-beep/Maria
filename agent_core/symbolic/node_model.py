"""SymbolicNode dataclass — node in property graph."""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


def _gen_node_id() -> str:
    """Generate short node id."""
    return f"node-{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class SymbolicNode:
    """Node in symbolic property graph.

    Properties dict is flexible (Q2 decision A) — type discriminator carried
    in `type` field. derived_from references source entity ("belief:<id>",
    "goal:<id>", "action:<id>", "synthetic").
    """

    node_id: str = field(default_factory=_gen_node_id)
    type: str = "synthetic"
    label: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)
    derived_from: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "type": self.type,
            "label": self.label,
            "properties": dict(self.properties),
            "derived_from": self.derived_from,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "_kind": "node",
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "SymbolicNode":
        return SymbolicNode(
            node_id=d.get("node_id", _gen_node_id()),
            type=d.get("type", "synthetic"),
            label=d.get("label", ""),
            properties=dict(d.get("properties", {})),
            derived_from=d.get("derived_from", ""),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
        )
