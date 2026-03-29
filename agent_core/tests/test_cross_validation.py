"""
Tests for Multi-Source Learning: CrossValidator, ConfidenceScorer, DisputeLog.

Tests:
- ConfidenceScorer: scoring dimensions, edge cases
- DisputeLog: CRUD, persistence, stats
- CrossValidator: validate_chunk, validate_file, LLM integration
"""

import json
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_core.cross_validation.confidence_scorer import (
    ConfidenceScorer,
    _normalize_text,
    _extract_keywords,
    _jaccard_similarity,
    _list_overlap,
)
from agent_core.cross_validation.dispute_log import DisputeLog, DisputeRecord
from agent_core.cross_validation.cross_validator import (
    CrossValidator,
    VALIDATION_THRESHOLD,
)


# ---- Helper data ----

RESULT_A = {
    "summary": "Fotosynteza to proces w ktorym rosliny przeksztalcaja swiatlo sloneczne "
               "w energie chemiczna. Zachodzi w chloroplastach przy udziale chlorofilu.",
    "key_points": [
        "Fotosynteza zachodzi w chloroplastach",
        "Chlorofil absorbuje swiatlo",
        "CO2 i woda sa substratami",
        "Produktem jest glukoza i tlen",
        "Proces dzieli sie na faze jasna i ciemna",
    ],
    "tags": ["fotosynteza", "chloroplast", "chlorofil", "glukoza", "tlen", "rosliny"],
}

RESULT_B_SIMILAR = {
    "summary": "Fotosynteza jest procesem biologicznym w roslinach. Energia sloneczna "
               "jest przetwarzana na energie chemiczna w chloroplastach.",
    "key_points": [
        "Fotosynteza to proces biologiczny roslin",
        "Chloroplasty sa miejscem fotosyntezy",
        "Swiatlo jest zrodlem energii",
        "Woda i dwutlenek wegla sa potrzebne",
        "Powstaje glukoza",
    ],
    "tags": ["fotosynteza", "chloroplast", "rosliny", "energia", "glukoza", "swiatlo"],
}

RESULT_B_DIFFERENT = {
    "summary": "Algorytmy sortowania dzielimy na porownawcze i nieporownawcze. "
               "Quicksort jest jednym z najszybszych algorytmow sortowania.",
    "key_points": [
        "Quicksort ma zlozonosc O(n log n) srednio",
        "Mergesort jest stabilny",
        "Bubblesort jest najprostszy",
    ],
    "tags": ["algorytmy", "sortowanie", "quicksort", "mergesort", "zlozonosc"],
}


# ---- ConfidenceScorer ----

class TestNormalizeText:

    def test_lowercase(self):
        assert _normalize_text("Hello World") == "hello world"

    def test_strip_punctuation(self):
        assert _normalize_text("a, b! c?") == "a b c"

    def test_normalize_whitespace(self):
        assert _normalize_text("  a   b  ") == "a b"


class TestExtractKeywords:

    def test_short_words_filtered(self):
        kw = _extract_keywords("I am a big cat on a mat")
        assert "am" not in kw  # 2 chars, below MIN_WORD_LEN
        assert "cat" in kw
        assert "mat" in kw

    def test_empty_string(self):
        assert _extract_keywords("") == set()


