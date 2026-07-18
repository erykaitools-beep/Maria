#!/usr/bin/env python3
"""
M.A.R.I.A. Throughput Watch

Time-based verification that the 2026-06-20 throughput change (7-day 10h learning
window + topic-supply unblock + NIM token-budget ceiling, commit fbdf236) keeps
working over time -- not just in the first hour. Snapshots the live signals,
appends them to a trend log, and (in --quiet) raises a Telegram alert ONLY when a
metric regresses.

What it watches:
  - awake-in-window %    : she should be ACTIVE during the learning window
  - learn / fetch / exam : the learning loop is actually turning
  - fresh material/day   : fetch keeps delivering (supply unclogged)
  - graduations/day      : goals still complete
  - NIM token budget     : burn stays under the ceiling (cost throttles, not clock)
  - mode thrash          : regulator isn't oscillating at window edges
  - stall-reaps          : the 'rna' grind backstop (commit 20109c6) firing a lot

Usage:
    python scripts/throughput_watch.py            # print snapshot
    python scripts/throughput_watch.py --quiet    # Telegram only if a metric regressed
    python scripts/throughput_watch.py --telegram # always send to Telegram

Cron (twice during the window, weekdays + weekend):
    0 12,18 * * * cd /home/maria/maria && /home/maria/maria/venv/bin/python scripts/throughput_watch.py --quiet >> /home/maria/maria/logs/throughput_watch.log 2>&1
"""

import json
import os
import sys
import time
import argparse
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

META_DIR = PROJECT_ROOT / "meta_data"
INPUT_DIR = PROJECT_ROOT / "input"
WATCH_LOG = META_DIR / "throughput_watch.jsonl"

LOOKBACK_SEC = 6 * 3600  # window for mode/action metrics

# Regression thresholds (alert when crossed)
ACTIVE_IN_WINDOW_MIN_PCT = 50.0   # below this = sleeping when she should be awake
NIM_ALERT_PCT = 85.0              # token budget burn
MODE_THRASH_MAX = 24             # mode_change events in lookback (>~4/h = thrashing)
STALL_REAP_ALERT = 3             # learning goals stall-reaped today (grind returned)


def _berlin_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Berlin")
    except Exception:
        return timezone(timedelta(hours=2))


def _iter_jsonl(path):
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _learning_hours():
    """Window hours from the SSoT (tracks any config change)."""
    try:
        from agent_core.environment.environment_model import PROFILE_LEARNING
        return set(PROFILE_LEARNING.auto_trigger_hours)
    except Exception:
        return set(range(9, 19))


def collect_snapshot():
    now = time.time()
    tz = _berlin_tz()
    since = now - LOOKBACK_SEC
    learning_hours = _learning_hours()

    # --- mode distribution (last lookback) ---
    active = in_window = in_window_active = mode_changes = 0
    last_mode = None
    last_health = None
    for d in _iter_jsonl(META_DIR / "homeostasis_events.jsonl"):
        ts = d.get("timestamp", 0)
        et = d.get("event_type")
        if et == "mode_change" and ts >= since:
            mode_changes += 1
        if et != "state_snapshot" or ts < since:
            continue
        mode = d.get("mode")
        last_mode, last_health = mode, d.get("health_score")
        if mode == "active":
            active += 1
        hour = datetime.fromtimestamp(ts, tz).hour
        if hour in learning_hours:
            in_window += 1
            if mode == "active":
                in_window_active += 1
    active_in_window_pct = (100.0 * in_window_active / in_window) if in_window else None

    # --- actions (last lookback) ---
    acts = {"learn": 0, "exam": 0, "fetch": 0, "review": 0, "creative": 0}
    for d in _iter_jsonl(META_DIR / "decision_traces.jsonl"):
        if d.get("started_at", 0) < since:
            continue
        at = d.get("action_type")
        if at in acts:
            acts[at] += 1

    # --- fresh material today ---
    today = date.today()
    fresh_files = 0
    if INPUT_DIR.exists():
        for f in INPUT_DIR.glob("*.txt"):
            try:
                if date.fromtimestamp(f.stat().st_mtime) == today:
                    fresh_files += 1
            except OSError:
                continue

    # --- goal graduations + stall-reaps today (dedup by id, last wins) ---
    goals = {}
    for g in _iter_jsonl(META_DIR / "goals.jsonl"):
        gid = g.get("id")
        if gid:
            goals[gid] = g
    grads_today = stall_reaps_today = 0
    for g in goals.values():
        if g.get("type") != "learning":
            continue
        upd = g.get("updated_at")
        is_today = isinstance(upd, (int, float)) and date.fromtimestamp(upd) == today
        if not is_today:
            continue
        status = g.get("status")
        if status == "achieved":
            grads_today += 1
        elif status == "abandoned":
            # stall-cap reaper (commit 20109c6) records this reason/actor
            trail = json.dumps(g.get("audit_trail", "")) + str(g.get("outcome", ""))
            if "stall" in trail.lower() or "planner_stall_cap_cleanup" in trail:
                stall_reaps_today += 1

    # --- PLAY "room for herself" today (commit ac21819) ---
    # Tracked (not alerted): the throughput change keeps her busy learning, and
    # PLAY only fires when idle -- so a busy day can squeeze out self-time. One
    # zero day isn't a regression, but the trend is worth seeing.
    play_today = 0
    for d in _iter_jsonl(META_DIR / "play_journal.jsonl"):
        ts = d.get("ts")
        if isinstance(ts, (int, float)) and date.fromtimestamp(ts) == today:
            play_today += 1

    # --- NIM token budget today ---
    nim_today = nim_limit = 0
    nim_calls = 0
    try:
        nb = json.loads((META_DIR / "nim_token_usage.json").read_text(encoding="utf-8"))
        nim_limit = nb.get("daily_limit", 0) or 0
        t = (nb.get("usage", {}) or {}).get(today.isoformat(), {})
        nim_today = t.get("total_tokens", 0)
        nim_calls = t.get("calls", 0)
    except Exception:
        pass
    nim_pct = (100.0 * nim_today / nim_limit) if nim_limit else None

    return {
        "ts": now,
        "berlin": datetime.fromtimestamp(now, tz).strftime("%Y-%m-%d %H:%M"),
        "mode_now": last_mode,
        "health": round(last_health, 3) if isinstance(last_health, (int, float)) else None,
        "active_in_window_pct": round(active_in_window_pct, 1) if active_in_window_pct is not None else None,
        "window_samples": in_window,
        "mode_changes_6h": mode_changes,
        "actions_6h": acts,
        "fresh_files_today": fresh_files,
        "graduations_today": grads_today,
        "stall_reaps_today": stall_reaps_today,
        "play_today": play_today,
        "nim_today": nim_today,
        "nim_limit": nim_limit,
        "nim_pct": round(nim_pct, 1) if nim_pct is not None else None,
        "nim_calls": nim_calls,
    }


