"""
BeliefBuilder - Populates world model from existing JSONL sources.

READ-ONLY consumption of:
- knowledge_index.jsonl (file statuses, exam scores)
- maria_longterm_memory.jsonl (summaries, tags, key_points per chunk)
- exam_results.jsonl (pass/fail confirmation)

Zero LLM. Zero side effects on source files.
Pattern: KnowledgeAnalyzer (teacher/knowledge_analyzer.py)
Kontrakt: docs/CONTRACTS.md - Kontrakt 6: World Model
"""

import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent_core.world_model.belief_model import (
    Belief, BeliefType, BeliefSource, EntityType, create_belief,
)
from agent_core.world_model.belief_store import BeliefStore

logger = logging.getLogger(__name__)

# Tag normalization (same rules as KnowledgeAnalyzer)
_TAG_STOP_WORDS = {
    "inne", "ogolne", "wiedza", "other", "general", "misc",
    "rozne", "notatki", "tekst", "plik",
}
_TAG_MIN_LEN = 2
_TAG_MAX_LEN = 40


def _normalize_tag(tag: str) -> Optional[str]:
    """Normalize a tag. Same logic as KnowledgeAnalyzer._normalize_tag()."""
    normalized = tag.lower().strip()
    if len(normalized) < _TAG_MIN_LEN or len(normalized) > _TAG_MAX_LEN:
        return None
    if normalized in _TAG_STOP_WORDS:
        return None
    return normalized


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load records from a JSONL file. Returns empty list on error."""
    if not path.exists():
        return []
    records = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except IOError:
        pass
    return records


# Concept FACT bar: a key_point earns FACT only on an exam at/above this score.
_CONCEPT_FACT_THRESHOLD = 0.7

# Synthesis blast-radius cap (hardening 2026-06-13). A synthesized record is
# gated only by a CLOSED-LOOP exam -- the questions are authored from the
# synthesis's OWN text, so the exam verifies recall, never that the claim is
# true or derivable from its sources. A hallucinated cross-source "insight"
# therefore self-verifies. To keep that blast radius small, a synthesis NEVER
# mints a near-unprunable FACT: its beliefs stay low-trust OBSERVATION (capped
# confidence) until an INDEPENDENT, non-synthesis source/exam corroborates the
# claim. This is independent of CONCEPT_TRUST_GATE.
_SYNTHESIS_BELIEF_CEIL = 0.6


def _is_synthetic_source(rec: Dict[str, Any]) -> bool:
    """True if an index/memory record originates from a SYNTHESIS.

    Two structural signals (folder marker OR ``synthesis_`` id prefix), so a
    record missing one field is still caught. Mirrors
    ``agent_core.synthesis.synthesis_agent._is_synthetic`` (kept local to avoid
    a circular import: synthesis_agent already imports from this module)."""
    if rec.get("folder") == "synthesis":
        return True
    fid = rec.get("source_file") or rec.get("id") or rec.get("file") or ""
    return str(fid).startswith("synthesis_")


# Provenance prefixes whose files share ONE logical origin. Every
# expert_<topic>.txt is the SAME expert LLM (NIM/Codex) answering a different
# knowledge-gap query (gap_planner ASK_EXPERT) -- so 100 expert_*.txt files are
# one voice, not 100 corroborating sources. Counting each as distinct
# manufactured a fake "cross-source" signal: it inflated synthesis
# eligibility/ranking AND topic-belief confidence (len(files)/5) on what is
# really a single source (audit 2026-06-16). Web/wiki/rss/input/edu files are
# independently fetched documents, so each stays its own logical source.
_CORPUS_PREFIXES = ("expert_",)


def _source_group(source_file: str) -> str:
    """Map a source_file to its LOGICAL source key for independence counting.

    Files from a single-origin corpus (see _CORPUS_PREFIXES) collapse to one
    shared key; every other file is its own source (returned unchanged). Use
    this -- never the raw distinct source_file count -- wherever a count is
    meant to represent INDEPENDENT sources (cross-source synthesis gate,
    topic-belief confidence). Kept here so the rule has one home, alongside the
    tag and synthetic-source rules (synthesis_agent imports it)."""
    sf = source_file or ""
    for prefix in _CORPUS_PREFIXES:
        if sf.startswith(prefix):
            return prefix.rstrip("_")
    return sf


def _concept_trust_mode() -> str:
    """Concept trust-gate mode: ``off`` (default), ``observe``, or ``armed``.

    The CONCEPT path (build_concept_beliefs / update_from_exam) historically
    stamped FACT from ANY passing exam, including the student grading its own
    answers -- the same self-graded hole the 2026-06-01 audit closed for FILE
    beliefs (build_file_beliefs + prune_unverified_file_beliefs use
    independently_verified_file_ids), but the concept tor was left out.

    Read live from ``CONCEPT_TRUST_GATE`` (loaded from .env at boot, so a change
    needs a restart):
    - ``armed``/1/true/yes/on -> a concept earns FACT only from an INDEPENDENT
      exam (grader_independent==True); a self-graded pass keeps it OBSERVATION.
    - ``observe`` -> behaviour UNCHANGED (FACT from any exam); the boot census
      reports how many FACTs rest on a self-graded exam.
    - anything else (incl. unset) -> ``off``, identical to ``observe`` for the
      builder (the census still runs; it is read-only).
    """
    raw = os.environ.get("CONCEPT_TRUST_GATE", "").strip().lower()
    if raw in {"armed", "arm", "1", "true", "yes", "on"}:
        return "armed"
    if raw == "observe":
        return "observe"
    return "off"


class BeliefBuilder:
    """
    Builds beliefs from existing JSONL data sources.

    All methods are idempotent - they check for existing beliefs
    before creating duplicates (via entity + source_id matching).
    """

    def __init__(
        self,
        knowledge_index_path: Path,
        longterm_memory_path: Path,
        exam_results_path: Path,
        denylist_path: Optional[Path] = None,
    ):
        self._knowledge_index_path = Path(knowledge_index_path)
        self._longterm_memory_path = Path(longterm_memory_path)
        self._exam_results_path = Path(exam_results_path)
        # Resurrection guard (rollback/quarantine): build_all is a pure
        # projection of the source JSONLs, so a store-only retract is undone
        # within one cycle unless the source/entity is on the denylist. None =
        # no denylist (tests, legacy callers) -> nothing is blocked.
        self._denylist_path = Path(denylist_path) if denylist_path else None
        # Watermark of the last completed build_all (per process). The
        # build enumerates ~32k candidates that the 2000-belief cap then
        # prunes right back out, so re-running it with UNCHANGED sources
        # is a pure create->prune washing machine (observed hourly 24/7,
        # 2026-06-11: "Built beliefs: 11612 topics, 0 files, 20342
        # concepts" every cycle, even at night with zero learning).
        self._last_build_watermark: Optional[Tuple] = None

    def _sources_watermark(self) -> Tuple:
        """(path, mtime_ns, size) per source JSONL. Equal watermark ==
        byte-identical inputs == identical build candidates."""
        marks = []
        for p in (
            self._knowledge_index_path,
            self._longterm_memory_path,
            self._exam_results_path,
        ):
            try:
                st = os.stat(p)
                marks.append((str(p), st.st_mtime_ns, st.st_size))
            except OSError:
                marks.append((str(p), 0, 0))
        return tuple(marks)

    def _load_denylist(self) -> Dict[str, set]:
        """Net active denylist {'source': set, 'entity': set}. Empty when no
        denylist path is configured (tests/legacy) -- blocks nothing."""
        if self._denylist_path is None:
            return {"source": set(), "entity": set()}
        from agent_core.world_model.retraction_log import load_denylist
        return load_denylist(self._denylist_path)

    def build_all(
        self, store: BeliefStore, force: bool = False,
    ) -> Dict[str, int]:
        """
        Build all beliefs from JSONL sources. Idempotent.

        Skips the whole pass when no source file changed since the last
        completed build (mtime+size watermark): the candidate set is a
        pure function of the sources, so an unchanged watermark can only
        re-create beliefs the cap pruned after the previous run -- churn,
        not knowledge. force=True overrides (manual/REPL rebuild).

        Uses store.bulk_mode() so that cap enforcement happens once at the
        end of the batch instead of per-add. On a cold build (~22k new
        concepts) this turns a multi-minute hang into seconds.

        Returns:
            Stats dict with counts per category (all zeros on skip, so
            callers checking any(stats.values()) treat it as a no-op).
        """
        watermark = self._sources_watermark()
        if not force and watermark == self._last_build_watermark:
            logger.debug(
                "[WorldModel] build_all skipped: sources unchanged "
                "since last build"
            )
            return {"topics": 0, "files": 0, "concepts": 0}

        with store.bulk_mode():
            # Self-healing trust gate: drop any file belief that is no longer
            # independently verified BEFORE re-creating the verified ones, so a
            # rebuild keeps the world model in sync with the gate (#2).
            self.prune_unverified_file_beliefs(store)
            stats = {
                "topics": self.build_topic_beliefs(store),
                "files": self.build_file_beliefs(store),
                "concepts": self.build_concept_beliefs(store),
            }
        # Stamp AFTER a completed pass: an exception mid-build leaves the
        # watermark unset, so the next call retries instead of skipping.
        self._last_build_watermark = watermark
        logger.info(
            f"[WorldModel] Built beliefs: "
            f"{stats['topics']} topics, {stats['files']} files, "
            f"{stats['concepts']} concepts"
        )
        return stats

    def prune_unverified_file_beliefs(self, store: BeliefStore, verified=None) -> int:
        """Self-healing trust gate (#2, 2026-06-01): drop FILE beliefs whose
        file is no longer INDEPENDENTLY verified, so the world model never
        RETAINS self-graded knowledge as canonical. The remove-side mirror of
        the create-side gate in build_file_beliefs -> a file belief exists IFF
        the file has an independent passing exam on record.

        Guarded: if exam_results is missing or empty the verified set cannot be
        trusted, so prune is SKIPPED -- a transient read failure must never
        mass-delete the world model. Returns the number of beliefs dropped.
        """
        p = Path(self._exam_results_path)
        if not p.is_file() or p.stat().st_size == 0:
            return 0
        from agent_core.world_model.belief_model import EntityType
        if verified is None:
            from agent_core.goals.success_criteria import independently_verified_file_ids
            verified = independently_verified_file_ids(
                results_path=str(self._exam_results_path)
            )
        dropped = 0
        for b in store.get_by_entity_type(EntityType.FILE):
            if b.entity not in verified:
                if store.drop_belief(b.belief_id):
                    dropped += 1
        if dropped:
            logger.info(
                f"[WorldModel] Pruned {dropped} unverified file beliefs "
                f"(self-graded -> provisional; {len(verified)} verified remain)"
            )
        return dropped

    def scan_concept_trust(
        self, store: BeliefStore, verified=None
    ) -> Dict[str, int]:
        """Observe-only census of CONCEPT-FACT beliefs by exam independence.

        Read-only mirror of the build-side concept gate: of the concept
        beliefs currently wearing the FACT badge, how many rest on an
        INDEPENDENT exam vs only a self-graded one. Never mutates the store --
        this is the telemetry that lets us watch the standing gap BEFORE arming
        CONCEPT_TRUST_GATE.

        Guarded exactly like prune_unverified_file_beliefs: returns ``{}`` (no
        report) when the exam log is missing/empty or the independent-verified
        set is empty, so a transient read can never raise a misleading
        "everything is self-graded" alarm.

        Returns ``{"total_fact", "independent", "self_graded"}`` or ``{}``.
        """
        p = Path(self._exam_results_path)
        if not p.is_file() or p.stat().st_size == 0:
            return {}
        if verified is None:
            from agent_core.goals.success_criteria import (
                independently_verified_file_ids,
            )
            verified = independently_verified_file_ids(
                min_score=_CONCEPT_FACT_THRESHOLD,
                results_path=str(self._exam_results_path),
            )
        if not verified:
            return {}
        total = independent = self_graded = 0
        for b in store.get_by_entity_type(EntityType.CONCEPT):
            if b.belief_type != BeliefType.FACT:
                continue
            total += 1
            src = b.related_entities[0] if b.related_entities else ""
            if src in verified:
                independent += 1
            else:
                self_graded += 1
        return {
            "total_fact": total,
            "independent": independent,
            "self_graded": self_graded,
        }

    def build_topic_beliefs(self, store: BeliefStore) -> int:
        """
        Create TOPIC beliefs from longterm memory tags.

        Each unique tag becomes a TOPIC entity with confidence
        based on how many files mention it.
        """
        records = _load_jsonl(self._longterm_memory_path)
        if not records:
            return 0

        denylist = self._load_denylist()

        # Count tag occurrences and track source files. SYNTHETIC records
        # (closed-loop synthesis output) are EXCLUDED from the topic source
        # set, mirroring the file/concept builders which already cap synthesis
        # via _is_synthetic_source. Without this, a synthesis could (a) create
        # a brand-new TOPIC entity from a tag the NIM fabricated, and (b)
        # inflate an existing topic's source-count/confidence with its own
        # self-referential file -- synthetic provenance leaking UNCAPPED into
        # the topic layer (topic beliefs are OBSERVATION, but the bypass also
        # means /forget_source could not unwind it). Denylisted sources are
        # dropped too so /forget_source reaches this layer (audit 2026-06-15 #2).
        denied_sources = denylist["source"]
        tag_files: Dict[str, set] = defaultdict(set)
        for rec in records:
            if _is_synthetic_source(rec):
                continue
            source_file = rec.get("source_file", "")
            if source_file in denied_sources:
                continue
            for tag in rec.get("tags", []):
                normalized = _normalize_tag(tag)
                if normalized:
                    tag_files[normalized].add(source_file)

        created = 0
        for tag, files in tag_files.items():
            # Resurrection guard: a retracted/quarantined topic belief must not
            # be re-minted by the next build (entity scope).
            if tag in denylist["entity"]:
                continue
            # Dedup: skip if belief already exists for this topic
            if store.find_by_entity_and_source(tag, f"topic:{tag}"):
                continue

            # Confidence reflects INDEPENDENT sources, not raw file count: a tag
            # carried by 100 expert_*.txt files is one LLM voice, not 100 (audit
            # 2026-06-16). related_entities/content keep the true file list.
            n_sources = len({_source_group(f) for f in files})
            confidence = min(1.0, n_sources / 5.0)
            belief = create_belief(
                entity=tag,
                entity_type=EntityType.TOPIC,
                belief_type=BeliefType.OBSERVATION,
                content=(
                    f"Temat '{tag}' wystepuje w {len(files)} plikach "
                    f"({n_sources} zrodel)"
                ),
                confidence=confidence,
                source=BeliefSource.LEARNING,
                source_id=f"topic:{tag}",
                tags=[tag],
                related_entities=list(files)[:10],
                evidence=[(BeliefSource.LEARNING.value, f"topic:{tag}", confidence)],
            )
            store.add(belief)
            created += 1

        return created

    def build_file_beliefs(self, store: BeliefStore) -> int:
        """
        Create FILE beliefs from knowledge_index.

        File status determines belief type and confidence.
        """
        records = _load_jsonl(self._knowledge_index_path)
        if not records:
            return 0

        # MERGE semantics: last record per id wins
        by_id: Dict[str, Dict] = {}
        for rec in records:
            file_id = rec.get("id", rec.get("file", ""))
            if file_id:
                by_id[file_id] = rec

        # Trust gate (#2, 2026-05-30, hardened by the 2026-06-01 audit): a belief
        # enters the canonical world model ONLY for knowledge an INDEPENDENT
        # examiner verified (grader_independent==True, score >= pass). The
        # 'completed' status alone is NOT proof of independence -- it is set by
        # any exam >= pass INCLUDING the student grading its own answers, so
        # admitting on it let self-assessed knowledge into the belief store under
        # a comment that falsely asserted independence. Read once, reused below.
        from agent_core.goals.success_criteria import independently_verified_file_ids
        verified = independently_verified_file_ids(
            results_path=str(self._exam_results_path)
        )

        denylist = self._load_denylist()
        created = 0
        for file_id, rec in by_id.items():
            status = rec.get("status", "new")

            # Resurrection guard: /forget_source <file_id> (source scope) or a
            # by-id /retract of this file belief (entity scope) blocks re-mint,
            # even when the file still passes the independent-exam gate below.
            if file_id in denylist["source"] or file_id in denylist["entity"]:
                continue

            # Un-examined OR only self-graded knowledge (new / learning /
            # learned / exam_failed, or 'completed' without an independent pass)
            # stays provisional in the knowledge_index and produces NO belief
            # until an independent exam clears it -- "read"/"self-graded" is not
            # "trusted".
            if status != "completed" or file_id not in verified:
                continue

            # Dedup
            if store.find_by_entity_and_source(file_id, f"file:{file_id}"):
                continue

            last_scores = rec.get("last_scores", [])
            avg_score = sum(last_scores) / len(last_scores) if last_scores else 0.0

            if avg_score >= 0.7:
                belief_type = BeliefType.FACT
                confidence = min(1.0, avg_score)
                content = f"Plik '{file_id}' opanowany (score {avg_score:.0%})"
            else:
                belief_type = BeliefType.OBSERVATION
                confidence = max(0.3, avg_score)
                content = f"Plik '{file_id}' ukonczony, ale slaby wynik ({avg_score:.0%})"

            # Synthesis blast-radius cap: a closed-loop exam cannot justify a
            # near-unprunable FACT, so a synthesized file stays OBSERVATION
            # (capped confidence) until independently corroborated.
            if _is_synthetic_source(rec):
                belief_type = BeliefType.OBSERVATION
                confidence = min(confidence, _SYNTHESIS_BELIEF_CEIL)
                content = (
                    f"Plik '{file_id}' (synteza, niezweryfikowana niezaleznie) "
                    f"score {avg_score:.0%}"
                )

            tags = [t.lower() for t in rec.get("tags", [])][:10]
            ev = [(BeliefSource.LEARNING.value, f"file:{file_id}", confidence)]
            if avg_score > 0:
                ev.append((BeliefSource.EXAM.value, f"exam:{file_id}", avg_score))
            belief = create_belief(
                entity=file_id,
                entity_type=EntityType.FILE,
                belief_type=belief_type,
                content=content,
                confidence=confidence,
                source=BeliefSource.LEARNING,
                source_id=f"file:{file_id}",
                tags=tags,
                evidence=ev,
            )
            store.add(belief)
            created += 1

        return created

    def build_concept_beliefs(self, store: BeliefStore) -> int:
        """
        Create CONCEPT beliefs from longterm memory key_points.

        Each key_point becomes a CONCEPT with tags as related entities.
        """
        records = _load_jsonl(self._longterm_memory_path)
        if not records:
            return 0

        # Build exam score map for confidence boosting. Track the best score
        # per file from ANY grader (exam_scores) AND, separately, from an
        # INDEPENDENT grader only (exam_scores_indep) -- the armed trust gate
        # admits FACT only on the latter, mirroring build_file_beliefs.
        exam_records = _load_jsonl(self._exam_results_path)
        exam_scores: Dict[str, float] = {}
        exam_scores_indep: Dict[str, float] = {}
        for er in exam_records:
            file_id = er.get("file", "")
            score = er.get("score", 0.0)
            if not file_id:
                continue
            # Keep best score per file
            exam_scores[file_id] = max(exam_scores.get(file_id, 0.0), score)
            if er.get("grader_independent"):
                exam_scores_indep[file_id] = max(
                    exam_scores_indep.get(file_id, 0.0), score
                )

        # observe-safe: enforce ONLY when armed AND at least one independent
        # exam exists. A transient/empty read of exam_results must never strip
        # FACT from the whole concept layer (concepts are ~57% of the cap).
        enforce = _concept_trust_mode() == "armed" and bool(exam_scores_indep)

        denylist = self._load_denylist()
        created = 0
        for rec in records:
            source_file = rec.get("source_file", "")
            # Resurrection guard: /forget_source <source_file> blocks every
            # concept belief derived from it (root-and-branch cut of a synthesis).
            if source_file and source_file in denylist["source"]:
                continue
            chunk_id = rec.get("chunk_id", source_file)
            key_points = rec.get("key_points", [])
            tags = rec.get("tags", [])
            normalized_tags = [t for t in (_normalize_tag(tg) for tg in tags) if t]
            # Synthesis blast-radius cap: concepts from a synthesis stay
            # OBSERVATION (the gating exam is a closed loop on the synthesis's
            # own text), regardless of score or CONCEPT_TRUST_GATE.
            is_synth = _is_synthetic_source(rec)

            for i, kp in enumerate(key_points):
                if not kp or not isinstance(kp, str):
                    continue

                # Truncate very long key points
                kp_short = kp[:200] if len(kp) > 200 else kp
                concept_id = f"concept:{chunk_id}:{i}"

                # Resurrection guard: a by-id /retract of this concept belief
                # (entity scope) blocks just this key point's re-mint.
                if kp_short in denylist["entity"]:
                    continue

                # Dedup
                if store.find_by_entity_and_source(kp_short, concept_id):
                    continue

                # Base confidence + boost if exam passed. The qualifying score
                # is the best INDEPENDENT score when the gate is armed, else the
                # best of any grader (legacy behaviour, observe/off) -- so FACT
                # in armed mode means "an independent examiner cleared this
                # file", consistent with the FILE belief trust gate.
                confidence = 0.5
                belief_type = BeliefType.OBSERVATION
                qualifying = (
                    exam_scores_indep.get(source_file, 0.0) if enforce
                    else exam_scores.get(source_file, 0.0)
                )
                fact_qualified = qualifying >= _CONCEPT_FACT_THRESHOLD
                if fact_qualified and not is_synth:
                    confidence = min(1.0, confidence + 0.2)
                    belief_type = BeliefType.FACT

                ev = [(BeliefSource.MEMORY_FACT.value, concept_id, confidence)]
                if fact_qualified:
                    ev.append((BeliefSource.EXAM.value, f"exam:{source_file}", qualifying))
                belief = create_belief(
                    entity=kp_short,
                    entity_type=EntityType.CONCEPT,
                    belief_type=belief_type,
                    content=kp_short,
                    confidence=confidence,
                    source=BeliefSource.MEMORY_FACT,
                    source_id=concept_id,
                    tags=normalized_tags,
                    related_entities=[source_file],
                    evidence=ev,
                )
                store.add(belief)
                created += 1

        return created

    def update_from_exam(
        self, store: BeliefStore, exam_record: Dict[str, Any]
    ) -> int:
        """
        Update beliefs based on exam result.

        Pass (score >= 0.7): +0.1 confidence, upgrade OBSERVATION to FACT.
        Fail (score < 0.7): -0.15 confidence, keep OBSERVATION.

        Returns:
            Number of beliefs revised.
        """
        file_id = exam_record.get("file", "")
        score = exam_record.get("score", 0.0)
        if not file_id:
            return 0

        passed = score >= 0.7
        revised = 0

        # Trust gate (armed): a pass promotes to FACT only when an INDEPENDENT
        # examiner graded it. A self-graded pass (grader_independent falsy) must
        # not stamp FACT -- same rule the build side enforces, applied to the
        # runtime promotion path so self-grading cannot back-door a FACT badge.
        independent = bool(exam_record.get("grader_independent"))
        gate_armed = _concept_trust_mode() == "armed"
        # Synthesis blast-radius cap on the runtime path too: a synthesis exam
        # is a closed loop, so a pass must never back-door a FACT badge here.
        is_synth = str(file_id).startswith("synthesis_")

        # Find beliefs related to this file (by source_id or related_entities)
        candidates = []
        for belief in store.get_current():
            if belief.source_id and file_id in belief.source_id:
                candidates.append(belief)
            elif file_id in belief.related_entities:
                candidates.append(belief)

        exam_evidence = [(BeliefSource.EXAM.value, f"exam:{file_id}", score)]

        for belief in candidates:
            if passed:
                new_conf = min(1.0, belief.confidence + 0.1)
                if is_synth:
                    # Closed-loop exam: never promote to FACT, never lift past
                    # the synthesis confidence ceiling.
                    new_type = None
                    new_conf = min(new_conf, _SYNTHESIS_BELIEF_CEIL)
                elif gate_armed and not independent:
                    new_type = None  # self-graded pass: no FACT promotion
                else:
                    new_type = BeliefType.FACT
            else:
                new_conf = max(0.1, belief.confidence - 0.15)
                new_type = None  # Keep current type

            result = store.revise(
                belief.belief_id, new_conf, new_type,
                new_evidence=exam_evidence,
            )
            if result:
                revised += 1

        return revised
