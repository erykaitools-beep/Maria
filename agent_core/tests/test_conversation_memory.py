"""
Tests for ConversationMemory - persistent conversation history with condensation.

Covers: persistence, condensation, context retrieval, integration.
"""

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_core.consciousness.conversation_memory import ConversationMemory
from agent_core.llm.router import LLMRouter
from agent_core.tests.spec_helpers import specced


@pytest.fixture
def tmp_data_dir():
    """Create a temporary directory for test data."""
    d = tempfile.mkdtemp()
    yield d
    # Cleanup
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def memory(tmp_data_dir):
    """Create a ConversationMemory instance with temp paths."""
    return ConversationMemory(
        history_path=Path(tmp_data_dir) / "conversation_history.jsonl",
        summaries_path=Path(tmp_data_dir) / "conversation_summaries.jsonl",
        session_id=5,
        source="repl",
    )


@pytest.fixture
def mock_brain():
    """Mock brain with _ask_once method."""
    brain = specced(LLMRouter)
    brain._ask_once.return_value = json.dumps({
        "summary": "Rozmawialismy o testach",
        "facts": ["Testy przechodza", "Dodano nowy modul"],
        "user_facts": ["User lubi grafy"],
        "sentiment": "positive",
    })
    return brain


# ============================================================
# TestPersistence
# ============================================================

class TestPersistence:
    """Tests for save_turn and restore_history."""

    def test_save_turn_creates_file(self, memory):
        """save_turn should create the JSONL file."""
        assert not memory.history_path.exists()
        memory.save_turn("user", "Czesc!")
        assert memory.history_path.exists()

    def test_save_turn_appends(self, memory):
        """Multiple save_turn calls should produce multiple lines."""
        memory.save_turn("user", "Pytanie 1")
        memory.save_turn("assistant", "Odpowiedz 1")
        memory.save_turn("user", "Pytanie 2")

        lines = memory.history_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3

    def test_save_turn_entry_format(self, memory):
        """Saved entries should have correct fields."""
        memory.save_turn("user", "Test message")
        line = memory.history_path.read_text(encoding="utf-8").strip()
        entry = json.loads(line)

        assert entry["role"] == "user"
        assert entry["content"] == "Test message"
        assert entry["session"] == 5
        assert entry["source"] == "repl"
        assert "ts" in entry
        assert isinstance(entry["ts"], float)

    def test_save_turn_content_truncated(self, memory):
        """Long content should be truncated at MAX_CONTENT_LENGTH."""
        long_text = "x" * 3000
        memory.save_turn("user", long_text)

        line = memory.history_path.read_text(encoding="utf-8").strip()
        entry = json.loads(line)
        assert len(entry["content"]) <= memory.MAX_CONTENT_LENGTH + 3  # +3 for "..."
        assert entry["content"].endswith("...")

    def test_save_turn_ignores_invalid_role(self, memory):
        """save_turn should ignore non user/assistant roles."""
        memory.save_turn("system", "Prompt text")
        assert not memory.history_path.exists()

    def test_save_turn_thread_safe(self, memory):
        """Concurrent save_turn calls from multiple threads."""
        errors = []

        def save_many(role, start):
            try:
                for i in range(20):
                    memory.save_turn(role, f"Message {start + i}")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=save_many, args=("user", 0))
        t2 = threading.Thread(target=save_many, args=("assistant", 100))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors
        lines = memory.history_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 40

    def test_restore_empty_file(self, memory):
        """restore_history returns empty list when no file exists."""
        result = memory.restore_history()
        assert result == []

    def test_restore_returns_correct_format(self, tmp_data_dir):
        """Restored messages match OllamaBrain format."""
        path = Path(tmp_data_dir) / "history.jsonl"

        # Write messages for session 4 (previous session)
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"ts": 1.0, "session": 4, "role": "user", "content": "Hej"}) + "\n")
            f.write(json.dumps({"ts": 2.0, "session": 4, "role": "assistant", "content": "Czesc!"}) + "\n")

        mem = ConversationMemory(history_path=path, session_id=5)
        result = mem.restore_history()

        assert len(result) == 2
        assert result[0] == {"role": "user", "content": "Hej"}
        assert result[1] == {"role": "assistant", "content": "Czesc!"}

    def test_restore_limits_messages(self, tmp_data_dir):
        """Only last MAX_RESTORE_MESSAGES messages are restored."""
        path = Path(tmp_data_dir) / "history.jsonl"

        with open(path, "w", encoding="utf-8") as f:
            for i in range(50):
                entry = {"ts": float(i), "session": 4, "role": "user", "content": f"Msg {i}"}
                f.write(json.dumps(entry) + "\n")

        mem = ConversationMemory(history_path=path, session_id=5)
        result = mem.restore_history()

        assert len(result) == mem.MAX_RESTORE_MESSAGES
        # Should be the last 20
        assert result[0]["content"] == "Msg 30"
        assert result[-1]["content"] == "Msg 49"

    def test_restore_filters_by_session(self, tmp_data_dir):
        """Restore prioritizes previous session messages."""
        path = Path(tmp_data_dir) / "history.jsonl"

        with open(path, "w", encoding="utf-8") as f:
            # Session 3 messages
            f.write(json.dumps({"ts": 1.0, "session": 3, "role": "user", "content": "Old"}) + "\n")
            # Session 4 messages (previous session)
            f.write(json.dumps({"ts": 2.0, "session": 4, "role": "user", "content": "Recent"}) + "\n")
            f.write(json.dumps({"ts": 3.0, "session": 4, "role": "assistant", "content": "Reply"}) + "\n")

        mem = ConversationMemory(history_path=path, session_id=5)
        result = mem.restore_history()

        assert len(result) == 2
        assert result[0]["content"] == "Recent"
        assert result[1]["content"] == "Reply"

    def test_save_and_restore_roundtrip(self, memory):
        """Save messages, then restore them in a new session."""
        memory.save_turn("user", "Pytanie")
        memory.save_turn("assistant", "Odpowiedz")
        memory.save_turn("user", "Kolejne pytanie")

        # New session reads previous session's messages
        mem2 = ConversationMemory(
            history_path=memory.history_path,
            session_id=6,
        )
        result = mem2.restore_history()

        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Pytanie"
        assert result[1]["role"] == "assistant"
        assert result[2]["role"] == "user"

    def test_session_turn_count(self, memory):
        """Turn count should track messages saved in current session."""
        assert memory.get_session_turn_count() == 0
        memory.save_turn("user", "Msg 1")
        assert memory.get_session_turn_count() == 1
        memory.save_turn("assistant", "Reply 1")
        assert memory.get_session_turn_count() == 2


