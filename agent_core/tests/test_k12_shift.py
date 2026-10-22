"""Tests for the K12 analysis shift (window + daily wall-clock budget).

The shift concentrates K12's periodic self-analysis into the evening gap
between the learning window closing (18:59) and QUIET opening (22:00), and caps
how much heavy inference it may spend per day.
"""

import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from agent_core.self_analysis.shift import AnalysisShift, _parse_hours

BERLIN = ZoneInfo("Europe/Berlin")


def _at(hour, day=16, minute=0):
    return datetime(2026, 8, day, hour, minute, tzinfo=BERLIN)


@pytest.fixture
def shift(tmp_path, monkeypatch):
    """Shift with defaults, writing its ledger under tmp_path."""
    for var in (
        "K12_SHIFT_HOURS", "K12_SHIFT_BUDGET_MIN",
        "K12_SHIFT_MIN_GAP_MIN", "K12_SHIFT_ENABLED",
    ):
        monkeypatch.delenv(var, raising=False)
    return AnalysisShift(meta_dir=tmp_path)


class TestHourParsing:

    def test_parses_a_comma_list(self):
        assert _parse_hours("19,20,21") == (19, 20, 21)

    def test_ignores_junk_and_out_of_range(self):
        assert _parse_hours("19, x, 25, -3, 20") == (19, 20)

    def test_empty_string_yields_no_hours(self):
        assert _parse_hours("") == ()


class TestWindow:

    def test_default_window_is_the_gap_between_learning_and_quiet(self, shift):
        """09-18:59 is learning, 22:00-06:59 is QUIET. 19-21 is what is left."""
        assert shift.hours == (19, 20, 21)

    @pytest.mark.parametrize("hour", [19, 20, 21])
    def test_inside_window(self, shift, hour):
        assert shift.is_in_window(_at(hour)) is True

    @pytest.mark.parametrize("hour", [8, 9, 13, 18, 22, 23, 3])
    def test_outside_window(self, shift, hour):
        assert shift.is_in_window(_at(hour)) is False

    def test_learning_hours_are_never_in_the_window(self, shift):
        """The whole point: the heavy call must not land during learning."""
        assert not any(shift.is_in_window(_at(h)) for h in range(9, 19))

    def test_empty_hour_list_means_no_restriction(self, tmp_path, monkeypatch):
        """An operator who clears the list has opted out, not misconfigured."""
        monkeypatch.setenv("K12_SHIFT_HOURS", "")
        s = AnalysisShift(meta_dir=tmp_path)
        assert s.is_in_window(_at(3)) is True


class TestPeriodicDecision:

    def test_allowed_inside_window(self, shift):
        allowed, reason = shift.should_run_periodic(_at(20))
        assert allowed is True
        assert reason == "in_shift"

    def test_held_outside_window_with_a_stated_reason(self, shift):
        allowed, reason = shift.should_run_periodic(_at(13))
        assert allowed is False
        assert "outside_window" in reason

    def test_disabled_shift_states_why(self, tmp_path, monkeypatch):
        monkeypatch.setenv("K12_SHIFT_ENABLED", "false")
        s = AnalysisShift(meta_dir=tmp_path)
        allowed, reason = s.should_run_periodic(_at(20))
        assert allowed is False
        assert reason == "shift_disabled"

    def test_min_gap_blocks_a_second_run_too_soon(self, shift):
        shift.record_run(60.0, now=_at(19, minute=0))
        allowed, reason = shift.should_run_periodic(_at(19, minute=30))
        assert allowed is False
        assert "min_gap" in reason

    def test_min_gap_clears_after_the_gap(self, shift):
        shift.record_run(60.0, now=_at(19, minute=0))
        allowed, _ = shift.should_run_periodic(_at(20, minute=5))
        assert allowed is True

    def test_min_gap_paces_the_shift_to_about_three_passes(self, shift):
        """The shift, not the 4h round-the-clock interval, sets the pace.

        With the 4h interval still gating, the next mark after a 19:00 run
        falls at 23:00 -- outside the window -- so the evening would get one
        pass and the 90 min budget could never be spent.
        """
        passes = 0
        for hour in (19, 20, 21):
            for minute in (0, 30):
                if shift.should_run_periodic(_at(hour, minute=minute))[0]:
                    shift.record_run(120.0, now=_at(hour, minute=minute))
                    passes += 1
        assert passes == 3


