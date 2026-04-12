"""
Tests for Faza 5: Workflow Orchestration.

Covers: model, store, engine, delegation, templates, progress reporter.
"""

import json
import os
import tempfile
import time
import pytest

from agent_core.workflow.workflow_model import (
    WorkflowStep,
    WorkflowState,
    WorkflowStatus,
    StepResult,
    FailPolicy,
    create_workflow,
)
from agent_core.workflow.workflow_store import WorkflowStore
from agent_core.workflow.workflow_engine import WorkflowEngine, MAX_ACTIVE_WORKFLOWS
from agent_core.workflow.delegation import DelegationManager
from agent_core.workflow.progress_reporter import ProgressReporter
from agent_core.workflow.templates import (
    research_workflow,
    deep_learn_workflow,
    daily_review_workflow,
    system_health_workflow,
    full_audit_workflow,
    WORKFLOW_TEMPLATES,
)


# === Fixtures ===

def _make_steps(n=3, actions=None):
    """Create N simple workflow steps."""
    actions = actions or ["learn", "exam", "review"]
    return [
        WorkflowStep(
            order=i,
            action=actions[i % len(actions)],
            params={"topic": "test"},
            description=f"Step {i}: {actions[i % len(actions)]}",
        )
        for i in range(n)
    ]


def _make_store(tmp_path=None):
    """Create a WorkflowStore with a temp file."""
    if tmp_path is None:
        tmp_path = tempfile.mkdtemp()
    path = os.path.join(tmp_path, "workflows.jsonl")
    return WorkflowStore(path=path)


class FakeDelegation(DelegationManager):
    """Delegation that always succeeds."""

    def __init__(self, success=True, error=None):
        super().__init__()
        self._success = success
        self._error = error
        self.delegated = []

    def delegate(self, step, goal_id=None, attempt=0):
        self.delegated.append((step, goal_id))
        return StepResult(
            order=step.order,
            action=step.action,
            success=self._success,
            result={"mock": True},
            error=self._error,
            duration_ms=10.0,
            retries_used=attempt,
        )


# ========== MODEL TESTS ==========

class TestWorkflowModel:

    def test_step_frozen(self):
        step = WorkflowStep(order=0, action="learn", params={}, description="Test")
        with pytest.raises(AttributeError):
            step.order = 1

    def test_step_to_dict_roundtrip(self):
        step = WorkflowStep(
            order=2, action="fetch", params={"topic": "AI"},
            description="Fetch AI", on_fail=FailPolicy.SKIP,
            max_retries=3, requires_approval=True, checkpoint=False,
        )
        d = step.to_dict()
        restored = WorkflowStep.from_dict(d)
        assert restored.order == 2
        assert restored.action == "fetch"
        assert restored.on_fail == FailPolicy.SKIP
        assert restored.max_retries == 3
        assert restored.requires_approval is True
        assert restored.checkpoint is False

    def test_step_result_to_dict_roundtrip(self):
        sr = StepResult(order=1, action="learn", success=True,
                        result={"chunks": 3}, duration_ms=500.0)
        d = sr.to_dict()
        restored = StepResult.from_dict(d)
        assert restored.order == 1
        assert restored.success is True
        assert restored.result["chunks"] == 3

    def test_workflow_state_to_dict_roundtrip(self):
        steps = _make_steps(2)
        wf = create_workflow("test_wf", "Test workflow", steps, goal_id="g-123")
        wf.status = WorkflowStatus.RUNNING
        wf.current_step = 1
        wf.results.append(StepResult(order=0, action="learn", success=True))

        d = wf.to_dict()
        restored = WorkflowState.from_dict(d)
        assert restored.workflow_id == wf.workflow_id
        assert restored.name == "test_wf"
        assert restored.status == WorkflowStatus.RUNNING
        assert restored.current_step == 1
        assert len(restored.results) == 1
        assert len(restored.steps) == 2

    def test_progress_pct(self):
        steps = _make_steps(4)
        wf = create_workflow("test", "Test", steps)
        assert wf.progress_pct == 0.0

        wf.results.append(StepResult(order=0, action="learn", success=True))
        assert wf.progress_pct == 25.0

        wf.results.append(StepResult(order=1, action="exam", success=True))
        assert wf.progress_pct == 50.0

    def test_progress_pct_empty_steps(self):
        wf = create_workflow("test", "Test", [])
        # Empty steps should not happen, but protect against it
        # create_workflow will fail due to engine validation, test model directly
        wf2 = WorkflowState(workflow_id="wf-test", name="t", description="",
                            steps=[], created_at=0, updated_at=0)
        assert wf2.progress_pct == 100.0

    def test_is_terminal(self):
        steps = _make_steps(1)
        wf = create_workflow("test", "Test", steps)
        assert not wf.is_terminal

        wf.status = WorkflowStatus.RUNNING
        assert not wf.is_terminal

        wf.status = WorkflowStatus.PAUSED
        assert not wf.is_terminal

        for status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED]:
            wf.status = status
            assert wf.is_terminal

    def test_current_step_def(self):
        steps = _make_steps(3)
        wf = create_workflow("test", "Test", steps)
        assert wf.current_step_def.order == 0

        wf.current_step = 2
        assert wf.current_step_def.order == 2

        wf.current_step = 3
        assert wf.current_step_def is None

    def test_create_workflow_factory(self):
        steps = _make_steps(2)
        wf = create_workflow("research", "Research AI", steps, goal_id="g-1",
                             metadata={"template": "research"})
        assert wf.workflow_id.startswith("wf-")
        assert wf.name == "research"
        assert wf.goal_id == "g-1"
        assert wf.status == WorkflowStatus.PENDING
        assert wf.metadata["template"] == "research"

    def test_fail_policy_values(self):
        assert FailPolicy.STOP.value == "stop"
        assert FailPolicy.SKIP.value == "skip"
        assert FailPolicy.RETRY.value == "retry"


