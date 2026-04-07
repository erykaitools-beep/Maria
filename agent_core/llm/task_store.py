"""
Persistent task store for Claude/Codex CLI tasks.

Saves tasks to JSONL BEFORE execution so they survive restarts.
After restart, incomplete tasks are marked INTERRUPTED.

File: meta_data/claude_tasks.jsonl
"""

import json
import logging
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_META_DIR = Path(__file__).resolve().parents[2] / "meta_data"
_DEFAULT_TASKS_PATH = _META_DIR / "claude_tasks.jsonl"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    INTERRUPTED = "INTERRUPTED"  # process died mid-task


class TaskStore:
    """
    JSONL-backed task persistence.

    Lifecycle: PENDING -> RUNNING -> COMPLETED/FAILED/TIMEOUT
    On restart: any RUNNING/PENDING -> INTERRUPTED
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path or _DEFAULT_TASKS_PATH)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def create_task(
        self,
        task_text: str,
        backend: str,
        source: str,
        timeout_s: float = 180,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Save a new task BEFORE execution. Returns task_id."""
        task_id = uuid.uuid4().hex[:12]
        record = {
            "task_id": task_id,
            "status": TaskStatus.PENDING.value,
            "task_text": task_text,
            "backend": backend,
            "source": source,
            "timeout_s": timeout_s,
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "duration_ms": None,
            "error": None,
            "result_summary": None,
        }
        if metadata:
            record["metadata"] = {
                k: str(v)[:200] for k, v in metadata.items()
            }
        self._append(record)
        return task_id

    def mark_running(self, task_id: str) -> None:
        """Mark task as started."""
        self._update(task_id, {
            "status": TaskStatus.RUNNING.value,
            "started_at": time.time(),
        })

    def mark_completed(
        self, task_id: str, result_summary: Optional[str] = None
    ) -> None:
        """Mark task as successfully completed."""
        now = time.time()
        task = self._find(task_id)
        started = task.get("started_at", now) if task else now
        self._update(task_id, {
            "status": TaskStatus.COMPLETED.value,
            "finished_at": now,
            "duration_ms": round((now - started) * 1000),
            "result_summary": (result_summary[:500] if result_summary else None),
        })

    def mark_failed(self, task_id: str, error: str) -> None:
        """Mark task as failed."""
        now = time.time()
        task = self._find(task_id)
        started = task.get("started_at", now) if task else now
        self._update(task_id, {
            "status": TaskStatus.FAILED.value,
            "finished_at": now,
            "duration_ms": round((now - started) * 1000),
            "error": error[:300],
        })

    def mark_timeout(self, task_id: str, timeout_s: float) -> None:
        """Mark task as timed out."""
        now = time.time()
        task = self._find(task_id)
        started = task.get("started_at", now) if task else now
        self._update(task_id, {
            "status": TaskStatus.TIMEOUT.value,
            "finished_at": now,
            "duration_ms": round((now - started) * 1000),
            "error": f"timeout after {timeout_s:.0f}s",
        })

    def recover_interrupted(self) -> List[Dict]:
        """
        Mark any PENDING/RUNNING tasks as INTERRUPTED.
        Call once at startup. Returns list of interrupted tasks.
        """
        interrupted = []
        tasks = self._load_all()
        now = time.time()
        for t in tasks:
            if t.get("status") in (
                TaskStatus.PENDING.value, TaskStatus.RUNNING.value
            ):
                t["status"] = TaskStatus.INTERRUPTED.value
                t["finished_at"] = now
                t["error"] = "process restarted before completion"
                interrupted.append(t)

        if interrupted:
            self._rewrite(tasks)
            logger.info(
                "[TaskStore] Marked %d interrupted tasks", len(interrupted)
            )
        return interrupted

    def get_recent(self, limit: int = 10) -> List[Dict]:
        """Get most recent tasks."""
        tasks = self._load_all()
        return tasks[-limit:]

    def get_task(self, task_id: str) -> Optional[Dict]:
        """Get task by ID."""
        return self._find(task_id)

    # -- Private --

    def _append(self, record: Dict) -> None:
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except IOError as e:
            logger.warning("[TaskStore] Write failed: %s", e)

    def _load_all(self) -> List[Dict]:
        if not self._path.exists():
            return []
        records = []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
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

    def _find(self, task_id: str) -> Optional[Dict]:
        for t in reversed(self._load_all()):
            if t.get("task_id") == task_id:
                return t
        return None

    def _update(self, task_id: str, updates: Dict) -> None:
        """Update task in-place by rewriting JSONL."""
        tasks = self._load_all()
        found = False
        for t in reversed(tasks):
            if t.get("task_id") == task_id:
                t.update(updates)
                found = True
                break
        if found:
            self._rewrite(tasks)

    def _rewrite(self, tasks: List[Dict]) -> None:
        try:
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                for t in tasks:
                    f.write(json.dumps(t, ensure_ascii=False) + "\n")
            tmp.replace(self._path)
        except IOError as e:
            logger.warning("[TaskStore] Rewrite failed: %s", e)
