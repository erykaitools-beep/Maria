"""
Tests for Phase 1: Decision Traceability.

Covers: episode_id generation, DecisionTrace model, TraceStore,
and episode_id propagation through LLM tape, K7, K10.
"""

import json
import threading
import time
from pathlib import Path

import pytest

from agent_core.tracing.episode import (
    generate_episode_id,
    current_episode_id,
    set_episode_id,
    clear_episode_id,
)
from agent_core.tracing.trace_model import DecisionTrace, TraceStep
from agent_core.tracing.trace_store import TraceStore


# -- Episode ID --------------------------------------------------


class TestEpisodeId:
    """Tests for episode ID generation and thread-local storage."""

    def test_generate_format(self):
        eid = generate_episode_id()
        assert eid.startswith("ep-")
        parts = eid.split("-")
        assert len(parts) == 3
        # timestamp hex + random hex
        assert len(parts[1]) >= 7
        assert len(parts[2]) == 8

    def test_generate_sets_current(self):
        clear_episode_id()
        assert current_episode_id() == ""
        eid = generate_episode_id()
        assert current_episode_id() == eid

    def test_set_and_clear(self):
        set_episode_id("ep-test-12345678")
        assert current_episode_id() == "ep-test-12345678"
        clear_episode_id()
        assert current_episode_id() == ""

    def test_unique(self):
        ids = {generate_episode_id() for _ in range(100)}
        assert len(ids) == 100

    def test_thread_isolation(self):
        """Each thread gets its own episode_id."""
        set_episode_id("ep-main-00000000")
        child_id = [None]

        def worker():
            child_id[0] = current_episode_id()
            generate_episode_id()
            child_id[0] = current_episode_id()

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        # Main thread should still have its ID
        assert current_episode_id() == "ep-main-00000000"
        # Child thread got its own ID
        assert child_id[0] != "ep-main-00000000"
        assert child_id[0].startswith("ep-")

    def teardown_method(self):
        clear_episode_id()


# -- TraceStep ---------------------------------------------------


class TestTraceStep:
    def test_to_dict(self):
        step = TraceStep(
            subsystem="k7_policy",
            action="check",
            result="blocked",
            detail={"reasons": ["rate_limited"]},
            timestamp=1000.0,
        )
        d = step.to_dict()
        assert d["subsystem"] == "k7_policy"
        assert d["result"] == "blocked"
        assert d["ts"] == 1000.0

    def test_from_dict(self):
        d = {"subsystem": "planner", "action": "goal_selected", "result": "ok", "ts": 1234.5}
        step = TraceStep.from_dict(d)
        assert step.subsystem == "planner"
        assert step.timestamp == 1234.5


# -- DecisionTrace -----------------------------------------------


class TestDecisionTrace:
    def test_add_step(self):
        trace = DecisionTrace(episode_id="ep-test-aabbccdd", started_at=time.time())
        trace.add_step("planner", "guard_check", "passed")
        trace.add_step("k7_policy", "check", "allowed")
        assert len(trace.steps) == 2
        assert trace.steps[0].subsystem == "planner"
        assert trace.steps[1].subsystem == "k7_policy"

    def test_finalize(self):
        trace = DecisionTrace(episode_id="ep-test-aabbccdd", started_at=time.time() - 0.5)
        trace.finalize(success=True, result_summary="LEARN completed")
        assert trace.success is True
        assert trace.finished_at > trace.started_at
        assert trace.duration_ms > 0

    def test_to_dict_round_trip(self):
        trace = DecisionTrace(
            episode_id="ep-test-aabbccdd",
            started_at=1000.0,
            tick_count=42,
            mode="active",
            health_score=0.95,
            goal_id="goal-123",
            goal_description="Nauka biologii",
            plan_id="plan-abc",
            action_type="learn",
            k7_decision="allow",
            k10_safety_mode="auto_commit",
            models_used=["llama3.1:8b"],
            total_llm_calls=2,
        )
        trace.add_step("planner", "execute", "ok")
        trace.finalize(success=True, result_summary="done")

        d = trace.to_dict()
        restored = DecisionTrace.from_dict(d)

        assert restored.episode_id == "ep-test-aabbccdd"
        assert restored.tick_count == 42
        assert restored.goal_id == "goal-123"
        assert restored.plan_id == "plan-abc"
        assert restored.k7_decision == "allow"
        assert len(restored.steps) == 1
        assert restored.success is True

    def test_to_compact(self):
        trace = DecisionTrace(
            episode_id="ep-66e5a1f0-3b7c9a1d",
            started_at=1000.0,
            goal_description="Nauka biologii",
            action_type="learn",
            duration_ms=245.3,
            total_llm_calls=2,
            success=True,
        )
        compact = trace.to_compact()
        assert "LEARN" in compact
        assert "Nauka biologii" in compact
        assert "OK" in compact
        assert "245ms" in compact
        assert "2 LLM" in compact

    def test_to_compact_blocked(self):
        trace = DecisionTrace(
            episode_id="ep-66e5a1f0-3b7c9a1d",
            started_at=1000.0,
            action_type="fetch",
            k7_decision="block",
            duration_ms=5.0,
            success=False,
        )
        compact = trace.to_compact()
        assert "FETCH" in compact
        assert "FAIL" in compact
        assert "K7:block" in compact


