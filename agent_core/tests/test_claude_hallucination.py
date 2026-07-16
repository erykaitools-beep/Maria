"""ClaudeClient must never return hallucinated tool-call text as a 'result'.

2026-06-22: /claude runs `claude --tools ""` (no tools, per the 2026-06-12
security audit). Asked to act ("send file X"), the model printed
<tool_call>{...}</tool_call> pseudo-syntax as plain text; that non-empty,
exit-0 output was returned as a successful result -> a false COMPLETED that
shipped gibberish to the operator. looks_like_tool_hallucination catches it.
"""

from agent_core.llm.claude_client import ClaudeClient, looks_like_tool_hallucination


# The actual morning output (abridged): "Let me check..." + fake tool calls.
_MORNING_GIBBERISH = (
    "Let me check the current DH roadmap and Telegram sending mechanism.\n\n"
    '<tool_call>\n{"name": "Read", "arguments": {"file_path": '
    '"docs/DIGITAL_HUMAN_ROADMAP.md"}}\n</tool_call>\n'
    '<tool_call>\n{"name": "Grep", "arguments": {"pattern": "send_message"}}\n'
    "</tool_call>"
)

_INVOKE_STYLE = (
    "Sure, I'll send it.\n"
    '<invoke name="send_telegram">\n<parameter name="file">x.md</parameter>\n'
    "</invoke>"
)


def test_morning_gibberish_flagged():
    assert looks_like_tool_hallucination(_MORNING_GIBBERISH) is True


def test_invoke_style_flagged():
    assert looks_like_tool_hallucination(_INVOKE_STYLE) is True


def test_tool_use_format_flagged():
    # The actual current CLI (claude 2.1.84) format, captured live 2026-06-22:
    # a <tool_use> block as TEXT followed by a confabulated answer.
    text = (
        '<tool_use>\n{"type":"tool_use","id":"toolu_01","name":"Read",'
        '"input":{"file_path":"docs/ROADMAP.md","limit":5}}\n</tool_use>\n\n'
        "The first heading line is:\n# M.A.R.I.A. — Roadmap"
    )
    assert looks_like_tool_hallucination(text) is True


def test_empty_and_none_not_flagged():
    assert looks_like_tool_hallucination("") is False
    assert looks_like_tool_hallucination(None) is False


def test_real_analysis_survives():
    # A substantial answer that merely mentions the phrase "tool_call" in prose
    # must NOT be flagged (no actual markers, plenty of text).
    text = ("Modul planner uzywa petli ReAct. " * 30)
    assert looks_like_tool_hallucination(text) is False


def test_real_analysis_with_incidental_tag_mention_survives():
    text = (
        "Analiza: backend /claude dziala bez narzedzi. " * 25
        + "W logach widac sztuczny znacznik <tool_call> ktory model wypisuje "
        "jako tekst, co jest oczekiwane przy --tools pustym."
    )
    # Has a marker but >400 chars of real prose -> survives.
    assert looks_like_tool_hallucination(text) is False


def test_short_answer_no_markers_survives():
    assert looks_like_tool_hallucination("Plik nie istnieje, nie moge go odczytac.") is False


def test_short_code_review_quoting_a_tag_survives():
    # Finding [5]: /claude is a text analyst -- a terse, correct review that
    # QUOTES a tool-call tag must not be discarded. Prose dominates -> survives.
    text = ('Bug: handler buduje <invoke name="send"> z <parameter name="x"> '
            "zamiast czystego tekstu; popraw na zwykla odpowiedz.")
    assert looks_like_tool_hallucination(text) is False


def test_nested_json_args_fully_stripped_and_flagged():
    # Finding [6]: the strip must remove a NESTED {"arguments": {...}} block so
    # the morning-style gibberish is correctly flagged (flat regex could not).
    text = ('Robie to.\n<tool_call>{"name": "Read", "arguments": '
            '{"file_path": "docs/x.md", "opts": {"deep": true}}}</tool_call>')
    assert looks_like_tool_hallucination(text) is True


def test_invoke_treats_gibberish_as_no_result(monkeypatch):
    """End-to-end: _invoke returns None (not the gibberish) when the CLI emits
    hallucinated tool-calls on exit 0."""
    client = ClaudeClient()

    class _FakeProc:
        returncode = 0
        stdout = _MORNING_GIBBERISH
        stderr = ""

    monkeypatch.setattr(
        "agent_core.llm.claude_client.subprocess.run",
        lambda *a, **k: _FakeProc(),
    )
    assert client._invoke("wyslij mape DH") is None


def test_invoke_returns_real_answer(monkeypatch):
    client = ClaudeClient()
    real = "Modul planner jest rule-based. " * 30

    class _FakeProc:
        returncode = 0
        stdout = real
        stderr = ""

    monkeypatch.setattr(
        "agent_core.llm.claude_client.subprocess.run",
        lambda *a, **k: _FakeProc(),
    )
    assert client._invoke("przeanalizuj planner") == real.strip()
