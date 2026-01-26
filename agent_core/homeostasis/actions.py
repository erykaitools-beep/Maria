"""
Corrective Action Generator and Alarm Dispatcher

Generates corrective actions based on system state:
- Memory consolidation requests
- Learning pause signals
- Inference throttling
- Goal stack interrupts
- Critical alarm dispatch

Spec reference: homeostasis_spec.md lines 1222-1286, 143-155
"""

import time
from typing import Dict, Any, List, Optional
from enum import Enum
from dataclasses import dataclass


class ActionType(Enum):
    """Types of corrective actions."""
    MODE_CHANGE = "mode_change"
    SIGNAL_MODULE = "signal_module"
    TRIGGER_CONSOLIDATION = "trigger_consolidation"
    TRIGGER_SNAPSHOT = "trigger_snapshot"
    OPERATOR_ALERT = "operator_alert"


class Urgency(Enum):
    """Action urgency levels."""
    IMMEDIATE = "immediate"   # Execute now
    SOON = "soon"            # Execute within next tick
    BACKGROUND = "background" # Execute when resources allow


@dataclass
class CorrectiveAction:
    """
    A corrective action to be executed.

    Spec: homeostasis_spec.md lines 1226-1235
    """
    action_type: ActionType
    target: str
    action: str
    urgency: Urgency
    reason: str
    parameters: Dict[str, Any] = None

    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "type": self.action_type.value,
            "target": self.target,
            "action": self.action,
            "urgency": self.urgency.value,
            "reason": self.reason,
            "parameters": self.parameters,
        }


class CorrectiveActionGenerator:
    """
    Generates corrective actions based on system state.

    Analyzes state and alerts to determine what actions
    should be taken to restore homeostasis.

    Spec: homeostasis_spec.md lines 1222-1286
    """

    # Thresholds for action generation
    MEMORY_PRESSURE_CONSOLIDATE = 75  # % → suggest consolidation
    CPU_PAUSE_LEARNING = 75           # % → pause background learning
    LATENCY_REDUCE_BATCH = 2000       # ms → reduce inference batch
    GOAL_DEPTH_INTERRUPT = 25         # depth → interrupt refinement

    def __init__(self):
        """Initialize action generator."""
        self._recent_actions: List[CorrectiveAction] = []
        self._last_consolidation_request = 0
        self._consolidation_cooldown = 300  # 5 minutes

    def generate_actions(
        self,
        state: Dict[str, Any],
        alerts: List[str],
    ) -> List[CorrectiveAction]:
        """
        Generate corrective actions based on state and alerts.

        Spec: homeostasis_spec.md lines 1225-1286

        Args:
            state: Interpreted state dictionary
            alerts: List of current alerts

        Returns:
            List of CorrectiveAction objects to execute
        """
        actions = []
        now = time.time()

        # Action 1: Memory consolidation
        memory_pressure = state.get("memory_pressure", 0)
        if memory_pressure > self.MEMORY_PRESSURE_CONSOLIDATE:
            # Check cooldown
            if now - self._last_consolidation_request > self._consolidation_cooldown:
                actions.append(CorrectiveAction(
                    action_type=ActionType.SIGNAL_MODULE,
                    target="memory",
                    action="consolidate_episodic",
                    urgency=Urgency.SOON,
                    reason=f"Memory pressure at {memory_pressure:.0f}%",
                    parameters={"target_freed_mb": 300},
                ))
                self._last_consolidation_request = now

        # Action 2: Pause background learning
        cpu_load = state.get("cpu_load", 0)
        if cpu_load > self.CPU_PAUSE_LEARNING:
            actions.append(CorrectiveAction(
                action_type=ActionType.SIGNAL_MODULE,
                target="learning_engine",
                action="pause",
                urgency=Urgency.SOON,
                reason=f"CPU saturation at {cpu_load:.0f}%",
            ))

        # Action 3: Reduce inference batch size
        inference_latency = state.get("inference_latency_ms", 0)
        if inference_latency > self.LATENCY_REDUCE_BATCH:
            actions.append(CorrectiveAction(
                action_type=ActionType.SIGNAL_MODULE,
                target="llm",
                action="reduce_batch_size",
                urgency=Urgency.IMMEDIATE,
                reason=f"Inference latency at {inference_latency:.0f}ms",
                parameters={"factor": 0.5},
            ))

        # Action 4: Goal stack interrupt
        if state.get("goal_stack_runaway", False):
            goal_depth = state.get("goal_stack_depth", 0)
            actions.append(CorrectiveAction(
                action_type=ActionType.SIGNAL_MODULE,
                target="metacontroller",
                action="interrupt_goal_refinement",
                urgency=Urgency.IMMEDIATE,
                reason=f"Goal stack depth at {goal_depth}",
            ))

        # Action 5: Semantic consistency check
        if not state.get("coherence_ok", True) and memory_pressure > 50:
            actions.append(CorrectiveAction(
                action_type=ActionType.SIGNAL_MODULE,
                target="memory",
                action="semantic_consistency_check",
                urgency=Urgency.BACKGROUND,
                reason="Coherence degraded with memory pressure",
            ))

        # Action 6: Snapshot before risky operations
        if any("ALERT" in a for a in alerts):
            actions.append(CorrectiveAction(
                action_type=ActionType.TRIGGER_SNAPSHOT,
                target="homeostasis",
                action="checkpoint",
                urgency=Urgency.SOON,
                reason="ALERT condition detected",
            ))

        # Action 7: Thermal throttling
        temp_c = state.get("temp_c", 50)
        if temp_c > 85:
            actions.append(CorrectiveAction(
                action_type=ActionType.SIGNAL_MODULE,
                target="llm",
                action="reduce_batch_size",
                urgency=Urgency.IMMEDIATE,
                reason=f"Thermal stress at {temp_c:.1f}°C",
                parameters={"factor": 0.5},
            ))
            actions.append(CorrectiveAction(
                action_type=ActionType.SIGNAL_MODULE,
                target="learning_engine",
                action="pause",
                urgency=Urgency.IMMEDIATE,
                reason=f"Thermal stress at {temp_c:.1f}°C",
            ))

        # Track actions for reporting
        self._recent_actions = actions

        return actions

    def get_recent_actions(self) -> List[CorrectiveAction]:
        """Get most recently generated actions."""
        return self._recent_actions


