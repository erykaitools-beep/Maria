"""Exercise UI notification consumers with temp logs and a local fake sender."""

import importlib
import json
from collections import deque
from types import SimpleNamespace

import pytest

from agent_core.storage.jsonl_reader import JSONLCursor


@pytest.fixture
def ui(monkeypatch, tmp_path):
    # Config may query the local Tailscale command on first import.
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: SimpleNamespace(stdout=""))
    app = importlib.import_module("maria_ui.app")
    monkeypatch.setattr(app, "_PLANNER_DECISIONS_PATH", tmp_path / "planner.jsonl")
    monkeypatch.setattr(app, "_planner_cursor", None)
    monkeypatch.setattr(app, "_planner_pending", deque())
    monkeypatch.setattr(app, "_event_pending", deque())
    monkeypatch.setattr(app, "_last_planner_timestamp", 0.0)
    monkeypatch.setattr(app, "_last_event_timestamp", 0.0)
    monkeypatch.setattr(app, "_last_known_mode", "ACTIVE")
    return app


def _append(path, records):
    with path.open("a", encoding="utf-8") as stream:
        for r in records:
            stream.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_planner_burst_same_timestamp_and_rotation_do_not_drop_messages(ui, monkeypatch):
    messages = []
    monkeypatch.setattr(ui, "send_proactive_notification", lambda **kw: messages.append(kw))
    rows = [{"action_type": "learn", "timestamp": 1.0, "message": f"m{i}"}
            for i in range(50)]
    _append(ui._PLANNER_DECISIONS_PATH, rows)
    ui._check_planner_notifications()
    ui._check_planner_notifications()
    assert [m["message"] for m in messages] == [f"m{i}" for i in range(50)]
    replacement = ui._PLANNER_DECISIONS_PATH.with_suffix(".tmp")
    _append(replacement, rows[-2:] + [{"action_type": "exam", "timestamp": 1.0,
                                      "message": "new"}])
    replacement.replace(ui._PLANNER_DECISIONS_PATH)
    ui._check_planner_notifications()
    assert [m["message"] for m in messages][-1] == "new"
    assert len(messages) == 51


def test_failed_send_preserves_unprocessed_batch_for_retry(ui, monkeypatch):
    sent = []
    rows = [{"action_type": "exam", "timestamp": 1.0, "message": str(i)}
            for i in range(3)]
    _append(ui._PLANNER_DECISIONS_PATH, rows)

    def sender(**kw):
        if kw["message"] == "1":
            raise OSError("fake sender unavailable")
        sent.append(kw["message"])

    monkeypatch.setattr(ui, "send_proactive_notification", sender)
    with pytest.raises(OSError, match="fake sender"):
        ui._check_planner_notifications()
    monkeypatch.setattr(ui, "send_proactive_notification", lambda **kw: sent.append(kw["message"]))
    ui._check_planner_notifications()
    assert sent == ["0", "1", "2"]


def test_bad_field_types_do_not_poison_following_planner_rows(ui, monkeypatch):
    sent = []
    monkeypatch.setattr(ui, "send_proactive_notification", lambda **kw: sent.append(kw))
    _append(ui._PLANNER_DECISIONS_PATH, [
        {"action_type": [], "timestamp": None},
        {"action_type": "exam", "timestamp": "old", "message": 42, "result": None},
        {"action_type": "learn", "timestamp": 3, "message": "next"},
    ])
    ui._check_planner_notifications()
    assert [row["message"] for row in sent] == ["42", "next"]
    assert not ui._planner_pending


def test_homeostasis_consumer_reads_whole_burst_in_file_order(ui, monkeypatch, tmp_path):
    path = tmp_path / "events.jsonl"
    rows = [{"event_type": "alert", "severity": "CRITICAL", "timestamp": 1.0,
             "message": f"alert {i}"} for i in range(25)]
    rows += [{"event": "state_snapshot", "mode": "REDUCED", "timestamp": 1.0},
             {"event": "mode_change", "from_mode": "REDUCED", "to_mode": "ACTIVE",
              "timestamp": 1.0}]
    _append(path, rows)
    monkeypatch.setattr(ui, "_event_cursor", JSONLCursor(path))
    monkeypatch.setattr(ui, "HOMEOSTASIS_AVAILABLE", True)
    sent = []
    monkeypatch.setattr(ui, "send_proactive_notification", lambda **kw: sent.append(kw))

    class OnePoll:
        done = False
        def is_set(self):
            return self.done
        def wait(self, seconds):
            self.done = True

    monkeypatch.setattr(ui, "_notification_stop_event", OnePoll())
    ui.notification_monitor_loop()
    assert [m["message"] for m in sent[:25]] == [f"alert {i}" for i in range(25)]
    assert len(sent) == 26
    assert ui._last_known_mode == "ACTIVE"


def test_history_reads_latest_messages_and_ignores_partial_write(ui, monkeypatch, tmp_path):
    path = tmp_path / "chat.jsonl"
    _append(path, [{"role": "user", "content": f"msg {i}"} for i in range(100)])
    with path.open("a") as stream:
        stream.write('{"content":"unfinished')
    monkeypatch.setattr(ui, "CHAT_LOG_FILE", path)
    monkeypatch.setattr(ui, "_ui_chat_history_loaded", False)
    monkeypatch.setattr(ui, "_ui_chat_history", [])
    assert ui._load_persisted_chat_history() == 50
    assert [r["content"] for r in ui._ui_chat_history] == [f"msg {i}" for i in range(50, 100)]
