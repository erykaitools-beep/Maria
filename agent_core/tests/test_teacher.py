"""
Tests for Agent Nauczyciel (Teacher Agent).

All tests use mocks and tmp fixtures - no real LLM calls needed.
"""

import json
import time
import threading
import pytest
from pathlib import Path
from datetime import datetime, timedelta

from agent_core.teacher.teaching_strategy import TeachingStrategy, SpacedRepetitionScheduler
from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
from agent_core.teacher.teacher_agent import TeacherAgent
from agent_core.homeostasis.core import HomeostasisCore
from agent_core.homeostasis.state_model import Mode


# ── Fixtures ──────────────────────────────────────────

def _write_jsonl(path: Path, records):
    """Helper to write JSONL test data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _make_index_record(file_id, status="new", priority=73, chunks_learned=0,
                       total_chunks=0, exam_attempts=0, last_scores=None,
                       updated_at=None):
    """Create a knowledge index record for testing."""
    return {
        "id": file_id,
        "file": file_id,
        "status": status,
        "priority": priority,
        "chunks_learned": chunks_learned,
        "total_chunks": total_chunks,
        "exam_attempts": exam_attempts,
        "last_scores": last_scores or [],
        "created_at": "2026-02-01T09:00:00Z",
        "updated_at": updated_at or "2026-02-01T09:00:00Z",
    }


def _make_exam_record(file_id, score=0.83, attempt=1, num_questions=4):
    """Create an exam result record for testing."""
    return {
        "file": file_id,
        "timestamp": "2026-02-01T09:24:17Z",
        "attempt": attempt,
        "score": score,
        "num_questions": num_questions,
    }


def _make_memory_record(source_file, chunk_index=0, tags=None):
    """Create a longterm memory record for testing."""
    return {
        "source_file": source_file,
        "chunk_id": f"{source_file}#chunk_{chunk_index}",
        "chunk_index": chunk_index,
        "timestamp": "2026-02-01T09:30:00Z",
        "summary": f"Summary of {source_file} chunk {chunk_index}",
        "key_points": ["point1", "point2"],
        "tags": tags or ["tag1", "tag2"],
    }


# ══════════════════════════════════════════════════════
# TestTeachingStrategy
# ══════════════════════════════════════════════════════

class TestTeachingStrategy:
    """Tests for TeachingStrategy data class."""

    def test_create_strategy(self):
        s = TeachingStrategy(TeachingStrategy.LEARN_NEW, "file_001.txt")
        assert s.strategy_type == "learn_new"
        assert s.target_file_id == "file_001.txt"
        assert s.params == {}
        assert s.created_at > 0

    def test_create_with_params(self):
        s = TeachingStrategy(
            TeachingStrategy.REVIEW, "file_002.txt",
            params={"last_score": 0.85, "difficulty": "hard"},
        )
        assert s.params["last_score"] == 0.85
        assert s.params["difficulty"] == "hard"

    def test_invalid_strategy_type(self):
        with pytest.raises(ValueError, match="Unknown strategy type"):
            TeachingStrategy("invalid_type", "file.txt")

    def test_all_valid_types(self):
        for t in TeachingStrategy.ALL_TYPES:
            s = TeachingStrategy(t, "file.txt")
            assert s.strategy_type == t

    def test_to_dict(self):
        s = TeachingStrategy(TeachingStrategy.FILL_GAP, "hard_file.txt",
                             params={"reason": "low_score"})
        d = s.to_dict()
        assert d["strategy_type"] == "fill_gap"
        assert d["target_file_id"] == "hard_file.txt"
        assert d["params"]["reason"] == "low_score"
        assert "created_at" in d

    def test_from_dict(self):
        data = {
            "strategy_type": "review",
            "target_file_id": "reviewed.txt",
            "params": {"last_score": 0.9},
            "created_at": 1000000.0,
        }
        s = TeachingStrategy.from_dict(data)
        assert s.strategy_type == "review"
        assert s.target_file_id == "reviewed.txt"
        assert s.created_at == 1000000.0

    def test_roundtrip(self):
        original = TeachingStrategy(
            TeachingStrategy.DEEPEN, "deep_file.txt",
            params={"level": 2},
        )
        d = original.to_dict()
        restored = TeachingStrategy.from_dict(d)
        assert restored.strategy_type == original.strategy_type
        assert restored.target_file_id == original.target_file_id
        assert restored.params == original.params

    def test_repr(self):
        s = TeachingStrategy(TeachingStrategy.LEARN_NEW, "file.txt")
        r = repr(s)
        assert "learn_new" in r
        assert "file.txt" in r


# ══════════════════════════════════════════════════════
# TestSpacedRepetitionScheduler
# ══════════════════════════════════════════════════════

class TestSpacedRepetitionScheduler:
    """Tests for spaced repetition scheduling."""

    @pytest.fixture
    def scheduler(self):
        return SpacedRepetitionScheduler()

    def test_low_score_short_interval(self, scheduler):
        assert scheduler.get_review_interval_hours(0.65) == 48

    def test_medium_score_medium_interval(self, scheduler):
        assert scheduler.get_review_interval_hours(0.75) == 120

    def test_high_score_long_interval(self, scheduler):
        assert scheduler.get_review_interval_hours(0.85) == 336

    def test_excellent_score_longest_interval(self, scheduler):
        assert scheduler.get_review_interval_hours(0.95) == 720

    def test_failed_score_next_day(self, scheduler):
        assert scheduler.get_review_interval_hours(0.5) == 24

    def test_perfect_score(self, scheduler):
        assert scheduler.get_review_interval_hours(1.0) == 720

    def test_is_due_for_review_yes(self, scheduler):
        # Completed 3 days ago with score 0.65 -> interval 48h -> due
        three_days_ago = (datetime.now() - timedelta(days=3)).isoformat() + "Z"
        rec = _make_index_record(
            "file.txt", status="completed",
            last_scores=[0.65], updated_at=three_days_ago,
        )
        assert scheduler.is_due_for_review(rec) is True

    def test_is_due_for_review_no(self, scheduler):
        # Completed 1 hour ago with score 0.65 -> interval 48h -> not due
        one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat() + "Z"
        rec = _make_index_record(
            "file.txt", status="completed",
            last_scores=[0.65], updated_at=one_hour_ago,
        )
        assert scheduler.is_due_for_review(rec) is False

    def test_not_due_if_not_completed(self, scheduler):
        rec = _make_index_record("file.txt", status="learning", last_scores=[0.65])
        assert scheduler.is_due_for_review(rec) is False

    def test_not_due_if_no_scores(self, scheduler):
        rec = _make_index_record("file.txt", status="completed", last_scores=[])
        assert scheduler.is_due_for_review(rec) is False

    def test_get_due_reviews(self, scheduler):
        old_date = (datetime.now() - timedelta(days=10)).isoformat() + "Z"
        recent_date = (datetime.now() - timedelta(hours=1)).isoformat() + "Z"

        snapshot = {
            "files_by_status": {
                "completed": [
                    _make_index_record("old.txt", status="completed",
                                       last_scores=[0.75], updated_at=old_date),
                    _make_index_record("recent.txt", status="completed",
                                       last_scores=[0.75], updated_at=recent_date),
                ],
            },
        }

        due = scheduler.get_due_reviews(snapshot)
        assert len(due) == 1
        assert due[0]["file"] == "old.txt"


# ══════════════════════════════════════════════════════
# TestKnowledgeAnalyzer
# ══════════════════════════════════════════════════════

class TestKnowledgeAnalyzer:
    """Tests for pure-data knowledge analysis."""

    @pytest.fixture
    def tmp_dir(self, tmp_path):
        """Create test directory structure."""
        (tmp_path / "input").mkdir()
        (tmp_path / "input" / "file1.txt").write_text("content1")
        (tmp_path / "input" / "file2.txt").write_text("content2")
        (tmp_path / "memory").mkdir()
        return tmp_path

    @pytest.fixture
    def analyzer(self, tmp_dir):
        return KnowledgeAnalyzer(
            knowledge_index_path=tmp_dir / "memory" / "knowledge_index.jsonl",
            longterm_memory_path=tmp_dir / "memory" / "longterm_memory.jsonl",
            exam_results_path=tmp_dir / "memory" / "exam_results.jsonl",
            input_dir=tmp_dir / "input",
        )

    def test_empty_snapshot(self, analyzer):
        snapshot = analyzer.get_knowledge_snapshot()
        assert snapshot["total_files"] == 0
        assert snapshot["average_exam_score"] == 0.0
        assert snapshot["input_file_count"] == 2

    def test_snapshot_counts_by_status(self, analyzer, tmp_dir):
        records = [
            _make_index_record("f1.txt", status="completed", chunks_learned=2, total_chunks=2),
            _make_index_record("f2.txt", status="new"),
            _make_index_record("f3.txt", status="new"),
            _make_index_record("f4.txt", status="learning", chunks_learned=1, total_chunks=3),
            _make_index_record("f5.txt", status="hard_topic"),
        ]
        _write_jsonl(tmp_dir / "memory" / "knowledge_index.jsonl", records)

        snapshot = analyzer.get_knowledge_snapshot()
        assert snapshot["total_files"] == 5
        assert len(snapshot["files_by_status"]["completed"]) == 1
        assert len(snapshot["files_by_status"]["new"]) == 2
        assert len(snapshot["new_files_available"]) == 2
        assert len(snapshot["learning_in_progress"]) == 1
        assert len(snapshot["hard_topics"]) == 1
        assert snapshot["total_chunks_learned"] == 3
        assert snapshot["total_chunks_available"] == 5

    def test_snapshot_average_exam_score(self, analyzer, tmp_dir):
        exams = [
            _make_exam_record("f1.txt", score=0.8),
            _make_exam_record("f2.txt", score=0.6),
        ]
        _write_jsonl(tmp_dir / "memory" / "exam_results.jsonl", exams)

        snapshot = analyzer.get_knowledge_snapshot()
        assert snapshot["average_exam_score"] == pytest.approx(0.7)

    def test_new_files_sorted_by_priority(self, analyzer, tmp_dir):
        records = [
            _make_index_record("low.txt", status="new", priority=30),
            _make_index_record("high.txt", status="new", priority=90),
            _make_index_record("mid.txt", status="new", priority=60),
        ]
        _write_jsonl(tmp_dir / "memory" / "knowledge_index.jsonl", records)

        snapshot = analyzer.get_knowledge_snapshot()
        new = snapshot["new_files_available"]
        assert new[0]["file"] == "high.txt"
        assert new[1]["file"] == "mid.txt"
        assert new[2]["file"] == "low.txt"

    def test_find_knowledge_gaps_partial(self, analyzer, tmp_dir):
        records = [
            _make_index_record("partial.txt", status="learning",
                               chunks_learned=1, total_chunks=3),
        ]
        _write_jsonl(tmp_dir / "memory" / "knowledge_index.jsonl", records)

        gaps = analyzer.find_knowledge_gaps()
        assert len(gaps) == 1
        assert gaps[0]["type"] == "partial"
        assert gaps[0]["progress"] == pytest.approx(1 / 3)

    def test_find_knowledge_gaps_low_score(self, analyzer, tmp_dir):
        records = [
            _make_index_record("low.txt", status="completed",
                               last_scores=[0.62]),
        ]
        _write_jsonl(tmp_dir / "memory" / "knowledge_index.jsonl", records)

        gaps = analyzer.find_knowledge_gaps()
        assert len(gaps) == 1
        assert gaps[0]["type"] == "low_score"

    def test_find_knowledge_gaps_exam_failed(self, analyzer, tmp_dir):
        records = [
            _make_index_record("failed.txt", status="exam_failed", exam_attempts=1),
        ]
        _write_jsonl(tmp_dir / "memory" / "knowledge_index.jsonl", records)

        gaps = analyzer.find_knowledge_gaps()
        assert len(gaps) == 1
        assert gaps[0]["type"] == "exam_failed"

    def test_find_gaps_sorted_by_priority(self, analyzer, tmp_dir):
        records = [
            _make_index_record("low.txt", status="completed", last_scores=[0.65]),
            _make_index_record("failed.txt", status="exam_failed", exam_attempts=1),
            _make_index_record("partial.txt", status="learning",
                               chunks_learned=1, total_chunks=3),
        ]
        _write_jsonl(tmp_dir / "memory" / "knowledge_index.jsonl", records)

        gaps = analyzer.find_knowledge_gaps()
        # partial (80) > exam_failed (70) > low_score (60)
        assert gaps[0]["type"] == "partial"
        assert gaps[1]["type"] == "exam_failed"
        assert gaps[2]["type"] == "low_score"

    def test_no_gaps_when_all_completed_high_score(self, analyzer, tmp_dir):
        records = [
            _make_index_record("good.txt", status="completed",
                               last_scores=[0.9], chunks_learned=2, total_chunks=2),
        ]
        _write_jsonl(tmp_dir / "memory" / "knowledge_index.jsonl", records)

        gaps = analyzer.find_knowledge_gaps()
        assert len(gaps) == 0

    def test_review_candidates(self, analyzer, tmp_dir):
        old_date = (datetime.now() - timedelta(days=5)).isoformat() + "Z"
        recent_date = (datetime.now() - timedelta(hours=1)).isoformat() + "Z"

        records = [
            _make_index_record("old.txt", status="completed", updated_at=old_date),
            _make_index_record("recent.txt", status="completed", updated_at=recent_date),
            _make_index_record("new.txt", status="new"),
        ]
        _write_jsonl(tmp_dir / "memory" / "knowledge_index.jsonl", records)

        candidates = analyzer.get_review_candidates(min_age_hours=48)
        assert len(candidates) == 1
        assert candidates[0]["file"] == "old.txt"

    def test_tag_frequency_map(self, analyzer, tmp_dir):
        memories = [
            _make_memory_record("f1.txt", tags=["logika", "myslenie", "decyzje"]),
            _make_memory_record("f2.txt", tags=["logika", "predykaty"]),
            _make_memory_record("f3.txt", tags=["myslenie", "logika"]),
        ]
        _write_jsonl(tmp_dir / "memory" / "longterm_memory.jsonl", memories)

        tags = analyzer.get_tag_frequency_map()
        assert tags["logika"] == 3
        assert tags["myslenie"] == 2
        assert tags["decyzje"] == 1
        assert tags["predykaty"] == 1

    def test_tag_map_empty(self, analyzer):
        tags = analyzer.get_tag_frequency_map()
        assert tags == {}

    def test_get_file_details_found(self, analyzer, tmp_dir):
        records = [_make_index_record("logika_01.txt", status="completed")]
        exams = [_make_exam_record("logika_01.txt", score=0.85)]
        memories = [_make_memory_record("logika_01.txt", tags=["logika"])]

        _write_jsonl(tmp_dir / "memory" / "knowledge_index.jsonl", records)
        _write_jsonl(tmp_dir / "memory" / "exam_results.jsonl", exams)
        _write_jsonl(tmp_dir / "memory" / "longterm_memory.jsonl", memories)

        details = analyzer.get_file_details("logika")
        assert details is not None
        assert details["file_name"] == "logika_01.txt"
        assert len(details["exams"]) == 1
        assert len(details["memories"]) == 1

    def test_get_file_details_not_found(self, analyzer, tmp_dir):
        records = [_make_index_record("other.txt")]
        _write_jsonl(tmp_dir / "memory" / "knowledge_index.jsonl", records)

        assert analyzer.get_file_details("nonexistent") is None

    def test_compact_summary(self, analyzer, tmp_dir):
        records = [
            _make_index_record("f1.txt", status="completed"),
            _make_index_record("f2.txt", status="new", priority=80),
            _make_index_record("f3.txt", status="hard_topic"),
        ]
        _write_jsonl(tmp_dir / "memory" / "knowledge_index.jsonl", records)

        summary = analyzer.get_compact_summary()
        assert "Pliki ukonczone: 1" in summary
        assert "Pliki nowe: 1" in summary
        assert "Trudne tematy: 1" in summary


# ══════════════════════════════════════════════════════
# Mock router for TeacherAgent tests
# ══════════════════════════════════════════════════════

class MockRouter:
    """Minimal mock of LLMRouter for testing."""

    def __init__(self, ask_once_response="mock response"):
        self._response = ask_once_response

    def _ask_once(self, prompt, temperature=0.3, **kwargs):
        return self._response

    def think(self, prompt, temperature=0.3, **kwargs):
        return self._response


def _make_teacher(tmp_path, index_records=None, exam_records=None):
    """Helper to create TeacherAgent with test data."""
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir(exist_ok=True)
    input_dir = tmp_path / "input"
    input_dir.mkdir(exist_ok=True)

    idx_path = mem_dir / "knowledge_index.jsonl"
    exam_path = mem_dir / "exam_results.jsonl"
    mem_path = mem_dir / "longterm_memory.jsonl"
    plans_path = tmp_path / "teacher_plans.jsonl"

    if index_records:
        _write_jsonl(idx_path, index_records)
    if exam_records:
        _write_jsonl(exam_path, exam_records)

    analyzer = KnowledgeAnalyzer(
        knowledge_index_path=idx_path,
        longterm_memory_path=mem_path,
        exam_results_path=exam_path,
        input_dir=input_dir,
    )
    router = MockRouter()
    agent = TeacherAgent(
        router=router,
        knowledge_analyzer=analyzer,
        plans_path=plans_path,
    )
    return agent


# ══════════════════════════════════════════════════════
# TestTeacherDecisions
# ══════════════════════════════════════════════════════

class TestTeacherDecisions:
    """Tests for the decision engine (priorities 1-6)."""

    def test_p1_continue_partial_learning(self, tmp_path):
        """P1: If a file is in 'learning' status, continue it."""
        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("partial.txt", status="learning",
                               chunks_learned=1, total_chunks=3),
            _make_index_record("new.txt", status="new", priority=90),
        ])
        snapshot = agent.analyzer.get_knowledge_snapshot()
        strategy = agent._decide_next_strategy(snapshot, 1)

        assert strategy is not None
        assert strategy.strategy_type == TeachingStrategy.LEARN_NEW
        assert strategy.target_file_id == "partial.txt"
        assert strategy.params["reason"] == "continue_partial"

    def test_p2_examine_ready_file(self, tmp_path):
        """P2: If a file is 'learned', run exam."""
        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("ready.txt", status="learned"),
            _make_index_record("new.txt", status="new"),
        ])
        snapshot = agent.analyzer.get_knowledge_snapshot()
        strategy = agent._decide_next_strategy(snapshot, 1)

        assert strategy is not None
        assert strategy.strategy_type == TeachingStrategy.REVIEW
        assert strategy.target_file_id == "ready.txt"
        assert strategy.params["reason"] == "exam_ready"

    def test_p3_start_new_file(self, tmp_path):
        """P3: Start new file with highest priority."""
        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("low.txt", status="new", priority=30),
            _make_index_record("high.txt", status="new", priority=90),
        ])
        snapshot = agent.analyzer.get_knowledge_snapshot()
        strategy = agent._decide_next_strategy(snapshot, 1)

        assert strategy is not None
        assert strategy.strategy_type == TeachingStrategy.LEARN_NEW
        assert strategy.target_file_id == "high.txt"
        assert strategy.params["reason"] == "new_file"

    def test_p4_spaced_repetition(self, tmp_path):
        """P4: Review completed file that is due for spaced repetition."""
        old_date = (datetime.now() - timedelta(days=10)).isoformat() + "Z"
        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("reviewed.txt", status="completed",
                               last_scores=[0.75], updated_at=old_date),
        ])
        snapshot = agent.analyzer.get_knowledge_snapshot()
        strategy = agent._decide_next_strategy(snapshot, 1)

        assert strategy is not None
        assert strategy.strategy_type == TeachingStrategy.REVIEW
        assert strategy.target_file_id == "reviewed.txt"
        assert strategy.params["reason"] == "spaced_repetition"

    def test_p5_retry_hard_topic(self, tmp_path):
        """P5: Retry hard topic after enough successes."""
        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("hard.txt", status="hard_topic", exam_attempts=2),
            # Need 3+ completed files to trigger P5
            _make_index_record("c1.txt", status="completed",
                               last_scores=[0.95],
                               updated_at=(datetime.now() - timedelta(hours=1)).isoformat() + "Z"),
            _make_index_record("c2.txt", status="completed",
                               last_scores=[0.95],
                               updated_at=(datetime.now() - timedelta(hours=1)).isoformat() + "Z"),
            _make_index_record("c3.txt", status="completed",
                               last_scores=[0.95],
                               updated_at=(datetime.now() - timedelta(hours=1)).isoformat() + "Z"),
        ])
        snapshot = agent.analyzer.get_knowledge_snapshot()
        strategy = agent._decide_next_strategy(snapshot, 1)

        assert strategy is not None
        assert strategy.strategy_type == TeachingStrategy.FILL_GAP
        assert strategy.target_file_id == "hard.txt"
        assert strategy.params["reason"] == "retry_hard_topic"

    def test_p5_hard_topic_not_retried_without_enough_completions(self, tmp_path):
        """P5: Don't retry hard topic if < 3 completions."""
        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("hard.txt", status="hard_topic"),
            _make_index_record("c1.txt", status="completed",
                               last_scores=[0.95],
                               updated_at=(datetime.now() - timedelta(hours=1)).isoformat() + "Z"),
        ])
        snapshot = agent.analyzer.get_knowledge_snapshot()
        strategy = agent._decide_next_strategy(snapshot, 1)

        # Should skip P5 (only 1 completion) and go to P6 or None
        assert strategy is None or strategy.params.get("reason") != "retry_hard_topic"

    def test_p1_takes_priority_over_p2(self, tmp_path):
        """P1 (continue learning) beats P2 (exam ready)."""
        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("learning.txt", status="learning",
                               chunks_learned=1, total_chunks=2),
            _make_index_record("ready.txt", status="learned"),
        ])
        snapshot = agent.analyzer.get_knowledge_snapshot()
        strategy = agent._decide_next_strategy(snapshot, 1)

        assert strategy.target_file_id == "learning.txt"

    def test_p2_takes_priority_over_p3(self, tmp_path):
        """P2 (exam ready) beats P3 (new file)."""
        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("ready.txt", status="learned"),
            _make_index_record("new.txt", status="new", priority=99),
        ])
        snapshot = agent.analyzer.get_knowledge_snapshot()
        strategy = agent._decide_next_strategy(snapshot, 1)

        assert strategy.target_file_id == "ready.txt"

    def test_nothing_to_do_returns_none(self, tmp_path):
        """All completed, nothing due -> None."""
        recent = (datetime.now() - timedelta(hours=1)).isoformat() + "Z"
        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("done.txt", status="completed",
                               last_scores=[0.95], updated_at=recent),
        ])
        snapshot = agent.analyzer.get_knowledge_snapshot()
        strategy = agent._decide_next_strategy(snapshot, 1)

        assert strategy is None

    def test_empty_index_returns_none(self, tmp_path):
        """Empty knowledge base -> None."""
        agent = _make_teacher(tmp_path)
        snapshot = agent.analyzer.get_knowledge_snapshot()
        strategy = agent._decide_next_strategy(snapshot, 1)

        assert strategy is None

    def test_nim_planning_limit(self, tmp_path):
        """NIM planning calls are limited per session."""
        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("partial.txt", status="learning",
                               chunks_learned=1, total_chunks=3),
        ])
        agent._max_nim_planning = 3
        agent._nim_planning_used = 3  # Already used all

        # Even with gaps, NIM won't be called
        # (but P1 will still fire for partial learning)
        snapshot = agent.analyzer.get_knowledge_snapshot()
        strategy = agent._decide_next_strategy(snapshot, 1)
        assert strategy is not None  # P1 fires
        assert agent._nim_planning_used == 3  # No new NIM calls

    def test_nim_gap_analysis_with_gaps(self, tmp_path):
        """P6: NIM gap analysis when gaps exist."""
        recent = (datetime.now() - timedelta(hours=1)).isoformat() + "Z"
        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("low.txt", status="completed",
                               last_scores=[0.55], updated_at=recent),
        ])
        # Mock router to return a file ID
        agent.router = MockRouter(ask_once_response="Polecam low.txt")

        snapshot = agent.analyzer.get_knowledge_snapshot()
        strategy = agent._decide_next_strategy(snapshot, 1)

        assert strategy is not None
        assert strategy.params.get("reason", "").startswith("nim_gap_analysis")
        assert agent._nim_planning_used == 1


