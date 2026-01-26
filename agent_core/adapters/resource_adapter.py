"""
Resource Watchdog Adapter

Bridges legacy maria_core.sys.resource_watchdog to agent_core ResourceSensor.
The legacy watchdog only monitors RAM and kills process on threshold.
This adapter integrates it with the homeostasis system.

Legacy: maria_core/sys/resource_watchdog.py
"""

import threading
import logging
from typing import Optional, Callable

from ..homeostasis.sensors.resource_sensor import ResourceSensor, ResourceMetrics
from ..homeostasis.state_model import Mode


logger = logging.getLogger(__name__)


class ResourceWatchdogAdapter:
    """
    Adapter that wraps legacy resource_watchdog for homeostasis integration.

    The legacy watchdog:
    - Monitors only RAM
    - Kills process if RAM > threshold
    - Runs independently

    This adapter:
    - Integrates with ResourceSensor for full metrics
    - Reports to homeostasis instead of killing process
    - Allows homeostasis to decide appropriate action
    """

    def __init__(
        self,
        limit_percent: int = 80,
        check_interval_sec: int = 3,
        on_threshold_exceeded: Optional[Callable[[float], None]] = None,
    ):
        """
        Initialize adapter.

        Args:
            limit_percent: RAM threshold percentage (legacy parameter)
            check_interval_sec: Check interval (legacy parameter)
            on_threshold_exceeded: Callback when threshold exceeded
                                   (replaces legacy os._exit behavior)
        """
        self._limit_percent = limit_percent
        self._check_interval = check_interval_sec
        self._on_threshold_exceeded = on_threshold_exceeded
        self._sensor = ResourceSensor()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> threading.Thread:
        """
        Start watchdog in background thread.

        Unlike legacy, this doesn't kill the process - it reports to callback.

        Returns:
            The watchdog thread
        """
        if self._running:
            logger.warning("Watchdog already running")
            return self._thread

        self._running = True
        self._thread = threading.Thread(
            target=self._watch_loop,
            daemon=True,
            name="HomeostasisWatchdog",
        )
        self._thread.start()

        logger.info(
            f"[Adapter] Watchdog started (limit={self._limit_percent}%, "
            f"interval={self._check_interval}s)"
        )

        return self._thread

    def stop(self) -> None:
        """Stop the watchdog."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            logger.info("[Adapter] Watchdog stopped")

    def _watch_loop(self) -> None:
        """
        Main watch loop - adapted from legacy _watch_ram_loop.

        Instead of os._exit, calls threshold callback.
        """
        import time

        while self._running:
            try:
                metrics = self._sensor.read_metrics()

                if metrics and metrics.ram_percent >= self._limit_percent:
                    logger.error(
                        f"[Watchdog] RAM {metrics.ram_percent:.1f}% >= {self._limit_percent}%"
                    )

                    if self._on_threshold_exceeded:
                        self._on_threshold_exceeded(metrics.ram_percent)
                    else:
                        # Default behavior: log warning but don't kill
                        # Let homeostasis handle it
                        logger.warning(
                            "[Watchdog] Threshold exceeded - reporting to homeostasis"
                        )

            except Exception as e:
                logger.error(f"[Watchdog] Error in watch loop: {e}")

            time.sleep(self._check_interval)

    def get_current_metrics(self) -> Optional[ResourceMetrics]:
        """
        Get current resource metrics.

        Returns:
            ResourceMetrics or None on failure
        """
        return self._sensor.read_metrics()

    @property
    def is_running(self) -> bool:
        """Check if watchdog is running."""
        return self._running

    @classmethod
    def from_legacy(cls, limit_percent: int = 80, check_interval_sec: int = 3):
        """
        Create adapter with legacy-compatible parameters.

        This mimics the signature of legacy start_watchdog() function.
        """
        return cls(
            limit_percent=limit_percent,
            check_interval_sec=check_interval_sec,
        )


def start_watchdog_adapted(
    limit_percent: int = 80,
    check_interval_sec: int = 3,
    on_threshold: Optional[Callable[[float], None]] = None,
) -> ResourceWatchdogAdapter:
    """
    Drop-in replacement for legacy start_watchdog().

    Args:
        limit_percent: RAM threshold
        check_interval_sec: Check interval
        on_threshold: Optional callback (if None, logs warning instead of killing)

    Returns:
        Running adapter instance
    """
    adapter = ResourceWatchdogAdapter(
        limit_percent=limit_percent,
        check_interval_sec=check_interval_sec,
        on_threshold_exceeded=on_threshold,
    )
    adapter.start()
    return adapter

