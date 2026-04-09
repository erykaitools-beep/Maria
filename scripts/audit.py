#!/usr/bin/env python3
"""
M.A.R.I.A. Periodic System Audit

Checks for common runtime pathologies:
1. Planner loops (same action+topic repeated >10x)
2. Stuck/stale goals (PENDING >7 days, zero progress)
3. Oneshot goals without completion (critique/self_analyze/creative on META goal)
4. Health drops and mode oscillations
5. Log file sizes and rotation needs
6. JSONL integrity (malformed lines)

Outputs: report file + Telegram notification.

Usage:
    python scripts/audit.py           # run audit, send Telegram
    python scripts/audit.py --dry-run # run audit, print only (no Telegram)
    python scripts/audit.py --quiet   # Telegram only if issues found

Cron (every 4 days at 06:00):
    0 6 */4 * * cd /home/maria/maria && /home/maria/maria/venv/bin/python scripts/audit.py --quiet
"""

import json
import os
import sys
import time
import argparse
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

META_DIR = PROJECT_ROOT / "meta_data"
REPORT_DIR = PROJECT_ROOT / "meta_data" / "audit_reports"

# JSONL files to check
MANAGED_LOGS = [
    "planner_decisions.jsonl",
    "goals.jsonl",
    "homeostasis_events.jsonl",
    "decision_traces.jsonl",
    "evaluation_reports.jsonl",
    "beliefs.jsonl",
    "experiment_proposals.jsonl",
    "experiment_reports.jsonl",
    "creative_journal.jsonl",
    "creative_tensions.jsonl",
    "critique_reports.jsonl",
    "web_fetch_registry.jsonl",
    "k7_escalation_log.jsonl",
    "k10_audit_log.jsonl",
]

# Max acceptable file size before rotation warning (50 MB)
LOG_SIZE_WARN_MB = 50


def load_jsonl(path: Path, max_lines: int = 0) -> list:
    """Load JSONL file, return list of dicts. Skips malformed lines."""
    records = []
    errors = 0
    if not path.exists():
        return records
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                errors += 1
            if max_lines and len(records) >= max_lines:
                break
    if errors:
        records.append({"_jsonl_errors": errors, "_file": str(path.name)})
    return records


def check_planner_loops(decisions: list, window_hours: int = 96) -> list:
    """Find repeated action+topic patterns in recent planner decisions."""
    cutoff = time.time() - (window_hours * 3600)
    recent = [d for d in decisions if d.get("timestamp", 0) > cutoff]

    # Count (action_type, topic) pairs
    counter = Counter()
    for d in recent:
        action = d.get("action_type", "?")
        topic = d.get("action_params", {}).get("topic", "")
        skipped = d.get("result", {}).get("skipped", False)
        if skipped:
            key = f"{action}+{topic}+SKIPPED"
        else:
            key = f"{action}+{topic}" if topic else action
        counter[key] += 1

    issues = []
    for key, count in counter.most_common():
        if count > 10:
            issues.append({
                "type": "planner_loop",
                "severity": "critical" if count > 50 else "warning",
                "pattern": key,
                "count": count,
                "window_hours": window_hours,
            })
    return issues


def check_stale_goals(goals: list) -> list:
    """Find goals stuck in PENDING/ACTIVE for >7 days with no progress."""
    issues = []
    now = time.time()
    seven_days = 7 * 24 * 3600

    for g in goals:
        status = g.get("status", "")
        if status not in ("pending", "active"):
            continue
        created = g.get("created_at", now)
        age = now - created
        progress = g.get("progress", 0.0)
        goal_type = g.get("type", "")

        # META goals are permanent, skip
        if goal_type == "meta":
            continue

        if age > seven_days and progress < 0.1:
            issues.append({
                "type": "stale_goal",
                "severity": "warning",
                "goal_id": g.get("id", "?"),
                "description": g.get("description", "?")[:60],
                "age_days": round(age / 86400, 1),
                "progress": progress,
                "status": status,
            })
    return issues


def check_oneshot_goals(decisions: list, goals_by_id: dict) -> list:
    """Find oneshot actions (critique, self_analyze, creative) running on non-closing goals."""
    issues = []
    oneshot_actions = {"critique", "self_analyze", "creative"}
    now = time.time()
    recent_cutoff = now - (96 * 3600)

    # Count how many times each goal_id was used for oneshot actions recently
    goal_action_counts = Counter()
    for d in decisions:
        if d.get("timestamp", 0) < recent_cutoff:
            continue
        action = d.get("action_type", "")
        goal_id = d.get("goal_id", "")
        if action in oneshot_actions and goal_id:
            goal_action_counts[(goal_id, action)] += 1

    for (goal_id, action), count in goal_action_counts.items():
        if count > 5:
            goal = goals_by_id.get(goal_id, {})
            status = goal.get("status", "?")
            if status in ("pending", "active"):
                issues.append({
                    "type": "oneshot_loop",
                    "severity": "critical",
                    "goal_id": goal_id,
                    "action": action,
                    "count": count,
                    "goal_status": status,
                    "description": goal.get("description", "?")[:60],
                })
    return issues


