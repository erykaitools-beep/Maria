"""Self-model intent handler for IntentRouter."""

from __future__ import annotations

import re
from typing import Optional


_IDENTITY_PATTERN = re.compile(r"\bkim\s+jestes\b|\bkim\s+jesteś\b", re.IGNORECASE)
_CAPABILITY_PATTERN = re.compile(r"\bco\s+umiesz\b", re.IGNORECASE)


def match_self_model(task: str, self_model) -> Optional["IntentMatch"]:
    """Match self-model queries and return an IntentMatch."""
    if self_model is None:
        return None

    text = task or ""
    is_identity = bool(_IDENTITY_PATTERN.search(text))
    is_capability = bool(_CAPABILITY_PATTERN.search(text))
    if not (is_identity or is_capability):
        return None

    from agent_core.routing.intent_router import IntentMatch

    query_type = "capabilities" if is_capability else "identity"
    return IntentMatch(
        handler=lambda: _describe(self_model, query_type),
        handler_name="self_model",
        args={"query_type": query_type},
        path="local",
        confidence=0.9,
        est_cost_tokens=0,
        est_latency_ms=100,
    )


def _describe(self_model, query_type: str) -> str:
    if query_type == "capabilities" and hasattr(
        self_model,
        "describe_capabilities_text",
    ):
        return str(self_model.describe_capabilities_text())

    if hasattr(self_model, "describe_self"):
        return str(self_model.describe_self())

    if hasattr(self_model, "get_status"):
        return str(self_model.get_status())

    raise AttributeError("self_model has no supported describe method")


__all__ = ["match_self_model"]
