"""Effector undo foundation (brick 2): EffectorCoordinator journals the inverse
BEFORE invoking OpenClaw, flag-gated + observe-only (never blocks the action).

Pins: with the flag on, a `write` is journaled with a restore-inverse capturing
the prior content; an `exec` is journaled IRREVERSIBLE; with the flag off nothing
is journaled and no extra read is spent; a preflight failure journals nothing; a
journal error never breaks the action.
"""

from unittest.mock import MagicMock, patch

from agent_core.effector.coordinator import EffectorCoordinator, EffectorTask, TaskStatus
from agent_core.effector.openclaw_client import OpenClawClient
from agent_core.effector.undo_journal import (
    EffectorUndoJournal, STATUS_IRREVERSIBLE, STATUS_RECORDED, STATUS_ACTION_FAILED,
)
from agent_core.tests.spec_helpers import specced


def _client(results):
    client = specced(OpenClawClient)
    queue = list(results)

    def _invoke(tool_name, args):
        return queue.pop(0) if queue else {"ok": False, "error": "drained"}

    client.invoke_tool = MagicMock(side_effect=_invoke)
    return client


def _preflight_ok():
    return patch.multiple(
        "agent_core.effector.coordinator",
        openclaw_gateway_alive=MagicMock(return_value=True),
        ollama_alive=MagicMock(return_value=True),
        model_loaded=MagicMock(return_value=True),
        warm_ollama_model=MagicMock(return_value=True),
    )


def test_write_is_journaled_with_restore_inverse(tmp_path, monkeypatch):
    monkeypatch.setenv("EFFECTOR_UNDO_JOURNAL_ENABLED", "1")
    journal = EffectorUndoJournal(path=tmp_path / "undo.jsonl")
    # queue: [0] pre-state read -> prior content, [1] the write itself
    client = _client([{"ok": True, "result": "OLD CONTENT"}, {"ok": True, "result": "ok"}])
    coord = EffectorCoordinator(openclaw_client=client, undo_journal=journal)
    with _preflight_ok():
        out = coord.execute_task(EffectorTask(tool_name="write",
                                              tool_args={"path": "/n/a.txt", "content": "NEW"}))
    assert out.status == TaskStatus.COMPLETED
    recs = journal.list_recent()
    assert len(recs) == 1 and recs[0].tool == "write"
    assert recs[0].inverse["kind"] == "invoke"
    assert recs[0].inverse["args"]["content"] == "OLD CONTENT"   # restores prior


def test_exec_is_journaled_irreversible(tmp_path, monkeypatch):
    monkeypatch.setenv("EFFECTOR_UNDO_JOURNAL_ENABLED", "1")
    journal = EffectorUndoJournal(path=tmp_path / "undo.jsonl")
    client = _client([{"ok": True, "result": "done"}])
    coord = EffectorCoordinator(openclaw_client=client, undo_journal=journal)
    with _preflight_ok():
        coord.execute_task(EffectorTask(tool_name="exec", tool_args={"command": "ls"}))
    recs = journal.list_recent()
    assert len(recs) == 1 and recs[0].status == STATUS_IRREVERSIBLE
    # exec is not a write -> no extra pre-state read was spent
    assert client.invoke_tool.call_count == 1


def test_flag_off_journals_nothing_and_spends_no_extra_read(tmp_path, monkeypatch):
    monkeypatch.delenv("EFFECTOR_UNDO_JOURNAL_ENABLED", raising=False)
    journal = EffectorUndoJournal(path=tmp_path / "undo.jsonl")
    client = _client([{"ok": True, "result": "ok"}])
    coord = EffectorCoordinator(openclaw_client=client, undo_journal=journal)
    with _preflight_ok():
        coord.execute_task(EffectorTask(tool_name="write",
                                        tool_args={"path": "/n/a.txt", "content": "NEW"}))
    assert journal.list_recent() == []
    assert client.invoke_tool.call_count == 1     # only the write, no pre-state read


def test_preflight_failure_journals_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("EFFECTOR_UNDO_JOURNAL_ENABLED", "1")
    journal = EffectorUndoJournal(path=tmp_path / "undo.jsonl")
    client = _client([{"ok": True}])
    coord = EffectorCoordinator(openclaw_client=client, undo_journal=journal)
    with patch.multiple("agent_core.effector.coordinator",
                        openclaw_gateway_alive=MagicMock(return_value=False),
                        ollama_alive=MagicMock(return_value=True)):
        out = coord.execute_task(EffectorTask(tool_name="write",
                                              tool_args={"path": "/n/a.txt", "content": "x"}))
    assert out.status == TaskStatus.PREFLIGHT_FAILED
    assert journal.list_recent() == []            # action never ran -> nothing journaled


def test_journal_error_never_breaks_the_action(tmp_path, monkeypatch):
    monkeypatch.setenv("EFFECTOR_UNDO_JOURNAL_ENABLED", "1")
    broken = MagicMock()
    broken.record_action.side_effect = RuntimeError("journal boom")
    client = _client([{"ok": True, "result": "ok"}])
    coord = EffectorCoordinator(openclaw_client=client, undo_journal=broken)
    with _preflight_ok():
        out = coord.execute_task(EffectorTask(tool_name="exec", tool_args={"command": "ls"}))
    assert out.status == TaskStatus.COMPLETED      # journal failure is swallowed


