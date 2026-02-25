"""
Tests for agent_core/awareness/context_builder.py
"""

import json
import time
import tempfile
import pytest
from pathlib import Path

from agent_core.awareness.context_builder import ContextBuilder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_knowledge_index(tmp_path: Path, records: list) -> Path:
    """Write knowledge_index.jsonl to tmp_path."""
    p = tmp_path / "knowledge_index.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


def _make_longterm_memory(tmp_path: Path, records: list) -> Path:
    """Write longterm_memory.jsonl to tmp_path."""
    p = tmp_path / "longterm_memory.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


def _make_code_self_model(tmp_path: Path, stats: dict) -> Path:
    """Write code_self_model.json to tmp_path."""
    p = tmp_path / "code_self_model.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"statistics": stats}, f)
    return p


def _make_input_dir(tmp_path: Path, filenames: list) -> Path:
    """Create input/ directory with dummy .txt files."""
    d = tmp_path / "input"
    d.mkdir()
    for name in filenames:
        (d / name).write_text("dummy")
    return d


# ---------------------------------------------------------------------------
# Tests: learning_status
# ---------------------------------------------------------------------------

class TestLearningStatus:

    def test_empty_index(self, tmp_path):
        ki = _make_knowledge_index(tmp_path, [])
        cb = ContextBuilder(knowledge_index_path=ki)
        assert cb._learning_status() == ""

    def test_missing_file(self, tmp_path):
        cb = ContextBuilder(knowledge_index_path=tmp_path / "nonexistent.jsonl")
        assert cb._learning_status() == ""

    def test_counts_statuses(self, tmp_path):
        records = [
            {"file": "a.txt", "status": "completed"},
            {"file": "b.txt", "status": "new"},
            {"file": "c.txt", "status": "new"},
            {"file": "d.txt", "status": "learning"},
        ]
        ki = _make_knowledge_index(tmp_path, records)
        cb = ContextBuilder(knowledge_index_path=ki)
        result = cb._learning_status()

        assert "4" in result
        assert "ukonczone" in result
        assert "nowe" in result
        assert "trakcie" in result

    def test_hard_topic_counted(self, tmp_path):
        records = [
            {"file": "a.txt", "status": "hard_topic"},
            {"file": "b.txt", "status": "completed"},
        ]
        ki = _make_knowledge_index(tmp_path, records)
        cb = ContextBuilder(knowledge_index_path=ki)
        result = cb._learning_status()

        assert "trudne" in result

    def test_skips_invalid_lines(self, tmp_path):
        p = tmp_path / "knowledge_index.jsonl"
        p.write_text('{"file": "a.txt", "status": "new"}\nNOT JSON\n{"file": "b.txt", "status": "completed"}\n')
        cb = ContextBuilder(knowledge_index_path=p)
        result = cb._learning_status()
        assert "2" in result

    def test_result_starts_with_mam(self, tmp_path):
        records = [{"file": "a.txt", "status": "new"}]
        ki = _make_knowledge_index(tmp_path, records)
        cb = ContextBuilder(knowledge_index_path=ki)
        result = cb._learning_status()
        assert result.startswith("Mam ")


# ---------------------------------------------------------------------------
# Tests: knowledge_summary
# ---------------------------------------------------------------------------

