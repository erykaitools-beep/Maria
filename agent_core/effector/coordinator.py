"""
Effector Coordinator — orchestrates OpenClaw tool invocations.

Replaces the "strzel subprocess i licz że zadziała" pattern with a small
state machine: pre-flight → pre-warm → execute → retry → self-diagnose.

Motivation: agent tools (web_search, web_fetch) require qwen2.5:3b
cold-load (~15-30s) + tool call + generation. With a uniform 30s limit
the subprocess was aborting mid-generation. Pre-warming the model and
adding two bounded retries makes /do reliable without pinning 3GB of
RAM permanently.

On persistent failure (3 attempts exhausted) we post an INCIDENT-style
entry to the Bulletin Board and notify the operator via Telegram.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from agent_core.effector.health_check import (
    openclaw_gateway_alive,
    ollama_alive,
    model_loaded,
)
from agent_core.effector.prewarm import warm_ollama_model
from agent_core.effector.undo_journal import (
    EffectorUndoJournal, STATUS_UNDONE, STATUS_ACTION_FAILED,
)


logger = logging.getLogger(__name__)


def _undo_journal_enabled() -> bool:
    """Flag-gated, default OFF (the pre-state capture adds an extra read call)."""
    return os.environ.get("EFFECTOR_UNDO_JOURNAL_ENABLED", "").strip().lower() in (
        "1", "true", "yes", "on")


def _undo_execute_enabled() -> bool:
    """Gates ACTUAL inverse execution (/undo_action + _execute_undo). Default OFF.

    Separate from the journal flag: journaling is observe-only, executing an
    inverse runs a real (unsandboxed) OpenClaw action and must be armed
    deliberately, with the operator present, for the live undo rung."""
    return os.environ.get("EFFECTOR_UNDO_EXECUTE_ENABLED", "").strip().lower() in (
        "1", "true", "yes", "on")


def _looks_like_missing_file(msg: str) -> bool:
    """True if a read error message indicates the file is absent (not a real error).

    Used to tell 'confirmed absent' (inverse = remove the new file) apart from a
    genuine read failure (no safe inverse). cat on a missing file reports
    'No such file or directory' / ENOENT (PL: 'Nie ma takiego pliku').

    Deliberately FILE-specific markers only: the bare token 'not found' was too
    broad -- it matches infra errors like 'command not found' / 'node not found' /
    '404 Not Found', which would wrongly classify a real read failure as 'absent'
    and build a DESTRUCTIVE remove inverse (the exact data-loss FIX-1 prevents)."""
    m = (msg or "").lower()
    return ("no such file" in m or "enoent" in m
            or "nie ma takiego pliku" in m)


def _looks_like_transient_node_error(msg: str) -> bool:
    """True if the error is a TRANSIENT node/gateway connectivity blip, not a
    verdict about the file. Under host CPU saturation the node host's websocket
    to the gateway briefly drops ("gateway closed", "unknown node", "gateway
    connect failed") and reconnects within ~1s. A pre-state read that lands in
    that window must be RETRIED, not treated as a final answer -- otherwise a
    fresh-file write is wrongly journaled irreversible. Distinct from
    _looks_like_missing_file (a real verdict: absent) and from a genuine read
    failure of an existing file (no safe inverse)."""
    m = (msg or "").lower()
    return ("unknown node" in m or "gateway closed" in m
            or "gateway connect failed" in m or "gateway client stopped" in m
            or "gateway timeout" in m or "node not connected" in m
            or "econnrefused" in m or "connection refused" in m)


# Agent tools that go through qwen2.5:3b via OpenClaw
AGENT_TOOLS = {"web_fetch", "web_search", "message", "cron"}
# Node tools go through the openclaw node process — no LLM, no warm-up
NODE_TOOLS = {"exec", "read", "write"}

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SEC = [0, 10, 30]  # first attempt: no wait; 10s, 30s after
DEFAULT_AGENT_MODEL = "qwen2.5:3b"


class TaskStatus(Enum):
    PENDING = "pending"
    PREFLIGHT_FAILED = "preflight_failed"
    COMPLETED = "completed"
    FAILED = "failed"       # persistent fail after all retries


@dataclass
class AttemptRecord:
    """One execution attempt — preflight/warm/execute outcome."""
    attempt_number: int
    started_at: float
    duration_s: float
    ok: bool
    error: str = ""
    stage: str = ""            # preflight/prewarm/execute

    def to_dict(self) -> dict:
        return {
            "attempt": self.attempt_number,
            "started_at": self.started_at,
            "duration_s": round(self.duration_s, 2),
            "ok": self.ok,
            "error": self.error,
            "stage": self.stage,
        }


@dataclass
class EffectorTask:
    """Single effector job flowing through the coordinator."""
    tool_name: str
    tool_args: Dict[str, Any]
    task_id: str = field(default_factory=lambda: f"eff-{uuid.uuid4().hex[:12]}")
    plan_id: Optional[str] = None
    goal_id: Optional[str] = None
    source: str = "planner"       # "/do", "planner", etc.
    created_at: float = field(default_factory=time.time)

    @property
    def is_agent_tool(self) -> bool:
        return self.tool_name in AGENT_TOOLS


@dataclass
class EffectorOutcome:
    """Final result of a task run, success or fail."""
    task_id: str
    tool_name: str
    status: TaskStatus
    attempts: List[AttemptRecord]
    result: Dict[str, Any] = field(default_factory=dict)
    total_duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == TaskStatus.COMPLETED


class EffectorCoordinator:
    """
    Orchestrates OpenClaw tool invocations with retry and diagnostics.

    Dependencies (wire via setters so partial setups still work):
      - openclaw_client: required, invokes the tool
      - bulletin_store: optional, receives INCIDENT entries on final fail
      - telegram_notifier: optional, notifies operator on final fail
      - homeostasis_core: optional, snapshots mode/health for diagnostics

    Usage:
        task = EffectorTask(tool_name="web_search", tool_args={"query": "..."})
        outcome = coordinator.execute_task(task)
        if outcome.ok:
            use(outcome.result)
    """

    def __init__(
        self,
        openclaw_client,
        bulletin_store=None,
        telegram_notifier=None,
        homeostasis_core=None,
        agent_model: str = DEFAULT_AGENT_MODEL,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_seq: Optional[List[float]] = None,
        undo_journal: Optional[EffectorUndoJournal] = None,
    ):
        self._client = openclaw_client
        self._bulletin = bulletin_store
        self._notifier = telegram_notifier
        self._core = homeostasis_core
        self._undo_journal = undo_journal
        self._agent_model = agent_model
        self._max_attempts = max_attempts
        self._backoff = backoff_seq or DEFAULT_BACKOFF_SEC
        if len(self._backoff) < max_attempts:
            # pad with last value so every attempt has a defined backoff
            last = self._backoff[-1] if self._backoff else 0
            self._backoff = (
                list(self._backoff)
                + [last] * (max_attempts - len(self._backoff))
            )

    # ----- Late-binding setters (wiring order-independent) --------------

    def set_bulletin_store(self, store) -> None:
        self._bulletin = store

    def set_telegram_notifier(self, notifier) -> None:
        self._notifier = notifier

    def set_homeostasis_core(self, core) -> None:
        self._core = core

    def set_undo_journal(self, journal) -> None:
        self._undo_journal = journal

    # ----- Public entry point -------------------------------------------

    def execute_task(self, task: EffectorTask) -> EffectorOutcome:
        """Run a task through the full pipeline."""
        start = time.time()
        attempts: List[AttemptRecord] = []

        # Pre-flight (once, before any attempt). If infra is down we don't
        # waste retries banging on a dead subprocess.
        pf_ok, pf_error = self._preflight()
        if not pf_ok:
            attempts.append(AttemptRecord(
                attempt_number=0, started_at=time.time(), duration_s=0.0,
                ok=False, error=pf_error, stage="preflight",
            ))
            outcome = EffectorOutcome(
                task_id=task.task_id, tool_name=task.tool_name,
                status=TaskStatus.PREFLIGHT_FAILED, attempts=attempts,
                total_duration_s=time.time() - start,
            )
            self._self_diagnose(task, outcome)
            return outcome

        # Pre-warm only for agent tools
        if task.is_agent_tool:
            self._prewarm_model()

        # Journal the inverse BEFORE executing (flag-gated, observe-only): capture
        # pre-state ONCE, before any attempt, so a later authority rung can offer
        # undo. Additive -- never blocks or changes the action; at OBSERVE
        # authority this code isn't reached (effector blocked upstream).
        undo_rid = self._journal_undo(task)

        # Attempt loop with backoff
        for i in range(self._max_attempts):
            if i > 0:
                wait = self._backoff[i]
                if wait > 0:
                    logger.info(
                        "[EffectorCoord] Retry %d/%d for %s, backoff %.0fs",
                        i + 1, self._max_attempts, task.tool_name, wait,
                    )
                    time.sleep(wait)
                # Refresh warm-up before retries — model may have been
                # evicted by Ollama while we waited.
                if task.is_agent_tool:
                    self._prewarm_model()

            rec = self._execute_attempt(task, attempt_number=i + 1)
            attempts.append(rec)

            if rec.ok:
                outcome = EffectorOutcome(
                    task_id=task.task_id, tool_name=task.tool_name,
                    status=TaskStatus.COMPLETED, attempts=attempts,
                    result=rec_result_for(rec),
                    total_duration_s=time.time() - start,
                )
                return outcome

        # All attempts failed: reconcile the journal so the stale 'recorded'
        # inverse for an action that never completed can never be offered as undo.
        if undo_rid and self._undo_journal is not None:
            try:
                self._undo_journal.mark_action_failed(
                    undo_rid, detail="effector action failed (all attempts)")
            except Exception as e:  # journal reconcile must never break the outcome
                logger.warning("[EffectorCoord] undo reconcile failed: %s", e)
        outcome = EffectorOutcome(
            task_id=task.task_id, tool_name=task.tool_name,
            status=TaskStatus.FAILED, attempts=attempts,
            total_duration_s=time.time() - start,
        )
        self._self_diagnose(task, outcome)
        return outcome

    # ----- Stages --------------------------------------------------------

    def _journal_undo(self, task: EffectorTask) -> Optional[str]:
        """Record an undo entry for this action before it runs (flag-gated).

        For `write`, capture the prior file content via a direct read on the same
        client so the inverse can restore it. Best-effort: a failure here NEVER
        blocks or changes the action (the journal is observability, not a gate).
        Returns the undo record_id (or None) so the caller can reconcile the
        journal to the action's actual outcome."""
        if not _undo_journal_enabled():
            return None
        try:
            if self._undo_journal is None:
                self._undo_journal = EffectorUndoJournal()
            read_fn = None
            if task.tool_name == "write":
                def read_fn(path):
                    # FIX-1: distinguish CONFIRMED-ABSENT (return None -> inverse
                    # removes the new file) from a genuine READ ERROR (raise ->
                    # capture_pre_state records captured=False, so no destructive
                    # inverse is built). Collapsing the two -- the old behaviour --
                    # turned a failed read of an EXISTING file into a 'remove'
                    # inverse, i.e. undo would DELETE a file it should restore.
                    #
                    # Resolution order per attempt: confirmed-absent -> retry the
                    # transient node/gateway flap -> genuine unknown. The client
                    # does NOT retry node errors (it re-raises OpenClawError), and
                    # under host CPU saturation the node briefly disconnects, so a
                    # one-shot pre-state read would wrongly journal irreversible.
                    last_exc = None
                    for attempt in range(3):
                        try:
                            r = self._client.invoke_tool("read", {"path": path})
                        except Exception as e:
                            if _looks_like_missing_file(str(e)):
                                return None  # confirmed absent
                            if _looks_like_transient_node_error(str(e)) and attempt < 2:
                                last_exc = e
                                time.sleep(1.0)
                                continue  # node reconnects in ~1s; try again
                            raise          # genuine error -> captured=False upstream
                        if r and r.get("ok"):
                            return r.get("result")
                        # ok==False WITHOUT raising: the live `read` (cat) reports a
                        # MISSING file this way -- ok=False + "No such file" on stderr
                        # -- instead of throwing, so apply the same confirmed-absent
                        # test as the except branch. A transient node blip can also
                        # surface here (ok=False + "unknown node" on stderr) -> retry.
                        err = (r.get("stderr") or r.get("error") or "") if r else ""
                        if _looks_like_missing_file(err):
                            return None  # confirmed absent
                        if _looks_like_transient_node_error(err) and attempt < 2:
                            time.sleep(1.0)
                            continue
                        # not-ok, not missing, not transient: genuinely unknown.
                        raise RuntimeError("read returned not-ok; pre-state unknown")
                    if last_exc is not None:
                        raise last_exc  # transient retries exhausted
                    raise RuntimeError("read returned not-ok; pre-state unknown")
            rec = self._undo_journal.record_action(
                tool=task.tool_name, args=task.tool_args,
                action_record_id=task.task_id, read_fn=read_fn,
                # Provenance for the autonomous SUGGEST side (undo_suggest): link
                # the journaled action back to the goal it served, so a later
                # detector can propose undoing an action whose goal failed.
                metadata={"goal_id": task.goal_id, "source": task.source},
            )
            return rec.record_id
        except Exception as e:
            logger.warning("[EffectorCoord] undo journal failed: %s", e)
            return None

    def _execute_undo(
        self,
        record_id: str,
        *,
        invoke: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Execute the journaled inverse for ``record_id`` and reconcile the journal.

        The operator-initiated undo keystone. Gated by EFFECTOR_UNDO_EXECUTE_ENABLED
        (default OFF -- executing an inverse runs a REAL, unsandboxed OpenClaw
        action, so it must be armed deliberately with the operator present).
        ``invoke`` is an injectable callable(tool, args)->dict so tests and
        /drill_undo can drive a sandboxed fake; the live path uses
        ``self._client.invoke_tool``. Returns a result dict {ok, reason, detail};
        never raises into the caller.

        Guards (fail-closed): flag on; journal present; record known; not already
        undone; the action actually happened (not ACTION_FAILED); and the inverse
        is an executable ``invoke`` plan (noop succeeds trivially, anything else --
        partial/unknown/irreversible -- is refused, never faked).
        """
        if not _undo_execute_enabled():
            return {"ok": False, "reason": "execute_disabled"}
        journal = self._undo_journal
        if journal is None:
            return {"ok": False, "reason": "no_journal"}
        rec = journal.get(record_id)
        if rec is None:
            return {"ok": False, "reason": "unknown_record"}
        if rec.status == STATUS_UNDONE:
            return {"ok": False, "reason": "already_undone"}
        if rec.status == STATUS_ACTION_FAILED:
            return {"ok": False, "reason": "action_failed"}  # nothing to undo
        inv = rec.inverse or {}
        kind = inv.get("kind")
        if kind == "noop":
            journal.mark_undone(record_id, ok=True, detail="noop (read-only action)")
            return {"ok": True, "reason": "noop"}
        if kind != "invoke":
            return {"ok": False, "reason": f"not_auto_reversible:{kind}"}

        invoke_fn = invoke if invoke is not None else self._client.invoke_tool
        try:
            result = invoke_fn(inv.get("tool"), inv.get("args") or {})
        except Exception as e:
            journal.mark_undone(record_id, ok=False, detail=f"inverse raised: {e}"[:300])
            return {"ok": False, "reason": "inverse_error", "detail": str(e)[:200]}

        ok = bool(result and result.get("ok"))
        detail = ""
        # FIX-4: verify a RESTORE (write inverse) actually landed -- re-read the
        # path and compare to the content we meant to restore. Refuse to claim
        # success on a mismatch: a silently corrupt restore is worse than an honest
        # UNDO_FAILED the operator can act on.
        if ok and inv.get("tool") == "write":
            want = (inv.get("args") or {}).get("content")
            path = (inv.get("args") or {}).get("path", "")
            try:
                rr = invoke_fn("read", {"path": path})
                got = rr.get("result") if rr and rr.get("ok") else None
            except Exception as e:
                got, detail = None, f"verify read raised: {e}"[:200]
            if got != want:
                ok = False
                detail = detail or "restore verify mismatch (content not faithfully restored)"
        # FIX-4b: a REMOVE (rm) inverse must leave the path ABSENT. OpenClaw may
        # report ok while the file remains (perm denied on the parent dir, race,
        # fs stall) -- re-read and refuse success if it is still present, rather
        # than mark UNDONE on an unverified report.
        elif ok and inv.get("tool") == "exec":
            argv = (inv.get("args") or {}).get("argv") or []
            path = argv[-1] if argv else ""
            if path:
                try:
                    rr = invoke_fn("read", {"path": path})
                    still_present = bool(rr and rr.get("ok"))
                except Exception:
                    still_present = False  # read fails == gone == removal confirmed
                if still_present:
                    ok = False
                    detail = detail or "remove verify failed (file still present after rm)"

        journal.mark_undone(record_id, ok=ok,
                            detail=detail or ("undone" if ok else "inverse not ok"))
        return {"ok": ok, "reason": "undone" if ok else "inverse_failed", "detail": detail}

    def _preflight(self) -> tuple[bool, str]:
        """Check openclaw gateway and Ollama before spending subprocess time."""
        if not openclaw_gateway_alive():
            return False, "openclaw_gateway_not_running"
        if not ollama_alive():
            return False, "ollama_unreachable"
        return True, ""

    def _prewarm_model(self) -> None:
        """Ensure qwen is loaded with long keep_alive. Non-blocking on fail."""
        if model_loaded(self._agent_model):
            # Already loaded — refresh keep_alive so it won't evict mid-run
            warm_ollama_model(self._agent_model)
            return
        warm_ollama_model(self._agent_model)

    def _execute_attempt(
        self, task: EffectorTask, attempt_number: int,
    ) -> AttemptRecord:
        """Single subprocess invocation through openclaw_client."""
        started = time.time()
        try:
            result = self._client.invoke_tool(task.tool_name, task.tool_args)
            duration = time.time() - started
            ok = bool(result.get("ok"))
            error = ""
            if not ok:
                # Prefer a named status if the client surfaced one — that's
                # how aborted/error/failed/timeout arrive from openclaw's
                # internal runner.
                status = str(result.get("status", "")).lower()
                if status in ("aborted", "error", "failed", "timeout"):
                    error = f"{status}_by_openclaw"
                else:
                    error = (
                        result.get("error")
                        or result.get("reason")
                        or "tool_returned_not_ok"
                    )
            rec = AttemptRecord(
                attempt_number=attempt_number,
                started_at=started,
                duration_s=duration,
                ok=ok,
                error=error,
                stage="execute",
            )
            # Stash full payload on the record so callers can retrieve it
            rec._raw_result = result  # type: ignore[attr-defined]
            return rec
        except Exception as e:
            return AttemptRecord(
                attempt_number=attempt_number,
                started_at=started,
                duration_s=time.time() - started,
                ok=False,
                error=f"exception: {e}",
                stage="execute",
            )

    # ----- Failure handling ---------------------------------------------

    def _self_diagnose(
        self, task: EffectorTask, outcome: EffectorOutcome,
    ) -> None:
        """On persistent failure: log, bulletin, notify."""
        context = self._system_context()
        logger.warning(
            "[EffectorCoord] %s failed after %d attempts (tool=%s): %s | "
            "context=%s",
            task.task_id,
            len(outcome.attempts),
            task.tool_name,
            [a.error for a in outcome.attempts],
            context,
        )

        self._post_bulletin(task, outcome, context)
        self._notify_operator(task, outcome)

    def _post_bulletin(
        self,
        task: EffectorTask,
        outcome: EffectorOutcome,
        context: Dict[str, Any],
    ) -> None:
        if self._bulletin is None:
            return
        try:
            from agent_core.bulletin.bulletin_model import (
                create_entry, EntryType,
            )
            entry = create_entry(
                entry_type=EntryType.IMPROVEMENT,
                topic=f"effector:{task.tool_name}",
                reason_code="effector_persistent_fail",
                summary=(
                    f"{task.tool_name} failed {len(outcome.attempts)}× "
                    f"({outcome.status.value}). "
                    f"Last error: {outcome.attempts[-1].error if outcome.attempts else '-'}"
                ),
                requested_by="effector_coordinator",
                goal_id=task.goal_id,
                priority=0.7,
                metadata={
                    "task_id": task.task_id,
                    "plan_id": task.plan_id,
                    "tool_args": task.tool_args,
                    "attempts": [a.to_dict() for a in outcome.attempts],
                    "total_duration_s": round(outcome.total_duration_s, 2),
                    "system_context": context,
                },
            )
            # add_entry nigdy nie istnialo na BulletinStore (fantom, audyt
            # 2026-06-12) -- realne API do gotowego entry to post().
            self._bulletin.post(entry)
        except Exception as e:
            logger.warning("[EffectorCoord] bulletin post failed: %s", e)

    def _notify_operator(
        self, task: EffectorTask, outcome: EffectorOutcome,
    ) -> None:
        if self._notifier is None:
            return
        try:
            if hasattr(self._notifier, "notify_effector_incident"):
                self._notifier.notify_effector_incident(task, outcome)
            else:
                # Fallback: reuse existing result notifier
                summary = (
                    f"{len(outcome.attempts)} prob, "
                    f"ostatni blad: "
                    f"{outcome.attempts[-1].error if outcome.attempts else '-'}"
                )
                self._notifier.notify_effector_result(
                    tool_name=task.tool_name, success=False, summary=summary,
                )
        except Exception as e:
            logger.warning("[EffectorCoord] operator notify failed: %s", e)

    def _system_context(self) -> Dict[str, Any]:
        """Snapshot mode/health and model state for the incident record."""
        ctx: Dict[str, Any] = {
            "agent_model_loaded": model_loaded(self._agent_model),
            "openclaw_gateway_alive": openclaw_gateway_alive(),
            "ollama_alive": ollama_alive(),
        }
        if self._core is not None:
            try:
                state = self._core.get_state()
                ctx["mode"] = getattr(state.mode, "value", str(state.mode))
                ctx["health_score"] = round(state.health_score, 3)
            except Exception:
                pass
        return ctx


def rec_result_for(rec: AttemptRecord) -> Dict[str, Any]:
    """Extract raw result payload attached to the attempt record."""
    return getattr(rec, "_raw_result", {})