# ══════════════════════════════════════════════════════
# TestTeacherExecution
# ══════════════════════════════════════════════════════

class TestTeacherExecution:
    """Tests for strategy execution and session management."""

    def test_exec_learn_success(self, tmp_path):
        """Successful learn execution."""
        agent = _make_teacher(tmp_path)
        agent.set_learn_fn(lambda fid, simple: {"success": True})

        strategy = TeachingStrategy(TeachingStrategy.LEARN_NEW, "file.txt")
        result = agent._execute_strategy(strategy)

        assert result["success"] is True
        assert result["type"] == "learn"
        assert agent._stats["chunks_learned"] == 1

    def test_exec_learn_failure(self, tmp_path):
        """Failed learn execution."""
        agent = _make_teacher(tmp_path)
        agent.set_learn_fn(lambda fid, simple: {"success": False, "error": "timeout"})

        strategy = TeachingStrategy(TeachingStrategy.LEARN_NEW, "file.txt")
        result = agent._execute_strategy(strategy)

        assert result["success"] is False
        assert agent._stats["chunks_learned"] == 0

    def test_exec_learn_no_fn_configured(self, tmp_path):
        """Learn without configured function."""
        agent = _make_teacher(tmp_path)

        strategy = TeachingStrategy(TeachingStrategy.LEARN_NEW, "file.txt")
        result = agent._execute_strategy(strategy)

        assert result["success"] is False
        assert "No learn function" in result["error"]

    def test_exec_review_pass(self, tmp_path):
        """Successful exam (passed)."""
        agent = _make_teacher(tmp_path)
        agent.set_exam_fn(lambda fid: {"success": True, "passed": True, "score": 0.85})

        strategy = TeachingStrategy(TeachingStrategy.REVIEW, "file.txt")
        result = agent._execute_strategy(strategy)

        assert result["success"] is True
        assert result["passed"] is True
        assert agent._stats["exams_run"] == 1
        assert agent._stats["exams_passed"] == 1

    def test_exec_review_fail(self, tmp_path):
        """Successful exam (failed score)."""
        agent = _make_teacher(tmp_path)
        agent.set_exam_fn(lambda fid: {"success": True, "passed": False, "score": 0.45})

        strategy = TeachingStrategy(TeachingStrategy.REVIEW, "file.txt")
        result = agent._execute_strategy(strategy)

        assert result["success"] is True
        assert result["passed"] is False
        assert agent._stats["exams_run"] == 1
        assert agent._stats["exams_passed"] == 0

    def test_exec_fill_gap(self, tmp_path):
        """Fill gap uses simple prompt."""
        calls = []
        agent = _make_teacher(tmp_path)
        agent.set_learn_fn(lambda fid, simple: (calls.append(simple), {"success": True})[1])

        strategy = TeachingStrategy(TeachingStrategy.FILL_GAP, "hard.txt")
        result = agent._execute_strategy(strategy)

        assert result["success"] is True
        assert calls == [True]  # use_simple=True

    def test_run_session_basic(self, tmp_path):
        """Run session with mock learn function."""
        learn_count = [0]

        def mock_learn(fid, simple):
            learn_count[0] += 1
            return {"success": True}

        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("f1.txt", status="new", priority=80),
        ])
        agent.set_learn_fn(mock_learn)

        status = agent.run_session(max_iterations=2)

        assert status["stats"]["strategies_executed"] >= 1
        assert learn_count[0] >= 1

    def test_run_session_stops_when_nothing_to_do(self, tmp_path):
        """Session stops early when no work."""
        agent = _make_teacher(tmp_path)  # Empty index

        status = agent.run_session(max_iterations=10)

        assert status["stats"]["strategies_executed"] == 0
        assert status["running"] is False

    def test_run_session_callback(self, tmp_path):
        """Callback is called after each iteration."""
        callback_calls = []

        def cb(iteration, strategy_type, result):
            callback_calls.append((iteration, strategy_type))

        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("f1.txt", status="new"),
        ])
        agent.set_learn_fn(lambda fid, simple: {"success": True})

        agent.run_session(max_iterations=1, callback=cb)

        assert len(callback_calls) == 1
        assert callback_calls[0][0] == 1  # iteration

    def test_stop_session(self, tmp_path):
        """Stop interrupts session."""
        iterations_done = [0]

        def slow_learn(fid, simple):
            iterations_done[0] += 1
            if iterations_done[0] >= 2:
                agent.stop()
            return {"success": True}

        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("f1.txt", status="new"),
            _make_index_record("f2.txt", status="new"),
            _make_index_record("f3.txt", status="new"),
        ])
        agent.set_learn_fn(slow_learn)

        status = agent.run_session(max_iterations=10)

        assert status["stats"]["strategies_executed"] <= 3

    def test_plan_persistence(self, tmp_path):
        """Plans are logged to JSONL."""
        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("f1.txt", status="new"),
        ])
        agent.set_learn_fn(lambda fid, simple: {"success": True})

        agent.run_session(max_iterations=1)

        history = agent.get_history()
        assert len(history) >= 1
        assert "strategy" in history[0]
        assert "result" in history[0]

    def test_get_next_plan_preview(self, tmp_path):
        """Preview next strategy without executing."""
        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("f1.txt", status="new", priority=80),
        ])

        preview = agent.get_next_plan_preview()
        assert preview is not None
        assert preview["strategy_type"] == TeachingStrategy.LEARN_NEW
        assert preview["target_file_id"] == "f1.txt"

    def test_get_next_plan_preview_empty(self, tmp_path):
        """Preview when nothing to do."""
        agent = _make_teacher(tmp_path)
        assert agent.get_next_plan_preview() is None

    def test_get_status(self, tmp_path):
        """Status dict structure."""
        agent = _make_teacher(tmp_path)
        status = agent.get_status()

        assert "running" in status
        assert "iteration" in status
        assert "stats" in status
        assert "nim_planning_used" in status
        assert status["running"] is False
        assert status["iteration"] == 0


