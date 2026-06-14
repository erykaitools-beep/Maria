#!/usr/bin/env python
"""
Measure impact of D1 fix — learning-window guard at plan creation.

Compares learn-family planner decisions before and after the D1 deploy
(2026-04-21 16:45 UTC, commit df28a52). Pre-D1 baseline was 848/889
learn decisions failing with reason=outside_learning_window in 72h
(95% fail rate, observed during glm-5.1 test).

D1 moves the guard from the executor to plan creation, so learn-family
actions outside the window should either be filtered at GoalSelector
(meta goals become infeasible) or rewritten to NOOP by
PlannerCore._enforce_learning_window. Both paths should yield:
    - 0 (or near-0) failures with reason=outside_learning_window
    - NOOPs with action_params.reason=outside_learning_window as the new
      "soft block" signal

Usage:
    python scripts/measure_d1_impact.py
    python scripts/measure_d1_impact.py --since 1776789927
    python scripts/measure_d1_impact.py --window-hours 24
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DECISIONS_PATH = PROJECT_ROOT / "meta_data" / "planner_decisions.jsonl"

# D1 deploy timestamp (2026-04-21 16:45:27 UTC)
D1_DEPLOY_TS = 1776789927

# Baseline from pre-D1 72h window (see project_glm51_architecture_findings.md).
# Correction 2026-04-21: earlier narrative attributed all 848 learn fails to
# outside_learning_window. Re-scanning result fields showed only 54 fails
# had that reason; 791 were unproductive strategies (success=false,
# chunks=0, exams=0, no reason). D1 addresses the 54, not the 791.
BASELINE_WINDOW_HOURS = 72
BASELINE_LEARN_TOTAL = 889
BASELINE_LEARN_FAILS = 848
BASELINE_FAIL_RATE = BASELINE_LEARN_FAILS / BASELINE_LEARN_TOTAL  # 0.953
BASELINE_OUTSIDE_WINDOW_FAILS = 54
BASELINE_UNPRODUCTIVE_FAILS = 791

# Threshold for calling the fix "effective"
TARGET_FAIL_RATE = 0.10
WARNING_FAIL_RATE = 0.20


def scan_decisions(since_ts: float, window_hours: float | None = None):
    """Aggregate planner decisions from `since_ts` onwards.

    Returns dict with counts and samples ready for reporting.
    """
    end_ts = since_ts + window_hours * 3600 if window_hours else None
    stats = {
        "total": 0,
        "by_action": Counter(),
        "by_status": Counter(),
        "learn_completed": 0,
        "learn_failed_total": 0,
        "learn_failed_outside_window": 0,
        # Teacher ran a strategy but produced nothing (chunks=0, exams=0).
        # Observed during 2026-04-21 deep analysis: 791 such cases in 72h,
        # far more than the 54 "outside_learning_window" fails. D1 did not
        # address these — they trace to _execute_strategy returning ~77ms
        # with nothing productive, which handlers.py correctly reports as
        # success=False (chunks_learned>0 gate).
        "learn_failed_unproductive": 0,
        "learn_failed_other": 0,
        "noop_redirects_outside_window": 0,
        "first_ts": None,
        "last_ts": None,
    }

    if not DECISIONS_PATH.exists():
        return stats

    learn_family = {"learn", "exam", "review", "fetch", "ask_expert"}

    with open(DECISIONS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = e.get("timestamp") or 0
            if ts < since_ts:
                continue
            if end_ts is not None and ts > end_ts:
                continue

            stats["total"] += 1
            stats["first_ts"] = min(stats["first_ts"] or ts, ts)
            stats["last_ts"] = max(stats["last_ts"] or 0, ts)

            action = e.get("action_type", "?")
            status = e.get("status", "?")
            stats["by_action"][action] += 1
            stats["by_status"][status] += 1

            result = e.get("result") or {}
            fail_reason = result.get("reason", "")
            params = e.get("action_params") or {}
            params_reason = params.get("reason", "")

            if action in learn_family:
                if status == "completed":
                    stats["learn_completed"] += 1
                elif status == "failed":
                    stats["learn_failed_total"] += 1
                    if fail_reason == "outside_learning_window":
                        stats["learn_failed_outside_window"] += 1
                    elif (
                        result.get("success") is False
                        and result.get("chunks_learned", 0) == 0
                        and result.get("exams_run", 0) == 0
                        and not fail_reason
                    ):
                        stats["learn_failed_unproductive"] += 1
                    else:
                        stats["learn_failed_other"] += 1

            if action == "noop" and params_reason == "outside_learning_window":
                stats["noop_redirects_outside_window"] += 1

    return stats


def format_ts(ts: float | None) -> str:
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S UTC")


def report(since_ts: float, window_hours: float | None, stats: dict) -> int:
    """Print a human-readable report. Returns exit code (0=pass, 1=warn, 2=fail)."""
    window_label = (
        f"{window_hours}h window from" if window_hours else "since"
    )
    print("=" * 68)
    print(f"D1 impact measurement — {window_label} {format_ts(since_ts)}")
    print("=" * 68)

    if stats["total"] == 0:
        print("No planner decisions in the requested window yet.")
        print("Wait for Maria to run a few planning cycles, then re-measure.")
        return 0

    span = (stats["last_ts"] or 0) - (stats["first_ts"] or 0)
    print(f"decisions observed: {stats['total']} "
          f"(span {span/3600:.1f}h, first {format_ts(stats['first_ts'])}, "
          f"last {format_ts(stats['last_ts'])})")
    print()

    print("action breakdown:")
    for act, n in stats["by_action"].most_common():
        print(f"  {n:>5}  {act}")
    print()

    print("status breakdown:")
    for st, n in stats["by_status"].most_common():
        print(f"  {n:>5}  {st}")
    print()

    learn_total = (
        stats["learn_completed"] + stats["learn_failed_total"]
    )
    if learn_total > 0:
        fail_rate = stats["learn_failed_total"] / learn_total
    else:
        fail_rate = 0.0
    outside_rate = (
        stats["learn_failed_outside_window"] / learn_total
        if learn_total else 0.0
    )

    print("learn-family decisions:")
    print(f"  completed:                 {stats['learn_completed']}")
    print(f"  failed (total):            {stats['learn_failed_total']}")
    print(f"    - outside_window:        {stats['learn_failed_outside_window']}")
    print(f"    - unproductive strategy: {stats['learn_failed_unproductive']}")
    print(f"      (teacher ran but 0 chunks/0 exams — D1.5 territory)")
    print(f"    - other reasons:         {stats['learn_failed_other']}")
    print(f"  NOOP redirects (D1 guard): {stats['noop_redirects_outside_window']}")
    print()

    print("comparison vs pre-D1 baseline (72h):")
    print(f"  baseline:  {BASELINE_LEARN_FAILS}/{BASELINE_LEARN_TOTAL} "
          f"learn fails = {BASELINE_FAIL_RATE:.1%}")
    print(f"    - outside_window:   {BASELINE_OUTSIDE_WINDOW_FAILS}")
    print(f"    - unproductive:     {BASELINE_UNPRODUCTIVE_FAILS}")
    if learn_total > 0:
        print(f"  current:   {stats['learn_failed_total']}/{learn_total} "
              f"learn fails = {fail_rate:.1%}")
        print(f"    - outside_window:   {stats['learn_failed_outside_window']}")
        print(f"    - unproductive:     {stats['learn_failed_unproductive']}")
    else:
        print("  current:   no learn-family decisions in window yet")
    print()

    print("D1 verdict (outside_window guard only):")
    if learn_total == 0:
        print("  INCONCLUSIVE — no learn-family decisions yet.")
        print("  Re-run once Maria has gone through a learning window.")
        return 0
    if outside_rate < TARGET_FAIL_RATE:
        print(f"  PASS — outside_window fail rate {outside_rate:.1%} "
              f"< target {TARGET_FAIL_RATE:.0%}. D1 effective.")
        if stats["noop_redirects_outside_window"] > 0:
            print(f"  ({stats['noop_redirects_outside_window']} NOOP "
                  f"redirects confirm the new guard is firing.)")
        rc = 0
    elif outside_rate < WARNING_FAIL_RATE:
        print(f"  PARTIAL — outside_window fail rate {outside_rate:.1%} "
              f"between target {TARGET_FAIL_RATE:.0%} and "
              f"warning {WARNING_FAIL_RATE:.0%}. Investigate residual paths.")
        rc = 1
    else:
        print(f"  FAIL — outside_window fail rate {outside_rate:.1%} "
              f">= warning {WARNING_FAIL_RATE:.0%}. Third leak present, "
              f"debug before D2.")
        rc = 2

    # Secondary signal: learning healthiness. D1 doesn't fix unproductive
    # strategies — that's D1.5 territory. Reporting so we don't declare
    # victory prematurely.
    unproductive = stats["learn_failed_unproductive"]
    if unproductive > 0:
        unproductive_rate = unproductive / learn_total
        print()
        print("learning health (separate from D1):")
        print(f"  unproductive strategies: {unproductive} "
              f"({unproductive_rate:.1%} of learn-family). "
              f"Teacher picks a strategy but produces 0 chunks / 0 exams "
              f"in ~77ms. Needs diagnosis before D2 (see D1.5 in "
              f"project_glm51_architecture_findings.md).")
    return rc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since", type=float, default=D1_DEPLOY_TS,
        help=f"Unix timestamp to measure from (default: D1 deploy "
             f"{format_ts(D1_DEPLOY_TS)})",
    )
    parser.add_argument(
        "--window-hours", type=float, default=None,
        help="Optional window length in hours (default: until now)",
    )
    args = parser.parse_args()

    stats = scan_decisions(args.since, args.window_hours)
    return report(args.since, args.window_hours, stats)


if __name__ == "__main__":
    sys.exit(main())