# -- TraceStore --------------------------------------------------


class TestTraceStore:
    def test_record_and_get_recent(self, tmp_path):
        store = TraceStore(path=tmp_path / "traces.jsonl")
        trace = DecisionTrace(episode_id="ep-test-11111111", started_at=1000.0)
        trace.finalize(success=True, result_summary="ok")
        store.record(trace)

        recent = store.get_recent(limit=5)
        assert len(recent) == 1
        assert recent[0]["episode_id"] == "ep-test-11111111"

    def test_persistence(self, tmp_path):
        path = tmp_path / "traces.jsonl"
        store1 = TraceStore(path=path)
        for i in range(3):
            t = DecisionTrace(episode_id=f"ep-test-{i:08d}", started_at=1000.0 + i)
            t.finalize(success=True)
            store1.record(t)

        # New store reads from file
        store2 = TraceStore(path=path)
        recent = store2.get_recent(limit=10)
        assert len(recent) == 3

    def test_get_by_episode_id(self, tmp_path):
        store = TraceStore(path=tmp_path / "traces.jsonl")
        t1 = DecisionTrace(episode_id="ep-find-me000000", started_at=1000.0)
        t1.finalize(success=True)
        t2 = DecisionTrace(episode_id="ep-not-me000000", started_at=1001.0)
        t2.finalize(success=False)
        store.record(t1)
        store.record(t2)

        found = store.get_by_episode_id("ep-find-me000000")
        assert found is not None
        assert found["episode_id"] == "ep-find-me000000"

        not_found = store.get_by_episode_id("ep-doesnt-exist")
        assert not_found is None

    def test_get_by_goal_id(self, tmp_path):
        store = TraceStore(path=tmp_path / "traces.jsonl")
        t1 = DecisionTrace(episode_id="ep-g1-00000001", started_at=1000.0, goal_id="goal-abc")
        t1.finalize(success=True)
        t2 = DecisionTrace(episode_id="ep-g2-00000002", started_at=1001.0, goal_id="goal-xyz")
        t2.finalize(success=True)
        t3 = DecisionTrace(episode_id="ep-g3-00000003", started_at=1002.0, goal_id="goal-abc")
        t3.finalize(success=False)
        store.record(t1)
        store.record(t2)
        store.record(t3)

        results = store.get_by_goal_id("goal-abc")
        assert len(results) == 2

    def test_get_failed(self, tmp_path):
        store = TraceStore(path=tmp_path / "traces.jsonl")
        for i in range(5):
            t = DecisionTrace(episode_id=f"ep-fail-{i:08d}", started_at=1000.0 + i)
            t.finalize(success=(i % 2 == 0))
            store.record(t)

        failed = store.get_failed(limit=10)
        assert len(failed) == 2
        assert all(f["success"] is False for f in failed)

    def test_get_stats(self, tmp_path):
        store = TraceStore(path=tmp_path / "traces.jsonl")
        for i in range(10):
            t = DecisionTrace(
                episode_id=f"ep-stat-{i:08d}",
                started_at=1000.0 + i,
                action_type="learn" if i < 6 else "fetch",
                total_llm_calls=2,
                k7_decision="block" if i == 3 else "allow",
            )
            t.finalize(success=(i != 3))
            t.duration_ms = 100.0 + i * 10
            store.record(t)

        stats = store.get_stats()
        assert stats["total"] == 10
        assert stats["success"] == 9
        assert stats["failed"] == 1
        assert stats["total_llm_calls"] == 20
        assert stats["k7_blocks"] == 1
        assert "learn" in stats["action_types"]
        assert "fetch" in stats["action_types"]

    def test_bounded_memory(self, tmp_path):
        store = TraceStore(path=tmp_path / "traces.jsonl")
        for i in range(250):
            t = DecisionTrace(episode_id=f"ep-bound-{i:08d}", started_at=1000.0 + i)
            t.finalize(success=True)
            store.record(t)

        # Memory should be bounded
        recent = store.get_recent(limit=300)
        assert len(recent) <= 200

    def test_thread_safety(self, tmp_path):
        store = TraceStore(path=tmp_path / "traces.jsonl")
        errors = []

        def writer(n):
            try:
                for i in range(20):
                    t = DecisionTrace(
                        episode_id=f"ep-t{n}-{i:08d}",
                        started_at=time.time(),
                    )
                    t.finalize(success=True)
                    store.record(t)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        recent = store.get_recent(limit=200)
        assert len(recent) == 100  # 5 threads * 20 each


