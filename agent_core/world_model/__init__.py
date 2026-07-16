"""
World Model (K6) for M.A.R.I.A.

Structured knowledge representation:
- Typed entities (topic, file, concept, person, place, module)
- Belief classification (fact, observation, hypothesis)
- Confidence tracking per belief with evidence provenance (v2)
- Belief revision on new evidence (exam results)
- v2: Compaction, smart pruning, confidence decay, dedup
- Queryable interface for Planner

Kontrakt: docs/CONTRACTS.md - Kontrakt 6: World Model
ADR-013: Rule-based, zero LLM, deterministic

Usage:
    from agent_core.world_model import WorldModel

    wm = WorldModel()
    wm.load()             # Load persisted beliefs
    wm.build()            # Build from existing JSONL sources
    gaps = wm.query.get_knowledge_gaps()
    wm.save()
"""

import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from agent_core.world_model.belief_model import (
    Belief, BeliefType, BeliefSource, EntityType, create_belief,
    STATUS_ACTIVE, STATUS_QUARANTINED, STATUS_RETRACTED,
)
from agent_core.world_model.belief_store import BeliefStore
from agent_core.world_model.belief_builder import BeliefBuilder
from agent_core.world_model.query import WorldModelQuery
from agent_core.world_model import retraction_log

logger = logging.getLogger(__name__)

# A soul-file write cannot be best-effort: the conscious-unlearn ops acquire the
# maintenance lock BLOCKING with this timeout (the adversarial review caught that
# maintain()'s non-blocking-skip pattern would silently DROP a retraction that
# raced a sleep pass). On timeout the op returns an explicit error, never a
# false "done".
_UNLEARN_LOCK_TIMEOUT = 30.0

# Default paths
_META_DIR = Path(__file__).resolve().parents[2] / "meta_data"
_MEMORY_DIR = Path(__file__).resolve().parents[2] / "memory"

_DEFAULT_BELIEFS_PATH = _META_DIR / "beliefs.jsonl"
_DEFAULT_KNOWLEDGE_INDEX_PATH = _MEMORY_DIR / "knowledge_index.jsonl"
_DEFAULT_LONGTERM_MEMORY_PATH = _MEMORY_DIR / "maria_longterm_memory.jsonl"
_DEFAULT_EXAM_RESULTS_PATH = _MEMORY_DIR / "exam_results.jsonl"
# Rollback/quarantine durable state (the conscious-unlearn ledger + the
# do-not-readd denylist that build_all consults so a retract never resurrects).
_DEFAULT_RETRACTIONS_PATH = _META_DIR / "retractions.jsonl"
_DEFAULT_DENYLIST_PATH = _META_DIR / "retraction_denylist.jsonl"


