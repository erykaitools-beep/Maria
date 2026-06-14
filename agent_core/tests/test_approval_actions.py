"""Tests for the approval action dispatcher (maria_ui/approval_actions.py).

Real stores only -- the whole point of layer 2 is that the write goes through a
genuine store, so a mock here would test nothing. Each test drives the same
store the live endpoint uses and asserts the side effect actually happened
(file written, task closed, bulletin resolved).
"""

import pytest

from maria_ui.approval_actions import apply_approval_action
from agent_core.hands.outbox import OutboxProposalStore, STATUS_REJECTED
from agent_core.conductor.conductor import Conductor
from agent_core.conductor.task_queue import TaskQueue
from agent_core.conductor.task_model import create_task
from agent_core.bulletin import BulletinStore, EntryType


# --- builders ---

def _outbox(tmp_path):
    return OutboxProposalStore(
        path=tmp_path / "outbox_proposals.jsonl", base_dir=str(tmp_path))


def _conductor(tmp_path):
    return Conductor(queue=TaskQueue(path=tmp_path / "maria_task_queue.jsonl"))


def _bulletin(tmp_path):
    return BulletinStore(path=tmp_path / "cognitive_bulletin.jsonl")


# --- notes ---

class TestNote:
    def test_approve_writes_and_clears_pending(self, tmp_path):
        outbox = _outbox(tmp_path)
        rec = outbox.propose("status.md", "tresc notatki", reason="status")
        res = apply_approval_action(
            outbox=outbox, conductor=None, bulletin=None,
            kind="note", item_id=rec["id"], action="approve")
        assert res["ok"] is True
        assert "Zapisano" in res["message"]
        assert outbox.list_pending() == []  # no longer pending

    def test_reject_marks_rejected(self, tmp_path):
        outbox = _outbox(tmp_path)
        rec = outbox.propose("n.md", "x", reason="y")
        res = apply_approval_action(
            outbox=outbox, conductor=None, bulletin=None,
            kind="note", item_id=rec["id"], action="reject")
        assert res["ok"] is True
        assert outbox.list_pending() == []
        assert outbox.get(rec["id"])["status"] == STATUS_REJECTED

    def test_approve_unknown_id_fails_cleanly(self, tmp_path):
        res = apply_approval_action(
            outbox=_outbox(tmp_path), conductor=None, bulletin=None,
            kind="note", item_id="obx-nope", action="approve")
        assert res["ok"] is False

    def test_no_store_degrades(self):
        res = apply_approval_action(
            outbox=None, conductor=None, bulletin=None,
            kind="note", item_id="obx-1", action="approve")
        assert res["ok"] is False
        assert "niedostepny" in res["message"]


# --- repairs ---

class TestRepair:
    def _seed(self, tmp_path):
        conductor = _conductor(tmp_path)
        bulletin = _bulletin(tmp_path)
        t = create_task(project="maria", phase="self_repair",
                        title="napraw model", description="x")
        conductor.add_task(t)
        bulletin.create_and_post(
            entry_type=EntryType.WAITING_HUMAN, topic="self-repair",
            reason_code="repair", summary="model down", requested_by="monitor",
            metadata={"task_id": t.task_id})
        return conductor, bulletin, t.task_id

    def test_approve_closes_task_and_bulletin(self, tmp_path):
        conductor, bulletin, tid = self._seed(tmp_path)
        res = apply_approval_action(
            outbox=None, conductor=conductor, bulletin=bulletin,
            kind="repair", item_id=tid, action="approve")
        assert res["ok"] is True
        # ADR-031: closed (DONE), not dispatched -> no longer PENDING
        assert tid not in {t.task_id for t in conductor.get_pending_repair_tasks()}
        # linked bulletin resolved -> no open WAITING_HUMAN
        assert bulletin.get_by_type(EntryType.WAITING_HUMAN) == []

    def test_approve_unknown_id_fails(self, tmp_path):
        conductor, bulletin, _ = self._seed(tmp_path)
        res = apply_approval_action(
            outbox=None, conductor=conductor, bulletin=bulletin,
            kind="repair", item_id="cdt-nope", action="approve")
        assert res["ok"] is False

    def test_reject_not_supported_for_repair(self, tmp_path):
        conductor, bulletin, tid = self._seed(tmp_path)
        res = apply_approval_action(
            outbox=None, conductor=conductor, bulletin=bulletin,
            kind="repair", item_id=tid, action="reject")
        assert res["ok"] is False
        # task stays PENDING -- nothing was closed
        assert tid in {t.task_id for t in conductor.get_pending_repair_tasks()}


# --- reviews ---

class TestReview:
    def test_approve_resolves_entry(self, tmp_path):
        bulletin = _bulletin(tmp_path)
        entry = bulletin.create_and_post(
            entry_type=EntryType.WAITING_HUMAN, topic="decyzja",
            reason_code="r", summary="s", requested_by="u")
        res = apply_approval_action(
            outbox=None, conductor=None, bulletin=bulletin,
            kind="review", item_id=entry.entry_id, action="approve")
        assert res["ok"] is True
        assert bulletin.get_by_type(EntryType.WAITING_HUMAN) == []

    def test_reject_also_resolves(self, tmp_path):
        bulletin = _bulletin(tmp_path)
        entry = bulletin.create_and_post(
            entry_type=EntryType.WAITING_HUMAN, topic="d2",
            reason_code="r", summary="s", requested_by="u")
        res = apply_approval_action(
            outbox=None, conductor=None, bulletin=bulletin,
            kind="review", item_id=entry.entry_id, action="reject")
        assert res["ok"] is True

    def test_unknown_entry_fails(self, tmp_path):
        res = apply_approval_action(
            outbox=None, conductor=None, bulletin=_bulletin(tmp_path),
            kind="review", item_id="cbb-nope", action="approve")
        assert res["ok"] is False


# --- guards ---

class TestGuards:
    def test_unknown_kind(self, tmp_path):
        res = apply_approval_action(
            outbox=None, conductor=None, bulletin=None,
            kind="weird", item_id="x", action="approve")
        assert res["ok"] is False
        assert "Nieznany rodzaj" in res["message"]

    def test_empty_id(self):
        res = apply_approval_action(
            outbox=None, conductor=None, bulletin=None,
            kind="note", item_id="  ", action="approve")
        assert res["ok"] is False
        assert "Brak id" in res["message"]
