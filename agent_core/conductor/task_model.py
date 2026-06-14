"""
Conductor — Task data model.

Tasks describe units of build work Maria delegates to Claude/Codex/operator
for external projects (initially: maria-market-agent, Phase 0.5).

Shared registry analogous to BulletinEntry but project-scoped: bulletin
tracks Maria's *internal* cognitive needs, conductor tracks *external*
build work she project-manages.

Follows the same conventions: frozen dataclass shape, Enum types, JSON
serialization via to_dict / from_dict, ID prefix for traceability.
"""

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskStatus(Enum):
    """Lifecycle status of a delegated build task."""

    PENDING = "pending"          # Newly seeded, not yet picked up
    IN_PROGRESS = "in_progress"  # Assignee is actively working
    DONE = "done"                # Completed (artifacts populated)
    BLOCKED = "blocked"          # Cannot proceed (dep missing, hardware, etc.)
    CANCELLED = "cancelled"      # Operator decided not to do it


# Terminal statuses — once here, the task is closed.
TERMINAL_STATUSES = {TaskStatus.DONE, TaskStatus.CANCELLED}


class Assignee(Enum):
    """Who is meant to execute the task.

    Conductor only records the assignee — it does not invoke any LLM or
    subprocess itself. Operator-triggered paths stay operator-triggered.

    Policy: see ``BUILDER_ASSIGNEES`` below. Maria autonomously routes
    build work to Codex or to the agent under construction itself —
    never to Claude CLI. Claude CLI stays in the enum because the
    operator can still hand-pick it via Telegram; Maria just won't
    assign to it from her tick loop.
    """

    OPERATOR = "operator"        # Eryk handles it manually
    CODEX = "codex"              # Codex CLI (autonomous-eligible)
    AGENT_SELF = "agent_self"    # Agent under construction does it (Phase 1+)
    CLAUDE_CLI = "claude_cli"    # Operator-triggered ONLY — see BUILDER_ASSIGNEES
    UNASSIGNED = "unassigned"    # Pending triage


# Assignees Maria may autonomously route work to from the tick loop.
#
# Excluded by design:
#   - CLAUDE_CLI: subscription account ban risk on autonomous CLI usage
#                 (operator-triggered Telegram /claude is fine — that's
#                 a different code path that does not touch the queue).
#   - OPERATOR: a human, not a runner. Maria flags tasks for operator
#               attention; she does not "assign" Eryk autonomously.
#   - UNASSIGNED: triage state, not a runner.
BUILDER_ASSIGNEES = frozenset({Assignee.CODEX, Assignee.AGENT_SELF})


@dataclass
class Task:
    """One unit of delegated build work."""

    task_id: str                 # Primary key — "cdt-{uuid12}"
    project: str                 # External project, e.g. "market_agent"
    phase: str                   # Phase tag, e.g. "phase_1_data_ingest"
    title: str                   # Short imperative ("Implement Binance OHLCV adapter")
    description: str             # Full instruction body for the assignee
    status: TaskStatus
    priority: float              # 0.0 - 1.0
    assignee: Assignee
    dependencies: List[str] = field(default_factory=list)   # task_ids that must be DONE first
    blockers: List[str] = field(default_factory=list)       # human-readable strings
    estimated_minutes: Optional[int] = None
    artifacts: Dict[str, Any] = field(default_factory=dict)  # files, links, hashes
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["assignee"] = self.assignee.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Task":
        return cls(
            task_id=d["task_id"],
            project=d["project"],
            phase=d.get("phase", ""),
            title=d["title"],
            description=d.get("description", ""),
            status=TaskStatus(d.get("status", "pending")),
            priority=float(d.get("priority", 0.5)),
            assignee=Assignee(d.get("assignee", "unassigned")),
            dependencies=list(d.get("dependencies", [])),
            blockers=list(d.get("blockers", [])),
            estimated_minutes=d.get("estimated_minutes"),
            artifacts=dict(d.get("artifacts", {})),
            created_at=float(d.get("created_at", time.time())),
            updated_at=float(d.get("updated_at", time.time())),
            started_at=d.get("started_at"),
            completed_at=d.get("completed_at"),
            notes=d.get("notes", ""),
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


def create_task(
    project: str,
    phase: str,
    title: str,
    description: str,
    priority: float = 0.5,
    assignee: Assignee = Assignee.UNASSIGNED,
    dependencies: Optional[List[str]] = None,
    estimated_minutes: Optional[int] = None,
) -> Task:
    """Factory — generate task ID and timestamps. New tasks start PENDING."""
    return Task(
        task_id=f"cdt-{uuid.uuid4().hex[:12]}",
        project=project,
        phase=phase,
        title=title,
        description=description,
        status=TaskStatus.PENDING,
        priority=priority,
        assignee=assignee,
        dependencies=list(dependencies or []),
    )
