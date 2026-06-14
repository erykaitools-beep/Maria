"""Auto-indexer for SemanticMemory.

Populates the vector store from Maria's JSONL data sources on startup.
Runs in a background thread to avoid blocking the tick loop.

Sources indexed:
    - knowledge_index.jsonl -> namespace "knowledge" (learning material topics)
    - beliefs.jsonl -> namespace "beliefs" (world model beliefs)
    - topic_hints.jsonl -> namespace "hints" (K12 suggestions)
    - input/ files -> extract title from header for richer knowledge embeddings
"""

import hashlib
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _extract_title_from_file(file_path: Path) -> str:
    """Extract human-readable title from input file header.

    Looks for lines like:
        # Tytul: Fizyka
        # Temat: logika formalna
    Falls back to cleaned filename.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for _ in range(5):  # Check first 5 lines
                line = f.readline()
                if not line:
                    break
                for prefix in ("# Tytul:", "# Temat:", "# Title:"):
                    if line.startswith(prefix):
                        return line[len(prefix):].strip()
    except (OSError, UnicodeDecodeError):
        pass

    # Fallback: clean filename
    name = file_path.stem
    # Remove prefixes like web_wiki_, web_rss_, input_NNN_, expert_
    name = re.sub(r'^(web_wiki_|web_rss_|input_\d+_|expert_)', '', name)
    return name.replace('_', ' ')


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load all records from a JSONL file."""
    records = []
    if not path.exists():
        return records
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        logger.warning(f"[INDEXER] Cannot read {path}: {e}")
    return records


def build_knowledge_entries(
    knowledge_path: Path,
    input_dir: Path,
    verified_ids: Optional[set] = None,
) -> List[Tuple[str, str]]:
    """Build (entry_id, text) pairs from knowledge_index + input files.

    Embeds: title + filename + status info. Only INDEPENDENTLY exam-verified
    files are indexed (see the trust gate below). ``verified_ids`` lets a caller
    inject the verified set (and lets tests avoid the filesystem); when None it
    is resolved via success_criteria.independently_verified_file_ids().
    """
    entries = []
    records = _load_jsonl(knowledge_path)

    if verified_ids is None:
        from agent_core.goals.success_criteria import independently_verified_file_ids
        verified_ids = independently_verified_file_ids()

    for rec in records:
        file_id = rec.get("id", "")
        filename = rec.get("file", "")
        status = rec.get("status", "new")

        if not file_id:
            continue

        # Trust gate (#2, 2026-05-30, hardened by the 2026-06-01 audit): only
        # knowledge an INDEPENDENT examiner verified (grader_independent==True,
        # score >= pass) is semantically indexed -> retrievable/groundable. The
        # 'completed' status alone is set by any exam >= pass INCLUDING the
        # student self-grading, so it is NOT proof of independence. Un-examined
        # or only self-graded knowledge stays provisional and is indexed only
        # once an independent exam clears it. "read"/"self-graded" != "trusted".
        if status != "completed" or file_id not in verified_ids:
            continue

        # Try to extract title from actual input file
        file_path = input_dir / filename
        title = _extract_title_from_file(file_path) if file_path.exists() else ""

        # Build embedding text: title is most semantic, filename as context
        if title:
            text = f"{title} ({filename}, status: {status})"
        else:
            clean_name = filename.replace('_', ' ').replace('.txt', '')
            text = f"{clean_name} (status: {status})"

        entries.append((f"knowledge:{file_id}", text))

    return entries


def make_belief_entry_id(entity: str) -> str:
    """Stable vector entry_id for a belief entity.

    Entities over 50 chars get a content-hash suffix instead of bare
    truncation: live data (2026-06-10) has 1063/1997 entities over 50
    chars and a REAL pair of distinct current beliefs sharing a 50-char
    prefix -- bare truncation collided them onto one entry_id (only one
    searchable, plus a re-embed ping-pong every boot as they overwrote
    each other).
    """
    if len(entity) <= 50:
        return f"belief:{entity}"
    digest = hashlib.md5(entity.encode("utf-8")).hexdigest()[:8]
    return f"belief:{entity[:40]}~{digest}"


def build_belief_entries(beliefs_path: Path) -> List[Tuple[str, str, Dict]]:
    """Build (entry_id, text, metadata) triples from beliefs.jsonl.

    Embeds: entity + content + tags.

    Metadata carries the dedup-resolution contract (2026-06-10): ``entity``
    only. It is revise-stable -- BeliefStore.revise() mints a NEW belief_id
    but never changes entity or content -- so consumers resolve hits via
    entity. belief_id is deliberately NOT stored: it churns on every
    boost/decay/exam revision, which would re-dirty ~2000 vectors (tens of
    MB appended to semantic_vectors.jsonl) on every restart for a key that
    goes stale within one sleep cycle anyway.
    Tombstoned records (superseded_by set) are skipped -- only current
    beliefs are retrievable.
    """
    entries = []
    # MERGE semantics: last CURRENT record per entity wins
    beliefs = {}
    for rec in _load_jsonl(beliefs_path):
        entity = rec.get("entity", "")
        if entity and rec.get("superseded_by") is None:
            beliefs[entity] = rec

    for entity, rec in beliefs.items():
        content = rec.get("content", "")
        tags = rec.get("tags", [])

        text = content if content else entity
        if tags:
            text += f" (tagi: {', '.join(tags[:5])})"

        entries.append((make_belief_entry_id(entity), text, {"entity": entity}))

    return entries


