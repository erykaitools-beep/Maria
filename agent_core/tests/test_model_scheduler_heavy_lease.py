"""Tests for ModelScheduler.heavy_lease() and its wiring.

heavy_lease() is the Krok-1 "connect": it makes the heavy LOCAL inference paths
that call Ollama directly -- the exam STUDENT answer, the exam author/grader
local fallback, and the learn/_ask_once local fallback -- serialize on the SAME
heavy mutex as ask_as_role()/ensure_ready(), instead of bypassing it. That bypass
was the confirmed mechanism of the exam-answer || planner contention storms (two
heavy local models thrashing one GPU-less CPU).

The lease is flag-gated by SCHEDULER_ENFORCE_MUTEX so the wiring ships inert and
is enabled + OBSERVED before cutover. These tests set the flag ON to verify the
serialization and OFF to verify the no-op.
"""

import threading
import time
from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from agent_core.llm.model_scheduler import ModelScheduler, _mutex_enforced


@pytest.fixture
def scheduler(tmp_path):
    return ModelScheduler(health_path=str(tmp_path / "model_health.json"))


@pytest.fixture
def enforce(monkeypatch):
    """Turn mutex enforcement ON for the duration of a test."""
    monkeypatch.setenv("SCHEDULER_ENFORCE_MUTEX", "1")


class _RecordingScheduler:
    """Stand-in scheduler whose heavy_lease records enter/exit, for wiring tests."""

    def __init__(self, events):
        self._events = events

    @contextmanager
    def heavy_lease(self, label="", timeout_s=120.0):
        self._events.append(("enter", label))
        try:
            yield
        finally:
            self._events.append(("exit", label))


# ============================================================
# FLAG GATING
# ============================================================

class TestHeavyLeaseFlag:
    def test_noop_when_flag_off(self, scheduler, monkeypatch):
        """Flag OFF (default): the lease does NOT take the heavy lock."""
        monkeypatch.delenv("SCHEDULER_ENFORCE_MUTEX", raising=False)
        with scheduler.heavy_lease("test"):
            # Lock is free -> a non-blocking acquire from "another caller" succeeds.
            assert scheduler._heavy_lock.acquire(blocking=False) is True
            scheduler._heavy_lock.release()

    def test_holds_lock_when_flag_on(self, scheduler, enforce):
        """Flag ON: the heavy lock is held for the duration of the lease."""
        with scheduler.heavy_lease("test"):
            # Held -> a non-blocking acquire fails.
            assert scheduler._heavy_lock.acquire(blocking=False) is False
        # Released after the with-block.
        assert scheduler._heavy_lock.acquire(blocking=False) is True
        scheduler._heavy_lock.release()

    def test_flag_truthy_and_falsy_values(self, monkeypatch):
        for v in ("1", "true", "yes", "on", "TRUE", "On", " 1 "):
            monkeypatch.setenv("SCHEDULER_ENFORCE_MUTEX", v)
            assert _mutex_enforced() is True, v
        for v in ("0", "false", "no", "off", "", "nope"):
            monkeypatch.setenv("SCHEDULER_ENFORCE_MUTEX", v)
            assert _mutex_enforced() is False, v

    def test_flag_unset_is_off(self, monkeypatch):
        monkeypatch.delenv("SCHEDULER_ENFORCE_MUTEX", raising=False)
        assert _mutex_enforced() is False


# ============================================================
# SERIALIZATION (the actual cure)
# ============================================================

class TestHeavyLeaseSerialization:
    def test_four_threads_never_overlap(self, scheduler, enforce):
        """Four heavy leases on separate threads run strictly one-at-a-time."""
        inside_snapshots = []
        live = {"n": 0}
        cl = threading.Lock()

        def worker():
            with scheduler.heavy_lease("w"):
                with cl:
                    live["n"] += 1
                    inside_snapshots.append(live["n"])
                time.sleep(0.03)
                with cl:
                    live["n"] -= 1

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Concurrency never exceeded 1 -> the mutex serialized every worker.
        assert max(inside_snapshots) == 1
        assert len(inside_snapshots) == 4

    def test_lease_waits_for_external_heavy_hold(self, scheduler, enforce):
        """A lease blocks while the SAME mutex is held outside heavy_lease().

        Simulates ask_as_role()/ensure_ready() holding _heavy_lock across its
        inference span: a lease on another thread must wait until that hold is
        released, proving both mechanisms share ONE lock (<=1 heavy local total).
        """
        scheduler._heavy_lock.acquire()  # stand in for an in-flight ask_as_role
        entered = threading.Event()

        def worker():
            with scheduler.heavy_lease("w", timeout_s=5.0):
                entered.set()

        t = threading.Thread(target=worker)
        t.start()
        try:
            # Must NOT enter while the external hold is active.
            assert not entered.wait(timeout=0.3)
            scheduler._heavy_lock.release()
            # Now the lease can proceed.
            assert entered.wait(timeout=2.0)
        finally:
            t.join()


