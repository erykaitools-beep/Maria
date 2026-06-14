"""Tests for trace_analyzer: load + group + pattern aggregation."""

import json
from pathlib import Path

import pytest

from agent_core.teacher.trace_analyzer import (
    ActionPattern,
    GoalPattern,
    TraceRecord,
    compute_action_patterns,
    compute_goal_patterns,
    group_by_goal,
    load_traces,
)


@pytest.fixture
def traces_file(tmp_path: Path) -> Path:
    """Build a small synthetic decision_traces.jsonl."""
    rows = [
        # goal-A: 6 episodes, 6 success (creative + noop pattern, 100%)
        {"episode_id": "ep-A1", "action_type": "creative", "goal_id": "goal-A",
         "goal_description": "Stymulacja postepu", "success": True, "started_at": 100.0, "mode": "active"},
        {"episode_id": "ep-A2", "action_type": "noop", "goal_id": "goal-A",
         "goal_description": "Stymulacja postepu", "success": True, "started_at": 200.0, "mode": "active"},
        {"episode_id": "ep-A3", "action_type": "creative", "goal_id": "goal-A",
         "goal_description": "Stymulacja postepu", "success": True, "started_at": 300.0, "mode": "active"},
        {"episode_id": "ep-A4", "action_type": "noop", "goal_id": "goal-A",
         "goal_description": "Stymulacja postepu", "success": True, "started_at": 400.0, "mode": "active"},
        {"episode_id": "ep-A5", "action_type": "creative", "goal_id": "goal-A",
         "goal_description": "Stymulacja postepu", "success": True, "started_at": 500.0, "mode": "active"},
        {"episode_id": "ep-A6", "action_type": "creative", "goal_id": "goal-A",
         "goal_description": "Stymulacja postepu", "success": True, "started_at": 600.0, "mode": "active"},
        # goal-B: 5 episodes, 1 success (learning, 20% - low success)
        {"episode_id": "ep-B1", "action_type": "exam", "goal_id": "goal-B",
         "goal_description": "Nauka X", "success": False, "started_at": 100.0, "mode": "active"},
        {"episode_id": "ep-B2", "action_type": "exam", "goal_id": "goal-B",
         "goal_description": "Nauka X", "success": False, "started_at": 200.0, "mode": "active"},
        {"episode_id": "ep-B3", "action_type": "review", "goal_id": "goal-B",
         "goal_description": "Nauka X", "success": False, "started_at": 300.0, "mode": "active"},
        {"episode_id": "ep-B4", "action_type": "review", "goal_id": "goal-B",
         "goal_description": "Nauka X", "success": True, "started_at": 400.0, "mode": "active"},
        {"episode_id": "ep-B5", "action_type": "exam", "goal_id": "goal-B",
         "goal_description": "Nauka X", "success": False, "started_at": 500.0, "mode": "active"},
        # goal-C: 2 episodes only (below min)
        {"episode_id": "ep-C1", "action_type": "fetch", "goal_id": "goal-C",
         "goal_description": "Small", "success": True, "started_at": 100.0, "mode": "active"},
        {"episode_id": "ep-C2", "action_type": "learn", "goal_id": "goal-C",
         "goal_description": "Small", "success": True, "started_at": 200.0, "mode": "active"},
        # Orphan (no goal_id) - dropped from goal grouping
        {"episode_id": "ep-X", "action_type": "creative", "goal_id": None,
         "goal_description": "", "success": True, "started_at": 100.0, "mode": "active"},
        # Aborted trace (no action_type) - silently skipped
        {"episode_id": "ep-aborted", "action_type": "", "goal_id": "goal-A",
         "goal_description": "Stymulacja postepu", "success": True, "started_at": 700.0, "mode": "active"},
    ]
    path = tmp_path / "decision_traces.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


