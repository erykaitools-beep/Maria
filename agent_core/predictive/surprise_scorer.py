"""SurpriseScorer: orchestrates B0 / B0.1 surprise detection per tick.

Wires together :py:class:`StateSnapshot`, :py:class:`ThresholdCalibrator`,
:py:class:`ActionBaseline`, and :py:class:`SurpriseBulletinAdapter` into
a single per-tick entry point: :py:meth:`score_tick`.

Per-tick flow (B0_IMPLEMENTATION_SHORTLIST rev 4 punkt 4-6):
  1. Skip-conditions check (mode SLEEP/REDUCED, cpu, ram, tick overrun,
     throttle window) -- cheap pre-check before any embedding call.
  2. Build current snapshot via :py:meth:`StateSnapshot.from_context`.
  3. Cold-start: cache snapshot, return None.
  4. Compute distances vs cached previous snapshot
     (semantic = 1 - cosine; numeric = per-feature scaled euclidean).
  5. Update calibrator (global + per-action observations).
  6. B0.1 path first: if ActionBaseline available + warm for the
     last action_type -> z-score against per-action distribution.
     Otherwise fall through to B0 global percentile path.
  7. Emit a SURPRISE bulletin entry on trigger; cache snapshot for next
     tick either way; return the entry (or None).

Predictive scoring MUST never block / overload homeostasis. Embedding
failures degrade gracefully (snapshot still cached, no emit).
"""

from __future__ import annotations

from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

from agent_core.bulletin.bulletin_model import BulletinEntry
from agent_core.predictive.action_baseline import ActionBaseline
from agent_core.predictive.bulletin_adapter import SurpriseBulletinAdapter
from agent_core.predictive.state_snapshot import StateSnapshot
from agent_core.predictive.threshold_calibrator import ThresholdCalibrator
from agent_core.semantic.embedding_model import EmbeddingModel


# Per-feature scaling for numeric distance. Keeps each feature's
# contribution in roughly [0, 1] before euclidean aggregation. Picked
# from the known operational range of each feature; future iterations
# may swap this for a properly calibrated per-feature z-score, but a
# fixed scale is robust + interpretable for MVP and avoids requiring
# yet another rolling distribution.
NUMERIC_FEATURE_SCALES: Dict[str, float] = {
    "cpu_percent": 100.0,
    "ram_gb": 32.0,
    "error_count_window": 10.0,
    "n_active_goals": 20.0,
    "mode_index": 4.0,
}

# Global percentile bucket names in the calibrator (parallel to B0.1's
# action:* keys held by ActionBaseline).
GLOBAL_KEY_SEMANTIC = "global:semantic"
GLOBAL_KEY_NUMERIC = "global:numeric"

# Defaults from SHORTLIST rev 4 (punkt 4 / decision #6 / decision #7a).
DEFAULT_THROTTLE_SECONDS: float = 60.0
DEFAULT_CPU_SKIP_PCT: float = 80.0
DEFAULT_RAM_SKIP_GB: float = 26.0
DEFAULT_TICK_OVERRUN_WINDOW: int = 3
DEFAULT_SIGMA_THRESHOLD: float = 2.5
DEFAULT_PERCENTILE: float = 95.0

# Modes that fully suppress predictive scoring (decision: punkt 4 skip
# conditions). Predictive scoring is high-cost (embedding call) and the
# system is by design quiet in these modes.
_SKIP_MODES = {"SLEEP", "REDUCED"}


