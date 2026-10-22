"""Cheap, cached read of the exam_failed backlog size.

Why this exists (2026-08-12): the off-window learn budget in the planner is a
flat 8 actions/day, which the night spends entirely on LEARN -- on 2026-08-12
the planner issued 8 night `learn` actions and ZERO exams between 00:00 and
09:00, while the CPU sat at 41-45C (the coldest, cheapest hours of the day) and
burned 152 cycles on `evaluate`. The exam_failed drain therefore ran only inside
the 09-19 window at ~1 file/hour.

The drain bonus (planner_core.OFF_WINDOW_EXAM_DRAIN_BONUS) is gated on this
count so it is SELF-REVERTING: the moment the backlog reaches zero the extra
night budget disappears on its own and the planner is back to its normal
rhythm. No flag to remember, no human gate to close later.

Deliberately counts exam_failed ONLY -- not "learned", which is non-empty
during ordinary operation and would make the bonus permanent.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Recount at most this often. The index is ~1500 lines (a few ms to scan), but
# this is consulted from the planner's decision path, so keep it rare.
_TTL_SEC = 300.0

_cache: dict = {"count": None, "at": 0.0, "mtime": None, "path": None}


def _resolve_index_path(index_path: Optional[Path]) -> Path:
    if index_path is not None:
        return Path(index_path)
    from maria_core.sys.config import KNOWLEDGE_INDEX
    return Path(KNOWLEDGE_INDEX)


def exam_failed_count(index_path: Optional[Path] = None,
                      ttl_sec: float = _TTL_SEC) -> int:
    """Number of records sitting in status 'exam_failed'.

    Cached for ttl_sec, invalidated early when the index mtime moves. Any
    failure (missing file, unreadable, bad JSON) returns 0 -- FAIL-CLOSED, so a
    broken read can only withdraw the drain bonus, never grant one.
    """
    try:
        path = _resolve_index_path(index_path)
        mtime = path.stat().st_mtime
        now = time.monotonic()
        if (_cache["count"] is not None
                and _cache["path"] == str(path)
                and _cache["mtime"] == mtime
                and now - _cache["at"] < ttl_sec):
            return _cache["count"]

        count = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    if json.loads(line).get("status") == "exam_failed":
                        count += 1
                except Exception:  # noqa: BLE001 - one bad line must not blind us
                    continue

        _cache.update({"count": count, "at": now, "mtime": mtime,
                       "path": str(path)})
        return count
    except Exception as e:  # noqa: BLE001
        logger.debug("[BACKLOG] exam_failed_count unavailable: %s", e)
        return 0


def reset_cache() -> None:
    """Drop the cache (tests, and any caller that just rewrote the index)."""
    _cache.update({"count": None, "at": 0.0, "mtime": None, "path": None})
