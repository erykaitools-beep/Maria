"""Tests for LLM Tape - raw LLM interaction recording."""

import json
import os
import threading
import time
from pathlib import Path

import pytest

from agent_core.llm.llm_tape import (
    LLMTape,
    TapeEntry,
    make_tape_entry,
    MAX_PROMPT_SUMMARY,
    MAX_RAW_RESPONSE,
)


@pytest.fixture
def tape(tmp_path):
    return LLMTape(path=tmp_path / "llm_tape.jsonl")


@pytest.fixture
def sample_entry():
    return make_tape_entry(
        model="llama3.1:8b",
        role="chat",
        prompt="Czesc, jak sie masz?",
        response="Czesc! Dobrze, dziekuje.",
        latency_ms=1234.5,
        success=True,
    )


# -- TapeEntry --

class TestTapeEntry:
    def test_make_tape_entry_basic(self):
        entry = make_tape_entry(
            model="qwen3:8b", role="planner",
            prompt="Analyze this", response="OK done",
            latency_ms=500.0,
        )
        assert entry.model == "qwen3:8b"
        assert entry.role == "planner"
        assert entry.success is True
        assert entry.latency_ms == 500.0
        assert entry.tokens_est == len("OK done") // 4

    def test_make_tape_entry_truncates_prompt(self):
        long_prompt = "x" * 1000
        entry = make_tape_entry(
            model="m", role="r", prompt=long_prompt,
            response="ok", latency_ms=0,
        )
        assert len(entry.prompt_summary) == MAX_PROMPT_SUMMARY

    def test_make_tape_entry_truncates_response(self):
        long_response = "y" * 5000
        entry = make_tape_entry(
            model="m", role="r", prompt="p",
            response=long_response, latency_ms=0,
        )
        assert len(entry.raw_response) == MAX_RAW_RESPONSE

    def test_make_tape_entry_handles_none(self):
        entry = make_tape_entry(
            model="m", role="r", prompt=None,
            response=None, latency_ms=0, success=False,
        )
        assert entry.prompt_summary == ""
        assert entry.raw_response == ""
        assert entry.tokens_est == 0
        assert entry.success is False

    def test_to_dict(self, sample_entry):
        d = sample_entry.to_dict()
        assert d["model"] == "llama3.1:8b"
        assert d["role"] == "chat"
        assert isinstance(d["ts"], float)

    def test_from_dict_roundtrip(self, sample_entry):
        d = sample_entry.to_dict()
        restored = TapeEntry.from_dict(d)
        assert restored.model == sample_entry.model
        assert restored.role == sample_entry.role
        assert restored.raw_response == sample_entry.raw_response

    def test_from_dict_defaults(self):
        entry = TapeEntry.from_dict({})
        assert entry.model == "unknown"
        assert entry.role == "unknown"
        assert entry.success is True


# -- LLMTape.record --

class TestLLMTapeRecord:
    def test_record_creates_file(self, tape, sample_entry):
        tape.record(sample_entry)
        assert tape.path.exists()

    def test_record_appends_jsonl(self, tape, sample_entry):
        tape.record(sample_entry)
        tape.record(sample_entry)
        lines = tape.path.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_record_valid_json(self, tape, sample_entry):
        tape.record(sample_entry)
        line = tape.path.read_text().strip()
        d = json.loads(line)
        assert d["model"] == "llama3.1:8b"

    def test_record_handles_missing_dir(self, tmp_path):
        tape = LLMTape(path=tmp_path / "subdir" / "tape.jsonl")
        entry = make_tape_entry("m", "r", "p", "resp", 0)
        # Should not crash even if parent dir missing
        # (will fail silently via logger.debug)
        tape.record(entry)


# -- LLMTape.get_recent --

