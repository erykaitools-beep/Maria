"""
Tests for Faza 5: Workflow Orchestration.

Covers: model, store, engine, delegation, templates, progress reporter.
"""

import json
import os
import tempfile
import threading
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


def _real_policy(tmp_path):
    """A REAL AutonomyPolicy (K7), logging into tmp_path.

    Deliberately the production class, not a stand-in that answers "allowed" to
    everything: these tests are the only proof the workflow path is actually
    governed, and a stand-in would prove only that the stand-in says yes. The
    log path is redirected so a test run never appends to the live daemon's
    autonomy decisions.
    """
    from agent_core.autonomy import AutonomyPolicy
    return AutonomyPolicy(log_path=tmp_path / "autonomy_decisions.jsonl")


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

    def test_save_surfaces_persistence_failure(self, tmp_path, monkeypatch):
        store = _make_store(str(tmp_path))
        wf = create_workflow("persist", "Persist", _make_steps(1))

        def fail_append(_workflow):
            raise OSError("disk unavailable")

        monkeypatch.setattr(store, "_append", fail_append)
        with pytest.raises(OSError, match="disk unavailable"):
            store.save(wf)
        assert store.get(wf.workflow_id) is None


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

    def test_step_cannot_be_preapproved_or_approved_for_the_wrong_order(self, tmp_path):
        engine, _store = self._make_engine(tmp_path)
        steps = [
            WorkflowStep(
                order=0,
                action="effector",
                params={"target": "exact"},
                description="Needs approval",
                requires_approval=True,
            )
        ]
        wf = engine.create("test", "Test", steps)

        assert engine.approve_step(wf.workflow_id, 0) is False
        engine.start(wf.workflow_id)
        assert engine.approve_step(wf.workflow_id, 0) is False
        engine.advance(wf.workflow_id)
        assert engine.approve_step(wf.workflow_id, 1) is False
        assert engine.approve_step(wf.workflow_id, 0) is True

    def test_cancel_during_delegate_cannot_be_overwritten_by_late_success(self, tmp_path):
        entered = threading.Event()
        release = threading.Event()

        class BlockingDelegation(DelegationManager):
            def delegate(self, step, goal_id=None, attempt=0):
                entered.set()
                assert release.wait(timeout=3)
                return StepResult(order=step.order, action=step.action, success=True)

        engine, store = self._make_engine(tmp_path, BlockingDelegation())
        wf = engine.create("race", "Race", _make_steps(1))
        engine.start(wf.workflow_id)
        worker = threading.Thread(target=engine.advance, args=(wf.workflow_id,))
        worker.start()
        assert entered.wait(timeout=3)

        assert engine.cancel(wf.workflow_id, "operator stop") is True
        release.set()
        worker.join(timeout=3)

        loaded = store.get(wf.workflow_id)
        assert loaded.status == WorkflowStatus.CANCELLED
        assert loaded.current_step == 0
        assert loaded.results == []

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

    def test_delegate_via_capability_router(self, tmp_path):
        dm = DelegationManager()
        dm.set_autonomy_policy(_real_policy(tmp_path))

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

    def test_delegate_via_task_executor(self, tmp_path):
        dm = DelegationManager()
        dm.set_autonomy_policy(_real_policy(tmp_path))

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

    def test_delegate_exception_handled(self, tmp_path):
        dm = DelegationManager()
        dm.set_autonomy_policy(_real_policy(tmp_path))

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


# ========== K7 GATE ON THE WORKFLOW PATH (2026-07-21) ==========

class RecordingRouter:
    """CapabilityRouter stand-in that remembers whether it was reached."""

    def __init__(self, action="fetch"):
        self.action = action
        self.dispatched = []

    def is_available(self, name):
        return name == self.action

    def dispatch(self, plan):
        self.dispatched.append(plan)
        return {"success": True, "reached": True}


