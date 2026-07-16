"""Tests for Maria's self-time ("pokoj dla siebie" / PLAY).

An ungraded, flag-gated idle action: when idle AND awake, Maria takes a "walk
through her own head" -- a free musing over what she already knows, written to
her own notebook she re-reads. No goal, no exam, no score.

Covers: PlayModule behaviour (ungraded, feed-forward, bookkeeping filter,
no-LLM fallback), planner _maybe_play gating (flag/cooldown/budget/quiet/awake),
keep-awake (PLAY resets the idle streak), executor dispatch, and the K7/spec/
handler registration that makes it work in production.
"""

from datetime import datetime
from types import SimpleNamespace

import agent_core.play.play_module as pm_mod
from agent_core.play import PlayModule
from agent_core.planner.planner_core import PlannerCore
from agent_core.planner.planner_model import ActionType, PlanStatus, create_plan
from agent_core.planner.action_executor import ActionExecutor
from agent_core.planner.time_context import TimeContext
from agent_core.routing.capability_router import CapabilityRouter
from agent_core.routing.capability_spec import DEFAULT_CAPABILITY_SPECS
from agent_core.routing.handlers import make_play_handler
from agent_core.autonomy.action_class import classify_action, ActionClassification


# ----------------------------- fakes -----------------------------------

class FakePlay:
    """Stand-in PlayModule for planner/executor tests."""

    def __init__(self, today=0, kind="daydream"):
        self._today = today
        self._kind = kind
        self.calls = 0

    def count_today(self):
        return self._today

    def play(self, trigger="planner_idle"):
        self.calls += 1
        return {"success": True, "kind": self._kind, "musing": "m", "seeds": ["a"]}


class _FakeState:
    def __init__(self, mode):
        self.mode = SimpleNamespace(value=mode)
        self.health_score = 1.0


class FakeHomeo:
    def __init__(self, mode="active"):
        self._mode = mode
        self.activity_calls = 0

    def get_state(self):
        return _FakeState(self._mode)

    def record_activity(self):
        self.activity_calls += 1


def _planner(tmp_path, enabled=False):
    p = PlannerCore(
        state_path=tmp_path / "state.json",
        decisions_path=tmp_path / "decisions.jsonl",
    )
    if enabled:
        p.set_play_enabled(True)
    return p


# real, idea-like beliefs vs. system bookkeeping
_REAL_BELIEFS = [
    {"belief_id": "b3", "content": "Fotosynteza zamienia swiatlo w energie chemiczna", "confidence": 0.8},
    {"belief_id": "b4", "content": "Liczby pierwsze sa podzielne tylko przez 1 i samych siebie", "confidence": 0.8},
]
_BOOKKEEPING = [
    {"belief_id": "b1", "content": "Plik 'expert_x.txt' opanowany (score 82%)", "confidence": 0.9},
    {"belief_id": "b2", "content": "Temat 'system' wystepuje w 18 plikach", "confidence": 0.9},
]


# ------------------------- PlayModule core ------------------------------

def test_play_writes_ungraded_entry(tmp_path):
    pm = PlayModule(data_dir=str(tmp_path), llm_fn=None,
                    belief_provider=lambda: list(_REAL_BELIEFS))
    res = pm.play()
    assert res["success"] is True
    entries = pm.journal.recent()
    assert len(entries) == 1
    e = entries[0]
    # ungraded by design: no score, no goal, no exam anywhere in the entry
    assert "score" not in e and "goal_id" not in e and "exam" not in e
    assert e["musing"]
    assert e["by_llm"] is False
    assert e["seeds"]


def test_play_filters_bookkeeping_seeds(tmp_path):
    pm = PlayModule(data_dir=str(tmp_path), llm_fn=None,
                    belief_provider=lambda: _BOOKKEEPING + _REAL_BELIEFS)
    pm.play()
    e = pm.journal.recent(1)[0]
    joined = " ".join(e["seeds"])
    assert "opanowany" not in joined
    assert "wystepuje w" not in joined
    assert e["seed_source"] == "beliefs"