class TestLLMTapeGetRecent:
    def test_empty_file(self, tape):
        assert tape.get_recent() == []

    def test_nonexistent_file(self, tmp_path):
        tape = LLMTape(path=tmp_path / "nonexistent.jsonl")
        assert tape.get_recent() == []

    def test_returns_last_n(self, tape):
        for i in range(20):
            entry = make_tape_entry("m", "r", f"prompt {i}", f"resp {i}", float(i))
            tape.record(entry)
        recent = tape.get_recent(limit=5)
        assert len(recent) == 5
        assert "prompt 19" in recent[-1]["prompt_summary"]

    def test_returns_all_if_fewer_than_limit(self, tape):
        entry = make_tape_entry("m", "r", "p", "resp", 0)
        tape.record(entry)
        recent = tape.get_recent(limit=10)
        assert len(recent) == 1


# -- LLMTape.get_stats --

class TestLLMTapeGetStats:
    def test_empty_stats(self, tape):
        stats = tape.get_stats()
        assert stats["total_calls"] == 0
        assert stats["error_rate"] == 0.0

    def test_stats_count(self, tape):
        for i in range(5):
            entry = make_tape_entry("llama3.1:8b", "chat", "p", "r", 100.0)
            tape.record(entry)
        entry_fail = make_tape_entry("llama3.1:8b", "chat", "p", "", 50.0, success=False)
        tape.record(entry_fail)

        stats = tape.get_stats(period_hours=1)
        assert stats["total_calls"] == 6
        assert stats["error_count"] == 1
        assert stats["error_rate"] == round(1 / 6, 3)
        assert "llama3.1:8b" in stats["models_used"]

    def test_stats_multiple_models(self, tape):
        tape.record(make_tape_entry("llama3.1:8b", "chat", "p", "r", 0))
        tape.record(make_tape_entry("qwen3:8b", "planner", "p", "r", 0))
        stats = tape.get_stats()
        assert sorted(stats["models_used"]) == ["llama3.1:8b", "qwen3:8b"]
        assert sorted(stats["roles_used"]) == ["chat", "planner"]


# -- LLMTape.get_recent_errors --

class TestLLMTapeGetRecentErrors:
    def test_no_errors(self, tape):
        tape.record(make_tape_entry("m", "r", "p", "ok", 0, success=True))
        assert tape.get_recent_errors() == []

    def test_returns_errors_only(self, tape):
        tape.record(make_tape_entry("m", "r", "p", "ok", 0, success=True))
        tape.record(make_tape_entry("m", "r", "p", "", 0, success=False))
        tape.record(make_tape_entry("m", "r", "p", "ok", 0, success=True))
        errors = tape.get_recent_errors(limit=5)
        assert len(errors) == 1
        assert errors[0]["success"] is False


# -- LLMTape rotation --

class TestLLMTapeRotation:
    def test_rotation_at_size_limit(self, tmp_path):
        tape = LLMTape(path=tmp_path / "tape.jsonl", max_size_bytes=500)
        # Write enough to exceed 500 bytes
        for i in range(20):
            entry = make_tape_entry("m", "r", f"prompt {i}", "x" * 50, 0)
            tape.record(entry)

        backup = tmp_path / "tape.jsonl.bak"
        assert backup.exists()
        # Current file should be smaller than max
        assert tape.path.stat().st_size < 500

    def test_no_rotation_under_limit(self, tape, sample_entry):
        tape.record(sample_entry)
        backup = tape.path.with_suffix(".jsonl.bak")
        assert not backup.exists()


# -- Thread safety --

class TestLLMTapeThreadSafety:
    def test_concurrent_writes(self, tape):
        """Multiple threads writing simultaneously should not corrupt file."""
        errors = []

        def writer(thread_id):
            try:
                for i in range(10):
                    entry = make_tape_entry(
                        "m", "r", f"t{thread_id}-{i}", "resp", 0
                    )
                    tape.record(entry)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # All 50 entries should be valid JSON
        lines = tape.path.read_text().strip().split("\n")
        assert len(lines) == 50
        for line in lines:
            json.loads(line)  # should not raise
