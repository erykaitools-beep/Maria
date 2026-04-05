"""
V3 Orchestrator layer - productization modules on top of V2 cognitive core.

Phase A: Foundation
  Module 1: UnifiedLauncher (maria.py)
  Module 2: OnboardingFlow
  Module 3: UserFacingSelfModel

Phase B: Task Pipeline
  Module 4: TaskOrchestrator
  Module 5: TaskDecomposer
  Module 6: ExecutionPlanBuilder
"""

from agent_core.orchestrator.self_model_facade import UserFacingSelfModel
from agent_core.orchestrator.onboarding import OnboardingFlow
from agent_core.orchestrator.task_decomposer import TaskDecomposer
from agent_core.orchestrator.execution_plan import ExecutionPlanBuilder
from agent_core.orchestrator.task_orchestrator import TaskOrchestrator

__all__ = [
    "UserFacingSelfModel",
    "OnboardingFlow",
    "TaskDecomposer",
    "ExecutionPlanBuilder",
    "TaskOrchestrator",
]
