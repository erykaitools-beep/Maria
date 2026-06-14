"""Tests for TaskIntentDetector — Polish + English patterns.

Scope: each supported tool gets happy-path cases, quote handling,
and one negative case. Order-sensitive: write patterns must match
before search patterns (write includes a content clause).
"""

import pytest

from agent_core.effector.intent_detector import TaskIntent, TaskIntentDetector


@pytest.fixture
def detector():
    return TaskIntentDetector()


class TestWrite:
    def test_polish_basic(self, detector):
        r = detector.detect("napisz plik /tmp/x.txt z trescia 'hello'")
        assert r is not None
        assert r.tool_name == "write"
        assert r.tool_args == {"path": "/tmp/x.txt", "content": "hello"}

    def test_polish_tekstem_synonym(self, detector):
        r = detector.detect("zapisz plik /tmp/y.md z tekstem 'Hej'")
        assert r.tool_name == "write"
        assert r.tool_args["content"] == "Hej"

    def test_polish_stworz_synonym(self, detector):
        r = detector.detect('stworz plik /home/maria/foo.txt z "ABC"')
        assert r.tool_name == "write"
        assert r.tool_args["path"] == "/home/maria/foo.txt"
        assert r.tool_args["content"] == "ABC"

    def test_english_basic(self, detector):
        r = detector.detect("write file /tmp/x.txt with 'hello'")
        assert r.tool_name == "write"
        assert r.tool_args == {"path": "/tmp/x.txt", "content": "hello"}

    def test_english_containing_synonym(self, detector):
        r = detector.detect("create /tmp/y containing foo")
        assert r.tool_name == "write"

    def test_content_without_quotes(self, detector):
        r = detector.detect("napisz plik /tmp/a.txt z trescia hello world")
        assert r.tool_name == "write"
        assert r.tool_args["content"] == "hello world"

    def test_multiline_content(self, detector):
        r = detector.detect("napisz plik /tmp/multi.txt z trescia 'line1\nline2'")
        assert r.tool_name == "write"
        assert "\n" in r.tool_args["content"]


class TestRead:
    def test_polish_basic(self, detector):
        r = detector.detect("przeczytaj plik /etc/hostname")
        assert r.tool_name == "read"
        assert r.tool_args == {"path": "/etc/hostname"}

    def test_polish_pokaz(self, detector):
        r = detector.detect("pokaz plik /tmp/x.txt")
        assert r.tool_name == "read"

    def test_english_cat(self, detector):
        r = detector.detect("cat /etc/hostname")
        assert r.tool_name == "read"
        assert r.tool_args == {"path": "/etc/hostname"}

    def test_english_without_file_keyword(self, detector):
        r = detector.detect("read /tmp/log.txt")
        assert r.tool_name == "read"


class TestWebFetch:
    def test_polish(self, detector):
        r = detector.detect("pobierz https://example.com/page")
        assert r.tool_name == "web_fetch"
        assert r.tool_args["url"] == "https://example.com/page"

    def test_english(self, detector):
        r = detector.detect("fetch https://api.github.com/users/torvalds")
        assert r.tool_name == "web_fetch"

    def test_non_http_url_rejected(self, detector):
        """ftp:// / file:// urls shouldn't match web_fetch."""
        r = detector.detect("pobierz ftp://example.com/file")
        # web_fetch pattern requires https?:// prefix; falls through to None
        # OR matches search (since "ftp://..." could be a query). Accept either.
        if r is not None:
            assert r.tool_name != "web_fetch"


class TestWebSearch:
    def test_polish_basic(self, detector):
        r = detector.detect("wyszukaj python asyncio")
        assert r.tool_name == "web_search"
        assert r.tool_args["query"] == "python asyncio"

    def test_polish_znajdz(self, detector):
        r = detector.detect("znajdz 'najnowsze wiadomosci z IT'")
        assert r.tool_name == "web_search"
        assert r.tool_args["query"] == "najnowsze wiadomosci z IT"

    def test_english(self, detector):
        r = detector.detect("search for claude api docs")
        assert r.tool_name == "web_search"
        assert r.tool_args["query"] == "claude api docs"


class TestExec:
    def test_polish(self, detector):
        r = detector.detect("wykonaj komende 'uptime'")
        assert r.tool_name == "exec"
        assert r.tool_args["command"] == "uptime"

    def test_polish_polecenie_synonym(self, detector):
        r = detector.detect("uruchom polecenie df -h")
        assert r.tool_name == "exec"
        assert r.tool_args["command"] == "df -h"

    def test_english(self, detector):
        r = detector.detect("run command 'free -m'")
        assert r.tool_name == "exec"
        assert r.tool_args["command"] == "free -m"

    def test_english_without_keyword(self, detector):
        r = detector.detect("execute whoami")
        assert r.tool_name == "exec"
        assert r.tool_args["command"] == "whoami"


class TestNoMatch:
    def test_empty_string(self, detector):
        assert detector.detect("") is None
        assert detector.detect("   ") is None

    def test_none_input(self, detector):
        assert detector.detect(None) is None  # type: ignore[arg-type]

    def test_ambiguous_text(self, detector):
        """Plain question / statement should not match."""
        assert detector.detect("co dzisiaj robilas?") is None

    def test_partial_keyword_only(self, detector):
        """'napisz' alone without the full pattern shouldn't match."""
        assert detector.detect("napisz") is None

    def test_goal_description(self, detector):
        """A typical goal description (learn X) must not false-match."""
        assert detector.detect("nauka tematu: python asyncio") is None


class TestPatternMeta:
    def test_returns_pattern_id(self, detector):
        r = detector.detect("napisz plik /tmp/x.txt z 'y'")
        assert r.pattern_id == "write_pl"

    def test_confidence_is_one(self, detector):
        r = detector.detect("wykonaj komende uptime")
        assert r.confidence == 1.0

    def test_raw_text_preserved(self, detector):
        text = "pobierz https://example.com/x"
        r = detector.detect(text)
        assert r.raw_text == text

    def test_help_examples_cover_every_tool(self, detector):
        examples = detector.help_examples()
        tools = {detector.detect(ex).tool_name for ex in examples}
        assert {"write", "read", "web_fetch", "web_search", "exec"} <= tools


class TestIntegrationWithToolSpecs:
    """Every detected intent must pass tool_specs validation."""

    @pytest.mark.parametrize("text", [
        "napisz plik /tmp/x.txt z 'hello'",
        "przeczytaj plik /etc/hostname",
        "pobierz https://example.com/x",
        "wyszukaj python asyncio",
        "wykonaj komende 'uptime'",
    ])
    def test_detected_intent_passes_validation(self, detector, text):
        from agent_core.effector.tool_specs import validate_args, is_tool_allowed

        intent = detector.detect(text)
        assert intent is not None, f"Detector missed: {text}"
        assert is_tool_allowed(intent.tool_name)
        valid, reason = validate_args(intent.tool_name, intent.tool_args)
        assert valid, f"{text} -> {intent.tool_name} {intent.tool_args}: {reason}"
