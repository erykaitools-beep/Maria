"""EffectorCoordinator._execute_undo -- run a journaled inverse + reconcile (DH-A).

The undo EXECUTION keystone, proven against an injectable in-memory fake invoke
(NO live OpenClaw). Covers the guards (flag/known/not-undone/action-failed/kind),
restore + remove success, and the FIX-4 verify-on-restore mismatch refusal.
"""

from unittest.mock import MagicMock

from agent_core.effector.coordinator import EffectorCoordinator
from agent_core.effector.openclaw_client import OpenClawClient
from agent_core.effector.undo_journal import (
    EffectorUndoJournal, STATUS_UNDONE, STATUS_UNDO_FAILED, STATUS_ACTION_FAILED,
)
from agent_core.tests.spec_helpers import specced


class FakeFS:
    """In-memory filesystem driving the injectable invoke(tool, args)."""

    def __init__(self, files=None, lossy=False):
        self.files = dict(files or {})
        self.lossy = lossy  # simulate a write that does not round-trip faithfully

    def invoke(self, tool, args):
        if tool == "write":
            content = args["content"]
            if self.lossy:
                content = content + "X"  # corrupt -> verify must catch it
            self.files[args["path"]] = content
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
        return {"ok": False, "error": "unknown tool"}


def _coord(journal):
    return EffectorCoordinator(openclaw_client=specced(OpenClawClient),
                               undo_journal=journal)


def _journal(tmp_path):
    return EffectorUndoJournal(path=tmp_path / "undo.jsonl")


def _on(monkeypatch):
    monkeypatch.setenv("EFFECTOR_UNDO_EXECUTE_ENABLED", "1")


# --- guards ---------------------------------------------------------------- #
def test_flag_off_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("EFFECTOR_UNDO_EXECUTE_ENABLED", raising=False)
    j = _journal(tmp_path)
    rec = j.record_action(tool="write", args={"path": "/a", "content": "n"},
                          read_fn=lambda p: "old")
    out = _coord(j)._execute_undo(rec.record_id, invoke=FakeFS().invoke)
    assert out["ok"] is False and out["reason"] == "execute_disabled"


def test_unknown_record(tmp_path, monkeypatch):
    _on(monkeypatch)
    out = _coord(_journal(tmp_path))._execute_undo("eundo-nope", invoke=FakeFS().invoke)
    assert out["reason"] == "unknown_record"


def test_already_undone(tmp_path, monkeypatch):
    _on(monkeypatch)
    j = _journal(tmp_path)
    rec = j.record_action(tool="write", args={"path": "/a", "content": "n"},
                          read_fn=lambda p: "old")
    j.mark_undone(rec.record_id, ok=True, detail="x")
    out = _coord(j)._execute_undo(rec.record_id, invoke=FakeFS().invoke)
    assert out["reason"] == "already_undone"


def test_action_failed_record_not_undoable(tmp_path, monkeypatch):
    _on(monkeypatch)
    j = _journal(tmp_path)
    rec = j.record_action(tool="write", args={"path": "/a", "content": "n"},
                          read_fn=lambda p: "old")
    j.mark_action_failed(rec.record_id)
    out = _coord(j)._execute_undo(rec.record_id, invoke=FakeFS().invoke)
    assert out["reason"] == "action_failed"


def test_irreversible_refused_not_faked(tmp_path, monkeypatch):
    _on(monkeypatch)
    j = _journal(tmp_path)
    rec = j.record_action(tool="exec", args={"command": "ls"})  # irreversible
    out = _coord(j)._execute_undo(rec.record_id, invoke=FakeFS().invoke)
    assert out["ok"] is False and out["reason"].startswith("not_auto_reversible")


def test_noop_read_inverse_succeeds(tmp_path, monkeypatch):
    _on(monkeypatch)
    j = _journal(tmp_path)
    rec = j.record_action(tool="read", args={"path": "/a"})  # noop inverse
    out = _coord(j)._execute_undo(rec.record_id, invoke=FakeFS().invoke)
    assert out["ok"] is True and out["reason"] == "noop"
    assert j.get(rec.record_id).status == STATUS_UNDONE


