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

import os
import time
import threading
import logging
from collections import deque
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

        # Sleep processing (set via set_semantic_memory)
        self._semantic_memory = None
        self._session_id = 0
        self._last_sleep_report = None
        self._experience_tracker = None

        # Perception (Warstwa 1, ADR-009: Tick Aggregator)
        self._perception_buffer = None  # Set via set_perception_buffer()
        self._external_queue: Deque = deque(maxlen=50)  # Thread-safe external events

        # Teacher auto-trigger (set via set_teacher_agent)
        self._teacher_agent = None
        self._teacher_thread: Optional[threading.Thread] = None
        self._teacher_last_run = 0.0

        # Planner (Warstwa 2 - replaces teacher auto-trigger when wired)
        self._planner_core = None
        self._planner_thread: Optional[threading.Thread] = None

        # Model Scheduler (multi-organ model stack)
        self._model_scheduler = None

        # Telegram bridge (operator notifications)
        self._telegram_bridge = None
        self._telegram_poll_interval = 30  # seconds
        self._telegram_last_poll = 0.0

    def set_semantic_memory(self, semantic_memory, session_id: int = 0, experience_tracker=None) -> None:
        """
        Set semantic memory reference for sleep processing.

        Called from HomeostasisModule after init.

        Args:
            semantic_memory: SemanticGraph instance
            session_id: Current session number
            experience_tracker: ExperienceTracker for recording sleep events
        """
        self._semantic_memory = semantic_memory
        self._session_id = session_id
        self._experience_tracker = experience_tracker

    def set_teacher_agent(self, teacher_agent) -> None:
        """
        Set teacher agent for autonomous learning during idle.

        Called from HomeostasisModule after init.

        Args:
            teacher_agent: TeacherAgent instance (with learn/exam fns already set)
        """
        self._teacher_agent = teacher_agent

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

    def set_telegram_bridge(self, bridge) -> None:
        """
        Set Telegram bridge for operator notifications.

        Bridge polls for messages and sends alerts.
        Called from HomeostasisModule after init.
        """
        self._telegram_bridge = bridge

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
        # ──────────────────────────────────────
        # PHASE 1: SENSE
        # ──────────────────────────────────────
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
            except Exception:
                pass

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
                logger.debug(f"ModelScheduler tick error: {e}")

        # ──────────────────────────────────────
        # PHASE 10: PLANNER (or teacher fallback)
        # ──────────────────────────────────────
        self._check_planner_trigger()

        # ──────────────────────────────────────
        # PHASE 11: TELEGRAM (poll + notify)
        # ──────────────────────────────────────
        self._check_telegram()

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
            logger.debug(f"Perception aggregation error: {e}")

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

    def _run_sleep_cycle(self) -> None:
        """
        Run sleep processing when entering SLEEP mode.

        Phases: NREM1 (stats) -> NREM2 (strengthen) -> NREM3 (cleanup) -> REM (dreams).
        """
        if not self._semantic_memory:
            logger.info("Sleep cycle skipped: no semantic_memory set")
            return

        try:
            from agent_core.consciousness.sleep_processor import SleepProcessor

            processor = SleepProcessor(
                semantic_memory=self._semantic_memory,
                session_id=self._session_id,
            )
            report = processor.process_sleep_cycle()
            self._last_sleep_report = report

            # Log sleep cycle event
            dream_count = report.get("rem", {}).get("dreams_generated", 0)
            self.event_logger._write_event({
                "timestamp": time.time(),
                "event": "sleep_cycle",
                "dream_count": dream_count,
                "phases_completed": report.get("phases_completed", 0),
                "session_id": self._session_id,
            })

            logger.info(
                f"Sleep cycle completed: {dream_count} dreams, "
                f"{report.get('phases_completed', 0)} phases"
            )
        except Exception as e:
            logger.warning(f"Sleep cycle failed: {e}")

    def _check_telegram(self) -> None:
        """
        Poll Telegram for operator messages (Phase 11).

        Runs every _telegram_poll_interval seconds (default 30).
        Non-blocking: poll takes ~1s max (short HTTP timeout).
        """
        if self._telegram_bridge is None:
            return

        now = time.time()
        if (now - self._telegram_last_poll) < self._telegram_poll_interval:
            return

        self._telegram_last_poll = now

        try:
            self._telegram_bridge.poll_and_respond()
        except Exception as e:
            logger.debug(f"[TELEGRAM] Poll error: {e}")

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

    def stop(self, reason: str = "user_request") -> None:
        """Stop the main loop."""
        self._running = False
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
