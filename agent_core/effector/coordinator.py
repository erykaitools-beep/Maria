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
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from agent_core.effector.health_check import (
    openclaw_gateway_alive,
    ollama_alive,
    model_loaded,
)
from agent_core.effector.prewarm import warm_ollama_model


logger = logging.getLogger(__name__)


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
    ):
        self._client = openclaw_client
        self._bulletin = bulletin_store
        self._notifier = telegram_notifier
        self._core = homeostasis_core
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

        # All attempts failed
        outcome = EffectorOutcome(
            task_id=task.task_id, tool_name=task.tool_name,
            status=TaskStatus.FAILED, attempts=attempts,
            total_duration_s=time.time() - start,
        )
        self._self_diagnose(task, outcome)
        return outcome

    # ----- Stages --------------------------------------------------------

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