class TestJaccardSimilarity:

    def test_identical_sets(self):
        assert _jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        assert _jaccard_similarity({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        sim = _jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"})
        assert sim == pytest.approx(2 / 4)

    def test_both_empty(self):
        assert _jaccard_similarity(set(), set()) == 1.0

    def test_one_empty(self):
        assert _jaccard_similarity(set(), {"a"}) == 0.0


class TestListOverlap:

    def test_identical_lists(self):
        items = ["fotosynteza zachodzi w chloroplastach", "chlorofil absorbuje swiatlo"]
        assert _list_overlap(items, items) == 1.0

    def test_no_overlap(self):
        a = ["fotosynteza w roslinach"]
        b = ["algorytmy sortowania"]
        assert _list_overlap(a, b) == 0.0

    def test_empty_lists(self):
        assert _list_overlap([], []) == 1.0
        assert _list_overlap([], ["x"]) == 0.0
        assert _list_overlap(["x"], []) == 0.0


class TestConfidenceScorer:

    def test_similar_results_higher_than_different(self):
        scorer = ConfidenceScorer()
        score_sim = scorer.score(RESULT_A, RESULT_B_SIMILAR)
        score_diff = scorer.score(RESULT_A, RESULT_B_DIFFERENT)
        # Similar results should score higher than completely different
        assert score_sim["overall"] > score_diff["overall"]
        assert score_sim["tags_agreement"] > score_diff["tags_agreement"]

    def test_different_results_low_confidence(self):
        scorer = ConfidenceScorer()
        score = scorer.score(RESULT_A, RESULT_B_DIFFERENT)
        assert score["overall"] < 0.3
        assert len(score["disputes"]) > 0

    def test_identical_results_perfect_score(self):
        scorer = ConfidenceScorer()
        score = scorer.score(RESULT_A, RESULT_A)
        assert score["overall"] == 1.0
        assert score["summary_similarity"] == 1.0
        assert score["tags_agreement"] == 1.0
        assert len(score["disputes"]) == 0

    def test_empty_results(self):
        scorer = ConfidenceScorer()
        score = scorer.score({}, {})
        assert score["overall"] >= 0.0

    def test_one_empty_one_full(self):
        scorer = ConfidenceScorer()
        score = scorer.score(RESULT_A, {})
        assert score["overall"] < 0.5

    def test_simple_format_supported(self):
        """Supports summary_simple and core_ideas from simplified learning."""
        scorer = ConfidenceScorer()
        simple = {
            "summary_simple": "Fotosynteza to proces w roslinach.",
            "core_ideas": ["rosliny", "swiatlo", "chloroplast"],
            "tags": ["fotosynteza"],
        }
        score = scorer.score(RESULT_A, simple)
        assert score["overall"] > 0.0


# ---- DisputeLog ----

class TestDisputeRecord:

    def test_creation(self):
        r = DisputeRecord(
            dispute_id="disp-abc",
            chunk_id="file#chunk_0",
            file_id="file.txt",
            source_a="ollama",
            source_b="nim",
            dimension="summary",
            severity="high",
            detail="Low overlap",
            confidence_score=0.3,
            timestamp=1000.0,
        )
        assert r.resolved is False
        assert r.severity == "high"

    def test_serialization(self):
        r = DisputeRecord(
            dispute_id="disp-1",
            chunk_id="f#c0",
            file_id="f",
            source_a="a",
            source_b="b",
            dimension="tags",
            severity="low",
            detail="test",
            confidence_score=0.5,
        )
        d = r.to_dict()
        restored = DisputeRecord.from_dict(d)
        assert restored.dispute_id == r.dispute_id
        assert restored.severity == r.severity


class TestDisputeLog:

    def test_record_disputes(self, tmp_path):
        log = DisputeLog(log_path=tmp_path / "disputes.jsonl")
        disputes = [
            {"dimension": "summary", "severity": "high", "detail": "Low overlap"},
            {"dimension": "tags", "severity": "medium", "detail": "Few shared tags"},
        ]
        records = log.record_disputes(
            chunk_id="file#chunk_0",
            file_id="file.txt",
            source_a="ollama",
            source_b="nim",
            disputes=disputes,
            confidence_score=0.3,
        )
        assert len(records) == 2
        assert records[0].dimension == "summary"
        assert records[1].severity == "medium"

    def test_persistence(self, tmp_path):
        path = tmp_path / "disputes.jsonl"
        log = DisputeLog(log_path=path)
        log.record_disputes(
            chunk_id="f#c0", file_id="f",
            source_a="a", source_b="b",
            disputes=[{"dimension": "summary", "severity": "high", "detail": "x"}],
            confidence_score=0.2,
        )
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["dimension"] == "summary"

    def test_get_recent(self, tmp_path):
        log = DisputeLog(log_path=tmp_path / "d.jsonl")
        log.record_disputes("c1", "f1", "a", "b",
                           [{"dimension": "tags", "severity": "low", "detail": "x"}], 0.5)
        log.record_disputes("c2", "f1", "a", "b",
                           [{"dimension": "summary", "severity": "high", "detail": "y"}], 0.3)
        recent = log.get_recent(limit=10)
        assert len(recent) == 2

    def test_get_by_file(self, tmp_path):
        log = DisputeLog(log_path=tmp_path / "d.jsonl")
        log.record_disputes("c1", "file_a", "a", "b",
                           [{"dimension": "tags", "severity": "low", "detail": "x"}], 0.5)
        log.record_disputes("c2", "file_b", "a", "b",
                           [{"dimension": "tags", "severity": "low", "detail": "y"}], 0.5)
        by_file = log.get_by_file("file_a")
        assert len(by_file) == 1

    def test_get_unresolved(self, tmp_path):
        log = DisputeLog(log_path=tmp_path / "d.jsonl")
        log.record_disputes("c1", "f", "a", "b",
                           [{"dimension": "tags", "severity": "low", "detail": "x"}], 0.5)
        unresolved = log.get_unresolved()
        assert len(unresolved) == 1

    def test_stats(self, tmp_path):
        log = DisputeLog(log_path=tmp_path / "d.jsonl")
        log.record_disputes("c1", "f", "a", "b", [
            {"dimension": "summary", "severity": "high", "detail": "x"},
            {"dimension": "tags", "severity": "low", "detail": "y"},
        ], 0.3)
        stats = log.get_stats()
        assert stats["total"] == 2
        assert stats["by_severity"]["high"] == 1
        assert stats["by_severity"]["low"] == 1
        assert stats["by_dimension"]["summary"] == 1

    def test_thread_safety(self, tmp_path):
        log = DisputeLog(log_path=tmp_path / "d.jsonl")
        errors = []

        def worker(idx):
            try:
                log.record_disputes(
                    f"c{idx}", "f", "a", "b",
                    [{"dimension": "tags", "severity": "low", "detail": f"t{idx}"}],
                    0.5,
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert log.get_stats()["total"] == 10


# ---- CrossValidator ----

class TestCrossValidator:

    def _mock_llm(self, result_dict):
        """Create a mock LLM that returns a JSON string."""
        return lambda prompt: json.dumps(result_dict)

    def test_validate_chunk_agreement(self, tmp_path):
        llm_fn = self._mock_llm(RESULT_B_SIMILAR)
        validator = CrossValidator(
            llm_fn=llm_fn,
            source_name="nim",
            dispute_log=DisputeLog(log_path=tmp_path / "d.jsonl"),
        )
        result = validator.validate_chunk(
            chunk_id="file#chunk_0",
            file_id="file.txt",
            chunk_text="Fotosynteza to proces...",
            original_result=RESULT_A,
            primary_source="ollama",
        )
        assert result["confidence"] > 0.0
        assert "secondary_result" in result

    def test_validate_chunk_disagreement(self, tmp_path):
        llm_fn = self._mock_llm(RESULT_B_DIFFERENT)
        validator = CrossValidator(
            llm_fn=llm_fn,
            source_name="nim",
            dispute_log=DisputeLog(log_path=tmp_path / "d.jsonl"),
        )
        result = validator.validate_chunk(
            chunk_id="file#chunk_0",
            file_id="file.txt",
            chunk_text="Fotosynteza...",
            original_result=RESULT_A,
        )
        assert result["confidence"] < VALIDATION_THRESHOLD
        assert len(result["disputes"]) > 0

    def test_validate_chunk_no_llm(self):
        validator = CrossValidator(llm_fn=None)
        result = validator.validate_chunk(
            chunk_id="c", file_id="f",
            chunk_text="text", original_result=RESULT_A,
        )
        assert not result["validated"]
        assert "error" in result

    def test_validate_chunk_llm_failure(self, tmp_path):
        def failing_llm(prompt):
            raise ConnectionError("API down")

        validator = CrossValidator(
            llm_fn=failing_llm,
            dispute_log=DisputeLog(log_path=tmp_path / "d.jsonl"),
        )
        result = validator.validate_chunk(
            chunk_id="c", file_id="f",
            chunk_text="text", original_result=RESULT_A,
        )
        assert not result["validated"]
        assert "error" in result

    def test_validate_chunk_bad_response(self, tmp_path):
        validator = CrossValidator(
            llm_fn=lambda p: "not valid json at all",
            dispute_log=DisputeLog(log_path=tmp_path / "d.jsonl"),
        )
        result = validator.validate_chunk(
            chunk_id="c", file_id="f",
            chunk_text="text", original_result=RESULT_A,
        )
        assert not result["validated"]

    def test_validate_file(self, tmp_path):
        llm_fn = self._mock_llm(RESULT_B_SIMILAR)
        validator = CrossValidator(
            llm_fn=llm_fn,
            source_name="nim",
            dispute_log=DisputeLog(log_path=tmp_path / "d.jsonl"),
        )

        chunk_texts = {
            "file#chunk_0": "Fotosynteza to proces...",
            "file#chunk_1": "Chloroplasty zawieraja chlorofil...",
        }
        memories = [
            {"chunk_id": "file#chunk_0", **RESULT_A},
            {"chunk_id": "file#chunk_1", **RESULT_A},
        ]

        result = validator.validate_file(
            file_id="file.txt",
            chunk_texts=chunk_texts,
            memory_records=memories,
        )
        assert result["chunks_validated"] == 2
        assert result["avg_confidence"] > 0.0

    def test_validate_file_max_chunks(self, tmp_path):
        llm_fn = self._mock_llm(RESULT_B_SIMILAR)
        validator = CrossValidator(
            llm_fn=llm_fn,
            dispute_log=DisputeLog(log_path=tmp_path / "d.jsonl"),
        )

        chunk_texts = {f"f#c{i}": "text" for i in range(20)}
        memories = [{"chunk_id": f"f#c{i}", **RESULT_A} for i in range(20)]

        result = validator.validate_file(
            file_id="f", chunk_texts=chunk_texts,
            memory_records=memories, max_chunks=5,
        )
        assert result["chunks_validated"] == 5

    def test_stats(self, tmp_path):
        llm_fn = self._mock_llm(RESULT_B_SIMILAR)
        validator = CrossValidator(
            llm_fn=llm_fn,
            dispute_log=DisputeLog(log_path=tmp_path / "d.jsonl"),
        )
        validator.validate_chunk(
            "c", "f", "text", RESULT_A,
        )
        stats = validator.get_stats()
        assert stats["total_validations"] == 1

    def test_set_llm_fn(self, tmp_path):
        validator = CrossValidator(
            dispute_log=DisputeLog(log_path=tmp_path / "d.jsonl"),
        )
        assert validator._llm_fn is None

        validator.set_llm_fn(self._mock_llm(RESULT_B_SIMILAR))
        result = validator.validate_chunk(
            "c", "f", "text", RESULT_A,
        )
        assert result["confidence"] > 0.0

    def test_disputes_logged(self, tmp_path):
        llm_fn = self._mock_llm(RESULT_B_DIFFERENT)
        dispute_log = DisputeLog(log_path=tmp_path / "d.jsonl")
        validator = CrossValidator(
            llm_fn=llm_fn,
            source_name="nim",
            dispute_log=dispute_log,
        )
        validator.validate_chunk(
            "file#chunk_0", "file.txt", "text", RESULT_A,
        )
        stats = dispute_log.get_stats()
        assert stats["total"] > 0