# ========== STORE TESTS ==========

class TestWorkflowStore:

    def test_save_and_get(self, tmp_path):
        store = _make_store(str(tmp_path))
        steps = _make_steps(2)
        wf = create_workflow("test", "Test", steps)
        store.save(wf)

        loaded = store.get(wf.workflow_id)
        assert loaded is not None
        assert loaded.name == "test"
        assert len(loaded.steps) == 2

    def test_get_nonexistent(self, tmp_path):
        store = _make_store(str(tmp_path))
        assert store.get("wf-nonexistent") is None

    def test_persistence_across_instances(self, tmp_path):
        path = os.path.join(str(tmp_path), "workflows.jsonl")
        store1 = WorkflowStore(path=path)
        steps = _make_steps(1)
        wf = create_workflow("persist_test", "Persist", steps)
        store1.save(wf)

        store2 = WorkflowStore(path=path)
        loaded = store2.get(wf.workflow_id)
        assert loaded is not None
        assert loaded.name == "persist_test"

    def test_merge_semantics(self, tmp_path):
        store = _make_store(str(tmp_path))
        steps = _make_steps(1)
        wf = create_workflow("merge", "Merge test", steps)
        store.save(wf)

        wf.status = WorkflowStatus.RUNNING
        store.save(wf)

        loaded = store.get(wf.workflow_id)
        assert loaded.status == WorkflowStatus.RUNNING

    def test_list_active(self, tmp_path):
        store = _make_store(str(tmp_path))
        steps = _make_steps(1)

        wf1 = create_workflow("active1", "A1", steps)
        wf1.status = WorkflowStatus.RUNNING
        store.save(wf1)

        wf2 = create_workflow("done", "Done", steps)
        wf2.status = WorkflowStatus.COMPLETED
        store.save(wf2)

        wf3 = create_workflow("pending", "Pending", steps)
        store.save(wf3)

        active = store.list_active()
        assert len(active) == 2  # RUNNING + PENDING
        ids = {w.workflow_id for w in active}
        assert wf1.workflow_id in ids
        assert wf3.workflow_id in ids

    def test_list_all_by_status(self, tmp_path):
        store = _make_store(str(tmp_path))
        steps = _make_steps(1)

        for i in range(3):
            wf = create_workflow(f"wf_{i}", f"WF {i}", steps)
            wf.status = WorkflowStatus.COMPLETED if i < 2 else WorkflowStatus.RUNNING
            store.save(wf)

        completed = store.list_all(WorkflowStatus.COMPLETED)
        assert len(completed) == 2

        running = store.list_all(WorkflowStatus.RUNNING)
        assert len(running) == 1

    def test_get_by_goal(self, tmp_path):
        store = _make_store(str(tmp_path))
        steps = _make_steps(1)
        wf = create_workflow("goal_wf", "Goal WF", steps, goal_id="goal-abc")
        store.save(wf)

        found = store.get_by_goal("goal-abc")
        assert found is not None
        assert found.workflow_id == wf.workflow_id

        assert store.get_by_goal("goal-xyz") is None

    def test_recover_interrupted(self, tmp_path):
        store = _make_store(str(tmp_path))
        steps = _make_steps(1)

        wf1 = create_workflow("running", "Running", steps)
        wf1.status = WorkflowStatus.RUNNING
        store.save(wf1)

        wf2 = create_workflow("paused", "Paused", steps)
        wf2.status = WorkflowStatus.PAUSED
        store.save(wf2)

        interrupted = store.recover_interrupted()
        assert len(interrupted) == 1
        assert interrupted[0].workflow_id == wf1.workflow_id
        assert interrupted[0].status == WorkflowStatus.PAUSED
        assert interrupted[0].paused_by == "system"

    def test_count(self, tmp_path):
        store = _make_store(str(tmp_path))
        assert store.count() == 0

        steps = _make_steps(1)
        store.save(create_workflow("a", "A", steps))
        store.save(create_workflow("b", "B", steps))
        assert store.count() == 2

    def test_prune_old(self, tmp_path):
        store = _make_store(str(tmp_path))
        steps = _make_steps(1)

        for i in range(10):
            wf = create_workflow(f"wf_{i}", f"WF {i}", steps)
            wf.status = WorkflowStatus.COMPLETED
            wf.completed_at = time.time() - (10 - i) * 100
            store.save(wf)

        pruned = store.prune_old(max_terminal=5)
        assert pruned == 5
        assert store.count() == 5

    def test_compact(self, tmp_path):
        path = os.path.join(str(tmp_path), "workflows.jsonl")
        store = WorkflowStore(path=path)
        steps = _make_steps(1)
        wf = create_workflow("compact", "Compact", steps)

        # Write same workflow many times to trigger compaction
        for i in range(25):
            wf.current_step = i % 3
            store.save(wf)

        # File should have been compacted
        with open(path, "r") as f:
            lines = [l for l in f if l.strip()]
        assert len(lines) <= 5  # Should be compacted to 1

    def test_malformed_line_skipped(self, tmp_path):
        path = os.path.join(str(tmp_path), "workflows.jsonl")
        with open(path, "w") as f:
            f.write("not json\n")
            f.write('{"workflow_id": "wf-good", "name": "ok", "steps": [], '
                    '"status": "pending", "current_step": 0, "results": [], '
                    '"created_at": 0, "updated_at": 0}\n')

        store = WorkflowStore(path=path)
        assert store.count() == 1


