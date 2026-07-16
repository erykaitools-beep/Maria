"""Effector undo foundation (brick 1): honest reversibility + inverse journal.

LIBRARY/observe-only -- no OpenClaw is invoked. Pins the honest core: irreversible
tools are flagged irreversible (never faked as undoable), write is reversible only
with a captured pre-state, and the journal is append-only with last-write-wins.
"""

from pathlib import Path

import pytest

from agent_core.action_safety.safety_model import Reversibility
from agent_core.effector import undo_journal as uj
from agent_core.effector.undo_journal import (
    EffectorUndoJournal,
    build_inverse,
    capture_pre_state,
    classify_reversibility,
    format_undo_list,
    format_undo_preview,
)


# --- classify_reversibility -------------------------------------------------

@pytest.mark.parametrize("tool,expected", [
    ("read", Reversibility.REVERSIBLE),
    ("web_fetch", Reversibility.REVERSIBLE),
    ("web_search", Reversibility.REVERSIBLE),
    ("write", Reversibility.REVERSIBLE),
    ("cron", Reversibility.PARTIALLY_REVERSIBLE),
    ("exec", Reversibility.IRREVERSIBLE),
    ("message", Reversibility.IRREVERSIBLE),
    ("totally_unknown_tool", Reversibility.IRREVERSIBLE),  # safe default
    ("EXEC", Reversibility.IRREVERSIBLE),                   # case-insensitive
])
def test_classify_reversibility(tool, expected):
    assert classify_reversibility(tool) == expected


# --- capture_pre_state ------------------------------------------------------

def test_capture_write_existing_file():
    pre = capture_pre_state("write", {"path": "/x/a.txt"},
                            read_fn=lambda p: "OLD CONTENT")
    assert pre["captured"] and pre["existed"] and pre["content"] == "OLD CONTENT"


def test_capture_write_absent_file():
    pre = capture_pre_state("write", {"path": "/x/new.txt"}, read_fn=lambda p: None)
    assert pre["captured"] and pre["existed"] is False


def test_capture_write_without_read_fn_is_uncaptured():
    pre = capture_pre_state("write", {"path": "/x/a.txt"})
    assert pre["captured"] is False


def test_capture_non_write_is_empty():
    assert capture_pre_state("exec", {"command": "ls"}) == {}


def test_capture_read_fn_error_does_not_crash():
    def boom(p):
        raise IOError("nope")
    pre = capture_pre_state("write", {"path": "/x/a.txt"}, read_fn=boom)
    assert pre["captured"] is False


# --- build_inverse ----------------------------------------------------------

def test_inverse_read_is_noop():
    assert build_inverse("read", {"path": "/x"})["kind"] == "noop"


def test_inverse_write_existing_restores_content():
    pre = {"captured": True, "existed": True, "content": "OLD"}
    inv = build_inverse("write", {"path": "/x/a.txt", "content": "NEW"}, pre)
    assert inv["kind"] == "invoke" and inv["tool"] == "write"
    assert inv["args"]["content"] == "OLD"          # restores the prior content


def test_inverse_write_new_file_removes_it_safely():
    pre = {"captured": True, "existed": False}
    inv = build_inverse("write", {"path": "/x/has space.txt"}, pre)
    assert inv["kind"] == "invoke" and inv["tool"] == "exec"
    # FIX-2: the path travels as a SINGLE argv element (the executor must not
    # re-split it on whitespace), AND the legacy command stays shell-quoted.
    assert inv["args"]["argv"] == ["rm", "--", "/x/has space.txt"]
    assert "'/x/has space.txt'" in inv["args"]["command"]


def test_inverse_write_without_capture_is_unknown():
    inv = build_inverse("write", {"path": "/x/a.txt"}, {"captured": False})
    assert inv["kind"] == "unknown"


@pytest.mark.parametrize("tool", ["exec", "message"])
def test_inverse_irreversible(tool):
    inv = build_inverse(tool, {})
    assert inv["kind"] == "irreversible" and inv["reason"]


def test_inverse_cron_add_is_partial():
    assert build_inverse("cron", {"action": "add"})["kind"] == "partial"


def test_inverse_unknown_tool_irreversible():
    assert build_inverse("frobnicate", {})["kind"] == "irreversible"


# --- EffectorUndoJournal ----------------------------------------------------

@pytest.fixture
def journal(tmp_path):
    return EffectorUndoJournal(path=tmp_path / "undo.jsonl")


