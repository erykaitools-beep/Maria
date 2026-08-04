"""
Delegation Manager - routes workflow steps to appropriate executors.

Uses CapabilityRouter for known actions, TaskExecutor for tool-based steps.

K7 PARITY (2026-07-21, workshop room #1): every path out of this class passes
through the autonomy policy first. Before this, a workflow step reached
CapabilityRouter.dispatch() -- and through it fs_write, effector, fetch,
ask_expert -- with no K7 check and no rate-limiter record, i.e. below the gate
the planner has always honoured. The room could not be opened with that hole in
it, so the gate is wired here rather than in a later "valves" step.

The gate is FAIL-CLOSED: an unwired policy blocks instead of passing. A missing
security check that silently permits is the failure mode this codebase has been
burned by before (Codex `exec` without --sandbox); an unwired gate must look
like a closed door, not an open one. Unit tests that exercise the state machine
rather than the gate opt out explicitly via :meth:`disable_k7_gate`.
"""

import logging
import os
import time
from typing import Any, Callable, Dict, Optional, Tuple

from agent_core.workflow.workflow_model import StepResult, WorkflowStep

logger = logging.getLogger(__name__)

# TaskExecutor steps carry a free-form tool name, not an ActionType, so the K7
# gate has nothing to classify them by. Map the tools that actually exist
# (registered in homeostasis_module: wiki_search / web_fetch / search_and_save /
# file_write / file_read / file_list) onto the ActionType whose governance fits:
# reaching for data == fetch, putting bytes on disk == fs_write.
TOOL_GATE_ACTIONS: Dict[str, str] = {
    "wiki_search": "fetch",
    "web_fetch": "fetch",
    "search_and_save": "fetch",
    "file_read": "fetch",
    "file_list": "fetch",
    "file_write": "fs_write",
}

# An unmapped tool is governed as `effector`, which in practice means REFUSED:
# the effector_authority rule needs an AuthorityManager the workflow path does
# not carry. That is the intended answer, not an accident -- a tool nobody
# classified must not slip through the gate on the day it is registered. Adding
# a tool therefore also means adding it above, deliberately.
UNKNOWN_TOOL_GATE_ACTION = "effector"


