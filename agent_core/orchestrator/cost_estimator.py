"""
CostEstimator (V3 Phase C, Module 7)

Estimates LLM call costs for execution plan steps.
Tracks three cost dimensions:
  - NIM API tokens (external, metered)
  - Local Ollama inference (free but uses RAM/CPU)
  - External CLI tools (Claude 3/h, Codex 10/h - rate-limited)

Wraps V2: TokenBudget, ModelRegistry, LLMTape stats.

Usage:
    estimator = CostEstimator(ctx)
    cost = estimator.estimate_action("learn")
    # cost.nim_tokens=1200, cost.local_calls=3, cost.external_calls=0
    budget = estimator.get_budget_status()
    # budget.nim_remaining_today=82000, budget.nim_status="OK"
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActionCost:
    """Estimated cost for a single action."""
    action: str
    nim_tokens: int = 0
    local_llm_calls: int = 0
    external_calls: int = 0
    description: str = ""

    @property
    def is_free(self) -> bool:
        """True if no paid API calls needed."""
        return self.nim_tokens == 0 and self.external_calls == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "nim_tokens": self.nim_tokens,
            "local_llm_calls": self.local_llm_calls,
            "external_calls": self.external_calls,
            "is_free": self.is_free,
            "description": self.description,
        }


@dataclass
class PlanCost:
    """Aggregated cost for an entire execution plan."""
    total_nim_tokens: int = 0
    total_local_calls: int = 0
    total_external_calls: int = 0
    step_costs: List[ActionCost] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_free(self) -> bool:
        return self.total_nim_tokens == 0 and self.total_external_calls == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_nim_tokens": self.total_nim_tokens,
            "total_local_calls": self.total_local_calls,
            "total_external_calls": self.total_external_calls,
            "is_free": self.is_free,
            "step_costs": [c.to_dict() for c in self.step_costs],
            "warnings": self.warnings,
        }

    def describe(self) -> str:
        lines = ["Szacowany koszt:"]
        if self.is_free:
            lines.append("  Calkowicie darmowy (lokalne LLM)")
        else:
            if self.total_nim_tokens > 0:
                lines.append(f"  NIM API: ~{self.total_nim_tokens} tokenow")
            if self.total_external_calls > 0:
                lines.append(f"  Zewnetrzne wywolania: {self.total_external_calls}")
        lines.append(f"  Lokalne LLM: {self.total_local_calls} wywolan")
        if self.warnings:
            for w in self.warnings:
                lines.append(f"  [!] {w}")
        return "\n".join(lines)


@dataclass
class BudgetStatus:
    """Current budget state across all LLM backends."""
    nim_remaining_today: int
    nim_status: str
    nim_rpm_available: bool
    claude_calls_remaining_hour: int
    codex_calls_remaining_hour: int
    local_available: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nim_remaining_today": self.nim_remaining_today,
            "nim_status": self.nim_status,
            "nim_rpm_available": self.nim_rpm_available,
            "claude_calls_remaining_hour": self.claude_calls_remaining_hour,
            "codex_calls_remaining_hour": self.codex_calls_remaining_hour,
            "local_available": self.local_available,
        }


# Per-action cost estimates (tokens for NIM, calls for local)
# Based on observed averages from llm_tape.jsonl
_ACTION_COSTS = {
    "learn": {"local": 3, "nim": 0, "desc": "3 lokalne wywolania LLM (ekstrakcja wiedzy)"},
    "exam": {"local": 2, "nim": 0, "desc": "2 lokalne wywolania (generowanie + ocena)"},
    "review": {"local": 2, "nim": 0, "desc": "2 lokalne wywolania (powtorka)"},
    "evaluate": {"local": 0, "nim": 0, "desc": "Zero LLM (rule-based metryki)"},
    "fetch": {"local": 0, "nim": 0, "desc": "Zero LLM (HTTP fetch)"},
    "maintenance": {"local": 0, "nim": 0, "desc": "Zero LLM (metryki systemu)"},
    "self_analyze": {"local": 0, "nim": 2500, "desc": "NIM API analiza (~2500 tokenow)"},
    "creative": {"local": 0, "nim": 1500, "desc": "NIM API refleksja (~1500 tokenow)"},
    "critique": {"local": 0, "nim": 0, "desc": "Zero LLM (rule-based)"},
    "validate": {"local": 0, "nim": 1200, "desc": "NIM API walidacja (~1200 tokenow)"},
    "ask_expert": {"local": 0, "nim": 0, "external": 1, "desc": "1 wywolanie Codex/NIM"},
    "effector": {"local": 0, "nim": 0, "desc": "Zero LLM (OpenClaw narzedzie)"},
    "noop": {"local": 0, "nim": 0, "desc": "Brak kosztu"},
}


class CostEstimator:
    """Estimates LLM costs for actions and plans."""

    def __init__(self, ctx):
        self._ctx = ctx

    def estimate_action(self, action: str, multiplier: int = 1) -> ActionCost:
        """
        Estimate cost for a single action type.

        Args:
            action: Action name (learn, exam, fetch, etc.)
            multiplier: How many times this action repeats

        Returns:
            ActionCost with token and call estimates.
        """
        template = _ACTION_COSTS.get(action, {"local": 1, "nim": 0})
        return ActionCost(
            action=action,
            nim_tokens=template.get("nim", 0) * multiplier,
            local_llm_calls=template.get("local", 0) * multiplier,
            external_calls=template.get("external", 0) * multiplier,
            description=template.get("desc", ""),
        )

    def estimate_plan(self, plan) -> PlanCost:
        """
        Estimate total cost for an ExecutionPlan.

        Args:
            plan: ExecutionPlan from ExecutionPlanBuilder

        Returns:
            PlanCost with aggregated costs and warnings.
        """
        result = PlanCost()

        for step in plan.steps:
            cost = self.estimate_action(step.action)
            result.step_costs.append(cost)
            result.total_nim_tokens += cost.nim_tokens
            result.total_local_calls += cost.local_llm_calls
            result.total_external_calls += cost.external_calls

        # Check budget
        budget = self.get_budget_status()
        if result.total_nim_tokens > 0 and result.total_nim_tokens > budget.nim_remaining_today:
            result.warnings.append(
                f"Plan wymaga ~{result.total_nim_tokens} NIM tokenow, "
                f"zostalo {budget.nim_remaining_today} na dzis"
            )
        if not budget.nim_rpm_available and result.total_nim_tokens > 0:
            result.warnings.append("NIM API: limit RPM wyczerpany (poczekaj chwile)")

        if result.total_external_calls > 0:
            if budget.codex_calls_remaining_hour <= 0:
                result.warnings.append("Codex: limit na godzine wyczerpany")

        return result

    def get_budget_status(self) -> BudgetStatus:
        """
        Get current budget across all LLM backends.

        Returns:
            BudgetStatus with remaining capacity.
        """
        nim_remaining = 100000
        nim_status = "OK"
        nim_rpm = True
        claude_remaining = 3
        codex_remaining = 10
        local_ok = True

        # NIM budget
        try:
            from agent_core.llm.token_budget import TokenBudget
            budget = self._get_token_budget()
            if budget:
                nim_remaining = budget.get_remaining_today()
                nim_status = budget.get_budget_status()
                nim_rpm = budget.can_use_nim()
        except Exception:
            pass

        # Claude rate
        try:
            claude = getattr(self._ctx, "claude_client", None)
            if claude and hasattr(claude, "_call_timestamps"):
                import time
                now = time.time()
                recent = [t for t in claude._call_timestamps if now - t < 3600]
                max_hour = getattr(claude, "MAX_CALLS_PER_HOUR", 3)
                claude_remaining = max(0, max_hour - len(recent))
        except Exception:
            pass

        # Codex rate
        try:
            codex = self._ctx.codex_client
            if codex and hasattr(codex, "_call_timestamps"):
                import time
                now = time.time()
                recent = [t for t in codex._call_timestamps if now - t < 3600]
                max_hour = getattr(codex, "MAX_CALLS_PER_HOUR", 10)
                codex_remaining = max(0, max_hour - len(recent))
        except Exception:
            pass

        return BudgetStatus(
            nim_remaining_today=nim_remaining,
            nim_status=nim_status,
            nim_rpm_available=nim_rpm,
            claude_calls_remaining_hour=claude_remaining,
            codex_calls_remaining_hour=codex_remaining,
            local_available=local_ok,
        )

    def _get_token_budget(self):
        """Try to get TokenBudget from LLM router."""
        try:
            router = getattr(self._ctx, "brain", None)
            if router and hasattr(router, "token_budget"):
                return router.token_budget
            llm_router = getattr(self._ctx, "llm_router", None)
            if llm_router and hasattr(llm_router, "token_budget"):
                return llm_router.token_budget
        except Exception:
            pass
        return None
