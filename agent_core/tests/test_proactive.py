"""
Tests for Proactive Contact Module.

Tests cover:
- ProactiveModel: dataclasses, enums, state persistence
- ContentGenerators: message generation from system data
- ProactiveScheduler: tick-based scheduling, cooldowns, quiet hours
- Integration: event triggering, operator contact tracking
"""

import json
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_core.evaluation.report import create_report
from agent_core.proactive.proactive_model import (
    CONTACT_COOLDOWNS,
    CONTACT_WINDOWS,
    ContactReason,
    ProactiveContact,
    ProactiveState,
)
from agent_core.proactive.generators import ContentGenerators
from agent_core.proactive.scheduler import (
    CHECK_INTERVAL_TICKS,
    ProactiveScheduler,
)


def _make_mock_dt(year=2026, month=4, day=11, hour=10, minute=0, weekday=4):
    """Create a MagicMock that behaves like datetime for scheduler patching."""
    mock_now = MagicMock()
    mock_now.hour = hour
    mock_now.weekday.return_value = weekday
    mock_now.strftime.side_effect = lambda fmt: datetime(year, month, day, hour, minute).strftime(fmt)
    mock_dt = MagicMock()
    mock_dt.now.return_value = mock_now
    return mock_dt


@pytest.fixture(autouse=True)
def _isolate_proactive_files(tmp_path, monkeypatch):
    """Redirect proactive state/history defaults to tmp for every test.

    Regression guard: a goal_achieved integration test built a scheduler
    without overriding _history_path, leaking 152 fake rows into the live
    meta_data/proactive_contacts.jsonl (which also seeds the RhythmDetector).
    Patching the module defaults before each test body means an
    inline-constructed scheduler can never touch live runtime files.
    """
    import agent_core.proactive.scheduler as _sched

    monkeypatch.setattr(_sched, "_STATE_FILE", tmp_path / "proactive_state.json")
    monkeypatch.setattr(_sched, "_HISTORY_FILE", tmp_path / "proactive_contacts.jsonl")


# ============================================================
# ProactiveModel tests
# ============================================================

class TestContactReason:
    def test_all_reasons_defined(self):
        assert len(ContactReason) == 9  # +OPERATOR_QUESTION (K14.1), +HYDRATION_NUDGE
        assert ContactReason.OPERATOR_QUESTION.value == "operator_question"
        assert ContactReason.HYDRATION_NUDGE.value == "hydration_nudge"

    def test_reason_values(self):
        assert ContactReason.MORNING_SUMMARY.value == "morning_summary"
        assert ContactReason.EVENING_RECAP.value == "evening_recap"
        assert ContactReason.WEEKLY_REVIEW.value == "weekly_review"
        assert ContactReason.GOAL_ACHIEVED.value == "goal_achieved"
        assert ContactReason.GOAL_PROPOSED.value == "goal_proposed"
        assert ContactReason.LEARNING_MILESTONE.value == "learning_milestone"
        assert ContactReason.IDLE_CHECKIN.value == "idle_checkin"
        assert ContactReason.HYDRATION_NUDGE.value == "hydration_nudge"

    def test_all_reasons_have_cooldowns(self):
        for reason in ContactReason:
            assert reason.value in CONTACT_COOLDOWNS

    def test_all_reasons_have_windows(self):
        for reason in ContactReason:
            assert reason.value in CONTACT_WINDOWS


class TestProactiveContact:
    def test_create(self):
        contact = ProactiveContact(
            reason=ContactReason.MORNING_SUMMARY,
            message="Dzien dobry!",
        )
        assert contact.reason == ContactReason.MORNING_SUMMARY
        assert contact.message == "Dzien dobry!"
        assert contact.timestamp > 0
        assert contact.metadata == {}

    def test_to_dict(self):
        contact = ProactiveContact(
            reason=ContactReason.GOAL_ACHIEVED,
            message="Cel osiagniety!",
            metadata={"count": 3},
        )
        d = contact.to_dict()
        assert d["reason"] == "goal_achieved"
        assert d["message"] == "Cel osiagniety!"
        assert d["metadata"]["count"] == 3
        assert "timestamp" in d


class TestProactiveState:
    def test_default(self):
        state = ProactiveState()
        assert state.enabled is True
        assert state.contacts_today == 0
        assert state.max_contacts_per_day == 8
        assert state.last_sent == {}

    def test_roundtrip(self):
        state = ProactiveState(
            enabled=False,
            contacts_today=3,
            last_day="2026-04-11",
            last_sent={"morning_summary": 1234567890.0},
            last_operator_contact=1234567800.0,
            seen_proposed_goal_ids=["g1", "g2"],
        )
        d = state.to_dict()
        restored = ProactiveState.from_dict(d)
        assert restored.enabled is False
        assert restored.contacts_today == 3
        assert restored.last_day == "2026-04-11"
        assert restored.last_sent["morning_summary"] == 1234567890.0
        assert restored.last_operator_contact == 1234567800.0
        assert restored.seen_proposed_goal_ids == ["g1", "g2"]

    def test_seen_proposed_default_empty(self):
        state = ProactiveState()
        assert state.seen_proposed_goal_ids == []

    def test_from_dict_missing_seen_proposed(self):
        # Old persisted state files won't have the new key
        state = ProactiveState.from_dict({"enabled": True})
        assert state.seen_proposed_goal_ids == []

    def test_sent_today_by_reason_roundtrip(self):
        state = ProactiveState(sent_today_by_reason={"hydration_nudge": 2})
        restored = ProactiveState.from_dict(state.to_dict())
        assert restored.sent_today_by_reason == {"hydration_nudge": 2}

    def test_from_dict_missing_sent_today_by_reason(self):
        # Old persisted state files predate the per-reason daily counter.
        state = ProactiveState.from_dict({"enabled": True})
        assert state.sent_today_by_reason == {}

    def test_from_dict_defaults(self):
        state = ProactiveState.from_dict({})
        assert state.enabled is True
        assert state.contacts_today == 0


# ============================================================
# ContentGenerators tests
# ============================================================