class RecordingExecutor:
    """TaskExecutor stand-in that remembers whether it was reached."""

    def __init__(self):
        self.calls = []

    def execute_single(self, tool_name, tool_args, description, goal_id):
        self.calls.append(tool_name)

        class R:
            success = True
            task_id = "t-1"
            results = []
            errors = []
        return R()


def _blocking_policy(tmp_path):
    """REAL AutonomyPolicy that genuinely refuses `fetch`.

    Built by giving the real rate limiter a budget of zero for that action
    rather than by stubbing check() -- the refusal travels the same code path a
    live refusal would, including the blocked_result payload shape. `fetch` is
    GUARDED, the tier the limiter actually consults (it is a no-op for
    ANALYTICAL -- see af47933).
    """
    from agent_core.autonomy import AutonomyPolicy
    from agent_core.autonomy.rate_limiter import ActionRateLimiter
    return AutonomyPolicy(
        rate_limiter=ActionRateLimiter(limits={"fetch": 0, "effector": 0}),
        log_path=tmp_path / "autonomy_decisions.jsonl",
    )


class TestDelegationK7Gate:
    """The workflow path must not reach the world below the K7 gate.

    Before 2026-07-21 it did: delegate() -> CapabilityRouter.dispatch() with no
    check and no rate-limiter record, so a workflow step could fs_write, drive
    the effector or fetch while the planner doing the same action was governed.
    """

    def test_unwired_policy_refuses_instead_of_passing(self):
        """Fail-closed: no gate wired == closed door, not open one."""
        dm = DelegationManager()
        router = RecordingRouter()
        dm.set_capability_router(router)
        dm.set_plan_factory(lambda a, p, g: object())

        step = WorkflowStep(order=0, action="fetch", params={}, description="x")
        result = dm.delegate(step)

        assert result.success is False
        assert result.result["blocked_by"] == "autonomy_policy"
        assert router.dispatched == [], "router was reached without a gate"

    def test_blocked_step_does_not_fall_through_to_task_executor(self, tmp_path):
        """A refusal must end the step -- not demote it to the other executor.

        This is the regression that matters most: if the gate returned None
        (= "not my job") instead of a refusal, delegate() would simply try the
        TaskExecutor next, and the blocked action would run anyway through the
        second door.
        """
        dm = DelegationManager()
        dm.set_autonomy_policy(_blocking_policy(tmp_path))
        router = RecordingRouter()
        executor = RecordingExecutor()
        dm.set_capability_router(router)
        dm.set_plan_factory(lambda a, p, g: object())
        dm.set_task_executor(executor)

        step = WorkflowStep(order=0, action="fetch", params={}, description="x")
        result = dm.delegate(step)

        assert result.success is False
        assert result.result["blocked_by"] == "autonomy_policy"
        assert router.dispatched == []
        assert executor.calls == [], "K7 refusal leaked into the TaskExecutor"

    def test_allowed_step_reaches_router_and_spends_its_budget(self, tmp_path):
        """Allowed action runs AND is recorded, so the limiter can see us.

        Proven through observable behaviour rather than by peeking at counters:
        with a budget of exactly one, a second identical step must be refused.
        If the workflow path skipped record_execution -- as it did before this
        change -- the budget would never run down and the second step would
        sail through.
        """
        from agent_core.autonomy import AutonomyPolicy
        from agent_core.autonomy.rate_limiter import ActionRateLimiter
        policy = AutonomyPolicy(
            rate_limiter=ActionRateLimiter(limits={"fetch": 1}),
            log_path=tmp_path / "autonomy_decisions.jsonl",
        )
        dm = DelegationManager()
        dm.set_autonomy_policy(policy)
        router = RecordingRouter()
        dm.set_capability_router(router)
        dm.set_plan_factory(lambda a, p, g: object())

        step = WorkflowStep(order=0, action="fetch", params={}, description="x")

        first = dm.delegate(step)
        assert first.success is True
        assert len(router.dispatched) == 1

        second = dm.delegate(step)
        assert second.success is False, "rate limiter is blind to workflow runs"
        assert second.result["blocked_by"] == "autonomy_policy"
        assert len(router.dispatched) == 1

    def test_task_executor_path_is_gated_too(self, tmp_path):
        """The tool door is governed as well -- it reaches net and disk."""
        dm = DelegationManager()
        dm.set_autonomy_policy(_blocking_policy(tmp_path))
        executor = RecordingExecutor()
        dm.set_task_executor(executor)

        step = WorkflowStep(
            order=0, action="web_fetch",
            params={"tool_name": "web_fetch", "tool_args": {"url": "x"}},
            description="x",
        )
        result = dm.delegate(step)

        assert result.success is False
        assert result.result["blocked_by"] == "autonomy_policy"
        assert executor.calls == []

    def test_unclassified_tool_is_refused(self, tmp_path):
        """A tool nobody mapped must not ride through on the day it appears.

        Unmapped tools are gated as `effector`, which the authority rule refuses
        on this path. That is the designed answer: registering a tool has to be
        accompanied by a deliberate classification in TOOL_GATE_ACTIONS.
        """
        dm = DelegationManager()
        dm.set_autonomy_policy(_real_policy(tmp_path))
        executor = RecordingExecutor()
        dm.set_task_executor(executor)

        step = WorkflowStep(
            order=0, action="brand_new_tool",
            params={"tool_name": "brand_new_tool"}, description="x",
        )
        result = dm.delegate(step)

        assert result.success is False
        assert result.result["blocked_by"] == "autonomy_policy"
        assert executor.calls == []

    def test_fs_write_honours_its_env_flag(self, tmp_path, monkeypatch):
        """FS_WRITE_ENABLED was enforced in the planner only.

        The workflow path reached the same effector, so a step could write to
        disk while the flag said no. `.env` is loaded at import time in this
        project, so the flag is cleared explicitly rather than assumed absent.
        """
        monkeypatch.delenv("FS_WRITE_ENABLED", raising=False)
        monkeypatch.setenv("FS_WRITE_ENABLED", "false")

        dm = DelegationManager()
        dm.set_autonomy_policy(_real_policy(tmp_path))
        router = RecordingRouter(action="fs_write")
        dm.set_capability_router(router)
        dm.set_plan_factory(lambda a, p, g: object())

        step = WorkflowStep(order=0, action="fs_write",
                            params={"path": "x.md"}, description="x")
        blocked = dm.delegate(step)
        assert blocked.success is False
        assert blocked.result["blocked_by"] == "fs_write_disabled"
        assert router.dispatched == []

        monkeypatch.setenv("FS_WRITE_ENABLED", "true")
        allowed = dm.delegate(step)
        assert allowed.success is True, (
            "flag on should restore the path, else this is a dead branch")
        assert len(router.dispatched) == 1

    def test_state_provider_feeds_live_mode_to_the_gate(self, tmp_path):
        """The gate must judge against the organism's real state, not 'active'.

        K7 rules are mode-aware, so a static default would ask the gate an
        easier question than the planner asks it.
        """
        seen = {}

        class SpyPolicy:
            def check(self, action_type, action_params, goal_id,
                      health_score, mode):
                seen["health"] = health_score
                seen["mode"] = mode

                class R:
                    allowed = True
                    rule_name = None
                    blocked_result = None
                return R()

            def record_execution(self, action_type, success):
                pass

        dm = DelegationManager()
        dm.set_autonomy_policy(SpyPolicy())
        dm.set_state_provider(lambda: (0.42, "sleep"))
        router = RecordingRouter()
        dm.set_capability_router(router)
        dm.set_plan_factory(lambda a, p, g: object())

        dm.delegate(WorkflowStep(order=0, action="fetch", params={},
                                 description="x"))
        assert seen == {"health": 0.42, "mode": "sleep"}

    def test_exploding_state_provider_is_a_closed_door(self, tmp_path):
        dm = DelegationManager()
        dm.set_autonomy_policy(_real_policy(tmp_path))
        dm.set_state_provider(lambda: (_ for _ in ()).throw(RuntimeError("offline")))
        router = RecordingRouter()
        dm.set_capability_router(router)
        dm.set_plan_factory(lambda a, p, g: object())

        result = dm.delegate(
            WorkflowStep(order=0, action="fetch", params={}, description="x")
        )

        assert result.success is False
        assert result.result["blocked_by"] == "state_unavailable"
        assert router.dispatched == []

    def test_exploding_gate_is_a_closed_door(self, tmp_path):
        """If the gate itself raises, refuse -- never fall through."""
        class ExplodingPolicy:
            def check(self, **kwargs):
                raise RuntimeError("gate on fire")

            def record_execution(self, action_type, success):
                pass

        dm = DelegationManager()
        dm.set_autonomy_policy(ExplodingPolicy())
        router = RecordingRouter()
        dm.set_capability_router(router)
        dm.set_plan_factory(lambda a, p, g: object())

        result = dm.delegate(
            WorkflowStep(order=0, action="fetch", params={}, description="x"))

        assert result.success is False
        assert result.result["blocked_by"] == "autonomy_policy"
        assert router.dispatched == []

    def test_opt_out_is_explicit(self, tmp_path):
        """Tests of the state machine may skip the gate -- loudly, on purpose."""
        dm = DelegationManager()
        dm.disable_k7_gate("unit test of the state machine")
        router = RecordingRouter()
        dm.set_capability_router(router)
        dm.set_plan_factory(lambda a, p, g: object())

        result = dm.delegate(
            WorkflowStep(order=0, action="fetch", params={}, description="x"))
        assert result.success is True
        assert len(router.dispatched) == 1


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

    def test_release_blocker_is_not_reported_as_success(self):
        messages = []
        reporter = ProgressReporter()
        reporter.set_telegram_notifier(messages.append)
        wf = create_workflow("model_release_audit", "Audit", _make_steps(1))
        wf.results.append(
            StepResult(
                order=0,
                action="publishable_release_gate",
                success=True,
                result={"results": [{"release_ready": False}]},
            )
        )
        wf.completed_at = time.time()

        reporter.on_workflow_completed(wf)

        assert "RELEASE BLOCKED" in messages[0]
        assert "Success rate" not in messages[0]

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

    def test_homeostasis_wiring_targets_bot_send_message(self):
        """Regression: the homeostasis wiring must send via bridge.bot.send_message,
        NOT bridge.send_message (which does not exist -> hasattr False -> silent
        no-op, so workflow progress was never delivered).

        Uses a REAL TelegramBridge with a fake bot. A MagicMock bridge would
        auto-create a .send_message attribute and hide the bug entirely.
        """
        from agent_core.telegram import TelegramBridge

        class _FakeBot:
            def __init__(self):
                self.calls = []

            def send_message(self, text, parse_mode="Markdown", chat_id=None):
                self.calls.append((text, parse_mode))
                return True

        fake_bot = _FakeBot()
        bridge = TelegramBridge(bot=fake_bot)

        # The crux of the bug: send_message is on .bot, not on the bridge.
        assert not hasattr(bridge, "send_message")
        assert hasattr(bridge.bot, "send_message")

        reporter = ProgressReporter()
        # SAME wiring expression as homeostasis_module.py
        reporter.set_telegram_notifier(
            lambda msg: bridge.bot.send_message(msg, parse_mode=None)
        )

        wf = create_workflow("recon", "Recon", _make_steps(2))
        wf.completed_at = time.time()
        reporter.on_workflow_completed(wf)  # force=True -> no cooldown

        assert len(fake_bot.calls) == 1
        text, parse_mode = fake_bot.calls[0]
        assert "Workflow completed: recon" in text
        assert parse_mode is None  # avoids Markdown choking on underscores


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
