"""
BeliefStore - JSONL persistence with MERGE semantics.

Storage: meta_data/beliefs.jsonl (append-only, last record per belief_id wins).
In-memory: Dict[belief_id, Belief] + indexes by entity, entity_type, tags.

Pattern: GoalStore (goals/store.py) + FetchRegistry MERGE semantics.
Kontrakt: docs/CONTRACTS.md - Kontrakt 6: World Model
"""

import dataclasses
import json
import logging
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.world_model.belief_model import (
    Belief, BeliefType, BeliefSource, EntityType, create_belief,
    STATUS_ACTIVE, STATUS_QUARANTINED, STATUS_RETRACTED,
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
        self._bulk_mode: bool = False  # when True, defer _enforce_cap to end of batch

        # Indexes (rebuilt on load and maintained on add)
        # Ordered-set semantics via dict (Py3.7+ preserves insertion order),
        # giving O(1) add/remove/membership. Keys are belief_ids, values are
        # always None. Lists here made add()/drop_belief() O(bucket) -> O(n^2)
        # across a full build/prune: the _by_entity_type buckets hold tens of
        # thousands of ids each (2026-07-13).
        self._by_entity: Dict[str, Dict[str, None]] = defaultdict(dict)
        self._by_entity_type: Dict[EntityType, Dict[str, None]] = defaultdict(dict)
        self._by_tag: Dict[str, Dict[str, None]] = defaultdict(dict)

    @contextmanager
    def bulk_mode(self):
        """Defer cap enforcement during mass inserts (BeliefBuilder.build_all).

        Without this, each add() triggers _enforce_cap() — O(n) per call on
        current beliefs. For a fresh build of ~22k concepts, that's O(n²)
        and hangs for minutes. With bulk_mode enabled, cap enforcement runs
        exactly once on exit.
        """
        prev = self._bulk_mode
        self._bulk_mode = True
        try:
            yield
        finally:
            self._bulk_mode = prev
            # Run cap enforcement once, after the whole batch
            self._enforce_cap()

    def load(self) -> int:
        """
        Load beliefs from JSONL with MERGE semantics.

        Pruned records (superseded_by == "pruned") are skipped on load — they
        are forgotten beliefs with no referential value. Revised records
        (superseded_by == <new_id>) are kept for history chain continuity.

        Returns:
            Number of current (non-superseded) beliefs loaded.
        """
        self._beliefs.clear()
        self._dirty.clear()

        if not self._path.exists():
            self._rebuild_indexes()
            return 0

        skipped_pruned = 0
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("superseded_by") == "pruned":
                            skipped_pruned += 1
                            continue
                        belief = Belief.from_dict(data)
                        self._beliefs[belief.belief_id] = belief
                    except (json.JSONDecodeError, KeyError, ValueError):
                        continue
        except IOError as e:
            logger.warning(f"Could not load beliefs: {e}")

        self._rebuild_indexes()
        current = [b for b in self._beliefs.values() if b.superseded_by is None]

        # Auto-compact if the file is bloated with pruned records.
        # Triggers on recovery from bug where prune tombstones were never
        # cleaned up. Threshold: 10x more pruned than active → compact now.
        if skipped_pruned > max(10 * len(current), 1000):
            logger.info(
                f"[BeliefStore] load: {skipped_pruned} pruned records in file "
                f"vs {len(current)} active — auto-compacting"
            )
            self.compact()
        elif skipped_pruned:
            logger.info(
                f"[BeliefStore] load: skipped {skipped_pruned} pruned records"
            )

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
            self._compact_if_needed()
        except IOError as e:
            logger.warning(f"Could not save beliefs: {e}")

    def add(self, belief: Belief) -> None:
        """Add a belief to the store.

        When bulk_mode() is active, _enforce_cap is deferred to the end
        of the batch (context manager exit) to avoid O(n²) behavior.
        """
        self._beliefs[belief.belief_id] = belief
        self._dirty.add(belief.belief_id)
        self._index_belief(belief)
        if not self._bulk_mode:
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
            # Carry the lifecycle forward: a revise/decay of a quarantined or
            # retracted belief must NOT silently mint a fresh active record
            # (resurrection). The new current version keeps the prior status.
            status=old.status,
            retraction=old.retraction,
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
            status=old.status,
            retraction=old.retraction,
        )

        self._beliefs[old.belief_id] = superseded
        self._dirty.add(old.belief_id)

        self.add(revised)
        return revised

    # -- Conscious unlearn: quarantine / retract / unquarantine ----
    # SAME belief_id in-place status flip (NOT a superseded chain): the record
    # stays CURRENT (superseded_by=None) so compact() PRESERVES it as the
    # on-disk audit, and there is no unstable-id churn. Callers should resolve a
    # belief by entity (the stable key) first; belief_id churns on revise/decay.

    def _lifecycle_snapshot(self, old: Belief, reason: str, actor: str,
                            actor_detail: str, episode_id: str) -> Dict[str, Any]:
        """Build the retraction audit payload, snapshotting the prior state so
        unquarantine can restore it."""
        return {
            "reason": reason,
            "actor": actor,
            "actor_detail": actor_detail,
            "ts": time.time(),
            "episode_id": episode_id,
            "prev_status": old.status,
            "prev_belief_type": old.belief_type.value,
            "prev_confidence": old.confidence,
        }

    def quarantine(self, belief_id: str, reason: str = "", actor: str = "operator",
                   actor_detail: str = "", episode_id: str = "") -> Optional[Belief]:
        """Reversible soft-hide. Guards status == active. Returns the new
        record (same belief_id, status=quarantined) or None if not eligible."""
        old = self._beliefs.get(belief_id)
        if old is None or old.superseded_by is not None or old.status != STATUS_ACTIVE:
            return None
        new = dataclasses.replace(
            old,
            status=STATUS_QUARANTINED,
            retraction=self._lifecycle_snapshot(old, reason, actor, actor_detail, episode_id),
            updated_at=time.time(),
            revision=old.revision + 1,
        )
        self._beliefs[belief_id] = new
        self._dirty.add(belief_id)
        return new

    def retract(self, belief_id: str, reason: str = "", actor: str = "operator",
                actor_detail: str = "", episode_id: str = "") -> Optional[Belief]:
        """Audited removal. Confidence forced to 0.0; kept CURRENT
        (superseded_by=None) so compaction preserves it as a tombstone-with-
        reason. Guards status in {active, quarantined}. Returns the new record
        or None if already retracted / not found."""
        old = self._beliefs.get(belief_id)
        if old is None or old.superseded_by is not None or old.status == STATUS_RETRACTED:
            return None
        new = dataclasses.replace(
            old,
            status=STATUS_RETRACTED,
            confidence=0.0,
            retraction=self._lifecycle_snapshot(old, reason, actor, actor_detail, episode_id),
            updated_at=time.time(),
            revision=old.revision + 1,
        )
        self._beliefs[belief_id] = new
        self._dirty.add(belief_id)
        return new

    def unquarantine(self, belief_id: str, actor: str = "operator",
                     actor_detail: str = "", episode_id: str = "") -> Optional[Belief]:
        """Restore a quarantined belief to its prior status/type/confidence.
        Guards status == quarantined. Returns the restored record or None."""
        old = self._beliefs.get(belief_id)
        if old is None or old.status != STATUS_QUARANTINED:
            return None
        ret = old.retraction or {}
        prev_status = ret.get("prev_status", STATUS_ACTIVE)
        prev_conf = ret.get("prev_confidence", old.confidence)
        try:
            prev_type = (BeliefType(ret["prev_belief_type"])
                         if ret.get("prev_belief_type") else old.belief_type)
        except (ValueError, KeyError):
            prev_type = old.belief_type
        new = dataclasses.replace(
            old,
            status=prev_status,
            belief_type=prev_type,
            confidence=prev_conf,
            retraction=None,
            updated_at=time.time(),
            revision=old.revision + 1,
        )
        self._beliefs[belief_id] = new
        self._dirty.add(belief_id)
        return new

    def get_current_by_source(self, value: str) -> List[Belief]:
        """Current beliefs derived from a file_id/synthesis_id, for by-source
        ops (/forget_source). Matches the file belief (entity == value or
        source_id == file:value) and concept beliefs whose source_id encodes it
        (concept:value:i). Topic beliefs are cross-file aggregates and are
        intentionally NOT matched -- one bad source must not retract a whole
        topic."""
        matches = []
        for b in self.get_current():
            sid = b.source_id or ""
            if (b.entity == value
                    or sid == f"file:{value}"
                    or sid.startswith(f"concept:{value}:")):
                matches.append(b)
        return matches

    def get(self, belief_id: str) -> Optional[Belief]:
        """Get belief by ID."""
        return self._beliefs.get(belief_id)

    def get_by_entity(self, entity: str) -> List[Belief]:
        """Get current beliefs for an entity."""
        ids = self._by_entity.get(entity, [])
        return [self._beliefs[bid] for bid in ids
                if bid in self._beliefs and self._beliefs[bid].superseded_by is None
                and self._beliefs[bid].status == STATUS_ACTIVE]

    def get_by_entity_type(self, entity_type: EntityType) -> List[Belief]:
        """Get current beliefs of a given entity type."""
        ids = self._by_entity_type.get(entity_type, [])
        return [self._beliefs[bid] for bid in ids
                if bid in self._beliefs and self._beliefs[bid].superseded_by is None
                and self._beliefs[bid].status == STATUS_ACTIVE]

    def get_by_tag(self, tag: str) -> List[Belief]:
        """Get current beliefs with a given tag."""
        ids = self._by_tag.get(tag, [])
        return [self._beliefs[bid] for bid in ids
                if bid in self._beliefs and self._beliefs[bid].superseded_by is None
                and self._beliefs[bid].status == STATUS_ACTIVE]

    def get_current(self) -> List[Belief]:
        """Get all non-superseded, active beliefs.

        Quarantined/retracted beliefs are non-active and excluded here -- so
        every consumer of get_current() (planner, decay, smart_prune, dedup,
        stats) automatically stops seeing a soft-hidden/retracted belief
        without each caller needing its own status guard.
        """
        return [b for b in self._beliefs.values()
                if b.superseded_by is None and b.status == STATUS_ACTIVE]

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

        # Lifecycle census over the non-superseded view (current + the
        # quarantined/retracted records get_current() now hides) -- free
        # operator visibility into how many beliefs are soft-hidden/retracted.
        by_status = defaultdict(int)
        for b in self._beliefs.values():
            if b.superseded_by is None:
                by_status[b.status] += 1

        return {
            "total": len(current),
            "total_all": len(self._beliefs),
            "by_belief_type": dict(by_type),
            "by_entity_type": dict(by_entity_type),
            "by_status": dict(by_status),
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
        """Add a belief to all indexes.

        Buckets are dict-backed ordered sets, so assignment is idempotent and
        O(1) -- no membership scan needed. The old ``bid not in list`` guard
        was O(bucket): with a few huge _by_entity_type buckets it turned a
        full build into O(n^2) (54k inserts -> ~7s of pure list scans).
        """
        bid = belief.belief_id
        self._by_entity[belief.entity][bid] = None
        self._by_entity_type[belief.entity_type][bid] = None
        for tag in belief.tags:
            self._by_tag[tag][bid] = None

    def compact(self) -> int:
        """Rewrite beliefs.jsonl to only non-superseded beliefs.

        Drops all records with superseded_by set (both "pruned" tombstones
        and revised-chain markers). Only the current, active view of the
        world survives compaction — both on disk and in memory. This
        prevents the JSONL and the in-memory dict from growing unboundedly
        as prune cycles accumulate tombstones.
        """
        if not self._path.exists():
            # Even without a file, shrink memory to current.
            keep_mem = {bid: b for bid, b in self._beliefs.items() if b.superseded_by is None}
            if len(keep_mem) < len(self._beliefs):
                self._beliefs = keep_mem
                self._rebuild_indexes()
                self._dirty.intersection_update(self._beliefs)
            return 0

        line_count = self._count_nonempty_lines()
        keep = [b for b in self._beliefs.values() if b.superseded_by is None]
        if line_count == 0 and not keep:
            return 0

        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                for belief in keep:
                    f.write(json.dumps(belief.to_dict(), ensure_ascii=False) + "\n")
            tmp_path.replace(self._path)
            # Shrink memory to match disk — drop tombstones entirely.
            self._beliefs = {b.belief_id: b for b in keep}
            self._rebuild_indexes()
            # All beliefs are now persisted; nothing is dirty.
            self._dirty.clear()
            return max(0, line_count - len(keep))
        except IOError as e:
            logger.warning(f"Could not compact beliefs: {e}")
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            return 0

    def _count_nonempty_lines(self) -> int:
        if not self._path.exists():
            return 0
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except IOError as e:
            logger.warning(f"Could not inspect beliefs: {e}")
            return 0

    def _compact_if_needed(self) -> None:
        keep = sum(1 for b in self._beliefs.values() if b.superseded_by is None)
        if keep == 0:
            return
        if self._count_nonempty_lines() > (2 * keep):
            self.compact()

    def drop_belief(self, belief_id: str) -> bool:
        """Remove a belief from memory and indexes.

        Used by prune paths (smart_prune, fallback) to forget beliefs
        without leaving tombstones in self._beliefs. The JSONL file
        retains historical append records until compact() runs.

        Returns True if removed, False if not present.
        """
        b = self._beliefs.pop(belief_id, None)
        if b is None:
            return False

        for idx, key in (
            (self._by_entity, b.entity),
            (self._by_entity_type, b.entity_type),
        ):
            bucket = idx.get(key)
            if bucket is not None:
                bucket.pop(belief_id, None)  # O(1) dict-backed ordered set
                if not bucket:
                    del idx[key]
        for tag in b.tags:
            bucket = self._by_tag.get(tag)
            if bucket is not None:
                bucket.pop(belief_id, None)
                if not bucket:
                    del self._by_tag[tag]

        self._dirty.discard(belief_id)
        return True

    def _enforce_cap(self) -> None:
        """Prune lowest-scored beliefs if over cap. v2: uses smart_prune.

        Pruned beliefs are DROPPED from memory (not kept as tombstones).
        After pruning, compact() is called to rewrite the JSONL without
        the dropped records — otherwise they would be loaded back on
        next restart (append-only file still has them as "current").
        """
        current = self.get_current()
        if len(current) <= MAX_CURRENT_BELIEFS:
            return
        pruned = 0
        try:
            from agent_core.world_model.belief_maintenance import smart_prune
            pruned = smart_prune(self, cap=MAX_CURRENT_BELIEFS)
        except Exception:
            # Fallback to naive pruning if maintenance module unavailable
            current.sort(key=lambda b: b.confidence)
            excess = len(current) - MAX_CURRENT_BELIEFS
            for b in current[:excess]:
                if self.drop_belief(b.belief_id):
                    pruned += 1
        if pruned > 0:
            self.compact()
