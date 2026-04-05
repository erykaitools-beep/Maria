"""
FreeVsPaidPlanner (V3 Phase C, Module 9)

Decides whether to use free (local Ollama) or paid (NIM API, Claude, Codex)
resources for a given task. Considers budget, urgency, quality needs.

Wraps V2: TokenBudget, LLMRouter routing decisions.

Usage:
    planner = FreeVsPaidPlanner(ctx)
    recommendation = planner.recommend("learn")
    # recommendation.strategy="local_only", recommendation.reason="..."
    plan_rec = planner.recommend_for_plan(execution_plan)
    # plan_rec.overall_strategy="mostly_local"
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from agent_core.orchestrator.cost_estimator import CostEstimator

logger = logging.getLogger(__name__)


class ResourceStrategy(Enum):
    """Resource allocation strategy."""
    LOCAL_ONLY = "local_only"
    PREFER_LOCAL = "prefer_local"
    MIXED = "mixed"
    PREFER_PAID = "prefer_paid"
    PAID_REQUIRED = "paid_required"


@dataclass(frozen=True)
class ActionRecommendation:
    """Resource recommendation for a single action."""
    action: str
    strategy: ResourceStrategy
    backend: str
    reason: str
    fallback_backend: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "strategy": self.strategy.value,
            "backend": self.backend,
            "reason": self.reason,
            "fallback_backend": self.fallback_backend,
        }


@dataclass
class PlanRecommendation:
    """Resource recommendation for an entire plan."""
    overall_strategy: ResourceStrategy
    step_recommendations: List[ActionRecommendation] = field(default_factory=list)
    nim_budget_ok: bool = True
    estimated_nim_spend: int = 0
    savings_if_local: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_strategy": self.overall_strategy.value,
            "step_recommendations": [r.to_dict() for r in self.step_recommendations],
            "nim_budget_ok": self.nim_budget_ok,
            "estimated_nim_spend": self.estimated_nim_spend,
            "savings_if_local": self.savings_if_local,
            "warnings": self.warnings,
        }

    def describe(self) -> str:
        labels = {
            ResourceStrategy.LOCAL_ONLY: "Calkowicie lokalne (darmowe)",
            ResourceStrategy.PREFER_LOCAL: "Glownie lokalne, opcjonalnie NIM",
            ResourceStrategy.MIXED: "Mieszane (lokalne + NIM API)",
            ResourceStrategy.PREFER_PAID: "Glownie NIM API",
            ResourceStrategy.PAID_REQUIRED: "Wymaga zewnetrznego API",
        }
        lines = [f"Strategia: {labels.get(self.overall_strategy, '?')}"]
        if self.estimated_nim_spend > 0:
            lines.append(f"Szacowane zuzycie NIM: ~{self.estimated_nim_spend} tokenow")
        if self.savings_if_local > 0:
            lines.append(
                f"Oszczednosc przy trybie lokalnym: ~{self.savings_if_local} tokenow"
            )
        if self.warnings:
            for w in self.warnings:
                lines.append(f"  [!] {w}")
        return "\n".join(lines)


# Actions that always run locally (zero LLM or local-only)
_ALWAYS_LOCAL = {
    "learn", "exam", "review", "evaluate", "maintenance",
    "noop", "fetch", "critique", "effector",
}

# Actions that use NIM API
_NIM_ACTIONS = {"self_analyze", "creative", "validate"}

# Actions that use external CLI (Codex/Claude)
_EXTERNAL_ACTIONS = {"ask_expert"}


class FreeVsPaidPlanner:
    """Decides resource allocation strategy for actions and plans."""

    def __init__(self, ctx):
        self._ctx = ctx
        self._cost_estimator = CostEstimator(ctx)

    def recommend(self, action: str) -> ActionRecommendation:
        """
        Recommend resource strategy for a single action.

        Args:
            action: Action name

        Returns:
            ActionRecommendation with strategy and backend.
        """
        if action in _ALWAYS_LOCAL:
            return ActionRecommendation(
                action=action,
                strategy=ResourceStrategy.LOCAL_ONLY,
                backend="ollama",
                reason="Akcja dziala na lokalnym LLM (darmowa)",
            )

        if action in _NIM_ACTIONS:
            budget = self._cost_estimator.get_budget_status()
            if budget.nim_status == "DEPLETED" or not budget.nim_rpm_available:
                return ActionRecommendation(
                    action=action,
                    strategy=ResourceStrategy.PREFER_LOCAL,
                    backend="ollama",
                    reason="NIM API niedostepne - fallback na lokalny LLM",
                    fallback_backend=None,
                )
            if budget.nim_status == "LOW":
                return ActionRecommendation(
                    action=action,
                    strategy=ResourceStrategy.MIXED,
                    backend="nim",
                    reason="NIM API dostepne ale budzet niski",
                    fallback_backend="ollama",
                )
            return ActionRecommendation(
                action=action,
                strategy=ResourceStrategy.PREFER_PAID,
                backend="nim",
                reason="NIM API dostepne, lepsza jakosc analizy",
                fallback_backend="ollama",
            )

        if action in _EXTERNAL_ACTIONS:
            budget = self._cost_estimator.get_budget_status()
            if budget.codex_calls_remaining_hour > 0:
                return ActionRecommendation(
                    action=action,
                    strategy=ResourceStrategy.MIXED,
                    backend="codex",
                    reason=f"Codex dostepny ({budget.codex_calls_remaining_hour}/h)",
                    fallback_backend="nim",
                )
            if budget.nim_rpm_available and budget.nim_status != "DEPLETED":
                return ActionRecommendation(
                    action=action,
                    strategy=ResourceStrategy.MIXED,
                    backend="nim",
                    reason="Codex wyczerpany, NIM jako fallback",
                    fallback_backend="ollama",
                )
            return ActionRecommendation(
                action=action,
                strategy=ResourceStrategy.LOCAL_ONLY,
                backend="ollama",
                reason="Zewnetrzne API niedostepne",
            )

        # Unknown action -> local fallback
        return ActionRecommendation(
            action=action,
            strategy=ResourceStrategy.LOCAL_ONLY,
            backend="ollama",
            reason="Nieznana akcja - domyslnie lokalne LLM",
        )

    def recommend_for_plan(self, plan) -> PlanRecommendation:
        """
        Recommend resource strategy for an entire execution plan.

        Args:
            plan: ExecutionPlan from ExecutionPlanBuilder

        Returns:
            PlanRecommendation with per-step and overall strategy.
        """
        recommendations = []
        nim_spend = 0
        has_paid = False
        has_local = False

        for step in plan.steps:
            rec = self.recommend(step.action)
            recommendations.append(rec)

            if rec.backend == "nim":
                cost = self._cost_estimator.estimate_action(step.action)
                nim_spend += cost.nim_tokens
                has_paid = True
            elif rec.backend in ("codex", "claude"):
                has_paid = True
            else:
                has_local = True

        # Determine overall strategy
        if not has_paid:
            overall = ResourceStrategy.LOCAL_ONLY
        elif not has_local:
            overall = ResourceStrategy.PAID_REQUIRED
        elif nim_spend > 5000:
            overall = ResourceStrategy.PREFER_PAID
        else:
            overall = ResourceStrategy.MIXED

        # Budget check
        budget = self._cost_estimator.get_budget_status()
        budget_ok = nim_spend <= budget.nim_remaining_today

        result = PlanRecommendation(
            overall_strategy=overall,
            step_recommendations=recommendations,
            nim_budget_ok=budget_ok,
            estimated_nim_spend=nim_spend,
            savings_if_local=nim_spend,  # All NIM could theoretically be local
        )

        if not budget_ok:
            result.warnings.append(
                f"Plan zuzyje ~{nim_spend} NIM tokenow, "
                f"ale zostalo tylko {budget.nim_remaining_today}"
            )

        return result

    def get_summary(self) -> Dict[str, Any]:
        """Get current resource allocation summary."""
        budget = self._cost_estimator.get_budget_status()
        return {
            "nim_available": budget.nim_status != "DEPLETED",
            "nim_remaining_today": budget.nim_remaining_today,
            "nim_status": budget.nim_status,
            "claude_available": budget.claude_calls_remaining_hour > 0,
            "claude_remaining_hour": budget.claude_calls_remaining_hour,
            "codex_available": budget.codex_calls_remaining_hour > 0,
            "codex_remaining_hour": budget.codex_calls_remaining_hour,
            "local_available": budget.local_available,
            "recommended_default": "ollama",
        }
