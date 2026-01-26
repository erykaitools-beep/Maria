"""
Homeostasis Public API and Event Bus

Provides:
- HomeostasisInterface: Public API for other modules
- HomeostasisEventBus: Event broadcasting system

API operations:
- READ: get_current_mode, get_resource_headroom, get_health_score, get_alert_state
- WRITE: request_resource_allocation, notify_module_state
- SIGNAL: signal_critical_error, request_mode_override

Events:
- mode_changed
- resource_reduced
- alert_raised
- health_degraded
- recovery_started

Spec reference: homeostasis_spec.md lines 709-817
"""

import time
import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

from .state_model import Mode


class ResourceType(Enum):
    """Types of resources that can be allocated."""
    CPU = "cpu"
    MEMORY = "memory"
    GPU_MEMORY = "gpu_memory"
    INFERENCE_TOKENS = "inference_tokens"


class Priority(Enum):
    """Priority levels for resource requests."""
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    BACKGROUND = "background"


@dataclass
class ResourceAllocation:
    """A resource allocation request/grant."""
    module_name: str
    resource_type: ResourceType
    quantity: int
    duration_seconds: int
    priority: Priority
    granted_at: float = 0
    expires_at: float = 0


@dataclass
class ModuleState:
    """State reported by a module."""
    module_name: str
    timestamp: float
    state: Dict[str, Any]


