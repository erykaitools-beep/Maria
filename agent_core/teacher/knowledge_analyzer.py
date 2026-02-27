"""
KnowledgeAnalyzer - Pure-data analysis of Maria's learning state.

Reads existing JSONL knowledge files and produces structured assessments.
Zero LLM calls - all analysis is done with Python logic.

Used by TeacherAgent to make informed decisions about what to learn next.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


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

    def _load_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        """Load records from a JSONL file."""
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
        except IOError as e:
            logger.warning(f"Could not read {path}: {e}")
        return records

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
        index = self._load_jsonl(self.index_path)
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

        # Count input files
        input_count = 0
        if self.input_dir.exists():
            input_count = len(list(self.input_dir.glob("*.txt")))

        return {
            "files_by_status": files_by_status,
            "total_files": len(index),
            "total_chunks_learned": total_chunks_learned,
            "total_chunks_available": total_chunks_available,
            "average_exam_score": avg_score,
            "hard_topics": files_by_status.get("hard_topic", []),
            "new_files_available": sorted(
                files_by_status.get("new", []),
                key=lambda r: r.get("priority", 0),
                reverse=True,
            ),
            "learning_in_progress": files_by_status.get("learning", []),
            "learned_ready_for_exam": files_by_status.get("learned", []),
            "input_file_count": input_count,
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
        index = self._load_jsonl(self.index_path)

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
        index = self._load_jsonl(self.index_path)
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

        index = self._load_jsonl(self.index_path)
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
