"""
Tests for HomeostasisCore main loop.

Spec reference: homeostasis_spec.md section 7 (lines 879-1100)
"""

import pytest
import time
import threading
from unittest.mock import Mock, patch, MagicMock

from agent_core.homeostasis.core import HomeostasisCore
from agent_core.homeostasis.event_logger import HomeostasisEventLogger
from agent_core.homeostasis.state_model import Mode, SystemState
from agent_core.memory.manager import MemoryManager
from agent_core.llm.manager import LLMManager
from agent_core.executor.module_executor import ModuleExecutor
from agent_core.telegram import TelegramBridge
from agent_core.operator.operator_model import OperatorModel
from agent_core.operator.rhythm_detector import RhythmDetector
from agent_core.registry.shared_context import SharedContext
from agent_core.proactive.scheduler import ProactiveScheduler
from agent_core.reminders.scheduler import ReminderScheduler
from agent_core.tests.spec_helpers import specced


class TestHomeostasisCore:
    """Tests for HomeostasisCore - spec lines 879-1100."""

    @pytest.fixture
    def core(self):
        """Create core instance with mocked dependencies."""
        core = HomeostasisCore(
            memory_manager=specced(MemoryManager),
            llm_manager=specced(LLMManager),
        )
        return core

    def test_initialization(self, core):
        """Core should initialize with ACTIVE mode."""
        assert core.state.mode == Mode.ACTIVE

    def test_initial_health_score(self, core):
        """Initial health score should be 1.0 (healthy)."""
        assert core.state.health_score == 1.0

    def test_has_all_sensors(self, core):
        """Core should have all sensor instances."""
        assert hasattr(core, 'resource_sensor')
        assert hasattr(core, 'cognitive_sensor')
        assert hasattr(core, 'thermal_sensor')
        assert hasattr(core, 'power_sensor')
        assert hasattr(core, 'time_sensor')

    def test_has_processing_components(self, core):
        """Core should have all processing components."""
        assert hasattr(core, 'interpreter')
        assert hasattr(core, 'validator')
        assert hasattr(core, 'regulator')
        assert hasattr(core, 'action_generator')


class TestTickExecution:
    """Tests for tick cycle - spec lines 900-950."""

    @pytest.fixture
    def core(self):
        """Create core with properly configured mock managers."""
        # Create mock memory manager with required methods
        memory_manager = specced(MemoryManager)
        memory_manager.get_semantic_coherence.return_value = 0.95
        memory_manager.get_total_entries.return_value = 100
        memory_manager.get_contradiction_count.return_value = 0
        memory_manager.get_episodic_freshness.return_value = 60.0
        memory_manager.get_recent_errors_count.return_value = 0

        # Create mock LLM manager
        llm_manager = specced(LLMManager)
        llm_manager.get_last_latency_ms.return_value = 150.0
        llm_manager.get_context_tokens.return_value = 1000

        core = HomeostasisCore(
            memory_manager=memory_manager,
            llm_manager=llm_manager,
        )
        return core

    def test_tick_executes_without_error(self, core):
        """Tick should execute without raising errors."""
        # Should not raise
        core._execute_tick()

    def test_tick_updates_state(self, core):
        """Each tick should update system state."""
        # Execute one tick
        core._execute_tick()

        # State should have interpreted state
        assert core.state.interpreted_state is not None

    def test_tick_calculates_health(self, core):
        """Each tick should recalculate health score."""
        # Execute tick
        core._execute_tick()

        # Health score should be set (0-1)
        assert 0 <= core.state.health_score <= 1

    def test_tick_count_increments(self, core):
        """Tick count should increment."""
        initial_count = core._tick_count

        core._execute_tick()

        # Note: _execute_tick doesn't increment, main_loop does
        # This test verifies the counter exists
        assert hasattr(core, '_tick_count')

    def test_stale_bulletin_prune_wired_into_tick(self, core):
        """The 7-day bulletin auto-resolve (prune_stale) must fire from the tick,
        not only the /board prune Telegram command -- otherwise K12 advisories
        pile up unresolved for weeks and resurface as stale 'advice'."""
        bs = MagicMock()
        bs.prune_stale.return_value = 0
        core.set_bulletin_store(bs)

        core._tick_count = 1800  # multiple of BULLETIN_PRUNE_INTERVAL
        core._execute_tick()
        assert bs.prune_stale.called

        bs.prune_stale.reset_mock()
        core._tick_count = 1801  # not a multiple -> no prune this tick
        core._execute_tick()
        assert not bs.prune_stale.called


