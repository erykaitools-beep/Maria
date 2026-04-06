"""
Tests for Code Agent - autonomous coding capability.

All external calls mocked (OpenClaw, Claude, Codex).
"""

import json
import os
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

from agent_core.code_agent.models import (
    ApprovalCheckpoint,
    GeneratedFile,
    PlannedFile,
    TestResult,
    WrittenFile,
)
from agent_core.code_agent.session import (
    CodeSession,
    CodeSessionStatus,
    CodeSessionStore,
)
from agent_core.code_agent.prompt_builder import CodePromptBuilder
from agent_core.code_agent.agent import CodeAgent


# ============================================================
# Models
# ============================================================

class TestPlannedFile:
    def test_to_dict(self):
        f = PlannedFile(path="agent_core/voice/core.py", purpose="Voice engine", complexity="high")
        d = f.to_dict()
        assert d["path"] == "agent_core/voice/core.py"
        assert d["complexity"] == "high"
        assert d["is_test"] is False

    def test_frozen(self):
        f = PlannedFile(path="test.py", purpose="test")
        with pytest.raises(AttributeError):
            f.path = "other.py"


class TestGeneratedFile:
    def test_to_dict(self):
        g = GeneratedFile(path="test.py", content="print('hi')", syntax_valid=True, llm_source="claude")
        d = g.to_dict()
        assert d["content_length"] == 11
        assert d["syntax_valid"] is True


class TestWrittenFile:
    def test_to_dict(self):
        w = WrittenFile(path="/tmp/test.py", content_hash="abc123", size_bytes=100, verified=True)
        d = w.to_dict()
        assert d["verified"] is True
        assert d["content_hash"] == "abc123"


class TestTestResult:
    def test_success(self):
        r = TestResult(run_number=1, command="pytest", exit_code=0, stdout="1 passed", passed=1, failed=0)
        assert r.success is True

    def test_failure(self):
        r = TestResult(run_number=1, command="pytest", exit_code=1, stdout="1 failed", passed=0, failed=1)
        assert r.success is False

    def test_to_dict(self):
        r = TestResult(run_number=2, command="pytest", exit_code=0, stdout="", passed=5, failed=0)
        d = r.to_dict()
        assert d["run_number"] == 2
        assert d["success"] is True


class TestApprovalCheckpoint:
    def test_to_dict(self):
        cp = ApprovalCheckpoint(name="plan_review", request_id="req-123", status="pending")
        d = cp.to_dict()
        assert d["name"] == "plan_review"
        assert d["status"] == "pending"


# ============================================================
# Session
# ============================================================

class TestCodeSession:
    def test_create(self):
        s = CodeSession(task_description="build voice module")
        assert s.session_id.startswith("cs-")
        assert s.status == CodeSessionStatus.PLANNING
        assert s.task_description == "build voice module"

    def test_status_transition(self):
        s = CodeSession()
        s.update_status(CodeSessionStatus.GENERATING)
        assert s.status == CodeSessionStatus.GENERATING
        assert s.completed_at is None

    def test_terminal_status(self):
        s = CodeSession()
        s.update_status(CodeSessionStatus.COMPLETED)
        assert s.status.is_terminal is True
        assert s.completed_at is not None

    def test_resumable_status(self):
        assert CodeSessionStatus.WAITING_BUDGET.is_resumable is True
        assert CodeSessionStatus.AWAITING_APPROVAL.is_resumable is True
        assert CodeSessionStatus.PLANNING.is_resumable is False

    def test_record_llm_call(self):
        s = CodeSession()
        s.record_llm_call("claude")
        s.record_llm_call("claude")
        s.record_llm_call("codex")
        assert s.llm_calls_used["claude"] == 2
        assert s.llm_calls_used["codex"] == 1
        assert s.total_llm_calls == 3

    def test_to_dict_from_dict_roundtrip(self):
        s = CodeSession(task_description="test task", target_dir="/tmp")
        s.files_planned.append(PlannedFile(path="test.py", purpose="test"))
        s.approval_checkpoints.append(ApprovalCheckpoint(name="review"))
        s.update_status(CodeSessionStatus.GENERATING)
        s.record_llm_call("claude")

        d = s.to_dict()
        s2 = CodeSession.from_dict(d)
        assert s2.session_id == s.session_id
        assert s2.status == CodeSessionStatus.GENERATING
        assert len(s2.files_planned) == 1
        assert s2.files_planned[0].path == "test.py"
        assert s2.llm_calls_used["claude"] == 1

    def test_describe(self):
        s = CodeSession(task_description="build voice")
        s.files_planned.append(PlannedFile(path="test.py", purpose="test"))
        desc = s.describe()
        assert "build voice" in desc
        assert "1 zaplanowanych" in desc