def detect_regressions(s):
    """Return a list of human-readable regression alerts (empty = healthy)."""
    alerts = []
    p = s["active_in_window_pct"]
    if p is not None and s["window_samples"] >= 10 and p < ACTIVE_IN_WINDOW_MIN_PCT:
        alerts.append(f"AWAKE: tylko {p:.0f}% ACTIVE w oknie nauki (sen wrocil?)")
    if s["nim_pct"] is not None and s["nim_pct"] >= NIM_ALERT_PCT:
        alerts.append(f"NIM: {s['nim_pct']:.0f}% budzetu dziennego ({s['nim_today']:,}/{s['nim_limit']:,})")
    if s["mode_changes_6h"] > MODE_THRASH_MAX:
        alerts.append(f"THRASH: {s['mode_changes_6h']} zmian trybu / 6h (oscylacja regulatora?)")
    if s["stall_reaps_today"] >= STALL_REAP_ALERT:
        alerts.append(f"GRIND: {s['stall_reaps_today']} celow stall-reaped dzis (mielenie wrocilo?)")
    # supply clogged: awake but no fresh material and no fetch all lookback
    if (p is not None and p >= ACTIVE_IN_WINDOW_MIN_PCT
            and s["fresh_files_today"] == 0 and s["actions_6h"]["fetch"] == 0):
        alerts.append("DOSTAWA: 0 swiezych plikow dzis i 0 fetchow/6h mimo czuwania")
    return alerts


def format_message(s, alerts):
    head = "[ALERT] THROUGHPUT-WATCH: regresja" if alerts else "[OK] throughput-watch"
    lines = [
        f"{head}  ({s['berlin']})",
        f"tryb={s['mode_now']} health={s['health']} | ACTIVE-w-oknie={s['active_in_window_pct']}% ({s['window_samples']} probek)",
        f"akcje/6h: learn={s['actions_6h']['learn']} exam={s['actions_6h']['exam']} fetch={s['actions_6h']['fetch']} creative={s['actions_6h']['creative']}",
        f"dzis: swieze pliki={s['fresh_files_today']} graduacje={s['graduations_today']} stall-reap={s['stall_reaps_today']} play={s['play_today']}",
        f"NIM: {s['nim_today']:,}/{s['nim_limit']:,} ({s['nim_pct']}%) calls={s['nim_calls']}",
    ]
    if alerts:
        lines.append("")
        lines += [f"• {a}" for a in alerts]
    return "\n".join(lines)


def send_telegram(message):
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
        from agent_core.telegram.bot import TelegramBot
        bot = TelegramBot()
        if not getattr(bot, "configured", False):
            print("[WARN] Telegram not configured (missing token/chat_id)")
            return False
        return bot.send_message(message)
    except Exception as e:
        print(f"[ERROR] Telegram send failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="M.A.R.I.A. Throughput Watch")
    parser.add_argument("--quiet", action="store_true", help="Telegram only if a metric regressed")
    parser.add_argument("--telegram", action="store_true", help="Always send to Telegram")
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)
    s = collect_snapshot()
    alerts = detect_regressions(s)
    message = format_message(s, alerts)
    print(message)

    # Append to trend log (best-effort)
    try:
        with WATCH_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({**s, "alerts": alerts}, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[WARN] could not append trend log: {e}")

    if args.telegram or (args.quiet and alerts):
        send_telegram(message)

    return 1 if alerts else 0


if __name__ == "__main__":
    sys.exit(main())