# ============================================================
# REENTRANCY (don't self-deadlock on a non-reentrant Lock)
# ============================================================

class TestHeavyLeaseReentrancy:
    def test_nested_lease_same_thread_no_deadlock(self, scheduler, enforce):
        """A lease nested in another lease on the SAME thread must not deadlock."""
        reached_inner = {"ok": False}
        with scheduler.heavy_lease("outer"):
            with scheduler.heavy_lease("inner"):
                reached_inner["ok"] = True
            # Still inside outer: the lock is still held by us.
            assert scheduler._heavy_lock.acquire(blocking=False) is False
        assert reached_inner["ok"] is True
        # Fully released after outer exits.
        assert scheduler._heavy_lock.acquire(blocking=False) is True
        scheduler._heavy_lock.release()


# ============================================================
# RESILIENCE (degrade, never wedge the tick)
# ============================================================

class TestHeavyLeaseResilience:
    def test_timeout_degrades_to_unguarded(self, scheduler, enforce):
        """If the mutex can't be acquired in time, the lease proceeds anyway."""
        scheduler._heavy_lock.acquire()  # never released here -> lease must time out
        try:
            entered = {"ok": False}
            t0 = time.time()
            with scheduler.heavy_lease("w", timeout_s=0.2):
                entered["ok"] = True
            elapsed = time.time() - t0
            assert entered["ok"] is True   # proceeded despite contention (no deadlock)
            assert elapsed >= 0.15         # but waited out the budget first
        finally:
            scheduler._heavy_lock.release()

    def test_lock_released_on_exception(self, scheduler, enforce):
        """An exception inside the lease still releases the mutex."""
        with pytest.raises(ValueError):
            with scheduler.heavy_lease("w"):
                raise ValueError("boom")
        # Not left locked.
        assert scheduler._heavy_lock.acquire(blocking=False) is True
        scheduler._heavy_lock.release()

    def test_noop_path_release_safe_after_exception(self, scheduler, monkeypatch):
        """Flag OFF + exception: no spurious release of a lock we never took."""
        monkeypatch.delenv("SCHEDULER_ENFORCE_MUTEX", raising=False)
        with pytest.raises(ValueError):
            with scheduler.heavy_lease("w"):
                raise ValueError("boom")
        # Lock was never taken and is still free.
        assert scheduler._heavy_lock.acquire(blocking=False) is True
        scheduler._heavy_lock.release()


# ============================================================
# WIRING (the lease is actually reached by the connected paths)
# ============================================================

class TestRouterSchedulerAccessor:
    def test_get_model_scheduler_roundtrip(self):
        from agent_core.llm.router import LLMRouter
        r = LLMRouter(ollama_brain=Mock())
        assert r.get_model_scheduler() is None
        sentinel = object()
        r.set_model_scheduler(sentinel)
        assert r.get_model_scheduler() is sentinel


class TestExamExaminerWiring:
    def test_local_grader_fallback_runs_inside_heavy_lease(self, monkeypatch):
        """The exam grader's LOCAL fallback executes within scheduler.heavy_lease()."""
        from agent_core.modules import teacher_module

        # Force the local fallback: no NIM key -> nim stays None -> _run goes local.
        monkeypatch.setattr("maria_core.sys.config.NVIDIA_NIM_API_KEY", "")
        monkeypatch.setattr(
            "maria_core.learning.llm_utils.call_ollama",
            lambda *a, **k: "LOCAL_GRADE",
        )

        events = []
        sched = _RecordingScheduler(events)
        grader = teacher_module._make_exam_grader_fn("qwen3:8b", scheduler=sched)

        out = grader("grade this answer")

        assert out == "LOCAL_GRADE"
        # The local call happened strictly between the lease enter and exit.
        assert events == [("enter", "exam_grader_local"), ("exit", "exam_grader_local")]

    def test_examiner_fallback_no_lease_when_scheduler_absent(self, monkeypatch):
        """Without a scheduler the fallback still works (degrades to no lease)."""
        from agent_core.modules import teacher_module

        monkeypatch.setattr("maria_core.sys.config.NVIDIA_NIM_API_KEY", "")
        monkeypatch.setattr(
            "maria_core.learning.llm_utils.call_ollama",
            lambda *a, **k: "LOCAL_AUTHOR",
        )

        author = teacher_module._make_exam_author_fn("qwen3:8b", scheduler=None)
        assert author("write questions") == "LOCAL_AUTHOR"