class HomeostasisInterface:
    """
    Public interface for other modules to interact with homeostasis.

    Spec: homeostasis_spec.md lines 712-798
    """

    def __init__(self):
        """Initialize homeostasis interface."""
        self._core = None  # Set by HomeostasisCore
        self._allocations: Dict[str, ResourceAllocation] = {}
        self._module_states: Dict[str, ModuleState] = {}
        self._lock = threading.Lock()

    def set_core(self, core) -> None:
        """Set reference to homeostasis core."""
        self._core = core

    # ─────────────────────────────────────────────
    # READ OPERATIONS (non-blocking, always safe)
    # ─────────────────────────────────────────────

    def get_current_mode(self) -> Mode:
        """
        Get current operating mode.

        Returns:
            Current Mode (ACTIVE, REDUCED, SLEEP, SURVIVAL)

        Spec: homeostasis_spec.md lines 716-718
        """
        if self._core:
            return self._core.state.mode
        return Mode.ACTIVE

    def get_resource_headroom(self) -> Dict[str, float]:
        """
        Get current resource availability.

        Returns:
            Dictionary with ram_pct, cpu_pct, disk_pct, thermal_pct

        Spec: homeostasis_spec.md lines 720-722
        """
        if self._core and self._core.state.interpreted_state:
            state = self._core.state.interpreted_state
            return {
                "ram_pct": state.get("ram_available_pct", 0),
                "cpu_pct": 100 - state.get("cpu_load", 100),
                "disk_pct": 100 - state.get("disk_used_pct", 100),
                "thermal_pct": 100 - state.get("thermal_stress", 0) * 100,
            }
        return {"ram_pct": 50, "cpu_pct": 50, "disk_pct": 50, "thermal_pct": 100}

    def get_health_score(self) -> float:
        """
        Get aggregate health score.

        Returns:
            Health score from 0.0 (critical) to 1.0 (healthy)

        Spec: homeostasis_spec.md lines 724-726
        """
        if self._core:
            return self._core.state.health_score
        return 1.0

    def get_alert_state(self) -> List[str]:
        """
        Get current alerts.

        Returns:
            List of alert strings

        Spec: homeostasis_spec.md lines 728-730
        """
        if self._core:
            return self._core.state.alerts.copy()
        return []

    def get_telemetry_snapshot(self) -> Dict[str, Any]:
        """
        Get full diagnostic dump for operator UI.

        Returns:
            Complete telemetry dictionary

        Spec: homeostasis_spec.md lines 732-734
        """
        if self._core:
            return self._core.get_telemetry()
        return {}

    # ─────────────────────────────────────────────
    # WRITE OPERATIONS (requests, not commands)
    # ─────────────────────────────────────────────

    def request_resource_allocation(
        self,
        module_name: str,
        resource_type: str,
        quantity: int,
        duration_seconds: int,
        priority: str = "normal",
    ) -> bool:
        """
        Request resource allocation.

        Spec: homeostasis_spec.md lines 737-755

        Args:
            module_name: Name of requesting module
            resource_type: Type of resource (cpu, memory, gpu_memory, inference_tokens)
            quantity: Amount requested
            duration_seconds: How long needed
            priority: Priority level (critical, high, normal, background)

        Returns:
            True if granted, False if denied
        """
        with self._lock:
            try:
                res_type = ResourceType(resource_type)
                pri = Priority(priority)
            except ValueError:
                return False

            # Check if resources available
            headroom = self.get_resource_headroom()
            mode = self.get_current_mode()

            # Deny background requests in REDUCED/SURVIVAL
            if pri == Priority.BACKGROUND and mode in [Mode.REDUCED, Mode.SURVIVAL]:
                return False

            # Deny all non-critical in SURVIVAL
            if mode == Mode.SURVIVAL and pri != Priority.CRITICAL:
                return False

            # Simple allocation logic (could be more sophisticated)
            if res_type == ResourceType.MEMORY:
                if headroom["ram_pct"] < 20:
                    return False
            elif res_type == ResourceType.CPU:
                if headroom["cpu_pct"] < 20:
                    return False

            # Grant allocation
            now = time.time()
            allocation = ResourceAllocation(
                module_name=module_name,
                resource_type=res_type,
                quantity=quantity,
                duration_seconds=duration_seconds,
                priority=pri,
                granted_at=now,
                expires_at=now + duration_seconds,
            )
            self._allocations[f"{module_name}:{resource_type}"] = allocation

            return True

    def notify_module_state(self, module_name: str, state: Dict[str, Any]) -> None:
        """
        Module reports its state to homeostasis.

        Spec: homeostasis_spec.md lines 757-770

        Args:
            module_name: Name of reporting module
            state: State dictionary (e.g., latency, tokens, errors)
        """
        with self._lock:
            self._module_states[module_name] = ModuleState(
                module_name=module_name,
                timestamp=time.time(),
                state=state,
            )

            # Update sensors with module data
            if self._core:
                if module_name == "llm" and "inference_latency_ms" in state:
                    # Could update cognitive sensor
                    pass

    # ─────────────────────────────────────────────
    # SIGNAL OPERATIONS (urgent)
    # ─────────────────────────────────────────────

    def signal_critical_error(
        self,
        module_name: str,
        error_type: str,
        urgency: str,
        recovery_suggestion: str,
    ) -> None:
        """
        Signal a critical error.

        Used ONLY for hard failures.

        Spec: homeostasis_spec.md lines 773-780

        Args:
            module_name: Name of module reporting error
            error_type: Type of error
            urgency: 'immediate' | 'soon' | 'background'
            recovery_suggestion: Suggested recovery action
        """
        if self._core:
            self._core.alarm_dispatcher.dispatch_critical(
                alarm_type=f"{module_name}:{error_type}",
                message=f"Module {module_name} reported {error_type}",
                recommended_action=recovery_suggestion,
            )

            # Record error in cognitive sensor
            self._core.cognitive_sensor.record_error()

    def request_mode_override(
        self,
        desired_mode: str,
        duration_seconds: int,
        reason: str,
    ) -> bool:
        """
        Request mode override from meta-controller.

        Spec: homeostasis_spec.md lines 782-798

        Args:
            desired_mode: Requested mode (active, reduced, sleep)
            duration_seconds: How long to maintain override
            reason: Why override is needed

        Returns:
            True if allowed, False if system too critical
        """
        if not self._core:
            return False

        try:
            mode = Mode(desired_mode)
        except ValueError:
            return False

        state = self._core.state.interpreted_state
        alerts = self._core.state.alerts

        allowed, message = self._core.regulator.request_mode_override(
            desired_mode=mode,
            duration_seconds=duration_seconds,
            reason=reason,
            state=state,
            alerts=alerts,
        )

        return allowed

    def get_module_states(self) -> Dict[str, ModuleState]:
        """Get all reported module states."""
        with self._lock:
            return self._module_states.copy()

    def get_active_allocations(self) -> List[ResourceAllocation]:
        """Get all active resource allocations."""
        with self._lock:
            now = time.time()
            return [a for a in self._allocations.values() if a.expires_at > now]


