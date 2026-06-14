"""Time intent handler for IntentRouter."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional


_TIME_PATTERN = re.compile(
    r"\b(godzina|time|data|dzien|dzień|pora)\b",
    re.IGNORECASE,
)


def match_time(task: str, time_awareness) -> Optional["IntentMatch"]:
    """Match time/date queries and return an IntentMatch."""
    if time_awareness is None:
        return None

    if not _TIME_PATTERN.search(task or ""):
        return None

    from agent_core.routing.intent_router import IntentMatch

    return IntentMatch(
        handler=lambda: _format_time(time_awareness),
        handler_name="time",
        args={},
        path="local",
        confidence=0.9,
        est_cost_tokens=0,
        est_latency_ms=50,
    )


def _format_time(time_awareness) -> str:
    if hasattr(time_awareness, "get_context"):
        return str(time_awareness.get_context())
    if hasattr(time_awareness, "format_time"):
        return str(time_awareness.format_time())
    return datetime.now().strftime("Jest %H:%M.")


__all__ = ["match_time"]
