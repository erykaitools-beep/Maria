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
)
from agent_core.world_model.belief_store import BeliefStore
from agent_core.world_model.belief_builder import BeliefBuilder
from agent_core.world_model.query import WorldModelQuery

logger = logging.getLogger(__name__)

# Default paths
_META_DIR = Path(__file__).resolve().parents[2] / "meta_data"
_MEMORY_DIR = Path(__file__).resolve().parents[2] / "memory"

_DEFAULT_BELIEFS_PATH = _META_DIR / "beliefs.jsonl"
_DEFAULT_KNOWLEDGE_INDEX_PATH = _MEMORY_DIR / "knowledge_index.jsonl"
_DEFAULT_LONGTERM_MEMORY_PATH = _MEMORY_DIR / "maria_longterm_memory.jsonl"
_DEFAULT_EXAM_RESULTS_PATH = _MEMORY_DIR / "exam_results.jsonl"


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
    ):
        self.store = BeliefStore(
            beliefs_path or _DEFAULT_BELIEFS_PATH,
        )
        self.builder = BeliefBuilder(
            knowledge_index_path=knowledge_index_path or _DEFAULT_KNOWLEDGE_INDEX_PATH,
            longterm_memory_path=longterm_memory_path or _DEFAULT_LONGTERM_MEMORY_PATH,
            exam_results_path=exam_results_path or _DEFAULT_EXAM_RESULTS_PATH,
        )
        self.query = WorldModelQuery(self.store)
        # Serializes maintain() across its callers (PlannerCycle thread
        # post-EVALUATE, Telegram /beliefs maintain thread). The store is
        # lock-free, and with semantic dedup a maintenance pass went from
        # sub-second to potentially minutes -- two concurrent passes can
        # lose merges (compact() swaps the dict from a stale snapshot and
        # clears _dirty). Non-blocking: the loser skips, never queues.
        self._maintenance_lock = threading.Lock()

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
