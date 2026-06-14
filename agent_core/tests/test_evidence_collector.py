"""Tests for EvidenceCollector."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_core.introspection.evidence_collector import (
    Evidence,
    EvidenceCollector,
)
from agent_core.introspection.query_router import ResponseMode
from agent_core.homeostasis.core import HomeostasisCore
from agent_core.llm.llm_tape import LLMTape
from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
from agent_core.tests.spec_helpers import specced


@pytest.fixture
def meta_dir(tmp_path):
    """Create meta_data dir with sample JSONL files."""
    meta = tmp_path / "meta_data"
    meta.mkdir()
    return meta


@pytest.fixture
def collector(tmp_path, meta_dir):
    return EvidenceCollector(project_root=str(tmp_path))


def _write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# -- Evidence dataclass --

class TestEvidence:
    def test_evidence_creation(self):
        e = Evidence(
            key="test.key", value="test_value",
            source="test.jsonl", confidence="high",
            timestamp=time.time(),
        )
        assert e.key == "test.key"
        assert e.confidence == "high"


# -- collect_for_mode routing --

class TestCollectForMode:
    def test_routes_to_status(self, collector):
        result = collector.collect_for_mode(ResponseMode.GROUNDED_STATUS)
        assert isinstance(result, list)

    def test_routes_to_error(self, collector):
        result = collector.collect_for_mode(ResponseMode.GROUNDED_ERROR)
        assert isinstance(result, list)

    def test_routes_to_learning(self, collector):
        result = collector.collect_for_mode(ResponseMode.GROUNDED_LEARNING)
        assert isinstance(result, list)

    def test_routes_to_planner(self, collector):
        result = collector.collect_for_mode(ResponseMode.GROUNDED_PLANNER)
        assert isinstance(result, list)

    def test_normal_returns_status(self, collector):
        # NORMAL mode falls back to status
        result = collector.collect_for_mode(ResponseMode.NORMAL)
        assert isinstance(result, list)


# -- Homeostasis collection --

class TestCollectHomeostasis:
    def test_from_runtime_object(self, collector):
        mock_core = specced(HomeostasisCore)
        state = MagicMock()
        state.mode.value = "active"
        state.health_score = 0.95
        mock_core.get_state.return_value = state
        collector.set_homeostasis_core(mock_core)

        evidence = collector.collect_status()
        modes = [e for e in evidence if e.key == "homeostasis.mode"]
        assert len(modes) == 1
        assert modes[0].value == "active"
        assert modes[0].confidence == "high"

    def test_from_jsonl_fallback(self, collector, meta_dir):
        _write_jsonl(meta_dir / "homeostasis_events.jsonl", [
            {"ts": time.time(), "mode": "active", "health": 0.88},
        ])
        evidence = collector.collect_status()
        modes = [e for e in evidence if e.key == "homeostasis.mode"]
        assert len(modes) == 1
        assert modes[0].value == "active"
        assert modes[0].confidence == "medium"

    def test_no_data(self, collector):
        evidence = collector.collect_status()
        modes = [e for e in evidence if e.key == "homeostasis.mode"]
        assert len(modes) == 0


# -- Planner collection --

class TestCollectPlanner:
    def test_last_action_from_jsonl(self, collector, meta_dir):
        _write_jsonl(meta_dir / "planner_decisions.jsonl", [
            {"timestamp": time.time(), "action_type": "learn",
             "goal_description": "Nauka nowego materialu", "status": "completed"},
            {"timestamp": time.time(), "action_type": "exam",
             "goal_description": "Egzamin", "status": "failed",
             "result": {"success": False, "reasons": ["consecutive_failures"]}},
        ])
        evidence = collector.collect_planner()
        actions = [e for e in evidence if e.key == "planner.last_action"]
        assert len(actions) == 1
        assert actions[0].value == "exam"

    def test_repeated_failures(self, collector, meta_dir):
        records = []
        for i in range(10):
            records.append({
                "timestamp": time.time(), "action_type": "exam",
                "status": "failed",
                "result": {"success": False, "reasons": ["blocked by K7"]},
            })
        _write_jsonl(meta_dir / "planner_decisions.jsonl", records)

        evidence = collector.collect_planner()
        failures = [e for e in evidence if "repeated_failure" in e.key]
        assert len(failures) >= 1
        assert "10 razy" in failures[0].value


# -- Learning collection --

class TestCollectLearning:
    def test_from_knowledge_analyzer(self, collector):
        # Bug #2 guard: real API is get_knowledge_snapshot() returning a {total_files,
        # files_by_status: {status: [records]}} shape -- "completed" is the bucket len.
        # specced() makes the old get_stats() phantom regress red.
        mock_ka = specced(KnowledgeAnalyzer)
        mock_ka.get_knowledge_snapshot.return_value = {
            "total_files": 67,
            "files_by_status": {"completed": [{"id": f"f{i}.txt"} for i in range(12)]},
        }
        collector.set_knowledge_analyzer(mock_ka)

        evidence = collector.collect_learning()
        files = [e for e in evidence if e.key == "learning.total_files"]
        assert len(files) == 1
        assert files[0].value == "67"
        completed = [e for e in evidence if e.key == "learning.completed"]
        assert completed[0].value == "12"

    def test_input_dir_fallback(self, collector, meta_dir, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "file1.txt").write_text("test")
        (input_dir / "file2.txt").write_text("test")

        evidence = collector.collect_learning()
        files = [e for e in evidence if e.key == "learning.total_files"]
        assert len(files) == 1
        assert files[0].value == "2"

    def test_recent_exams(self, collector, meta_dir):
        _write_jsonl(meta_dir / "teacher_plans.jsonl", [
            {"timestamp": time.time(), "result": {
                "type": "exam", "score": 0.85, "passed": True,
                "file_id": "test_file.txt"}},
        ])
        evidence = collector.collect_learning()
        exams = [e for e in evidence if e.key == "learning.last_exam"]
        assert len(exams) == 1
        assert "85" in exams[0].value or "0.85" in exams[0].value


# -- LLM tape collection --

class TestCollectTape:
    def test_tape_stats_from_object(self, collector):
        mock_tape = specced(LLMTape)
        mock_tape.get_stats.return_value = {
            "total_calls": 42, "error_count": 2, "error_rate": 0.048,
        }
        collector.set_llm_tape(mock_tape)

        evidence = collector.collect_status()
        calls = [e for e in evidence if e.key == "llm.total_calls_24h"]
        assert len(calls) == 1
        assert calls[0].value == "42"

    def test_tape_errors(self, collector):
        mock_tape = specced(LLMTape)
        mock_tape.get_recent_errors.return_value = [
            {"model": "llama3.1:8b", "role": "chat", "raw_response": "", "ts": time.time()},
        ]
        collector.set_llm_tape(mock_tape)

        evidence = collector.collect_error()
        errors = [e for e in evidence if e.key == "llm.error"]
        assert len(errors) == 1


# -- Autonomy blocks --

class TestCollectAutonomy:
    def test_autonomy_blocks(self, collector, meta_dir):
        _write_jsonl(meta_dir / "autonomy_decisions.jsonl", [
            {"decision": "block", "rule_name": "consecutive_failure_breaker",
             "ts": time.time()},
            {"decision": "block", "rule_name": "consecutive_failure_breaker",
             "ts": time.time()},
            {"decision": "allow", "ts": time.time()},
        ])
        evidence = collector.collect_error()
        blocks = [e for e in evidence if "autonomy.block" in e.key]
        assert len(blocks) >= 1
        assert "2 blokad" in blocks[0].value


# -- Goals --

class TestCollectGoals:
    def test_goals_from_jsonl(self, collector, meta_dir):
        _write_jsonl(meta_dir / "goals.jsonl", [
            {"goal_id": "goal-meta-learn", "status": "active",
             "goal_type": "meta", "title": "Autonomiczna nauka"},
            {"goal_id": "goal-maint", "status": "active",
             "goal_type": "maintenance", "title": "Utrzymaj health"},
        ])
        evidence = collector.collect_planner()
        goals = [e for e in evidence if e.key.startswith("goal.")]
        assert len(goals) == 2


# -- Compact summary --

class TestCompactSummary:
    def test_builds_summary(self, collector, meta_dir):
        _write_jsonl(meta_dir / "homeostasis_events.jsonl", [
            {"ts": time.time(), "mode": "active", "health": 0.92},
        ])
        summary = collector.build_compact_summary()
        assert "Stan operacyjny" in summary
        assert "active" in summary

    def test_cache_works(self, collector, meta_dir):
        _write_jsonl(meta_dir / "homeostasis_events.jsonl", [
            {"ts": time.time(), "mode": "active", "health": 0.92},
        ])
        s1 = collector.build_compact_summary()
        s2 = collector.build_compact_summary()
        assert s1 == s2  # cached

    def test_max_length(self, collector):
        summary = collector.build_compact_summary()
        assert len(summary) <= 600

    def test_empty_when_no_data(self, collector):
        summary = collector.build_compact_summary()
        assert summary == ""  # no data = empty
