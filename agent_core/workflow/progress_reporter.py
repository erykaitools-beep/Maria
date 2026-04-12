"""
Progress Reporter - workflow events to Telegram + PerceptionBuffer.

Respects notification cooldowns and SalienceFilter conventions.
"""

import logging
import time
from typing import Any, Optional

from agent_core.workflow.workflow_model import StepResult, WorkflowState, WorkflowStep

logger = logging.getLogger(__name__)

# Cooldowns per event type (seconds)
COOLDOWN_STEP_COMPLETE = 60       # Max 1 step notification per minute
COOLDOWN_WORKFLOW_EVENT = 30      # Start/pause/resume/cancel


class ProgressReporter:
    """Reports workflow progress via Telegram and perception events."""

    def __init__(self):
        self._telegram_notifier = None  # Callable: (message: str) -> None
        self._perception_buffer = None
        self._last_notify: dict = {}    # event_type -> timestamp

    def set_telegram_notifier(self, notifier: Any) -> None:
        """Set Telegram send function: (message: str) -> None."""
        self._telegram_notifier = notifier

    def set_perception_buffer(self, buffer: Any) -> None:
        """Set PerceptionBuffer for internal event emission."""
        self._perception_buffer = buffer

    # --- Workflow lifecycle events ---

    def on_workflow_started(self, wf: WorkflowState) -> None:
        msg = (
            f"Workflow started: {wf.name}\n"
            f"Steps: {len(wf.steps)}\n"
            f"ID: {wf.workflow_id[:16]}"
        )
        self._notify("wf_start", msg)
        self._emit_event("workflow_started", wf.workflow_id, {"name": wf.name})

    def on_workflow_completed(self, wf: WorkflowState) -> None:
        duration = (wf.completed_at or time.time()) - wf.created_at
        mins = duration / 60
        msg = (
            f"Workflow completed: {wf.name}\n"
            f"Steps: {len(wf.results)}/{len(wf.steps)}\n"
            f"Duration: {mins:.1f}min\n"
            f"Success rate: {wf.progress_pct:.0f}%"
        )
        self._notify("wf_complete", msg, force=True)
        self._emit_event("workflow_completed", wf.workflow_id, {
            "name": wf.name,
            "duration_min": round(mins, 1),
            "success_pct": wf.progress_pct,
        })

    def on_workflow_failed(
        self, wf: WorkflowState, step: WorkflowStep, result: StepResult
    ) -> None:
        msg = (
            f"Workflow FAILED: {wf.name}\n"
            f"Failed at step {step.order + 1}/{len(wf.steps)}: {step.description}\n"
            f"Error: {result.error or 'unknown'}"
        )
        self._notify("wf_fail", msg, force=True)
        self._emit_event("workflow_failed", wf.workflow_id, {
            "name": wf.name,
            "failed_step": step.order,
            "error": result.error,
        })

    def on_workflow_paused(self, wf: WorkflowState) -> None:
        msg = f"Workflow paused: {wf.name} (by: {wf.paused_by})"
        self._notify("wf_pause", msg)
        self._emit_event("workflow_paused", wf.workflow_id, {
            "name": wf.name,
            "paused_by": wf.paused_by,
        })

    def on_workflow_resumed(self, wf: WorkflowState) -> None:
        msg = f"Workflow resumed: {wf.name}"
        self._notify("wf_resume", msg)
        self._emit_event("workflow_resumed", wf.workflow_id, {
            "name": wf.name,
        })

    def on_workflow_cancelled(self, wf: WorkflowState) -> None:
        msg = f"Workflow cancelled: {wf.name}\nReason: {wf.error or 'operator'}"
        self._notify("wf_cancel", msg, force=True)
        self._emit_event("workflow_cancelled", wf.workflow_id, {
            "name": wf.name,
            "reason": wf.error,
        })

    # --- Step events ---

    def on_step_completed(
        self, wf: WorkflowState, step: WorkflowStep, result: StepResult
    ) -> None:
        msg = (
            f"[{wf.name}] Step {step.order + 1}/{len(wf.steps)}: "
            f"{step.description} ({result.duration_ms:.0f}ms)"
        )
        self._notify("step_complete", msg)

    def on_step_skipped(
        self, wf: WorkflowState, step: WorkflowStep, result: StepResult
    ) -> None:
        msg = (
            f"[{wf.name}] Step {step.order + 1} SKIPPED: "
            f"{step.description} (error: {result.error})"
        )
        self._notify("step_skip", msg)

    def on_step_approval_needed(
        self, wf: WorkflowState, step: WorkflowStep
    ) -> None:
        msg = (
            f"Workflow {wf.name} needs approval\n"
            f"Step {step.order + 1}: {step.description}\n"
            f"Use: /wf approve {wf.workflow_id[:8]} {step.order}"
        )
        self._notify("step_approval", msg, force=True)

    # --- Internal ---

    def _notify(self, event_type: str, message: str, force: bool = False) -> None:
        """Send Telegram notification with cooldown."""
        if self._telegram_notifier is None:
            return

        now = time.time()
        cooldown = COOLDOWN_WORKFLOW_EVENT
        if event_type == "step_complete":
            cooldown = COOLDOWN_STEP_COMPLETE

        if not force:
            last = self._last_notify.get(event_type, 0)
            if now - last < cooldown:
                return

        try:
            self._telegram_notifier(message)
            self._last_notify[event_type] = now
        except Exception as e:
            logger.warning("Telegram notify failed: %s", e)

    def _emit_event(
        self, event_type: str, workflow_id: str, data: dict
    ) -> None:
        """Emit perception event."""
        if self._perception_buffer is None:
            return
        try:
            from agent_core.perception.event import (
                create_event,
                PerceptionSource,
            )
            event = create_event(
                source=PerceptionSource.PLANNER,
                event_type=event_type,
                payload={**data, "workflow_id": workflow_id},
                priority=0.6 if "fail" in event_type else 0.4,
            )
            self._perception_buffer.add(event)
        except Exception as e:
            logger.debug("Could not emit perception event: %s", e)
