"""Create PENDING effector-undo SUGGESTIONS that require operator approval.

Mirrors ``agent_core/self_repair/task_creator.py`` (STOP-AT-PENDING, ADR-030/
031): the task always sets ``artifacts['approval_required']=True`` and uses
``assignee=OPERATOR`` (outside ``BUILDER_ASSIGNEES``), so the autonomous
dispatcher never routes it -- two independent locks plus the conductor's
``phase != 'effector_undo'`` exclusion = three layers.

The deliberate DIFFERENCE from self-repair: on ``/approve_undo`` the operator
does not merely CLOSE the task -- the bounded, journaled, post-verified inverse
actually runs (``coordinator._execute_undo``). That is safe where dispatching
Codex to the live prod repo was not (ADR-031): an undo is one reversible
OpenClaw call, already proven live and verified after the fact.

Gate vs self-repair: NO NIM requirement (an undo is local -- detect + propose +
operator runs a bounded inverse; no LLM work). Snapshot freshness + ACTIVE/
REDUCED mode + per-record cooldown are kept (don't propose undos while asleep).
"""

from __future__ import annotations

import importlib
import logging
import time
from typing import Any, Dict, Optional

from agent_core.conductor.task_model import Assignee, TaskStatus, create_task
from agent_core.self_repair.task_creator import _send_notification
from agent_core.undo_suggest.detector import (
    SUGGEST_COOLDOWN_SECONDS,
    UndoSuggestionCandidate,
)

logger = logging.getLogger("agent_core.undo_suggest")

UNDO_SUGGEST_PHASE = "effector_undo"
UNDO_SUGGEST_TTL_SECONDS = 24 * 3600


def record_cooldown_active(
    conductor: Any, undo_record_id: str, now: Optional[float] = None
) -> bool:
    """True if a same-record proposal should suppress a fresh one.

    An OPEN proposal (PENDING/BLOCKED/IN_PROGRESS) holds the cooldown REGARDLESS
    of age -- so exactly one open proposal exists per record at a time (review
    F1/F2: with an age-based window shorter than the 24h TTL, a still-PENDING task
    stopped holding the cooldown after 4h and every scan minted a duplicate). A
    recently CLOSED proposal (DONE/CANCELLED) holds a short back-off measured from
    its CLOSE time, so a just-expired/just-undone record is not re-proposed on the
    very next scan; an old closure does not block a genuinely-recurring action.
    """
    current = time.time() if now is None else now
    try:
        tasks = conductor.list_tasks(project="maria")
    except Exception:
        logger.warning("[UndoSuggest] cooldown lookup failed", exc_info=True)
        return False
    for task in tasks:
        if getattr(task, "phase", "") != UNDO_SUGGEST_PHASE:
            continue
        artifacts = getattr(task, "artifacts", {}) or {}
        if artifacts.get("undo_record_id") != undo_record_id:
            continue
        if getattr(task, "status", None) in (TaskStatus.DONE, TaskStatus.CANCELLED):
            closed_at = (
                getattr(task, "completed_at", None)
                or getattr(task, "updated_at", None)
                or getattr(task, "created_at", 0.0)
            )
            if current - float(closed_at or 0.0) < SUGGEST_COOLDOWN_SECONDS:
                return True
            continue
        # Any open proposal holds the cooldown for as long as it stays open.
        return True
    return False