def _client_read_raises(exc, then):
    """Client whose first (pre-state read) invoke raises ``exc``; later calls
    return values popped from ``then``."""
    client = specced(OpenClawClient)
    calls = {"n": 0}
    queue = list(then)

    def _invoke(tool_name, args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise exc
        return queue.pop(0) if queue else {"ok": True, "result": "ok"}

    client.invoke_tool = MagicMock(side_effect=_invoke)
    return client


def test_read_error_does_NOT_build_a_destructive_remove(tmp_path, monkeypatch):
    # FIX-1 (data-loss guard): a GENERIC read failure on the pre-state read must
    # NOT be treated as 'file absent' -> must NOT produce an rm inverse. The record
    # is honestly IRREVERSIBLE (no safe inverse), so undo can never delete a file
    # whose prior content we failed to read.
    monkeypatch.setenv("EFFECTOR_UNDO_JOURNAL_ENABLED", "1")
    journal = EffectorUndoJournal(path=tmp_path / "undo.jsonl")
    client = _client_read_raises(RuntimeError("connection reset"),
                                 then=[{"ok": True, "result": "ok"}])
    coord = EffectorCoordinator(openclaw_client=client, undo_journal=journal)
    with _preflight_ok():
        coord.execute_task(EffectorTask(tool_name="write",
                                        tool_args={"path": "/n/a.txt", "content": "NEW"}))
    rec = journal.list_recent()[0]
    assert rec.status == STATUS_IRREVERSIBLE
    assert rec.inverse["kind"] != "invoke"        # NOT a rm / restore
    assert rec.pre_state.get("captured") is False


def test_command_not_found_is_NOT_treated_as_absent(tmp_path, monkeypatch):
    # Review fix #1: 'command not found' (a missing cat binary / infra error)
    # contains 'not found' but is NOT a missing FILE -> must not build an rm
    # inverse. Only 'no such file'/ENOENT signal absence.
    monkeypatch.setenv("EFFECTOR_UNDO_JOURNAL_ENABLED", "1")
    journal = EffectorUndoJournal(path=tmp_path / "undo.jsonl")
    client = _client_read_raises(
        RuntimeError("Node command failed: sh: cat: command not found"),
        then=[{"ok": True, "result": "ok"}])
    coord = EffectorCoordinator(openclaw_client=client, undo_journal=journal)
    with _preflight_ok():
        coord.execute_task(EffectorTask(tool_name="write",
                                        tool_args={"path": "/n/a.txt", "content": "NEW"}))
    rec = journal.list_recent()[0]
    assert rec.status == STATUS_IRREVERSIBLE
    assert rec.inverse["kind"] != "invoke"        # NOT a destructive rm
    assert rec.pre_state.get("captured") is False


def test_confirmed_absent_builds_remove_inverse(tmp_path, monkeypatch):
    # FIX-1 other branch: a read error that clearly means 'No such file' IS treated
    # as absent -> the inverse removes the newly-created file (kind invoke).
    monkeypatch.setenv("EFFECTOR_UNDO_JOURNAL_ENABLED", "1")
    journal = EffectorUndoJournal(path=tmp_path / "undo.jsonl")
    client = _client_read_raises(
        RuntimeError("Node command failed: cat: /n/new.txt: No such file or directory"),
        then=[{"ok": True, "result": "ok"}])
    coord = EffectorCoordinator(openclaw_client=client, undo_journal=journal)
    with _preflight_ok():
        coord.execute_task(EffectorTask(tool_name="write",
                                        tool_args={"path": "/n/new.txt", "content": "NEW"}))
    rec = journal.list_recent()[0]
    assert rec.status == STATUS_RECORDED
    assert rec.inverse["kind"] == "invoke"
    assert rec.inverse["tool"] == "exec"          # remove the new file


def test_failed_action_is_reconciled_to_action_failed(tmp_path, monkeypatch):
    # Reconcile: the inverse is journaled BEFORE execution; if the action then
    # fails, the stale 'recorded' inverse must be flipped to ACTION_FAILED so undo
    # is never offered for something that never happened.
    monkeypatch.setenv("EFFECTOR_UNDO_JOURNAL_ENABLED", "1")
    journal = EffectorUndoJournal(path=tmp_path / "undo.jsonl")
    # read (pre-state) ok, then the single write attempt fails.
    client = _client([{"ok": True, "result": "OLD"}, {"ok": False, "error": "boom"}])
    coord = EffectorCoordinator(openclaw_client=client, undo_journal=journal,
                                max_attempts=1, backoff_seq=[0.0])
    with _preflight_ok():
        out = coord.execute_task(EffectorTask(tool_name="write",
                                              tool_args={"path": "/n/a.txt", "content": "NEW"}))
    assert out.status == TaskStatus.FAILED
    assert journal.get(journal.list_recent()[0].record_id).status == STATUS_ACTION_FAILED
