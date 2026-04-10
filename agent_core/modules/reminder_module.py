"""
REPL commands: /remind and /todo.

/remind [create|list|dismiss|snooze]
/todo [create|list|done|cancel]
"""

import logging
import time
from datetime import datetime

from agent_core.registry import MariaModule, CommandInfo

logger = logging.getLogger(__name__)


class ReminderModule(MariaModule):
    """Reminders & Todos - time-triggered notifications and task tracking."""

    name = "reminders"
    description = "Przypomnienia i zadania"

    def init(self, ctx) -> bool:
        self.ctx = ctx
        return True

    def get_commands(self):
        return [
            CommandInfo(
                "/remind", self._cmd_remind,
                "  /remind <tekst> <czas>         - nowe przypomnienie (np. /remind spotkanie za 30min)\n"
                "  /remind list                   - lista aktywnych przypomnien\n"
                "  /remind dismiss <id>           - usun przypomnienie\n"
                "  /remind snooze <id> [minuty]   - odloz (domyslnie 15min)\n"
                "  /remind daily <tekst> <HH:MM>  - codzienne przypomnienie",
                "[REMINDERS]",
            ),
            CommandInfo(
                "/todo", self._cmd_todo,
                "  /todo <tekst>                  - nowe zadanie\n"
                "  /todo list [all]               - lista zadan (pending / all)\n"
                "  /todo done <id>                - oznacz jako zrobione\n"
                "  /todo cancel <id>              - anuluj zadanie\n"
                "  /todo high <tekst>             - nowe zadanie (priorytet wysoki)\n"
                "  /todo deadline <id> <czas>     - ustaw deadline",
                "[REMINDERS]",
            ),
        ]

    # ----- helpers -----

    def _get_reminder_store(self):
        return getattr(self.ctx, 'reminder_store', None)

    def _get_todo_store(self):
        return getattr(self.ctx, 'todo_store', None)

    # ----- /remind -----

    def _cmd_remind(self, args):
        store = self._get_reminder_store()
        if store is None:
            print("[Remind] Modul nie zainicjalizowany")
            return

        if not args:
            return self._remind_list(store)

        sub = args[0].lower()
        if sub == "list":
            return self._remind_list(store)
        elif sub == "dismiss" and len(args) > 1:
            return self._remind_dismiss(store, args[1])
        elif sub == "snooze" and len(args) > 1:
            minutes = 15
            if len(args) > 2:
                try:
                    minutes = int(args[2])
                except ValueError:
                    pass
            return self._remind_snooze(store, args[1], minutes)
        elif sub == "daily" and len(args) > 2:
            return self._remind_create_daily(store, args)
        else:
            return self._remind_create(store, args)

    def _remind_create(self, store, args):
        from agent_core.reminders import Reminder, parse_time, format_scheduled_time

        # Find time expression in args (last 1-2 tokens)
        text_parts = []
        time_str = None
        scheduled = None

        # Try last 2 tokens as time, then last 1
        for n in (2, 1):
            if len(args) >= n + 1:
                candidate = " ".join(args[-n:])
                ts = parse_time(candidate)
                if ts is not None:
                    scheduled = ts
                    time_str = candidate
                    text_parts = args[:-n]
                    break

        if scheduled is None:
            # No time found - default to 30min from now
            text_parts = args
            scheduled = time.time() + 1800
            time_str = "za 30min"

        text = " ".join(text_parts)
        if not text:
            print("[Remind] Uzycie: /remind <tekst> <czas>")
            print("  Czas: za 30min, za 2h, o 14:30, jutro 9:00")
            return

        rem = Reminder(text=text, scheduled_at=scheduled)
        store.add(rem)
        when = format_scheduled_time(scheduled)
        print(f"[Remind] Utworzono: {rem.id}")
        print(f"  \"{text}\" - {when}")

    def _remind_create_daily(self, store, args):
        from agent_core.reminders import Reminder, Recurrence, parse_time, format_scheduled_time

        # /remind daily <text...> <HH:MM>
        time_str = args[-1]
        text = " ".join(args[1:-1])
        if not text:
            print("[Remind] Uzycie: /remind daily <tekst> <HH:MM>")
            return

        scheduled = parse_time(time_str)
        if scheduled is None:
            print(f"[Remind] Nie rozumiem czasu: {time_str}")
            return

        rem = Reminder(text=text, scheduled_at=scheduled, recurrence=Recurrence.DAILY)
        store.add(rem)
        when = format_scheduled_time(scheduled)
        print(f"[Remind] Codzienne: {rem.id}")
        print(f"  \"{text}\" - codziennie {datetime.fromtimestamp(scheduled).strftime('%H:%M')}")

    def _remind_list(self, store):
        pending = store.get_pending()
        if not pending:
            print("[Remind] Brak aktywnych przypomnien")
            return

        from agent_core.reminders import format_scheduled_time
        print(f"[Remind] Aktywne przypomnienia ({len(pending)}):")
        for r in sorted(pending, key=lambda x: x.scheduled_at):
            when = format_scheduled_time(r.scheduled_at)
            status = "SNOOZED" if r.status.value == "SNOOZED" else ""
            recur = f" [{r.recurrence.value}]" if r.recurrence.value != "ONCE" else ""
            extra = f" {status}" if status else ""
            print(f"  {r.id}: \"{r.text}\" - {when}{recur}{extra}")

    def _remind_dismiss(self, store, id_or_prefix):
        rem = self._find_by_prefix(store.get_all(), id_or_prefix)
        if rem is None:
            print(f"[Remind] Nie znaleziono: {id_or_prefix}")
            return
        store.dismiss(rem.id)
        print(f"[Remind] Usunieto: {rem.id} \"{rem.text}\"")

    def _remind_snooze(self, store, id_or_prefix, minutes):
        rem = self._find_by_prefix(store.get_pending(), id_or_prefix)
        if rem is None:
            print(f"[Remind] Nie znaleziono: {id_or_prefix}")
            return
        store.snooze(rem.id, minutes)
        print(f"[Remind] Odlozono o {minutes}min: {rem.id} \"{rem.text}\"")

    # ----- /todo -----

    def _cmd_todo(self, args):
        store = self._get_todo_store()
        if store is None:
            print("[Todo] Modul nie zainicjalizowany")
            return

        if not args:
            return self._todo_list(store, show_all=False)

        sub = args[0].lower()
        if sub == "list":
            show_all = len(args) > 1 and args[1].lower() == "all"
            return self._todo_list(store, show_all)
        elif sub == "done" and len(args) > 1:
            return self._todo_done(store, args[1])
        elif sub == "cancel" and len(args) > 1:
            return self._todo_cancel(store, args[1])
        elif sub == "high":
            return self._todo_create(store, args[1:], priority="HIGH")
        elif sub == "deadline" and len(args) > 2:
            return self._todo_set_deadline(store, args[1], " ".join(args[2:]))
        else:
            return self._todo_create(store, args)

    def _todo_create(self, store, args, priority="NORMAL"):
        from agent_core.reminders import Todo, TodoPriority

        text = " ".join(args)
        if not text:
            print("[Todo] Uzycie: /todo <tekst>")
            return

        todo = Todo(text=text, priority=TodoPriority(priority))
        store.add(todo)
        prio_str = f" [{priority}]" if priority != "NORMAL" else ""
        print(f"[Todo] Utworzono: {todo.id}{prio_str}")
        print(f"  \"{text}\"")

    def _todo_list(self, store, show_all=False):
        if show_all:
            todos = store.get_all()
            label = "Wszystkie"
        else:
            todos = store.get_pending()
            label = "Aktywne"

        if not todos:
            print(f"[Todo] Brak zadan ({label.lower()})")
            return

        from agent_core.reminders import format_scheduled_time
        print(f"[Todo] {label} zadania ({len(todos)}):")
        for t in sorted(todos, key=lambda x: (x.status.value, -_priority_sort(x.priority.value))):
            status = t.status.value
            prio = f" [{t.priority.value}]" if t.priority.value != "NORMAL" else ""
            deadline = ""
            if t.deadline:
                deadline = f" (do: {format_scheduled_time(t.deadline)})"
                if t.is_overdue():
                    deadline += " ZALEGLY!"
            done = " [DONE]" if status == "DONE" else ""
            cancelled = " [CANCELLED]" if status == "CANCELLED" else ""
            print(f"  {t.id}: \"{t.text}\"{prio}{deadline}{done}{cancelled}")

    def _todo_done(self, store, id_or_prefix):
        todo = self._find_by_prefix(store.get_pending(), id_or_prefix)
        if todo is None:
            print(f"[Todo] Nie znaleziono: {id_or_prefix}")
            return
        store.complete(todo.id)
        print(f"[Todo] Zrobione: {todo.id} \"{todo.text}\"")

    def _todo_cancel(self, store, id_or_prefix):
        todo = self._find_by_prefix(store.get_pending(), id_or_prefix)
        if todo is None:
            print(f"[Todo] Nie znaleziono: {id_or_prefix}")
            return
        store.cancel(todo.id)
        print(f"[Todo] Anulowano: {todo.id} \"{todo.text}\"")

    def _todo_set_deadline(self, store, id_or_prefix, time_str):
        from agent_core.reminders import parse_time, format_scheduled_time

        todo = self._find_by_prefix(store.get_pending(), id_or_prefix)
        if todo is None:
            print(f"[Todo] Nie znaleziono: {id_or_prefix}")
            return

        ts = parse_time(time_str)
        if ts is None:
            print(f"[Todo] Nie rozumiem czasu: {time_str}")
            return

        todo.deadline = ts
        store._append(todo)
        store._todos[todo.id] = todo
        when = format_scheduled_time(ts)
        print(f"[Todo] Deadline: {todo.id} - {when}")

    # ----- utils -----

    @staticmethod
    def _find_by_prefix(items, prefix):
        """Find item by ID or ID prefix."""
        for item in items:
            if item.id == prefix or item.id.startswith(prefix):
                return item
        return None


def _priority_sort(p: str) -> int:
    return {"HIGH": 3, "NORMAL": 2, "LOW": 1}.get(p, 0)
