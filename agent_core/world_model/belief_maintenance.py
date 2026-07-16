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
import re
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
    Rewrite beliefs.jsonl with only non-superseded beliefs.
    Drops all tombstones (superseded_by set) from disk.

    Delegates to BeliefStore.compact() when available: that path is ATOMIC
    (tmp file + os.replace -- a crash mid-rewrite cannot truncate the live
    beliefs.jsonl) and also drops tombstones from MEMORY, so stats() stops
    counting revision-chain ghosts. The manual fallback below remains for
    duck-typed stores without compact() (tests) and is atomic as well.

    Edge note: store.compact() does NOT create the file when it never
    existed (unsaved store) -- beliefs simply stay dirty until the next
    save(). Production stores always have the file (load()/build()+save()
    at startup), so this only shows up in tests.

    Returns: number of records removed.
    """
    compact = getattr(store, "compact", None)
    if callable(compact):
        removed = compact()
        if removed > 0:
            logger.info(
                f"[BeliefStore] Compacted via store.compact(): "
                f"{removed} records removed"
            )
        return removed

    # Fallback: count before
    old_count = 0
    path = store._path
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                old_count = sum(1 for line in f if line.strip())
        except IOError:
            old_count = 0

    # Rewrite with only current beliefs (drops tombstones)
    _rewrite_jsonl(store)

    new_count = sum(
        1 for b in store._beliefs.values() if b.superseded_by is None
    )
    removed = max(0, old_count - new_count)
    if removed > 0:
        logger.info(f"[BeliefStore] Compacted: {old_count} -> {new_count} records ({removed} removed)")
    return removed


def _rewrite_jsonl(store) -> None:
    """Rewrite JSONL from in-memory state, excluding superseded records.

    Atomic: writes to a tmp file then os.replace()s it over the live path,
    so a crash mid-rewrite can never truncate beliefs.jsonl (the soul file).
    Mirrors BeliefStore.compact(); kept only as the duck-typed fallback.
    """
    path = store._path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        for belief in store._beliefs.values():
            if belief.superseded_by is not None:
                continue
            f.write(json.dumps(belief.to_dict(), ensure_ascii=False) + "\n")
    tmp_path.replace(path)
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

    # Prune lowest-scored: drop from memory entirely (no tombstones).
    # JSONL retains the historical records until the next compact().
    to_prune = len(current) - cap
    pruned = 0
    for score, belief in scored[:to_prune]:
        if store.drop_belief(belief.belief_id):
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


_DIGIT_RUNS = re.compile(r"\d+")


def _is_template_pair(a, b) -> bool:
    """
    True when the two contents collapse to the SAME text once each
    belief's own entity is removed and digit runs are normalized --
    builder-style stat records ("Temat 'X' wystepuje w N plikach",
    "Plik 'Y' opanowany (score Z%)") where the entity IS the record
    identity, so embedding similarity measures the shared template, not
    duplicate knowledge. All 5 pairs in the first live OBSERVE batch
    (2026-06-11) were these; merging would have deleted real records.

    Both entities must actually occur in their own content: when they do
    not, equal signatures mean the contents are genuinely near-identical
    -- a real duplicate, which this guard must NOT block.
    """
    if not a.entity or not b.entity:
        return False
    if a.entity not in a.content or b.entity not in b.content:
        return False
    sig_a = _DIGIT_RUNS.sub("#", a.content.replace(a.entity, "\x00"))
    sig_b = _DIGIT_RUNS.sub("#", b.content.replace(b.entity, "\x00"))
    return sig_a == sig_b


def find_semantic_duplicates(
    store,
    semantic_memory,
    similarity_threshold: float = 0.95,
    scan_limit: Optional[int] = None,
) -> List[Tuple[str, str, float]]:
    """
    Find pairs of beliefs with semantically similar content.
    Uses SemanticMemory search on the "beliefs" namespace.

    Hit resolution goes via metadata["entity"] ONLY: entity and content are
    revise-stable, while revise()/NREM2-boost/decay mint a NEW belief_id on
    every revision -- an id-keyed index goes stale within one sleep cycle
    AND re-dirties ~2000 vectors per restart (found 2026-06-10), which is
    why belief_id is deliberately NOT part of the metadata contract.

    Default threshold 0.95, NOT lower: measured on the live store
    (2026-06-10), median pairwise cosine between belief vectors is 0.733
    and p99 is 0.875 -- a 0.85 threshold would pair 97.8% of all beliefs.
    At 0.95 the matched pairs are genuine paraphrases. Builder stat
    records pairing only via their shared template are filtered out by
    _is_template_pair regardless of similarity.

    scan_limit caps how many beliefs are QUERIED per run. Candidate mix:
    half newest-created (fresh beliefs from build_all are the likeliest
    dups), half random from the rest -- revise() preserves created_at, so a
    pure newest-first window would re-query the SAME beliefs forever and
    96% of the old backlog would never be reached. Each query is a linear
    scan of the namespace (~0.1-0.8s pure-Python), so an uncapped sweep
    over ~2000 beliefs would take tens of minutes.

    Returns: List of (keep_id, remove_id, similarity) sorted by similarity desc.
    """
    current = store.get_current()
    if not current or not semantic_memory:
        return []

    if scan_limit is not None and scan_limit <= 0:
        logger.info(
            "[BeliefStore] Semantic dedup: scan_limit=%s -- sweep disabled",
            scan_limit,
        )
        return []

    # Entity -> current belief (highest confidence wins on collision).
    by_entity = {}
    for b in current:
        prev = by_entity.get(b.entity)
        if prev is None or b.confidence > prev.confidence:
            by_entity[b.entity] = b

    newest = sorted(current, key=lambda b: b.created_at, reverse=True)
    if scan_limit is not None and scan_limit < len(newest):
        import random
        half = scan_limit // 2
        head = newest[:half]
        tail = newest[half:]
        backlog = random.sample(tail, min(scan_limit - half, len(tail)))
        candidates = head + backlog
    else:
        candidates = newest

    pairs = []
    seen_pairs = set()
    total_hits = 0
    resolved_hits = 0
    search_errors = 0
    template_skips = 0

    for belief in candidates:
        try:
            results = semantic_memory.search(
                belief.content, namespace="beliefs", top_k=3
            )
            total_hits += len(results)
            for result in results:
                # Real SemanticMemory API: SearchResult is a __slots__ object
                # (entry, score), entry.metadata is the dict. The old
                # result.get(...) raised AttributeError on every hit and the
                # except below swallowed it -> this function silently returned
                # [] forever (wired-but-dead, found 2026-06-10).
                sim = getattr(result, "score", 0.0)
                entry = getattr(result, "entry", None)
                metadata = getattr(entry, "metadata", None) or {}

                # Resolve the hit to a CURRENT belief via its stable entity.
                other = by_entity.get(metadata.get("entity", ""))
                if other is None:
                    continue
                resolved_hits += 1

                if sim < similarity_threshold:
                    continue
                if other.belief_id == belief.belief_id:
                    continue  # the query belief's own vector
                if other.entity == belief.entity:
                    # Same-entity collision: the shared vector carries only
                    # ONE of the contents (last-wins index), so the score
                    # never compared these two texts -- merging on it would
                    # destroy an uncompared belief. Exact dedup owns the
                    # same-entity case.
                    continue
                if _is_template_pair(belief, other):
                    # Same sentence about two different subjects: merging
                    # would delete one subject's record outright.
                    template_skips += 1
                    continue
                pair_key = tuple(sorted([belief.belief_id, other.belief_id]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                # Keep higher confidence
                if belief.confidence >= other.confidence:
                    pairs.append((belief.belief_id, other.belief_id, sim))
                else:
                    pairs.append((other.belief_id, belief.belief_id, sim))
        except Exception:
            search_errors += 1
            continue

    if total_hits == 0:
        # Observability over silence. NOTE: a dead embedding backend does
        # NOT raise -- embed() returns [] and search returns no hits -- so
        # backend availability must be checked explicitly to avoid blaming
        # an unpopulated namespace for an Ollama outage.
        backend_up = bool(getattr(semantic_memory, "available", True))
        if search_errors or not backend_up:
            logger.info(
                "[BeliefStore] Semantic dedup: 0 hits, backend_available=%s, "
                "search_errors=%d/%d -- embedding backend problem likely",
                backend_up, search_errors, len(candidates)
            )
        else:
            logger.info(
                "[BeliefStore] Semantic dedup: 0 hits across %d beliefs -- "
                "'beliefs' namespace likely unpopulated", len(candidates)
            )
    elif resolved_hits == 0:
        # Hits exist but none resolve to a current belief: the namespace
        # predates the entity metadata contract (2026-06-10) or the index
        # is fully stale. THIS was the silent killer before the contract:
        # searches returned plenty, dedup matched nothing.
        logger.info(
            "[BeliefStore] Semantic dedup: %d hits but 0 resolvable to "
            "current beliefs -- index lacks entity metadata "
            "(re-index needed)", total_hits
        )

    if template_skips:
        logger.info(
            "[BeliefStore] Semantic dedup: %d template pair(s) skipped "
            "(content differs only by own entity / digit runs)",
            template_skips,
        )

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
        # Carry the lifecycle of the kept belief forward (resurrection guard):
        # merging must not turn a quarantined/retracted belief back into a
        # fresh active record under a new id.
        status=keep.status,
        retraction=keep.retraction,
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
                status=old.status,
                retraction=old.retraction,
            )
            store._beliefs[old.belief_id] = sup
            store._dirty.add(old.belief_id)

    store.add(revised)
    return True


# Semantic dedup safety rails (2026-06-10). Rollout is three-step (house
# flag->observe->cutover discipline), because merging by embedding
# similarity rewrites the belief soul irreversibly (compact() drops the
# tombstones in the same maintenance pass):
#   unset/off       -> semantic phase skipped entirely
#   =observe        -> find pairs and LOG them at INFO, merge NOTHING
#                      (the calibration data the OBSERVE phase needs)
#   =1/true/yes/on  -> merge for real, capped per run
# Flags are read live from os.environ, but the daemon's environment comes
# from systemd EnvironmentFile (.env) frozen at start -- arming requires a
# .env edit PLUS a service restart; an SSH-shell export is a no-op.
# Caps bound the blast radius of a bad threshold: at most
# MAX_SEMANTIC_MERGES_PER_RUN merges and SEMANTIC_DEDUP_SCAN_LIMIT queried
# beliefs per run; SEMANTIC_DEDUP_THRESHOLD overrides the 0.95 default.
SEMANTIC_DEDUP_FLAG = "SEMANTIC_DEDUP_ENABLED"
MAX_SEMANTIC_MERGES_PER_RUN = 20
DEFAULT_SEMANTIC_SCAN_LIMIT = 150
DEFAULT_SEMANTIC_THRESHOLD = 0.95
_TRUTHY = {"1", "true", "yes", "on"}


def _semantic_dedup_mode() -> str:
    """Resolve the rollout mode: 'off' | 'observe' | 'merge'."""
    import os
    raw = os.environ.get(SEMANTIC_DEDUP_FLAG, "").strip().lower()
    if raw in ("observe", "dry_run", "dry-run"):
        return "observe"
    if raw in _TRUTHY:
        return "merge"
    return "off"


def _semantic_scan_limit() -> int:
    import os
    try:
        value = int(os.environ.get(
            "SEMANTIC_DEDUP_SCAN_LIMIT", DEFAULT_SEMANTIC_SCAN_LIMIT
        ))
    except (TypeError, ValueError):
        return DEFAULT_SEMANTIC_SCAN_LIMIT
    # Negative would mean an UNBOUNDED sweep (tens of minutes in the
    # planner thread) -- clamp to 0 (= sweep disabled, logged as such).
    return max(0, value)


def _semantic_threshold() -> float:
    import os
    try:
        return float(os.environ.get(
            "SEMANTIC_DEDUP_THRESHOLD", DEFAULT_SEMANTIC_THRESHOLD
        ))
    except (TypeError, ValueError):
        return DEFAULT_SEMANTIC_THRESHOLD


def deduplicate(
    store,
    semantic_memory=None,
    similarity_threshold: Optional[float] = None,
) -> int:
    """
    Full dedup pass: find duplicates and merge them.

    If semantic_memory is available AND SEMANTIC_DEDUP_ENABLED is armed,
    uses embedding similarity: =observe logs would-be pairs WITHOUT
    merging; =1/true/yes/on merges (capped: scan limit + max merges/run).
    Always runs exact matching as baseline.

    Returns: number of beliefs merged (removed).
    """
    merged = 0

    # Phase 1: exact duplicates (always runs)
    exact_pairs = find_exact_duplicates(store)
    for keep_id, remove_id in exact_pairs:
        if merge_duplicate_pair(store, keep_id, remove_id):
            merged += 1

    # Phase 2: semantic duplicates (optional, flag-gated)
    mode = _semantic_dedup_mode()
    if semantic_memory and mode == "off":
        logger.debug(
            "[BeliefStore] Semantic dedup wired but disabled "
            f"({SEMANTIC_DEDUP_FLAG} not armed)"
        )
    elif semantic_memory:
        threshold = (
            similarity_threshold if similarity_threshold is not None
            else _semantic_threshold()
        )
        try:
            sem_pairs = find_semantic_duplicates(
                store, semantic_memory, threshold,
                scan_limit=_semantic_scan_limit(),
            )
            if mode == "observe":
                # OBSERVE rollout step: full visibility, zero mutation.
                for keep_id, remove_id, sim in sem_pairs:
                    keep = store.get(keep_id)
                    remove = store.get(remove_id)
                    logger.info(
                        "[BeliefStore] Semantic dedup OBSERVE: would keep "
                        f"{keep_id} ({getattr(keep, 'entity', '?')!r}), "
                        f"remove {remove_id} "
                        f"({getattr(remove, 'entity', '?')!r}), "
                        f"sim={sim:.3f}"
                    )
                logger.info(
                    "[BeliefStore] Semantic dedup OBSERVE: "
                    f"{len(sem_pairs)} candidate pairs at "
                    f"threshold {threshold} (0 merged, observe mode)"
                )
            else:
                sem_merged = 0
                attempted = 0
                for keep_id, remove_id, sim in sem_pairs:
                    if sem_merged >= MAX_SEMANTIC_MERGES_PER_RUN:
                        logger.info(
                            "[BeliefStore] Semantic dedup: merge cap reached "
                            f"({MAX_SEMANTIC_MERGES_PER_RUN}), "
                            f"{len(sem_pairs) - attempted} pairs deferred"
                        )
                        break
                    attempted += 1
                    if merge_duplicate_pair(store, keep_id, remove_id):
                        sem_merged += 1
                        logger.info(
                            f"[BeliefStore] Semantic merge: kept {keep_id}, "
                            f"removed {remove_id} (sim={sim:.3f})"
                        )
                merged += sem_merged
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