# ============================================================
# TestCondensation
# ============================================================

class TestCondensation:
    """Tests for condense_session and related methods."""

    def test_condense_returns_dict(self, memory, mock_brain):
        """condense_session should return a summary dict."""
        memory.save_turn("user", "Pytanie testowe")
        memory.save_turn("assistant", "Odpowiedz testowa")

        result = memory.condense_session(mock_brain)

        assert isinstance(result, dict)
        assert "summary" in result
        assert "facts" in result
        assert "session" in result

    def test_condense_includes_required_fields(self, memory, mock_brain):
        """Condensed summary should include all required fields."""
        memory.save_turn("user", "Test")
        memory.save_turn("assistant", "Ok")

        result = memory.condense_session(mock_brain)

        assert result["session"] == 5
        assert "date" in result
        assert result["turn_count"] == 2
        assert "summary" in result
        assert "facts" in result
        assert "user_facts" in result
        assert "sentiment" in result
        assert "condensed_by" in result

    def test_condense_uses_ask_once(self, memory, mock_brain):
        """Condensation should use _ask_once, not think()."""
        memory.save_turn("user", "Test")
        memory.save_turn("assistant", "Reply")

        memory.condense_session(mock_brain)

        mock_brain._ask_once.assert_called_once()
        mock_brain.think.assert_not_called()

    def test_condense_prompt_includes_conversation(self, memory, mock_brain):
        """Condensation prompt should contain conversation messages."""
        memory.save_turn("user", "Jak dziala homeostasis?")
        memory.save_turn("assistant", "Homeostasis reguluje tryby pracy")

        memory.condense_session(mock_brain)

        call_args = mock_brain._ask_once.call_args
        prompt = call_args[0][0]
        assert "homeostasis" in prompt.lower()

    def test_condense_handles_llm_failure(self, memory):
        """Should return rule-based fallback when LLM fails."""
        memory.save_turn("user", "Test")
        memory.save_turn("assistant", "Reply")

        brain = specced(LLMRouter)
        brain._ask_once.side_effect = Exception("LLM error")

        result = memory.condense_session(brain)

        assert result is not None
        assert result["condensed_by"] == "rule"
        assert result["turn_count"] == 2

    def test_condense_handles_bad_json(self, memory):
        """Should fallback when LLM returns non-JSON."""
        memory.save_turn("user", "Test")
        memory.save_turn("assistant", "Reply")

        brain = specced(LLMRouter)
        brain._ask_once.return_value = "To nie jest JSON, tylko tekst"

        result = memory.condense_session(brain)

        assert result is not None
        assert result["condensed_by"] == "rule"

    def test_condense_empty_session(self, memory, mock_brain):
        """Should return None for empty session (no messages)."""
        result = memory.condense_session(mock_brain)
        assert result is None

    def test_save_summary_creates_file(self, memory):
        """save_summary should create the summaries JSONL file."""
        summary = {"session": 5, "summary": "Test", "facts": [], "user_facts": [], "sentiment": "neutral"}
        memory.save_summary(summary)

        assert memory.summaries_path.exists()
        line = memory.summaries_path.read_text(encoding="utf-8").strip()
        loaded = json.loads(line)
        assert loaded["summary"] == "Test"

    def test_save_summary_appends(self, memory):
        """Multiple save_summary calls should append."""
        memory.save_summary({"session": 1, "summary": "First"})
        memory.save_summary({"session": 2, "summary": "Second"})

        lines = memory.summaries_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_condense_with_analyze_task_fallback(self, memory):
        """When brain has no _ask_once, should try analyze_task."""
        memory.save_turn("user", "Test")
        memory.save_turn("assistant", "Reply")

        brain = MagicMock(spec=[])  # No _ask_once
        brain.analyze_task = MagicMock(return_value=json.dumps({
            "summary": "Via analyze_task",
            "facts": [],
            "user_facts": [],
            "sentiment": "neutral",
        }))

        result = memory.condense_session(brain)

        assert result is not None
        assert result["summary"] == "Via analyze_task"


