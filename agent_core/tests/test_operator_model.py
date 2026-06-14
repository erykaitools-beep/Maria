"""Tests for OperatorModel (K14) and PrivacyGuard (K14.3)."""

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from agent_core.operator.operator_model import (
    CurrentContext,
    DayRhythm,
    OperatorFact,
    OperatorModel,
    get_operator_model,
    reset_operator_model_singleton,
)
from agent_core.operator.privacy_guard import PrivacyGuard


# ============================================================
# PrivacyGuard tests
# ============================================================


class TestPrivacyGuard:
    def test_empty_allows_all(self):
        guard = PrivacyGuard()
        assert guard.is_allowed("anything") is True
        assert guard.is_allowed("salary info") is True

    def test_add_boundary(self):
        guard = PrivacyGuard()
        assert guard.add_boundary("salary") is True
        assert guard.add_boundary("salary") is False  # duplicate
        assert guard.get_boundaries() == ["salary"]

    def test_remove_boundary(self):
        guard = PrivacyGuard(["salary", "health"])
        assert guard.remove_boundary("salary") is True
        assert guard.remove_boundary("nonexistent") is False
        assert guard.get_boundaries() == ["health"]

    def test_is_allowed_blocks_substring(self):
        guard = PrivacyGuard(["salary"])
        assert guard.is_allowed("my salary is high") is False
        assert guard.is_allowed("SALARY info") is False  # case insensitive
        assert guard.is_allowed("my job is fun") is True

    def test_case_insensitive(self):
        guard = PrivacyGuard()
        guard.add_boundary("Health")
        assert guard.is_allowed("health issues") is False
        assert guard.is_allowed("HEALTH problems") is False

    def test_empty_string_rejected(self):
        guard = PrivacyGuard()
        assert guard.add_boundary("") is False
        assert guard.add_boundary("   ") is False

    def test_long_string_rejected(self):
        guard = PrivacyGuard()
        assert guard.add_boundary("x" * 201) is False
        assert guard.add_boundary("x" * 200) is True

    def test_serialization(self):
        guard = PrivacyGuard(["salary", "health"])
        data = guard.to_list()
        restored = PrivacyGuard.from_list(data)
        assert restored.get_boundaries() == ["salary", "health"]

    def test_is_allowed_empty_text(self):
        guard = PrivacyGuard(["salary"])
        assert guard.is_allowed("") is True  # empty text matches nothing


# ============================================================
# OperatorFact tests
# ============================================================


class TestOperatorFact:
    def test_to_dict(self):
        fact = OperatorFact(value="Eryk", confidence=1.0, source="explicit")
        d = fact.to_dict()
        assert d["value"] == "Eryk"
        assert d["confidence"] == 1.0

    def test_from_dict(self):
        d = {"value": "32", "confidence": 0.8, "source": "inferred"}
        fact = OperatorFact.from_dict(d)
        assert fact.value == "32"
        assert fact.confidence == 0.8

    def test_from_dict_defaults(self):
        fact = OperatorFact.from_dict({})
        assert fact.value == ""
        assert fact.confidence == 1.0


# ============================================================
# DayRhythm tests
# ============================================================


class TestDayRhythm:
    def test_defaults(self):
        r = DayRhythm()
        assert r.typical_wake_hour == 7
        assert r.typical_sleep_hour == 23
        assert r.work_hours == [9, 17]
        assert r.confidence == 0.0

    def test_serialization(self):
        r = DayRhythm(typical_wake_hour=6, confidence=0.8, sample_count=50)
        d = r.to_dict()
        restored = DayRhythm.from_dict(d)
        assert restored.typical_wake_hour == 6
        assert restored.confidence == 0.8
        assert restored.sample_count == 50


# ============================================================
# CurrentContext tests
# ============================================================


