"""Tests for Faza 4: Digital Hands.

Covers: ExecutionJournal, TaskExecutor, ResultValidator, WebResearcher, FileManager.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_core.hands.execution_journal import ExecutionJournal, JournalEntry
from agent_core.hands.task_executor import TaskExecutor, TaskStep, TaskResult
from agent_core.hands.result_validator import ResultValidator
from agent_core.hands.web_researcher import WebResearcher
from agent_core.hands.file_manager import FileManager


# =============================================================================
# ExecutionJournal
# =============================================================================

class TestJournalEntry:
    def test_to_dict(self):
        entry = JournalEntry(
            entry_id="exec-test123",
            task_description="Test task",
            tool_name="wiki_search",
            tool_args={"query": "python"},
        )
        d = entry.to_dict()
        assert d["entry_id"] == "exec-test123"
        assert d["status"] == "pending"
        assert d["tool_name"] == "wiki_search"

    def test_default_status(self):
        entry = JournalEntry(
            entry_id="x", task_description="x",
            tool_name="x", tool_args={},
        )
        assert entry.status == "pending"


class TestExecutionJournal:
    @pytest.fixture
    def journal(self, tmp_path):
        return ExecutionJournal(path=tmp_path / "journal.jsonl")

    def test_create_entry(self, journal):
        entry = journal.create_entry(
            task_description="Search wiki",
            tool_name="wiki_search",
            tool_args={"query": "AI"},
        )
        assert entry.entry_id.startswith("exec-")
        assert entry.status == "pending"

    def test_lifecycle(self, journal):
        entry = journal.create_entry(
            task_description="Test", tool_name="test", tool_args={},
        )
        journal.mark_running(entry)
        assert entry.status == "running"
        assert entry.started_at is not None

        journal.mark_completed(entry, {"result": "ok"})
        assert entry.status == "completed"
        assert entry.duration_ms > 0

    def test_mark_failed(self, journal):
        entry = journal.create_entry(
            task_description="Test", tool_name="test", tool_args={},
        )
        journal.mark_running(entry)
        journal.mark_failed(entry, "network error")
        assert entry.status == "failed"
        assert entry.error == "network error"

    def test_add_step(self, journal):
        entry = journal.create_entry(
            task_description="Test", tool_name="test", tool_args={},
        )
        journal.add_step(entry, "step1", "ok", {"data": 42})
        assert len(entry.steps) == 1
        assert entry.steps[0]["step"] == "step1"

    def test_get_recent(self, journal):
        for i in range(5):
            journal.create_entry(
                task_description=f"Task {i}", tool_name="t", tool_args={},
            )
        recent = journal.get_recent(3)
        assert len(recent) == 3

    def test_get_by_id(self, journal):
        entry = journal.create_entry(
            task_description="Find me", tool_name="t", tool_args={},
        )
        found = journal.get_by_id(entry.entry_id)
        assert found is entry

    def test_get_by_id_not_found(self, journal):
        assert journal.get_by_id("nonexistent") is None

    def test_get_stats(self, journal):
        e1 = journal.create_entry(task_description="t", tool_name="t", tool_args={})
        journal.mark_running(e1)
        journal.mark_completed(e1, {})

        e2 = journal.create_entry(task_description="t", tool_name="t", tool_args={})
        journal.mark_running(e2)
        journal.mark_failed(e2, "err")

        stats = journal.get_stats()
        assert stats["total"] == 2
        assert stats["completed"] == 1
        assert stats["failed"] == 1
        assert stats["success_rate"] == 0.5

    def test_persistence(self, journal, tmp_path):
        entry = journal.create_entry(
            task_description="Persist test", tool_name="t", tool_args={},
        )
        journal.mark_running(entry)
        journal.mark_completed(entry, {"done": True})

        # Check JSONL file exists
        path = tmp_path / "journal.jsonl"
        assert path.exists()
        data = json.loads(path.read_text().strip())
        assert data["status"] == "completed"

    def test_bounded_memory(self):
        journal = ExecutionJournal(path=Path("/dev/null"))
        for i in range(250):
            journal.create_entry(task_description=f"t{i}", tool_name="t", tool_args={})
        assert len(journal._entries) <= 200


# =============================================================================
# ResultValidator
# =============================================================================

class TestResultValidator:
    def test_success_reported(self):
        v = ResultValidator()
        result = v.validate("generic", {}, {"success": True})
        assert result["valid"] is True

    def test_failure_reported(self):
        v = ResultValidator()
        result = v.validate("generic", {}, {"success": False})
        assert result["valid"] is False

    def test_file_write_exists(self, tmp_path):
        v = ResultValidator()
        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = v.validate("file_write", {"path": str(f)}, {"success": True})
        assert result["valid"] is True

    def test_file_write_missing(self):
        v = ResultValidator()
        result = v.validate("file_write", {"path": "/nonexistent"}, {"success": True})
        assert result["valid"] is False

    def test_web_search_with_results(self):
        v = ResultValidator()
        result = v.validate("web_search", {}, {
            "success": True,
            "results": [{"title": "test"}],
        })
        assert result["valid"] is True

    def test_web_search_empty(self):
        v = ResultValidator()
        result = v.validate("web_search", {}, {"success": True, "results": []})
        assert result["valid"] is False

    def test_web_fetch_with_content(self):
        v = ResultValidator()
        result = v.validate("web_fetch", {}, {
            "success": True,
            "content": "x" * 100,
        })
        assert result["valid"] is True

    def test_web_fetch_too_short(self):
        v = ResultValidator()
        result = v.validate("web_fetch", {}, {"success": True, "content": "hi"})
        assert result["valid"] is False


# =============================================================================
# TaskExecutor
# =============================================================================

class TestTaskExecutor:
    @pytest.fixture
    def executor(self, tmp_path):
        journal = ExecutionJournal(path=tmp_path / "j.jsonl")
        return TaskExecutor(journal=journal)

    def test_execute_single_success(self, executor):
        executor.register_tool("test", lambda args: {"success": True, "ok": True})
        result = executor.execute_single("test", {}, "Test task")
        assert result.success is True
        assert result.steps_completed == 1

    def test_execute_single_failure(self, executor):
        executor.register_tool("fail", lambda args: {"success": False})
        result = executor.execute_single("fail", {})
        assert result.success is False

    def test_execute_multi_step(self, executor):
        executor.register_tool("step_a", lambda args: {"success": True, "ok": True})
        executor.register_tool("step_b", lambda args: {"success": True, "ok": True})

        steps = [
            TaskStep(name="First", tool_name="step_a", tool_args={}),
            TaskStep(name="Second", tool_name="step_b", tool_args={}),
        ]
        result = executor.execute_steps(steps, "Multi-step test")
        assert result.success is True
        assert result.steps_completed == 2

    def test_multi_step_stops_on_failure(self, executor):
        executor.register_tool("ok", lambda args: {"success": True, "ok": True})
        executor.register_tool("fail", lambda args: {"success": False})

        steps = [
            TaskStep(name="OK", tool_name="ok", tool_args={}),
            TaskStep(name="Fail", tool_name="fail", tool_args={}),
            TaskStep(name="Never", tool_name="ok", tool_args={}),
        ]
        result = executor.execute_steps(steps, "Fail test")
        assert result.success is False
        assert result.steps_completed == 1
        assert result.steps_total == 3

    def test_unknown_tool(self, executor):
        result = executor.execute_single("nonexistent", {})
        assert result.success is False
        assert "No handler" in result.errors[0]

    def test_retry_on_exception(self, executor):
        call_count = [0]
        def flaky(args):
            call_count[0] += 1
            if call_count[0] < 2:
                raise RuntimeError("flaky")
            return {"success": True, "ok": True}

        executor.register_tool("flaky", flaky)
        result = executor.execute_single("flaky", {}, max_retries=3)
        assert result.success is True
        assert call_count[0] == 2

    def test_journal_tracking(self, executor):
        executor.register_tool("t", lambda args: {"success": True, "ok": True})
        result = executor.execute_single("t", {}, "Tracked task")
        assert result.journal_entry_id is not None

        entry = executor.journal.get_by_id(result.journal_entry_id)
        assert entry is not None
        assert entry.status == "completed"

    def test_get_available_tools(self, executor):
        executor.register_tool("a", lambda x: {})
        executor.register_tool("b", lambda x: {})
        tools = executor.get_available_tools()
        assert "a" in tools
        assert "b" in tools

    def test_result_has_duration(self, executor):
        executor.register_tool("t", lambda args: {"success": True, "ok": True})
        result = executor.execute_single("t", {})
        assert result.duration_ms >= 0

    def test_task_result_to_dict(self):
        r = TaskResult(
            task_id="task-123", success=True,
            steps_completed=2, steps_total=2,
            results=[], errors=[], duration_ms=100.0,
        )
        d = r.to_dict()
        assert d["task_id"] == "task-123"
        assert d["success"] is True


# =============================================================================
# WebResearcher
# =============================================================================

class TestWebResearcher:
    def test_search_wikipedia_no_query(self):
        wr = WebResearcher()
        result = wr.search_wikipedia({"query": ""})
        assert result["success"] is False

    def test_search_wikipedia_no_client(self):
        wr = WebResearcher()
        result = wr.search_wikipedia({"query": "python"})
        assert result["success"] is False
        assert "niedostepny" in result["error"]

    def test_search_wikipedia_success(self):
        wr = WebResearcher()
        wiki = MagicMock()
        wiki.search.return_value = ["Python (jezyk)"]
        wiki.fetch.return_value = {
            "title": "Python",
            "extract": "Python to jezyk programowania" * 10,
            "url": "https://pl.wikipedia.org/wiki/Python",
        }
        wr.set_wiki_client(wiki)

        result = wr.search_wikipedia({"query": "python", "save": False})
        assert result["success"] is True
        assert result["count"] == 1
        assert "Python" in result["results"][0]["title"]

    def test_search_and_save(self):
        wr = WebResearcher()
        wiki = MagicMock()
        wiki.search.return_value = ["AI"]
        wiki.fetch.return_value = {"title": "AI", "extract": "Sztuczna inteligencja", "url": ""}
        writer = MagicMock()
        writer.write.return_value = "input/web_wiki_ai.txt"
        wr.set_wiki_client(wiki)
        wr.set_content_writer(writer)

        result = wr.search_and_save({"topic": "AI"})
        assert result["success"] is True
        assert len(result["saved_files"]) == 1

    def test_fetch_url_no_url(self):
        wr = WebResearcher()
        result = wr.fetch_url({"url": ""})
        assert result["success"] is False

    @patch("requests.get")
    def test_fetch_url_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = "Hello World" * 100
        mock_get.return_value = mock_resp

        wr = WebResearcher()
        result = wr.fetch_url({"url": "https://example.com"})
        assert result["success"] is True
        assert result["length"] > 0


# =============================================================================
# FileManager
# =============================================================================

class TestFileManager:
    @pytest.fixture
    def fm(self, tmp_path):
        return FileManager(base_dir=tmp_path)

    def test_write_note(self, fm, tmp_path):
        result = fm.write_note({
            "title": "Test Note",
            "content": "Hello world",
            "directory": "input",
        })
        assert result["success"] is True
        assert Path(result["path"]).exists()

    def test_write_note_no_title(self, fm):
        result = fm.write_note({"title": "", "content": "hello"})
        assert result["success"] is False

    def test_write_note_no_content(self, fm):
        result = fm.write_note({"title": "test", "content": ""})
        assert result["success"] is False

    def test_write_note_unsafe_dir(self, fm):
        result = fm.write_note({
            "title": "test", "content": "hello", "directory": "/etc",
        })
        assert result["success"] is False

    def test_write_note_no_overwrite(self, fm, tmp_path):
        (tmp_path / "input").mkdir()
        (tmp_path / "input" / "test_note.txt").write_text("existing")

        result = fm.write_note({
            "title": "Test Note",
            "content": "New content",
        })
        assert result["success"] is True
        # Should have timestamp suffix, not overwrite
        assert "test_note.txt" != Path(result["path"]).name

    def test_read_file(self, fm, tmp_path):
        (tmp_path / "input").mkdir()
        f = tmp_path / "input" / "test.txt"
        f.write_text("hello world")

        result = fm.read_file({"path": str(f)})
        assert result["success"] is True
        assert result["content"] == "hello world"

    def test_read_file_outside_safe_dirs(self, fm):
        result = fm.read_file({"path": "/etc/passwd"})
        assert result["success"] is False

    def test_read_file_not_found(self, fm, tmp_path):
        result = fm.read_file({"path": str(tmp_path / "input" / "nope.txt")})
        assert result["success"] is False

    def test_list_files(self, fm, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "a.txt").write_text("a")
        (input_dir / "b.txt").write_text("b")
        (input_dir / "c.py").write_text("c")

        result = fm.list_files({"directory": "input", "pattern": "*.txt"})
        assert result["success"] is True
        assert result["count"] == 2

    def test_list_files_nonexistent(self, fm):
        result = fm.list_files({"directory": "nonexistent"})
        assert result["success"] is False

    def test_sanitize_filename(self):
        assert FileManager._sanitize_filename("Hello World!") == "hello_world"
        assert FileManager._sanitize_filename("test/path:name") == "test_path_name"
        assert FileManager._sanitize_filename("") == "notatka"
        assert len(FileManager._sanitize_filename("x" * 200)) <= 80


# =============================================================================
# Integration: TaskExecutor + FileManager
# =============================================================================

class TestIntegration:
    def test_executor_with_file_manager(self, tmp_path):
        journal = ExecutionJournal(path=tmp_path / "j.jsonl")
        executor = TaskExecutor(journal=journal)
        fm = FileManager(base_dir=tmp_path)

        executor.register_tool("file_write", fm.write_note)

        result = executor.execute_single("file_write", {
            "title": "Integration Test",
            "content": "This was created by TaskExecutor",
        }, "Write a test note")

        assert result.success is True
        # File should exist
        entry = journal.get_by_id(result.journal_entry_id)
        assert entry.status == "completed"

    def test_multi_step_wiki_then_save(self, tmp_path):
        """Simulate: search wiki -> save as note."""
        journal = ExecutionJournal(path=tmp_path / "j.jsonl")
        executor = TaskExecutor(journal=journal)
        fm = FileManager(base_dir=tmp_path)

        # Mock wiki search
        def fake_search(args):
            return {
                "success": True, "ok": True,
                "results": [{"title": "AI", "extract": "Sztuczna inteligencja..."}],
                "count": 1,
            }

        executor.register_tool("wiki_search", fake_search)
        executor.register_tool("file_write", fm.write_note)

        steps = [
            TaskStep(name="Search", tool_name="wiki_search", tool_args={"query": "AI"}),
            TaskStep(name="Save", tool_name="file_write", tool_args={
                "title": "AI Research",
                "content": "Wyniki wyszukiwania o AI",
            }),
        ]
        result = executor.execute_steps(steps, "Research and save")
        assert result.success is True
        assert result.steps_completed == 2
