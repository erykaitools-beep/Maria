"""Tests for D4 mode-aware learning (2026-04-26).

Covers all three layers:
- W1: ``ModePostmortemRecorder`` captures REDUCED → ACTIVE episodes.
- W2: ``ModeAnalyzer`` clusters recurring root causes and posts to bulletin.
- W3: ``PlannerCore._apply_mode_aware_defer`` rewrites plans to NOOP when
  bulletin advisory has ``mode_aware=True`` and the current hour matches.
- Core hook in ``HomeostasisCore._transition_mode``.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_core.self_analysis.mode_postmortem import (
    ModePostmortemRecorder,
    ModePostmortem,
    alerts_signature,
)
from agent_core.self_analysis.mode_analyzer import (
    ModeAnalyzer,
    ModePattern,
    _hour_bucket,
)
from agent_core.memory.manager import MemoryManager
from agent_core.llm.manager import LLMManager
from agent_core.tests.spec_helpers import specced


# =============================================================================
# alerts_signature
# =============================================================================


class TestAlertsSignature:

    def test_empty_returns_none_marker(self):
        assert alerts_signature([]) == "none"
        assert alerts_signature([""]) == "other"

    def test_cpu_alert_recognised(self):
        assert "cpu" in alerts_signature(["ALERT: CPU saturated (97%)"]).split("|")

    def test_combined_alerts_sorted(self):
        sig = alerts_signature([
            "ALERT: CPU saturated", "ALERT: temp high",
        ])
        assert sig == "cpu|thermal"

    def test_unknown_alert_falls_to_other(self):
        assert alerts_signature(["something obscure"]) == "other"

    def test_mixed_recognised_and_unknown(self):
        assert "cpu" in alerts_signature([
            "weird stuff", "ALERT: cpu high",
        ]).split("|")


# =============================================================================
# ModePostmortemRecorder (W1)
# =============================================================================


class TestModePostmortemRecorder:

    def _recorder(self, tmp_path):
        return ModePostmortemRecorder(
            postmortem_path=tmp_path / "mode_postmortems.jsonl",
        )

    def test_no_pending_initially(self, tmp_path):
        rec = self._recorder(tmp_path)
        assert not rec.has_pending

    def test_note_entry_marks_pending(self, tmp_path):
        rec = self._recorder(tmp_path)
        rec.note_entry(metrics={"cpu_load": 90}, alerts=["ALERT: CPU"])
        assert rec.has_pending

    def test_note_exit_without_entry_returns_none(self, tmp_path):
        rec = self._recorder(tmp_path)
        result = rec.note_exit(metrics={}, alerts=[])
        assert result is None

    def test_note_exit_writes_postmortem(self, tmp_path):
        rec = self._recorder(tmp_path)
        rec.note_entry(
            timestamp=time.time() - 30,
            tick_count=100,
            metrics={"cpu_load": 95.0, "ram_available_pct": 60},
            alerts=["ALERT: CPU saturated"],
        )
        result = rec.note_exit(
            tick_count=130,
            metrics={"cpu_load": 50.0},
            alerts=[],
            health_score=0.85,
        )
        assert result is not None
        assert isinstance(result, ModePostmortem)
        assert result.from_mode == "reduced"
        assert result.to_mode == "active"
        assert result.duration_sec == pytest.approx(30, abs=2)
        assert result.alerts_signature == "cpu"
        assert result.entry_metrics["cpu_load"] == 95.0
        assert result.exit_tick == 130
        assert result.health_score_at_exit == pytest.approx(0.85)
        assert not rec.has_pending

        path = tmp_path / "mode_postmortems.jsonl"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8").strip())
        assert data["postmortem_id"] == result.postmortem_id

    def test_discard_pending_clears_state(self, tmp_path):
        rec = self._recorder(tmp_path)
        rec.note_entry(metrics={}, alerts=[])
        rec.discard_pending()
        assert not rec.has_pending

    def test_get_recent_filters_by_window(self, tmp_path):
        rec = self._recorder(tmp_path)
        # Old episode (10 days ago)
        rec.note_entry(timestamp=time.time() - 10 * 86400)
        rec.note_exit()
        # Recent episode (1 hour ago)
        rec.note_entry(timestamp=time.time() - 3600)
        rec.note_exit()

        all_recent = rec.get_recent(window_seconds=7 * 86400)
        assert len(all_recent) == 1

        wide = rec.get_recent(window_seconds=30 * 86400)
        assert len(wide) == 2

    def test_chained_analyzer_invoked_on_exit(self, tmp_path):
        rec = self._recorder(tmp_path)
        analyzer = specced(ModeAnalyzer)
        rec.set_analyzer(analyzer)
        rec.note_entry(metrics={}, alerts=[])
        rec.note_exit(metrics={}, alerts=[])
        analyzer.analyze.assert_called_once()


# =============================================================================
# ModeAnalyzer (W2)
# =============================================================================


class _StubRecorder:
    def __init__(self, records):
        self._records = records

    def get_recent(self, window_seconds: float = 7 * 86400):
        cutoff = time.time() - window_seconds
        return [r for r in self._records if r.get("entry_ts", 0) >= cutoff]


def _pm_record(
    sig: str,
    hour: int,
    action: str = None,
    duration: float = 30.0,
    age_sec: float = 3600,
):
    return {
        "postmortem_id": f"pm-{sig}-{hour}-{int(age_sec)}",
        "alerts_signature": sig,
        "hour_of_day_berlin": hour,
        "active_action_type": action,
        "duration_sec": duration,
        "entry_ts": time.time() - age_sec,
        "exit_ts": time.time() - age_sec + duration,
    }


class TestModeAnalyzer:

    def test_no_recorder_returns_empty(self):
        an = ModeAnalyzer(postmortem_recorder=None)
        report = an.analyze(force=True)
        assert report.patterns == []
        assert report.total_postmortems == 0

    def test_below_threshold_no_pattern(self):
        rec = _StubRecorder([_pm_record("cpu", 10)])
        an = ModeAnalyzer(postmortem_recorder=rec)
        report = an.analyze(force=True)
        assert report.patterns == []
        assert report.total_postmortems == 1

    def test_at_threshold_emits_pattern(self):
        rec = _StubRecorder([
            _pm_record("cpu", 10, action="learn"),
            _pm_record("cpu", 11, action="learn"),
        ])
        an = ModeAnalyzer(postmortem_recorder=rec, threshold=2)
        report = an.analyze(force=True)
        assert len(report.patterns) == 1
        p = report.patterns[0]
        assert p.alerts_signature == "cpu"
        assert p.hour_bucket == "morning"
        assert p.active_action_type == "learn"
        assert p.count == 2

    def test_distinct_buckets_kept_separate(self):
        rec = _StubRecorder([
            _pm_record("cpu", 10, action="learn"),
            _pm_record("cpu", 11, action="learn"),
            _pm_record("cpu", 20, action="learn"),
            _pm_record("cpu", 21, action="learn"),
        ])
        an = ModeAnalyzer(postmortem_recorder=rec, threshold=2)
        report = an.analyze(force=True)
        buckets = sorted(p.hour_bucket for p in report.patterns)
        assert buckets == ["evening", "morning"]

    def test_dedup_no_double_post(self):
        from agent_core.bulletin import BulletinStore
        from agent_core.bulletin.bulletin_model import EntryType

        bulletin = BulletinStore(
            path=Path("/tmp/__d4_dedup.jsonl"),
        )
        # Wipe any leftovers
        bulletin._entries = {}

        rec = _StubRecorder([
            _pm_record("cpu", 10, action="learn"),
            _pm_record("cpu", 11, action="learn"),
        ])
        an = ModeAnalyzer(
            postmortem_recorder=rec,
            bulletin_store=bulletin,
            threshold=2,
        )
        an.analyze(force=True)
        an.analyze(force=True)
        entries = bulletin.get_by_type(EntryType.IMPROVEMENT)
        assert len(entries) == 1
        assert entries[0].metadata.get("mode_aware") is True
        assert entries[0].metadata.get("action_hint") == "learn"
        # Cleanup
        try:
            Path("/tmp/__d4_dedup.jsonl").unlink()
        except OSError:
            pass

    def test_should_run_respects_cooldown(self):
        an = ModeAnalyzer(postmortem_recorder=_StubRecorder([]), cooldown_sec=600)
        now = time.time()
        an._last_run_ts = now
        assert an.should_run(now=now + 300) is False
        assert an.should_run(now=now + 700) is True


class TestHourBucket:

    def test_unknown_hour(self):
        assert _hour_bucket(-1) == "unknown"

    @pytest.mark.parametrize("hour,bucket", [
        (6, "morning"), (11, "morning"),
        (12, "afternoon"), (17, "afternoon"),
        (18, "evening"), (21, "evening"),
        (22, "night"), (5, "night"), (0, "night"),
    ])
    def test_buckets(self, hour, bucket):
        assert _hour_bucket(hour) == bucket


# =============================================================================
# Planner W3: mode-aware defer
# =============================================================================


class TestPlannerModeAwareDefer:

    def _make_planner(self, tmp_path):
        from agent_core.planner.planner_core import PlannerCore
        from agent_core.bulletin import BulletinStore
        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        bulletin = BulletinStore(
            path=tmp_path / "cognitive_bulletin.jsonl",
        )
        planner.set_bulletin_store(bulletin)
        return planner, bulletin

    def _post_advisory(
        self, bulletin, action_hint, hour_bucket, mode_aware=True,
    ):
        from agent_core.bulletin.bulletin_model import EntryType
        return bulletin.create_and_post(
            entry_type=EntryType.IMPROVEMENT,
            topic=f"mode_loop:{hour_bucket}:{action_hint}",
            reason_code="mode_aware_pattern",
            summary="REDUCED loop test",
            requested_by="mode_analyzer",
            priority=0.85,
            metadata={
                "action_hint": action_hint,
                "mode_aware": mode_aware,
                "hour_bucket": hour_bucket,
            },
        )

    def _make_plan(self, action_type_str="learn"):
        from agent_core.planner.planner_model import (
            create_plan, ActionType,
        )
        return create_plan(
            goal_id="g1",
            goal_description="x",
            action_type=ActionType[action_type_str.upper()],
        )

    def test_defer_when_hour_matches(self, tmp_path):
        from agent_core.planner.planner_model import ActionType
        planner, bulletin = self._make_planner(tmp_path)
        self._post_advisory(bulletin, "learn", "morning")

        plan = self._make_plan("learn")
        with patch.object(planner, "_current_hour_bucket", return_value="morning"):
            planner._apply_bulletin_advisory(plan, trace=None)
            planner._apply_mode_aware_defer(plan, trace=None)

        assert plan.action_type == ActionType.NOOP
        assert plan.action_params["deferred_action"] == "learn"
        assert plan.action_params["hour_bucket"] == "morning"
        assert plan.action_params["reason"].startswith("mode_aware_defer:")

    def test_no_defer_when_hour_mismatches(self, tmp_path):
        from agent_core.planner.planner_model import ActionType
        planner, bulletin = self._make_planner(tmp_path)
        self._post_advisory(bulletin, "learn", "morning")

        plan = self._make_plan("learn")
        with patch.object(planner, "_current_hour_bucket", return_value="night"):
            planner._apply_bulletin_advisory(plan, trace=None)
            planner._apply_mode_aware_defer(plan, trace=None)

        assert plan.action_type == ActionType.LEARN
        assert "deferred_action" not in plan.action_params

    def test_no_defer_when_advisory_not_mode_aware(self, tmp_path):
        from agent_core.planner.planner_model import ActionType
        planner, bulletin = self._make_planner(tmp_path)
        self._post_advisory(
            bulletin, "learn", "morning", mode_aware=False,
        )

        plan = self._make_plan("learn")
        with patch.object(planner, "_current_hour_bucket", return_value="morning"):
            planner._apply_bulletin_advisory(plan, trace=None)
            planner._apply_mode_aware_defer(plan, trace=None)

        assert plan.action_type == ActionType.LEARN

    def test_no_defer_without_advisory(self, tmp_path):
        from agent_core.planner.planner_model import ActionType
        planner, _ = self._make_planner(tmp_path)
        plan = self._make_plan("learn")
        with patch.object(planner, "_current_hour_bucket", return_value="morning"):
            planner._apply_mode_aware_defer(plan, trace=None)
        assert plan.action_type == ActionType.LEARN

    def test_defer_writes_trace_step(self, tmp_path):
        planner, bulletin = self._make_planner(tmp_path)
        self._post_advisory(bulletin, "learn", "morning")

        class _Stub:
            def __init__(self):
                self.steps = []
            def add_step(self, source, action, status, payload):
                self.steps.append((source, action, status, payload))

        trace = _Stub()
        plan = self._make_plan("learn")
        with patch.object(planner, "_current_hour_bucket", return_value="morning"):
            planner._apply_bulletin_advisory(plan, trace=trace)
            planner._apply_mode_aware_defer(plan, trace=trace)

        defer_steps = [s for s in trace.steps if s[1] == "defer"]
        assert len(defer_steps) == 1
        assert defer_steps[0][0] == "mode_aware"
        assert defer_steps[0][2] == "applied"
        assert defer_steps[0][3]["deferred_action"] == "learn"


# =============================================================================
# Core integration: _transition_mode -> recorder
# =============================================================================


class TestCoreModePostmortemHook:

    def _make_core(self):
        from agent_core.homeostasis.core import HomeostasisCore
        return HomeostasisCore(
            memory_manager=specced(MemoryManager),
            llm_manager=specced(LLMManager),
        )

    def test_setter_stores_recorder(self):
        from agent_core.homeostasis.state_model import Mode
        core = self._make_core()
        rec = specced(ModePostmortemRecorder)
        core.set_mode_postmortem_recorder(rec)
        assert core._mode_postmortem_recorder is rec

    def test_entering_reduced_calls_note_entry(self):
        from agent_core.homeostasis.state_model import Mode
        core = self._make_core()
        rec = specced(ModePostmortemRecorder)
        core.set_mode_postmortem_recorder(rec)
        core.state.mode = Mode.ACTIVE

        core._transition_mode(Mode.ACTIVE, Mode.REDUCED)
        rec.note_entry.assert_called_once()
        rec.note_exit.assert_not_called()

    def test_reduced_to_active_calls_note_exit(self):
        from agent_core.homeostasis.state_model import Mode
        core = self._make_core()
        rec = specced(ModePostmortemRecorder)
        core.set_mode_postmortem_recorder(rec)
        core.state.mode = Mode.REDUCED

        core._transition_mode(Mode.REDUCED, Mode.ACTIVE)
        rec.note_exit.assert_called_once()

    def test_reduced_to_sleep_discards_pending(self):
        from agent_core.homeostasis.state_model import Mode
        core = self._make_core()
        rec = specced(ModePostmortemRecorder)
        core.set_mode_postmortem_recorder(rec)
        core.state.mode = Mode.REDUCED

        core._transition_mode(Mode.REDUCED, Mode.SLEEP)
        rec.discard_pending.assert_called_once()
        rec.note_exit.assert_not_called()

    def test_no_recorder_no_crash(self):
        from agent_core.homeostasis.state_model import Mode
        core = self._make_core()
        # No recorder wired — transition must still work.
        core._transition_mode(Mode.ACTIVE, Mode.REDUCED)
        assert core.state.mode == Mode.REDUCED
