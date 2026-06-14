"""Tests for SurpriseScorer (B0/B0.1 orchestrator, 2026-05-09)."""

import hashlib
from typing import List, Optional

import pytest

from agent_core.bulletin.bulletin_model import EntryType
from agent_core.predictive.action_baseline import ActionBaseline
from agent_core.predictive.bulletin_adapter import SurpriseBulletinAdapter
from agent_core.predictive.state_snapshot import StateSnapshot
from agent_core.predictive.surprise_scorer import (
    SurpriseScorer,
    _aligned_numeric_distance,
)
from agent_core.predictive.threshold_calibrator import ThresholdCalibrator


# --- test infrastructure ---------------------------------------------


def _hash_embed(text: str) -> List[float]:
    """Deterministic 8-d embed via md5. Identical text -> identical vector.

    Cross-text cosine distance is uncontrolled (depends on hash output);
    tests that need a specific distance fall back to numeric-distance
    dominance, which IS controllable via the homeostasis dict.
    """
    digest = hashlib.md5(text.encode()).digest()[:8]
    # +1 keeps the vector away from all-zero so cosine_similarity stays
    # well-defined (the EmbeddingModel helper short-circuits on zero norm).
    return [float(b) + 1.0 for b in digest]


def _make_scorer(
    *,
    cal: Optional[ThresholdCalibrator] = None,
    action_baseline: Optional[ActionBaseline] = None,
    throttle_seconds: float = 0.0,
    cpu_skip_pct: float = 80.0,
    ram_skip_gb: float = 26.0,
    sigma_threshold: float = 2.5,
    embed_fn=None,
):
    cal = cal if cal is not None else ThresholdCalibrator()
    posted: List = []
    adapter = SurpriseBulletinAdapter(post_fn=posted.append)
    scorer = SurpriseScorer(
        embed_fn or _hash_embed,
        cal,
        adapter,
        action_baseline=action_baseline,
        throttle_seconds=throttle_seconds,
        cpu_skip_pct=cpu_skip_pct,
        ram_skip_gb=ram_skip_gb,
        sigma_threshold=sigma_threshold,
    )
    return scorer, posted, cal


def _homeo(cpu=10.0, ram=8.0, err=0, mode="ACTIVE"):
    return {
        "cpu_percent": cpu,
        "ram_gb": ram,
        "error_count_window": err,
        "mode": mode,
    }


# --- skip conditions: short-circuit before any embedding -------------


def test_sleep_mode_skips_no_embedding_call():
    """mode=SLEEP -> short-circuit, embedder must not be called."""
    embed_calls: List[str] = []

    def counting_embed(text: str) -> List[float]:
        embed_calls.append(text)
        return [1.0]

    scorer, posted, _ = _make_scorer(embed_fn=counting_embed)
    out = scorer.score_tick(timestamp=100.0, homeostasis_summary=_homeo(mode="SLEEP"))
    assert out is None
    assert posted == []
    assert embed_calls == []


def test_reduced_mode_skips_no_embedding_call():
    embed_calls: List[str] = []
    scorer, posted, _ = _make_scorer(
        embed_fn=lambda t: (embed_calls.append(t) or [1.0])
    )
    out = scorer.score_tick(
        timestamp=100.0, homeostasis_summary=_homeo(mode="REDUCED")
    )
    assert out is None
    assert embed_calls == []


def test_throttle_skips_within_window():
    """Two ticks within throttle window: second is dropped (no embed)."""
    embed_calls: List[str] = []
    scorer, posted, _ = _make_scorer(
        throttle_seconds=60.0,
        embed_fn=lambda t: (embed_calls.append(t) or _hash_embed(t)),
    )
    # Cold start sets last_score_ts = 100.0
    scorer.score_tick(timestamp=100.0, homeostasis_summary=_homeo())
    embed_calls.clear()  # ignore cold-start (no embed call there anyway)
    # Within throttle window -> skip without embedding
    out = scorer.score_tick(timestamp=130.0, homeostasis_summary=_homeo())
    assert out is None
    assert embed_calls == []


def test_cpu_high_skips():
    scorer, posted, _ = _make_scorer(cpu_skip_pct=80.0)
    out = scorer.score_tick(timestamp=100.0, homeostasis_summary=_homeo(cpu=85.0))
    assert out is None
    assert posted == []


def test_ram_high_skips():
    scorer, posted, _ = _make_scorer(ram_skip_gb=26.0)
    out = scorer.score_tick(timestamp=100.0, homeostasis_summary=_homeo(ram=27.0))
    assert out is None
    assert posted == []


def test_tick_overrun_recent_skips():
    scorer, posted, _ = _make_scorer()
    scorer.report_tick_overrun(True)
    out = scorer.score_tick(timestamp=100.0, homeostasis_summary=_homeo())
    assert out is None
    assert posted == []


