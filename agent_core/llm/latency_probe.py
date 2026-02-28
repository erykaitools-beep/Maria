"""
Latency Probe - Quick LLM latency measurement

Provides non-blocking latency checks for homeostasis.
Used by pulse thread for hang detection.
"""

import time
import threading
import logging
from typing import Optional, Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

logger = logging.getLogger(__name__)


class LatencyProbe:
    """
    Quick LLM latency measurement.

    Sends minimal prompt to measure response time.
    Used for hang detection in pulse thread.
    """

    # Default probe configuration
    PROBE_PROMPT = "Hi"
    DEFAULT_TIMEOUT_SEC = 5.0

    def __init__(
        self,
        inference_func: Optional[Callable[[str], str]] = None,
    ):
        """
        Initialize latency probe.

        Args:
            inference_func: Function to call for inference (prompt -> response)
        """
        self._inference_func = inference_func
        self._last_latency_ms = 0.0
        self._last_probe_time = 0.0
        self._executor = ThreadPoolExecutor(max_workers=1)

        if not self._inference_func:
            logger.debug("No inference_func provided - probe inactive until set")

    def measure_latency(
        self,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    ) -> float:
        """
        Measure LLM latency with timeout.

        Non-blocking: returns 9999 if timeout exceeded.

        Args:
            timeout_sec: Maximum time to wait

        Returns:
            Latency in milliseconds (9999 if timeout/error)
        """
        if not self._inference_func:
            return -1.0  # no inference function = no data

        start_time = time.time()

        try:
            # Submit probe task
            future = self._executor.submit(
                self._do_probe
            )

            # Wait with timeout
            result = future.result(timeout=timeout_sec)

            latency_ms = (time.time() - start_time) * 1000
            self._last_latency_ms = latency_ms
            self._last_probe_time = time.time()

            return latency_ms

        except FuturesTimeoutError:
            logger.warning(f"Latency probe timed out after {timeout_sec}s")
            return 9999.0

        except Exception as e:
            logger.warning(f"Latency probe failed: {e}")
            return 9999.0

    def _do_probe(self) -> str:
        """Execute probe inference."""
        return self._inference_func(self.PROBE_PROMPT)

    def get_last_latency(self) -> float:
        """Get last measured latency in milliseconds."""
        return self._last_latency_ms

    def get_last_probe_time(self) -> float:
        """Get timestamp of last probe."""
        return self._last_probe_time

    def is_responsive(self, threshold_ms: float = 5000.0) -> bool:
        """
        Check if LLM is responsive.

        Args:
            threshold_ms: Maximum acceptable latency

        Returns:
            True if last latency was below threshold
        """
        return self._last_latency_ms < threshold_ms

    def shutdown(self) -> None:
        """Shutdown probe executor."""
        self._executor.shutdown(wait=False)


class AsyncLatencyProbe:
    """
    Async version of latency probe.

    Runs probes in background thread, updates results.
    """

    PROBE_INTERVAL_SEC = 30.0  # Probe every 30 seconds

    def __init__(
        self,
        inference_func: Optional[Callable[[str], str]] = None,
    ):
        """
        Initialize async latency probe.

        Args:
            inference_func: Function for inference
        """
        self._probe = LatencyProbe(inference_func)
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start background probing."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._probe_loop,
            daemon=True,
            name="LatencyProbe",
        )
        self._thread.start()
        logger.info("Async latency probe started")

    def stop(self) -> None:
        """Stop background probing."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        self._probe.shutdown()
        logger.info("Async latency probe stopped")

    def _probe_loop(self) -> None:
        """Background probe loop."""
        while self._running:
            try:
                self._probe.measure_latency()
            except Exception as e:
                logger.warning(f"Probe loop error: {e}")

            # Wait for next probe
            for _ in range(int(self.PROBE_INTERVAL_SEC * 10)):
                if not self._running:
                    break
                time.sleep(0.1)

    def get_latency(self) -> float:
        """Get most recent latency."""
        return self._probe.get_last_latency()

    def is_responsive(self, threshold_ms: float = 5000.0) -> bool:
        """Check if LLM is responsive."""
        return self._probe.is_responsive(threshold_ms)