# ══════════════════════════════════════════════════════
# TestTeacherModule
# ══════════════════════════════════════════════════════

_UNSET = object()


class MockContext:
    """Minimal SharedContext mock for module tests."""

    def __init__(self, brain=_UNSET):
        self.brain = MockRouter() if brain is _UNSET else brain
        self.semantic_memory = None


class TestTeacherModule:
    """Tests for REPL module registration and commands."""

    def test_module_init(self):
        from agent_core.modules.teacher_module import TeacherModule
        mod = TeacherModule()
        ctx = MockContext()
        assert mod.init(ctx) is True
        assert mod.name == "teacher"

    def test_module_commands(self):
        from agent_core.modules.teacher_module import TeacherModule
        mod = TeacherModule()
        ctx = MockContext()
        mod.init(ctx)
        commands = mod.get_commands()
        assert len(commands) == 1
        assert commands[0].name == "/teacher"

    def test_lazy_init_creates_agent(self):
        from agent_core.modules.teacher_module import TeacherModule
        mod = TeacherModule()
        ctx = MockContext()
        mod.init(ctx)
        agent = mod._get_agent()
        assert agent is not None

    def test_no_brain_returns_none(self, capsys):
        from agent_core.modules.teacher_module import TeacherModule
        mod = TeacherModule()
        ctx = MockContext(brain=None)
        mod.init(ctx)
        agent = mod._get_agent()
        assert agent is None

    def test_show_plan(self, capsys):
        from agent_core.modules.teacher_module import TeacherModule
        mod = TeacherModule()
        ctx = MockContext()
        mod.init(ctx)
        mod._show_plan()
        out = capsys.readouterr().out
        assert "Brak pracy" in out or "Nastepny krok" in out


