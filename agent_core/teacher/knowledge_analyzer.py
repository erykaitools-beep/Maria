"""
KnowledgeAnalyzer - Pure-data analysis of Maria's learning state.

Reads existing JSONL knowledge files and produces structured assessments.
Zero LLM calls - all analysis is done with Python logic.

Used by TeacherAgent to make informed decisions about what to learn next.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from agent_core.world_model.belief_builder import _source_group

logger = logging.getLogger(__name__)

# Window for the "recent" exam figures. A daily frame quoting the lifetime mean
# cannot move: on 07-12..07-15 it printed 83% four days running while the real
# recent scores drifted, because 1347 historical exams outvote a day's worth.
EXAM_WINDOW_HOURS = 24.0


def _parse_iso_utc(value: Any) -> Optional[float]:
    """ISO-8601 stamp (as written by the teacher, trailing 'Z') -> epoch seconds.

    Returns None when absent or unparseable, so callers can skip the record
    rather than silently count it as 1970.

    The 'Z' is mapped to +00:00 rather than stripped: stripping leaves a naive
    datetime that .timestamp() then reads as LOCAL time, shifting every stamp by
    the UTC offset (2h in Berlin summer) and quietly moving the window edges.
    """
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


# Tag normalization
_TAG_STOP_WORDS = {
    "inne", "ogolne", "wiedza", "other", "general", "misc",
    "rozne", "notatki", "tekst", "plik",
}
_TAG_MIN_LEN = 2
_TAG_MAX_LEN = 40

# Cache TTL for topic map (seconds)
_TOPIC_MAP_CACHE_TTL = 60

# Function words carrying no topical signal when a multi-word topic phrase
# (a project sub-goal name) is matched by token overlap. PL + EN.
_TOPIC_STOPWORDS = frozenset({
    "i", "a", "o", "u", "w", "z", "za", "ze", "we", "na", "do", "od", "po",
    "pod", "nad", "przy", "bez", "dla", "jak", "czy", "co", "to", "sie",
    "się", "oraz", "albo", "lub", "jest", "sa", "są", "byc", "być", "ten",
    "ta", "te", "tym", "tego", "ich", "ktore", "które",
    "the", "an", "of", "in", "on", "and", "or", "for", "with",
})


class KnowledgeAnalyzer:
    """
    Analyzes Maria's current knowledge state from JSONL files.

    Reads:
    - knowledge_index.jsonl: file statuses, priorities, exam scores
    - exam_results.jsonl: detailed exam history
    - maria_longterm_memory.jsonl: learned summaries, tags

    All methods are read-only, no side effects.
    """

    def __init__(
        self,
        knowledge_index_path: Optional[Path] = None,
        longterm_memory_path: Optional[Path] = None,
        exam_results_path: Optional[Path] = None,
        input_dir: Optional[Path] = None,
    ):
        # Use config defaults if not provided
        from maria_core.sys.config import (
            KNOWLEDGE_INDEX, LONGTERM_MEMORY, EXAM_RESULTS, INPUT_DIR,
        )
        self.index_path = Path(knowledge_index_path or KNOWLEDGE_INDEX)
        self.memory_path = Path(longterm_memory_path or LONGTERM_MEMORY)
        self.exam_path = Path(exam_results_path or EXAM_RESULTS)
        self.input_dir = Path(input_dir or INPUT_DIR)

        # Cache for topic file map
        self._topic_map_cache: Optional[Dict[str, List[str]]] = None
        self._topic_map_cache_ts: float = 0.0

    def _load_jsonl(self, path: Path, merge_key: str = "") -> List[Dict[str, Any]]:
        """Load records from a JSONL file.

        Args:
            path: Path to JSONL file.
            merge_key: If set, apply MERGE semantics (last record per key wins).
                       This collapses duplicates and bounds memory.
        """
        if not path.exists():
            return []
        if merge_key:
            merged: Dict[str, Dict[str, Any]] = {}
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                rec = json.loads(line)
                                key = rec.get(merge_key, "")
                                if key:
                                    merged[key] = rec
                            except json.JSONDecodeError:
                                continue
            except IOError as e:
                logger.warning(f"Could not read {path}: {e}")
            return list(merged.values())
        from collections import deque
        records: deque = deque(maxlen=5000)
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except IOError as e:
            logger.warning(f"Could not read {path}: {e}")
        return list(records)

    def get_knowledge_snapshot(self) -> Dict[str, Any]:
        """
        Complete snapshot of current knowledge state.

        Returns:
            Dict with:
            - files_by_status: {status: [records]}
            - total_files: int
            - total_chunks_learned: int
            - total_chunks_available: int
            - average_exam_score: float (lifetime)
            - average_exam_score_24h: float (last EXAM_WINDOW_HOURS)
            - exam_count_24h: int (sample size behind average_exam_score_24h)
            - hard_topics: List[Dict]
            - new_files_available: List[Dict]
            - learning_in_progress: List[Dict]
            - input_file_count: int
        """
        index = self._load_jsonl(self.index_path, merge_key="id")
        exams = self._load_jsonl(self.exam_path)

        # Group by status
        files_by_status: Dict[str, List[Dict]] = {}
        total_chunks_learned = 0
        total_chunks_available = 0

        for rec in index:
            status = rec.get("status", "unknown")
            files_by_status.setdefault(status, []).append(rec)
            total_chunks_learned += rec.get("chunks_learned", 0)
            total_chunks_available += rec.get("total_chunks", 0)

        # Average exam score (lifetime -- kept for callers that want the all-time
        # picture; anything reporting on a day must use the _24h pair below).
        all_scores = [e.get("score", 0) for e in exams if "score" in e]
        avg_score = sum(all_scores) / len(all_scores) if all_scores else 0.0

        # Same average over the recent window. The count travels with it because
        # a mean over 2 exams and a mean over 200 are not the same claim, and the
        # reader cannot tell them apart from the percentage alone.
        cutoff = time.time() - EXAM_WINDOW_HOURS * 3600
        recent_scores = []
        for e in exams:
            if "score" not in e:
                continue
            ts = _parse_iso_utc(e.get("timestamp"))
            if ts is not None and ts >= cutoff:
                recent_scores.append(e["score"])
        avg_score_24h = (
            sum(recent_scores) / len(recent_scores) if recent_scores else 0.0
        )

        # Count input files and detect unindexed ones
        input_count = 0
        unindexed_files: List[str] = []
        if self.input_dir.exists():
            indexed_names = {
                rec.get("file", rec.get("id", "")) for rec in index
            }
            for txt in self.input_dir.glob("*.txt"):
                input_count += 1
                if txt.name not in indexed_names:
                    unindexed_files.append(txt.name)

        # Topics from cached topic map
        topic_map = self.get_topic_file_map()
        topics_available = list(topic_map.keys())

        # new_files_available: indexed "new" status + unindexed input files
        new_from_index = sorted(
            files_by_status.get("new", []),
            key=lambda r: r.get("priority", 0),
            reverse=True,
        )
        # Pliki w input/ ktorych nie ma jeszcze w indeksie
        new_from_disk = [{"file": name, "status": "unindexed"} for name in unindexed_files]

        return {
            "files_by_status": files_by_status,
            "total_files": len(index),
            "total_chunks_learned": total_chunks_learned,
            "total_chunks_available": total_chunks_available,
            "average_exam_score": avg_score,
            "average_exam_score_24h": avg_score_24h,
            "exam_count_24h": len(recent_scores),
            "hard_topics": files_by_status.get("hard_topic", []),
            "new_files_available": new_from_index + new_from_disk,
            "learning_in_progress": files_by_status.get("learning", []),
            "learned_ready_for_exam": files_by_status.get("learned", []),
            "input_file_count": input_count,
            "unindexed_file_count": len(unindexed_files),
            "topics_available": topics_available,
        }

    def get_file_details(self, file_id: str) -> Optional[Dict[str, Any]]:
        """
        Detailed info about a specific file.

        Args:
            file_id: File ID (partial match supported)

        Returns:
            Dict with index record + exam history + memory entries,
            or None if not found.
        """
        index = self._load_jsonl(self.index_path, merge_key="id")

        # Find matching record (partial match)
        match = None
        for rec in index:
            name = rec.get("file", rec.get("id", ""))
            if file_id.lower() in name.lower():
                match = rec
                break

        if not match:
            return None

        file_name = match.get("file", match.get("id", ""))

        # Find exam results
        exams = self._load_jsonl(self.exam_path)
        file_exams = [
            e for e in exams
            if file_id.lower() in e.get("file", "").lower()
        ]

        # Find memory entries
        memories = self._load_jsonl(self.memory_path)
        file_memories = [
            m for m in memories
            if file_id.lower() in m.get("source_file", "").lower()
        ]

        return {
            "record": match,
            "file_name": file_name,
            "exams": file_exams,
            "memories": file_memories,
        }

    def find_knowledge_gaps(self) -> List[Dict[str, Any]]:
        """
        Identify knowledge gaps.

        Gap types:
        - partial: File with some chunks learned but not all
        - low_score: Completed but score < 0.7
        - stale: Completed long ago, may need review

        Returns:
            List of gap descriptors sorted by priority.
        """
        index = self._load_jsonl(self.index_path, merge_key="id")
        gaps = []

        for rec in index:
            status = rec.get("status", "")
            file_id = rec.get("file", rec.get("id", ""))

            # Partial learning
            chunks_learned = rec.get("chunks_learned", 0)
            total_chunks = rec.get("total_chunks", 0)
            if status == "learning" and total_chunks > 0 and chunks_learned < total_chunks:
                gaps.append({
                    "type": "partial",
                    "file_id": file_id,
                    "progress": chunks_learned / total_chunks,
                    "priority": 80,  # High priority to finish
                })

            # Low scores on completed
            scores = rec.get("last_scores", [])
            if status == "completed" and scores and scores[-1] < 0.7:
                gaps.append({
                    "type": "low_score",
                    "file_id": file_id,
                    "score": scores[-1],
                    "priority": 60,
                })

            # Exam failed
            if status == "exam_failed":
                gaps.append({
                    "type": "exam_failed",
                    "file_id": file_id,
                    "attempts": rec.get("exam_attempts", 0),
                    "priority": 70,
                })

        gaps.sort(key=lambda g: g["priority"], reverse=True)
        return gaps

    def count_chunks_learned(self, hours: float = EXAM_WINDOW_HOURS) -> int:
        """How many chunks actually landed in long-term memory in the last `hours`.

        Counted from the memory file itself, because that is the only record of a
        chunk being learned. The tempting proxy -- successful learn/fill_gap
        actions in teacher_plans.jsonl -- overcounts: learn_next_chunk returns
        True when a file's chunks are already all in memory, so a no-op logs as a
        success. On 2026-07-16 that gap was 101 actions vs 83 chunks (+22%), all
        18 of them fill_gap retries against one already-completed file.

        Deliberately NOT part of get_knowledge_snapshot(): that runs on the
        planner tick path, and this reads a file an order of magnitude larger.
        """
        cutoff = time.time() - hours * 3600
        count = 0
        for rec in self._load_jsonl(self.memory_path):
            ts = _parse_iso_utc(rec.get("timestamp"))
            if ts is not None and ts >= cutoff:
                count += 1
        return count

    def get_review_candidates(self, min_age_hours: int = 48) -> List[Dict[str, Any]]:
        """
        Completed files that may benefit from review.

        Args:
            min_age_hours: Minimum hours since last update

        Returns:
            List of completed file records older than min_age_hours.
        """
        import time
        from datetime import datetime

        index = self._load_jsonl(self.index_path, merge_key="id")
        now = time.time()
        candidates = []

        for rec in index:
            if rec.get("status") != "completed":
                continue

            updated_at = rec.get("updated_at", "")
            if not updated_at:
                continue

            try:
                updated = datetime.fromisoformat(updated_at.rstrip("Z"))
                hours_since = (now - updated.timestamp()) / 3600
                if hours_since >= min_age_hours:
                    candidates.append(rec)
            except (ValueError, TypeError):
                continue

        return candidates

    def get_tag_frequency_map(self) -> Dict[str, int]:
        """
        Extract tag frequencies from longterm memory.

        Useful for cross-topic connection detection.

        Returns:
            {tag: count} sorted by frequency.
        """
        memories = self._load_jsonl(self.memory_path)
        tag_counts: Dict[str, int] = {}

        for mem in memories:
            tags = mem.get("tags", [])
            for tag in tags:
                tag_lower = tag.lower().strip()
                if tag_lower:
                    tag_counts[tag_lower] = tag_counts.get(tag_lower, 0) + 1

        return dict(sorted(tag_counts.items(), key=lambda x: x[1], reverse=True))

    # -- Topic awareness ------------------------------------

    @staticmethod
    def _normalize_tag(tag: str) -> Optional[str]:
        """Normalize a tag for topic matching. Returns None if rejected."""
        normalized = tag.lower().strip()
        if len(normalized) < _TAG_MIN_LEN or len(normalized) > _TAG_MAX_LEN:
            return None
        if normalized in _TAG_STOP_WORDS:
            return None
        return normalized

    def get_topic_file_map(self) -> Dict[str, List[str]]:
        """
        Build mapping: normalized_tag -> [file_id, ...].

        Reads longterm_memory.jsonl and extracts tags per source_file.
        Cached with TTL to avoid recalculating every tick.

        Returns:
            Dict sorted by file count (most files first).
        """
        now = time.time()
        if (self._topic_map_cache is not None
                and (now - self._topic_map_cache_ts) < _TOPIC_MAP_CACHE_TTL):
            return self._topic_map_cache

        memories = self._load_jsonl(self.memory_path)
        topic_files: Dict[str, set] = {}

        for mem in memories:
            source = mem.get("source_file", "")
            if not source:
                continue
            for tag in mem.get("tags", []):
                normalized = self._normalize_tag(tag)
                if normalized is not None:
                    topic_files.setdefault(normalized, set()).add(source)

        # Rank by INDEPENDENT sources, not raw file count: a tag carried by 100
        # expert_*.txt files is one LLM voice, not 100 (cross-source WYDMUSZKA,
        # audit 2026-06-16). The file LISTS are preserved unchanged (membership
        # consumers need them) -- only the ordering collapses single-origin
        # corpora, so deepen/expand ranking reflects real breadth.
        result = {
            topic: sorted(files)
            for topic, files in sorted(
                topic_files.items(),
                key=lambda x: len({_source_group(f) for f in x[1]}),
                reverse=True,
            )
        }

        self._topic_map_cache = result
        self._topic_map_cache_ts = now
        return result

    def get_files_for_topics(
        self, topics: List[str]
    ) -> List[Tuple[str, float]]:
        """
        Find files matching given topics with scoring.

        Scoring (deterministic):
        - exact tag match: +3.0
        - prefix match (tag starts with topic): +2.0
        - whole-word match (topic is a token of tag): +1.0
        - filename contains topic as a whole word (or topic IS the file): +0.5

        All comparisons case-insensitive.

        Args:
            topics: List of topic search terms

        Returns:
            List of (file_id, score) sorted by score descending.
            Only files with score > 0 included.
        """
        topic_map = self.get_topic_file_map()
        index_records = self._load_jsonl(self.index_path, merge_key="id")

        # All known file IDs from index
        all_file_ids = set()
        for rec in index_records:
            fid = rec.get("id", rec.get("file", ""))
            if fid:
                all_file_ids.add(fid)

        # Also include files from topic_map not yet in index
        for files in topic_map.values():
            all_file_ids.update(files)

        file_scores: Dict[str, float] = {}
        topics_lower = [t.lower().strip() for t in topics if t.strip()]

        if not topics_lower:
            return []

        # Multi-word topics (project sub-goal names are SENTENCES, e.g.
        # "podstawy funding rate na perpetual futures") can never equal a tag,
        # prefix one, or be a single token -- the branches below make them
        # unmatchable to any material. For such topics, match by significant
        # token overlap instead: a tag whose content tokens are contained in
        # the topic's content tokens describes a sub-aspect of it.
        topic_sig: Dict[str, set] = {}
        for topic in topics_lower:
            toks = set(re.findall(r"[^\W_]+", topic, flags=re.UNICODE))
            sig = {
                t for t in toks
                if t not in _TOPIC_STOPWORDS and len(t) >= 3
            }
            if len(sig) >= 2:
                topic_sig[topic] = sig

        # Score from tag matching.
        # The +1.0 branch used to be a raw SUBSTRING test (`topic in tag`), which
        # for a short token like "rna" matched the inside of dozens of unrelated
        # Polish words -- "hepbu(rna)", "alte(rna)tywa", "nadmie(rna)" -- pulling
        # ~50 off-topic files into the pool and poisoning the learn/exam scope and
        # the progress denominator. It now requires a WHOLE-WORD (token) match:
        # "rna" matches the tag "kwas rna" but not the substring inside "hepburna".
        # Exact (+3.0) and prefix (+2.0) keep their broader reach. (2026-06-20)
        for tag, files in topic_map.items():
            # [^\W_]+ tokenizes on whitespace AND underscore (\w keeps "a_b" whole)
            tag_tokens = set(re.findall(r"[^\W_]+", tag, flags=re.UNICODE))
            for topic in topics_lower:
                score = 0.0
                if tag == topic:
                    score = 3.0
                elif tag.startswith(topic):
                    score = 2.0
                elif topic in tag_tokens:
                    score = 1.0
                elif topic in topic_sig:
                    # Multi-word topic: tag's content tokens ⊆ topic's content
                    # tokens. >=2 common tokens, or a single-token tag whose
                    # token is long enough (>=5) to be a real term ("carry"),
                    # so short generic tags ("rate") do not pull noise.
                    tag_sig = {
                        t for t in tag_tokens
                        if t not in _TOPIC_STOPWORDS and len(t) >= 3
                    }
                    common = tag_sig & topic_sig[topic]
                    if len(common) >= 2 or (
                        len(common) == 1 and len(tag_sig) == 1
                        and len(next(iter(common))) >= 5
                    ):
                        score = 1.0

                if score > 0:
                    for fid in files:
                        file_scores[fid] = file_scores.get(fid, 0.0) + score

        # Score from filename matching -- whole-word too, so web_wiki_rna.txt
        # scores but web_wiki_transkrypcja_hepburna.txt no longer does. The
        # `topic == fid` self-match keeps filename-shaped topics working (e.g. a
        # fetch-handoff goal "learn web_wiki_x.txt").
        for fid in all_file_ids:
            fid_lower = fid.lower()
            fid_tokens = set(re.findall(r"[^\W_]+", fid_lower, flags=re.UNICODE))
            fid_stem = fid_lower.rsplit(".", 1)[0]
            for topic in topics_lower:
                if topic in fid_tokens or topic in (fid_lower, fid_stem):
                    file_scores[fid] = file_scores.get(fid, 0.0) + 0.5
                elif (topic in topic_sig
                      and len(fid_tokens & topic_sig[topic]) >= 2):
                    # expert_funding_rate.txt <- "podstawy funding rate na..."
                    file_scores[fid] = file_scores.get(fid, 0.0) + 0.5

        # Sort by score descending, then alphabetically for stability.
        # No top-N cap: whole-word matching already removes the substring noise
        # that used to blow a topic up to 50+ files, and a genuinely broad topic's
        # full set is the honest progress denominator (capping it would silently
        # drop already-verified files and block graduation -- review M3, 06-20).
        results = [
            (fid, score)
            for fid, score in file_scores.items()
            if score > 0
        ]
        results.sort(key=lambda x: (-x[1], x[0]))
        return results

    def files_created_since(self, cutoff_epoch: float) -> set:
        """File ids whose index record was FIRST created at/after ``cutoff_epoch``.

        Freshness floor for /project sub-goals (2026-07-11): a project child must
        not inherit credit from files that pre-existed its own creation -- the
        confirmed false-close vector, where a pre-existing independently-verified
        file merely shares topic tokens with the goal sentence. ``created_at`` is
        stamped only at FIRST index and preserved across re-scans, so a
        pre-existing file keeps its OLD timestamp and is correctly excluded.

        The index ``created_at`` is an ISO-8601 UTC string ('...Z'); a Goal's
        ``created_at`` is a float epoch -- parsed here once. Fail-closed: a record
        with a missing/malformed ``created_at`` is EXCLUDED (an untimestamped file
        cannot prove freshness), which only ever tightens the owned set.
        """
        from datetime import datetime, timezone
        fresh = set()
        for rec in self._load_jsonl(self.index_path, merge_key="id"):
            fid = rec.get("id") or rec.get("file")
            ca = rec.get("created_at")
            if not fid or not isinstance(ca, str):
                continue
            try:
                iso = ca[:-1] if ca.endswith("Z") else ca
                dt = datetime.fromisoformat(iso)
                # 'Z'/naive -> assume UTC; a real offset (e.g. +02:00) is kept.
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ts = dt.timestamp()
            except (ValueError, TypeError):
                continue
            if ts >= cutoff_epoch:
                fresh.add(fid)
        return fresh

    def get_compact_summary(self) -> str:
        """
        Compact text summary of knowledge state for NIM planning prompt.

        Optimized for minimal token usage (~200 tokens).
        """
        snapshot = self.get_knowledge_snapshot()
        by_status = snapshot["files_by_status"]

        lines = [
            f"Pliki ukonczone: {len(by_status.get('completed', []))}",
            f"Pliki nowe: {len(by_status.get('new', []))}",
            f"W trakcie nauki: {len(by_status.get('learning', []))}",
            f"Trudne tematy: {len(by_status.get('hard_topic', []))}",
            f"Sredni wynik egzaminow: {snapshot['average_exam_score']:.0%}",
        ]

        # List hard topics by name (max 3)
        for ht in by_status.get("hard_topic", [])[:3]:
            lines.append(f"  Trudny: {ht.get('id', ht.get('file', '?'))}")

        # List new files (max 5)
        for nf in snapshot.get("new_files_available", [])[:5]:
            lines.append(
                f"  Nowy: {nf.get('id', nf.get('file', '?'))} "
                f"(priorytet: {nf.get('priority', 0):.0f})"
            )

        return "\n".join(lines)
