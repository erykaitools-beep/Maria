#!/usr/bin/env python3
"""D4 verification — mode-aware learning success criterion (2026-04-26).

Computes the three signals D4 promised and prints a single-page report
with a PASS / PARTIAL / FAIL verdict so the operator can decide the next
move after the 7d soak.

Reads three runtime files (no LLM, no Maria daemon needed):
- meta_data/mode_postmortems.jsonl    -- W1 recorder output
- meta_data/cognitive_bulletin.jsonl  -- W2 analyzer + W3 advisory channel
- meta_data/homeostasis_events.jsonl  -- mode_change events for fraction calc

Usage:
    python3 scripts/verify_d4.py [--window-days N] [--baseline 0.197]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "meta_data"

POSTMORTEM_PATH = META / "mode_postmortems.jsonl"
BULLETIN_PATH = META / "cognitive_bulletin.jsonl"
EVENTS_PATH = META / "homeostasis_events.jsonl"

# D4 success thresholds (matched to docs/D_BOARDS.md criterion).
DEFAULT_WINDOW_DAYS = 7
DEFAULT_BASELINE_FRACTION = 0.197  # 19.7% pre-D4 baseline (Eryk 2026-04-22)
TARGET_REDUCED_FRACTION = 0.10
TARGET_MODE_AWARE_ENTRIES = 3


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _within(records: List[Dict[str, Any]], cutoff: float, key: str = "timestamp") -> List[Dict[str, Any]]:
    return [r for r in records if r.get(key, 0) >= cutoff]


def reduced_fraction(events: List[Dict[str, Any]], window_sec: float) -> Tuple[float, Dict[str, float]]:
    """Estimate fraction of time spent in REDUCED over the window.

    Uses mode_change events with ``duration_in_prev_mode_sec``. The duration
    fields measure how long the *previous* mode was held, so we sum
    durations attributed to ``from_mode == "reduced"`` for transitions that
    happened inside the window.
    """
    cutoff = time.time() - window_sec
    by_mode_sec: Dict[str, float] = {"active": 0, "reduced": 0, "sleep": 0, "survival": 0}
    transitions = 0

    for ev in events:
        if ev.get("event_type") != "mode_change":
            continue
        ts = ev.get("timestamp", 0)
        if ts < cutoff:
            continue
        transitions += 1
        from_mode = ev.get("from_mode")
        dur = float(ev.get("duration_in_prev_mode_sec") or 0.0)
        if from_mode in by_mode_sec:
            by_mode_sec[from_mode] += dur

    total_attributed = sum(by_mode_sec.values())
    if total_attributed <= 0:
        return 0.0, {**by_mode_sec, "transitions": transitions, "total_attributed_sec": 0.0}

    fraction = by_mode_sec["reduced"] / total_attributed
    return fraction, {
        **by_mode_sec,
        "transitions": float(transitions),
        "total_attributed_sec": total_attributed,
    }


def postmortem_summary(records: List[Dict[str, Any]], window_sec: float) -> Dict[str, Any]:
    cutoff = time.time() - window_sec
    recent = [r for r in records if r.get("entry_ts", 0) >= cutoff]
    sigs = Counter(r.get("alerts_signature", "?") for r in recent)
    hours = Counter(r.get("hour_of_day_berlin", -1) for r in recent)
    actions = Counter(r.get("active_action_type") or "(none)" for r in recent)
    durations = [r.get("duration_sec", 0.0) for r in recent]
    avg_dur = (sum(durations) / len(durations)) if durations else 0.0
    return {
        "count": len(recent),
        "by_signature": sigs.most_common(),
        "by_hour": sorted(hours.items()),
        "by_action": actions.most_common(),
        "avg_duration_sec": avg_dur,
    }


def mode_aware_bulletin(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Count IMPROVEMENT entries with mode_aware=True. The bulletin file
    persists by appending — terminal entries (resolved) are kept too. We
    deduplicate by entry_id taking the latest record."""
    latest: Dict[str, Dict[str, Any]] = {}
    for entry in records:
        eid = entry.get("entry_id")
        if not eid:
            continue
        latest[eid] = entry  # last write wins -> matches BulletinStore MERGE semantics

    by_action: Counter = Counter()
    by_bucket: Counter = Counter()
    by_status: Counter = Counter()
    matching: List[Dict[str, Any]] = []

    for entry in latest.values():
        if entry.get("entry_type") != "improvement":
            continue
        meta = entry.get("metadata") or {}
        if not meta.get("mode_aware"):
            continue
        matching.append(entry)
        by_action[meta.get("action_hint") or "(any)"] += 1
        by_bucket[meta.get("hour_bucket") or "(unknown)"] += 1
        by_status[entry.get("status", "?")] += 1

    return {
        "count": len(matching),
        "by_action": by_action.most_common(),
        "by_bucket": by_bucket.most_common(),
        "by_status": by_status.most_common(),
        "examples": [
            {
                "entry_id": e.get("entry_id"),
                "topic": e.get("topic"),
                "summary": (e.get("summary") or "")[:100],
                "priority": e.get("priority"),
                "action_hint": (e.get("metadata") or {}).get("action_hint"),
                "abandon_count": (e.get("metadata") or {}).get("abandon_count"),
            }
            for e in matching[:5]
        ],
    }


