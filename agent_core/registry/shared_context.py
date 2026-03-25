"""
SharedContext - Dependency container for REPL modules.

Bundles shared objects that modules need access to.
Created once during init_brain() and passed to all modules.
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SharedContext:
    """
    Shared dependencies for all REPL modules.

    Created by main.py during initialization.
    Passed to each module's init() method.
    """
    # Core objects (set during init_brain)
    brain: Any = None
    brain_loop: Any = None
    semantic_memory: Any = None
    episodic_memory: Any = None

    # Subsystems (set by modules during init)
    homeostasis_core: Any = None
    identity_store: Any = None
    consciousness: Any = None
    conversation_memory: Any = None
    perception_buffer: Any = None  # PerceptionBuffer (Warstwa 1)
    sandbox_manager: Any = None    # SandboxManager (Kontrakt K2)
    goal_store: Any = None         # GoalStore (Kontrakt K3)
    evaluation_observer: Any = None  # EvaluationObserver (Kontrakt K4)
    planner_core: Any = None         # PlannerCore (Warstwa 2, Kontrakt K5)
    knowledge_analyzer: Any = None   # KnowledgeAnalyzer (topic awareness)
    world_model: Any = None          # WorldModel (Kontrakt K6)
    autonomy_policy: Any = None      # AutonomyPolicy (Kontrakt K7)
    deliberation: Any = None         # Deliberation (Kontrakt K8)
    meta_cognition: Any = None       # MetaCognition (Kontrakt K9)
    action_safety: Any = None        # ActionSafety (Kontrakt K10)
    experiment_system: Any = None    # ExperimentSystem (Kontrakt K11)
    model_scheduler: Any = None      # ModelScheduler (multi-organ model stack)
    openclaw_client: Any = None      # OpenClawClient (effector, ADR-016)
    self_analysis: Any = None        # SelfAnalysis (K12, cognitive loop)
    creative_module: Any = None      # CreativeModule (K13, strategic reflection)
    llm_tape: Any = None             # LLMTape (raw LLM interaction log)
    evidence_collector: Any = None   # EvidenceCollector (Phase 2, grounded responses)

    # REPL state
    last_result: Any = None

    # Configuration
    brain_model: str = "llama3.1:8b"

    def update(self, **kwargs) -> None:
        """Update context fields. Used after reload."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
