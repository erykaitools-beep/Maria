"""Tests for the unified approval inbox aggregator (maria_ui/approval_inbox.py).

Real components only -- each queue is populated through its own store (or raw
jsonl in the store's own format) and read back through build_approval_inbox.
No mocks: a MagicMock would happily swallow a wrong field name and hide the
exact bug this screen exists to surface.
"""

import json
from pathlib import Path

import pytest

from maria_ui.approval_inbox import build_approval_inbox, _preview
from agent_core.conductor.task_queue import TaskQueue
from agent_core.conductor.task_model import create_task
from agent_core.bulletin import BulletinStore, EntryType


# --- fixtures: write each queue in its store's real on-disk format ---

def _write_outbox(meta_dir: Path, records):
    """Append raw proposal records (the store collapses to latest-per-id)."""
    path = meta_dir / "outbox_proposals.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _note(pid, filename, *, status="pending", created_at=100.0,
          reason="", content=""):
    return {
        "id": pid, "created_at": created_at, "filename": filename,
        "content": content, "reason": reason, "status": status,
    }


def _post_repair(meta_dir: Path, *, title, phase="self_repair",
                 project="maria", created_at=100.0, artifacts=None,
                 notes="", done=False):
    queue = TaskQueue(path=meta_dir / "maria_task_queue.jsonl")
    t = create_task(project=project, phase=phase, title=title,
                    description="desc body")
    t.created_at = created_at
    t.notes = notes
    if artifacts:
        t.artifacts = artifacts
    queue.post(t)
    if done:
        from agent_core.conductor.task_model import TaskStatus
        queue.update(t.task_id, status=TaskStatus.DONE)
    return t.task_id


def _bulletin(meta_dir: Path):
    return BulletinStore(path=meta_dir / "cognitive_bulletin.jsonl")


# --- tests ---

class TestEmpty:
    def test_empty_meta_dir(self, tmp_path):
        out = build_approval_inbox(tmp_path)
        assert out == {"items": [],
                       "counts": {"note": 0, "repair": 0, "review": 0,
                                  "total": 0}}


class TestNotes:
    def test_pending_notes_listed(self, tmp_path):
        _write_outbox(tmp_path, [
            _note("obx-1", "status_2026.md", reason="dzienny status"),
            _note("obx-2", "alert.md", content="cos sie dzieje"),
        ])
        out = build_approval_inbox(tmp_path)
        assert out["counts"]["note"] == 2
        note = next(i for i in out["items"] if i["id"] == "obx-1")
        assert note["kind"] == "note"
        assert note["title"] == "status_2026.md"
        assert note["detail"] == "dzienny status"

    def test_written_note_excluded(self, tmp_path):
        # Two transitions for the same id: pending then written. The store
        # keeps the latest (written) -> it must NOT appear in the inbox.
        _write_outbox(tmp_path, [
            _note("obx-9", "old.md", status="pending"),
            _note("obx-9", "old.md", status="written"),
            _note("obx-8", "live.md", status="pending"),
        ])
        out = build_approval_inbox(tmp_path)
        ids = {i["id"] for i in out["items"]}
        assert ids == {"obx-8"}
        assert out["counts"]["note"] == 1

    def test_content_fallback_when_no_reason(self, tmp_path):
        _write_outbox(tmp_path, [_note("obx-3", "n.md", content="tresc tu")])
        out = build_approval_inbox(tmp_path)
        assert out["items"][0]["detail"] == "tresc tu"

    def test_body_preferred_over_reason_and_full_in_extra(self, tmp_path):
        # Production case: a note has BOTH a one-word reason and a real body.
        # The preview must show the BODY (what Maria wants to post), and the
        # FULL untruncated body must ride in extra["content"] so the app can
        # render the whole note on tap. Reason stays available in extra too.
        body = "Maria -- status note\n" + ("szczegoly " * 40)
        _write_outbox(tmp_path, [
            _note("obx-7", "maria_status_x.md", reason="autonomous",
                  content=body),
        ])
        out = build_approval_inbox(tmp_path)
        item = out["items"][0]
        assert item["detail"].startswith("Maria -- status note")
        assert item["detail"] != "autonomous"
        assert item["extra"]["content"] == body  # full, untruncated
        assert item["extra"]["reason"] == "autonomous"


