"""
Delegation Manager - routes workflow steps to appropriate executors.

Uses CapabilityRouter for known actions, TaskExecutor for tool-based steps.
"""

import logging
import time
from typing import Any, Callable, Dict, Optional

from agent_core.workflow.workflow_model import StepResult, WorkflowStep

logger = logging.getLogger(__name__)


class DelegationManager:
    """Routes workflow steps to the right executor."""

    def __init__(self):
        self._capability_router = None
        self._task_executor = None
        self._plan_factory = None  # Callable to create Plan from step

    def set_capability_router(self, router: Any) -> None:
        self._capability_router = router

    def set_task_executor(self, executor: Any) -> None:
        self._task_executor = executor

    def set_plan_factory(self, factory: Callable) -> None:
        """Set factory: (action: str, params: dict, goal_id: str) -> Plan."""
        self._plan_factory = factory

    def delegate(
        self,
        step: WorkflowStep,
        goal_id: Optional[str] = None,
        attempt: int = 0,
    ) -> StepResult:
        """
        Execute a single workflow step via the best available executor.

        Priority:
        1. CapabilityRouter (for planner action types: learn, exam, fetch, etc.)
        2. TaskExecutor (for tool-based steps: wiki_search, file_write, etc.)
        3. Fallback: return failure
        """
        start = time.time()

        try:
            result = self._try_capability_router(step, goal_id)
            if result is not None:
                elapsed = (time.time() - start) * 1000
                return StepResult(
                    order=step.order,
                    action=step.action,
                    success=result.get("success", False),
                    result=result,
                    error=result.get("error"),
                    duration_ms=elapsed,
                    retries_used=attempt,
                )

            result = self._try_task_executor(step, goal_id)
            if result is not None:
                elapsed = (time.time() - start) * 1000
                return StepResult(
                    order=step.order,
                    action=step.action,
                    success=result.get("success", False),
                    result=result,
                    error=result.get("error"),
                    duration_ms=elapsed,
                    retries_used=attempt,
                )

            elapsed = (time.time() - start) * 1000
            return StepResult(
                order=step.order,
                action=step.action,
                success=False,
                error=f"No executor available for action: {step.action}",
                duration_ms=elapsed,
                retries_used=attempt,
            )

        except Exception as e:
            elapsed = (time.time() - start) * 1000
            logger.error("Delegation error for step %d (%s): %s",
                         step.order, step.action, e)
            return StepResult(
                order=step.order,
                action=step.action,
                success=False,
                error=str(e),
                duration_ms=elapsed,
                retries_used=attempt,
            )

    def _try_capability_router(
        self, step: WorkflowStep, goal_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Try to dispatch via CapabilityRouter (planner actions)."""
        if self._capability_router is None:
            return None
        if not self._capability_router.is_available(step.action):
            return None
        if self._plan_factory is None:
            return None

        plan = self._plan_factory(step.action, step.params, goal_id)
        try:
            return self._capability_router.dispatch(plan)
        except Exception as e:
            logger.error("CapabilityRouter dispatch failed: %s", e)
            return {"success": False, "error": str(e)}

    def _try_task_executor(
        self, step: WorkflowStep, goal_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Try to dispatch via TaskExecutor (tool-based steps)."""
        if self._task_executor is None:
            return None

        # TaskExecutor uses tool_name from params or action
        tool_name = step.params.get("tool_name", step.action)
        tool_args = step.params.get("tool_args", step.params)

        try:
            task_result = self._task_executor.execute_single(
                tool_name=tool_name,
                tool_args=tool_args,
                description=step.description,
                goal_id=goal_id,
            )
            return {
                "success": task_result.success,
                "task_id": task_result.task_id,
                "results": task_result.results,
                "errors": task_result.errors,
            }
        except Exception as e:
            logger.error("TaskExecutor failed: %s", e)
            return None

    def can_delegate(self, action: str) -> bool:
        """Check if we can handle this action type."""
        if self._capability_router and self._capability_router.is_available(action):
            return True
        if self._task_executor:
            return True
        return False