def render(report: Dict[str, Any]) -> str:
    """Pretty-print the audit report. Stdout only — no file side effects."""

    rf = report["reduced_fraction"]
    rf_pct = rf["fraction"] * 100
    pm = report["postmortems"]
    bull = report["bulletin"]

    lines = [
        "=" * 72,
        f"  D4 verification — {report['window_days']}d window  (baseline {report['baseline_pct']:.1f}%)",
        "=" * 72,
        "",
        f"[1] REDUCED fraction: {rf_pct:.2f}%  (target <{TARGET_REDUCED_FRACTION*100:.0f}%, baseline {report['baseline_pct']:.1f}%)",
        f"    transitions={int(rf['transitions'])}  attributed={rf['total_attributed_sec']:.0f}s "
        f"({rf['total_attributed_sec']/3600:.1f}h)",
        f"    by_mode_sec: active={rf['active']:.0f}  reduced={rf['reduced']:.0f}  "
        f"sleep={rf['sleep']:.0f}  survival={rf['survival']:.0f}",
        "",
        f"[2] Mode post-mortems: {pm['count']} record(s)",
    ]
    if pm["count"]:
        lines.append(f"    avg dwell: {pm['avg_duration_sec']:.1f}s")
        lines.append("    by alerts_signature: " + ", ".join(f"{s}={n}" for s, n in pm["by_signature"][:6]))
        lines.append("    by action: " + ", ".join(f"{a}={n}" for a, n in pm["by_action"][:6]))
        if pm["by_hour"]:
            hour_str = ", ".join(f"h{h}={n}" for h, n in pm["by_hour"])
            lines.append(f"    by hour: {hour_str}")
    else:
        lines.append("    (none — Maria did not enter REDUCED in this window)")

    lines += [
        "",
        f"[3] Bulletin mode_aware IMPROVEMENT entries: {bull['count']} "
        f"(target >={TARGET_MODE_AWARE_ENTRIES})",
    ]
    if bull["count"]:
        lines.append("    by action_hint: " + ", ".join(f"{a}={n}" for a, n in bull["by_action"][:6]))
        lines.append("    by hour_bucket: " + ", ".join(f"{b}={n}" for b, n in bull["by_bucket"][:6]))
        lines.append("    by status: " + ", ".join(f"{s}={n}" for s, n in bull["by_status"][:6]))
        lines.append("    examples:")
        for ex in bull["examples"]:
            lines.append(
                f"      - {ex['entry_id']} [{ex['action_hint']}] "
                f"abandons={ex['abandon_count']} pri={ex['priority']:.2f}"
            )
            lines.append(f"        {ex['summary']}")
    else:
        lines.append("    (none — no patterns crossed the analyzer threshold)")

    # Verdict
    lines += [
        "",
        "-" * 72,
        f"VERDICT: {report['verdict']}",
        "-" * 72,
    ]
    for note in report["notes"]:
        lines.append(f"  - {note}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="D4 mode-aware verification")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument(
        "--baseline", type=float, default=DEFAULT_BASELINE_FRACTION,
        help="Pre-D4 REDUCED fraction baseline (default 0.197 = 19.7%%)",
    )
    args = parser.parse_args()

    window_sec = args.window_days * 86400.0

    events = _load_jsonl(EVENTS_PATH)
    postmortems = _load_jsonl(POSTMORTEM_PATH)
    bulletin = _load_jsonl(BULLETIN_PATH)

    rf_value, rf_breakdown = reduced_fraction(events, window_sec)
    rf_breakdown["fraction"] = rf_value
    pm_summary = postmortem_summary(postmortems, window_sec)
    bulletin_summary = mode_aware_bulletin(bulletin)

    notes: List[str] = []
    fraction_pass = rf_value < TARGET_REDUCED_FRACTION
    bulletin_pass = bulletin_summary["count"] >= TARGET_MODE_AWARE_ENTRIES
    has_data = rf_breakdown["transitions"] > 0 or pm_summary["count"] > 0 or bulletin_summary["count"] > 0

    if not has_data:
        verdict = "INCONCLUSIVE — no mode-related runtime signal in the window"
        notes.append("Restart Maria and re-run after she has produced REDUCED transitions.")
    elif fraction_pass and bulletin_pass:
        verdict = "PASS — both criteria met"
        notes.append(f"REDUCED dropped {(args.baseline - rf_value)*100:.1f}pp from baseline.")
        notes.append(f"Bulletin holds {bulletin_summary['count']} mode_aware entries (>= target).")
    elif fraction_pass:
        verdict = "PASS-A — REDUCED fraction below target (bulletin signal weak)"
        notes.append("Lack of bulletin entries may mean too few REDUCED episodes to cluster.")
    elif bulletin_pass:
        verdict = "PASS-B — bulletin entries posted; planner deferral has signal to act on"
        notes.append("REDUCED fraction not yet below 10%, but the corrective channel is active.")
    else:
        verdict = "FAIL / IN PROGRESS — neither criterion met yet"
        notes.append("Consider extending the window, raising threshold, or revisiting W2 clustering.")

    if rf_breakdown["transitions"] == 0:
        notes.append("No mode_change events in window — homeostasis_events.jsonl may have rotated.")
    if pm_summary["count"] == 0 and rf_breakdown["reduced"] > 0:
        notes.append("REDUCED time recorded but no post-mortems — recorder hook may not be wired.")

    report = {
        "window_days": args.window_days,
        "baseline_pct": args.baseline * 100,
        "reduced_fraction": rf_breakdown,
        "postmortems": pm_summary,
        "bulletin": bulletin_summary,
        "verdict": verdict,
        "notes": notes,
    }
    print(render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
