"""Hardcoded systemic failure detectors for self-repair."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agent_core.conductor.task_model import TaskStatus

logger = logging.getLogger("agent_core.self_repair")

MODEL_UNAVAILABLE = "model_unavailable"
DISPATCHER_STUCK = "dispatcher_stuck"
ACTION_FAILURE_STORM = "action_failure_storm"
THREAD_UNHEALTHY = "thread_unhealthy"

COOLDOWN_SECONDS = 4 * 3600
DISPATCHER_STUCK_SECONDS = 60 * 60
ACTION_WINDOW_SECONDS = 60 * 60
ACTION_MIN_SAMPLE = 10
ACTION_FAILURE_RATE = 0.30
# A transient worker (PlannerCycle/TeacherAutoSession) alive this long is
# wedged, not working: any sane cycle finishes well under this. The 2026-06-02
# Ollama freeze ran 10.5h; 30 min is a safe ceiling that never false-positives
# on a legitimately long learning session.
THREAD_WEDGE_SECONDS = 30 * 60

SERVICE_NAMES = (
    "NVIDIA NIM API",
    "Ollama (local LLM)",
    "OpenClaw Effector",
)

CooldownLookup = Callable[[str, Optional[str]], bool]


@dataclass(frozen=True)
class RepairCandidate:
    """Candidate systemic failure that may become a self-repair task."""

    repair_kind: str
    summary: str
    evidence_summary: Dict[str, Any]
    detected_at: float


def detect_model_unavailable(
    snapshot_store: Any,
    cooldown_lookup: CooldownLookup,
) -> List[RepairCandidate]:
    """Detect services that flipped available -> unavailable in 3 snapshots."""
    try:
        snapshots = snapshot_store.load_recent(3)
    except Exception:
        logger.warning("[SelfRepair] model detector failed", exc_info=True)
        return []

    if len(snapshots) < 3:
        return []

    first, second, third = snapshots[-3], snapshots[-2], snapshots[-1]
    candidates: List[RepairCandidate] = []
    for service_name in SERVICE_NAMES:
        first_status = _service_status(first, service_name)
        second_status = _service_status(second, service_name)
        third_status = _service_status(third, service_name)
        if first_status != "available":
            continue
        if not (
            _is_unavailable(service_name, second_status)
            and _is_unavailable(service_name, third_status)
        ):
            continue
        if _in_cooldown(cooldown_lookup, MODEL_UNAVAILABLE, service_name):
            logger.info(
                "[SelfRepair] refused task creation: reason=%s",
                {
                    "reason": "cooldown",
                    "repair_kind": MODEL_UNAVAILABLE,
                    "subject": service_name,
                },
            )
            continue

        short_name = _service_short_name(service_name)
        candidates.append(
            RepairCandidate(
                repair_kind=MODEL_UNAVAILABLE,
                summary=f"{short_name} unavailable across last 2 snapshots",
                evidence_summary={
                    "service_name": service_name,
                    "subject": service_name,
                    "statuses": [first_status, second_status, third_status],
                    "snapshot_ids": [
                        first.get("snapshot_id"),
                        second.get("snapshot_id"),
                        third.get("snapshot_id"),
                    ],
                    "one_line": (
                        f"{short_name}: {first_status} -> "
                        f"{second_status} -> {third_status}"
                    ),
                },
                detected_at=time.time(),
            )
        )
    return candidates


def detect_dispatcher_stuck(
    conductor: Any,
    cooldown_lookup: CooldownLookup,
) -> List[RepairCandidate]:
    """Detect non-maria tasks stuck in progress for more than 60 minutes."""
    now = time.time()
    try:
        tasks = conductor.list_tasks(status=TaskStatus.IN_PROGRESS)
    except Exception:
        logger.warning("[SelfRepair] dispatcher detector failed", exc_info=True)
        return []

    candidates: List[RepairCandidate] = []
    for task in tasks:
        project = getattr(task, "project", "")
        if project == "maria":
            continue
        stale_seconds = now - float(getattr(task, "updated_at", now) or now)
        if stale_seconds <= DISPATCHER_STUCK_SECONDS:
            continue
        if _in_cooldown(cooldown_lookup, DISPATCHER_STUCK, project):
            logger.info(
                "[SelfRepair] refused task creation: reason=%s",
                {
                    "reason": "cooldown",
                    "repair_kind": DISPATCHER_STUCK,
                    "subject": project,
                },
            )
            continue
        candidates.append(
            RepairCandidate(
                repair_kind=DISPATCHER_STUCK,
                summary=f"Dispatcher stuck for project {project}",
                evidence_summary={
                    "project": project,
                    "subject": project,
                    "task_id": getattr(task, "task_id", ""),
                    "title": getattr(task, "title", ""),
                    "updated_at": getattr(task, "updated_at", None),
                    "stale_seconds": round(stale_seconds, 1),
                    "one_line": (
                        f"{project}: task {getattr(task, 'task_id', '')} "
                        f"stale for {int(stale_seconds // 60)} min"
                    ),
                },
                detected_at=now,
            )
        )
    return candidates


def _is_real_failure(record: Dict[str, Any]) -> bool:
    """A genuine action failure -- not a skipped (declined) action.

    T-LEARN-003: skipped actions are audited with success=False but were never
    attempted (outside window, no material). Counting them would inflate the
    failure-storm rate -- exactly the false "4/10 failed" exam storms seen when
    the planner skipped off-window exams.
    """
    return record.get("success") is False and not record.get("skipped")


def detect_action_failure_storm(
    audit_path: Path,
    cooldown_lookup: CooldownLookup,
) -> List[RepairCandidate]:
    """Detect high failure rate in the action audit over the last hour."""
    if _in_cooldown(cooldown_lookup, ACTION_FAILURE_STORM, None):
        logger.info(
            "[SelfRepair] refused task creation: reason=%s",
            {"reason": "cooldown", "repair_kind": ACTION_FAILURE_STORM},
        )
        return []

    now = time.time()
    records: List[Dict[str, Any]] = []
    if not audit_path.exists():
        return []

    try:
        with open(audit_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                timestamp = record.get("timestamp")
                if not isinstance(timestamp, (int, float)):
                    continue
                if now - float(timestamp) <= ACTION_WINDOW_SECONDS:
                    records.append(record)
    except OSError:
        logger.warning("[SelfRepair] action audit read failed", exc_info=True)
        return []

    total = len(records)
    if total < ACTION_MIN_SAMPLE:
        return []
    failures = sum(1 for record in records if _is_real_failure(record))
    failure_rate = failures / total if total else 0.0
    if failure_rate < ACTION_FAILURE_RATE:
        return []

    by_action: Dict[str, Dict[str, int]] = {}
    for record in records:
        action_type = str(record.get("action_type", "unknown"))
        bucket = by_action.setdefault(action_type, {"total": 0, "failures": 0})
        bucket["total"] += 1
        if _is_real_failure(record):
            bucket["failures"] += 1

    return [
        RepairCandidate(
            repair_kind=ACTION_FAILURE_STORM,
            summary=f"Action failure storm: {failures}/{total} failed",
            evidence_summary={
                "total_actions": total,
                "failures": failures,
                "failure_rate": round(failure_rate, 3),
                "window_seconds": ACTION_WINDOW_SECONDS,
                "by_action_type": by_action,
                "one_line": f"{failures}/{total} actions failed in the last hour",
            },
            detected_at=now,
        )
    ]


def detect_thread_unhealthy(
    thread_health: List[Dict[str, Any]],
    cooldown_lookup: CooldownLookup,
) -> List[RepairCandidate]:
    """Detect background threads that died (persistent) or wedged (transient).

    7b heartbeat watchdog. The out-of-loop ``TickWatchdog`` only catches a
    frozen MAIN loop; a worker thread can die or wedge while the main loop
    ticks on, and nothing notices:
      * persistent (``TelegramPoll``, ``TickWatchdog``) -- if it dies, the
        escalation channel / emergency brake is silently gone.
      * transient (``PlannerCycle``, ``TeacherAutoSession``) -- if it wedges
        (the Ollama-call freeze that hung the loop on 2026-06-02, now relocated
        to a background thread), planning/learning silently halts because the
        trigger sees ``is_alive()==True`` and never re-spawns.
    Neither is observable from the main-loop heartbeat. This detector surfaces
    them through the normal repair-task path (operator alert, ADR-031).

    ``thread_health`` is what ``HomeostasisCore.get_thread_health()`` returns:
    each entry is ``{name, kind('persistent'|'transient'), alive, age_sec}``.
    """
    now = time.time()
    candidates: List[RepairCandidate] = []
    for entry in thread_health or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")) or "unknown"
        kind = str(entry.get("kind", ""))
        alive = bool(entry.get("alive", False))
        age_sec = entry.get("age_sec")

        condition: Optional[str] = None
        detail = ""
        if kind == "persistent" and not alive:
            condition = "dead"
            detail = f"{name}: persistent thread is dead"
        elif (
            kind == "transient"
            and alive
            and isinstance(age_sec, (int, float))
            and age_sec >= THREAD_WEDGE_SECONDS
        ):
            condition = "wedged"
            detail = (
                f"{name}: transient thread alive {int(age_sec // 60)} min "
                f"(>= {THREAD_WEDGE_SECONDS // 60} min)"
            )
        if condition is None:
            continue

        if _in_cooldown(cooldown_lookup, THREAD_UNHEALTHY, name):
            logger.info(
                "[SelfRepair] refused task creation: reason=%s",
                {
                    "reason": "cooldown",
                    "repair_kind": THREAD_UNHEALTHY,
                    "subject": name,
                },
            )
            continue

        candidates.append(
            RepairCandidate(
                repair_kind=THREAD_UNHEALTHY,
                summary=f"Thread unhealthy ({condition}): {name}",
                evidence_summary={
                    "thread_name": name,
                    "subject": name,
                    "kind": kind,
                    "condition": condition,
                    "alive": alive,
                    "age_sec": (
                        round(age_sec, 1)
                        if isinstance(age_sec, (int, float))
                        else None
                    ),
                    "one_line": detail,
                },
                detected_at=now,
            )
        )
    return candidates


def _service_status(snapshot: Dict[str, Any], service_name: str) -> str:
    for service in snapshot.get("external_services", []) or []:
        if isinstance(service, dict) and service.get("name") == service_name:
            return str(service.get("status", "unknown"))
    return "unknown"


def _is_unavailable(service_name: str, status: str) -> bool:
    """Whether a snapshot status string means the service is DOWN.

    Vocabulary must match what tool_registry actually emits per service (audit
    2026-06-16):
    - NIM: emits "available" / "depleted" / "unknown". "depleted" is RPM/budget
      back-pressure (normal -- NIM is reachable, just rate/budget-limited), NOT an
      outage, so it must NOT trip model_unavailable (was a false positive). Only a
      genuine "unavailable" counts.
    - OpenClaw emits "disconnected", Codex "not_configured" -- the old check only
      matched "unavailable", so an actually-down effector NEVER tripped (false
      negative). Treat both as down.
    Ollama is hardcoded "available" in tool_registry (no cheap reliable probe;
    a fake one would lie -- see ADR note), so its liveness is covered by
    detect_thread_unhealthy (PlannerCycle/TeacherAutoSession wedge), not here.
    """
    if service_name == "NVIDIA NIM API":
        return status == "unavailable"
    return status in ("unavailable", "disconnected", "not_configured")


def _service_short_name(service_name: str) -> str:
    if service_name == "NVIDIA NIM API":
        return "NIM API"
    if service_name == "Ollama (local LLM)":
        return "Ollama"
    if service_name == "OpenClaw Effector":
        return "OpenClaw"
    return service_name


def _in_cooldown(
    cooldown_lookup: CooldownLookup,
    repair_kind: str,
    subject: Optional[str],
) -> bool:
    return bool(cooldown_lookup(repair_kind, subject))
