"""System failure monitor orchestration."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, List, Optional

from agent_core.conductor.task_model import TaskStatus
from agent_core.self_repair.detectors import (
    COOLDOWN_SECONDS,
    RepairCandidate,
    detect_action_failure_storm,
    detect_dispatcher_stuck,
    detect_model_unavailable,
    detect_thread_unhealthy,
)

logger = logging.getLogger("agent_core.self_repair")


def _heartbeat_detector_enabled() -> bool:
    """7b flag (parallel-run): off by default, arm via .env HEARTBEAT_DETECTOR_ENABLED."""
    return os.environ.get("HEARTBEAT_DETECTOR_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


class SystemFailureMonitor:
    """Run whitelisted system-failure detectors and create repair tasks."""

    def __init__(
        self,
        self_perception: Any,
        conductor: Any,
        audit_path: Path,
        repair_task_creator: Any,
        heartbeat_provider: Optional[Any] = None,
    ):
        self._self_perception = self_perception
        self._conductor = conductor
        self._audit_path = audit_path
        self._repair_task_creator = repair_task_creator
        # 7b: live source of per-thread liveness (HomeostasisCore). Only used
        # when HEARTBEAT_DETECTOR_ENABLED is on; None = heartbeat detector off.
        self._heartbeat_provider = heartbeat_provider
        if hasattr(repair_task_creator, "set_self_perception"):
            repair_task_creator.set_self_perception(self_perception)

    def scan_and_create(self) -> List[str]:
        """Run detectors, gate candidates, and return created task IDs."""
        started = time.monotonic()
        latest = self._self_perception.get_latest()
        snapshot_store = getattr(self._self_perception, "_store", None)
        if snapshot_store is None:
            logger.info(
                "[SelfRepair] refused task creation: reason=%s",
                {"reason": "missing_snapshot_store"},
            )
            return []

        candidates: List[RepairCandidate] = []
        candidates.extend(
            detect_model_unavailable(snapshot_store, self._cooldown_lookup)
        )
        candidates.extend(
            detect_dispatcher_stuck(self._conductor, self._cooldown_lookup)
        )
        candidates.extend(
            detect_action_failure_storm(self._audit_path, self._cooldown_lookup)
        )

        # 7b heartbeat detector (flag-gated, parallel-run): dead/wedged worker
        # threads the main-loop watchdog structurally cannot see. Off by
        # default; wrapped so a provider glitch can never break the core 3.
        if self._heartbeat_provider is not None and _heartbeat_detector_enabled():
            try:
                health = self._heartbeat_provider.get_thread_health()
                candidates.extend(
                    detect_thread_unhealthy(health, self._cooldown_lookup)
                )
            except Exception:
                logger.warning(
                    "[SelfRepair] heartbeat detector failed", exc_info=True
                )

        # Finding #4: when a detector actually fires, refresh the self-state
        # snapshot on-demand. Phase 18 only snapshots every ~30 min, but the
        # repair gate (task_creator.is_fresh) requires one younger than 5 min —
        # so at a real failure it would otherwise refuse with stale_snapshot
        # most of the time. Guarded by `candidates`, so a healthy system (no
        # candidates) pays nothing. The mode gate + STOP-AT-PENDING are
        # untouched.
        if candidates and hasattr(self._self_perception, "take_snapshot"):
            try:
                self._self_perception.take_snapshot()
                latest = self._self_perception.get_latest()
            except Exception:
                logger.warning(
                    "[SelfRepair] on-demand snapshot refresh failed",
                    exc_info=True,
                )

        created: List[str] = []
        snapshot_id = ""
        if isinstance(latest, dict):
            snapshot_id = str(latest.get("snapshot_id", ""))
        for candidate in candidates:
            try:
                task_id = self._repair_task_creator.create(candidate, snapshot_id)
                if task_id:
                    created.append(task_id)
            except Exception:
                logger.warning(
                    "[SelfRepair] task creation failed for %s",
                    candidate.repair_kind,
                    exc_info=True,
                )

        elapsed_ms = (time.monotonic() - started) * 1000
        if elapsed_ms > 500:
            logger.warning(
                "[SelfRepair] scan exceeded budget: %.1fms",
                elapsed_ms,
            )
        return created

    def _cooldown_lookup(self, repair_kind: str, subject: Optional[str]) -> bool:
        now = time.time()
        for task in self._conductor.list_tasks(project="maria"):
            if getattr(task, "phase", "") != "self_repair":
                continue
            artifacts = getattr(task, "artifacts", {}) or {}
            if artifacts.get("repair_kind") != repair_kind:
                continue
            task_subject = artifacts.get("repair_subject")
            if subject is not None and task_subject not in (None, subject):
                continue
            if now - float(getattr(task, "created_at", 0.0) or 0.0) < COOLDOWN_SECONDS:
                return True
        return False

    def pending_same_kind_in_cooldown(self, repair_kind: str) -> bool:
        """Compatibility helper used by tests and diagnostics."""
        now = time.time()
        for task in self._conductor.list_tasks(
            project="maria",
            status=TaskStatus.PENDING,
        ):
            if getattr(task, "phase", "") != "self_repair":
                continue
            if task.artifacts.get("repair_kind") != repair_kind:
                continue
            if now - float(task.created_at) < COOLDOWN_SECONDS:
                return True
        return False
