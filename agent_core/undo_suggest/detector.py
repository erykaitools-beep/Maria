"""Detect effector actions Maria should propose undoing (autonomous SUGGEST side).

v1 rule -- *orphaned reversible action*: a journaled effector action with a
genuinely executable inverse (status RECORDED, inverse kind 'invoke') whose
owning goal is now FAILED or ABANDONED. The action served a goal that did not
pan out, so what it left behind (e.g. a written file) is a candidate for
cleanup. This is a heuristic ON PURPOSE: it only PROPOSES, the operator judges
(an action can legitimately outlive its goal). More rules can be added later
without touching the lifecycle (suggestion_creator / monitor / expiry).

Pure functions + a frozen candidate dataclass, mirroring
``agent_core/self_repair/detectors.py``. Nothing here invokes OpenClaw.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from agent_core.effector.undo_journal import STATUS_RECORDED

logger = logging.getLogger("agent_core.undo_suggest")

# Per undo_record_id back-off, so the same action is not re-proposed every scan
# while it sits PENDING awaiting the operator. Mirrors self-repair COOLDOWN.
SUGGEST_COOLDOWN_SECONDS = 4 * 3600
# Don't judge an action until it has settled. The undo record is journaled
# RECORDED *before* the action runs (coordinator captures pre-state first), and
# the coordinator then retries with backoff (~40s envelope today) before
# reconciling a failed action to ACTION_FAILED. A scan during that window could
# otherwise propose undoing an action still in flight -- and if the goal fails
# from an independent cause meanwhile, describe a file not yet written. Require
# the record to be older than the worst-case retry envelope plus margin.
MIN_RECORD_AGE_SECONDS = 120
# Only inspect the recent tail of the journal -- old actions are not regrets.
MAX_JOURNAL_SCAN = 50
# GoalStatus.value strings that count as "the goal this action served failed".
_TERMINAL_REGRET = {"failed", "abandoned"}

# (undo_record_id) -> True if a recent suggestion for it is still in cooldown.
CooldownLookup = Callable[[str], bool]


@dataclass(frozen=True)
class UndoSuggestionCandidate:
    """A journaled action Maria proposes undoing, pending operator approval."""

    undo_record_id: str
    tool: str
    goal_id: Optional[str]
    summary: str
    evidence_summary: Dict[str, Any]
    detected_at: float


def detect_orphaned_reversible_actions(
    journal: Any,
    goal_store: Any,
    cooldown_lookup: CooldownLookup,
    *,
    max_scan: int = MAX_JOURNAL_SCAN,
    now: Optional[float] = None,
) -> List[UndoSuggestionCandidate]:
    """Scan the undo journal for RECORDED, auto-undoable actions whose goal failed.

    Conservative by construction: skips anything not genuinely reversible
    (inverse kind must be 'invoke'), anything without a linked goal, any goal not
    terminally failed/abandoned, and anything still in cooldown. An empty journal
    or missing goal linkage simply yields no candidates -- never an error.
    """
    current = time.time() if now is None else now
    try:
        records = journal.list_recent(max_scan)
    except Exception:
        logger.warning("[UndoSuggest] journal scan failed", exc_info=True)
        return []

    candidates: List[UndoSuggestionCandidate] = []
    for rec in records:
        if getattr(rec, "status", "") != STATUS_RECORDED:
            continue  # already undone / action_failed / irreversible -> nothing to offer
        inverse = getattr(rec, "inverse", {}) or {}
        if inverse.get("kind") != "invoke":
            continue  # only genuinely auto-undoable actions (no noop/partial/unknown)
        if current - float(getattr(rec, "created_at", 0.0) or 0.0) < MIN_RECORD_AGE_SECONDS:
            continue  # action may still be executing / retrying -> too young to judge
        meta = getattr(rec, "metadata", {}) or {}
        goal_id = meta.get("goal_id")
        if not goal_id:
            continue  # no goal to judge regret against
        goal = _safe_get_goal(goal_store, goal_id)
        if goal is None:
            continue
        status_value = _goal_status_value(goal)
        if status_value not in _TERMINAL_REGRET:
            continue  # goal still live / achieved -> not a regret
        if cooldown_lookup(rec.record_id):
            continue  # already proposed recently, still pending

        path = (getattr(rec, "args", {}) or {}).get("path", "")
        note = inverse.get("note", "")
        candidates.append(
            UndoSuggestionCandidate(
                undo_record_id=rec.record_id,
                tool=getattr(rec, "tool", ""),
                goal_id=goal_id,
                summary=(
                    f"{rec.tool} for goal {goal_id} ({status_value}) -- "
                    f"propose undo of {path or 'action'}"
                ),
                evidence_summary={
                    "undo_record_id": rec.record_id,
                    "tool": getattr(rec, "tool", ""),
                    "path": path,
                    "goal_id": goal_id,
                    "goal_status": status_value,
                    "inverse_note": note,
                    "one_line": (
                        f"{rec.tool} {path} -- goal {goal_id} {status_value}; "
                        f"undo would {note or 'reverse it'}"
                    ),
                },
                detected_at=current,
            )
        )
    return candidates


def _safe_get_goal(goal_store: Any, goal_id: str) -> Optional[Any]:
    try:
        return goal_store.get(goal_id)
    except Exception:
        logger.warning(
            "[UndoSuggest] goal lookup failed for %s", goal_id, exc_info=True
        )
        return None


def _goal_status_value(goal: Any) -> str:
    """Return the goal's status as a lowercase string (GoalStatus enum or raw)."""
    status = getattr(goal, "status", None)
    return str(getattr(status, "value", status) or "").lower()
