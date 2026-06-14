"""Warm crash recovery state (Klocek 9, TIER 1 roof).

Persists a tiny OPERATIONAL snapshot so the daemon can wake WARM (resume its
in-flight strategic plan) instead of cold. Deliberately narrow:

  * mode + last_mode_change   -- HINT only. The boot restore LOGS it; tick 1
    re-derives the real mode from live sensors. So a crash CAUSED by a bad
    mode (OOM / storm / SURVIVAL) can never be resurrected into a crash loop.
  * active_goal_ids           -- IDs only. goals.jsonl stays the source of
    truth (ADR-001), so the snapshot can never diverge from it (no split-brain).
  * strategic_plan            -- the in-flight plan, re-checked for expiry /
    exhaustion on restore before reuse.

ONE file, meta_data/warm_recovery.json, written atomically (tmp + fsync +
os.replace) so a hard kill (the watchdog's os._exit) never leaves a torn file.
Everything is gated by WARM_RECOVERY_ENABLED at the call sites; this module is
pure I/O + shaping with no side effects of its own and never raises.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent_core.homeostasis.recovery")

SCHEMA_VERSION = 1
DEFAULT_PATH = Path("meta_data/warm_recovery.json")
# A snapshot older than this is treated as stale on boot -> ignored (cold boot).
# Short on purpose: a long downtime means the in-flight plan is almost certainly
# expired anyway, and a stale operational state is not worth resuming.
DEFAULT_MAX_AGE_SECONDS = 15 * 60


def is_enabled() -> bool:
    """WARM_RECOVERY_ENABLED feature flag (parallel-run, OFF by default).

    Same idiom as HEARTBEAT_DETECTOR_ENABLED / SCHEDULER_ENFORCE_MUTEX /
    STRATEGIC_PLANNER_DRIVES. OFF = cold boot exactly as before."""
    return os.environ.get("WARM_RECOVERY_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def build_snapshot(
    mode: str,
    last_mode_change_time: float,
    active_goal_ids: List[str],
    plan_dict: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Shape the recovery payload. Pure -- the only clock read is the write
    timestamp used later for the freshness gate."""
    return {
        "schema_version": SCHEMA_VERSION,
        "written_at": time.time(),
        "mode": mode,
        "last_mode_change_time": last_mode_change_time,
        "active_goal_ids": list(active_goal_ids or []),
        "strategic_plan": plan_dict,  # StrategicPlan.to_dict() output or None
    }


def write_snapshot(snapshot: Dict[str, Any], path: Path = DEFAULT_PATH) -> bool:
    """Atomically persist the recovery snapshot (tmp + fsync + os.replace).

    Safe across a process restart (the watchdog's os._exit, our threat model):
    a kill mid-write leaves either the old file or the new one, never a torn
    one, and the renamed file is visible to the next process via the page cache.
    (A parent-dir fsync would additionally cover power-loss, but that is out of
    scope and omitted for consistency with every other atomic writer here.)
    Returns True on success; never raises (a recovery write must not be able to
    break the tick loop)."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except Exception:
        logger.warning("[Recovery] snapshot write failed", exc_info=True)
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False


def read_snapshot(
    path: Path = DEFAULT_PATH,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
) -> Optional[Dict[str, Any]]:
    """Load the recovery snapshot if present, parseable, fresh, and current
    schema. Returns None (=> cold boot) on missing file, corruption (a torn
    last write), schema mismatch, or staleness. Never raises."""
    path = Path(path)
    try:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        logger.warning(
            "[Recovery] snapshot read/parse failed -> cold boot", exc_info=True
        )
        return None

    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        logger.info("[Recovery] snapshot schema mismatch -> cold boot")
        return None

    written_at = data.get("written_at")
    if not isinstance(written_at, (int, float)):
        return None
    age = time.time() - float(written_at)
    if age > max_age_seconds:
        logger.info(
            "[Recovery] snapshot stale (%.0fs > %.0fs) -> cold boot",
            age, max_age_seconds,
        )
        return None
    return data