# ─────────────────────────────────────────────────
# EVENT BUS
# ─────────────────────────────────────────────────

class HomeostasisEventBus:
    """
    Event broadcasting system for homeostasis.

    Modules subscribe to events and receive notifications.

    Spec: homeostasis_spec.md lines 801-817
    """

    def __init__(self):
        """Initialize event bus."""
        self._subscribers: Dict[str, List[Callable]] = {
            "mode_changed": [],
            "resource_reduced": [],
            "alert_raised": [],
            "health_degraded": [],
            "recovery_started": [],
        }
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, callback: Callable) -> bool:
        """
        Subscribe to an event type.

        Args:
            event_type: Type of event to subscribe to
            callback: Function to call when event occurs

        Returns:
            True if subscribed successfully
        """
        with self._lock:
            if event_type in self._subscribers:
                self._subscribers[event_type].append(callback)
                return True
            return False

    def unsubscribe(self, event_type: str, callback: Callable) -> bool:
        """
        Unsubscribe from an event type.

        Args:
            event_type: Type of event
            callback: Function to remove

        Returns:
            True if unsubscribed successfully
        """
        with self._lock:
            if event_type in self._subscribers:
                try:
                    self._subscribers[event_type].remove(callback)
                    return True
                except ValueError:
                    pass
            return False

    def emit_mode_changed(
        self,
        old_mode: Mode,
        new_mode: Mode,
        reason: str,
    ) -> None:
        """
        Emit mode changed event.

        Spec: homeostasis_spec.md lines 804-805
        """
        self._emit("mode_changed", {
            "old_mode": old_mode.value,
            "new_mode": new_mode.value,
            "reason": reason,
            "timestamp": time.time(),
        })

    def emit_resource_reduced(
        self,
        resource_type: str,
        new_allocation: int,
    ) -> None:
        """
        Emit resource reduced event.

        Spec: homeostasis_spec.md lines 807-808
        """
        self._emit("resource_reduced", {
            "resource_type": resource_type,
            "new_allocation": new_allocation,
            "timestamp": time.time(),
        })

    def emit_alert_raised(
        self,
        alert_type: str,
        severity: str,
        recommended_action: str,
    ) -> None:
        """
        Emit alert raised event.

        Spec: homeostasis_spec.md lines 810-811
        """
        self._emit("alert_raised", {
            "alert_type": alert_type,
            "severity": severity,
            "recommended_action": recommended_action,
            "timestamp": time.time(),
        })

    def emit_health_degraded(
        self,
        health_score: float,
        first_issue: str,
    ) -> None:
        """
        Emit health degraded event.

        Spec: homeostasis_spec.md lines 813-814
        """
        self._emit("health_degraded", {
            "health_score": health_score,
            "first_issue": first_issue,
            "timestamp": time.time(),
        })

    def emit_recovery_started(
        self,
        from_state: str,
        recovery_type: str,
    ) -> None:
        """
        Emit recovery started event.

        Spec: homeostasis_spec.md lines 816-817
        """
        self._emit("recovery_started", {
            "from_state": from_state,
            "recovery_type": recovery_type,
            "timestamp": time.time(),
        })

    def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit event to all subscribers."""
        with self._lock:
            subscribers = self._subscribers.get(event_type, []).copy()

        for callback in subscribers:
            try:
                callback(data)
            except Exception as e:
                # Don't let subscriber errors break the bus
                pass
