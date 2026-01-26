# memory/node.py

import uuid
from typing import Any, List, Dict, Optional
from datetime import datetime

class Node:
    """
    Węzeł w grafie semantycznym.
    Reprezentuje pojęcie, fakt lub koncepcję.
    """

    def __init__(
        self,
        label: str,
        node_type: str = "entity",
        attributes: Optional[Dict[str, Any]] = None,
        embedding: Optional[List[float]] = None,
        confidence: float = 1.0,
        source: str = "unknown"
    ):
        self.id = f"node:{uuid.uuid4().hex[:8]}"
        self.label = label
        self.type = node_type  # entity, concept, fact, rule, event
        self.attributes = attributes or {}
        self.embedding = embedding  # Wektor semantyczny
        self.confidence = confidence  # [0.0, 1.0]
        self.source = source  # "inferred", "external", "feedback", "auto"

        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.access_count = 0
        self.importance = 0.5

        # Meta-informacje
        self.is_outdated = False
        self.superseded_by = None  # ID węzła, który go zastąpił

    def update_metadata(self, confidence=None, importance=None):
        """Aktualizuj metadata węzła"""
        self.updated_at = datetime.now()
        if confidence is not None:
            self.confidence = max(0.0, min(1.0, confidence))
        if importance is not None:
            self.importance = max(0.0, min(1.0, importance))

    def increment_access(self):
        """Increment licznika dostępu (boost dla consolidation)"""
        self.access_count += 1
        self.update_metadata(confidence=min(1.0, self.confidence + 0.01))

    def to_dict(self):
        """Serializacja do JSON"""
        return {
            "id": self.id,
            "label": self.label,
            "type": self.type,
            "attributes": self.attributes,
            "confidence": self.confidence,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "access_count": self.access_count,
            "importance": self.importance,
            "is_outdated": self.is_outdated
        }

    def __repr__(self):
        return f"Node({self.label}|type={self.type}|conf={self.confidence:.2f}|imp={self.importance:.2f})"


class Edge:
    """
    Krawędź w grafie semantycznym.
    Łączy dwa węzły z semantyczną relacją.
    """

    def __init__(
        self,
        from_node_id: str,
        relation: str,
        to_node_id: str,
        weight: float = 1.0,
        confidence: float = 1.0,
        source: str = "unknown",
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.id = f"edge:{uuid.uuid4().hex[:8]}"
        self.from_id = from_node_id
        self.relation = relation  # "isTypeOf", "locatedIn", "causes", etc.
        self.to_id = to_node_id
        self.weight = weight  # Siła relacji
        self.confidence = confidence  # Ufność w relację
        self.source = source
        self.metadata = metadata or {}

        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.access_count = 0

    def increment_weight(self, delta=0.1):
        """Wzmocnij relację"""
        self.weight = min(2.0, self.weight + delta)
        self.updated_at = datetime.now()

    def to_dict(self):
        return {
            "id": self.id,
            "from": self.from_id,
            "relation": self.relation,
            "to": self.to_id,
            "weight": self.weight,
            "confidence": self.confidence,
            "source": self.source
        }

    def __repr__(self):
        return f"Edge({self.from_id} —{self.relation}→ {self.to_id}|w={self.weight:.2f})"
