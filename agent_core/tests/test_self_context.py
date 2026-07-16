"""Tests for Super-META E0 SelfContext aggregator (read-only situational picture)."""

import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from agent_core.awareness.self_context import SelfContext


# ---------------------------------------------------------------------------
# Fake organs (mirror the SimpleNamespace + Fake* convention of self_perception)
# ---------------------------------------------------------------------------

class FakeOperatorModel:
    def __init__(self, name="Eryk", raise_brief=False):
        self._name = name
        self._raise_brief = raise_brief

    def get_name(self):
        return self._name

    def get_context_for_prompt(self):
        if self._raise_brief:
            raise RuntimeError("operator model boom")
        return f"[Profil operatora] Operator: {self._name}. Styl: casual."


class FakeSelfPerception:
    def __init__(self, snapshot=None):
        self._snapshot = snapshot

    def get_latest(self):
        return self._snapshot


class FakeContextBuilder:
    def __init__(self, text="[Swiadomosc: Mam 5 plikow do nauki.]"):
        self._text = text
        self.calls = 0

    def build(self):
        self.calls += 1
        return self._text


def _goal(type_name, desc, priority, is_active=True, id=None):
    return SimpleNamespace(
        id=id or f"goal-{type_name.lower()}",
        type=SimpleNamespace(name=type_name),
        description=desc,
        priority=priority,
        is_active=is_active,
    )


class FakeGoalStore:
    def __init__(self, goals=None, meta=None):
        self._goals = goals or []
        self._meta = meta

    def get(self, goal_id):
        return self._meta if goal_id == "goal-meta-learn" else None

    def get_active(self):
        return [g for g in self._goals if getattr(g, "is_active", False)]


class FakeVisionMemory:
    def __init__(self, latest=None):
        self._latest = latest

    def latest(self):
        return self._latest


def _snapshot():
    return {
        "mode": "ACTIVE",
        "mode_label": "aktywna",
        "timestamp": time.time(),
        "capabilities": {"total": 12, "free": 7, "guarded": 3, "restricted": 2},
        "external_services": [
            {"name": "NIM API", "status": "available"},
            {"name": "Ollama", "status": "available"},
            {"name": "OpenClaw", "status": "unavailable"},
        ],
        "limitations": {"by_severity": {"critical": 1, "warning": 2, "info": 4}},
    }