# ══════════════════════════════════════════════════════
# TestTeacherAutoTrigger
# ══════════════════════════════════════════════════════

class MockTeacherAgent:
    """Lightweight mock of TeacherAgent for homeostasis trigger tests."""

    def __init__(self):
        self.sessions_run = 0
        self.stopped = False
        self._running = False

    def run_session(self, max_iterations=3, callback=None):
        self._running = True
        self.sessions_run += 1
        self._running = False
        return {"stats": {"strategies_executed": 1, "chunks_learned": 1, "exams_run": 0}}

    def stop(self):
        self.stopped = True
        self._running = False


class TestTeacherAutoTrigger:
    """Tests for autonomous teacher triggering via homeostasis."""

    def _make_core(self, tmp_path):
        """Create HomeostasisCore with mocked event logger."""
        from agent_core.homeostasis.event_logger import HomeostasisEventLogger
        log_path = tmp_path / "events.jsonl"
        event_logger = HomeostasisEventLogger(log_path=log_path)

        core = HomeostasisCore(event_logger=event_logger)
        return core

    def test_trigger_when_idle_and_active(self, tmp_path):
        """Teacher triggers when ACTIVE + idle > threshold."""
        core = self._make_core(tmp_path)
        teacher = MockTeacherAgent()
        core.set_teacher_agent(teacher)

        # Simulate idle state
        core.state.mode = Mode.ACTIVE
        core.state.idle_seconds = 700  # > 600 threshold
        core._teacher_last_run = 0  # No cooldown

        core._check_teacher_trigger()

        # Thread should be started
        assert core._teacher_thread is not None
        core._teacher_thread.join(timeout=5)
        assert teacher.sessions_run == 1

    def test_no_trigger_when_not_idle(self, tmp_path):
        """No trigger when idle < threshold."""
        core = self._make_core(tmp_path)
        teacher = MockTeacherAgent()
        core.set_teacher_agent(teacher)

        core.state.mode = Mode.ACTIVE
        core.state.idle_seconds = 300  # < 600

        core._check_teacher_trigger()

        assert core._teacher_thread is None
        assert teacher.sessions_run == 0

    def test_no_trigger_when_not_active(self, tmp_path):
        """No trigger in REDUCED/SLEEP/SURVIVAL mode."""
        core = self._make_core(tmp_path)
        teacher = MockTeacherAgent()
        core.set_teacher_agent(teacher)

        for mode in [Mode.REDUCED, Mode.SLEEP, Mode.SURVIVAL]:
            core.state.mode = mode
            core.state.idle_seconds = 700

            core._check_teacher_trigger()

            assert core._teacher_thread is None
            assert teacher.sessions_run == 0

    def test_no_trigger_during_cooldown(self, tmp_path):
        """No trigger when cooldown hasn't expired."""
        core = self._make_core(tmp_path)
        teacher = MockTeacherAgent()
        core.set_teacher_agent(teacher)

        core.state.mode = Mode.ACTIVE
        core.state.idle_seconds = 700
        core._teacher_last_run = time.time() - 60  # Only 60s ago (< 900 cooldown)

        core._check_teacher_trigger()

        assert core._teacher_thread is None
        assert teacher.sessions_run == 0

    def test_no_trigger_when_session_running(self, tmp_path):
        """No trigger when a session is already in progress."""
        core = self._make_core(tmp_path)
        teacher = MockTeacherAgent()
        core.set_teacher_agent(teacher)

        core.state.mode = Mode.ACTIVE
        core.state.idle_seconds = 700

        # Fake a running thread
        fake_thread = threading.Thread(target=lambda: time.sleep(10), daemon=True)
        fake_thread.start()
        core._teacher_thread = fake_thread

        core._check_teacher_trigger()

        # Should not start another session
        assert teacher.sessions_run == 0

    def test_no_trigger_without_teacher_set(self, tmp_path):
        """No trigger when teacher agent not configured."""
        core = self._make_core(tmp_path)
        core.state.mode = Mode.ACTIVE
        core.state.idle_seconds = 700

        core._check_teacher_trigger()

        assert core._teacher_thread is None

    def test_stop_on_mode_transition(self, tmp_path):
        """Teacher stopped when leaving ACTIVE mode."""
        core = self._make_core(tmp_path)
        teacher = MockTeacherAgent()
        core.set_teacher_agent(teacher)

        core._transition_mode(Mode.ACTIVE, Mode.REDUCED)

        assert teacher.stopped is True

    def test_no_stop_when_staying_active(self, tmp_path):
        """No stop if transition doesn't leave ACTIVE."""
        core = self._make_core(tmp_path)
        teacher = MockTeacherAgent()
        core.set_teacher_agent(teacher)

        # Transition from REDUCED to ACTIVE should not stop teacher
        core._transition_mode(Mode.REDUCED, Mode.ACTIVE)

        assert teacher.stopped is False

    def test_event_logged_after_session(self, tmp_path):
        """Teacher session logs event to JSONL."""
        from agent_core.homeostasis.event_logger import HomeostasisEventLogger
        log_path = tmp_path / "events.jsonl"
        event_logger = HomeostasisEventLogger(log_path=log_path)

        core = HomeostasisCore(event_logger=event_logger)
        teacher = MockTeacherAgent()
        core.set_teacher_agent(teacher)

        core.state.mode = Mode.ACTIVE
        core.state.idle_seconds = 700

        core._check_teacher_trigger()
        core._teacher_thread.join(timeout=5)

        # Check event log
        events = event_logger.get_recent_events(limit=10)
        teacher_events = [e for e in events if e.get("event") == "teacher_session"]
        assert len(teacher_events) == 1
        assert teacher_events[0]["trigger"] == "idle_auto"
        assert teacher_events[0]["chunks_learned"] == 1

    def test_cooldown_set_after_session(self, tmp_path):
        """_teacher_last_run updated after session completes."""
        core = self._make_core(tmp_path)
        teacher = MockTeacherAgent()
        core.set_teacher_agent(teacher)

        before = time.time()
        core.state.mode = Mode.ACTIVE
        core.state.idle_seconds = 700

        core._check_teacher_trigger()
        core._teacher_thread.join(timeout=5)

        assert core._teacher_last_run >= before