# ========== ENGINE TESTS ==========

class TestWorkflowEngine:

    def _make_engine(self, tmp_path, delegation=None):
        store = _make_store(str(tmp_path))
        deleg = delegation or FakeDelegation(success=True)
        return WorkflowEngine(store, deleg), store

    def test_create_workflow(self, tmp_path):
        engine, store = self._make_engine(tmp_path)
        steps = _make_steps(3)
        wf = engine.create("test", "Test workflow", steps)

        assert wf.workflow_id.startswith("wf-")
        assert wf.status == WorkflowStatus.PENDING
        assert len(wf.steps) == 3
        assert store.get(wf.workflow_id) is not None

    def test_create_empty_steps_raises(self, tmp_path):
        engine, _ = self._make_engine(tmp_path)
        with pytest.raises(ValueError, match="at least one step"):
            engine.create("empty", "Empty", [])

    def test_create_max_active_limit(self, tmp_path):
        engine, _ = self._make_engine(tmp_path)
        steps = _make_steps(1)

        for i in range(MAX_ACTIVE_WORKFLOWS):
            engine.create(f"wf_{i}", f"WF {i}", steps)

        with pytest.raises(ValueError, match="Too many active"):
            engine.create("overflow", "Overflow", steps)

    def test_start_workflow(self, tmp_path):
        engine, store = self._make_engine(tmp_path)
        steps = _make_steps(2)
        wf = engine.create("test", "Test", steps)

        assert engine.start(wf.workflow_id) is True
        loaded = store.get(wf.workflow_id)
        assert loaded.status == WorkflowStatus.RUNNING

    def test_start_nonexistent(self, tmp_path):
        engine, _ = self._make_engine(tmp_path)
        assert engine.start("wf-nonexistent") is False

    def test_start_already_running(self, tmp_path):
        engine, store = self._make_engine(tmp_path)
        steps = _make_steps(1)
        wf = engine.create("test", "Test", steps)
        engine.start(wf.workflow_id)
        assert engine.start(wf.workflow_id) is False

    def test_advance_executes_step(self, tmp_path):
        deleg = FakeDelegation(success=True)
        engine, store = self._make_engine(tmp_path, deleg)
        steps = _make_steps(2)
        wf = engine.create("test", "Test", steps)
        engine.start(wf.workflow_id)

        result = engine.advance(wf.workflow_id)
        assert result is not None
        assert result.success is True
        assert result.order == 0

        loaded = store.get(wf.workflow_id)
        assert loaded.current_step == 1

    def test_advance_completes_workflow(self, tmp_path):
        deleg = FakeDelegation(success=True)
        engine, store = self._make_engine(tmp_path, deleg)
        steps = _make_steps(2)
        wf = engine.create("test", "Test", steps)
        engine.start(wf.workflow_id)

        engine.advance(wf.workflow_id)  # Step 0
        engine.advance(wf.workflow_id)  # Step 1 -> complete

        loaded = store.get(wf.workflow_id)
        assert loaded.status == WorkflowStatus.COMPLETED
        assert loaded.completed_at is not None

    def test_advance_after_complete_returns_none(self, tmp_path):
        deleg = FakeDelegation(success=True)
        engine, _ = self._make_engine(tmp_path, deleg)
        steps = _make_steps(1)
        wf = engine.create("test", "Test", steps)
        engine.start(wf.workflow_id)
        engine.advance(wf.workflow_id)

        assert engine.advance(wf.workflow_id) is None

    def test_advance_fail_policy_stop(self, tmp_path):
        deleg = FakeDelegation(success=False, error="LLM timeout")
        engine, store = self._make_engine(tmp_path, deleg)
        steps = [
            WorkflowStep(order=0, action="learn", params={},
                         description="Fail", on_fail=FailPolicy.STOP),
        ]
        wf = engine.create("test", "Test", steps)
        engine.start(wf.workflow_id)

        result = engine.advance(wf.workflow_id)
        assert result.success is False

        loaded = store.get(wf.workflow_id)
        assert loaded.status == WorkflowStatus.FAILED
        assert "LLM timeout" in loaded.error

    def test_advance_fail_policy_skip(self, tmp_path):
        deleg = FakeDelegation(success=False, error="timeout")
        engine, store = self._make_engine(tmp_path, deleg)
        steps = [
            WorkflowStep(order=0, action="learn", params={},
                         description="Skip me", on_fail=FailPolicy.SKIP),
            WorkflowStep(order=1, action="exam", params={},
                         description="Continue"),
        ]
        wf = engine.create("test", "Test", steps)
        engine.start(wf.workflow_id)

        result = engine.advance(wf.workflow_id)
        assert result.success is False

        loaded = store.get(wf.workflow_id)
        # Should have skipped to step 1, not failed
        assert loaded.status == WorkflowStatus.RUNNING
        assert loaded.current_step == 1

    def test_advance_fail_policy_retry(self, tmp_path):
        call_count = [0]
        class RetryDelegation(DelegationManager):
            def delegate(self, step, goal_id=None, attempt=0):
                call_count[0] += 1
                success = call_count[0] >= 2
                return StepResult(
                    order=step.order, action=step.action,
                    success=success, error=None if success else "retry me",
                    duration_ms=5.0, retries_used=attempt,
                )

        store = _make_store(str(tmp_path))
        engine = WorkflowEngine(store, RetryDelegation())
        steps = [
            WorkflowStep(order=0, action="learn", params={},
                         description="Retry", on_fail=FailPolicy.RETRY,
                         max_retries=3),
        ]
        wf = engine.create("test", "Test", steps)
        engine.start(wf.workflow_id)

        # First attempt fails
        r1 = engine.advance(wf.workflow_id)
        assert r1.success is False

        # Second attempt succeeds
        r2 = engine.advance(wf.workflow_id)
        assert r2.success is True

    def test_pause_and_resume(self, tmp_path):
        engine, store = self._make_engine(tmp_path)
        steps = _make_steps(2)
        wf = engine.create("test", "Test", steps)
        engine.start(wf.workflow_id)

        assert engine.pause(wf.workflow_id) is True
        loaded = store.get(wf.workflow_id)
        assert loaded.status == WorkflowStatus.PAUSED
        assert loaded.paused_by == "operator"

        # Can't advance while paused
        assert engine.advance(wf.workflow_id) is None

        assert engine.resume(wf.workflow_id) is True
        loaded = store.get(wf.workflow_id)
        assert loaded.status == WorkflowStatus.RUNNING

    def test_cancel(self, tmp_path):
        engine, store = self._make_engine(tmp_path)
        steps = _make_steps(2)
        wf = engine.create("test", "Test", steps)
        engine.start(wf.workflow_id)

        assert engine.cancel(wf.workflow_id, "not needed") is True
        loaded = store.get(wf.workflow_id)
        assert loaded.status == WorkflowStatus.CANCELLED
        assert loaded.error == "not needed"

    def test_cancel_terminal_fails(self, tmp_path):
        deleg = FakeDelegation(success=True)
        engine, _ = self._make_engine(tmp_path, deleg)
        steps = _make_steps(1)
        wf = engine.create("test", "Test", steps)
        engine.start(wf.workflow_id)
        engine.advance(wf.workflow_id)  # Complete

        assert engine.cancel(wf.workflow_id) is False

    def test_approve_step(self, tmp_path):
        engine, store = self._make_engine(tmp_path)
        steps = [
            WorkflowStep(order=0, action="effector", params={},
                         description="Needs approval",
                         requires_approval=True),
        ]
        wf = engine.create("test", "Test", steps)
        engine.start(wf.workflow_id)

        # Advance pauses for approval
        result = engine.advance(wf.workflow_id)
        assert result is None
        loaded = store.get(wf.workflow_id)
        assert loaded.status == WorkflowStatus.PAUSED
        assert loaded.paused_by == "approval_needed"

        # Approve and resume
        assert engine.approve_step(wf.workflow_id, 0) is True
        loaded = store.get(wf.workflow_id)
        assert loaded.status == WorkflowStatus.RUNNING

    def test_get_progress(self, tmp_path):
        deleg = FakeDelegation(success=True)
        engine, _ = self._make_engine(tmp_path, deleg)
        steps = _make_steps(3)
        wf = engine.create("test", "Test", steps)
        engine.start(wf.workflow_id)
        engine.advance(wf.workflow_id)

        progress = engine.get_progress(wf.workflow_id)
        assert progress is not None
        assert progress["status"] == "running"
        assert progress["completed_steps"] == 1
        assert progress["total_steps"] == 3
        assert progress["progress_pct"] == pytest.approx(33.3, abs=0.1)

    def test_get_progress_nonexistent(self, tmp_path):
        engine, _ = self._make_engine(tmp_path)
        assert engine.get_progress("wf-nope") is None

    def test_list_workflows(self, tmp_path):
        engine, _ = self._make_engine(tmp_path)
        steps = _make_steps(1)

        engine.create("wf1", "WF 1", steps)
        engine.create("wf2", "WF 2", steps)

        wfs = engine.list_workflows()
        assert len(wfs) == 2

    def test_list_workflows_by_status(self, tmp_path):
        deleg = FakeDelegation(success=True)
        engine, _ = self._make_engine(tmp_path, deleg)
        steps = _make_steps(1)

        wf1 = engine.create("run", "Running", steps)
        engine.start(wf1.workflow_id)

        engine.create("pend", "Pending", steps)

        running = engine.list_workflows(WorkflowStatus.RUNNING)
        assert len(running) == 1
        assert running[0]["name"] == "run"

    def test_advance_next_active(self, tmp_path):
        deleg = FakeDelegation(success=True)
        engine, store = self._make_engine(tmp_path, deleg)
        steps = _make_steps(2)

        wf1 = engine.create("first", "First", steps)
        wf2 = engine.create("second", "Second", steps)
        engine.start(wf1.workflow_id)
        engine.start(wf2.workflow_id)

        # Should advance the oldest (first)
        result = engine.advance_next_active()
        assert result is not None

        loaded = store.get(wf1.workflow_id)
        assert loaded.current_step == 1

    def test_advance_next_active_no_running(self, tmp_path):
        engine, _ = self._make_engine(tmp_path)
        assert engine.advance_next_active() is None

    def test_get_workflow(self, tmp_path):
        engine, _ = self._make_engine(tmp_path)
        steps = _make_steps(1)
        wf = engine.create("test", "Test", steps)

        loaded = engine.get_workflow(wf.workflow_id)
        assert loaded is not None
        assert loaded.name == "test"

        assert engine.get_workflow("wf-nope") is None