def test_tick_overrun_window_clears_after_n_calls():
    """Default overrun window=3: 3 clean reports flush the True flag."""
    scorer, posted, _ = _make_scorer()
    scorer.report_tick_overrun(True)
    scorer.report_tick_overrun(False)
    scorer.report_tick_overrun(False)
    scorer.report_tick_overrun(False)  # ringbuffer (maxlen=3) drops the True
    # Now overruns deque == [False, False, False] -> any() == False
    out = scorer.score_tick(timestamp=100.0, homeostasis_summary=_homeo())
    # First call is cold-start -> None, but it ran past skip checks (no exception)
    assert out is None  # cold start, not skip


# --- cold start + state caching --------------------------------------


def test_cold_start_skip_caches_snapshot():
    """First call has no t-1 -> cache + return None."""
    scorer, posted, _ = _make_scorer()
    out = scorer.score_tick(timestamp=100.0, homeostasis_summary=_homeo())
    assert out is None
    assert posted == []


# --- B0 global path: warm-up + emit + no-emit -----------------------


def test_b0_global_warmup_no_emit():
    """Empty calibrator -> no high-confidence emit even on big jump."""
    scorer, posted, _ = _make_scorer()
    # Cold start
    scorer.score_tick(timestamp=100.0, homeostasis_summary=_homeo(cpu=10))
    # Big jump but global percentile threshold is None (warm-up)
    out = scorer.score_tick(
        timestamp=200.0, homeostasis_summary=_homeo(cpu=70, err=50)
    )
    assert out is None
    assert posted == []


def test_b0_global_large_jump_emits():
    """Pre-warmed calibrator + numeric-dominant jump -> emit b0_global."""
    cal = ThresholdCalibrator(min_samples_global=20)
    # Tight low baseline -> 95-percentile threshold ~ 0.034
    for i in range(25):
        cal.add(0.01 + i * 0.001, "global:semantic", timestamp=float(i))
        cal.add(0.01 + i * 0.001, "global:numeric", timestamp=float(i))
    scorer, posted, _ = _make_scorer(cal=cal)

    # Cold start at modest state
    scorer.score_tick(
        timestamp=100.0, homeostasis_summary=_homeo(cpu=10, err=1),
        n_active_goals=5, last_decision={"action_type": "learn"},
    )
    # Big numeric jump (cpu, err, n_goals all swing) -> numeric_distance dominant
    out = scorer.score_tick(
        timestamp=200.0, homeostasis_summary=_homeo(cpu=70, err=50),
        n_active_goals=50, last_decision={"action_type": "learn"},
    )
    assert out is not None
    assert out.entry_type == EntryType.SURPRISE
    assert posted == [out]
    md = out.metadata
    assert md["source"] == "b0_global"
    assert md["z_semantic"] is None
    assert md["z_numeric"] is None
    assert md["action_type"] is None  # global path doesn't tag action_type


def test_b0_global_same_state_no_emit_after_warmup():
    """Identical homeo two ticks -> distance ~ 0 -> no emit."""
    cal = ThresholdCalibrator(min_samples_global=20)
    # High threshold so even moderate distance wouldn't trigger
    for i in range(25):
        cal.add(0.5, "global:semantic", timestamp=float(i))
        cal.add(0.5, "global:numeric", timestamp=float(i))
    scorer, posted, _ = _make_scorer(cal=cal)
    homeo = _homeo(cpu=10, err=1)
    scorer.score_tick(
        timestamp=100.0, homeostasis_summary=homeo, n_active_goals=5,
        last_decision={"action_type": "learn"},
    )
    out = scorer.score_tick(
        timestamp=200.0, homeostasis_summary=homeo, n_active_goals=5,
        last_decision={"action_type": "learn"},
    )
    assert out is None
    assert posted == []


# --- B0.1 action-aware path ------------------------------------------


def test_b0_1_emits_when_warm_and_unexpected():
    """Action baseline warm + huge jump -> emit b0_1_action."""
    # Use very high min_samples_global so we never use the global path here.
    cal = ThresholdCalibrator(min_samples_global=10000, min_samples_action=10)
    ab = ActionBaseline(cal)
    # Tight baseline around small distances
    for i in range(15):
        ab.add_observation("learn", 0.01, 0.01, timestamp=float(i))
    scorer, posted, _ = _make_scorer(
        cal=cal, action_baseline=ab, sigma_threshold=2.0
    )
    scorer.score_tick(
        timestamp=100.0, homeostasis_summary=_homeo(cpu=10, err=1),
        n_active_goals=5, last_decision={"action_type": "learn"},
    )
    out = scorer.score_tick(
        timestamp=200.0, homeostasis_summary=_homeo(cpu=70, err=50),
        n_active_goals=50, last_decision={"action_type": "learn"},
    )
    assert out is not None
    md = out.metadata
    assert md["source"] == "b0_1_action"
    assert md["action_type"] == "learn"
    assert md["z_semantic"] is not None
    assert md["z_numeric"] is not None
    # combined_surprise = max(|z_sem|, |z_num|)
    expected_combined = max(abs(md["z_semantic"]), abs(md["z_numeric"]))
    assert md["combined_surprise"] == pytest.approx(expected_combined, abs=1e-9)


