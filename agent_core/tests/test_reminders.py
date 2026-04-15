"""Tests for reminders module - models, store, scheduler, time parser."""

import json
import os
import tempfile
import time
import pytest
from pathlib import Path

from agent_core.reminders.reminder_model import (
    Reminder, ReminderStatus, Recurrence,
    Todo, TodoStatus, TodoPriority,
)
from agent_core.reminders.reminder_store import ReminderStore, TodoStore
from agent_core.reminders.scheduler import ReminderScheduler, CHECK_INTERVAL_TICKS
from agent_core.reminders.time_parser import parse_time, format_scheduled_time


# ========== Reminder Model ==========

class TestReminderModel:
    def test_reminder_defaults(self):
        r = Reminder(text="test")
        assert r.status == ReminderStatus.PENDING
        assert r.recurrence == Recurrence.ONCE
        assert r.notify_telegram is True
        assert r.id.startswith("rem-")

    def test_reminder_is_due(self):
        r = Reminder(text="test", scheduled_at=time.time() - 10)
        assert r.is_due()

    def test_reminder_not_due_yet(self):
        r = Reminder(text="test", scheduled_at=time.time() + 3600)
        assert not r.is_due()

    def test_reminder_triggered_not_due(self):
        r = Reminder(text="test", scheduled_at=time.time() - 10, status=ReminderStatus.TRIGGERED)
        assert not r.is_due()

    def test_reminder_dismissed_not_due(self):
        r = Reminder(text="test", scheduled_at=time.time() - 10, status=ReminderStatus.DISMISSED)
        assert not r.is_due()

    def test_reminder_snoozed_is_due(self):
        r = Reminder(text="test", status=ReminderStatus.SNOOZED, snoozed_until=time.time() - 5)
        assert r.is_due()

    def test_reminder_snoozed_not_due(self):
        r = Reminder(text="test", status=ReminderStatus.SNOOZED, snoozed_until=time.time() + 3600)
        assert not r.is_due()

    def test_reminder_to_dict(self):
        r = Reminder(text="test", recurrence=Recurrence.DAILY)
        d = r.to_dict()
        assert d["text"] == "test"
        assert d["recurrence"] == "DAILY"
        assert d["status"] == "PENDING"

    def test_reminder_from_dict(self):
        d = {"id": "rem-abc", "text": "hello", "scheduled_at": 1000.0,
             "recurrence": "WEEKLY", "status": "PENDING"}
        r = Reminder.from_dict(d)
        assert r.id == "rem-abc"
        assert r.recurrence == Recurrence.WEEKLY

    def test_reminder_roundtrip(self):
        r = Reminder(text="rt", scheduled_at=1234.5, recurrence=Recurrence.MONTHLY)
        r2 = Reminder.from_dict(r.to_dict())
        assert r2.text == r.text
        assert r2.recurrence == r.recurrence
        assert r2.scheduled_at == r.scheduled_at


# ========== Todo Model ==========

class TestTodoModel:
    def test_todo_defaults(self):
        t = Todo(text="task")
        assert t.status == TodoStatus.PENDING
        assert t.priority == TodoPriority.NORMAL
        assert t.id.startswith("todo-")
        assert t.deadline is None

    def test_todo_overdue(self):
        t = Todo(text="late", deadline=time.time() - 100)
        assert t.is_overdue()

    def test_todo_not_overdue(self):
        t = Todo(text="ok", deadline=time.time() + 3600)
        assert not t.is_overdue()

    def test_todo_no_deadline_not_overdue(self):
        t = Todo(text="no dl")
        assert not t.is_overdue()

    def test_todo_done_not_overdue(self):
        t = Todo(text="done", deadline=time.time() - 100, status=TodoStatus.DONE)
        assert not t.is_overdue()

    def test_todo_roundtrip(self):
        t = Todo(text="rt", priority=TodoPriority.HIGH)
        t2 = Todo.from_dict(t.to_dict())
        assert t2.text == t.text
        assert t2.priority == TodoPriority.HIGH


# ========== ReminderStore ==========