# ========== DELEGATION TESTS ==========

class TestDelegationManager:

    def test_delegate_no_executors(self):
        dm = DelegationManager()
        step = WorkflowStep(order=0, action="learn", params={}, description="Test")
        result = dm.delegate(step)
        assert result.success is False
        assert "No executor available" in result.error

    def test_delegate_via_capability_router(self):
        dm = DelegationManager()

        class FakeRouter:
            def is_available(self, name):
                return name == "learn"
            def dispatch(self, plan):
                return {"success": True, "chunks": 3}

        class FakePlan:
            pass

        dm.set_capability_router(FakeRouter())
        dm.set_plan_factory(lambda action, params, gid: FakePlan())

        step = WorkflowStep(order=0, action="learn", params={}, description="Test")
        result = dm.delegate(step)
        assert result.success is True
        assert result.result["chunks"] == 3

    def test_delegate_via_task_executor(self):
        dm = DelegationManager()

        class FakeTaskResult:
            success = True
            task_id = "t-1"
            results = [{"ok": True}]
            errors = []

        class FakeExecutor:
            def execute_single(self, tool_name, tool_args, description, goal_id):
                return FakeTaskResult()

        dm.set_task_executor(FakeExecutor())

        step = WorkflowStep(
            order=0, action="wiki_search",
            params={"tool_name": "wiki_search", "tool_args": {"query": "AI"}},
            description="Search Wikipedia",
        )
        result = dm.delegate(step)
        assert result.success is True

    def test_delegate_exception_handled(self):
        dm = DelegationManager()

        class BrokenRouter:
            def is_available(self, name):
                return True
            def dispatch(self, plan):
                raise RuntimeError("Boom")

        dm.set_capability_router(BrokenRouter())
        dm.set_plan_factory(lambda a, p, g: object())

        step = WorkflowStep(order=0, action="learn", params={}, description="Test")
        result = dm.delegate(step)
        assert result.success is False
        assert "Boom" in result.error

    def test_can_delegate(self):
        dm = DelegationManager()
        assert dm.can_delegate("learn") is False

        class FakeRouter:
            def is_available(self, name):
                return name == "learn"

        dm.set_capability_router(FakeRouter())
        assert dm.can_delegate("learn") is True
        assert dm.can_delegate("unknown") is False