class TestLoadTraces:
    def test_loads_valid_traces(self, traces_file):
        traces = load_traces(traces_file)
        # 15 rows - 1 aborted = 14
        assert len(traces) == 14

    def test_aborted_traces_dropped(self, traces_file):
        traces = load_traces(traces_file)
        eps = {t.episode_id for t in traces}
        assert "ep-aborted" not in eps

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_traces(tmp_path / "nope.jsonl") == []

    def test_malformed_line_skipped(self, tmp_path):
        path = tmp_path / "broken.jsonl"
        path.write_text(
            '{"valid": true, "episode_id": "ep-1", "action_type": "x", "goal_id": "g", '
            '"goal_description": "d", "success": true, "started_at": 1.0}\n'
            '{this is not json}\n'
            '{"episode_id": "ep-2", "action_type": "y", "goal_id": "g", '
            '"goal_description": "d", "success": true, "started_at": 2.0}\n',
            encoding="utf-8",
        )
        traces = load_traces(path)
        assert len(traces) == 2


class TestGroupByGoal:
    def test_groups_by_goal_id(self, traces_file):
        traces = load_traces(traces_file)
        grouped = group_by_goal(traces)
        assert "goal-A" in grouped
        assert "goal-B" in grouped
        assert "goal-C" in grouped
        assert len(grouped["goal-A"]) == 6
        assert len(grouped["goal-B"]) == 5
        assert len(grouped["goal-C"]) == 2

    def test_orphans_dropped(self, traces_file):
        traces = load_traces(traces_file)
        grouped = group_by_goal(traces)
        all_eps = {t.episode_id for ts in grouped.values() for t in ts}
        assert "ep-X" not in all_eps  # no goal_id


class TestGoalPatterns:
    def test_min_episodes_filter(self, traces_file):
        traces = load_traces(traces_file)
        patterns = compute_goal_patterns(traces, min_episodes=5)
        gids = {p.goal_id for p in patterns}
        assert "goal-A" in gids
        assert "goal-B" in gids
        assert "goal-C" not in gids  # only 2 episodes

    def test_success_rate_computed(self, traces_file):
        traces = load_traces(traces_file)
        patterns = compute_goal_patterns(traces, min_episodes=5)
        a = next(p for p in patterns if p.goal_id == "goal-A")
        b = next(p for p in patterns if p.goal_id == "goal-B")
        assert a.success_rate == 1.0
        assert b.success_rate == 0.2

    def test_action_histogram(self, traces_file):
        traces = load_traces(traces_file)
        patterns = compute_goal_patterns(traces, min_episodes=5)
        a = next(p for p in patterns if p.goal_id == "goal-A")
        assert a.action_histogram == {"creative": 4, "noop": 2}

    def test_dominant_actions(self, traces_file):
        traces = load_traces(traces_file)
        patterns = compute_goal_patterns(traces, min_episodes=5)
        a = next(p for p in patterns if p.goal_id == "goal-A")
        assert "creative" in a.dominant_actions

    def test_sort_high_success_first(self, traces_file):
        traces = load_traces(traces_file)
        patterns = compute_goal_patterns(traces, min_episodes=5)
        assert patterns[0].goal_id == "goal-A"
        assert patterns[0].success_rate >= patterns[-1].success_rate


class TestActionPatterns:
    def test_aggregate_across_goals(self, traces_file):
        traces = load_traces(traces_file)
        patterns = compute_action_patterns(traces, min_episodes=2)
        atypes = {p.action_type for p in patterns}
        # creative appears in goal-A (4x) + orphan dropped from goal group but
        # still counted at action level (it was filtered only in group_by_goal,
        # not load_traces - confirm)
        assert "creative" in atypes
        assert "exam" in atypes
        assert "review" in atypes

    def test_min_episodes_filter(self, traces_file):
        traces = load_traces(traces_file)
        patterns = compute_action_patterns(traces, min_episodes=100)
        assert patterns == []

    def test_success_rate(self, traces_file):
        traces = load_traces(traces_file)
        patterns = compute_action_patterns(traces, min_episodes=2)
        # creative had 4 successes in goal-A + 1 in orphan = 5/5 = 100%
        # exam had 3 fails in goal-B = 0%
        creative = next((p for p in patterns if p.action_type == "creative"), None)
        exam = next((p for p in patterns if p.action_type == "exam"), None)
        assert creative is not None
        assert creative.success_rate == 1.0
        assert exam is not None
        assert exam.success_rate == 0.0
