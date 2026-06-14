"""
Conductor — Maria's project-management layer for delegated build work.

Maria does not write code for external projects (the market agent,
future tools); she project-manages the build by tracking a queue of
delegated tasks and exposing what's next to the operator and to the
assignees (Claude CLI, Codex, manual operator work).

This is Phase 0.5 of the market-agent build roadmap, structurally
moved before Phase 1 so Maria can drive the build instead of the
operator hand-walking each step.

Public API:
    from agent_core.conductor import (
        Assignee, Conductor, Task, TaskStatus,
        TaskQueue, BuildStatus, BuildStatusStore,
        create_task,
    )
"""

from agent_core.conductor.build_status import BuildStatus, BuildStatusStore
from agent_core.conductor.conductor import Conductor
from agent_core.conductor.task_model import (
    Assignee,
    BUILDER_ASSIGNEES,
    Task,
    TaskStatus,
    TERMINAL_STATUSES,
    create_task,
)
from agent_core.conductor.task_queue import TaskQueue

__all__ = [
    "Assignee",
    "BUILDER_ASSIGNEES",
    "BuildStatus",
    "BuildStatusStore",
    "Conductor",
    "Task",
    "TaskQueue",
    "TaskStatus",
    "TERMINAL_STATUSES",
    "create_task",
]