class TestRepairs:
    def test_only_pending_self_repair(self, tmp_path):
        keep = _post_repair(tmp_path, title="napraw model", created_at=200.0,
                            artifacts={"repair_kind": "model_unavailable"})
        _post_repair(tmp_path, title="inny phase", phase="phase_1")  # wrong phase
        _post_repair(tmp_path, title="zrobione", done=True)          # terminal
        out = build_approval_inbox(tmp_path)
        assert out["counts"]["repair"] == 1
        item = next(i for i in out["items"] if i["kind"] == "repair")
        assert item["id"] == keep
        assert item["title"] == "napraw model"
        assert item["extra"]["repair_kind"] == "model_unavailable"

    def test_non_maria_project_excluded(self, tmp_path):
        _post_repair(tmp_path, title="market task", project="market_agent",
                     phase="self_repair")
        out = build_approval_inbox(tmp_path)
        assert out["counts"]["repair"] == 0


class TestReviews:
    def test_waiting_human_listed(self, tmp_path):
        store = _bulletin(tmp_path)
        store.create_and_post(
            entry_type=EntryType.WAITING_HUMAN, topic="koncept-trust",
            reason_code="needs_decision", summary="867/1149 self-graded",
            requested_by="concept_trust_scan", priority=0.8,
        )
        out = build_approval_inbox(tmp_path)
        assert out["counts"]["review"] == 1
        item = next(i for i in out["items"] if i["kind"] == "review")
        assert item["title"] == "koncept-trust"
        assert item["detail"] == "867/1149 self-graded"
        assert item["extra"]["requested_by"] == "concept_trust_scan"

    def test_other_type_excluded(self, tmp_path):
        store = _bulletin(tmp_path)
        store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL, topic="brak materialu",
            reason_code="no_material", summary="x", requested_by="planner",
        )
        out = build_approval_inbox(tmp_path)
        assert out["counts"]["review"] == 0

    def test_resolved_excluded(self, tmp_path):
        store = _bulletin(tmp_path)
        entry = store.create_and_post(
            entry_type=EntryType.WAITING_HUMAN, topic="zamkniete",
            reason_code="x", summary="y", requested_by="z",
        )
        store.resolve(entry.entry_id, reason="done")
        out = build_approval_inbox(tmp_path)
        assert out["counts"]["review"] == 0


class TestMixedAndShape:
    def test_counts_and_required_keys(self, tmp_path):
        _write_outbox(tmp_path, [_note("obx-a", "n.md")])
        _post_repair(tmp_path, title="r")
        _bulletin(tmp_path).create_and_post(
            entry_type=EntryType.WAITING_HUMAN, topic="t", reason_code="r",
            summary="s", requested_by="u",
        )
        out = build_approval_inbox(tmp_path)
        assert out["counts"] == {"note": 1, "repair": 1, "review": 1,
                                 "total": 3}
        for item in out["items"]:
            assert set(item) >= {"kind", "id", "title", "detail",
                                 "created_at", "extra"}

    def test_sorted_newest_first(self, tmp_path):
        _write_outbox(tmp_path, [
            _note("obx-old", "old.md", created_at=100.0),
            _note("obx-new", "new.md", created_at=300.0),
        ])
        _post_repair(tmp_path, title="mid", created_at=200.0)
        out = build_approval_inbox(tmp_path)
        stamps = [i["created_at"] for i in out["items"]]
        assert stamps == sorted(stamps, reverse=True)
        assert out["items"][0]["id"] == "obx-new"

    def test_one_broken_queue_does_not_blank_others(self, tmp_path):
        # A corrupt task queue must not take down notes/reviews.
        (tmp_path / "maria_task_queue.jsonl").write_text(
            "{ this is not json\n", encoding="utf-8")
        _write_outbox(tmp_path, [_note("obx-z", "n.md")])
        out = build_approval_inbox(tmp_path)
        assert out["counts"]["note"] == 1


class TestPreview:
    def test_truncates_long_text(self):
        long = "x" * 500
        got = _preview(long, limit=240)
        assert got.endswith("...")
        assert len(got) <= 243

    def test_short_text_untouched(self):
        assert _preview("  hej  ") == "hej"

    def test_none_safe(self):
        assert _preview(None) == ""