class TestContentGenerators:
    def setup_method(self):
        self.gen = ContentGenerators()

    def test_morning_summary_basic(self):
        self.gen.set_user_name_fn(lambda: "Operator")
        self.gen.set_health_fn(lambda: 0.92)
        self.gen.set_mode_fn(lambda: "ACTIVE")
        self.gen.set_knowledge_fn(lambda: {
            "total_files": 20,
            "files_by_status": {"completed": [{}] * 8, "new": [{}] * 5},
            "total_chunks_learned": 45,
        })
        self.gen.set_active_goals_fn(lambda: [
            {"description": "Learn physics", "id": "g1"},
        ])
        self.gen.set_proposed_goals_fn(lambda: [])
        self.gen.set_evaluation_fn(lambda: None)

        contact = self.gen.generate(ContactReason.MORNING_SUMMARY)
        assert contact is not None
        assert "Operator" in contact.message
        assert "92%" in contact.message
        assert "8/20" in contact.message
        assert "Learn physics" in contact.message

    def test_morning_summary_no_data(self):
        """Morning summary works even with no data accessors."""
        contact = self.gen.generate(ContactReason.MORNING_SUMMARY)
        assert contact is not None
        assert contact.reason == ContactReason.MORNING_SUMMARY
        assert "Operator" in contact.message  # default fallback

    @staticmethod
    def _report(stability: float = 0.0):
        """A real EvaluationReport shaped like generate_report(24.0) output."""
        report = create_report(period_start=time.time() - 86400, period_end=time.time())
        report.metrics = {"system_stability": stability}
        return report

    def test_evening_recap_with_stats(self):
        self.gen.set_user_name_fn(lambda: "Operator")
        self.gen.set_knowledge_fn(lambda: {
            "exam_count_24h": 4,
            "average_exam_score_24h": 0.85,
        })
        self.gen.set_recent_achievements_fn(lambda: ["Learned chemistry"])
        self.gen.set_chunks_learned_fn(lambda: 12)
        self.gen.set_evaluation_fn(lambda: self._report())

        contact = self.gen.generate(ContactReason.EVENING_RECAP)
        assert contact is not None
        assert "Operator" in contact.message
        assert "Chunki nauczone (24h): 12" in contact.message
        # Whole line asserted, not the digits: "4" and "24" both occur inside the
        # literal "(24h)", so a substring check here passes on any sample size.
        assert "Egzaminy (24h): 4, sredni wynik 85%" in contact.message
        assert "chemistry" in contact.message

    def test_evening_recap_quotes_no_lifetime_totals(self):
        """The recap reports the day, so lifetime aggregates must not reach it.

        Regression: the frame read total_chunks_learned/average_exam_score and so
        printed "5379 chunks / 83%" four evenings running (07-12..07-15) -- an
        all-time sum a single day cannot move.
        """
        self.gen.set_user_name_fn(lambda: "Operator")
        self.gen.set_knowledge_fn(lambda: {
            "total_chunks_learned": 5379,   # lifetime traps
            "average_exam_score": 0.83,
            "exam_count_24h": 2,
            "average_exam_score_24h": 0.5,
        })
        self.gen.set_recent_achievements_fn(lambda: [])
        self.gen.set_chunks_learned_fn(lambda: 80)
        self.gen.set_evaluation_fn(lambda: self._report())

        contact = self.gen.generate(ContactReason.EVENING_RECAP)
        assert contact is not None
        assert "5379" not in contact.message
        assert "83%" not in contact.message
        assert "Chunki nauczone (24h): 80" in contact.message
        assert "Egzaminy (24h): 2, sredni wynik 50%" in contact.message

    def test_evening_recap_omits_exams_when_none_today(self):
        """No exams in the window is a real answer -- print no score at all."""
        self.gen.set_user_name_fn(lambda: "Operator")
        self.gen.set_knowledge_fn(lambda: {
            "average_exam_score": 0.83,     # lifetime exists...
            "exam_count_24h": 0,            # ...but nothing was sat today
            "average_exam_score_24h": 0.0,
        })
        self.gen.set_chunks_learned_fn(lambda: 5)
        self.gen.set_evaluation_fn(lambda: self._report())

        contact = self.gen.generate(ContactReason.EVENING_RECAP)
        assert contact is not None
        assert "egzamin" not in contact.message.lower()
        assert "83%" not in contact.message

    def test_evening_recap_omits_achievements_when_none_today(self):
        """A day with no achievements must say nothing, not reach into history."""
        self.gen.set_user_name_fn(lambda: "Operator")
        self.gen.set_recent_achievements_fn(lambda: [])
        self.gen.set_chunks_learned_fn(lambda: 5)
        self.gen.set_evaluation_fn(lambda: self._report())

        contact = self.gen.generate(ContactReason.EVENING_RECAP)
        assert contact is not None
        assert "Osiagniecia" not in contact.message

    def test_evening_recap_empty(self):
        """Evening recap returns None if nothing happened."""
        self.gen.set_user_name_fn(lambda: "Operator")
        contact = self.gen.generate(ContactReason.EVENING_RECAP)
        assert contact is None

    def test_morning_summary_exam_figure_is_windowed(self):
        """Morning brief quotes recent form, not the immovable lifetime mean."""
        self.gen.set_user_name_fn(lambda: "Operator")
        self.gen.set_knowledge_fn(lambda: {
            "total_files": 20,
            "files_by_status": {"completed": [{}] * 8},
            "total_chunks_learned": 45,     # legitimate: "Wiedza" is cumulative
            "average_exam_score": 0.83,     # lifetime trap
            "exam_count_24h": 3,
            "average_exam_score_24h": 0.6,
        })
        self.gen.set_evaluation_fn(lambda: None)

        contact = self.gen.generate(ContactReason.MORNING_SUMMARY)
        assert contact is not None
        assert "45 chunkow" in contact.message   # cumulative claim stays
        assert "Egzaminy (24h): 3, sredni wynik 60%" in contact.message
        assert "83%" not in contact.message

    @patch("agent_core.proactive.generators.datetime")
    def test_weekly_review_only_sunday(self, mock_dt):
        """Weekly review only fires on Sunday."""
        mock_now = MagicMock()
        mock_now.weekday.return_value = 0  # Monday
        mock_dt.now.return_value = mock_now

        contact = self.gen.generate(ContactReason.WEEKLY_REVIEW)
        assert contact is None

    @patch("agent_core.proactive.generators.datetime")
    def test_weekly_review_on_sunday(self, mock_dt):
        mock_now = MagicMock()
        mock_now.weekday.return_value = 6  # Sunday
        mock_dt.now.return_value = mock_now

        self.gen.set_user_name_fn(lambda: "Operator")
        self.gen.set_knowledge_fn(lambda: {
            "total_files": 10,
            "files_by_status": {"completed": [{}] * 5},
        })
        self.gen.set_goal_stats_fn(lambda: {"achieved": 3, "active": 2})
        self.gen.set_evaluation_fn(lambda: None)

        contact = self.gen.generate(ContactReason.WEEKLY_REVIEW)
        assert contact is not None
        assert "tygodnia" in contact.message
        assert "50%" in contact.message

    def test_goal_achieved(self):
        self.gen.set_recent_achievements_fn(lambda: [
            "Learned quantum physics",
            "Completed Python course",
        ])
        contact = self.gen.generate(ContactReason.GOAL_ACHIEVED)
        assert contact is not None
        assert "quantum physics" in contact.message
        assert contact.metadata.get("count") == 2

    def test_goal_achieved_none(self):
        self.gen.set_recent_achievements_fn(lambda: [])
        contact = self.gen.generate(ContactReason.GOAL_ACHIEVED)
        assert contact is None

    def test_idle_checkin(self):
        self.gen.set_user_name_fn(lambda: "Operator")
        self.gen.set_knowledge_fn(lambda: {
            "files_by_status": {"new": [{}] * 3},
        })
        self.gen.set_proposed_goals_fn(lambda: [{"id": "g1", "description": "test"}])
        self.gen.set_health_fn(lambda: 0.95)

        contact = self.gen.generate(ContactReason.IDLE_CHECKIN)
        assert contact is not None
        assert "Operator" in contact.message
        assert "3 nowych" in contact.message

    def test_safe_call_handles_exception(self):
        """Accessor that throws should not crash generator."""
        self.gen.set_health_fn(lambda: 1/0)  # ZeroDivisionError
        contact = self.gen.generate(ContactReason.MORNING_SUMMARY)
        assert contact is not None

    def test_generate_unknown_reason(self):
        result = self.gen.generate(ContactReason.MORNING_SUMMARY)
        assert result is not None

    def test_proposed_goal_alert_empty(self):
        assert self.gen.proposed_goal_alert([]) is None

    def test_proposed_goal_alert_single(self):
        contact = self.gen.proposed_goal_alert([
            {"id": "g1", "description": "K12 advisory escalation: stale_goals (3x w 7d)"},
        ])
        assert contact is not None
        assert contact.reason == ContactReason.GOAL_PROPOSED
        assert "Nowy PROPOSED cel" in contact.message
        assert "stale_goals" in contact.message
        assert "/goals" in contact.message
        assert contact.metadata["count"] == 1
        assert contact.metadata["goal_ids"] == ["g1"]

    def test_proposed_goal_alert_batch(self):
        contact = self.gen.proposed_goal_alert([
            {"id": "g1", "description": "First proposed goal"},
            {"id": "g2", "description": "Second proposed goal"},
            {"id": "g3", "description": "Third proposed goal"},
        ])
        assert contact is not None
        assert "3 nowych PROPOSED celow" in contact.message
        assert "First proposed goal" in contact.message
        assert "Second proposed goal" in contact.message
        assert "Third proposed goal" in contact.message
        assert contact.metadata["count"] == 3
        assert set(contact.metadata["goal_ids"]) == {"g1", "g2", "g3"}

    def test_proposed_goal_alert_batch_truncates_over_five(self):
        goals = [{"id": f"g{i}", "description": f"Goal {i}"} for i in range(7)]
        contact = self.gen.proposed_goal_alert(goals)
        assert contact is not None
        assert "7 nowych" in contact.message
        # First five inline
        for i in range(5):
            assert f"Goal {i}" in contact.message
        assert "i 2 wiecej" in contact.message

    def test_proposed_goal_alert_missing_description_falls_back(self):
        contact = self.gen.proposed_goal_alert([{"id": "gx"}])
        assert contact is not None
        # Falls back to "?" placeholder, doesn't crash
        assert contact.metadata["count"] == 1


