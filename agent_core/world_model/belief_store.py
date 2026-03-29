"""
BeliefStore - JSONL persistence with MERGE semantics.

Storage: meta_data/beliefs.jsonl (append-only, last record per belief_id wins).
In-memory: Dict[belief_id, Belief] + indexes by entity, entity_type, tags.

Pattern: GoalStore (goals/store.py) + FetchRegistry MERGE semantics.
Kontrakt: docs/CONTRACTS.md - Kontrakt 6: World Model
"""

import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.world_model.belief_model import (
    Belief, BeliefType, BeliefSource, EntityType, create_belief,
)

logger = logging.getLogger(__name__)

# Prevent unbounded growth
MAX_CURRENT_BELIEFS = 2000


class BeliefStore:
    """
    Persistent belief storage with in-memory indexes.

    MERGE semantics: on load, last record per belief_id wins.
    Append-only writes to JSONL.
    """

    def __init__(self, beliefs_path: Path):
        self._path = Path(beliefs_path)
        self._beliefs: Dict[str, Belief] = {}
        self._dirty: set = set()  # belief_ids needing save

        # Indexes (rebuilt on load and maintained on add)
        self._by_entity: Dict[str, List[str]] = defaultdict(list)
        self._by_entity_type: Dict[EntityType, List[str]] = defaultdict(list)
        self._by_tag: Dict[str, List[str]] = defaultdict(list)

    def load(self) -> int:
        """
        Load beliefs from JSONL with MERGE semantics.

        Returns:
            Number of current (non-superseded) beliefs loaded.
        """
        self._beliefs.clear()
        self._dirty.clear()

        if not self._path.exists():
            self._rebuild_indexes()
            return 0

        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        belief = Belief.from_dict(data)
                        self._beliefs[belief.belief_id] = belief
                    except (json.JSONDecodeError, KeyError, ValueError):
                        continue
        except IOError as e:
            logger.warning(f"Could not load beliefs: {e}")

        self._rebuild_indexes()
        current = [b for b in self._beliefs.values() if b.superseded_by is None]
        return len(current)

    def save(self) -> None:
        """Append dirty (new/updated) beliefs to JSONL."""
        if not self._dirty:
            return

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                for bid in self._dirty:
                    belief = self._beliefs.get(bid)
                    if belief:
                        f.write(json.dumps(belief.to_dict(), ensure_ascii=False) + "\n")
            self._dirty.clear()
        except IOError as e:
            logger.warning(f"Could not save beliefs: {e}")

    def add(self, belief: Belief) -> None:
        """Add a belief to the store."""
        self._beliefs[belief.belief_id] = belief
        self._dirty.add(belief.belief_id)
        self._index_belief(belief)
        self._enforce_cap()

    def revise(
        self,
        belief_id: str,
        new_confidence: float,
        new_belief_type: Optional[BeliefType] = None,
        new_evidence: Optional[list] = None,
    ) -> Optional[Belief]:
        """
        Create a revised version of an existing belief.

        The old belief gets superseded_by pointing to the new one.
        v2: optionally merge new evidence with existing.

        Returns:
            New revised Belief, or None if original not found.
        """
        old = self._beliefs.get(belief_id)
        if old is None or old.superseded_by is not None:
            return None

        now = time.time()
        new_id = f"belief-{__import__('uuid').uuid4().hex[:12]}"

        # v2: merge evidence (old + new, deduped by source_ref)
        merged_evidence = old.evidence
        if new_evidence:
            seen_refs = {e[1] for e in old.evidence if len(e) >= 2}
            extra = tuple(
                tuple(e) for e in new_evidence
                if len(e) >= 3 and e[1] not in seen_refs
            )
            merged_evidence = old.evidence + extra

        # Create revised belief
        revised = Belief(
            belief_id=new_id,
            entity=old.entity,
            entity_type=old.entity_type,
            belief_type=new_belief_type or old.belief_type,
            content=old.content,
            confidence=max(0.0, min(1.0, new_confidence)),
            source=old.source,
            source_id=old.source_id,
            tags=old.tags,
            created_at=old.created_at,
            updated_at=now,
            revision=old.revision + 1,
            superseded_by=None,
            related_entities=old.related_entities,
            evidence=merged_evidence,
        )

        # Mark old as superseded
        superseded = Belief(
            belief_id=old.belief_id,
            entity=old.entity,
            entity_type=old.entity_type,
            belief_type=old.belief_type,
            content=old.content,
            confidence=old.confidence,
            source=old.source,
            source_id=old.source_id,
            tags=old.tags,
            created_at=old.created_at,
            updated_at=now,
            revision=old.revision,
            superseded_by=new_id,
            related_entities=old.related_entities,
            evidence=old.evidence,
        )

        self._beliefs[old.belief_id] = superseded
        self._dirty.add(old.belief_id)

        self.add(revised)
        return revised

    def get(self, belief_id: str) -> Optional[Belief]:
        """Get belief by ID."""
        return self._beliefs.get(belief_id)

    def get_by_entity(self, entity: str) -> List[Belief]:
        """Get current beliefs for an entity."""
        ids = self._by_entity.get(entity, [])
        return [self._beliefs[bid] for bid in ids
                if bid in self._beliefs and self._beliefs[bid].superseded_by is None]

    def get_by_entity_type(self, entity_type: EntityType) -> List[Belief]:
        """Get current beliefs of a given entity type."""
        ids = self._by_entity_type.get(entity_type, [])
        return [self._beliefs[bid] for bid in ids
                if bid in self._beliefs and self._beliefs[bid].superseded_by is None]

    def get_by_tag(self, tag: str) -> List[Belief]:
        """Get current beliefs with a given tag."""
        ids = self._by_tag.get(tag, [])
        return [self._beliefs[bid] for bid in ids
                if bid in self._beliefs and self._beliefs[bid].superseded_by is None]

    def get_current(self) -> List[Belief]:
        """Get all non-superseded beliefs."""
        return [b for b in self._beliefs.values() if b.superseded_by is None]

    def find_by_entity_and_source(
        self, entity: str, source_id: str
    ) -> Optional[Belief]:
        """Find current belief by entity + source_id (for dedup)."""
        for b in self.get_by_entity(entity):
            if b.source_id == source_id and b.superseded_by is None:
                return b
        return None

    def stats(self) -> Dict[str, Any]:
        """Summary statistics."""
        current = self.get_current()
        by_type = defaultdict(int)
        by_entity_type = defaultdict(int)
        total_confidence = 0.0

        for b in current:
            by_type[b.belief_type.value] += 1
            by_entity_type[b.entity_type.value] += 1
            total_confidence += b.confidence

        return {
            "total": len(current),
            "total_all": len(self._beliefs),
            "by_belief_type": dict(by_type),
            "by_entity_type": dict(by_entity_type),
            "avg_confidence": round(total_confidence / len(current), 3) if current else 0.0,
        }

    # -- Internal ------------------------------------------------

    def _rebuild_indexes(self) -> None:
        """Rebuild all indexes from scratch."""
        self._by_entity.clear()
        self._by_entity_type.clear()
        self._by_tag.clear()

        for belief in self._beliefs.values():
            self._index_belief(belief)

    def _index_belief(self, belief: Belief) -> None:
        """Add a belief to all indexes."""
        bid = belief.belief_id
        if bid not in self._by_entity.get(belief.entity, []):
            self._by_entity[belief.entity].append(bid)
        if bid not in self._by_entity_type.get(belief.entity_type, []):
            self._by_entity_type[belief.entity_type].append(bid)
        for tag in belief.tags:
            if bid not in self._by_tag.get(tag, []):
                self._by_tag[tag].append(bid)

    def compact(self) -> int:
        """Compact beliefs.jsonl by removing superseded records. v2."""
        from agent_core.world_model.belief_maintenance import compact_jsonl
        return compact_jsonl(self)

    def _enforce_cap(self) -> None:
        """Prune lowest-scored beliefs if over cap. v2: uses smart_prune."""
        current = self.get_current()
        if len(current) <= MAX_CURRENT_BELIEFS:
            return
        try:
            from agent_core.world_model.belief_maintenance import smart_prune
            smart_prune(self, cap=MAX_CURRENT_BELIEFS)
        except Exception:
            # Fallback to naive pruning if maintenance module unavailable
            current.sort(key=lambda b: b.confidence)
            excess = len(current) - MAX_CURRENT_BELIEFS
            for b in current[:excess]:
                superseded = Belief(
                    belief_id=b.belief_id,
                    entity=b.entity,
                    entity_type=b.entity_type,
                    belief_type=b.belief_type,
                    content=b.content,
                    confidence=b.confidence,
                    source=b.source,
                    source_id=b.source_id,
                    tags=b.tags,
                    created_at=b.created_at,
                    updated_at=time.time(),
                    revision=b.revision,
                    superseded_by="pruned",
                    related_entities=b.related_entities,
                    evidence=b.evidence,
                )
                self._beliefs[b.belief_id] = superseded
                self._dirty.add(b.belief_id)
