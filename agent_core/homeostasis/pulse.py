"""
Homeostasis Pulse Thread - High-frequency emergency detection

Runs every 100ms at high priority to detect CRITICAL emergencies fast.
Wakes main loop if immediate action needed.

Monitors:
- OOM imminent (< 100 MB free)
- Thermal shutdown imminent (> 98°C)
- LLM hang (> 60s latency)

Spec reference: homeostasis_spec.md lines 1498-1560
"""

import time
import threading
import queue
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

from .sensors.resource_sensor import ResourceSensor
from .sensors.thermal_sensor import ThermalSensor


logger = logging.getLogger(__name__)


@dataclass
class PulseAlert:
    """Alert from pulse thread."""
    alert_type: str  # 'CRITICAL' | 'ALERT'
    message: str
    timestamp: float
    metric_value: float


class HomeostasisPulseThread(threading.Thread):
    """
    High-frequency monitoring thread.

    Runs every 100ms to detect CRITICAL emergencies fast.
    Communicates with main loop via queue.

    Spec: homeostasis_spec.md lines 1504-1560
    """

    # Pulse configuration
    PULSE_INTERVAL_SEC = 0.1  # 100ms
    MIN_SLEEP_SEC = 0.05      # Minimum sleep between pulses

    # Critical thresholds (must act immediately)
    RAM_CRITICAL_PCT = 3      # < 3% free → OOM imminent
    TEMP_CRITICAL_C = 98      # > 98°C → shutdown imminent
    LATENCY_CRITICAL_MS = 60000  # > 60s → LLM hung

    def __init__(
        self,
        alert_queue: queue.Queue,
        resource_sensor: Optional[ResourceSensor] = None,
        thermal_sensor: Optional[ThermalSensor] = None,
    ):
        """
        Initialize pulse thread.

        Args:
            alert_queue: Queue to send alerts to main loop
            resource_sensor: Resource sensor (creates own if None)
            thermal_sensor: Thermal sensor (creates own if None)
        """
        super().__init__(daemon=True, name="HomeostasisPulse")
        self.alert_queue = alert_queue
        self.resource_sensor = resource_sensor or ResourceSensor()
        self.thermal_sensor = thermal_sensor or ThermalSensor()
        self._running = True
        self._pulse_count = 0

    def run(self) -> None:
        """
        High-frequency pulse loop.

        Spec: homeostasis_spec.md lines 1517-1556
        """
        logger.info("Homeostasis pulse thread started")

        while self._running:
            try:
                tick_start = time.time()

                # Quick non-blocking reads
                self._check_critical_conditions()

                self._pulse_count += 1

                # Sleep until next pulse
                elapsed = time.time() - tick_start
                sleep_time = max(self.MIN_SLEEP_SEC, self.PULSE_INTERVAL_SEC - elapsed)
                time.sleep(sleep_time)

            except Exception as e:
                logger.error(f"Pulse thread exception: {e}")
                time.sleep(self.PULSE_INTERVAL_SEC)

        logger.info("Homeostasis pulse thread stopped")

    def _check_critical_conditions(self) -> None:
        """
        Check for critical conditions requiring immediate action.

        Only checks the most critical thresholds that need
        sub-second response time.
        """
        # Read metrics (non-blocking)
        resource = self.resource_sensor.read_metrics()
        thermal = self.thermal_sensor.read_metrics()

        if resource is None:
            return

        # Check OOM imminent
        ram_available_pct = resource.ram_available_pct
        if ram_available_pct < self.RAM_CRITICAL_PCT:
            self._send_alert(PulseAlert(
                alert_type="CRITICAL",
                message=f"OOM imminent ({ram_available_pct:.1f}% RAM free)",
                timestamp=time.time(),
                metric_value=ram_available_pct,
            ))

        # Check thermal shutdown
        if thermal and thermal.cpu_temp_c > self.TEMP_CRITICAL_C:
            self._send_alert(PulseAlert(
                alert_type="CRITICAL",
                message=f"Thermal shutdown imminent ({thermal.cpu_temp_c:.1f}°C)",
                timestamp=time.time(),
                metric_value=thermal.cpu_temp_c,
            ))

        # Check LLM hang (if latency available)
        if resource.inference_latency_ms > self.LATENCY_CRITICAL_MS:
            self._send_alert(PulseAlert(
                alert_type="CRITICAL",
                message=f"LLM hung ({resource.inference_latency_ms/1000:.1f}s latency)",
                timestamp=time.time(),
                metric_value=resource.inference_latency_ms,
            ))

    def _send_alert(self, alert: PulseAlert) -> None:
        """Send alert to main loop via queue."""
        try:
            self.alert_queue.put_nowait({
                "type": alert.alert_type,
                "message": alert.message,
                "timestamp": alert.timestamp,
                "metric_value": alert.metric_value,
            })
            logger.warning(f"Pulse alert: {alert.message}")
        except queue.Full:
            logger.error("Alert queue full, dropping alert")

    def stop(self) -> None:
        """Stop the pulse thread."""
        self._running = False

    def is_running(self) -> bool:
        """Check if pulse thread is running."""
        return self._running

    def get_pulse_count(self) -> int:
        """Get number of pulses executed."""
        return self._pulse_count


class PulseAlertHandler:
    """
    Handles alerts from pulse thread in main loop.

    Processes the alert queue and integrates with
    the main homeostasis tick.
    """

    def __init__(self, alert_queue: queue.Queue):
        """
        Initialize alert handler.

        Args:
            alert_queue: Queue receiving alerts from pulse thread
        """
        self.alert_queue = alert_queue
        self._recent_alerts: list = []

    def check_for_alerts(self) -> list:
        """
        Check for pending alerts from pulse thread.

        Non-blocking check of the queue.

        Returns:
            List of alerts received since last check
        """
        alerts = []

        try:
            while True:
                alert = self.alert_queue.get_nowait()
                alerts.append(alert)
                self._recent_alerts.append(alert)
        except queue.Empty:
            pass

        # Keep recent alerts bounded
        if len(self._recent_alerts) > 100:
            self._recent_alerts = self._recent_alerts[-50:]

        return alerts

    def has_critical_alert(self) -> bool:
        """Check if there's a pending critical alert."""
        try:
            # Peek without removing
            alerts = []
            while True:
                alert = self.alert_queue.get_nowait()
                alerts.append(alert)
        except queue.Empty:
            pass

        # Put them back
        for alert in alerts:
            try:
                self.alert_queue.put_nowait(alert)
            except queue.Full:
                pass

        return any(a.get("type") == "CRITICAL" for a in alerts)

    def get_recent_alerts(self, limit: int = 10) -> list:
        """Get recent alerts."""
        return self._recent_alerts[-limit:]
