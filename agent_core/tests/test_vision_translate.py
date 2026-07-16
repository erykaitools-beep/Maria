"""LLMRouter.translate_to_polish -- render LLaVA's English scene description as
fluent Polish (NIM-first, local fallback, English last resort).

Unit-tests the method in isolation (router built via __new__ with stubbed
nim/ollama) so no real model or network is touched.
"""

from unittest.mock import MagicMock

from agent_core.llm.router import LLMRouter


def _router(nim_ok=True):
    r = LLMRouter.__new__(LLMRouter)
    r.nim = MagicMock()
    r.nim.model = "dracarys-70b"
    r.ollama = MagicMock()
    r.ollama.model = "qwen3:8b"
    r._nim_calls = 0
    r._nim_fallbacks = 0
    r._record_nim_usage = MagicMock()
    r._record_tape = MagicMock()
    r._should_use_nim = MagicMock(return_value=nim_ok)
    return r


def test_nim_first_returns_polish():
    r = _router(nim_ok=True)
    r.nim._ask_once.return_value = "Widać ulicę i dom."
    out = r.translate_to_polish("A street and a house are visible.")
    assert out == "Widać ulicę i dom."
    r.nim._ask_once.assert_called_once()
    r._record_nim_usage.assert_called_once()
    r.ollama.think.assert_not_called()       # NIM succeeded -> no local call


def test_nim_failure_falls_back_to_local():
    r = _router(nim_ok=True)
    r.nim._ask_once.side_effect = RuntimeError("nim down")
    r.ollama.think.return_value = "Lokalny polski opis."
    out = r.translate_to_polish("A car outside.")
    assert out == "Lokalny polski opis."
    r.ollama.think.assert_called_once()
    assert r._nim_fallbacks == 1


def test_nim_skipped_when_budget_or_unavailable():
    r = _router(nim_ok=False)               # _should_use_nim False (budget/no key)
    r.ollama.think.return_value = "Polski z lokalnego."
    out = r.translate_to_polish("Two trees.")
    assert out == "Polski z lokalnego."
    r.nim._ask_once.assert_not_called()


def test_both_fail_returns_english():
    r = _router(nim_ok=True)
    r.nim._ask_once.side_effect = RuntimeError("nim down")
    r.ollama.think.side_effect = RuntimeError("ollama down")
    out = r.translate_to_polish("A fence and a wall.")
    assert out == "A fence and a wall."     # honest English, never garbled/empty


def test_blank_nim_result_falls_through_to_local():
    r = _router(nim_ok=True)
    r.nim._ask_once.return_value = "   "     # blank -> not accepted
    r.ollama.think.return_value = "Z lokalnego."
    out = r.translate_to_polish("Something.")
    assert out == "Z lokalnego."


def test_empty_input_returned_as_is():
    r = _router()
    assert r.translate_to_polish("") == ""
    assert r.translate_to_polish("   ") == "   "
    r.nim._ask_once.assert_not_called()
