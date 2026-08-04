"""Tests for HomeostasisPulseThread critical-condition checks.

Pins the deliberate ABSENCE of an LLM-latency gate: ResourceSensor never
carries a real latency measurement into the pulse, and on a CPU-only box
long inference is normal operation (median chat ~114s), so a latency
CRITICAL would storm. Freeze concerns belong to call_with_timeout and
TickWatchdog.
"""

import queue
import time
from unittest.mock import MagicMock

from agent_core.homeostasis.pulse import HomeostasisPulseThread
from agent_core.homeostasis.state_model import ResourceMetrics


def _metrics(ram_available_mb=16000.0, inference_latency_ms=0.0):
    return ResourceMetrics(
        timestamp=time.time(),
        ram_used_mb=16000.0,
        ram_total_mb=32000.0,
        ram_available_mb=ram_available_mb,
        swap_used_pct=0.0,
        cpu_percent=20.0,
        load_avg_1m=1.0,
        load_avg_5m=1.0,
        load_avg_15m=1.0,
        disk_used_pct=50.0,
        disk_io_queue_depth=0,
        process_count=200,
        temp_c=50.0,
        inference_latency_ms=inference_latency_ms,
    )


def _make_pulse(metrics):
    alert_queue = queue.Queue()
    resource_sensor = MagicMock()
    resource_sensor.read_metrics.return_value = metrics
    thermal_sensor = MagicMock()
    thermal_sensor.read_metrics.return_value = None
    pulse = HomeostasisPulseThread(
        alert_queue=alert_queue,
        resource_sensor=resource_sensor,
        thermal_sensor=thermal_sensor,
    )
    return pulse, alert_queue


class TestPulseCriticalConditions:

    def test_oom_imminent_fires_critical(self):
        # 2% free RAM -> below RAM_CRITICAL_PCT=3
        pulse, alerts = _make_pulse(_metrics(ram_available_mb=640.0))
        pulse._check_critical_conditions()

        alert = alerts.get_nowait()
        assert alert["type"] == "CRITICAL"
        assert "OOM" in alert["message"]

    def test_healthy_metrics_no_alert(self):
        pulse, alerts = _make_pulse(_metrics())
        pulse._check_critical_conditions()

        assert alerts.empty()

    def test_huge_latency_does_not_alert(self):
        """No latency gate: 999s inference must NOT produce an alert."""
        pulse, alerts = _make_pulse(_metrics(inference_latency_ms=999_000.0))
        pulse._check_critical_conditions()

        assert alerts.empty()
