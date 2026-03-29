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

    def load(self) -> int:
        """
        Load persisted beliefs from beliefs.jsonl.

        Returns:
            Number of current (non-superseded) beliefs loaded.
        """
        return self.store.load()

    def build(self) -> Dict[str, int]:
        """
        Build/refresh beliefs from JSONL sources. Idempotent.

        Returns:
            Stats dict: {"topics": N, "files": M, "concepts": K}
        """
        return self.builder.build_all(self.store)

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
        """
        from agent_core.world_model.belief_maintenance import run_maintenance
        return run_maintenance(self.store, semantic_memory)