def build_hint_entries(hints_path: Path) -> List[Tuple[str, str]]:
    """Build (entry_id, text) pairs from topic_hints.jsonl."""
    entries = []
    for rec in _load_jsonl(hints_path):
        topic = rec.get("topic", "")
        if not topic:
            continue
        source = rec.get("source", "self_analysis")
        consumed = rec.get("consumed", False)
        text = f"Sugestia nauki: {topic} (zrodlo: {source})"
        entries.append((f"hint:{topic[:50]}", text))
    return entries


# Namespace for full learned CONTENT (summary + key_points) per chunk, keyed by
# source_file metadata. Distinct from "knowledge" (thin title only). Powers the
# held-out exam's closed-book retrieval (answer from real search over her notes,
# not a spoon-fed same-file summary) and gives production a content-level recall
# path it otherwise lacks.
SUMMARY_NAMESPACE = "summaries"


def build_summary_entries(memory_path: Path) -> List[Tuple[str, str, str]]:
    """Build (entry_id, text, source_file) triples from long-term memory chunks.

    Unlike build_knowledge_entries (which embeds only a thin title), this embeds
    the actual learned content (summary + key_points) per chunk so it is
    retrievable cross-file and a single file can be excluded at query time.

    No independent-exam trust gate here on purpose: this namespace is Maria's
    working RECALL over everything she has read, not the canonical belief store.
    The held-out grader judges the answer independently, so letting self-graded
    notes feed recall does not let unverified knowledge into beliefs (that gate
    lives in build_knowledge_entries / belief_builder and is untouched).
    """
    entries: List[Tuple[str, str, str]] = []
    for rec in _load_jsonl(memory_path):
        source_file = rec.get("source_file", "")
        chunk_id = rec.get("chunk_id") or (
            f"{source_file}#chunk_{rec.get('chunk_index', '0')}" if source_file else ""
        )
        if not source_file or not chunk_id:
            continue
        summary = rec.get("summary") or rec.get("summary_simple", "")
        key_points = rec.get("key_points") or rec.get("core_ideas", [])
        parts = [summary.strip()] if summary else []
        for kp in key_points:
            parts.append(f"- {kp}")
        text = "\n".join(p for p in parts if p)
        if not text.strip():
            continue
        entries.append((f"summary:{chunk_id}", text, source_file))
    return entries


def index_summaries(semantic_memory, memory_path, only_new: bool = True) -> int:
    """Index learned-chunk summaries into SUMMARY_NAMESPACE with source_file
    metadata (so results can be filtered/excluded by file). Incremental by
    default: skips entry_ids already in the store. Returns count newly indexed.
    """
    triples = build_summary_entries(Path(memory_path))
    if not triples:
        return 0

    by_file: Dict[str, List[Tuple[str, str]]] = {}
    for entry_id, text, source_file in triples:
        if only_new and semantic_memory.store.get(entry_id) is not None:
            continue
        by_file.setdefault(source_file, []).append((entry_id, text))

    total = 0
    for source_file, batch in by_file.items():
        total += semantic_memory.index_batch(
            SUMMARY_NAMESPACE, batch, extra_metadata={"source_file": source_file},
        )
    if total > 0:
        semantic_memory.save()
        logger.info(
            f"[INDEXER] Indexed {total} summary chunks into '{SUMMARY_NAMESPACE}'"
        )
    return total


