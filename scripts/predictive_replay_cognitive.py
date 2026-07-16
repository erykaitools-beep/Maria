#!/usr/bin/env python
"""Re-pointed predictive eye: watch what Maria DOES/THINKS, not her vitals.

READ-ONLY offline experiment. The first replay (predictive_replay.py) opened
B0 on the homeostasis vitals stream (cpu/ram/mode/health) and found it inert
-- but the stream-richness sweep (workflow wf_12b44525) showed that flatness
is stream-specific: the real surprise-worthy structure lives in
decision_traces (the cognitive cycle), with a standout 06-09 failure storm,
and exam fails as non-circular ground truth.

This script re-points the eye: it builds StateSnapshots from the cognitive
fields (action_type, result_summary, goal, k7_decision) + a rolling
failure/block numeric channel, then drives the REAL surprise math
(EmbeddingModel.cosine_similarity, _aligned_numeric_distance, the real
ThresholdCalibrator + ActionBaseline, the real _maybe_emit logic) over all
2843 decision_traces. It then validates against ground truth we ALREADY have:

  - does it fire on / around the 06-09 failure storm?
  - does it stay QUIET during idle no_goals stretches (low false-positive)?
  - does B0.1 (per-action z-score) actually warm here (unlike the vitals run)?
  - permutation test: are fires concentrated near failures MORE than chance?

No production code touched; StateSnapshot is constructed directly with custom
fields, and the emit decision mirrors surprise_scorer._maybe_emit exactly.
"""

from __future__ import annotations

import bisect
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path("/home/maria/maria")
META = ROOT / "meta_data"
MEM = ROOT / "memory"
sys.path.insert(0, str(ROOT))

from agent_core.predictive.state_snapshot import StateSnapshot  # noqa: E402
from agent_core.predictive.threshold_calibrator import ThresholdCalibrator  # noqa: E402
from agent_core.predictive.action_baseline import ActionBaseline  # noqa: E402
from agent_core.predictive.surprise_scorer import _aligned_numeric_distance  # noqa: E402
from agent_core.semantic.embedding_model import EmbeddingModel  # noqa: E402

PERCENTILE = 95.0
SIGMA = 2.5
GLOBAL_FLOOR = 200
ACTION_FLOOR = 20
WIN = 3600.0  # rolling window for failure/block density


def load(p: Path) -> List[dict]:
    return [json.loads(l) for l in open(p) if l.strip()]


def build_semantic(tr: dict) -> str:
    # NON-CIRCULAR: deliberately EXCLUDE k7_decision -- 'k7=block' co-occurs
    # with the 33 k7-block failures and would leak the label into the eye.
    # Watch only the cognitive content (what was done / about what).
    lines = []
    at = tr.get("action_type") or ""
    if at:
        lines.append(f"action={at}")
    rs = (tr.get("result_summary") or "")[:120]
    if rs:
        lines.append(f"result={rs}")
    gd = (tr.get("goal_description") or "")[:120]
    if gd:
        lines.append(f"goal={gd}")
    return "\n".join(lines) if lines else "idle"


