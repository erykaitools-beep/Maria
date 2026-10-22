"""Prioritize admitted work by purpose, independently of its model type.

These scopes only order waiting compute requests. They never authorize an
action, bypass cooling, or interrupt an inference that has already started.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from typing import Iterator, Optional


class WorkPurpose(str, Enum):
    WORLD_EVENT = "world_event"
    ACTION = "action"
    INTERACTION = "interaction"
    BACKGROUND = "background"


_RANKS = {
    WorkPurpose.WORLD_EVENT: -20,
    WorkPurpose.ACTION: -10,
    WorkPurpose.INTERACTION: 0,
    WorkPurpose.BACKGROUND: 10,
}
_PURPOSE: ContextVar[Optional[WorkPurpose]] = ContextVar("maria_work_purpose", default=None)


def current_work_purpose() -> Optional[WorkPurpose]:
    return _PURPOSE.get()


@contextmanager
def work_purpose(purpose: WorkPurpose) -> Iterator[None]:
    """Scope a purpose; a nested helper cannot demote its caller's task."""
    purpose = WorkPurpose(purpose)
    current = _PURPOSE.get()
    if current is not None and _RANKS[current] < _RANKS[purpose]:
        purpose = current
    token = _PURPOSE.set(purpose)
    try:
        yield
    finally:
        _PURPOSE.reset(token)


def compute_priority(kind: str, explicit: Optional[int] = None) -> int:
    """Use the task's purpose; unscoped legacy callers retain their ordering."""
    purpose = current_work_purpose()
    if purpose is not None:
        return _RANKS[purpose]
    return explicit if explicit is not None else (0 if kind == "text" else 10)


def action_purpose(action, params=None) -> WorkPurpose:
    """Tool actions and explicit operator commands precede autonomous upkeep."""
    name = getattr(action, "value", action)
    if name in {"effector", "fs_write"} or (params or {}).get("source") == "operator_command":
        return WorkPurpose.ACTION
    return WorkPurpose.BACKGROUND
