#!/usr/bin/env python3
"""Pre-test checklist for 24h autonomy test (2026-05-24/25).

Invoked by Maria's reminder ``on_fire_command`` ~2h before test start
(nd 2026-05-24 17:00 Berlin = 15:00 UTC). Output captured to Telegram
by the reminder scheduler.

Checks:
  C1  Maria PID + uptime + tick count
  C2  Baseline action stats (last 7 days)
  C3  PROPOSED + PENDING goals (approval queue snapshot)
  C4  Recent bulletins, especially goal_exhausted_cycle (B4 cap=5 signal)
  C5  Master prompt addendum activation status
  C6  Last 6 days journal errors + mode transitions

Stdlib-only. Reads meta_data/* + /mnt/storage/data/logs/ archive +
queries systemd. Designed defensively — single check failure does
not abort the whole report.
"""

import json
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path("/home/maria/maria")
META = PROJECT_ROOT / "meta_data"
ARCHIVE = Path("/mnt/storage/data/logs")


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return rows


def check_pid_uptime() -> str:
    try:
        out = subprocess.run(
            ["pgrep", "-f", "venv/bin/python maria.py"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        pids = [p for p in out.stdout.strip().split() if p]
        if not pids:
            return "C1 PID: **NOT FOUND** (maria.py nie biega — krytyczne!)"
        pid = pids[0]
        elapsed = subprocess.run(
            ["ps", "-p", pid, "-o", "etime="],
            capture_output=True, text=True, check=False, timeout=5,
        ).stdout.strip()

        # tick count + mode from last homeostasis event
        events_file = META / "homeostasis_events.jsonl"
        last_event: Dict[str, Any] = {}
        if events_file.exists():
            try:
                with open(events_file, "rb") as f:
                    f.seek(0, 2)
                    size = f.tell()
                    f.seek(max(0, size - 8192))
                    tail = f.read().decode("utf-8", errors="ignore")
                for line in reversed(tail.split("\n")):
                    line = line.strip()
                    if line:
                        try:
                            last_event = json.loads(line)
                            break
                        except json.JSONDecodeError:
                            continue
            except OSError:
                pass

        tick = last_event.get("tick_count", "?")
        mode = last_event.get("mode", "?")
        health = last_event.get("health_score", "?")
        return (
            f"C1 PID **{pid}** — uptime {elapsed}, tick {tick}, "
            f"mode {mode}, health {health}"
        )
    except Exception as e:
        return f"C1 ERROR: {e}"


def check_action_stats(days: int = 7) -> str:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    counts: Dict[str, int] = {}
    successes: Dict[str, int] = {}

    files = [META / "action_audit.jsonl", ARCHIVE / "action_audit.jsonl"]
    for path in files:
        for d in _read_jsonl(path):
            if d.get("timestamp", 0) < cutoff:
                continue
            at = d.get("action_type", "?")
            counts[at] = counts.get(at, 0) + 1
            if d.get("success"):
                successes[at] = successes.get(at, 0) + 1

    if not counts:
        return f"C2 Actions: zero w ostatnich {days}d"

    total = sum(counts.values())
    total_success = sum(successes.values())
    lines = [
        f"C2 Actions last {days}d — total {total}, success {total_success} "
        f"({100*total_success/total:.0f}%):"
    ]
    for at in sorted(counts, key=lambda k: -counts[k]):
        n = counts[at]
        s = successes.get(at, 0)
        lines.append(f"  {at}: {s}/{n} ({100*s/n:.0f}%)")
    return "\n".join(lines)


def check_goals() -> str:
    rows = _read_jsonl(META / "goals.jsonl")
    if not rows:
        return "C3 Goals: goals.jsonl pusty/missing"

    latest: Dict[str, Dict[str, Any]] = {}
    for d in rows:
        if "id" in d:
            latest[d["id"]] = d

    by_status: Dict[str, List[Dict[str, Any]]] = {}
    for g in latest.values():
        st = g.get("status", "?")
        by_status.setdefault(st, []).append(g)

    active = by_status.get("active", [])
    proposed = by_status.get("proposed", [])
    pending = by_status.get("pending", [])

    lines = [
        f"C3 Goals — active {len(active)}, proposed {len(proposed)}, "
        f"pending {len(pending)} (others: "
        f"{ {k: len(v) for k, v in by_status.items() if k not in ('active','proposed','pending')} })"
    ]
    if proposed:
        lines.append("  PROPOSED awaiting approval:")
        for g in proposed[:5]:
            desc = (g.get("description") or "")[:60]
            lines.append(f"    {g['id'][:16]}: {desc}")
    return "\n".join(lines)


def check_bulletins(days: int = 6) -> str:
    rows = _read_jsonl(META / "cognitive_bulletin.jsonl")
    if not rows:
        return "C4 Bulletins: cognitive_bulletin.jsonl pusty/missing"
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()

    latest: Dict[str, Dict[str, Any]] = {}
    for d in rows:
        if "entry_id" not in d:
            continue
        if d.get("updated_at", 0) < cutoff:
            continue
        latest[d["entry_id"]] = d

    exhausted = [
        b for b in latest.values()
        if b.get("reason_code") == "goal_exhausted_cycle"
    ]
    improvements = [
        b for b in latest.values()
        if b.get("entry_type") == "improvement"
    ]

    lines = [
        f"C4 Bulletins last {days}d — total {len(latest)}, "
        f"improvements {len(improvements)}, "
        f"**goal_exhausted_cycle (B4 cap=5): {len(exhausted)}**"
    ]
    if exhausted:
        lines.append("  B4 signals fired (T-B4-001 cap working):")
        for b in exhausted[:5]:
            summary = (b.get("summary") or "")[:80]
            lines.append(f"    {b['entry_id'][:24]}: {summary}")
    return "\n".join(lines)


def check_master_prompt_addendum() -> str:
    mp = PROJECT_ROOT / "agent_core/llm/master_prompt.py"
    if not mp.exists():
        return "C5 master_prompt.py: missing"
    try:
        text = mp.read_text(encoding="utf-8")
    except OSError as e:
        return f"C5 master_prompt.py: read error {e}"
    has_addendum = any(
        marker in text
        for marker in ("AUTONOMY_TEST", "autonomy_test", "addendum")
    )
    note = "gotowy do aktywacji" if has_addendum else "BRAK — sprawdź"
    return (
        f"C5 master_prompt addendum present: **{has_addendum}** "
        f"({note}). Kod zero-effect domyślnie."
    )


def check_journal_errors(days: int = 6) -> str:
    try:
        out = subprocess.run(
            [
                "journalctl", "-u", "maria",
                "--since", f"{days} days ago",
                "-p", "warning", "--no-pager",
            ],
            capture_output=True, text=True, check=False, timeout=20,
        )
    except Exception as e:
        return f"C6 journalctl ERROR: {e}"
    raw = out.stdout.strip().split("\n") if out.stdout else []
    errs = [l for l in raw if "ERROR" in l or "CRITICAL" in l]
    return (
        f"C6 journal last {days}d — {len(errs)} ERROR/CRITICAL "
        f"(total warnings+: {len(raw)})"
    )


def main() -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sections = [
        "# Pre-test 24h autonomy checklist",
        f"Generated: {now}",
        "Test start: 2026-05-24 19:00 Berlin (17:00 UTC) — ~2h from now",
        "Test end:   2026-05-25 19:00 Berlin (17:00 UTC)",
        "",
        check_pid_uptime(),
        "",
        check_action_stats(),
        "",
        check_goals(),
        "",
        check_bulletins(),
        "",
        check_master_prompt_addendum(),
        "",
        check_journal_errors(),
        "",
        "---",
        "Eryk: 2h do startu testu. Sprawdź C4 (B4 cap=5 sygnał) i C5 (addendum). "
        "Pełny raport zapisany w meta_data/pre_test_checklist_2026_05_24.md",
    ]
    body = "\n".join(sections)
    try:
        (META / "pre_test_checklist_2026_05_24.md").write_text(
            body, encoding="utf-8"
        )
    except OSError:
        pass
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
