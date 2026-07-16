"""Offline tests for CHAT_FAST_CONTEXT: cache-stable chat prefix + bounded context.

Root cause (measured live 2026-06-08): the chat path re-prefilled the ENTIRE
history every turn because refresh_time_context() rewrote the system message
(live HH:MM clock + session duration) on every call, busting Ollama's KV cache.
On this CPU-only box a full 4096-token prefill is ~260s -- past the 240s
read-timeout -- so a chat timed out before answering even with nothing else on
the CPU. Direct probes:
  - full 4096-tok prefill        = 261s
  - stable prefix + new turn     =  1.7s  (KV cache HIT)
  - one-line system-message edit =  88.5s (KV cache BUSTED)

The fix keeps the system prefix byte-stable (only a COARSE date/part-of-day
clock, never the per-call minute or session duration), sends each user turn
clean==stored so the next call's cached prefix matches a turn back, and bounds
the cold-cache context. These tests pin all three. No Ollama / network.
"""

import re

import pytest

from models.ollama_brain import (
    OllamaBrain,
    _fast_context_enabled,
    _CHAT_CTX_HIGH_CHARS,
    _CHAT_CTX_LOW_CHARS,
    _CHAT_TAIL_MAX_CHARS,
)

_HHMM = re.compile(r"\b\d{1,2}:\d{2}\b")


@pytest.fixture
def brain(monkeypatch):
    monkeypatch.setenv("CHAT_FAST_CONTEXT", "1")
    return OllamaBrain(verify_model=False)


# --- the cache-stability mechanism -----------------------------------------

def test_prefix_excludes_minute_clock_and_session_duration(brain, monkeypatch):
    """The cached prefix must carry no per-call volatile time -- that mutation
    was the bug. A coarse date/part-of-day is fine (shifts only hours apart)."""
    monkeypatch.setattr(
        brain, "_get_coarse_time_context",
        lambda: "poniedzialek, 08.06.2026 (wieczor)",
    )
    sys = brain._build_stable_system_prompt()
    assert not _HHMM.search(sys)          # no HH:MM
    assert "Rozmawiamy juz" not in sys    # no session-duration counter
    assert "08.06.2026" in sys            # coarse date present (awareness kept)


def test_prefix_byte_stable_while_minute_clock_advances(brain, monkeypatch):
    """THE core invariant: the wall clock advances every turn, but as long as
    the COARSE bucket is unchanged the prefix is byte-identical -> cache stays
    warm (1.7s) instead of re-prefilling (88.5s)."""
    minutes = iter(["18:00", "18:05", "18:11"])
    monkeypatch.setattr(brain, "_get_time_context",
                        lambda: f"godzina {next(minutes)}")  # would-be volatile
    monkeypatch.setattr(brain, "_get_coarse_time_context",
                        lambda: "poniedzialek, 08.06.2026 (wieczor)")  # stable

    a = brain._compose_send_messages("x")[0]["content"]
    b = brain._compose_send_messages("y")[0]["content"]
    assert a == b  # prefix unaffected by the advancing minute clock


def test_user_turn_sent_clean_equals_what_is_stored(brain):
    """send==store is what actually makes the cache hit: a decorated send vs a
    clean store would diverge the cache one turn back on every call."""
    msgs = brain._compose_send_messages("dokladnie to zdanie")
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"] == "dokladnie to zdanie"  # byte-clean, no tail


def test_send_list_starts_system_ends_user(brain):
    brain.history.append({"role": "user", "content": "a"})
    brain.history.append({"role": "assistant", "content": "b"})
    msgs = brain._compose_send_messages("c")
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["role"] == "user"


# --- situational tail (live state rides AFTER the cached prefix) ------------

def test_situational_tail_is_second_system_after_prefix(brain, monkeypatch):
    """Live work/state goes in a SECOND system message after the cached prefix
    (so the chat knows what Maria is doing now), user turn still clean."""
    monkeypatch.setattr(brain, "_get_work_context", lambda: "ucze sie: astronomia")
    msgs = brain._compose_send_messages("pytanie")
    assert msgs[0]["role"] == "system"               # cached prefix
    assert msgs[1]["role"] == "system"               # situational tail
    assert "astronomia" in msgs[1]["content"]
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"] == "pytanie"           # still byte-clean


def test_situational_tail_does_not_bust_prefix(brain, monkeypatch):
    """THE invariant for B: the tail changes every turn (live state) but the
    cached PREFIX stays byte-identical -> KV cache stays warm."""
    monkeypatch.setattr(brain, "_get_coarse_time_context",
                        lambda: "poniedzialek, 08.06.2026 (wieczor)")
    work = iter(["praca A", "praca B"])
    monkeypatch.setattr(brain, "_get_work_context", lambda: next(work))
    a = brain._compose_send_messages("x")
    b = brain._compose_send_messages("y")
    assert a[0]["content"] == b[0]["content"]          # prefix identical
    assert a[1]["content"] != b[1]["content"]          # tail differs (live)