class SurpriseScorer:
    """Per-tick orchestrator. Stateful: caches last snapshot + last score time."""

    def __init__(
        self,
        embed_fn: Callable[[str], List[float]],
        calibrator: ThresholdCalibrator,
        adapter: SurpriseBulletinAdapter,
        action_baseline: Optional[ActionBaseline] = None,
        *,
        throttle_seconds: float = DEFAULT_THROTTLE_SECONDS,
        cpu_skip_pct: float = DEFAULT_CPU_SKIP_PCT,
        ram_skip_gb: float = DEFAULT_RAM_SKIP_GB,
        tick_overrun_window: int = DEFAULT_TICK_OVERRUN_WINDOW,
        sigma_threshold: float = DEFAULT_SIGMA_THRESHOLD,
        percentile: float = DEFAULT_PERCENTILE,
    ):
        self._embed_fn = embed_fn
        self._cal = calibrator
        self._adapter = adapter
        self._action_baseline = action_baseline

        self._throttle_sec = float(throttle_seconds)
        self._cpu_skip_pct = float(cpu_skip_pct)
        self._ram_skip_gb = float(ram_skip_gb)
        self._sigma_threshold = float(sigma_threshold)
        self._percentile = float(percentile)

        self._last_snapshot: Optional[StateSnapshot] = None
        self._last_score_ts: Optional[float] = None
        self._tick_overruns: Deque[bool] = deque(maxlen=int(tick_overrun_window))

    # --- public surface ------------------------------------------------

    def report_tick_overrun(self, overran: bool) -> None:
        """Record whether the most recent tick overran its budget.

        The scorer skips when ANY of the last N reported ticks overran
        (decision: punkt 4). Caller wires this from the homeostasis tick
        loop's own duration measurement.
        """
        self._tick_overruns.append(bool(overran))

    def score_tick(
        self,
        timestamp: float,
        homeostasis_summary: Optional[Dict[str, Any]] = None,
        n_active_goals: Optional[int] = None,
        last_decision: Optional[Dict[str, Any]] = None,
        episode_id: Optional[str] = None,
    ) -> Optional[BulletinEntry]:
        """One predictive-scoring iteration. Returns the emitted entry or None.

        Returns ``None`` whenever the tick was skipped, the system was
        in cold start, the embedding failed, or the surprise was below
        threshold. The bulletin (if any) has already been posted via
        the injected adapter at return time.
        """
        homeo = homeostasis_summary or {}
        mode = homeo.get("mode")

        skip_reason = self._skip_reason(mode, homeo, timestamp)
        if skip_reason is not None:
            return None

        state_t = StateSnapshot.from_context(
            timestamp=timestamp,
            homeostasis_summary=homeo,
            n_active_goals=n_active_goals,
            last_decision=last_decision,
            episode_id=episode_id,
        )

        # Cold start: nothing to compare against yet. Cache & return.
        if self._last_snapshot is None:
            self._last_snapshot = state_t
            self._last_score_ts = timestamp
            return None

        # Distances. Embedding failure -> graceful degrade (cache + None).
        try:
            t_embed = self._embed_fn(state_t.semantic_text)
            t1_embed = self._embed_fn(self._last_snapshot.semantic_text)
        except Exception:
            self._last_snapshot = state_t
            self._last_score_ts = timestamp
            return None

        semantic_distance = 1.0 - EmbeddingModel.cosine_similarity(t_embed, t1_embed)
        numeric_distance = _aligned_numeric_distance(state_t, self._last_snapshot)

        # Daily recompute (decision #7c) -- prunes outside-window obs.
        if self._cal.should_recompute(timestamp):
            self._cal.recompute(timestamp)

        # Feed the global buckets every scored tick.
        self._cal.add(semantic_distance, GLOBAL_KEY_SEMANTIC, timestamp=timestamp)
        self._cal.add(numeric_distance, GLOBAL_KEY_NUMERIC, timestamp=timestamp)

        action_type = state_t.last_action_type
        if self._action_baseline is not None and action_type:
            self._action_baseline.add_observation(
                action_type,
                semantic_distance=semantic_distance,
                numeric_distance=numeric_distance,
                timestamp=timestamp,
            )

        emitted = self._maybe_emit(
            timestamp=timestamp,
            state_t=state_t,
            state_t1=self._last_snapshot,
            semantic_distance=semantic_distance,
            numeric_distance=numeric_distance,
            action_type=action_type,
            episode_id=episode_id,
        )

        # Always advance state, regardless of whether we emitted.
        self._last_snapshot = state_t
        self._last_score_ts = timestamp
        return emitted

    # --- internals -----------------------------------------------------

    def _skip_reason(
        self,
        mode: Optional[str],
        homeo: Dict[str, Any],
        now: float,
    ) -> Optional[str]:
        """Return a short skip reason (logged by caller) or None to proceed.

        Order matters: cheapest checks first so the embedding call is
        avoided as early as possible (decision: punkt 4).
        """
        if mode is not None and mode.upper() in _SKIP_MODES:
            return f"mode:{mode}"
        if (
            self._last_score_ts is not None
            and (now - self._last_score_ts) < self._throttle_sec
        ):
            return "throttle"
        cpu = homeo.get("cpu_percent")
        if cpu is not None and float(cpu) > self._cpu_skip_pct:
            return "cpu_high"
        ram = homeo.get("ram_gb")
        if ram is not None and float(ram) > self._ram_skip_gb:
            return "ram_high"
        if self._tick_overruns and any(self._tick_overruns):
            return "tick_overrun"
        return None

    def _maybe_emit(
        self,
        *,
        timestamp: float,
        state_t: StateSnapshot,
        state_t1: StateSnapshot,
        semantic_distance: float,
        numeric_distance: float,
        action_type: Optional[str],
        episode_id: Optional[str],
    ) -> Optional[BulletinEntry]:
        """B0.1 first, then fall back to B0 global. Returns the emitted entry."""
        # B0.1: action-aware z-score (preferred when warm)
        if self._action_baseline is not None and action_type:
            z = self._action_baseline.get_z_scores(
                action_type,
                semantic_distance=semantic_distance,
                numeric_distance=numeric_distance,
            )
            if z is not None:
                z_sem, z_num = z
                if (
                    abs(z_sem) > self._sigma_threshold
                    or abs(z_num) > self._sigma_threshold
                ):
                    combined = max(abs(z_sem), abs(z_num))
                    return self._adapter.emit_surprise(
                        semantic_distance=semantic_distance,
                        numeric_distance=numeric_distance,
                        combined_surprise=combined,
                        source="b0_1_action",
                        numeric_features_used=state_t.numeric_features_used,
                        state_t_summary=state_t.semantic_text,
                        state_t1_summary=state_t1.semantic_text,
                        action_type=action_type,
                        z_semantic=z_sem,
                        z_numeric=z_num,
                        health_score=state_t.health_score,
                        episode_id=episode_id,
                        timestamp=timestamp,
                    )
                return None  # B0.1 warm and below threshold -> no fallback

        # B0 global: percentile threshold path
        sem_threshold = self._cal.get_percentile_threshold(
            GLOBAL_KEY_SEMANTIC, percentile=self._percentile
        )
        num_threshold = self._cal.get_percentile_threshold(
            GLOBAL_KEY_NUMERIC, percentile=self._percentile
        )
        if sem_threshold is None or num_threshold is None:
            # Warm-up: log diagnostic only, no high-confidence emit
            return None

        sem_over = semantic_distance > sem_threshold
        num_over = numeric_distance > num_threshold
        if not (sem_over or num_over):
            return None

        # Combined for B0 global = ratio over threshold (>1.0 always on emit).
        # Conservative: max channel signal preserved (parallels decision #5b).
        combined = max(
            semantic_distance / sem_threshold if sem_threshold > 0 else 0.0,
            numeric_distance / num_threshold if num_threshold > 0 else 0.0,
        )
        return self._adapter.emit_surprise(
            semantic_distance=semantic_distance,
            numeric_distance=numeric_distance,
            combined_surprise=combined,
            source="b0_global",
            numeric_features_used=state_t.numeric_features_used,
            state_t_summary=state_t.semantic_text,
            state_t1_summary=state_t1.semantic_text,
            health_score=state_t.health_score,
            episode_id=episode_id,
            timestamp=timestamp,
        )


# --- module-level helpers ----------------------------------------------


def _aligned_numeric_distance(t: StateSnapshot, t1: StateSnapshot) -> float:
    """Per-feature scaled euclidean over features both snapshots provide.

    Two snapshots may report different feature subsets (decision #9 --
    missing feature -> skip rather than zero-fill). Distance is computed
    over the intersection only; if there is no overlap we return 0.0
    (no signal, not high-confidence surprise -- caller proceeds normally).

    Mean-normalisation by the count of shared features keeps the
    distance comparable across rounds where the intersection size
    drifts, e.g. when one snapshot is missing health metrics.
    """
    shared = set(t.numeric_features.keys()) & set(t1.numeric_features.keys())
    if not shared:
        return 0.0
    sq_sum = 0.0
    for feat in shared:
        scale = NUMERIC_FEATURE_SCALES.get(feat, 1.0)
        diff = (t.numeric_features[feat] - t1.numeric_features[feat]) / scale
        sq_sum += diff * diff
    return (sq_sum / len(shared)) ** 0.5
