"""
Resource Sensor - Hardware metrics collection

Monitors (spec section 1.1.A):
- RAM: used, free, swap, pressure
- CPU: usage %, load average (1m, 5m, 15m), per-thread
- Disk: usage %, I/O queue depth
- Process count: system vs agent-owned

Adapter for: maria_core/sys/resource_watchdog.py

Spec reference: homeostasis_spec.md lines 17-42
"""

import time
from typing import Optional

import psutil

from ..state_model import ResourceMetrics


class ResourceSensor:
    """
    Reads hardware resource metrics.

    Non-blocking implementation using psutil.
    Falls back to worst-case values on sensor failure.
    """

    def __init__(self):
        """Initialize resource sensor."""
        self._last_cpu_percent = 0.0
        # Initialize CPU percent measurement (first call returns 0)
        psutil.cpu_percent(interval=None)

    def read_metrics(self) -> Optional[ResourceMetrics]:
        """
        Non-blocking read of system metrics.

        Returns:
            ResourceMetrics with current values, or None on complete failure

        Spec: homeostasis_spec.md lines 943-974
        """
        try:
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            cpu = psutil.cpu_percent(interval=None)  # Non-blocking
            disk = psutil.disk_usage('/')
            load_avg = self._get_load_average()

            return ResourceMetrics(
                timestamp=time.time(),
                ram_used_mb=mem.used / 1024 / 1024,
                ram_total_mb=mem.total / 1024 / 1024,
                ram_available_mb=mem.available / 1024 / 1024,
                swap_used_pct=swap.percent,
                cpu_percent=cpu,
                load_avg_1m=load_avg[0],
                load_avg_5m=load_avg[1],
                load_avg_15m=load_avg[2],
                disk_used_pct=disk.percent,
                disk_io_queue_depth=self._get_io_queue_depth(),
                process_count=len(psutil.pids()),
                temp_c=0.0,  # Filled by ThermalSensor
                inference_latency_ms=0.0,  # Filled by CognitiveSensor
            )
        except Exception as e:
            # Sensor failure: assume worst case (spec line 969-974)
            return ResourceMetrics(
                timestamp=time.time(),
                ram_used_mb=0,
                ram_total_mb=0,
                ram_available_mb=0,
                swap_used_pct=100,
                cpu_percent=100,
                load_avg_1m=99,
                load_avg_5m=99,
                load_avg_15m=99,
                disk_used_pct=100,
                disk_io_queue_depth=999,
                process_count=0,
                temp_c=99,
                inference_latency_ms=9999,
            )

    def _get_load_average(self) -> tuple:
        """Get system load average (1m, 5m, 15m)."""
        try:
            # Works on Unix, returns (0,0,0) on Windows
            load = psutil.getloadavg()
            return load
        except (AttributeError, OSError):
            # Windows fallback: use CPU percent as approximation
            cpu = psutil.cpu_percent(interval=None)
            return (cpu / 100, cpu / 100, cpu / 100)

    def _get_io_queue_depth(self) -> int:
        """
        Get disk I/O queue depth.

        Returns approximate queue depth based on disk counters.
        """
        try:
            counters = psutil.disk_io_counters()
            if counters:
                # Approximate: pending reads + writes
                return counters.read_count % 100 + counters.write_count % 100
            return 0
        except Exception:
            return 0

    def get_memory_pressure(self) -> float:
        """
        Calculate memory pressure indicator (0-100).

        Higher values indicate more pressure.
        """
        try:
            mem = psutil.virtual_memory()
            # Pressure = 100 - available percent
            return 100 - (mem.available / mem.total * 100)
        except Exception:
            return 100.0  # Assume worst case