def test_play_stores_fetchable_topic_labels(tmp_path):
    # 2026-06-20: PLAY loop write side -- the seed beliefs' fetchable TAGS (the
    # searchable subjects of what she mused on) are captured in `topics` so a
    # waking fascination she returns to can steer fresh supply (twin of dreams).
    # Tags, not entity: TOPIC-type beliefs are filtered as bookkeeping before
    # seeding, so the subject comes from the CONCEPT seed's tags.
    tagged = [
        {"belief_id": "t1", "content": "Fotosynteza zamienia swiatlo w energie",
         "tags": ["fotosynteza", "biologia"], "confidence": 0.8},
        {"belief_id": "t2", "content": "Liczby pierwsze sa szczegolne",
         "tags": ["liczby pierwsze", "teoria liczb"], "confidence": 0.8},
    ]
    pm = PlayModule(data_dir=str(tmp_path), llm_fn=None,
                    belief_provider=lambda: tagged)
    pm.play()
    e = pm.journal.recent(1)[0]
    assert e["topics"]                                   # tags surfaced as topics
    assert set(e["topics"]) <= {"fotosynteza", "biologia",
                                "liczby pierwsze", "teoria liczb"}
    assert any(t in e["topics"] for t in ("fotosynteza", "liczby pierwsze"))


def test_play_topics_empty_without_fetchable_tags(tmp_path):
    # Seed beliefs with no fetchable tags -> topics stays empty (better empty
    # than garbage-in): too-short and file-id tags are dropped at the source.
    untagged = [
        {"belief_id": "u1", "content": "Pewna idea pierwsza",
         "tags": [], "confidence": 0.8},
        {"belief_id": "u2", "content": "Pewna idea druga",
         "tags": ["a", "web_rss_x.txt"], "confidence": 0.8},  # short / file-id
    ]
    pm = PlayModule(data_dir=str(tmp_path), llm_fn=None,
                    belief_provider=lambda: untagged)
    pm.play()
    e = pm.journal.recent(1)[0]
    assert e["topics"] == []


def test_play_uses_llm_when_present(tmp_path):
    pm = PlayModule(data_dir=str(tmp_path), llm_fn=lambda p: "MOJA WOLNA MYSL",
                    belief_provider=lambda: list(_REAL_BELIEFS))
    res = pm.play()
    assert res["musing"] == "MOJA WOLNA MYSL"
    assert pm.journal.recent(1)[0]["by_llm"] is True


def test_play_falls_back_when_llm_fails(tmp_path):
    def boom(_p):
        raise RuntimeError("ollama down")
    pm = PlayModule(data_dir=str(tmp_path), llm_fn=boom,
                    belief_provider=lambda: list(_REAL_BELIEFS))
    res = pm.play()
    assert res["success"] is True
    # graceful fallback to a plain rule-based note, never crashes the tick
    assert res["musing"]


def test_play_feed_forward_continues_thread(tmp_path, monkeypatch):
    # Force the "continue a prior thread" branch (random >= 0.5) + det. picks.
    monkeypatch.setattr(pm_mod.random, "random", lambda: 0.99)
    monkeypatch.setattr(pm_mod.random, "choice", lambda seq: seq[0])
    pm = PlayModule(data_dir=str(tmp_path), llm_fn=lambda p: "myslе dalej",
                    belief_provider=lambda: list(_REAL_BELIEFS))
    first = pm.play()
    assert first["continued_thread"] is False  # nothing to continue yet
    second = pm.play()
    assert second["continued_thread"] is True
    # the journal entry links back to a prior entry (the loop creative never closed)
    assert pm.journal.recent(1)[0]["continues"] is not None


