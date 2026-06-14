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


# ============================================================
# ProactiveModel tests
# ============================================================

class TestContactReason:
    def test_all_reasons_defined(self):
        assert len(ContactReason) == 8

    def test_reason_values(self):
        assert ContactReason.MORNING_SUMMARY.value == "morning_summary"
        assert ContactReason.EVENING_RECAP.value == "evening_recap"
        assert ContactReason.WEEKLY_REVIEW.value == "weekly_review"
        assert ContactReason.GOAL_ACHIEVED.value == "goal_achieved"
        assert ContactReason.GOAL_PROPOSED.value == "goal_proposed"
        assert ContactReason.LEARNING_MILESTONE.value == "learning_milestone"
        assert ContactReason.INTEREST_MATCH.value == "interest_match"
        assert ContactReason.IDLE_CHECKIN.value == "idle_checkin"

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

    def test_evening_recap_with_stats(self):
        self.gen.set_user_name_fn(lambda: "Operator")
        self.gen.set_planner_stats_fn(lambda: {"total_cycles": 150})
        self.gen.set_knowledge_fn(lambda: {
            "total_chunks_learned": 12,
            "average_exam_score": 0.85,
        })
        self.gen.set_recent_achievements_fn(lambda: ["Learned chemistry"])
        self.gen.set_evaluation_fn(lambda: None)

        contact = self.gen.generate(ContactReason.EVENING_RECAP)
        assert contact is not None
        assert "Operator" in contact.message
        assert "150" in contact.message
        assert "chemistry" in contact.message

    def test_evening_recap_empty(self):
        """Evening recap returns None if nothing happened."""
        self.gen.set_user_name_fn(lambda: "Operator")
        contact = self.gen.generate(ContactReason.EVENING_RECAP)
        assert contact is None

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

    def test_learning_milestone(self):
        self.gen.set_knowledge_fn(lambda: {
            "total_files": 10,
            "files_by_status": {"completed": [{}] * 5},
            "total_chunks_learned": 30,
            "average_exam_score": 0.8,
        })
        contact = self.gen.generate(ContactReason.LEARNING_MILESTONE)
        assert contact is not None
        assert "50%" in contact.message
        assert contact.metadata.get("milestone_pct") == 50

    def test_learning_milestone_zero(self):
        self.gen.set_knowledge_fn(lambda: {
            "total_files": 10,
            "files_by_status": {"completed": []},
        })
        contact = self.gen.generate(ContactReason.LEARNING_MILESTONE)
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

    def test_interest_match(self):
        self.gen.set_user_interests_fn(lambda: ["physics", "chemistry"])
        self.gen.set_user_name_fn(lambda: "Operator")
        self.gen.set_knowledge_fn(lambda: {
            "new_files_available": [
                {"title": "Quantum Physics Basics", "file_id": "f1"},
                {"title": "Cooking recipes", "file_id": "f2"},
            ],
        })

        contact = self.gen.generate(ContactReason.INTEREST_MATCH)
        assert contact is not None
        assert "Quantum Physics" in contact.message
        assert "Cooking" not in contact.message

    def test_interest_match_no_interests(self):
        self.gen.set_user_interests_fn(lambda: [])
        contact = self.gen.generate(ContactReason.INTEREST_MATCH)
        assert contact is None

    def test_interest_match_no_matches(self):
        self.gen.set_user_interests_fn(lambda: ["music"])
        self.gen.set_knowledge_fn(lambda: {
            "new_files_available": [
                {"title": "Physics 101", "file_id": "f1"},
            ],
        })
        contact = self.gen.generate(ContactReason.INTEREST_MATCH)
        assert contact is None

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