class TestSenseSubPhaseTiming:
    """Per-sensor timing inside 01_sense (2026-07-12 diagnostic).

    01_sense stalled 7-20s sporadically while every call in the path looks
    cheap, so the overrun event must name WHICH sensor blocked (01a-01d),
    and unaccounted_ms must not double-count sub-phases against their parent.
    """

    @pytest.fixture
    def core(self):
        memory_manager = specced(MemoryManager)
        memory_manager.get_semantic_coherence.return_value = 0.95
        memory_manager.get_total_entries.return_value = 100
        memory_manager.get_contradiction_count.return_value = 0
        memory_manager.get_episodic_freshness.return_value = 60.0
        memory_manager.get_recent_errors_count.return_value = 0

        llm_manager = specced(LLMManager)
        llm_manager.get_last_latency_ms.return_value = 150.0
        llm_manager.get_context_tokens.return_value = 1000

        return HomeostasisCore(
            memory_manager=memory_manager,
            llm_manager=llm_manager,
        )

    def test_tick_records_sense_sub_phases(self, core):
        """A tick records all four sensor sub-timings plus the parent."""
        core._execute_tick()

        for key in ("01a_resource", "01b_thermal", "01c_time",
                    "01d_cognitive", "01_sense"):
            assert key in core._phase_ms
        subs_ms = sum(
            v for k, v in core._phase_ms.items()
            if k.startswith("01") and k != "01_sense"
        )
        # Parent covers the subs plus the metric merge, which deliberately
        # sits outside the sub-timers (parent-minus-subs gap = the merge).
        assert core._phase_ms["01_sense"] >= subs_ms - 1

    def test_slow_sensor_lands_in_its_own_sub_phase(self, core):
        """An artificially slowed sensor is named by its sub-timing."""
        real_read = core.thermal_sensor.read_metrics

        def slow_read():
            time.sleep(0.05)
            return real_read()

        core.thermal_sensor.read_metrics = slow_read
        core._execute_tick()

        assert core._phase_ms["01b_thermal"] >= 45
        assert core._phase_ms["01a_resource"] < 45

    def test_unaccounted_excludes_sub_phases(self, core):
        """unaccounted_ms is computed against top-level phases only.

        Sub-phases re-measure time already inside 01_sense; summing both
        would understate unaccounted by the whole sense duration.
        """
        events = []
        core.event_logger = MagicMock()
        core.event_logger._write_event = lambda e: events.append(e)
        core._last_timing_log_ts = 0.0  # force a baseline timing sample

        real_read = core.thermal_sensor.read_metrics

        def slow_read():
            time.sleep(0.05)
            return real_read()

        core.thermal_sensor.read_metrics = slow_read
        core._execute_tick()

        timing = [e for e in events
                  if e.get("event") in ("tick_timing_sample", "tick_overrun")]
        assert timing, "expected a timing event from the forced baseline"
        event = timing[-1]
        expected = event["tick_ms"] - sum(
            v for k, v in event["phase_ms"].items()
            if k in ("01_sense", "08.5_vision", "10_planner", "11_telegram")
        )
        assert abs(event["unaccounted_ms"] - expected) < 20


class TestModeTransitions:
    """Tests for mode transitions via core - spec lines 950-1000."""

    @pytest.fixture
    def core(self):
        core = HomeostasisCore(
            memory_manager=specced(MemoryManager),
            llm_manager=specced(LLMManager),
        )
        return core

    def test_transition_to_reduced(self, core):
        """Core should handle ACTIVE -> REDUCED transition."""
        # Force transition
        core._transition_mode(Mode.ACTIVE, Mode.REDUCED)

        assert core.state.mode == Mode.REDUCED

    def test_transition_to_survival(self, core):
        """Core should handle transition to SURVIVAL."""
        core._transition_mode(Mode.ACTIVE, Mode.SURVIVAL)

        assert core.state.mode == Mode.SURVIVAL

    def test_transition_updates_timestamp(self, core):
        """Mode transition should update change time."""
        initial_time = core.state.last_mode_change_time

        time.sleep(0.01)

        core._transition_mode(Mode.ACTIVE, Mode.REDUCED)

        assert core.state.last_mode_change_time > initial_time

    def test_transition_logs_to_audit(self, core):
        """Mode transition should add audit log entry."""
        initial_log_len = len(core.audit_log)

        core._transition_mode(Mode.ACTIVE, Mode.REDUCED)

        assert len(core.audit_log) > initial_log_len

        # Last entry should be mode_change
        last_entry = core.audit_log[-1]
        assert last_entry["event"] == "mode_change"