class TestCurrentContext:
    def test_inactive_by_default(self):
        ctx = CurrentContext()
        assert ctx.is_active() is False
        assert ctx.get_text() is None

    def test_active_context(self):
        ctx = CurrentContext(
            text="deadline today",
            set_at=time.time(),
            expires_at=time.time() + 3600,
        )
        assert ctx.is_active() is True
        assert ctx.get_text() == "deadline today"

    def test_expired_context(self):
        ctx = CurrentContext(
            text="old context",
            set_at=time.time() - 7200,
            expires_at=time.time() - 3600,
        )
        assert ctx.is_active() is False
        assert ctx.get_text() is None

    def test_serialization(self):
        ctx = CurrentContext(text="test", set_at=1000.0, expires_at=2000.0)
        d = ctx.to_dict()
        restored = CurrentContext.from_dict(d)
        assert restored.text == "test"
        assert restored.set_at == 1000.0


# ============================================================
# OperatorModel core tests
# ============================================================


class TestOperatorModel:
    @pytest.fixture
    def tmp_dir(self, tmp_path):
        return tmp_path

    @pytest.fixture
    def model(self, tmp_dir, monkeypatch):
        # Prevent migration from production user_profile.json
        monkeypatch.setattr(
            "agent_core.operator.operator_model.LEGACY_PROFILE_PATH",
            tmp_dir / "nonexistent_legacy.json",
        )
        path = tmp_dir / "operator_model.json"
        return OperatorModel(path=path)

    def test_create_default(self, model):
        assert model.get_name() == "Operator"
        assert model.get_fact("name") is not None

    def test_set_get_fact(self, model):
        model.set_fact("job", "programmer", 1.0, "explicit")
        fact = model.get_fact("job")
        assert fact is not None
        assert fact.value == "programmer"
        assert fact.confidence == 1.0
        assert fact.source == "explicit"

    def test_get_fact_value(self, model):
        model.set_fact("city", "Berlin", 0.8, "inferred")
        assert model.get_fact_value("city") == "Berlin"
        assert model.get_fact_value("nonexistent", "default") == "default"

    def test_get_all_facts(self, model):
        model.set_fact("job", "dev", 1.0, "test")
        model.set_fact("city", "Berlin", 0.8, "test")
        facts = model.get_all_facts()
        assert "job" in facts
        assert "city" in facts
        assert facts["job"].value == "dev"

    def test_remove_fact(self, model):
        model.set_fact("temp", "value")
        assert model.remove_fact("temp") is True
        assert model.remove_fact("temp") is False
        assert model.get_fact("temp") is None

    def test_confidence_clamped(self, model):
        model.set_fact("x", "val", confidence=5.0)
        assert model.get_fact("x").confidence == 1.0
        model.set_fact("y", "val", confidence=-1.0)
        assert model.get_fact("y").confidence == 0.0

    def test_set_name_shortcut(self, model):
        model.set_name("Eryk")
        assert model.get_name() == "Eryk"

    # -- Preferences --

    def test_preferences(self, model):
        model.set_preference("detail_level", "verbose")
        assert model.get_preference("detail_level") == "verbose"
        assert model.get_preference("nonexistent", "default") == "default"

    def test_get_preferences(self, model):
        prefs = model.get_preferences()
        assert "response_style" in prefs

    # -- Interests --

    def test_add_interest(self, model):
        assert model.add_interest("physics") is True
        assert model.add_interest("physics") is False  # duplicate
        assert "physics" in model.get_interests()

    def test_remove_interest(self, model):
        model.add_interest("chemistry")
        assert model.remove_interest("chemistry") is True
        assert model.remove_interest("chemistry") is False

    def test_interest_privacy_blocked(self, model):
        model.add_boundary("gambling")
        assert model.add_interest("gambling tips") is False

    # -- Day Rhythm --

    def test_rhythm_defaults(self, model):
        r = model.rhythm
        assert r.typical_wake_hour == 7
        assert r.confidence == 0.0

    def test_set_rhythm(self, model):
        new_rhythm = DayRhythm(
            typical_wake_hour=6,
            typical_sleep_hour=22,
            confidence=0.8,
            sample_count=30,
        )
        model.set_rhythm(new_rhythm)
        assert model.rhythm.typical_wake_hour == 6
        assert model.rhythm.confidence == 0.8

    def test_is_likely_active(self, model):
        # This test depends on current time, so just verify it returns bool
        result = model.is_likely_active()
        assert isinstance(result, bool)

    def test_is_likely_working(self, model):
        result = model.is_likely_working()
        assert isinstance(result, bool)

    # -- Current Context --

    def test_set_get_context(self, model):
        model.set_context("deadline today", expires_hours=24)
        assert model.get_context() == "deadline today"

    def test_context_clear(self, model):
        model.set_context("something")
        model.clear_context()
        assert model.get_context() is None

    def test_context_auto_expire(self, model):
        """Context with 0 hours expires immediately."""
        model.set_context("test", expires_hours=0)
        # expires_at = now + 0 = now, so should be expired
        time.sleep(0.01)
        assert model.get_context() is None

    # -- Privacy Boundaries --

    def test_add_remove_boundary(self, model):
        assert model.add_boundary("salary") is True
        assert "salary" in model.get_boundaries()
        assert model.remove_boundary("salary") is True
        assert "salary" not in model.get_boundaries()

    def test_fact_blocked_by_privacy(self, model):
        model.add_boundary("salary")
        model.set_fact("salary", "100k")
        # Fact should NOT be stored
        assert model.get_fact("salary") is None

    def test_fact_value_blocked_by_privacy(self, model):
        model.add_boundary("secret")
        model.set_fact("info", "this is secret data")
        assert model.get_fact("info") is None

    # -- Stats --

    def test_record_interaction(self, model):
        model.record_interaction("telegram")
        stats = model.get_stats()
        assert stats["total_messages"] >= 1

    def test_record_session(self, model):
        model.record_session()
        stats = model.get_stats()
        assert stats["sessions_count"] >= 1

    # -- Persistence --

    def test_persistence(self, tmp_dir):
        path = tmp_dir / "model.json"
        m1 = OperatorModel(path=path)
        m1.set_fact("job", "developer", 1.0, "test")
        m1.add_interest("ai")
        m1.set_context("working")

        # Reload from disk
        m2 = OperatorModel(path=path)
        assert m2.get_fact_value("job") == "developer"
        assert "ai" in m2.get_interests()
        assert m2.get_context() == "working"

    def test_persistence_boundaries(self, tmp_dir):
        path = tmp_dir / "model.json"
        m1 = OperatorModel(path=path)
        m1.add_boundary("health")

        m2 = OperatorModel(path=path)
        assert "health" in m2.get_boundaries()

    # -- Context for Prompt --

    def test_get_context_for_prompt(self, model):
        model.set_name("Eryk")
        model.set_fact("job", "developer")
        model.add_interest("physics")
        prompt = model.get_context_for_prompt()
        assert "Eryk" in prompt
        assert "developer" in prompt
        assert "physics" in prompt

    def test_prompt_includes_context(self, model):
        model.set_context("on vacation")
        prompt = model.get_context_for_prompt()
        assert "vacation" in prompt

    # -- Operator Brief --

    def test_get_operator_brief(self, model):
        model.set_name("Eryk")
        model.set_fact("age", "32")
        model.add_interest("coding")
        brief = model.get_operator_brief()
        assert "Eryk" in brief
        assert "32" in brief
        assert "coding" in brief

    def test_brief_shows_rhythm(self, model):
        model.set_rhythm(DayRhythm(confidence=0.8, sample_count=20))
        brief = model.get_operator_brief()
        assert "80%" in brief

    def test_brief_shows_boundaries(self, model):
        model.add_boundary("health")
        brief = model.get_operator_brief()
        assert "health" in brief

    # -- Full Data --

    def test_get_full_data(self, model):
        data = model.get_full_data()
        assert "durable_facts" in data
        assert "preferences" in data
        assert "day_rhythm" in data

    def test_get_profile_card_shape(self, model):
        # Plank 3 (split-brain #5): OM must serve the flat UserProfile shape the
        # Web UI profile page (profile.js) reads, so the front-end is unchanged
        # when _get_user_profile() switches from UserProfile() to the OM.
        model.set_name("Eryk")
        model.add_interest("spanie")
        model.add_fact("mieszka w Berlinie")
        model.set_preference("response_style", "direct")

        card = model.get_profile_card()
        # Exact top-level shape the front-end indexes into.
        assert set(card.keys()) == {
            "identity", "preferences", "interests", "schedule", "facts", "stats"
        }
        assert card["identity"]["name"] == "Eryk"
        assert "language" in card["identity"]
        assert "timezone" in card["identity"]
        assert "spanie" in card["interests"]
        assert card["preferences"].get("response_style") == "direct"
        assert isinstance(card["schedule"]["notes"], list)
        assert isinstance(card["facts"], list)
        assert isinstance(card["stats"], dict)