# ============================================================
# TestContextRetrieval
# ============================================================

class TestContextRetrieval:
    """Tests for get_conversation_context and related methods."""

    def test_get_recent_summaries_empty(self, memory):
        """No file returns empty list."""
        result = memory.get_recent_summaries()
        assert result == []

    def test_get_recent_summaries_limit(self, memory):
        """Should respect limit parameter."""
        for i in range(10):
            memory.save_summary({"session": i, "summary": f"Session {i}"})

        result = memory.get_recent_summaries(limit=3)
        assert len(result) == 3
        assert result[0]["session"] == 7
        assert result[2]["session"] == 9

    def test_get_recent_summaries_order(self, memory):
        """Summaries should be in chronological order (newest last)."""
        memory.save_summary({"session": 1, "summary": "First"})
        memory.save_summary({"session": 2, "summary": "Second"})
        memory.save_summary({"session": 3, "summary": "Third"})

        result = memory.get_recent_summaries(limit=10)
        assert result[0]["session"] == 1
        assert result[2]["session"] == 3

    def test_get_conversation_context_string(self, memory):
        """Should return formatted context string."""
        memory.save_summary({
            "session": 7, "date": "2026-02-25",
            "summary": "Pracowalismy nad NIM API",
            "facts": [], "user_facts": ["User lubi grafy"],
            "sentiment": "positive",
        })
        memory.save_summary({
            "session": 8, "date": "2026-02-26",
            "summary": "Testowalismy homeostasis",
            "facts": [], "user_facts": [],
            "sentiment": "positive",
        })

        ctx = memory.get_conversation_context(limit=3)

        assert "[Pamiec rozmow]" in ctx
        assert "Sesja 7" in ctx
        assert "NIM API" in ctx
        assert "Sesja 8" in ctx
        assert "homeostasis" in ctx
        assert "User lubi grafy" in ctx

    def test_get_conversation_context_empty(self, memory):
        """Should return empty string when no summaries."""
        ctx = memory.get_conversation_context()
        assert ctx == ""

    def test_get_all_user_facts_deduplicates(self, memory):
        """User facts across sessions should be deduplicated."""
        memory.save_summary({
            "session": 1, "summary": "S1",
            "user_facts": ["User lubi grafy", "User ma mini PC"],
        })
        memory.save_summary({
            "session": 2, "summary": "S2",
            "user_facts": ["User lubi grafy", "User planuje test 8h"],
        })

        facts = memory.get_all_user_facts()
        assert len(facts) == 3
        assert "User lubi grafy" in facts
        assert "User ma mini PC" in facts
        assert "User planuje test 8h" in facts

    def test_get_all_user_facts_empty(self, memory):
        """No summaries returns empty list."""
        facts = memory.get_all_user_facts()
        assert facts == []

    def test_get_all_user_facts_case_insensitive_dedup(self, memory):
        """Deduplication should be case-insensitive."""
        memory.save_summary({"session": 1, "summary": "S1", "user_facts": ["User lubi grafy"]})
        memory.save_summary({"session": 2, "summary": "S2", "user_facts": ["user lubi grafy"]})

        facts = memory.get_all_user_facts()
        assert len(facts) == 1