def run_initial_indexing(semantic_memory, data_dir: str, memory_dir: str,
                         input_dir: str) -> Dict[str, int]:
    """Run full initial indexing of all sources.

    Returns dict with counts per namespace.
    """
    data_path = Path(data_dir)
    memory_path = Path(memory_dir)
    input_path = Path(input_dir)

    counts = {}
    start = time.time()

    # 1. Knowledge (from knowledge_index + input file titles)
    knowledge = build_knowledge_entries(
        memory_path / "knowledge_index.jsonl",
        input_path,
    )
    if knowledge:
        count = semantic_memory.index_batch("knowledge", knowledge)
        counts["knowledge"] = count
        logger.info(f"[INDEXER] Indexed {count} knowledge entries")

    # 2. Beliefs. Ghost cleanup runs FIRST: the store sits at its
    # MAX_VECTORS cap (2026-06-10: 6522 belief vectors vs 1997 current
    # beliefs), so indexing before cleanup would evict live entries from
    # other namespaces while thousands of reclaimable ghost slots exist.
    try:
        belief_stale = cleanup_stale_belief_vectors(
            semantic_memory,
            str(data_path / "beliefs.jsonl"),
        )
        if belief_stale:
            counts["belief_ghosts_removed"] = belief_stale
    except Exception as e:  # cleanup must never break startup indexing
        logger.warning(f"[INDEXER] Belief ghost cleanup skipped: {e}")

    beliefs = build_belief_entries(data_path / "beliefs.jsonl")
    if beliefs:
        count = semantic_memory.index_batch("beliefs", beliefs)
        counts["beliefs"] = count
        logger.info(f"[INDEXER] Indexed {count} belief entries")

    # 3. Hints
    hints = build_hint_entries(data_path / "topic_hints.jsonl")
    if hints:
        count = semantic_memory.index_batch("hints", hints)
        counts["hints"] = count
        logger.info(f"[INDEXER] Indexed {count} hint entries")

    # 4. Summaries (full learned content -> SUMMARY_NAMESPACE). Powers the
    # held-out exam's closed-book retrieval (answer from real cross-file search,
    # not the spoon-fed same-file summary) and content-level recall. Incremental
    # (skips already-indexed chunks) so re-runs on later startups are cheap.
    try:
        summary_count = index_summaries(
            semantic_memory, memory_path / "maria_longterm_memory.jsonl"
        )
        if summary_count:
            counts["summaries"] = summary_count
    except Exception as e:  # never let recall-index work break startup indexing
        logger.warning(f"[INDEXER] Summary indexing skipped: {e}")

    # Cleanup stale vectors (files that no longer exist in knowledge_index)
    stale_removed = cleanup_stale_vectors(
        semantic_memory,
        str(memory_path / "knowledge_index.jsonl"),
    )
    if stale_removed:
        counts["stale_removed"] = stale_removed

    # Save vectors to JSONL
    saved = semantic_memory.save()

    elapsed = time.time() - start
    # Removal counters excluded: "indexed N vectors" must mean embeds, not
    # cleanups -- on the migration boot ghosts removed (4500+) would dwarf
    # the real work and turn the operator's verification log into a lie.
    _removal_keys = ("stale_removed", "belief_ghosts_removed")
    total = sum(v for k, v in counts.items() if k not in _removal_keys)
    logger.info(
        f"[INDEXER] Initial indexing complete: {total} vectors "
        f"({counts}) in {elapsed:.1f}s, {saved} saved to disk"
    )

    return counts


STARTUP_DELAY_SEC = 60  # Wait for homeostasis to stabilize before CPU-heavy embedding
INCREMENTAL_NAMESPACE = "knowledge"


def start_background_indexing(semantic_memory, data_dir: str, memory_dir: str,
                               input_dir: str,
                               delay_sec: float = STARTUP_DELAY_SEC) -> threading.Thread:
    """Start initial indexing in a background thread after a delay.

    Delays embedding work to avoid CPU spike that triggers REDUCED mode.
    Returns the thread (for join/monitoring).
    """
    def _run():
        try:
            if delay_sec > 0:
                logger.info(f"[INDEXER] Waiting {delay_sec:.0f}s before indexing (CPU cooldown)")
                time.sleep(delay_sec)
            run_initial_indexing(semantic_memory, data_dir, memory_dir, input_dir)
        except Exception as e:
            logger.error(f"[INDEXER] Background indexing failed: {e}")

    t = threading.Thread(target=_run, name="semantic-indexer", daemon=True)
    t.start()
    logger.info("[INDEXER] Background indexing started")
    return t