def test_b0_1_same_state_no_emit_when_within_baseline():
    """Same state -> distance 0 sits within varied baseline (small abs(z))."""
    cal = ThresholdCalibrator(min_samples_global=10000, min_samples_action=10)
    ab = ActionBaseline(cal)
    # Varied baseline 0..0.56 -> mean ~ 0.28, std ~ 0.18
    for i in range(15):
        d = i * 0.04
        ab.add_observation("learn", d, d, timestamp=float(i))
    scorer, posted, _ = _make_scorer(
        cal=cal, action_baseline=ab, sigma_threshold=2.5
    )
    homeo = _homeo(cpu=10, err=1)
    scorer.score_tick(
        timestamp=100.0, homeostasis_summary=homeo, n_active_goals=5,
        last_decision={"action_type": "learn"},
    )
    # Distance ~ 0 -> z = (0 - 0.28) / 0.18 ~ -1.55, abs < 2.5 -> no emit
    out = scorer.score_tick(
        timestamp=200.0, homeostasis_summary=homeo, n_active_goals=5,
        last_decision={"action_type": "learn"},
    )
    assert out is None
    assert posted == []


def test_b0_1_below_sigma_no_fallback_to_global():
    """B0.1 warm + below sigma_threshold -> no emit AND no global fallback."""
    cal = ThresholdCalibrator(min_samples_global=20, min_samples_action=10)
    # Pre-warm BOTH global and action so either path could fire if cascade
    # logic were broken.
    for i in range(25):
        cal.add(0.0001, "global:semantic", timestamp=float(i))
        cal.add(0.0001, "global:numeric", timestamp=float(i))
    ab = ActionBaseline(cal)
    for i in range(15):
        ab.add_observation("learn", 0.1 + i * 0.01, 0.1 + i * 0.01, timestamp=float(i))
    scorer, posted, _ = _make_scorer(
        cal=cal, action_baseline=ab, sigma_threshold=100.0  # absurdly high
    )
    scorer.score_tick(
        timestamp=100.0, homeostasis_summary=_homeo(cpu=10, err=1),
        n_active_goals=5, last_decision={"action_type": "learn"},
    )
    # Big jump -> b0_1 triggers, computes z, |z| < 100 -> no emit. Crucially
    # the cascade does NOT then try b0_global (which would emit because
    # the distance massively exceeds the global percentile threshold).
    out = scorer.score_tick(
        timestamp=200.0, homeostasis_summary=_homeo(cpu=70, err=50),
        n_active_goals=50, last_decision={"action_type": "learn"},
    )
    assert out is None
    assert posted == []


def test_rare_action_falls_back_to_global():
    """Action with N<20 baseline -> B0.1 None -> B0 global path runs.

    Global is pre-filled with 25 tight values so the 95-percentile lands
    on a low pre-fill value, not on the larger value the scorer adds for
    this tick.
    """
    cal = ThresholdCalibrator(min_samples_global=5, min_samples_action=20)
    ab = ActionBaseline(cal)
    # Only 3 samples of "rare_action" -> still warm under N=20 floor
    for i in range(3):
        ab.add_observation("rare_action", 0.05, 0.05, timestamp=float(i))
    # Pre-warm GLOBAL with enough samples that 95p doesn't shift onto
    # the freshly-added value.
    for i in range(25):
        cal.add(0.01 + i * 0.001, "global:semantic", timestamp=float(i + 10))
        cal.add(0.01 + i * 0.001, "global:numeric", timestamp=float(i + 10))
    scorer, posted, _ = _make_scorer(cal=cal, action_baseline=ab)
    scorer.score_tick(
        timestamp=100.0, homeostasis_summary=_homeo(cpu=10, err=1),
        n_active_goals=5, last_decision={"action_type": "rare_action"},
    )
    out = scorer.score_tick(
        timestamp=200.0, homeostasis_summary=_homeo(cpu=70, err=50),
        n_active_goals=50, last_decision={"action_type": "rare_action"},
    )
    assert out is not None
    assert out.metadata["source"] == "b0_global"  # B0.1 was warm -> fell through


# --- graceful degradation + path absence -----------------------------


