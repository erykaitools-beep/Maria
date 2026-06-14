"""
Fetch decision audit log.

Each fetch session writes one record to meta_data/fetch_decisions.jsonl
so post-hoc analysis can answer "who triggered this fetch and why?".
The complementary INFO-level log line keeps systemd journal readable.

Schema (per record):
    ts            : float epoch seconds
    ts_iso        : str ISO timestamp (UTC)
    origin        : str — one of saturation_meta_fetch / user_request /
                    planner_default / unknown (driven by plan metadata)
    trigger       : str — raw plan.metadata.trigger if any, else ""
    goal_id       : str — best-effort, "" if not on the plan
    goal_description : str — truncated to 120 chars
    topics_requested : list[str] — from plan.action_params.topics
    max_articles  : int
    duration_ms   : float
    outcome       : str — success / partial / no_articles / skipped / error
    skipped_reason: str — only when outcome=skipped (e.g. outside_learning_window)
    error         : str — only when outcome=error
    result        : dict — full stats from run_fetch_session
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_LOG_PATH = Path("meta_data/fetch_decisions.jsonl")


def classify_origin(plan) -> Dict[str, str]:
    """
    Map a Plan into a stable observability origin tag.

    Priority order:
    1. plan.metadata["trigger"] verbatim (set by planner_core for saturation
       META fetches, conversation-driven flows, etc.)
    2. user_request — when action_params has explicit topics (came from
       a USER goal, e.g. /learn or chat).
    3. planner_default — autonomous planner picked FETCH on its own.

    Returns:
        {"origin": "<tag>", "trigger": "<raw plan trigger or empty>"}
    """
    raw_trigger = ""
    metadata = getattr(plan, "metadata", None) or {}
    if isinstance(metadata, dict):
        raw_trigger = str(metadata.get("trigger") or "")

    if raw_trigger:
        return {"origin": raw_trigger, "trigger": raw_trigger}

    action_params = getattr(plan, "action_params", None) or {}
    topics = action_params.get("topics") if isinstance(action_params, dict) else None
    if topics:
        return {"origin": "user_request", "trigger": ""}

    return {"origin": "planner_default", "trigger": ""}


def _build_record(
    plan,
    *,
    outcome: str,
    duration_ms: float,
    result: Optional[Dict[str, Any]] = None,
    skipped_reason: str = "",
    error: str = "",
) -> Dict[str, Any]:
    """Assemble the JSONL record for a single fetch decision."""
    classification = classify_origin(plan)

    action_params = getattr(plan, "action_params", None) or {}
    topics: List[str] = []
    max_articles = 3
    if isinstance(action_params, dict):
        topics_raw = action_params.get("topics") or []
        if isinstance(topics_raw, list):
            topics = [str(t) for t in topics_raw]
        max_articles = int(action_params.get("max_articles", 3) or 3)

    goal_id = str(getattr(plan, "goal_id", "") or "")
    goal_description = str(getattr(plan, "goal_description", "") or "")[:120]

    now = time.time()
    record: Dict[str, Any] = {
        "ts": now,
        "ts_iso": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "origin": classification["origin"],
        "trigger": classification["trigger"],
        "goal_id": goal_id,
        "goal_description": goal_description,
        "topics_requested": topics,
        "max_articles": max_articles,
        "duration_ms": round(duration_ms, 1),
        "outcome": outcome,
    }
    if skipped_reason:
        record["skipped_reason"] = skipped_reason
    if error:
        record["error"] = error
    if result:
        record["result"] = result
    return record


def log_fetch_decision(
    plan,
    *,
    outcome: str,
    duration_ms: float,
    result: Optional[Dict[str, Any]] = None,
    skipped_reason: str = "",
    error: str = "",
    log_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Append one record to fetch_decisions.jsonl and emit a one-line INFO log.

    Never raises — observability is best-effort. Returns the record (also
    handy for tests).
    """
    record = _build_record(
        plan,
        outcome=outcome,
        duration_ms=duration_ms,
        result=result,
        skipped_reason=skipped_reason,
        error=error,
    )

    target = log_path or DEFAULT_LOG_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("fetch_decisions.jsonl write skipped: %s", exc)

    # One-liner so journalctl shows the why without parsing JSONL
    summary_bits = [
        f"origin={record['origin']}",
        f"outcome={outcome}",
        f"topics={record['topics_requested']}",
    ]
    if result:
        summary_bits.append(
            f"fetched={result.get('articles_fetched', 0)}/"
            f"{result.get('topics_searched', 0)}"
        )
        summary_bits.append(
            f"rss_filtered={result.get('rss_filtered', 0)}"
        )
    if skipped_reason:
        summary_bits.append(f"reason={skipped_reason}")
    if error:
        summary_bits.append(f"error={error[:80]}")
    summary_bits.append(f"dur_ms={record['duration_ms']:.0f}")

    logger.info("[FETCH_DECISION] %s", " ".join(summary_bits))
    return record
