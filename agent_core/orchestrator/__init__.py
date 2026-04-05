"""
V3 Orchestrator layer - productization modules on top of V2 cognitive core.

Phase A: Foundation (Module 1-3)
Phase B: Task Pipeline (Module 4-6)
Phase C: Practical Intelligence (Module 7-9)
Phase D: Execution Bridge (Module 10-13)
"""

from agent_core.orchestrator.self_model_facade import UserFacingSelfModel
from agent_core.orchestrator.onboarding import OnboardingFlow
from agent_core.orchestrator.task_decomposer import TaskDecomposer
from agent_core.orchestrator.execution_plan import ExecutionPlanBuilder
from agent_core.orchestrator.task_orchestrator import TaskOrchestrator
from agent_core.orchestrator.cost_estimator import CostEstimator
from agent_core.orchestrator.time_estimator import TimeEstimator
from agent_core.orchestrator.free_vs_paid import FreeVsPaidPlanner
from agent_core.orchestrator.execution_router import ExecutionRouter
from agent_core.orchestrator.tool_registry import ToolCapabilityRegistry
from agent_core.orchestrator.progress_tracker import TaskProgressTracker
from agent_core.orchestrator.limitation_reporter import LimitationReporter

__all__ = [
    "UserFacingSelfModel", "OnboardingFlow",
    "TaskDecomposer", "ExecutionPlanBuilder", "TaskOrchestrator",
    "CostEstimator", "TimeEstimator", "FreeVsPaidPlanner",
    "ExecutionRouter", "ToolCapabilityRegistry",
    "TaskProgressTracker", "LimitationReporter",
]
