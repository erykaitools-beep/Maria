"""
Reminder scheduler - checks due reminders on tick and fires notifications.

Designed to run in homeostasis tick loop (Phase 11+).
"""

import logging
import time
from datetime import datetime
from typing import Callable, Optional

from agent_core.reminders.reminder_model import Reminder, ReminderStatus
from agent_core.reminders.reminder_store import ReminderStore, TodoStore

logger = logging.getLogger(__name__)

# Check reminders every N ticks (1 tick ~ 1s, check every 30s)
CHECK_INTERVAL_TICKS = 30

# Overdue todo notification cooldown (notify once per hour)
OVERDUE_NOTIFY_COOLDOWN = 3600


class ReminderScheduler:
    """
    Checks due reminders periodically and fires notifications.

    Usage:
        scheduler = ReminderScheduler(reminder_store, todo_store)
        scheduler.set_notify_fn(telegram_send_message)
        # In tick loop:
        scheduler.tick()
    """

    def __init__(
        self,
        reminder_store: ReminderStore,
        todo_store: Optional[TodoStore] = None,
    ):
        self._reminder_store = reminder_store
        self._todo_store = todo_store
        self._notify_fn: Optional[Callable[[str], None]] = None
        self._repl_fn: Optional[Callable[[str], None]] = None
        self._tick_count = 0
        self._last_overdue_notify = 0.0

    def set_notify_fn(self, fn: Callable[[str], None]) -> None:
        """Set Telegram notification function."""
        self._notify_fn = fn

    def set_repl_fn(self, fn: Callable[[str], None]) -> None:
        """Set REPL output function (for daemon mode console)."""
        self._repl_fn = fn

    def tick(self) -> int:
        """
        Called every homeostasis tick. Returns number of fired reminders.

        Only actually checks every CHECK_INTERVAL_TICKS ticks.
        """
        self._tick_count += 1
        if self._tick_count % CHECK_INTERVAL_TICKS != 0:
            return 0

        fired = 0
        now = time.time()

        # Fire due reminders
        due = self._reminder_store.get_due(now)
        for rem in due:
            self._fire_reminder(rem)
            fired += 1

        # Notify about overdue todos (with cooldown)
        if self._todo_store and (now - self._last_overdue_notify) > OVERDUE_NOTIFY_COOLDOWN:
            overdue = self._todo_store.get_overdue(now)
            if overdue:
                self._notify_overdue_todos(overdue)
                self._last_overdue_notify = now

        return fired

    def _fire_reminder(self, rem: Reminder) -> None:
        """Fire a single reminder notification."""
        dt = datetime.fromtimestamp(rem.scheduled_at)
        time_str = dt.strftime("%H:%M")
        msg = f"[Przypomnienie {time_str}] {rem.text}"

        logger.info("Firing reminder %s: %s", rem.id, rem.text)

        if rem.notify_telegram and self._notify_fn:
            try:
                self._notify_fn(msg)
            except Exception as e:
                logger.warning("Telegram notify failed for %s: %s", rem.id, e)

        if self._repl_fn:
            try:
                self._repl_fn(msg)
            except Exception:
                pass

        self._reminder_store.mark_triggered(rem)

    def _notify_overdue_todos(self, overdue: list) -> None:
        """Notify about overdue todos."""
        if not self._notify_fn:
            return
        lines = [f"[Zaległe zadania: {len(overdue)}]"]
        for t in overdue[:5]:  # max 5 in notification
            lines.append(f"  - {t.text} ({t.id})")
        if len(overdue) > 5:
            lines.append(f"  ... i {len(overdue) - 5} wiecej")
        try:
            self._notify_fn("\n".join(lines))
        except Exception as e:
            logger.warning("Overdue notify failed: %s", e)

    def force_check(self) -> int:
        """Force immediate check (bypass tick counter). Returns fired count."""
        now = time.time()
        due = self._reminder_store.get_due(now)
        fired = 0
        for rem in due:
            self._fire_reminder(rem)
            fired += 1
        return fired