# ========== PROGRESS REPORTER TESTS ==========

class TestProgressReporter:

    def test_no_notifier_no_error(self):
        reporter = ProgressReporter()
        wf = create_workflow("test", "Test", _make_steps(1))
        # Should not raise
        reporter.on_workflow_started(wf)
        reporter.on_workflow_completed(wf)

    def test_telegram_notification(self):
        messages = []
        reporter = ProgressReporter()
        reporter.set_telegram_notifier(lambda msg: messages.append(msg))

        wf = create_workflow("test", "Test workflow", _make_steps(2))
        reporter.on_workflow_started(wf)

        assert len(messages) == 1
        assert "Workflow started" in messages[0]
        assert "test" in messages[0].lower() or "Test" in messages[0]

    def test_completion_notification(self):
        messages = []
        reporter = ProgressReporter()
        reporter.set_telegram_notifier(lambda msg: messages.append(msg))

        wf = create_workflow("test", "Test", _make_steps(2))
        wf.completed_at = time.time()
        reporter.on_workflow_completed(wf)

        assert len(messages) == 1
        assert "completed" in messages[0].lower()

    def test_failure_notification(self):
        messages = []
        reporter = ProgressReporter()
        reporter.set_telegram_notifier(lambda msg: messages.append(msg))

        wf = create_workflow("test", "Test", _make_steps(1))
        step = wf.steps[0]
        result = StepResult(order=0, action="learn", success=False, error="OOM")
        reporter.on_workflow_failed(wf, step, result)

        assert len(messages) == 1
        assert "FAILED" in messages[0]
        assert "OOM" in messages[0]

    def test_cooldown_prevents_spam(self):
        messages = []
        reporter = ProgressReporter()
        reporter.set_telegram_notifier(lambda msg: messages.append(msg))

        wf = create_workflow("test", "Test", _make_steps(3))
        step = wf.steps[0]
        result = StepResult(order=0, action="learn", success=True, duration_ms=100)

        # Rapid fire step completions
        reporter.on_step_completed(wf, step, result)
        reporter.on_step_completed(wf, step, result)
        reporter.on_step_completed(wf, step, result)

        # Only first should get through (cooldown 60s)
        assert len(messages) == 1

    def test_force_bypasses_cooldown(self):
        messages = []
        reporter = ProgressReporter()
        reporter.set_telegram_notifier(lambda msg: messages.append(msg))

        wf = create_workflow("test", "Test", _make_steps(1))
        wf.completed_at = time.time()

        # Completions are force=True, so both should go through
        reporter.on_workflow_completed(wf)
        reporter.on_workflow_completed(wf)
        assert len(messages) == 2

    def test_approval_needed_notification(self):
        messages = []
        reporter = ProgressReporter()
        reporter.set_telegram_notifier(lambda msg: messages.append(msg))

        wf = create_workflow("test", "Test", _make_steps(1))
        step = wf.steps[0]
        reporter.on_step_approval_needed(wf, step)

        assert len(messages) == 1
        assert "approval" in messages[0].lower()

    def test_perception_event_emitted(self):
        events = []

        class FakeBuffer:
            def add(self, event):
                events.append(event)

        reporter = ProgressReporter()
        reporter.set_perception_buffer(FakeBuffer())

        wf = create_workflow("test", "Test", _make_steps(1))
        reporter.on_workflow_started(wf)

        assert len(events) == 1

    def test_perception_without_buffer(self):
        reporter = ProgressReporter()
        wf = create_workflow("test", "Test", _make_steps(1))
        # Should not raise
        reporter.on_workflow_started(wf)