def test_no_tail_means_no_second_system_message(brain, monkeypatch):
    """All providers empty -> empty tail -> only the prefix system message
    (graceful: the tail never appends an empty blurb)."""
    monkeypatch.setattr(brain, "_get_work_context", lambda: "")
    monkeypatch.setattr(brain, "_get_awareness_context", lambda: "")
    brain._evidence_collector = None
    msgs = brain._compose_send_messages("pytanie")
    assert len([m for m in msgs if m["role"] == "system"]) == 1


def test_situational_tail_capped(brain, monkeypatch):
    monkeypatch.setattr(brain, "_get_work_context", lambda: "x" * 5000)
    tail = brain._build_situational_tail()
    assert 0 < len(tail) <= _CHAT_TAIL_MAX_CHARS + 8   # cap + " ..." suffix


def test_conversation_context_not_in_prefix_rides_in_tail(brain, monkeypatch):
    """Regression (adversarial review 2026-06-21): Phase 20 appends conversation
    summaries to the file mid-chat. If that fed the cached prefix it would change
    the prefix bytes every few minutes and bust the KV cache. The prefix MUST
    exclude conversation context; it rides in the situational tail instead."""
    monkeypatch.setattr(brain, "_get_coarse_time_context",
                        lambda: "poniedzialek, 08.06.2026 (wieczor)")
    # Summary changes between turns (as Phase 20 condenses a new session).
    convos = iter(["[Pamiec rozmow: A]", "[Pamiec rozmow: B]"])
    monkeypatch.setattr(brain, "_get_conversation_context", lambda: next(convos))

    a = brain._compose_send_messages("x")
    b = brain._compose_send_messages("y")

    # Prefix byte-identical despite the conversation summary changing.
    assert a[0]["content"] == b[0]["content"]
    assert "Pamiec rozmow" not in a[0]["content"]   # not in the cached prefix
    # It rides in the situational tail (second system message).
    assert a[1]["role"] == "system"
    assert "Pamiec rozmow: A" in a[1]["content"]


# --- the cold-cache safety net (bounded context) ---------------------------

def test_context_bounded_when_history_huge(brain):
    """A cache MISS over a huge history must still fit under the timeout."""
    for i in range(20):
        brain.history.append({"role": "user", "content": f"U{i} " + "x" * 1500})
        brain.history.append({"role": "assistant", "content": f"A{i} " + "y" * 1500})

    msgs = brain._compose_send_messages("najnowsze pytanie")
    total = sum(len(m["content"]) for m in msgs)

    assert total <= _CHAT_CTX_HIGH_CHARS + 512   # bounded near HIGH
    joined = " ".join(m["content"] for m in msgs)
    assert "A19" in joined        # newest kept
    assert "U0 " not in joined     # oldest dropped


def test_trim_keeps_system_and_latest_prompt(brain):
    for _ in range(40):
        brain.history.append({"role": "user", "content": "x" * 1000})
        brain.history.append({"role": "assistant", "content": "y" * 1000})
    msgs = brain._compose_send_messages("PYTANIE_MARKER")
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["content"] == "PYTANIE_MARKER"


def test_hysteresis_trims_down_to_low_not_just_high(brain):
    """Trimming to LOW (not HIGH) makes trims rare -> warm cache stays warm."""
    big = "z" * 800
    turns = [{"role": "user" if i % 2 == 0 else "assistant", "content": big}
             for i in range(60)]
    trimmed = brain._trim_turns_to_budget(turns, base_chars=0)
    total = sum(len(m["content"]) for m in trimmed)
    assert total <= _CHAT_CTX_LOW_CHARS          # trimmed all the way to LOW
    assert trimmed[-1] is turns[-1]               # newest preserved


def test_small_history_is_not_trimmed(brain):
    turns = [{"role": "user", "content": "krotkie"},
             {"role": "assistant", "content": "ok"}]
    out = brain._trim_turns_to_budget(turns, base_chars=100)
    assert out == turns


# --- think() wiring: storage stays clean and matches what was sent ----------

def test_think_sends_and_stores_the_same_clean_user_turn(brain, monkeypatch):
    captured = {}

    def fake_chat(messages, **kw):
        captured["messages"] = list(messages)
        return "odpowiedz"

    monkeypatch.setattr(brain, "_chat", fake_chat)
    out = brain.think("pytanie testowe")

    assert out == "odpowiedz"
    sent_user = captured["messages"][-1]
    assert sent_user["role"] == "user"
    assert sent_user["content"] == "pytanie testowe"        # sent clean
    stored_users = [m["content"] for m in brain.history if m["role"] == "user"]
    assert "pytanie testowe" in stored_users                 # stored identical
    assert any(m["role"] == "assistant" and m["content"] == "odpowiedz"
               for m in brain.history)


# --- flag gating -----------------------------------------------------------

def test_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("CHAT_FAST_CONTEXT", raising=False)
    assert _fast_context_enabled() is False


def test_flag_off_uses_legacy_full_history(monkeypatch):
    monkeypatch.delenv("CHAT_FAST_CONTEXT", raising=False)
    b = OllamaBrain(verify_model=False)
    captured = {}

    def fake_chat(messages, **kw):
        captured["messages"] = messages  # legacy passes the live deque itself
        return "ok"

    monkeypatch.setattr(b, "_chat", fake_chat)
    b.think("legacy pytanie")
    assert captured["messages"] is b.history
    assert b.history[0]["role"] == "system"
