"""Expiry sweep for pending self-repair tasks."""

from __future__ import annotations

import logging
import time
import importlib
from dataclasses import replace
from typing import Any, List, Optional

from agent_core.conductor.task_model import TaskStatus
from agent_core.self_repair.task_creator import _send_notification

logger = logging.getLogger("agent_core.self_repair")

# A maria self-repair task should never legitimately sit IN_PROGRESS (it is
# never autonomously dispatched -- ADR-031, /approve_repair closes it). If one
# is stuck there past this generous grace (e.g. the daemon was killed mid-flight
# before the dispatcher's BLOCKED reaper could run), nothing else recovers it
# (audit 2026-06-16 #18). 2h is well beyond any real operation.
STALE_IN_PROGRESS_SECONDS = 2 * 3600


def expire_stale_repair_tasks(
    conductor: Any,
    bulletin_store: Any,
    notifier: Any,
    now: Optional[float] = None,
) -> List[str]:
    """Sweep self-repair tasks that can no longer make progress.

    Two cases are cleaned so the queue never accumulates dead repair tasks --
    the operator should not have to clear them by hand:

    - PENDING past ``expires_at`` -- operator never approved within 24h.
    - BLOCKED -- autonomous dispatch dead-ended (e.g. the dirty-workspace
      safeguard during a dev session). These cannot recover on their own, so
      they are cleaned immediately rather than lingering forever. The old sweep
      only looked at PENDING, so an approved-then-blocked task zombified.
    """
    current = time.time() if now is None else now

    expired_ids: List[str] = []
    for task in _list_repair_tasks(conductor, TaskStatus.PENDING):
        expires_at = task.artifacts.get("expires_at")
        if not isinstance(expires_at, (int, float)) or float(expires_at) > current:
            continue
        if _cancel_repair_task(
            conductor, bulletin_store, task, current,
            notes="expired_no_response after 24h",
            reason="task_expired",
        ):
            expired_ids.append(task.task_id)

    cleaned_ids: List[str] = []
    for task in _list_repair_tasks(conductor, TaskStatus.BLOCKED):
        if _cancel_repair_task(
            conductor, bulletin_store, task, current,
            notes="cleaned_up: blocked self-repair cannot proceed autonomously",
            reason="task_blocked_cleanup",
        ):
            cleaned_ids.append(task.task_id)

    stuck_ids: List[str] = []
    for task in _list_repair_tasks(conductor, TaskStatus.IN_PROGRESS):
        last_ts = getattr(task, "updated_at", None) or getattr(task, "started_at", None) or 0.0
        if not isinstance(last_ts, (int, float)):
            continue
        if (current - float(last_ts)) < STALE_IN_PROGRESS_SECONDS:
            continue
        if _cancel_repair_task(
            conductor, bulletin_store, task, current,
            notes="cleaned_up: in_progress self-repair stuck past grace",
            reason="task_stuck_cleanup",
        ):
            stuck_ids.append(task.task_id)

    if expired_ids:
        _send_notification(
            notifier,
            "[Self-repair] Expired without operator approval:\n"
            + "\n".join(f"- {task_id}" for task_id in expired_ids),
        )
    if cleaned_ids:
        _send_notification(
            notifier,
            "[Self-repair] Cleaned up blocked tasks (could not proceed):\n"
            + "\n".join(f"- {task_id}" for task_id in cleaned_ids),
        )
    if stuck_ids:
        _send_notification(
            notifier,
            "[Self-repair] Cleaned up stuck in_progress tasks:\n"
            + "\n".join(f"- {task_id}" for task_id in stuck_ids),
        )
    return expired_ids + cleaned_ids + stuck_ids


def _list_repair_tasks(conductor: Any, status: "TaskStatus") -> List[Any]:
    """List maria self-repair tasks in a given status (safe on errors)."""
    try:
        if status == TaskStatus.PENDING and hasattr(
            conductor, "get_pending_repair_tasks"
        ):
            return conductor.get_pending_repair_tasks()
        return [
            t for t in conductor.list_tasks(project="maria", status=status)
            if getattr(t, "phase", "") == "self_repair"
        ]
    except Exception:
        logger.warning("[SelfRepair] expiry list failed", exc_info=True)
        return []


def _cancel_repair_task(
    conductor: Any,
    bulletin_store: Any,
    task: Any,
    current: float,
    notes: str,
    reason: str,
) -> bool:
    """Move one repair task to CANCELLED and resolve its bulletin."""
    try:
        updated = replace(
            task,
            status=TaskStatus.CANCELLED,
            updated_at=current,
            completed_at=current,
            notes=notes,
        )
        conductor.add_task(updated)
        _close_linked_bulletin(bulletin_store, task.task_id, reason)
        return True
    except Exception:
        logger.warning(
            "[SelfRepair] expiry failed for %s", task.task_id, exc_info=True
        )
        return False


def _close_linked_bulletin(
    bulletin_store: Any, task_id: str, reason: str = "task_expired"
) -> None:
    if bulletin_store is None:
        return
    try:
        bulletin_model = importlib.import_module(
            "agent_core.bulletin.bulletin_model"
        )
        resolved_status = bulletin_model.EntryStatus.RESOLVED

        for entry in bulletin_store.get_open():
            metadata = getattr(entry, "metadata", {}) or {}
            if metadata.get("task_id") != task_id:
                continue
            metadata["close_reason"] = reason
            entry.metadata = metadata
            bulletin_store.update_status(
                entry.entry_id,
                resolved_status,
                reason,
            )
    except Exception:
        logger.warning("[SelfRepair] bulletin close failed", exc_info=True)
