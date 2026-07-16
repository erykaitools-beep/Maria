"""
Belief Model - dataclasses for World Model (K6).

Typed entities, belief classification, confidence tracking.
Frozen dataclasses (like PerceptionEvent).

v2: Evidence tracking - beliefs carry provenance evidence tuples.

Kontrakt: docs/CONTRACTS.md - Kontrakt 6: World Model
ADR-013: Rule-based, zero LLM, deterministic
"""

import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class EntityType(Enum):
    """Type of entity in the world model."""
    TOPIC = "topic"        # Knowledge topic (from tags)
    FILE = "file"          # Learning file (from knowledge_index)
    CONCEPT = "concept"    # Concept/term (from memory_facts)
    MODULE = "module"      # Maria internal module
    PERSON = "person"      # Person (from memory_facts)
    PLACE = "place"        # Place (from memory_facts)


class BeliefType(Enum):
    """Classification of a belief."""
    FACT = "fact"                 # Verified by exam (score >= 0.7)
    OBSERVATION = "observation"  # Learned but not verified
    HYPOTHESIS = "hypothesis"    # Inferred from related data


class BeliefSource(Enum):
    """Where this belief came from."""
    LEARNING = "learning"        # learning_agent output
    EXAM = "exam"                # exam_results confirmation
    MEMORY_FACT = "memory_fact"  # memory_facts triples
    SYSTEM = "system"            # System-generated
    USER = "user"                # User-provided


# Belief lifecycle statuses (rollback/quarantine, 2026-06-14). "active" is the
# ONLY visible state: every consumer read-filter requires status == STATUS_ACTIVE
# (single source of truth for "visible = active"). A missing status key on an
# old record means active (backward compatible). quarantined = reversible
# soft-hide; retracted = audited removal kept on disk as a tombstone-with-reason.
STATUS_ACTIVE = "active"
STATUS_QUARANTINED = "quarantined"
STATUS_RETRACTED = "retracted"


@dataclass(frozen=True)
class Belief:
    """
    A single belief in the world model.

    Frozen - beliefs are immutable once created.
    Updated beliefs create new records (MERGE semantics on belief_id).
    """
    belief_id: str
    entity: str                    # What this is about (normalized label)
    entity_type: EntityType
    belief_type: BeliefType
    content: str                   # Human-readable statement
    confidence: float              # 0.0 to 1.0
    source: BeliefSource
    source_id: str                 # Specific source (file_id, exam_id)
    tags: Tuple[str, ...]          # Related tags (tuple for hashability)
    created_at: float
    updated_at: float
    revision: int                  # Revision counter (MERGE semantics)
    superseded_by: Optional[str]   # belief_id of newer version
    related_entities: Tuple[str, ...]
    evidence: Tuple[Tuple[str, str, float], ...] = ()  # v2: (source_type, source_ref, weight)
    # v3 (rollback/quarantine, 2026-06-14): conscious-unlearn lifecycle.
    # status="active" is the normal state; "quarantined" = reversible soft-hide
    # (invisible to every consumer, vector evicted, kept on disk + in audit);
    # "retracted" = audited removal (confidence forced 0.0, kept CURRENT so
    # compact() preserves it as a tombstone-with-reason). A non-active record
    # keeps superseded_by=None so it survives compaction. Old records load as
    # "active" (backward-compatible). retraction = {reason, actor, actor_detail,
    # ts, prev_status, prev_belief_type, prev_confidence, episode_id} or None.
    status: str = "active"
    retraction: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSONL storage."""
        d = {
            "belief_id": self.belief_id,
            "entity": self.entity,
            "entity_type": self.entity_type.value,
            "belief_type": self.belief_type.value,
            "content": self.content,
            "confidence": self.confidence,
            "source": self.source.value,
            "source_id": self.source_id,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "revision": self.revision,
            "superseded_by": self.superseded_by,
            "related_entities": list(self.related_entities),
        }
        if self.evidence:
            d["evidence"] = [list(e) for e in self.evidence]
        # Emit lifecycle fields only when non-default (mirrors evidence) so
        # the on-disk shape is unchanged for the active common case.
        if self.status != "active":
            d["status"] = self.status
        if self.retraction is not None:
            d["retraction"] = self.retraction
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Belief":
        """Deserialize from dict. Backward-compatible (evidence defaults to empty)."""
        # v2: parse evidence tuples, fallback to empty for old records
        raw_evidence = d.get("evidence", [])
        evidence = tuple(
            tuple(e) for e in raw_evidence
            if isinstance(e, (list, tuple)) and len(e) >= 3
        )
        return Belief(
            belief_id=d["belief_id"],
            entity=d["entity"],
            entity_type=EntityType(d["entity_type"]),
            belief_type=BeliefType(d["belief_type"]),
            content=d["content"],
            confidence=d["confidence"],
            source=BeliefSource(d["source"]),
            source_id=d.get("source_id", ""),
            tags=tuple(d.get("tags", [])),
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
            revision=d.get("revision", 1),
            superseded_by=d.get("superseded_by"),
            related_entities=tuple(d.get("related_entities", [])),
            evidence=evidence,
            status=d.get("status", "active"),
            retraction=d.get("retraction"),
        )


def create_belief(
    entity: str,
    entity_type: EntityType,
    belief_type: BeliefType,
    content: str,
    confidence: float,
    source: BeliefSource,
    source_id: str = "",
    tags: Optional[List[str]] = None,
    related_entities: Optional[List[str]] = None,
    belief_id: Optional[str] = None,
    revision: int = 1,
    evidence: Optional[List[Tuple[str, str, float]]] = None,
) -> Belief:
    """Factory function for creating a Belief."""
    now = time.time()
    return Belief(
        belief_id=belief_id or f"belief-{uuid.uuid4().hex[:12]}",
        entity=entity,
        entity_type=entity_type,
        belief_type=belief_type,
        content=content,
        confidence=max(0.0, min(1.0, confidence)),
        source=source,
        source_id=source_id,
        tags=tuple(tags or []),
        created_at=now,
        updated_at=now,
        revision=revision,
        superseded_by=None,
        related_entities=tuple(related_entities or []),
        evidence=tuple(evidence or []),
    )
