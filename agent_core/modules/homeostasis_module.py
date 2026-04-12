"""Homeostasis REPL commands: /homeostasis [status|start|stop|events|summary]."""

import logging
import threading
import time
from datetime import datetime

from agent_core.registry import MariaModule, CommandInfo
from agent_core.homeostasis.core import HomeostasisCore
from agent_core.homeostasis.state_model import Mode
from agent_core.homeostasis.event_logger import get_event_logger
from agent_core.memory.manager import MemoryManager
from agent_core.llm.manager import LLMManager

logger = logging.getLogger(__name__)


class HomeostasisModule(MariaModule):
    """Homeostasis monitoring and control."""

    name = "homeostasis"
    description = "Autonomous regulation loop (sensors, mode, alerts)"

    def __init__(self):
        self._thread = None
        self._running = False

    def init(self, ctx) -> bool:
        self.ctx = ctx

        # Initialize homeostasis core if not already done
        if ctx.homeostasis_core is None:
            try:
                memory_manager = MemoryManager()
                llm_manager = LLMManager()
                ctx.homeostasis_core = HomeostasisCore(
                    memory_manager=memory_manager,
                    llm_manager=llm_manager,
                    executor=None,
                )
                print("[Homeostasis] [OK] Initialized")
            except Exception as e:
                print(f"[Homeostasis] [WARN] Init failed: {e}")
                return False

        # Initialize ModelScheduler (multi-organ model stack)
        core = ctx.homeostasis_core
        if core:
            try:
                from agent_core.llm.model_scheduler import ModelScheduler
                from agent_core.llm.model_registry import ModelRole

                scheduler = ModelScheduler()
                scheduler.load_health()

                # Register MODEL-02 (EXECUTOR) which is already loaded by OllamaBrain
                brain_model = getattr(ctx, 'brain_model', 'llama3.1:8b')
                scheduler.register_running_model(ModelRole.EXECUTOR, brain_model)

                ctx.model_scheduler = scheduler
                core.set_model_scheduler(scheduler)

                # Wire to LLMRouter if available
                if ctx.brain and hasattr(ctx.brain, 'set_model_scheduler'):
                    ctx.brain.set_model_scheduler(scheduler)

                print("[Homeostasis] [OK] ModelScheduler initialized")
            except Exception as e:
                logger.debug(f"ModelScheduler not initialized: {e}")

        # Initialize SemanticMemory (nomic-embed-text vector store)
        if core:
            try:
                from agent_core.semantic import SemanticMemory
                from pathlib import Path as _Path
                from maria_core.sys.config import BASE_DIR as _BASE
                _data_dir = str(_BASE / "meta_data")
                sem = SemanticMemory(data_dir=_data_dir)
                if sem.initialize():
                    ctx.semantic_search = sem
                    logger.info("[Homeostasis] SemanticMemory initialized (nomic-embed-text)")

                    # Start background indexing (knowledge, beliefs, hints)
                    from agent_core.semantic.indexer import start_background_indexing
                    start_background_indexing(
                        sem,
                        data_dir=_data_dir,
                        memory_dir=str(_BASE / "memory"),
                        input_dir=str(_BASE / "input"),
                    )
                else:
                    ctx.semantic_search = sem  # Still usable, will try on-demand
                    logger.info("[Homeostasis] SemanticMemory loaded (model not warm yet)")
            except Exception as e:
                logger.warning(f"[Homeostasis] SemanticMemory failed: {e}")

        # Initialize LLM Tape (raw interaction logging)
        if core:
            try:
                from agent_core.llm.llm_tape import LLMTape
                from pathlib import Path
                tape_path = Path(ctx.config.BASE_DIR) / "meta_data" / "llm_tape.jsonl"
                tape = LLMTape(path=tape_path)
                ctx.llm_tape = tape

                # Wire to LLMRouter
                if ctx.brain and hasattr(ctx.brain, 'set_llm_tape'):
                    ctx.brain.set_llm_tape(tape)
                # Wire to OllamaBrain (for direct brain usage / Web UI)
                _brain = getattr(ctx.brain, 'ollama', ctx.brain)
                if _brain and hasattr(_brain, 'set_llm_tape'):
                    _brain.set_llm_tape(tape)

                print("[Homeostasis] [OK] LLM Tape initialized")
            except Exception as e:
                logger.debug(f"LLM Tape not initialized: {e}")

        # Initialize OperatorModel (K14 - replaces UserProfile)
        try:
            from agent_core.operator.operator_model import OperatorModel
            from agent_core.operator.rhythm_detector import RhythmDetector
            operator_model = OperatorModel()
            ctx.user_profile = operator_model  # backward compat name in SharedContext
            ctx.operator_model = operator_model
            # RhythmDetector - seed from proactive contact history
            rhythm_detector = RhythmDetector()
            try:
                import json
                _history = Path("meta_data/proactive_contacts.jsonl")
                if _history.exists():
                    _ts_list = []
                    with open(_history, "r", encoding="utf-8") as _f:
                        for _line in _f:
                            _line = _line.strip()
                            if _line:
                                try:
                                    _rec = json.loads(_line)
                                    if _rec.get("reason") != "morning_summary":
                                        _ts_list.append(_rec.get("timestamp", 0))
                                except (json.JSONDecodeError, KeyError):
                                    pass
                    # Also seed from proactive state (operator contact timestamps)
                    _state_file = Path("meta_data/proactive_state.json")
                    if _state_file.exists():
                        _state = json.loads(_state_file.read_text(encoding="utf-8"))
                        _last = _state.get("last_operator_contact", 0)
                        if _last > 0:
                            _ts_list.append(_last)
                    rhythm_detector.seed(_ts_list)
            except Exception:
                pass
            ctx.rhythm_detector = rhythm_detector
            # Update OperatorModel rhythm from detector
            if rhythm_detector.sample_count >= 5:
                operator_model.set_rhythm(rhythm_detector.get_rhythm())
            # Wire to brain for system prompt injection
            _brain = getattr(ctx.brain, 'ollama', ctx.brain)
            if _brain and hasattr(_brain, 'set_user_profile'):
                _brain.set_user_profile(operator_model)
            print(f"[Homeostasis] [OK] OperatorModel initialized (operator: {operator_model.get_name()}, rhythm samples: {rhythm_detector.sample_count})")
        except Exception as e:
            logger.debug(f"OperatorModel not initialized: {e}")

        # Initialize PerceptionBuffer (Warstwa 1)
        if core:
            try:
                from agent_core.perception.buffer import PerceptionBuffer
                perception_buffer = PerceptionBuffer(maxlen=200)
                core.set_perception_buffer(perception_buffer)
                ctx.perception_buffer = perception_buffer
                print("[Homeostasis] [OK] PerceptionBuffer initialized (maxlen=200)")
            except Exception as e:
                logger.debug(f"PerceptionBuffer not initialized: {e}")

        # Initialize SandboxManager (Kontrakt K2)
        if core:
            try:
                from maria_core.sys.config import (
                    SANDBOX_DIR, KNOWLEDGE_INDEX, LONGTERM_MEMORY, EXAM_RESULTS,
                )
                from agent_core.sandbox.manager import SandboxManager

                sandbox_mgr = SandboxManager(
                    sandbox_base_dir=SANDBOX_DIR,
                    production_index=KNOWLEDGE_INDEX,
                    production_memory=LONGTERM_MEMORY,
                    production_exams=EXAM_RESULTS,
                )
                sandbox_mgr.startup_recovery()
                ctx.sandbox_manager = sandbox_mgr
                print("[Homeostasis] [OK] SandboxManager initialized")
            except Exception as e:
                logger.debug(f"SandboxManager not initialized: {e}")

        # Initialize GoalStore (Kontrakt K3)
        try:
            from pathlib import Path
            from maria_core.sys.config import BASE_DIR
            from agent_core.goals.store import GoalStore

            goals_path = BASE_DIR / "meta_data" / "goals.jsonl"
            goal_store = GoalStore(goals_path)
            goal_store.load()
            goal_store.seed_if_empty()
            goal_store.expire_proposed()
            if goal_store.stats()["total"] > 0:
                goal_store.save()
            ctx.goal_store = goal_store
            print(f"[Homeostasis] [OK] GoalStore initialized ({goal_store.stats()['total']} goals)")
        except Exception as e:
            logger.debug(f"GoalStore not initialized: {e}")

        # Initialize EvaluationObserver (Kontrakt K4, READ-ONLY)
        try:
            from maria_core.sys.config import BASE_DIR, KNOWLEDGE_INDEX, EXAM_RESULTS
            from agent_core.evaluation.observer import EvaluationObserver

            meta = BASE_DIR / "meta_data"
            eval_observer = EvaluationObserver(
                knowledge_index_path=KNOWLEDGE_INDEX,
                exam_results_path=EXAM_RESULTS,
                teacher_plans_path=meta / "teacher_plans.jsonl",
                homeostasis_events_path=meta / "homeostasis_events.jsonl",
                personality_experiences_path=meta / "personality_experiences.jsonl",
                reports_path=meta / "evaluation_reports.jsonl",
            )
            ctx.evaluation_observer = eval_observer
            print("[Homeostasis] [OK] EvaluationObserver initialized (READ-ONLY)")
        except Exception as e:
            logger.debug(f"EvaluationObserver not initialized: {e}")

        # Pass semantic_memory to core for sleep processing
        if core and ctx.semantic_memory:
            session_id = 0
            experience_tracker = None
            if ctx.consciousness:
                session_id = ctx.consciousness.identity.get_session_count()
                experience_tracker = ctx.consciousness.experience_tracker
            elif ctx.identity_store:
                session_id = ctx.identity_store.get_session_count()
            core.set_semantic_memory(
                ctx.semantic_memory,
                session_id=session_id,
                experience_tracker=experience_tracker,
            )

        # Wire teacher agent for autonomous learning during idle
        if core and ctx.brain and hasattr(ctx.brain, '_ask_once'):
            try:
                from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
                from agent_core.teacher.teacher_agent import TeacherAgent
                from agent_core.modules.teacher_module import TeacherModule

                analyzer = KnowledgeAnalyzer()
                teacher = TeacherAgent(router=ctx.brain, knowledge_analyzer=analyzer)

                # Wire learning/exam functions via teacher module helper
                helper = TeacherModule()
                helper.init(ctx)
                teacher.set_learn_fn(helper._learn_chunk_wrapped)
                teacher.set_exam_fn(helper._run_exam_wrapped)

                core.set_teacher_agent(teacher)
                print("[Homeostasis] [OK] Teacher agent wired for auto-learning")
            except Exception as e:
                logger.debug(f"Teacher agent not wired: {e}")

        # Wire PlannerCore (Warstwa 2) - replaces teacher auto-trigger in Phase 10
        if core:
            try:
                from agent_core.planner.planner_core import PlannerCore

                planner = PlannerCore()
                planner.set_homeostasis_core(core)

                if ctx.perception_buffer:
                    planner.set_perception_buffer(ctx.perception_buffer)
                if ctx.goal_store:
                    planner.set_goal_store(ctx.goal_store)
                if ctx.evaluation_observer:
                    planner.set_evaluation_observer(ctx.evaluation_observer)
                if ctx.sandbox_manager:
                    planner.set_sandbox_manager(ctx.sandbox_manager)

                # Reuse the teacher agent that was already wired above
                if hasattr(core, '_teacher_agent') and core._teacher_agent:
                    planner.set_teacher_agent(core._teacher_agent)

                # Knowledge analyzer for snapshot + topic awareness
                try:
                    from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
                    analyzer = KnowledgeAnalyzer()
                    planner.set_knowledge_analyzer(analyzer)
                    ctx.knowledge_analyzer = analyzer
                except Exception:
                    pass

                # World Model (K6) for structured knowledge representation
                try:
                    from agent_core.world_model import WorldModel
                    world_model = WorldModel()
                    loaded = world_model.load()
                    if loaded == 0:
                        stats = world_model.build()
                        world_model.save()
                        total = sum(stats.values())
                        print(f"[Homeostasis] [OK] WorldModel built ({total} beliefs)")
                    else:
                        print(f"[Homeostasis] [OK] WorldModel loaded ({loaded} beliefs)")
                    planner.set_world_model(world_model)
                    ctx.world_model = world_model
                except Exception as e:
                    logger.debug(f"WorldModel not initialized: {e}")

                # Autonomy Policy (K7) for action governance
                try:
                    from agent_core.autonomy import AutonomyPolicy, AuthorityManager
                    from agent_core.autonomy.approval_queue import ApprovalQueue
                    from agent_core.autonomy.tool_budget import ToolBudgetManager

                    # Phase 5: Authority Manager (persisted level)
                    authority_manager = AuthorityManager()
                    ctx.authority_manager = authority_manager

                    autonomy_policy = AutonomyPolicy(
                        authority_manager=authority_manager,
                    )
                    planner.set_autonomy_policy(autonomy_policy)
                    ctx.autonomy_policy = autonomy_policy

                    # Phase 5: Approval Queue for effector HITL
                    approval_queue = ApprovalQueue()
                    planner.set_approval_queue(approval_queue)
                    ctx.approval_queue = approval_queue

                    # Phase 5: Per-tool budget manager
                    tool_budget = ToolBudgetManager(
                        tool_rate_limits=authority_manager.get_config().tool_rate_limits,
                        failure_cooldown_sec=authority_manager.get_config().failure_cooldown_sec,
                        max_consecutive_failures=authority_manager.get_config().max_consecutive_failures,
                    )
                    ctx.tool_budget = tool_budget

                    auth_level = authority_manager.get_level().value
                    print(f"[Homeostasis] [OK] AutonomyPolicy wired (K7, authority={auth_level})")
                except Exception as e:
                    logger.debug(f"AutonomyPolicy not initialized: {e}")

                # Deliberation (K8) for multi-step strategies
                try:
                    from agent_core.deliberation import Deliberation
                    deliberation = Deliberation()
                    planner.set_deliberation(deliberation)
                    ctx.deliberation = deliberation
                    print("[Homeostasis] [OK] Deliberation wired (K8)")
                except Exception as e:
                    logger.debug(f"Deliberation not initialized: {e}")

                # Meta-Cognition (K9) for self-reflection
                try:
                    from agent_core.meta_cognition import MetaCognition
                    meta_cognition = MetaCognition()
                    planner.set_meta_cognition(meta_cognition)
                    ctx.meta_cognition = meta_cognition
                    print("[Homeostasis] [OK] MetaCognition wired (K9)")
                except Exception as e:
                    logger.debug(f"MetaCognition not initialized: {e}")

                # Action Safety (K10) for unified action audit
                try:
                    from agent_core.action_safety import ActionSafety
                    action_safety = ActionSafety()
                    action_safety.set_homeostasis_core(core)
                    if ctx.goal_store:
                        action_safety.set_goal_store(ctx.goal_store)
                    if ctx.knowledge_analyzer:
                        action_safety.set_knowledge_analyzer(ctx.knowledge_analyzer)
                    planner.set_action_safety(action_safety)
                    ctx.action_safety = action_safety
                    print("[Homeostasis] [OK] ActionSafety wired (K10)")
                except Exception as e:
                    logger.debug(f"ActionSafety not initialized: {e}")

                # Experiment System (K11) for autonomous parameter tuning
                try:
                    from agent_core.experiment import ExperimentSystem
                    experiment_system = ExperimentSystem()
                    experiment_system.set_homeostasis_core(core)
                    if ctx.evaluation_observer:
                        experiment_system.set_evaluation_observer(ctx.evaluation_observer)
                    if hasattr(core, '_teacher_agent') and core._teacher_agent:
                        experiment_system.set_teacher_agent(core._teacher_agent)
                    planner.set_experiment_system(experiment_system)
                    ctx.experiment_system = experiment_system
                    print("[Homeostasis] [OK] ExperimentSystem wired (K11)")
                except Exception as e:
                    logger.debug(f"ExperimentSystem not initialized: {e}")

                # OpenClaw Effector (ADR-016) - optional, graceful fallback
                # NOTE: Do NOT use openclaw.health_check() here - it triggers
                # `nodes run -- echo ok` which loads qwen2.5:3b (3GB, 6 CPU cores)
                # and causes mode transition to REDUCED. Use lightweight pgrep instead.
                try:
                    from agent_core.effector import OpenClawClient
                    import subprocess as _sp
                    _gw_check = _sp.run(
                        ["pgrep", "-f", "openclaw.*gateway"],
                        capture_output=True, timeout=2,
                    )
                    if _gw_check.returncode == 0:
                        openclaw = OpenClawClient()
                        planner.set_openclaw_client(openclaw)
                        ctx.openclaw_client = openclaw
                        print("[Homeostasis] [OK] OpenClaw effector wired (gateway detected)")
                    else:
                        logger.debug("OpenClaw gateway not running, effector disabled")
                except Exception as e:
                    logger.debug(f"OpenClaw not initialized: {e}")

                # Cross-Validator (Faza F) - multi-source learning validation
                # Uses NIM as secondary LLM to validate knowledge learned by Ollama
                try:
                    from agent_core.cross_validation import CrossValidator, DisputeLog

                    dispute_log = DisputeLog()
                    cross_validator = CrossValidator(
                        source_name="nim",
                        dispute_log=dispute_log,
                    )

                    # Wire secondary LLM: NIM if available via brain (LLMRouter)
                    _brain = ctx.brain if hasattr(ctx, 'brain') else None
                    if _brain and hasattr(_brain, 'nim') and _brain.nim and getattr(_brain.nim, 'api_key', None):
                        _nim_ref = _brain.nim
                        cross_validator.set_llm_fn(
                            lambda p, _n=_nim_ref: _n._ask_once(p, temperature=0.3)
                        )
                        print("[Homeostasis] [OK] CrossValidator wired (NIM secondary)")
                    else:
                        print("[Homeostasis] [--] CrossValidator: no NIM, validation inactive")

                    planner.set_cross_validator(cross_validator)
                    ctx.cross_validator = cross_validator
                    ctx.dispute_log = dispute_log
                except Exception as e:
                    logger.debug(f"CrossValidator not initialized: {e}")

                # Codex CLI (ChatGPT encyclopedia) - optional, graceful fallback
                try:
                    from agent_core.llm.codex_client import CodexClient
                    codex = CodexClient()
                    if codex.is_available():
                        if ctx.brain and hasattr(ctx.brain, 'set_codex_client'):
                            ctx.brain.set_codex_client(codex)
                        ctx.codex_client = codex
                        print("[Homeostasis] [OK] Codex CLI wired (encyclopedia)")
                    else:
                        ctx.codex_client = codex  # keep ref for later availability
                        print("[Homeostasis] [--] Codex CLI not installed (install: npm i -g @openai/codex)")
                except Exception as e:
                    logger.debug(f"Codex CLI not initialized: {e}")

                # K12 Self-Analysis (cognitive loop)
                try:
                    from agent_core.self_analysis import SelfAnalysis
                    from maria_core.sys.config import BASE_DIR as _BASE_DIR
                    sa = SelfAnalysis(project_root=str(_BASE_DIR))

                    # Wire LLM function: use router.ask_as_role if available
                    # Capture reference at wire time to avoid late-binding issues
                    _sa_brain = ctx.brain
                    if hasattr(_sa_brain, "ask_as_role"):
                        def _sa_llm_fn(prompt, _b=_sa_brain):
                            return _b.ask_as_role("planner", prompt)
                        sa.set_llm_fn(_sa_llm_fn)
                    elif hasattr(_sa_brain, "_ask_once"):
                        def _sa_llm_fn(prompt, _b=_sa_brain):
                            return _b._ask_once(prompt, temperature=0.3)
                        sa.set_llm_fn(_sa_llm_fn)

                    # Wire NIM API for stronger analysis (K12 Phase 2)
                    _sa_router = ctx.brain
                    if hasattr(_sa_router, '_ask_once') and getattr(_sa_router, 'nim', None) is not None:
                        def _sa_nim_fn(prompt, _r=_sa_router):
                            return _r._ask_once(prompt, temperature=0.3)
                        sa._analyzer.set_nim_fn(_sa_nim_fn)
                        print("[Homeostasis] [OK] K12 NIM analyzer wired")

                    if ctx.goal_store:
                        sa.set_goal_store(ctx.goal_store)
                    if ctx.world_model:
                        sa.set_world_model(ctx.world_model)
                    if hasattr(ctx, 'memory_query') and ctx.memory_query:
                        sa._collector.set_memory_query(ctx.memory_query)

                    # Wire Claude CLI client (K12 Phase 2)
                    try:
                        from agent_core.self_analysis.claude_cli_client import ClaudeCLIClient
                        claude_cli = ClaudeCLIClient()
                        if ctx.openclaw_client:
                            claude_cli.set_openclaw_client(ctx.openclaw_client)
                        sa._analyzer.set_claude_cli(claude_cli)
                        if claude_cli.is_available():
                            print("[Homeostasis] [OK] Claude CLI wired (K12 Phase 2)")
                        else:
                            print("[Homeostasis] [--] Claude CLI not available (fallback: local)")
                    except Exception as e2:
                        logger.debug(f"Claude CLI not wired: {e2}")

                    planner.set_self_analysis(sa)
                    ctx.self_analysis = sa
                    print("[Homeostasis] [OK] SelfAnalysis wired (K12)")
                except Exception as e:
                    logger.warning(f"SelfAnalysis not initialized: {e}")

                # K13 Creative Module (strategic reflection)
                try:
                    from agent_core.creative.facade import CreativeModule
                    from maria_core.sys.config import BASE_DIR as _BASE_DIR
                    creative = CreativeModule(
                        data_dir=str(_BASE_DIR / "meta_data"),
                        memory_dir=str(_BASE_DIR / "memory"),
                        goal_store=ctx.goal_store,
                    )
                    # Phase 2: wire NIM LLM function if available
                    _router = ctx.brain
                    if hasattr(_router, '_ask_once') and getattr(_router, 'nim', None) is not None:
                        creative.set_llm_fn(lambda p: _router._ask_once(p))
                        print("[Homeostasis] [OK] CreativeModule LLM wired (NIM)")
                    planner.set_creative_module(creative)
                    ctx.creative_module = creative
                    print("[Homeostasis] [OK] CreativeModule wired (K13)")

                    # Wire SemanticMemory to creative MemoryRetriever
                    if ctx.semantic_search:
                        creative._memory_retriever.set_semantic_memory(ctx.semantic_search)
                        print("[Homeostasis] [OK] CreativeModule semantic memory wired")

                    # Wire Codex/ChatGPT as expert for creative exploration
                    if hasattr(ctx, 'codex_client') and ctx.codex_client and ctx.codex_client.is_available():
                        creative.set_expert_fn(
                            lambda p, _c=ctx.codex_client: _c.ask(p, source="creative")
                        )
                        print("[Homeostasis] [OK] CreativeModule expert wired (Codex/ChatGPT)")
                except Exception as e:
                    logger.warning(f"CreativeModule not initialized: {e}")

                # Faza G: CriticAgent (knowledge quality gate)
                try:
                    from agent_core.critic import CriticAgent
                    from maria_core.sys.config import BASE_DIR as _BASE_DIR

                    critic = CriticAgent(project_root=str(_BASE_DIR))

                    # Wire belief store
                    if ctx.world_model and hasattr(ctx.world_model, 'store'):
                        critic.set_belief_store(ctx.world_model.store)

                    # Wire dispute log
                    if hasattr(ctx, 'dispute_log') and ctx.dispute_log:
                        critic.set_dispute_log(ctx.dispute_log)

                    # Wire goal store
                    if ctx.goal_store:
                        critic.set_goal_store(ctx.goal_store)

                    # Wire LLM (NIM for summary decoration)
                    _cr_router = ctx.brain
                    if hasattr(_cr_router, '_ask_once') and getattr(_cr_router, 'nim', None) is not None:
                        critic.set_llm_fn(lambda p, _r=_cr_router: _r._ask_once(p))

                    planner.set_critic_agent(critic)
                    ctx.critic_agent = critic
                    print("[Homeostasis] [OK] CriticAgent wired (Faza G)")
                except Exception as e:
                    logger.warning(f"CriticAgent not initialized: {e}")

                # Cognitive Bulletin Board (Learning Upgrade Phase 1)
                try:
                    from agent_core.bulletin import BulletinStore
                    bulletin_store = BulletinStore()
                    planner.set_bulletin_store(bulletin_store)
                    ctx.bulletin_store = bulletin_store

                    # Phase 2: KnowledgeAuditor
                    from agent_core.bulletin import KnowledgeAuditor
                    auditor = KnowledgeAuditor()
                    if hasattr(ctx, 'memory_query') and ctx.memory_query:
                        auditor.set_memory_query(ctx.memory_query)
                    if ctx.world_model and hasattr(ctx.world_model, 'store'):
                        auditor.set_belief_store(ctx.world_model.store)
                    if hasattr(ctx, 'critic_agent') and ctx.critic_agent:
                        auditor.set_critic_agent(ctx.critic_agent)
                    if ctx.knowledge_analyzer:
                        auditor.set_knowledge_analyzer(ctx.knowledge_analyzer)
                    planner.set_knowledge_auditor(auditor)
                    ctx.knowledge_auditor = auditor

                    # Phase 3: GapPlanner
                    from agent_core.bulletin import GapPlanner
                    gap_planner = GapPlanner()
                    gap_planner.set_bulletin_store(bulletin_store)
                    planner.set_gap_planner(gap_planner)
                    ctx.gap_planner = gap_planner

                    # Phase 4: ExpertBridge (audit-aware expert queries)
                    from agent_core.bulletin.expert_bridge import ExpertBridge
                    expert_bridge = ExpertBridge()
                    expert_bridge.set_auditor(auditor)
                    expert_bridge.set_gap_planner(gap_planner)
                    # LLM function wired below (after brain check)
                    ctx.expert_bridge = expert_bridge
                    planner.executor.set_expert_bridge(expert_bridge)

                    print("[Homeostasis] [OK] BulletinStore + Auditor + GapPlanner + ExpertBridge wired (Learning Upgrade)")
                except Exception as e:
                    logger.warning(f"BulletinStore not initialized: {e}")

                # Wire LLM router to executor for ASK_EXPERT actions
                if ctx.brain and hasattr(ctx.brain, 'ask_encyclopedia'):
                    planner.executor.set_llm_router(ctx.brain)
                    # Wire ExpertBridge LLM function
                    if hasattr(ctx, 'expert_bridge') and ctx.expert_bridge:
                        ctx.expert_bridge.set_llm_fn(
                            lambda p, _b=ctx.brain: _b.ask_encyclopedia(
                                prompt=p, source="expert_bridge",
                            )
                        )
                        print("[Homeostasis] [OK] ExpertBridge LLM wired")

                # Wire SemanticMemory to executor for semantic-aware fetch
                if ctx.semantic_search:
                    planner.executor.set_semantic_search(ctx.semantic_search)

                # Phase 1 Tracing: DecisionTrace store
                try:
                    from agent_core.tracing.trace_store import TraceStore
                    trace_store = TraceStore()
                    planner.set_trace_store(trace_store)
                    ctx.trace_store = trace_store
                    print("[Homeostasis] [OK] TraceStore wired (Phase 1 tracing)")
                except Exception as e:
                    logger.warning(f"TraceStore not initialized: {e}")

                # Phase 2: Unified MemoryQuery API
                try:
                    from agent_core.memory.query import MemoryQuery
                    memory_query = MemoryQuery()
                    if ctx.semantic_search:
                        memory_query.set_semantic_memory(ctx.semantic_search)
                    ctx.memory_query = memory_query
                    print("[Homeostasis] [OK] MemoryQuery wired (Phase 2)")
                except Exception as e:
                    logger.warning(f"MemoryQuery not initialized: {e}")

                # CapabilityRouter: registry-based dispatch
                try:
                    from agent_core.routing import CapabilityRouter, DEFAULT_CAPABILITY_SPECS
                    from agent_core.routing.handlers import (
                        make_learn_handler, make_exam_handler,
                        make_review_handler, make_evaluate_handler,
                        make_maintenance_handler, make_fetch_handler,
                        make_experiment_handler, make_effector_handler,
                        make_self_analyze_handler, make_creative_handler,
                        make_ask_expert_handler, make_validate_handler,
                        make_critique_handler, make_noop_handler,
                    )

                    cap_router = CapabilityRouter()

                    # Teacher-based capabilities (learn/exam/review)
                    _teacher = getattr(core, '_teacher_agent', None)
                    _analyzer = ctx.knowledge_analyzer if hasattr(ctx, 'knowledge_analyzer') else None
                    _sem = ctx.semantic_search if hasattr(ctx, 'semantic_search') else None
                    _goals = ctx.goal_store if hasattr(ctx, 'goal_store') else None
                    # Telegram notifier wires later - use planner.executor
                    # as bridge (handlers read from it at call time)
                    _tg = lambda: getattr(planner.executor, '_telegram_notifier', None)

                    cap_router.register("learn", make_learn_handler(
                        _teacher, _analyzer, _sem, _goals, _tg,
                    ), DEFAULT_CAPABILITY_SPECS["learn"])
                    cap_router.register("exam", make_exam_handler(
                        _teacher, _analyzer, _goals, _tg,
                    ), DEFAULT_CAPABILITY_SPECS["exam"])
                    cap_router.register("review", make_review_handler(
                        _teacher, _analyzer,
                    ), DEFAULT_CAPABILITY_SPECS["review"])

                    # Evaluation
                    _eval_obs = ctx.evaluation_observer if hasattr(ctx, 'evaluation_observer') else None
                    cap_router.register("evaluate", make_evaluate_handler(
                        _eval_obs,
                    ), DEFAULT_CAPABILITY_SPECS["evaluate"])

                    # Maintenance
                    cap_router.register("maintenance", make_maintenance_handler(
                        core, _goals,
                    ), DEFAULT_CAPABILITY_SPECS["maintenance"])

                    # Fetch
                    cap_router.register("fetch", make_fetch_handler(
                        _analyzer, _sem,
                    ), DEFAULT_CAPABILITY_SPECS["fetch"])

                    # Experiment (K11)
                    _exp = ctx.experiment_system if hasattr(ctx, 'experiment_system') else None
                    cap_router.register("experiment", make_experiment_handler(
                        _exp,
                    ), DEFAULT_CAPABILITY_SPECS["experiment"])

                    # Effector (OpenClaw)
                    _claw = ctx.openclaw_client if hasattr(ctx, 'openclaw_client') else None
                    cap_router.register("effector", make_effector_handler(
                        _claw,
                    ), DEFAULT_CAPABILITY_SPECS["effector"])

                    # Self-Analysis (K12)
                    _sa = ctx.self_analysis if hasattr(ctx, 'self_analysis') else None
                    cap_router.register("self_analyze", make_self_analyze_handler(
                        _sa, _tg,
                    ), DEFAULT_CAPABILITY_SPECS["self_analyze"])

                    # Creative (K13)
                    _creative = ctx.creative_module if hasattr(ctx, 'creative_module') else None
                    cap_router.register("creative", make_creative_handler(
                        _creative, _tg,
                    ), DEFAULT_CAPABILITY_SPECS["creative"])

                    # Ask Expert (Codex/ChatGPT) - with ExpertBridge (Phase 4)
                    _llm_rtr = ctx.brain if (hasattr(ctx, 'brain') and ctx.brain and hasattr(ctx.brain, 'ask_encyclopedia')) else None
                    _expert_br = ctx.expert_bridge if hasattr(ctx, 'expert_bridge') else None
                    _bull_store = ctx.bulletin_store if hasattr(ctx, 'bulletin_store') else None
                    cap_router.register("ask_expert", make_ask_expert_handler(
                        _llm_rtr,
                        expert_bridge=_expert_br,
                        bulletin_store=_bull_store,
                    ), DEFAULT_CAPABILITY_SPECS["ask_expert"])

                    # Validate (Faza F)
                    _cross_val = ctx.cross_validator if hasattr(ctx, 'cross_validator') else None
                    _wm = ctx.world_model if hasattr(ctx, 'world_model') else None
                    cap_router.register("validate", make_validate_handler(
                        _cross_val, _wm, _analyzer,
                    ), DEFAULT_CAPABILITY_SPECS["validate"])

                    # Critique (Faza G)
                    _critic = ctx.critic_agent if hasattr(ctx, 'critic_agent') else None
                    cap_router.register("critique", make_critique_handler(
                        _critic, _tg,
                    ), DEFAULT_CAPABILITY_SPECS["critique"])

                    # Noop
                    cap_router.register("noop", make_noop_handler(),
                                        DEFAULT_CAPABILITY_SPECS["noop"])

                    planner.set_capability_router(cap_router)
                    ctx.capability_router = cap_router
                    print(f"[Homeostasis] [OK] CapabilityRouter wired ({cap_router.registered_count} capabilities)")

                    # Wire CapabilityManifest (K15)
                    try:
                        from agent_core.operator.capability_manifest import CapabilityManifest
                        manifest = CapabilityManifest()
                        manifest.set_capability_router(cap_router)
                        manifest.set_context(ctx)
                        if core:
                            manifest.set_mode_fn(lambda: core.current_mode.name if core.current_mode else "UNKNOWN")
                        ctx.capability_manifest = manifest
                        print(f"[Homeostasis] [OK] CapabilityManifest wired ({len(manifest.get_available())} available)")
                    except Exception as e:
                        logger.debug(f"CapabilityManifest not initialized: {e}")
                except Exception as e:
                    logger.warning(f"CapabilityRouter not initialized: {e}")

                core.set_planner_core(planner)
                ctx.planner_core = planner
                print("[Homeostasis] [OK] PlannerCore wired (Warstwa 2)")

                # Wire work context provider to OllamaBrain (chat knows what planner does)
                # ctx.brain may be LLMRouter wrapping OllamaBrain
                _brain = ctx.brain
                if hasattr(_brain, 'ollama'):
                    _brain = _brain.ollama  # Unwrap LLMRouter -> OllamaBrain
                if _brain and hasattr(_brain, 'set_work_context_provider'):
                    _brain.set_work_context_provider(
                        lambda: _build_work_context(ctx)
                    )
                    print("[Homeostasis] [OK] Work context wired to chat")
            except Exception as e:
                logger.debug(f"PlannerCore not wired: {e}")

        # Initialize Telegram bridge (operator notifications)
        if core:
            try:
                from agent_core.telegram import TelegramBridge
                telegram = TelegramBridge()
                if telegram.configured:
                    core.set_telegram_bridge(telegram)
                    ctx.telegram_bridge = telegram

                    # Register basic commands
                    _register_telegram_commands(telegram, ctx)

                    # Wire notifier to planner's action executor + Phase 5 approval flow
                    if ctx.planner_core:
                        ctx.planner_core.executor.set_telegram_notifier(telegram.notifier)
                        ctx.planner_core.set_telegram_notifier(telegram.notifier)

                    # Flush old messages to avoid re-processing (e.g. /restart loop)
                    telegram.bot.flush_pending()

                    # Send startup notification
                    telegram.notifier.notify_startup()

                    # Recover interrupted tasks from previous run
                    try:
                        from agent_core.llm.task_store import TaskStore
                        _task_store = TaskStore()
                        interrupted = _task_store.recover_interrupted()
                        if interrupted:
                            lines = [f"*{len(interrupted)} przerwanych taskow:*"]
                            for t in interrupted[:5]:
                                backend = t.get("backend", "?")
                                text = t.get("task_text", "?")[:60]
                                lines.append(f"  [{backend}] {text}")
                            telegram.notifier.send_raw("\n".join(lines))
                            logger.info(
                                "[TaskStore] Recovered %d interrupted tasks",
                                len(interrupted),
                            )
                    except Exception as e:
                        logger.debug(f"TaskStore recovery skipped: {e}")

                    print("[Homeostasis] [OK] Telegram bridge wired (ClawBot)")
                else:
                    print("[Homeostasis] [--] Telegram not configured (set TELEGRAM_BOT_TOKEN in .env)")
            except Exception as e:
                logger.debug(f"Telegram bridge not initialized: {e}")

        # Initialize Vision cortex (visual perception pipeline)
        if core:
            try:
                from agent_core.vision.cortex import VisionCortex
                from agent_core.vision.preprocessing.preprocessor import VisionPreprocessor
                from agent_core.vision.modules.motion.detector import MotionModule
                from agent_core.vision.modules.scene.analyzer import SceneModule

                preprocessor = VisionPreprocessor(target_resolution=(640, 480))
                vision_cortex = VisionCortex(preprocessor=preprocessor)

                # LLaVA function for scene descriptions
                def _llava_describe(prompt: str, image_b64: str):
                    """Call LLaVA via Ollama /api/generate."""
                    import requests
                    try:
                        resp = requests.post(
                            "http://localhost:11434/api/generate",
                            json={
                                "model": "llava",
                                "prompt": prompt,
                                "images": [image_b64],
                                "stream": False,
                            },
                            timeout=30,
                        )
                        if resp.status_code == 200:
                            return resp.json().get("response", "")
                    except Exception as e:
                        logger.debug(f"LLaVA call failed: {e}")
                    return None

                # Add modules (LLaVA NOT in tick loop - too slow, 30s/call)
                # SceneModule uses stats fallback in tick, LLaVA only via /vision snap
                vision_cortex.add_module(MotionModule())
                scene = SceneModule(use_polish=True)
                scene._llava_describe = _llava_describe  # store for on-demand use
                vision_cortex.add_module(scene)

                # Try to add USB webcam sensor (graceful if no camera)
                try:
                    from agent_core.vision.sensors.usb_webcam import USBWebcamSensor
                    sensor = USBWebcamSensor(device=0, flip=True)
                    if sensor.open():
                        vision_cortex.add_sensor(sensor)
                        print(f"[Homeostasis] [OK] VisionCortex initialized (sensor: {sensor.sensor_id})")
                    else:
                        vision_cortex.add_sensor(sensor)  # add anyway, health will show disconnected
                        print("[Homeostasis] [OK] VisionCortex initialized (sensor: not connected)")
                except Exception as e:
                    logger.debug(f"USB webcam not available: {e}")
                    print("[Homeostasis] [OK] VisionCortex initialized (no sensor)")

                ctx.vision_cortex = vision_cortex
                core.set_vision_cortex(vision_cortex)
            except Exception as e:
                logger.debug(f"VisionCortex not initialized: {e}")

        # Initialize Code Agent (autonomous coding)
        try:
            from agent_core.code_agent.agent import CodeAgent
            code_agent = CodeAgent(ctx)
            if ctx.openclaw_client:
                code_agent.set_openclaw(ctx.openclaw_client)
            # Wire Claude/Codex LLM functions
            if hasattr(ctx, 'claude_client') and ctx.claude_client:
                code_agent.set_claude_fn(ctx.claude_client.ask)
            elif hasattr(ctx, 'codex_client') and ctx.codex_client:
                code_agent.set_codex_fn(ctx.codex_client.ask)
            # Wire Telegram notifications
            if ctx.telegram_bridge and hasattr(ctx.telegram_bridge, 'notifier'):
                code_agent.set_notify_fn(ctx.telegram_bridge.notifier.send_message)
            ctx.code_agent = code_agent
            print("[Homeostasis] [OK] Code Agent initialized")
        except Exception as e:
            logger.debug(f"Code Agent not initialized: {e}")

        # Start introspection scheduler (daily code self-model refresh)
        try:
            from agent_core.introspection.scheduler import IntrospectionScheduler
            intro_sched = IntrospectionScheduler(
                project_root=str(Path(ctx.config.BASE_DIR)),
                interval_sec=86400,  # 24h (AST scan is heavy)
            )
            intro_sched.start()
            print("[Homeostasis] [OK] Introspection scheduler started (24h)")
        except Exception as e:
            logger.debug(f"Introspection scheduler not started: {e}")

        # Wire state-grounded operator response pipeline (Phase 2)
        try:
            from agent_core.introspection.query_router import OperationalQueryRouter
            from agent_core.introspection.evidence_collector import EvidenceCollector
            from agent_core.introspection.response_builder import ResponseBuilder

            qr = OperationalQueryRouter()
            ec = EvidenceCollector(project_root=str(Path(ctx.config.BASE_DIR)))
            rb = ResponseBuilder()

            # Wire runtime objects for full evidence access
            if ctx.homeostasis_core:
                ec.set_homeostasis_core(ctx.homeostasis_core)
            if ctx.planner_core:
                ec.set_planner_core(ctx.planner_core)
            if ctx.knowledge_analyzer:
                ec.set_knowledge_analyzer(ctx.knowledge_analyzer)
            if ctx.evaluation_observer:
                ec.set_evaluation_observer(ctx.evaluation_observer)
            if ctx.llm_tape:
                ec.set_llm_tape(ctx.llm_tape)
            if ctx.self_analysis:
                ec.set_self_analysis(ctx.self_analysis)
            if ctx.goal_store:
                ec.set_goal_store(ctx.goal_store)
            if hasattr(ctx, 'memory_query') and ctx.memory_query:
                ec.set_memory_query(ctx.memory_query)
            if ctx.vision_cortex:
                ec.set_vision_cortex(ctx.vision_cortex)

            ctx.evidence_collector = ec

            # Wire to OllamaBrain
            _brain = ctx.brain
            if hasattr(_brain, 'ollama'):
                _brain = _brain.ollama
            if _brain and hasattr(_brain, 'set_grounding_pipeline'):
                _brain.set_grounding_pipeline(qr, ec, rb)

            print("[Homeostasis] [OK] Grounding pipeline wired (Phase 2)")
        except Exception as e:
            logger.debug(f"Grounding pipeline not wired: {e}")

        # Initialize Reminders & Todos (Phase 12)
        try:
            from agent_core.reminders import ReminderStore, TodoStore, ReminderScheduler
            reminder_store = ReminderStore()
            todo_store = TodoStore()
            scheduler = ReminderScheduler(reminder_store, todo_store)

            # Wire Telegram notifications
            if ctx.telegram_bridge and hasattr(ctx.telegram_bridge, 'bot'):
                scheduler.set_notify_fn(ctx.telegram_bridge.bot.send_message)

            ctx.reminder_store = reminder_store
            ctx.todo_store = todo_store
            ctx.reminder_scheduler = scheduler

            if core:
                core.set_reminder_scheduler(scheduler)

            r_count = reminder_store.count()
            t_count = todo_store.count()
            print(f"[Homeostasis] [OK] Reminders ({r_count['pending']} pending) + Todos ({t_count['pending']} pending)")
        except Exception as e:
            logger.debug(f"Reminders not initialized: {e}")

        # Initialize Proactive Contact (Phase 13)
        try:
            from agent_core.proactive import ProactiveScheduler
            proactive = ProactiveScheduler()

            # Wire Telegram send
            if ctx.telegram_bridge and hasattr(ctx.telegram_bridge, 'notifier'):
                proactive.set_notify_fn(ctx.telegram_bridge.notifier.send_raw)

            # Wire data accessors for content generators
            gen = proactive.generators
            if ctx.user_profile:
                gen.set_user_name_fn(lambda: ctx.user_profile.get_name())
                gen.set_user_interests_fn(lambda: ctx.user_profile.get_interests())
            om = getattr(ctx, 'operator_model', None)
            if om:
                gen.set_operator_context_fn(lambda: om.get_context())
                gen.set_operator_rhythm_fn(lambda: om.rhythm)
            if ctx.evaluation_observer:
                gen.set_evaluation_fn(lambda: ctx.evaluation_observer.generate_report(24.0))
            if ctx.knowledge_analyzer:
                gen.set_knowledge_fn(lambda: ctx.knowledge_analyzer.get_knowledge_snapshot())
            if ctx.goal_store:
                gen.set_goal_stats_fn(lambda: ctx.goal_store.stats())
                gen.set_active_goals_fn(
                    lambda: [
                        {"description": g.description, "id": g.id}
                        for g in ctx.goal_store.get_active()
                    ]
                )
                gen.set_proposed_goals_fn(
                    lambda: [
                        {"description": g.description, "id": g.id}
                        for g in ctx.goal_store.get_proposed()
                    ]
                )
                gen.set_recent_achievements_fn(
                    lambda: [
                        g.description
                        for g in ctx.goal_store.get_all()
                        if g.status.value == "achieved"
                    ][-5:]
                )
            if core:
                gen.set_health_fn(lambda: core.get_state().get("health_score", 0))
                gen.set_mode_fn(lambda: core.get_state().get("mode", "?"))
            if ctx.planner_core:
                gen.set_planner_stats_fn(
                    lambda: {"total_cycles": ctx.planner_core.state.total_cycles}
                    if hasattr(ctx.planner_core, 'state') else {}
                )

            ctx.proactive_scheduler = proactive

            if core:
                core.set_proactive_scheduler(proactive)

            status = "enabled" if proactive.enabled else "disabled"
            print(f"[Homeostasis] [OK] Proactive contact ({status}, {proactive.state.contacts_today} today)")
        except Exception as e:
            logger.debug(f"Proactive contact not initialized: {e}")

        return True

    def get_commands(self):
        return [
            CommandInfo(
                "/homeostasis", self._cmd_homeostasis,
                "  /homeostasis           - pokaz status homeostazy\n"
                "  /homeostasis start     - uruchom petle homeostazy w tle\n"
                "  /homeostasis stop      - zatrzymaj petle homeostazy\n"
                "  /homeostasis events N  - pokaz ostatnie N zdarzen (domyslnie 10)\n"
                "  /homeostasis summary   - pokaz podsumowanie sesji",
                "[HEART] HOMEOSTASIS",
            ),
        ]

    def _cmd_homeostasis(self, args):
        """Handle /homeostasis commands."""
        core = self.ctx.homeostasis_core
        if not core:
            print("[Homeostasis] [ERROR] Not initialized")
            return

        subcommand = args[0].lower() if args else "status"

        if subcommand == "status":
            self._show_status(core)
        elif subcommand == "start":
            self._start_loop(core)
        elif subcommand == "stop":
            self._stop_loop(core)
        elif subcommand == "events":
            limit = 10
            if len(args) > 1:
                try:
                    limit = int(args[1])
                except ValueError:
                    pass
            self._show_events(limit)
        elif subcommand == "summary":
            self._show_summary()
        else:
            print(f"[Homeostasis] Unknown subcommand: {subcommand}")
            print("  Usage: /homeostasis [status|start|stop|events|summary]")

    def _show_status(self, core):
        state = core.state
        telemetry = core.get_telemetry()

        print("\n" + "=" * 50)
        print("[HEART] HOMEOSTASIS STATUS")
        print("=" * 50)
        print(f"  Mode:         {state.mode.value.upper()}")
        print(f"  Health Score: {state.health_score:.1%}")
        print(f"  Mode Duration: {state.mode_duration_seconds:.0f}s")
        print(f"  Idle Seconds: {state.idle_seconds:.0f}s")

        if state.alerts:
            print(f"\n  [WARN] Alerts ({len(state.alerts)}):")
            for alert in state.alerts[-5:]:
                print(f"    - {alert}")
        else:
            print(f"\n  [OK] No alerts")

        if telemetry.get("resource_headroom"):
            rh = telemetry["resource_headroom"]
            print(f"\n  Resources:")
            print(f"    RAM:  {rh.get('ram_pct', 0):.0f}% available")
            print(f"    CPU:  {rh.get('cpu_pct', 0):.0f}% available")
            print(f"    Disk: {rh.get('disk_pct', 0):.0f}% available")

        print(f"\n  Loop Running: {'Yes' if self._running else 'No'}")
        print("=" * 50 + "\n")

    def _start_loop(self, core):
        if self._running:
            print("[Homeostasis] Already running")
            return

        def loop():
            self._running = True
            print("[Homeostasis] [START] Starting monitoring loop...")

            while self._running:
                try:
                    core._execute_tick()

                    if core.state.mode != Mode.ACTIVE:
                        print(f"[Homeostasis] [WARN] Mode: {core.state.mode.value}")

                    time.sleep(1.0)
                except Exception as e:
                    print(f"[Homeostasis] [WARN] Error: {e}")
                    time.sleep(5.0)

            print("[Homeostasis] [STOP] Loop stopped")

        self._thread = threading.Thread(
            target=loop, daemon=True, name="HomeostasisLoop"
        )
        self._thread.start()
        print("[Homeostasis] [OK] Monitoring started")

    def _stop_loop(self, core):
        if not self._running:
            print("[Homeostasis] Not running")
            return

        self._running = False
        core.stop(reason="user_request")
        print("[Homeostasis] Stopping...")

    def _show_events(self, limit):
        event_logger = get_event_logger()
        events = event_logger.get_recent_events(limit=limit)

        print("\n" + "=" * 70)
        print(f"[EVENTS] HOMEOSTASIS EVENTS (last {len(events)})")
        print("=" * 70)

        if not events:
            print("  No events recorded yet.")
        else:
            for event in events:
                ts = event.get("timestamp", event.get("ts", 0))
                dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                event_type = event.get("event", event.get("event_type", "?"))

                if event_type == "mode_change":
                    from_m = event.get("from_mode", event.get("from", "?"))
                    to_m = event.get("to_mode", event.get("to", "?"))
                    trigger = event.get("trigger", {})
                    constraint = trigger.get("constraint", "?")
                    value = trigger.get("value")
                    threshold = trigger.get("threshold")
                    duration = event.get("duration_in_prev_mode_sec", 0)

                    print(f"\n  [{dt}] MODE CHANGE: {from_m} -> {to_m}")
                    print(f"      Trigger: {constraint}")
                    if value is not None:
                        print(f"      Value: {value} (threshold: {threshold})")
                    print(f"      Duration in {from_m}: {duration:.0f}s")

                elif event_type == "alert":
                    severity = event.get("severity", "?")
                    alert_type = event.get("alert_type", "?")
                    message = event.get("message", "")
                    print(f"\n  [{dt}] {severity}: {alert_type}")
                    print(f"      {message}")

                elif event_type == "state_snapshot":
                    mode = event.get("mode", "?")
                    health = event.get("health_score", 0)
                    metrics = event.get("metrics", {})
                    ram = metrics.get("ram_available_pct", 0)
                    cpu = metrics.get("cpu_load", 0)
                    print(f"\n  [{dt}] SNAPSHOT: mode={mode}, health={health:.0%}")
                    print(f"      RAM: {ram:.0f}%, CPU: {cpu:.0f}%")

                elif event_type == "startup":
                    print(f"\n  [{dt}] STARTUP: {event.get('message', '')}")

                elif event_type == "shutdown":
                    reason = event.get("reason", "?")
                    uptime = event.get("uptime_sec", 0)
                    print(f"\n  [{dt}] SHUTDOWN: reason={reason}, uptime={uptime:.0f}s")

                else:
                    print(f"\n  [{dt}] {event_type}: {event}")

        print("\n" + "=" * 70)
        print(f"  Log file: {event_logger.log_path}")
        print("=" * 70 + "\n")

    def _show_summary(self):
        event_logger = get_event_logger()
        summary = event_logger.get_session_summary()

        print("\n" + "=" * 50)
        print("[SUMMARY] HOMEOSTASIS SESSION SUMMARY")
        print("=" * 50)
        print(f"  Uptime:        {summary['uptime_sec']:.0f}s ({summary['uptime_sec']/3600:.1f}h)")
        print(f"  Total Events:  {summary['total_events']}")
        print(f"  Mode Changes:  {summary['mode_changes']}")
        print(f"  Modes Visited: {', '.join(summary['modes_visited']) or 'none'}")
        print(f"\n  Alerts:")
        print(f"    CRITICAL: {summary['alerts']['CRITICAL']}")
        print(f"    ALERT:    {summary['alerts']['ALERT']}")
        print(f"    WARNING:  {summary['alerts']['WARNING']}")
        print(f"\n  Log File: {summary['log_file']}")
        print("=" * 50 + "\n")

    def cleanup(self):
        if self._running:
            self._running = False