# ============================================================
# Learn from message tests
# ============================================================


class TestLearnFromMessage:
    @pytest.fixture
    def model(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agent_core.operator.operator_model.LEGACY_PROFILE_PATH",
            tmp_path / "nonexistent_legacy.json",
        )
        return OperatorModel(path=tmp_path / "model.json")

    def test_learn_name(self, model):
        added = model.learn_from_message("mam na imie Eryk")
        assert added >= 1
        assert model.get_name() == "Eryk"

    def test_learn_name_jestem(self, model):
        model.learn_from_message("jestem Tomek")
        assert model.get_name() == "Tomek"

    def test_skip_maria_as_name(self, model):
        model.learn_from_message("jestem Maria")
        assert model.get_name() != "Maria"

    def test_learn_age(self, model):
        model.learn_from_message("mam 32 lata i pracuje")
        assert model.get_fact_value("age") == "32"

    def test_learn_job(self, model):
        model.learn_from_message("pracuje jako plytkarz w Niemczech")
        assert model.get_fact_value("job") == "plytkarz"

    def test_learn_job_location(self, model):
        model.learn_from_message("pracuje jako plytkarz w Niemczech")
        assert model.get_fact_value("job_location") == "Niemczech"

    def test_learn_city(self, model):
        model.learn_from_message("mieszkam w Berlinie")
        assert model.get_fact_value("city") == "Berlinie"

    def test_learn_interest(self, model):
        model.learn_from_message("interesuje mnie fizyka kwantowa")
        interests = model.get_interests()
        assert any("fizyka" in i for i in interests)

    def test_learn_work_hours(self, model):
        model.learn_from_message("pracuje od 9 do 17")
        assert model.get_fact_value("work_schedule") == "9-17"
        assert model.rhythm.work_hours == [9, 17]

    def test_learn_birthday(self, model):
        model.learn_from_message("moje urodziny to 15 marca")
        assert model.get_fact_value("birthday") == "15 marca"

    def test_privacy_blocks_learning(self, model):
        model.add_boundary("urodziny")
        model.learn_from_message("moje urodziny to 15 marca")
        assert model.get_fact("birthday") is None

    def test_empty_message(self, model):
        assert model.learn_from_message("") == 0
        assert model.learn_from_message("hi") == 0

    def test_multiple_facts(self, model):
        added = model.learn_from_message(
            "mam 32 lata, pracuje jako plytkarz w Niemczech"
        )
        assert added >= 2