# ========== TEMPLATE TESTS ==========

class TestWorkflowTemplates:

    def test_research_workflow(self):
        steps = research_workflow("quantum physics")
        assert len(steps) == 3
        assert steps[0].action == "fetch"
        assert steps[1].action == "learn"
        assert steps[2].action == "exam"
        assert "quantum physics" in steps[0].params.get("topic", "")

    def test_deep_learn_workflow(self):
        steps = deep_learn_workflow("neural networks")
        assert len(steps) == 5
        actions = [s.action for s in steps]
        assert actions == ["fetch", "learn", "exam", "review", "exam"]

    def test_daily_review_workflow(self):
        steps = daily_review_workflow()
        assert len(steps) == 3
        actions = [s.action for s in steps]
        assert "evaluate" in actions
        assert "critique" in actions

    def test_system_health_workflow(self):
        steps = system_health_workflow()
        assert len(steps) == 3
        actions = [s.action for s in steps]
        assert "self_analyze" in actions

    def test_full_audit_workflow(self):
        steps = full_audit_workflow()
        assert len(steps) == 4
        actions = [s.action for s in steps]
        assert "validate" in actions

    def test_all_templates_have_ordered_steps(self):
        for name, tmpl in WORKFLOW_TEMPLATES.items():
            if tmpl["needs_topic"]:
                steps = tmpl["factory"]("test_topic")
            else:
                steps = tmpl["factory"]()
            orders = [s.order for s in steps]
            assert orders == sorted(orders), f"Template {name} steps not ordered"

    def test_template_registry_completeness(self):
        assert len(WORKFLOW_TEMPLATES) == 5
        for name, tmpl in WORKFLOW_TEMPLATES.items():
            assert "factory" in tmpl
            assert "description" in tmpl
            assert "needs_topic" in tmpl
            assert "estimated_minutes" in tmpl
            assert callable(tmpl["factory"])

    def test_all_steps_have_fail_policy(self):
        for name, tmpl in WORKFLOW_TEMPLATES.items():
            if tmpl["needs_topic"]:
                steps = tmpl["factory"]("test")
            else:
                steps = tmpl["factory"]()
            for step in steps:
                assert isinstance(step.on_fail, FailPolicy), \
                    f"Template {name} step {step.order} missing FailPolicy"


