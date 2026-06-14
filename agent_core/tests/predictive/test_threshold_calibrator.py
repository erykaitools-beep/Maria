"""Tests for ThresholdCalibrator (B0/B0.1 calibration layer, 2026-05-09)."""

import statistics

import pytest

from agent_core.predictive.threshold_calibrator import (
    DistributionStats,
    ThresholdCalibrator,
)


# --- ingestion + counts ----------------------------------------------


def test_add_increments_observation_count():
    cal = ThresholdCalibrator()
    cal.add(0.1, "global", timestamp=100.0)
    cal.add(0.2, "global", timestamp=101.0)
    cal.add(0.3, "global", timestamp=102.0)
    assert cal.observation_count("global") == 3


def test_separate_distributions_independent():
    cal = ThresholdCalibrator()
    cal.add(0.1, "global", timestamp=100.0)
    cal.add(0.5, "action:learn", timestamp=100.0)
    cal.add(0.6, "action:learn", timestamp=101.0)
    assert cal.observation_count("global") == 1
    assert cal.observation_count("action:learn") == 2
    assert set(cal.distributions()) == {"global", "action:learn"}


def test_observation_count_unknown_key_is_zero():
    cal = ThresholdCalibrator()
    assert cal.observation_count("nope") == 0


# --- warm-up gating --------------------------------------------------


def test_warming_up_global_default_threshold_200():
    cal = ThresholdCalibrator()
    for i in range(199):
        cal.add(0.1, "global", timestamp=float(i))
    assert cal.is_warming_up("global") is True
    cal.add(0.1, "global", timestamp=199.0)
    assert cal.is_warming_up("global") is False


def test_warming_up_action_threshold_20_when_action_aware():
    cal = ThresholdCalibrator()
    for i in range(19):
        cal.add(0.1, "action:learn", timestamp=float(i))
    assert cal.is_warming_up("action:learn", action_aware=True) is True
    cal.add(0.1, "action:learn", timestamp=19.0)
    assert cal.is_warming_up("action:learn", action_aware=True) is False


def test_warming_up_action_aware_flag_is_explicit():
    """Same key reads warm-up differently depending on action_aware flag."""
    cal = ThresholdCalibrator()
    for i in range(50):
        cal.add(0.1, "action:learn", timestamp=float(i))
    # 50 samples: above N=20 (action) but below N=200 (global)
    assert cal.is_warming_up("action:learn", action_aware=True) is False
    assert cal.is_warming_up("action:learn", action_aware=False) is True


# --- percentile threshold (B0 global) -------------------------------


def test_percentile_threshold_returns_none_during_warmup():
    cal = ThresholdCalibrator()
    for i in range(50):
        cal.add(0.1, "global", timestamp=float(i))
    assert cal.get_percentile_threshold("global") is None


def test_percentile_threshold_unknown_key_returns_none():
    cal = ThresholdCalibrator(min_samples_global=1)
    assert cal.get_percentile_threshold("missing") is None


def test_percentile_95_correct_value_uniform_distribution():
    """Distance i for i in 0..199 -> 95%-ile sits near the high tail."""
    cal = ThresholdCalibrator()
    for i in range(200):
        cal.add(float(i), "global", timestamp=float(i))
    # Expected idx = int(200 * 0.95) = 190 -> values[190] = 190.0
    assert cal.get_percentile_threshold("global", percentile=95.0) == 190.0


def test_percentile_100_returns_max_value():
    """Boundary: percentile=100 must clamp to last index, not crash."""
    cal = ThresholdCalibrator(min_samples_global=3)
    cal.add(1.0, "g", timestamp=1.0)
    cal.add(5.0, "g", timestamp=2.0)
    cal.add(2.0, "g", timestamp=3.0)
    assert cal.get_percentile_threshold("g", percentile=100.0) == 5.0


def test_percentile_threshold_independent_of_insertion_order():
    """Percentile is computed on sorted values, not on add order."""
    cal = ThresholdCalibrator(min_samples_global=5)
    for v in [5.0, 1.0, 4.0, 2.0, 3.0]:
        cal.add(v, "g", timestamp=0.0)
    # 5 values, percentile=80 -> idx=int(5*0.8)=4 -> sorted[4]=5.0
    assert cal.get_percentile_threshold("g", percentile=80.0) == 5.0