# ============================================================
# TestIntegration
# ============================================================

class TestIntegration:
    """Integration tests for full conversation memory lifecycle."""

    def test_full_lifecycle(self, memory, mock_brain):
        """Save turns, condense, save summary, read context."""
        # 1. Save conversation turns
        memory.save_turn("user", "Jak dodac nowy modul?")
        memory.save_turn("assistant", "Trzeba stworzyc klase dziedziczaca z MariaModule")
        memory.save_turn("user", "Dziekuje!")
        memory.save_turn("assistant", "Nie ma za co")

        # 2. Condense
        condensed = memory.condense_session(mock_brain)
        assert condensed is not None

        # 3. Save summary
        memory.save_summary(condensed)

        # 4. Read context
        ctx = memory.get_conversation_context()
        assert "[Pamiec rozmow]" in ctx
        assert "Sesja 5" in ctx

    def test_multiple_sessions_accumulation(self, tmp_data_dir):
        """Multiple sessions accumulate summaries correctly."""
        history_path = Path(tmp_data_dir) / "history.jsonl"
        summaries_path = Path(tmp_data_dir) / "summaries.jsonl"

        for session_id in [1, 2, 3]:
            mem = ConversationMemory(
                history_path=history_path,
                summaries_path=summaries_path,
                session_id=session_id,
            )
            mem.save_turn("user", f"Msg from session {session_id}")
            mem.save_turn("assistant", f"Reply in session {session_id}")
            mem.save_summary({
                "session": session_id,
                "date": f"2026-02-{24 + session_id}",
                "summary": f"Sesja {session_id} o testach",
                "facts": [],
                "user_facts": [],
                "sentiment": "positive",
            })

        # New session reads all summaries
        mem4 = ConversationMemory(
            history_path=history_path,
            summaries_path=summaries_path,
            session_id=4,
        )
        summaries = mem4.get_recent_summaries(limit=10)
        assert len(summaries) == 3

        ctx = mem4.get_conversation_context()
        assert "Sesja 1" in ctx
        assert "Sesja 2" in ctx
        assert "Sesja 3" in ctx

    def test_conversation_context_for_system_prompt(self, memory):
        """Context string should be suitable for system prompt injection."""
        memory.save_summary({
            "session": 4, "date": "2026-02-26",
            "summary": "Pracowalismy nad swiadomoscia",
            "facts": ["Dodano TraitEvolver"],
            "user_facts": ["User preferuje systematyczne podejscie"],
            "sentiment": "positive",
        })

        ctx = memory.get_conversation_context()

        # Should be reasonably short for system prompt
        assert len(ctx) < 500
        # Should start with section header
        assert ctx.startswith("[Pamiec rozmow]")

    def test_import_from_package(self):
        """ConversationMemory should be importable from consciousness package."""
        from agent_core.consciousness.conversation_memory import ConversationMemory as CM
        assert CM is not None

    def test_extract_json_various_formats(self, memory):
        """_extract_json should handle various LLM output formats."""
        # Plain JSON
        result = memory._extract_json('{"summary": "test", "facts": []}')
        assert result["summary"] == "test"

        # JSON in markdown code block
        result = memory._extract_json('```json\n{"summary": "test2"}\n```')
        assert result["summary"] == "test2"

        # JSON with surrounding text
        result = memory._extract_json('Here is the result: {"summary": "test3"} done.')
        assert result["summary"] == "test3"

        # Completely invalid
        result = memory._extract_json("no json here at all")
        assert result is None


# ============================================================
# TestPendingCondensation -- the daemon-safe backlog drain
# ============================================================

def _seed_session(memory, session, n_turns, last_ts):
    """Append n_turns user/assistant turns for `session`, newest at last_ts."""
    path = memory.history_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for i in range(n_turns):
            role = "user" if i % 2 == 0 else "assistant"
            ts = last_ts - (n_turns - 1 - i)  # ascending, ending at last_ts
            f.write(json.dumps({
                "ts": ts, "session": session, "role": role,
                "content": f"wiadomosc {i} sesji {session}",
            }, ensure_ascii=False) + "\n")


