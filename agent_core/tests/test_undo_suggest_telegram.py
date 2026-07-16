"""Telegram surface for the undo-SUGGEST side: /approve_undo + /drill_suggest_undo.

Drives the REAL handlers through register_telegram_commands with a real
Conductor + BulletinStore + EffectorCoordinator (fake in-memory OpenClaw client)
+ UndoSuggestionCreator. Covers registration, the EXECUTE flag gate, unknown
task, the happy execute-then-close path, the failure-then-block path, and the
drill propose chain.
"""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent_core.bulletin.bulletin_store import BulletinStore
from agent_core.conductor import Conductor, TaskQueue
from agent_core.conductor.task_model import TaskStatus
from agent_core.effector.coordinator import EffectorCoordinator
from agent_core.effector.openclaw_client import OpenClawClient
from agent_core.effector.undo_journal import EffectorUndoJournal, STATUS_UNDONE
from agent_core.modules.homeostasis_telegram_commands import (
    register_telegram_commands as _register,
)
from agent_core.tests.spec_helpers import specced
from agent_core.undo_suggest.detector import UndoSuggestionCandidate
from agent_core.undo_suggest.suggestion_creator import UndoSuggestionCreator


class FakeFS:
    def __init__(self, files=None):
        self.files = dict(files or {})
        # When True, reads return a wrong value -> the undo post-verify mismatches
        # and _execute_undo refuses success (data-corruption guard). Read live on
        # each call, so a test can toggle it after the harness is built.
        self.corrupt_read = False

    def invoke(self, tool, args):
        if tool == "write":
            self.files[args["path"]] = args["content"]
            return {"ok": True, "result": "ok"}
        if tool == "read":
            p = args["path"]
            if self.corrupt_read:
                return {"ok": True, "result": "CORRUPT-" + str(self.files.get(p, ""))}
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
        self.bot = MagicMock()

    def register_command(self, command, handler):
        self.handlers[command] = handler


class FakeSelfPerception:
    def get_latest(self):
        return {"snapshot_id": "sps-1", "mode": "ACTIVE"}

    def is_fresh(self, max_age_seconds=300):
        return True

    def take_snapshot(self):
        return self.get_latest()


def _harness(tmp_path, files=None):
    fs = FakeFS(files=files)
    client = specced(OpenClawClient)
    client.invoke_tool = MagicMock(side_effect=fs.invoke)
    journal = EffectorUndoJournal(path=tmp_path / "undo.jsonl")
    coord = EffectorCoordinator(openclaw_client=client, undo_journal=journal)
    conductor = Conductor(queue=TaskQueue(path=tmp_path / "maria_task_queue.jsonl"))
    bulletin = BulletinStore(path=tmp_path / "bulletin.jsonl")
    creator = UndoSuggestionCreator(
        conductor=conductor, bulletin_store=bulletin,
        notifier=MagicMock(), self_perception=FakeSelfPerception(),
    )
    ctx = SimpleNamespace(
        effector_coordinator=coord,
        undo_journal=journal,
        maria_conductor=conductor,
        bulletin_store=bulletin,
        undo_suggestion_creator=creator,
    )
    bridge = FakeBridge()
    _register(bridge, ctx)
    return bridge, journal, conductor, bulletin, fs, creator


def _seed_suggestion(journal, creator, *, path="/a", prior="OLD"):
    """A real reversible journal record + a PENDING suggestion task for it."""
    rec = journal.record_action(
        tool="write", args={"path": path, "content": "NEW"},
        read_fn=lambda p: prior, metadata={"goal_id": "g1"},
    )
    candidate = UndoSuggestionCandidate(
        undo_record_id=rec.record_id, tool="write", goal_id="g1",
        summary=f"write for goal g1 (failed) -- propose undo of {path}",
        evidence_summary={"path": path, "goal_status": "failed",
                          "inverse_note": "restore"},
        detected_at=time.time(),
    )
    task_id = creator.create(candidate, "sps-1", bypass_gate=True)
    return rec, task_id


def test_commands_registered(tmp_path):
    bridge, *_ = _harness(tmp_path)
    assert "approve_undo" in bridge.handlers
    assert "drill_suggest_undo" in bridge.handlers


def test_approve_undo_flag_off_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("EFFECTOR_UNDO_EXECUTE_ENABLED", raising=False)
    bridge, journal, conductor, _, _, creator = _harness(tmp_path)
    rec, task_id = _seed_suggestion(journal, creator)

    out = bridge.handlers["approve_undo"](task_id)

    assert "WYLACZONE" in out
    assert journal.get(rec.record_id).status != STATUS_UNDONE
    # task stays PENDING (nothing executed)
    assert conductor.get_pending_undo_suggestions()[0].task_id == task_id


def test_approve_undo_unknown_task(tmp_path, monkeypatch):
    monkeypatch.setenv("EFFECTOR_UNDO_EXECUTE_ENABLED", "1")
    bridge, *_ = _harness(tmp_path)
    assert "Nie znaleziono" in bridge.handlers["approve_undo"]("cdt-nope")


def test_approve_undo_happy_executes_and_closes(tmp_path, monkeypatch):
    monkeypatch.setenv("EFFECTOR_UNDO_EXECUTE_ENABLED", "1")
    bridge, journal, conductor, bulletin, fs, creator = _harness(
        tmp_path, files={"/a": "NEW"}
    )
    rec, task_id = _seed_suggestion(journal, creator, path="/a", prior="OLD")

    out = bridge.handlers["approve_undo"](task_id)

    assert "cofnieto" in out.lower()
    # inverse executed: restore prior content
    assert journal.get(rec.record_id).status == STATUS_UNDONE
    assert fs.files["/a"] == "OLD"
    # task closed, bulletin resolved
    task = [t for t in conductor.list_tasks(project="maria") if t.task_id == task_id][0]
    assert task.status == TaskStatus.DONE
    assert conductor.get_pending_undo_suggestions() == []
    assert bulletin.get_open() == []
    # Review F3: confirmation is delivered ONCE (via the returned string); the
    # handler must NOT also explicitly send it.
    bridge.bot.send_message.assert_not_called()


def test_approve_undo_failure_blocks_task(tmp_path, monkeypatch):
    monkeypatch.setenv("EFFECTOR_UNDO_EXECUTE_ENABLED", "1")
    bridge, journal, conductor, bulletin, fs, creator = _harness(
        tmp_path, files={"/a": "NEW"}
    )
    rec, task_id = _seed_suggestion(journal, creator, path="/a", prior="OLD")
    # Make the restore verification fail: the post-write re-read returns a
    # different content than intended -> _execute_undo refuses success. Toggled
    # AFTER seeding, so the pre-state capture (separate read_fn) is unaffected.
    fs.corrupt_read = True

    out = bridge.handlers["approve_undo"](task_id)

    assert "NIE powiodlo" in out
    task = [t for t in conductor.list_tasks(project="maria") if t.task_id == task_id][0]
    assert task.status == TaskStatus.BLOCKED
    # Review F4: the bulletin is closed immediately on failure, not left open to
    # leak when expiry is flag-gated off.
    assert bulletin.get_open() == []


def test_drill_suggest_undo_force_creates(tmp_path):
    bridge, journal, conductor, bulletin, _, _ = _harness(tmp_path)

    out = bridge.handlers["drill_suggest_undo"]("force")

    assert "Drill OK" in out
    pending = conductor.get_pending_undo_suggestions()
    assert len(pending) == 1
    assert pending[0].artifacts["drill"] is True
    assert pending[0].artifacts["approval_required"] is True
    assert bulletin.get_open()