# ========== INTEGRATION TESTS ==========

class TestWorkflowIntegration:

    def test_full_workflow_lifecycle(self, tmp_path):
        """Create -> start -> advance through all steps -> complete."""
        deleg = FakeDelegation(success=True)
        store = _make_store(str(tmp_path))
        engine = WorkflowEngine(store, deleg)

        steps = research_workflow("AI")
        wf = engine.create("research_ai", "Research AI", steps)
        engine.start(wf.workflow_id)

        # Advance through all 3 steps
        for i in range(3):
            result = engine.advance(wf.workflow_id)
            assert result is not None

        loaded = store.get(wf.workflow_id)
        assert loaded.status == WorkflowStatus.COMPLETED
        assert len(loaded.results) == 3
        assert loaded.progress_pct == 100.0

    def test_workflow_with_mixed_results(self, tmp_path):
        """Workflow where some skip-on-fail steps fail."""
        call_count = [0]

        class MixedDelegation(DelegationManager):
            def delegate(self, step, goal_id=None, attempt=0):
                call_count[0] += 1
                # First step (fetch) fails
                success = step.action != "fetch"
                return StepResult(
                    order=step.order, action=step.action,
                    success=success,
                    error="no network" if not success else None,
                    duration_ms=10.0,
                )

        store = _make_store(str(tmp_path))
        engine = WorkflowEngine(store, MixedDelegation())

        steps = research_workflow("AI")  # fetch(skip) + learn + exam(skip)
        wf = engine.create("test", "Test", steps)
        engine.start(wf.workflow_id)

        # Step 0: fetch fails -> skip
        r0 = engine.advance(wf.workflow_id)
        assert r0.success is False

        # Step 1: learn succeeds
        r1 = engine.advance(wf.workflow_id)
        assert r1.success is True

        # Step 2: exam succeeds
        r2 = engine.advance(wf.workflow_id)
        assert r2.success is True

        loaded = store.get(wf.workflow_id)
        assert loaded.status == WorkflowStatus.COMPLETED

    def test_workflow_pause_resume_complete(self, tmp_path):
        """Pause mid-workflow, resume, complete."""
        deleg = FakeDelegation(success=True)
        store = _make_store(str(tmp_path))
        engine = WorkflowEngine(store, deleg)

        steps = _make_steps(3)
        wf = engine.create("test", "Test", steps)
        engine.start(wf.workflow_id)

        engine.advance(wf.workflow_id)  # Step 0
        engine.pause(wf.workflow_id)
        assert engine.advance(wf.workflow_id) is None  # Paused

        engine.resume(wf.workflow_id)
        engine.advance(wf.workflow_id)  # Step 1
        engine.advance(wf.workflow_id)  # Step 2

        loaded = store.get(wf.workflow_id)
        assert loaded.status == WorkflowStatus.COMPLETED

    def test_workflow_persists_across_restart(self, tmp_path):
        """Simulate restart: create engine, advance, recreate engine, continue."""
        path = os.path.join(str(tmp_path), "workflows.jsonl")

        # First "session"
        store1 = WorkflowStore(path=path)
        deleg1 = FakeDelegation(success=True)
        engine1 = WorkflowEngine(store1, deleg1)
        steps = _make_steps(3)
        wf = engine1.create("persist", "Persist test", steps)
        engine1.start(wf.workflow_id)
        engine1.advance(wf.workflow_id)  # Step 0

        wf_id = wf.workflow_id

        # "Restart" - new store, new engine
        store2 = WorkflowStore(path=path)
        deleg2 = FakeDelegation(success=True)
        engine2 = WorkflowEngine(store2, deleg2)

        # Recover interrupted (was RUNNING when "crashed")
        interrupted = store2.recover_interrupted()
        assert len(interrupted) == 1

        # Resume and continue
        engine2.resume(wf_id)
        engine2.advance(wf_id)  # Step 1
        engine2.advance(wf_id)  # Step 2

        loaded = store2.get(wf_id)
        assert loaded.status == WorkflowStatus.COMPLETED

    def test_workflow_with_progress_reporter(self, tmp_path):
        """Full lifecycle with progress reporter."""
        messages = []
        reporter = ProgressReporter()
        reporter.set_telegram_notifier(lambda msg: messages.append(msg))

        deleg = FakeDelegation(success=True)
        store = _make_store(str(tmp_path))
        engine = WorkflowEngine(store, deleg)
        engine.set_progress_reporter(reporter)

        steps = _make_steps(2)
        wf = engine.create("test", "Test", steps)
        engine.start(wf.workflow_id)
        engine.advance(wf.workflow_id)
        engine.advance(wf.workflow_id)

        # Should have: started + step_complete + completed
        assert len(messages) >= 2  # At least start + complete
        assert any("started" in m.lower() for m in messages)
        assert any("completed" in m.lower() for m in messages)
