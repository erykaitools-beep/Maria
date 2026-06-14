"""ActionBaseline: per-action z-score wrapper for B0.1 surprise scoring.

Thin convenience layer over :py:class:`ThresholdCalibrator`. Encodes the
"distribution per (action_type, distance_type)" key naming used by B0.1
(decision #3, decision #5) and exposes the cascade contract:

  add_observation(action_type, semantic_distance, numeric_distance)
  get_z_scores(action_type, semantic_distance, numeric_distance)
      -> Optional[(z_semantic, z_numeric)]

The caller (surprise_scorer) treats a None return from
:py:meth:`get_z_scores` as "this action_type is still in warm-up -- fall
back to B0 global" (decision #7d).

This module owns ONLY the action-aware naming + z-score computation;
it does NOT own the calibrator instance lifecycle (held by the scorer)
and does NOT emit bulletin events (that is bulletin_adapter).
"""

from __future__ import annotations

from typing import Optional, Tuple

from agent_core.predictive.threshold_calibrator import ThresholdCalibrator


# Avoid div-by-zero when a distribution collapses (e.g. all-equal samples).
_STD_EPSILON: float = 1e-6


def _key(action_type: str, distance_type: str) -> str:
    """Stable distribution key for the calibrator.

    ``distance_type`` is ``"semantic"`` or ``"numeric"``; the prefix
    ``action:`` keeps action-aware buckets distinct from ``global:*``
    percentile buckets the scorer tracks in parallel.
    """
    return f"action:{action_type}:{distance_type}"


class ActionBaseline:
    """Per-action distance baseline over a shared ThresholdCalibrator."""

    def __init__(self, calibrator: ThresholdCalibrator):
        self._cal = calibrator

    def add_observation(
        self,
        action_type: str,
        semantic_distance: float,
        numeric_distance: float,
        timestamp: Optional[float] = None,
    ) -> None:
        """Record one observation for this action_type's two distributions."""
        self._cal.add(
            float(semantic_distance),
            _key(action_type, "semantic"),
            timestamp=timestamp,
        )
        self._cal.add(
            float(numeric_distance),
            _key(action_type, "numeric"),
            timestamp=timestamp,
        )

    def get_z_scores(
        self,
        action_type: str,
        semantic_distance: float,
        numeric_distance: float,
    ) -> Optional[Tuple[float, float]]:
        """Return ``(z_semantic, z_numeric)`` or ``None`` during warm-up.

        Either distribution being below the action-aware floor (decision
        #7d, default N<20) yields None, signalling the caller to fall
        back to the B0 global percentile path.
        """
        sem_stats = self._cal.get_distribution_stats(
            _key(action_type, "semantic"), action_aware=True
        )
        num_stats = self._cal.get_distribution_stats(
            _key(action_type, "numeric"), action_aware=True
        )
        if sem_stats is None or num_stats is None:
            return None
        z_sem = (semantic_distance - sem_stats.mean) / max(
            sem_stats.std, _STD_EPSILON
        )
        z_num = (numeric_distance - num_stats.mean) / max(
            num_stats.std, _STD_EPSILON
        )
        return z_sem, z_num

    def observation_count(
        self, action_type: str, distance_type: str
    ) -> int:
        """Per-(action_type, distance_type) sample count, for diagnostics."""
        return self._cal.observation_count(_key(action_type, distance_type))