class TestBudget:

    def test_budget_is_a_ceiling_not_a_quota(self, shift):
        """Nothing forces the analyst to spend the remainder of the budget."""
        assert shift.remaining_sec(_at(20)) == pytest.approx(90 * 60)
        allowed, _ = shift.should_run_periodic(_at(20))
        assert allowed is True

    def test_exhausted_budget_stops_the_periodic_trigger(self, shift):
        shift.record_run(91 * 60.0, now=_at(19))
        allowed, reason = shift.should_run_periodic(_at(21))
        assert allowed is False
        assert "budget_exhausted" in reason

    def test_spend_accumulates_across_runs(self, shift):
        shift.record_run(600.0, now=_at(19))
        shift.record_run(300.0, now=_at(20))
        assert shift.spent_sec(_at(20)) == pytest.approx(900.0)
        assert shift.remaining_sec(_at(20)) == pytest.approx(90 * 60 - 900)

    def test_budget_resets_on_the_next_day(self, shift):
        shift.record_run(91 * 60.0, now=_at(20, day=16))
        assert shift.should_run_periodic(_at(20, day=16))[0] is False
        assert shift.should_run_periodic(_at(20, day=17))[0] is True

    def test_ledger_survives_a_restart(self, tmp_path, monkeypatch):
        """Budget lives on disk; a daemon restart must not hand out a fresh 90 min."""
        monkeypatch.delenv("K12_SHIFT_BUDGET_MIN", raising=False)
        first = AnalysisShift(meta_dir=tmp_path)
        first.record_run(80 * 60.0, now=_at(19))

        second = AnalysisShift(meta_dir=tmp_path)
        assert second.spent_sec(_at(20)) == pytest.approx(80 * 60.0)

    def test_corrupt_ledger_does_not_wedge_the_shift(self, tmp_path, monkeypatch):
        monkeypatch.delenv("K12_SHIFT_BUDGET_MIN", raising=False)
        (tmp_path / "k12_shift_state.json").write_text("{ not json", encoding="utf-8")
        s = AnalysisShift(meta_dir=tmp_path)
        assert s.should_run_periodic(_at(20))[0] is True

    def test_negative_duration_is_ignored(self, shift):
        shift.record_run(-5.0, now=_at(20))
        assert shift.spent_sec(_at(20)) == 0.0

    def test_window_never_crosses_midnight(self, shift):
        """The date-keyed ledger is only safe while the window sits in one date.

        A window spanning midnight would split one evening across two budgets --
        the trap that forced the night exam pool to be rekeyed by dark stretch
        rather than by date on 2026-08-15.
        """
        assert 23 not in shift.hours and 0 not in shift.hours
        keys = {shift._today_key(_at(h)) for h in shift.hours}
        assert len(keys) == 1


class TestStatus:

    def test_status_reports_the_ledger(self, shift):
        shift.record_run(30 * 60.0, now=_at(19))
        st = shift.status(_at(20))
        assert st["window_hours"] == [19, 20, 21]
        assert st["in_window"] is True
        assert st["spent_min"] == pytest.approx(30.0)
        assert st["remaining_min"] == pytest.approx(60.0)
        assert st["runs_today"] == 1

    def test_status_explains_a_held_shift(self, shift):
        st = shift.status(_at(11))
        assert st["periodic_allowed"] is False
        assert "outside_window" in st["reason"]