class TestReminderStore:
    @pytest.fixture
    def store(self, tmp_path):
        return ReminderStore(path=tmp_path / "rem.jsonl")

    def test_add_and_get(self, store):
        r = Reminder(text="test")
        store.add(r)
        assert store.get(r.id) is not None
        assert store.get(r.id).text == "test"

    def test_get_pending(self, store):
        store.add(Reminder(text="a"))
        store.add(Reminder(text="b", status=ReminderStatus.TRIGGERED))
        assert len(store.get_pending()) == 1

    def test_get_due(self, store):
        store.add(Reminder(text="due", scheduled_at=time.time() - 10))
        store.add(Reminder(text="future", scheduled_at=time.time() + 3600))
        due = store.get_due()
        assert len(due) == 1
        assert due[0].text == "due"

    def test_dismiss(self, store):
        r = Reminder(text="dis")
        store.add(r)
        store.dismiss(r.id)
        assert store.get(r.id).status == ReminderStatus.DISMISSED

    def test_snooze(self, store):
        r = Reminder(text="snz")
        store.add(r)
        store.snooze(r.id, 10)
        s = store.get(r.id)
        assert s.status == ReminderStatus.SNOOZED
        assert s.snoozed_until is not None

    def test_mark_triggered_once(self, store):
        r = Reminder(text="once", scheduled_at=time.time() - 10)
        store.add(r)
        store.mark_triggered(r)
        assert store.get(r.id).status == ReminderStatus.TRIGGERED
        # No new reminder created for ONCE
        assert len(store.get_pending()) == 0

    def test_mark_triggered_daily(self, store):
        r = Reminder(text="daily", scheduled_at=time.time() - 10, recurrence=Recurrence.DAILY)
        store.add(r)
        store.mark_triggered(r)
        assert store.get(r.id).status == ReminderStatus.TRIGGERED
        # New daily reminder created
        pending = store.get_pending()
        assert len(pending) == 1
        assert pending[0].text == "daily"
        assert pending[0].recurrence == Recurrence.DAILY

    def test_persistence(self, tmp_path):
        path = tmp_path / "rem.jsonl"
        store1 = ReminderStore(path=path)
        store1.add(Reminder(text="persist", scheduled_at=1000.0))

        store2 = ReminderStore(path=path)
        assert len(store2.get_all()) == 1
        assert store2.get_all()[0].text == "persist"

    def test_count(self, store):
        store.add(Reminder(text="a"))
        store.add(Reminder(text="b", status=ReminderStatus.TRIGGERED))
        c = store.count()
        assert c["pending"] == 1
        assert c["triggered"] == 1
        assert c["total"] == 2

    def test_load_corrupted_jsonl_line(self, tmp_path):
        path = tmp_path / "rem.jsonl"
        valid = Reminder(text="valid reminder")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(valid.to_dict()) + "\n")
            f.write("{bad json\n")

        store = ReminderStore(path=path)
        assert store.get(valid.id) is not None


# ========== TodoStore ==========

class TestTodoStore:
    @pytest.fixture
    def store(self, tmp_path):
        return TodoStore(path=tmp_path / "todo.jsonl")

    def test_add_and_get(self, store):
        t = Todo(text="task")
        store.add(t)
        assert store.get(t.id) is not None

    def test_complete(self, store):
        t = Todo(text="done")
        store.add(t)
        store.complete(t.id)
        assert store.get(t.id).status == TodoStatus.DONE
        assert store.get(t.id).completed_at is not None

    def test_cancel(self, store):
        t = Todo(text="can")
        store.add(t)
        store.cancel(t.id)
        assert store.get(t.id).status == TodoStatus.CANCELLED

    def test_get_pending(self, store):
        store.add(Todo(text="a"))
        store.add(Todo(text="b", status=TodoStatus.DONE))
        assert len(store.get_pending()) == 1

    def test_get_overdue(self, store):
        store.add(Todo(text="late", deadline=time.time() - 100))
        store.add(Todo(text="ok", deadline=time.time() + 3600))
        overdue = store.get_overdue()
        assert len(overdue) == 1

    def test_persistence(self, tmp_path):
        path = tmp_path / "todo.jsonl"
        s1 = TodoStore(path=path)
        s1.add(Todo(text="persist"))
        s2 = TodoStore(path=path)
        assert len(s2.get_all()) == 1

    def test_count(self, store):
        store.add(Todo(text="a"))
        store.add(Todo(text="b"))
        store.complete(store.get_pending()[0].id)
        c = store.count()
        assert c["pending"] == 1
        assert c["done"] == 1

    def test_load_corrupted_jsonl_line(self, tmp_path):
        path = tmp_path / "todo.jsonl"
        valid = Todo(text="valid todo")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(valid.to_dict()) + "\n")
            f.write("{bad json\n")

        store = TodoStore(path=path)
        assert store.get(valid.id) is not None


# ========== ReminderScheduler ==========

