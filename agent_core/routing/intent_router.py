"""
IntentRouter core for cheap-first task dispatch.

Phase 1 is an isolated library: it routes and can execute local handlers,
but OpenClaw paths are placeholders until T-002 wiring.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Optional

from agent_core.effector.intent_detector import TaskIntentDetector
from agent_core.routing.handlers.memory import match_memory
from agent_core.routing.handlers.self_model import match_self_model
from agent_core.routing.handlers.time import match_time
from agent_core.routing.handlers.weather import match_weather

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntentMatch:
    """Result of IntentRouter.route()."""

    handler: Callable[[], str]
    handler_name: str
    args: Dict[str, Any]
    path: str
    confidence: float
    est_cost_tokens: int
    est_latency_ms: int
    fallback: Optional["IntentMatch"] = None


def _openclaw_placeholder(task: str) -> str:
    return f"[INTENT_ROUTER] would dispatch to OpenClaw: {task}"


class IntentRouter:
    """Route tasks to the cheapest viable path first."""

    def __init__(
        self,
        weather_sensor=None,
        time_awareness=None,
        memory_query=None,
        self_model=None,
        capability_router=None,
        task_intent_detector=None,
        effector_coordinator=None,
        llm_classifier_fn=None,
        enabled: Optional[bool] = None,
    ):
        self._weather_sensor = weather_sensor
        self._time_awareness = time_awareness
        self._memory_query = memory_query
        self._self_model = self_model
        self._capability_router = capability_router
        self._task_intent_detector = task_intent_detector or TaskIntentDetector()
        self._effector_coordinator = effector_coordinator
        self._llm_classifier_fn = llm_classifier_fn
        self._enabled = self._resolve_enabled(enabled)

    @staticmethod
    def _resolve_enabled(enabled: Optional[bool]) -> bool:
        if enabled is not None:
            return bool(enabled)
        value = os.environ.get("INTENT_ROUTER_ENABLED", "false")
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def route(self, task: str) -> IntentMatch:
        """Route a task without executing OpenClaw."""
        task = task or ""
        raw_fallback = self._raw_openclaw_match(task)

        if not self._enabled:
            return IntentMatch(
                handler=lambda: _openclaw_placeholder(task),
                handler_name="legacy",
                args={"task": task},
                path="openclaw_raw",
                confidence=0.0,
                est_cost_tokens=0,
                est_latency_ms=8000,
            )

        for matcher, sensor in (
            (match_weather, self._weather_sensor),
            (match_time, self._time_awareness),
            # TODO(T-002): add status handler when StatusCollector exists.
            (match_memory, self._memory_query),
            (match_self_model, self._self_model),
        ):
            match = matcher(task, sensor)
            if match:
                logger.debug(
                    "IntentRouter route: path=%s handler=%s",
                    match.path,
                    match.handler_name,
                )
                return replace(match, fallback=raw_fallback)

        pattern_match = self._openclaw_pattern_match(task, raw_fallback)
        if pattern_match:
            logger.debug(
                "IntentRouter route: path=%s handler=%s",
                pattern_match.path,
                pattern_match.handler_name,
            )
            return pattern_match

        # Step 3 LLM classifier is intentionally skipped in Phase 1.
        logger.debug("IntentRouter route: path=openclaw_raw handler=openclaw_raw")
        return raw_fallback

    def route_and_execute(self, task: str) -> str:
        """
        Route and execute only local handlers.

        OpenClaw paths return a placeholder until T-002 wires the real
        EffectorCoordinator dispatch.
        """
        match = self.route(task)
        if match.path in ("openclaw_pattern", "openclaw_raw"):
            return _openclaw_placeholder(task)

        try:
            return str(match.handler())
        except Exception as exc:
            logger.warning(
                "IntentRouter local handler failed: handler=%s error=%s",
                match.handler_name,
                exc,
            )
            if match.fallback:
                return _openclaw_placeholder(task)
            raise

    def list_handlers(self) -> List[Dict[str, Any]]:
        """Return handler metadata for help and cost previews."""
        return [
            {
                "name": "weather",
                "regex_summary": "weather|pogoda|prognoza + city",
                "est_latency_ms": 500,
            },
            {
                "name": "time",
                "regex_summary": "godzina|time|data|dzien|pora",
                "est_latency_ms": 50,
            },
            {
                "name": "memory",
                "regex_summary": "co wiesz o|pamietasz|gaps",
                "est_latency_ms": 100,
            },
            {
                "name": "self_model",
                "regex_summary": "kim jestes|co umiesz",
                "est_latency_ms": 100,
            },
            {
                "name": "openclaw_pattern",
                "regex_summary": "write/read/fetch/search/exec patterns",
                "est_latency_ms": 8000,
            },
            {
                "name": "openclaw_raw",
                "regex_summary": "fallback for unmatched tasks",
                "est_latency_ms": 10000,
            },
        ]

    def _openclaw_pattern_match(
        self,
        task: str,
        fallback: IntentMatch,
    ) -> Optional[IntentMatch]:
        if not self._task_intent_detector:
            return None

        detected = self._task_intent_detector.detect(task)
        if not detected:
            return None

        return IntentMatch(
            handler=lambda: _openclaw_placeholder(task),
            handler_name=detected.tool_name,
            args={
                "tool_name": detected.tool_name,
                "tool_args": dict(detected.tool_args),
                "pattern_id": detected.pattern_id,
            },
            path="openclaw_pattern",
            confidence=detected.confidence,
            est_cost_tokens=0,
            est_latency_ms=8000,
            fallback=fallback,
        )

    @staticmethod
    def _raw_openclaw_match(task: str) -> IntentMatch:
        return IntentMatch(
            handler=lambda: _openclaw_placeholder(task),
            handler_name="openclaw_raw",
            args={"task": task},
            path="openclaw_raw",
            confidence=0.1,
            est_cost_tokens=0,
            est_latency_ms=10000,
        )


__all__ = ["IntentMatch", "IntentRouter"]
