"""
TaskOrchestrator (V3 Phase B, Module 4)

Top-level facade for user task intake. Accepts a natural language task,
decomposes it, builds an execution plan, creates a Goal, and returns
everything the user needs to review and approve.

Wraps V2: GoalStore (K3), PlannerCore (K5), K8 Deliberation.

Usage:
    orch = TaskOrchestrator(ctx)

    # Submit a task
    result = orch.submit("naucz sie fizyki kwantowej")
    print(result.plan.describe())

    # Approve and execute
    orch.approve(result.task_id)

    # Check progress
    progress = orch.get_progress(result.task_id)
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent_core.orchestrator.task_decomposer import TaskDecomposer, DecomposedTask
from agent_core.orchestrator.execution_plan import ExecutionPlanBuilder, ExecutionPlan

logger = logging.getLogger(__name__)


class TaskStatus:
    """Task lifecycle statuses."""
    PLANNED = "planned"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskRecord:
    """Record of a submitted task."""
    task_id: str
    description: str
    status: str
    decomposition: DecomposedTask
    plan: ExecutionPlan
    goal_id: Optional[str]
    created_at: float
    updated_at: float
    approved_at: Optional[float] = None
    completed_at: Optional[float] = None
    progress: float = 0.0
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "status": self.status,
            "goal_id": self.goal_id,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "completed_at": self.completed_at,
            "progress": self.progress,
            "plan": self.plan.to_dict(),
            "decomposition": self.decomposition.to_dict(),
            "result": self.result,
            "error": self.error,
        }


@dataclass
class SubmitResult:
    """Result of task submission."""
    task_id: str
    decomposition: DecomposedTask
    plan: ExecutionPlan
    auto_approved: bool = False
    goal_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "plan": self.plan.to_dict(),
            "decomposition": self.decomposition.to_dict(),
            "auto_approved": self.auto_approved,
            "goal_id": self.goal_id,
        }


class TaskOrchestrator:
    """Top-level task intake and lifecycle management."""

    MAX_TASKS = 50  # In-memory limit

    def __init__(self, ctx):
        """
        Args:
            ctx: SharedContext instance
        """
        self._ctx = ctx
        self._decomposer = TaskDecomposer(ctx)
        self._plan_builder = ExecutionPlanBuilder(ctx)
        self._tasks: Dict[str, TaskRecord] = {}

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    def submit(
        self,
        description: str,
        auto_approve: bool = False,
        priority: float = 0.8,
    ) -> SubmitResult:
        """
        Submit a new task. Decomposes, plans, optionally creates goal.

        Args:
            description: Natural language task description
            auto_approve: If True, create goal immediately (skip review)
            priority: Goal priority (0.0-1.0)

        Returns:
            SubmitResult with task_id, decomposition, and plan.
        """
        task_id = f"task-{uuid.uuid4().hex[:10]}"
        now = time.time()

        # Step 1: Decompose
        decomposition = self._decomposer.decompose(description)

        # Step 2: Build execution plan
        plan = self._plan_builder.build(decomposition)

        # Step 3: Create task record
        record = TaskRecord(
            task_id=task_id,
            description=description,
            status=TaskStatus.PLANNED,
            decomposition=decomposition,
            plan=plan,
            goal_id=None,
            created_at=now,
            updated_at=now,
        )

        self._tasks[task_id] = record
        self._trim_old_tasks()

        # Step 4: Auto-approve if requested and plan is executable
        goal_id = None
        auto_approved = False
        if auto_approve and plan.is_executable:
            goal_id = self._create_goal(record, priority)
            record.goal_id = goal_id
            record.status = TaskStatus.APPROVED
            record.approved_at = now
            record.updated_at = now
            auto_approved = True
            logger.info(f"Task {task_id} auto-approved -> goal {goal_id}")

        logger.info(
            f"Task submitted: {task_id} ({decomposition.category.value}, "
            f"{plan.total_steps} steps, executable={plan.is_executable})"
        )

        return SubmitResult(
            task_id=task_id,
            decomposition=decomposition,
            plan=plan,
            auto_approved=auto_approved,
            goal_id=goal_id,
        )

    # ------------------------------------------------------------------
    # Approve / Cancel
    # ------------------------------------------------------------------

    def approve(self, task_id: str, priority: float = 0.8) -> Optional[str]:
        """
        Approve a planned task - creates Goal in GoalStore.

        Args:
            task_id: Task to approve
            priority: Goal priority

        Returns:
            Goal ID or None if task not found / already approved.
        """
        record = self._tasks.get(task_id)
        if not record:
            return None
        if record.status != TaskStatus.PLANNED:
            return record.goal_id  # Already approved or terminal

        goal_id = self._create_goal(record, priority)
        if goal_id:
            record.goal_id = goal_id
            record.status = TaskStatus.APPROVED
            record.approved_at = time.time()
            record.updated_at = time.time()
            logger.info(f"Task {task_id} approved -> goal {goal_id}")

        return goal_id

    def cancel(self, task_id: str, reason: str = "user_cancelled") -> bool:
        """
        Cancel a task. If goal exists, abandon it.

        Returns:
            True if cancelled successfully.
        """
        record = self._tasks.get(task_id)
        if not record:
            return False
        if record.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            return False

        record.status = TaskStatus.CANCELLED
        record.updated_at = time.time()
        record.error = reason

        # Abandon goal if exists
        if record.goal_id:
            self._abandon_goal(record.goal_id, reason)

        logger.info(f"Task {task_id} cancelled: {reason}")
        return True

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------

    def get_progress(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get task progress by checking goal state.

        Returns:
            Progress dict or None if not found.
        """
        record = self._tasks.get(task_id)
        if not record:
            return None

        # Sync progress from goal
        if record.goal_id:
            self._sync_goal_progress(record)

        return {
            "task_id": record.task_id,
            "description": record.description,
            "status": record.status,
            "progress": record.progress,
            "goal_id": record.goal_id,
            "plan_steps": record.plan.total_steps,
            "blocked_steps": len(record.plan.blocked_steps),
            "created_at": record.created_at,
            "approved_at": record.approved_at,
            "completed_at": record.completed_at,
            "error": record.error,
        }

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get full task record as dict."""
        record = self._tasks.get(task_id)
        if not record:
            return None
        if record.goal_id:
            self._sync_goal_progress(record)
        return record.to_dict()

    def list_tasks(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List tasks, optionally filtered by status.

        Returns:
            List of task summary dicts (without full plan details).
        """
        results = []
        for record in sorted(self._tasks.values(), key=lambda r: r.created_at, reverse=True):
            if status and record.status != status:
                continue
            if record.goal_id:
                self._sync_goal_progress(record)
            results.append({
                "task_id": record.task_id,
                "description": record.description,
                "status": record.status,
                "progress": record.progress,
                "category": record.decomposition.category.value,
                "steps": record.plan.total_steps,
                "goal_id": record.goal_id,
                "created_at": record.created_at,
            })
        return results

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def submit_and_approve(
        self, description: str, priority: float = 0.8,
    ) -> SubmitResult:
        """Submit + auto-approve in one call."""
        return self.submit(description, auto_approve=True, priority=priority)

    def get_decomposer(self) -> TaskDecomposer:
        """Access the underlying TaskDecomposer."""
        return self._decomposer

    def get_plan_builder(self) -> ExecutionPlanBuilder:
        """Access the underlying ExecutionPlanBuilder."""
        return self._plan_builder

    # ------------------------------------------------------------------
    # Internal: Goal management
    # ------------------------------------------------------------------

    def _create_goal(self, record: TaskRecord, priority: float) -> Optional[str]:
        """Create a Goal in GoalStore for this task."""
        goal_store = self._ctx.goal_store
        if not goal_store:
            logger.warning("No GoalStore - cannot create goal for task")
            return None

        try:
            from agent_core.goals.goal_model import (
                GoalType, GoalStatus as GS, create_goal,
            )

            category = record.decomposition.category.value
            topic = record.decomposition.topic

            # Determine goal type from category
            if category in ("learn_topic", "explore_new", "consolidate", "fetch_info"):
                goal_type = GoalType.LEARNING
            elif category in ("analyze", "system_check"):
                goal_type = GoalType.MAINTENANCE
            else:
                goal_type = GoalType.USER

            goal = create_goal(
                goal_type=goal_type,
                description=record.description,
                priority=priority,
                status=GS.ACTIVE,
                created_by="orchestrator",
                metadata={
                    "task_id": record.task_id,
                    "category": category,
                    "topic": topic,
                    "source": "v3_orchestrator",
                    "template": record.decomposition.template_name,
                    "total_steps": record.plan.total_steps,
                },
            )

            goal_id = goal_store.create(goal)
            goal_store.save()
            return goal_id

        except Exception as e:
            logger.warning(f"Failed to create goal: {e}")
            return None

    def _abandon_goal(self, goal_id: str, reason: str) -> None:
        """Abandon a goal in GoalStore."""
        goal_store = self._ctx.goal_store
        if not goal_store:
            return
        try:
            from agent_core.goals.goal_model import GoalStatus
            goal = goal_store.get(goal_id)
            if goal and not goal.is_terminal:
                goal_store.update_status(
                    goal_id,
                    GoalStatus.ABANDONED,
                    reason=reason,
                    actor="orchestrator",
                )
                goal_store.save()
        except Exception as e:
            logger.warning(f"Failed to abandon goal {goal_id}: {e}")

    def _sync_goal_progress(self, record: TaskRecord) -> None:
        """Sync task status from goal state."""
        goal_store = self._ctx.goal_store
        if not goal_store or not record.goal_id:
            return

        try:
            goal = goal_store.get(record.goal_id)
            if not goal:
                return

            record.progress = goal.progress

            if goal.status.value == "achieved":
                if record.status != TaskStatus.COMPLETED:
                    record.status = TaskStatus.COMPLETED
                    record.completed_at = time.time()
                    record.result = goal.outcome or {}
                    record.updated_at = time.time()
            elif goal.status.value == "failed":
                if record.status != TaskStatus.FAILED:
                    record.status = TaskStatus.FAILED
                    record.updated_at = time.time()
            elif goal.status.value == "abandoned":
                if record.status != TaskStatus.CANCELLED:
                    record.status = TaskStatus.CANCELLED
                    record.updated_at = time.time()
            elif goal.status.value in ("active", "pending"):
                if record.status == TaskStatus.APPROVED:
                    record.status = TaskStatus.EXECUTING
                    record.updated_at = time.time()

        except Exception as e:
            logger.debug(f"Goal sync failed for {record.goal_id}: {e}")

    def _trim_old_tasks(self) -> None:
        """Remove oldest completed/cancelled tasks if over limit."""
        if len(self._tasks) <= self.MAX_TASKS:
            return

        terminal = [
            (r.updated_at, tid)
            for tid, r in self._tasks.items()
            if r.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED)
        ]
        terminal.sort()

        while len(self._tasks) > self.MAX_TASKS and terminal:
            _, tid = terminal.pop(0)
            del self._tasks[tid]
