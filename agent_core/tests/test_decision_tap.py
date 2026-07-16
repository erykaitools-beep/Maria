"""Tests for the CEGLA 2 decision tap (observability of planner K5).

Guards the two pre-arming fixes from the adversarial wiring review:
  1. PEEK-SAFETY -- is_action_backed_off(peek=True) must NOT evict TTL-expired
     entries (an eviction perturbs strategic_planner's TTL-blind backed_off list).
  2. SCHEMA FIDELITY -- the per-candidate frame MUST carry goal.description, the
     one rule-read field (is_saturation_meta / F_meta) that is irrecoverable once
     a week of frames is written without it.
Plus the flag-gate (OFF -> zero writes) and basic frame shape.
"""
import json
import time

import pytest

from agent_core.planner.planner_core import PlannerCore
from agent_core.planner.decision_tap import DecisionTap, build_frame
from agent_core.goals.goal_model import Goal, GoalType, GoalStatus


def _goal(gid="g-meta", gtype=GoalType.META, desc="czy juz umiem funding rate?"):
    now = time.time()
    return Goal(
        id=gid, type=gtype, description=desc, priority=0.5,
        status=GoalStatus.ACTIVE, progress=0.0, parent_goal_id=None,
        created_by="system", created_at=now, updated_at=now,
    )


class TestPeekSafety:
    """Fix #1: peek=True is read-only over the live _action_failures dict."""

    def test_peek_does_not_evict_expired_entry(self):
        pc = PlannerCore()
        pc._FAILURE_MEMORY_TTL = 0.01
        for _ in range(3):
            pc.record_action_failure("learn", "g-1")
        time.sleep(0.02)  # let TTL expire
        key = pc._action_key("learn", "g-1")

        # peek MUST report expired-as-not-backed-off WITHOUT deleting the entry
        assert pc.is_action_backed_off("learn", "g-1", peek=True) is False
        assert key in pc._action_failures, "peek evicted a live entry -> observer effect"

        # the default (mutating) path still evicts -- unchanged behaviour
        assert pc.is_action_backed_off("learn", "g-1") is False
        assert key not in pc._action_failures

    def test_peek_matches_value_for_active_backoff(self):
        pc = PlannerCore()
        for _ in range(3):
            pc.record_action_failure("learn", "g-1")
        key = pc._action_key("learn", "g-1")
        assert pc.is_action_backed_off("learn", "g-1", peek=True) is True
        assert pc.is_action_backed_off("learn", "g-1") is True
        assert key in pc._action_failures  # never removed while active


class TestFrameSchema:
    """Fix #2 + flag-gate: description is captured; OFF writes nothing."""

    def _isolate_live_queries(self, pc):
        # Neutralise the noisy live-subsystem queries so the test targets the
        # candidate-dict construction (the schema), not world_model/topic pickers.
        pc._find_weak_topic_file = lambda snap: None
        pc._pick_expert_topic = lambda: None
        pc._project_child_material_count = lambda g: 0
        pc._off_window_budget_remaining = lambda: 0
        pc._heavy_action_mode_ok = lambda: True
        pc._is_action_rate_limited = lambda a: False

    def test_frame_captures_goal_description(self, tmp_path):
        pc = PlannerCore()
        self._isolate_live_queries(pc)
        out = tmp_path / "frames.jsonl"
        pc._decision_tap = DecisionTap(out_path=str(out), enabled=True)

        pc._tap_decision_frame(
            {"knowledge_snapshot": None, "evaluation_metrics": {}},
            [_goal(desc="prosze rozwaz czy juz opanowalem X")],
            None, tick_count=7,
        )

        lines = out.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1, "tap swallowed an exception and wrote no frame"
        frame = json.loads(lines[0])
        cand = frame["candidates"][0]
        assert cand["description"] == "prosze rozwaz czy juz opanowalem X"
        # sanity: the escape-surface / hidden keys the replay needs are present
        assert "backed_off_learn" in cand
        assert frame["exit_path"] == "goal_loop"

    def test_disabled_tap_writes_nothing(self, tmp_path):
        pc = PlannerCore()
        self._isolate_live_queries(pc)
        out = tmp_path / "frames.jsonl"
        pc._decision_tap = DecisionTap(out_path=str(out), enabled=False)
        pc._tap_decision_frame(
            {"knowledge_snapshot": None, "evaluation_metrics": {}},
            [_goal()], None, tick_count=1,
        )
        assert not out.exists(), "flag-gated OFF tap must never write"


class TestBuildFrame:
    def test_build_frame_has_required_keys(self):
        frame = build_frame(
            episode_id="ep-1", tick_count=1, now=123.0, mode="ACTIVE",
            health_score=1.0, exit_path="goal_loop",
            ranked_goals=[{"id": "g", "type": "meta", "description": "d"}],
            snapshot=None, metrics={}, is_learning_window=True,
            off_window_exec_allowed=False, hidden={}, ext={}, strategic=None,
        )
        for k in ("episode_id", "candidates", "snapshot_digest", "hidden", "ext", "exit_path"):
            assert k in frame
        assert frame["candidates"][0]["description"] == "d"
