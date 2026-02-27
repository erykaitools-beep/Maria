"""
TeachingStrategy - Named, parameterized teaching plans.
SpacedRepetitionScheduler - Review scheduling based on exam scores.

Used by TeacherAgent to represent decisions about what to learn next.
"""

import time
from typing import Dict, Any, Optional, List


class TeachingStrategy:
    """
    A named teaching strategy targeting a specific file.

    Strategy types:
    - LEARN_NEW: Learn a new file from scratch
    - DEEPEN: Re-learn with deeper prompts
    - REVIEW: Spaced repetition review
    - FILL_GAP: Focus on weak/hard areas
    """

    LEARN_NEW = "learn_new"
    DEEPEN = "deepen"
    REVIEW = "review"
    FILL_GAP = "fill_gap"

    ALL_TYPES = {LEARN_NEW, DEEPEN, REVIEW, FILL_GAP}

    def __init__(
        self,
        strategy_type: str,
        target_file_id: str,
        params: Optional[Dict[str, Any]] = None,
    ):
        if strategy_type not in self.ALL_TYPES:
            raise ValueError(f"Unknown strategy type: {strategy_type}")
        self.strategy_type = strategy_type
        self.target_file_id = target_file_id
        self.params = params or {}
        self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSONL persistence."""
        return {
            "strategy_type": self.strategy_type,
            "target_file_id": self.target_file_id,
            "params": self.params,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TeachingStrategy":
        """Deserialize from JSONL."""
        strategy = cls(
            strategy_type=data["strategy_type"],
            target_file_id=data["target_file_id"],
            params=data.get("params", {}),
        )
        strategy.created_at = data.get("created_at", time.time())
        return strategy

    def __repr__(self) -> str:
        return (
            f"TeachingStrategy({self.strategy_type}, "
            f"{self.target_file_id!r}, params={self.params})"
        )


class SpacedRepetitionScheduler:
    """
    Simple spaced repetition based on exam scores and time.

    Higher scores = longer intervals between reviews.
    """

    # (min_score, max_score) -> review interval in hours
    INTERVALS = [
        (0.0, 0.6, 24),     # Failed: review next day
        (0.6, 0.7, 48),     # Barely passed: 2 days
        (0.7, 0.8, 120),    # OK: 5 days
        (0.8, 0.9, 336),    # Good: 14 days
        (0.9, 1.01, 720),   # Excellent: 30 days
    ]

    def get_review_interval_hours(self, last_score: float) -> int:
        """
        Return hours until next review based on last exam score.

        Args:
            last_score: Exam score 0.0-1.0

        Returns:
            Hours until next review
        """
        for min_s, max_s, hours in self.INTERVALS:
            if min_s <= last_score < max_s:
                return hours
        # Default for score >= 1.0
        return 720

    def is_due_for_review(
        self,
        file_record: Dict[str, Any],
        current_time: Optional[float] = None,
    ) -> bool:
        """
        Check if a completed file is due for review.

        Args:
            file_record: Knowledge index record with last_scores, updated_at
            current_time: Override current time (for testing)

        Returns:
            True if review is due
        """
        if file_record.get("status") != "completed":
            return False

        scores = file_record.get("last_scores", [])
        if not scores:
            return False

        last_score = scores[-1]
        interval_hours = self.get_review_interval_hours(last_score)

        updated_at = file_record.get("updated_at", "")
        if not updated_at:
            return False

        try:
            from datetime import datetime
            updated = datetime.fromisoformat(updated_at.rstrip("Z"))
            now = current_time or time.time()
            now_dt = datetime.fromtimestamp(now)
            hours_since = (now_dt - updated).total_seconds() / 3600
            return hours_since >= interval_hours
        except (ValueError, TypeError):
            return False

    def get_due_reviews(
        self,
        knowledge_snapshot: Dict[str, Any],
        current_time: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return all completed files due for review, sorted by urgency.

        Most overdue files come first.

        Args:
            knowledge_snapshot: From KnowledgeAnalyzer.get_knowledge_snapshot()
            current_time: Override current time (for testing)

        Returns:
            List of file records due for review
        """
        completed = knowledge_snapshot.get("files_by_status", {}).get("completed", [])
        due = []
        for rec in completed:
            if self.is_due_for_review(rec, current_time):
                due.append(rec)

        # Sort by updated_at (oldest first = most overdue)
        due.sort(key=lambda r: r.get("updated_at", ""))
        return due