# -- Integration: episode_id propagation -------------------------


class TestEpisodeIdPropagation:
    """Test that episode_id flows into LLM tape and K7/K10 records."""

    def test_llm_tape_entry_auto_reads_episode(self):
        from agent_core.llm.llm_tape import make_tape_entry
        set_episode_id("ep-llm-test0000")
        entry = make_tape_entry(
            model="llama3.1:8b",
            role="planner",
            prompt="test prompt",
            response="test response",
            latency_ms=100.0,
        )
        assert entry.episode_id == "ep-llm-test0000"
        d = entry.to_dict()
        assert d["episode_id"] == "ep-llm-test0000"
        clear_episode_id()

    def test_llm_tape_entry_no_episode(self):
        from agent_core.llm.llm_tape import make_tape_entry
        clear_episode_id()
        entry = make_tape_entry(
            model="llama3.1:8b",
            role="chat",
            prompt="hello",
            response="world",
            latency_ms=50.0,
        )
        assert entry.episode_id == ""
        d = entry.to_dict()
        # Empty episode_id should be omitted from dict
        assert "episode_id" not in d

    def test_k7_escalation_auto_reads_episode(self):
        from agent_core.autonomy.escalation import EscalationHandler
        set_episode_id("ep-k7-test00000")
        handler = EscalationHandler(log_path=Path("/dev/null"))
        result = handler.handle(
            action_type="fetch",
            decision="block",
            reasons=["rate_limited"],
        )
        # Check the recent record has episode_id
        recent = handler.get_recent(limit=1)
        assert len(recent) == 1
        assert recent[0].get("episode_id") == "ep-k7-test00000"
        clear_episode_id()

    def test_k10_action_record_auto_reads_episode(self):
        from agent_core.action_safety.safety_model import (
            create_action_record, SafetyProfile, SafetyMode,
            Reversibility, EffectType,
        )
        set_episode_id("ep-k10-test0000")
        profile = SafetyProfile(
            safety_mode=SafetyMode.AUTO_COMMIT,
            reversibility=Reversibility.REVERSIBLE,
            effect_type=EffectType.KNOWLEDGE,
            needs_before_snapshot=False,
            needs_after_snapshot=False,
        )
        record = create_action_record(
            plan_id="plan-test123",
            action_type="learn",
            profile=profile,
        )
        assert record.episode_id == "ep-k10-test0000"
        d = record.to_dict()
        assert d["episode_id"] == "ep-k10-test0000"
        clear_episode_id()

    def test_k10_action_record_no_episode(self):
        from agent_core.action_safety.safety_model import (
            create_action_record, SafetyProfile, SafetyMode,
            Reversibility, EffectType,
        )
        clear_episode_id()
        profile = SafetyProfile(
            safety_mode=SafetyMode.AUDIT_ONLY,
            reversibility=Reversibility.IRREVERSIBLE,
            effect_type=EffectType.EXTERNAL_API,
            needs_before_snapshot=True,
            needs_after_snapshot=True,
        )
        record = create_action_record(
            plan_id="plan-test456",
            action_type="fetch",
            profile=profile,
        )
        assert record.episode_id == ""
        d = record.to_dict()
        # Empty episode_id should be omitted
        assert "episode_id" not in d

    def teardown_method(self):
        clear_episode_id()
