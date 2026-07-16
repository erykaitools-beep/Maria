"""
Conductor — Task queue (JSONL-backed, MERGE semantics).

Mirrors BulletinStore's persistence pattern: append-only JSONL on disk,
in-memory dict for lookups, lazy-load on first access. Last write wins
on the same task_id, so updates are simple appends.

Default path: meta_data/market_task_queue.jsonl (one queue file per
project — each project gets its own queue keyed by ``project`` field).
The path can be overridden for tests and multi-project setups.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.conductor.task_model import (
    Assignee,
    Task,
    TaskStatus,
)

logger = logging.getLogger(__name__)

_DEFAULT_PATH = (
    Path(__file__).resolve().parents[2] / "meta_data" / "market_task_queue.jsonl"
)


class TaskQueue:
    """JSONL-backed store of delegated build tasks."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _DEFAULT_PATH
        self._tasks: Optional[Dict[str, Task]] = None
        self._last_loaded_mtime: float = 0.0
        # Reentrant lock so the three in-process writers (tick-loop dispatcher,
        # Telegram handler, Web UI) genuinely serialize read-modify-write on the
        # shared dict instead of racing. Docstrings elsewhere long CLAIMED a
        # per-store lock that did not exist (audit 2026-06-16 #3); this is it.
        # RLock because public methods nest (post -> _ensure_loaded -> _append).
        self._lock = threading.RLock()

    # --- Persistence -------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Load tasks if not yet loaded, OR if the file changed on disk.

        The mtime check makes the queue safe for external writers (e.g.
        ``scripts/seed_task_*.py`` running in a different process while
        Maria's daemon is up). Without it Maria caches at boot and never
        sees externally-appended tasks until the next restart.

        On corrupted JSON we still load whatever lines we can — the same
        forgiving behavior as before. _last_loaded_mtime is only updated
        on a clean read so transient stat failures don't poison the cache.
        """
        current_mtime = 0.0
        if self._path.exists():
            try:
                current_mtime = self._path.stat().st_mtime
            except OSError:
                current_mtime = 0.0

        if self._tasks is not None and current_mtime <= self._last_loaded_mtime:
            return
        self._tasks = {}
        if not self._path.exists():
            self._last_loaded_mtime = 0.0
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        task = Task.from_dict(d)
                        self._tasks[task.task_id] = task  # MERGE
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.warning(
                            "[CONDUCTOR] Skipping corrupted task line %s: %s",
                            line_no,
                            e,
                        )
            self._last_loaded_mtime = current_mtime
        except OSError as e:
            logger.error(f"[CONDUCTOR] Cannot read {self._path}: {e}")

    def _append(self, task: Task) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(task.to_dict(), ensure_ascii=False) + "\n")
            # Bump mtime cache so our own append doesn't trigger a needless
            # full reload on the next read.
            try:
                self._last_loaded_mtime = self._path.stat().st_mtime
            except OSError:
                pass
        except OSError as e:
            logger.error(f"[CONDUCTOR] Cannot write {self._path}: {e}")

    # --- CRUD --------------------------------------------------------

    def post(self, task: Task) -> Task:
        """Insert or update a task. Returns the persisted task."""
        with self._lock:
            self._ensure_loaded()
            assert self._tasks is not None
            self._tasks[task.task_id] = task
            self._append(task)
            logger.info(
                "[CONDUCTOR] Posted: %s project=%s phase=%s status=%s",
                task.task_id,
                task.project,
                task.phase,
                task.status.value,
            )
            return task

    def update(self, task_id: str, **fields: Any) -> Optional[Task]:
        """Apply partial updates to an existing task. Returns updated
        task or None if task_id is unknown.

        ``status`` and ``assignee`` accept either Enum or string.
        """
        with self._lock:
            self._ensure_loaded()
            assert self._tasks is not None
            existing = self._tasks.get(task_id)
            if existing is None:
                logger.warning("[CONDUCTOR] update: unknown task_id %s", task_id)
                return None

            d = existing.to_dict()
            for key, value in fields.items():
                if value is None and key not in ("started_at", "completed_at", "estimated_minutes"):
                    continue
                if key == "status" and isinstance(value, TaskStatus):
                    d["status"] = value.value
                elif key == "assignee" and isinstance(value, Assignee):
                    d["assignee"] = value.value
                else:
                    d[key] = value
            d["updated_at"] = time.time()

            updated = Task.from_dict(d)
            self._tasks[task_id] = updated
            self._append(updated)
            return updated

    def get(self, task_id: str) -> Optional[Task]:
        with self._lock:
            self._ensure_loaded()
            assert self._tasks is not None
            return self._tasks.get(task_id)

    # --- Queries -----------------------------------------------------

    def list(
        self,
        project: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        include_terminal: bool = True,
    ) -> List[Task]:
        """Return tasks optionally filtered by project and/or status."""
        with self._lock:
            self._ensure_loaded()
            assert self._tasks is not None
            out: List[Task] = []
            for t in self._tasks.values():
                if project is not None and t.project != project:
                    continue
                if status is not None and t.status != status:
                    continue
                if not include_terminal and t.is_terminal:
                    continue
                out.append(t)
            return out

    def get_next(self, project: str) -> Optional[Task]:
        """Pick the highest-priority PENDING task in ``project`` whose
        dependencies are all DONE. Returns None if nothing is ready."""
        with self._lock:
            self._ensure_loaded()
            assert self._tasks is not None
            candidates: List[Task] = []
            for t in self._tasks.values():
                if t.project != project:
                    continue
                if t.status != TaskStatus.PENDING:
                    continue
                if not self._deps_satisfied(t):
                    continue
                candidates.append(t)
            if not candidates:
                return None
            # Highest priority first; tie-break: oldest created_at wins so a
            # backlog drains in submission order rather than oscillating.
            candidates.sort(key=lambda x: (-x.priority, x.created_at))
            return candidates[0]

    def _deps_satisfied(self, task: Task) -> bool:
        assert self._tasks is not None
        for dep_id in task.dependencies:
            dep = self._tasks.get(dep_id)
            if dep is None or dep.status != TaskStatus.DONE:
                return False
        return True

    # --- Aggregates --------------------------------------------------

    def stats(self, project: Optional[str] = None) -> Dict[str, int]:
        """Counts per status, optionally scoped to one project."""
        with self._lock:
            self._ensure_loaded()
            assert self._tasks is not None
            out: Dict[str, int] = {s.value: 0 for s in TaskStatus}
            out["total"] = 0
            for t in self._tasks.values():
                if project is not None and t.project != project:
                    continue
                out[t.status.value] += 1
                out["total"] += 1
            return out

    def projects(self) -> List[str]:
        with self._lock:
            self._ensure_loaded()
            assert self._tasks is not None
            return sorted({t.project for t in self._tasks.values()})