# ============================================================
# Hydration nudge generator
# ============================================================

def _make_weather(temp=34.0, feels=33.0, city="Berlin"):
    """Build a WeatherData sample for hydration-nudge tests."""
    from agent_core.weather.weather_sensor import WeatherData
    return WeatherData(
        city=city, temp_c=temp, feels_like_c=feels,
        description="bezchmurnie", humidity=30, wind_speed_ms=2.0,
        icon="01d", sunrise=0, sunset=0, fetched_at=0.0,
    )


class TestHydrationNudgeGenerator:
    def setup_method(self):
        self.gen = ContentGenerators()
        self.gen.set_user_name_fn(lambda: "Eryk")

    def test_no_weather_accessor_returns_none(self):
        # Accessor never wired -> nothing to say.
        assert self.gen.generate(ContactReason.HYDRATION_NUDGE) is None

    def test_mild_day_returns_none(self):
        self.gen.set_weather_data_fn(lambda: _make_weather(temp=21, feels=20))
        assert self.gen.generate(ContactReason.HYDRATION_NUDGE) is None

    def test_weather_unavailable_returns_none(self):
        self.gen.set_weather_data_fn(lambda: None)
        assert self.gen.generate(ContactReason.HYDRATION_NUDGE) is None

    def test_hot_day_produces_nudge(self):
        self.gen.set_weather_data_fn(lambda: _make_weather(temp=34, feels=33))
        contact = self.gen.generate(ContactReason.HYDRATION_NUDGE)
        assert contact is not None
        assert contact.reason == ContactReason.HYDRATION_NUDGE
        assert "Eryk" in contact.message
        assert "34" in contact.message
        assert contact.metadata["temp_c"] == 34
        assert contact.metadata["feels_like_c"] == 33

    def test_dnd_context_suppresses_nudge(self):
        self.gen.set_weather_data_fn(lambda: _make_weather(temp=34, feels=33))
        self.gen.set_operator_context_fn(lambda: "Eryk na urlopie do piatku")
        assert self.gen.generate(ContactReason.HYDRATION_NUDGE) is None

    def test_no_emoji_in_message(self):
        """ADR-005: production strings stay ASCII-safe (no emoji)."""
        self.gen.set_weather_data_fn(lambda: _make_weather(temp=34, feels=33))
        contact = self.gen.generate(ContactReason.HYDRATION_NUDGE)
        assert contact.message.isascii()

    @patch("agent_core.proactive.generators.datetime")
    def test_message_varies_by_hour(self, mock_dt):
        """Two nudges at different hours should not read identically."""
        self.gen.set_weather_data_fn(lambda: _make_weather(temp=34, feels=33))
        messages = set()
        for hour in (12, 13, 14, 15):
            mock_dt.now.return_value = MagicMock(hour=hour)
            c = self.gen.generate(ContactReason.HYDRATION_NUDGE)
            messages.add(c.message)
        assert len(messages) >= 2  # rotation actually varies the wording

    def test_accessor_exception_is_safe(self):
        self.gen.set_weather_data_fn(lambda: 1 / 0)  # raises
        assert self.gen.generate(ContactReason.HYDRATION_NUDGE) is None


# ============================================================
# ProactiveScheduler tests
# ============================================================