def main() -> None:
    print("=" * 78)
    print("RE-POINTED EYE -- B0 over decision_traces (cognitive cycle)")
    print("READ-ONLY. No daemon, no production code changed.")
    print("=" * 78)

    traces = load(META / "decision_traces.jsonl")
    traces.sort(key=lambda t: t.get("started_at") or t.get("finished_at") or 0)

    # ground truth -- GENUINE TASK FAILURES only (success==False AND NOT a
    # k7-block). k7-blocks are excluded because 'k7=block' would otherwise
    # be both a feature and the label. These are the real learn/exam fails
    # (the 06-09 storm), detectable only if the cognitive state is unusual.
    fail_ts = sorted(t.get("started_at") or t.get("finished_at")
                     for t in traces
                     if t.get("success") is False and t.get("k7_decision") != "block")
    block_ts = sorted(t.get("started_at") or t.get("finished_at")
                      for t in traces if t.get("k7_decision") == "block")

    # exam fails (truly independent stream -- ISO ts + string score).
    import datetime
    def _iso(ts: str) -> Optional[float]:
        try:
            return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None
    exam_fail_ts: List[float] = []
    exam_indep_fail_ts: List[float] = []
    try:
        exams = load(MEM / "exam_results.jsonl")
        for e in exams:
            raw = e.get("score")
            try:
                score = float(raw)
            except (TypeError, ValueError):
                continue
            ts = _iso(e.get("timestamp", "")) if isinstance(e.get("timestamp"), str) else e.get("timestamp")
            if ts is None:
                continue
            if score < 0.6:
                exam_fail_ts.append(ts)
                if e.get("grader_independent"):
                    exam_indep_fail_ts.append(ts)
    except Exception as ex:
        print(f"  (exam_results unreadable: {ex})")
    win_lo = traces[0].get("started_at"); win_hi = traces[-1].get("started_at")
    exam_in_window = [t for t in exam_fail_ts if win_lo <= t <= win_hi]

    def rolling(ts_list: List[float], now: float) -> float:
        lo = now - WIN
        i = bisect.bisect_left(ts_list, lo)
        j = bisect.bisect_right(ts_list, now)
        return float(j - i)

    em = EmbeddingModel()
    print(f"  nomic available: {em.is_available()}")
    print(f"  traces: {len(traces)} over "
          f"{(traces[-1]['started_at']-traces[0]['started_at'])/86400:.1f}d")
    print(f"  ground truth: {len(fail_ts)} genuine task-failures (non-block), "
          f"{len(block_ts)} k7-blocks (excluded), "
          f"{len(exam_fail_ts)} exam-fails total / {len(exam_in_window)} in 7d window "
          f"({len(exam_indep_fail_ts)} independent-graded)")

    cal = ThresholdCalibrator(min_samples_global=GLOBAL_FLOOR, min_samples_action=ACTION_FLOOR)
    ab = ActionBaseline(cal)

    prev: Optional[StateSnapshot] = None
    prev_emb: Optional[List[float]] = None

    fires: List[dict] = []
    sem_series: List[float] = []
    num_series: List[float] = []
    scored = 0
    n_idle = 0
    fire_on_idle = 0
    fire_on_fail = 0
    b01_eligible_ticks = 0

    def is_idle(tr: dict) -> bool:
        return not (tr.get("action_type") or "") and (tr.get("result_summary") == "no_goals")

    for tr in traces:
        ts = tr.get("started_at") or tr.get("finished_at")
        if ts is None:
            continue
        idle = is_idle(tr)
        action = tr.get("action_type") or ""

        # NON-CIRCULAR numeric channel: pure cognitive-effort signals, NONE
        # derived from the success/block label. A heavy reasoning episode
        # (high dur / many llm calls / high latency) is unusual on its own;
        # if failures happen to ride such states, that is genuine detection.
        numeric = {
            "goal_active": 1.0 if tr.get("goal_id") else 0.0,
            "dur": min((tr.get("duration_ms") or 0) / 120000.0, 1.0),
            "llm": min((tr.get("total_llm_calls") or 0) / 5.0, 1.0),
            "latency": min((tr.get("total_llm_latency_ms") or 0) / 120000.0, 1.0),
        }
        snap = StateSnapshot(
            timestamp=ts,
            semantic_text=build_semantic(tr),
            numeric_features=numeric,
            mode=tr.get("mode"),
            last_action_type=action or None,
            health_score=tr.get("health_score"),
        )
        emb = em.embed(snap.semantic_text)

        if prev is None:
            prev, prev_emb = snap, emb
            continue

        if emb and prev_emb and len(emb) == len(prev_emb):
            sem = 1.0 - EmbeddingModel.cosine_similarity(emb, prev_emb)
        else:
            sem = 0.0
        num = _aligned_numeric_distance(snap, prev)
        sem_series.append(sem)
        num_series.append(num)
        scored += 1
        if idle:
            n_idle += 1

        # feed calibrator (mirror scorer order)
        cal.add(sem, "global:semantic", timestamp=ts)
        cal.add(num, "global:numeric", timestamp=ts)
        if action:
            ab.add_observation(action, semantic_distance=sem, numeric_distance=num, timestamp=ts)

        fired = False
        source = None
        # B0.1 first
        if action:
            z = ab.get_z_scores(action, semantic_distance=sem, numeric_distance=num)
            if z is not None:
                b01_eligible_ticks += 1
                z_sem, z_num = z
                if abs(z_sem) > SIGMA or abs(z_num) > SIGMA:
                    fired, source = True, "b0_1_action"
                # B0.1 warm but below threshold -> NO fallback (matches scorer)
            else:
                fired, source = _b0_global(cal, sem, num)
        else:
            fired, source = _b0_global(cal, sem, num)

        if fired:
            near_fail = any(abs(ts - f) <= 600 for f in fail_ts)
            fires.append({"ts": ts, "source": source, "action": action,
                          "sem": round(sem, 4), "num": round(num, 4),
                          "idle": idle, "near_fail": near_fail})
            if idle:
                fire_on_idle += 1
            if near_fail:
                fire_on_fail += 1

        prev, prev_emb = snap, emb

    # ---- report --------------------------------------------------------
    print("\n" + "-" * 78)
    print("RESULTS")
    print("-" * 78)
    print(f"  scored ticks: {scored}  (idle no_goals: {n_idle} = {100*n_idle/scored:.0f}%)")
    print(f"  B0.1 eligible ticks (action baseline warm): {b01_eligible_ticks} "
          f"{'-> B0.1 ALIVE' if b01_eligible_ticks else '-> B0.1 dead'}")
    print(f"  CHANNEL VARIANCE:")
    print(f"    semantic: std={statistics.pstdev(sem_series):.4f} "
          f"max={max(sem_series):.4f} mean={statistics.fmean(sem_series):.4f}")
    print(f"    numeric : std={statistics.pstdev(num_series):.4f} "
          f"max={max(num_series):.4f} mean={statistics.fmean(num_series):.4f}")
    print(f"  FIRES: {len(fires)}  by source: {dict(Counter(f['source'] for f in fires))}")

    # discrimination: fire-rate on failures vs idle vs normal
    n_fail_traces = len(fail_ts)
    recall_fail = fire_on_fail
    fp_idle_rate = fire_on_idle / n_idle if n_idle else 0
    normal_ticks = scored - n_idle
    fires_normal = len(fires) - fire_on_idle
    fr_normal = fires_normal / normal_ticks if normal_ticks else 0
    print(f"\n  DISCRIMINATION (the headline):")
    print(f"    fires near a failure (+/-600s): {fire_on_fail}/{len(fires)} fires")
    print(f"    false-positive on idle: {fire_on_idle}/{n_idle} idle ticks "
          f"= {fp_idle_rate*100:.2f}%")
    print(f"    fire-rate on active (non-idle) ticks: {fires_normal}/{normal_ticks} "
          f"= {fr_normal*100:.2f}%")
    print(f"    -> ratio active:idle fire-rate = "
          f"{(fr_normal/fp_idle_rate) if fp_idle_rate else float('inf'):.1f}x")

    # storm 06-09 concentration
    fires_in_storm = sum(1 for f in fires
                         if _in_storm(f["ts"], traces))
    print(f"\n  06-09 FAILURE STORM: fires inside the storm window: {fires_in_storm}")

    # permutation: are fires near failures MORE than chance among scored ticks?
    scored_ts = [t.get("started_at") for t in traces if (t.get("started_at"))][1:]
    obs_near = fire_on_fail
    null = _perm_null(scored_ts, fail_ts, len(fires))
    p = sum(1 for x in null if x >= obs_near) / len(null)
    print(f"\n  PERMUTATION (fires-near-failure vs random placement among ticks):")
    print(f"    observed near-fail fires: {obs_near}; null median: {statistics.median(null):.1f}; "
          f"p95: {sorted(null)[int(0.95*len(null))]:.1f}")
    print(f"    p-value (obs >= null): {p:.4f}  "
          f"-> {'SIGNAL (fires track task-failures beyond chance)' if p < 0.05 else 'NO extra signal'}")

    # independent exam fails in window (gold non-circular, but sparse)
    if exam_in_window:
        fire_ts_list = [f["ts"] for f in fires]
        near_exam = sum(1 for ef in exam_in_window
                        if any(abs(ef - ft) <= 1800 for ft in fire_ts_list))
        print(f"\n  EXAM-FAIL coincidence (gold, +/-30min): "
              f"{near_exam}/{len(exam_in_window)} in-window exam fails had a fire nearby")
    else:
        print(f"\n  EXAM-FAIL coincidence: 0 exam fails fall in the 7d trace window "
              f"(exams span back to 2025-12; thin overlap -- not usable here)")

    out = Path("/tmp/predictive_cognitive_results.json")
    out.write_text(json.dumps({"fires": fires, "scored": scored, "n_idle": n_idle,
                               "b01_eligible": b01_eligible_ticks,
                               "discrimination": {"recall_fail": recall_fail,
                                                  "fp_idle_rate": fp_idle_rate,
                                                  "fr_normal": fr_normal},
                               "perm_p": p}, indent=2))
    print(f"\nFull results -> {out}")


