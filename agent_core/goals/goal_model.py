"""
Goal Model - dataclasses for Goal System.

Kontrakt: docs/CONTRACTS.md - Kontrakt 3: Goal System
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class GoalType(Enum):
    """Typ celu."""
    META = "meta"                # Misja systemu (1 cel, zawsze aktywny)
    USER = "user"                # Cele od uzytkownika (przez /goal create)
    LEARNING = "learning"        # Cele nauki (generowane z Teacher P1-P6)
    MAINTENANCE = "maintenance"  # Cele utrzymania (z homeostasis thresholds)


class GoalStatus(Enum):
    """Status celu."""
    PROPOSED = "proposed"        # Auto-sugerowany, czeka na potwierdzenie
    PENDING = "pending"          # Zatwierdzony, nie rozpoczety
    ACTIVE = "active"            # W trakcie realizacji
    ACHIEVED = "achieved"        # Zrealizowany
    FAILED = "failed"            # Nie udalo sie
    ABANDONED = "abandoned"      # Swiadomie porzucony


# Statusy ktore licza sie jako "aktywne" (wliczane do limitu 20)
ACTIVE_STATUSES = {GoalStatus.PENDING, GoalStatus.ACTIVE}

# Statusy terminalne (cel zakonczony)
TERMINAL_STATUSES = {GoalStatus.ACHIEVED, GoalStatus.FAILED, GoalStatus.ABANDONED}

# Limity
MAX_ACTIVE_GOALS = 20
MAX_PROPOSED_GOALS = 3
MAX_HIERARCHY_DEPTH = 3
PROPOSED_TIMEOUT_SECONDS = 24 * 3600  # 24h


@dataclass
class AuditEntry:
    """Zapis zmiany statusu celu."""
    timestamp: float
    old_status: Optional[str]   # None dla pierwszego wpisu
    new_status: str
    reason: str
    actor: str                  # "teacher" / "user" / "homeostasis" / "planner" / "system"

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "old_status": self.old_status,
            "new_status": self.new_status,
            "reason": self.reason,
            "actor": self.actor,
        }

    @staticmethod
    def from_dict(d: dict) -> "AuditEntry":
        return AuditEntry(
            timestamp=d["timestamp"],
            old_status=d.get("old_status"),
            new_status=d["new_status"],
            reason=d["reason"],
            actor=d["actor"],
        )


@dataclass
class Goal:
    """Pojedynczy cel w systemie celow Marii."""
    id: str
    type: GoalType
    description: str             # Human-readable (po polsku OK)
    priority: float              # 0.0 do 1.0
    status: GoalStatus
    progress: float              # 0.0 do 1.0
    parent_goal_id: Optional[str]
    created_by: str              # "system" / "user" / "teacher" / "homeostasis"
    created_at: float
    updated_at: float
    deadline: Optional[float] = None
    audit_trail: List[AuditEntry] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        """Czy cel jest aktywny (PENDING lub ACTIVE)."""
        return self.status in ACTIVE_STATUSES

    @property
    def is_terminal(self) -> bool:
        """Czy cel jest zakonczony."""
        return self.status in TERMINAL_STATUSES

    def to_dict(self) -> dict:
        """Serializacja do dict (dla goals.jsonl)."""
        return {
            "id": self.id,
            "type": self.type.value,
            "description": self.description,
            "priority": self.priority,
            "status": self.status.value,
            "progress": self.progress,
            "parent_goal_id": self.parent_goal_id,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deadline": self.deadline,
            "audit_trail": [a.to_dict() for a in self.audit_trail],
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(d: dict) -> "Goal":
        """Deserializacja z dict."""
        return Goal(
            id=d["id"],
            type=GoalType(d["type"]),
            description=d["description"],
            priority=d["priority"],
            status=GoalStatus(d["status"]),
            progress=d.get("progress", 0.0),
            parent_goal_id=d.get("parent_goal_id"),
            created_by=d.get("created_by", "system"),
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
            deadline=d.get("deadline"),
            audit_trail=[
                AuditEntry.from_dict(a)
                for a in d.get("audit_trail", [])
            ],
            metadata=d.get("metadata", {}),
        )


def create_goal(
    goal_type: GoalType,
    description: str,
    priority: float,
    status: GoalStatus = GoalStatus.PENDING,
    created_by: str = "system",
    parent_goal_id: Optional[str] = None,
    deadline: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
    goal_id: Optional[str] = None,
) -> Goal:
    """Factory function do tworzenia celow z automatycznym audit trail."""
    now = time.time()
    gid = goal_id or f"goal-{uuid.uuid4().hex[:12]}"

    goal = Goal(
        id=gid,
        type=goal_type,
        description=description,
        priority=max(0.0, min(1.0, priority)),
        status=status,
        progress=0.0,
        parent_goal_id=parent_goal_id,
        created_by=created_by,
        created_at=now,
        updated_at=now,
        deadline=deadline,
        audit_trail=[
            AuditEntry(
                timestamp=now,
                old_status=None,
                new_status=status.value,
                reason="created",
                actor=created_by,
            )
        ],
        metadata=metadata or {},
    )
    return goal