def test_play_quiet_when_no_seeds(tmp_path):
    pm = PlayModule(data_dir=str(tmp_path), llm_fn=None, belief_provider=lambda: [])
    res = pm.play()
    assert res["success"] is True
    assert res["kind"] == "quiet"
    assert pm.journal.recent() == []  # nothing forced into the notebook


def test_count_today_increments(tmp_path):
    pm = PlayModule(data_dir=str(tmp_path), llm_fn=None,
                    belief_provider=lambda: list(_REAL_BELIEFS))
    assert pm.count_today() == 0
    pm.play()
    assert pm.count_today() == 1


# ----------------------- planner _maybe_play gating ---------------------

def test_play_flag_off_returns_none(tmp_path, monkeypatch):
    monkeypatch.delenv("PLAY_ENABLED", raising=False)  # avoid .env leak
    p = _planner(tmp_path)
    p.set_play_module(FakePlay())
    assert p._play_enabled is False
    assert p._maybe_play({}) is None


def test_play_happy_path_emits_plan(tmp_path):
    p = _planner(tmp_path, enabled=True)
    p._homeostasis_core = FakeHomeo("active")
    p._time_ctx = TimeContext(now=datetime(2026, 6, 19, 14, 30))  # daytime, not quiet
    p.set_play_module(FakePlay(today=0))
    p._state.last_play_ts = 0.0

    plan = p._maybe_play({})
    assert plan is not None
    assert plan.action_type == ActionType.PLAY
    assert plan.goal_id is None
    assert p._state.last_play_ts > 0.0  # cooldown stamped


def test_play_cooldown_blocks(tmp_path):
    import time
    p = _planner(tmp_path, enabled=True)
    p._homeostasis_core = FakeHomeo("active")
    p._time_ctx = TimeContext(now=datetime(2026, 6, 19, 14, 30))
    p.set_play_module(FakePlay(today=0))
    p._state.last_play_ts = time.time()  # just played
    assert p._maybe_play({}) is None


def test_play_budget_blocks(tmp_path):
    p = _planner(tmp_path, enabled=True)
    p._homeostasis_core = FakeHomeo("active")
    p._time_ctx = TimeContext(now=datetime(2026, 6, 19, 14, 30))
    p.set_play_module(FakePlay(today=p._play_daily_budget))  # budget spent
    p._state.last_play_ts = 0.0
    assert p._maybe_play({}) is None


def test_play_quiet_hours_blocks(tmp_path):
    p = _planner(tmp_path, enabled=True)
    p._homeostasis_core = FakeHomeo("active")
    p._time_ctx = TimeContext(now=datetime(2026, 6, 19, 23, 30))  # quiet hours
    p.set_play_module(FakePlay(today=0))
    p._state.last_play_ts = 0.0
    assert p._maybe_play({}) is None


def test_play_asleep_blocks(tmp_path):
    p = _planner(tmp_path, enabled=True)
    p._homeostasis_core = FakeHomeo("sleep")  # never wake her to play
    p._time_ctx = TimeContext(now=datetime(2026, 6, 19, 14, 30))
    p.set_play_module(FakePlay(today=0))
    p._state.last_play_ts = 0.0
    assert p._maybe_play({}) is None


def test_play_reduced_blocks(tmp_path):
    # leisure must not add fresh CPU load while degraded (REDUCED sheds load)
    p = _planner(tmp_path, enabled=True)
    p._homeostasis_core = FakeHomeo("reduced")
    p._time_ctx = TimeContext(now=datetime(2026, 6, 19, 14, 30))
    p.set_play_module(FakePlay(today=0))
    p._state.last_play_ts = 0.0
    assert p._maybe_play({}) is None


def test_set_play_enabled_runtime_toggle(tmp_path, monkeypatch):
    monkeypatch.delenv("PLAY_ENABLED", raising=False)
    p = _planner(tmp_path)
    assert p._play_enabled is False
    p.set_play_enabled(True)
    assert p._play_enabled is True
    p.set_play_enabled(False)
    assert p._play_enabled is False