class TestProactiveScheduler:
    def setup_method(self):
        self._tmp = Path("/tmp/test_proactive")
        self._tmp.mkdir(exist_ok=True)
        self.state_path = self._tmp / "proactive_state.json"
        if self.state_path.exists():
            self.state_path.unlink()
        history = self._tmp / "proactive_contacts.jsonl"
        if history.exists():
            history.unlink()

        self.sched = ProactiveScheduler(state_path=self.state_path)
        # Override history path to isolated tmp
        self.sched._history_path = self._tmp / "proactive_contacts.jsonl"
        self.sent_messages = []
        self.sched.set_notify_fn(lambda msg: self.sent_messages.append(msg))

    def test_tick_skips_without_interval(self):
        result = self.sched.tick()
        assert result == 0

    def test_tick_disabled(self):
        self.sched.set_enabled(False)
        self.sched._tick_count = CHECK_INTERVAL_TICKS - 1
        result = self.sched.tick()
        assert result == 0
        assert len(self.sent_messages) == 0

    def test_tick_no_notify_fn(self):
        sched = ProactiveScheduler(state_path=self.state_path)
        sched._tick_count = CHECK_INTERVAL_TICKS - 1
        result = sched.tick()
        assert result == 0

    @patch("agent_core.proactive.scheduler.datetime")
    def test_quiet_hours_blocked(self, mock_dt):
        """No proactive contact during quiet hours (23:00-6:00)."""
        mock_dt.now.return_value = _make_mock_dt(hour=2).now.return_value

        self.sched._tick_count = CHECK_INTERVAL_TICKS - 1
        result = self.sched.tick()
        assert result == 0

    def test_daily_limit(self):
        self.sched.state.contacts_today = 8
        self.sched.state.last_day = datetime.now().strftime("%Y-%m-%d")
        self.sched._tick_count = CHECK_INTERVAL_TICKS - 1
        result = self.sched.tick()
        assert result == 0

    def test_record_operator_contact(self):
        self.sched.record_operator_contact()
        assert self.sched.state.last_operator_contact > 0
        assert self.state_path.exists()

    def test_trigger_event(self):
        self.sched.trigger_event(ContactReason.GOAL_ACHIEVED)
        assert ContactReason.GOAL_ACHIEVED in self.sched._pending_events

    def test_trigger_event_no_duplicate(self):
        self.sched.trigger_event(ContactReason.GOAL_ACHIEVED)
        self.sched.trigger_event(ContactReason.GOAL_ACHIEVED)
        assert len(self.sched._pending_events) == 1

    @patch("agent_core.proactive.scheduler.datetime")
    def test_event_processing(self, mock_dt):
        """Events are processed and sent."""
        mock_dt.now.return_value = _make_mock_dt(hour=10).now.return_value

        self.sched.generators.set_recent_achievements_fn(
            lambda: ["Learned physics"]
        )
        self.sched.trigger_event(ContactReason.GOAL_ACHIEVED)

        self.sched._tick_count = CHECK_INTERVAL_TICKS - 1
        result = self.sched.tick()
        assert result >= 1
        assert any("physics" in msg for msg in self.sent_messages)

    def test_cooldown_respected(self):
        self.sched.state.last_sent["goal_achieved"] = time.time()
        assert not self.sched._can_send(ContactReason.GOAL_ACHIEVED)

    def test_cooldown_expired(self):
        self.sched.state.last_sent["goal_achieved"] = time.time() - 7200
        assert self.sched._can_send(ContactReason.GOAL_ACHIEVED)

    @patch("agent_core.proactive.scheduler.datetime")
    def test_morning_window(self, mock_dt):
        mock_dt.now.return_value = _make_mock_dt(hour=7).now.return_value
        assert self.sched._in_time_window(ContactReason.MORNING_SUMMARY)

        mock_dt.now.return_value = _make_mock_dt(hour=10).now.return_value
        assert not self.sched._in_time_window(ContactReason.MORNING_SUMMARY)

    @patch("agent_core.proactive.scheduler.datetime")
    def test_evening_window(self, mock_dt):
        mock_dt.now.return_value = _make_mock_dt(hour=20).now.return_value
        assert self.sched._in_time_window(ContactReason.EVENING_RECAP)

        mock_dt.now.return_value = _make_mock_dt(hour=15).now.return_value
        assert not self.sched._in_time_window(ContactReason.EVENING_RECAP)

    def test_state_persistence(self):
        self.sched.set_enabled(False)
        self.sched.record_operator_contact()

        sched2 = ProactiveScheduler(state_path=self.state_path)
        assert sched2.enabled is False
        assert sched2.state.last_operator_contact > 0

    def test_get_status(self):
        status = self.sched.get_status()
        assert "enabled" in status
        assert "contacts_today" in status
        assert "quiet_hours" in status
        assert "cooldowns" in status
        assert len(status["cooldowns"]) == len(ContactReason)

    def test_get_history_empty(self):
        history = self.sched.get_history()
        assert history == []

    @patch("agent_core.proactive.scheduler.datetime")
    def test_history_logged(self, mock_dt):
        """Sent contacts are logged to JSONL."""
        mock_dt.now.return_value = _make_mock_dt(hour=10).now.return_value

        self.sched.generators.set_recent_achievements_fn(
            lambda: ["Test achievement"]
        )
        self.sched.trigger_event(ContactReason.GOAL_ACHIEVED)
        self.sched._tick_count = CHECK_INTERVAL_TICKS - 1
        self.sched.tick()

        history = self.sched.get_history()
        assert len(history) >= 1
        assert history[-1]["reason"] == "goal_achieved"

    @patch("agent_core.proactive.scheduler.datetime")
    def test_idle_checkin_after_48h(self, mock_dt):
        """Idle checkin fires after 48h of no contact."""
        mock_dt.now.return_value = _make_mock_dt(hour=12).now.return_value

        self.sched.state.last_operator_contact = time.time() - (72 * 3600)
        self.sched.generators.set_user_name_fn(lambda: "Operator")

        sent = self.sched._check_idle()
        assert sent == 1
        assert any("Dawno" in msg for msg in self.sent_messages)

    def test_idle_checkin_no_contact_history(self):
        self.sched.state.last_operator_contact = 0
        sent = self.sched._check_idle()
        assert sent == 0

    def test_idle_checkin_recent_contact(self):
        self.sched.state.last_operator_contact = time.time() - 3600
        sent = self.sched._check_idle()
        assert sent == 0

    def test_set_enabled(self):
        self.sched.set_enabled(False)
        assert self.sched.enabled is False
        assert self.state_path.exists()

        self.sched.set_enabled(True)
        assert self.sched.enabled is True

    @patch("agent_core.proactive.scheduler.datetime")
    def test_daily_counter_reset(self, mock_dt):
        """Daily counter resets on new day."""
        mock_dt.now.return_value = _make_mock_dt(hour=10).now.return_value

        self.sched.state.contacts_today = 5
        self.sched.state.last_day = "2026-04-10"

        self.sched._tick_count = CHECK_INTERVAL_TICKS - 1
        self.sched.tick()

        # Either counter reset or day updated
        assert (
            self.sched.state.contacts_today < 5
            or self.sched.state.last_day != "2026-04-10"
        )

    # ─── PROPOSED-goal detection (Phase 13) ───

    @patch("agent_core.proactive.scheduler.datetime")
    def test_proposed_goal_first_seen_notifies(self, mock_dt):
        """First time a PROPOSED goal id is seen -> alert sent."""
        mock_dt.now.return_value = _make_mock_dt(hour=14).now.return_value

        self.sched.generators.set_proposed_goals_fn(
            lambda: [{"id": "g_new", "description": "Brand new advisory escalation"}]
        )

        self.sched._tick_count = CHECK_INTERVAL_TICKS - 1
        result = self.sched.tick()

        assert result >= 1
        assert any("Brand new advisory" in m for m in self.sent_messages)
        assert "g_new" in self.sched.state.seen_proposed_goal_ids

    @patch("agent_core.proactive.scheduler.datetime")
    def test_proposed_goal_already_seen_silent(self, mock_dt):
        """Re-seeing same PROPOSED id -> no notification (already alerted)."""
        mock_dt.now.return_value = _make_mock_dt(hour=14).now.return_value
        self.sched.state.seen_proposed_goal_ids = ["g_old"]

        self.sched.generators.set_proposed_goals_fn(
            lambda: [{"id": "g_old", "description": "Already-seen goal"}]
        )

        self.sched._tick_count = CHECK_INTERVAL_TICKS - 1
        result = self.sched.tick()

        # Goal-proposed slot must not have fired
        assert not any("Already-seen goal" in m for m in self.sent_messages)

    @patch("agent_core.proactive.scheduler.datetime")
    def test_proposed_goal_cooldown_blocks_then_releases(self, mock_dt):
        """Cooldown blocks notification but seen-set is NOT updated, so it fires later."""
        mock_dt.now.return_value = _make_mock_dt(hour=14).now.return_value

        # Recent send for GOAL_PROPOSED -> cooldown active
        self.sched.state.last_sent[ContactReason.GOAL_PROPOSED.value] = time.time()

        self.sched.generators.set_proposed_goals_fn(
            lambda: [{"id": "g_cooldown", "description": "Cooldown-blocked goal"}]
        )

        sent = self.sched._check_proposed_goals()
        assert sent == 0
        assert any("Cooldown" not in m for m in self.sent_messages) or not self.sent_messages
        # Seen-set must NOT contain g_cooldown — next eligible tick still treats it as new
        assert "g_cooldown" not in self.sched.state.seen_proposed_goal_ids

        # Expire cooldown manually
        self.sched.state.last_sent[ContactReason.GOAL_PROPOSED.value] = (
            time.time() - 700
        )
        sent2 = self.sched._check_proposed_goals()
        assert sent2 == 1
        assert "g_cooldown" in self.sched.state.seen_proposed_goal_ids

    @patch("agent_core.proactive.scheduler.datetime")
    def test_proposed_goal_confirmed_drops_from_seen(self, mock_dt):
        """When a previously-seen goal is no longer PROPOSED (confirmed/rejected),
        it gets removed from seen_proposed_goal_ids without notification."""
        mock_dt.now.return_value = _make_mock_dt(hour=14).now.return_value
        self.sched.state.seen_proposed_goal_ids = ["g_a", "g_b"]

        # Only g_a still PROPOSED — g_b confirmed
        self.sched.generators.set_proposed_goals_fn(
            lambda: [{"id": "g_a", "description": "Still proposed"}]
        )

        sent = self.sched._check_proposed_goals()
        assert sent == 0
        assert self.sched.state.seen_proposed_goal_ids == ["g_a"]

    @patch("agent_core.proactive.scheduler.datetime")
    def test_proposed_goal_no_accessor_returns_zero(self, mock_dt):
        """No accessor wired -> safely returns 0."""
        mock_dt.now.return_value = _make_mock_dt(hour=14).now.return_value
        # No accessor wired
        sent = self.sched._check_proposed_goals()
        assert sent == 0

    @patch("agent_core.proactive.scheduler.datetime")
    def test_proposed_goal_accessor_raises_returns_zero(self, mock_dt):
        """Accessor exception is swallowed."""
        mock_dt.now.return_value = _make_mock_dt(hour=14).now.return_value

        def boom():
            raise RuntimeError("kaboom")

        self.sched.generators.set_proposed_goals_fn(boom)
        sent = self.sched._check_proposed_goals()
        assert sent == 0

    @patch("agent_core.proactive.scheduler.datetime")
    def test_proposed_goal_quiet_hours_blocked(self, mock_dt):
        """Quiet hours block GOAL_PROPOSED (None window respects quiet hours via _in_time_window)."""
        mock_dt.now.return_value = _make_mock_dt(hour=2).now.return_value

        self.sched.generators.set_proposed_goals_fn(
            lambda: [{"id": "g_night", "description": "Late-night goal"}]
        )

        # Direct call (bypassing tick's quiet-hours short-circuit) to verify
        # _in_time_window also blocks on its own.
        sent = self.sched._check_proposed_goals()
        assert sent == 0
        assert "g_night" not in self.sched.state.seen_proposed_goal_ids

    def test_proposed_goal_state_persists_across_restart(self):
        """seen_proposed_goal_ids survives state-file roundtrip."""
        self.sched.state.seen_proposed_goal_ids = ["g_persist_1", "g_persist_2"]
        self.sched._save_state()

        sched2 = ProactiveScheduler(state_path=self.state_path)
        assert set(sched2.state.seen_proposed_goal_ids) == {"g_persist_1", "g_persist_2"}

    @patch("agent_core.proactive.scheduler.datetime")
    def test_scheduled_morning(self, mock_dt):
        """Morning summary fires in window with data."""
        mock_dt.now.return_value = _make_mock_dt(hour=7, weekday=1).now.return_value

        self.sched.generators.set_user_name_fn(lambda: "Operator")
        self.sched.generators.set_health_fn(lambda: 0.9)
        self.sched.generators.set_mode_fn(lambda: "ACTIVE")
        self.sched.generators.set_knowledge_fn(lambda: {
            "total_files": 10,
            "files_by_status": {"completed": [{}] * 5, "new": [{}] * 2},
            "total_chunks_learned": 20,
        })
        self.sched.generators.set_active_goals_fn(lambda: [])
        self.sched.generators.set_proposed_goals_fn(lambda: [])
        self.sched.generators.set_evaluation_fn(lambda: None)

        self.sched._tick_count = CHECK_INTERVAL_TICKS - 1
        result = self.sched.tick()
        assert result >= 1
        assert any("Operator" in msg for msg in self.sent_messages)


