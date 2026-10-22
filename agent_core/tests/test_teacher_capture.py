"""Tests for full-fidelity teacher call capture (training corpus feed)."""

import json
import os
from pathlib import Path

import pytest

from agent_core.llm import teacher_capture
from agent_core.llm.teacher_capture import capture, is_enabled


LONG_PROMPT = "P" * 5000
LONG_RESPONSE = "R" * 9000


def _rows(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class TestCaptureScope:
    def test_learning_role_is_captured(self, tmp_path):
        target = tmp_path / "capture.jsonl"
        assert capture("nim/big", "learning", "prompt", "answer", True, path=target) is True
        rows = _rows(target)
        assert len(rows) == 1
        assert rows[0]["model"] == "nim/big"
        assert rows[0]["role"] == "learning"

    @pytest.mark.parametrize("role", ["chat", "planner", "vision_translate", "encyclopedia"])
    def test_other_roles_are_ignored(self, tmp_path, role):
        target = tmp_path / "capture.jsonl"
        assert capture("m", role, "prompt", "answer", True, path=target) is False
        assert not target.exists()

    def test_failed_call_is_not_a_training_pair(self, tmp_path):
        target = tmp_path / "capture.jsonl"
        assert capture("m", "learning", "prompt", "answer", False, path=target) is False
        assert not target.exists()

    @pytest.mark.parametrize("response", ["", "   ", "\n"])
    def test_empty_response_is_not_a_training_pair(self, tmp_path, response):
        target = tmp_path / "capture.jsonl"
        assert capture("m", "learning", "prompt", response, True, path=target) is False
        assert not target.exists()

    def test_empty_prompt_is_rejected(self, tmp_path):
        target = tmp_path / "capture.jsonl"
        assert capture("m", "learning", "", "answer", True, path=target) is False
        assert not target.exists()


class TestNoTruncation:
    def test_prompt_and_response_survive_whole(self, tmp_path):
        """The point of this module: the tape's 200/2000 caps must not apply."""
        target = tmp_path / "capture.jsonl"
        capture("m", "learning", LONG_PROMPT, LONG_RESPONSE, True, path=target)
        row = _rows(target)[0]
        assert row["prompt"] == LONG_PROMPT
        assert row["response"] == LONG_RESPONSE

    def test_tape_truncates_where_capture_does_not(self, tmp_path):
        """Guards the reason this module exists, not just its behaviour."""
        from agent_core.llm.llm_tape import make_tape_entry

        entry = make_tape_entry("m", "learning", LONG_PROMPT, LONG_RESPONSE, 1.0)
        assert len(entry.prompt_summary) == 200
        assert len(entry.raw_response) == 2000

        target = tmp_path / "capture.jsonl"
        capture("m", "learning", LONG_PROMPT, LONG_RESPONSE, True, path=target)
        row = _rows(target)[0]
        assert len(row["prompt"]) == len(LONG_PROMPT)
        assert len(row["response"]) == len(LONG_RESPONSE)


class TestOffSwitch:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("TEACHER_CAPTURE_ENABLED", raising=False)
        assert is_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", " no "])
    def test_disabled_values(self, monkeypatch, tmp_path, value):
        monkeypatch.setenv("TEACHER_CAPTURE_ENABLED", value)
        assert is_enabled() is False
        target = tmp_path / "capture.jsonl"
        assert capture("m", "learning", "p", "a", True, path=target) is False
        assert not target.exists()


class TestSafety:
    def test_ceiling_stops_writing(self, tmp_path, monkeypatch):
        target = tmp_path / "capture.jsonl"
        capture("m", "learning", "p", "a", True, path=target)
        monkeypatch.setattr(teacher_capture, "MAX_FILE_BYTES", 1)
        monkeypatch.setattr(teacher_capture, "_ceiling_warned", False)
        assert capture("m", "learning", "p", "a", True, path=target) is False
        assert len(_rows(target)) == 1

    def test_unwritable_path_does_not_raise(self, tmp_path):
        """This sits on the hot path of every LLM call."""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        assert capture("m", "learning", "p", "a", True, path=blocker / "x.jsonl") is False

    def test_appends_rather_than_overwrites(self, tmp_path):
        target = tmp_path / "capture.jsonl"
        for i in range(3):
            capture("m", "learning", f"p{i}", f"a{i}", True, path=target)
        rows = _rows(target)
        assert [r["prompt"] for r in rows] == ["p0", "p1", "p2"]


class TestRouterWiring:
    def test_record_tape_feeds_capture(self, tmp_path, monkeypatch):
        """The hook must actually fire from the router, not just exist."""
        import agent_core.llm.router as router_mod

        seen = {}

        def fake_capture(**kwargs):
            seen.update(kwargs)
            return True

        monkeypatch.setattr(
            "agent_core.llm.teacher_capture.capture", fake_capture, raising=True
        )

        router = router_mod.LLMRouter.__new__(router_mod.LLMRouter)
        router._llm_tape = None
        router._record_tape(
            role="learning",
            model="nim/big",
            prompt=LONG_PROMPT,
            response=LONG_RESPONSE,
            start_time=__import__("time").time(),
            success=True,
        )

        assert seen.get("role") == "learning"
        assert seen.get("prompt") == LONG_PROMPT
        assert seen.get("response") == LONG_RESPONSE
        assert seen.get("success") is True