# ══════════════════════════════════════════════════════
# Topic Awareness - KnowledgeAnalyzer
# ══════════════════════════════════════════════════════


class TestNormalizeTag:
    """Tests for KnowledgeAnalyzer._normalize_tag()."""

    def test_basic_normalization(self):
        assert KnowledgeAnalyzer._normalize_tag("Fizyka") == "fizyka"
        assert KnowledgeAnalyzer._normalize_tag("  LOGIKA  ") == "logika"

    def test_rejects_stop_words(self):
        assert KnowledgeAnalyzer._normalize_tag("inne") is None
        assert KnowledgeAnalyzer._normalize_tag("Ogolne") is None
        assert KnowledgeAnalyzer._normalize_tag("WIEDZA") is None
        assert KnowledgeAnalyzer._normalize_tag("misc") is None

    def test_rejects_short_tags(self):
        assert KnowledgeAnalyzer._normalize_tag("x") is None
        assert KnowledgeAnalyzer._normalize_tag("") is None

    def test_rejects_long_tags(self):
        assert KnowledgeAnalyzer._normalize_tag("a" * 41) is None

    def test_accepts_valid_tags(self):
        assert KnowledgeAnalyzer._normalize_tag("ab") == "ab"
        assert KnowledgeAnalyzer._normalize_tag("a" * 40) == "a" * 40
        assert KnowledgeAnalyzer._normalize_tag("fizyka kwantowa") == "fizyka kwantowa"


