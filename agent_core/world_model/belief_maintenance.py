"""
Belief Maintenance - compaction, smart pruning, confidence decay, dedup.

Belief Store v2: batch maintenance operations for epistemological hygiene.
All functions operate on a BeliefStore instance as pure batch operations.

Kontrakt: docs/CONTRACTS.md - Kontrakt 6: World Model
ADR-013: Rule-based, zero LLM, deterministic
"""

import json
import logging
import math
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from agent_core.world_model.belief_model import Belief, BeliefType

logger = logging.getLogger(__name__)

# -- Confidence Decay Constants --

DECAY_HALF_LIVES = {
    BeliefType.FACT: 90.0,         # Facts decay slowly (exam-verified)
    BeliefType.OBSERVATION: 30.0,  # Observations decay at medium rate
    BeliefType.HYPOTHESIS: 14.0,   # Hypotheses decay fast
}

DECAY_FLOOR = 0.05          # Beliefs never fully vanish
DECAY_MIN_DELTA = 0.05      # Only revise if confidence changes by >= this
SECONDS_PER_DAY = 86400.0


# ═══════════════════════════════════════════════════════
# Compaction
# ═══════════════════════════════════════════════════════


def compact_jsonl(store) -> int:
    """
    Rewrite beliefs.jsonl with only current in-memory state.
    Removes all superseded and pruned records.

    Returns: number of records removed.
    """
    # Count before
    old_count = 0
    path = store._path
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                old_count = sum(1 for line in f if line.strip())
        except IOError:
            old_count = 0

    # Rewrite with only current beliefs
    _rewrite_jsonl(store)

    new_count = len(store._beliefs)
    removed = max(0, old_count - new_count)
    if removed > 0:
        logger.info(f"[BeliefStore] Compacted: {old_count} -> {new_count} records ({removed} removed)")
    return removed


def _rewrite_jsonl(store) -> None:
    """Rewrite JSONL from in-memory state."""
    path = store._path
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for belief in store._beliefs.values():
            f.write(json.dumps(belief.to_dict(), ensure_ascii=False) + "\n")
    store._dirty.clear()


# ═══════════════════════════════════════════════════════
# Smart Pruning
# ═══════════════════════════════════════════════════════


# Belief type importance: FACTs are harder to prune than HYPOTHESEs
_TYPE_IMPORTANCE = {
    BeliefType.FACT: 1.0,         # Exam-verified, highest value
    BeliefType.OBSERVATION: 0.6,  # Learned but not verified
    BeliefType.HYPOTHESIS: 0.3,   # Speculative, easy to prune
}

# Evidence strength bonus: beliefs with strong provenance are more valuable
_EVIDENCE_WEIGHT_THRESHOLD = 3  # beliefs with >= 3 evidence tuples get bonus


def compute_belief_score(
    belief: Belief,
    now: float,
    reference_counts: Dict[str, int],
    half_life_days: float = 30.0,
) -> float:
    """
    Multi-factor score for pruning priority.

    Higher = more valuable (keep longer).

    Factors:
    - 0.30 * confidence
    - 0.20 * freshness (exponential decay from updated_at)
    - 0.15 * revision factor (log-scaled)
    - 0.10 * reference factor (how many other beliefs reference this entity)
    - 0.15 * type importance (FACT > OBSERVATION > HYPOTHESIS)
    - 0.10 * evidence strength (beliefs with provenance are more valuable)

    Returns: float 0.0 to ~1.0
    """
    # Freshness: exponential decay
    age_days = max(0.0, (now - belief.updated_at) / SECONDS_PER_DAY)
    freshness = math.pow(0.5, age_days / max(half_life_days, 1.0))

    # Revision factor: log-scaled, capped at revision=20
    max_rev = 20
    revision_factor = min(1.0, math.log1p(belief.revision) / math.log1p(max_rev))

    # Reference factor: how many other beliefs reference this entity
    ref_count = reference_counts.get(belief.entity, 0)
    max_refs = 10
    reference_factor = min(1.0, ref_count / max(max_refs, 1))

    # Type importance: FACTs survive longer
    type_importance = _TYPE_IMPORTANCE.get(belief.belief_type, 0.5)

    # Evidence strength: beliefs with provenance are more valuable
    evidence_count = len(belief.evidence) if belief.evidence else 0
    evidence_factor = min(1.0, evidence_count / max(_EVIDENCE_WEIGHT_THRESHOLD, 1))

    score = (
        0.30 * belief.confidence
        + 0.20 * freshness
        + 0.15 * revision_factor
        + 0.10 * reference_factor
        + 0.15 * type_importance
        + 0.10 * evidence_factor
    )
    return round(score, 4)


def _count_references(beliefs: List[Belief]) -> Dict[str, int]:
    """Count how many beliefs reference each entity in related_entities."""
    counts: Dict[str, int] = defaultdict(int)
    for b in beliefs:
        for entity in b.related_entities:
            counts[entity] += 1
        # Also count tag-based references
        for tag in b.tags:
            counts[tag] += 1
    return dict(counts)


