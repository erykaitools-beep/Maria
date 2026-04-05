"""
ExecutionPlanBuilder (V3 Phase B, Module 6)

Builds an execution plan from a DecomposedTask, enriched with
constraints, K7 classifications, estimated cost (LLM calls),
and readiness checks.

Wraps V2: ActionExecutor dispatch paths, K7 autonomy policy,
CapabilityRouter availability.

Usage:
    builder = ExecutionPlanBuilder(ctx)
    plan = builder.build(decomposed_task)
    # plan.steps_with_constraints = [...]
    # plan.total_llm_calls = 7
    # plan.blocked_steps = []
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent_core.orchestrator.task_decomposer import DecomposedTask, TaskStep

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StepConstraint:
    """Constraint on a single execution step."""
    step_order: int
    action: str
    description: str
    estimated_llm_calls: int
    k7_classification: str
    is_available: bool
    is_blocked: bool
    block_reason: str
    requires_approval: bool


@dataclass
class ExecutionPlan:
    """Complete execution plan ready for user review."""
    task_description: str
    category: str
    topic: Optional[str]
    feasibility: str
    infeasibility_reason: str
    steps: List[StepConstraint]
    total_llm_calls: int
    total_steps: int
    blocked_steps: List[StepConstraint]
    requires_approval: bool
    requires_network: bool
    estimated_mode: str
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_executable(self) -> bool:
        """Can this plan run without blockers?"""
        return self.feasibility == "feasible" and len(self.blocked_steps) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_description": self.task_description,
            "category": self.category,
            "topic": self.topic,
            "feasibility": self.feasibility,
            "infeasibility_reason": self.infeasibility_reason,
            "steps": [
                {
                    "order": s.step_order,
                    "action": s.action,
                    "description": s.description,
                    "estimated_llm_calls": s.estimated_llm_calls,
                    "k7_classification": s.k7_classification,
                    "is_available": s.is_available,
                    "is_blocked": s.is_blocked,
                    "block_reason": s.block_reason,
                    "requires_approval": s.requires_approval,
                }
                for s in self.steps
            ],
            "total_llm_calls": self.total_llm_calls,
            "total_steps": self.total_steps,
            "blocked_count": len(self.blocked_steps),
            "is_executable": self.is_executable,
            "requires_approval": self.requires_approval,
            "requires_network": self.requires_network,
            "estimated_mode": self.estimated_mode,
            "warnings": self.warnings,
        }

    def describe(self) -> str:
        """Human-readable plan summary in Polish."""
        lines = [f"Plan wykonania: {self.task_description}"]
        if self.topic:
            lines.append(f"Temat: {self.topic}")
        lines.append(f"Kategoria: {self.category}")
        lines.append(f"Wykonalnosc: {self.feasibility}")
        lines.append("")

        for step in self.steps:
            status = "BLOKADA" if step.is_blocked else "OK"
            approval = " [wymaga zatwierdzenia]" if step.requires_approval else ""
            lines.append(
                f"  {step.step_order + 1}. [{status}] {step.description}"
                f" ({step.action}, ~{step.estimated_llm_calls} LLM calls)"
                f"{approval}"
            )
            if step.is_blocked:
                lines.append(f"     Powod: {step.block_reason}")

        lines.append("")
        lines.append(f"Lacznie: {self.total_steps} krokow, ~{self.total_llm_calls} wywolan LLM")
        if self.blocked_steps:
            lines.append(f"Zablokowane: {len(self.blocked_steps)} krokow")
        if self.warnings:
            lines.append("Ostrzezenia:")
            for w in self.warnings:
                lines.append(f"  - {w}")

        return "\n".join(lines)


# Estimated LLM calls per action type
_LLM_CALL_ESTIMATES = {
    "learn": 3,
    "exam": 2,
    "review": 2,
    "evaluate": 0,
    "fetch": 0,
    "maintenance": 0,
    "self_analyze": 2,
    "creative": 1,
    "critique": 0,
    "validate": 1,
    "ask_expert": 1,
    "effector": 0,
    "noop": 0,
}

# Actions that need operator approval (restricted in K7)
_APPROVAL_ACTIONS = {"effector"}


class ExecutionPlanBuilder:
    """Builds execution plans from decomposed tasks."""

    def __init__(self, ctx):
        """
        Args:
            ctx: SharedContext instance
        """
        self._ctx = ctx

    def build(self, decomposed: DecomposedTask) -> ExecutionPlan:
        """
        Build execution plan from a decomposed task.

        Enriches each step with availability, K7 status, LLM cost,
        and checks for blockers.

        Args:
            decomposed: DecomposedTask from TaskDecomposer

        Returns:
            ExecutionPlan with constraints and feasibility.
        """
        step_constraints = []
        warnings = []

        for task_step in decomposed.steps:
            constraint = self._build_step_constraint(task_step)
            step_constraints.append(constraint)

        blocked = [s for s in step_constraints if s.is_blocked]
        total_llm = sum(s.estimated_llm_calls for s in step_constraints)
        needs_approval = any(s.requires_approval for s in step_constraints)

        # Mode-based warnings
        mode = self._get_current_mode()
        if mode == "REDUCED":
            warnings.append("Tryb REDUCED - ciezkie operacje LLM moga byc blokowane")
        elif mode in ("SLEEP", "SURVIVAL"):
            warnings.append(f"Tryb {mode} - wiekszosc operacji niedostepna")

        # Network warning
        if decomposed.requires_network:
            warnings.append("Plan wymaga dostepu do sieci (fetch)")

        # Blocked steps warning
        if blocked:
            warnings.append(f"{len(blocked)} krokow zablokowanych - plan moze nie wykonac sie w calosci")

        return ExecutionPlan(
            task_description=decomposed.original_input,
            category=decomposed.category.value,
            topic=decomposed.topic,
            feasibility=decomposed.feasibility,
            infeasibility_reason=decomposed.infeasibility_reason,
            steps=step_constraints,
            total_llm_calls=total_llm,
            total_steps=len(step_constraints),
            blocked_steps=blocked,
            requires_approval=needs_approval,
            requires_network=decomposed.requires_network,
            estimated_mode=mode,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_step_constraint(self, step: TaskStep) -> StepConstraint:
        """Build constraint for a single step."""
        available = self._is_action_available(step.action)
        blocked, block_reason = self._is_action_blocked(step.action)
        llm_calls = _LLM_CALL_ESTIMATES.get(step.action, 1) * step.estimated_actions
        needs_approval = step.action in _APPROVAL_ACTIONS

        return StepConstraint(
            step_order=step.order,
            action=step.action,
            description=step.description,
            estimated_llm_calls=llm_calls,
            k7_classification=step.k7_classification,
            is_available=available,
            is_blocked=blocked,
            block_reason=block_reason,
            requires_approval=needs_approval,
        )

    def _is_action_available(self, action: str) -> bool:
        """Check if action handler is registered."""
        router = getattr(self._ctx, "capability_router", None)
        if router:
            return router.is_available(action)
        return True  # Assume available if no router

    def _is_action_blocked(self, action: str) -> tuple:
        """Check K7 autonomy policy for blocks.

        Returns:
            (is_blocked: bool, reason: str)
        """
        policy = self._ctx.autonomy_policy
        if not policy:
            return (False, "")

        try:
            classification = policy.classify_action(action)
            if hasattr(classification, "level"):
                level = classification.level
            elif hasattr(classification, "value"):
                level = classification.value
            else:
                level = str(classification)

            if level == "forbidden":
                return (True, f"Akcja {action} jest zabroniona (K7 FORBIDDEN)")
        except Exception:
            pass

        return (False, "")

    def _get_current_mode(self) -> str:
        """Get homeostasis mode."""
        core = self._ctx.homeostasis_core
        if core:
            mode = getattr(core, "_current_mode", None)
            if mode:
                return mode.name if hasattr(mode, "name") else str(mode)
        return "UNKNOWN"
