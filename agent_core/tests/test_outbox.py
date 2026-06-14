"""Tests for the Rung 2 outbox (TIER 2 hands): compose + propose/approve gate.

All I/O uses tmp_path (live daemon races meta_data). The key invariant under
test: NOTHING is written until approve(); the write reuses the guarded engine
with no_overwrite (no undo -> never clobber).
"""

from pathlib import Path

from agent_core.hands.outbox import (
    OutboxProposalStore,
    STATUS_PENDING,
    STATUS_WRITTEN,
    STATUS_FAILED,
    STATUS_REJECTED,
    compose_status_note,
    is_enabled,
)
from agent_core.hands.sandbox_writer import MAX_WRITE_BYTES, default_outbox_root


def _store(tmp_path):
    return OutboxProposalStore(path=tmp_path / "proposals.jsonl", base_dir=str(tmp_path))


def _outbox_dir(tmp_path):
    return Path(default_outbox_root(str(tmp_path)))


# -- composer --

def test_compose_status_note_is_deterministic():
    fields = {"ts_label": "2026-06-07", "mode": "ACTIVE", "health": 0.9,
              "active_goals": 5, "uptime_days": 205}
    a = compose_status_note(fields)
    b = compose_status_note(fields)
    assert a == b
    assert "status note" in a
    assert "ACTIVE" in a and "0.9" in a and "5" in a
    assert a.endswith("\n")


def test_compose_status_note_optional_note():
    assert "note:" not in compose_status_note({"mode": "X"})
    assert "note:         hi" in compose_status_note({"mode": "X", "note": "hi"})


def test_compose_status_note_rich_fields():
    """The richer note renders identity + vitals + goals + learning + cognition."""
    fields = {
        "ts_label": "2026-06-08 17:23", "uptime_days": 206, "tick": 78904,
        "mode": "sleep", "health": 0.95, "alerts": 0,
        "active_goals": 4, "goals_breakdown": "3 learning, 1 meta",
        "proposed_goals": 2, "knowledge": "466/467 complete",
        "last_exam": "83% (closed-book, independent)",
        "planner": "7 cycles, 2 plans",
        "capabilities": "15 (5 free, 9 guarded, 1 restricted)",
        "note": "autonomous",
    }
    out = compose_status_note(fields)
    assert "tick:         78904" in out
    assert "alerts:       0" in out  # 0 is meaningful -> shown, not dropped
    assert "active goals: 4 (3 learning, 1 meta)" in out
    assert "proposed:     2" in out
    assert "knowledge:    466/467 complete" in out
    assert "last exam:    83% (closed-book, independent)" in out
    assert "planner:      7 cycles, 2 plans" in out
    assert "capabilities: 15 (5 free, 9 guarded, 1 restricted)" in out
    assert out.endswith("\n")
    # deterministic
    assert out == compose_status_note(fields)


def test_compose_status_note_drops_missing_extras():
    """A subsystem gap drops only its line; core vitals stay. Never breaks."""
    out = compose_status_note(
        {"ts_label": "t", "mode": "sleep", "health": 0.9, "active_goals": 1}
    )
    for absent in ("tick:", "alerts:", "proposed:", "knowledge:",
                   "last exam:", "planner:", "capabilities:"):
        assert absent not in out
    assert "mode:         sleep" in out
    assert "active goals: 1" in out  # no breakdown -> no parens
    assert "(" not in out


# -- propose: NO write, just a pending row --

def test_propose_writes_nothing_to_outbox(tmp_path):
    store = _store(tmp_path)
    rec = store.propose("maria_note_1", "hello world")
    assert rec["status"] == STATUS_PENDING
    assert rec["id"].startswith("obx-")
    assert len(store.list_pending()) == 1
    # crucial: proposing creates NO file on the world
    assert not _outbox_dir(tmp_path).exists() or not any(_outbox_dir(tmp_path).iterdir())


# -- approve: the ONLY write path --

def test_approve_writes_file_guarded(tmp_path):
    store = _store(tmp_path)
    rec = store.propose("maria_note_1", "hello world")

    res = store.approve(rec["id"])

    assert res["ok"] is True
    written = _outbox_dir(tmp_path) / "maria_note_1.txt"
    assert written.read_text() == "hello world"
    assert "maria_outbox" in res["result"]["path"]
    # proposal flips to written; no longer pending
    assert store.get(rec["id"])["status"] == STATUS_WRITTEN
    assert store.list_pending() == []