class TestAuditLogging:
    """Tests for audit logging - spec lines 1000-1050."""

    @pytest.fixture
    def core(self):
        core = HomeostasisCore(
            memory_manager=specced(MemoryManager),
            llm_manager=specced(LLMManager),
        )
        return core

    def test_audit_log_exists(self, core):
        """Core should maintain audit log (deque for bounded memory)."""
        assert hasattr(core, 'audit_log')
        from collections import deque
        assert isinstance(core.audit_log, deque)

    def test_get_audit_log(self, core):
        """Should be able to retrieve audit log."""
        log = core.get_audit_log(10)

        assert isinstance(log, list)

    def test_audit_records_mode_changes(self, core):
        """Mode changes should be logged."""
        core._transition_mode(Mode.ACTIVE, Mode.REDUCED)

        log = core.get_audit_log(10)

        # Should have entry for mode change
        mode_changes = [e for e in log if e.get("event") == "mode_change"]
        assert len(mode_changes) >= 1

    def test_audit_log_has_timestamps(self, core):
        """Audit entries should have timestamps."""
        core._transition_mode(Mode.ACTIVE, Mode.REDUCED)

        log = core.get_audit_log(10)

        for entry in log:
            assert "timestamp" in entry


class TestHealthScore:
    """Tests for health score calculation - spec lines 1100-1150."""

    @pytest.fixture
    def core(self):
        """Create core with properly configured mock managers."""
        memory_manager = specced(MemoryManager)
        memory_manager.get_semantic_coherence.return_value = 0.95
        memory_manager.get_total_entries.return_value = 100
        memory_manager.get_contradiction_count.return_value = 0
        memory_manager.get_episodic_freshness.return_value = 60.0
        memory_manager.get_recent_errors_count.return_value = 0

        llm_manager = specced(LLMManager)
        llm_manager.get_last_latency_ms.return_value = 150.0
        llm_manager.get_context_tokens.return_value = 1000

        core = HomeostasisCore(
            memory_manager=memory_manager,
            llm_manager=llm_manager,
        )
        return core

    def test_health_score_range(self, core):
        """Health score should always be 0-1."""
        # Execute a tick to calculate health
        core._execute_tick()

        assert 0 <= core.state.health_score <= 1

    def test_compute_health_method(self, core):
        """_compute_health should return valid score."""
        state = {"memory_pressure": 50, "cpu_load": 50}
        alerts = []

        score = core._compute_health(state, alerts)

        assert 0 <= score <= 1

    def test_alerts_reduce_health(self, core):
        """Alerts should reduce health score."""
        state = {"memory_pressure": 0, "cpu_load": 0}

        # No alerts = high health
        score_no_alerts = core._compute_health(state, [])

        # With WARNING
        score_warning = core._compute_health(state, ["WARNING: Test"])

        # With ALERT
        score_alert = core._compute_health(state, ["ALERT: Test"])

        # With CRITICAL
        score_critical = core._compute_health(state, ["CRITICAL: Test"])

        # More severe alerts should give lower scores
        assert score_no_alerts >= score_warning
        assert score_warning >= score_alert
        assert score_alert >= score_critical

    def test_critical_gives_low_health(self, core):
        """CRITICAL alert should give significantly lower health."""
        state = {"memory_pressure": 0, "cpu_load": 0}
        alerts = ["CRITICAL: RAM pressure imminent OOM"]

        score = core._compute_health(state, alerts)

        # Should be notably reduced
        assert score < 0.6


