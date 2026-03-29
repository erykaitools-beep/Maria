"""Tests for TimeAwareness module."""

import pytest
from datetime import datetime
from unittest.mock import patch

from agent_core.homeostasis.time_awareness import TimeAwareness


class TestTimeAwareness:
    """Test time awareness functionality."""

    def test_format_duration_seconds(self):
        """Test duration formatting for seconds."""
        assert TimeAwareness.format_duration(30) == "30 sek"
        assert TimeAwareness.format_duration(59) == "59 sek"

    def test_format_duration_minutes(self):
        """Test duration formatting for minutes."""
        assert TimeAwareness.format_duration(60) == "1 min"
        assert TimeAwareness.format_duration(120) == "2 min"
        assert TimeAwareness.format_duration(3599) == "59 min"

    def test_format_duration_hours(self):
        """Test duration formatting for hours."""
        assert TimeAwareness.format_duration(3600) == "1h"
        assert TimeAwareness.format_duration(7200) == "2h"
        assert TimeAwareness.format_duration(3660) == "1h 1min"
        assert TimeAwareness.format_duration(5400) == "1h 30min"

    def test_format_time(self):
        """Test time formatting."""
        time_str = TimeAwareness.format_time()
        # Should be HH:MM format
        assert len(time_str) == 5
        assert time_str[2] == ":"

    @patch("agent_core.homeostasis.time_awareness.datetime")
    def test_get_time_of_day_morning(self, mock_datetime):
        """Test time of day detection - morning."""
        mock_datetime.now.return_value = datetime(2026, 2, 2, 7, 30)
        assert TimeAwareness.get_time_of_day() == "wczesny ranek"

    @patch("agent_core.homeostasis.time_awareness.datetime")
    def test_get_time_of_day_night(self, mock_datetime):
        """Test time of day detection - night."""
        mock_datetime.now.return_value = datetime(2026, 2, 2, 23, 30)
        assert TimeAwareness.get_time_of_day() == "noc"

    @patch("agent_core.homeostasis.time_awareness.datetime")
    def test_get_time_of_day_afternoon(self, mock_datetime):
        """Test time of day detection - afternoon."""
        mock_datetime.now.return_value = datetime(2026, 2, 2, 15, 0)
        assert TimeAwareness.get_time_of_day() == "popoludnie"

    @patch("agent_core.homeostasis.time_awareness.datetime")
    def test_is_late_night_true(self, mock_datetime):
        """Test late night detection - true."""
        mock_datetime.now.return_value = datetime(2026, 2, 2, 23, 30)
        assert TimeAwareness.is_late_night() is True

    @patch("agent_core.homeostasis.time_awareness.datetime")
    def test_is_late_night_false(self, mock_datetime):
        """Test late night detection - false."""
        mock_datetime.now.return_value = datetime(2026, 2, 2, 14, 0)
        assert TimeAwareness.is_late_night() is False

    @patch("agent_core.homeostasis.time_awareness.datetime")
    def test_is_weekend_saturday(self, mock_datetime):
        """Test weekend detection - Saturday."""
        mock_datetime.now.return_value = datetime(2026, 2, 7, 12, 0)  # Saturday
        assert TimeAwareness.is_weekend() is True

    @patch("agent_core.homeostasis.time_awareness.datetime")
    def test_is_weekend_monday(self, mock_datetime):
        """Test weekend detection - Monday."""
        mock_datetime.now.return_value = datetime(2026, 2, 2, 12, 0)  # Monday
        assert TimeAwareness.is_weekend() is False

    @patch("agent_core.homeostasis.time_awareness.datetime")
    def test_get_greeting_morning(self, mock_datetime):
        """Test greeting - morning."""
        mock_datetime.now.return_value = datetime(2026, 2, 2, 9, 0)
        assert TimeAwareness.get_greeting() == "Dzien dobry"

    @patch("agent_core.homeostasis.time_awareness.datetime")
    def test_get_greeting_evening(self, mock_datetime):
        """Test greeting - evening."""
        mock_datetime.now.return_value = datetime(2026, 2, 2, 20, 0)
        assert TimeAwareness.get_greeting() == "Dobry wieczor"

    @patch("agent_core.homeostasis.time_awareness.datetime")
    def test_get_greeting_night(self, mock_datetime):
        """Test greeting - night."""
        mock_datetime.now.return_value = datetime(2026, 2, 2, 23, 30)
        assert TimeAwareness.get_greeting() == "Hej"

    def test_get_context_basic(self):
        """Test context generation without session info."""
        ctx = TimeAwareness.get_context()
        assert "Jest" in ctx
        assert ":" in ctx  # Contains time

    def test_get_context_with_session(self):
        """Test context with session duration."""
        ctx = TimeAwareness.get_context(session_seconds=7200)  # 2 hours
        assert "Rozmawiamy" in ctx
        assert "2h" in ctx

    def test_get_context_with_idle(self):
        """Test context with idle time."""
        ctx = TimeAwareness.get_context(idle_seconds=600)  # 10 min
        assert "Nie pisales" in ctx
        assert "10 min" in ctx

    def test_get_context_short_idle_ignored(self):
        """Test that short idle time is not shown."""
        ctx = TimeAwareness.get_context(idle_seconds=60)  # 1 min - too short
        assert "Nie pisales" not in ctx

    @patch("agent_core.homeostasis.time_awareness.datetime")
    def test_get_sleep_suggestion_late_night(self, mock_datetime):
        """Test sleep suggestion at late night."""
        mock_datetime.now.return_value = datetime(2026, 2, 2, 23, 30)
        suggestion = TimeAwareness.get_sleep_suggestion(idle_seconds=2000)
        assert suggestion is not None
        assert "spac" in suggestion.lower()

    @patch("agent_core.homeostasis.time_awareness.datetime")
    def test_get_sleep_suggestion_long_idle(self, mock_datetime):
        """Test sleep suggestion for very long idle (daytime)."""
        mock_datetime.now.return_value = datetime(2026, 2, 2, 14, 0)  # 14:00
        suggestion = TimeAwareness.get_sleep_suggestion(idle_seconds=8000)  # > 2h
        assert suggestion is not None
        assert "ok" in suggestion.lower()

    def test_get_sleep_suggestion_none(self):
        """Test no sleep suggestion for normal activity."""
        suggestion = TimeAwareness.get_sleep_suggestion(idle_seconds=300)  # 5 min
        assert suggestion is None

    def test_get_wakeup_greeting_long_sleep(self):
        """Test wakeup greeting after long sleep."""
        greeting = TimeAwareness.get_wakeup_greeting(sleep_seconds=36000)  # 10h
        assert "Spales dlugo" in greeting

    def test_get_wakeup_greeting_medium(self):
        """Test wakeup greeting after medium break."""
        greeting = TimeAwareness.get_wakeup_greeting(sleep_seconds=5400)  # 1.5h
        assert "Nie bylo Cie" in greeting

    def test_get_wakeup_greeting_short(self):
        """Test wakeup greeting after short break."""
        greeting = TimeAwareness.get_wakeup_greeting(sleep_seconds=1800)  # 30 min
        assert "Wracasz" in greeting

    @patch("agent_core.homeostasis.time_awareness.datetime")
    def test_get_day_context(self, mock_datetime):
        """Test day context formatting."""
        mock_datetime.now.return_value = datetime(2026, 2, 7, 9, 0)  # Saturday morning
        ctx = TimeAwareness.get_day_context()
        assert "sobota" in ctx
        assert "ranek" in ctx or "przedpoludnie" in ctx