class AlarmDispatcher:
    """
    Dispatches critical alarms and operator notifications.

    Handles:
    - Critical interrupt signals
    - Graceful shutdown preparation
    - Operator alerts

    Spec: homeostasis_spec.md lines 143-155
    """

    def __init__(self):
        """Initialize alarm dispatcher."""
        self._alarm_history: List[Dict[str, Any]] = []
        self._pending_operator_alerts: List[str] = []

    def dispatch_critical(
        self,
        alarm_type: str,
        message: str,
        recommended_action: str,
    ) -> None:
        """
        Dispatch a critical alarm.

        Args:
            alarm_type: Type of alarm (e.g., 'OOM', 'THERMAL', 'LLM_HANG')
            message: Human-readable message
            recommended_action: What should be done
        """
        alarm = {
            "timestamp": time.time(),
            "type": alarm_type,
            "severity": "CRITICAL",
            "message": message,
            "recommended_action": recommended_action,
        }
        self._alarm_history.append(alarm)
        self._pending_operator_alerts.append(
            f"CRITICAL [{alarm_type}]: {message}"
        )

    def dispatch_alert(
        self,
        alarm_type: str,
        message: str,
    ) -> None:
        """
        Dispatch a non-critical alert.

        Args:
            alarm_type: Type of alert
            message: Human-readable message
        """
        alarm = {
            "timestamp": time.time(),
            "type": alarm_type,
            "severity": "ALERT",
            "message": message,
        }
        self._alarm_history.append(alarm)

    def dispatch_warning(
        self,
        warning_type: str,
        message: str,
    ) -> None:
        """
        Dispatch a warning.

        Args:
            warning_type: Type of warning
            message: Human-readable message
        """
        alarm = {
            "timestamp": time.time(),
            "type": warning_type,
            "severity": "WARNING",
            "message": message,
        }
        self._alarm_history.append(alarm)

    def prepare_graceful_shutdown(self) -> List[CorrectiveAction]:
        """
        Prepare for graceful shutdown.

        Returns actions needed for clean shutdown.

        Spec: homeostasis_spec.md lines 1706-1726
        """
        return [
            CorrectiveAction(
                action_type=ActionType.SIGNAL_MODULE,
                target="all",
                action="shutdown_prepare",
                urgency=Urgency.IMMEDIATE,
                reason="Graceful shutdown initiated",
            ),
            CorrectiveAction(
                action_type=ActionType.TRIGGER_SNAPSHOT,
                target="homeostasis",
                action="final_checkpoint",
                urgency=Urgency.IMMEDIATE,
                reason="Pre-shutdown snapshot",
            ),
        ]

    def get_pending_operator_alerts(self) -> List[str]:
        """Get and clear pending operator alerts."""
        alerts = self._pending_operator_alerts.copy()
        self._pending_operator_alerts.clear()
        return alerts

    def get_alarm_history(
        self,
        limit: int = 100,
        severity: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get alarm history.

        Args:
            limit: Maximum number of alarms to return
            severity: Filter by severity ('CRITICAL', 'ALERT', 'WARNING')

        Returns:
            List of alarm records
        """
        history = self._alarm_history
        if severity:
            history = [a for a in history if a["severity"] == severity]
        return history[-limit:]

    def clear_history(self) -> None:
        """Clear alarm history."""
        self._alarm_history.clear()
