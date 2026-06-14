"""
TimeEstimator (V3 Phase C, Module 8)

Estimates execution time for plan steps based on model timeouts
and historical latency data from LLM tape.

Wraps V2: execution_budget timeouts, model_registry latency budgets,
LLMTape historical stats.

Usage:
    estimator = TimeEstimator(ctx)
    est = estimator.estimate_action("learn")
    # est.seconds=120, est.label="~2 min"
    plan_time = estimator.estimate_plan(execution_plan)
    # plan_time.total_seconds=480, plan_time.label="~8 min"
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TimeEstimate:
    """Time estimate for a single action."""
    action: str
    seconds: float
    label: str
    confidence: str = "medium"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "seconds": self.seconds,
            "label": self.label,
            "confidence": self.confidence,
        }


@dataclass
class PlanTimeEstimate:
    """Aggregated time estimate for an execution plan."""
    total_seconds: float = 0.0
    label: str = ""
    step_estimates: List[TimeEstimate] = field(default_factory=list)
    includes_model_loading: bool = False
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_seconds": self.total_seconds,
            "label": self.label,
            "step_estimates": [e.to_dict() for e in self.step_estimates],
            "includes_model_loading": self.includes_model_loading,
            "warnings": self.warnings,
        }

    def describe(self) -> str:
        lines = [f"Szacowany czas: {self.label}"]
        for est in self.step_estimates:
            lines.append(f"  {est.action}: {est.label} [{est.confidence}]")
        if self.includes_model_loading:
            lines.append("  (wlicza czas ladowania modelu)")
        if self.warnings:
            for w in self.warnings:
                lines.append(f"  [!] {w}")
        return "\n".join(lines)


def _format_duration(seconds: float) -> str:
    """Format seconds to human-readable Polish string."""
    if seconds < 60:
        return f"~{int(seconds)} sek"
    elif seconds < 3600:
        minutes = seconds / 60
        if minutes < 2:
            return "~1 min"
        return f"~{int(minutes)} min"
    else:
        hours = seconds / 3600
        if hours < 2:
            return "~1 godz"
        return f"~{hours:.1f} godz"


# Per-action time estimates in seconds
# Based on: execution_budget timeouts + observed llm_tape latencies
_ACTION_TIMES = {
    # Learning actions (local LLM, ~40-120s per call)
    "learn": {"seconds": 180.0, "confidence": "medium",
              "note": "3 wywolania LLM po ~60s"},
    "exam": {"seconds": 120.0, "confidence": "medium",
             "note": "2 wywolania LLM"},
    "review": {"seconds": 120.0, "confidence": "medium",
               "note": "2 wywolania LLM"},

    # Zero-LLM actions (fast)
    "evaluate": {"seconds": 5.0, "confidence": "high",
                 "note": "Rule-based, brak LLM"},
    "maintenance": {"seconds": 3.0, "confidence": "high",
                    "note": "Odczyt metryk"},
    "noop": {"seconds": 0.0, "confidence": "high", "note": ""},
    "critique": {"seconds": 5.0, "confidence": "high",
                 "note": "Rule-based analiza"},

    # Network actions
    "fetch": {"seconds": 15.0, "confidence": "low",
              "note": "Zalezy od sieci (Wikipedia/RSS)"},

    # NIM API actions (~5-30s per call)
    "self_analyze": {"seconds": 30.0, "confidence": "medium",
                     "note": "NIM API analiza"},
    "creative": {"seconds": 20.0, "confidence": "medium",
                 "note": "NIM API refleksja"},
    "validate": {"seconds": 25.0, "confidence": "medium",
                 "note": "NIM API walidacja"},

    # External CLI actions (slow)
    "ask_expert": {"seconds": 60.0, "confidence": "low",
                   "note": "Codex/NIM, zalezy od obciazenia"},

    # Effector
    "effector": {"seconds": 30.0, "confidence": "low",
                 "note": "OpenClaw, zalezy od narzedzia"},
}

# Cold start penalty for models that need loading
_COLD_START_SECONDS = {
    "planner": 15.0,   # qwen3:8b loading
    "coder": 15.0,     # qwen2.5-coder:7b loading
    "memory": 5.0,     # nomic-embed-text loading
}


class TimeEstimator:
    """Estimates execution time for actions and plans."""

    def __init__(self, ctx):
        self._ctx = ctx

    def estimate_action(self, action: str, multiplier: int = 1) -> TimeEstimate:
        """
        Estimate time for a single action.

        Args:
            action: Action name
            multiplier: Repetition count

        Returns:
            TimeEstimate with seconds and human label.
        """
        template = _ACTION_TIMES.get(action, {"seconds": 60.0, "confidence": "low"})
        total = template["seconds"] * multiplier

        return TimeEstimate(
            action=action,
            seconds=total,
            label=_format_duration(total),
            confidence=template.get("confidence", "low"),
        )

    def estimate_plan(self, plan) -> PlanTimeEstimate:
        """
        Estimate total time for an ExecutionPlan.

        Args:
            plan: ExecutionPlan from ExecutionPlanBuilder

        Returns:
            PlanTimeEstimate with total and per-step.
        """
        result = PlanTimeEstimate()
        needs_cold_start = set()

        for step in plan.steps:
            est = self.estimate_action(step.action)
            result.step_estimates.append(est)
            result.total_seconds += est.seconds

            # Track cold start needs
            if step.action in ("self_analyze", "creative", "validate"):
                needs_cold_start.add("planner")
            if step.action == "ask_expert":
                needs_cold_start.add("planner")

        # Add cold start penalties
        cold_start_total = sum(
            _COLD_START_SECONDS.get(model, 0) for model in needs_cold_start
        )
        if cold_start_total > 0:
            result.total_seconds += cold_start_total
            result.includes_model_loading = True

        result.label = _format_duration(result.total_seconds)

        # Warnings
        if result.total_seconds > 300:
            result.warnings.append(
                f"Plan moze zajac {_format_duration(result.total_seconds)} - "
                f"przekracza budzet 5-minutowy na epizod"
            )

        mode = self._get_mode()
        if mode == "REDUCED":
            result.warnings.append(
                "Tryb REDUCED - czasy moga byc dluzsze (ograniczone LLM)"
            )

        return result

    def get_historical_avg(self, action: str) -> Optional[float]:
        """
        Get historical average latency for an action from LLM tape.

        Returns:
            Average latency in seconds, or None if no data.
        """
        tape = getattr(self._ctx, "llm_tape", None)
        if not tape:
            return None

        try:
            stats = tape.get_stats(period_hours=168)  # Last 7 days
            avg_ms = stats.get("avg_latency_ms", 0)
            if avg_ms > 0:
                return avg_ms / 1000.0
        except Exception:
            pass
        return None

    def _get_mode(self) -> str:
        core = self._ctx.homeostasis_core
        if core:
            mode = getattr(getattr(core, "state", None), "mode", None)
            if mode:
                return mode.name if hasattr(mode, "name") else str(mode)
        return "UNKNOWN"
