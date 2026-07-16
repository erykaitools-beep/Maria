"""Super-META E2: Maria's chat tail can carry a situational-self block (who she
is talking to + what she last saw + her state), so she answers as ONE situated
person. The block MUST live in the situational tail, never the cached prefix --
a per-call edit there busts the warm KV cache (the 240s-timeout class). Flag-gated
OFF (SELF_CONTEXT_CHAT_ENABLED), mirroring the honest-limits hint. No Ollama /
network.
"""

import pytest

from models.ollama_brain import OllamaBrain


class _StubSelfContext:
    """Minimal SelfContext: returns a fixed chat block (decouples the brain test
    from E0 aggregation internals -- those are covered in test_self_context)."""

    def __init__(self, text="[Twoja sytuacja]\nRozmawiasz teraz z operatorem: Eryk.\n"
                            "Ostatnio widzialas (5 min temu): Osoba przy biurku."):
        self._text = text

    def format_for_chat(self):
        return self._text


class _BoomSelfContext:
    def format_for_chat(self):
        raise RuntimeError("self_context boom")


@pytest.fixture
def brain():
    return OllamaBrain(verify_model=False)


def test_self_context_absent_when_flag_off(brain, monkeypatch):
    monkeypatch.delenv("SELF_CONTEXT_CHAT_ENABLED", raising=False)
    brain.set_self_context(_StubSelfContext())
    assert "Twoja sytuacja" not in brain._build_situational_tail()


def test_self_context_present_when_flag_on(brain, monkeypatch):
    monkeypatch.setenv("SELF_CONTEXT_CHAT_ENABLED", "1")
    brain.set_self_context(_StubSelfContext())
    tail = brain._build_situational_tail()
    assert "Twoja sytuacja" in tail
    assert "Osoba przy biurku" in tail          # last vision rides into the tail


def test_no_self_context_without_wiring(brain, monkeypatch):
    monkeypatch.setenv("SELF_CONTEXT_CHAT_ENABLED", "1")
    assert "Twoja sytuacja" not in brain._build_situational_tail()   # nothing wired


def test_empty_block_is_skipped(brain, monkeypatch):
    monkeypatch.setenv("SELF_CONTEXT_CHAT_ENABLED", "1")
    brain.set_self_context(_StubSelfContext(text=""))               # nothing to say
    assert "Twoja sytuacja" not in brain._build_situational_tail()


def test_format_for_chat_exception_is_safe(brain, monkeypatch):
    """A throwing SelfContext degrades to no block -- never crashes the tail."""
    monkeypatch.setenv("SELF_CONTEXT_CHAT_ENABLED", "1")
    brain.set_self_context(_BoomSelfContext())
    tail = brain._build_situational_tail()      # must not raise
    assert "Twoja sytuacja" not in tail


def test_prefix_byte_stable_regardless_of_self_context(brain, monkeypatch):
    """THE cache-safety invariant: the situational-self block lives in the tail,
    so the cached prefix is byte-identical whether SelfContext is wired + flag on
    or not. A per-call change in the prefix would bust the warm KV cache (240s)."""
    prefix_before = brain._build_stable_system_prompt()
    monkeypatch.setenv("SELF_CONTEXT_CHAT_ENABLED", "1")
    brain.set_self_context(_StubSelfContext())
    prefix_after = brain._build_stable_system_prompt()
    assert prefix_before == prefix_after        # prefix never moves -> cache safe
