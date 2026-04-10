"""
Persistent store for Reminders and Todos.

Append-only JSONL with last-record-per-id semantics (same as GoalStore).
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

from agent_core.reminders.reminder_model import (
    Reminder, ReminderStatus, Recurrence,
    Todo, TodoStatus,
)

logger = logging.getLogger(__name__)

_META_DIR = Path(__file__).resolve().parents[2] / "meta_data"


class ReminderStore:
    """JSONL-backed store for reminders."""

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path or _META_DIR / "reminders.jsonl")
        self._reminders: Dict[str, Reminder] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                rem = Reminder.from_dict(data)
                self._reminders[rem.id] = rem
        except Exception as e:
            logger.warning("Failed to load reminders: %s", e)

    def _append(self, reminder: Reminder) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(reminder.to_dict(), ensure_ascii=False) + "\n")

    def add(self, reminder: Reminder) -> Reminder:
        self._reminders[reminder.id] = reminder
        self._append(reminder)
        return reminder

    def get(self, reminder_id: str) -> Optional[Reminder]:
        return self._reminders.get(reminder_id)

    def get_due(self, now: Optional[float] = None) -> List[Reminder]:
        """Return all reminders that should fire now."""
        return [r for r in self._reminders.values() if r.is_due(now)]

    def get_pending(self) -> List[Reminder]:
        return [
            r for r in self._reminders.values()
            if r.status in (ReminderStatus.PENDING, ReminderStatus.SNOOZED)
        ]

    def get_all(self) -> List[Reminder]:
        return list(self._reminders.values())

    def update(self, reminder: Reminder) -> None:
        self._reminders[reminder.id] = reminder
        self._append(reminder)

    def dismiss(self, reminder_id: str) -> Optional[Reminder]:
        rem = self._reminders.get(reminder_id)
        if rem:
            rem.status = ReminderStatus.DISMISSED
            self.update(rem)
        return rem

    def snooze(self, reminder_id: str, minutes: int = 15) -> Optional[Reminder]:
        rem = self._reminders.get(reminder_id)
        if rem:
            rem.status = ReminderStatus.SNOOZED
            rem.snoozed_until = time.time() + minutes * 60
            self.update(rem)
        return rem

    def mark_triggered(self, reminder: Reminder) -> None:
        """Mark as triggered; if recurring, create next instance."""
        reminder.status = ReminderStatus.TRIGGERED
        reminder.triggered_at = time.time()
        self.update(reminder)

        if reminder.recurrence != Recurrence.ONCE:
            next_rem = Reminder(
                text=reminder.text,
                scheduled_at=_next_occurrence(reminder.scheduled_at, reminder.recurrence),
                recurrence=reminder.recurrence,
                notify_telegram=reminder.notify_telegram,
                metadata=dict(reminder.metadata),
            )
            self.add(next_rem)

    def count(self) -> Dict[str, int]:
        pending = sum(1 for r in self._reminders.values() if r.status == ReminderStatus.PENDING)
        snoozed = sum(1 for r in self._reminders.values() if r.status == ReminderStatus.SNOOZED)
        triggered = sum(1 for r in self._reminders.values() if r.status == ReminderStatus.TRIGGERED)
        return {"pending": pending, "snoozed": snoozed, "triggered": triggered, "total": len(self._reminders)}


class TodoStore:
    """JSONL-backed store for todos."""

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path or _META_DIR / "todos.jsonl")
        self._todos: Dict[str, Todo] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                todo = Todo.from_dict(data)
                self._todos[todo.id] = todo
        except Exception as e:
            logger.warning("Failed to load todos: %s", e)

    def _append(self, todo: Todo) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(todo.to_dict(), ensure_ascii=False) + "\n")

    def add(self, todo: Todo) -> Todo:
        self._todos[todo.id] = todo
        self._append(todo)
        return todo

    def get(self, todo_id: str) -> Optional[Todo]:
        return self._todos.get(todo_id)

    def get_pending(self) -> List[Todo]:
        return [t for t in self._todos.values() if t.status == TodoStatus.PENDING]

    def get_all(self) -> List[Todo]:
        return list(self._todos.values())

    def complete(self, todo_id: str) -> Optional[Todo]:
        todo = self._todos.get(todo_id)
        if todo and todo.status == TodoStatus.PENDING:
            todo.status = TodoStatus.DONE
            todo.completed_at = time.time()
            self._append(todo)
        return todo

    def cancel(self, todo_id: str) -> Optional[Todo]:
        todo = self._todos.get(todo_id)
        if todo and todo.status == TodoStatus.PENDING:
            todo.status = TodoStatus.CANCELLED
            self._append(todo)
        return todo

    def get_overdue(self, now: Optional[float] = None) -> List[Todo]:
        return [t for t in self._todos.values() if t.is_overdue(now)]

    def count(self) -> Dict[str, int]:
        pending = sum(1 for t in self._todos.values() if t.status == TodoStatus.PENDING)
        done = sum(1 for t in self._todos.values() if t.status == TodoStatus.DONE)
        return {"pending": pending, "done": done, "total": len(self._todos)}


def _next_occurrence(current_ts: float, recurrence: Recurrence) -> float:
    """Calculate next occurrence timestamp."""
    if recurrence == Recurrence.DAILY:
        return current_ts + 86400
    elif recurrence == Recurrence.WEEKLY:
        return current_ts + 7 * 86400
    elif recurrence == Recurrence.MONTHLY:
        return current_ts + 30 * 86400  # approximate
    return current_ts