def _full_ctx():
    meta = _goal("META", "Autonomiczna nauka", 1.0)
    return SimpleNamespace(
        operator_model=FakeOperatorModel(),
        self_perception=FakeSelfPerception(_snapshot()),
        context_builder=FakeContextBuilder(),
        goal_store=FakeGoalStore(
            goals=[
                meta,
                _goal("MAINTENANCE", "Utrzymaj health", 0.95),
                _goal("LEARNING", "Naucz sie pythona", 0.8),
            ],
            meta=meta,
        ),
        vision_memory=FakeVisionMemory(
            {"description": "Kot na parapecie.", "timestamp": time.time(), "iso": "2026"},
        ),
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_build_merges_all_four_sources():
    sc = SelfContext(_full_ctx())
    picture = sc.build()

    assert picture["who"]["name"] == "Eryk"
    assert "Operator: Eryk" in picture["who"]["brief"]

    st = picture["self"]
    assert st["mode_label"] == "aktywna"
    assert st["capabilities_total"] == 12
    assert st["free"] == 7
    assert st["services"] == "2/3"  # 2 of 3 available
    assert st["limitations_critical"] == 1
    assert isinstance(st["snapshot_age_s"], float)

    assert picture["knowledge"] == "[Swiadomosc: Mam 5 plikow do nauki.]"

    mission = picture["mission"]
    assert mission["meta_active"] is True
    assert mission["active_goals"] == 3


def test_top_goal_excludes_perpetual_scaffolding():
    """Top goal = current real focus, never META/MAINTENANCE scaffolding."""
    sc = SelfContext(_full_ctx())
    mission = sc.build()["mission"]
    # META (1.0) and MAINTENANCE (0.95) outrank LEARNING (0.8) by priority,
    # but they are scaffolding -> the real focus is the LEARNING goal.
    assert mission["top_goal"] == "Naucz sie pythona"
    assert mission["active_work_goals"] == 1


def test_format_for_telegram_contains_key_facts():
    sc = SelfContext(_full_ctx())
    text = sc.format_for_telegram()
    assert "Kto: Eryk" in text
    assert "aktywna" in text
    assert "Misja META: aktywna" in text
    assert "Naucz sie pythona" in text
    assert "Mam 5 plikow" in text
    assert "Wzrok" in text
    assert "Kot na parapecie." in text


# ---------------------------------------------------------------------------
# format_for_chat (Super-META E2: chat-tail situational self)
# ---------------------------------------------------------------------------

def test_format_for_chat_contains_situational_self():
    text = SelfContext(_full_ctx()).format_for_chat()
    assert text.startswith("[Twoja sytuacja]")
    assert "Eryk" in text                      # who she is talking to
    assert "Kot na parapecie." in text         # what she last saw (the new bit)
    assert "tryb aktywna" in text              # current mode
    assert "Naucz sie pythona" in text         # current focus (not scaffolding)


def test_format_for_chat_vision_shows_age():
    ctx = _full_ctx()
    ctx.vision_memory = FakeVisionMemory(
        {"description": "Osoba przy biurku.", "timestamp": time.time() - 300, "iso": "2026"}
    )
    text = SelfContext(ctx).format_for_chat()
    assert "Ostatnio widzialas (5 min temu): Osoba przy biurku." in text


def test_format_for_chat_empty_when_nothing_known():
    blank = SimpleNamespace(
        operator_model=None, self_perception=None,
        context_builder=None, goal_store=None, vision_memory=None,
    )
    assert SelfContext(blank).format_for_chat() == ""


def test_format_for_chat_omits_vision_when_none_seen():
    ctx = _full_ctx()
    ctx.vision_memory = FakeVisionMemory(None)  # nothing seen yet
    text = SelfContext(ctx).format_for_chat()
    assert "Eryk" in text
    assert "Ostatnio widzialas" not in text


def test_humanize_age_buckets():
    h = SelfContext._humanize_age
    assert h(None) == ""
    assert h(-5) == ""
    assert h(45) == " (45s temu)"
    assert h(300) == " (5 min temu)"
    assert h(7200) == " (2h temu)"


# ---------------------------------------------------------------------------
# Vision slot (E1)
# ---------------------------------------------------------------------------

def test_vision_slot_present_in_picture():
    v = SelfContext(_full_ctx()).build()["vision"]
    assert v["latest"] == "Kot na parapecie."
    assert isinstance(v["age_s"], float)


def test_vision_absent_when_no_memory():
    ctx = _full_ctx()
    ctx.vision_memory = None
    assert SelfContext(ctx).build()["vision"] == {}


def test_vision_nothing_seen_yet():
    ctx = _full_ctx()
    ctx.vision_memory = FakeVisionMemory(latest=None)
    assert SelfContext(ctx).build()["vision"] == {"latest": None}


# ---------------------------------------------------------------------------
# Defensive degradation
# ---------------------------------------------------------------------------

def test_missing_organs_degrade_to_empty_slots():
    ctx = SimpleNamespace(
        operator_model=None,
        self_perception=None,
        goal_store=None,
        context_builder=FakeContextBuilder(text=""),
    )
    picture = SelfContext(ctx).build()
    assert picture["who"] == {}
    assert picture["self"] == {}
    assert picture["mission"] == {}
    assert picture["knowledge"] == ""
    # format never crashes even with empty slots
    assert "Kto: nieznany" in SelfContext(ctx).format_for_telegram()


def test_organ_exception_is_isolated():
    """A raising organ degrades its own slot; other slots stay intact."""
    ctx = _full_ctx()
    ctx.operator_model = FakeOperatorModel(raise_brief=True)
    picture = SelfContext(ctx).build()
    # _who catches the brief failure and returns {} -> rest unaffected
    assert picture["who"] == {}
    assert picture["self"]["mode_label"] == "aktywna"
    assert picture["mission"]["meta_active"] is True


def test_snapshot_absent_marks_no_snapshot():
    ctx = _full_ctx()
    ctx.self_perception = FakeSelfPerception(snapshot=None)
    st = SelfContext(ctx).build()["self"]
    assert st["snapshot_age_s"] is None


def test_meta_goal_missing_reports_inactive():
    ctx = _full_ctx()
    ctx.goal_store = FakeGoalStore(goals=[_goal("LEARNING", "x", 0.8)], meta=None)
    mission = SelfContext(ctx).build()["mission"]
    assert mission["meta_active"] is False
    assert mission["top_goal"] == "x"


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def test_cache_avoids_rebuild_then_invalidate_forces_it():
    ctx = _full_ctx()
    cb = ctx.context_builder
    sc = SelfContext(ctx)

    sc.build()
    assert cb.calls == 1
    sc.build()  # within TTL -> served from cache, organs not re-read
    assert cb.calls == 1

    sc.invalidate()
    sc.build()  # forced rebuild
    assert cb.calls == 2


def test_force_rebuild_bypasses_cache():
    ctx = _full_ctx()
    cb = ctx.context_builder
    sc = SelfContext(ctx)
    sc.build()
    sc.build(force=True)
    assert cb.calls == 2


# ---------------------------------------------------------------------------
# E3: cross-organ operator-presence API
# ---------------------------------------------------------------------------

class FakeOperatorModelStats(FakeOperatorModel):
    """Operator model that also exposes get_stats() with a last_seen (E3)."""

    def __init__(self, last_seen=None, **kw):
        super().__init__(**kw)
        self._last_seen = last_seen

    def get_stats(self):
        return {"last_seen": self._last_seen} if self._last_seen is not None else {}


def _ctx_present(last_seen):
    return SimpleNamespace(operator_model=FakeOperatorModelStats(last_seen=last_seen))


def test_seconds_since_operator_seen_recent():
    sc = SelfContext(_ctx_present(datetime.now().isoformat()))
    secs = sc.seconds_since_operator_seen()
    assert secs is not None
    assert 0 <= secs < 5  # local-TZ round-trip, no 2h offset bug


def test_seconds_since_operator_seen_none_when_unknown():
    # no get_stats at all
    assert SelfContext(SimpleNamespace(operator_model=FakeOperatorModel())).seconds_since_operator_seen() is None
    # get_stats present but empty last_seen
    assert SelfContext(_ctx_present(None)).seconds_since_operator_seen() is None
    # no operator_model
    assert SelfContext(SimpleNamespace()).seconds_since_operator_seen() is None
    # unparseable timestamp
    assert SelfContext(_ctx_present("not-a-timestamp")).seconds_since_operator_seen() is None


def test_operator_active_recently_true_when_just_seen():
    sc = SelfContext(_ctx_present(datetime.now().isoformat()))
    assert sc.operator_active_recently() is True
    assert sc.operator_active_recently(window_s=10) is True


def test_operator_active_recently_false_when_old():
    sc = SelfContext(_ctx_present((datetime.now() - timedelta(minutes=30)).isoformat()))
    assert sc.operator_active_recently() is False            # default 300s window
    assert sc.operator_active_recently(window_s=3600) is True  # wider window catches it


def test_operator_active_recently_fails_open_when_unknown():
    # Unknown presence MUST read as ABSENT (False) so vision is never silenced
    # by a cold/blank/corrupt profile.
    assert SelfContext(SimpleNamespace()).operator_active_recently() is False
    assert SelfContext(_ctx_present(None)).operator_active_recently() is False
    assert SelfContext(_ctx_present("garbage")).operator_active_recently() is False


def test_who_slot_carries_last_seen_age():
    ctx = _full_ctx()
    ctx.operator_model = FakeOperatorModelStats(last_seen=datetime.now().isoformat())
    who = SelfContext(ctx).build()["who"]
    assert who["name"] == "Eryk"
    assert isinstance(who["last_seen_age_s"], float)
    assert who["last_seen_age_s"] < 5


def test_telegram_view_shows_operator_activity():
    ctx = _full_ctx()
    ctx.operator_model = FakeOperatorModelStats(last_seen=datetime.now().isoformat())
    text = SelfContext(ctx).format_for_telegram()
    assert "Kto: Eryk" in text
    assert "aktywny" in text


# ---------------------------------------------------------------------------
# E3 rung2: planner publishes live focus; _mission prefers it over the heuristic
# ---------------------------------------------------------------------------

def test_mission_no_focus_uses_heuristic():
    m = SelfContext(_full_ctx()).build()["mission"]
    assert m["top_goal"] == "Naucz sie pythona"   # highest-priority non-scaffold
    assert m["focus_source"] == "heuristic"
    assert m["current_action"] is None


def test_mission_prefers_published_focus_over_heuristic():
    # Two active work goals; heuristic would pick the higher-priority one.
    g_top = _goal("LEARNING", "Naucz sie pythona", 0.8, id="g-py")
    g_other = _goal("LEARNING", "Zbadaj rynek", 0.5, id="g-rynek")
    ctx = SimpleNamespace(goal_store=FakeGoalStore(goals=[g_top, g_other]))
    sc = SelfContext(ctx, context_builder=FakeContextBuilder())
    assert sc.build()["mission"]["top_goal"] == "Naucz sie pythona"   # heuristic baseline
    # planner publishes the OTHER (still-active) goal as its live focus
    sc.set_active_focus(goal_id="g-rynek", description="Zbadaj rynek", action="fetch")
    sc.invalidate()  # bust the 45s cache so the new focus is read (real display lag)
    m = sc.build()["mission"]
    assert m["top_goal"] == "Zbadaj rynek"
    assert m["current_action"] == "fetch"
    assert m["focus_source"] == "planner"


def test_mission_ignores_focus_for_inactive_goal():
    # Planner published a focus, then the goal finished (no longer in active set).
    # Liveness gate must drop the stale focus and fall back to the heuristic.
    g = _goal("LEARNING", "Naucz sie pythona", 0.8, id="g-py")
    ctx = SimpleNamespace(goal_store=FakeGoalStore(goals=[g]))
    sc = SelfContext(ctx, context_builder=FakeContextBuilder())
    sc.set_active_focus(goal_id="g-DONE", description="Stary skonczony cel", action="learn")
    m = sc.build()["mission"]
    assert m["top_goal"] == "Naucz sie pythona"   # liveness gate -> heuristic
    assert m["focus_source"] == "heuristic"


def test_mission_falls_back_when_focus_stale():
    sc = SelfContext(_full_ctx())
    sc.set_active_focus(
        goal_id="g", description="Stary cel", action="LEARN",
        ts=time.time() - (SelfContext.ACTIVE_FOCUS_TTL + 10),
    )
    m = sc.build()["mission"]
    assert m["top_goal"] == "Naucz sie pythona"   # focus too old -> heuristic
    assert m["focus_source"] == "heuristic"


def test_active_focus_ttl_boundary():
    sc = SelfContext(SimpleNamespace())
    assert sc._active_focus() is None                       # nothing published
    sc.set_active_focus(description="x", ts=time.time())
    assert sc._active_focus() is not None                   # fresh
    sc.set_active_focus(description="x", ts=time.time() - 99999)
    assert sc._active_focus() is None                       # expired


def test_telegram_view_shows_planner_focus_marker():
    # goal-learning is an active goal in _full_ctx, so the liveness gate trusts it.
    sc = SelfContext(_full_ctx())
    sc.set_active_focus(goal_id="goal-learning", description="Zbadaj rynek", action="fetch")
    text = sc.format_for_telegram()
    assert "Glowny cel: Zbadaj rynek" in text
    assert "[planista: fetch]" in text