# ============================================================
# Migration from UserProfile tests
# ============================================================


class TestMigration:
    def test_migrate_from_user_profile(self, tmp_path):
        """Test migration from legacy user_profile.json format."""
        # Create legacy profile
        legacy = {
            "version": 1,
            "identity": {
                "name": "Eryk",
                "language": "pl",
                "timezone": "Europe/Warsaw",
            },
            "preferences": {
                "response_style": "casual",
                "autonomy_level": "medium",
            },
            "interests": ["programowanie", "fizyka"],
            "schedule": {"notes": ["praca: 9-17"]},
            "facts": [
                "mam 32lata , pracuje obecnie jako plytkarz w Niemczech"
            ],
            "stats": {
                "first_seen": "2026-04-10T17:44:37",
                "last_seen": "2026-04-10T18:16:08",
                "total_messages": 1,
                "sessions_count": 0,
            },
        }

        legacy_path = tmp_path / "user_profile.json"
        legacy_path.write_text(json.dumps(legacy), encoding="utf-8")

        model_path = tmp_path / "operator_model.json"

        # Patch LEGACY_PROFILE_PATH for test
        import agent_core.operator.operator_model as om
        old_legacy = om.LEGACY_PROFILE_PATH
        om.LEGACY_PROFILE_PATH = legacy_path
        try:
            model = OperatorModel(path=model_path)
        finally:
            om.LEGACY_PROFILE_PATH = old_legacy

        # Verify migration
        assert model.get_name() == "Eryk"
        assert model.get_fact_value("language") == "pl"
        assert "programowanie" in model.get_interests()
        assert "fizyka" in model.get_interests()
        assert model.get_fact_value("age") == "32"
        assert model.get_fact_value("job") == "plytkarz"

        # Work hours from schedule notes
        assert model.rhythm.work_hours == [9, 17]

        # Stats preserved
        stats = model.get_stats()
        assert stats["total_messages"] == 1

    def test_no_legacy_creates_default(self, tmp_path, monkeypatch):
        """No legacy file -> clean default."""
        monkeypatch.setattr(
            "agent_core.operator.operator_model.LEGACY_PROFILE_PATH",
            tmp_path / "nonexistent_legacy.json",
        )
        model = OperatorModel(path=tmp_path / "model.json")
        assert model.get_name() == "Operator"

    def test_existing_model_not_migrated(self, tmp_path):
        """If operator_model.json exists, don't re-migrate."""
        model_path = tmp_path / "operator_model.json"
        model_path.write_text(json.dumps({
            "version": 2,
            "durable_facts": {
                "name": {"value": "Custom", "confidence": 1.0, "source": "x", "updated_at": ""},
            },
            "preferences": {},
            "interests": [],
            "day_rhythm": {},
            "current_context": {},
            "privacy_boundaries": [],
            "stats": {},
        }), encoding="utf-8")

        model = OperatorModel(path=model_path)
        assert model.get_name() == "Custom"  # Not overwritten


