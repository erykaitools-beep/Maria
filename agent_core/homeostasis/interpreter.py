"""
State Interpreter - Raw metrics to semantic state conversion

Converts raw sensor data to semantic state with:
- Exponential moving average (EMA) smoothing
- Derived metrics calculation
- Semantic interpretation

Spec reference: homeostasis_spec.md lines 1015-1084
"""

import time
from typing import Dict, Any, List, Optional
from collections import deque

from .state_model import ResourceMetrics, CognitiveMetrics


class StateInterpreter:
    """
    Converts raw metrics to semantic state.

    Applies exponential smoothing to reduce noise and
    calculates derived metrics for decision making.

    Spec: homeostasis_spec.md section 7.1 StateInterpreter class
    """

    # EMA smoothing parameter (0-1, lower = smoother)
    DEFAULT_ALPHA = 0.3

    def __init__(self, alpha: float = DEFAULT_ALPHA, history_size: int = 10):
        """
        Initialize state interpreter.

        Args:
            alpha: EMA smoothing factor (0.3 = moderate smoothing)
            history_size: Number of samples to keep for averaging
        """
        self.alpha = alpha
        self._resource_history: deque = deque(maxlen=history_size)
        self._cognitive_history: deque = deque(maxlen=history_size)

        # Smoothed values
        self._smoothed_ram_used = None
        self._smoothed_cpu = None
        self._smoothed_temp = None
        self._smoothed_latency = None

    def process_metrics(
        self,
        resource: ResourceMetrics,
        cognitive: CognitiveMetrics,
        idle_seconds: float = 0,
    ) -> Dict[str, Any]:
        """
        Interpret metrics into semantic state.

        Args:
            resource: Hardware resource metrics
            cognitive: Cognitive state metrics
            idle_seconds: Seconds since last user interaction

        Returns:
            Dictionary with interpreted semantic state

        Spec: homeostasis_spec.md lines 1025-1063
        """
        # Add to history
        self._resource_history.append(resource)
        self._cognitive_history.append(cognitive)

        # Apply EMA smoothing
        smoothed_resource = self._smooth_resource_metrics(resource)

        # Calculate derived metrics
        ram_available_pct = smoothed_resource.ram_available_pct
        cpu_load = smoothed_resource.cpu_percent
        memory_pressure = smoothed_resource.memory_pressure

        # Thermal stress (0-1 scale, 60°C = 0, 95°C = 1)
        thermal_stress = max(0, min(1, (smoothed_resource.temp_c - 60) / 35))

        # Cognitive interpretation
        coherence_ok = cognitive.context_coherence > 0.85
        errors_high = cognitive.error_count_1h > 20
        goal_stack_runaway = cognitive.goal_stack_depth > 25
        attention_dispersed = cognitive.attention_fragmentation > 0.7

        return {
            "timestamp": resource.timestamp,

            # Resource state
            "ram_available_pct": ram_available_pct,
            "ram_available_mb": smoothed_resource.ram_available_mb,
            "cpu_load": cpu_load,
            "thermal_stress": thermal_stress,
            "memory_pressure": memory_pressure,
            "disk_used_pct": smoothed_resource.disk_used_pct,
            "temp_c": smoothed_resource.temp_c,

            # Cognitive state (boolean flags)
            "coherence_ok": coherence_ok,
            "errors_high": errors_high,
            "goal_stack_runaway": goal_stack_runaway,
            "attention_dispersed": attention_dispersed,

            # Numeric cognitive values
            "context_coherence": cognitive.context_coherence,
            "error_count_1h": cognitive.error_count_1h,
            "goal_stack_depth": cognitive.goal_stack_depth,
            "inference_latency_ms": cognitive.inference_latency_ms,
            "contradiction_count": cognitive.contradiction_count,
            "task_completion_ratio": cognitive.task_completion_ratio,

            # Time state
            "idle_seconds": idle_seconds,

            # Raw values for logging
            "raw_cpu_percent": resource.cpu_percent,
            "raw_ram_used_mb": resource.ram_used_mb,
        }

    def _smooth_resource_metrics(self, metrics: ResourceMetrics) -> ResourceMetrics:
        """
        Apply exponential moving average smoothing.

        Spec: homeostasis_spec.md lines 1065-1083
        """
        # Initialize smoothed values on first call
        if self._smoothed_ram_used is None:
            self._smoothed_ram_used = metrics.ram_used_mb
            self._smoothed_cpu = metrics.cpu_percent
            self._smoothed_temp = metrics.temp_c
            self._smoothed_latency = metrics.inference_latency_ms
        else:
            # Apply EMA: new = alpha * current + (1-alpha) * previous
            self._smoothed_ram_used = (
                self.alpha * metrics.ram_used_mb +
                (1 - self.alpha) * self._smoothed_ram_used
            )
            self._smoothed_cpu = (
                self.alpha * metrics.cpu_percent +
                (1 - self.alpha) * self._smoothed_cpu
            )
            self._smoothed_temp = (
                self.alpha * metrics.temp_c +
                (1 - self.alpha) * self._smoothed_temp
            )
            self._smoothed_latency = (
                self.alpha * metrics.inference_latency_ms +
                (1 - self.alpha) * self._smoothed_latency
            )

        # Return new metrics with smoothed values
        return ResourceMetrics(
            timestamp=metrics.timestamp,
            ram_used_mb=self._smoothed_ram_used,
            ram_total_mb=metrics.ram_total_mb,
            ram_available_mb=metrics.ram_total_mb - self._smoothed_ram_used,
            swap_used_pct=metrics.swap_used_pct,
            cpu_percent=self._smoothed_cpu,
            load_avg_1m=metrics.load_avg_1m,
            load_avg_5m=metrics.load_avg_5m,
            load_avg_15m=metrics.load_avg_15m,
            disk_used_pct=metrics.disk_used_pct,
            disk_io_queue_depth=metrics.disk_io_queue_depth,
            process_count=metrics.process_count,
            temp_c=self._smoothed_temp,
            inference_latency_ms=self._smoothed_latency,
        )

    def get_trend(self, metric_name: str, window: int = 5) -> str:
        """
        Analyze trend for a metric.

        Args:
            metric_name: Name of metric (e.g., 'cpu_percent', 'ram_used_mb')
            window: Number of samples to analyze

        Returns:
            'rising', 'falling', or 'stable'
        """
        if len(self._resource_history) < window:
            return "stable"

        recent = list(self._resource_history)[-window:]

        # Get values for the metric
        try:
            values = [getattr(m, metric_name) for m in recent]
        except AttributeError:
            return "stable"

        # Calculate trend
        first_half = sum(values[:len(values)//2]) / (len(values)//2)
        second_half = sum(values[len(values)//2:]) / (len(values) - len(values)//2)

        diff_pct = (second_half - first_half) / max(first_half, 1) * 100

        if diff_pct > 10:
            return "rising"
        elif diff_pct < -10:
            return "falling"
        else:
            return "stable"

    def get_average(self, metric_name: str, window: int = 5) -> Optional[float]:
        """
        Get average value for a metric over recent history.

        Args:
            metric_name: Name of metric
            window: Number of samples to average

        Returns:
            Average value or None if insufficient data
        """
        if len(self._resource_history) < 1:
            return None

        recent = list(self._resource_history)[-window:]

        try:
            values = [getattr(m, metric_name) for m in recent]
            return sum(values) / len(values)
        except AttributeError:
            return None

    def reset(self) -> None:
        """Reset interpreter state (e.g., after mode change)."""
        self._resource_history.clear()
        self._cognitive_history.clear()
        self._smoothed_ram_used = None
        self._smoothed_cpu = None
        self._smoothed_temp = None
        self._smoothed_latency = None