def check_mode_oscillations(events: list, window_hours: int = 24) -> list:
    """Count mode changes in recent window."""
    issues = []
    cutoff = time.time() - (window_hours * 3600)
    mode_changes = [
        e for e in events
        if e.get("event_type") == "mode_change" and e.get("timestamp", 0) > cutoff
    ]

    if len(mode_changes) > 20:
        issues.append({
            "type": "mode_oscillation",
            "severity": "warning",
            "changes_24h": len(mode_changes),
            "message": f"{len(mode_changes)} mode changes in {window_hours}h (>20 = unstable)",
        })

    # Check if currently in REDUCED/SLEEP for >6h
    if mode_changes:
        last = mode_changes[-1]
        to_mode = last.get("to_mode", "")
        age = time.time() - last.get("timestamp", time.time())
        if to_mode in ("reduced", "sleep") and age > 6 * 3600:
            issues.append({
                "type": "prolonged_degradation",
                "severity": "warning",
                "mode": to_mode,
                "hours": round(age / 3600, 1),
            })
    return issues


def check_log_sizes() -> list:
    """Check JSONL file sizes and count malformed lines."""
    issues = []
    for name in MANAGED_LOGS:
        path = META_DIR / name
        if not path.exists():
            continue
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > LOG_SIZE_WARN_MB:
            issues.append({
                "type": "log_size",
                "severity": "warning",
                "file": name,
                "size_mb": round(size_mb, 1),
            })
    return issues


def check_jsonl_integrity() -> list:
    """Check JSONL files for malformed lines."""
    issues = []
    for name in MANAGED_LOGS:
        path = META_DIR / name
        if not path.exists():
            continue
        errors = 0
        total = 0
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    json.loads(line)
                except json.JSONDecodeError:
                    errors += 1
        if errors > 0:
            issues.append({
                "type": "jsonl_corrupt",
                "severity": "critical" if errors > 10 else "warning",
                "file": name,
                "errors": errors,
                "total_lines": total,
            })
    return issues


def check_health_state() -> list:
    """Check planner state for anomalies."""
    issues = []
    state_path = META_DIR / "planner_state.json"
    if not state_path.exists():
        return issues

    with open(state_path, "r") as f:
        state = json.load(f)

    # Check consecutive NOOP
    noop_count = state.get("consecutive_noop_count", 0)
    if noop_count > 50:
        issues.append({
            "type": "excessive_noop",
            "severity": "warning",
            "count": noop_count,
            "message": f"Planner stuck in NOOP for {noop_count} consecutive cycles",
        })

    # Check if planner hasn't run in a while
    last_cycle = state.get("last_cycle_tick", 0)
    total = state.get("total_cycles", 0)
    if total > 0 and last_cycle == 0:
        issues.append({
            "type": "planner_stalled",
            "severity": "critical",
            "message": "Planner has cycles but last_cycle_tick=0 (possible crash)",
        })

    return issues


def run_audit() -> dict:
    """Run all audit checks, return structured report."""
    report = {
        "timestamp": time.time(),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "checks": [],
        "issues": [],
        "summary": {},
    }

    # Load data
    decisions = load_jsonl(META_DIR / "planner_decisions.jsonl")
    goals = load_jsonl(META_DIR / "goals.jsonl")
    events = load_jsonl(META_DIR / "homeostasis_events.jsonl")

    goals_by_id = {}
    for g in goals:
        gid = g.get("id")
        if gid:
            goals_by_id[gid] = g

    # Run checks
    checks = [
        ("planner_loops", check_planner_loops, [decisions]),
        ("stale_goals", check_stale_goals, [goals]),
        ("oneshot_loops", check_oneshot_goals, [decisions, goals_by_id]),
        ("mode_oscillations", check_mode_oscillations, [events]),
        ("log_sizes", check_log_sizes, []),
        ("jsonl_integrity", check_jsonl_integrity, []),
        ("health_state", check_health_state, []),
    ]

    all_issues = []
    for name, func, args in checks:
        try:
            issues = func(*args)
            report["checks"].append({"name": name, "issues": len(issues), "ok": len(issues) == 0})
            all_issues.extend(issues)
        except Exception as e:
            report["checks"].append({"name": name, "error": str(e)})

    report["issues"] = all_issues

    critical = sum(1 for i in all_issues if i.get("severity") == "critical")
    warnings = sum(1 for i in all_issues if i.get("severity") == "warning")
    report["summary"] = {
        "total_issues": len(all_issues),
        "critical": critical,
        "warnings": warnings,
        "status": "CRITICAL" if critical else ("WARNING" if warnings else "OK"),
    }

    return report