def cleanup_stale_vectors(semantic_memory, knowledge_path: str, verified_ids=None) -> int:
    """Remove knowledge vectors that should no longer be retrievable.

    A vector is stale for either reason: (1) its file left knowledge_index, or
    (2) the file is no longer INDEPENDENTLY verified -- self-healing trust gate
    (#2, 2026-06-01): only independently-verified knowledge stays indexed and
    groundable, mirroring the create-side gate in build_knowledge_entries.

    Guarded: if exam_results is missing/empty the verified set cannot be
    trusted, so the trust filter is skipped and only the left-the-index case
    applies -- a transient read failure must never wipe the whole index.

    Returns count of removed vectors.
    """
    kp = Path(knowledge_path)

    # Trusted (independently-verified) file set, guarded against a missing/empty
    # exam_results that would otherwise make every file look unverified.
    # ``verified_ids`` lets a caller inject the set (and lets tests avoid the
    # filesystem); when None it is resolved + guarded here.
    if verified_ids is not None:
        trust_filter = True
        verified = verified_ids
    else:
        from agent_core.goals.success_criteria import (
            independently_verified_file_ids, _resolve_exam_results_path,
        )
        _rp = _resolve_exam_results_path()
        trust_filter = bool(_rp and _rp.is_file() and _rp.stat().st_size > 0)
        verified = independently_verified_file_ids() if trust_filter else set()

    # Entry ids that should REMAIN indexed.
    current_ids = set()
    if kp.exists():
        for rec in _load_jsonl(kp):
            file_id = rec.get("id", "")
            if not file_id:
                continue
            # Keep iff in-index AND (trust set untrustworthy OR verified). With
            # the trust filter off we keep any in-index file (legacy behaviour)
            # so a read failure can never mass-remove.
            if (not trust_filter) or (file_id in verified):
                current_ids.add(f"knowledge:{file_id}")

    # Find stale vectors in knowledge namespace
    stored_ids = semantic_memory.store.list_ids_by_namespace("knowledge")
    stale_ids = [eid for eid in stored_ids if eid not in current_ids]

    if not stale_ids:
        return 0

    for eid in stale_ids:
        semantic_memory.remove(eid)

    # Full rewrite needed after removals (append-only save won't delete)
    semantic_memory.store.save_full()
    logger.info(f"[INDEXER] Cleaned {len(stale_ids)} stale vectors: {stale_ids[:5]}")

    return len(stale_ids)


def cleanup_stale_belief_vectors(semantic_memory, beliefs_path: str) -> int:
    """Remove belief vectors whose entity is no longer a CURRENT belief.

    Ghosts accumulate because belief entities get pruned/merged away while
    the startup indexer only ever ADDS (2026-06-10 audit: 6522 belief
    vectors vs 1997 current beliefs, store at the MAX_VECTORS cap, so every
    new vector evicted the globally-oldest entry -- including exam-critical
    summaries). Mirrors cleanup_stale_vectors (knowledge namespace).

    Resolution: prefer metadata["entity"] (full entity, present since the
    2026-06-10 metadata contract); legacy entries without it survive only
    when their entry_id matches what the current id scheme
    (make_belief_entry_id) would produce for some current entity.

    Guarded: a missing/empty beliefs.jsonl means the current set cannot be
    trusted -- skip cleanup entirely rather than mass-remove.

    Returns count of removed vectors.
    """
    bp = Path(beliefs_path)
    if not bp.exists():
        return 0

    current_entities = set()
    for rec in _load_jsonl(bp):
        entity = rec.get("entity", "")
        if entity and rec.get("superseded_by") is None:
            current_entities.add(entity)

    # Empty current set = unreadable/empty file; never wipe the namespace.
    if not current_entities:
        return 0

    # Ids the CURRENT id scheme would produce. Legacy entries (no metadata)
    # survive only if their id matches this scheme exactly -- old-format
    # truncated ids of >50-char entities deliberately do NOT match, so the
    # migration boot removes them and the same boot re-indexes those
    # beliefs under collision-free hash-suffixed ids.
    current_ids = {make_belief_entry_id(e) for e in current_entities}

    stale_ids = []
    for eid in semantic_memory.store.list_ids_by_namespace("beliefs"):
        entry = semantic_memory.store.get(eid)
        if entry is None:
            continue
        meta_entity = entry.metadata.get("entity", "")
        if meta_entity:
            if meta_entity not in current_entities:
                stale_ids.append(eid)
        elif eid not in current_ids:
            # Legacy entry (no metadata contract): entry_id is the only key.
            stale_ids.append(eid)

    if not stale_ids:
        return 0

    for eid in stale_ids:
        semantic_memory.remove(eid)

    # Full rewrite needed after removals (append-only save won't delete)
    semantic_memory.store.save_full()
    logger.info(
        f"[INDEXER] Cleaned {len(stale_ids)} ghost belief vectors: {stale_ids[:5]}"
    )

    return len(stale_ids)


def index_new_files(semantic_memory, knowledge_path: str, input_dir: str) -> int:
    """Index only files not yet in the vector store.

    Call after learning new material or fetching new web content.
    Returns count of newly indexed entries.
    """
    kp = Path(knowledge_path)
    ip = Path(input_dir)

    if not kp.exists():
        return 0

    all_entries = build_knowledge_entries(kp, ip)
    if not all_entries:
        return 0

    # Filter: only entries not yet in store
    new_entries = []
    for entry_id, text in all_entries:
        if semantic_memory.store.get(entry_id) is None:
            new_entries.append((entry_id, text))

    if not new_entries:
        return 0

    count = semantic_memory.index_batch(INCREMENTAL_NAMESPACE, new_entries)
    if count > 0:
        semantic_memory.save()
        logger.info(f"[INDEXER] Incremental: indexed {count} new knowledge entries")
    return count
