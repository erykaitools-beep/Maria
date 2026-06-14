"""ThresholdCalibrator: rolling-window distance distribution -> thresholds.

Provides the data layer for surprise scoring:
  - B0 global: percentile threshold (decision #7a, default 95%)
  - B0.1 action-aware: mean/std for sigma z-score (decision #7a)
  - Warm-up gating: N<200 global, N<20 action (decision #7d)
  - Rolling 7d window (decision #7b)
  - Per-day recompute cadence (decision #7c)
  - In-memory only, no SSoT (decision #8)

Multiple named distributions are kept independently so a single
calibrator can serve both global ("global") and per-action
("action:learn", "action:skip", ...) channels.

This module owns the distribution math; it does NOT own log replay
(load-from-logs at startup is a later integration commit) and does NOT
emit bulletin events (that is bulletin_adapter.py).
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


# Defaults from B0_IMPLEMENTATION_SHORTLIST rev 4 (decisions #7b/#7c/#7d)
DEFAULT_WINDOW_SECONDS: float = 7 * 86400
DEFAULT_MIN_SAMPLES_GLOBAL: int = 200
DEFAULT_MIN_SAMPLES_ACTION: int = 20
DEFAULT_RECOMPUTE_INTERVAL_SECONDS: float = 86400


@dataclass(frozen=True)
class DistributionStats:
    """Summary of a distance distribution. Inputs to B0.1 z-score."""

    mean: float
    std: float
    n: int


class ThresholdCalibrator:
    """Rolling-window calibrator for surprise distance thresholds.

    Observations are tagged by ``distribution_key`` (free-form string;
    callers use ``"global"`` for B0 and e.g. ``"action:learn"`` for
    B0.1). Each distribution accumulates (timestamp, distance) tuples
    inside the configured time window.

    Pruning happens lazily on :py:meth:`recompute`, not on every
    :py:meth:`add`, so high-frequency adds stay cheap. Callers should
    invoke ``recompute()`` once per day (or whenever
    :py:meth:`should_recompute` returns True).
    """

    def __init__(
        self,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        min_samples_global: int = DEFAULT_MIN_SAMPLES_GLOBAL,
        min_samples_action: int = DEFAULT_MIN_SAMPLES_ACTION,
        recompute_interval_seconds: float = DEFAULT_RECOMPUTE_INTERVAL_SECONDS,
    ):
        self._window_sec = float(window_seconds)
        self._min_global = int(min_samples_global)
        self._min_action = int(min_samples_action)
        self._recompute_interval = float(recompute_interval_seconds)

        self._obs: Dict[str, List[Tuple[float, float]]] = {}
        self._last_recompute_ts: Optional[float] = None

    # --- ingestion ---------------------------------------------------

    def add(
        self,
        distance: float,
        distribution_key: str,
        timestamp: Optional[float] = None,
    ) -> None:
        """Record one distance observation under the named distribution."""
        if timestamp is None:
            timestamp = time.time()
        bucket = self._obs.setdefault(distribution_key, [])
        bucket.append((float(timestamp), float(distance)))

    # --- warm-up gating ---------------------------------------------

    def is_warming_up(
        self,
        distribution_key: str,
        *,
        action_aware: bool = False,
    ) -> bool:
        """True when sample count is below the warm-up threshold.

        ``action_aware=False`` (default) uses the global N<200 floor;
        ``action_aware=True`` uses the per-action N<20 floor (decision
        #7d). The caller picks which floor applies — the calibrator
        does NOT infer it from the key name to keep the contract
        explicit.
        """
        n = len(self._obs.get(distribution_key, []))
        floor = self._min_action if action_aware else self._min_global
        return n < floor

    # --- threshold lookups -----------------------------------------

    def get_percentile_threshold(
        self,
        distribution_key: str,
        percentile: float = 95.0,
    ) -> Optional[float]:
        """Return the distance at the given percentile (for B0 global).

        Returns None during warm-up — caller treats None as "no
        high-confidence emit yet" (decision #7d).
        """
        if self.is_warming_up(distribution_key):
            return None
        values = [d for _, d in self._obs.get(distribution_key, [])]
        if not values:
            return None
        values.sort()
        # Largest index < len, computed from percentile in [0, 100].
        idx = int(len(values) * percentile / 100.0)
        idx = max(0, min(idx, len(values) - 1))
        return values[idx]

    def get_distribution_stats(
        self,
        distribution_key: str,
        *,
        action_aware: bool = False,
    ) -> Optional[DistributionStats]:
        """Return mean/std/n for sigma z-score (B0.1).

        Returns None during warm-up. Uses sample std (n-1 denominator)
        — the conventional choice for z-score against an unknown
        population. n>=2 is required for std; on n==1 returns None.
        """
        if self.is_warming_up(distribution_key, action_aware=action_aware):
            return None
        values = [d for _, d in self._obs.get(distribution_key, [])]
        if len(values) < 2:
            return None
        mean = statistics.fmean(values)
        std = statistics.stdev(values)
        return DistributionStats(mean=mean, std=std, n=len(values))

    # --- maintenance -------------------------------------------------

    def should_recompute(self, now: Optional[float] = None) -> bool:
        """True when enough time elapsed since the last :py:meth:`recompute`.

        Before the first :py:meth:`recompute` call ``_last_recompute_ts``
        is None, which makes this always return True so a fresh
        calibrator gets a recompute on its first poll.
        """
        if self._last_recompute_ts is None:
            return True
        if now is None:
            now = time.time()
        return (now - self._last_recompute_ts) >= self._recompute_interval

    def recompute(self, now: Optional[float] = None) -> None:
        """Prune observations older than the window and mark the time.

        Call after :py:meth:`should_recompute` reports True. Empty
        distribution buckets are removed entirely so they no longer
        appear in :py:meth:`distributions`.
        """
        if now is None:
            now = time.time()
        cutoff = now - self._window_sec
        for key in list(self._obs.keys()):
            kept = [(ts, d) for ts, d in self._obs[key] if ts >= cutoff]
            if kept:
                self._obs[key] = kept
            else:
                del self._obs[key]
        self._last_recompute_ts = now

    # --- introspection ----------------------------------------------

    def observation_count(self, distribution_key: str) -> int:
        return len(self._obs.get(distribution_key, []))

    def distributions(self) -> List[str]:
        """Names of all distributions currently holding observations."""
        return list(self._obs.keys())
