"""
Tests for Unified Memory Query API (Phase 2).

Covers: MemoryQuery topic search, provenance, freshness, gap detection.
"""

import json
import time
from pathlib import Path

import pytest

from agent_core.memory.query import (
    MemoryQuery, MemoryResult, MemorySource, _freshness_score, _parse_ts,
)


# -- Helpers --

def _write_jsonl(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# -- Freshness --

class TestFreshness:
    def test_now_is_fresh(self):
        score = _freshness_score(time.time())
        assert score >= 0.99

    def test_old_is_stale(self):
        week_ago = time.time() - 168 * 3600
        score = _freshness_score(week_ago)
        assert score <= 0.01

    def test_half_age(self):
        half = time.time() - 84 * 3600
        score = _freshness_score(half)
        assert 0.4 < score < 0.6

    def test_zero_ts(self):
        assert _freshness_score(0) == 0.0

    def test_future_ts(self):
        assert _freshness_score(time.time() + 100) == 1.0


class TestParseTs:
    def test_float(self):
        ts = _parse_ts(1700000000.0)
        assert ts == 1700000000.0

    def test_int(self):
        ts = _parse_ts(1700000000)
        assert ts == 1700000000.0

    def test_iso8601(self):
        ts = _parse_ts("2026-03-28T12:00:00")
        assert ts > 0

    def test_empty(self):
        assert _parse_ts("") == 0.0
        assert _parse_ts(None) == 0.0


# -- MemoryResult --

class TestMemoryResult:
    def test_to_dict(self):
        r = MemoryResult(
            source=MemorySource.KNOWLEDGE_INDEX,
            content="Plik fotosynteza.txt: status=completed",
            confidence=0.85,
            freshness=0.9,
            relevance=0.95,
            provenance={"file_id": "fotosynteza"},
        )
        d = r.to_dict()
        assert d["source"] == "knowledge_index"
        assert d["confidence"] == 0.85
        assert d["provenance"]["file_id"] == "fotosynteza"


# -- MemoryQuery --

class TestMemoryQuery:
    def _make_query(self, tmp_path, knowledge=None, beliefs=None):
        kp = tmp_path / "memory" / "knowledge_index.jsonl"
        bp = tmp_path / "meta_data" / "beliefs.jsonl"

        if knowledge:
            _write_jsonl(kp, knowledge)
        if beliefs:
            _write_jsonl(bp, beliefs)

        return MemoryQuery(
            knowledge_path=kp,
            beliefs_path=bp,
            exam_path=tmp_path / "memory" / "exam_results.jsonl",
            hints_path=tmp_path / "meta_data" / "topic_hints.jsonl",
        )

    def test_query_empty(self, tmp_path):
        mq = self._make_query(tmp_path)
        results = mq.query_topic("fizyka")
        assert results == []

    def test_query_knowledge_match(self, tmp_path):
        mq = self._make_query(tmp_path, knowledge=[
            {"id": "fizyka_01", "file": "expert_fizyka.txt", "status": "completed",
             "chunks_learned": 5, "total_chunks": 5, "last_scores": [0.8, 0.9],
             "updated_at": time.time()},
            {"id": "biologia_01", "file": "expert_biologia.txt", "status": "new",
             "chunks_learned": 0, "total_chunks": 3, "updated_at": time.time()},
        ])
        results = mq.query_topic("fizyka")
        assert len(results) == 1
        assert results[0].source == MemorySource.KNOWLEDGE_INDEX
        assert "fizyka" in results[0].content.lower()
        assert results[0].confidence > 0.5  # avg of 0.8 and 0.9

    def test_query_beliefs_match(self, tmp_path):
        mq = self._make_query(tmp_path, beliefs=[
            {"entity": "fotosynteza", "content": "Proces zamiany swiatla w energie",
             "confidence": 0.7, "tags": ["biologia", "rosliny"],
             "source": "learning", "created_at": time.time()},
        ])
        results = mq.query_topic("fotosynteza")
        assert len(results) == 1
        assert results[0].source == MemorySource.BELIEFS
        assert results[0].confidence == 0.7

    def test_query_both_sources(self, tmp_path):
        mq = self._make_query(tmp_path,
            knowledge=[
                {"id": "genetyka_01", "file": "expert_genetyka.txt", "status": "learning",
                 "chunks_learned": 2, "total_chunks": 4, "last_scores": [],
                 "updated_at": time.time()},
            ],
            beliefs=[
                {"entity": "genetyka", "content": "Nauka o dziedziczeniu cech",
                 "confidence": 0.6, "tags": ["biologia"], "source": "learning",
                 "created_at": time.time()},
            ],
        )
        results = mq.query_topic("genetyka")
        assert len(results) == 2
        sources = {r.source for r in results}
        assert MemorySource.KNOWLEDGE_INDEX in sources
        assert MemorySource.BELIEFS in sources

    def test_query_sorted_by_combined_score(self, tmp_path):
        mq = self._make_query(tmp_path,
            knowledge=[
                {"id": "fizyka_01", "file": "fizyka_kwantowa.txt", "status": "completed",
                 "chunks_learned": 5, "total_chunks": 5, "last_scores": [0.95],
                 "updated_at": time.time()},
            ],
            beliefs=[
                {"entity": "fizyka kwantowa", "content": "low confidence old belief",
                 "confidence": 0.2, "tags": [], "source": "inference",
                 "created_at": time.time() - 500000},
            ],
        )
        results = mq.query_topic("fizyka")
        assert len(results) >= 1
        # Knowledge (high confidence, fresh) should rank above belief (low confidence, old)
        if len(results) >= 2:
            assert results[0].source == MemorySource.KNOWLEDGE_INDEX

    def test_query_no_match(self, tmp_path):
        mq = self._make_query(tmp_path, knowledge=[
            {"id": "bio_01", "file": "biologia.txt", "status": "new",
             "updated_at": time.time()},
        ])
        results = mq.query_topic("astronomia")
        assert results == []

    def test_cache_invalidation(self, tmp_path):
        mq = self._make_query(tmp_path, knowledge=[
            {"id": "test_01", "file": "test.txt", "status": "new",
             "updated_at": time.time()},
        ])
        results1 = mq.query_topic("test")
        assert len(results1) == 1

        # Add more data
        kp = tmp_path / "memory" / "knowledge_index.jsonl"
        with open(kp, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "id": "test_02", "file": "test2.txt", "status": "learning",
                "updated_at": time.time(),
            }) + "\n")

        mq._invalidate_cache()
        results2 = mq.query_topic("test")
        assert len(results2) == 2

    def test_superseded_beliefs_excluded(self, tmp_path):
        mq = self._make_query(tmp_path, beliefs=[
            {"entity": "atom", "content": "old belief", "confidence": 0.3,
             "created_at": time.time() - 1000, "superseded_by": "belief-new"},
            {"entity": "atom", "content": "new belief", "confidence": 0.8,
             "created_at": time.time()},
        ])
        results = mq.query_topic("atom")
        assert len(results) == 1
        assert results[0].confidence == 0.8