def _register_telegram_commands(bridge, ctx):
    """Register Telegram command handlers for operator interaction."""

    def _cmd_status(args):
        """Return system status summary."""
        parts = []
        if ctx.homeostasis_core:
            state = ctx.homeostasis_core.get_state()
            parts.append(f"Mode: {state.mode.value}")
            parts.append(f"Health: {state.health_score:.0%}")
            if state.alerts:
                parts.append(f"Alerts: {len(state.alerts)}")

        if ctx.planner_core:
            status = ctx.planner_core.get_status()
            parts.append(f"Planner cycles: {status['total_cycles']}")
            parts.append(f"Plans executed: {status['total_plans_executed']}")

        if ctx.knowledge_analyzer:
            try:
                snap = ctx.knowledge_analyzer.get_knowledge_snapshot()
                if snap:
                    by_status = snap.get("files_by_status", {})
                    completed = len(by_status.get("completed", []))
                    total = snap.get("total_files", 0)
                    parts.append(f"Knowledge: {completed}/{total} completed")
            except Exception:
                pass

        if ctx.goal_store:
            try:
                stats = ctx.goal_store.stats()
                parts.append(f"Goals: {stats.get('active', 0)} active, {stats.get('proposed', 0)} proposed")
            except Exception:
                pass

        return "\n".join(parts) if parts else "System OK"

    def _cmd_goals(args):
        """List active and proposed goals."""
        if not ctx.goal_store:
            return "GoalStore not available"

        lines = []
        active = ctx.goal_store.get_active()
        if active:
            lines.append(f"*Active ({len(active)}):*")
            for g in active[:20]:
                lines.append(f"  [{g.id[:8]}] pri={g.priority:.2f} {g.description[:65]}")

        proposed = ctx.goal_store.get_proposed()
        if proposed:
            lines.append(f"\n*Proposed ({len(proposed)}):*")
            for g in sorted(proposed, key=lambda x: x.priority, reverse=True)[:10]:
                lines.append(f"  [{g.id[:8]}] pri={g.priority:.2f} {g.description[:65]}")

        # Stats
        stats = ctx.goal_store.stats()
        abandoned = stats["by_status"].get("abandoned", 0)
        achieved = stats["by_status"].get("achieved", 0)
        if abandoned or achieved:
            lines.append(f"\nZakonczone: {achieved} achieved, {abandoned} abandoned")

        return "\n".join(lines) if lines else "Brak celow"

    def _cmd_approve(args):
        """Approve a proposed goal by ID prefix."""
        if not ctx.goal_store or not args:
            return "Uzycie: approve <id-prefix>"
        prefix = args.strip()
        proposed = ctx.goal_store.get_proposed()
        match = [g for g in proposed if g.id.startswith(prefix)]
        if not match:
            return f"Nie znaleziono celu: {prefix}"
        if len(match) > 1:
            return f"Wiele dopasowani ({len(match)}), podaj dluzszy prefix"
        goal = match[0]
        ctx.goal_store.confirm(goal.id)
        ctx.goal_store.save()
        return f"Zatwierdzono: {goal.description[:80]}"

    def _cmd_reject(args):
        """Reject a proposed goal by ID prefix."""
        if not ctx.goal_store or not args:
            return "Uzycie: reject <id-prefix>"
        prefix = args.strip()
        proposed = ctx.goal_store.get_proposed()
        match = [g for g in proposed if g.id.startswith(prefix)]
        if not match:
            return f"Nie znaleziono celu: {prefix}"
        if len(match) > 1:
            return f"Wiele dopasowani ({len(match)}), podaj dluzszy prefix"
        goal = match[0]
        ctx.goal_store.reject(goal.id, reason="operator_telegram")
        ctx.goal_store.save()
        return f"Odrzucono: {goal.description[:80]}"

    def _cmd_restart(args):
        """Restart Maria (systemd will bring her back in 10s)."""
        import os

        bridge.notifier.send_raw("Restarting M.A.R.I.A. ... (wraca za ~10s)")

        # Give Telegram time to send the message, then exit
        # sys.exit(1) = failure -> systemd Restart=on-failure kicks in
        def _delayed_exit():
            time.sleep(2)
            os._exit(1)

        t = threading.Thread(target=_delayed_exit, daemon=True)
        t.start()
        return None  # Message already sent via send_raw

    def _cmd_priority(args):
        """Set priority for a goal: /priority <id-prefix> <0.0-1.0>"""
        from agent_core.goals.goal_model import AuditEntry
        if not ctx.goal_store or not args:
            return "Uzycie: /priority <id-prefix> <0.0-1.0>"
        parts = args.strip().split(None, 1)
        if len(parts) < 2:
            return "Uzycie: /priority <id-prefix> <0.0-1.0>"
        prefix = parts[0]
        try:
            new_pri = float(parts[1])
        except ValueError:
            return f"Nieprawidlowy priorytet: {parts[1]}"
        if not (0.0 <= new_pri <= 1.0):
            return "Priorytet musi byc 0.0-1.0"

        # Search in proposed + active goals
        candidates = ctx.goal_store.get_proposed() + ctx.goal_store.get_active()
        match = [g for g in candidates if g.id.startswith(prefix)]
        if not match:
            return f"Nie znaleziono celu: {prefix}"
        if len(match) > 1:
            return f"Wiele dopasowani ({len(match)}), podaj dluzszy prefix"
        goal = match[0]
        old_pri = goal.priority
        goal.priority = new_pri
        goal.updated_at = time.time()
        goal.audit_trail.append(AuditEntry(
            timestamp=time.time(),
            old_status=goal.status.value,
            new_status=goal.status.value,
            reason=f"priority {old_pri:.2f} -> {new_pri:.2f} (operator)",
            actor="operator",
        ))
        ctx.goal_store._mark_dirty(goal.id)
        ctx.goal_store.save()
        return f"Priorytet {goal.description[:60]}: {old_pri:.2f} -> {new_pri:.2f}"

    def _cmd_learn(args):
        """Create a learning goal from Telegram: /learn <topic>"""
        if not args or not args.strip():
            return "Uzycie: /learn <temat>\nPrzyklad: /learn fizyka kwantowa"
        topic = args.strip()
        try:
            from agent_core.perception.conversation_learning import process_user_message
            result = process_user_message(f"naucz sie o {topic}", ctx, channel="telegram")
            if result and result.get("goal_id"):
                return f"Dodam do nauki: '{result['topic']}'"
            else:
                return f"Nie udalo sie utworzyc celu dla: '{topic}'"
        except Exception as e:
            return f"Blad: {e}"

    def _cmd_trace(args):
        """Show recent decision traces."""
        trace_store = getattr(ctx, 'trace_store', None)
        if not trace_store:
            return "TraceStore niedostepny."

        args = args.strip()
        # /trace <episode_id> - show specific trace
        if args and args.startswith("ep-"):
            t = trace_store.get_by_episode_id(args)
            if not t:
                return f"Trace {args} nie znaleziony."
            steps_text = ""
            for s in t.get("steps", [])[:8]:
                steps_text += f"  {s['subsystem']}: {s['action']} -> {s['result']}\n"
            return (
                f"*Trace {t['episode_id'][-8:]}*\n"
                f"Action: {t.get('action_type', '?')}\n"
                f"Goal: {t.get('goal_description', '-')[:40]}\n"
                f"K7: {t.get('k7_decision', '-')}\n"
                f"Success: {t.get('success')}\n"
                f"Duration: {t.get('duration_ms', 0):.0f}ms\n"
                f"LLM calls: {t.get('total_llm_calls', 0)}\n"
                f"Steps:\n{steps_text}"
            )

        # /trace stats - aggregate stats
        if args == "stats":
            stats = trace_store.get_stats()
            at = stats.get("action_types", {})
            at_text = ", ".join(f"{k}:{v}" for k, v in sorted(at.items(), key=lambda x: -x[1])[:5])
            return (
                f"*Trace stats* (last {stats['total']})\n"
                f"OK: {stats.get('success', 0)} | FAIL: {stats.get('failed', 0)}\n"
                f"K7 blocks: {stats.get('k7_blocks', 0)}\n"
                f"Avg: {stats.get('avg_duration_ms', 0):.0f}ms\n"
                f"LLM: {stats.get('total_llm_calls', 0)} calls\n"
                f"Actions: {at_text}"
            )

        # /trace failed - recent failures
        if args == "failed":
            failed = trace_store.get_failed(limit=5)
            if not failed:
                return "Brak ostatnich bledow."
            lines = []
            for t in failed:
                eid = t.get("episode_id", "?")[-8:]
                action = t.get("action_type", "?")
                k7 = t.get("k7_decision", "")
                summary = t.get("result_summary", "")[:40]
                lines.append(f"[{eid}] {action} K7:{k7} - {summary}")
            return "*Ostatnie bledy:*\n" + "\n".join(lines)

        # /trace - show last N traces (default 5)
        limit = 5
        if args.isdigit():
            limit = min(int(args), 10)
        recent = trace_store.get_recent(limit=limit)
        if not recent:
            return "Brak traces."
        lines = []
        for t in recent:
            eid = t.get("episode_id", "?")[-8:]
            action = t.get("action_type", "?")
            ok = "OK" if t.get("success") else "FAIL"
            dur = t.get("duration_ms", 0)
            goal = (t.get("goal_description") or "-")[:25]
            lines.append(f"[{eid}] {action} {ok} {dur:.0f}ms - {goal}")
        return "*Ostatnie trace:*\n" + "\n".join(lines)

    def _cmd_memory(args):
        """Query Maria's knowledge about a topic."""
        topic = args.strip()
        if not topic:
            return "Uzycie: /memory <temat>\nNp. /memory fizyka\n/memory gaps"

        memory_query = getattr(ctx, 'memory_query', None)
        if not memory_query:
            return "MemoryQuery niedostepny."

        try:
            # /memory gaps - knowledge gap analysis
            if topic.lower() == "gaps":
                gaps = memory_query.get_knowledge_gaps(top_k=5)
                if not gaps:
                    return "Brak luk w wiedzy."
                lines = ["*Luki w wiedzy:*"]
                for g in gaps:
                    lines.append(f"- {g['topic']}: {g['confidence']:.0%} ({g['reason']})")
                return "\n".join(lines)

            # /memory <topic> - query knowledge
            summary = memory_query.get_topic_summary(topic)
            if not summary.get("known"):
                return f"Nie mam wiedzy o: {topic}"

            results = memory_query.query_topic(topic, top_k=5)
            lines = [
                f"*Wiedza o '{topic}':*",
                f"Pliki: {summary.get('files_count', 0)}, przekonania: {summary.get('beliefs_count', 0)}",
                f"Pewnosc: {summary.get('avg_confidence', 0):.0%}, swiezosc: {summary.get('freshness', 0):.0%}",
                "",
            ]
            for r in results[:5]:
                src = r.source.value[:4]
                lines.append(f"[{src}] {r.content[:60]}")

            return "\n".join(lines)
        except Exception as e:
            return f"Blad: {e}"

    # -- Phase 5: Effector commands --

    def _cmd_efapprove(args):
        """Approve a pending effector request."""
        queue = getattr(ctx, 'approval_queue', None)
        if not queue or not args:
            return "Uzycie: /efapprove <request-id-prefix>"
        prefix = args.strip()
        approved = queue.approve(prefix)
        if not approved:
            return f"Nie znaleziono oczekujacego requestu: {prefix}"
        return f"Zatwierdzono efektor: {approved.tool_name} ({approved.request_id[:12]})"

    def _cmd_efreject(args):
        """Reject a pending effector request."""
        queue = getattr(ctx, 'approval_queue', None)
        if not queue or not args:
            return "Uzycie: /efreject <request-id-prefix>"
        prefix = args.strip()
        rejected = queue.reject(prefix)
        if not rejected:
            return f"Nie znaleziono oczekujacego requestu: {prefix}"
        return f"Odrzucono efektor: {rejected.tool_name} ({rejected.request_id[:12]})"

    def _cmd_efstatus(args):
        """Show effector authority status and pending requests."""
        parts = []

        auth_mgr = getattr(ctx, 'authority_manager', None)
        if auth_mgr:
            status = auth_mgr.get_status()
            parts.append(f"*Authority level:* {status['authority_level']}")

        queue = getattr(ctx, 'approval_queue', None)
        if queue:
            stats = queue.get_stats()
            parts.append(f"Pending: {stats['pending']}, Approved: {stats['approved']}")
            pending = queue.get_pending()
            for p in pending[:5]:
                parts.append(f"  [{p.request_id[:8]}] {p.tool_name} - {p.goal_description[:40]}")

        budget = getattr(ctx, 'tool_budget', None)
        if budget:
            bstats = budget.get_stats()
            for tool, ts in bstats.items():
                if ts['consecutive_failures'] > 0 or ts['locked']:
                    parts.append(f"  {tool}: {ts['invocations_this_window']}/{ts['rate_limit']} "
                                 f"fails={ts['consecutive_failures']} locked={ts['locked']}")

        return "\n".join(parts) if parts else "Brak danych efektora"

    def _cmd_authority(args):
        """Change effector authority level."""
        from agent_core.autonomy.authority_level import AuthorityLevel

        auth_mgr = getattr(ctx, 'authority_manager', None)
        if not auth_mgr:
            return "AuthorityManager niedostepny"

        arg = args.strip().lower()
        if not arg:
            level = auth_mgr.get_level()
            return (
                f"*Aktualny level:* {level.value}\n"
                "Dostepne: observe, suggest, confirm, bounded\n"
                "Uzycie: /authority <level>"
            )

        try:
            new_level = AuthorityLevel(arg)
        except ValueError:
            return f"Nieznany level: {arg}. Dostepne: observe, suggest, confirm, bounded"

        ok = auth_mgr.set_level(new_level)
        if not ok:
            return f"Nie mozna ustawic: {arg} (max: bounded)"

        # On downgrade, reject pending approvals
        queue = getattr(ctx, 'approval_queue', None)
        if queue and new_level.value in ("observe", "suggest"):
            rejected = queue.reject_all_pending("authority_downgrade")
            if rejected > 0:
                return f"Authority: {new_level.value} (odrzucono {rejected} oczekujacych)"

        return f"Authority: {new_level.value}"

    def _cmd_validate(args):
        """Show cross-validation stats and disputes."""
        cv = getattr(ctx, 'cross_validator', None)
        dl = getattr(ctx, 'dispute_log', None)

        args = args.strip()

        # /validate disputes - recent disputes
        if args == "disputes":
            if not dl:
                return "DisputeLog niedostepny."
            recent = dl.get_recent(limit=10)
            if not recent:
                return "Brak sporow."
            lines = []
            for d in recent:
                rec = d if isinstance(d, dict) else d.to_dict()
                fid = rec.get("file_id", "?")[:20]
                dim = rec.get("dimension", "?")
                sev = rec.get("severity", "?")
                lines.append(f"  [{fid}] {dim} (sev={sev})")
            return "*Ostatnie spory:*\n" + "\n".join(lines)

        # /validate unresolved - unresolved disputes
        if args == "unresolved":
            if not dl:
                return "DisputeLog niedostepny."
            unresolved = dl.get_unresolved()
            if not unresolved:
                return "Brak nierozwiazanych sporow."
            lines = []
            for d in unresolved[:10]:
                rec = d if isinstance(d, dict) else d.to_dict()
                fid = rec.get("file_id", "?")[:20]
                dim = rec.get("dimension", "?")
                lines.append(f"  [{fid}] {dim}")
            return f"*Nierozwiazane ({len(unresolved)}):*\n" + "\n".join(lines)

        # /validate - stats overview (default)
        parts = ["*Cross-Validation (Faza F):*"]
        if cv:
            stats = cv.get_stats()
            parts.append(
                f"Validated: {stats.get('chunks_validated', 0)} chunks\n"
                f"Agreed: {stats.get('chunks_agreed', 0)}\n"
                f"Disputed: {stats.get('chunks_disputed', 0)}\n"
                f"Avg confidence: {stats.get('avg_confidence', 0):.2f}"
            )
        else:
            parts.append("CrossValidator niedostepny (brak NIM?).")

        if dl:
            dl_stats = dl.get_stats()
            parts.append(
                f"\n*Disputes:*\n"
                f"Total: {dl_stats.get('total', 0)}\n"
                f"Unresolved: {dl_stats.get('unresolved', 0)}"
            )

        return "\n".join(parts)

    def _cmd_nauka(args):
        """Show learning goals and their progress."""
        gs = getattr(ctx, 'goal_store', None)
        if not gs:
            return "GoalStore niedostepny."

        args = args.strip()

        # /nauka <topic> - search by topic
        if args:
            goals = gs.find_by_topic(args)
            if not goals:
                return f"Brak celow nauki o '{args}'."
            lines = [f"*Nauka: {args}*"]
            for g in goals[:5]:
                status = g.status.value
                progress = f"{g.progress:.0%}"
                age = time.time() - g.created_at
                age_str = f"{age/3600:.0f}h" if age < 86400 else f"{age/86400:.0f}d"
                line = f"  [{g.id[:8]}] {status} | {progress} | {age_str} temu"
                if g.outcome:
                    score = g.outcome.get("final_score", 0)
                    line += f" | wynik: {score:.0%}"
                lines.append(line)
            return "\n".join(lines)

        # /nauka - list all LEARNING goals
        from agent_core.goals.goal_model import GoalType
        all_goals = [g for g in gs._goals.values() if g.type == GoalType.LEARNING]
        if not all_goals:
            return "Brak celow nauki."

        active = [g for g in all_goals if g.is_active]
        done = [g for g in all_goals if g.status.value == "achieved"]

        lines = [f"*Cele nauki: {len(active)} aktywnych, {len(done)} ukonczonych*"]
        for g in sorted(active, key=lambda x: x.priority, reverse=True)[:8]:
            topic = g.metadata.get("topic", g.description[:25])
            lines.append(f"  [{g.id[:8]}] {topic} | {g.progress:.0%} | pri={g.priority:.1f}")

        if done:
            lines.append(f"\n*Ukonczone ({len(done)}):*")
            for g in sorted(done, key=lambda x: x.updated_at, reverse=True)[:5]:
                topic = g.metadata.get("topic", g.description[:25])
                score = ""
                if g.outcome:
                    score = f" | wynik: {g.outcome.get('final_score', 0):.0%}"
                lines.append(f"  [{g.id[:8]}] {topic}{score}")

        return "\n".join(lines)

    def _cmd_beliefs(args):
        """Show belief store stats and run maintenance."""
        wm = getattr(ctx, 'world_model', None)
        if not wm:
            return "WorldModel niedostepny."

        args = args.strip()

        # /beliefs maintain - run full maintenance
        if args == "maintain":
            try:
                results = wm.maintain()
                parts = ["*Belief maintenance complete:*"]
                for k, v in results.items():
                    parts.append(f"  {k}: {v}")
                return "\n".join(parts)
            except Exception as e:
                return f"Blad maintenance: {e}"

        # /beliefs gaps - weakest topics
        if args == "gaps":
            try:
                gaps = wm.query.get_knowledge_gaps()[:10]
                if not gaps:
                    return "Brak luk w wiedzy."
                lines = ["*Najslabsze tematy:*"]
                for g in gaps:
                    lines.append(
                        f"  {g['topic']}: {g['confidence']:.0%} "
                        f"({g.get('belief_count', '?')} beliefs)"
                    )
                return "\n".join(lines)
            except Exception as e:
                return f"Blad: {e}"

        # /beliefs - stats overview (default)
        try:
            stats = wm.stats()
            by_type = stats.get("by_belief_type", {})
            by_etype = stats.get("by_entity_type", {})
            return (
                f"*Belief Store v2:*\n"
                f"Active: {stats.get('total', 0)} beliefs\n"
                f"All records: {stats.get('total_all', 0)}\n"
                f"Avg confidence: {stats.get('avg_confidence', 0):.0%}\n"
                f"\n*By type:*\n"
                f"  FACT: {by_type.get('fact', 0)}\n"
                f"  OBSERVATION: {by_type.get('observation', 0)}\n"
                f"  HYPOTHESIS: {by_type.get('hypothesis', 0)}\n"
                f"\n*By entity:*\n"
                f"  Topics: {by_etype.get('topic', 0)}\n"
                f"  Files: {by_etype.get('file', 0)}\n"
                f"  Concepts: {by_etype.get('concept', 0)}"
            )
        except Exception as e:
            return f"Blad: {e}"

    def _cmd_help(args):
        """List available commands grouped by category."""
        return (
            "*ClawBot - Komendy*\n"
            "\n*System:*\n"
            "/status - stan systemu\n"
            "/restart - restart Marii\n"
            "/authority [level] - autoryzacja\n"
            "\n*Cele i zatwierdzanie:*\n"
            "/goals - lista celow\n"
            "/approve <id> - zatwierdz cel\n"
            "/reject <id> - odrzuc cel\n"
            "/priority <id> <0-1> - priorytet\n"
            "\n*Wiedza i nauka:*\n"
            "/learn <temat> - naucz sie\n"
            "/nauka [temat] - postep nauki\n"
            "/memory <temat> - co Maria wie\n"
            "/beliefs [gaps|maintain] - beliefs\n"
            "/validate - cross-validation\n"
            "/board - tablica potrzeb\n"
            "\n*Kodowanie (Code Agent):*\n"
            "/code <zadanie> - zlec kodowanie\n"
            "/code approve - zatwierdz krok\n"
            "/code status - aktywna sesja\n"
            "/code history - historia\n"
            "\n*AI asystenci:*\n"
            "/claude <zadanie> - Claude (3/h)\n"
            "/codex <zadanie> - Codex/ChatGPT\n"
            "/analyze <modul> - analiza kodu\n"
            "\n*Przypomnienia i zadania:*\n"
            "/remind <tekst> <czas> - przypomnienie\n"
            "/remind list - lista przypomnien\n"
            "/remind dismiss <id> - usun\n"
            "/todo <tekst> - nowe zadanie\n"
            "/todo list - lista zadan\n"
            "/todo done <id> - oznacz zrobione\n"
            "\n*Proaktywnosc:*\n"
            "/proactive - status proaktywnego kontaktu\n"
            "/proactive on|off - wlacz/wylacz\n"
            "/proactive history - historia kontaktow\n"
            "/profile - profil operatora\n"
            "\n*Diagnostyka:*\n"
            "/tasks [N] - historia taskow Claude/Codex\n"
            "/pdf <task_id> - wyslij wynik jako PDF\n"
            "/trace [N|stats] - traces\n"
            "/efapprove <id> - zatwierdz efektor\n"
            "/efreject <id> - odrzuc efektor\n"
            "/efstatus - status efektora"
        )

    def _cmd_board(args):
        """Show cognitive bulletin board status."""
        bs = getattr(ctx, 'bulletin_store', None)
        if not bs:
            return "BulletinStore niedostepny."

        args = args.strip()

        # /board stats
        if not args or args == "stats":
            s = bs.stats()
            lines = [
                "*Tablica potrzeb poznawczych:*",
                f"Otwarte: {s['open']}",
                f"Actionable: {s['actionable']}",
                f"Total: {s['total']}",
            ]
            if s["by_type"]:
                lines.append("\n*By type:*")
                for t, c in sorted(s["by_type"].items()):
                    lines.append(f"  {t}: {c}")
            return "\n".join(lines)

        # /board open - list open entries
        if args == "open":
            entries = bs.get_open()
            if not entries:
                return "Tablica pusta - brak otwartych potrzeb."
            lines = ["*Otwarte potrzeby:*"]
            for e in entries[:15]:
                status_icon = {
                    "open": "NEW", "in_progress": "WIP",
                    "blocked": "BLK",
                }.get(e.status.value, e.status.value)
                lines.append(
                    f"  [{status_icon}] {e.entry_type.value}: "
                    f"{e.topic} (pri={e.priority:.1f})"
                )
                if e.goal_id:
                    lines.append(f"    goal: {e.goal_id[:16]}")
            return "\n".join(lines)

        # /board prune - cleanup stale entries
        if args == "prune":
            pruned = bs.prune_stale()
            return f"Pruned {pruned} stale entries."

        return "Uzycie: /board [open|prune]"

    def _send_result_pdf(task_id, backend, task_text, result, duration_ms=None, timestamp=None):
        """Generate PDF from result and send via Telegram."""
        try:
            from agent_core.telegram.pdf_export import generate_task_pdf
            pdf_path = generate_task_pdf(
                task_id=task_id, backend=backend,
                task_text=task_text, result=result,
                duration_ms=duration_ms, timestamp=timestamp,
            )
            if pdf_path:
                bridge.bot.send_document(
                    pdf_path,
                    caption=f"[{backend}] {task_text[:80]}",
                )
        except Exception as e:
            logger.debug(f"PDF export failed: {e}")

    def _cmd_codex(args):
        """Execute code task via Codex CLI: /codex <task description>"""
        if not args or not args.strip():
            return (
                "Uzycie: /codex <opis zadania>\n"
                "Przyklad: /codex przeanalizuj modul critic i zaproponuj ulepszenia\n"
                "Przyklad: /codex znajdz TODO i FIXME w agent_core/planner/\n"
                "Przyklad: /codex napisz test dla funkcji compute_belief_score"
            )
        task = args.strip()

        # Run async in background thread
        import threading

        def _run_codex_task():
            from agent_core.llm.task_store import TaskStore
            store = TaskStore()
            task_id = store.create_task(
                task_text=task, backend="codex",
                source="telegram_codex", timeout_s=300,
            )
            try:
                from agent_core.llm.codex_client import CodexClient
                codex = CodexClient(timeout_s=300)
                if not codex.is_available():
                    store.mark_failed(task_id, "Codex CLI niedostepny")
                    bridge.bot.send_message("[Code] Codex CLI niedostepny.")
                    return

                # Build prompt with project context
                prompt = (
                    f"Projekt M.A.R.I.A. (Python, agent_core/). "
                    f"Zadanie od operatora: {task}"
                )

                store.mark_running(task_id)
                bridge.bot.send_message(
                    f"[Code] Pracuje nad: {task[:80]}...\n"
                    f"(task: {task_id}, timeout: 5min)"
                )

                result = codex.ask(prompt, source="telegram_code", context={"task": task})
                if result:
                    store.mark_completed(task_id, result[:500])
                    # Send full result as PDF
                    task_rec = store.get_task(task_id)
                    _send_result_pdf(
                        task_id, "codex", task, result,
                        duration_ms=task_rec.get("duration_ms") if task_rec else None,
                        timestamp=task_rec.get("created_at") if task_rec else None,
                    )
                    # Trim for Telegram (4096 char limit)
                    if len(result) > 3800:
                        result = result[:3800] + "\n...(obciete)"
                    bridge.bot.send_message(f"[Code] Wynik:\n\n{result}")

                    # Save to bulletin board
                    bs = getattr(ctx, 'bulletin_store', None)
                    if bs:
                        try:
                            from agent_core.bulletin.bulletin_model import EntryType
                            bs.add_entry(
                                entry_type=EntryType.CODE_TASK,
                                topic=task[:100],
                                content=result[:500],
                                source="telegram_code",
                                metadata={"full_result_length": len(result), "task_id": task_id},
                            )
                        except Exception:
                            pass
                else:
                    # Check if it was a timeout (codex returns None on timeout)
                    store.mark_timeout(task_id, 300)
                    bridge.bot.send_message(
                        f"[Code] Brak odpowiedzi (timeout 5min).\n"
                        f"Task {task_id} zapisany - mozesz ponowic."
                    )
            except Exception as e:
                store.mark_failed(task_id, str(e)[:300])
                bridge.bot.send_message(f"[Code] Blad: {e}")

        t = threading.Thread(target=_run_codex_task, daemon=True)
        t.start()
        return f"Przyjeto zadanie: '{task[:60]}'. Wynik za chwile..."

    def _cmd_code(args):
        """Code Agent: /code <task|status|approve|reject|cancel|history>"""
        code_agent = getattr(ctx, 'code_agent', None)
        if not code_agent:
            return "Code Agent niedostepny."

        if not args or not args.strip():
            # Show status or help
            active = code_agent.get_active()
            if active:
                return active.describe()
            return (
                "*Code Agent - autonomiczne kodowanie*\n\n"
                "/code <zadanie> - zlec kodowanie\n"
                "/code status - aktywna sesja\n"
                "/code approve - zatwierdz krok\n"
                "/code reject - odrzuc krok\n"
                "/code cancel - anuluj sesje\n"
                "/code history - historia sesji\n\n"
                "Przyklad: /code zrob modul do glosu"
            )

        parts = args.strip().split(None, 1)
        subcmd = parts[0].lower()
        sub_args = parts[1] if len(parts) > 1 else ""

        if subcmd == "status":
            active = code_agent.get_active()
            if not active:
                return "Brak aktywnej sesji kodowania."
            return active.describe()

        elif subcmd == "approve":
            active = code_agent.get_active()
            if not active:
                return "Brak sesji czekajacych na zatwierdzenie."
            sid = sub_args.strip() if sub_args.strip() else active.session_id
            if code_agent.approve_checkpoint(sid):
                # Resume in background
                import threading
                def _resume():
                    try:
                        code_agent.resume(active.session_id)
                    except Exception as e:
                        bridge.bot.send_message(f"[Code] Blad przy wznowieniu: {e}")
                threading.Thread(target=_resume, daemon=True).start()
                return f"Zatwierdzono. Kontynuuje sesje {active.session_id[:8]}..."
            return "Nie ma czekajacego checkpointu."

        elif subcmd == "reject":
            active = code_agent.get_active()
            if not active:
                return "Brak sesji do odrzucenia."
            sid = sub_args.strip() if sub_args.strip() else active.session_id
            if code_agent.reject_checkpoint(sid):
                return f"Odrzucono - sesja anulowana."
            return "Nie ma czekajacego checkpointu."

        elif subcmd == "cancel":
            active = code_agent.get_active()
            if not active:
                return "Brak aktywnej sesji."
            if code_agent.cancel(active.session_id):
                return f"Sesja {active.session_id[:8]} anulowana."
            return "Nie mozna anulowac."

        elif subcmd == "history":
            sessions = code_agent.list_sessions(5)
            if not sessions:
                return "Brak sesji w historii."
            lines = ["*Historia Code Agent:*"]
            for s in sessions:
                files = len(s.files_written)
                lines.append(
                    f"  {s.session_id[:8]} {s.status.value} "
                    f"({files} plikow) {s.task_description[:40]}"
                )
            return "\n".join(lines)

        else:
            # Everything else is a task description
            task = args.strip()
            active = code_agent.get_active()
            if active and not active.status.is_terminal:
                return (
                    f"Aktywna sesja: {active.session_id[:8]} ({active.status.value})\n"
                    f"Uzyj /code cancel aby anulowac."
                )

            import threading
            def _run_code():
                try:
                    session = code_agent.start(task)
                    if session.status.value == "awaiting_approval":
                        pass  # Notification already sent by agent
                    elif session.status.value == "waiting_budget":
                        bridge.bot.send_message(
                            f"[Code] Brak budgetu LLM. Sesja {session.session_id[:8]} "
                            f"wznowi sie automatycznie."
                        )
                    elif session.status.value == "failed":
                        bridge.bot.send_message(
                            f"[Code] Nie udalo sie: {session.result_summary}"
                        )
                except Exception as e:
                    bridge.bot.send_message(f"[Code] Blad: {e}")

            threading.Thread(target=_run_code, daemon=True).start()
            return f"Rozpoczynam kodowanie: '{task[:60]}'. Plan za chwile..."

    def _cmd_analyze(args):
        """Analyze a module via Codex: /analyze <module_path>"""
        if not args or not args.strip():
            return (
                "Uzycie: /analyze <sciezka modulu>\n"
                "Przyklad: /analyze agent_core/critic\n"
                "Przyklad: /analyze agent_core/planner/planner_core.py"
            )
        module_path = args.strip()

        import threading

        def _run_analysis():
            from agent_core.llm.task_store import TaskStore
            store = TaskStore()
            task_id = store.create_task(
                task_text=f"analyze: {module_path}", backend="codex",
                source="telegram_analyze", timeout_s=300,
                metadata={"module": module_path},
            )
            try:
                from agent_core.llm.codex_client import CodexClient
                codex = CodexClient(timeout_s=300)
                if not codex.is_available():
                    store.mark_failed(task_id, "Codex CLI niedostepny")
                    bridge.bot.send_message("[Analyze] Codex CLI niedostepny.")
                    return

                prompt = (
                    f"Przeanalizuj modul '{module_path}' w projekcie M.A.R.I.A. "
                    f"(Python, katalog agent_core/). "
                    f"Opisz: 1) Co robi modul 2) Jakie ma problemy/TODO "
                    f"3) Propozycje ulepszen (max 3). "
                    f"Odpowiedz zwiezle po polsku."
                )

                store.mark_running(task_id)
                bridge.bot.send_message(
                    f"[Analyze] Analizuje: {module_path}...\n"
                    f"(task: {task_id}, timeout: 5min)"
                )

                result = codex.ask(prompt, source="telegram_analyze", context={"module": module_path})
                if result:
                    store.mark_completed(task_id, result[:500])
                    task_rec = store.get_task(task_id)
                    _send_result_pdf(
                        task_id, "codex", f"analyze: {module_path}", result,
                        duration_ms=task_rec.get("duration_ms") if task_rec else None,
                        timestamp=task_rec.get("created_at") if task_rec else None,
                    )
                    if len(result) > 3800:
                        result = result[:3800] + "\n...(obciete)"
                    bridge.bot.send_message(f"[Analyze] {module_path}:\n\n{result}")

                    # Post improvement proposals to bulletin
                    bs = getattr(ctx, 'bulletin_store', None)
                    if bs:
                        try:
                            from agent_core.bulletin.bulletin_model import EntryType
                            bs.add_entry(
                                entry_type=EntryType.IMPROVEMENT,
                                topic=f"Analiza: {module_path}",
                                content=result[:500],
                                source="telegram_analyze",
                                metadata={"module": module_path, "task_id": task_id},
                            )
                        except Exception:
                            pass
                else:
                    store.mark_timeout(task_id, 300)
                    bridge.bot.send_message(
                        f"[Analyze] Brak odpowiedzi (timeout 5min).\n"
                        f"Task {task_id} zapisany - mozesz ponowic."
                    )
            except Exception as e:
                store.mark_failed(task_id, str(e)[:300])
                bridge.bot.send_message(f"[Analyze] Blad: {e}")

        t = threading.Thread(target=_run_analysis, daemon=True)
        t.start()
        return f"Analizuje modul: '{module_path}'. Wynik za chwile..."

    def _cmd_claude(args):
        """Execute task via Claude Code CLI: /claude <task>"""
        if not args or not args.strip():
            return (
                "Uzycie: /claude <opis zadania>\n"
                "Przyklad: /claude przeanalizuj planner_core.py i znajdz potencjalne bugi\n"
                "Przyklad: /claude zaproponuj refactor modulu critic\n"
                "Limit: 3/h, 15/dzien (subskrypcja operatora)"
            )
        task = args.strip()

        import threading

        def _run_claude_task():
            from agent_core.llm.task_store import TaskStore
            store = TaskStore()
            task_id = store.create_task(
                task_text=task, backend="claude",
                source="telegram_claude", timeout_s=300,
            )
            try:
                from agent_core.llm.claude_client import ClaudeClient
                client = ClaudeClient(timeout_s=300)
                if not client.is_available():
                    store.mark_failed(task_id, "Claude CLI niedostepny")
                    bridge.bot.send_message("[Claude] CLI niedostepny.")
                    return

                stats = client.get_stats()
                if stats["remaining_hour"] <= 0:
                    store.mark_failed(task_id, "rate_limited")
                    bridge.bot.send_message(
                        f"[Claude] Limit godzinowy wyczerpany "
                        f"({stats['calls_this_hour']}/{stats['max_per_hour']}). "
                        f"Sprobuj pozniej."
                    )
                    return

                store.mark_running(task_id)
                bridge.bot.send_message(
                    f"[Claude] Pracuje nad: {task[:80]}...\n"
                    f"(task: {task_id}, timeout: 5min, "
                    f"zostalo {stats['remaining_hour']}/{stats['max_per_hour']})"
                )

                result = client.ask(
                    prompt=f"Projekt M.A.R.I.A. (Python, agent_core/). Zadanie: {task}",
                    source="telegram_claude",
                    context={"task": task},
                )
                if result:
                    store.mark_completed(task_id, result[:500])
                    task_rec = store.get_task(task_id)
                    _send_result_pdf(
                        task_id, "claude", task, result,
                        duration_ms=task_rec.get("duration_ms") if task_rec else None,
                        timestamp=task_rec.get("created_at") if task_rec else None,
                    )
                    if len(result) > 3800:
                        result = result[:3800] + "\n...(obciete)"
                    bridge.bot.send_message(f"[Claude] Wynik:\n\n{result}")

                    bs = getattr(ctx, 'bulletin_store', None)
                    if bs:
                        try:
                            from agent_core.bulletin.bulletin_model import EntryType
                            bs.add_entry(
                                entry_type=EntryType.CODE_TASK,
                                topic=task[:100],
                                content=result[:500],
                                source="telegram_claude",
                                metadata={"backend": "claude", "task_id": task_id},
                            )
                        except Exception:
                            pass
                else:
                    store.mark_timeout(task_id, 300)
                    bridge.bot.send_message(
                        f"[Claude] Brak odpowiedzi (timeout 5min).\n"
                        f"Task {task_id} zapisany - mozesz ponowic."
                    )
            except Exception as e:
                store.mark_failed(task_id, str(e)[:300])
                bridge.bot.send_message(f"[Claude] Blad: {e}")

        t = threading.Thread(target=_run_claude_task, daemon=True)
        t.start()
        return f"Przyjeto (Claude): '{task[:60]}'. Wynik za chwile..."

    def _cmd_tasks(args):
        """Show recent tasks: /tasks [N]"""
        from agent_core.llm.task_store import TaskStore
        store = TaskStore()
        limit = 5
        if args and args.strip().isdigit():
            limit = min(int(args.strip()), 20)
        tasks = store.get_recent(limit)
        if not tasks:
            return "Brak zapisanych taskow."
        lines = [f"*Ostatnie {len(tasks)} taskow:*"]
        for t in reversed(tasks):
            tid = t.get("task_id", "?")
            status = t.get("status", "?")
            backend = t.get("backend", "?")
            text = t.get("task_text", "?")[:50]
            dur = t.get("duration_ms")
            dur_str = f" {dur/1000:.0f}s" if dur else ""
            err = t.get("error", "")
            err_str = f" | {err[:40]}" if err else ""
            lines.append(f"  `{tid}` [{backend}] {status}{dur_str}{err_str}\n  {text}")
        return "\n".join(lines)

    def _cmd_pdf(args):
        """Re-export a past task as PDF: /pdf <task_id>"""
        if not args or not args.strip():
            return (
                "Uzycie: /pdf <task_id>\n"
                "Uzyj /tasks aby zobaczyc dostepne taski."
            )
        task_id = args.strip()
        from agent_core.llm.task_store import TaskStore
        store = TaskStore()
        # Support prefix matching
        task = store.get_task(task_id)
        if not task:
            # Try prefix match
            for t in reversed(store.get_recent(50)):
                if t.get("task_id", "").startswith(task_id):
                    task = t
                    break
        if not task:
            return f"Task '{task_id}' nie znaleziony. Uzyj /tasks."
        if task.get("status") != "COMPLETED":
            return f"Task {task['task_id']} status: {task.get('status')} (PDF tylko dla COMPLETED)."
        summary = task.get("result_summary", "")
        if not summary:
            return f"Task {task['task_id']} nie ma zapisanego wyniku."
        _send_result_pdf(
            task["task_id"], task.get("backend", "?"),
            task.get("task_text", "?"), summary,
            duration_ms=task.get("duration_ms"),
            timestamp=task.get("created_at"),
        )
        return f"PDF wygenerowany dla task {task['task_id']}."

    def _cmd_profile(args):
        """Operator profile: /profile [set|rhythm|add_interest|remove_interest] <text>"""
        om = getattr(ctx, 'operator_model', None) or getattr(ctx, 'user_profile', None)
        if not om:
            return "OperatorModel niedostepny."

        if not args or not args.strip():
            return om.get_summary()

        parts = args.strip().split(None, 1)
        subcmd = parts[0].lower()
        text = parts[1] if len(parts) > 1 else ""

        if subcmd == "set" and text:
            # /profile set job plytkarz
            kv = text.split(None, 1)
            if len(kv) < 2:
                return "Uzycie: /profile set <klucz> <wartosc>"
            key, value = kv[0], kv[1]
            om.set_fact(key, value, 1.0, "explicit:telegram")
            return f"Ustawiono {key} = {value}"
        elif subcmd == "rhythm":
            r = om.rhythm
            if r.confidence == 0:
                return "Brak danych o rytmie dnia (za malo interakcji)."
            return (
                f"*Rytm dnia:*\n"
                f"Wstaje: ~{r.typical_wake_hour}:00\n"
                f"Praca: {r.work_hours[0]}:00-{r.work_hours[1]}:00\n"
                f"Spi od: ~{r.typical_sleep_hour}:00\n"
                f"Pewnosc: {r.confidence:.0%} (probek: {r.sample_count})"
            )
        elif subcmd == "add_interest" and text:
            ok = om.add_interest(text)
            return f"Dodano zainteresowanie: {text}" if ok else f"Juz znane: {text}"
        elif subcmd == "add_fact" and text:
            ok = om.add_fact(text)
            return f"Dodano fakt: {text}" if ok else f"Juz znane: {text}"
        elif subcmd == "remove_interest" and text:
            ok = om.remove_interest(text)
            return f"Usunieto: {text}" if ok else f"Nie znaleziono: {text}"
        elif subcmd == "remove_fact" and text:
            ok = om.remove_fact(text)
            return f"Usunieto: {text}" if ok else f"Nie znaleziono: {text}"
        else:
            return (
                "*Profil operatora:*\n"
                "/profile - pokaz profil\n"
                "/profile set <klucz> <wartosc>\n"
                "/profile rhythm - rytm dnia\n"
                "/profile add\\_interest <temat>\n"
                "/profile add\\_fact <fakt>\n"
                "/profile remove\\_interest <temat>\n"
                "/profile remove\\_fact <klucz>"
            )

    def _cmd_remind(args):
        """Telegram: /remind <text> <time> | /remind list | /remind dismiss <id>"""
        rs = getattr(ctx, 'reminder_store', None)
        if not rs:
            return "Przypomnienia nie zainicjalizowane"
        if not args:
            return "Uzycie: /remind <tekst> <czas>\nNp: /remind spotkanie za 30min\n/remind list\n/remind dismiss <id>"

        parts = args.split(None, 1) if isinstance(args, str) else [args]
        sub = parts[0].lower() if parts else ""

        if sub == "list":
            pending = rs.get_pending()
            if not pending:
                return "Brak aktywnych przypomnien"
            from agent_core.reminders import format_scheduled_time
            lines = [f"*Przypomnienia ({len(pending)}):*"]
            for r in sorted(pending, key=lambda x: x.scheduled_at):
                when = format_scheduled_time(r.scheduled_at)
                recur = f" [{r.recurrence.value}]" if r.recurrence.value != "ONCE" else ""
                lines.append(f"  {r.id}: {r.text} - {when}{recur}")
            return "\n".join(lines)

        if sub == "dismiss" and len(parts) > 1:
            rest = parts[1].strip()
            rem = _find_by_prefix(rs.get_pending(), rest)
            if not rem:
                return f"Nie znaleziono: {rest}"
            rs.dismiss(rem.id)
            return f"Usunieto: {rem.id}"

        if sub == "snooze" and len(parts) > 1:
            rest = parts[1].strip().split()
            id_pref = rest[0]
            minutes = int(rest[1]) if len(rest) > 1 else 15
            rem = _find_by_prefix(rs.get_pending(), id_pref)
            if not rem:
                return f"Nie znaleziono: {id_pref}"
            rs.snooze(rem.id, minutes)
            return f"Odlozono o {minutes}min: {rem.id}"

        # Create reminder: /remind <text> <time>
        from agent_core.reminders import Reminder, parse_time, format_scheduled_time
        text = args if isinstance(args, str) else " ".join(args)
        tokens = text.split()
        scheduled = None
        reminder_text = text

        # Try last 2 tokens as time, then last 1
        for n in (2, 1):
            if len(tokens) >= n + 1:
                candidate = " ".join(tokens[-n:])
                ts = parse_time(candidate)
                if ts is not None:
                    scheduled = ts
                    reminder_text = " ".join(tokens[:-n])
                    break

        if scheduled is None:
            scheduled = time.time() + 1800  # default 30min

        rem = Reminder(text=reminder_text, scheduled_at=scheduled)
        rs.add(rem)
        when = format_scheduled_time(scheduled)
        return f"Przypomnienie: {rem.id}\n\"{reminder_text}\" - {when}"

    def _cmd_todo(args):
        """Telegram: /todo <text> | /todo list | /todo done <id>"""
        ts = getattr(ctx, 'todo_store', None)
        if not ts:
            return "Zadania nie zainicjalizowane"
        if not args:
            # Show pending by default
            pending = ts.get_pending()
            if not pending:
                return "Brak aktywnych zadan"
            lines = [f"*Zadania ({len(pending)}):*"]
            for t in pending:
                prio = f" [{t.priority.value}]" if t.priority.value != "NORMAL" else ""
                lines.append(f"  {t.id}: {t.text}{prio}")
            return "\n".join(lines)

        parts = args.split(None, 1) if isinstance(args, str) else [args]
        sub = parts[0].lower() if parts else ""

        if sub == "list":
            pending = ts.get_pending()
            if not pending:
                return "Brak aktywnych zadan"
            lines = [f"*Zadania ({len(pending)}):*"]
            for t in pending:
                prio = f" [{t.priority.value}]" if t.priority.value != "NORMAL" else ""
                lines.append(f"  {t.id}: {t.text}{prio}")
            return "\n".join(lines)

        if sub == "done" and len(parts) > 1:
            id_pref = parts[1].strip()
            todo = _find_by_prefix(ts.get_pending(), id_pref)
            if not todo:
                return f"Nie znaleziono: {id_pref}"
            ts.complete(todo.id)
            return f"Zrobione: {todo.id} \"{todo.text}\""

        if sub == "cancel" and len(parts) > 1:
            id_pref = parts[1].strip()
            todo = _find_by_prefix(ts.get_pending(), id_pref)
            if not todo:
                return f"Nie znaleziono: {id_pref}"
            ts.cancel(todo.id)
            return f"Anulowano: {todo.id}"

        # Create: /todo <text>
        from agent_core.reminders import Todo
        text = args if isinstance(args, str) else " ".join(args)
        todo = Todo(text=text)
        ts.add(todo)
        return f"Zadanie: {todo.id}\n\"{text}\""

    def _find_by_prefix(items, prefix):
        """Find item by ID or ID prefix."""
        prefix = prefix.strip()
        for item in items:
            if item.id == prefix or item.id.startswith(prefix):
                return item
        return None

    def _cmd_proactive(args):
        """Handle /proactive [status|on|off|history]."""
        sched = ctx.proactive_scheduler if hasattr(ctx, 'proactive_scheduler') else None
        if not sched:
            return "Proactive contact not initialized"

        parts = args.split() if isinstance(args, str) else list(args)
        sub = parts[0].lower() if parts else "status"

        if sub == "on":
            sched.set_enabled(True)
            return "Proaktywny kontakt: WLACZONY"

        if sub == "off":
            sched.set_enabled(False)
            return "Proaktywny kontakt: WYLACZONY"

        if sub == "history":
            limit = 5
            if len(parts) > 1:
                try:
                    limit = int(parts[1])
                except ValueError:
                    pass
            history = sched.get_history(limit)
            if not history:
                return "Brak historii kontaktow"
            lines = [f"*Ostatnie kontakty ({len(history)}):*"]
            for h in history:
                from datetime import datetime
                ts = h.get("timestamp", 0)
                dt = datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else "?"
                reason = h.get("reason", "?")
                lines.append(f"  [{dt}] {reason}")
            return "\n".join(lines)

        # Default: status
        status = sched.get_status()
        state = "WLACZONY" if status["enabled"] else "WYLACZONY"
        lines = [
            f"*Proaktywny kontakt: {state}*",
            f"Dzisiaj: {status['contacts_today']}/{status['max_per_day']}",
            f"Cisza nocna: {'tak' if status['quiet_hours'] else 'nie'}",
            f"Idle operatora: {status['operator_idle_human']}",
        ]
        # Next possible contacts
        for reason, info in status.get("cooldowns", {}).items():
            remaining = info.get("remaining_sec", 0)
            if remaining > 0:
                from agent_core.homeostasis.time_awareness import TimeAwareness
                lines.append(f"  {reason}: za {TimeAwareness.format_duration(remaining)}")
        return "\n".join(lines)

    def _cmd_privacy(args):
        """Privacy boundaries: /privacy [add|remove|list] <topic>"""
        om = getattr(ctx, 'operator_model', None)
        if not om:
            return "OperatorModel niedostepny."
        if not args or not args.strip():
            boundaries = om.get_boundaries()
            if not boundaries:
                return "Brak granic prywatnosci. Uzyj /privacy add <temat>"
            lines = ["*Granice prywatnosci:*"]
            for b in boundaries:
                lines.append(f"  - {b}")
            lines.append("\n/privacy add <temat> | /privacy remove <temat>")
            return "\n".join(lines)

        parts = args.strip().split(None, 1)
        subcmd = parts[0].lower()
        text = parts[1] if len(parts) > 1 else ""

        if subcmd == "add" and text:
            ok = om.add_boundary(text)
            return f"Dodano granice: {text}" if ok else f"Juz istnieje: {text}"
        elif subcmd == "remove" and text:
            ok = om.remove_boundary(text)
            return f"Usunieto granice: {text}" if ok else f"Nie znaleziono: {text}"
        elif subcmd == "list":
            return _cmd_privacy("")
        else:
            return "Uzycie: /privacy add <temat> | /privacy remove <temat> | /privacy list"

    def _cmd_context(args):
        """Current context: /context <text> [hours] | /context clear"""
        om = getattr(ctx, 'operator_model', None)
        if not om:
            return "OperatorModel niedostepny."
        if not args or not args.strip():
            current = om.get_context()
            if current:
                return f"Aktualny kontekst: {current}"
            return "Brak kontekstu. Uzyj /context <tekst> [godziny]"

        text = args.strip()
        if text.lower() == "clear":
            om.clear_context()
            return "Kontekst wyczyszczony."

        # Parse optional hours at the end: "/context deadline today 8"
        parts = text.rsplit(None, 1)
        hours = 24
        if len(parts) == 2:
            try:
                hours = int(parts[1])
                text = parts[0]
            except ValueError:
                pass  # Last word wasn't a number, use full text

        om.set_context(text, expires_hours=hours)
        return f"Kontekst ustawiony: {text} (wygasa za {hours}h)"

    def _cmd_capabilities(args):
        """What can Maria do: /capabilities"""
        manifest = getattr(ctx, 'capability_manifest', None)
        if not manifest:
            return "CapabilityManifest niedostepny."
        return manifest.get_summary()

    bridge.register_command("capabilities", _cmd_capabilities)
    bridge.register_command("privacy", _cmd_privacy)
    bridge.register_command("context", _cmd_context)
    bridge.register_command("proactive", _cmd_proactive)
    bridge.register_command("remind", _cmd_remind)
    bridge.register_command("todo", _cmd_todo)
    bridge.register_command("profile", _cmd_profile)
    bridge.register_command("pdf", _cmd_pdf)
    bridge.register_command("tasks", _cmd_tasks)
    bridge.register_command("claude", _cmd_claude)
    bridge.register_command("code", _cmd_code)
    bridge.register_command("codex", _cmd_codex)
    bridge.register_command("analyze", _cmd_analyze)
    bridge.register_command("board", _cmd_board)
    bridge.register_command("status", _cmd_status)
    bridge.register_command("goals", _cmd_goals)
    bridge.register_command("approve", _cmd_approve)
    bridge.register_command("reject", _cmd_reject)
    bridge.register_command("restart", _cmd_restart)
    bridge.register_command("priority", _cmd_priority)
    bridge.register_command("learn", _cmd_learn)
    bridge.register_command("trace", _cmd_trace)
    bridge.register_command("memory", _cmd_memory)
    bridge.register_command("validate", _cmd_validate)
    bridge.register_command("beliefs", _cmd_beliefs)
    bridge.register_command("nauka", _cmd_nauka)
    bridge.register_command("efapprove", _cmd_efapprove)
    bridge.register_command("efreject", _cmd_efreject)
    bridge.register_command("efstatus", _cmd_efstatus)
    bridge.register_command("authority", _cmd_authority)
    bridge.register_command("help", _cmd_help)
    bridge.register_command("start", lambda a: _cmd_help(a))  # Handle /start from Telegram


