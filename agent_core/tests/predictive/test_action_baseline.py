"""Tests for ActionBaseline (B0.1 per-action z-score wrapper, 2026-05-09)."""

import pytest

from agent_core.predictive.action_baseline import ActionBaseline
from agent_core.predictive.threshold_calibrator import ThresholdCalibrator


# --- ingestion: keys land in the right distributions ----------------


def test_add_observation_records_both_distance_types():
    cal = ThresholdCalibrator()
    ab = ActionBaseline(cal)
    ab.add_observation(
        "learn", semantic_distance=0.1, numeric_distance=0.2, timestamp=10.0
    )
    assert cal.observation_count("action:learn:semantic") == 1
    assert cal.observation_count("action:learn:numeric") == 1


def test_add_observation_isolates_action_types():
    cal = ThresholdCalibrator()
    ab = ActionBaseline(cal)
    ab.add_observation("learn", 0.1, 0.2, timestamp=10.0)
    ab.add_observation("skip", 0.5, 0.6, timestamp=11.0)
    assert cal.observation_count("action:learn:semantic") == 1
    assert cal.observation_count("action:skip:semantic") == 1
    assert ab.observation_count("learn", "semantic") == 1
    assert ab.observation_count("skip", "numeric") == 1


# --- warm-up: get_z_scores returns None until both distributions ready ---


def test_z_scores_none_during_warmup():
    cal = ThresholdCalibrator(min_samples_action=20)
    ab = ActionBaseline(cal)
    for i in range(10):
        ab.add_observation("learn", 0.1, 0.2, timestamp=float(i))
    assert ab.get_z_scores("learn", 0.1, 0.2) is None


def test_z_scores_none_when_only_one_distance_type_warm():
    """Both distributions must clear warm-up -- partial readiness = None.

    Constructed by manually adding to one bucket via the calibrator: a
    real :py:meth:`add_observation` always feeds both at once, but a
    defensive caller may have only one ready (e.g. lopsided log replay).
    Contract: cascade still triggers on partial readiness.
    """
    cal = ThresholdCalibrator(min_samples_action=5)
    ab = ActionBaseline(cal)
    # Five semantic observations, only two numeric -> numeric still warm
    for i in range(5):
        cal.add(0.1 * i, "action:learn:semantic", timestamp=float(i))
    cal.add(0.2, "action:learn:numeric", timestamp=10.0)
    cal.add(0.3, "action:learn:numeric", timestamp=11.0)
    assert ab.get_z_scores("learn", 0.5, 0.6) is None


# --- z-score math: warm path -----------------------------------------


def test_z_scores_math_after_warmup():
    """20 samples of each distance type -> stats computable -> z-score."""
    cal = ThresholdCalibrator(min_samples_action=20)
    ab = ActionBaseline(cal)
    # Both distributions: uniform 0..19 -> mean=9.5, sample std~5.916
    for i in range(20):
        ab.add_observation("learn", float(i), float(i), timestamp=float(i))
    z = ab.get_z_scores("learn", semantic_distance=21.0, numeric_distance=21.0)
    assert z is not None
    z_sem, z_num = z
    # (21 - 9.5) / 5.916 ~ 1.944
    assert z_sem == pytest.approx(1.944, abs=0.01)
    assert z_num == pytest.approx(1.944, abs=0.01)


def test_z_scores_negative_when_below_mean():
    """z-score sign reflects direction (below-baseline -> negative)."""
    cal = ThresholdCalibrator(min_samples_action=20)
    ab = ActionBaseline(cal)
    for i in range(20):
        ab.add_observation(
            "learn", float(i + 10), float(i + 10), timestamp=float(i)
        )
    # Mean ~19.5; query below mean -> negative z
    z = ab.get_z_scores("learn", 5.0, 5.0)
    assert z is not None
    z_sem, z_num = z
    assert z_sem < 0
    assert z_num < 0


def test_z_scores_handle_collapsed_std():
    """Constant distribution (std=0) must not divide by zero."""
    cal = ThresholdCalibrator(min_samples_action=20)
    ab = ActionBaseline(cal)
    for i in range(20):
        ab.add_observation("learn", 0.5, 0.5, timestamp=float(i))
    z = ab.get_z_scores("learn", 0.5, 0.5)
    assert z is not None
    z_sem, z_num = z
    # Difference is zero; z stays finite (eps in denominator) and equals 0
    assert z_sem == pytest.approx(0.0, abs=1e-3)
    assert z_num == pytest.approx(0.0, abs=1e-3)


# --- cascade: unknown action falls through to None ----------------------


def test_unknown_action_returns_none():
    cal = ThresholdCalibrator(min_samples_action=20)
    ab = ActionBaseline(cal)
    # Never observed "experiment" -> 0 samples both distributions
    assert ab.get_z_scores("experiment", 0.1, 0.2) is None


def test_observation_count_unknown_action_is_zero():
    cal = ThresholdCalibrator()
    ab = ActionBaseline(cal)
    assert ab.observation_count("nope", "semantic") == 0


# --- shared calibrator: separation from globals --------------------------


def test_action_keys_isolated_from_global_keys():
    """Global percentile buckets and action-aware buckets do not collide."""
    cal = ThresholdCalibrator(min_samples_global=3, min_samples_action=3)
    ab = ActionBaseline(cal)
    cal.add(0.9, "global:semantic", timestamp=0.0)
    cal.add(0.9, "global:semantic", timestamp=1.0)
    cal.add(0.9, "global:semantic", timestamp=2.0)
    ab.add_observation("learn", 0.1, 0.1, timestamp=10.0)
    ab.add_observation("learn", 0.1, 0.1, timestamp=11.0)
    ab.add_observation("learn", 0.1, 0.1, timestamp=12.0)
    # Independent buckets, independent counts
    assert cal.observation_count("global:semantic") == 3
    assert cal.observation_count("action:learn:semantic") == 3
    # 95-percentile of identical 0.9s = 0.9; z of identical 0.1s = 0
    assert cal.get_percentile_threshold("global:semantic") == 0.9
    z = ab.get_z_scores("learn", 0.1, 0.1)
    assert z is not None
    assert z[0] == pytest.approx(0.0, abs=1e-3)
