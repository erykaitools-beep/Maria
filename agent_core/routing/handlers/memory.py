"""Memory intent handler for IntentRouter."""

from __future__ import annotations

import json
import re
from typing import Optional


_TOPIC_PATTERNS = [
    re.compile(r"\bco\s+wiesz\s+o\s+(?P<topic>.+?)(?:\?|$|\.)", re.IGNORECASE),
    re.compile(r"\bpamietasz\s+(?P<topic>.+?)(?:\?|$|\.)", re.IGNORECASE),
    re.compile(r"\bpamiętasz\s+(?P<topic>.+?)(?:\?|$|\.)", re.IGNORECASE),
]
_GAPS_PATTERN = re.compile(r"\bgaps\b", re.IGNORECASE)


def match_memory(task: str, memory_query) -> Optional["IntentMatch"]:
    """Match memory queries and return an IntentMatch."""
    if memory_query is None:
        return None

    text = (task or "").strip()
    if not text:
        return None

    if _GAPS_PATTERN.search(text):
        from agent_core.routing.intent_router import IntentMatch

        return IntentMatch(
            handler=lambda: _format_gaps(memory_query),
            handler_name="memory",
            args={"query_type": "gaps"},
            path="local",
            confidence=0.85,
            est_cost_tokens=0,
            est_latency_ms=100,
        )

    for pattern in _TOPIC_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        topic = _clean_topic(match.group("topic"))
        if not topic:
            continue

        from agent_core.routing.intent_router import IntentMatch

        return IntentMatch(
            handler=lambda topic=topic: _format_topic(memory_query, topic),
            handler_name="memory",
            args={"topic": topic},
            path="local",
            confidence=0.9,
            est_cost_tokens=0,
            est_latency_ms=100,
        )

    return None


def _clean_topic(topic: str) -> str:
    return re.sub(r"\s+", " ", topic or "").strip(" ?.,")


def _format_topic(memory_query, topic: str) -> str:
    if hasattr(memory_query, "get_topic_summary"):
        summary = memory_query.get_topic_summary(topic)
        return json.dumps(summary, ensure_ascii=False, sort_keys=True)

    if hasattr(memory_query, "query_topic"):
        results = memory_query.query_topic(topic)
        if not results:
            return f"Nie mam zapisanej wiedzy o: {topic}."
        return "\n".join(str(getattr(r, "content", r)) for r in results[:5])

    raise AttributeError("memory_query has no supported topic method")


def _format_gaps(memory_query) -> str:
    if hasattr(memory_query, "get_knowledge_gaps"):
        gaps = memory_query.get_knowledge_gaps()
        return json.dumps(gaps, ensure_ascii=False, sort_keys=True)
    raise AttributeError("memory_query has no get_knowledge_gaps method")


__all__ = ["match_memory"]
