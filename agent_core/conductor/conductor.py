"""
Conductor — orchestrator facade.

The conductor is Maria's *project manager* role: she does not write
market-agent code, she does not call exchanges. She tracks a queue of
delegated tasks (TaskQueue), knows which is next, and keeps a
human-readable status snapshot (BuildStatus) for the operator.

Concretely:
- Per tick: recompute BuildStatus for every project that has tasks,
  cheaply (read-only, no LLM).
- On demand (Telegram, Web UI, REPL): hand back the next task or the
  current status.
- Mark task lifecycle transitions when the assignee reports back.

Conductor is deliberately small — heavy lifting lives in TaskQueue and
BuildStatusStore. The class exists to give callers one entry point and
keep the per-project status math in one place.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from agent_core.conductor.build_status import BuildStatus, BuildStatusStore
from agent_core.conductor.task_model import (
    Assignee,
    BUILDER_ASSIGNEES,
    Task,
    TaskStatus,
)
from agent_core.conductor.task_queue import TaskQueue

logger = logging.getLogger(__name__)


class Conductor:
    """Read-only orchestrator over a TaskQueue + BuildStatusStore.

    Pure state management — no LLM, no subprocess invocation. Telegram
    commands and Web UI read from the status store; assignees post
    status updates through the lifecycle methods below.
    """

    def __init__(
        self,
        queue: Optional[TaskQueue] = None,
        status_store: Optional[BuildStatusStore] = None,
    ):
        self._queue = queue or TaskQueue()
        self._status = status_store or BuildStatusStore()

    # --- Tick (cheap, called from homeostasis) -----------------------

    def tick(self) -> None:
        """Refresh BuildStatus for every project with at least one task.

        O(N) over tasks — N is small (tens to a few hundred). Safe to
        call every cycle; the I/O is one JSONL read + one JSON write.
        """
        for project in self._queue.projects():
            self._refresh_status(project)

    def _refresh_status(self, project: str) -> BuildStatus:
        stats = self._queue.stats(project=project)
        all_tasks = self._queue.list(project=project)

        # Pick "current phase": phase tag of the most recent IN_PROGRESS
        # task; fall back to phase of the next pending task.
        in_progress = [t for t in all_tasks if t.status == TaskStatus.IN_PROGRESS]
        in_progress.sort(key=lambda t: t.updated_at, reverse=True)
        current_phase = in_progress[0].phase if in_progress else ""
        if not current_phase:
            nxt = self._queue.get_next(project)
            current_phase = nxt.phase if nxt else ""

        # Last completed: most recent DONE.
        done = [t for t in all_tasks if t.status == TaskStatus.DONE]
        done.sort(key=lambda t: t.completed_at or t.updated_at, reverse=True)
        last_done_id = done[0].task_id if done else None

        # Next task ready to assign.
        nxt = self._queue.get_next(project)
        next_id = nxt.task_id if nxt else None

        # Blockers: distinct human-readable strings from BLOCKED tasks.
        blocked_tasks = [t for t in all_tasks if t.status == TaskStatus.BLOCKED]
        blockers: List[str] = []
        seen = set()
        for t in blocked_tasks:
            for b in t.blockers:
                if b not in seen:
                    blockers.append(b)
                    seen.add(b)

        total = stats["total"]
        progress_pct = (stats["done"] / total) if total else 0.0

        status = BuildStatus(
            project=project,
            current_phase=current_phase,
            progress_pct=progress_pct,
            blockers=blockers,
            last_completed_task_id=last_done_id,
            next_task_id=next_id,
            pending_count=stats["pending"],
            in_progress_count=stats["in_progress"],
            done_count=stats["done"],
            blocked_count=stats["blocked"],
            total_count=total,
        )
        self._status.save(status)
        return status

    # --- Read API ----------------------------------------------------

    def get_status(self, project: str) -> Optional[BuildStatus]:
        return self._status.load(project)

    def get_next_task(self, project: str) -> Optional[Task]:
        """Return the next assignable PENDING task regardless of
        assignee. Used by Telegram/Web UI display and by the operator
        to preview what's coming up — including human-only tasks."""
        return self._queue.get_next(project)

    def get_autonomous_next(self, project: str) -> Optional[Task]:
        """Return the next PENDING task Maria may autonomously route.

        Honors ``BUILDER_ASSIGNEES`` — Codex and the agent-under-
        construction are eligible; Claude CLI / OPERATOR / UNASSIGNED
        are not. Tasks marked ``approval_required`` are held for
        operator approval before autonomous dispatch. Used when the tick
        loop wants something to dispatch without human interaction.

        FAIL-CLOSED on the live repo (audit 2026-06-16): for project=='maria'
        (whose dispatcher targets /home/maria/maria, the running repo) a
        MISSING ``approval_required`` key defaults to True (held) -- a forgotten
        flag must never auto-dispatch Codex onto production. self_repair-phase
        tasks are NEVER autonomously routed regardless of the flag: per ADR-031
        self-repair is an ALERT, ``/approve_repair`` CLOSES it, it is never
        dispatched. Other projects keep the fail-open default (legit autonomous
        builds in their own sandboxes).
        """
        # Live-repo dispatch defaults to held; sandboxed projects to dispatchable.
        approval_default = project == "maria"
        ready = [
            t for t in self._queue.list(project=project, status=TaskStatus.PENDING)
            if t.assignee in BUILDER_ASSIGNEES
            and self._deps_satisfied(t)
            and t.phase != "self_repair"
            and t.phase != "effector_undo"
            and not t.artifacts.get("approval_required", approval_default)
        ]
        if not ready:
            return None
        ready.sort(key=lambda x: (-x.priority, x.created_at))
        return ready[0]

    def _deps_satisfied(self, task: Task) -> bool:
        # Re-implements the queue's private check so we can reuse the
        # dependency-aware filter from this layer without exposing it
        # broadly.
        for dep_id in task.dependencies:
            dep = self._queue.get(dep_id)
            if dep is None or dep.status != TaskStatus.DONE:
                return False
        return True

    def list_projects(self) -> List[str]:
        return self._queue.projects()

    def list_tasks(
        self,
        project: Optional[str] = None,
        status: Optional[TaskStatus] = None,
    ) -> List[Task]:
        return self._queue.list(project=project, status=status)

    def get_pending_repair_tasks(self) -> List[Task]:
        """List maria self-repair tasks waiting for operator approval."""
        return [
            task for task in self._queue.list(
                project="maria",
                status=TaskStatus.PENDING,
            )
            if task.phase == "self_repair"
        ]

    def get_pending_undo_suggestions(self) -> List[Task]:
        """List maria effector-undo suggestions waiting for operator approval."""
        return [
            task for task in self._queue.list(
                project="maria",
                status=TaskStatus.PENDING,
            )
            if task.phase == "effector_undo"
        ]

    # --- Lifecycle (assignees / operator) ----------------------------

    def add_task(self, task: Task) -> Task:
        """Insert a new task. The status snapshot will refresh on the
        next tick — callers who need it now should call ``tick()``."""
        return self._queue.post(task)

    def mark_in_progress(
        self, task_id: str, assignee: Assignee
    ) -> Optional[Task]:
        return self._queue.update(
            task_id,
            status=TaskStatus.IN_PROGRESS,
            assignee=assignee,
            started_at=time.time(),
        )

    def mark_done(
        self,
        task_id: str,
        artifacts: Optional[Dict] = None,
        notes: str = "",
    ) -> Optional[Task]:
        existing = self._queue.get(task_id)
        if existing is None:
            return None
        merged_artifacts = dict(existing.artifacts)
        if artifacts:
            merged_artifacts.update(artifacts)
        return self._queue.update(
            task_id,
            status=TaskStatus.DONE,
            artifacts=merged_artifacts,
            completed_at=time.time(),
            notes=notes or existing.notes,
        )

    def mark_blocked(
        self, task_id: str, reason: str
    ) -> Optional[Task]:
        existing = self._queue.get(task_id)
        if existing is None:
            return None
        blockers = list(existing.blockers)
        if reason and reason not in blockers:
            blockers.append(reason)
        return self._queue.update(
            task_id,
            status=TaskStatus.BLOCKED,
            blockers=blockers,
        )

    def mark_pending(self, task_id: str) -> Optional[Task]:
        """Resurrect a BLOCKED or CANCELLED task back into the pool."""
        existing = self._queue.get(task_id)
        if existing is None:
            return None
        return self._queue.update(
            task_id,
            status=TaskStatus.PENDING,
            blockers=[],
        )

    def requeue_stale_in_progress(
        self,
        project: str,
        assignee: Assignee = Assignee.CODEX,
        max_requeues: int = 2,
    ) -> List[Task]:
        """Boot-time sweep: return orphaned IN_PROGRESS tasks to the pool.

        Dispatch is synchronous inside the tick loop, so on a fresh process
        no dispatch can be in flight -- any IN_PROGRESS task with the given
        assignee is an orphan from a crash mid-dispatch (2026-06-30: the
        liveness watchdog os._exit'ed during a Codex run; os._exit bypasses
        the dispatcher's BLOCKED-on-exception handler, stranding the task).

        Each sweep increments ``stale_requeue_count`` in task.artifacts.
        Past ``max_requeues`` the task goes BLOCKED instead -- a task whose
        dispatch keeps dying would otherwise crash-loop on every boot.

        Call ONLY at process boot, before the tick loop starts. Mid-run an
        IN_PROGRESS task means a dispatch genuinely in flight.
        """
        requeued: List[Task] = []
        stale = self._queue.list(
            project=project, status=TaskStatus.IN_PROGRESS
        )
        for task in stale:
            if task.assignee != assignee:
                continue
            artifacts = dict(task.artifacts)
            count = int(artifacts.get("stale_requeue_count", 0)) + 1
            artifacts["stale_requeue_count"] = count
            if count > max_requeues:
                updated = self._queue.update(
                    task.task_id,
                    status=TaskStatus.BLOCKED,
                    artifacts=artifacts,
                    blockers=list(task.blockers) + [
                        f"orphaned in_progress {count}x (crash mid-dispatch?)"
                    ],
                )
            else:
                updated = self._queue.update(
                    task.task_id,
                    status=TaskStatus.PENDING,
                    artifacts=artifacts,
                )
            if updated is not None:
                requeued.append(updated)
        return requeued