class TestCodeSessionStore:
    def test_save_and_load(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            store = CodeSessionStore(path=path)
            s = CodeSession(task_description="test")
            store.save(s)

            store2 = CodeSessionStore(path=path)
            loaded = store2.get(s.session_id)
            assert loaded is not None
            assert loaded.task_description == "test"
        finally:
            os.unlink(path)

    def test_get_active(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            store = CodeSessionStore(path=path)

            s1 = CodeSession(task_description="done")
            s1.update_status(CodeSessionStatus.COMPLETED)
            store.save(s1)

            s2 = CodeSession(task_description="active")
            store.save(s2)

            active = store.get_active()
            assert active is not None
            assert active.task_description == "active"
        finally:
            os.unlink(path)

    def test_get_resumable(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            store = CodeSessionStore(path=path)
            s = CodeSession(task_description="paused")
            s.update_status(CodeSessionStatus.WAITING_BUDGET)
            store.save(s)

            r = store.get_resumable()
            assert r is not None
            assert r.task_description == "paused"
        finally:
            os.unlink(path)

    def test_prefix_match(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            store = CodeSessionStore(path=path)
            s = CodeSession(task_description="test")
            store.save(s)

            prefix = s.session_id[:6]
            found = store.get(prefix)
            assert found is not None
            assert found.session_id == s.session_id
        finally:
            os.unlink(path)


# ============================================================
# PromptBuilder
# ============================================================

class TestCodePromptBuilder:
    def test_gather_context(self):
        builder = CodePromptBuilder(project_root="/tmp/nonexistent")
        ctx = builder.gather_architecture_context()
        assert "M.A.R.I.A." in ctx
        assert "agent_core" in ctx

    def test_build_design_prompt(self):
        builder = CodePromptBuilder(project_root="/tmp")
        prompt = builder.build_design_prompt("build a voice module")
        assert "voice module" in prompt
        assert "JSON array" in prompt

    def test_build_generate_prompt(self):
        builder = CodePromptBuilder(project_root="/tmp")
        plan = PlannedFile(path="test.py", purpose="test file", complexity="low")
        prompt = builder.build_generate_prompt(plan)
        assert "test.py" in prompt
        assert "PURPOSE: test file" in prompt

    def test_build_fix_prompt(self):
        builder = CodePromptBuilder()
        prompt = builder.build_fix_prompt("test.py", "def foo(): pass", "AssertionError", "line 5")
        assert "test.py" in prompt
        assert "def foo(): pass" in prompt

    def test_parse_file_plan_json(self):
        response = '[{"path": "core.py", "purpose": "main", "complexity": "high", "dependencies": [], "is_test": false}]'
        files = CodePromptBuilder.parse_file_plan(response)
        assert len(files) == 1
        assert files[0].path == "core.py"
        assert files[0].complexity == "high"

    def test_parse_file_plan_with_fences(self):
        response = '```json\n[{"path": "test.py", "purpose": "test"}]\n```'
        files = CodePromptBuilder.parse_file_plan(response)
        assert len(files) == 1
        assert files[0].path == "test.py"

    def test_parse_file_plan_invalid(self):
        files = CodePromptBuilder.parse_file_plan("not json at all")
        assert files == []

    def test_extract_code_clean(self):
        code = "def hello():\n    return 'world'"
        assert CodePromptBuilder.extract_code(code) == code

    def test_extract_code_fenced(self):
        response = "```python\ndef hello():\n    return 'world'\n```"
        code = CodePromptBuilder.extract_code(response)
        assert "def hello():" in code
        assert "```" not in code

    def test_build_review_prompt(self):
        builder = CodePromptBuilder()
        files = [GeneratedFile(path="test.py", content="def foo(): pass")]
        prompt = builder.build_review_prompt(files)
        assert "test.py" in prompt
        assert "PASS or FAIL" in prompt


# ============================================================
# CodeAgent
# ============================================================

class TestCodeAgent:
    def _make_agent(self):
        ctx = MagicMock()
        ctx.openclaw_client = None
        ctx.claude_client = None
        ctx.codex_client = None
        ctx.telegram_bridge = None
        ctx.code_agent = None
        agent = CodeAgent(ctx)
        # Isolate session store per test
        import tempfile
        f = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        f.close()
        agent._session_store = CodeSessionStore(path=f.name)
        return agent

    def test_start_creates_session(self):
        agent = self._make_agent()
        # Mock LLM to return a file plan
        agent.set_claude_fn(lambda p, source, context: json.dumps([
            {"path": "agent_core/voice/core.py", "purpose": "Voice engine", "is_test": False},
            {"path": "agent_core/tests/test_voice.py", "purpose": "Tests", "is_test": True},
        ]))
        session = agent.start("build voice module")
        assert session.session_id.startswith("cs-")
        assert len(session.files_planned) == 2
        assert session.status == CodeSessionStatus.AWAITING_APPROVAL

    def test_start_no_llm_budget(self):
        agent = self._make_agent()
        # No LLM functions set -> waiting for budget
        session = agent.start("build something")
        assert session.status == CodeSessionStatus.WAITING_BUDGET

    def test_start_one_at_a_time(self):
        agent = self._make_agent()
        agent.set_claude_fn(lambda p, source, context: '[{"path": "a.py", "purpose": "test"}]')
        s1 = agent.start("task 1")
        s2 = agent.start("task 2")
        # Should return the same (active) session
        assert s1.session_id == s2.session_id

    def test_cancel(self):
        agent = self._make_agent()
        agent.set_claude_fn(lambda p, source, context: '[{"path": "a.py", "purpose": "test"}]')
        session = agent.start("task")
        assert agent.cancel(session.session_id)
        updated = agent.get_session(session.session_id)
        assert updated.status == CodeSessionStatus.CANCELLED

    def test_approve_and_resume(self):
        agent = self._make_agent()
        call_count = {"n": 0}

        def mock_llm(prompt, source, context):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return '[{"path": "test.py", "purpose": "test", "is_test": false}]'
            else:
                return 'def hello():\n    return "world"'

        agent.set_codex_fn(mock_llm)
        session = agent.start("write hello")
        assert session.status == CodeSessionStatus.AWAITING_APPROVAL

        # Approve
        assert agent.approve_checkpoint(session.session_id)
        # Resume - should generate code
        agent.resume(session.session_id)
        updated = agent.get_session(session.session_id)
        assert len(updated.files_generated) >= 1

    def test_reject_cancels(self):
        agent = self._make_agent()
        agent.set_claude_fn(lambda p, source, context: '[{"path": "a.py", "purpose": "test"}]')
        session = agent.start("task")
        assert agent.reject_checkpoint(session.session_id)
        updated = agent.get_session(session.session_id)
        assert updated.status == CodeSessionStatus.CANCELLED

    def test_validate_syntax_valid(self):
        agent = self._make_agent()
        assert agent._validate_syntax("def foo(): pass") is True

    def test_validate_syntax_invalid(self):
        agent = self._make_agent()
        assert agent._validate_syntax("def foo(") is False

    def test_resolve_path_valid(self):
        agent = self._make_agent()
        path = agent._resolve_path("agent_core/voice/core.py", "/home/maria/maria")
        assert path == "/home/maria/maria/agent_core/voice/core.py"

    def test_resolve_path_traversal_blocked(self):
        agent = self._make_agent()
        path = agent._resolve_path("../../etc/passwd", "/home/maria/maria")
        assert path is None

    def test_resolve_path_dangerous_blocked(self):
        agent = self._make_agent()
        path = agent._resolve_path(".env", "/home/maria/maria")
        assert path is None

    def test_is_self_modify(self):
        agent = self._make_agent()
        assert agent._is_self_modify("/home/maria/maria/agent_core/voice/core.py") is True
        assert agent._is_self_modify("/tmp/test.py") is False

    def test_parse_test_output(self):
        agent = self._make_agent()
        output = "collected 5 items\n\n5 passed in 1.23s\n"
        passed, failed, errors = agent._parse_test_output(output)
        assert passed == 5
        assert failed == 0

    def test_parse_test_output_failures(self):
        agent = self._make_agent()
        output = "FAILED test_voice.py::test_init\n2 passed, 1 failed in 0.5s\n"
        passed, failed, errors = agent._parse_test_output(output)
        assert passed == 2
        assert failed == 1
        assert len(errors) >= 1

    def test_max_iterations_guard(self):
        agent = self._make_agent()
        session = CodeSession(task_description="test", max_iterations=0)
        session.files_planned.append(PlannedFile(path="test.py", purpose="test", is_test=True))
        session.files_generated.append(GeneratedFile(path="test.py", content="pass"))
        session.files_written.append(WrittenFile(path="/tmp/test.py", content_hash="x", size_bytes=4))

        # Mock OpenClaw to return failing tests
        mock_claw = MagicMock()
        mock_claw.invoke_tool.return_value = {
            "ok": True, "result": "1 failed in 0.1s\nFAILED test.py::test_x", "exit_code": 1,
        }
        agent.set_openclaw(mock_claw)

        # With max_iterations=0, should fail immediately
        session.status = CodeSessionStatus.TESTING
        session.current_step = "test"
        agent._test(session)
        assert session.status == CodeSessionStatus.FAILED
        assert "0 iteracjach" in session.result_summary

    def test_self_modify_guard_blocks(self):
        agent = self._make_agent()
        session = CodeSession(task_description="modify core", target_dir="/home/maria/maria")
        session.files_generated.append(
            GeneratedFile(path="agent_core/voice/core.py", content="pass")
        )

        mock_claw = MagicMock()
        mock_claw.invoke_tool.return_value = {"ok": True, "result": ""}
        agent.set_openclaw(mock_claw)

        agent._write(session)
        # Should request self-modify approval
        assert session.status == CodeSessionStatus.AWAITING_APPROVAL
        assert any(cp.name == "self_modify" for cp in session.approval_checkpoints)

    def test_list_sessions(self):
        agent = self._make_agent()
        agent.set_claude_fn(lambda p, source, context: '[{"path": "a.py", "purpose": "test"}]')
        s = agent.start("task")
        sessions = agent.list_sessions()
        assert len(sessions) >= 1

    def test_budget_tracking(self):
        agent = self._make_agent()
        call_count = {"n": 0}

        def mock_claude(prompt, source, context):
            call_count["n"] += 1
            return '[{"path": "a.py", "purpose": "test"}]'

        agent.set_claude_fn(mock_claude)
        session = agent.start("task")
        assert session.llm_calls_used["claude"] >= 1

    def test_notify_called(self):
        agent = self._make_agent()
        notifications = []
        agent.set_notify_fn(lambda msg: notifications.append(msg))
        agent.set_claude_fn(lambda p, source, context: '[{"path": "a.py", "purpose": "test"}]')
        agent.start("task")
        assert len(notifications) >= 1
        assert "Code Agent" in notifications[0]


# ============================================================
# TaskDecomposer CODE category
# ============================================================

class TestTaskDecomposerCode:
    def test_classify_code(self):
        from agent_core.orchestrator.task_decomposer import TaskDecomposer, TaskCategory
        ctx = MagicMock()
        ctx.homeostasis_core = None
        ctx.knowledge_analyzer = None
        d = TaskDecomposer(ctx)
        result = d.decompose("zrob modul do glosu")
        assert result.category == TaskCategory.CODE
        assert len(result.steps) == 6

    def test_classify_build(self):
        from agent_core.orchestrator.task_decomposer import TaskDecomposer, TaskCategory
        ctx = MagicMock()
        ctx.homeostasis_core = None
        ctx.knowledge_analyzer = None
        d = TaskDecomposer(ctx)
        result = d.decompose("build a voice module")
        assert result.category == TaskCategory.CODE

    def test_classify_implement(self):
        from agent_core.orchestrator.task_decomposer import TaskDecomposer, TaskCategory
        ctx = MagicMock()
        ctx.homeostasis_core = None
        ctx.knowledge_analyzer = None
        d = TaskDecomposer(ctx)
        result = d.decompose("implement REST API endpoint")
        assert result.category == TaskCategory.CODE

    def test_code_steps_structure(self):
        from agent_core.orchestrator.task_decomposer import TaskDecomposer, TaskCategory
        ctx = MagicMock()
        ctx.homeostasis_core = None
        ctx.knowledge_analyzer = None
        d = TaskDecomposer(ctx)
        result = d.decompose("napisz modul glosu")
        steps = result.steps
        actions = [s.action for s in steps]
        assert "code_design" in actions
        assert "code_generate" in actions
        assert "code_write" in actions
        assert "code_test" in actions
        assert "code_review" in actions

    def test_code_in_categories(self):
        from agent_core.orchestrator.task_decomposer import TaskDecomposer
        ctx = MagicMock()
        ctx.homeostasis_core = None
        d = TaskDecomposer(ctx)
        cats = d.get_available_categories()
        names = [c["category"] for c in cats]
        assert "code" in names

    def test_topic_extraction(self):
        from agent_core.orchestrator.task_decomposer import TaskDecomposer
        ctx = MagicMock()
        ctx.homeostasis_core = None
        ctx.knowledge_analyzer = None
        d = TaskDecomposer(ctx)
        result = d.decompose("zrob modul glosu")
        assert result.topic is not None
        assert "glosu" in result.topic.lower()
