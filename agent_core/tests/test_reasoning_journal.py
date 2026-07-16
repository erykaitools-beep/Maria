"""ReasoningJournal - Maria "thinks out loud" into an append-only notebook.

Direction 2026-07-05: capture the LLM's PROSE (not just the parsed decision),
keyed by episode_id, as raw material for future cross-model synthesis.
Capture-only hooks in creative (safe_llm_call), K12 (ExternalAnalyzer.analyze)
and teacher NIM gap analysis; /myslenie shows the notebook in Telegram.
"""

import json

import pytest

from agent_core.tracing.episode import set_episode_id, clear_episode_id
from agent_core.tracing.reasoning_journal import (
    ReasoningJournal,
    get_reasoning_journal,
    set_reasoning_journal,
    MAX_REASONING_CHARS,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # .env leaks via load_dotenv() at import -- pin the default (enabled).
    monkeypatch.delenv("REASONING_JOURNAL_ENABLED", raising=False)
    clear_episode_id()
    yield
    clear_episode_id()
    set_reasoning_journal(None)


def _journal(tmp_path):
    return ReasoningJournal(tmp_path / "reasoning_journal.jsonl")


class TestJournalCore:
    def test_record_and_recent_roundtrip(self, tmp_path):
        j = _journal(tmp_path)
        eid = j.record(
            source="creative.meta_goal_engine",
            reasoning="Napiecie miedzy nauka a brakiem materialu...",
            conclusion="meta-cel: poszerz zrodla",
            model="dracarys-70b",
            prompt_hint="Jestes agentem...",
        )
        assert eid and eid.startswith("rj-")
        entries = j.recent(5)
        assert len(entries) == 1
        e = entries[0]
        assert e["source"] == "creative.meta_goal_engine"
        assert "Napiecie" in e["reasoning"]
        assert e["conclusion"] == "meta-cel: poszerz zrodla"
        assert e["model"] == "dracarys-70b"

    def test_newest_first_and_limit(self, tmp_path):
        j = _journal(tmp_path)
        for i in range(5):
            j.record(source="s", reasoning=f"mysl {i}")
        entries = j.recent(2)
        assert len(entries) == 2
        assert entries[0]["reasoning"] == "mysl 4"
        assert entries[1]["reasoning"] == "mysl 3"

    def test_source_filter(self, tmp_path):
        j = _journal(tmp_path)
        j.record(source="creative.reframe", reasoning="a")
        j.record(source="k12.nim_api", reasoning="b")
        assert [e["source"] for e in j.recent(5, source="k12")] == ["k12.nim_api"]

    def test_episode_correlation(self, tmp_path):
        j = _journal(tmp_path)
        set_episode_id("ep-test-123")
        j.record(source="s", reasoning="w epizodzie")
        clear_episode_id()
        j.record(source="s", reasoning="poza epizodem")
        eps = j.for_episode("ep-test-123")
        assert len(eps) == 1
        assert eps[0]["reasoning"] == "w epizodzie"
        assert j.recent(1)[0]["episode_id"] is None

    def test_truncation(self, tmp_path):
        j = _journal(tmp_path)
        j.record(source="s", reasoning="x" * (MAX_REASONING_CHARS + 500))
        assert len(j.recent(1)[0]["reasoning"]) == MAX_REASONING_CHARS

    def test_empty_reasoning_skipped(self, tmp_path):
        j = _journal(tmp_path)
        assert j.record(source="s", reasoning="   ") is None
        assert j.recent(5) == []

    def test_kill_switch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REASONING_JOURNAL_ENABLED", "false")
        j = _journal(tmp_path)
        assert j.record(source="s", reasoning="mysl") is None
        assert not j.path.exists()

    def test_recent_on_missing_file(self, tmp_path):
        assert _journal(tmp_path).recent(5) == []

    def test_corrupt_line_skipped(self, tmp_path):
        j = _journal(tmp_path)
        j.record(source="s", reasoning="dobra")
        with open(j.path, "a", encoding="utf-8") as f:
            f.write("NIE-JSON\n")
        j.record(source="s", reasoning="tez dobra")
        assert len(j.recent(10)) == 2


class TestCreativeHook:
    def test_safe_llm_call_records(self, tmp_path):
        from agent_core.creative.llm_utils import safe_llm_call
        j = _journal(tmp_path)
        set_reasoning_journal(j)

        out = safe_llm_call(
            lambda p: "Rozwazam napiecie X vs Y -> wniosek Z",
            "prompt tresc", "meta_goal_engine",
        )
        assert out == "Rozwazam napiecie X vs Y -> wniosek Z"
        entries = j.recent(5)
        assert len(entries) == 1
        assert entries[0]["source"] == "creative.meta_goal_engine"
        assert entries[0]["prompt_hint"].startswith("prompt tresc")

    def test_failed_call_records_nothing(self, tmp_path):
        from agent_core.creative.llm_utils import safe_llm_call
        j = _journal(tmp_path)
        set_reasoning_journal(j)

        def boom(p):
            raise RuntimeError("llm down")

        assert safe_llm_call(boom, "prompt", "reframe") is None
        assert j.recent(5) == []


class TestK12Hook:
    def test_analyze_records_reasoning(self, tmp_path):
        from agent_core.self_analysis.external_analyzer import ExternalAnalyzer
        j = _journal(tmp_path)
        set_reasoning_journal(j)

        response = json.dumps({
            "recommendations": [{
                "topic": "funding rate",
                "description": "ucz sie funding rate",
                "suggested_action": "create_goal",
                "priority": 0.7,
            }],
        })
        analyzer = ExternalAnalyzer(llm_fn=lambda p: response)
        report = analyzer.analyze({"input_hash": "h1"})
        assert report.recommendations

        entries = j.recent(5)
        assert len(entries) == 1
        assert entries[0]["source"].startswith("k12.")
        assert "funding rate" in entries[0]["reasoning"]
        assert entries[0]["conclusion"].startswith("create_goal")


class TestMyslenieCommand:
    def _handler(self, tmp_path):
        from types import SimpleNamespace
        from agent_core.modules.homeostasis_telegram_commands import (
            register_telegram_commands,
        )

        class FakeBridge:
            def __init__(self):
                self.handlers = {}

            def register_command(self, command, handler):
                self.handlers[command] = handler

        bridge = FakeBridge()
        register_telegram_commands(bridge, SimpleNamespace(goal_store=None))
        return bridge.handlers["myslenie"]

    def test_empty_journal_message(self, tmp_path):
        set_reasoning_journal(_journal(tmp_path))
        out = self._handler(tmp_path)("")
        assert "pusty" in out

    def test_lists_entries(self, tmp_path):
        j = _journal(tmp_path)
        set_reasoning_journal(j)
        j.record(source="creative.reframe", reasoning="dluga mysl o celach",
                 conclusion="przeformulowac cel")
        out = self._handler(tmp_path)("5")
        assert "Notatnik rozumowania" in out
        assert "creative.reframe" in out
        assert "przeformulowac cel" in out

    def test_source_filter_arg(self, tmp_path):
        j = _journal(tmp_path)
        set_reasoning_journal(j)
        j.record(source="creative.reframe", reasoning="a")
        j.record(source="k12.nim_api", reasoning="b")
        out = self._handler(tmp_path)("5 creative")
        assert "creative.reframe" in out
        assert "k12.nim_api" not in out
