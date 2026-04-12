"""
ExecutionJournal - Full audit trail for task execution.

Complements K10 AuditLog (safety classification) with:
- Task composition (sub-steps)
- Retry tracking
- Duration and status lifecycle

Append-only JSONL, bounded in-memory cache.
"""

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_JOURNAL_FILE = Path("meta_data/execution_journal.jsonl")
_MAX_MEMORY = 200


@dataclass
class JournalEntry:
    """A single task execution record."""

    entry_id: str
    task_description: str
    tool_name: str
    tool_args: Dict[str, Any]
    goal_id: Optional[str] = None
    episode_id: Optional[str] = None

    # Lifecycle
    status: str = "pending"  # pending, running, completed, failed, interrupted
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    duration_ms: float = 0.0

    # Results
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    # Sub-steps
    steps: List[Dict[str, Any]] = field(default_factory=list)

    # Retry
    attempt: int = 1
    max_retries: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "task_description": self.task_description,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "goal_id": self.goal_id,
            "episode_id": self.episode_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "result": self.result,
            "error": self.error,
            "steps": self.steps,
            "attempt": self.attempt,
            "max_retries": self.max_retries,
        }


class ExecutionJournal:
    """Append-only journal of task executions."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _JOURNAL_FILE
        self._entries: List[JournalEntry] = []
        self._lock = threading.Lock()

    def create_entry(
        self,
        task_description: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        goal_id: Optional[str] = None,
        episode_id: Optional[str] = None,
        max_retries: int = 1,
    ) -> JournalEntry:
        """Create and register a new journal entry."""
        entry = JournalEntry(
            entry_id=f"exec-{uuid.uuid4().hex[:12]}",
            task_description=task_description,
            tool_name=tool_name,
            tool_args=tool_args,
            goal_id=goal_id,
            episode_id=episode_id,
            max_retries=max_retries,
        )
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > _MAX_MEMORY:
                self._entries = self._entries[-_MAX_MEMORY:]
        return entry

    def mark_running(self, entry: JournalEntry) -> None:
        """Mark entry as running."""
        entry.status = "running"
        entry.started_at = time.time()

    def add_step(
        self, entry: JournalEntry, step_name: str, result: str, detail: Optional[Dict] = None
    ) -> None:
        """Add a sub-step to the entry."""
        entry.steps.append({
            "step": step_name,
            "result": result,
            "detail": detail or {},
            "timestamp": time.time(),
        })

    def mark_completed(self, entry: JournalEntry, result: Dict[str, Any]) -> None:
        """Mark entry as completed."""
        entry.status = "completed"
        entry.result = result
        entry.finished_at = time.time()
        if entry.started_at:
            entry.duration_ms = (entry.finished_at - entry.started_at) * 1000
        self._persist(entry)

    def mark_failed(self, entry: JournalEntry, error: str) -> None:
        """Mark entry as failed."""
        entry.status = "failed"
        entry.error = error
        entry.finished_at = time.time()
        if entry.started_at:
            entry.duration_ms = (entry.finished_at - entry.started_at) * 1000
        self._persist(entry)

    def get_recent(self, limit: int = 10) -> List[JournalEntry]:
        """Get recent entries."""
        with self._lock:
            return list(self._entries[-limit:])

    def get_by_id(self, entry_id: str) -> Optional[JournalEntry]:
        """Find entry by ID."""
        with self._lock:
            for e in reversed(self._entries):
                if e.entry_id == entry_id:
                    return e
        return None

    def get_stats(self) -> Dict[str, Any]:
        """Execution statistics."""
        with self._lock:
            total = len(self._entries)
            completed = sum(1 for e in self._entries if e.status == "completed")
            failed = sum(1 for e in self._entries if e.status == "failed")
            return {
                "total": total,
                "completed": completed,
                "failed": failed,
                "success_rate": completed / total if total > 0 else 0.0,
            }

    def _persist(self, entry: JournalEntry) -> None:
        """Append entry to JSONL."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("ExecutionJournal: persist error: %s", e)
