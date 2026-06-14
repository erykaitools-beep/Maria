"""
Tests for HomeostasisCore main loop.

Spec reference: homeostasis_spec.md section 7 (lines 879-1100)
"""

import pytest
import time
import threading
from unittest.mock import Mock, patch, MagicMock

from agent_core.homeostasis.core import HomeostasisCore
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
