"""Repair task creation with operator approval gate."""

from __future__ import annotations

import json
import logging
import time
import importlib
from typing import Any, Dict, Optional

from agent_core.conductor.task_model import Assignee, TaskStatus, create_task
from agent_core.self_repair.detectors import COOLDOWN_SECONDS, RepairCandidate

logger = logging.getLogger("agent_core.self_repair")

WORKSPACE_PATH = "/home/maria/maria"
REPAIR_TASK_TTL_SECONDS = 24 * 3600


class RepairTaskCreator:
    """Create PENDING self-repair tasks that require operator approval.

    The created task always sets ``artifacts["approval_required"] = True``.
    The autonomous dispatcher must refuse such tasks until the operator
    flips the flag through ``/approve_repair``.
    """

    def __init__(
        self,
        conductor: Any,
        bulletin_store: Any,
        task_board_writer: Any,
        notifier: Any,
        self_perception: Optional[Any] = None,
    ):
        self._conductor = conductor
        self._bulletin_store = bulletin_store
        self._task_board_writer = task_board_writer
        self._notifier = notifier
        self._self_perception = self_perception

    def set_self_perception(self, self_perception: Any) -> None:
        """Wire SelfPerception after construction."""
        self._self_perception = self_perception

    def create(
        self,
        candidate: RepairCandidate,
        snapshot_id: str,
        bypass_gate: bool = False,
    ) -> Optional[str]:
        """Create task + bulletin + TASK_BOARD echo + notification.

        ``bypass_gate=True`` skips the eligibility gate (mode/NIM/freshness/
        cooldown). It exists ONLY for the operator live drill
        (``/drill_repair force``), so the creation chain can be exercised on
        demand even in SLEEP. The created task is still ``approval_required``,
        so it never auto-dispatches -- a drill is harmless.
        """
        snapshot = self._latest_snapshot()
        refusal = None if bypass_gate else self._gate_refusal(candidate, snapshot)
        if refusal is not None:
            logger.info("[SelfRepair] refused task creation: reason=%s", refusal)
            return None

        now = time.time()
        title = _truncate_title(f"Self-repair: {candidate.summary}")
        description = self._build_description(title, candidate)
        task = create_task(
            project="maria",
            phase="self_repair",
            title=title,
            description=description,
            priority=0.8,
            assignee=Assignee.CODEX,
            dependencies=[],
        )
        task.created_at = now
        task.updated_at = now
        task.artifacts = {
            "repair_kind": candidate.repair_kind,
            "repair_subject": _candidate_subject(candidate),
            "evidence_summary": candidate.evidence_summary,
            "created_by": "maria_self_diagnosis",
            "snapshot_id": snapshot_id or str(snapshot.get("snapshot_id", "")),
            "workspace_path": WORKSPACE_PATH,
            "approval_required": True,
            "drill": candidate.repair_kind == "drill"
            or bool(candidate.evidence_summary.get("drill")),
            "expires_at": now + REPAIR_TASK_TTL_SECONDS,
        }
        self._conductor.add_task(task)

        short_description = candidate.summary[:140]
        if self._bulletin_store is not None:
            try:
                bulletin_model = importlib.import_module(
                    "agent_core.bulletin.bulletin_model"
                )
                entry_type = bulletin_model.EntryType.IMPROVEMENT

                self._bulletin_store.create_and_post(
                    entry_type=entry_type,
                    topic=f"self_repair_{candidate.repair_kind}",
                    reason_code=f"self_repair_{candidate.repair_kind}",
                    summary=f"Self-repair created: {short_description}",
                    requested_by="self_repair_monitor",
                    priority=0.7,
                    metadata={
                        "task_id": task.task_id,
                        "repair_kind": candidate.repair_kind,
                        "evidence_summary": candidate.evidence_summary,
                    },
                )
            except Exception:
                logger.warning("[SelfRepair] bulletin post failed", exc_info=True)

        if self._task_board_writer is not None:
            try:
                self._task_board_writer.append_repair_entry(
                    task_id=task.task_id,
                    title=title,
                    repair_kind=candidate.repair_kind,
                    evidence_summary=candidate.evidence_summary,
                    expires_at=task.artifacts["expires_at"],
                )
            except Exception:
                logger.warning("[SelfRepair] TASK_BOARD echo failed", exc_info=True)

        _send_notification(
            self._notifier,
            (
                f"[Self-repair] Created {task.task_id}: {candidate.summary}\n"
                f"Approve: /approve_repair {task.task_id}"
            ),
        )
        return task.task_id

    def _latest_snapshot(self) -> Dict[str, Any]:
        if self._self_perception is None:
            return {}
        latest = self._self_perception.get_latest()
        return latest if isinstance(latest, dict) else {}

    def _gate_refusal(
        self,
        candidate: RepairCandidate,
        snapshot: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if self._self_perception is None:
            return {"reason": "missing_self_perception"}
        try:
            if not self._self_perception.is_fresh(max_age_seconds=300):
                return {"reason": "stale_snapshot", "repair_kind": candidate.repair_kind}
        except TypeError:
            if not self._self_perception.is_fresh(300):
                return {"reason": "stale_snapshot", "repair_kind": candidate.repair_kind}

        mode = str(snapshot.get("mode", ""))
        if mode not in ("ACTIVE", "REDUCED"):
            return {
                "reason": "mode_not_eligible",
                "mode": mode,
                "repair_kind": candidate.repair_kind,
            }

        nim_status = _service_status(snapshot, "NVIDIA NIM API")
        if nim_status != "available":
            # Don't deadlock the detector that is REPORTING a NIM outage: a
            # model_unavailable candidate whose subject IS NIM must still create
            # its alert even though NIM is down -- otherwise a genuine NIM outage
            # can never surface (the gate blocked the very task meant to flag it,
            # audit 2026-06-16 #14). All other repair kinds still require NIM.
            subject = _candidate_subject(candidate)
            is_nim_self_report = (
                candidate.repair_kind == "model_unavailable"
                and subject == "NVIDIA NIM API"
            )
            if not is_nim_self_report:
                return {
                    "reason": "nim_unavailable",
                    "nim_status": nim_status,
                    "repair_kind": candidate.repair_kind,
                }

        if self._pending_same_kind_in_cooldown(candidate.repair_kind):
            return {"reason": "cooldown", "repair_kind": candidate.repair_kind}
        return None

    def _pending_same_kind_in_cooldown(self, repair_kind: str) -> bool:
        now = time.time()
        if hasattr(self._conductor, "get_pending_repair_tasks"):
            tasks = self._conductor.get_pending_repair_tasks()
        else:
            tasks = self._conductor.list_tasks(
                project="maria",
                status=TaskStatus.PENDING,
            )
        for task in tasks:
            if task.artifacts.get("repair_kind") != repair_kind:
                continue
            if now - float(task.created_at) < COOLDOWN_SECONDS:
                return True
        return False

    def _build_description(
        self,
        title: str,
        candidate: RepairCandidate,
    ) -> str:
        evidence = json.dumps(
            candidate.evidence_summary,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        return f"""# {title}

## Context
This task was created autonomously by Maria's SystemFailureMonitor
after detecting a systemic problem in the running system. Maria is
the local autonomous AI agent project at /home/maria/maria. You
are running on Maria's behalf via the Conductor dispatcher.

## Detection evidence
```json
{evidence}
```

## Repair kind: {candidate.repair_kind}

### If repair_kind == "model_unavailable":
The named service has been unavailable for at least 2 consecutive
30-min snapshots. Determine root cause: is it network, configuration,
credentials, or the upstream service itself? Files to investigate:
- For NIM: `agent_core/llm/nim_client.py`, `.env` NVIDIA_NIM_*
  variables, last 100 lines of `meta_data/llm_tape.jsonl`.
- For Ollama: `systemctl status ollama` (read-only diagnostic),
  `agent_core/llm/llm_manager.py`.
- For OpenClaw: `agent_core/effector/openclaw_client.py`,
  `pgrep openclaw_gateway`.
Output: a markdown diagnostic to stdout AND a code fix if possible.
If no fix possible (e.g. upstream API outage), produce diagnostic
and recommended operator action only. Do not make speculative changes.

### If repair_kind == "dispatcher_stuck":
A Conductor task has been IN_PROGRESS for >60 minutes. Diagnose:
inspect `meta_data/<project>_task_queue.jsonl` for the stuck task;
check logs for the assignee; determine whether to mark BLOCKED,
re-PENDING, or extend the timeout. Files:
- `agent_core/conductor/dispatcher.py` (dispatch logic)
- `agent_core/conductor/conductor.py` (lifecycle methods)
Output: code change OR mark the task appropriately via conductor
lifecycle methods + commit.

### If repair_kind == "action_failure_storm":
At least 30% of actions in the last hour have failed. Read
`meta_data/action_audit.jsonl` (last hour), group failures by
`action_type` + `goal_id`, identify the dominant failure pattern.
Files to investigate depend on the dominant action_type:
- learn -> `agent_core/teacher/learning_agent.py`
- fetch -> `agent_core/web_source/`
- exam -> `agent_core/teacher/exam_agent.py`
Output: diagnostic + targeted fix.

### If repair_kind == "thread_unhealthy":
A background thread died (persistent) or wedged (transient, alive far
past any sane cycle); the main-loop watchdog cannot see either. Read
`evidence_summary.thread_name` + `condition`:
- TickWatchdog dead -> the freeze emergency brake is gone; a restart
  re-arms it (`HomeostasisCore.start_watchdog`).
- TelegramPoll wedged -> escalation channel stalled, likely a blocked
  HTTP poll; `agent_core/homeostasis/core.py` `_check_telegram_trigger`.
- PlannerCycle / TeacherAutoSession wedged -> a blocking LLM call
  (cf. the 2026-06-02 Ollama freeze, now relocated to a bg thread);
  `agent_core/planner/`, `agent_core/teacher/`, heavy mutex /
  `OLLAMA_HTTP_TIMEOUT`.
Output: diagnostic + recommended operator action (restart if a
persistent thread died). Do not make speculative changes.

## Constraints
- Branch: `refactor/homeostasis` inline.
- Conventions: see `CLAUDE.md` and `docs/orchestration/WORKER_BRIEF_TEMPLATE.md`.
- Tests: full `agent_core/tests/` must still pass.
- Auto-commit safeguard: do not commit unrelated work. Pre-dispatch
  workspace was verified clean.

## Done criteria
- Diagnostic written to stdout in the Codex response.
- If code change made: tests still pass, commit on `refactor/homeostasis`.
- If no fix possible: explain why + recommend operator action.
"""


def _truncate_title(title: str) -> str:
    if len(title) <= 80:
        return title
    return title[:77].rstrip() + "..."


def _candidate_subject(candidate: RepairCandidate) -> Optional[str]:
    subject = candidate.evidence_summary.get("subject")
    if subject is not None:
        return str(subject)
    if candidate.repair_kind == "model_unavailable":
        return str(candidate.evidence_summary.get("service_name", ""))
    if candidate.repair_kind == "dispatcher_stuck":
        return str(candidate.evidence_summary.get("project", ""))
    return None


def _service_status(snapshot: Dict[str, Any], service_name: str) -> str:
    for service in snapshot.get("external_services", []) or []:
        if isinstance(service, dict) and service.get("name") == service_name:
            return str(service.get("status", "unknown"))
    return "unknown"


def _send_notification(notifier: Any, text: str) -> None:
    if notifier is None:
        return
    # Quiet hours: the repair task is already queued (/pending_repairs) with a
    # 24h expiry, echoed to the bulletin and the task board, before this ping.
    # Defer the night notice rather than wake the operator -- self-repair is an
    # ALERT the operator closes in-session (ADR-031), not something to act on at
    # 3am, and the task outlives the night.
    if getattr(notifier, "in_quiet_hours", lambda: False)():
        return
    # PLAIN TEXT (parse_mode=None): the body carries '/approve_repair <id>'.
    # Telegram Markdown treats '_' as italic and, when underscores balance,
    # silently eats them -- '/approve_repair' would arrive as '/approverepair'
    # and fail. No API error is raised, so the markdown->plain fallback never
    # fires. See agent_core/telegram/notifier.py send_raw docstring.
    try:
        if hasattr(notifier, "send_raw"):
            notifier.send_raw(text, parse_mode=None)
        elif hasattr(notifier, "send_message"):
            notifier.send_message(text)
        elif hasattr(notifier, "_bot") and hasattr(notifier._bot, "send_message"):
            notifier._bot.send_message(text, parse_mode=None)
    except Exception:
        logger.warning("[SelfRepair] Telegram notification failed", exc_info=True)