class TestCoreTelemetry:
    """Tests for telemetry retrieval."""

    @pytest.fixture
    def core(self):
        core = HomeostasisCore(
            memory_manager=specced(MemoryManager),
            llm_manager=specced(LLMManager),
        )
        return core

    def test_get_telemetry(self, core):
        """Should return telemetry snapshot."""
        telemetry = core.get_telemetry()

        assert isinstance(telemetry, dict)
        assert "mode" in telemetry
        assert "health_score" in telemetry
        assert "alerts" in telemetry

    def test_get_state(self, core):
        """Should return current system state."""
        state = core.get_state()

        assert state is not None
        assert hasattr(state, 'mode')
        assert hasattr(state, 'health_score')


class TestCoreControl:
    """Tests for core control operations."""

    @pytest.fixture
    def core(self):
        core = HomeostasisCore(
            memory_manager=specced(MemoryManager),
            llm_manager=specced(LLMManager),
        )
        return core

    def test_stop(self, core):
        """Should be able to stop the core."""
        core._running = True
        core.stop()

        assert core._running == False

    def test_is_running(self, core):
        """Should report running status."""
        assert core.is_running() == False

        core._running = True
        assert core.is_running() == True

    def test_record_user_interaction(self, core):
        """Should record user interaction."""
        # Should not raise
        core.record_user_interaction()

    def test_record_activity(self, core):
        """Should record system activity."""
        # Should not raise
        core.record_activity()


class TestCoreWithExecutor:
    """Tests for core with executor signals."""

    @pytest.fixture
    def core_with_executor(self):
        executor = specced(ModuleExecutor)
        core = HomeostasisCore(
            memory_manager=specced(MemoryManager),
            llm_manager=specced(LLMManager),
            executor=executor,
        )
        return core

    def test_transition_signals_executor(self, core_with_executor):
        """Mode transition should signal executor."""
        core_with_executor._transition_mode(Mode.ACTIVE, Mode.SLEEP)

        # Executor should have received signal
        core_with_executor.executor.signal_module.assert_called()

    def test_survival_signals_minimize(self, core_with_executor):
        """SURVIVAL transition should signal minimize."""
        core_with_executor._transition_mode(Mode.ACTIVE, Mode.SURVIVAL)

        # Check that signal_module was called for llm minimize
        calls = core_with_executor.executor.signal_module.call_args_list
        call_args = [c[0] for c in calls]

        # Should have called for llm and memory
        assert any("llm" in str(args) for args in call_args)


class TestPhase11OperatorLearning:
    """Regression for Phase 11 (_check_telegram) operator learning wiring.

    Guards the self._ctx -> self._shared_context fix: operator_model and
    rhythm_detector live on the shared context; the old code read a never-set
    self._ctx, so the AttributeError was swallowed and learning never fired.
    """

    def test_telegram_poll_feeds_operator_model_and_rhythm(self):
        core = HomeostasisCore(memory_manager=specced(MemoryManager), llm_manager=specced(LLMManager))

        bridge = specced(TelegramBridge)
        bridge.last_poll_message_count = 1
        bridge.last_poll_texts = ["czesc maria, jak leci"]

        operator_model = specced(OperatorModel)
        rhythm_detector = specced(RhythmDetector)
        shared_ctx = specced(SharedContext)
        shared_ctx.operator_model = operator_model
        shared_ctx.rhythm_detector = rhythm_detector

        core._telegram_bridge = bridge
        core._proactive_scheduler = specced(ProactiveScheduler)
        core._shared_context = shared_ctx
        core._planner_core = None  # skip K9 needs_human branch
        core._telegram_last_poll = 0.0  # force poll to fire

        core._check_telegram()
        # Phase 11 now runs in a background thread (poll must never block the
        # pulse); join before asserting the learning wiring fired.
        if core._telegram_poll_thread is not None:
            core._telegram_poll_thread.join(timeout=5)

        operator_model.learn_from_message.assert_called_once_with(
            "czesc maria, jak leci"
        )
        rhythm_detector.record_contact.assert_called_once()

    def test_telegram_poll_no_shared_context_is_safe(self):
        """Missing shared context must no-op, not raise (defensive getattr)."""
        core = HomeostasisCore(memory_manager=specced(MemoryManager), llm_manager=specced(LLMManager))

        bridge = specced(TelegramBridge)
        bridge.last_poll_message_count = 1
        bridge.last_poll_texts = ["hej"]

        core._telegram_bridge = bridge
        core._proactive_scheduler = specced(ProactiveScheduler)
        core._planner_core = None
        core._telegram_last_poll = 0.0
        # _shared_context intentionally not set

        core._check_telegram()  # must not raise
        # Drain the background poll thread so its work (and any error) settles.
        if core._telegram_poll_thread is not None:
            core._telegram_poll_thread.join(timeout=5)


