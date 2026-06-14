"""
Tests for agent_core.web_source.decision_log.

Covers origin classification, JSONL append, and graceful failure modes.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_core.web_source.decision_log import (
    classify_origin,
    log_fetch_decision,
)


def _plan(metadata=None, action_params=None, goal_id="g-1", goal_description="test goal"):
    return SimpleNamespace(
        metadata=metadata or {},
        action_params=action_params or {},
        goal_id=goal_id,
        goal_description=goal_description,
    )


class TestClassifyOrigin:

    def test_metadata_trigger_wins(self):
        plan = _plan(metadata={"trigger": "saturation_meta_fetch"},
                     action_params={"topics": ["fizyka"]})
        assert classify_origin(plan) == {
            "origin": "saturation_meta_fetch",
            "trigger": "saturation_meta_fetch",
        }

    def test_user_request_when_topics_no_trigger(self):
        plan = _plan(action_params={"topics": ["mechanika"]})
        assert classify_origin(plan) == {
            "origin": "user_request",
            "trigger": "",
        }

    def test_planner_default_when_neither(self):
        plan = _plan()
        assert classify_origin(plan) == {
            "origin": "planner_default",
            "trigger": "",
        }

    def test_handles_missing_attrs(self):
        # Plan-like without metadata or action_params should not raise
        bare = SimpleNamespace(goal_id="g", goal_description="d")
        out = classify_origin(bare)
        assert out["origin"] == "planner_default"


class TestLogFetchDecision:

    def test_appends_jsonl_record(self, tmp_path):
        log = tmp_path / "fetch_decisions.jsonl"
        plan = _plan(action_params={"topics": ["fizyka"], "max_articles": 5})
        rec = log_fetch_decision(
            plan,
            outcome="success",
            duration_ms=123.4,
            result={"articles_fetched": 2, "topics_searched": 3,
                    "rss_filtered": 1, "wiki_fetched": 1, "rss_fetched": 1},
            log_path=log,
        )
        assert rec["origin"] == "user_request"
        assert rec["outcome"] == "success"
        assert rec["topics_requested"] == ["fizyka"]
        assert rec["max_articles"] == 5

        lines = log.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["origin"] == "user_request"
        assert parsed["result"]["articles_fetched"] == 2

    def test_skipped_outcome_records_reason(self, tmp_path):
        log = tmp_path / "f.jsonl"
        rec = log_fetch_decision(
            _plan(),
            outcome="skipped",
            duration_ms=0.1,
            skipped_reason="outside_learning_window",
            log_path=log,
        )
        assert rec["outcome"] == "skipped"
        assert rec["skipped_reason"] == "outside_learning_window"
        parsed = json.loads(log.read_text(encoding="utf-8").strip())
        assert parsed["skipped_reason"] == "outside_learning_window"

    def test_error_outcome_records_error(self, tmp_path):
        log = tmp_path / "f.jsonl"
        rec = log_fetch_decision(
            _plan(),
            outcome="error",
            duration_ms=50.0,
            error="Boom — analyzer missing",
            log_path=log,
        )
        assert rec["outcome"] == "error"
        assert rec["error"].startswith("Boom")

    def test_swallows_io_errors(self, tmp_path):
        # Pointing at a path that cannot be created — shouldn't raise
        bad = tmp_path / "no" / "such" / "dir" / "f.jsonl"
        # mkdir parents=True will succeed; instead simulate by using
        # an existing file as parent
        existing_file = tmp_path / "blocker"
        existing_file.write_text("x")
        target = existing_file / "child.jsonl"
        # Should not raise even though parent isn't a directory
        rec = log_fetch_decision(
            _plan(), outcome="success", duration_ms=1.0, log_path=target,
        )
        assert rec["outcome"] == "success"

    def test_three_outcomes_share_schema(self, tmp_path):
        log = tmp_path / "f.jsonl"
        for outcome, kwargs in [
            ("success", {"result": {"articles_fetched": 1, "topics_searched": 1}}),
            ("no_articles", {"result": {"articles_fetched": 0, "topics_searched": 4}}),
            ("error", {"error": "x"}),
        ]:
            log_fetch_decision(
                _plan(metadata={"trigger": "saturation_meta_fetch"}),
                outcome=outcome,
                duration_ms=10.0,
                log_path=log,
                **kwargs,
            )
        records = [json.loads(l) for l in log.read_text(encoding="utf-8").strip().splitlines()]
        assert len(records) == 3
        for r in records:
            assert "ts" in r and "ts_iso" in r
            assert r["origin"] == "saturation_meta_fetch"
