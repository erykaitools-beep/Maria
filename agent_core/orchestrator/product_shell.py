"""
ProductShell (V3 Phase E, Module 14)

Unified V3 facade - single entry point for all orchestrator capabilities.
Combines Phase A-D modules into a coherent API that Web UI, REPL,
and Telegram can consume.

This is the "product" interface: submit task -> get plan -> approve -> track.

Usage:
    shell = ProductShell(ctx)

    # End-to-end task flow
    result = shell.do("naucz sie fizyki kwantowej")
    print(result["plan"]["describe"])
    shell.approve(result["task_id"])
    print(shell.progress(result["task_id"]))

    # Discovery
    print(shell.who_am_i())
    print(shell.what_can_i_do())
    print(shell.limitations())
"""

import logging
from typing import Any, Dict, List, Optional

from agent_core.orchestrator.self_model_facade import UserFacingSelfModel
from agent_core.orchestrator.onboarding import OnboardingFlow
from agent_core.orchestrator.task_orchestrator import TaskOrchestrator
from agent_core.orchestrator.cost_estimator import CostEstimator
from agent_core.orchestrator.time_estimator import TimeEstimator
from agent_core.orchestrator.free_vs_paid import FreeVsPaidPlanner
from agent_core.orchestrator.execution_router import ExecutionRouter
from agent_core.orchestrator.tool_registry import ToolCapabilityRegistry
from agent_core.orchestrator.progress_tracker import TaskProgressTracker
from agent_core.orchestrator.limitation_reporter import LimitationReporter

logger = logging.getLogger(__name__)


class ProductShell:
    """Unified V3 product facade."""

    def __init__(self, ctx):
        self._ctx = ctx
        self.self_model = UserFacingSelfModel(ctx)
        self.onboarding = OnboardingFlow(ctx, self.self_model)
        self.orchestrator = TaskOrchestrator(ctx)
        self.cost_estimator = CostEstimator(ctx)
        self.time_estimator = TimeEstimator(ctx)
        self.resource_planner = FreeVsPaidPlanner(ctx)
        self.execution_router = ExecutionRouter(ctx)
        self.tool_registry = ToolCapabilityRegistry(ctx)
        self.progress_tracker = TaskProgressTracker(ctx)
        self.limitation_reporter = LimitationReporter(ctx)

    # ------------------------------------------------------------------
    # Identity & Discovery (Phase A)
    # ------------------------------------------------------------------

    def who_am_i(self) -> str:
        """Self-description text."""
        return self.self_model.describe_self()

    def what_can_i_do(self) -> str:
        """Capabilities text."""
        return self.tool_registry.describe()

    def limitations(self) -> str:
        """Current limitations text."""
        return self.limitation_reporter.describe()

    def get_status(self) -> Dict[str, Any]:
        """Full system status for dashboard."""
        return {
            "identity": self.self_model.get_status(),
            "capabilities": self.tool_registry.get_summary(),
            "services": self.tool_registry.list_external_services(),
            "budget": self.cost_estimator.get_budget_status().to_dict(),
            "resources": self.resource_planner.get_summary(),
            "progress": self.progress_tracker.get_summary(),
            "limitations": self.limitation_reporter.get_report(),
            "onboarding_completed": self.onboarding.is_completed(),
        }

    # ------------------------------------------------------------------
    # Task Flow (Phase B + C + D)
    # ------------------------------------------------------------------

    def do(
        self,
        task_description: str,
        auto_approve: bool = False,
        priority: float = 0.8,
    ) -> Dict[str, Any]:
        """
        Submit a task with full enrichment: decomposition, plan,
        cost, time, and resource recommendations.

        Args:
            task_description: What to do (natural language PL/EN)
            auto_approve: Skip review, create goal immediately
            priority: Goal priority (0.0-1.0)

        Returns:
            Rich result dict with plan, cost, time, resources.
        """
        # Submit through orchestrator
        submit = self.orchestrator.submit(
            task_description,
            auto_approve=auto_approve,
            priority=priority,
        )

        # Enrich with cost, time, resource estimates
        plan_cost = self.cost_estimator.estimate_plan(submit.plan)
        plan_time = self.time_estimator.estimate_plan(submit.plan)
        plan_resources = self.resource_planner.recommend_for_plan(submit.plan)

        return {
            "task_id": submit.task_id,
            "auto_approved": submit.auto_approved,
            "goal_id": submit.goal_id,
            "decomposition": submit.decomposition.to_dict(),
            "plan": submit.plan.to_dict(),
            "plan_describe": submit.plan.describe(),
            "cost": plan_cost.to_dict(),
            "cost_describe": plan_cost.describe(),
            "time": plan_time.to_dict(),
            "time_describe": plan_time.describe(),
            "resources": plan_resources.to_dict(),
            "resources_describe": plan_resources.describe(),
            "is_executable": submit.plan.is_executable,
            "is_free": plan_cost.is_free,
        }

    def approve(self, task_id: str, priority: float = 0.8) -> Optional[str]:
        """Approve a planned task. Returns goal_id."""
        return self.orchestrator.approve(task_id, priority)

    def cancel(self, task_id: str, reason: str = "user_cancelled") -> bool:
        """Cancel a task."""
        return self.orchestrator.cancel(task_id, reason)

    def progress(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task progress."""
        return self.orchestrator.get_progress(task_id)

    def tasks(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List tasks."""
        return self.orchestrator.list_tasks(status)

    # ------------------------------------------------------------------
    # Execution (Phase D)
    # ------------------------------------------------------------------

    def execute(self, action: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Execute a single action directly."""
        return self.execution_router.execute(action, params)

    def can_execute(self, action: str) -> Dict[str, Any]:
        """Check if an action can run right now."""
        return self.execution_router.can_execute(action)

    # ------------------------------------------------------------------
    # Convenience for text output
    # ------------------------------------------------------------------

    def do_and_describe(self, task_description: str) -> str:
        """Submit task and return human-readable summary."""
        result = self.do(task_description)

        lines = [
            f"Zadanie: {task_description}",
            f"Kategoria: {result['decomposition']['category']}",
            f"Temat: {result['decomposition'].get('topic', '-')}",
            "",
            result["plan_describe"],
            "",
            result["cost_describe"],
            "",
            result["time_describe"],
            "",
            result["resources_describe"],
        ]

        if result["is_executable"]:
            lines.append(f"\nTask ID: {result['task_id']}")
            if result["auto_approved"]:
                lines.append(f"Goal ID: {result['goal_id']} (auto-approved)")
            else:
                lines.append("Uzyj /v3 approve <task_id> aby zatwierdzic")
        else:
            lines.append("\nPlan nie jest wykonalny - sprawdz ograniczenia powyzej")

        return "\n".join(lines)