def smart_prune(store, cap: int = 2000) -> int:
    """
    Prune lowest-scored beliefs when over cap.
    Uses compute_belief_score() instead of confidence-only.

    Returns: number of beliefs pruned.
    """
    current = store.get_current()
    if len(current) <= cap:
        return 0

    now = time.time()
    ref_counts = _count_references(current)

    # Score all current beliefs
    scored = [
        (compute_belief_score(b, now, ref_counts), b)
        for b in current
    ]
    scored.sort(key=lambda x: x[0])

    # Prune lowest-scored
    to_prune = len(current) - cap
    pruned = 0
    for score, belief in scored[:to_prune]:
        # Mark as superseded with "pruned"
        from agent_core.world_model.belief_model import Belief as _B
        superseded = _B(
            belief_id=belief.belief_id,
            entity=belief.entity,
            entity_type=belief.entity_type,
            belief_type=belief.belief_type,
            content=belief.content,
            confidence=belief.confidence,
            source=belief.source,
            source_id=belief.source_id,
            tags=belief.tags,
            created_at=belief.created_at,
            updated_at=belief.updated_at,
            revision=belief.revision,
            superseded_by="pruned",
            related_entities=belief.related_entities,
            evidence=belief.evidence,
        )
        store._beliefs[belief.belief_id] = superseded
        store._dirty.add(belief.belief_id)
        pruned += 1

    if pruned > 0:
        logger.info(f"[BeliefStore] Smart-pruned {pruned} beliefs (cap={cap})")
    return pruned


# ═══════════════════════════════════════════════════════
# Confidence Decay
# ═══════════════════════════════════════════════════════


def compute_decayed_confidence(
    belief: Belief,
    now: float,
    half_lives: Optional[Dict[BeliefType, float]] = None,
) -> float:
    """
    Apply exponential decay to belief confidence.

    decayed = confidence * 2^(-age_days / half_life)

    Uses updated_at as anchor (last revision resets the clock).
    Minimum floor: DECAY_FLOOR (beliefs never fully vanish).
    """
    hl = (half_lives or DECAY_HALF_LIVES).get(
        belief.belief_type, 30.0
    )
    age_days = max(0.0, (now - belief.updated_at) / SECONDS_PER_DAY)
    decayed = belief.confidence * math.pow(0.5, age_days / max(hl, 1.0))
    return max(DECAY_FLOOR, round(decayed, 4))


def apply_decay(
    store,
    now: Optional[float] = None,
    half_lives: Optional[Dict[BeliefType, float]] = None,
    min_delta: float = DECAY_MIN_DELTA,
) -> int:
    """
    Apply confidence decay to all current beliefs.

    Only revises beliefs whose decayed confidence differs by >= min_delta
    from stored confidence (avoid churning on tiny changes).
    Idempotent: running twice quickly produces 0 revisions on second run.

    Returns: number of beliefs revised due to decay.
    """
    if now is None:
        now = time.time()

    current = store.get_current()
    revised = 0

    for belief in current:
        decayed = compute_decayed_confidence(belief, now, half_lives)
        delta = abs(belief.confidence - decayed)

        if delta >= min_delta:
            result = store.revise(belief.belief_id, decayed)
            if result:
                revised += 1

    if revised > 0:
        logger.info(f"[BeliefStore] Decay applied to {revised} beliefs")
    return revised


# ═══════════════════════════════════════════════════════
# Deduplication
# ═══════════════════════════════════════════════════════


def find_exact_duplicates(store) -> List[Tuple[str, str]]:
    """
    Find pairs of beliefs with identical entity + content (exact match).
    Deterministic, zero-LLM fallback for dedup.

    Returns: List of (keep_id, remove_id) pairs.
    Higher-confidence belief is kept.
    """
    current = store.get_current()

    # Group by (entity_type, entity, content_normalized)
    groups: Dict[tuple, List[Belief]] = defaultdict(list)
    for b in current:
        key = (b.entity_type.value, b.entity.lower().strip(), b.content.lower().strip()[:100])
        groups[key].append(b)

    pairs = []
    for key, beliefs in groups.items():
        if len(beliefs) < 2:
            continue
        # Sort by confidence desc, keep highest
        beliefs.sort(key=lambda b: b.confidence, reverse=True)
        keep = beliefs[0]
        for dup in beliefs[1:]:
            pairs.append((keep.belief_id, dup.belief_id))

    return pairs