def _b0_global(cal, sem, num) -> Tuple[bool, Optional[str]]:
    st = cal.get_percentile_threshold("global:semantic", percentile=PERCENTILE)
    nt = cal.get_percentile_threshold("global:numeric", percentile=PERCENTILE)
    if st is None or nt is None:
        return False, None
    if sem > st or num > nt:
        return True, "b0_global"
    return False, None


def _in_storm(ts: float, traces: List[dict]) -> bool:
    # storm = the 6h windows on 2026-06-09 with the failure cluster
    import datetime
    dt = datetime.datetime.utcfromtimestamp(ts)
    return dt.strftime("%Y-%m-%d") == "2026-06-09" and 4 <= dt.hour <= 14


def _perm_null(scored_ts: List[float], fail_ts: List[float], k: int, iters: int = 2000):
    # deterministic LCG, place k fires randomly among scored ticks, count near-fail
    x = 12345
    def rnd(n):
        nonlocal x
        x = (1103515245 * x + 12345) & 0x7fffffff
        return x % n
    fset = sorted(fail_ts)
    out = []
    N = len(scored_ts)
    for _ in range(iters):
        chosen = set()
        while len(chosen) < min(k, N):
            chosen.add(rnd(N))
        near = 0
        for idx in chosen:
            t = scored_ts[idx]
            i = bisect.bisect_left(fset, t - 600)
            j = bisect.bisect_right(fset, t + 600)
            if j > i:
                near += 1
        out.append(near)
    return out


if __name__ == "__main__":
    main()