def _make_memory_record(source_file, tags):
    """Create a longterm memory record with tags."""
    return {
        "source_file": source_file,
        "chunk_id": f"{source_file}#chunk_0",
        "chunk_index": 0,
        "summary": "test summary",
        "tags": tags,
        "timestamp": "2026-03-01T12:00:00Z",
    }


class TestTopicFileMap:
    """Tests for KnowledgeAnalyzer.get_topic_file_map()."""

    def test_basic_map(self, tmp_path):
        mem_path = tmp_path / "memory.jsonl"
        _write_jsonl(mem_path, [
            _make_memory_record("fizyka.txt", ["fizyka", "mechanika"]),
            _make_memory_record("fizyka2.txt", ["fizyka", "optyka"]),
            _make_memory_record("logika.txt", ["logika"]),
        ])

        analyzer = KnowledgeAnalyzer(
            knowledge_index_path=tmp_path / "idx.jsonl",
            longterm_memory_path=mem_path,
            exam_results_path=tmp_path / "exam.jsonl",
            input_dir=tmp_path / "input",
        )
        topic_map = analyzer.get_topic_file_map()

        assert "fizyka" in topic_map
        assert len(topic_map["fizyka"]) == 2
        assert "logika" in topic_map
        assert len(topic_map["logika"]) == 1

    def test_empty_memory(self, tmp_path):
        analyzer = KnowledgeAnalyzer(
            knowledge_index_path=tmp_path / "idx.jsonl",
            longterm_memory_path=tmp_path / "empty_mem.jsonl",
            exam_results_path=tmp_path / "exam.jsonl",
            input_dir=tmp_path / "input",
        )
        assert analyzer.get_topic_file_map() == {}

    def test_cache_ttl(self, tmp_path):
        mem_path = tmp_path / "memory.jsonl"
        _write_jsonl(mem_path, [
            _make_memory_record("file1.txt", ["tag1"]),
        ])

        analyzer = KnowledgeAnalyzer(
            knowledge_index_path=tmp_path / "idx.jsonl",
            longterm_memory_path=mem_path,
            exam_results_path=tmp_path / "exam.jsonl",
            input_dir=tmp_path / "input",
        )
        result1 = analyzer.get_topic_file_map()
        assert "tag1" in result1

        # Add more data
        _write_jsonl(mem_path, [
            _make_memory_record("file1.txt", ["tag1"]),
            _make_memory_record("file2.txt", ["tag2"]),
        ])

        # Same result (cached)
        result2 = analyzer.get_topic_file_map()
        assert result2 is result1  # Same object = cache hit

        # Expire cache
        analyzer._topic_map_cache_ts = 0.0
        result3 = analyzer.get_topic_file_map()
        assert "tag2" in result3  # Now sees the new data

    def test_stop_words_excluded(self, tmp_path):
        mem_path = tmp_path / "memory.jsonl"
        _write_jsonl(mem_path, [
            _make_memory_record("file.txt", ["fizyka", "inne", "wiedza"]),
        ])

        analyzer = KnowledgeAnalyzer(
            knowledge_index_path=tmp_path / "idx.jsonl",
            longterm_memory_path=mem_path,
            exam_results_path=tmp_path / "exam.jsonl",
            input_dir=tmp_path / "input",
        )
        topic_map = analyzer.get_topic_file_map()
        assert "fizyka" in topic_map
        assert "inne" not in topic_map
        assert "wiedza" not in topic_map


