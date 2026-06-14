"""
Homeostasis Core - Main event loop

The central coordinator running at ~1 Hz (1-second ticks).

Phases per tick:
1. SENSE: Read system and cognitive metrics
2. INTERPRET: Convert to semantic state with smoothing
3. VALIDATE: Check constraints, generate alerts
4. DECIDE: Determine operating mode
5. ACT: Generate and execute corrective actions
6. HEALTH: Update aggregate health score
7. PERCEIVE: Aggregate sensor events + external events into PerceptionBuffer
8. AUDIT: Log state and decisions
9. PLAN: Planner cycle (or teacher fallback when no planner)

Spec reference: homeostasis_spec.md section 7.1 (lines 1289-1478)
ADR-009: Tick Aggregator (perception via tick loop, not event bus)
"""

import json
import os
import time
import threading
import logging
from collections import deque
from pathlib import Path
from typing import Dict, Any, Deque, List, Optional, TYPE_CHECKING

from .state_model import Mode, SystemState, ResourceMetrics, CognitiveMetrics
from .sensors.resource_sensor import ResourceSensor
from .sensors.cognitive_sensor import CognitiveSensor
from .sensors.thermal_sensor import ThermalSensor
from .sensors.power_sensor import PowerSensor
from .sensors.time_sensor import TimeSensor
from .interpreter import StateInterpreter
from .constraints import ConstraintValidator, Thresholds
from .mode_regulator import ModeRegulator
from .actions import CorrectiveActionGenerator, AlarmDispatcher, CorrectiveAction, Urgency
from .event_logger import HomeostasisEventLogger, get_event_logger

if TYPE_CHECKING:
    from ..memory.manager import MemoryManager
    from ..llm.manager import LLMManager
    from ..executor.module_executor import ModuleExecutor


logger = logging.getLogger(__name__)

SELF_PERCEPTION_TICK_INTERVAL = 1800  # ticks (≈30 min at 1 tick/sec)
SELF_REPAIR_SCAN_INTERVAL = 600       # ticks (≈10 min at 1 tick/sec)
SELF_REPAIR_EXPIRY_INTERVAL = 120     # ticks (≈2 min at 1 tick/sec)
WARM_RECOVERY_WRITE_INTERVAL = 120    # ticks (≈2 min) -- Klocek 9a periodic persist
OUTBOX_PROPOSE_CHECK_INTERVAL = 1800  # ticks (≈30 min) -- Rung 2 autonomous proposer check (self-throttles to ~20h)