class TestPendingCondensation:
    """condense_pending_sessions: drain CLOSED sessions from durable history."""

    NOW = 1_000_000.0
    IDLE = 1800.0

    def test_condenses_idle_unsummarized_session(self, memory, mock_brain):
        _seed_session(memory, session=101, n_turns=4, last_ts=self.NOW - 5000)
        n = memory.condense_pending_sessions(
            mock_brain, now=self.NOW, idle_secs=self.IDLE
        )
        assert n == 1
        summaries = memory.get_recent_summaries(limit=10)
        assert len(summaries) == 1
        assert summaries[0]["session"] == 101
        assert summaries[0]["turn_count"] == 4

    def test_skips_live_session(self, memory, mock_brain):
        """A session whose newest turn is within idle_secs is the live
        conversation -> must NOT be condensed mid-flight."""
        _seed_session(memory, session=202, n_turns=4, last_ts=self.NOW - 60)
        n = memory.condense_pending_sessions(
            mock_brain, now=self.NOW, idle_secs=self.IDLE
        )
        assert n == 0
        assert memory.get_recent_summaries(limit=10) == []

    def test_skips_already_summarized(self, memory, mock_brain):
        _seed_session(memory, session=303, n_turns=4, last_ts=self.NOW - 5000)
        memory.save_summary({"session": 303, "summary": "stare", "date": "x"})
        n = memory.condense_pending_sessions(
            mock_brain, now=self.NOW, idle_secs=self.IDLE
        )
        assert n == 0  # already done -> skipped
        mock_brain._ask_once.assert_not_called()

    def test_skips_single_turn_session(self, memory, mock_brain):
        _seed_session(memory, session=404, n_turns=1, last_ts=self.NOW - 5000)
        n = memory.condense_pending_sessions(
            mock_brain, now=self.NOW, idle_secs=self.IDLE
        )
        assert n == 0  # turns < 2 -> not worth a summary

    def test_max_per_run_cap_and_resume(self, memory, mock_brain):
        for s in (501, 502, 503):
            _seed_session(memory, session=s, n_turns=2, last_ts=self.NOW - 5000)
        first = memory.condense_pending_sessions(
            mock_brain, now=self.NOW, idle_secs=self.IDLE, max_per_run=2
        )
        assert first == 2
        # The remaining one is drained on the next call (idempotent backlog).
        second = memory.condense_pending_sessions(
            mock_brain, now=self.NOW, idle_secs=self.IDLE, max_per_run=2
        )
        assert second == 1
        third = memory.condense_pending_sessions(
            mock_brain, now=self.NOW, idle_secs=self.IDLE, max_per_run=2
        )
        assert third == 0  # nothing left

    def test_oldest_first(self, memory, mock_brain):
        _seed_session(memory, session=601, n_turns=2, last_ts=self.NOW - 9000)  # oldest
        _seed_session(memory, session=602, n_turns=2, last_ts=self.NOW - 3000)
        memory.condense_pending_sessions(
            mock_brain, now=self.NOW, idle_secs=self.IDLE, max_per_run=1
        )
        summaries = memory.get_recent_summaries(limit=10)
        assert len(summaries) == 1
        assert summaries[0]["session"] == 601  # oldest condensed first

    def test_rule_fallback_on_llm_failure(self, memory):
        brain = specced(LLMRouter)
        brain._ask_once.side_effect = Exception("LLM down")
        _seed_session(memory, session=701, n_turns=3, last_ts=self.NOW - 5000)
        n = memory.condense_pending_sessions(
            brain, now=self.NOW, idle_secs=self.IDLE
        )
        assert n == 1
        summaries = memory.get_recent_summaries(limit=10)
        assert summaries[0]["condensed_by"] == "rule"
        assert summaries[0]["session"] == 701

    def test_backlog_date_from_last_turn(self, memory, mock_brain):
        """Backlog summaries carry the session's real date, not 'today'."""
        last_ts = self.NOW - 5000
        _seed_session(memory, session=801, n_turns=2, last_ts=last_ts)
        memory.condense_pending_sessions(
            mock_brain, now=self.NOW, idle_secs=self.IDLE
        )
        expected = time.strftime("%Y-%m-%d", time.localtime(last_ts))
        assert memory.get_recent_summaries(limit=10)[0]["date"] == expected

    def test_no_history_file_is_safe(self, memory, mock_brain):
        # history_path does not exist yet
        assert memory.condense_pending_sessions(mock_brain, now=self.NOW) == 0