class TestGetFilesForTopics:
    """Tests for KnowledgeAnalyzer.get_files_for_topics() with scoring."""

    def _make_analyzer(self, tmp_path, mem_records, idx_records=None):
        mem_path = tmp_path / "memory.jsonl"
        idx_path = tmp_path / "idx.jsonl"
        _write_jsonl(mem_path, mem_records)
        if idx_records:
            _write_jsonl(idx_path, idx_records)
        return KnowledgeAnalyzer(
            knowledge_index_path=idx_path,
            longterm_memory_path=mem_path,
            exam_results_path=tmp_path / "exam.jsonl",
            input_dir=tmp_path / "input",
        )

    def test_exact_match_scores_highest(self, tmp_path):
        """Exact tag match gets +3.0."""
        analyzer = self._make_analyzer(tmp_path, [
            _make_memory_record("exact.txt", ["fizyka"]),
            _make_memory_record("partial.txt", ["fizyka kwantowa"]),
        ])
        results = analyzer.get_files_for_topics(["fizyka"])
        assert len(results) == 2
        # exact.txt should score higher (exact=3 vs prefix=2)
        assert results[0][0] == "exact.txt"
        assert results[0][1] > results[1][1]

    def test_prefix_vs_substring_scoring(self, tmp_path):
        """'fizyk' should prefer 'fizyka kwantowa' (prefix=2) over 'metafizyka' (substring=1)."""
        analyzer = self._make_analyzer(tmp_path, [
            _make_memory_record("fizyka_file.txt", ["fizyka kwantowa"]),
            _make_memory_record("meta_file.txt", ["metafizyka"]),
        ])
        results = analyzer.get_files_for_topics(["fizyk"])
        assert len(results) == 2
        # fizyka_file scores higher: prefix(2) > substring(1)
        assert results[0][0] == "fizyka_file.txt"
        assert results[0][1] > results[1][1]

    def test_filename_fallback(self, tmp_path):
        """File with matching name gets +0.5 even without tag match."""
        analyzer = self._make_analyzer(tmp_path, [], idx_records=[
            _make_index_record("fizyka_intro.txt"),
            _make_index_record("matematyka.txt"),
        ])
        results = analyzer.get_files_for_topics(["fizyka"])
        assert len(results) == 1
        assert results[0][0] == "fizyka_intro.txt"
        assert results[0][1] == 0.5

    def test_empty_topics(self, tmp_path):
        analyzer = self._make_analyzer(tmp_path, [
            _make_memory_record("file.txt", ["tag"]),
        ])
        assert analyzer.get_files_for_topics([]) == []
        assert analyzer.get_files_for_topics([""]) == []

    def test_case_insensitive(self, tmp_path):
        analyzer = self._make_analyzer(tmp_path, [
            _make_memory_record("file.txt", ["Fizyka"]),
        ])
        results = analyzer.get_files_for_topics(["FIZYKA"])
        assert len(results) == 1