# -- Topic Summary --

class TestTopicSummary:
    def test_unknown_topic(self, tmp_path):
        mq = MemoryQuery(
            knowledge_path=tmp_path / "k.jsonl",
            beliefs_path=tmp_path / "b.jsonl",
        )
        summary = mq.get_topic_summary("unknown")
        assert summary["known"] is False

    def test_known_topic(self, tmp_path):
        kp = tmp_path / "k.jsonl"
        _write_jsonl(kp, [
            {"id": "bio", "file": "biologia.txt", "status": "completed",
             "last_scores": [0.9], "updated_at": time.time()},
        ])
        mq = MemoryQuery(knowledge_path=kp, beliefs_path=tmp_path / "b.jsonl")
        summary = mq.get_topic_summary("biologia")
        assert summary["known"] is True
        assert summary["files_count"] == 1
        assert summary["avg_confidence"] > 0.5


# -- Knowledge Gaps --

class TestKnowledgeGaps:
    def test_low_confidence_beliefs(self, tmp_path):
        bp = tmp_path / "b.jsonl"
        _write_jsonl(bp, [
            {"entity": "strong_topic", "confidence": 0.9, "source": "learning"},
            {"entity": "weak_topic", "confidence": 0.3, "source": "inference"},
            {"entity": "very_weak", "confidence": 0.1, "source": "inference"},
        ])
        mq = MemoryQuery(knowledge_path=tmp_path / "k.jsonl", beliefs_path=bp)
        gaps = mq.get_knowledge_gaps(top_k=5)
        assert len(gaps) == 2  # Only confidence < 0.5
        assert gaps[0]["confidence"] < gaps[1]["confidence"]  # Sorted ascending

    def test_exam_failed_files(self, tmp_path):
        kp = tmp_path / "k.jsonl"
        _write_jsonl(kp, [
            {"id": "ok_file", "file": "ok.txt", "status": "completed"},
            {"id": "failed_file", "file": "fail.txt", "status": "exam_failed"},
            {"id": "hard_file", "file": "hard.txt", "status": "hard_topic"},
        ])
        mq = MemoryQuery(knowledge_path=kp, beliefs_path=tmp_path / "b.jsonl")
        gaps = mq.get_knowledge_gaps(top_k=5)
        assert len(gaps) == 2
        reasons = [g["reason"] for g in gaps]
        assert "exam_failed" in reasons
        assert "hard_topic" in reasons


# -- Staleness fix A: vector cleanup --

class TestVectorCleanup:
    def test_cleanup_stale_vectors(self, tmp_path):
        from agent_core.semantic.indexer import cleanup_stale_vectors
        from unittest.mock import MagicMock

        sm = MagicMock()
        # Store has 3 entries, but knowledge only has 2 files
        sm.store.list_ids_by_namespace.return_value = [
            "knowledge:file_a", "knowledge:file_b", "knowledge:file_c"
        ]

        kp = tmp_path / "knowledge_index.jsonl"
        _write_jsonl(kp, [
            {"id": "file_a"},
            {"id": "file_b"},
            # file_c is missing -> should be removed
        ])

        removed = cleanup_stale_vectors(sm, str(kp))
        assert removed == 1
        sm.remove.assert_called_once_with("knowledge:file_c")
        sm.store.save_full.assert_called_once()

    def test_cleanup_no_stale(self, tmp_path):
        from agent_core.semantic.indexer import cleanup_stale_vectors
        from unittest.mock import MagicMock

        sm = MagicMock()
        sm.store.list_ids_by_namespace.return_value = ["knowledge:file_a"]

        kp = tmp_path / "knowledge_index.jsonl"
        _write_jsonl(kp, [{"id": "file_a"}])

        removed = cleanup_stale_vectors(sm, str(kp))
        assert removed == 0
        sm.remove.assert_not_called()