class UndoSuggestionCreator:
    """Create PENDING undo-suggestion tasks gated for operator approval."""

    def __init__(
        self,
        conductor: Any,
        bulletin_store: Any,
        notifier: Any,
        self_perception: Optional[Any] = None,
    ):
        self._conductor = conductor
        self._bulletin_store = bulletin_store
        self._notifier = notifier
        self._self_perception = self_perception

    def set_self_perception(self, self_perception: Any) -> None:
        """Wire SelfPerception after construction (wiring order-independent)."""
        self._self_perception = self_perception

    def create(
        self,
        candidate: UndoSuggestionCandidate,
        snapshot_id: str = "",
        bypass_gate: bool = False,
    ) -> Optional[str]:
        """Create task + bulletin + Telegram notification. Returns task_id or None.

        ``bypass_gate=True`` skips the eligibility gate (mode/freshness/cooldown).
        It exists ONLY for the operator live drill (``/drill_suggest_undo``), so
        the proposal chain can be exercised on demand even in SLEEP. The created
        task is still ``approval_required`` + ``assignee=OPERATOR``, so it never
        auto-dispatches -- a drill is harmless.
        """
        snapshot = self._latest_snapshot()
        refusal = None if bypass_gate else self._gate_refusal(candidate, snapshot)
        if refusal is not None:
            logger.info("[UndoSuggest] refused suggestion: reason=%s", refusal)
            return None

        now = time.time()
        title = _truncate_title(f"Undo suggestion: {candidate.summary}")
        task = create_task(
            project="maria",
            phase=UNDO_SUGGEST_PHASE,
            title=title,
            description=self._build_description(title, candidate),
            priority=0.6,
            assignee=Assignee.OPERATOR,  # never a BUILDER_ASSIGNEE -> never auto-dispatched
            dependencies=[],
        )
        task.created_at = now
        task.updated_at = now
        task.artifacts = {
            "undo_record_id": candidate.undo_record_id,
            "undo_subject": candidate.evidence_summary.get("path", ""),
            "goal_id": candidate.goal_id,
            "evidence_summary": candidate.evidence_summary,
            "created_by": "undo_suggester",
            "snapshot_id": snapshot_id or str(snapshot.get("snapshot_id", "")),
            "approval_required": True,
            "drill": bool(candidate.evidence_summary.get("drill")),
            "expires_at": now + UNDO_SUGGEST_TTL_SECONDS,
        }
        self._conductor.add_task(task)

        self._post_bulletin(task.task_id, candidate)
        _send_notification(
            self._notifier,
            (
                f"[Undo] Maria proponuje cofnac {candidate.undo_record_id}: "
                f"{candidate.summary}\n"
                f"Podglad: /undo_preview {candidate.undo_record_id}\n"
                f"Zatwierdz (wykona cofniecie na zywym OpenClaw): "
                f"/approve_undo {task.task_id}"
            ),
        )
        return task.task_id

    # ----- internals -----------------------------------------------------

    def _latest_snapshot(self) -> Dict[str, Any]:
        if self._self_perception is None:
            return {}
        latest = self._self_perception.get_latest()
        return latest if isinstance(latest, dict) else {}

    def _gate_refusal(
        self,
        candidate: UndoSuggestionCandidate,
        snapshot: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if self._self_perception is None:
            return {"reason": "missing_self_perception"}
        try:
            fresh = self._self_perception.is_fresh(max_age_seconds=300)
        except TypeError:
            fresh = self._self_perception.is_fresh(300)
        if not fresh:
            return {"reason": "stale_snapshot",
                    "undo_record_id": candidate.undo_record_id}

        mode = str(snapshot.get("mode", ""))
        if mode not in ("ACTIVE", "REDUCED"):
            return {"reason": "mode_not_eligible", "mode": mode,
                    "undo_record_id": candidate.undo_record_id}

        if self._pending_same_record_in_cooldown(candidate.undo_record_id):
            return {"reason": "cooldown",
                    "undo_record_id": candidate.undo_record_id}
        return None

    def _pending_same_record_in_cooldown(self, undo_record_id: str) -> bool:
        return record_cooldown_active(self._conductor, undo_record_id)

    def _post_bulletin(
        self, task_id: str, candidate: UndoSuggestionCandidate
    ) -> None:
        if self._bulletin_store is None:
            return
        try:
            bulletin_model = importlib.import_module(
                "agent_core.bulletin.bulletin_model"
            )
            self._bulletin_store.create_and_post(
                entry_type=bulletin_model.EntryType.IMPROVEMENT,
                topic=f"effector_undo_{candidate.undo_record_id}",
                reason_code="effector_undo_suggestion",
                summary=f"Undo proposed: {candidate.summary[:140]}",
                requested_by="undo_suggester",
                priority=0.6,
                metadata={
                    "task_id": task_id,
                    "undo_record_id": candidate.undo_record_id,
                    "goal_id": candidate.goal_id,
                    "evidence_summary": candidate.evidence_summary,
                },
            )
        except Exception:
            logger.warning("[UndoSuggest] bulletin post failed", exc_info=True)

    def _build_description(
        self, title: str, candidate: UndoSuggestionCandidate
    ) -> str:
        ev = candidate.evidence_summary
        return (
            f"# {title}\n\n"
            "Maria's autonomous undo detector proposes reversing one of her own\n"
            "journaled effector actions. This is an ALERT requiring operator\n"
            "approval -- the inverse runs ONLY on `/approve_undo`, on the live\n"
            "OpenClaw, and is post-verified.\n\n"
            f"- undo_record_id: {candidate.undo_record_id}\n"
            f"- tool: {candidate.tool}\n"
            f"- path: {ev.get('path', '')}\n"
            f"- goal_id: {candidate.goal_id} (status: {ev.get('goal_status', '')})\n"
            f"- inverse: {ev.get('inverse_note', '')}\n\n"
            f"Preview: /undo_preview {candidate.undo_record_id}\n"
        )


def _truncate_title(title: str) -> str:
    if len(title) <= 80:
        return title
    return title[:77].rstrip() + "..."