# ============================================================
# Cross-process reload tests
# ============================================================


class TestCrossProcess:
    def test_reload_on_external_change(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agent_core.operator.operator_model.LEGACY_PROFILE_PATH",
            tmp_path / "nonexistent_legacy.json",
        )
        path = tmp_path / "model.json"
        m1 = OperatorModel(path=path)
        m1.set_fact("job", "dev")

        # Simulate external process modifying the file
        data = json.loads(path.read_text(encoding="utf-8"))
        data["durable_facts"]["job"]["value"] = "manager"
        path.write_text(json.dumps(data), encoding="utf-8")

        # Touch the file to update mtime
        os.utime(path, (time.time() + 1, time.time() + 1))

        # m1 should detect change and reload
        assert m1.get_fact_value("job") == "manager"


class TestSharedSingleton:
    """get_operator_model() must return one process-wide instance so the
    daemon and Web UI share a single source of truth (split-brain fix #5)."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        # Avoid migrating from the real user_profile.json + start clean.
        monkeypatch.setattr(
            "agent_core.operator.operator_model.LEGACY_PROFILE_PATH",
            tmp_path / "nonexistent_legacy.json",
        )
        reset_operator_model_singleton()
        yield
        reset_operator_model_singleton()

    def test_returns_same_instance(self, tmp_path):
        a = get_operator_model(path=tmp_path / "om.json")
        b = get_operator_model()  # path ignored after first creation
        assert a is b

    def test_mutation_is_shared(self, tmp_path):
        a = get_operator_model(path=tmp_path / "om.json")
        b = get_operator_model()
        a.set_fact("city", "Berlin")
        # b is the same object -> sees the fact without any file reload
        assert b.get_fact_value("city") == "Berlin"

    def test_reset_creates_new_instance(self, tmp_path):
        a = get_operator_model(path=tmp_path / "om.json")
        reset_operator_model_singleton()
        c = get_operator_model(path=tmp_path / "om.json")
        assert c is not a


class TestScheduleNotes:
    """E2 regression: schedule notes must accumulate as a capped list, not
    overwrite each other. The b890e7b UI rewire collapsed every note onto a
    single durable fact 'schedule_note', silently discarding all but the most
    recent note."""

    @pytest.fixture
    def model(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agent_core.operator.operator_model.LEGACY_PROFILE_PATH",
            tmp_path / "nonexistent_legacy.json",
        )
        return OperatorModel(path=tmp_path / "operator_model.json")

    def test_notes_accumulate(self, model):
        model.add_schedule_note("pracuje 9-17")
        model.add_schedule_note("piatek wolny")
        assert model.get_schedule_notes() == ["pracuje 9-17", "piatek wolny"]

    def test_notes_dedup(self, model):
        model.add_schedule_note("pracuje 9-17")
        model.add_schedule_note("pracuje 9-17")
        assert model.get_schedule_notes() == ["pracuje 9-17"]

    def test_notes_capped_at_30(self, model):
        for i in range(35):
            model.add_schedule_note(f"note {i}")
        notes = model.get_schedule_notes()
        assert len(notes) == 30
        assert notes[-1] == "note 34"  # newest kept
        assert "note 0" not in notes   # oldest dropped

    def test_remove_note(self, model):
        model.add_schedule_note("a")
        model.add_schedule_note("b")
        assert model.remove_schedule_note("a") is True
        assert model.remove_schedule_note("missing") is False
        assert model.get_schedule_notes() == ["b"]

    def test_persists_as_list(self, model):
        model.add_schedule_note("x")
        model.add_schedule_note("y")
        disk = json.loads(Path(model._path).read_text(encoding="utf-8"))
        assert disk["schedule_notes"] == ["x", "y"]

    def test_legacy_single_fact_migrates(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agent_core.operator.operator_model.LEGACY_PROFILE_PATH",
            tmp_path / "nonexistent_legacy.json",
        )
        path = tmp_path / "operator_model.json"
        path.write_text(json.dumps({
            "version": 2,
            "durable_facts": {
                "name": {"value": "Eryk", "confidence": 1.0,
                         "source": "x", "updated_at": ""},
                "schedule_note": {"value": "pracuje 7-16", "confidence": 0.8,
                                  "source": "explicit:schedule", "updated_at": ""},
            },
            "preferences": {}, "interests": [], "stats": {},
        }), encoding="utf-8")
        m = OperatorModel(path=path)
        assert m.get_schedule_notes() == ["pracuje 7-16"]
        assert m.get_fact("schedule_note") is None  # legacy fact consumed


class TestConcurrency:
    """E1 regression: readers must not crash or tear when writers mutate the
    shared model concurrently (one singleton shared by daemon + Flask +
    Telegram threads). Before the RLock + locked-reload fix this raised
    'dictionary changed size during iteration'."""

    def test_concurrent_read_write_no_crash(self, tmp_path, monkeypatch):
        import threading

        monkeypatch.setattr(
            "agent_core.operator.operator_model.LEGACY_PROFILE_PATH",
            tmp_path / "nonexistent_legacy.json",
        )
        om = OperatorModel(path=tmp_path / "operator_model.json")
        errors = []
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    om.get_all_facts()
                    om.get_interests()
                    om.get_preferences()
                    om.get_full_data()
                except Exception as e:  # noqa: BLE001
                    errors.append(repr(e))
                    return

        def writer(n):
            i = 0
            while not stop.is_set():
                try:
                    om.set_fact(f"k{n}_{i % 5}", str(i), 1.0, "t")
                    om.add_interest(f"i{n}_{i % 7}")
                    om.remove_interest(f"i{n}_{(i + 2) % 7}")
                    i += 1
                except Exception as e:  # noqa: BLE001
                    errors.append(repr(e))
                    return

        threads = [threading.Thread(target=reader) for _ in range(4)] + \
                  [threading.Thread(target=writer, args=(n,)) for n in range(3)]
        for t in threads:
            t.start()
        time.sleep(0.5)
        stop.set()
        for t in threads:
            t.join(timeout=5)
        assert not errors, errors[:3]
