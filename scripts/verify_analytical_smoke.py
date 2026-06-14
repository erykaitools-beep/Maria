#!/usr/bin/env python3
"""ANALYTICAL classification smoke test (commit 6033de0, 2026-04-26).

After splitting K7's GUARDED tier into ANALYTICAL + GUARDED, READ-ONLY
self-reflection actions (self_analyze, creative, critique, validate)
should run in SLEEP/REDUCED instead of being blocked by
``rule_degraded_mode_restrict``. This script confirms — or refutes —
that the change took effect on the running daemon.

Reads (no daemon, no LLM):
- meta_data/decision_traces.jsonl   -- per-tick action records with mode + k7
- meta_data/homeostasis_events.jsonl -- mode_change events (locate restart)
- meta_data/cognitive_bulletin.jsonl -- new K12 advisory + K13 meta-goals

Usage:
    python3 scripts/verify_analytical_smoke.py [--since-minutes 60]

The default window is "since the most recent daemon restart" if a fresh
restart marker can be found, otherwise the last 60 minutes.
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

TRACES_PATH = META / "decision_traces.jsonl"
EVENTS_PATH = META / "homeostasis_events.jsonl"
BULLETIN_PATH = META / "cognitive_bulletin.jsonl"

# The four actions reclassified as ANALYTICAL (commit 6033de0).
ANALYTICAL_ACTIONS = ("self_analyze", "creative", "critique", "validate")
DEGRADED_MODES = ("sleep", "reduced")


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


def find_daemon_start_ts() -> Optional[float]:
    """Read the running maria.py process start time from /proc.

    More accurate than mode_change heuristics — works even when the
    daemon just restarted and has not yet emitted any transition.
    Returns None if no maria.py process is running.
    """
    proc_root = Path("/proc")
    try:
        boot_time = 0.0
        with open("/proc/stat", "r") as f:
            for line in f:
                if line.startswith("btime"):
                    boot_time = float(line.split()[1])
                    break
        if not boot_time:
            return None
        clk_tck = 100.0  # POSIX default; CONFIG_HZ=100 on this kernel

        for pid_dir in proc_root.iterdir():
            if not pid_dir.name.isdigit():
                continue
            try:
                cmdline = (pid_dir / "cmdline").read_bytes().replace(b"\x00", b" ")
            except (FileNotFoundError, PermissionError):
                continue
            if b"maria.py" not in cmdline:
                continue
            try:
                stat = (pid_dir / "stat").read_text()
            except (FileNotFoundError, PermissionError):
                continue
            # field 22 (0-indexed 21) = starttime in clock ticks since boot.
            # comm field is in parens and may contain spaces — split after ')'.
            tail = stat[stat.rindex(")") + 2:].split()
            starttime_ticks = float(tail[19])  # field 22 minus 3 (we sliced past pid+comm)
            return boot_time + starttime_ticks / clk_tck
    except Exception:
        return None
    return None


def find_restart_ts(events: List[Dict[str, Any]]) -> Optional[float]:
    """Fallback restart detector via mode_change events. Used only when
    /proc lookup fails (e.g. running off-host with copied jsonl files).

    Looks for a gap > 5min between consecutive mode_changes; otherwise
    returns None so the caller can fall back to a fixed time window.
    Importantly: never returns an old timestamp from before the gap —
    if the most recent transition is itself stale (> 30min), there is
    nothing useful to anchor on.
    """
    mc = sorted(
        (e for e in events if e.get("event_type") == "mode_change"),
        key=lambda e: e.get("timestamp", 0),
    )
    if not mc:
        return None
    for i in range(len(mc) - 1, 0, -1):
        gap = mc[i].get("timestamp", 0) - mc[i - 1].get("timestamp", 0)
        if gap > 300:
            return mc[i].get("timestamp")
    most_recent = mc[-1].get("timestamp", 0)
    if time.time() - most_recent > 1800:
        return None
    return mc[0].get("timestamp")


def is_k7_blocked(trace: Dict[str, Any]) -> bool:
    """A trace is "K7 blocked" when k7_decision != allow OR the result
    summary explicitly mentions blocking. We accept either signal — the
    pre-fix runs showed both depending on which path captured first."""
    decision = (trace.get("k7_decision") or "").lower()
    if decision and decision not in ("allow", ""):
        return True
    summary = (trace.get("result_summary") or "").lower()
    return "k7 blocked" in summary or "blocked: block" in summary


def trace_summary(
    traces: List[Dict[str, Any]], cutoff: float
) -> Dict[str, Any]:
    recent = [t for t in traces if t.get("started_at", 0) >= cutoff]
    analytical = [
        t for t in recent if t.get("action_type") in ANALYTICAL_ACTIONS
    ]

    # Sleep/reduced bucket
    deg = [t for t in analytical if t.get("mode") in DEGRADED_MODES]
    deg_blocked = [t for t in deg if is_k7_blocked(t)]
    deg_success = [t for t in deg if t.get("success") and not is_k7_blocked(t)]

    # Active bucket (regression check — must still work)
    act = [t for t in analytical if t.get("mode") == "active"]
    act_success = [t for t in act if t.get("success") and not is_k7_blocked(t)]

    by_action_mode: Counter = Counter()
    for t in analytical:
        key = f"{t.get('action_type')}/{t.get('mode')}"
        by_action_mode[key] += 1

    return {
        "total_traces": len(recent),
        "analytical_total": len(analytical),
        "degraded": {
            "total": len(deg),
            "blocked": len(deg_blocked),
            "success": len(deg_success),
            "examples": [
                {
                    "action": t.get("action_type"),
                    "mode": t.get("mode"),
                    "success": t.get("success"),
                    "summary": (t.get("result_summary") or "")[:80],
                    "k7_decision": t.get("k7_decision"),
                    "started_at": t.get("started_at"),
                }
                for t in deg[:5]
            ],
        },
        "active": {
            "total": len(act),
            "success": len(act_success),
        },
        "by_action_mode": by_action_mode.most_common(),
    }


def mode_timeline(events: List[Dict[str, Any]], cutoff: float) -> Dict[str, Any]:
    transitions = []
    for ev in events:
        if ev.get("event_type") != "mode_change":
            continue
        ts = ev.get("timestamp", 0)
        if ts < cutoff:
            continue
        transitions.append(
            {
                "ts": ts,
                "from": ev.get("from_mode"),
                "to": ev.get("to_mode"),
                "trigger": (ev.get("trigger") or {}).get("constraint", "?"),
            }
        )
    in_degraded = any(t["to"] in DEGRADED_MODES for t in transitions)
    return {"transitions": transitions, "entered_degraded": in_degraded}


def bulletin_changes(records: List[Dict[str, Any]], cutoff: float) -> Dict[str, Any]:
    fresh = [r for r in records if r.get("created_at", 0) >= cutoff]
    by_reason: Counter = Counter()
    by_requested: Counter = Counter()
    for r in fresh:
        by_reason[r.get("reason_code") or "?"] += 1
        by_requested[r.get("requested_by") or "?"] += 1
    return {
        "new_entries": len(fresh),
        "by_reason": by_reason.most_common(5),
        "by_requested_by": by_requested.most_common(5),
    }


def render(report: Dict[str, Any]) -> str:
    cutoff = report["cutoff_ts"]
    cutoff_iso = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(cutoff))
    age_min = (time.time() - cutoff) / 60.0
    ts = report["traces"]
    deg = ts["degraded"]
    mt = report["modes"]
    bull = report["bulletin"]

    lines = [
        "=" * 72,
        f"  ANALYTICAL smoke (commit 6033de0)  window since {cutoff_iso}  ({age_min:.0f}min)",
        "=" * 72,
        "",
        f"[1] Mode timeline: {len(mt['transitions'])} transition(s); "
        f"entered SLEEP/REDUCED = {mt['entered_degraded']}",
    ]
    for t in mt["transitions"][:8]:
        when = time.strftime("%H:%M:%S", time.gmtime(t["ts"]))
        lines.append(f"    {when}Z  {t['from']:>8} -> {t['to']:<8}  ({t['trigger']})")
    if len(mt["transitions"]) > 8:
        lines.append(f"    ... +{len(mt['transitions']) - 8} more")

    lines += [
        "",
        f"[2] ANALYTICAL action attempts in window: "
        f"{ts['analytical_total']} / {ts['total_traces']} total traces",
    ]
    if ts["by_action_mode"]:
        lines.append("    by action/mode:")
        for k, n in ts["by_action_mode"]:
            lines.append(f"      {n:3d}  {k}")
    else:
        lines.append("    (no ANALYTICAL traces yet — cooldowns may not have fired)")

    lines += [
        "",
        f"[3] In SLEEP/REDUCED: total={deg['total']}  "
        f"K7-blocked={deg['blocked']}  success={deg['success']}",
        f"    (active mode: total={ts['active']['total']}  success={ts['active']['success']})",
    ]
    for ex in deg["examples"]:
        when = time.strftime("%H:%M:%S", time.gmtime(ex["started_at"] or 0))
        lines.append(
            f"      {when}Z  {ex['action']}/{ex['mode']}  "
            f"k7={ex['k7_decision']} success={ex['success']}"
        )
        lines.append(f"        {ex['summary']}")

    lines += [
        "",
        f"[4] Bulletin entries created in window: {bull['new_entries']}",
    ]
    if bull["by_reason"]:
        lines.append(
            "    reasons: " + ", ".join(f"{r}={n}" for r, n in bull["by_reason"])
        )
    if bull["by_requested_by"]:
        lines.append(
            "    sources: " + ", ".join(f"{s}={n}" for s, n in bull["by_requested_by"])
        )

    lines += ["", "-" * 72, f"VERDICT: {report['verdict']}", "-" * 72]
    for note in report["notes"]:
        lines.append(f"  - {note}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="ANALYTICAL classification smoke")
    parser.add_argument(
        "--since-minutes",
        type=int,
        default=None,
        help="Override window — minutes back from now. Default: since restart.",
    )
    args = parser.parse_args()

    events = _load_jsonl(EVENTS_PATH)
    traces = _load_jsonl(TRACES_PATH)
    bulletin = _load_jsonl(BULLETIN_PATH)

    if args.since_minutes is not None:
        cutoff = time.time() - args.since_minutes * 60.0
    else:
        cutoff = (
            find_daemon_start_ts()
            or find_restart_ts(events)
            or (time.time() - 3600.0)
        )

    trace_data = trace_summary(traces, cutoff)
    mode_data = mode_timeline(events, cutoff)
    bull_data = bulletin_changes(bulletin, cutoff)

    deg = trace_data["degraded"]
    notes: List[str] = []

    # Verdict logic
    if not mode_data["entered_degraded"]:
        verdict = "INCONCLUSIVE — Maria has not entered SLEEP/REDUCED yet"
        notes.append("Wait for idle_timeout (~30min after last activity) and re-run.")
    elif deg["total"] == 0:
        verdict = "INCONCLUSIVE — entered degraded mode but no ANALYTICAL attempts yet"
        notes.append("K12 cooldown is 4h — first attempt may still be pending.")
        notes.append("K13 fires on tension; sometimes silent for hours.")
    elif deg["blocked"] > 0 and deg["success"] == 0:
        verdict = "FAIL — ANALYTICAL still blocked by K7 in degraded mode"
        notes.append("Confirm the daemon was restarted after commit 6033de0.")
        notes.append("Check journalctl for 'mode_restrict' rule_name.")
    elif deg["success"] > 0 and deg["blocked"] == 0:
        verdict = "PASS — ANALYTICAL runs cleanly in SLEEP/REDUCED"
        notes.append(
            f"{deg['success']} successful ANALYTICAL action(s) in degraded mode."
        )
        if bull_data["new_entries"]:
            notes.append(
                f"Bulletin gained {bull_data['new_entries']} new entries — advisory pipeline live."
            )
    elif deg["success"] > 0 and deg["blocked"] > 0:
        verdict = "PARTIAL — some ANALYTICAL ran, some still blocked"
        notes.append("Investigate the blocked ones — may be a different rule than mode_restrict.")
    else:
        verdict = "INCONCLUSIVE — degraded mode reached but no clean signal yet"

    # Regression flag
    if trace_data["active"]["total"] > 0 and trace_data["active"]["success"] == 0:
        notes.append("[REGRESSION?] ANALYTICAL actions failing in ACTIVE mode too.")

    report = {
        "cutoff_ts": cutoff,
        "traces": trace_data,
        "modes": mode_data,
        "bulletin": bull_data,
        "verdict": verdict,
        "notes": notes,
    }
    print(render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
