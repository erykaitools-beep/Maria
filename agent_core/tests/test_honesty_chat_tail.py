"""Etap 3 (DH 'Samowiedza' in chat): Maria's chat tail can carry a short, honest
"what I can't reliably do yet" line (K15.2) so she stops overclaiming. The line
MUST live in the situational tail, never the cached prefix -- a per-call edit
there busts the warm KV cache (the 240s-timeout class, 2026-06-08). Flag-gated
OFF (HONESTY_HINT_ENABLED). Also pins the qualify_statement double-comma fix.
No Ollama / network.
"""

import pytest

from models.ollama_brain import OllamaBrain
from agent_core.operator.honesty_protocol import HonestyProtocol


# --- qualify_statement: double-comma fix --------------------------------------

def test_low_confidence_has_no_stray_comma_after_ale():
    p = HonestyProtocol()
    out = p.qualify_statement("Moge to zrobic", 0.3)
    assert "nie jestem pewna" in out.lower()
    assert "ale," not in out               # the bug was "...ale, moge..."
    assert "ale moge" in out               # correct join


def test_medium_confidence_no_stray_comma():
    p = HonestyProtocol()
    out = p.qualify_statement("Potrafie pobierac dane", 0.65)
    assert out.startswith("Prawdopodobnie ")   # space, not "Prawdopodobnie,"
    assert "Prawdopodobnie," not in out


def test_high_and_zero_confidence_unchanged():
    p = HonestyProtocol()
    assert p.qualify_statement("Umiem sie uczyc", 0.95) == "Umiem sie uczyc"
    assert p.qualify_statement("Cos tam", 0.0) == "Nie wiem."


# --- get_honest_limits_line ---------------------------------------------------

class _Lim:
    def __init__(self, category, description):
        self.category = category
        self.description = description


class _StubManifest:
    def __init__(self, limitations):
        self._lims = limitations

    def get_limitations(self):
        return self._lims


def test_limits_line_empty_without_manifest():
    assert HonestyProtocol().get_honest_limits_line() == ""


def test_limits_line_skips_perf_and_transient():
    """Hardware (perf) + mode-based (transient) limits are NOT honest 'can't do'
    -> dropped, so a healthy system emits nothing."""
    p = HonestyProtocol()
    p.set_capability_manifest(_StubManifest([
        _Lim("hardware", "Brak GPU - LLM na CPU"),
        _Lim("software", "Tryb SLEEP - ograniczone dzialania"),
        _Lim("autonomy", "Domyslny poziom: OBSERVE"),  # stale -> dropped
    ]))
    assert p.get_honest_limits_line() == ""


def test_limits_line_lists_concrete_gaps():
    p = HonestyProtocol()
    p.set_capability_manifest(_StubManifest([
        _Lim("hardware", "Brak GPU"),
        _Lim("software", "Brak dostepu do email, kalendarza, smart home"),
        _Lim("knowledge", "Ucze sie tylko z plikow txt i Wikipedia PL"),
    ]))
    line = p.get_honest_limits_line()
    assert "Szczerze" in line
    assert "email" in line
    assert "Wikipedia" in line
    assert "GPU" not in line                # hardware (perf) dropped


def test_limits_line_capped():
    p = HonestyProtocol()
    p.set_capability_manifest(_StubManifest(
        [_Lim("software", f"rzecz {i}") for i in range(10)]
    ))
    line = p.get_honest_limits_line(max_items=2)
    assert line.count(";") == 1            # 2 items -> exactly 1 separator


# --- chat tail integration + CACHE SAFETY -------------------------------------

@pytest.fixture
def brain():
    return OllamaBrain(verify_model=False)


def _honesty_with_limits():
    p = HonestyProtocol()
    p.set_capability_manifest(_StubManifest([
        _Lim("software", "Brak dostepu do email, kalendarza, smart home"),
    ]))
    return p


def test_hint_absent_when_flag_off(brain, monkeypatch):
    monkeypatch.delenv("HONESTY_HINT_ENABLED", raising=False)
    brain.set_honesty_protocol(_honesty_with_limits())
    assert "Szczerze" not in brain._build_situational_tail()


def test_hint_present_when_flag_on(brain, monkeypatch):
    monkeypatch.setenv("HONESTY_HINT_ENABLED", "1")
    brain.set_honesty_protocol(_honesty_with_limits())
    assert "email" in brain._build_situational_tail()


def test_no_hint_without_protocol_even_when_flag_on(brain, monkeypatch):
    monkeypatch.setenv("HONESTY_HINT_ENABLED", "1")
    assert "Szczerze" not in brain._build_situational_tail()   # nothing wired


def test_prefix_byte_stable_regardless_of_honesty(brain, monkeypatch):
    """THE cache-safety invariant: the honest-limits hint lives in the tail, so
    the cached prefix is byte-identical whether honesty is wired + flag on or
    not. A per-call change in the prefix would bust the warm KV cache (240s)."""
    prefix_before = brain._build_stable_system_prompt()
    monkeypatch.setenv("HONESTY_HINT_ENABLED", "1")
    brain.set_honesty_protocol(_honesty_with_limits())
    prefix_after = brain._build_stable_system_prompt()
    assert prefix_before == prefix_after   # prefix never moves -> cache safe
