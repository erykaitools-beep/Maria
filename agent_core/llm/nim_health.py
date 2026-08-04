"""Outcome-based health tracking for the NIM API.

WHY THIS EXISTS (audit 2026-07-28)
----------------------------------
Maria's NIM health signal used to be derived from her own token-budget counter:
``CostEstimator(ctx).get_budget_status().nim_status``, which only ever emits
"OK" / "LOW" / "DEPLETED" (``token_budget.get_budget_status``). The self-repair
rule ``model_unavailable`` waits for the literal word "unavailable"
(``self_repair/detectors._is_unavailable``), so the NIM branch was structurally
unreachable -- the intersection of the two vocabularies was empty.

Measured consequence: during the 2026-07-27 dracarys EOL outage (254 consecutive
HTTP 410) and the 2026-07-28 shared-endpoint congestion (63 hard failures), all
2946 self-perception snapshots ever written recorded NIM as "available". Maria
could not notice that her main reasoning path was down.

Worse, the budget counter is ANTI-CORRELATED with an outage: ``_record_nim_usage``
only runs on the success path, so the more NIM fails, the healthier the counter
looks.

WHAT THIS MEASURES
------------------
The only thing that answers "is NIM answering?" -- the outcome of real calls.
It is fed from ``NIMClient._chat``, the single chokepoint every caller shares,
so paths that bypass ``LLMRouter`` (``teacher_module``'s own NIMClient,
``cross_validator``, ``heldout_author``) are covered too.

Deliberately NOT fed from ``NIMClient.health_check`` / ``is_available``: those
are synthetic probes, and this project has been burned three times by synthetic
probes that passed while the real workload failed. Real work is the only witness.

STATUS VOCABULARY (matches what detectors._is_unavailable consumes)
-------------------------------------------------------------------
- "unknown"     -- fewer than MIN_SAMPLE attempts in the window. An idle daemon
                   must never look like an outage.
- "unavailable" -- enough attempts, and NOT ONE of them succeeded. This is a
                   real outage (the 410 EOL day looked exactly like this) and is
                   the only status that trips self-repair.
- "degraded"    -- calls are getting through, but the failure ratio is above
                   DEGRADED_FAILURE_RATIO. Shared-endpoint congestion looks like
                   this. Reported for visibility but deliberately does NOT trip
                   self-repair: Maria cannot repair someone else's queue, and an
                   alarm she can only ignore is worse than no alarm.
- "available"   -- otherwise.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional, Tuple

# Rolling window over which outcomes are judged. 30 min matches the
# self-perception snapshot cadence (Phase 18), so a snapshot always describes a
# window that ends at the snapshot.
WINDOW_SECONDS = float(os.environ.get("NIM_HEALTH_WINDOW_SECONDS", 1800))

# Minimum attempts before the window may return a verdict at all. Below this the
# answer is "unknown" -- one failed call is not an outage, and silence is not
# evidence of health.
#
# Calibrated by replaying the tracker over two real logged days (2026-07-28).
# Because detect_model_unavailable needs TWO consecutive "unavailable" windows,
# this threshold effectively means "2*N failed calls and not one success within
# an hour":
#
#   threshold   07-27 outage (254x HTTP 410)   07-28 congestion (63 fails, 83% ok)
#       3       alarm at 07:00                 silent
#       4       alarm at 08:30                 silent
#       5       alarm at 10:00                 silent
#       8       alarm at 10:00                 silent
#
# The congestion day is the false-positive test and it stays silent at every
# threshold, so the only thing the threshold buys is detection latency on a
# quiet night. 3 it is. (Evidence base is two days -- widen it before treating
# this number as settled.) Tunable via NIM_HEALTH_MIN_SAMPLE + restart.
MIN_SAMPLE = int(os.environ.get("NIM_HEALTH_MIN_SAMPLE", 3))

# Failure ratio at or above which a still-answering endpoint counts as degraded.
DEGRADED_FAILURE_RATIO = float(
    os.environ.get("NIM_HEALTH_DEGRADED_RATIO", 0.5)
)

# Hard cap on retained outcomes. Bounds memory regardless of call volume; the
# window filter below is what actually decides the verdict.
MAX_RECORDS = 500

# Truncation for the stored error string (goes into snapshots and Telegram).
MAX_ERROR_CHARS = 200

STATUS_AVAILABLE = "available"
STATUS_DEGRADED = "degraded"
STATUS_UNAVAILABLE = "unavailable"
STATUS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class NimHealthSnapshot:
    """Immutable verdict over the rolling window."""

    status: str
    attempts: int
    successes: int
    failures: int
    failure_ratio: float
    window_seconds: float
    last_success_ts: Optional[float]
    last_failure_ts: Optional[float]
    last_error: str

    def as_details(self) -> Dict[str, Any]:
        """Flatten for the `details` block of an external-service entry."""
        return {
            "health_window_seconds": int(self.window_seconds),
            "health_attempts": self.attempts,
            "health_successes": self.successes,
            "health_failures": self.failures,
            "health_failure_ratio": round(self.failure_ratio, 3),
            "last_success_age_s": _age(self.last_success_ts),
            "last_failure_age_s": _age(self.last_failure_ts),
            "last_error": self.last_error,
        }


def _age(ts: Optional[float], now: Optional[float] = None) -> Optional[int]:
    if ts is None:
        return None
    return int(max(0.0, (now if now is not None else time.time()) - ts))


class NimHealthTracker:
    """Thread-safe rolling record of NIM call outcomes.

    Shared across threads (planner, teacher, tick loop all call NIM), so every
    read and write takes the lock -- this project has been bitten before by a
    shared singleton whose accessors were not serialized.

    ``snapshot()`` is peek-safe: it does not evict, re-order, or otherwise mutate
    state. Expiry happens only on the write path. A "read-only" accessor that
    quietly mutates is exactly the trap that made `is_action_backed_off` lie.
    """

    def __init__(
        self,
        window_seconds: float = WINDOW_SECONDS,
        min_sample: int = MIN_SAMPLE,
        degraded_ratio: float = DEGRADED_FAILURE_RATIO,
        max_records: int = MAX_RECORDS,
    ) -> None:
        self._window = float(window_seconds)
        self._min_sample = int(min_sample)
        self._degraded_ratio = float(degraded_ratio)
        self._lock = threading.Lock()
        # (timestamp, ok)
        self._records: Deque[Tuple[float, bool]] = deque(maxlen=int(max_records))
        self._last_success_ts: Optional[float] = None
        self._last_failure_ts: Optional[float] = None
        self._last_error: str = ""

    # -------------------------------------------------
    # WRITE PATH (called from NIMClient._chat)
    # -------------------------------------------------

    def record_success(self, now: Optional[float] = None) -> None:
        ts = time.time() if now is None else now
        with self._lock:
            self._records.append((ts, True))
            self._last_success_ts = ts
            self._prune_locked(ts)

    def record_failure(self, error: str = "", now: Optional[float] = None) -> None:
        ts = time.time() if now is None else now
        with self._lock:
            self._records.append((ts, False))
            self._last_failure_ts = ts
            self._last_error = (error or "")[:MAX_ERROR_CHARS]
            self._prune_locked(ts)

    def _prune_locked(self, now: float) -> None:
        """Drop outcomes that fell out of the window. Caller holds the lock."""
        cutoff = now - self._window
        while self._records and self._records[0][0] < cutoff:
            self._records.popleft()

    # -------------------------------------------------
    # READ PATH
    # -------------------------------------------------

    def snapshot(self, now: Optional[float] = None) -> NimHealthSnapshot:
        """Current verdict. Does not mutate tracker state."""
        ts = time.time() if now is None else now
        cutoff = ts - self._window
        with self._lock:
            in_window = [ok for (t, ok) in self._records if t >= cutoff]
            last_success = self._last_success_ts
            last_failure = self._last_failure_ts
            last_error = self._last_error

        attempts = len(in_window)
        successes = sum(1 for ok in in_window if ok)
        failures = attempts - successes
        ratio = (failures / attempts) if attempts else 0.0

        if attempts < self._min_sample:
            status = STATUS_UNKNOWN
        elif successes == 0:
            status = STATUS_UNAVAILABLE
        elif ratio >= self._degraded_ratio:
            status = STATUS_DEGRADED
        else:
            status = STATUS_AVAILABLE

        return NimHealthSnapshot(
            status=status,
            attempts=attempts,
            successes=successes,
            failures=failures,
            failure_ratio=ratio,
            window_seconds=self._window,
            last_success_ts=last_success,
            last_failure_ts=last_failure,
            last_error=last_error,
        )

    def reset(self) -> None:
        """Clear all state. For tests and for a deliberate operator reset."""
        with self._lock:
            self._records.clear()
            self._last_success_ts = None
            self._last_failure_ts = None
            self._last_error = ""


# Module-level singleton: callers build their own NIMClient instances
# (teacher_module does), so per-instance state would fragment the picture.
_TRACKER = NimHealthTracker()


def get_nim_health() -> NimHealthTracker:
    """Shared tracker fed by every NIMClient._chat call in the process."""
    return _TRACKER
