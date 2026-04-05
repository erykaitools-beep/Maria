"""
V3 Orchestrator layer - productization modules on top of V2 cognitive core.

Phase A: Foundation
  Module 1: UnifiedLauncher (maria.py)
  Module 2: OnboardingFlow
  Module 3: UserFacingSelfModel
"""

from agent_core.orchestrator.self_model_facade import UserFacingSelfModel
from agent_core.orchestrator.onboarding import OnboardingFlow

__all__ = ["UserFacingSelfModel", "OnboardingFlow"]
