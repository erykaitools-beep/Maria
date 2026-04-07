"""
Tests for TaskStore - persistent task tracking for Claude/Codex CLI tasks.

Covers: create, lifecycle transitions, recovery, /tasks command formatting.
"""

import json
import time
from pathlib import Path

import pytest

from agent_core.llm.task_store import TaskStore, TaskStatus


@pytest.fixture
def tmp_store(tmp_path):
    """TaskStore with temp file."""
    return TaskStore(path=tmp_path / "tasks.jsonl")


class TestTaskStoreLifecycle:
    """Core lifecycle: PENDING -> RUNNING -> terminal state."""

    def test_create_task_returns_id(self, tmp_store):
        tid = tmp_store.create_task("test task", backend="claude", source="test")
        assert isinstance(tid, str)
        assert len(tid) == 12

    def test_create_persists_to_file(self, tmp_store):
        tid = tmp_store.create_task("hello", backend="codex", source="test")
        task = tmp_store.get_task(tid)
        assert task is not None
        assert task["status"] == "PENDING"
        assert task["backend"] == "codex"
        assert task["task_text"] == "hello"

    def test_mark_running(self, tmp_store):
        tid = tmp_store.create_task("run me", backend="claude", source="test")
        tmp_store.mark_running(tid)
        task = tmp_store.get_task(tid)
        assert task["status"] == "RUNNING"
        assert task["started_at"] is not None

    def test_mark_completed(self, tmp_store):
        tid = tmp_store.create_task("finish me", backend="claude", source="test")
        tmp_store.mark_running(tid)
        tmp_store.mark_completed(tid, "result summary here")
        task = tmp_store.get_task(tid)
        assert task["status"] == "COMPLETED"
        assert task["finished_at"] is not None
        assert task["duration_ms"] is not None
        assert task["result_summary"] == "result summary here"

    def test_mark_failed(self, tmp_store):
        tid = tmp_store.create_task("fail me", backend="codex", source="test")
        tmp_store.mark_running(tid)
        tmp_store.mark_failed(tid, "connection error")
        task = tmp_store.get_task(tid)
        assert task["status"] == "FAILED"
        assert "connection error" in task["error"]

    def test_mark_timeout(self, tmp_store):
        tid = tmp_store.create_task("slow task", backend="claude", source="test")
        tmp_store.mark_running(tid)
        tmp_store.mark_timeout(tid, 300)
        task = tmp_store.get_task(tid)
        assert task["status"] == "TIMEOUT"
        assert "300" in task["error"]

    def test_completed_truncates_result(self, tmp_store):
        tid = tmp_store.create_task("big result", backend="claude", source="test")
        tmp_store.mark_running(tid)
        tmp_store.mark_completed(tid, "x" * 1000)
        task = tmp_store.get_task(tid)
        assert len(task["result_summary"]) == 500

    def test_failed_truncates_error(self, tmp_store):
        tid = tmp_store.create_task("big error", backend="claude", source="test")
        tmp_store.mark_running(tid)
        tmp_store.mark_failed(tid, "e" * 500)
        task = tmp_store.get_task(tid)
        assert len(task["error"]) == 300


class TestTaskStoreRecovery:
    """Recovery of interrupted tasks on restart."""

    def test_recover_marks_pending_as_interrupted(self, tmp_store):
        tid = tmp_store.create_task("pending task", backend="claude", source="test")
        interrupted = tmp_store.recover_interrupted()
        assert len(interrupted) == 1
        assert interrupted[0]["task_id"] == tid
        assert interrupted[0]["status"] == "INTERRUPTED"

    def test_recover_marks_running_as_interrupted(self, tmp_store):
        tid = tmp_store.create_task("running task", backend="claude", source="test")
        tmp_store.mark_running(tid)
        interrupted = tmp_store.recover_interrupted()
        assert len(interrupted) == 1
        assert interrupted[0]["status"] == "INTERRUPTED"

    def test_recover_skips_completed(self, tmp_store):
        tid = tmp_store.create_task("done task", backend="claude", source="test")
        tmp_store.mark_running(tid)
        tmp_store.mark_completed(tid, "ok")
        interrupted = tmp_store.recover_interrupted()
        assert len(interrupted) == 0

    def test_recover_skips_already_failed(self, tmp_store):
        tid = tmp_store.create_task("failed task", backend="claude", source="test")
        tmp_store.mark_running(tid)
        tmp_store.mark_failed(tid, "err")
        interrupted = tmp_store.recover_interrupted()
        assert len(interrupted) == 0

    def test_recover_multiple(self, tmp_store):
        t1 = tmp_store.create_task("task1", backend="claude", source="test")
        t2 = tmp_store.create_task("task2", backend="codex", source="test")
        tmp_store.mark_running(t1)
        # t2 stays PENDING
        t3 = tmp_store.create_task("task3", backend="claude", source="test")
        tmp_store.mark_running(t3)
        tmp_store.mark_completed(t3, "done")  # this one is safe
        interrupted = tmp_store.recover_interrupted()
        assert len(interrupted) == 2
        ids = {t["task_id"] for t in interrupted}
        assert t1 in ids
        assert t2 in ids

    def test_recover_idempotent(self, tmp_store):
        tmp_store.create_task("task", backend="claude", source="test")
        first = tmp_store.recover_interrupted()
        assert len(first) == 1
        second = tmp_store.recover_interrupted()
        assert len(second) == 0  # already marked


class TestTaskStoreQuery:
    """Query methods."""

    def test_get_recent_empty(self, tmp_store):
        assert tmp_store.get_recent() == []

    def test_get_recent_returns_latest(self, tmp_store):
        for i in range(7):
            tmp_store.create_task(f"task {i}", backend="claude", source="test")
        recent = tmp_store.get_recent(3)
        assert len(recent) == 3
        assert "task 6" in recent[-1]["task_text"]

    def test_get_task_not_found(self, tmp_store):
        assert tmp_store.get_task("nonexistent") is None

    def test_metadata_stored(self, tmp_store):
        tid = tmp_store.create_task(
            "meta task", backend="claude", source="test",
            metadata={"module": "critic", "extra": "data"},
        )
        task = tmp_store.get_task(tid)
        assert task["metadata"]["module"] == "critic"


class TestTaskStoreFileHandling:
    """Edge cases for JSONL persistence."""

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        store = TaskStore(path=path)
        assert store.get_recent() == []

    def test_corrupted_line_skipped(self, tmp_path):
        path = tmp_path / "corrupt.jsonl"
        path.write_text('{"task_id":"aaa","status":"COMPLETED"}\nNOT JSON\n')
        store = TaskStore(path=path)
        tasks = store.get_recent()
        assert len(tasks) == 1

    def test_concurrent_creates(self, tmp_store):
        """Multiple creates don't corrupt the file."""
        ids = []
        for i in range(20):
            tid = tmp_store.create_task(f"task {i}", backend="claude", source="test")
            ids.append(tid)
        assert len(set(ids)) == 20
        assert len(tmp_store.get_recent(100)) == 20


class TestStartupCooldown:
    """Startup notification cooldown."""

    def test_cooldown_is_6h(self):
        from agent_core.telegram.notifier import _STARTUP_COOLDOWN_SEC
        assert _STARTUP_COOLDOWN_SEC == 21600
