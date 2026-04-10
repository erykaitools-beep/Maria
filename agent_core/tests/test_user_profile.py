"""
Tests for UserProfile - operator knowledge persistence.

Tests: identity, preferences, interests, schedule, facts,
       auto-learning from messages, context for prompt.
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from agent_core.consciousness.user_profile import UserProfile


@pytest.fixture
def profile(tmp_path):
    """Fresh UserProfile with temp storage."""
    return UserProfile(path=tmp_path / "user_profile.json")


@pytest.fixture
def loaded_profile(tmp_path):
    """UserProfile with pre-loaded data."""
    p = UserProfile(path=tmp_path / "user_profile.json")
    p.set_name("Eryk")
    p.add_interest("fizyka")
    p.add_interest("programowanie")
    p.add_fact("mieszka w Niemczech")
    p.add_schedule_note("praca: 9-17")
    return p


class TestIdentity:
    def test_default_name(self, profile):
        assert profile.get_name() == "Eryk"

    def test_set_name(self, profile):
        profile.set_name("Jan")
        assert profile.get_name() == "Jan"

    def test_name_trimmed(self, profile):
        profile.set_name("  Anna  ")
        assert profile.get_name() == "Anna"

    def test_name_max_length(self, profile):
        profile.set_name("x" * 100)
        assert len(profile.get_name()) == 50

    def test_default_language(self, profile):
        assert profile.get_language() == "pl"

    def test_default_timezone(self, profile):
        assert profile.get_timezone() == "Europe/Warsaw"


class TestPreferences:
    def test_get_default_style(self, profile):
        assert profile.get_preference("response_style") == "casual"

    def test_set_preference(self, profile):
        profile.set_preference("response_style", "formal")
        assert profile.get_preference("response_style") == "formal"

    def test_get_unknown_preference(self, profile):
        assert profile.get_preference("nonexistent") is None
        assert profile.get_preference("nonexistent", "default") == "default"

    def test_get_all_preferences(self, profile):
        prefs = profile.get_preferences()
        assert "response_style" in prefs
        assert "autonomy_level" in prefs


class TestInterests:
    def test_add_interest(self, profile):
        assert profile.add_interest("fizyka") is True
        assert "fizyka" in profile.get_interests()

    def test_add_duplicate(self, profile):
        profile.add_interest("fizyka")
        assert profile.add_interest("fizyka") is False
        assert profile.get_interests().count("fizyka") == 1

    def test_case_insensitive_dedup(self, profile):
        profile.add_interest("Fizyka")
        assert profile.add_interest("fizyka") is False

    def test_remove_interest(self, profile):
        profile.add_interest("fizyka")
        assert profile.remove_interest("fizyka") is True
        assert "fizyka" not in profile.get_interests()

    def test_remove_nonexistent(self, profile):
        assert profile.remove_interest("nieistniejace") is False

    def test_empty_interest_rejected(self, profile):
        assert profile.add_interest("") is False
        assert profile.add_interest("  ") is False

    def test_long_interest_rejected(self, profile):
        assert profile.add_interest("x" * 101) is False

    def test_cap_50(self, profile):
        for i in range(55):
            profile.add_interest(f"topic_{i}")
        assert len(profile.get_interests()) == 50


class TestSchedule:
    def test_add_note(self, profile):
        profile.add_schedule_note("praca: 9-17")
        assert "praca: 9-17" in profile.get_schedule_notes()

    def test_dedup_note(self, profile):
        profile.add_schedule_note("praca: 9-17")
        profile.add_schedule_note("praca: 9-17")
        assert profile.get_schedule_notes().count("praca: 9-17") == 1

    def test_remove_note(self, profile):
        profile.add_schedule_note("praca: 9-17")
        assert profile.remove_schedule_note("praca: 9-17") is True
        assert "praca: 9-17" not in profile.get_schedule_notes()

    def test_empty_note_rejected(self, profile):
        profile.add_schedule_note("")
        assert len(profile.get_schedule_notes()) == 0

    def test_cap_30(self, profile):
        for i in range(35):
            profile.add_schedule_note(f"note_{i}")
        assert len(profile.get_schedule_notes()) == 30


class TestFacts:
    def test_add_fact(self, profile):
        assert profile.add_fact("mieszka w Berlinie") is True
        assert "mieszka w Berlinie" in profile.get_facts()

    def test_dedup_fact(self, profile):
        profile.add_fact("lubi koty")
        assert profile.add_fact("lubi koty") is False

    def test_case_insensitive_dedup(self, profile):
        profile.add_fact("Lubi Koty")
        assert profile.add_fact("lubi koty") is False

    def test_remove_fact(self, profile):
        profile.add_fact("lubi koty")
        assert profile.remove_fact("lubi koty") is True
        assert len(profile.get_facts()) == 0

    def test_empty_fact_rejected(self, profile):
        assert profile.add_fact("") is False

    def test_cap_100(self, profile):
        for i in range(105):
            profile.add_fact(f"fact_{i}")
        assert len(profile.get_facts()) == 100


class TestAutoLearnFromMessage:
    def test_learn_interest(self, profile):
        profile.learn_from_message("interesuje mnie fizyka kwantowa")
        assert "fizyka kwantowa" in profile.get_interests()

    def test_learn_hobby(self, profile):
        profile.learn_from_message("moje hobby to modelarstwo")
        assert "modelarstwo" in profile.get_interests()

    def test_learn_location(self, profile):
        profile.learn_from_message("mieszkam w Berlinie")
        facts = profile.get_facts()
        assert any("berlin" in f.lower() for f in facts)

    def test_learn_birthday(self, profile):
        profile.learn_from_message("moje urodziny to 15 marca")
        facts = profile.get_facts()
        assert any("urodziny" in f.lower() for f in facts)

    def test_learn_name(self, profile):
        profile.learn_from_message("mam na imie Tomek")
        assert profile.get_name() == "Tomek"

    def test_ignore_short_message(self, profile):
        result = profile.learn_from_message("ok")
        assert result == 0

    def test_no_false_name_maria(self, profile):
        profile.learn_from_message("jestem Maria")
        # Should not change name to Maria (that's the bot)
        assert profile.get_name() == "Eryk"

    def test_learn_work_schedule(self, profile):
        profile.learn_from_message("pracuje od 9 do 17")
        notes = profile.get_schedule_notes()
        assert len(notes) >= 1
        assert any("9" in n for n in notes)


class TestLearnFromUserFacts:
    def test_structured_operator(self, profile):
        profile.learn_from_user_facts(["operator: Jan"])
        assert profile.get_name() == "Jan"

    def test_structured_interest(self, profile):
        profile.learn_from_user_facts(["zainteresowanie: AI"])
        assert "ai" in [i.lower() for i in profile.get_interests()]

    def test_free_form_fact(self, profile):
        added = profile.learn_from_user_facts(["lubi programowac w Python"])
        assert added == 1
        assert "lubi programowac w Python" in profile.get_facts()

    def test_mixed_facts(self, profile):
        profile.learn_from_user_facts([
            "operator: Eryk",
            "interesuje sie kosmosem",
            "",  # empty - should skip
        ])
        assert profile.get_name() == "Eryk"
        assert "interesuje sie kosmosem" in profile.get_facts()

    def test_dedup_on_ingest(self, profile):
        profile.learn_from_user_facts(["fakt testowy"])
        added = profile.learn_from_user_facts(["fakt testowy"])
        assert added == 0


class TestContextForPrompt:
    def test_basic_context(self, profile):
        ctx = profile.get_context_for_prompt()
        assert "[Profil uzytkownika]" in ctx
        assert "Eryk" in ctx

    def test_with_interests(self, loaded_profile):
        ctx = loaded_profile.get_context_for_prompt()
        assert "fizyka" in ctx
        assert "programowanie" in ctx

    def test_with_schedule(self, loaded_profile):
        ctx = loaded_profile.get_context_for_prompt()
        assert "9-17" in ctx

    def test_with_facts(self, loaded_profile):
        ctx = loaded_profile.get_context_for_prompt()
        assert "Niemczech" in ctx


class TestPersistence:
    def test_save_and_load(self, tmp_path):
        path = tmp_path / "test_profile.json"
        p1 = UserProfile(path=path)
        p1.set_name("Tomek")
        p1.add_interest("muzyka")
        p1.add_fact("gra na gitarze")

        # Load fresh instance
        p2 = UserProfile(path=path)
        assert p2.get_name() == "Tomek"
        assert "muzyka" in p2.get_interests()
        assert "gra na gitarze" in p2.get_facts()

    def test_atomic_write(self, tmp_path):
        path = tmp_path / "test_profile.json"
        p = UserProfile(path=path)
        p.add_interest("test")
        # No .tmp file should remain
        assert not (path.with_suffix(".tmp")).exists()

    def test_schema_migration(self, tmp_path):
        """Old profile without new fields should get defaults."""
        path = tmp_path / "old_profile.json"
        old_data = {"identity": {"name": "StareProfil"}}
        with open(path, "w") as f:
            json.dump(old_data, f)

        p = UserProfile(path=path)
        assert p.get_name() == "StareProfil"
        assert p.get_language() == "pl"  # default filled in
        assert isinstance(p.get_interests(), list)


class TestStats:
    def test_record_interaction(self, profile):
        profile.record_interaction("telegram")
        stats = profile.get_stats()
        assert stats["total_messages"] == 1

    def test_record_session(self, profile):
        profile.record_session()
        stats = profile.get_stats()
        assert stats["sessions_count"] == 1

    def test_channel_tracking(self, profile):
        profile.record_channel_use("telegram")
        assert "telegram" in profile.get_active_channels()

    def test_invalid_channel_ignored(self, profile):
        profile.record_channel_use("smoke_signal")
        channels = profile.get_active_channels()
        assert "smoke_signal" not in channels


class TestSummary:
    def test_summary_includes_name(self, profile):
        s = profile.get_summary()
        assert "Eryk" in s

    def test_summary_with_data(self, loaded_profile):
        s = loaded_profile.get_summary()
        assert "fizyka" in s
        assert "9-17" in s
        assert "Niemczech" in s


class TestCrossProcessReload:
    """Test that changes from one instance are visible in another."""

    def test_reload_on_context(self, tmp_path):
        import os, time
        path = tmp_path / "shared.json"
        p1 = UserProfile(path=path)
        p2 = UserProfile(path=path)
        # Force mtime difference so reload triggers
        p2._last_mtime = 0

        p1.add_interest("nowy temat")
        ctx = p2.get_context_for_prompt()
        assert "nowy temat" in ctx

    def test_reload_on_full_profile(self, tmp_path):
        path = tmp_path / "shared.json"
        p1 = UserProfile(path=path)
        p2 = UserProfile(path=path)
        p2._last_mtime = 0

        p1.add_fact("testowy fakt")
        fp = p2.get_full_profile()
        assert "testowy fakt" in fp.get("facts", [])

    def test_reload_on_summary(self, tmp_path):
        path = tmp_path / "shared.json"
        p1 = UserProfile(path=path)
        p2 = UserProfile(path=path)
        p2._last_mtime = 0

        p1.add_schedule_note("praca: 8-16")
        s = p2.get_summary()
        assert "8-16" in s


class TestFullProfile:
    def test_returns_dict(self, profile):
        fp = profile.get_full_profile()
        assert isinstance(fp, dict)
        assert "identity" in fp
        assert "preferences" in fp
        assert "interests" in fp
        assert "facts" in fp

    def test_is_copy(self, profile):
        """Returned dict should be a copy, not a reference."""
        fp = profile.get_full_profile()
        fp["identity"]["name"] = "HACKED"
        assert profile.get_name() == "Eryk"