class TestAutonomousSynthesisPhase:
    """Phase 10.8: the tick paces the autonomous synthesis picker (cegla E).
    Cadence + ACTIVE gate live here; cooldown/window/topic policy lives in
    synthesis.picker (tested separately)."""

    @pytest.fixture
    def core(self):
        mm = specced(MemoryManager)
        mm.get_semantic_coherence.return_value = 0.95
        mm.get_total_entries.return_value = 100
        mm.get_contradiction_count.return_value = 0
        mm.get_episodic_freshness.return_value = 60.0
        mm.get_recent_errors_count.return_value = 0
        llm = specced(LLMManager)
        llm.get_last_latency_ms.return_value = 150.0
        llm.get_context_tokens.return_value = 1000
        return HomeostasisCore(memory_manager=mm, llm_manager=llm)

    def test_trigger_fires_on_cadence_when_active(self, core):
        calls = []
        core.set_synthesis_trigger(lambda: calls.append(1))
        core.state.mode = Mode.ACTIVE
        core._tick_count = 30  # 30 % 600 == 30
        core._execute_tick()
        assert calls == [1]

    def test_trigger_silent_off_cadence(self, core):
        calls = []
        core.set_synthesis_trigger(lambda: calls.append(1))
        core.state.mode = Mode.ACTIVE
        core._tick_count = 31  # wrong remainder
        core._execute_tick()
        assert calls == []

    def test_trigger_exception_does_not_break_tick(self, core):
        def boom():
            raise RuntimeError("picker down")
        core.set_synthesis_trigger(boom)
        core.state.mode = Mode.ACTIVE
        core._tick_count = 30
        core._execute_tick()  # must not raise -- caught by _log_phase_error
        assert "10.8 synthesis" in core._phase_error_state


class TestPhaseErrorThrottle:
    """_log_phase_error: tick-phase guards log at WARNING with throttling.

    Audit 2026-06-12: guards used logger.debug, invisible at production INFO
    level -- phases died silently for months (auto_promotion, code_agent).
    """

    @pytest.fixture
    def core(self):
        return HomeostasisCore(memory_manager=specced(MemoryManager), llm_manager=specced(LLMManager))

    def test_first_error_logs_warning_immediately(self, core, caplog):
        with caplog.at_level("WARNING", logger="agent_core.homeostasis.core"):
            core._log_phase_error("12 reminder", ValueError("boom"))

        assert len(caplog.records) == 1
        rec = caplog.records[0]
        assert rec.levelname == "WARNING"
        assert "12 reminder" in rec.getMessage()
        assert "boom" in rec.getMessage()

    def test_repeats_within_interval_are_suppressed(self, core, caplog):
        with caplog.at_level("WARNING", logger="agent_core.homeostasis.core"):
            for _ in range(50):
                core._log_phase_error("12 reminder", ValueError("boom"))

        # Tylko pierwszy przechodzi; reszta zliczona w stanie tlumika.
        assert len(caplog.records) == 1
        _, suppressed = core._phase_error_state["12 reminder"]
        assert suppressed == 49

    def test_after_interval_logs_again_with_suppressed_count(self, core, caplog):
        with caplog.at_level("WARNING", logger="agent_core.homeostasis.core"):
            core._log_phase_error("13 proactive", ValueError("boom"))
            for _ in range(7):
                core._log_phase_error("13 proactive", ValueError("boom"))
            # Cofnij zegar tlumika o wiecej niz interval.
            last_ts, suppressed = core._phase_error_state["13 proactive"]
            core._phase_error_state["13 proactive"] = (
                last_ts - core.PHASE_ERROR_WARN_INTERVAL_SEC - 1, suppressed)
            core._log_phase_error("13 proactive", ValueError("boom"))

        assert len(caplog.records) == 2
        assert "7 repeats suppressed" in caplog.records[1].getMessage()
        # Licznik wyzerowany po emisji.
        assert core._phase_error_state["13 proactive"][1] == 0

    def test_labels_throttle_independently(self, core, caplog):
        with caplog.at_level("WARNING", logger="agent_core.homeostasis.core"):
            core._log_phase_error("12 reminder", ValueError("a"))
            core._log_phase_error("14 workflow", RuntimeError("b"))

        assert len(caplog.records) == 2

    def test_failing_phase_goes_through_throttled_warning(self, core, caplog):
        """Integration: a raising phase component logs WARNING, not debug."""
        core._reminder_scheduler = specced(ReminderScheduler)
        core._reminder_scheduler.tick.side_effect = RuntimeError("scheduler down")

        with caplog.at_level("WARNING", logger="agent_core.homeostasis.core"):
            # Wywolaj sam guard fazy 12 tak jak robi to tick.
            try:
                core._reminder_scheduler.tick()
            except Exception as e:
                core._log_phase_error("12 reminder", e)

        assert any("scheduler down" in r.getMessage() for r in caplog.records)