# --------------------------- keep-awake ---------------------------------

def test_play_resets_idle_streak(tmp_path):
    """PLAY counts as activity so it keeps her awake (the deliberate exception
    to the 'thinking in circles -> sleep' rule)."""
    p = _planner(tmp_path, enabled=True)
    p._autonomy_policy = None  # skip K7 for a focused execution test
    homeo = FakeHomeo("active")
    p._homeostasis_core = homeo
    p.set_play_module(FakePlay())

    plan = create_plan(None, "Self-time", ActionType.PLAY, {"trigger": "planner_idle"})
    out = p._finalize_plan(plan)

    assert out.status == PlanStatus.COMPLETED
    assert homeo.activity_calls == 1  # idle streak reset -> stays awake


def test_play_quiet_does_not_keep_awake(tmp_path):
    """A 'quiet' play (no seeds) must NOT hold the sleep timer open -- otherwise
    a seed-dry day could keep her awake forever."""
    p = _planner(tmp_path, enabled=True)
    p._autonomy_policy = None
    homeo = FakeHomeo("active")
    p._homeostasis_core = homeo
    p.set_play_module(FakePlay(kind="quiet"))

    plan = create_plan(None, "Self-time", ActionType.PLAY, {"trigger": "planner_idle"})
    p._finalize_plan(plan)

    assert homeo.activity_calls == 0  # no real musing -> she is allowed to rest


# ------------------- executor dispatch + handler/spec -------------------

def test_executor_dispatches_play(tmp_path):
    ex = ActionExecutor()
    fake = FakePlay()
    ex.set_play_module(fake)
    plan = create_plan(None, "self-time", ActionType.PLAY, {"trigger": "x"})
    res = ex.execute(plan)
    assert res["success"] is True
    assert fake.calls == 1


def test_play_handler_no_module():
    handler = make_play_handler(None)
    plan = create_plan(None, "self-time", ActionType.PLAY, {})
    res = handler(plan)
    assert res["success"] is False


def test_play_handler_runs_via_router():
    fake = FakePlay()
    router = CapabilityRouter()
    router.register("play", make_play_handler(fake), DEFAULT_CAPABILITY_SPECS["play"])
    plan = create_plan(None, "self-time", ActionType.PLAY, {"trigger": "planner_idle"})
    res = router.dispatch(plan)
    assert res["success"] is True
    assert fake.calls == 1


def test_play_is_k7_free():
    # registered in both the K7 classifier and the capability spec, else it
    # would silently fall to RESTRICTED (unknown) and never run in production.
    assert classify_action("play") == ActionClassification.FREE
    assert DEFAULT_CAPABILITY_SPECS["play"].k7_classification == "free"


def test_play_telegram_command(tmp_path):
    """The OBSERVE surface: /play toggles + peeks at her musings."""
    from agent_core.modules.homeostasis_telegram_commands import register_telegram_commands

    class FakeBridge:
        def __init__(self):
            self.handlers = {}

        def register_command(self, command, handler):
            self.handlers[command] = handler

    p = _planner(tmp_path)
    pm = PlayModule(data_dir=str(tmp_path), llm_fn=None,
                    belief_provider=lambda: list(_REAL_BELIEFS))
    ctx = SimpleNamespace(
        maria_conductor=None, self_perception=None, homeostasis_core=None,
        planner_core=p, knowledge_analyzer=None, goal_store=None,
        bulletin_store=None, play_module=pm,
    )
    bridge = FakeBridge()
    register_telegram_commands(bridge, ctx)
    cmd = bridge.handlers["play"]

    assert "OFF" in cmd("")            # default status
    assert "ON" in cmd("on")           # arm
    assert p._play_enabled is True
    pm.play()                          # produce a musing
    assert "musingow" in cmd("")       # status surfaces the journal
    assert "OFF" in cmd("off")         # disable
    assert p._play_enabled is False
