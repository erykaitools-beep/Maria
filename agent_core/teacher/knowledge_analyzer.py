"""
KnowledgeAnalyzer - Pure-data analysis of Maria's learning state.

Reads existing JSONL knowledge files and produces structured assessments.
Zero LLM calls - all analysis is done with Python logic.

Used by TeacherAgent to make informed decisions about what to learn next.
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Tag normalization
_TAG_STOP_WORDS = {
    "inne", "ogolne", "wiedza", "other", "general", "misc",
    "rozne", "notatki", "tekst", "plik",
}
_TAG_MIN_LEN = 2
_TAG_MAX_LEN = 40

# Cache TTL for topic map (seconds)
_TOPIC_MAP_CACHE_TTL = 60


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
            - average_exam_score: float
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

        # Average exam score
        all_scores = [e.get("score", 0) for e in exams if "score" in e]
        avg_score = sum(all_scores) / len(all_scores) if all_scores else 0.0

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

        # Sort by file count descending, convert sets to sorted lists
        result = {
            topic: sorted(files)
            for topic, files in sorted(
                topic_files.items(),
                key=lambda x: len(x[1]),
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
        - substring match (topic in tag): +1.0
        - filename contains topic: +0.5

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

        # Score from tag matching
        for tag, files in topic_map.items():
            for topic in topics_lower:
                score = 0.0
                if tag == topic:
                    score = 3.0
                elif tag.startswith(topic):
                    score = 2.0
                elif topic in tag:
                    score = 1.0

                if score > 0:
                    for fid in files:
                        file_scores[fid] = file_scores.get(fid, 0.0) + score

        # Score from filename matching
        for fid in all_file_ids:
            fid_lower = fid.lower()
            for topic in topics_lower:
                if topic in fid_lower:
                    file_scores[fid] = file_scores.get(fid, 0.0) + 0.5

        # Sort by score descending, then alphabetically for stability
        results = [
            (fid, score)
            for fid, score in file_scores.items()
            if score > 0
        ]
        results.sort(key=lambda x: (-x[1], x[0]))
        return results

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