def find_semantic_duplicates(
    store,
    semantic_memory,
    similarity_threshold: float = 0.85,
) -> List[Tuple[str, str, float]]:
    """
    Find pairs of beliefs with semantically similar content.
    Uses SemanticMemory search on the "beliefs" namespace.

    Returns: List of (keep_id, remove_id, similarity) sorted by similarity desc.
    """
    current = store.get_current()
    if not current or not semantic_memory:
        return []

    pairs = []
    seen_pairs = set()

    for belief in current:
        try:
            results = semantic_memory.search(
                belief.content, namespace="beliefs", top_k=3
            )
            for result in results:
                sim = result.get("score", 0.0)
                other_id = result.get("metadata", {}).get("belief_id", "")
                if (
                    sim >= similarity_threshold
                    and other_id
                    and other_id != belief.belief_id
                ):
                    pair_key = tuple(sorted([belief.belief_id, other_id]))
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        # Keep higher confidence
                        other = store.get(other_id)
                        if other and other.superseded_by is None:
                            if belief.confidence >= other.confidence:
                                pairs.append((belief.belief_id, other_id, sim))
                            else:
                                pairs.append((other_id, belief.belief_id, sim))
        except Exception:
            continue

    pairs.sort(key=lambda x: x[2], reverse=True)
    return pairs


def merge_duplicate_pair(store, keep_id: str, remove_id: str) -> bool:
    """
    Merge two duplicate beliefs: keep one, supersede the other.

    The kept belief gets:
    - max(confidence_a, confidence_b)
    - union of tags
    - union of related_entities (capped at 10)
    - merged evidence tuples
    - revision incremented

    Returns: True if merge succeeded.
    """
    keep = store.get(keep_id)
    remove = store.get(remove_id)
    if not keep or not remove:
        return False
    if keep.superseded_by is not None or remove.superseded_by is not None:
        return False

    # Merge metadata
    new_conf = max(keep.confidence, remove.confidence)
    merged_tags = tuple(sorted(set(keep.tags + remove.tags)))
    merged_entities = tuple(sorted(set(keep.related_entities + remove.related_entities)))[:10]

    # Merge evidence (dedup by source_ref)
    seen_refs = set()
    merged_ev = []
    for e in keep.evidence + remove.evidence:
        ref = e[1] if len(e) >= 2 else ""
        if ref not in seen_refs:
            seen_refs.add(ref)
            merged_ev.append(e)

    # Revise keep with merged data
    now = time.time()
    new_id = f"belief-{__import__('uuid').uuid4().hex[:12]}"

    revised = Belief(
        belief_id=new_id,
        entity=keep.entity,
        entity_type=keep.entity_type,
        belief_type=keep.belief_type,
        content=keep.content,
        confidence=max(0.0, min(1.0, new_conf)),
        source=keep.source,
        source_id=keep.source_id,
        tags=merged_tags,
        created_at=keep.created_at,
        updated_at=now,
        revision=keep.revision + 1,
        superseded_by=None,
        related_entities=merged_entities,
        evidence=tuple(merged_ev),
    )

    # Supersede both old beliefs
    for old_id in (keep_id, remove_id):
        old = store._beliefs.get(old_id)
        if old:
            sup = Belief(
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
            store._beliefs[old.belief_id] = sup
            store._dirty.add(old.belief_id)

    store.add(revised)
    return True


def deduplicate(
    store,
    semantic_memory=None,
    similarity_threshold: float = 0.85,
) -> int:
    """
    Full dedup pass: find duplicates and merge them.

    If semantic_memory is available, uses embedding similarity.
    Always runs exact matching as baseline.

    Returns: number of beliefs merged (removed).
    """
    merged = 0

    # Phase 1: exact duplicates (always runs)
    exact_pairs = find_exact_duplicates(store)
    for keep_id, remove_id in exact_pairs:
        if merge_duplicate_pair(store, keep_id, remove_id):
            merged += 1

    # Phase 2: semantic duplicates (optional)
    if semantic_memory:
        try:
            sem_pairs = find_semantic_duplicates(
                store, semantic_memory, similarity_threshold
            )
            for keep_id, remove_id, sim in sem_pairs:
                if merge_duplicate_pair(store, keep_id, remove_id):
                    merged += 1
        except Exception as e:
            logger.debug(f"Semantic dedup skipped: {e}")

    if merged > 0:
        logger.info(f"[BeliefStore] Deduplicated {merged} beliefs")
    return merged


# ═══════════════════════════════════════════════════════
# Full Maintenance Cycle
# ═══════════════════════════════════════════════════════


def run_maintenance(
    store,
    semantic_memory=None,
    cap: int = 2000,
) -> Dict[str, int]:
    """
    Run full maintenance cycle: decay -> dedup -> prune -> compact.
    Intended for SLEEP phase or periodic trigger.

    Returns: dict with counts per operation.
    """
    results = {}
    results["decayed"] = apply_decay(store)
    results["deduped"] = deduplicate(store, semantic_memory)
    results["pruned"] = smart_prune(store, cap)
    results["compacted"] = compact_jsonl(store)
    logger.info(f"[BeliefStore] Maintenance complete: {results}")
    return results
