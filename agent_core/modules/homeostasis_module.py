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

                # Wire LLM router to executor for ASK_EXPERT actions
                if ctx.brain and hasattr(ctx.brain, 'ask_encyclopedia'):
                    planner.executor.set_llm_router(ctx.brain)

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
                    print("[Homeostasis] [OK] Telegram bridge wired (ClawBot)")
                else:
                    print("[Homeostasis] [--] Telegram not configured (set TELEGRAM_BOT_TOKEN in .env)")
            except Exception as e:
                logger.debug(f"Telegram bridge not initialized: {e}")

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

    def _cmd_help(args):
        """List available commands."""
        return (
            "*Komendy ClawBot:*\n"
            "/status - stan systemu\n"
            "/goals - lista celow\n"
            "/trace [N|stats|failed|ep-ID] - traces\n"
            "/memory <temat> - co Maria wie\n"
            "/memory gaps - luki w wiedzy\n"
            "/learn <temat> - naucz sie o temacie\n"
            "/approve <id> - zatwierdz cel\n"
            "/reject <id> - odrzuc cel\n"
            "/priority <id> <0-1> - zmien priorytet\n"
            "/efapprove <id> - zatwierdz efektor\n"
            "/efreject <id> - odrzuc efektor\n"
            "/efstatus - status efektora\n"
            "/authority [level] - zmien poziom autoryzacji\n"
            "/restart - restart Marii\n"
            "/help - ta pomoc"
        )

    bridge.register_command("status", _cmd_status)
    bridge.register_command("goals", _cmd_goals)
    bridge.register_command("approve", _cmd_approve)
    bridge.register_command("reject", _cmd_reject)
    bridge.register_command("restart", _cmd_restart)
    bridge.register_command("priority", _cmd_priority)
    bridge.register_command("learn", _cmd_learn)
    bridge.register_command("trace", _cmd_trace)
    bridge.register_command("memory", _cmd_memory)
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

    if not parts:
        return ""

    return "; ".join(parts)