class WorldModel:
    """
    Main entry point for K6 World Model.

    Combines BeliefStore, BeliefBuilder, and WorldModelQuery
    into a single facade.
    """

    def __init__(
        self,
        beliefs_path: Optional[Path] = None,
        knowledge_index_path: Optional[Path] = None,
        longterm_memory_path: Optional[Path] = None,
        exam_results_path: Optional[Path] = None,
        retractions_path: Optional[Path] = None,
        denylist_path: Optional[Path] = None,
    ):
        self.store = BeliefStore(
            beliefs_path or _DEFAULT_BELIEFS_PATH,
        )
        # Conscious-unlearn durable state (rollback/quarantine).
        self._retractions_path = Path(retractions_path or _DEFAULT_RETRACTIONS_PATH)
        self._denylist_path = Path(denylist_path or _DEFAULT_DENYLIST_PATH)
        self.builder = BeliefBuilder(
            knowledge_index_path=knowledge_index_path or _DEFAULT_KNOWLEDGE_INDEX_PATH,
            longterm_memory_path=longterm_memory_path or _DEFAULT_LONGTERM_MEMORY_PATH,
            exam_results_path=exam_results_path or _DEFAULT_EXAM_RESULTS_PATH,
            denylist_path=self._denylist_path,
        )
        self.query = WorldModelQuery(self.store)
        # Serializes maintain() across its callers (PlannerCycle thread
        # post-EVALUATE, Telegram /beliefs maintain thread). The store is
        # lock-free, and with semantic dedup a maintenance pass went from
        # sub-second to potentially minutes -- two concurrent passes can
        # lose merges (compact() swaps the dict from a stale snapshot and
        # clears _dirty). Non-blocking: the loser skips, never queues.
        self._maintenance_lock = threading.Lock()
        # Optional handles for conscious-unlearn vector/cache consistency, wired
        # at daemon start (set_unlearn_handles). None in unit tests -> vector
        # eviction is skipped (the startup cleanup_stale_belief_vectors still
        # evicts a fully-quarantined entity's vector on the next boot).
        self._semantic_memory = None
        self._memory_query = None

    def load(self) -> int:
        """
        Load persisted beliefs from beliefs.jsonl.

        Returns:
            Number of current (non-superseded) beliefs loaded.
        """
        return self.store.load()

    def build(self, force: bool = False) -> Dict[str, int]:
        """
        Build/refresh beliefs from JSONL sources. Idempotent.

        Skipped entirely (zeros returned) when no source file changed
        since the last completed build; force=True overrides.

        Returns:
            Stats dict: {"topics": N, "files": M, "concepts": K}
        """
        return self.builder.build_all(self.store, force=force)

    def reconcile_trust(self) -> int:
        """Drop file beliefs whose file is no longer independently verified
        (self-healing trust gate, #2 2026-06-01) and persist on change.

        Cheap, idempotent, and safe to run on every startup after load() so the
        world model never keeps self-graded knowledge as canonical -- the
        runtime rebuild (build_all) does the same, but rebuilds only fire after
        learning activity, while a freshly-loaded store needs this once.

        Returns the number of beliefs pruned.
        """
        pruned = self.builder.prune_unverified_file_beliefs(self.store)
        if pruned:
            # compact() (full rewrite), NOT save() (append-only): drop_belief
            # removes from memory but the append log still has the record as
            # "current", so without a rewrite the pruned beliefs reload on the
            # next restart.
            self.store.compact()
        return pruned

    def scan_concept_trust(self) -> Dict[str, int]:
        """Read-only census of concept-FACT beliefs by exam independence
        (observe telemetry for the concept trust gate). Never mutates the
        store; returns {} when the exam data is missing/empty/untrustworthy.
        See BeliefBuilder.scan_concept_trust for the guard rationale.
        """
        return self.builder.scan_concept_trust(self.store)

    def process_exam_result(self, exam_record: Dict[str, Any]) -> int:
        """
        Update beliefs based on exam outcome.

        Returns:
            Count of revised beliefs.
        """
        return self.builder.update_from_exam(self.store, exam_record)

    def save(self) -> None:
        """Persist current beliefs to beliefs.jsonl."""
        self.store.save()

    def stats(self) -> Dict[str, Any]:
        """Summary stats."""
        return self.store.stats()

    # -- v2: Maintenance operations --

    def compact(self) -> int:
        """Compact beliefs.jsonl by removing superseded records."""
        from agent_core.world_model.belief_maintenance import compact_jsonl
        return compact_jsonl(self.store)

    def apply_decay(self) -> int:
        """Apply confidence decay to stale beliefs."""
        from agent_core.world_model.belief_maintenance import apply_decay
        return apply_decay(self.store)

    def deduplicate(self, semantic_memory=None) -> int:
        """Remove duplicate beliefs via exact + semantic similarity."""
        from agent_core.world_model.belief_maintenance import deduplicate
        return deduplicate(self.store, semantic_memory)

    def maintain(self, semantic_memory=None) -> Dict[str, int]:
        """
        Run full maintenance cycle: decay -> dedup -> prune -> compact.
        Intended for SLEEP phase or periodic trigger.

        Returns {"skipped": "maintenance_in_progress"} when another thread
        is already maintaining (see _maintenance_lock comment in __init__).
        """
        if not self._maintenance_lock.acquire(blocking=False):
            logger.info("[WorldModel] maintain() skipped: already running")
            return {"skipped": "maintenance_in_progress"}
        try:
            from agent_core.world_model.belief_maintenance import run_maintenance
            return run_maintenance(self.store, semantic_memory)
        finally:
            self._maintenance_lock.release()

    # -- Conscious unlearn: operator-driven retract / quarantine ----
    # The operator-MANUAL ops below are gated by their caller's authority
    # (master-only Telegram/Skrzynka), NOT by RETRACTION_ENABLED -- the flag
    # gates only the future AUTONOMOUS path (faithfulness-CONTRADICTED ->
    # auto-quarantine), which is deliberately not wired yet (post-observe, like
    # SYNTH_ENABLED). Every op acquires the maintenance lock BLOCKING, mutates
    # in place, writes the durable retractions.jsonl ledger, evicts the vector,
    # and (for retract/forget_source) appends the source/entity denylist so the
    # next build_all never resurrects it.

    def set_unlearn_handles(self, semantic_memory=None, memory_query=None) -> None:
        """Wire the LIVE semantic memory + memory query (daemon start) so
        retraction evicts vectors and invalidates the in-process query cache
        immediately. Pass the shared instances, never fresh ones."""
        self._semantic_memory = semantic_memory
        self._memory_query = memory_query

    def _resolve_targets(self, target: str):
        """Resolve a target string to current active beliefs: an exact
        belief_id first, else every active belief for that entity."""
        b = self.store.get(target)
        if b is not None and b.superseded_by is None and b.status == STATUS_ACTIVE:
            return [b]
        # Quarantined-by-id (e.g. unquarantine/retract of a hidden belief).
        if b is not None and b.superseded_by is None:
            return [b]
        return self.store.get_by_entity(target)

    def _evict_vector(self, entity: str) -> None:
        """Evict the entity's belief vector, but ONLY when no active belief
        remains for it (one vector per entity backs all its beliefs)."""
        if self._semantic_memory is None:
            return
        if self.store.get_by_entity(entity):
            return  # an active belief still backs this entity -> keep the vector
        try:
            from agent_core.semantic.indexer import make_belief_entry_id
            if self._semantic_memory.remove(make_belief_entry_id(entity)):
                self._semantic_memory.save()
        except Exception as exc:  # vector consistency is best-effort
            logger.warning("[Unlearn] vector evict failed for %s: %s", entity, exc)

    def _readd_vector(self, entity: str) -> None:
        """Re-embed the entity vector from the CURRENT highest-confidence active
        belief (not the just-unquarantined one -- one entity, one shared vector,
        last-writer-wins content)."""
        if self._semantic_memory is None:
            return
        actives = self.store.get_by_entity(entity)
        if not actives:
            return
        winner = max(actives, key=lambda b: b.confidence)
        text = winner.content if winner.content else entity
        if winner.tags:
            text += f" (tagi: {', '.join(list(winner.tags)[:5])})"
        try:
            from agent_core.semantic.indexer import make_belief_entry_id
            self._semantic_memory.index_text(
                "beliefs", make_belief_entry_id(entity), text, {"entity": entity})
            self._semantic_memory.save()
        except Exception as exc:
            logger.warning("[Unlearn] vector re-add failed for %s: %s", entity, exc)

    def _invalidate_query_cache(self) -> None:
        if self._memory_query is not None:
            try:
                self._memory_query._invalidate_cache()
            except Exception:
                pass

    def _run_unlearn(self, op: str, targets, reason: str, actor: str,
                     actor_detail: str, source_scope=None,
                     denylist_writes=None) -> Dict[str, Any]:
        """Apply a conscious-unlearn op to the resolved targets under the
        maintenance lock, write the ledger, evict/restore vectors, persist, and
        invalidate the query cache. Returns a result dict."""
        from agent_core.tracing import current_episode_id

        if not targets:
            return {"ok": False, "op": op, "count": 0,
                    "message": "no matching current belief"}

        if not self._maintenance_lock.acquire(timeout=_UNLEARN_LOCK_TIMEOUT):
            return {"ok": False, "op": op, "count": 0,
                    "message": "belief layer busy (maintenance), retry"}
        try:
            episode_id = current_episode_id()
            per_target = []
            entities_touched = []
            for b in list(targets):
                if op == retraction_log.OP_QUARANTINE:
                    new = self.store.quarantine(b.belief_id, reason, actor, actor_detail, episode_id)
                elif op == retraction_log.OP_RETRACT:
                    new = self.store.retract(b.belief_id, reason, actor, actor_detail, episode_id)
                elif op == retraction_log.OP_UNQUARANTINE:
                    new = self.store.unquarantine(b.belief_id, actor, actor_detail, episode_id)
                else:
                    new = None
                if new is None:
                    continue
                per_target.append({
                    "belief_id": new.belief_id,
                    "entity": new.entity,
                    "belief_type": b.belief_type.value,
                    "confidence": b.confidence,
                    "source_id": b.source_id,
                })
                entities_touched.append(new.entity)

            if not per_target:
                return {"ok": False, "op": op, "count": 0,
                        "message": "targets not eligible (already in that state?)"}

            # Denylist writes (resurrection guard) for retract/forget_source.
            for scope, value in (denylist_writes or []):
                retraction_log.append_denylist_entry(
                    self._denylist_path, scope, value, reason=reason, active=True)

            # Persist beliefs (append -> a fresh MemoryQuery reads the new state;
            # crash durability is covered by reapply_pending_retractions on boot).
            self.store.save()

            # Vector consistency.
            for entity in set(entities_touched):
                if op == retraction_log.OP_UNQUARANTINE:
                    self._readd_vector(entity)
                else:
                    self._evict_vector(entity)
            self._invalidate_query_cache()

            record = {
                "retraction_id": retraction_log.new_retraction_id(),
                "op": op,
                "actor": actor,
                "actor_detail": actor_detail,
                "reason": reason,
                "mode": "manual",
                "target_entities": sorted(set(entities_touched)),
                "target_belief_ids": [pt["belief_id"] for pt in per_target],
                "per_target": per_target,
                "source_scope": source_scope,
                "episode_id": episode_id,
                "count": len(per_target),
            }
            retraction_log.append_retraction(self._retractions_path, record)
            return {"ok": True, "op": op, "count": len(per_target),
                    "retraction_id": record["retraction_id"],
                    "entities": record["target_entities"],
                    "belief_ids": record["target_belief_ids"],
                    "message": f"{op}: {len(per_target)} belief(s)"}
        finally:
            self._maintenance_lock.release()

    def quarantine_belief(self, target: str, reason: str = "", actor: str = "operator",
                          actor_detail: str = "") -> Dict[str, Any]:
        """Reversible soft-hide of a belief (by id or entity)."""
        return self._run_unlearn(
            retraction_log.OP_QUARANTINE, self._resolve_targets(target),
            reason, actor, actor_detail,
            source_scope={"kind": "by_id_or_entity", "value": target})

    def retract_belief(self, target: str, reason: str = "", actor: str = "operator",
                       actor_detail: str = "") -> Dict[str, Any]:
        """Audited removal of a belief (by id or entity). Denylists the entity
        so the next build_all never re-mints it."""
        targets = self._resolve_targets(target)
        denylist = [(retraction_log.SCOPE_ENTITY, b.entity) for b in targets]
        return self._run_unlearn(
            retraction_log.OP_RETRACT, targets, reason, actor, actor_detail,
            source_scope={"kind": "by_id_or_entity", "value": target},
            denylist_writes=denylist)

    def unquarantine_belief(self, target: str, actor: str = "operator",
                            actor_detail: str = "") -> Dict[str, Any]:
        """Restore a quarantined belief (by id or entity)."""
        # Resolve includes quarantined-by-id; for by-entity, find quarantined.
        b = self.store.get(target)
        if b is not None and b.status == STATUS_QUARANTINED:
            targets = [b]
        else:
            targets = [x for x in self.store._beliefs.values()
                       if x.entity == target and x.superseded_by is None
                       and x.status == STATUS_QUARANTINED]
        result = self._run_unlearn(
            retraction_log.OP_UNQUARANTINE, targets, "", actor, actor_detail,
            source_scope={"kind": "by_id_or_entity", "value": target})
        # Lift any entity denylist so a rebuild can re-mint (symmetry).
        if result.get("ok"):
            for entity in result.get("entities", []):
                retraction_log.append_denylist_entry(
                    self._denylist_path, retraction_log.SCOPE_ENTITY, entity,
                    reason="unquarantine", active=False)
        return result

    def forget_source(self, source_value: str, reason: str = "",
                      actor: str = "operator", actor_detail: str = "") -> Dict[str, Any]:
        """Root-and-branch: retract every belief derived from a file_id/
        synthesis_id AND denylist the source so build_all never re-creates them.
        The real hook for pulling a flagged-bad synthesis. By-source bulk is
        atomic -- NOT subject to the future auto-path per-run cap. The source is
        denylisted even when no live belief currently matches, so a source that
        rebuilds later still never re-mints."""
        targets = self.store.get_current_by_source(source_value)
        scope = {"kind": "by_source", "value": source_value}
        if not targets:
            # Denylist-only: no live beliefs to retract, but the durable guard
            # still arms so a future build_all never creates them.
            from agent_core.tracing import current_episode_id
            retraction_log.append_denylist_entry(
                self._denylist_path, retraction_log.SCOPE_SOURCE, source_value,
                reason=reason, active=True)
            record = {
                "retraction_id": retraction_log.new_retraction_id(),
                "op": retraction_log.OP_RETRACT, "actor": actor,
                "actor_detail": actor_detail, "reason": reason, "mode": "manual",
                "target_entities": [], "target_belief_ids": [], "per_target": [],
                "source_scope": scope, "episode_id": current_episode_id(), "count": 0,
            }
            retraction_log.append_retraction(self._retractions_path, record)
            return {"ok": True, "op": retraction_log.OP_RETRACT, "count": 0,
                    "source_denylisted": True,
                    "retraction_id": record["retraction_id"],
                    "message": f"source {source_value} denylisted (0 live beliefs)"}
        return self._run_unlearn(
            retraction_log.OP_RETRACT, targets, reason, actor, actor_detail,
            source_scope=scope,
            denylist_writes=[(retraction_log.SCOPE_SOURCE, source_value)])

    def list_retractions(self, limit: int = 20):
        """Read the retraction ledger (newest first) for operator review."""
        return retraction_log.read_retractions(self._retractions_path, limit=limit)

    def census_unlearn(self) -> Dict[str, Any]:
        """Read-only integrity census (mirrors scan_concept_trust): lifecycle
        counts + DESYNC detection. A desync = an ACTIVE belief whose entity or
        source is on the denylist -- the build gate should have blocked it, so a
        non-zero count means the resurrection guard half-failed (e.g. a belief
        minted before the denylist, or a gate bypass). Never mutates."""
        by_status = self.store.stats().get("by_status", {})
        denylist = retraction_log.load_denylist(self._denylist_path)
        denied_entities = denylist.get("entity", set())
        denied_sources = denylist.get("source", set())
        desync = []
        if denied_entities:
            for b in self.store.get_current():  # active only
                if b.entity in denied_entities:
                    desync.append({"belief_id": b.belief_id, "entity": b.entity,
                                   "scope": "entity"})
        for src in denied_sources:
            for b in self.store.get_current_by_source(src):
                desync.append({"belief_id": b.belief_id, "entity": b.entity,
                               "scope": "source", "source": src})
        return {
            "by_status": by_status,
            "denylist_sources": len(denied_sources),
            "denylist_entities": len(denied_entities),
            "desync_count": len(desync),
            "desync": desync[:20],
        }

    def reapply_pending_retractions(self) -> int:
        """Boot guard: re-apply any retraction whose target entity still shows
        an active belief on disk (a crash between the in-memory flip and save()
        would otherwise leave it active, and the next build_all could re-mint).
        Resolves by entity (stable) since belief_id churns. Returns the count
        re-applied."""
        rows = retraction_log.read_retractions(self._retractions_path, limit=100000)
        if not rows:
            return 0
        # Net latest op per entity (rows are newest-first).
        latest = {}
        for row in rows:
            op = row.get("op")
            for entity in row.get("target_entities", []):
                if entity not in latest:
                    latest[entity] = (op, row.get("reason", ""), row.get("actor", "auto"))
        reapplied = 0
        for entity, (op, reason, actor) in latest.items():
            if op not in (retraction_log.OP_QUARANTINE, retraction_log.OP_RETRACT):
                continue  # unquarantine is the latest -> belief should be active
            for b in self.store.get_by_entity(entity):  # active beliefs only
                if op == retraction_log.OP_QUARANTINE:
                    if self.store.quarantine(b.belief_id, reason, actor, "boot-replay"):
                        reapplied += 1
                else:
                    if self.store.retract(b.belief_id, reason, actor, "boot-replay"):
                        reapplied += 1
        if reapplied:
            self.store.save()
            logger.info("[Unlearn] boot replay re-applied %d retraction(s)", reapplied)
        return reapplied