def test_record_reversible_write(journal):
    rec = journal.record_action(tool="write", args={"path": "/x/a.txt", "content": "n"},
                                read_fn=lambda p: "old", now=1.0)
    assert rec.status == uj.STATUS_RECORDED
    assert rec.reversibility == Reversibility.REVERSIBLE.value
    assert rec.inverse["kind"] == "invoke"
    assert journal.get(rec.record_id).record_id == rec.record_id


def test_record_irreversible_exec_is_flagged_not_faked(journal):
    rec = journal.record_action(tool="exec", args={"command": "rm -rf /tmp/x"}, now=2.0)
    assert rec.status == uj.STATUS_IRREVERSIBLE
    assert rec.reversibility == Reversibility.IRREVERSIBLE.value
    assert rec.inverse["kind"] == "irreversible"      # never pretends to undo


def test_record_write_uncaptured_is_honestly_irreversible(journal):
    # FIX-3 honesty: a write whose pre-state could not be captured (read raised)
    # has NO safe inverse (kind 'unknown'). The record must NOT advertise itself as
    # auto-reversible -- otherwise /undo_list/preview mislead and a later executor
    # is handed an un-runnable inverse.
    def boom(_):
        raise RuntimeError("read failed")
    rec = journal.record_action(tool="write", args={"path": "/x/a.txt", "content": "n"},
                                read_fn=boom, now=5.0)
    assert rec.inverse["kind"] == "unknown"
    assert rec.status == uj.STATUS_IRREVERSIBLE
    assert rec.reversibility == Reversibility.IRREVERSIBLE.value


def test_mark_action_failed_reconciles_record(journal):
    rec = journal.record_action(tool="write", args={"path": "/x/a.txt", "content": "n"},
                                read_fn=lambda p: "old", now=6.0)
    assert rec.status == uj.STATUS_RECORDED
    journal.mark_action_failed(rec.record_id, detail="action boom", now=7.0)
    assert journal.get(rec.record_id).status == uj.STATUS_ACTION_FAILED


def test_mark_action_failed_unknown_id_is_noop(journal):
    journal.mark_action_failed("eundo-nope")  # must not raise
    assert journal.list_recent() == []


def test_journal_append_only_and_last_write_wins(journal):
    rec = journal.record_action(tool="write", args={"path": "/x/a.txt"},
                                read_fn=lambda p: None, now=3.0)
    journal.mark_undone(rec.record_id, ok=True, detail="restored", now=4.0)
    fresh = journal.get(rec.record_id)
    assert fresh.status == uj.STATUS_UNDONE
    assert fresh.metadata["undo_detail"] == "restored"
    # both the original and the update are physically present (append-only)
    lines = [l for l in journal._path.read_text().splitlines() if l.strip()]
    assert len(lines) == 2


def test_list_recent_dedupes_by_id(journal):
    r1 = journal.record_action(tool="read", args={"path": "/a"}, now=1.0)
    r2 = journal.record_action(tool="message", args={"content": "hi"}, now=2.0)
    journal.mark_undone(r1.record_id, ok=False, detail="x", now=3.0)
    recent = journal.list_recent()
    ids = [r.record_id for r in recent]
    assert ids.count(r1.record_id) == 1 and r2.record_id in ids


def test_mark_undone_unknown_id_is_noop(journal):
    journal.mark_undone("eundo-doesnotexist", ok=True)  # must not raise
    assert journal.list_recent() == []


# --- operator-facing formatting --------------------------------------------

def test_format_undo_list_empty():
    assert "pusty" in format_undo_list([]).lower()


def test_format_undo_list_shows_each_record(journal):
    journal.record_action(tool="write", args={"path": "/a"}, read_fn=lambda p: "x", now=1.0)
    journal.record_action(tool="exec", args={"command": "ls"}, now=2.0)
    out = format_undo_list(journal.list_recent())
    assert "write" in out and "exec" in out and "/undo_preview" in out


def test_format_preview_unknown_record():
    assert "Nie znam" in format_undo_preview(None)


def test_format_preview_invoke_shows_plan_and_defers_execution(journal):
    rec = journal.record_action(tool="write", args={"path": "/a.txt", "content": "n"},
                                read_fn=lambda p: "OLD", now=1.0)
    out = format_undo_preview(journal.get(rec.record_id))
    assert "narzedzie=write" in out and "RAZEM" in out      # plan shown, exec deferred


def test_format_preview_irreversible_is_honest(journal):
    rec = journal.record_action(tool="exec", args={"command": "rm x"}, now=1.0)
    out = format_undo_preview(journal.get(rec.record_id))
    assert "NIE da sie" in out