def format_telegram_message(report: dict) -> str:
    """Format audit report for Telegram (Markdown)."""
    status = report["summary"]["status"]
    icon = {"OK": "[OK]", "WARNING": "[!]", "CRITICAL": "[!!]"}.get(status, "?")

    lines = [
        f"*{icon} Audyt Marii - {report['date']}*",
        "",
        f"Status: *{status}*",
        f"Problemy: {report['summary']['total_issues']} "
        f"({report['summary']['critical']} krytycznych, "
        f"{report['summary']['warnings']} ostrzezen)",
        "",
    ]

    # Checks summary
    for check in report["checks"]:
        mark = "OK" if check.get("ok") else f"{check.get('issues', '?')} issues"
        if "error" in check:
            mark = f"ERROR: {check['error'][:30]}"
        lines.append(f"  {check['name']}: {mark}")

    # Critical issues detail
    critical = [i for i in report["issues"] if i.get("severity") == "critical"]
    if critical:
        lines.append("")
        lines.append("*Krytyczne:*")
        for issue in critical[:5]:
            itype = issue.get("type", "?")
            if itype == "planner_loop":
                lines.append(f"  - Petla: {issue['pattern']} x{issue['count']}")
            elif itype == "oneshot_loop":
                lines.append(
                    f"  - Oneshot loop: {issue['action']} na {issue['goal_id'][:12]} x{issue['count']}"
                )
            elif itype == "jsonl_corrupt":
                lines.append(f"  - Uszkodzony: {issue['file']} ({issue['errors']} bledow)")
            else:
                lines.append(f"  - {itype}: {json.dumps(issue, ensure_ascii=False)[:80]}")

    # Warning issues (brief)
    warnings = [i for i in report["issues"] if i.get("severity") == "warning"]
    if warnings:
        lines.append("")
        lines.append(f"*Ostrzezenia ({len(warnings)}):*")
        for issue in warnings[:5]:
            itype = issue.get("type", "?")
            if itype == "stale_goal":
                lines.append(
                    f"  - Stary cel: {issue['description']} ({issue['age_days']}d)"
                )
            elif itype == "log_size":
                lines.append(f"  - Duzy log: {issue['file']} ({issue['size_mb']} MB)")
            elif itype == "mode_oscillation":
                lines.append(f"  - {issue['changes_24h']} zmian trybu w 24h")
            else:
                lines.append(f"  - {itype}")
        if len(warnings) > 5:
            lines.append(f"  ...i {len(warnings) - 5} wiecej")

    return "\n".join(lines)


def save_report(report: dict) -> Path:
    """Save audit report as JSON file."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
    path = REPORT_DIR / f"audit_{date_str}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return path


def send_telegram(message: str) -> bool:
    """Send message via Telegram bot."""
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")

        from agent_core.telegram.bot import TelegramBot
        bot = TelegramBot()
        if not bot.configured:
            print("[WARN] Telegram not configured (missing token/chat_id)")
            return False
        return bot.send_message(message)
    except Exception as e:
        print(f"[ERROR] Telegram send failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="M.A.R.I.A. System Audit")
    parser.add_argument("--dry-run", action="store_true", help="Print only, no Telegram")
    parser.add_argument("--quiet", action="store_true", help="Telegram only if issues found")
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)

    print(f"[AUDIT] Starting at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report = run_audit()

    # Save report
    report_path = save_report(report)
    print(f"[AUDIT] Report saved: {report_path}")

    # Format message
    message = format_telegram_message(report)

    # Print
    status = report["summary"]["status"]
    print(f"\n{message}\n")
    print(f"[AUDIT] Status: {status} ({report['summary']['total_issues']} issues)")

    # Send Telegram
    if args.dry_run:
        print("[AUDIT] Dry run - skipping Telegram")
    elif args.quiet and status == "OK":
        print("[AUDIT] Quiet mode, no issues - skipping Telegram")
    else:
        ok = send_telegram(message)
        print(f"[AUDIT] Telegram: {'sent' if ok else 'FAILED'}")

    # Exit code for cron
    if report["summary"]["critical"] > 0:
        sys.exit(2)
    elif report["summary"]["warnings"] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