class TestReminderScheduler:
    @pytest.fixture
    def setup(self, tmp_path):
        rs = ReminderStore(path=tmp_path / "rem.jsonl")
        ts = TodoStore(path=tmp_path / "todo.jsonl")
        sched = ReminderScheduler(rs, ts)
        return rs, ts, sched

    def test_tick_fires_due(self, setup):
        rs, ts, sched = setup
        fired = []
        sched.set_notify_fn(lambda msg: fired.append(msg))

        rs.add(Reminder(text="fire me", scheduled_at=time.time() - 10))

        # Tick enough times to trigger check
        for _ in range(CHECK_INTERVAL_TICKS):
            sched.tick()

        assert len(fired) == 1
        assert "fire me" in fired[0]
        assert rs.get_all()[0].status == ReminderStatus.TRIGGERED

    def test_tick_skips_future(self, setup):
        rs, ts, sched = setup
        fired = []
        sched.set_notify_fn(lambda msg: fired.append(msg))

        rs.add(Reminder(text="future", scheduled_at=time.time() + 3600))

        for _ in range(CHECK_INTERVAL_TICKS):
            sched.tick()

        assert len(fired) == 0

    def test_force_check(self, setup):
        rs, ts, sched = setup
        fired = []
        sched.set_notify_fn(lambda msg: fired.append(msg))

        rs.add(Reminder(text="force", scheduled_at=time.time() - 10))

        count = sched.force_check()
        assert count == 1
        assert len(fired) == 1

    def test_overdue_todo_notification(self, setup):
        rs, ts, sched = setup
        msgs = []
        sched.set_notify_fn(lambda msg: msgs.append(msg))

        ts.add(Todo(text="zalegly", deadline=time.time() - 100))

        for _ in range(CHECK_INTERVAL_TICKS):
            sched.tick()

        # Should have overdue notification
        assert any("zalegly" in m.lower() or "Zaleg" in m for m in msgs)

    def test_repl_fn_called(self, setup):
        rs, ts, sched = setup
        repl = []
        sched.set_repl_fn(lambda msg: repl.append(msg))

        rs.add(Reminder(text="repl test", scheduled_at=time.time() - 10, notify_telegram=False))

        sched.force_check()
        assert len(repl) == 1


# ========== Time Parser ==========

class TestTimeParser:
    def test_za_30min(self):
        now = time.time()
        ts = parse_time("za 30min")
        assert ts is not None
        assert abs(ts - (now + 1800)) < 2

    def test_za_2h(self):
        now = time.time()
        ts = parse_time("za 2h")
        assert ts is not None
        assert abs(ts - (now + 7200)) < 2

    def test_za_1d(self):
        now = time.time()
        ts = parse_time("za 1d")
        assert ts is not None
        assert abs(ts - (now + 86400)) < 2

    def test_in_30min(self):
        now = time.time()
        ts = parse_time("in 30min")
        assert ts is not None
        assert abs(ts - (now + 1800)) < 2

    def test_o_1430(self):
        ts = parse_time("o 14:30")
        assert ts is not None
        from datetime import datetime
        dt = datetime.fromtimestamp(ts)
        assert dt.hour == 14
        assert dt.minute == 30

    def test_at_0900(self):
        ts = parse_time("at 09:00")
        assert ts is not None
        from datetime import datetime
        dt = datetime.fromtimestamp(ts)
        assert dt.hour == 9
        assert dt.minute == 0

    def test_jutro(self):
        ts = parse_time("jutro 10:00")
        assert ts is not None
        from datetime import datetime, timedelta
        dt = datetime.fromtimestamp(ts)
        tomorrow = (datetime.now() + timedelta(days=1)).date()
        assert dt.date() == tomorrow

    def test_tomorrow(self):
        ts = parse_time("tomorrow 8:00")
        assert ts is not None

    def test_pojutrze(self):
        ts = parse_time("pojutrze 12:00")
        assert ts is not None
        from datetime import datetime, timedelta
        dt = datetime.fromtimestamp(ts)
        day_after = (datetime.now() + timedelta(days=2)).date()
        assert dt.date() == day_after

    def test_bare_hhmm(self):
        ts = parse_time("15:00")
        assert ts is not None
        from datetime import datetime
        dt = datetime.fromtimestamp(ts)
        assert dt.hour == 15

    def test_bare_30min(self):
        now = time.time()
        ts = parse_time("30min")
        assert ts is not None
        assert abs(ts - (now + 1800)) < 2

    def test_bare_2h(self):
        now = time.time()
        ts = parse_time("2h")
        assert ts is not None
        assert abs(ts - (now + 7200)) < 2

    def test_invalid(self):
        assert parse_time("foobar") is None
        assert parse_time("") is None

    def test_za_polish_units(self):
        now = time.time()
        for expr in ("za 5 minut", "za 5 minuty"):
            ts = parse_time(expr)
            assert ts is not None
            assert abs(ts - (now + 300)) < 2


class TestFormatScheduledTime:
    def test_today(self):
        ts = time.time() + 3600  # 1h from now
        result = format_scheduled_time(ts)
        assert "dzis" in result

    def test_tomorrow(self):
        from datetime import datetime, timedelta
        tomorrow = datetime.now().replace(hour=12, minute=0) + timedelta(days=1)
        result = format_scheduled_time(tomorrow.timestamp())
        assert "jutro" in result

    def test_far_future(self):
        from datetime import datetime, timedelta
        future = datetime.now() + timedelta(days=5)
        result = format_scheduled_time(future.timestamp())
        assert "." in result  # date format dd.mm
