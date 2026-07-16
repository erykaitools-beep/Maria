#!/usr/bin/env python
"""Offline replay of the B0/B0.1 predictive "eyes" over Maria's real corpus.

READ-ONLY diagnostic. Touches NO live store and NO daemon. Answers Eryk's
"czy to ma sens": when the predictive surprise layer is opened on Maria's
actual logged history, does it carry meaningful signal, or is it inert/noise?

It reuses the REAL predictive components -- StateSnapshot.from_context,
ThresholdCalibrator, ActionBaseline, SurpriseScorer, SurpriseBulletinAdapter
-- with a fake post_fn that records emissions, so the verdict tests the real
scoring code, not a re-implementation.

Per the adversarial review (workflow wf_d7c6cc5c-39b), it reports up front:
  - the TRUE scorable set (SLEEP/REDUCED are skipped by design)
  - warm-up coverage (the calibrator may never warm on a single daemon run)
  - per-channel distance variance (is the 768-dim semantic channel inert?)
and treats clustering-vs-Poisson as the headline falsifiable test, with
real-nomic-vs-hash-embed to expose a dead semantic channel and an
INDEPENDENT machine-readable anomaly proxy (kept separate from the scorer's
own cpu/ram inputs to avoid a circular true-positive rate).
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path("/home/maria/maria")
META = ROOT / "meta_data"
sys.path.insert(0, str(ROOT))

from agent_core.predictive.state_snapshot import StateSnapshot  # noqa: E402
from agent_core.predictive.threshold_calibrator import ThresholdCalibrator  # noqa: E402
from agent_core.predictive.action_baseline import ActionBaseline  # noqa: E402
from agent_core.predictive.bulletin_adapter import SurpriseBulletinAdapter  # noqa: E402
from agent_core.predictive.surprise_scorer import (  # noqa: E402
    SurpriseScorer,
    GLOBAL_KEY_SEMANTIC,
    GLOBAL_KEY_NUMERIC,
)
from agent_core.semantic.embedding_model import EmbeddingModel  # noqa: E402

TOTAL_RAM_GB = 32.0
ERROR_WINDOW_SEC = 3600.0  # rolling window for the derived error_count feature
JOIN_WINDOW_SEC = 90.0     # strict nearest-preceding join for last_action_type


# --------------------------------------------------------------------------
# Corpus loading + derivation
# --------------------------------------------------------------------------

def load_jsonl(path: Path) -> List[dict]:
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def load_state_snapshots() -> List[dict]:
    recs = load_jsonl(META / "homeostasis_events.jsonl")
    snaps = [r for r in recs if r.get("event_type") == "state_snapshot"]
    snaps.sort(key=lambda r: r["timestamp"])
    return snaps


def load_anomaly_markers() -> Dict[str, List[float]]:
    """INDEPENDENT machine-readable anomaly ground truth.

    Deliberately NOT derived from the scorer's own cpu/ram numeric inputs --
    these are event-level state changes the homeostat itself logged. Still
    partly correlated (a health drop can follow a resource spike), so the
    verdict flags coincidence with these as SECONDARY, with the clustering
    test (which needs no ground truth) as the primary falsifiable metric.
    """
    recs = load_jsonl(META / "homeostasis_events.jsonl")
    markers: Dict[str, List[float]] = defaultdict(list)
    for r in recs:
        et = r.get("event_type")
        ev = r.get("event")
        ts = r.get("timestamp")
        if ts is None:
            continue
        if et == "mode_change":
            to_mode = str(r.get("to_mode", "")).lower()
            if to_mode in ("reduced", "survival", "off", "sleep"):
                markers["mode_change"].append(ts)
        if ev == "recovery" or et == "recovery":
            markers["recovery"].append(ts)
        if et == "state_snapshot":
            hs = r.get("health_score")
            if hs is not None and hs < 0.7:
                markers["health_below_0.7"].append(ts)
    return markers


def build_error_lookup(traces: List[dict]) -> Callable[[float], float]:
    """Rolling count of decision-trace failures in the preceding window.

    Pinned canonical derivation for error_count_window (the feature has no
    direct corpus field). Sparse by nature (69 failures over 7d) -- reported
    as near-constant if so, rather than silently dropped.
    """
    fails = sorted(
        t.get("finished_at") or t.get("started_at")
        for t in traces
        if t.get("success") is False and (t.get("finished_at") or t.get("started_at"))
    )

    def lookup(ts: float) -> float:
        lo = ts - ERROR_WINDOW_SEC
        return float(sum(1 for f in fails if lo <= f <= ts))

    return lookup


def build_action_join(traces: List[dict]) -> Callable[[float], Optional[Tuple[str, float]]]:
    """Nearest-preceding non-empty action_type within a strict window."""
    labelled = sorted(
        (t.get("finished_at") or t.get("started_at"), t.get("action_type"))
        for t in traces
        if t.get("action_type") and (t.get("finished_at") or t.get("started_at"))
    )
    times = [t for t, _ in labelled]

    def lookup(ts: float) -> Optional[Tuple[str, float]]:
        import bisect
        i = bisect.bisect_right(times, ts) - 1
        if i < 0:
            return None
        t_at, action = labelled[i]
        gap = ts - t_at
        if gap > JOIN_WINDOW_SEC:
            return None
        return action, gap

    return lookup


# --------------------------------------------------------------------------
# Embedders
# --------------------------------------------------------------------------

def make_hash_embed(dim: int = 768) -> Callable[[str], List[float]]:
    def hash_embed(text: str) -> List[float]:
        if not text or not text.strip():
            return []
        vals: List[float] = []
        seed = text.encode()
        i = 0
        while len(vals) < dim:
            block = hashlib.sha256(seed + i.to_bytes(4, "little")).digest()
            for b in block:
                vals.append(b / 255.0 - 0.5)
                if len(vals) >= dim:
                    break
            i += 1
        return vals
    return hash_embed


# --------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------

def run_replay(
    snaps: List[dict],
    error_lookup: Callable[[float], float],
    action_join: Callable[[float], Optional[Tuple[str, float]]],
    embed_fn: Callable[[str], List[float]],
    *,
    global_floor: int,
    action_floor: int,
    label: str,
) -> dict:
    cal = ThresholdCalibrator(
        min_samples_global=global_floor,
        min_samples_action=action_floor,
    )
    baseline = ActionBaseline(cal)
    recorded: List[Any] = []
    adapter = SurpriseBulletinAdapter(post_fn=recorded.append)
    scorer = SurpriseScorer(
        embed_fn=embed_fn,
        calibrator=cal,
        adapter=adapter,
        action_baseline=baseline,
        throttle_seconds=0.0,  # corpus rows are already ~60s apart
    )

    # Per-tick observability we collect alongside the real scorer.
    sem_series: List[float] = []   # semantic distances on scored (non-skip,non-cold) ticks
    num_series: List[float] = []
    scored_ts: List[float] = []
    semantic_texts: List[str] = []
    join_gaps: List[float] = []
    labelled_ticks = 0
    empty_embed_ticks = 0

    n_total = len(snaps)
    n_skipped_mode = 0
    n_cold = 0
    n_scored = 0

    prev_emb: Optional[List[float]] = None
    prev_snap: Optional[StateSnapshot] = None

    from agent_core.predictive.surprise_scorer import _aligned_numeric_distance

    for r in snaps:
        ts = r["timestamp"]
        mode = r.get("mode")
        metrics = r.get("metrics", {}) or {}

        cpu_load = metrics.get("cpu_load")
        ram_pct = metrics.get("ram_available_pct")
        ram_gb = (1.0 - ram_pct / 100.0) * TOTAL_RAM_GB if ram_pct is not None else None
        homeo = {
            "cpu_percent": cpu_load,
            "ram_gb": ram_gb,
            "error_count_window": error_lookup(ts),
            "mode": mode,
            "health_score": r.get("health_score"),
        }

        joined = action_join(ts)
        last_decision = None
        if joined is not None:
            action, gap = joined
            last_decision = {"action_type": action}
            join_gaps.append(gap)
            labelled_ticks += 1

        # --- drive the REAL scorer (this is what live would fire) ---
        scorer.score_tick(
            timestamp=ts,
            homeostasis_summary=homeo,
            n_active_goals=3,           # static standing-goal proxy this window
            last_decision=last_decision,
            episode_id=None,
        )

        # --- mirror the scorer's own skip/cold logic for the raw series ---
        if mode is not None and mode.upper() in ("SLEEP", "REDUCED"):
            n_skipped_mode += 1
            continue

        snap = StateSnapshot.from_context(
            timestamp=ts,
            homeostasis_summary=homeo,
            n_active_goals=3,
            last_decision=last_decision,
        )
        emb = embed_fn(snap.semantic_text)
        if not emb:
            empty_embed_ticks += 1

        if prev_snap is None:
            n_cold += 1
            prev_snap, prev_emb = snap, emb
            continue

        if emb and prev_emb and len(emb) == len(prev_emb):
            sem = 1.0 - EmbeddingModel.cosine_similarity(emb, prev_emb)
        else:
            sem = float("nan")  # flagged; never silently scored as 1.0
        num = _aligned_numeric_distance(snap, prev_snap)

        if not math.isnan(sem):
            sem_series.append(sem)
        num_series.append(num)
        scored_ts.append(ts)
        semantic_texts.append(snap.semantic_text)
        n_scored += 1
        prev_snap, prev_emb = snap, emb

    # --- fires from the real scorer ---
    fires = []
    for entry in recorded:
        md = entry.metadata
        fires.append({
            "timestamp": md["timestamp"],
            "source": md["source"],
            "action_type": md.get("action_type"),
            "semantic_distance": md["semantic_distance"],
            "numeric_distance": md["numeric_distance"],
            "combined_surprise": md["combined_surprise"],
            "numeric_features_used": md["numeric_features_used"],
        })

    # --- warm-up coverage ---
    global_obs = cal.observation_count(GLOBAL_KEY_SEMANTIC)
    action_keys = [k for k in cal.distributions() if k.startswith("action:")]
    action_counts = {k: cal.observation_count(k) for k in action_keys}
    actions_warm = [k for k, c in action_counts.items()
                    if c >= action_floor and ":semantic" in k]

    return {
        "label": label,
        "global_floor": global_floor,
        "action_floor": action_floor,
        "counts": {
            "total_snapshots": n_total,
            "skipped_sleep_reduced": n_skipped_mode,
            "cold_start": n_cold,
            "scored_ticks": n_scored,
            "ticks_with_action_label": labelled_ticks,
            "empty_embedding_ticks": empty_embed_ticks,
        },
        "warmup": {
            "global_obs": global_obs,
            "global_floor": global_floor,
            "global_warm": global_obs >= global_floor,
            "scored_after_warm": max(0, n_scored - global_floor),
            "action_distributions": len(action_keys) // 2,
            "actions_reaching_floor": actions_warm,
        },
        "channel_variance": {
            "semantic_mean": _safe(statistics.fmean, sem_series),
            "semantic_std": _safe(statistics.pstdev, sem_series),
            "semantic_max": max(sem_series) if sem_series else None,
            "semantic_distinct_texts": len(set(semantic_texts)),
            "numeric_mean": _safe(statistics.fmean, num_series),
            "numeric_std": _safe(statistics.pstdev, num_series),
            "numeric_max": max(num_series) if num_series else None,
        },
        "join": {
            "labelled_ticks": labelled_ticks,
            "join_gap_median": _safe(statistics.median, join_gaps),
        },
        "fires": fires,
        "fire_count": len(fires),
        "scored_ts": scored_ts,
        "sem_series": sem_series,
        "num_series": num_series,
    }


def _safe(fn, seq):
    try:
        return round(fn(seq), 5) if seq else None
    except Exception:
        return None


# --------------------------------------------------------------------------
# Verdict metrics
# --------------------------------------------------------------------------

def fano_factor(timestamps: List[float], span_lo: float, span_hi: float,
                bucket_sec: float = 3600.0) -> Optional[dict]:
    """Clustering test: variance/mean of per-bucket fire counts vs Poisson(=1).

    Fano ~1 -> uniform/random (noise). Fano >>1 -> clustered (overdispersed
    = events bunch near real state-changes). Fano <1 -> regular.
    """
    if not timestamps:
        return None
    n_buckets = max(1, int(math.ceil((span_hi - span_lo) / bucket_sec)))
    counts = [0] * n_buckets
    for t in timestamps:
        idx = min(n_buckets - 1, int((t - span_lo) / bucket_sec))
        counts[idx] += 1
    mean = statistics.fmean(counts)
    if mean == 0:
        return None
    var = statistics.pvariance(counts)
    return {
        "n_buckets": n_buckets,
        "fires": len(timestamps),
        "mean_per_bucket": round(mean, 4),
        "fano_factor": round(var / mean, 4),
        "nonempty_buckets": sum(1 for c in counts if c > 0),
    }


def coincidence(fire_ts: List[float], markers: Dict[str, List[float]],
                window: float = 600.0) -> dict:
    out = {}
    all_markers = sorted(t for v in markers.values() for t in v)
    matched = 0
    for ft in fire_ts:
        if any(abs(ft - m) <= window for m in all_markers):
            matched += 1
    out["fires"] = len(fire_ts)
    out["fires_near_any_marker"] = matched
    out["tp_rate"] = round(matched / len(fire_ts), 3) if fire_ts else None
    out["marker_counts"] = {k: len(v) for k, v in markers.items()}
    return out


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> None:
    print("=" * 78)
    print("PREDICTIVE EYES (B0/B0.1) -- OFFLINE REPLAY OVER REAL CORPUS")
    print("READ-ONLY. No daemon, no live store touched.")
    print("=" * 78)

    snaps = load_state_snapshots()
    traces = load_jsonl(META / "decision_traces.jsonl")
    markers = load_anomaly_markers()
    error_lookup = build_error_lookup(traces)
    action_join = build_action_join(traces)

    span_lo = snaps[0]["timestamp"]
    span_hi = snaps[-1]["timestamp"]
    mode_dist = Counter(s.get("mode") for s in snaps)
    print(f"\nCorpus: {len(snaps)} state_snapshots, "
          f"span {(span_hi-span_lo)/3600:.1f}h")
    print(f"  mode distribution: {dict(mode_dist)}")
    print(f"  decision_traces: {len(traces)} rows; "
          f"failures (success=False): {sum(1 for t in traces if t.get('success') is False)}")
    print(f"  independent anomaly markers: "
          f"{ {k: len(v) for k, v in markers.items()} }")

    # nomic availability
    em = EmbeddingModel()
    nomic_ok = em.is_available()
    print(f"  nomic-embed-text available: {nomic_ok}")
    nomic_embed = em.embed if nomic_ok else make_hash_embed()
    hash_embed = make_hash_embed()

    runs = []
    runs.append(run_replay(snaps, error_lookup, action_join, nomic_embed,
                           global_floor=200, action_floor=20,
                           label="A: live-faithful (nomic, floor 200/20)"))
    runs.append(run_replay(snaps, error_lookup, action_join, nomic_embed,
                           global_floor=50, action_floor=20,
                           label="B: lowered-floor (nomic, floor 50/20)"))
    runs.append(run_replay(snaps, error_lookup, action_join, hash_embed,
                           global_floor=50, action_floor=20,
                           label="C: hash-embed control (floor 50/20)"))

    for run in runs:
        print("\n" + "-" * 78)
        print(run["label"])
        print("-" * 78)
        c = run["counts"]
        print(f"  scorable: {c['total_snapshots']} total "
              f"- {c['skipped_sleep_reduced']} sleep/reduced skipped "
              f"- {c['cold_start']} cold = {c['scored_ticks']} scored ticks")
        print(f"  ticks with a real action label (join <= {JOIN_WINDOW_SEC:.0f}s): "
              f"{c['ticks_with_action_label']}   empty-embed ticks: {c['empty_embedding_ticks']}")
        w = run["warmup"]
        print(f"  WARM-UP: global_obs={w['global_obs']} vs floor={w['global_floor']} "
              f"-> warm={w['global_warm']}; scored-while-warm~{w['scored_after_warm']}")
        print(f"           action distributions seen: {w['action_distributions']}; "
              f"reaching floor (B0.1 eligible): {w['actions_reaching_floor'] or 'NONE -> B0.1 never runs'}")
        cv = run["channel_variance"]
        print(f"  CHANNEL VARIANCE:")
        print(f"    semantic: mean={cv['semantic_mean']} std={cv['semantic_std']} "
              f"max={cv['semantic_max']} distinct_texts={cv['semantic_distinct_texts']}")
        print(f"    numeric : mean={cv['numeric_mean']} std={cv['numeric_std']} "
              f"max={cv['numeric_max']}")
        print(f"  FIRES: {run['fire_count']}")
        if run["fires"]:
            srcs = Counter(f["source"] for f in run["fires"])
            print(f"    by source: {dict(srcs)}")
        fano = fano_factor(run["scored_ts"] and [f["timestamp"] for f in run["fires"]] or [],
                           span_lo, span_hi)
        if fano:
            print(f"  CLUSTERING (headline): {fano}")
            verdict = ("CLUSTERED (signal)" if fano["fano_factor"] > 1.5
                       else "UNIFORM/Poisson (noise)" if fano["fano_factor"] < 1.3
                       else "borderline")
            print(f"    -> {verdict}  [Fano 1.0 = random/noise, >>1 = clustered]")
        else:
            print(f"  CLUSTERING: n/a (too few/no fires)")
        coin = coincidence([f["timestamp"] for f in run["fires"]], markers)
        print(f"  COINCIDENCE w/ independent markers (SECONDARY, +/-600s): "
              f"tp_rate={coin['tp_rate']} ({coin['fires_near_any_marker']}/{coin['fires']})")

    # real-vs-hash: is the semantic channel inert?
    print("\n" + "=" * 78)
    print("SEMANTIC CHANNEL LIVENESS (run B nomic vs run C hash)")
    print("=" * 78)
    b, hsh = runs[1], runs[2]
    print(f"  nomic semantic std: {b['channel_variance']['semantic_std']}  "
          f"distinct_texts: {b['channel_variance']['semantic_distinct_texts']}")
    print(f"  hash  semantic std: {hsh['channel_variance']['semantic_std']}")
    print(f"  numeric std (both ~identical): nomic={b['channel_variance']['numeric_std']} "
          f"hash={hsh['channel_variance']['numeric_std']}")
    fires_b = set(round(f["timestamp"], 1) for f in b["fires"])
    fires_c = set(round(f["timestamp"], 1) for f in hsh["fires"])
    inter = len(fires_b & fires_c)
    union = len(fires_b | fires_c) or 1
    print(f"  fire-set overlap nomic vs hash: {inter}/{union} "
          f"(Jaccard {inter/union:.2f})")
    print("  NOTE: high overlap here means NUMERIC dominance, NOT a healthy "
          "semantic channel.")

    # dump full results for auditing
    out = Path("/tmp/predictive_replay_results.json")
    dump = {r["label"]: {k: v for k, v in r.items()
                         if k not in ("scored_ts", "sem_series", "num_series")}
            for r in runs}
    out.write_text(json.dumps(dump, indent=2))
    print(f"\nFull machine-readable results -> {out}")


if __name__ == "__main__":
    main()
