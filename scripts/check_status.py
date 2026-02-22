#!/usr/bin/env python
"""
Quick status check script for 36h stability test.

Run this in a separate terminal to check system status without
interrupting the main REPL session.

Usage:
    python scripts/check_status.py
    python scripts/check_status.py --events 20
    python scripts/check_status.py --full
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def format_timestamp(ts: float) -> str:
    """Format Unix timestamp to readable string."""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human readable."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


def read_events(limit: int = 10) -> list:
    """Read recent events from JSONL log."""
    log_path = PROJECT_ROOT / "meta_data" / "homeostasis_events.jsonl"

    if not log_path.exists():
        return []

    events = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    events.reverse()  # Newest first
    return events[:limit]


def get_summary() -> dict:
    """Get session summary from events."""
    log_path = PROJECT_ROOT / "meta_data" / "homeostasis_events.jsonl"

    summary = {
        "total_events": 0,
        "mode_changes": 0,
        "modes_visited": set(),
        "alerts": {"CRITICAL": 0, "ALERT": 0, "WARNING": 0},
        "first_event_ts": None,
        "last_event_ts": None,
    }

    if not log_path.exists():
        return summary

    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                event = json.loads(line.strip())
                summary["total_events"] += 1

                ts = event.get("timestamp") or event.get("ts")
                if ts:
                    if summary["first_event_ts"] is None:
                        summary["first_event_ts"] = ts
                    summary["last_event_ts"] = ts

                evt = event.get("event") or event.get("event_type")
                if evt == "mode_change":
                    summary["mode_changes"] += 1
                    summary["modes_visited"].add(event.get("to_mode", "unknown"))
                elif evt == "alert":
                    severity = event.get("severity", "UNKNOWN")
                    if severity in summary["alerts"]:
                        summary["alerts"][severity] += 1
            except:
                continue

    summary["modes_visited"] = list(summary["modes_visited"])
    return summary


def check_memory_files() -> dict:
    """Check memory file sizes and counts."""
    memory_dir = PROJECT_ROOT / "memory"

    result = {}

    # Knowledge index
    ki_path = memory_dir / "knowledge_index.jsonl"
    if ki_path.exists():
        with open(ki_path, "r", encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        result["knowledge_index"] = {
            "size_kb": ki_path.stat().st_size / 1024,
            "entries": len(lines),
        }

    # Longterm memory
    ltm_path = memory_dir / "maria_longterm_memory.jsonl"
    if ltm_path.exists():
        with open(ltm_path, "r", encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        result["longterm_memory"] = {
            "size_kb": ltm_path.stat().st_size / 1024,
            "entries": len(lines),
        }

    # Semantic graph
    sg_path = PROJECT_ROOT / "semantic_graph.json"
    if sg_path.exists():
        try:
            with open(sg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            result["semantic_graph"] = {
                "size_kb": sg_path.stat().st_size / 1024,
                "nodes": len(data.get("nodes", {})),
                "edges": len(data.get("edges", [])),
            }
        except:
            pass

    return result


def print_quick_status():
    """Print quick status overview."""
    print("\n" + "=" * 60)
    print("[STATUS] M.A.R.I.A. QUICK STATUS CHECK")
    print("=" * 60)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Summary
    summary = get_summary()

    if summary["first_event_ts"]:
        uptime = summary["last_event_ts"] - summary["first_event_ts"]
        print(f"\n[STATS] Session Uptime: {format_duration(uptime)}")

    print(f"   Total Events: {summary['total_events']}")
    print(f"   Mode Changes: {summary['mode_changes']}")
    print(f"   Modes Visited: {', '.join(summary['modes_visited']) or 'none'}")

    print(f"\n[ALERTS]:")
    print(f"   CRITICAL: {summary['alerts']['CRITICAL']}")
    print(f"   ALERT:    {summary['alerts']['ALERT']}")
    print(f"   WARNING:  {summary['alerts']['WARNING']}")

    # Memory files
    memory = check_memory_files()
    print(f"\n[MEMORY] Memory Files:")
    if "semantic_graph" in memory:
        sg = memory["semantic_graph"]
        print(f"   Semantic Graph: {sg['nodes']} nodes, {sg['edges']} edges ({sg['size_kb']:.1f} KB)")
    if "longterm_memory" in memory:
        ltm = memory["longterm_memory"]
        print(f"   Longterm Memory: {ltm['entries']} entries ({ltm['size_kb']:.1f} KB)")
    if "knowledge_index" in memory:
        ki = memory["knowledge_index"]
        print(f"   Knowledge Index: {ki['entries']} entries ({ki['size_kb']:.1f} KB)")

    # Last event
    events = read_events(limit=1)
    if events:
        last = events[0]
        evt = last.get("event") or last.get("event_type")
        ts = last.get("timestamp") or last.get("ts", 0)
        print(f"\n[LAST] Last Event: {evt} at {format_timestamp(ts)}")

    print("=" * 60 + "\n")


def print_events(limit: int = 10):
    """Print recent events."""
    events = read_events(limit=limit)

    print("\n" + "=" * 70)
    print(f"[EVENTS] HOMEOSTASIS EVENTS (last {len(events)})")
    print("=" * 70)

    if not events:
        print("  No events recorded yet.")
    else:
        for event in events:
            ts = event.get("timestamp") or event.get("ts", 0)
            dt = format_timestamp(ts)
            evt = event.get("event") or event.get("event_type", "?")

            if evt == "mode_change":
                from_m = event.get("from_mode", event.get("from", "?"))
                to_m = event.get("to_mode", event.get("to", "?"))
                trigger = event.get("trigger", {})
                constraint = trigger.get("constraint", "?")
                duration = event.get("duration_in_prev_mode_sec", 0)

                print(f"\n  [{dt}] MODE CHANGE: {from_m} → {to_m}")
                print(f"      Trigger: {constraint}")
                print(f"      Duration in {from_m}: {format_duration(duration)}")

            elif evt == "alert":
                severity = event.get("severity", "?")
                alert_type = event.get("alert_type", "?")
                message = event.get("message", "")
                print(f"\n  [{dt}] {severity}: {alert_type}")
                print(f"      {message}")

            elif evt == "state_snapshot":
                mode = event.get("mode", "?")
                health = event.get("health_score", 0)
                metrics = event.get("metrics", {})
                ram = metrics.get("ram_available_pct", 0)
                cpu = metrics.get("cpu_load", 0)
                print(f"\n  [{dt}] SNAPSHOT: mode={mode}, health={health:.0%}")
                print(f"      RAM: {ram:.0f}% avail, CPU: {cpu:.0f}%")

            elif evt == "startup":
                print(f"\n  [{dt}] STARTUP")

            elif evt == "shutdown":
                reason = event.get("reason", "?")
                uptime = event.get("uptime_sec", 0)
                print(f"\n  [{dt}] SHUTDOWN: {reason} (uptime: {format_duration(uptime)})")

            else:
                print(f"\n  [{dt}] {evt}")

    print("\n" + "=" * 70 + "\n")


def print_full_report():
    """Print full status report."""
    print_quick_status()
    print_events(limit=20)


def main():
    parser = argparse.ArgumentParser(description="Check M.A.R.I.A. status")
    parser.add_argument("--events", type=int, default=0, help="Show N recent events")
    parser.add_argument("--full", action="store_true", help="Full report")
    args = parser.parse_args()

    if args.full:
        print_full_report()
    elif args.events > 0:
        print_events(limit=args.events)
    else:
        print_quick_status()


if __name__ == "__main__":
    main()
