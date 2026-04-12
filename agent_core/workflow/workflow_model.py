"""
Workflow data model - steps, state, status.

Design: extends K8 Strategy concept with persistence + checkpoints + interrupts.
Linear sequences first (per roadmap: "branching dopiero gdy potrzebny").
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class WorkflowStatus(Enum):
    """Lifecycle status of a workflow."""
    PENDING = "pending"          # Created, not started
    RUNNING = "running"          # Actively executing steps
    PAUSED = "paused"            # Paused by operator or system
    COMPLETED = "completed"      # All steps done
    FAILED = "failed"            # Step failed, workflow stopped
    CANCELLED = "cancelled"      # Cancelled by operator


class FailPolicy(Enum):
    """What to do when a step fails."""
    STOP = "stop"                # Stop workflow (default)
    SKIP = "skip"                # Skip failed step, continue
    RETRY = "retry"              # Retry same step (up to max_retries)


@dataclass(frozen=True)
class WorkflowStep:
    """Single step in a workflow."""
    order: int
    action: str                  # ActionType value: "learn", "fetch", etc.
    params: Dict[str, Any]       # Action parameters
    description: str             # Human-readable
    on_fail: FailPolicy = FailPolicy.STOP
    max_retries: int = 1
    requires_approval: bool = False
    checkpoint: bool = True      # Persist state after this step

    def to_dict(self) -> dict:
        return {
            "order": self.order,
            "action": self.action,
            "params": self.params,
            "description": self.description,
            "on_fail": self.on_fail.value,
            "max_retries": self.max_retries,
            "requires_approval": self.requires_approval,
            "checkpoint": self.checkpoint,
        }

    @staticmethod
    def from_dict(d: dict) -> "WorkflowStep":
        return WorkflowStep(
            order=d["order"],
            action=d["action"],
            params=d.get("params", {}),
            description=d.get("description", ""),
            on_fail=FailPolicy(d.get("on_fail", "stop")),
            max_retries=d.get("max_retries", 1),
            requires_approval=d.get("requires_approval", False),
            checkpoint=d.get("checkpoint", True),
        )


@dataclass
class StepResult:
    """Result of executing a single workflow step."""
    order: int
    action: str
    success: bool
    result: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: float = 0.0
    retries_used: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "order": self.order,
            "action": self.action,
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "retries_used": self.retries_used,
            "timestamp": self.timestamp,
        }

    @staticmethod
    def from_dict(d: dict) -> "StepResult":
        return StepResult(
            order=d["order"],
            action=d["action"],
            success=d.get("success", False),
            result=d.get("result", {}),
            error=d.get("error"),
            duration_ms=d.get("duration_ms", 0.0),
            retries_used=d.get("retries_used", 0),
            timestamp=d.get("timestamp", 0.0),
        )


@dataclass
class WorkflowState:
    """Full state of a workflow instance."""
    workflow_id: str
    name: str
    description: str
    steps: List[WorkflowStep]
    status: WorkflowStatus = WorkflowStatus.PENDING
    current_step: int = 0        # Index into steps list
    goal_id: Optional[str] = None
    results: List[StepResult] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    error: Optional[str] = None
    paused_by: Optional[str] = None  # "operator" or "system"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def progress_pct(self) -> float:
        """Percentage of steps completed (0-100)."""
        if not self.steps:
            return 100.0
        completed = sum(1 for r in self.results if r.success)
        return round(completed / len(self.steps) * 100, 1)

    @property
    def is_terminal(self) -> bool:
        """Whether workflow is in a terminal state."""
        return self.status in (
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        )

    @property
    def current_step_def(self) -> Optional[WorkflowStep]:
        """Get current step definition, or None if done."""
        if 0 <= self.current_step < len(self.steps):
            return self.steps[self.current_step]
        return None

    def to_dict(self) -> dict:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status.value,
            "current_step": self.current_step,
            "goal_id": self.goal_id,
            "results": [r.to_dict() for r in self.results],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "paused_by": self.paused_by,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(d: dict) -> "WorkflowState":
        return WorkflowState(
            workflow_id=d["workflow_id"],
            name=d["name"],
            description=d.get("description", ""),
            steps=[WorkflowStep.from_dict(s) for s in d.get("steps", [])],
            status=WorkflowStatus(d.get("status", "pending")),
            current_step=d.get("current_step", 0),
            goal_id=d.get("goal_id"),
            results=[StepResult.from_dict(r) for r in d.get("results", [])],
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
            completed_at=d.get("completed_at"),
            error=d.get("error"),
            paused_by=d.get("paused_by"),
            metadata=d.get("metadata", {}),
        )


def create_workflow(
    name: str,
    description: str,
    steps: List[WorkflowStep],
    goal_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> WorkflowState:
    """Factory function for creating a workflow."""
    now = time.time()
    return WorkflowState(
        workflow_id=f"wf-{uuid.uuid4().hex[:12]}",
        name=name,
        description=description,
        steps=sorted(steps, key=lambda s: s.order),
        goal_id=goal_id,
        metadata=metadata or {},
        created_at=now,
        updated_at=now,
    )