def test_approve_is_idempotent(tmp_path):
    store = _store(tmp_path)
    rec = store.propose("note", "x")
    assert store.approve(rec["id"])["ok"] is True
    second = store.approve(rec["id"])
    assert second["ok"] is False
    assert "not pending" in second["error"]


def test_approve_unknown_id(tmp_path):
    res = _store(tmp_path).approve("obx-nope")
    assert res["ok"] is False
    assert "no proposal" in res["error"]


def test_approve_respects_size_cap(tmp_path):
    store = _store(tmp_path)
    rec = store.propose("big", "a" * (MAX_WRITE_BYTES + 1))
    res = store.approve(rec["id"])
    assert res["ok"] is False
    assert store.get(rec["id"])["status"] == STATUS_FAILED
    assert not (_outbox_dir(tmp_path) / "big.txt").exists()


def test_approve_never_overwrites(tmp_path):
    # Two proposals, same filename: first writes, second must NOT clobber it.
    store = _store(tmp_path)
    a = store.propose("dup", "first")
    b = store.propose("dup", "second")
    assert store.approve(a["id"])["ok"] is True
    res_b = store.approve(b["id"])
    assert res_b["ok"] is False  # no_overwrite
    assert (_outbox_dir(tmp_path) / "dup.txt").read_text() == "first"  # untouched
    assert store.get(b["id"])["status"] == STATUS_FAILED


def test_is_enabled_off_by_default(monkeypatch):
    monkeypatch.delenv("OUTBOX_WRITE_ENABLED", raising=False)
    assert is_enabled() is False
    monkeypatch.setenv("OUTBOX_WRITE_ENABLED", "1")
    assert is_enabled() is True


def test_seconds_since_last(tmp_path):
    store = _store(tmp_path)
    assert store.seconds_since_last() is None  # empty ledger
    store.propose("n", "x")
    gap = store.seconds_since_last()
    assert gap is not None and gap < 5  # just proposed


def test_get_exact_and_refuses_loose_ids(tmp_path):
    store = _store(tmp_path)
    full = store.propose("a", "x")["id"]           # obx-XXXXXXXX
    suffix = full.split("-")[1]                     # the 8-hex tail
    assert store.get(full)["id"] == full           # exact
    assert store.get(suffix)["id"] == full         # unique 8-hex suffix
    assert store.get("obx-") is None               # constant prefix -> refused
    assert store.get("") is None                   # empty -> refused
    assert store.get("ob") is None                 # too short (<4) -> refused


def test_propose_if_none_pending_dedups(tmp_path):
    store = _store(tmp_path)
    first = store.propose_if_none_pending("a", "x")
    assert first is not None
    second = store.propose_if_none_pending("b", "y")  # one already pending
    assert second is None
    assert len(store.list_pending()) == 1


def test_load_tolerates_corrupt_line(tmp_path):
    store = _store(tmp_path)
    rec = store.propose("good", "x")
    with open(tmp_path / "proposals.jsonl", "a", encoding="utf-8") as f:
        f.write('{"id": "obx-broken", "status":\n')  # torn last write
    # the valid record still loads; the garbage line is skipped, no raise
    assert any(r["id"] == rec["id"] for r in store.list_pending())


def test_no_overwrite_is_atomic_against_existing(tmp_path):
    # O_EXCL path: a pre-existing target is refused, never truncated.
    from agent_core.hands.sandbox_writer import sandbox_write
    (tmp_path / "x.txt").write_text("ORIGINAL")
    r = sandbox_write("x", "NEW", sandbox_root=str(tmp_path), no_overwrite=True)
    assert r["success"] is False
    assert (tmp_path / "x.txt").read_text() == "ORIGINAL"


def test_sanitize_drops_nul_no_raise(tmp_path):
    # A NUL in the name must not propagate ValueError out of the engine.
    from agent_core.hands.sandbox_writer import sandbox_write
    r = sandbox_write("a\x00b", "y", sandbox_root=str(tmp_path))
    assert r["success"] is True
    assert r["path"].endswith(".txt")


def test_reject_marks_and_does_not_write(tmp_path):
    store = _store(tmp_path)
    rec = store.propose("note", "x")
    assert store.reject(rec["id"])["ok"] is True
    assert store.get(rec["id"])["status"] == STATUS_REJECTED
    assert store.list_pending() == []
    assert not (_outbox_dir(tmp_path) / "note.txt").exists()
