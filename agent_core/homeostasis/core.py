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
7. AUDIT: Log state and decisions

Spec reference: homeostasis_spec.md section 7.1 (lines 1289-1478)
"""

import time
import threading
import logging
from typing import Dict, Any, List, Optional, TYPE_CHECKING

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

    def __init__(
        self,
        memory_manager: Optional["MemoryManager"] = None,
        llm_manager: Optional["LLMManager"] = None,
        executor: Optional["ModuleExecutor"] = None,
        thresholds: Optional[Thresholds] = None,
    ):
        """
        Initialize homeostasis core.

        Args:
            memory_manager: Memory module interface
            llm_manager: LLM module interface
            executor: Module signal executor
            thresholds: Custom constraint thresholds
        """
        # External dependencies
        self.memory = memory_manager
        self.llm = llm_manager
        self.executor = executor

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
        self.alarm_dispatcher = AlarmDispatcher()

        # State
        self.state = SystemState(
            mode=Mode.ACTIVE,
            health_score=1.0,
            last_mode_change_time=time.time(),
            alerts=[],
            idle_seconds=0,
        )

        # Audit log
        self.audit_log: List[Dict[str, Any]] = []

        # Control
        self._running = False
        self._tick_count = 0

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

        # ──────────────────────────────────────
        # PHASE 8: AUDIT & LOG
        # ──────────────────────────────────────
        if self._tick_count % self.LOG_INTERVAL_TICKS == 0:
            self._log_state(interpreted_state)

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
            elif new_mode == Mode.SURVIVAL:
                self.executor.signal_module("llm", "minimize")
                self.executor.signal_module("memory", "readonly")
            elif new_mode == Mode.REDUCED:
                self.executor.signal_module("learning_engine", "pause")
            elif new_mode == Mode.ACTIVE:
                self.executor.signal_module("learning_engine", "resume")

        # Update state
        result = self.regulator.transition_to(new_mode)
        self.state.mode = new_mode
        self.state.last_mode_change_time = time.time()

        # Audit log
        self.audit_log.append({
            "timestamp": time.time(),
            "event": "mode_change",
            "from": old_mode.value,
            "to": new_mode.value,
        })

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
        self.audit_log.append({
            "timestamp": time.time(),
            "event": "state_snapshot",
            "mode": self.state.mode.value,
            "health": self.state.health_score,
            "ram_available_pct": state.get("ram_available_pct", 0),
            "cpu_load": state.get("cpu_load", 0),
            "alerts": self.state.alerts.copy(),
        })

        # Keep audit log bounded
        if len(self.audit_log) > 10000:
            self.audit_log = self.audit_log[-5000:]

    def stop(self) -> None:
        """Stop the main loop."""
        self._running = False

    def is_running(self) -> bool:
        """Check if main loop is running."""
        return self._running

    def get_state(self) -> SystemState:
        """Get current system state."""
        return self.state

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent audit log entries."""
        return self.audit_log[-limit:]

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
        return {
            "mode": self.state.mode.value,
            "health_score": self.state.health_score,
            "alerts": self.state.alerts.copy(),
            "idle_seconds": self.state.idle_seconds,
            "tick_count": self._tick_count,
            "mode_duration_sec": self.state.mode_duration_seconds,
            "interpreted_state": self.state.interpreted_state.copy(),
        }