class DelegationManager:
    """Routes workflow steps to the right executor."""

    def __init__(self):
        self._capability_router = None
        self._task_executor = None
        self._plan_factory = None  # Callable to create Plan from step
        self._autonomy_policy = None       # K7 gate (required unless disabled)
        self._state_provider = None        # () -> (health_score, mode)
        self._gate_disabled = False        # explicit, logged opt-out

    def set_capability_router(self, router: Any) -> None:
        self._capability_router = router

    def set_task_executor(self, executor: Any) -> None:
        self._task_executor = executor

    def set_plan_factory(self, factory: Callable) -> None:
        """Set factory: (action: str, params: dict, goal_id: str) -> Plan."""
        self._plan_factory = factory

    def set_autonomy_policy(self, policy: Any) -> None:
        """Wire the K7 gate. Without it every delegation is refused."""
        self._autonomy_policy = policy

    def set_state_provider(self, provider: Callable[[], Tuple[float, str]]) -> None:
        """Set callable returning (health_score, mode) for the K7 check.

        K7 rules are mode- and health-aware (an action allowed in ACTIVE can be
        refused in SLEEP), so passing static defaults would hand the gate a
        rosier picture of the organism than the planner gets. Optional: without
        it the gate still runs, on the neutral (1.0, "active") pair.
        """
        self._state_provider = provider

    def disable_k7_gate(self, reason: str) -> None:
        """Opt out of the gate. For tests of the state machine only.

        Deliberately noisy and deliberately requires a reason: a security gate
        that can be turned off quietly is not a gate.
        """
        self._gate_disabled = True
        logger.warning("DelegationManager: K7 gate DISABLED (%s)", reason)

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

    def _k7_check(
        self, action_type: str, params: Dict[str, Any], goal_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Ask K7 whether this step may run. None = allowed.

        A non-None return is a REFUSAL and must be returned to the caller as the
        step's outcome -- never as None. Returning None on a refusal would let
        :meth:`delegate` fall through to the next executor, which is exactly the
        bypass this gate exists to close.
        """
        if self._gate_disabled:
            return None

        # FS_WRITE_ENABLED is enforced in planner_core only, so the workflow
        # path could write to disk with the flag off. Honour it here too.
        # (Proper home is the fs_write handler itself, where every caller would
        # be covered -- deliberately out of scope for opening this room.)
        if action_type == "fs_write" and os.getenv(
                "FS_WRITE_ENABLED", "").strip().lower() not in (
                "1", "true", "yes", "on"):
            logger.info("Workflow step 'fs_write' refused: FS_WRITE_ENABLED off")
            return {
                "success": False,
                "blocked_by": "fs_write_disabled",
                "error": "FS_WRITE_ENABLED is off",
            }

        if self._autonomy_policy is None:
            logger.error(
                "Workflow step '%s' refused: K7 autonomy policy not wired "
                "(fail-closed)", action_type,
            )
            return {
                "success": False,
                "blocked_by": "autonomy_policy",
                "error": "K7 autonomy policy not wired (fail-closed)",
            }

        health, mode = 1.0, "active"
        if self._state_provider is not None:
            try:
                health, mode = self._state_provider()
            except Exception as e:  # provider must never decide the outcome
                logger.warning("State provider failed, using defaults: %s", e)

        try:
            check = self._autonomy_policy.check(
                action_type=action_type,
                action_params=params,
                goal_id=goal_id,
                health_score=health,
                mode=mode,
            )
        except Exception as e:
            # An exploding gate is a closed gate.
            logger.error("K7 check raised for '%s': %s", action_type, e)
            return {
                "success": False,
                "blocked_by": "autonomy_policy",
                "error": f"K7 check failed: {e}",
            }

        if check.allowed:
            return None

        blocked = dict(check.blocked_result or {})
        reasons = blocked.get("reasons", [])
        logger.info(
            "Workflow step '%s' blocked by K7 (%s): %s",
            action_type, check.rule_name or "policy", reasons,
        )
        blocked.setdefault("success", False)
        blocked.setdefault("blocked_by", "autonomy_policy")
        blocked.setdefault(
            "error", f"blocked by K7: {check.rule_name or 'policy'}")
        return blocked

    def _k7_record(self, action_type: str, result: Optional[Dict[str, Any]]) -> None:
        """Tell K7 the action ran, so the rate limiter is not blind to us."""
        if self._gate_disabled or self._autonomy_policy is None:
            return
        try:
            self._autonomy_policy.record_execution(
                action_type=action_type,
                success=bool(result and result.get("success")),
            )
        except Exception as e:  # accounting must never sink a completed step
            logger.warning("K7 record_execution failed for '%s': %s",
                           action_type, e)

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

        refusal = self._k7_check(step.action, step.params, goal_id)
        if refusal is not None:
            return refusal

        plan = self._plan_factory(step.action, step.params, goal_id)
        try:
            result = self._capability_router.dispatch(plan)
        except Exception as e:
            logger.error("CapabilityRouter dispatch failed: %s", e)
            result = {"success": False, "error": str(e)}
        self._k7_record(step.action, result)
        return result

    def _try_task_executor(
        self, step: WorkflowStep, goal_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Try to dispatch via TaskExecutor (tool-based steps)."""
        if self._task_executor is None:
            return None

        # TaskExecutor uses tool_name from params or action
        tool_name = step.params.get("tool_name", step.action)
        tool_args = step.params.get("tool_args", step.params)

        gate_action = TOOL_GATE_ACTIONS.get(tool_name, UNKNOWN_TOOL_GATE_ACTION)
        refusal = self._k7_check(gate_action, step.params, goal_id)
        if refusal is not None:
            refusal.setdefault("tool_name", tool_name)
            return refusal

        try:
            task_result = self._task_executor.execute_single(
                tool_name=tool_name,
                tool_args=tool_args,
                description=step.description,
                goal_id=goal_id,
            )
            result = {
                "success": task_result.success,
                "task_id": task_result.task_id,
                "results": task_result.results,
                "errors": task_result.errors,
            }
        except Exception as e:
            logger.error("TaskExecutor failed: %s", e)
            self._k7_record(gate_action, None)
            return None
        self._k7_record(gate_action, result)
        return result

    def can_delegate(self, action: str) -> bool:
        """Check if we can handle this action type."""
        if self._capability_router and self._capability_router.is_available(action):
            return True
        if self._task_executor:
            return True
        return False
