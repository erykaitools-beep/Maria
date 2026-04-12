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
    telegram_bridge: Any = None      # TelegramBridge (operator notifications)
    codex_client: Any = None         # CodexClient (ChatGPT encyclopedia via Codex CLI)
    semantic_search: Any = None       # SemanticMemory (nomic-embed-text vector store)
    trace_store: Any = None            # TraceStore (Phase 1 decision traceability)
    memory_query: Any = None           # MemoryQuery (Phase 2 unified memory API)
    vision_cortex: Any = None          # VisionCortex (visual perception pipeline)
    code_agent: Any = None             # CodeAgent (autonomous coding)

    # Faza F/G + Learning Upgrade
    cross_validator: Any = None        # CrossValidator (multi-source validation)
    dispute_log: Any = None            # DisputeLog (Faza F disputes)
    critic_agent: Any = None           # CriticAgent (Faza G knowledge quality)
    bulletin_store: Any = None         # BulletinStore (cognitive bulletin board)
    knowledge_auditor: Any = None      # KnowledgeAuditor (gap detection)
    gap_planner: Any = None            # GapPlanner (learning gap strategies)
    expert_bridge: Any = None          # ExpertBridge (audit-aware expert queries)

    # Phase 5 Effector Safety
    authority_manager: Any = None      # AuthorityManager (5-level authority)
    approval_queue: Any = None         # ApprovalQueue (HITL approval workflow)
    tool_budget: Any = None            # ToolBudgetManager (per-tool rate limits)

    # V3 Orchestrator (Phase A)
    capability_router: Any = None      # CapabilityRouter (registry-based dispatch)
    context_builder: Any = None        # ContextBuilder (self-awareness aggregator)
    user_facing_self_model: Any = None # UserFacingSelfModel (V3 Module 3)
    onboarding_flow: Any = None        # OnboardingFlow (V3 Module 2)
    task_orchestrator: Any = None      # TaskOrchestrator (V3 Module 4)
    product_shell: Any = None          # ProductShell (V3 Module 14)

    # User profile
    user_profile: Any = None             # UserProfile (operator knowledge)

    # Reminders & Todos
    reminder_store: Any = None           # ReminderStore (time-triggered notifications)
    todo_store: Any = None               # TodoStore (task tracking)
    reminder_scheduler: Any = None       # ReminderScheduler (tick-based firing)

    # Proactive Contact
    proactive_scheduler: Any = None      # ProactiveScheduler (Maria initiates contact)

    # Self-Model Maturity (K15)
    capability_manifest: Any = None      # CapabilityManifest (K15)
    honesty_protocol: Any = None         # HonestyProtocol (K15.2)
    state_reporter: Any = None           # StateReporter (K15.1)
    growth_awareness: Any = None         # GrowthAwareness (K15.3)
    weather_sensor: Any = None           # WeatherSensor (M3)

    # Operational Perception (Faza 3)
    holiday_sensor: Any = None           # HolidaySensor (PL+DE)
    system_sensor: Any = None            # SystemSensor v2
    workspace_sensor: Any = None         # WorkspaceSensor
    salience_filter: Any = None          # SalienceFilter
    perception_fusion: Any = None        # PerceptionFusion

    # Digital Hands (Faza 4)
    task_executor: Any = None            # TaskExecutor
    execution_journal: Any = None        # ExecutionJournal
    web_researcher: Any = None           # WebResearcher
    file_manager: Any = None             # FileManager

    # REPL state
    last_result: Any = None

    # Configuration
    brain_model: str = "llama3.1:8b"

    def update(self, **kwargs) -> None:
        """Update context fields. Used after reload."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
