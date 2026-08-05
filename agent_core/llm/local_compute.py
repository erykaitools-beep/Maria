"""Process-wide safety gate for CPU-bound local model work.

The mini PC has one shared CPU budget for text generation, vision inference,
and bge-m3 embeddings.  Treating those call paths as independent allowed them
to overlap and turn a slow request into a sustained thermal incident.

This module provides one fail-closed lease for every local Ollama inference and
an edge-triggered cooling latch.  At the thermal stop threshold new work is
rejected and registered background jobs are cancelled.  Work is admitted again
only after the lower resume threshold is reached.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Dict, Iterator, Optional

logger = logging.getLogger(__name__)


THERMAL_STOP_C = 80.0
THERMAL_RESUME_C = 70.0
NIM_RESOURCE_EXHAUSTED_BACKOFF_S = 300.0
LEASE_POLL_S = 0.2


class LocalComputeBlocked(RuntimeError):
    """Raised when local inference must not start for safety reasons."""


@dataclass(frozen=True)
class _BackgroundTask:
    name: str
    cancel: Callable[[], None]
    cancel_on_nim_exhausted: bool


class LocalComputeCoordinator:
    """Serialize local model work and own the thermal cooling latch.

    The compute slot is deliberately fail-closed: a caller that times out while
    waiting is rejected rather than allowed to run concurrently.  A per-thread
    depth counter makes nested wrappers safe (for example router -> OllamaBrain).
    """

    def __init__(
        self,
        stop_temp_c: float = THERMAL_STOP_C,
        resume_temp_c: float = THERMAL_RESUME_C,
    ) -> None:
        if resume_temp_c >= stop_temp_c:
            raise ValueError("resume temperature must be below stop temperature")
        self.stop_temp_c = float(stop_temp_c)
        self.resume_temp_c = float(resume_temp_c)
        self._state_lock = threading.RLock()
        self._slot = threading.Lock()
        self._local = threading.local()
        self._cooling = False
        self._last_temp_c: Optional[float] = None
        self._temperature_available: Optional[bool] = None
        self._active_kind: Optional[str] = None
        self._active_model: Optional[str] = None
        self._active_since: Optional[float] = None
        self._background_tasks: Dict[str, _BackgroundTask] = {}
        self._nim_resource_exhausted_until = 0.0

    @property
    def cooling(self) -> bool:
        with self._state_lock:
            return self._cooling

    def observe_temperature(
        self,
        temp_c: float,
        *,
        reading_available: bool = True,
    ) -> str:
        """Update the hysteresis latch and return entered/exited/unchanged."""
        with self._state_lock:
            self._temperature_available = bool(reading_available)
        if not reading_available:
            # The sensor's compatibility fallback is 50C. Never let that
            # fabricated value release an existing cooling latch.
            return "unavailable"
        if temp_c >= self.stop_temp_c:
            result = self.enter_cooling(temp_c)
            return "entered" if result["transitioned"] else "unchanged"
        if temp_c <= self.resume_temp_c:
            result = self.exit_cooling(temp_c)
            return "exited" if result["transitioned"] else "unchanged"
        with self._state_lock:
            self._last_temp_c = float(temp_c)
        return "unchanged"

    def enter_cooling(self, temp_c: Optional[float] = None) -> Dict[str, object]:
        """Latch cooling and cooperatively cancel every background compute job."""
        with self._state_lock:
            if temp_c is not None:
                self._last_temp_c = float(temp_c)
                self._temperature_available = True
            transitioned = not self._cooling
            self._cooling = True
            tasks = list(self._background_tasks.values()) if transitioned else []

        cancelled = []
        for task in tasks:
            try:
                task.cancel()
                cancelled.append(task.name)
            except Exception as exc:  # safety action must remain best-effort
                logger.warning("[LOCAL-COMPUTE] Failed to cancel %s: %s", task.name, exc)

        if transitioned:
            logger.warning(
                "[LOCAL-COMPUTE] Cooling entered at %.1fC; cancelled=%s",
                self._last_temp_c if self._last_temp_c is not None else -1.0,
                cancelled,
            )
        return {
            "transitioned": transitioned,
            "cooling": True,
            "cancelled_tasks": cancelled,
        }

    def exit_cooling(self, temp_c: Optional[float] = None) -> Dict[str, object]:
        """Leave cooling only at or below the safe resume threshold."""
        with self._state_lock:
            if temp_c is not None:
                self._last_temp_c = float(temp_c)
                self._temperature_available = True
            current = self._last_temp_c
            if current is None or current > self.resume_temp_c:
                return {
                    "transitioned": False,
                    "cooling": self._cooling,
                    "reason": "resume_threshold_not_reached",
                }
            transitioned = self._cooling
            self._cooling = False

        if transitioned:
            logger.info("[LOCAL-COMPUTE] Cooling exited at %.1fC", current)
        return {"transitioned": transitioned, "cooling": False}

    def register_background_task(
        self,
        name: str,
        cancel: Callable[[], None],
        *,
        cancel_on_nim_exhausted: bool = False,
    ) -> str:
        """Register a cancellable warm-up/indexing job and return its token."""
        token = uuid.uuid4().hex
        task = _BackgroundTask(name, cancel, cancel_on_nim_exhausted)
        with self._state_lock:
            self._background_tasks[token] = task
            cooling = self._cooling
            nim_blocked = (
                cancel_on_nim_exhausted
                and time.monotonic() < self._nim_resource_exhausted_until
            )
        if cooling or nim_blocked:
            cancel()
        return token

    def unregister_background_task(self, token: str) -> None:
        with self._state_lock:
            self._background_tasks.pop(token, None)

    def note_nim_resource_exhausted(
        self,
        backoff_s: float = NIM_RESOURCE_EXHAUSTED_BACKOFF_S,
    ) -> Dict[str, object]:
        """Suppress a local-fallback stampede after NIM HTTP 503."""
        with self._state_lock:
            self._nim_resource_exhausted_until = max(
                self._nim_resource_exhausted_until,
                time.monotonic() + max(0.0, float(backoff_s)),
            )
            tasks = [
                task for task in self._background_tasks.values()
                if task.cancel_on_nim_exhausted
            ]

        cancelled = []
        for task in tasks:
            try:
                task.cancel()
                cancelled.append(task.name)
            except Exception as exc:
                logger.warning("[LOCAL-COMPUTE] Failed to cancel %s: %s", task.name, exc)
        logger.warning(
            "[LOCAL-COMPUTE] NIM ResourceExhausted; local fallback backed off for %.0fs",
            backoff_s,
        )
        return {"local_fallback_blocked": True, "cancelled_tasks": cancelled}

    def local_fallback_allowed(self) -> bool:
        with self._state_lock:
            return (
                not self._cooling
                and time.monotonic() >= self._nim_resource_exhausted_until
            )

    def startup_background_allowed(self) -> bool:
        """Whether startup warm-up may run before checking live CPU load."""
        with self._state_lock:
            sensor_failed = self._temperature_available is False
        return self.local_fallback_allowed() and not sensor_failed

    def verify_startup_temperature(self) -> str:
        """Read a real sensor once before autonomous startup compute.

        Homeostasis usually supplies the first reading before the 30/60-second
        startup delays expire. Module initialization can be slow, though, so a
        background thread must not assume an unknown temperature is safe.
        """
        with self._state_lock:
            if self._temperature_available is not None:
                return "known"
        try:
            from agent_core.homeostasis.sensors.thermal_sensor import ThermalSensor
            metrics = ThermalSensor().read_metrics()
            return self.observe_temperature(
                metrics.cpu_temp_c,
                reading_available=metrics.reading_available,
            )
        except Exception as exc:
            with self._state_lock:
                self._temperature_available = False
            logger.warning(
                "[LOCAL-COMPUTE] Startup temperature probe failed: %s", exc,
            )
            return "unavailable"

    def _blocked_reason(
        self,
        cancel_event: Optional[threading.Event],
    ) -> Optional[str]:
        if cancel_event is not None and cancel_event.is_set():
            return "background task cancelled"
        with self._state_lock:
            if self._cooling:
                return "thermal cooling active"
        return None

    @contextmanager
    def lease(
        self,
        kind: str,
        *,
        model: str = "",
        timeout_s: Optional[float] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Iterator[None]:
        """Acquire the single local-compute slot without a fail-open path."""
        reason = self._blocked_reason(cancel_event)
        if reason:
            raise LocalComputeBlocked(reason)

        depth = getattr(self._local, "depth", 0)
        if depth:
            self._local.depth = depth + 1
            try:
                yield
            finally:
                self._local.depth -= 1
            return

        deadline = None if timeout_s is None else time.monotonic() + max(0.0, timeout_s)
        acquired = False
        while not acquired:
            reason = self._blocked_reason(cancel_event)
            if reason:
                raise LocalComputeBlocked(reason)
            if deadline is not None and time.monotonic() >= deadline:
                raise LocalComputeBlocked("local compute slot timeout")
            wait_s = LEASE_POLL_S
            if deadline is not None:
                wait_s = min(wait_s, max(0.0, deadline - time.monotonic()))
            acquired = self._slot.acquire(timeout=wait_s)

        reason = self._blocked_reason(cancel_event)
        if reason:
            self._slot.release()
            raise LocalComputeBlocked(reason)

        self._local.depth = 1
        with self._state_lock:
            self._active_kind = kind
            self._active_model = model or None
            self._active_since = time.monotonic()
        try:
            yield
        finally:
            with self._state_lock:
                self._active_kind = None
                self._active_model = None
                self._active_since = None
            self._local.depth = 0
            self._slot.release()

    def snapshot(self) -> Dict[str, object]:
        with self._state_lock:
            active_for = (
                time.monotonic() - self._active_since
                if self._active_since is not None else 0.0
            )
            return {
                "cooling": self._cooling,
                "last_temp_c": self._last_temp_c,
                "temperature_available": self._temperature_available,
                "stop_temp_c": self.stop_temp_c,
                "resume_temp_c": self.resume_temp_c,
                "active_kind": self._active_kind,
                "active_model": self._active_model,
                "active_for_s": round(active_for, 3),
                "background_tasks": [
                    task.name for task in self._background_tasks.values()
                ],
                "nim_resource_exhausted": (
                    time.monotonic() < self._nim_resource_exhausted_until
                ),
            }

    def reset_for_tests(self) -> None:
        """Clear safety state when no lease is active (tests only)."""
        with self._state_lock:
            if self._active_kind is not None:
                raise RuntimeError("cannot reset while local compute is active")
            self._cooling = False
            self._last_temp_c = None
            self._temperature_available = None
            self._background_tasks.clear()
            self._nim_resource_exhausted_until = 0.0


_COORDINATOR = LocalComputeCoordinator()


def get_local_compute_coordinator() -> LocalComputeCoordinator:
    """Return the process-wide coordinator shared by every local model path."""
    return _COORDINATOR