def test_embedding_failure_caches_state_no_crash():
    """embed_fn raising on a non-cold-start tick -> graceful None, no post."""
    cal = ThresholdCalibrator()
    posted: List = []
    adapter = SurpriseBulletinAdapter(post_fn=posted.append)

    state = {"calls": 0}

    def boom(text: str) -> List[float]:
        state["calls"] += 1
        raise RuntimeError("ollama down")

    scorer = SurpriseScorer(boom, cal, adapter)
    # Cold start: snapshot built but NO embed call yet (t-1 is None)
    out1 = scorer.score_tick(timestamp=100.0, homeostasis_summary=_homeo())
    assert out1 is None
    assert state["calls"] == 0
    # Second tick: embed raises -> graceful None
    out2 = scorer.score_tick(timestamp=200.0, homeostasis_summary=_homeo(cpu=20))
    assert out2 is None
    assert posted == []
    assert state["calls"] >= 1


def test_no_action_baseline_uses_global_path_only():
    """action_baseline=None -> B0.1 disabled, only B0 global is consulted."""
    cal = ThresholdCalibrator(min_samples_global=20)
    for i in range(25):
        cal.add(0.01, "global:semantic", timestamp=float(i))
        cal.add(0.01, "global:numeric", timestamp=float(i))
    scorer, posted, _ = _make_scorer(cal=cal, action_baseline=None)
    scorer.score_tick(
        timestamp=100.0, homeostasis_summary=_homeo(cpu=10, err=1),
        n_active_goals=5, last_decision={"action_type": "learn"},
    )
    out = scorer.score_tick(
        timestamp=200.0, homeostasis_summary=_homeo(cpu=70, err=50),
        n_active_goals=50, last_decision={"action_type": "learn"},
    )
    assert out is not None
    assert out.metadata["source"] == "b0_global"


# --- payload contract -------------------------------------------------


def test_emit_payload_carries_raw_subscores_and_features():
    """SURPRISE entry must surface raw distances + numeric_features_used."""
    cal = ThresholdCalibrator(min_samples_global=20)
    for i in range(25):
        cal.add(0.001, "global:semantic", timestamp=float(i))
        cal.add(0.001, "global:numeric", timestamp=float(i))
    scorer, posted, _ = _make_scorer(cal=cal)
    scorer.score_tick(
        timestamp=100.0, homeostasis_summary=_homeo(cpu=10, err=1),
        n_active_goals=5,
    )
    out = scorer.score_tick(
        timestamp=200.0, homeostasis_summary=_homeo(cpu=70, err=50),
        n_active_goals=50,
    )
    assert out is not None
    md = out.metadata
    assert isinstance(md["semantic_distance"], float)
    assert isinstance(md["numeric_distance"], float)
    assert isinstance(md["combined_surprise"], float)
    assert md["source"] == "b0_global"
    feats = md["numeric_features_used"]
    assert isinstance(feats, list)
    # All five features were supplied via _homeo + n_active_goals
    for f in ["cpu_percent", "ram_gb", "error_count_window", "n_active_goals", "mode_index"]:
        assert f in feats


# --- numeric distance helper -----------------------------------------


def test_aligned_numeric_distance_no_overlap_returns_zero():
    a = StateSnapshot(
        timestamp=0.0, semantic_text="",
        numeric_features={"cpu_percent": 10.0},
    )
    b = StateSnapshot(
        timestamp=1.0, semantic_text="",
        numeric_features={"ram_gb": 8.0},
    )
    assert _aligned_numeric_distance(a, b) == 0.0


def test_aligned_numeric_distance_identical_is_zero():
    feats = {"cpu_percent": 10.0, "ram_gb": 8.0}
    a = StateSnapshot(timestamp=0.0, semantic_text="x", numeric_features=feats)
    b = StateSnapshot(timestamp=1.0, semantic_text="x", numeric_features=feats)
    assert _aligned_numeric_distance(a, b) == 0.0


def test_aligned_numeric_distance_uses_intersection_only():
    """Features only in one snapshot are silently ignored."""
    a = StateSnapshot(
        timestamp=0.0, semantic_text="x",
        numeric_features={"cpu_percent": 50.0, "ram_gb": 16.0, "n_active_goals": 5.0},
    )
    b = StateSnapshot(
        timestamp=1.0, semantic_text="x",
        numeric_features={"cpu_percent": 50.0, "ram_gb": 16.0},  # n_goals missing
    )
    # cpu identical, ram identical -> distance = 0 over the 2 shared features
    assert _aligned_numeric_distance(a, b) == 0.0


def test_aligned_numeric_distance_scales_per_feature():
    """cpu diff 50 (scale 100) -> 0.5; sole feature -> sqrt(0.25/1) = 0.5."""
    a = StateSnapshot(
        timestamp=0.0, semantic_text="x",
        numeric_features={"cpu_percent": 10.0},
    )
    b = StateSnapshot(
        timestamp=1.0, semantic_text="x",
        numeric_features={"cpu_percent": 60.0},
    )
    assert _aligned_numeric_distance(a, b) == pytest.approx(0.5, abs=1e-9)
