"""Etap 4 (DH 'Relacja' / K14.1): ActiveLearner -- Maria asks AT MOST one
low-pressure question/day to fill a high-value gap in her operator model, picks
privacy-safely, captures the answer, and never stacks two open questions. Wired
into the ProactiveScheduler as a flag-gated (ACTIVE_LEARNER_ENABLED)
OPERATOR_QUESTION reason. Pure logic + generator + scheduler-gating; no daemon.
"""

from agent_core.operator.active_learner import (
    ActiveLearner,
    GAP_CANDIDATES,
    _PER_KEY_COOLDOWN_SEC,
)
from agent_core.proactive.generators import ContentGenerators
from agent_core.proactive.proactive_model import ContactReason


# --- a precise fake operator model --------------------------------------------

class _FakeFact:
    def __init__(self, value, confidence):
        self.value = value
        self.confidence = confidence


class _FakeOM:
    def __init__(self, facts=None, blocked=None):
        self._facts = dict(facts or {})
        self._blocked = set(blocked or [])
        self.set_calls = []

    def get_fact(self, key):
        return self._facts.get(key)

    def is_allowed(self, topic):
        return topic not in self._blocked

    def set_fact(self, key, value, confidence=1.0, source=""):
        self.set_calls.append((key, value, confidence, source))
        self._facts[key] = _FakeFact(value, confidence)


def _al(tmp_path):
    return ActiveLearner(state_path=tmp_path / "al.json")


# --- pick_gap (the privacy-aware ranker) --------------------------------------

def test_picks_highest_weight_missing_gap(tmp_path):
    assert _al(tmp_path).pick_gap(_FakeOM()) == "city"   # weight 0.9 wins


def test_skips_known_high_confidence_fact(tmp_path):
    om = _FakeOM(facts={"city": _FakeFact("Berlin", 0.9)})
    assert _al(tmp_path).pick_gap(om) == "personal_goal"  # next highest


def test_low_confidence_fact_is_still_a_gap(tmp_path):
    om = _FakeOM(facts={"city": _FakeFact("?", 0.3)})
    assert _al(tmp_path).pick_gap(om) == "city"


def test_respects_privacy_boundary(tmp_path):
    om = _FakeOM(blocked={"city"})
    assert _al(tmp_path).pick_gap(om) == "personal_goal"  # never ask off-limits


def test_none_when_everything_known(tmp_path):
    facts = {c.key: _FakeFact("x", 0.95) for c in GAP_CANDIDATES}
    assert _al(tmp_path).pick_gap(_FakeOM(facts=facts)) is None


def test_per_key_cooldown_blocks_reask(tmp_path):
    al = _al(tmp_path)
    om = _FakeOM()
    base = 1_700_000_000.0                  # a realistic epoch (never-asked = 0.0)
    al.next_question(om, now=base)          # asks city, stamps asked@base
    al._pending = None                      # pretend it was answered
    # still missing, but within the 14d cooldown -> skip city, offer next gap
    assert al.pick_gap(om, now=base + 1000.0) == "personal_goal"
    # after the cooldown -> city eligible again
    assert al.pick_gap(om, now=base + _PER_KEY_COOLDOWN_SEC + 1.0) == "city"


# --- next_question / pending / persistence ------------------------------------

def test_next_question_marks_pending_and_persists(tmp_path):
    al = _al(tmp_path)
    q = al.next_question(_FakeOM())
    assert q and "miasta" in q.lower()
    assert al.has_pending() and al.pending_key() == "city"
    # survives a restart (fresh instance reads the same state file)
    al2 = ActiveLearner(state_path=tmp_path / "al.json")
    assert al2.has_pending() and al2.pending_key() == "city"


def test_one_open_question_at_a_time(tmp_path):
    al = _al(tmp_path)
    om = _FakeOM()
    assert al.next_question(om) is not None
    assert al.next_question(om) is None     # pending blocks a second ask


# --- consume_answer -----------------------------------------------------------

def test_consume_answer_stores_on_asked_fact_and_clears(tmp_path):
    al = _al(tmp_path)
    om = _FakeOM()
    al.next_question(om)                     # pending=city
    assert al.consume_answer("Berlin", om) == "city"
    # hedged confidence (heuristic capture, not a parsed statement)
    assert ("city", "Berlin", 0.8, "asked:telegram") in om.set_calls
    assert not al.has_pending()


def test_stale_pending_not_captured_and_unwedges(tmp_path):
    """A much-later unrelated message must NOT be stored as the answer, and the
    abandoned pending must clear so asking isn't wedged forever (review [5]/[6])."""
    al = _al(tmp_path)
    om = _FakeOM()
    base = 1_700_000_000.0
    al.next_question(om, now=base)                     # asks city, pending@base
    assert al.consume_answer("kup mleko", om, now=base + 7 * 3600) is None
    assert om.set_calls == []                          # nothing stored
    assert not al.has_pending()                        # stale pending cleared


def test_fresh_pending_is_captured(tmp_path):
    al = _al(tmp_path)
    om = _FakeOM()
    base = 1_700_000_000.0
    al.next_question(om, now=base)
    assert al.consume_answer("Berlin", om, now=base + 600) == "city"  # 10 min later
    assert om.set_calls and om.set_calls[0][1] == "Berlin"


def test_consume_answer_no_pending_returns_none(tmp_path):
    assert _al(tmp_path).consume_answer("Berlin", _FakeOM()) is None


def test_consume_answer_empty_text_keeps_pending(tmp_path):
    al = _al(tmp_path)
    al.next_question(_FakeOM())
    assert al.consume_answer("   ", _FakeOM()) is None
    assert al.has_pending()                  # an empty reply isn't an answer


# --- generator wiring ---------------------------------------------------------

def test_generator_emits_question():
    gen = ContentGenerators()
    gen.set_operator_question_fn(lambda: "Z jakiego miasta jestes?")
    c = gen.generate(ContactReason.OPERATOR_QUESTION)
    assert c is not None
    assert c.reason == ContactReason.OPERATOR_QUESTION
    assert "miasta" in c.message


def test_generator_none_when_nothing_to_ask():
    gen = ContentGenerators()
    gen.set_operator_question_fn(lambda: None)
    assert gen.generate(ContactReason.OPERATOR_QUESTION) is None


def test_generator_none_without_fn():
    assert ContentGenerators().generate(ContactReason.OPERATOR_QUESTION) is None


# --- scheduler flag-gating ----------------------------------------------------

def test_scheduler_checks_operator_question_only_when_flag_on(tmp_path, monkeypatch):
    from agent_core.proactive import ProactiveScheduler

    sched = ProactiveScheduler(state_path=tmp_path / "p.json")
    asked = []

    def spy(reason):
        asked.append(reason)
        return None  # return nothing -> no _send, no history I/O

    monkeypatch.setattr(sched.generators, "generate", spy)
    monkeypatch.setattr(sched, "_in_time_window", lambda r: True)
    monkeypatch.setattr(sched, "_can_send", lambda r: True)

    monkeypatch.delenv("ACTIVE_LEARNER_ENABLED", raising=False)
    sched._check_scheduled()
    assert ContactReason.OPERATOR_QUESTION not in asked   # off -> never asked

    asked.clear()
    monkeypatch.setenv("ACTIVE_LEARNER_ENABLED", "1")
    sched._check_scheduled()
    assert ContactReason.OPERATOR_QUESTION in asked       # on -> checked
