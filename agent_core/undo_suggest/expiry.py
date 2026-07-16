"""Expiry sweep for pending/blocked effector-undo suggestions.

Mirrors ``agent_core/self_repair/expiry.py`` so the conductor queue never
accumulates dead undo-suggestion tasks (the operator should not have to clear
them by hand):

- PENDING past ``expires_at`` (24h) -- the operator never approved.
- BLOCKED -- ``/approve_undo`` ran the inverse and it FAILED (the handler marks
  the task BLOCKED with the failure reason). It cannot recover on its own, so it
  is cleaned immediately. The underlying undo journal already records the
  ``undo_failed`` status, so the operator can retry manually via /undo_action.

Both transitions move the task to CANCELLED and resolve the linked bulletin.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import Any, List, Optional

from agent_core.conductor.task_model import TaskStatus
from agent_core.self_repair.expiry import _close_linked_bulletin
from agent_core.self_repair.task_creator import _send_notification
from agent_core.undo_suggest.suggestion_creator import UNDO_SUGGEST_PHASE

logger = logging.getLogger("agent_core.undo_suggest")


def expire_stale_undo_suggestions(
    conductor: Any,
    bulletin_store: Any,
    notifier: Any,
    now: Optional[float] = None,
) -> List[str]:
    """Sweep undo-suggestion tasks that can no longer make progress."""
    current = time.time() if now is None else now

    expired_ids: List[str] = []
    for task in _list_undo_tasks(conductor, TaskStatus.PENDING):
        expires_at = task.artifacts.get("expires_at")
        if not isinstance(expires_at, (int, float)) or float(expires_at) > current:
            continue
        if _cancel_undo_task(
            conductor, bulletin_store, task, current,
            notes="expired_no_response after 24h",
            reason="suggestion_expired",
        ):
            expired_ids.append(task.task_id)

    cleaned_ids: List[str] = []
    for task in _list_undo_tasks(conductor, TaskStatus.BLOCKED):
        if _cancel_undo_task(
            conductor, bulletin_store, task, current,
            notes="cleaned_up: undo inverse failed, cannot proceed autonomously",
            reason="undo_blocked_cleanup",
        ):
            cleaned_ids.append(task.task_id)

    if expired_ids:
        _send_notification(
            notifier,
            "[Undo] Suggestions expired without operator approval:\n"
            + "\n".join(f"- {task_id}" for task_id in expired_ids),
        )
    if cleaned_ids:
        _send_notification(
            notifier,
            "[Undo] Cleaned up blocked suggestions (inverse failed):\n"
            + "\n".join(f"- {task_id}" for task_id in cleaned_ids),
        )
    return expired_ids + cleaned_ids


def _list_undo_tasks(conductor: Any, status: "TaskStatus") -> List[Any]:
    """List maria effector-undo tasks in a given status (safe on errors)."""
    try:
        return [
            t for t in conductor.list_tasks(project="maria", status=status)
            if getattr(t, "phase", "") == UNDO_SUGGEST_PHASE
        ]
    except Exception:
        logger.warning("[UndoSuggest] expiry list failed", exc_info=True)
        return []


def _cancel_undo_task(
    conductor: Any,
    bulletin_store: Any,
    task: Any,
    current: float,
    notes: str,
    reason: str,
) -> bool:
    """Move one undo-suggestion task to CANCELLED and resolve its bulletin."""
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
            "[UndoSuggest] expiry failed for %s", task.task_id, exc_info=True
        )
        return False