# --- distribution stats (B0.1 sigma) ---------------------------------


def test_distribution_stats_returns_none_during_warmup():
    cal = ThresholdCalibrator()
    for i in range(10):
        cal.add(0.1, "action:learn", timestamp=float(i))
    assert cal.get_distribution_stats(
        "action:learn", action_aware=True
    ) is None


def test_distribution_stats_correct_mean_and_std():
    cal = ThresholdCalibrator()
    values = [float(i) for i in range(20)]  # 0..19
    for i, v in enumerate(values):
        cal.add(v, "action:learn", timestamp=float(i))
    stats = cal.get_distribution_stats("action:learn", action_aware=True)
    assert stats is not None
    assert isinstance(stats, DistributionStats)
    assert stats.n == 20
    assert stats.mean == pytest.approx(statistics.fmean(values))
    assert stats.std == pytest.approx(statistics.stdev(values))


def test_distribution_stats_n_one_returns_none():
    """Sample std requires n>=2."""
    cal = ThresholdCalibrator(min_samples_action=1)
    cal.add(0.5, "action:learn", timestamp=0.0)
    assert cal.get_distribution_stats(
        "action:learn", action_aware=True
    ) is None


# --- recompute / window pruning --------------------------------------


def test_recompute_prunes_observations_outside_window():
    cal = ThresholdCalibrator(window_seconds=100.0)
    cal.add(0.1, "global", timestamp=0.0)        # too old, will be pruned
    cal.add(0.2, "global", timestamp=50.0)       # too old, will be pruned
    cal.add(0.3, "global", timestamp=150.0)      # kept
    cal.add(0.4, "global", timestamp=199.0)      # kept
    cal.recompute(now=200.0)
    # Only observations with ts >= 200 - 100 = 100 survive
    assert cal.observation_count("global") == 2


def test_recompute_drops_empty_distributions():
    cal = ThresholdCalibrator(window_seconds=10.0)
    cal.add(0.1, "stale", timestamp=0.0)
    cal.add(0.2, "fresh", timestamp=100.0)
    cal.recompute(now=105.0)
    # 'stale' had only an old observation -> bucket removed entirely
    assert "stale" not in cal.distributions()
    assert "fresh" in cal.distributions()


def test_recompute_marks_timestamp():
    cal = ThresholdCalibrator()
    assert cal.should_recompute(now=0.0) is True  # never run -> always due
    cal.recompute(now=1000.0)
    assert cal.should_recompute(now=1000.0) is False


def test_should_recompute_respects_interval():
    cal = ThresholdCalibrator(recompute_interval_seconds=100.0)
    cal.recompute(now=0.0)
    assert cal.should_recompute(now=99.0) is False
    assert cal.should_recompute(now=100.0) is True
    assert cal.should_recompute(now=500.0) is True


def test_recompute_does_not_alter_in_window_observations():
    """Pruning must only remove out-of-window points, not reorder them."""
    cal = ThresholdCalibrator(window_seconds=1000.0, min_samples_global=3)
    for i in range(5):
        cal.add(float(i), "g", timestamp=float(i * 100))
    cal.recompute(now=500.0)
    # All 5 observations have ts in [0, 400] -> within last 1000s -> kept
    assert cal.observation_count("g") == 5
    # Percentile still sees the full set
    assert cal.get_percentile_threshold("g", percentile=100.0) == 4.0


# --- custom thresholds passed to constructor -------------------------


def test_custom_min_samples_global():
    cal = ThresholdCalibrator(min_samples_global=3)
    cal.add(0.1, "g", timestamp=0.0)
    cal.add(0.2, "g", timestamp=1.0)
    assert cal.is_warming_up("g") is True
    cal.add(0.3, "g", timestamp=2.0)
    assert cal.is_warming_up("g") is False


def test_custom_min_samples_action():
    cal = ThresholdCalibrator(min_samples_action=2)
    cal.add(0.1, "action:x", timestamp=0.0)
    assert cal.is_warming_up("action:x", action_aware=True) is True
    cal.add(0.2, "action:x", timestamp=1.0)
    assert cal.is_warming_up("action:x", action_aware=True) is False