class TestKnowledgeSummary:

    def test_missing_file(self, tmp_path):
        cb = ContextBuilder(longterm_memory_path=tmp_path / "nope.jsonl")
        assert cb._knowledge_summary() == ""

    def test_no_tags(self, tmp_path):
        records = [{"source_file": "a.txt", "summary": "something"}]
        lm = _make_longterm_memory(tmp_path, records)
        cb = ContextBuilder(longterm_memory_path=lm)
        assert cb._knowledge_summary() == ""

    def test_extracts_tags(self, tmp_path):
        records = [
            {"source_file": "a.txt", "tags": ["decyzje", "ekspert"]},
            {"source_file": "b.txt", "tags": ["pytania", "decyzje"]},
        ]
        lm = _make_longterm_memory(tmp_path, records)
        cb = ContextBuilder(longterm_memory_path=lm)
        result = cb._knowledge_summary()

        assert result.startswith("Tagi nauki:")
        assert "decyzje" in result

    def test_deduplicates_tags(self, tmp_path):
        records = [
            {"tags": ["abc", "abc", "abc"]},
            {"tags": ["abc"]},
        ]
        lm = _make_longterm_memory(tmp_path, records)
        cb = ContextBuilder(longterm_memory_path=lm)
        result = cb._knowledge_summary()
        # "abc" should appear only once
        assert result.count("abc") == 1

    def test_limits_to_8_tags(self, tmp_path):
        tags_per_record = [f"tag{i}" for i in range(20)]
        records = [{"tags": tags_per_record}]
        lm = _make_longterm_memory(tmp_path, records)
        cb = ContextBuilder(longterm_memory_path=lm)
        result = cb._knowledge_summary()
        # Max 8 tags in output
        tags_in_result = result.replace("Tagi nauki: ", "").split(", ")
        assert len(tags_in_result) <= 8


# ---------------------------------------------------------------------------
# Tests: code_summary
# ---------------------------------------------------------------------------

class TestCodeSummary:

    def test_missing_file(self, tmp_path):
        cb = ContextBuilder(code_self_model_path=tmp_path / "nope.json")
        assert cb._code_summary() == ""

    def test_reads_statistics(self, tmp_path):
        csm = _make_code_self_model(tmp_path, {
            "files": 92, "lines": 16942, "functions": 133, "classes": 89
        })
        cb = ContextBuilder(code_self_model_path=csm)
        result = cb._code_summary()

        assert result.startswith("Moj kod:")
        assert "92" in result
        assert "16942" in result
        assert "133" in result

    def test_handles_empty_stats(self, tmp_path):
        p = tmp_path / "model.json"
        p.write_text(json.dumps({"statistics": {}}))
        cb = ContextBuilder(code_self_model_path=p)
        assert cb._code_summary() == ""

    def test_handles_invalid_json(self, tmp_path):
        p = tmp_path / "model.json"
        p.write_text("NOT JSON")
        cb = ContextBuilder(code_self_model_path=p)
        assert cb._code_summary() == ""

    def test_partial_stats(self, tmp_path):
        csm = _make_code_self_model(tmp_path, {"files": 10})
        cb = ContextBuilder(code_self_model_path=csm)
        result = cb._code_summary()
        assert "10" in result
        assert "linii" not in result


# ---------------------------------------------------------------------------
# Tests: system_status
# ---------------------------------------------------------------------------

class TestSystemStatus:

    def test_returns_string_or_empty(self, tmp_path):
        cb = ContextBuilder()
        result = cb._system_status()
        # Either has RAM/CPU info or is empty (if psutil fails)
        assert isinstance(result, str)

    def test_format_when_available(self, tmp_path):
        cb = ContextBuilder()
        result = cb._system_status()
        if result:
            assert "RAM" in result
            assert "CPU" in result
            assert "%" in result


# ---------------------------------------------------------------------------
# Tests: build() - main method
# ---------------------------------------------------------------------------