class HomeostasisCore:
    """
    Main homeostasis coordinator.

    Runs the continuous monitoring loop and coordinates
    all homeostasis components.

    Spec: homeostasis_spec.md lines 1292-1478
    """

    # Tick configuration
    TICK_INTERVAL_SEC = 1.0
    TICK_WARNING_THRESHOLD_SEC = 0.5  # Warn if tick takes > 500ms
    LOG_INTERVAL_TICKS = 60  # Log state every 60 seconds

    # Teacher auto-trigger configuration
    TEACHER_IDLE_THRESHOLD = 600   # 10 min idle before triggering
    TEACHER_COOLDOWN = 900         # 15 min between sessions
    TEACHER_MAX_ITERATIONS = 3     # Short sessions for auto-trigger

    def __init__(
        self,
        memory_manager: Optional["MemoryManager"] = None,
        llm_manager: Optional["LLMManager"] = None,
        executor: Optional["ModuleExecutor"] = None,
        thresholds: Optional[Thresholds] = None,
        event_logger: Optional[HomeostasisEventLogger] = None,
    ):
        """
        Initialize homeostasis core.

        Args:
            memory_manager: Memory module interface
            llm_manager: LLM module interface
            executor: Module signal executor
            thresholds: Custom constraint thresholds
            event_logger: Event logger for persistent logging (default: global)
        """
        # External dependencies
        self.memory = memory_manager
        self.llm = llm_manager
        self.executor = executor

        # Event logger (persistent JSONL logging)
        self.event_logger = event_logger or get_event_logger()

        # NREM-throttle stamp (audyt 2026-06-12): in-memory licznik zerowal
        # sie na restart -- 3 boost-passy w 21h na deploy-day vs projektowane
        # 1/20h (inflacja confidence, blocker #1 z rewizji 2026-06-10).
        # Stempel mieszka OBOK event-logu (produkcja: meta_data/, testy:
        # tmp_path) i przezywa restart.
        self._belief_sleep_throttle_path = (
            Path(self.event_logger.log_path).parent
            / "belief_sleep_throttle.json"
        )
        self._last_belief_sleep_ts = self._load_belief_sleep_ts()

        # Sensors
        self.resource_sensor = ResourceSensor()
        self.cognitive_sensor = CognitiveSensor()
        self.thermal_sensor = ThermalSensor()
        self.power_sensor = PowerSensor()
        self.time_sensor = TimeSensor()

        # Processing components
        self.interpreter = StateInterpreter()
        self.validator = ConstraintValidator(thresholds)
        self.regulator = ModeRegulator()
        self.action_generator = CorrectiveActionGenerator()
        self.alarm_dispatcher = AlarmDispatcher(event_logger=self.event_logger)

        # State
        self.state = SystemState(
            mode=Mode.ACTIVE,
            health_score=1.0,
            last_mode_change_time=time.time(),
            alerts=[],
            idle_seconds=0,
        )

        # Audit log (in-memory, bounded to prevent memory leak)
        self.audit_log: Deque[Dict[str, Any]] = deque(maxlen=1000)

        # Control
        self._running = False
        self._tick_count = 0

        # Throttle warningow z faz ticku (audyt 2026-06-12):
        # {label: (ts_ostatniego_warninga, ile_stlumiono_od_tamtej_pory)}
        self._phase_error_state: Dict[str, Any] = {}

        # Sleep processing
        self._semantic_memory = None  # Legacy (kept for compat)
        self._belief_store = None     # Real data for sleep consolidation
        self._session_id = 0
        self._last_sleep_report = None
        self._experience_tracker = None

        # Perception (Warstwa 1, ADR-009: Tick Aggregator)
        self._perception_buffer = None  # Set via set_perception_buffer()
        self._external_queue: Deque = deque(maxlen=50)  # Thread-safe external events

        # Teacher auto-trigger (set via set_teacher_agent)
        self._teacher_agent = None
        self._teacher_thread: Optional[threading.Thread] = None
        self._teacher_thread_started: Optional[float] = None  # monotonic, 7b wedge age
        self._teacher_last_run = 0.0

        # Autonomous synthesis picker (Etap 2b, cegla E). A callback wired
        # by HomeostasisModule; the cooldown/window/topic policy lives in
        # the callback + synthesis.picker, the tick only paces the check.
        self._synthesis_trigger = None

        # Planner (Warstwa 2 - replaces teacher auto-trigger when wired)
        self._planner_core = None
        self._planner_thread: Optional[threading.Thread] = None
        self._planner_thread_started: Optional[float] = None  # monotonic, 7b wedge age

        # Liveness watchdog (out-of-loop freeze detector, 2026-06-02 incident)
        self._last_tick_monotonic: Optional[float] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_stop = threading.Event()
        self._watchdog_stall_sec = float(os.environ.get("WATCHDOG_STALL_SEC", "300"))
        self._watchdog_check_sec = float(os.environ.get("WATCHDOG_CHECK_SEC", "30"))

        # Model Scheduler (multi-organ model stack)
        self._model_scheduler = None

        # Vision cortex (visual perception pipeline)
        self._vision_cortex = None
        self._vision_adapter = None
        self._vision_interval = 1  # perceive every N ticks
        self._vision_last_tick = 0

        # Telegram bridge (operator notifications)
        self._telegram_bridge = None
        self._telegram_poll_interval = 30  # seconds
        self._telegram_last_poll = 0.0
        # Phase 11 runs the poll in a background thread (get_updates is a
        # synchronous 3s-timeout HTTP call that must never block the pulse).
        self._telegram_poll_thread: Optional[threading.Thread] = None
        self._telegram_poll_thread_started: Optional[float] = None  # monotonic, 7b wedge age

        # Reminder scheduler (Phase 12)
        self._reminder_scheduler = None

        # Proactive contact scheduler (Phase 13)
        self._proactive_scheduler = None

        # Workflow engine (Phase 14)
        self._workflow_engine = None

        # Environment manager (Phase 15)
        self._environment_manager = None

        # Auto-Promotion (Phase 16 - Faza 7)
        self._auto_promotion = None

        # Conductor (Phase 17 - delegated build orchestration, e.g. market_agent)
        self._conductor = None

        # Self-Perception (Phase 18 - periodic self-state snapshots)
        self._self_perception: Optional[Any] = None

        # Self-Repair (Phase 19 - systemic failure detection + gate)
        self._system_failure_monitor: Optional[Any] = None
        self._maria_conductor: Optional[Any] = None
        self._bulletin_store: Optional[Any] = None
        self._telegram_notifier: Optional[Any] = None

        # Outbox (TIER 2 hands, Rung 2): autonomous status-note PROPOSER callback
        # (only proposes; the write is operator-gated). Set via set_outbox_proposer.
        self._outbox_proposer: Optional[Any] = None

        # Autonomous Codex dispatcher (Phase 17) — pops PENDING tasks with
        # assignee=codex and fires CodexClient. None until set_conductor_dispatcher
        # is called by HomeostasisModule. List allows multiple projects.
        self._conductor_dispatchers: list = []

        # Bulletin escalator (Phase 9.6 - Most #1)
        self._bulletin_escalator = None

        # D4 W1: Mode post-mortem recorder. When set, REDUCED entries/exits
        # are captured into a structured JSONL trail used by ModeAnalyzer.
        self._mode_postmortem_recorder = None

    def set_mode_postmortem_recorder(self, recorder) -> None:
        """Wire ``ModePostmortemRecorder`` (D4 W1) — captures REDUCED
        episodes for the mode pattern analyzer."""
        self._mode_postmortem_recorder = recorder

    def set_semantic_memory(self, semantic_memory, session_id: int = 0, experience_tracker=None) -> None:
        """
        Set semantic memory reference for sleep processing (legacy compat).

        Called from HomeostasisModule after init.
        """
        self._semantic_memory = semantic_memory
        self._session_id = session_id
        self._experience_tracker = experience_tracker

    def set_belief_store(self, belief_store) -> None:
        """Set BeliefStore for sleep consolidation (NREM2 strengthen, NREM3 forgetting)."""
        self._belief_store = belief_store

    def set_teacher_agent(self, teacher_agent) -> None:
        """
        Set teacher agent for autonomous learning during idle.

        Called from HomeostasisModule after init.

        Args:
            teacher_agent: TeacherAgent instance (with learn/exam fns already set)
        """
        self._teacher_agent = teacher_agent

    def set_synthesis_trigger(self, callback) -> None:
        """Wire the autonomous synthesis picker (Etap 2b, cegla E).

        Called from HomeostasisModule after init. ``callback`` is a zero-arg
        closure that checks the learning window + cooldown (via
        synthesis.picker) and, when due, runs one observe-mode synthesis
        cycle in a background thread. The tick only paces how often we ask.
        """
        self._synthesis_trigger = callback

    def set_model_scheduler(self, scheduler) -> None:
        """
        Set model scheduler for multi-organ model management.

        Scheduler tick() runs before planner to ensure models are
        loaded/unloaded based on idle timeouts and RAM pressure.
        Called from HomeostasisModule after init.
        """
        self._model_scheduler = scheduler

    def set_planner_core(self, planner_core) -> None:
        """
        Set planner for autonomous decision making during tick loop.

        When planner is set, it replaces teacher auto-trigger in Phase 10.
        Called from HomeostasisModule after init.
        """
        self._planner_core = planner_core

    def set_reminder_scheduler(self, scheduler) -> None:
        """Set reminder scheduler for Phase 12 tick check."""
        self._reminder_scheduler = scheduler

    def set_proactive_scheduler(self, scheduler) -> None:
        """Set proactive contact scheduler for Phase 13 tick check."""
        self._proactive_scheduler = scheduler

    def set_workflow_engine(self, engine) -> None:
        """Set workflow engine for Phase 14 tick-driven workflow advancement."""
        self._workflow_engine = engine

    def set_environment_manager(self, manager) -> None:
        """Set environment manager for Phase 15 auto-detection."""
        self._environment_manager = manager

    def set_auto_promotion(self, auto_promotion) -> None:
        """Set auto-promotion module for Phase 16 (Faza 7 - Trust & Autonomy)."""
        self._auto_promotion = auto_promotion

    def set_bulletin_escalator(self, escalator) -> None:
        """Set BulletinEscalator for Phase 9.6 (Most #1 — k12 advisory escalation)."""
        self._bulletin_escalator = escalator

    def set_conductor(self, conductor) -> None:
        """Set Conductor for Phase 17 delegated build orchestration.

        Conductor.tick() is read-only state aggregation — refreshes
        BuildStatus snapshots for every project in the queue. Cheap
        enough to run every 180 ticks (~90s) alongside auto-promotion.
        """
        self._conductor = conductor

    def set_self_perception(self, self_perception: Any) -> None:
        """Set SelfPerception for Phase 18 periodic snapshots."""
        self._self_perception = self_perception

    def set_system_failure_monitor(self, monitor: Any) -> None:
        """Set SystemFailureMonitor for Phase 19 self-repair scans."""
        self._system_failure_monitor = monitor

    def set_maria_conductor(self, conductor: Any) -> None:
        """Set the project=maria conductor for self-repair expiry sweeps."""
        self._maria_conductor = conductor

    def set_bulletin_store(self, bulletin_store: Any) -> None:
        """Set BulletinStore for Phase 19 expiry bulletin closure."""
        self._bulletin_store = bulletin_store

    def set_telegram_notifier(self, notifier: Any) -> None:
        """Set TelegramNotifier for Phase 19 operator notifications."""
        self._telegram_notifier = notifier

    def set_outbox_proposer(self, proposer: Any) -> None:
        """Set the Rung 2 autonomous outbox proposer callback: proposer(reason)
        -> proposes a status-note (PENDING + Telegram) for operator approval.
        Only ever proposes; never writes (the write is operator-gated)."""
        self._outbox_proposer = proposer

    def add_conductor_dispatcher(self, dispatcher) -> None:
        """Register a ConductorDispatcher for autonomous Codex dispatch.

        Phase 17 will call dispatcher.dispatch_next() when its interval
        elapses. One dispatcher per project (e.g. market_agent). Multiple
        dispatchers are checked round-robin per tick; only one may fire
        per tick to respect Codex rate limits and avoid burn loops.
        """
        if dispatcher is not None:
            self._conductor_dispatchers.append(dispatcher)

    def set_telegram_bridge(self, bridge) -> None:
        """
        Set Telegram bridge for operator notifications.

        Bridge polls for messages and sends alerts.
        Called from HomeostasisModule after init.
        """
        self._telegram_bridge = bridge

    def set_vision_cortex(self, cortex) -> None:
        """
        Set vision cortex for visual perception pipeline.

        Cortex perceive() runs in Phase 8.5 (after sensor aggregation).
        Events flow through VisionPerceptionAdapter into PerceptionBuffer.
        Called from HomeostasisModule after init.
        """
        self._vision_cortex = cortex
        try:
            from agent_core.vision.adapter import VisionPerceptionAdapter
            self._vision_adapter = VisionPerceptionAdapter()
        except Exception as e:
            logger.debug(f"VisionPerceptionAdapter not created: {e}")

    def set_perception_buffer(self, buffer) -> None:
        """
        Set perception buffer for tick aggregation (Warstwa 1).

        Called from HomeostasisModule after init.

        Args:
            buffer: PerceptionBuffer instance
        """
        self._perception_buffer = buffer

    def push_external_event(self, event) -> None:
        """
        Push external event to be ingested in next tick.

        Thread-safe (deque append is atomic in CPython).
        Called from REPL thread, teacher thread, etc.

        Args:
            event: PerceptionEvent from any adapter
        """
        self._external_queue.append(event)

    def _drain_external_queue(self) -> list:
        """
        Drain all pending external events. Called ONLY from tick loop thread.

        Returns:
            List of PerceptionEvents
        """
        events = []
        while self._external_queue:
            try:
                events.append(self._external_queue.popleft())
            except IndexError:
                break
        return events

    # Throttle: pierwszy blad fazy od razu, potem max 1 warning / interval.
    PHASE_ERROR_WARN_INTERVAL_SEC = 600  # 10 min

    def _log_phase_error(self, label: str, e: Exception) -> None:
        """Log a tick-phase exception at WARNING with per-phase throttling.

        Audit 2026-06-12: these guards used logger.debug, which production
        logging (INFO root level, maria.py:34) never emits -- a phase could
        die on every tick for months with zero trace. That exact mechanism
        killed auto_promotion (a month) and code_agent (since deploy day).

        The tick runs ~1/s, so a permanently broken phase would emit ~86k
        warnings/day unthrottled. First error logs immediately; afterwards
        at most one warning per PHASE_ERROR_WARN_INTERVAL_SEC per label,
        carrying the count of suppressed repeats.
        """
        now = time.time()
        last_ts, suppressed = self._phase_error_state.get(label, (0.0, 0))
        if now - last_ts >= self.PHASE_ERROR_WARN_INTERVAL_SEC:
            suffix = f" ({suppressed} repeats suppressed)" if suppressed else ""
            logger.warning("Phase %s error: %r%s", label, e, suffix)
            self._phase_error_state[label] = (now, 0)
        else:
            self._phase_error_state[label] = (last_ts, suppressed + 1)

    def main_loop(self) -> None:
        """
        Main homeostasis event loop.

        Runs every ~1 second until stopped.

        Spec: homeostasis_spec.md lines 1316-1394
        """
        self._running = True
        logger.info("Homeostasis main loop started")

        while self._running:
            try:
                tick_start = time.time()

                # Execute tick
                self._execute_tick()

                self._tick_count += 1

                # Wait for next tick
                tick_duration = time.time() - tick_start
                if tick_duration < self.TICK_INTERVAL_SEC:
                    time.sleep(self.TICK_INTERVAL_SEC - tick_duration)
                else:
                    logger.warning(
                        f"Homeostasis tick took {tick_duration:.2f}s (> {self.TICK_INTERVAL_SEC}s)"
                    )

            except Exception as e:
                logger.error(f"Homeostasis loop exception: {e}", exc_info=True)
                self.state.alerts.append(f"CRITICAL: Homeostasis exception: {e}")
                time.sleep(self.TICK_INTERVAL_SEC)

        logger.info("Homeostasis main loop stopped")

    def _execute_tick(self) -> None:
        """
        Execute a single tick of the homeostasis loop.

        Phases from spec lines 1327-1386:
        1. SENSE
        2. INTERPRET
        3. VALIDATE
        4. DECIDE MODE
        5. GENERATE ACTIONS
        6. EXECUTE ACTIONS
        7. UPDATE HEALTH
        8. AUDIT
        """
        # Per-phase timing (diagnostic, #3): isolate the tick-overrun culprit.
        # Each wrapped phase records ms into self._phase_ms; main_loop logs it
        # on overrun. "unaccounted" = tick_elapsed - sum(phase_ms) catches any
        # culprit outside the wrapped set, so we are never blind.
        self._phase_ms = {}
        self._tick_t0 = time.perf_counter()
        # Liveness heartbeat for the out-of-loop watchdog (see start_watchdog):
        # stamped at tick start so a tick that wedges mid-phase ages past the
        # deadline and trips the watchdog instead of hanging silently for hours.
        self._last_tick_monotonic = time.monotonic()

        # ──────────────────────────────────────
        # PHASE 1: SENSE
        # ──────────────────────────────────────
        _t_phase = time.perf_counter()
        resource_metrics = self.resource_sensor.read_metrics()
        thermal_metrics = self.thermal_sensor.read_metrics()
        time_metrics = self.time_sensor.read_metrics()

        # Merge thermal into resource metrics
        if resource_metrics and thermal_metrics:
            resource_metrics = ResourceMetrics(
                timestamp=resource_metrics.timestamp,
                ram_used_mb=resource_metrics.ram_used_mb,
                ram_total_mb=resource_metrics.ram_total_mb,
                ram_available_mb=resource_metrics.ram_available_mb,
                swap_used_pct=resource_metrics.swap_used_pct,
                cpu_percent=resource_metrics.cpu_percent,
                load_avg_1m=resource_metrics.load_avg_1m,
                load_avg_5m=resource_metrics.load_avg_5m,
                load_avg_15m=resource_metrics.load_avg_15m,
                disk_used_pct=resource_metrics.disk_used_pct,
                disk_io_queue_depth=resource_metrics.disk_io_queue_depth,
                process_count=resource_metrics.process_count,
                temp_c=thermal_metrics.cpu_temp_c,
                inference_latency_ms=resource_metrics.inference_latency_ms,
            )

        cognitive_metrics = self.cognitive_sensor.read_metrics(
            memory_manager=self.memory,
            llm_manager=self.llm,
        )
        self._phase_ms["01_sense"] = round((time.perf_counter() - _t_phase) * 1000, 1)

        # ──────────────────────────────────────
        # PHASE 2: INTERPRET
        # ──────────────────────────────────────
        interpreted_state = self.interpreter.process_metrics(
            resource_metrics,
            cognitive_metrics,
            idle_seconds=time_metrics.idle_streak_sec,
        )

        self.state.interpreted_state = interpreted_state
        self.state.idle_seconds = time_metrics.idle_streak_sec

        # ──────────────────────────────────────
        # PHASE 3: VALIDATE CONSTRAINTS
        # ──────────────────────────────────────
        all_ok, alerts = self.validator.validate(interpreted_state)
        self.state.alerts = alerts

        # Dispatch alarms for critical issues
        for alert in alerts:
            if "CRITICAL" in alert:
                self.alarm_dispatcher.dispatch_critical(
                    alarm_type="constraint_violation",
                    message=alert,
                    recommended_action="Check system state immediately",
                )

        # ──────────────────────────────────────
        # PHASE 4: DECIDE MODE
        # ──────────────────────────────────────
        new_mode = self.regulator.decide_mode(interpreted_state, alerts)

        if new_mode != self.state.mode:
            self._transition_mode(self.state.mode, new_mode)

        # ──────────────────────────────────────
        # PHASE 5: GENERATE CORRECTIVE ACTIONS
        # ──────────────────────────────────────
        actions = self.action_generator.generate_actions(interpreted_state, alerts)

        # ──────────────────────────────────────
        # PHASE 6: EXECUTE CORRECTIVE ACTIONS
        # ──────────────────────────────────────
        self._execute_corrective_actions(actions)

        # ──────────────────────────────────────
        # PHASE 7: UPDATE HEALTH SCORE
        # ──────────────────────────────────────
        self.state.health_score = self._compute_health(interpreted_state, alerts)

        # Notify operator on health drop (< 0.7)
        if self._telegram_bridge and self.state.health_score < 0.7:
            try:
                self._telegram_bridge.notifier.notify_health_drop(
                    self.state.health_score,
                    self.state.mode.value,
                    self.state.alerts[:5],
                )
            except Exception as e:
                # Don't let a notify failure break the tick, but make it
                # visible — a swallowed health alert means the operator
                # never learns the system is degrading.
                logger.warning(
                    "Health-drop notification to operator failed "
                    "(health=%.2f mode=%s): %s",
                    self.state.health_score, self.state.mode.value, e,
                )

        # ──────────────────────────────────────
        # PHASE 8: PERCEIVE (Tick Aggregator, ADR-009)
        # ──────────────────────────────────────
        self._aggregate_perception(
            resource_metrics=resource_metrics,
            cognitive_metrics=cognitive_metrics,
            thermal_metrics=thermal_metrics,
            time_metrics=time_metrics,
        )

        # ──────────────────────────────────────
        # PHASE 8.5: VISION (visual perception pipeline)
        # ──────────────────────────────────────
        _t_phase = time.perf_counter()
        self._perceive_vision()
        self._phase_ms["08.5_vision"] = round((time.perf_counter() - _t_phase) * 1000, 1)

        # ──────────────────────────────────────
        # PHASE 9: AUDIT & LOG
        # ──────────────────────────────────────
        if self._tick_count % self.LOG_INTERVAL_TICKS == 0:
            self._log_state(interpreted_state)

        # ──────────────────────────────────────
        # PHASE 9.5: MODEL SCHEDULER (idle timeouts, RAM pressure)
        # ──────────────────────────────────────
        if self._model_scheduler:
            try:
                self._model_scheduler.tick()
            except Exception as e:
                self._log_phase_error("9.5 model-scheduler", e)

        # ──────────────────────────────────────
        # PHASE 9.6: BULLETIN ESCALATOR (Most #1 — k12 advisory -> PROPOSED)
        # Cadence: every 1800 ticks (~30 min). K12 entries are rare and the
        # 7-day window means latency on escalation rarely matters.
        #
        # Emits JSONL events so wire-up can be verified without journalctl.
        # First-tick event captures whether the escalator is wired at all.
        # ──────────────────────────────────────
        if self._tick_count % 1800 == 0:
            self.event_logger._write_event({
                "timestamp": time.time(),
                "event": "escalator_phase_entered",
                "tick_count": self._tick_count,
                "escalator_wired": self._bulletin_escalator is not None,
            })
            if self._bulletin_escalator:
                try:
                    created = self._bulletin_escalator.scan_and_escalate()
                    self.event_logger._write_event({
                        "timestamp": time.time(),
                        "event": "escalator_scan_completed",
                        "tick_count": self._tick_count,
                        "goals_created": len(created or []),
                        "goal_ids": list(created or []),
                    })
                except Exception as e:
                    logger.exception("Phase 9.6 bulletin escalator failed")
                    self.event_logger._write_event({
                        "timestamp": time.time(),
                        "event": "escalator_scan_error",
                        "tick_count": self._tick_count,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    })

        # ──────────────────────────────────────
        # PHASE 9.7: LOG ARCHIVAL (daily, even in ACTIVE mode)
        # ──────────────────────────────────────
        self._maybe_archive_logs()

        # ──────────────────────────────────────
        # PHASE 10: PLANNER (or teacher fallback)
        # ──────────────────────────────────────
        _t_phase = time.perf_counter()
        self._check_planner_trigger()
        self._phase_ms["10_planner"] = round((time.perf_counter() - _t_phase) * 1000, 1)

        # ──────────────────────────────────────
        # PHASE 10.8: AUTONOMOUS SYNTHESIS (Etap 2b, cegla E)
        # Maria sama wybiera temat i syntetyzuje wiedze raz dziennie w
        # oknie nauki. Sprawdzamy co ~600 tickow (~10 min); realny rate
        # limit to 24h cooldown w pickerze. Tryb observe dopoki
        # SYNTH_ENABLED nieuzbrojony -- zero zapisow do produkcji.
        # ──────────────────────────────────────
        if (
            self._synthesis_trigger is not None
            and self.state.mode == Mode.ACTIVE
            and self._tick_count % 600 == 30
        ):
            try:
                self._synthesis_trigger()
            except Exception as e:
                self._log_phase_error("10.8 synthesis", e)

        # ──────────────────────────────────────
        # PHASE 11: TELEGRAM (poll + notify)
        # ──────────────────────────────────────
        _t_phase = time.perf_counter()
        self._check_telegram()
        self._phase_ms["11_telegram"] = round((time.perf_counter() - _t_phase) * 1000, 1)

        # ──────────────────────────────────────
        # PHASE 12: REMINDERS (check due)
        # ──────────────────────────────────────
        if self._reminder_scheduler:
            try:
                self._reminder_scheduler.tick()
            except Exception as e:
                self._log_phase_error("12 reminder", e)

        # ──────────────────────────────────────
        # PHASE 13: PROACTIVE CONTACT (Maria initiates)
        # ──────────────────────────────────────
        if self._proactive_scheduler:
            try:
                self._proactive_scheduler.tick()
            except Exception as e:
                self._log_phase_error("13 proactive", e)

        # ──────────────────────────────────────
        # PHASE 14: WORKFLOW ENGINE (advance active workflows)
        # ──────────────────────────────────────
        if self._workflow_engine and self._tick_count % 60 == 30:
            try:
                self._workflow_engine.advance_next_active()
            except Exception as e:
                self._log_phase_error("14 workflow", e)

        # ──────────────────────────────────────
        # PHASE 15: ENVIRONMENT (auto-detect mode)
        # ──────────────────────────────────────
        if self._environment_manager and self._tick_count % 300 == 0:
            try:
                self._environment_manager.maybe_auto_switch()
            except Exception as e:
                self._log_phase_error("15 environment", e)

        # ──────────────────────────────────────
        # PHASE 16: AUTO-PROMOTION (Faza 7 - Trust & Autonomy)
        # ──────────────────────────────────────
        if self._auto_promotion and self._tick_count % 180 == 0:
            try:
                self._auto_promotion.tick()
            except Exception as e:
                self._log_phase_error("16 auto-promotion", e)

        # ──────────────────────────────────────
        # PHASE 17: CONDUCTOR (delegated build orchestration)
        # ──────────────────────────────────────
        # Refreshes BuildStatus snapshots so /market_status and the Web
        # UI see fresh numbers without scanning the whole task queue.
        # Read-only — never writes to TaskQueue, never invokes LLMs.
        if self._conductor and self._tick_count % 180 == 0:
            try:
                self._conductor.tick()
            except Exception as e:
                self._log_phase_error("17 conductor", e)

        # T-SELF-003: also tick the maria conductor (different queue).
        if hasattr(self, "_shared_context") and getattr(
            self._shared_context, "maria_conductor", None
        ):
            if self._tick_count % 180 == 0:
                try:
                    self._shared_context.maria_conductor.tick()
                except Exception as e:
                    self._log_phase_error("17 maria-conductor", e)

        # Autonomous Codex dispatch — fires when at least one dispatcher's
        # interval has elapsed AND a PENDING task with assignee=codex
        # exists. Cap at one dispatch per tick (round-robin across
        # registered dispatchers) so a Codex burn loop on one project
        # cannot starve another and the rate-limit window has room.
        if self._conductor_dispatchers:
            for dispatcher in self._conductor_dispatchers:
                try:
                    if dispatcher.should_dispatch():
                        result = dispatcher.dispatch_next()
                        logger.info(
                            "[Phase17] dispatched project=%s outcome=%s task=%s",
                            dispatcher.project, result.outcome.value,
                            result.task_id,
                        )
                        break  # one Codex call per tick
                except Exception as e:
                    logger.exception(
                        "[Phase17] dispatcher error project=%s: %s",
                        getattr(dispatcher, "project", "?"), e,
                    )

        # ──────────────────────────────────────
        # PHASE 18: SELF-PERCEPTION (periodic self-state snapshot)
        # ──────────────────────────────────────
        if (
            self._self_perception
            and self._tick_count % SELF_PERCEPTION_TICK_INTERVAL == 0
        ):
            try:
                self._self_perception.take_snapshot()
            except Exception as e:
                logger.warning(
                    f"[Phase18] self-perception snapshot error: {e}",
                    exc_info=True,
                )

        # ──────────────────────────────────────
        # PHASE 19: SELF-REPAIR (system failure detection + expiry)
        # ──────────────────────────────────────
        if (
            self._system_failure_monitor
            and self._tick_count % SELF_REPAIR_SCAN_INTERVAL == 0
        ):
            try:
                created = self._system_failure_monitor.scan_and_create()
                if created:
                    logger.info(f"[Phase19] self-repair tasks created: {created}")
            except Exception as e:
                logger.warning(f"[Phase19] self-repair scan error: {e}", exc_info=True)

        if (
            self._maria_conductor
            and self._tick_count % SELF_REPAIR_EXPIRY_INTERVAL == 0
        ):
            try:
                from agent_core.self_repair import expire_stale_repair_tasks

                expired = expire_stale_repair_tasks(
                    self._maria_conductor,
                    self._bulletin_store,
                    self._telegram_notifier,
                )
                if expired:
                    logger.info(f"[Phase19] expired self-repair tasks: {expired}")
            except Exception as e:
                logger.warning(f"[Phase19] expiry sweep error: {e}", exc_info=True)

        # Klocek 9a: periodic warm-recovery persist (flag-gated; cheap no-op
        # when off). Captures state between mode transitions so a hard crash
        # mid-cycle still leaves a recent snapshot to resume from.
        if self._tick_count % WARM_RECOVERY_WRITE_INTERVAL == 0:
            self._write_recovery_snapshot()

        # Rung 2 (TIER 2 hands): autonomous outbox proposer (flag-gated). Only
        # ever PROPOSES a status note (pending row + Telegram ping); the actual
        # write is operator-gated via /approve_note. The proposer self-throttles
        # to ~20h, so this just polls; OFF = cheap no-op.
        if self._tick_count % OUTBOX_PROPOSE_CHECK_INTERVAL == 0:
            self._maybe_propose_outbox()


        # Per-phase timing emit (#4). NB: production run_daemon() calls
        # _execute_tick() directly and never main_loop(), so this MUST live
        # here, not in main_loop. Wall-clock cadence (not tick_count -- ticks
        # advance +1/s in every mode; the old "SLEEP fast-forwards by 60"
        # claim here was comment folklore, never true in run_daemon).
        # An overrun is ANY tick > 2s, regardless
        # of mode: _execute_tick itself never sleeps (the inter-tick wait lives
        # in run_daemon, OUTSIDE this method), so a multi-second tick is always
        # anomalous -- including in SLEEP, where the ~3s synchronous Telegram
        # poll and rare CPU-starvation stalls strike. (An earlier guard
        # suppressed SLEEP overruns on the false premise that SLEEP ticks are
        # "intentionally long"; they are normally ~40ms -- the long ones are the
        # very freezes we hunt.) "unaccounted" = tick - sum(measured phases) so
        # the culprit can't hide outside the wrapped set.
        try:
            _tick_ms = (time.perf_counter() - getattr(self, "_tick_t0", time.perf_counter())) * 1000
            _now = time.time()
            _overrun = _tick_ms > 2000
            _baseline_due = (_now - getattr(self, "_last_timing_log_ts", 0.0)) >= 300
            if _overrun or _baseline_due:
                _phase_ms = getattr(self, "_phase_ms", {})
                # cpu_percent + load_avg expose CPU-starvation: a tick whose
                # measured phases are trivial but wall-clock is seconds means the
                # thread was descheduled (e.g. concurrent Ollama inference pegging
                # cores). resource_metrics was read in PHASE 1 of this tick.
                _rm = resource_metrics
                self.event_logger._write_event({
                    "ts": _now,
                    "event": "tick_overrun" if _overrun else "tick_timing_sample",
                    "tick_count": self._tick_count,
                    "tick_ms": round(_tick_ms, 1),
                    "phase_ms": _phase_ms,
                    "unaccounted_ms": round(_tick_ms - sum(_phase_ms.values()), 1),
                    "cpu_percent": round(getattr(_rm, "cpu_percent", 0.0) or 0.0, 1),
                    "load_avg_1m": round(getattr(_rm, "load_avg_1m", 0.0) or 0.0, 2),
                    "mode": self.state.mode.value,
                })
                self._last_timing_log_ts = _now
        except Exception as _te:
            logger.debug(f"tick-timing emit failed: {_te}")

    def _aggregate_perception(
        self,
        resource_metrics=None,
        cognitive_metrics=None,
        thermal_metrics=None,
        time_metrics=None,
    ) -> None:
        """
        Aggregate sensor events + external events into PerceptionBuffer.

        ADR-009: Tick Aggregator. Called once per tick after health update.
        Converts raw sensor metrics to PerceptionEvents and pushes them
        along with any external events (from REPL, teacher, etc.).

        Args:
            resource_metrics: ResourceMetrics from Phase 1 (may be None)
            cognitive_metrics: CognitiveMetrics from Phase 1 (may be None)
            thermal_metrics: ThermalMetrics from Phase 1 (may be None)
            time_metrics: TimeMetrics from Phase 1 (may be None)
        """
        if self._perception_buffer is None:
            return

        try:
            from agent_core.perception.adapters.sensor_adapter import SensorAdapter

            # Convert sensor metrics to PerceptionEvents
            if resource_metrics:
                self._perception_buffer.push(
                    SensorAdapter.from_resource_metrics(resource_metrics)
                )
            if cognitive_metrics:
                self._perception_buffer.push(
                    SensorAdapter.from_cognitive_metrics(cognitive_metrics)
                )
            if thermal_metrics:
                self._perception_buffer.push(
                    SensorAdapter.from_thermal_metrics(thermal_metrics)
                )
            if time_metrics:
                self._perception_buffer.push(
                    SensorAdapter.from_time_metrics(time_metrics)
                )

            # PowerSensor is read separately (not in Phase 1 currently)
            # Will be added when power_sensor is integrated into Phase 1

            # Drain external events (from REPL, teacher, etc.)
            external_events = self._drain_external_queue()
            if external_events:
                self._perception_buffer.push_many(external_events)

            # Remove expired events
            self._perception_buffer.drain_expired()

        except Exception as e:
            self._log_phase_error("8 perception-aggregation", e)

    def _perceive_vision(self) -> None:
        """
        Phase 8.5: Capture and process frame from vision cortex.

        Runs every _vision_interval ticks (default 5) to avoid CPU overhead.
        Events flow through VisionPerceptionAdapter into PerceptionBuffer.
        Writes state to meta_data/vision_state.json for Web UI.
        Graceful: no-op if vision not wired or camera unavailable.
        """
        if self._vision_cortex is None or self._vision_adapter is None:
            return
        if self._perception_buffer is None:
            return

        # Rate limit: not every tick
        if (self._tick_count - self._vision_last_tick) < self._vision_interval:
            return
        self._vision_last_tick = self._tick_count

        try:
            percept = self._vision_cortex.perceive()
            if percept is not None:
                events = self._vision_adapter.adapt(percept)
                if events:
                    self._perception_buffer.push_many(events)
                # Write state for Web UI (every perception, not every tick)
                self._write_vision_state(percept)
        except Exception as e:
            self._log_phase_error("8.5 vision", e)

    def _write_vision_state(self, percept) -> None:
        """Write vision state to JSON for Web UI consumption."""
        import json
        try:
            status = self._vision_cortex.get_status()
            state = {
                "status": status,
                "last_percept": {
                    "timestamp": percept.timestamp,
                    "summary": percept.summary,
                    "quality": round(percept.quality, 3),
                    "health": round(percept.vision_health.overall, 3),
                    "modules_run": percept.modules_run,
                    "sensor_id": percept.sensor_id,
                    "processing_time_ms": percept.total_processing_time_ms,
                },
            }
            # Motion data
            if percept.motion:
                state["last_percept"]["motion"] = {
                    "motion_detected": percept.motion.motion_detected,
                    "motion_level": round(percept.motion.motion_level, 3),
                    "classification": percept.motion.classification.value,
                    "alert_level": percept.motion.alert_level.value,
                    "regions_count": len(percept.motion.regions),
                }
            # Scene data
            if percept.scene:
                state["last_percept"]["scene"] = {
                    "description": percept.scene.description,
                    "lighting": percept.scene.lighting,
                    "dominant_colors": list(percept.scene.dominant_colors),
                    "complexity": round(percept.scene.complexity, 3),
                    "backend_used": percept.scene.backend_used,
                }
            # Sensor health
            sensor = self._vision_cortex.active_sensor
            if sensor:
                h = sensor.health
                state["health"] = {
                    "sensor_id": sensor.sensor_id,
                    "health": h.to_dict(),
                    "description": h.to_human_description(),
                }

            meta_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "meta_data",
            )
            state_path = os.path.join(meta_dir, "vision_state.json")
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)

            # Save last frame as JPEG for Web UI preview
            frame_image = getattr(self._vision_cortex, '_last_frame_image', None)
            if frame_image is not None:
                try:
                    import cv2
                    frame_path = os.path.join(meta_dir, "vision_frame.jpg")
                    cv2.imwrite(frame_path, frame_image, [cv2.IMWRITE_JPEG_QUALITY, 80])
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Vision state write error: {e}")

    def _transition_mode(self, old_mode: Mode, new_mode: Mode) -> None:
        """
        Execute safe mode transition.

        Spec: homeostasis_spec.md lines 1396-1424

        Args:
            old_mode: Current mode
            new_mode: Target mode
        """
        logger.info(f"Mode transition: {old_mode.value} → {new_mode.value}")

        # Pre-transition: trigger snapshot
        self._trigger_snapshot()

        # Signal dependent modules based on new mode
        if self.executor:
            if new_mode == Mode.SLEEP:
                self.executor.signal_module("learning_engine", "pause")
            if new_mode == Mode.SURVIVAL:
                self.executor.signal_module("llm", "minimize")
                self.executor.signal_module("memory", "readonly")
            elif new_mode == Mode.REDUCED:
                self.executor.signal_module("learning_engine", "pause")
            elif new_mode == Mode.ACTIVE:
                self.executor.signal_module("learning_engine", "resume")

        # Stop teacher when leaving ACTIVE mode
        if old_mode == Mode.ACTIVE and new_mode != Mode.ACTIVE:
            if self._teacher_agent:
                self._teacher_agent.stop()
                logger.info("Teacher session stopped: leaving ACTIVE mode")

        # Run sleep cycle when entering SLEEP mode
        if new_mode == Mode.SLEEP:
            self._run_sleep_cycle()

        # Update state
        result = self.regulator.transition_to(new_mode)
        self.state.mode = new_mode
        self.state.last_mode_change_time = time.time()

        # Persistent event log (JSONL) - with full context
        self.event_logger.log_mode_change(
            from_mode=old_mode,
            to_mode=new_mode,
            interpreted_state=self.state.interpreted_state or {},
            alerts=self.state.alerts,
            health_score=self.state.health_score,
            tick_count=self._tick_count,
        )

        # In-memory audit log (backward compatibility)
        self.audit_log.append({
            "timestamp": time.time(),
            "event": "mode_change",
            "from": old_mode.value,
            "to": new_mode.value,
        })

        # Notify operator via Telegram
        if self._telegram_bridge:
            try:
                self._telegram_bridge.notifier.notify_mode_change(
                    from_mode=old_mode.value,
                    to_mode=new_mode.value,
                    trigger=", ".join(self.state.alerts[:3]),
                )
            except Exception:
                pass

        # Personality signals on recovery transitions (C6 fix).
        # SURVIVAL → ACTIVE feeds `cierpliwa` via survival_mode_recovered;
        # REDUCED → ACTIVE feeds `cierpliwa` via reduced_mode_stable.
        if self._experience_tracker and new_mode == Mode.ACTIVE:
            try:
                if old_mode == Mode.SURVIVAL:
                    self._experience_tracker.record(
                        "survival_mode_recovered",
                        {"from": old_mode.value, "to": new_mode.value},
                    )
                elif old_mode == Mode.REDUCED:
                    self._experience_tracker.record(
                        "reduced_mode_stable",
                        {"from": old_mode.value, "to": new_mode.value},
                    )
            except Exception:
                pass

        # D4 W1: feed ModePostmortemRecorder so the mode_analyzer can later
        # cluster recurring REDUCED root causes by alerts/hour/action.
        if self._mode_postmortem_recorder is not None:
            try:
                interp_state = self.state.interpreted_state or {}
                alerts = list(self.state.alerts or [])
                health = float(self.state.health_score)
                if new_mode == Mode.REDUCED:
                    self._mode_postmortem_recorder.note_entry(
                        tick_count=self._tick_count,
                        metrics=interp_state,
                        alerts=alerts,
                        trigger={"alerts": alerts[:3]},
                    )
                elif old_mode == Mode.REDUCED and new_mode == Mode.ACTIVE:
                    self._mode_postmortem_recorder.note_exit(
                        tick_count=self._tick_count,
                        metrics=interp_state,
                        alerts=alerts,
                        trigger={"alerts": alerts[:3]},
                        health_score=health,
                    )
                elif old_mode == Mode.REDUCED:
                    # Bail out cleanly — recording only ACTIVE recoveries
                    # avoids inflating the dataset with REDUCED→SLEEP and
                    # REDUCED→SURVIVAL chains that have a different cause.
                    self._mode_postmortem_recorder.discard_pending()
            except Exception as e:
                logger.debug(f"[ModePostmortem] hook failed: {e}")

    def _execute_corrective_actions(self, actions: List[CorrectiveAction]) -> None:
        """
        Execute corrective actions.

        Spec: homeostasis_spec.md lines 1426-1441

        Args:
            actions: List of actions to execute
        """
        for action in actions:
            try:
                if action.action_type.value == "signal_module":
                    if self.executor:
                        self.executor.signal_module(
                            action.target,
                            action.action,
                            **action.parameters,
                        )
                elif action.action_type.value == "trigger_snapshot":
                    self._trigger_snapshot()

            except Exception as e:
                logger.warning(f"Action failed: {action.to_dict()} - {e}")

    # Belief phases (NREM2 boost / NREM3 forgetting) run at most once per
    # this many seconds of wall-clock, regardless of how often SLEEP is
    # entered. SLEEP flaps several times a day (learning-window wakes,
    # activity resets); unthrottled NREM2 +0.02/entry would saturate every
    # evidenced belief at 0.95 within days and destroy the confidence
    # calibration that prune scoring and the trust regime depend on
    # (2026-06-10 adversarial review, blocker #1). The stamp is persisted
    # next to the event log -- "one extra pass per restart" turned out NOT
    # to be harmless: audit 2026-06-12 confirmed 3 boost passes in 21h on a
    # deploy day (restarts at 05:01/05:28/16:25/17:24 kept resetting it).
    BELIEF_SLEEP_MIN_GAP_SEC: float = 20 * 3600
    _last_belief_sleep_ts: float = 0.0

    def _load_belief_sleep_ts(self) -> float:
        """Load the persisted NREM throttle stamp (0.0 when absent/corrupt)."""
        try:
            with open(self._belief_sleep_throttle_path, "r", encoding="utf-8") as f:
                return float(json.load(f).get("last_belief_sleep_ts", 0.0))
        except (OSError, ValueError, TypeError):
            return 0.0

    def _save_belief_sleep_ts(self, ts: float) -> None:
        """Persist the NREM throttle stamp (atomic tmp+replace)."""
        try:
            path = self._belief_sleep_throttle_path
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"last_belief_sleep_ts": ts}, f)
            tmp.replace(path)
        except OSError as e:
            logger.warning(f"Belief-sleep throttle persist failed: {e}")

    def _run_sleep_cycle(self) -> None:
        """
        Run sleep processing when entering SLEEP mode.

        Phases: NREM1 (stats) -> NREM2 (strengthen) -> NREM3 (forgetting) -> Archival -> REM (dreams).
        Works on real data: BeliefStore + knowledge_index.
        """
        try:
            from agent_core.consciousness.sleep_processor import SleepProcessor

            # Two guards on the belief-mutating phases (review 2026-06-10):
            # 1) wall-clock throttle (see BELIEF_SLEEP_MIN_GAP_SEC above);
            # 2) planner-thread guard: the planner mutates the same lock-free
            #    BeliefStore from its background thread (maintain() after
            #    EVALUATE). Belief phases run only when no planner cycle is
            #    alive. Planner cycles are spawned from THIS tick thread
            #    (phase 10), so one cannot start mid-sleep-cycle -- the
            #    entry check is sufficient.
            now = time.time()
            planner_alive = bool(
                self._planner_thread and self._planner_thread.is_alive()
            )
            beliefs_due = (
                (now - self._last_belief_sleep_ts)
                >= self.BELIEF_SLEEP_MIN_GAP_SEC
            )
            if planner_alive:
                belief_skip_reason = "planner_alive"
            elif not beliefs_due:
                belief_skip_reason = "throttled"
            else:
                belief_skip_reason = None
            use_store = (
                self._belief_store if belief_skip_reason is None else None
            )

            processor = SleepProcessor(
                belief_store=use_store,
                session_id=self._session_id,
            )
            report = processor.process_sleep_cycle()
            self._last_sleep_report = report
            if use_store is not None:
                self._last_belief_sleep_ts = now
                self._save_belief_sleep_ts(now)

            # Log sleep cycle event. Carries the NREM2/NREM3 belief numbers
            # and whether the store was wired at all -- before 2026-06-10 the
            # belief path was a silent no-op (wiring-order bug) and this event
            # could not tell a real sleep from a cosmetic one.
            dream_count = len(report.get("dreams", []))
            phases = report.get("phases", {})

            def _phase_int(phase: str, key: str) -> int:
                # Phase results can be error-shaped ({'error': ...}); never
                # let a missing key poison the event write.
                value = phases.get(phase) or {}
                raw = value.get(key, 0) if isinstance(value, dict) else 0
                return raw if isinstance(raw, int) else 0

            self.event_logger._write_event({
                "timestamp": time.time(),
                "event": "sleep_cycle",
                "dream_count": dream_count,
                "phases_completed": report.get("phases_completed", 0),
                "belief_store_wired": self._belief_store is not None,
                "belief_phases_ran": use_store is not None,
                "belief_skip_reason": belief_skip_reason,
                "beliefs_boosted": _phase_int("nrem2", "beliefs_boosted"),
                "beliefs_before": _phase_int("nrem3", "beliefs_before"),
                "beliefs_pruned": _phase_int("nrem3", "beliefs_pruned"),
                "session_id": self._session_id,
            })

            logger.info(
                f"Sleep cycle completed: {dream_count} dreams, "
                f"{report.get('phases_completed', 0)} phases"
            )
        except Exception as e:
            logger.warning(f"Sleep cycle failed: {e}")

    # -- Phase 9.7: Log Archival ----------------------------------

    _last_archival_ts: float = 0.0
    _ARCHIVAL_INTERVAL_SEC: int = 86400  # 24h

    def _maybe_archive_logs(self) -> None:
        """Run log archival once per day, even in ACTIVE mode.

        Prevents unbounded JSONL growth (~4.7 MB/day -> ~22 GB/year).
        Archives records older than min_age_days per file to /mnt/storage/.
        """
        import time as _time
        now = _time.time()
        if now - self._last_archival_ts < self._ARCHIVAL_INTERVAL_SEC:
            return

        try:
            from pathlib import Path
            archive_path = Path("/mnt/storage/data")
            if not archive_path.parent.exists():
                return

            from agent_core.storage import LogArchiver
            archiver = LogArchiver()
            result = archiver.run_archival()
            self._last_archival_ts = now
            total = result.get("total_archived", 0)
            if total > 0:
                logger.info(
                    f"Phase 9.7: Archived {total} log records "
                    f"({result.get('total_kept', 0)} kept active)"
                )
        except Exception as e:
            self._log_phase_error("9.7 archival", e)

    def _check_telegram(self) -> None:
        """
        Poll Telegram for operator messages (Phase 11).

        Runs every _telegram_poll_interval seconds (default 30). The poll
        itself (bot.get_updates -> command handlers -> replies -> operator
        learning) runs in a short-lived BACKGROUND thread and NEVER on the
        tick. get_updates is a synchronous requests.get with a 3s HTTP
        read-timeout, so a slow/late Telegram API would otherwise freeze the
        whole pulse for ~3s -- the recurring tick_overrun (confirmed: a 3.25s
        tick spent 3.21s in poll, CPU idle 1%). Mirrors the planner's
        background-thread pattern; the is_alive() guard prevents stacking
        a new poll when one is still blocked on a slow API.
        """
        if self._telegram_bridge is None:
            return

        # Don't stack a new poll on top of one still blocked on a slow API.
        if (self._telegram_poll_thread is not None
                and self._telegram_poll_thread.is_alive()):
            return

        now = time.time()
        if (now - self._telegram_last_poll) < self._telegram_poll_interval:
            return

        self._telegram_last_poll = now

        def _run() -> None:
            try:
                self._telegram_bridge.poll_and_respond()
                # Track operator contact for proactive scheduler + rhythm
                if (self._proactive_scheduler
                        and self._telegram_bridge.last_poll_message_count > 0):
                    self._proactive_scheduler.record_operator_contact()
                    # Feed RhythmDetector + OperatorModel learning
                    import time as _time
                    ctx = getattr(self, '_shared_context', None)
                    om = getattr(ctx, 'operator_model', None)
                    rd = getattr(ctx, 'rhythm_detector', None)
                    if rd:
                        rd.record_contact(_time.time())
                    if om:
                        # Learn from last messages (non-command texts)
                        for msg_text in getattr(self._telegram_bridge, 'last_poll_texts', []):
                            om.learn_from_message(msg_text)
            except Exception as e:
                self._log_phase_error("11 telegram-poll", e)

            # K9: notify operator when meta-cognition signals needs_human
            if self._planner_core and hasattr(self._planner_core, '_meta_cognition'):
                mc = self._planner_core._meta_cognition
                if mc and hasattr(mc, 'needs_human'):
                    try:
                        if mc.needs_human():
                            self._telegram_bridge.notifier.notify_needs_human(
                                "Spadek pewnosci w decyzjach. Sprawdz /status i /goals."
                            )
                    except Exception:
                        pass

        self._telegram_poll_thread = threading.Thread(
            target=_run, daemon=True, name="TelegramPoll"
        )
        self._telegram_poll_thread_started = time.monotonic()
        self._telegram_poll_thread.start()

    def _check_planner_trigger(self) -> None:
        """
        Check if planner should run this tick.

        Replaces Phase 10 teacher auto-trigger when planner is wired.
        Planner handles its own frequency (every 60 ticks + event-driven).
        Falls back to teacher auto-trigger if no planner configured.

        Runs planner cycle in a background thread to avoid blocking
        the tick loop during long LLM calls (learning/exam sessions).
        """
        if self._planner_core is None:
            # Fallback: if no planner, use old teacher trigger
            self._check_teacher_trigger()
            return

        # Don't start a new cycle if one is already running in background
        if self._planner_thread is not None and self._planner_thread.is_alive():
            return

        try:
            if self._planner_core.should_run(self._tick_count):
                # Capture tick_count before spawning thread
                tick = self._tick_count
                self._start_planner_cycle(tick)
        except Exception as e:
            logger.warning(f"[PLANNER] Trigger error: {e}")

    def _start_planner_cycle(self, tick_count: int) -> None:
        """Start planner cycle in background thread (non-blocking)."""

        def _run():
            try:
                plan = self._planner_core.run_cycle(tick_count)
                if plan:
                    logger.info(
                        f"[PLANNER] Cycle complete: {plan.action_type.value} "
                        f"-> {plan.status.value} "
                        f"({plan.duration_ms:.0f}ms)"
                    )
            except Exception as e:
                logger.warning(f"[PLANNER] Cycle error: {e}")

        self._planner_thread = threading.Thread(
            target=_run, daemon=True, name="PlannerCycle"
        )
        self._planner_thread_started = time.monotonic()
        self._planner_thread.start()

    def _check_teacher_trigger(self) -> None:
        """
        Check if conditions are met for autonomous teacher session.

        Conditions:
        1. Teacher agent is configured
        2. Mode is ACTIVE
        3. Idle >= TEACHER_IDLE_THRESHOLD
        4. No session currently running
        5. Cooldown period has passed
        6. Within learning window (EnvironmentManager LEARNING mode or time-based)
        """
        if self._teacher_agent is None:
            return

        if self.state.mode != Mode.ACTIVE:
            return

        if self.state.idle_seconds < self.TEACHER_IDLE_THRESHOLD:
            return

        # Already running
        if self._teacher_thread is not None and self._teacher_thread.is_alive():
            return

        # Cooldown
        now = time.time()
        if now - self._teacher_last_run < self.TEACHER_COOLDOWN:
            return

        # Learning window gate (idle-triggered only, planner-driven unaffected)
        try:
            from agent_core.environment.environment_model import (
                EnvironmentMode, is_learning_window,
            )
            if self._environment_manager is not None:
                current_mode = self._environment_manager.get_active_mode()
                if current_mode == EnvironmentMode.LEARNING:
                    pass  # Explicitly in learning mode - allow
                elif is_learning_window():
                    pass  # Within time window - allow
                else:
                    return  # Outside learning window - suppress idle learning
            elif not is_learning_window():
                return  # No manager, use static time check
        except Exception as e:
            logger.debug("[TEACHER] Learning window check failed, allowing: %s", e)

        self._start_teacher_session()

    def _start_teacher_session(self) -> None:
        """Start teacher session in background thread."""

        def _run():
            try:
                logger.info("[TEACHER] Auto-session starting (idle trigger)")
                status = self._teacher_agent.run_session(
                    max_iterations=self.TEACHER_MAX_ITERATIONS,
                )
                stats = status.get("stats", {})

                self.event_logger._write_event({
                    "timestamp": time.time(),
                    "event": "teacher_session",
                    "trigger": "idle_auto",
                    "iterations": stats.get("strategies_executed", 0),
                    "chunks_learned": stats.get("chunks_learned", 0),
                    "exams_run": stats.get("exams_run", 0),
                })

                logger.info(
                    f"[TEACHER] Auto-session complete: "
                    f"{stats.get('strategies_executed', 0)} strategies, "
                    f"{stats.get('chunks_learned', 0)} chunks"
                )
            except Exception as e:
                logger.warning(f"[TEACHER] Auto-session failed: {e}")
            finally:
                self._teacher_last_run = time.time()

        self._teacher_thread = threading.Thread(
            target=_run, daemon=True, name="TeacherAutoSession"
        )
        self._teacher_thread_started = time.monotonic()
        self._teacher_thread.start()

    def get_last_sleep_report(self) -> Optional[Dict[str, Any]]:
        """Get report from last sleep cycle (if any)."""
        return self._last_sleep_report

    def _trigger_snapshot(self) -> None:
        """
        Trigger system state snapshot.

        Spec: homeostasis_spec.md lines 1443-1448
        """
        try:
            if self.executor:
                self.executor.signal_module("memory", "checkpoint")
        except Exception as e:
            logger.warning(f"Snapshot trigger failed: {e}")
        # Klocek 9a: persist warm-recovery state on the same beats this fires
        # (mode transitions + corrective action). Flag-gated, best-effort.
        self._write_recovery_snapshot()

    def _write_recovery_snapshot(self) -> None:
        """Persist warm-recovery operational state (Klocek 9a), flag-gated.

        Best-effort and never raises: a recovery write must never be able to
        stall or crash the tick loop (the watchdog would os._exit on a wedge).
        Sources are read from the shared context; mode/last_mode_change come
        straight off self.state. When the flag is OFF this is a cheap no-op."""
        from agent_core.homeostasis import recovery
        if not recovery.is_enabled():
            return
        try:
            ctx = getattr(self, "_shared_context", None)
            sp = getattr(ctx, "strategic_planner", None) if ctx else None
            plan = getattr(sp, "current_plan", None) if sp else None
            gs = getattr(ctx, "goal_store", None) if ctx else None
            snapshot = recovery.build_snapshot(
                mode=self.state.mode.value,
                last_mode_change_time=self.state.last_mode_change_time,
                active_goal_ids=self._active_goal_ids(gs),
                plan_dict=plan.to_dict() if plan else None,
            )
            recovery.write_snapshot(snapshot)
        except Exception:
            logger.warning("[Recovery] write_recovery_snapshot failed", exc_info=True)

    @staticmethod
    def _active_goal_ids(goal_store: Any) -> List[str]:
        """Active goal IDs only -- goals.jsonl stays the source of truth."""
        if goal_store is None or not hasattr(goal_store, "get_active"):
            return []
        try:
            return [g.id for g in goal_store.get_active() if getattr(g, "id", None)]
        except Exception:
            return []

    def _maybe_propose_outbox(self) -> None:
        """Rung 2 (TIER 2 hands): when OUTBOX_WRITE_ENABLED, ask the proposer to
        PROPOSE a status note (it never writes -- the write is operator-gated).
        The flag check lives here so it is unit-testable; OFF or no proposer set
        = cheap no-op. Best-effort: never breaks the tick."""
        if self._outbox_proposer is None:
            return
        try:
            from agent_core.hands import outbox as _outbox
            if _outbox.is_enabled():
                self._outbox_proposer("autonomous")
        except Exception as e:
            logger.warning(f"[Outbox] autonomous propose error: {e}", exc_info=True)

    def _compute_health(
        self,
        state: Dict[str, Any],
        alerts: List[str],
    ) -> float:
        """
        Compute aggregate health score (0-1).

        Spec: homeostasis_spec.md lines 1450-1466

        Args:
            state: Interpreted state
            alerts: Current alerts

        Returns:
            Health score from 0.0 (critical) to 1.0 (healthy)
        """
        score = 1.0

        # Penalty for alerts
        for alert in alerts:
            if "CRITICAL" in alert:
                score -= 0.5
            elif "ALERT" in alert:
                score -= 0.15
            elif "WARNING" in alert:
                score -= 0.05

        # Factor in resource utilization
        memory_pressure = state.get("memory_pressure", 0)
        cpu_load = state.get("cpu_load", 0)

        score *= (1.0 - memory_pressure / 100 * 0.3)
        score *= (1.0 - cpu_load / 100 * 0.2)

        # Clamp to [0, 1]
        return max(0.0, min(1.0, score))

    def _log_state(self, state: Dict[str, Any]) -> None:
        """
        Log periodic state snapshot.

        Spec: homeostasis_spec.md lines 1468-1478
        """
        # Process RSS (resident memory) - track for memory leak detection
        process_rss_mb = self._get_process_rss_mb()

        # Persistent event log (JSONL)
        self.event_logger.log_state_snapshot(
            mode=self.state.mode,
            health_score=self.state.health_score,
            interpreted_state=state,
            alerts_count=len(self.state.alerts),
            tick_count=self._tick_count,
            extra={"process_rss_mb": process_rss_mb} if process_rss_mb else None,
        )

        if process_rss_mb:
            logger.info(
                f"[MEMORY] Process RSS: {process_rss_mb:.1f} MB "
                f"(tick {self._tick_count})"
            )

        # In-memory audit log (backward compatibility)
        self.audit_log.append({
            "timestamp": time.time(),
            "event": "state_snapshot",
            "mode": self.state.mode.value,
            "health": self.state.health_score,
            "ram_available_pct": state.get("ram_available_pct", 0),
            "cpu_load": state.get("cpu_load", 0),
            "process_rss_mb": process_rss_mb,
            "alerts": self.state.alerts.copy(),
        })

        # audit_log is deque(maxlen=1000), auto-evicts old entries

    @staticmethod
    def _get_process_rss_mb() -> Optional[float]:
        """Get current process RSS (Resident Set Size) in MB via /proc."""
        try:
            with open(f"/proc/{os.getpid()}/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        # VmRSS: 123456 kB
                        kb = int(line.split()[1])
                        return kb / 1024.0
        except (OSError, ValueError, IndexError):
            pass
        return None

    # ──────────────────────────────────────────────────────────────────
    # Liveness watchdog (2026-06-02 incident: 10.5h silent tick-loop freeze)
    # ──────────────────────────────────────────────────────────────────
    def start_watchdog(self) -> None:
        """Arm an out-of-loop liveness watchdog on a separate daemon thread.

        The tick runs many blocking phases (LLM calls, vision, sleep cycle). If
        one wedges -- as a strategic-planner Ollama call did on 2026-06-02,
        freezing the loop for 10.5h with nothing noticing (the self-repair
        monitor runs on the same frozen loop) -- only an observer OUTSIDE the
        loop can react. This thread watches the per-tick heartbeat and, on a
        stall past the deadline, dumps every thread's stack and exits non-zero
        so systemd (Restart=on-failure) relaunches a clean process.

        Opt out with MARIA_WATCHDOG=0. Tune with WATCHDOG_STALL_SEC. Idempotent.
        """
        if os.environ.get("MARIA_WATCHDOG", "1").strip().lower() in {
            "0", "false", "no", "off",
        }:
            logger.info("[WATCHDOG] disabled via MARIA_WATCHDOG")
            return
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            return
        self._last_tick_monotonic = time.monotonic()
        self._watchdog_stop.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, name="TickWatchdog", daemon=True
        )
        self._watchdog_thread.start()
        logger.info(
            "[WATCHDOG] armed: stall > %.0fs -> dump + force restart",
            self._watchdog_stall_sec,
        )

    def _tick_stalled_for(self) -> Optional[float]:
        """Seconds since the current tick started, or None before the first tick."""
        if self._last_tick_monotonic is None:
            return None
        return time.monotonic() - self._last_tick_monotonic

    def get_thread_health(self) -> List[Dict[str, Any]]:
        """Per-thread liveness for the 7b heartbeat detector (Phase 19).

        The out-of-loop watchdog only sees the MAIN tick. This reports the
        background workers it structurally cannot:
          * persistent (``TickWatchdog``) -- must stay alive for the whole
            process; if it dies we silently lose the freeze emergency brake.
          * transient (``TelegramPoll``, ``PlannerCycle``,
            ``TeacherAutoSession``) -- spawned per cycle, so not-alive is
            NORMAL; alive far past any sane cycle == wedged (the 2026-06-02
            Ollama freeze, now relocated to a background thread).
        Only threads ever started are reported; a never-started one (feature
        off) is omitted so it is never mistaken for a death. Pure read.
        """
        now = time.monotonic()
        health: List[Dict[str, Any]] = []

        def _transient(name, thread, started):
            alive = thread is not None and thread.is_alive()
            age = (now - started) if (alive and started is not None) else None
            return {
                "name": name,
                "kind": "transient",
                "alive": alive,
                "age_sec": age,
            }

        if self._watchdog_thread is not None:
            health.append({
                "name": "TickWatchdog",
                "kind": "persistent",
                "alive": self._watchdog_thread.is_alive(),
                "age_sec": None,
            })
        if self._telegram_poll_thread is not None:
            health.append(_transient(
                "TelegramPoll",
                self._telegram_poll_thread,
                self._telegram_poll_thread_started,
            ))
        if self._planner_thread is not None:
            health.append(_transient(
                "PlannerCycle",
                self._planner_thread,
                self._planner_thread_started,
            ))
        if self._teacher_thread is not None:
            health.append(_transient(
                "TeacherAutoSession",
                self._teacher_thread,
                self._teacher_thread_started,
            ))
        return health

    def _watchdog_should_trip(self) -> bool:
        """True iff the loop is running and its tick has stalled past the
        deadline. Pure read; the watchdog loop calls it each interval."""
        if not self._running:
            return False
        stalled = self._tick_stalled_for()
        return stalled is not None and stalled >= self._watchdog_stall_sec

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(self._watchdog_check_sec):
            if self._watchdog_should_trip():
                self._trip_watchdog(self._tick_stalled_for() or 0.0)

    def _trip_watchdog(self, stalled: float) -> None:
        """Last resort: the tick loop is wedged. Record where, then hard-exit so
        systemd restarts us. Uses os._exit because the main thread is stuck in a
        blocking call -- a SIGTERM would not be serviced until it returned."""
        logger.critical(
            "[WATCHDOG] tick loop stalled %.0fs (> %.0fs) at tick %s -- dumping "
            "stacks and forcing restart", stalled, self._watchdog_stall_sec,
            self._tick_count,
        )
        try:
            import faulthandler
            import sys
            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(1)

    def stop(self, reason: str = "user_request") -> None:
        """Stop the main loop."""
        self._running = False
        self._watchdog_stop.set()
        self.event_logger.log_shutdown(reason=reason)
        self.event_logger.flush()

    def is_running(self) -> bool:
        """Check if main loop is running."""
        return self._running

    def get_state(self) -> SystemState:
        """Get current system state."""
        return self.state

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent audit log entries."""
        return list(self.audit_log)[-limit:]

    def record_user_interaction(self) -> None:
        """Record that user interaction occurred."""
        self.time_sensor.record_interaction()

    def record_activity(self) -> None:
        """Record system activity (non-user)."""
        self.time_sensor.record_activity()

    def get_telemetry(self) -> Dict[str, Any]:
        """
        Get current telemetry snapshot.

        Returns comprehensive system status for UI/API.
        """
        telemetry = {
            "mode": self.state.mode.value,
            "health_score": self.state.health_score,
            "alerts": self.state.alerts.copy(),
            "idle_seconds": self.state.idle_seconds,
            "tick_count": self._tick_count,
            "mode_duration_sec": self.state.mode_duration_seconds,
            "interpreted_state": self.state.interpreted_state.copy(),
        }
        if self._perception_buffer is not None:
            telemetry["perception"] = self._perception_buffer.stats()
        return telemetry