# --- restore (write inverse) ----------------------------------------------- #
def test_restore_existing_file_success(tmp_path, monkeypatch):
    _on(monkeypatch)
    j = _journal(tmp_path)
    fs = FakeFS(files={"/a": "NEW"})  # current (post-action) content
    # journal a write that overwrote prior "OLD"
    rec = j.record_action(tool="write", args={"path": "/a", "content": "NEW"},
                          read_fn=lambda p: "OLD")
    out = _coord(j)._execute_undo(rec.record_id, invoke=fs.invoke)
    assert out["ok"] is True
    assert fs.files["/a"] == "OLD"               # prior content restored
    assert j.get(rec.record_id).status == STATUS_UNDONE


def test_restore_verify_mismatch_refuses(tmp_path, monkeypatch):
    # FIX-4: a write that does not round-trip faithfully (lossy) must be caught --
    # _execute_undo re-reads and refuses to claim success, marking UNDO_FAILED.
    _on(monkeypatch)
    j = _journal(tmp_path)
    fs = FakeFS(files={"/a": "NEW"}, lossy=True)
    rec = j.record_action(tool="write", args={"path": "/a", "content": "NEW"},
                          read_fn=lambda p: "OLD")
    out = _coord(j)._execute_undo(rec.record_id, invoke=fs.invoke)
    assert out["ok"] is False
    assert "mismatch" in out["detail"]
    assert j.get(rec.record_id).status == STATUS_UNDO_FAILED


# --- remove (exec inverse) ------------------------------------------------- #
def test_remove_new_file_success(tmp_path, monkeypatch):
    _on(monkeypatch)
    j = _journal(tmp_path)
    fs = FakeFS(files={"/n/has space.txt": "NEW"})
    # journal a write that CREATED a new file (no prior) -> inverse removes it
    rec = j.record_action(tool="write", args={"path": "/n/has space.txt", "content": "NEW"},
                          read_fn=lambda p: None)
    out = _coord(j)._execute_undo(rec.record_id, invoke=fs.invoke)
    assert out["ok"] is True
    assert "/n/has space.txt" not in fs.files     # newly-created file removed
    assert j.get(rec.record_id).status == STATUS_UNDONE


def test_remove_reported_ok_but_file_remains_is_failure(tmp_path, monkeypatch):
    # Review fix #2 (FIX-4b): a rm inverse that OpenClaw reports ok=True but that
    # did NOT actually delete (perm denied/race) must be caught -- _execute_undo
    # re-reads, sees the file present, and refuses success (UNDO_FAILED).
    _on(monkeypatch)
    j = _journal(tmp_path)

    class StubbornFS(FakeFS):
        def invoke(self, tool, args):
            if tool == "exec":
                return {"ok": True, "result": ""}  # claims success, deletes nothing
            return super().invoke(tool, args)

    fs = StubbornFS(files={"/n/new.txt": "NEW"})
    rec = j.record_action(tool="write", args={"path": "/n/new.txt", "content": "NEW"},
                          read_fn=lambda p: None)  # new file -> rm inverse
    out = _coord(j)._execute_undo(rec.record_id, invoke=fs.invoke)
    assert out["ok"] is False
    assert "still present" in out["detail"]
    assert j.get(rec.record_id).status == STATUS_UNDO_FAILED


def test_inverse_invoke_raises_marks_failed(tmp_path, monkeypatch):
    _on(monkeypatch)
    j = _journal(tmp_path)
    rec = j.record_action(tool="write", args={"path": "/a", "content": "NEW"},
                          read_fn=lambda p: "OLD")

    def boom(tool, args):
        raise RuntimeError("openclaw down")

    out = _coord(j)._execute_undo(rec.record_id, invoke=boom)
    assert out["ok"] is False and out["reason"] == "inverse_error"
    assert j.get(rec.record_id).status == STATUS_UNDO_FAILED


def test_inverse_not_ok_marks_failed(tmp_path, monkeypatch):
    _on(monkeypatch)
    j = _journal(tmp_path)
    rec = j.record_action(tool="write", args={"path": "/a", "content": "NEW"},
                          read_fn=lambda p: "OLD")
    out = _coord(j)._execute_undo(rec.record_id, invoke=lambda t, a: {"ok": False})
    assert out["ok"] is False and out["reason"] == "inverse_failed"
    assert j.get(rec.record_id).status == STATUS_UNDO_FAILED
