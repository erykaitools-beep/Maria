"""
Workflow Engine - multi-step process execution with checkpoints.

Design principles (from roadmap):
- Linear sequences first, branching later if needed
- One step per advance() call (non-blocking, driven by planner tick)
- Persistent state survives restarts
- Operator can pause/resume/cancel at any time
"""

import logging
import time
from typing import Any, Dict, List, Optional

from agent_core.workflow.workflow_model import (
    FailPolicy,
    StepResult,
    WorkflowState,
    WorkflowStatus,
    WorkflowStep,
    create_workflow,
)
from agent_core.workflow.workflow_store import WorkflowStore
from agent_core.workflow.delegation import DelegationManager

logger = logging.getLogger(__name__)

MAX_ACTIVE_WORKFLOWS = 5
MAX_TOTAL_WORKFLOWS = 100


class WorkflowEngine:
    """
    Orchestrates multi-step workflows.

    Usage:
        engine = WorkflowEngine(store, delegation)
        wf = engine.create("research", "Research topic X", steps)
        engine.start(wf.workflow_id)
        # Called each planner tick:
        result = engine.advance(wf.workflow_id)
    """

    def __init__(
        self,
        store: WorkflowStore,
        delegation: DelegationManager,
    ):
        self._store = store
        self._delegation = delegation
        self._progress_reporter = None

    def set_progress_reporter(self, reporter: Any) -> None:
        """Set optional ProgressReporter for Telegram/perception events."""
        self._progress_reporter = reporter

    # --- Lifecycle ---

    def create(
        self,
        name: str,
        description: str,
        steps: List[WorkflowStep],
        goal_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkflowState:
        """Create a new workflow (status=PENDING)."""
        if not steps:
            raise ValueError("Workflow must have at least one step")

        active = self._store.list_active()
        if len(active) >= MAX_ACTIVE_WORKFLOWS:
            raise ValueError(
                f"Too many active workflows ({len(active)}/{MAX_ACTIVE_WORKFLOWS}). "
                "Complete or cancel existing ones first."
            )

        wf = create_workflow(name, description, steps, goal_id, metadata)
        self._store.save(wf)
        logger.info("Created workflow %s: %s (%d steps)",
                     wf.workflow_id, name, len(steps))
        return wf

    def start(self, workflow_id: str) -> bool:
        """Start a PENDING workflow."""
        wf = self._store.get(workflow_id)
        if wf is None:
            logger.warning("Workflow %s not found", workflow_id)
            return False
        if wf.status != WorkflowStatus.PENDING:
            logger.warning("Cannot start workflow %s in status %s",
                           workflow_id, wf.status.value)
            return False

        wf.status = WorkflowStatus.RUNNING
        wf.current_step = 0
        wf.updated_at = time.time()
        self._store.save(wf)

        if self._progress_reporter:
            self._progress_reporter.on_workflow_started(wf)

        logger.info("Started workflow %s", workflow_id)
        return True

    def advance(self, workflow_id: str) -> Optional[StepResult]:
        """
        Execute the next step of a running workflow.

        Returns StepResult if a step was executed, None if nothing to do.
        Called once per planner tick for active workflows.
        """
        wf = self._store.get(workflow_id)
        if wf is None:
            return None
        if wf.status != WorkflowStatus.RUNNING:
            return None

        step = wf.current_step_def
        if step is None:
            # All steps done
            self._complete(wf)
            return None

        # Check if step requires approval
        if step.requires_approval:
            if not wf.metadata.get(f"step_{step.order}_approved"):
                wf.status = WorkflowStatus.PAUSED
                wf.paused_by = "approval_needed"
                wf.updated_at = time.time()
                self._store.save(wf)
                if self._progress_reporter:
                    self._progress_reporter.on_step_approval_needed(wf, step)
                return None

        # Execute step
        result = self._delegation.delegate(step, wf.goal_id)
        wf.results.append(result)
        wf.updated_at = time.time()

        if result.success:
            self._handle_success(wf, step, result)
        else:
            self._handle_failure(wf, step, result)

        return result

    def advance_next_active(self) -> Optional[StepResult]:
        """Advance the highest-priority active workflow. For tick loop."""
        active = self._store.list_active()
        running = [wf for wf in active if wf.status == WorkflowStatus.RUNNING]
        if not running:
            return None
        # Oldest running workflow first (FIFO)
        running.sort(key=lambda w: w.created_at)
        return self.advance(running[0].workflow_id)

    # --- Control ---

    def pause(self, workflow_id: str, by: str = "operator") -> bool:
        """Pause a running workflow."""
        wf = self._store.get(workflow_id)
        if wf is None or wf.status != WorkflowStatus.RUNNING:
            return False

        wf.status = WorkflowStatus.PAUSED
        wf.paused_by = by
        wf.updated_at = time.time()
        self._store.save(wf)

        if self._progress_reporter:
            self._progress_reporter.on_workflow_paused(wf)

        logger.info("Paused workflow %s (by: %s)", workflow_id, by)
        return True

    def resume(self, workflow_id: str) -> bool:
        """Resume a paused workflow."""
        wf = self._store.get(workflow_id)
        if wf is None or wf.status != WorkflowStatus.PAUSED:
            return False

        wf.status = WorkflowStatus.RUNNING
        wf.paused_by = None
        wf.updated_at = time.time()
        self._store.save(wf)

        if self._progress_reporter:
            self._progress_reporter.on_workflow_resumed(wf)

        logger.info("Resumed workflow %s", workflow_id)
        return True

    def cancel(self, workflow_id: str, reason: str = "") -> bool:
        """Cancel a non-terminal workflow."""
        wf = self._store.get(workflow_id)
        if wf is None or wf.is_terminal:
            return False

        wf.status = WorkflowStatus.CANCELLED
        wf.error = reason or "Cancelled by operator"
        wf.completed_at = time.time()
        wf.updated_at = time.time()
        self._store.save(wf)

        if self._progress_reporter:
            self._progress_reporter.on_workflow_cancelled(wf)

        logger.info("Cancelled workflow %s: %s", workflow_id, reason)
        return True

    def approve_step(self, workflow_id: str, step_order: int) -> bool:
        """Approve a step that requires approval."""
        wf = self._store.get(workflow_id)
        if wf is None:
            return False
        wf.metadata[f"step_{step_order}_approved"] = True
        if wf.status == WorkflowStatus.PAUSED and wf.paused_by == "approval_needed":
            wf.status = WorkflowStatus.RUNNING
            wf.paused_by = None
        wf.updated_at = time.time()
        self._store.save(wf)
        return True

    # --- Query ---

    def get_progress(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow progress summary."""
        wf = self._store.get(workflow_id)
        if wf is None:
            return None

        completed_steps = [r for r in wf.results if r.success]
        failed_steps = [r for r in wf.results if not r.success]

        return {
            "workflow_id": wf.workflow_id,
            "name": wf.name,
            "status": wf.status.value,
            "progress_pct": wf.progress_pct,
            "current_step": wf.current_step,
            "total_steps": len(wf.steps),
            "completed_steps": len(completed_steps),
            "failed_steps": len(failed_steps),
            "current_action": wf.current_step_def.description if wf.current_step_def else None,
            "total_duration_ms": sum(r.duration_ms for r in wf.results),
            "error": wf.error,
            "paused_by": wf.paused_by,
        }

    def list_workflows(
        self, status: Optional[WorkflowStatus] = None
    ) -> List[Dict[str, Any]]:
        """List workflows as summary dicts."""
        wfs = self._store.list_all(status)
        return [
            {
                "workflow_id": wf.workflow_id,
                "name": wf.name,
                "status": wf.status.value,
                "progress_pct": wf.progress_pct,
                "steps": len(wf.steps),
                "created_at": wf.created_at,
                "updated_at": wf.updated_at,
                "goal_id": wf.goal_id,
            }
            for wf in wfs[:20]  # Cap list output
        ]

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowState]:
        """Get full workflow state."""
        return self._store.get(workflow_id)

    # --- Internal ---

    def _handle_success(
        self, wf: WorkflowState, step: WorkflowStep, result: StepResult
    ) -> None:
        """Handle successful step execution."""
        logger.info("Workflow %s step %d/%d completed: %s",
                     wf.workflow_id, step.order + 1, len(wf.steps), step.action)

        wf.current_step += 1

        if wf.current_step >= len(wf.steps):
            self._complete(wf)
        else:
            if step.checkpoint:
                self._store.save(wf)
            if self._progress_reporter:
                self._progress_reporter.on_step_completed(wf, step, result)

    def _handle_failure(
        self, wf: WorkflowState, step: WorkflowStep, result: StepResult
    ) -> None:
        """Handle failed step execution based on FailPolicy."""
        logger.warning("Workflow %s step %d failed: %s - %s",
                        wf.workflow_id, step.order, step.action, result.error)

        if step.on_fail == FailPolicy.RETRY and result.retries_used < step.max_retries:
            # Will retry on next advance() call (don't move current_step)
            logger.info("Will retry step %d (attempt %d/%d)",
                        step.order, result.retries_used + 1, step.max_retries)
            self._store.save(wf)
            return

        if step.on_fail == FailPolicy.SKIP:
            logger.info("Skipping failed step %d, continuing", step.order)
            wf.current_step += 1
            if wf.current_step >= len(wf.steps):
                self._complete(wf)
            else:
                self._store.save(wf)
            if self._progress_reporter:
                self._progress_reporter.on_step_skipped(wf, step, result)
            return

        # STOP (default)
        wf.status = WorkflowStatus.FAILED
        wf.error = result.error or f"Step {step.order} ({step.action}) failed"
        wf.completed_at = time.time()
        self._store.save(wf)

        if self._progress_reporter:
            self._progress_reporter.on_workflow_failed(wf, step, result)

    def _complete(self, wf: WorkflowState) -> None:
        """Mark workflow as completed."""
        wf.status = WorkflowStatus.COMPLETED
        wf.completed_at = time.time()
        wf.updated_at = time.time()
        self._store.save(wf)

        if self._progress_reporter:
            self._progress_reporter.on_workflow_completed(wf)

        logger.info("Workflow %s completed (%d steps, %.0f%% success)",
                     wf.workflow_id, len(wf.steps), wf.progress_pct)