class TestSnapshotTopicsAvailable:
    """Test that get_knowledge_snapshot() includes topics_available."""

    def test_snapshot_has_topics(self, tmp_path):
        mem_path = tmp_path / "memory.jsonl"
        idx_path = tmp_path / "idx.jsonl"
        _write_jsonl(mem_path, [
            _make_memory_record("f1.txt", ["fizyka", "optyka"]),
        ])
        _write_jsonl(idx_path, [
            _make_index_record("f1.txt", status="completed"),
        ])
        (tmp_path / "input").mkdir(exist_ok=True)

        analyzer = KnowledgeAnalyzer(
            knowledge_index_path=idx_path,
            longterm_memory_path=mem_path,
            exam_results_path=tmp_path / "exam.jsonl",
            input_dir=tmp_path / "input",
        )
        snapshot = analyzer.get_knowledge_snapshot()
        assert "topics_available" in snapshot
        assert "fizyka" in snapshot["topics_available"]
        assert "optyka" in snapshot["topics_available"]


# ══════════════════════════════════════════════════════
# Topic Filtering - TeacherAgent
# ══════════════════════════════════════════════════════


class TestTeacherTopicFilter:
    """Tests for filter_file_ids in TeacherAgent."""

    def test_filter_selects_matching_file(self, tmp_path):
        """With filter, Teacher picks only matching files."""
        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("fizyka.txt", status="new", priority=90),
            _make_index_record("historia.txt", status="new", priority=100),
        ])
        agent._learn_chunk_fn = lambda fid, simple: {"success": True}

        status = agent.run_session(
            max_iterations=1,
            filter_file_ids=["fizyka.txt"],
        )
        stats = status.get("stats", {})
        assert stats["chunks_learned"] == 1
        assert stats["strategies_executed"] == 1

    def test_filter_blocks_all_candidates_idle(self, tmp_path):
        """When filter removes all candidates, Teacher goes IDLE."""
        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("historia.txt", status="new", priority=100),
        ])
        status = agent.run_session(
            max_iterations=1,
            filter_file_ids=["fizyka.txt"],
        )
        stats = status.get("stats", {})
        assert stats["strategies_executed"] == 0
        assert stats.get("idle_reason") == "filtered_out_all_candidates"
        assert stats.get("filtered_out_count", 0) > 0

    def test_filter_blocks_p1_in_progress(self, tmp_path):
        """Filter blocks P1 continue_partial if file not in filter."""
        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("historia.txt", status="learning",
                               chunks_learned=1, total_chunks=3),
        ])
        status = agent.run_session(
            max_iterations=1,
            filter_file_ids=["fizyka.txt"],
        )
        stats = status.get("stats", {})
        assert stats["strategies_executed"] == 0
        assert stats.get("idle_reason") == "filtered_out_all_candidates"

    def test_no_filter_backward_compatible(self, tmp_path):
        """Without filter, Teacher works as before."""
        agent = _make_teacher(tmp_path, index_records=[
            _make_index_record("file.txt", status="new", priority=50),
        ])
        agent._learn_chunk_fn = lambda fid, simple: {"success": True}

        status = agent.run_session(max_iterations=1)
        stats = status.get("stats", {})
        assert stats["chunks_learned"] == 1