def _build_work_context(ctx) -> str:
    """
    Build short work status text for chat system prompt.

    Reads planner, deliberation, experiment, and learning state.
    Returns max ~300 chars so it doesn't bloat the prompt.
    """
    parts = []

    # Last planner action
    if ctx.planner_core:
        try:
            history = ctx.planner_core.get_history(limit=1)
            if history:
                last = history[-1]
                action = last.get("action_type", "?")
                msg = last.get("message", "")
                status = last.get("status", "?")
                if action != "skip" and msg:
                    parts.append(f"Ostatnia akcja: {msg}")
        except Exception:
            pass

    # Active deliberation strategy
    if ctx.deliberation:
        try:
            status = ctx.deliberation.get_status()
            active = status.get("active_details", [])
            if active:
                s = active[0]
                tmpl = s.get("template", "?")
                step = s.get("current_step", "?")
                parts.append(f"Strategia: {tmpl} - {step}")
        except Exception:
            pass

    # Experiment proposals waiting
    if ctx.experiment_system:
        try:
            proposals = ctx.experiment_system.proposal_engine.get_active_proposals()
            if proposals:
                parts.append(f"{len(proposals)} propozycji eksperymentow czeka na zatwierdzenie")

            if ctx.experiment_system.runner.is_running:
                exp = ctx.experiment_system.runner.get_current()
                if exp:
                    parts.append(f"Eksperyment w toku: {exp.parameter_id}")
        except Exception:
            pass

    # Knowledge snapshot
    if ctx.knowledge_analyzer:
        try:
            snap = ctx.knowledge_analyzer.get_knowledge_snapshot()
            if snap:
                by_status = snap.get("files_by_status", {})
                learning = len(by_status.get("learning", []))
                completed = len(by_status.get("completed", []))
                total = snap.get("total_files", 0)
                if learning > 0:
                    parts.append(f"Ucze sie: {learning} plikow w toku, {completed}/{total} ukonczonych")
                elif total > 0:
                    parts.append(f"Wiedza: {completed}/{total} plikow ukonczonych")
        except Exception:
            pass

    # Vision - what Maria sees
    if ctx.vision_cortex:
        try:
            last = ctx.vision_cortex.last_percept
            if last and last.summary:
                parts.append(f"Wzrok: {last.summary}")
        except Exception:
            pass

    if not parts:
        return ""

    return "; ".join(parts)