class TestBuild:

    def _full_cb(self, tmp_path) -> ContextBuilder:
        """Builder with all sources populated."""
        ki = _make_knowledge_index(tmp_path, [
            {"file": "a.txt", "status": "completed"},
            {"file": "b.txt", "status": "new"},
            {"file": "c.txt", "status": "learning"},
        ])
        lm = _make_longterm_memory(tmp_path, [
            {"tags": ["decyzje", "pytania", "ekspert"]},
        ])
        csm = _make_code_self_model(tmp_path, {
            "files": 92, "lines": 16942, "functions": 133
        })
        return ContextBuilder(
            knowledge_index_path=ki,
            longterm_memory_path=lm,
            code_self_model_path=csm,
        )

    def test_build_returns_string(self, tmp_path):
        cb = self._full_cb(tmp_path)
        result = cb.build()
        assert isinstance(result, str)

    def test_build_starts_with_swiadomosc(self, tmp_path):
        cb = self._full_cb(tmp_path)
        result = cb.build()
        assert result.startswith("[Swiadomosc:")

    def test_build_ends_with_bracket(self, tmp_path):
        cb = self._full_cb(tmp_path)
        result = cb.build()
        assert result.endswith(".]")

    def test_build_contains_file_info(self, tmp_path):
        cb = self._full_cb(tmp_path)
        result = cb.build()
        assert "plikow" in result

    def test_build_contains_tags(self, tmp_path):
        cb = self._full_cb(tmp_path)
        result = cb.build()
        assert "decyzje" in result or "pytania" in result

    def test_build_contains_code_info(self, tmp_path):
        cb = self._full_cb(tmp_path)
        result = cb.build()
        assert "92" in result

    def test_cache_is_used(self, tmp_path):
        cb = self._full_cb(tmp_path)
        result1 = cb.build()
        result2 = cb.build()
        assert result1 == result2

    def test_cache_expires(self, tmp_path):
        cb = self._full_cb(tmp_path)
        cb.CACHE_TTL = 0  # Immediate expiry
        cb.build()
        first_cache_time = cb._cache_time
        time.sleep(0.02)
        cb.build()
        # Cache should have been rebuilt (new timestamp)
        assert cb._cache_time > first_cache_time

    def test_invalidate_cache(self, tmp_path):
        cb = self._full_cb(tmp_path)
        cb.build()
        original_time = cb._cache_time
        time.sleep(0.01)
        cb.invalidate_cache()
        assert cb._cache_time == 0.0
        cb.build()
        assert cb._cache_time > original_time

    def test_empty_result_when_no_sources(self, tmp_path):
        # All paths point to nonexistent files
        cb = ContextBuilder(
            knowledge_index_path=tmp_path / "nope1.jsonl",
            longterm_memory_path=tmp_path / "nope2.jsonl",
            code_self_model_path=tmp_path / "nope3.json",
        )
        # With no psutil or empty result, cache is ""
        # With psutil available, system_status will still provide data
        result = cb.build()
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Tests: get_input_files and get_detailed_file_list
# ---------------------------------------------------------------------------

class TestFileListing:

    def test_get_input_files_empty_dir(self, tmp_path):
        d = tmp_path / "input"
        d.mkdir()
        cb = ContextBuilder(input_dir=d)
        assert cb.get_input_files() == []

    def test_get_input_files_lists_txt(self, tmp_path):
        d = _make_input_dir(tmp_path, ["a.txt", "b.txt", "readme.md"])
        cb = ContextBuilder(input_dir=d)
        files = cb.get_input_files()
        assert "a.txt" in files
        assert "b.txt" in files
        assert "readme.md" not in files  # only .txt

    def test_get_input_files_missing_dir(self, tmp_path):
        cb = ContextBuilder(input_dir=tmp_path / "nonexistent")
        assert cb.get_input_files() == []

    def test_get_detailed_file_list(self, tmp_path):
        records = [
            {"file": "a.txt", "status": "completed", "priority": 80.0, "last_scores": [0.83]},
            {"file": "b.txt", "status": "new", "priority": 50.0, "last_scores": []},
        ]
        ki = _make_knowledge_index(tmp_path, records)
        cb = ContextBuilder(knowledge_index_path=ki)
        result = cb.get_detailed_file_list()

        assert len(result) == 2
        completed = next(r for r in result if r["file"] == "a.txt")
        assert completed["status"] == "completed"
        assert completed["exam_score"] == 0.83

    def test_get_detailed_file_list_missing(self, tmp_path):
        cb = ContextBuilder(knowledge_index_path=tmp_path / "nope.jsonl")
        assert cb.get_detailed_file_list() == []


# ---------------------------------------------------------------------------
# Tests: import
# ---------------------------------------------------------------------------

def test_import_from_package():
    from agent_core.awareness import ContextBuilder as CB
    assert CB is not None


def test_instantiate_default():
    """ContextBuilder should not raise on default construction."""
    cb = ContextBuilder()
    assert cb is not None
    assert cb.CACHE_TTL == 60
