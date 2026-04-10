"""
Reminder & Todo data models.

Reminder: time-triggered notification (one-time or recurring).
Todo: task item with optional deadline (no automatic trigger).
"""

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, Optional


class ReminderStatus(str, Enum):
    PENDING = "PENDING"
    TRIGGERED = "TRIGGERED"
    SNOOZED = "SNOOZED"
    DISMISSED = "DISMISSED"


class Recurrence(str, Enum):
    ONCE = "ONCE"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class TodoStatus(str, Enum):
    PENDING = "PENDING"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class TodoPriority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


@dataclass
class Reminder:
    """Time-triggered notification."""

    id: str = field(default_factory=lambda: f"rem-{uuid.uuid4().hex[:8]}")
    text: str = ""
    scheduled_at: float = 0.0  # Unix timestamp
    recurrence: Recurrence = Recurrence.ONCE
    status: ReminderStatus = ReminderStatus.PENDING
    notify_telegram: bool = True
    created_at: float = field(default_factory=time.time)
    triggered_at: Optional[float] = None
    snoozed_until: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_due(self, now: Optional[float] = None) -> bool:
        """Check if reminder should fire."""
        now = now or time.time()
        if self.status == ReminderStatus.SNOOZED:
            return self.snoozed_until is not None and now >= self.snoozed_until
        if self.status != ReminderStatus.PENDING:
            return False
        return now >= self.scheduled_at

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["recurrence"] = self.recurrence.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Reminder":
        data = dict(data)
        if "recurrence" in data:
            data["recurrence"] = Recurrence(data["recurrence"])
        if "status" in data:
            data["status"] = ReminderStatus(data["status"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Todo:
    """Task item with optional deadline."""

    id: str = field(default_factory=lambda: f"todo-{uuid.uuid4().hex[:8]}")
    text: str = ""
    priority: TodoPriority = TodoPriority.NORMAL
    status: TodoStatus = TodoStatus.PENDING
    deadline: Optional[float] = None  # Unix timestamp, optional
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_overdue(self, now: Optional[float] = None) -> bool:
        """Check if todo is past deadline."""
        if self.deadline is None or self.status != TodoStatus.PENDING:
            return False
        return (now or time.time()) > self.deadline

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["priority"] = self.priority.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Todo":
        data = dict(data)
        if "priority" in data:
            data["priority"] = TodoPriority(data["priority"])
        if "status" in data:
            data["status"] = TodoStatus(data["status"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
