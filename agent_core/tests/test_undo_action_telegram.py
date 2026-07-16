"""/undo_action <id> [tak]: operator-initiated undo execution, fail-closed + gated.

Drives the REAL coordinator._execute_undo through register_telegram_commands, with
a fake in-memory client standing in for live OpenClaw. Covers the flag gate, the
guards, the two-step confirm, and a successful restore.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from agent_core.effector.coordinator import EffectorCoordinator
from agent_core.effector.openclaw_client import OpenClawClient
from agent_core.effector.undo_journal import EffectorUndoJournal, STATUS_UNDONE
from agent_core.modules.homeostasis_telegram_commands import (
    register_telegram_commands as _register,
)
from agent_core.tests.spec_helpers import specced


class FakeFS:
    def __init__(self, files=None):
        self.files = dict(files or {})

    def invoke(self, tool, args):
        if tool == "write":
            self.files[args["path"]] = args["content"]
            return {"ok": True, "result": "ok"}
        if tool == "read":
            p = args["path"]
            if p in self.files:
                return {"ok": True, "result": self.files[p]}
            return {"ok": False, "error": "cat: No such file or directory"}
        if tool == "exec":
            argv = args.get("argv") or []
            if len(argv) >= 3 and argv[0] == "rm":
                self.files.pop(argv[-1], None)
            return {"ok": True, "result": ""}
        return {"ok": False, "error": "unknown"}


class FakeBridge:
    def __init__(self):
        self.handlers = {}

    def register_command(self, command, handler):
        self.handlers[command] = handler


def _harness(tmp_path, files=None):
    fs = FakeFS(files=files)
    client = specced(OpenClawClient)
    client.invoke_tool = MagicMock(side_effect=fs.invoke)
    journal = EffectorUndoJournal(path=tmp_path / "undo.jsonl")
    coord = EffectorCoordinator(openclaw_client=client, undo_journal=journal)
    ctx = SimpleNamespace(effector_coordinator=coord, undo_journal=journal)
    bridge = FakeBridge()
    _register(bridge, ctx)
    return bridge, journal, fs


def test_registered(tmp_path):
    bridge, *_ = _harness(tmp_path)
    assert "undo_action" in bridge.handlers


def test_flag_off_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("EFFECTOR_UNDO_EXECUTE_ENABLED", raising=False)
    bridge, journal, _ = _harness(tmp_path)
    rec = journal.record_action(tool="write", args={"path": "/a", "content": "NEW"},
                                read_fn=lambda p: "OLD")
    out = bridge.handlers["undo_action"](rec.record_id + " tak")
    assert "WYLACZONE" in out
    # nothing executed
    assert journal.get(rec.record_id).status != STATUS_UNDONE


def test_unknown_record(tmp_path, monkeypatch):
    monkeypatch.setenv("EFFECTOR_UNDO_EXECUTE_ENABLED", "1")
    bridge, *_ = _harness(tmp_path)
    assert "Nie znam" in bridge.handlers["undo_action"]("eundo-nope tak")


def test_bare_call_previews_then_confirm_executes(tmp_path, monkeypatch):
    monkeypatch.setenv("EFFECTOR_UNDO_EXECUTE_ENABLED", "1")
    bridge, journal, fs = _harness(tmp_path, files={"/a": "NEW"})
    rec = journal.record_action(tool="write", args={"path": "/a", "content": "NEW"},
                                read_fn=lambda p: "OLD")
    # step 1: bare call -> preview + asks to confirm, executes NOTHING
    preview = bridge.handlers["undo_action"](rec.record_id)
    assert "tak" in preview
    assert journal.get(rec.record_id).status != STATUS_UNDONE
    assert fs.files["/a"] == "NEW"
    # step 2: confirm -> restores prior content
    done = bridge.handlers["undo_action"](rec.record_id + " tak")
    assert "Cofnieto" in done
    assert fs.files["/a"] == "OLD"
    assert journal.get(rec.record_id).status == STATUS_UNDONE


def test_already_undone(tmp_path, monkeypatch):
    monkeypatch.setenv("EFFECTOR_UNDO_EXECUTE_ENABLED", "1")
    bridge, journal, _ = _harness(tmp_path, files={"/a": "NEW"})
    rec = journal.record_action(tool="write", args={"path": "/a", "content": "NEW"},
                                read_fn=lambda p: "OLD")
    bridge.handlers["undo_action"](rec.record_id + " tak")
    again = bridge.handlers["undo_action"](rec.record_id + " tak")
    assert "juz cofniety" in again


def test_irreversible_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("EFFECTOR_UNDO_EXECUTE_ENABLED", "1")
    bridge, journal, _ = _harness(tmp_path)
    rec = journal.record_action(tool="exec", args={"command": "ls"})  # irreversible
    out = bridge.handlers["undo_action"](rec.record_id + " tak")
    assert "NIE da sie" in out


def test_no_id_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("EFFECTOR_UNDO_EXECUTE_ENABLED", "1")
    bridge, *_ = _harness(tmp_path)
    assert "Uzycie" in bridge.handlers["undo_action"]("")