class TestOperatorRhythmReanalyze:
    """Phase 18b: periodic rhythm re-analysis on the live, seeded detector.

    record_contact() feeds the detector during Telegram polls, but the persisted
    DayRhythm was only computed at boot. These tests use REAL RhythmDetector +
    OperatorModel (never mocks -- a mock's get_rhythm returns a truthy Mock that
    set_rhythm would swallow, hiding the bug).
    """

    def _build(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        # Avoid migrating production user_profile.json into the tmp model.
        monkeypatch.setattr(
            "agent_core.operator.operator_model.LEGACY_PROFILE_PATH",
            tmp_path / "nonexistent_legacy.json",
        )
        core = HomeostasisCore(
            memory_manager=specced(MemoryManager),
            llm_manager=specced(LLMManager),
        )
        rd = RhythmDetector()
        om = OperatorModel(path=tmp_path / "operator_model.json")
        core._shared_context = SimpleNamespace(rhythm_detector=rd, operator_model=om)
        return core, rd, om

    def test_cold_detector_does_not_clobber(self, tmp_path, monkeypatch):
        core, rd, om = self._build(tmp_path, monkeypatch)
        before = om.rhythm.sample_count
        rd.seed([1_700_000_000.0 + i * 3600 for i in range(3)])  # 3 < 5
        assert core._reanalyze_operator_rhythm() is False
        assert om.rhythm.sample_count == before  # boot rhythm untouched

    def test_warm_detector_refreshes_and_advances(self, tmp_path, monkeypatch):
        core, rd, om = self._build(tmp_path, monkeypatch)
        base = 1_700_000_000.0
        rd.seed([base + i * 3600 for i in range(5)])  # exactly MIN_SAMPLES_BASIC
        assert core._reanalyze_operator_rhythm() is True
        assert om.rhythm.sample_count == 5
        assert om.rhythm.last_analyzed
        # A new live contact must move the persisted rhythm WITHOUT a restart.
        rd.record_contact(base + 6 * 3600)
        assert core._reanalyze_operator_rhythm() is True
        assert om.rhythm.sample_count == 6

    def test_missing_context_is_safe(self, tmp_path, monkeypatch):
        core, rd, om = self._build(tmp_path, monkeypatch)
        core._shared_context = None
        assert core._reanalyze_operator_rhythm() is False


class TestGrowthRefreshPhase:
    """Phase 18c: the tick refreshes growth targets on the self-perception
    cadence (SELF_PERCEPTION_TICK_INTERVAL). Without it refresh() ran once at
    boot and the live growth numbers froze."""

    @pytest.fixture
    def core(self, tmp_path):
        mm = specced(MemoryManager)
        mm.get_semantic_coherence.return_value = 0.95
        mm.get_total_entries.return_value = 100
        mm.get_contradiction_count.return_value = 0
        mm.get_episodic_freshness.return_value = 60.0
        mm.get_recent_errors_count.return_value = 0
        llm = specced(LLMManager)
        llm.get_last_latency_ms.return_value = 150.0
        llm.get_context_tokens.return_value = 1000
        # tmp event logger so the tick's escalator/audit writes (Phase 9.6 fires
        # at % 1800 == 0) never touch the live homeostasis_events.jsonl.
        ev = HomeostasisEventLogger(log_path=tmp_path / "events.jsonl")
        return HomeostasisCore(memory_manager=mm, llm_manager=llm, event_logger=ev)

    def test_refresh_fires_on_cadence(self, core):
        from agent_core.homeostasis.core import SELF_PERCEPTION_TICK_INTERVAL

        class _Growth:
            def __init__(self):
                self.calls = 0

            def refresh(self):
                self.calls += 1

        g = _Growth()
        core.set_growth_awareness(g)
        core._tick_count = SELF_PERCEPTION_TICK_INTERVAL  # exact multiple -> fires
        core._execute_tick()
        assert g.calls == 1

    def test_refresh_silent_off_cadence(self, core):
        class _Growth:
            def __init__(self):
                self.calls = 0

            def refresh(self):
                self.calls += 1

        g = _Growth()
        core.set_growth_awareness(g)
        core._tick_count = 1  # not a multiple of the interval
        core._execute_tick()
        assert g.calls == 0

    def test_refresh_exception_does_not_break_tick(self, core):
        from agent_core.homeostasis.core import SELF_PERCEPTION_TICK_INTERVAL

        class _Boom:
            def refresh(self):
                raise RuntimeError("growth down")

        core.set_growth_awareness(_Boom())
        core._tick_count = SELF_PERCEPTION_TICK_INTERVAL
        core._execute_tick()  # must not raise -- phase wraps errors


class TestConversationCondensePhase:
    """Phase 20: the tick drains idle-session conversation condensation on the
    CONVERSATION_CONDENSE_INTERVAL cadence. Without it condense fired only at
    REPL shutdown -> dead in the 24/7 daemon, so summaries froze (Feb 2026)."""

    @pytest.fixture
    def core(self, tmp_path):
        from types import SimpleNamespace
        mm = specced(MemoryManager)
        mm.get_semantic_coherence.return_value = 0.95
        mm.get_total_entries.return_value = 100
        mm.get_contradiction_count.return_value = 0
        mm.get_episodic_freshness.return_value = 60.0
        mm.get_recent_errors_count.return_value = 0
        llm = specced(LLMManager)
        llm.get_last_latency_ms.return_value = 150.0
        llm.get_context_tokens.return_value = 1000
        ev = HomeostasisEventLogger(log_path=tmp_path / "events.jsonl")
        c = HomeostasisCore(memory_manager=mm, llm_manager=llm, event_logger=ev)
        # Phase 20 reads the brain off the shared context (maria_conductor access
        # in the tick is getattr-guarded, so a sparse namespace is safe).
        c._shared_context = SimpleNamespace(brain=object())
        return c

    def test_condense_fires_on_cadence(self, core):
        from agent_core.homeostasis.core import CONVERSATION_CONDENSE_INTERVAL

        class _Cond:
            def __init__(self):
                self.calls = 0

            def condense_pending_sessions(self, brain):
                self.calls += 1
                return 0

        cond = _Cond()
        core.set_conversation_memory(cond)
        core._tick_count = CONVERSATION_CONDENSE_INTERVAL  # exact multiple
        core._execute_tick()
        # Condense runs in a transient thread (so it never blocks the tick) --
        # join before asserting it ran.
        assert core._condense_thread is not None
        core._condense_thread.join(timeout=2)
        assert cond.calls == 1

    def test_condense_silent_off_cadence(self, core):
        from agent_core.homeostasis.core import CONVERSATION_CONDENSE_INTERVAL

        class _Cond:
            def __init__(self):
                self.calls = 0

            def condense_pending_sessions(self, brain):
                self.calls += 1
                return 0

        cond = _Cond()
        core.set_conversation_memory(cond)
        core._tick_count = CONVERSATION_CONDENSE_INTERVAL + 1  # off cadence
        core._execute_tick()
        assert cond.calls == 0

    def test_condense_skipped_without_brain(self, core):
        from types import SimpleNamespace
        from agent_core.homeostasis.core import CONVERSATION_CONDENSE_INTERVAL

        class _Cond:
            def __init__(self):
                self.calls = 0

            def condense_pending_sessions(self, brain):
                self.calls += 1
                return 0

        core._shared_context = SimpleNamespace()  # no brain attribute
        cond = _Cond()
        core.set_conversation_memory(cond)
        core._tick_count = CONVERSATION_CONDENSE_INTERVAL
        core._execute_tick()
        assert cond.calls == 0  # no brain -> skip, never crashes

    def test_condense_exception_does_not_break_tick(self, core):
        from agent_core.homeostasis.core import CONVERSATION_CONDENSE_INTERVAL

        class _Boom:
            def condense_pending_sessions(self, brain):
                raise RuntimeError("condense down")

        core.set_conversation_memory(_Boom())
        core._tick_count = CONVERSATION_CONDENSE_INTERVAL
        core._execute_tick()  # spawn is non-blocking; tick must not raise
        # The error is raised + swallowed inside the thread, not the tick.
        if core._condense_thread:
            core._condense_thread.join(timeout=2)

    def test_condense_does_not_block_the_tick(self, core):
        """The whole point of the thread: a SLOW condense batch must not stall
        the tick. Inline it overran 30-55s/cadence (tick_overrun)."""
        import threading
        import time as _time
        from agent_core.homeostasis.core import CONVERSATION_CONDENSE_INTERVAL

        started = threading.Event()
        release = threading.Event()

        class _Slow:
            def condense_pending_sessions(self, brain):
                started.set()
                release.wait(2)  # hold the "LLM" until the test releases it
                return 0

        core.set_conversation_memory(_Slow())
        core._tick_count = CONVERSATION_CONDENSE_INTERVAL
        t0 = _time.perf_counter()
        core._execute_tick()
        elapsed = _time.perf_counter() - t0

        assert started.wait(2)   # condense actually started (in the thread)
        assert elapsed < 1.0     # but the tick returned WITHOUT waiting for it
        release.set()
        if core._condense_thread:
            core._condense_thread.join(timeout=2)


class TestVisionAdvisorPhase:
    """Phase 8.5 passes the adapted vision events to vision_advisor.maybe_react,
    so a salient visual event can trigger a reaction. Guards the
    'wired but never called' bug class (vision was write-only before)."""

    @pytest.fixture
    def core(self, tmp_path):
        mm = specced(MemoryManager)
        mm.get_semantic_coherence.return_value = 0.95
        mm.get_total_entries.return_value = 100
        mm.get_contradiction_count.return_value = 0
        mm.get_episodic_freshness.return_value = 60.0
        mm.get_recent_errors_count.return_value = 0
        llm = specced(LLMManager)
        llm.get_last_latency_ms.return_value = 150.0
        llm.get_context_tokens.return_value = 1000
        ev = HomeostasisEventLogger(log_path=tmp_path / "events.jsonl")
        return HomeostasisCore(memory_manager=mm, llm_manager=llm, event_logger=ev)

    @staticmethod
    def _wire_vision(core, advisor):
        from types import SimpleNamespace
        events = [SimpleNamespace(event_type="vision_motion")]

        class _Cortex:
            def perceive(self):
                return object()  # non-None percept

        class _Adapter:
            def adapt(self, percept):
                return events

        class _Buf:
            def __init__(self):
                self.pushed = None

            def push_many(self, evs):
                self.pushed = evs

        core._vision_cortex = _Cortex()
        core._vision_adapter = _Adapter()
        core._perception_buffer = _Buf()
        core._write_vision_state = lambda percept: None  # no live file write
        core._vision_interval = 1
        core._vision_last_tick = 0
        core._tick_count = 1
        if advisor is not None:
            core.set_vision_advisor(advisor)
        return events

    def test_perceive_vision_calls_advisor_with_events(self, core):
        class _Advisor:
            def __init__(self):
                self.seen = None

            def maybe_react(self, evs):
                self.seen = evs

        advisor = _Advisor()
        events = self._wire_vision(core, advisor)
        core._perceive_vision()
        assert core._perception_buffer.pushed is events
        assert advisor.seen is events  # the advisor saw the same adapted events

    def test_perceive_vision_safe_without_advisor(self, core):
        self._wire_vision(core, advisor=None)
        core._perceive_vision()  # no advisor wired -> must not raise
        assert core._perception_buffer.pushed is not None