# ============================================================
# Hydration nudge: scheduler-level (window, cap, flag, counter)
# ============================================================

class TestHydrationNudgeScheduler:
    def setup_method(self):
        self._tmp = Path("/tmp/test_proactive_hydration")
        self._tmp.mkdir(exist_ok=True)
        self.state_path = self._tmp / "proactive_state.json"
        if self.state_path.exists():
            self.state_path.unlink()
        self.sched = ProactiveScheduler(state_path=self.state_path)
        self.sched._history_path = self._tmp / "proactive_contacts.jsonl"
        self.sent_messages = []
        self.sched.set_notify_fn(lambda msg: self.sent_messages.append(msg))
        self.sched.generators.set_user_name_fn(lambda: "Eryk")
        self.sched.generators.set_weather_data_fn(lambda: _make_weather(34, 33))

    def _tick_at(self, hour):
        with patch("agent_core.proactive.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = _make_mock_dt(hour=hour).now.return_value
            self.sched._tick_count = CHECK_INTERVAL_TICKS - 1
            return self.sched.tick()

    def _water_msgs(self):
        return [m for m in self.sent_messages if "wod" in m.lower()]

    def test_under_daily_reason_cap_unit(self):
        assert self.sched._under_daily_reason_cap(ContactReason.HYDRATION_NUDGE)
        self.sched.state.sent_today_by_reason["hydration_nudge"] = 2
        assert not self.sched._under_daily_reason_cap(ContactReason.HYDRATION_NUDGE)
        # Reasons without a configured cap are always allowed here.
        self.sched.state.sent_today_by_reason["morning_summary"] = 99
        assert self.sched._under_daily_reason_cap(ContactReason.MORNING_SUMMARY)

    def test_hot_day_in_window_sends_nudge(self):
        self._tick_at(13)
        assert len(self._water_msgs()) == 1
        assert "Eryk" in self.sent_messages[0]
        assert self.sched.state.sent_today_by_reason.get("hydration_nudge") == 1

    def test_mild_day_no_nudge(self):
        self.sched.generators.set_weather_data_fn(lambda: _make_weather(22, 21))
        self._tick_at(13)
        assert self._water_msgs() == []

    def test_before_window_no_nudge(self):
        self._tick_at(9)  # hydration window is 11-20
        assert self._water_msgs() == []

    def test_after_window_no_nudge(self):
        self._tick_at(21)  # past 20:00 (also quiet hours start at 23)
        assert self._water_msgs() == []

    def test_daily_cap_blocks_third_send(self):
        # Drive three eligible ticks, bypassing the 3.5h cooldown each time so
        # only the 2/day cap can stop the third.
        for _ in range(3):
            self.sched.state.last_sent.pop("hydration_nudge", None)
            self._tick_at(13)
        assert len(self._water_msgs()) == 2
        assert self.sched.state.sent_today_by_reason["hydration_nudge"] == 2

    def test_cooldown_blocks_rapid_resend(self):
        self._tick_at(13)
        self._tick_at(13)  # cooldown (3.5h) not elapsed -> no second send
        assert len(self._water_msgs()) == 1

    def test_flag_off_disables_nudge(self, monkeypatch):
        monkeypatch.setenv("HYDRATION_NUDGE_ENABLED", "false")
        self._tick_at(13)
        assert self._water_msgs() == []

    def test_new_day_resets_reason_counter(self):
        self.sched.state.sent_today_by_reason = {"hydration_nudge": 2}
        self.sched.state.last_day = "2000-01-01"
        self._tick_at(9)  # out of hydration window -> reset but no refill
        assert self.sched.state.sent_today_by_reason.get("hydration_nudge", 0) == 0


# ============================================================
# Integration tests
# ============================================================

class TestProactiveIntegration:
    def test_import(self):
        from agent_core.proactive import (
            ContactReason,
            ProactiveContact,
            ProactiveScheduler,
            ContentGenerators,
        )
        assert ProactiveScheduler is not None

    @patch("agent_core.proactive.scheduler.datetime")
    def test_scheduler_with_generators(self, mock_dt):
        """Full flow: generators wired -> event triggered -> message sent."""
        mock_dt.now.return_value = _make_mock_dt(hour=14).now.return_value

        state_path = Path("/tmp/test_proactive_integration.json")
        if state_path.exists():
            state_path.unlink()
        sched = ProactiveScheduler(state_path=state_path)
        sent = []
        sched.set_notify_fn(lambda msg: sent.append(msg))

        sched.generators.set_recent_achievements_fn(
            lambda: ["Completed AI basics"]
        )
        sched.trigger_event(ContactReason.GOAL_ACHIEVED)

        sched._tick_count = CHECK_INTERVAL_TICKS - 1
        result = sched.tick()

        assert result >= 1
        assert any("AI basics" in msg for msg in sent)

    def test_telegram_bridge_message_count(self):
        from agent_core.telegram import TelegramBridge
        bridge = TelegramBridge()
        assert hasattr(bridge, "last_poll_message_count")
        assert bridge.last_poll_message_count == 0


# ============================================================
# GOAL_ACHIEVED live wiring (real caller-backed, no mocks on path)
# ============================================================

class TestGoalAchievedLiveWiring:
    """Drive a REAL GoalStore through bind_goal_store() and assert the
    GOAL_ACHIEVED event path actually fires.

    Regression guard: trigger_event() previously had ZERO production callers --
    the only test (test_trigger_event) exercised it in isolation, so the whole
    event-based path silently rotted. These tests replicate the exact wiring
    homeostasis_module.py performs (status observer + recent_achievements
    accessor) and fail if either the GoalStore observer hook or
    ProactiveScheduler.bind_goal_store() stops working.
    """

    def setup_method(self):
        import tempfile

        from agent_core.goals.store import GoalStore

        self._tmp = Path(tempfile.mkdtemp(prefix="proactive_wire_"))
        self.store = GoalStore(self._tmp / "goals.jsonl")
        self.sched = ProactiveScheduler(state_path=self._tmp / "proactive_state.json")
        # Isolate history from the live meta_data/proactive_contacts.jsonl.
        self.sched._history_path = self._tmp / "proactive_contacts.jsonl"

        # --- mirror production wiring (homeostasis_module.py) ---
        self.sched.bind_goal_store(self.store)
        self.sched.generators.set_recent_achievements_fn(
            lambda: [
                g.description
                for g in self.store.get_all()
                if g.status.value == "achieved"
            ][-5:]
        )
        self.sent = []
        self.sched.set_notify_fn(self.sent.append)

    def _add_active_goal(self, description="Learn quantum physics"):
        from agent_core.goals.goal_model import GoalStatus, GoalType, create_goal

        goal = create_goal(
            goal_type=GoalType.LEARNING,
            description=description,
            priority=0.6,
            status=GoalStatus.ACTIVE,
        )
        self.store.create(goal)
        return goal

    def test_auto_achieve_via_progress_queues_event(self):
        """update_progress->1.0 funnels through update_status -> observer -> queue."""
        goal = self._add_active_goal()
        assert ContactReason.GOAL_ACHIEVED not in self.sched._pending_events
        self.store.update_progress(goal.id, 1.0)
        assert ContactReason.GOAL_ACHIEVED in self.sched._pending_events

    def test_planner_path_update_status_queues_event(self):
        """Direct update_status(ACHIEVED) -- the planner/action_executor path."""
        from agent_core.goals.goal_model import GoalStatus

        goal = self._add_active_goal()
        self.store.update_status(goal.id, GoalStatus.ACHIEVED, "done", "system")
        assert ContactReason.GOAL_ACHIEVED in self.sched._pending_events

    def test_creating_active_goal_does_not_fire(self):
        """create() bypasses update_status, so no spurious event on creation."""
        self._add_active_goal()
        assert ContactReason.GOAL_ACHIEVED not in self.sched._pending_events

    def test_non_achieved_transition_does_not_fire(self):
        from agent_core.goals.goal_model import GoalStatus

        goal = self._add_active_goal()
        self.store.update_status(goal.id, GoalStatus.ABANDONED, "drop", "system")
        assert ContactReason.GOAL_ACHIEVED not in self.sched._pending_events

    def test_noop_reset_does_not_refire(self):
        from agent_core.goals.goal_model import GoalStatus

        goal = self._add_active_goal()
        self.store.update_status(goal.id, GoalStatus.ACHIEVED, "done", "system")
        self.sched._pending_events.clear()
        # Re-setting to the same status must not re-queue (old==new guard).
        self.store.update_status(goal.id, GoalStatus.ACHIEVED, "again", "system")
        assert ContactReason.GOAL_ACHIEVED not in self.sched._pending_events

    def test_end_to_end_sends_real_contact(self):
        """Full path: achieve -> process -> generate from real store -> send."""
        self._add_active_goal("Master linear algebra")  # stays ACTIVE
        achieved = self._add_active_goal("Read Sapiens")
        self.store.update_progress(achieved.id, 1.0)

        sent = self.sched._process_events()

        assert sent == 1
        assert len(self.sent) == 1
        assert "Cel osiagniety" in self.sent[0]
        assert "Sapiens" in self.sent[0]
        # The still-active goal must not appear as an achievement.
        assert "linear algebra" not in self.sent[0]

    def test_store_without_observer_still_works(self):
        """A GoalStore with no observers must function unchanged (decoupling)."""
        from agent_core.goals.goal_model import GoalStatus, GoalType, create_goal
        from agent_core.goals.store import GoalStore

        store = GoalStore(self._tmp / "goals_unbound.jsonl")
        goal = create_goal(GoalType.LEARNING, "x", 0.5, status=GoalStatus.ACTIVE)
        store.create(goal)
        assert store.update_progress(goal.id, 1.0) is True
        assert store.get(goal.id).status == GoalStatus.ACHIEVED

    def test_observer_exception_does_not_break_store(self):
        """A throwing observer must not corrupt the status write."""
        from agent_core.goals.goal_model import GoalStatus

        def _boom(goal, old, new):
            raise RuntimeError("observer blew up")

        self.store.register_status_observer(_boom)
        goal = self._add_active_goal()
        assert self.store.update_progress(goal.id, 1.0) is True
        assert self.store.get(goal.id).status == GoalStatus.ACHIEVED

    def test_bind_none_is_safe(self):
        self.sched.bind_goal_store(None)  # must not raise

    def test_homeostasis_wires_bind_goal_store(self):
        """The production init MUST call bind_goal_store -- this is the exact
        wiring that was missing (trigger_event had zero callers). A source
        check guards the call site, which the behavioural tests above cannot
        reach without running the full homeostasis init. The regex requires a
        real (non-None, non-empty) argument so a `bind_goal_store(None)` typo or
        a dead `()` call cannot pass the guard."""
        import re

        src = Path(__file__).resolve().parents[1] / "modules" / "homeostasis_module.py"
        text = src.read_text(encoding="utf-8")
        assert re.search(r"\.bind_goal_store\(\s*(?!None\b)\w", text), (
            "homeostasis_module.py must call proactive.bind_goal_store(<goal_store>) "
            "with a real argument -- the GOAL_ACHIEVED event path is dead without it"
        )


class TestLearningMilestoneWiring:
    """LEARNING_MILESTONE: twin of GOAL_ACHIEVED. The teacher pushes passed-exam
    milestones into the scheduler buffer; the generator drains + batches them."""

    def setup_method(self):
        self.sched = ProactiveScheduler()
        self.sched.generators.set_recent_milestones_fn(
            self.sched.drain_recent_milestones
        )
        self.sent = []
        self.sched.set_notify_fn(self.sent.append)

    def test_note_queues_event_and_buffers(self):
        assert ContactReason.LEARNING_MILESTONE not in self.sched._pending_events
        self.sched.note_learning_milestone("astronomia", 0.85)
        assert ContactReason.LEARNING_MILESTONE in self.sched._pending_events
        assert len(self.sched._milestone_buffer) == 1

    def test_empty_topic_ignored(self):
        self.sched.note_learning_milestone("", 0.9)
        assert ContactReason.LEARNING_MILESTONE not in self.sched._pending_events
        assert self.sched._milestone_buffer == []

    def test_dedup_same_file_within_window(self):
        self.sched.note_learning_milestone("astronomia", 0.85)
        self.sched.note_learning_milestone("astronomia", 0.90)  # re-pass (spaced rep)
        assert len(self.sched._milestone_buffer) == 1  # not re-buffered

    def test_distinct_files_both_buffered(self):
        self.sched.note_learning_milestone("astronomia", 0.85)
        self.sched.note_learning_milestone("fotosynteza", 0.72)
        assert len(self.sched._milestone_buffer) == 2

    def test_drain_clears_buffer(self):
        self.sched.note_learning_milestone("astronomia", 0.85)
        items = self.sched.drain_recent_milestones()
        assert len(items) == 1 and items[0]["topic"] == "astronomia"
        assert self.sched.drain_recent_milestones() == []

    def test_end_to_end_sends_real_contact(self):
        """Full path: note -> process -> generate (drain) -> send."""
        self.sched.note_learning_milestone("astronomia_gwiazdy", 0.85)
        self.sched.note_learning_milestone("fotosynteza", 0.72)

        sent = self.sched._process_events()

        assert sent == 1
        assert len(self.sent) == 1
        msg = self.sent[0]
        assert "Nauczylam sie" in msg
        assert "astronomia gwiazdy" in msg  # underscore -> space, no extension
        assert "85%" in msg
        assert "fotosynteza" in msg
        # Buffer drained -> a second process with no new milestones sends nothing.
        assert self.sched._process_events() == 0

    def test_cooldown_blocks_but_retains_buffer(self):
        """If LEARNING_MILESTONE is on cooldown, generate() is never called, so
        the buffer is retained for the next eligible tick (not lost)."""
        self.sched._state.last_sent[ContactReason.LEARNING_MILESTONE.value] = time.time()
        self.sched.note_learning_milestone("astronomia", 0.85)
        sent = self.sched._process_events()
        assert sent == 0
        assert len(self.sched._milestone_buffer) == 1  # still pending

    def test_homeostasis_wires_recent_milestones(self):
        """Production init MUST wire the milestone accessor, else the buffer is
        never drained and the ping never fires (dead event path)."""
        import re

        src = Path(__file__).resolve().parents[1] / "modules" / "homeostasis_module.py"
        text = src.read_text(encoding="utf-8")
        assert re.search(r"set_recent_milestones_fn\(\s*(?!None\b)\w", text), (
            "homeostasis_module.py must wire gen.set_recent_milestones_fn(<accessor>)"
        )

    def test_teacher_module_wires_milestone_fn(self):
        """The teacher MUST forward passed exams to proactive."""
        import re

        src = Path(__file__).resolve().parents[1] / "modules" / "teacher_module.py"
        text = src.read_text(encoding="utf-8")
        assert ".set_milestone_fn(" in text and "note_learning_milestone" in text


class TestSituationalAwareness:
    """E4: proactive messages speak from the live SelfContext picture -- the
    planner's REAL current focus (E3 rung2). Flag-gated PROACTIVE_SITUATIONAL.
    Vision is deliberately NOT restated here (it rides the E2 chat tail; echoing
    it proactively would duplicate the VisionAdvisor ping)."""

    def setup_method(self):
        self.gen = ContentGenerators()

    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("PROACTIVE_SITUATIONAL", raising=False)
        self.gen.set_self_context_fn(lambda: {
            "mission": {"top_goal": "Cel", "focus_source": "planner"},
        })
        assert self.gen._situational_lines() == []

    def test_on_includes_planner_focus(self, monkeypatch):
        monkeypatch.setenv("PROACTIVE_SITUATIONAL", "true")
        self.gen.set_self_context_fn(lambda: {
            "mission": {"top_goal": "Zbadaj rynek", "current_action": "fetch",
                        "focus_source": "planner"},
        })
        lines = self.gen._situational_lines()
        assert lines == ["Teraz pracuje nad: Zbadaj rynek"]

    def test_does_not_restate_vision(self, monkeypatch):
        # Vision lives in the E2 chat tail; it must NOT leak into proactive.
        monkeypatch.setenv("PROACTIVE_SITUATIONAL", "true")
        self.gen.set_self_context_fn(lambda: {
            "vision": {"latest": "Osoba przy biurku", "age_s": 600},
            "mission": {"top_goal": "Zbadaj rynek", "focus_source": "planner"},
        })
        joined = " ".join(self.gen._situational_lines())
        assert "Osoba przy biurku" not in joined
        assert "Ostatnio widzialam" not in joined
        assert "Teraz pracuje nad" in joined  # only the focus

    def test_skips_heuristic_focus_only_trusts_planner(self, monkeypatch):
        monkeypatch.setenv("PROACTIVE_SITUATIONAL", "true")
        self.gen.set_self_context_fn(lambda: {
            "mission": {"top_goal": "Zgadywany cel", "focus_source": "heuristic"},
        })
        assert self.gen._situational_lines() == []  # not the planner's real focus

    def test_no_picture_degrades_to_empty(self, monkeypatch):
        monkeypatch.setenv("PROACTIVE_SITUATIONAL", "true")
        assert self.gen._situational_lines() == []      # no accessor wired
        self.gen.set_self_context_fn(lambda: None)
        assert self.gen._situational_lines() == []      # picture unavailable

    def test_morning_summary_includes_focus_when_on(self, monkeypatch):
        monkeypatch.setenv("PROACTIVE_SITUATIONAL", "true")
        self.gen.set_user_name_fn(lambda: "Eryk")
        self.gen.set_self_context_fn(lambda: {
            "mission": {"top_goal": "Naucz sie pythona", "current_action": "learn",
                        "focus_source": "planner"},
        })
        msg = self.gen.generate(ContactReason.MORNING_SUMMARY).message
        assert "Teraz pracuje nad" in msg and "Naucz sie pythona" in msg

    def test_morning_summary_no_situational_when_off(self, monkeypatch):
        monkeypatch.delenv("PROACTIVE_SITUATIONAL", raising=False)
        self.gen.set_user_name_fn(lambda: "Eryk")
        self.gen.set_self_context_fn(lambda: {
            "mission": {"top_goal": "Naucz sie pythona", "focus_source": "planner"},
        })
        msg = self.gen.generate(ContactReason.MORNING_SUMMARY).message
        assert "Teraz pracuje nad" not in msg


# ============================================================
# Production wiring (homeostasis_module.wire_proactive_generators)
# ============================================================

class TestProactiveWiring:
    """Drive the REAL wiring against REAL stores.

    Both bugs the daily frame shipped lived in these lambdas, not in the store
    or the generator -- unit tests on either side each saw a correct half while
    the recap went out claiming a ten-day-old goal as today's work.
    """

    @pytest.fixture
    def ctx(self, tmp_path):
        from types import SimpleNamespace
        from agent_core.goals.store import GoalStore
        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer

        (tmp_path / "memory").mkdir()
        (tmp_path / "input").mkdir()
        return SimpleNamespace(
            goal_store=GoalStore(tmp_path / "goals.jsonl"),
            knowledge_analyzer=KnowledgeAnalyzer(
                knowledge_index_path=tmp_path / "memory" / "knowledge_index.jsonl",
                longterm_memory_path=tmp_path / "memory" / "longterm_memory.jsonl",
                exam_results_path=tmp_path / "memory" / "exam_results.jsonl",
                input_dir=tmp_path / "input",
            ),
            evaluation_observer=None,
            self_context=None,
        )

    @staticmethod
    def _wire(ctx, tmp_path):
        from agent_core.modules.homeostasis_module import wire_proactive_generators

        gen = ContentGenerators()
        proactive = ProactiveScheduler()
        wire_proactive_generators(gen, ctx, None, proactive)
        return gen

    @staticmethod
    def _achieve(store, description, hours_ago):
        from agent_core.goals.goal_model import GoalType, GoalStatus, create_goal

        gid = store.create(create_goal(GoalType.LEARNING, description, 0.5))
        store.update_status(gid, GoalStatus.ACHIEVED, "done", "test")
        stamp = time.time() - hours_ago * 3600
        for entry in store.get(gid).audit_trail:
            if entry.new_status == GoalStatus.ACHIEVED.value:
                entry.timestamp = stamp

    def test_recap_does_not_claim_an_old_goal_as_todays_work(self, ctx, tmp_path):
        """The shipped bug: a goal achieved on 07-05 headlined the 07-15 recap."""
        self._achieve(ctx.goal_store, "Ancient win", 250)

        gen = self._wire(ctx, tmp_path)
        gen.set_user_name_fn(lambda: "Eryk")
        contact = gen.generate(ContactReason.EVENING_RECAP)

        assert contact is None or "Ancient win" not in contact.message

    def test_recap_shows_a_goal_achieved_today(self, ctx, tmp_path):
        self._achieve(ctx.goal_store, "Fresh win", 2)

        gen = self._wire(ctx, tmp_path)
        gen.set_user_name_fn(lambda: "Eryk")
        contact = gen.generate(ContactReason.EVENING_RECAP)

        assert contact is not None
        assert "Fresh win" in contact.message

    def test_chunk_line_reads_memory_not_the_lifetime_total(self, ctx, tmp_path):
        """Wiring must reach count_chunks_learned, never total_chunks_learned."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        with open(ctx.knowledge_analyzer.memory_path, "w") as f:
            for i, hours_ago in enumerate([1, 2, 400, 500]):
                stamp = (now - timedelta(hours=hours_ago)).isoformat().replace(
                    "+00:00", "Z"
                )
                f.write(json.dumps({
                    "source_file": "t.txt", "chunk_id": f"c{i}", "timestamp": stamp,
                }) + "\n")

        gen = self._wire(ctx, tmp_path)
        gen.set_user_name_fn(lambda: "Eryk")
        contact = gen.generate(ContactReason.EVENING_RECAP)

        assert contact is not None
        assert "Chunki nauczone (24h): 2" in contact.message
        assert "4" not in contact.message.split("Chunki nauczone (24h): ")[1][:2]