class TestPlannerGating:
    """The shift gates the SCHEDULED analysis only. Alarms must never wait."""

    def _planner(self, tmp_path, monkeypatch, hour):
        from agent_core.planner.planner_core import PlannerCore
        import agent_core.self_analysis.shift as shift_mod

        monkeypatch.setattr(shift_mod, "berlin_now", lambda: _at(hour))

        planner = PlannerCore(
            state_path=tmp_path / "planner_state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )

        class _StubAnalysis:
            def __init__(self, meta_dir):
                self.shift = AnalysisShift(meta_dir=meta_dir)

        planner._self_analysis = _StubAnalysis(tmp_path)
        # Old enough that the periodic trigger is otherwise due.
        planner._state.last_self_analysis_ts = 0.0
        return planner

    def test_periodic_fires_inside_the_shift(self, tmp_path, monkeypatch):
        planner = self._planner(tmp_path, monkeypatch, hour=20)
        plan = planner._maybe_self_analyze({})
        assert plan is not None
        assert plan.action_params["trigger"] == "periodic"

    def test_shift_paces_instead_of_the_4h_interval(self, tmp_path, monkeypatch):
        """A run 10 min ago is not 4h ago, yet the shift's min-gap decides."""
        import time as _t
        planner = self._planner(tmp_path, monkeypatch, hour=20)
        planner._state.last_self_analysis_ts = _t.time() - 3600  # 1h, under 4h
        assert planner._maybe_self_analyze({}) is not None

    def test_disabled_shift_restores_the_4h_cadence(self, tmp_path, monkeypatch):
        import time as _t
        monkeypatch.setenv("K12_SHIFT_ENABLED", "false")
        planner = self._planner(tmp_path, monkeypatch, hour=13)
        planner._state.last_self_analysis_ts = _t.time() - 3600  # under 4h
        assert planner._maybe_self_analyze({}) is None
        planner._state.last_self_analysis_ts = _t.time() - 5 * 3600  # over 4h
        assert planner._maybe_self_analyze({}) is not None

    def test_periodic_is_held_during_the_learning_window(self, tmp_path, monkeypatch):
        """13:00 is prime learning time -- the heavy call must not land here."""
        planner = self._planner(tmp_path, monkeypatch, hour=13)
        assert planner._maybe_self_analyze({}) is None

    def test_held_periodic_does_not_burn_the_cooldown(self, tmp_path, monkeypatch):
        """A held trigger must stay due, so it fires when the window opens."""
        planner = self._planner(tmp_path, monkeypatch, hour=13)
        planner._maybe_self_analyze({})
        assert planner._state.last_self_analysis_ts == 0.0

    def test_low_retention_alarm_fires_outside_the_window(self, tmp_path, monkeypatch):
        """An alarm that waits until 19:00 is not an alarm."""
        planner = self._planner(tmp_path, monkeypatch, hour=13)
        plan = planner._maybe_self_analyze({"retention_rate": 0.1})
        assert plan is not None
        assert plan.action_params["trigger"] == "low_retention"

    def test_k9_alarm_fires_outside_the_window(self, tmp_path, monkeypatch):
        planner = self._planner(tmp_path, monkeypatch, hour=4)

        class _K9:
            def needs_human(self):
                return True

        planner._meta_cognition = _K9()
        plan = planner._maybe_self_analyze({})
        assert plan is not None
        assert plan.action_params["trigger"] == "k9_needs_human"

    def test_exhausted_budget_holds_periodic_but_not_alarms(self, tmp_path, monkeypatch):
        planner = self._planner(tmp_path, monkeypatch, hour=20)
        planner._self_analysis.shift.record_run(95 * 60.0, now=_at(20))

        assert planner._maybe_self_analyze({}) is None
        plan = planner._maybe_self_analyze({"retention_rate": 0.1})
        assert plan is not None
        assert plan.action_params["trigger"] == "low_retention"


class TestSafeShiftStatus:
    """A footer must never be able to cost the operator the whole report.

    The K12 Telegram notification sits inside a bare `except Exception: pass`,
    so anything raising while the card is built silently drops the report.
    """

    def test_returns_status_when_available(self, tmp_path, monkeypatch):
        from agent_core.self_analysis.shift import safe_shift_status
        monkeypatch.delenv("K12_SHIFT_BUDGET_MIN", raising=False)
        analysis = SimpleNamespace(shift=AnalysisShift(meta_dir=tmp_path))
        assert safe_shift_status(analysis)["budget_min"] == 90.0

    def test_missing_shift_attribute_yields_none_not_an_exception(self):
        """Reaching for `.shift` must happen INSIDE the guard.

        Passing `analysis.shift` as an argument would raise at the call site,
        before the guard could catch anything -- which is exactly how the
        handler test caught this: the notification was never sent at all.
        """
        from agent_core.self_analysis.shift import safe_shift_status
        assert safe_shift_status(SimpleNamespace()) is None

    def test_raising_status_yields_none(self):
        from agent_core.self_analysis.shift import safe_shift_status

        class _Exploding:
            def status(self):
                raise RuntimeError("ledger on fire")

        assert safe_shift_status(SimpleNamespace(shift=_Exploding())) is None

    def test_card_still_builds_without_a_footer(self):
        """No status -> card goes out, just without the pacing line."""
        from agent_core.self_analysis.recommendation_model import (
            AnalysisReport, format_report_for_telegram,
        )
        report = AnalysisReport(model="nemotron", summary="cos sie dzieje")
        summary, recs, issues = format_report_for_telegram(report, None)
        assert "cos sie dzieje" in summary
        assert "zmiana:" not in summary
