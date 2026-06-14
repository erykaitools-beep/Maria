"""Homeostasis REPL commands: /homeostasis [status|start|stop|events|summary]."""

import logging
import os
import threading
import time
from datetime import datetime

from agent_core.registry import MariaModule, CommandInfo
from agent_core.homeostasis.core import HomeostasisCore
from agent_core.homeostasis.state_model import Mode
from agent_core.homeostasis.event_logger import get_event_logger
from agent_core.memory.manager import MemoryManager
from agent_core.llm.manager import LLMManager
from agent_core.modules.homeostasis_outbox import _propose_outbox_status_note
from agent_core.modules.homeostasis_telegram_commands import (
    register_telegram_commands,
)

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
            core._shared_context = ctx
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
                logger.warning(f"ModelScheduler not initialized: {e}")

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

        # Warm-pin exam models (student=llama3.1, grader=qwen3) so the first
        # exam after a restart doesn't pay the cold-start inference penalty
        # (~8 min of 240s timeouts, 2026-06-04). Background thread, ENV-gated
        # (MARIA_WARMUP=0 to disable). Runs even without SemanticMemory.
        if core:
            try:
                from agent_core.llm.warmup import start_background_warmup
                start_background_warmup()
            except Exception as e:
                logger.warning(f"[Homeostasis] Model warm-up failed to start: {e}")

        # Initialize LLM Tape (raw interaction logging)
        if core:
            try:
                from agent_core.llm.llm_tape import LLMTape
                from maria_core.sys.config import BASE_DIR
                tape_path = BASE_DIR / "meta_data" / "llm_tape.jsonl"
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
                # Promoted from debug to warning — the previous silent
                # debug() swallowed an AttributeError from a nonexistent
                # SharedContext attribute, causing zero writes to
                # llm_tape.jsonl from 2026-04-13 until 2026-04-17.
                logger.warning(f"[Homeostasis] LLM Tape init failed: {e}")

        # Initialize OperatorModel (K14 - replaces UserProfile)
        try:
            from agent_core.operator.operator_model import get_operator_model
            from agent_core.operator.rhythm_detector import RhythmDetector
            operator_model = get_operator_model()
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
            logger.warning(f"OperatorModel not initialized: {e}")

        # Initialize PerceptionBuffer (Warstwa 1)
        if core:
            try:
                from agent_core.perception.buffer import PerceptionBuffer
                perception_buffer = PerceptionBuffer(maxlen=200)
                core.set_perception_buffer(perception_buffer)
                ctx.perception_buffer = perception_buffer
                print("[Homeostasis] [OK] PerceptionBuffer initialized (maxlen=200)")
            except Exception as e:
                logger.warning(f"PerceptionBuffer not initialized: {e}")

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
                logger.warning(f"SandboxManager not initialized: {e}")

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
            logger.warning(f"GoalStore not initialized: {e}")

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
            logger.warning(f"EvaluationObserver not initialized: {e}")

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

        # NOTE: BeliefStore wiring for sleep consolidation moved BELOW, right
        # after `ctx.world_model = world_model` -- the old check here ran
        # before ctx.world_model was assigned (line ~347 in this same init),
        # so it never fired and NREM2/NREM3 were a silent no-op in production
        # (wired-but-dead class, found 2026-06-10).

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
                logger.warning(f"Teacher agent not wired: {e}")

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
                    # Self-healing trust gate (#2, 2026-06-01): a loaded store may
                    # still hold file beliefs admitted before the gate on a
                    # self-graded 'completed'. Reconcile once on every startup so
                    # only independently-verified knowledge stays canonical.
                    try:
                        pruned = world_model.reconcile_trust()
                        if pruned:
                            print(f"[Homeostasis] [OK] WorldModel trust-reconciled "
                                  f"({pruned} self-graded file beliefs pruned)")
                    except Exception as _e:
                        logger.warning(f"WorldModel trust reconcile skipped: {_e}")
                    planner.set_world_model(world_model)
                    ctx.world_model = world_model
                    # Wire BeliefStore for sleep consolidation (NREM2/NREM3).
                    # MUST happen after world_model exists -- see the note at
                    # the old (dead) wiring site above. Own try: a wiring
                    # failure must not be mislogged as "WorldModel not
                    # initialized" by the outer except.
                    try:
                        core.set_belief_store(world_model.store)
                        print("[Homeostasis] [OK] BeliefStore wired for "
                              "sleep consolidation (NREM2/NREM3)")
                    except Exception as _wire_e:
                        logger.warning(
                            f"Sleep consolidation wiring failed: {_wire_e}")
                except Exception as e:
                    logger.warning(f"WorldModel not initialized: {e}")

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
                    logger.warning(f"AutonomyPolicy not initialized: {e}")

                # Deliberation (K8) for multi-step strategies
                try:
                    from agent_core.deliberation import Deliberation
                    deliberation = Deliberation()
                    planner.set_deliberation(deliberation)
                    ctx.deliberation = deliberation
                    print("[Homeostasis] [OK] Deliberation wired (K8)")
                except Exception as e:
                    logger.warning(f"Deliberation not initialized: {e}")

                # Meta-Cognition (K9) for self-reflection
                try:
                    from agent_core.meta_cognition import MetaCognition
                    meta_cognition = MetaCognition()
                    planner.set_meta_cognition(meta_cognition)
                    ctx.meta_cognition = meta_cognition
                    print("[Homeostasis] [OK] MetaCognition wired (K9)")
                except Exception as e:
                    logger.warning(f"MetaCognition not initialized: {e}")

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
                    logger.warning(f"ActionSafety not initialized: {e}")

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
                    logger.warning(f"ExperimentSystem not initialized: {e}")

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

                        # EffectorCoordinator: preflight/prewarm/retry/diagnose
                        try:
                            from agent_core.effector.coordinator import EffectorCoordinator
                            _bs = ctx.bulletin_store if hasattr(ctx, 'bulletin_store') else None
                            _tg = ctx.telegram_notifier if hasattr(ctx, 'telegram_notifier') else None
                            coord = EffectorCoordinator(
                                openclaw_client=openclaw,
                                bulletin_store=_bs,
                                telegram_notifier=_tg,
                                homeostasis_core=ctx.core if hasattr(ctx, 'core') else None,
                            )
                            ctx.effector_coordinator = coord
                            planner.executor.set_effector_coordinator(coord)
                            print("[Homeostasis] [OK] EffectorCoordinator wired (preflight+prewarm+retry)")
                        except Exception as e:
                            logger.warning(f"EffectorCoordinator init failed: {e}")
                    else:
                        logger.warning("OpenClaw gateway not running, effector disabled")
                except Exception as e:
                    logger.warning(f"OpenClaw not initialized: {e}")

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
                    logger.warning(f"CrossValidator not initialized: {e}")

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
                    logger.warning(f"Codex CLI not initialized: {e}")

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
                    if ctx.consciousness:
                        sa.set_consciousness(ctx.consciousness)

                    # Wire Claude CLI client (K12 Phase 2) — gated to prevent
                    # Anthropic account ban from autonomous subscription CLI usage.
                    # Default: disabled. Operator-triggered paths (Telegram /claude)
                    # are unaffected and keep working regardless.
                    import os
                    autonomous_claude = os.environ.get(
                        "CLAUDE_CLI_AUTONOMOUS", ""
                    ).lower() in ("true", "1", "yes")
                    if autonomous_claude:
                        try:
                            from agent_core.self_analysis.claude_cli_client import ClaudeCLIClient
                            claude_cli = ClaudeCLIClient()
                            if ctx.openclaw_client:
                                claude_cli.set_openclaw_client(ctx.openclaw_client)
                            sa._analyzer.set_claude_cli(claude_cli)
                            if claude_cli.is_available():
                                print("[Homeostasis] [!!] Claude CLI AUTONOMOUS enabled (ban risk)")
                            else:
                                print("[Homeostasis] [--] Claude CLI not available (fallback: local)")
                        except Exception as e2:
                            logger.warning(f"Claude CLI not wired: {e2}")
                    else:
                        print("[Homeostasis] [--] Claude CLI autonomous DISABLED (safe mode)")

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

                    # Concept trust-gate observe scan (2026-06-13): the FILE/index
                    # trust gate filters self-graded exams, but the CONCEPT path
                    # (build_concept_beliefs) never did -- so concept-FACTs can
                    # rest on a self-graded exam. Read-only census reported here
                    # (NOT at WorldModel init -- bulletin_store does not exist that
                    # early) so the standing gap is visible on the board BEFORE
                    # arming CONCEPT_TRUST_GATE. Pure observe: scan mutates nothing.
                    try:
                        _wm = getattr(ctx, "world_model", None)
                        census = _wm.scan_concept_trust() if _wm else {}
                        if census and census.get("self_graded", 0) > 0:
                            from agent_core.world_model.belief_builder import (
                                _concept_trust_mode,
                            )
                            _mode = _concept_trust_mode()
                            core.event_logger._write_event({
                                "timestamp": time.time(),
                                "event": "concept_trust_scan",
                                "mode": _mode,
                                "total_fact": census["total_fact"],
                                "independent": census["independent"],
                                "self_graded": census["self_graded"],
                            })
                            print(
                                f"[Homeostasis] [OK] Concept trust scan: "
                                f"{census['self_graded']}/{census['total_fact']} "
                                f"concept-FACTs self-graded "
                                f"({census['independent']} independent, "
                                f"mode={_mode})"
                            )
                            from agent_core.bulletin.bulletin_model import EntryType
                            bulletin_store.create_and_post(
                                entry_type=EntryType.NEED_REVIEW,
                                topic="Koncept trust-gate: FACT z samo-ocenionego egzaminu",
                                reason_code="concept_trust_self_graded",
                                summary=(
                                    f"{census['self_graded']}/{census['total_fact']} "
                                    f"koncept-FACTow opiera sie na egzaminie "
                                    f"samo-ocenionym (nie niezaleznym); "
                                    f"{census['independent']} niezaleznych. "
                                    f"tryb={_mode}. Uzbrojenie: "
                                    f"CONCEPT_TRUST_GATE=armed w .env + restart."
                                ),
                                requested_by="concept_trust_scan",
                                metadata={
                                    "total_fact": census["total_fact"],
                                    "independent": census["independent"],
                                    "self_graded": census["self_graded"],
                                    "mode": _mode,
                                },
                            )
                    except Exception as _e:
                        logger.warning(f"Concept trust scan skipped: {_e}")

                    # Late-bind bulletin into EffectorCoordinator if it was
                    # created before this store existed (order-of-init).
                    if hasattr(ctx, 'effector_coordinator') and ctx.effector_coordinator:
                        ctx.effector_coordinator.set_bulletin_store(bulletin_store)

                    # D2 (2026-04-26): late-bind into K12 SelfAnalysis so
                    # strategic recs post IMPROVEMENT entries instead of
                    # misrouted LEARNING goals. SelfAnalysis is wired earlier
                    # in init, before this store exists.
                    if hasattr(ctx, 'self_analysis') and ctx.self_analysis:
                        ctx.self_analysis.set_bulletin_store(bulletin_store)

                    # R1 (2026-05-29): late-bind into Critic so quality findings
                    # post NEED_REVIEW advisories instead of PROPOSED goals
                    # (260 critic goals aged to ABANDONED without being worked).
                    if hasattr(ctx, 'critic_agent') and ctx.critic_agent:
                        ctx.critic_agent.set_bulletin_store(bulletin_store)

                    # Most #2 step 1 (2026-05-08): late-bind K11 ProposalEngine
                    # into K12 SelfAnalysis. Recommendations with
                    # suggested_action="experiment" are passed through
                    # k12_to_k11_router heuristics; matches become K11 Proposals
                    # (DRAFT or auto-approved by confidence).
                    if (hasattr(ctx, 'self_analysis') and ctx.self_analysis
                            and hasattr(ctx, 'experiment_system')
                            and ctx.experiment_system):
                        ctx.self_analysis.set_proposal_engine(
                            ctx.experiment_system.proposal_engine
                        )
                        print("[Homeostasis] [OK] K12->K11 router wired (Most #2)")

                    # D3 (2026-04-26): late-bind into K13 Creative so the
                    # LoopDetector posts IMPROVEMENT entries when an abandoned
                    # meta-goal pattern is suppressed.
                    if hasattr(ctx, 'creative_module') and ctx.creative_module:
                        ctx.creative_module.set_bulletin_store(bulletin_store)

                    # D4 (2026-04-26): mode-aware learning — wire the
                    # post-mortem recorder + analyzer so recurring REDUCED
                    # root causes surface in the bulletin. Recorder feeds
                    # JSONL; analyzer clusters and posts IMPROVEMENT entries
                    # with mode_aware=True so the planner can soft-defer.
                    try:
                        from agent_core.self_analysis.mode_postmortem import (
                            ModePostmortemRecorder,
                        )
                        from agent_core.self_analysis.mode_analyzer import (
                            ModeAnalyzer,
                        )
                        from maria_core.sys.config import BASE_DIR as _BASE_DIR

                        pm_recorder = ModePostmortemRecorder(
                            postmortem_path=(
                                _BASE_DIR / "meta_data" / "mode_postmortems.jsonl"
                            ),
                        )
                        mode_analyzer = ModeAnalyzer(
                            postmortem_recorder=pm_recorder,
                            bulletin_store=bulletin_store,
                        )
                        pm_recorder.set_analyzer(mode_analyzer)

                        if hasattr(ctx, 'homeostasis_core') and ctx.homeostasis_core:
                            ctx.homeostasis_core.set_mode_postmortem_recorder(
                                pm_recorder,
                            )
                        ctx.mode_postmortem_recorder = pm_recorder
                        ctx.mode_analyzer = mode_analyzer
                        print("[Homeostasis] [OK] D4 mode-aware learning wired")
                    except Exception as e:
                        logger.warning(f"D4 mode-aware not initialized: {e}")

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
                    # Warstwa 3: cross-check audit claims against real material
                    if hasattr(ctx, 'memory_query') and ctx.memory_query:
                        gap_planner.set_memory_query(ctx.memory_query)
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

                    # Wire critic + bulletin into TeacherAgent for gap-driven priorities
                    if core._teacher_agent:
                        if hasattr(ctx, 'critic_agent') and ctx.critic_agent:
                            core._teacher_agent.set_critic_agent(ctx.critic_agent)
                        core._teacher_agent.set_bulletin_store(bulletin_store)
                        logger.info("[TEACHER] Critic + BulletinStore wired for gap-driven learning")
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
                    # ... and to the planner itself, so post-EVALUATE
                    # maintain() can run SEMANTIC belief dedup (flag-gated,
                    # SEMANTIC_DEDUP_ENABLED). NOTE: the live instance is
                    # ctx.semantic_search -- ctx.semantic_memory is never
                    # assigned anywhere (found 2026-06-10).
                    planner.set_semantic_memory(ctx.semantic_search)

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
                        make_fs_write_handler,
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

                    _consc = ctx.consciousness if hasattr(ctx, 'consciousness') else None
                    cap_router.register("learn", make_learn_handler(
                        _teacher, _analyzer, _sem, _goals, _tg,
                        consciousness=_consc,
                    ), DEFAULT_CAPABILITY_SPECS["learn"])
                    cap_router.register("exam", make_exam_handler(
                        _teacher, _analyzer, _goals, _tg,
                        consciousness=_consc,
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
                        _analyzer, _sem, _goals,
                    ), DEFAULT_CAPABILITY_SPECS["fetch"])

                    # Experiment (K11)
                    _exp = ctx.experiment_system if hasattr(ctx, 'experiment_system') else None
                    cap_router.register("experiment", make_experiment_handler(
                        _exp,
                    ), DEFAULT_CAPABILITY_SPECS["experiment"])

                    # Effector (OpenClaw) — coordinator preferred, client fallback
                    _claw = ctx.openclaw_client if hasattr(ctx, 'openclaw_client') else None
                    _coord = ctx.effector_coordinator if hasattr(ctx, 'effector_coordinator') else None
                    cap_router.register("effector", make_effector_handler(
                        _claw, effector_coordinator=_coord,
                    ), DEFAULT_CAPABILITY_SPECS["effector"])

                    # FS_WRITE (B2) -- first real effector primitive, sandboxed.
                    # Inert unless FS_WRITE_ENABLED + a goal carries a file_exists
                    # criterion; closes that goal on external evidence.
                    cap_router.register("fs_write", make_fs_write_handler(
                        _goals, telegram_notifier=_tg,
                    ), DEFAULT_CAPABILITY_SPECS["fs_write"])

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

                        # Wire HonestyProtocol (K15.2) - evidence-based confidence
                        try:
                            from agent_core.operator.honesty_protocol import HonestyProtocol
                            honesty = HonestyProtocol()
                            honesty.set_capability_manifest(manifest)
                            ctx.honesty_protocol = honesty
                            print("[Homeostasis] [OK] HonestyProtocol (K15.2) wired")
                        except Exception as e:
                            logger.warning(f"HonestyProtocol not initialized: {e}")

                        # Wire StateReporter (K15.1) - structured self-status
                        try:
                            from agent_core.operator.state_reporter import StateReporter
                            state_reporter = StateReporter()
                            state_reporter.set_capability_manifest(manifest)
                            if core:
                                state_reporter.set_homeostasis_core(core)
                            if ctx.goal_store:
                                state_reporter.set_goal_store(ctx.goal_store)
                            if ctx.knowledge_analyzer:
                                state_reporter.set_knowledge_analyzer(ctx.knowledge_analyzer)
                            if hasattr(ctx, 'identity_store') and ctx.identity_store:
                                state_reporter.set_identity_store(ctx.identity_store)
                            ctx.state_reporter = state_reporter
                            print("[Homeostasis] [OK] StateReporter (K15.1) wired")
                        except Exception as e:
                            logger.warning(f"StateReporter not initialized: {e}")

                        # Wire GrowthAwareness (K15.3) - limitations as targets
                        try:
                            from agent_core.operator.growth_awareness import GrowthAwareness
                            growth = GrowthAwareness()
                            growth.set_capability_manifest(manifest)
                            if hasattr(ctx, 'honesty_protocol') and ctx.honesty_protocol:
                                growth.set_honesty_protocol(ctx.honesty_protocol)
                            if ctx.knowledge_analyzer:
                                growth.set_knowledge_analyzer(ctx.knowledge_analyzer)
                            growth.refresh()
                            ctx.growth_awareness = growth
                            _target_count = len(growth.get_targets(status="identified"))
                            print(f"[Homeostasis] [OK] GrowthAwareness (K15.3) wired ({_target_count} targets)")
                        except Exception as e:
                            logger.warning(f"GrowthAwareness not initialized: {e}")

                    except Exception as e:
                        logger.warning(f"CapabilityManifest not initialized: {e}")
                except Exception as e:
                    logger.warning(f"CapabilityRouter not initialized: {e}")

                # Strategic Planner (v2 Phase B) - LLM-powered planning layer
                try:
                    from agent_core.planner.strategic_planner import StrategicPlanner
                    strategic = StrategicPlanner()
                    if ctx.goal_store:
                        strategic.set_goal_store(ctx.goal_store)
                    if ctx.knowledge_analyzer:
                        strategic.set_knowledge_analyzer(ctx.knowledge_analyzer)
                    if ctx.evaluation_observer:
                        strategic.set_evaluation_observer(ctx.evaluation_observer)
                    # Wire LLM via router ask_as_role
                    if ctx.brain and hasattr(ctx.brain, 'ask_as_role'):
                        strategic.set_llm_fn(ctx.brain.ask_as_role)
                    elif ctx.brain and hasattr(ctx.brain, 'ollama') and hasattr(ctx.brain.ollama, 'ask_as_role'):
                        strategic.set_llm_fn(ctx.brain.ollama.ask_as_role)
                    planner.set_strategic_planner(strategic)
                    ctx.strategic_planner = strategic
                    print("[Homeostasis] [OK] StrategicPlanner wired (v2 Phase B)")
                except Exception as e:
                    logger.warning(f"StrategicPlanner not initialized: {e}")

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
                logger.warning(f"PlannerCore not wired: {e}")

        # Initialize Telegram bridge (operator notifications)
        if core:
            try:
                from agent_core.telegram import TelegramBridge
                telegram = TelegramBridge()
                if telegram.configured:
                    core.set_telegram_bridge(telegram)
                    ctx.telegram_bridge = telegram

                    # Register basic commands
                    register_telegram_commands(telegram, ctx)

                    # Wire notifier to planner's action executor + Phase 5 approval flow
                    if ctx.planner_core:
                        ctx.planner_core.executor.set_telegram_notifier(telegram.notifier)
                        ctx.planner_core.set_telegram_notifier(telegram.notifier)

                    # Late-bind Telegram notifier into EffectorCoordinator
                    # so notify_effector_incident works (coordinator was
                    # constructed before Telegram came up).
                    ctx.telegram_notifier = telegram.notifier
                    if hasattr(ctx, 'effector_coordinator') and ctx.effector_coordinator:
                        ctx.effector_coordinator.set_telegram_notifier(telegram.notifier)

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
                        logger.warning(f"TaskStore recovery skipped: {e}")

                    print("[Homeostasis] [OK] Telegram bridge wired (ClawBot)")
                else:
                    print("[Homeostasis] [--] Telegram not configured (set TELEGRAM_BOT_TOKEN in .env)")
            except Exception as e:
                logger.warning(f"Telegram bridge not initialized: {e}")

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
                    logger.warning(f"USB webcam not available: {e}")
                    print("[Homeostasis] [OK] VisionCortex initialized (no sensor)")

                ctx.vision_cortex = vision_cortex
                core.set_vision_cortex(vision_cortex)
            except Exception as e:
                logger.warning(f"VisionCortex not initialized: {e}")

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
            # Audyt 2026-06-12: send_message bylo fantomem na TelegramNotifier
            # -- AttributeError ubijal caly init w KAZDYM z ~290 bootow od
            # deployu (02-22). Realne API: send_raw; parse_mode=None bo wyniki
            # code-taskow niosa podkreslniki (sciezki, komendy checkpointow),
            # ktore Markdown po cichu zjada (lekcja /approve_note 06-08).
            if ctx.telegram_bridge and hasattr(ctx.telegram_bridge, 'notifier'):
                _ca_notifier = ctx.telegram_bridge.notifier
                code_agent.set_notify_fn(
                    lambda text, _n=_ca_notifier: _n.send_raw(text, parse_mode=None)
                )
            ctx.code_agent = code_agent
            print("[Homeostasis] [OK] Code Agent initialized")
        except Exception as e:
            logger.warning(f"Code Agent not initialized: {e}")

        # Start introspection scheduler (daily code self-model refresh)
        try:
            from agent_core.introspection.scheduler import IntrospectionScheduler
            from maria_core.sys.config import BASE_DIR as _INTRO_BASE
            intro_sched = IntrospectionScheduler(
                project_root=str(_INTRO_BASE),
                interval_sec=86400,  # 24h (AST scan is heavy)
            )
            intro_sched.start()
            print("[Homeostasis] [OK] Introspection scheduler started (24h)")
        except Exception as e:
            # Promoted debug->warning — SharedContext.config bug 2026-04-13.
            logger.warning(f"[Homeostasis] Introspection scheduler not started: {e}")

        # Wire state-grounded operator response pipeline (Phase 2)
        try:
            from agent_core.introspection.query_router import OperationalQueryRouter
            from agent_core.introspection.evidence_collector import EvidenceCollector
            from agent_core.introspection.response_builder import ResponseBuilder
            from maria_core.sys.config import BASE_DIR as _EC_BASE

            qr = OperationalQueryRouter()
            ec = EvidenceCollector(project_root=str(_EC_BASE))
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
            # Promoted debug->warning — SharedContext.config bug 2026-04-13.
            logger.warning(f"[Homeostasis] Grounding pipeline not wired: {e}")

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
            logger.warning(f"Reminders not initialized: {e}")

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

            # Wire weather sensor (M3: WeatherSensor + SalienceFilter)
            _owm_key = os.environ.get("OPENWEATHERMAP_API_KEY", "")
            _owm_city = ""
            if om:
                _owm_city = om.get_fact_value("city", "") if hasattr(om, "get_fact_value") else ""
            if not _owm_city:
                _owm_city = os.environ.get("OPENWEATHERMAP_CITY", "")
            if _owm_key and _owm_city:
                try:
                    from agent_core.weather import WeatherSensor, is_weather_salient, format_weather_line
                    _weather_sensor = WeatherSensor(api_key=_owm_key, city=_owm_city)
                    ctx.weather_sensor = _weather_sensor

                    def _weather_accessor(_ws=_weather_sensor, _om=om):
                        data = _ws.fetch()
                        if data is None:
                            return None
                        salient = is_weather_salient(data, _om)
                        return format_weather_line(data, salient)

                    gen.set_weather_fn(_weather_accessor)
                    print(f"[Homeostasis] [OK] WeatherSensor ({_owm_city})")
                except Exception as e:
                    logger.warning("WeatherSensor init failed: %s", e)

            # Wire Faza 3: Operational Perception (holidays, system, workspace, fusion)
            try:
                from agent_core.weather.holiday_sensor import HolidaySensor
                from agent_core.homeostasis.sensors.system_sensor import SystemSensor
                from agent_core.homeostasis.sensors.workspace_sensor import WorkspaceSensor
                from agent_core.perception.salience_filter import SalienceFilter
                from agent_core.perception.fusion import PerceptionFusion

                _holiday = HolidaySensor()
                _sys_sensor = SystemSensor()
                _ws_sensor = WorkspaceSensor()
                _salience = SalienceFilter(operator_model=om)
                _fusion = PerceptionFusion()
                _fusion.set_holiday_sensor(_holiday)
                _fusion.set_system_sensor(_sys_sensor)
                _fusion.set_workspace_sensor(_ws_sensor)
                _fusion.set_salience_filter(_salience)
                if hasattr(ctx, 'weather_sensor') and ctx.weather_sensor:
                    from agent_core.weather import is_weather_salient, format_weather_line as _fmt_weather
                    _ws_ref = ctx.weather_sensor
                    def _weather_for_fusion(_ws=_ws_ref, _om=om):
                        data = _ws.fetch()
                        if data is None:
                            return None
                        sal = is_weather_salient(data, _om)
                        return _fmt_weather(data, sal)
                    _fusion.set_weather_fn(_weather_for_fusion)

                gen.set_perception_fn(lambda _f=_fusion: _f.format_for_brief())

                ctx.holiday_sensor = _holiday
                ctx.system_sensor = _sys_sensor
                ctx.workspace_sensor = _ws_sensor
                ctx.salience_filter = _salience
                ctx.perception_fusion = _fusion

                _holiday_today = _holiday.format_today()
                _holiday_info = f", dzis: {_holiday_today}" if _holiday_today else ""
                print(f"[Homeostasis] [OK] PerceptionFusion (Faza 3){_holiday_info}")
            except Exception as e:
                logger.warning(f"PerceptionFusion not initialized: {e}")

            # Wire Digital Hands (Faza 4)
            try:
                from agent_core.hands import (
                    ExecutionJournal, TaskExecutor, ResultValidator,
                    WebResearcher, FileManager,
                )
                _journal = ExecutionJournal()
                _validator = ResultValidator()
                _task_exec = TaskExecutor(journal=_journal, validator=_validator)
                _web_researcher = WebResearcher()
                _file_manager = FileManager()

                # Wire web researcher with existing web_source clients
                try:
                    from agent_core.web_source.wiki_client import WikiClient
                    from agent_core.web_source.content_writer import ContentWriter
                    _web_researcher.set_wiki_client(WikiClient())
                    _web_researcher.set_content_writer(ContentWriter())
                except Exception:
                    pass

                # Register tool handlers
                _task_exec.register_tool("wiki_search", _web_researcher.search_wikipedia)
                _task_exec.register_tool("web_fetch", _web_researcher.fetch_url)
                _task_exec.register_tool("search_and_save", _web_researcher.search_and_save)
                _task_exec.register_tool("file_write", _file_manager.write_note)
                _task_exec.register_tool("file_read", _file_manager.read_file)
                _task_exec.register_tool("file_list", _file_manager.list_files)

                ctx.execution_journal = _journal
                ctx.task_executor = _task_exec
                ctx.web_researcher = _web_researcher
                ctx.file_manager = _file_manager

                print(f"[Homeostasis] [OK] Digital Hands (Faza 4, {len(_task_exec.get_available_tools())} tools)")
            except Exception as e:
                logger.warning(f"Digital Hands not initialized: {e}")

            # Wire Workflow Orchestration (Faza 5)
            try:
                from agent_core.workflow import WorkflowStore, WorkflowEngine, DelegationManager, ProgressReporter
                from agent_core.planner.planner_model import Plan, PlanStatus, ActionType, create_plan

                _wf_store = WorkflowStore()
                _delegation = DelegationManager()

                # Wire delegation to capability router and task executor
                if ctx.capability_router:
                    _delegation.set_capability_router(ctx.capability_router)
                    _delegation.set_plan_factory(
                        lambda action, params, gid: create_plan(
                            goal_id=gid,
                            goal_description=f"workflow step: {action}",
                            action_type=ActionType(action),
                            action_params=params,
                        )
                    )
                if ctx.task_executor:
                    _delegation.set_task_executor(ctx.task_executor)

                _wf_engine = WorkflowEngine(_wf_store, _delegation)

                # Wire progress reporter
                _wf_reporter = ProgressReporter()
                if ctx.perception_buffer:
                    _wf_reporter.set_perception_buffer(ctx.perception_buffer)
                if ctx.telegram_bridge:
                    _wf_reporter.set_telegram_notifier(
                        lambda msg: ctx.telegram_bridge.send_message(msg)
                        if hasattr(ctx.telegram_bridge, 'send_message')
                        else None
                    )
                _wf_engine.set_progress_reporter(_wf_reporter)

                # Recover interrupted workflows
                _interrupted = _wf_store.recover_interrupted()

                ctx.workflow_engine = _wf_engine
                ctx.workflow_store = _wf_store

                _wf_count = _wf_store.count()
                _int_info = f", {len(_interrupted)} recovered" if _interrupted else ""
                print(f"[Homeostasis] [OK] Workflow Engine (Faza 5, {_wf_count} workflows{_int_info})")
            except Exception as e:
                logger.warning(f"Workflow Engine not initialized: {e}")

            # Wire Environment Adaptation (Faza 6)
            try:
                from agent_core.environment import EnvironmentManager, ModeDetector

                _env_detector = ModeDetector()
                if core:
                    _env_detector.set_homeostasis_core(core)
                if ctx.user_profile:
                    _env_detector.set_operator_model(ctx.user_profile)

                _env_manager = EnvironmentManager(detector=_env_detector)
                ctx.environment_manager = _env_manager

                _env_mode = _env_manager.get_active_mode().value
                print(f"[Homeostasis] [OK] Environment Manager (Faza 6, mode={_env_mode})")
            except Exception as e:
                logger.warning(f"Environment Manager not initialized: {e}")

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
            logger.warning(f"Proactive contact not initialized: {e}")

        # Faza 7: Trust & Autonomy Graduation
        try:
            from agent_core.autonomy.incident_memory import IncidentMemory
            from agent_core.autonomy.trust_scorer import TrustScorer
            from agent_core.autonomy.auto_promotion import AutoPromotion

            incident_memory = IncidentMemory()
            ctx.incident_memory = incident_memory

            trust_scorer = TrustScorer()
            # Wire available data sources
            if ctx.goal_store:
                trust_scorer.set_goal_store(ctx.goal_store)
            if getattr(ctx, 'approval_queue', None):
                trust_scorer.set_approval_queue(ctx.approval_queue)
            trust_scorer.set_incident_memory(incident_memory)
            if getattr(ctx, 'meta_cognition', None):
                try:
                    tracker = ctx.meta_cognition._confidence
                    trust_scorer.set_confidence_tracker(tracker)
                except Exception:
                    pass
            if getattr(ctx, 'authority_manager', None):
                trust_scorer.set_authority_manager(ctx.authority_manager)
            ctx.trust_scorer = trust_scorer

            auto_promotion = AutoPromotion(
                trust_scorer=trust_scorer,
                authority_manager=getattr(ctx, 'authority_manager', None),
                goal_store=ctx.goal_store if ctx.goal_store else None,
            )
            ctx.auto_promotion = auto_promotion

            # Wire Telegram notifications for promotion events
            if ctx.telegram_bridge:
                try:
                    auto_promotion.set_notify_fn(ctx.telegram_bridge.bot.send_message)
                except Exception:
                    pass

            avg_trust = trust_scorer.get_average_trust()
            inc_count = incident_memory.count()
            # Wire incident memory to planner executor
            if planner:
                planner.set_incident_memory(incident_memory)

            print(f"[Homeostasis] [OK] Faza 7 Trust & Autonomy (trust={avg_trust:.2f}, incidents={inc_count})")
        except Exception as e:
            logger.warning(f"Faza 7 not initialized: {e}")

        # Most #1: Bulletin Escalator (Phase 9.6 — k12 advisory -> PROPOSED goal)
        try:
            from agent_core.bulletin.escalator import BulletinEscalator
            _bull_store = getattr(ctx, 'bulletin_store', None)
            _goal_store = getattr(ctx, 'goal_store', None)
            if _bull_store and _goal_store:
                ctx.bulletin_escalator = BulletinEscalator(
                    bulletin_store=_bull_store,
                    goal_store=_goal_store,
                )
                print("[Homeostasis] [OK] BulletinEscalator wired (Most #1, Phase 9.6)")
            else:
                logger.warning(
                    f"BulletinEscalator skipped: bulletin_store={_bull_store is not None}, "
                    f"goal_store={_goal_store is not None}"
                )
        except Exception as e:
            logger.warning(f"BulletinEscalator not initialized: {e}")

        # Wire tick hooks for Faza 5+6+7 + Most #1
        if core:
            if ctx.workflow_engine:
                core.set_workflow_engine(ctx.workflow_engine)
            if ctx.environment_manager:
                core.set_environment_manager(ctx.environment_manager)
            if getattr(ctx, 'auto_promotion', None):
                core.set_auto_promotion(ctx.auto_promotion)
            if getattr(ctx, 'bulletin_escalator', None):
                core.set_bulletin_escalator(ctx.bulletin_escalator)

        # Self-Perception (Phase 18 — periodic self-state snapshots)
        if core:
            try:
                from agent_core.self_perception import SelfPerception, SnapshotStore
                self_perception = SelfPerception(
                    ctx=ctx,
                    snapshot_store=SnapshotStore(),
                    bulletin_store=getattr(ctx, 'bulletin_store', None),
                )
                ctx.self_perception = self_perception
                core.set_self_perception(self_perception)
                print("[Homeostasis] [OK] SelfPerception wired (Phase 18)")
            except Exception as e:
                logger.warning(f"SelfPerception not initialized: {e}")

        # Conductor (Phase 17 — delegated build orchestration, e.g. market_agent)
        try:
            from agent_core.conductor import Conductor
            conductor = Conductor()
            ctx.conductor = conductor
            if core:
                core.set_conductor(conductor)
            print("[Homeostasis] [OK] Conductor wired (Phase 17)")

        except Exception as e:
            logger.warning(f"Conductor not initialized: {e}")

        # Maria-repo conductor (T-SELF-003) — separate queue for self-repair
        # and other maria-project tasks. Independent of market_agent.
        try:
            from agent_core.conductor import Conductor
            from agent_core.conductor.task_queue import TaskQueue
            from pathlib import Path

            maria_queue_path = Path("meta_data/maria_task_queue.jsonl")
            maria_conductor = Conductor(queue=TaskQueue(path=maria_queue_path))
            ctx.maria_conductor = maria_conductor
            if core:
                core.set_maria_conductor(maria_conductor)
            print("[Homeostasis] [OK] Maria conductor wired (project=maria)")
        except Exception as e:
            logger.warning(f"Maria conductor not initialized: {e}")

        # Self-Repair (Phase 19 — systemic failure detection + STOP-AT-PENDING)
        if (
            core
            and getattr(ctx, 'self_perception', None)
            and getattr(ctx, 'maria_conductor', None)
        ):
            try:
                from pathlib import Path
                from agent_core.self_repair import (
                    RepairTaskCreator,
                    SystemFailureMonitor,
                    TaskBoardWriter,
                )

                repair_creator = RepairTaskCreator(
                    conductor=ctx.maria_conductor,
                    bulletin_store=getattr(ctx, 'bulletin_store', None),
                    task_board_writer=TaskBoardWriter(),
                    notifier=getattr(ctx, 'telegram_notifier', None),
                    self_perception=ctx.self_perception,
                )
                monitor = SystemFailureMonitor(
                    self_perception=ctx.self_perception,
                    conductor=ctx.maria_conductor,
                    audit_path=Path("meta_data/action_audit.jsonl"),
                    repair_task_creator=repair_creator,
                    heartbeat_provider=core,  # 7b: per-thread liveness (flag-gated)
                )
                ctx.repair_task_creator = repair_creator
                ctx.system_failure_monitor = monitor
                core.set_system_failure_monitor(monitor)
                core.set_bulletin_store(getattr(ctx, 'bulletin_store', None))
                core.set_telegram_notifier(getattr(ctx, 'telegram_notifier', None))
                print("[Homeostasis] [OK] SelfRepair wired (Phase 19)")
            except Exception as e:
                logger.warning(f"SelfRepair not initialized: {e}", exc_info=True)

        # Outbox (TIER 2 hands, Rung 2) -- operator-visible artifact via a gated
        # write. The autonomous side only PROPOSES (flag OUTBOX_WRITE_ENABLED);
        # the write happens only on /approve_note. Wired with its own try/except.
        if core is not None:
            try:
                from pathlib import Path as _Path
                from agent_core.hands.outbox import OutboxProposalStore
                try:
                    from maria_core.sys.config import BASE_DIR as _base
                    _base = str(_base)
                except Exception:
                    _base = "."  # CWD fallback (systemd WorkingDirectory + os.chdir)
                ctx.outbox_store = OutboxProposalStore(
                    path=_Path(_base) / "meta_data" / "outbox_proposals.jsonl",
                    base_dir=_base,
                )
                core.set_outbox_proposer(
                    lambda reason: _propose_outbox_status_note(ctx, reason)
                )
                print("[Homeostasis] [OK] Outbox wired (Rung 2 hands)")
            except Exception as e:
                logger.warning(f"Outbox not initialized: {e}", exc_info=True)

        # Autonomous Codex dispatcher (Phase 17) — one per project.
        # Wired AFTER Conductor with its own try/except so a telegram
        # wiring glitch can't take Conductor down with it. Falls through
        # silently if codex_client unavailable; manual /codex Telegram
        # path stays operational regardless.
        if core and getattr(ctx, 'conductor', None) and getattr(ctx, 'codex_client', None):
            try:
                from agent_core.conductor.dispatcher import (
                    ConductorDispatcher,
                )
                notify = None
                if ctx.telegram_bridge and hasattr(ctx.telegram_bridge, 'bot'):
                    notify = ctx.telegram_bridge.bot.send_message
                dispatcher = ConductorDispatcher(
                    conductor=ctx.conductor,
                    codex_client=ctx.codex_client,
                    project="market_agent",
                    notify_fn=notify,
                )
                core.add_conductor_dispatcher(dispatcher)
                print(
                    "[Homeostasis] [OK] ConductorDispatcher wired "
                    "(project=market_agent, autonomous Codex dispatch)"
                )
            except Exception as e:
                logger.warning(f"ConductorDispatcher not wired: {e}")

        # Maria-repo dispatcher (T-SELF-003). Workspace is the maria repo
        # itself. Tasks are seeded by self_repair (T-SELF-002) or manually
        # via Conductor.add_task. Inline mode — branch refactor/homeostasis.
        if (
            core
            and getattr(ctx, 'maria_conductor', None)
            and getattr(ctx, 'codex_client', None)
        ):
            try:
                from agent_core.conductor.dispatcher import ConductorDispatcher
                notify = None
                if ctx.telegram_bridge and hasattr(ctx.telegram_bridge, 'bot'):
                    notify = ctx.telegram_bridge.bot.send_message
                maria_dispatcher = ConductorDispatcher(
                    conductor=ctx.maria_conductor,
                    codex_client=ctx.codex_client,
                    project="maria",
                    notify_fn=notify,
                )
                core.add_conductor_dispatcher(maria_dispatcher)
                print(
                    "[Homeostasis] [OK] ConductorDispatcher wired "
                    "(project=maria, autonomous Codex dispatch)"
                )
            except Exception as e:
                logger.warning(f"Maria ConductorDispatcher not wired: {e}")

        # IntentRouter (Faza K Deska #1 Phase 2 — T-IR-002 wire-up)
        try:
            from agent_core.routing import IntentRouter
            from agent_core.homeostasis.time_awareness import TimeAwareness
            ctx.intent_router = IntentRouter(
                weather_sensor=getattr(ctx, 'weather_sensor', None),
                time_awareness=TimeAwareness,
                memory_query=getattr(ctx, 'memory_query', None),
                self_model=None,
                capability_router=getattr(ctx, 'capability_router', None),
                effector_coordinator=getattr(ctx, 'effector_coordinator', None),
                enabled=None,
            )
            print(
                f"[Homeostasis] [OK] IntentRouter wired "
                f"(enabled={ctx.intent_router._enabled})"
            )
        except Exception as e:
            logger.warning(f"IntentRouter not initialized: {e}")

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
            CommandInfo(
                "/workflow", self._cmd_workflow,
                "  /workflow              - lista aktywnych workflow\n"
                "  /workflow list         - lista wszystkich workflow\n"
                "  /workflow start <tmpl> [topic] - uruchom z szablonu\n"
                "  /workflow pause <id>   - wstrzymaj workflow\n"
                "  /workflow resume <id>  - wznow workflow\n"
                "  /workflow cancel <id>  - anuluj workflow\n"
                "  /workflow progress <id>- postep workflow\n"
                "  /workflow templates    - dostepne szablony",
                "[BRAIN] WORKFLOW",
            ),
            CommandInfo(
                "/env", self._cmd_env,
                "  /env                   - aktualny tryb srodowiska\n"
                "  /env list              - dostepne tryby\n"
                "  /env switch <mode>     - przelacz tryb (default/learning/monitoring/quiet)\n"
                "  /env auto              - wlacz auto-detekcje",
                "[BRAIN] ENVIRONMENT",
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

    # --- Workflow commands (Faza 5) ---

    def _cmd_workflow(self, args):
        """Handle /workflow commands."""
        engine = self.ctx.workflow_engine
        if not engine:
            print("[Workflow] Not initialized")
            return

        sub = args[0].lower() if args else "status"

        if sub in ("status", ""):
            self._wf_show_active(engine)
        elif sub == "list":
            self._wf_show_all(engine)
        elif sub == "templates":
            self._wf_show_templates()
        elif sub == "start" and len(args) >= 2:
            topic = " ".join(args[2:]) if len(args) > 2 else None
            self._wf_start(engine, args[1], topic)
        elif sub == "pause" and len(args) >= 2:
            self._wf_control(engine, "pause", args[1])
        elif sub == "resume" and len(args) >= 2:
            self._wf_control(engine, "resume", args[1])
        elif sub == "cancel" and len(args) >= 2:
            self._wf_control(engine, "cancel", args[1])
        elif sub == "progress" and len(args) >= 2:
            self._wf_show_progress(engine, args[1])
        else:
            print("[Workflow] Usage: /workflow [list|start|pause|resume|cancel|progress|templates]")

    def _wf_show_active(self, engine):
        active = engine.list_workflows()
        active = [w for w in active if w["status"] in ("running", "pending", "paused")]
        if not active:
            print("[Workflow] No active workflows")
            return
        print(f"\n{'='*50}")
        print("[WORKFLOW] Active Workflows")
        print(f"{'='*50}")
        for w in active:
            print(f"  {w['workflow_id'][:12]}  {w['name']:<20} {w['status']:<10} {w['progress_pct']:.0f}%")
        print()

    def _wf_show_all(self, engine):
        wfs = engine.list_workflows()
        if not wfs:
            print("[Workflow] No workflows")
            return
        print(f"\n{'='*50}")
        print(f"[WORKFLOW] All Workflows ({len(wfs)})")
        print(f"{'='*50}")
        for w in wfs:
            print(f"  {w['workflow_id'][:12]}  {w['name']:<20} {w['status']:<10} {w['progress_pct']:.0f}%")
        print()

    def _wf_show_templates(self):
        try:
            from agent_core.workflow.templates import WORKFLOW_TEMPLATES
            print(f"\n{'='*50}")
            print("[WORKFLOW] Available Templates")
            print(f"{'='*50}")
            for name, tmpl in WORKFLOW_TEMPLATES.items():
                topic = " <topic>" if tmpl["needs_topic"] else ""
                print(f"  {name:<15} ~{tmpl['estimated_minutes']}min  {tmpl['description']}")
                print(f"                  /workflow start {name}{topic}")
            print()
        except Exception as e:
            print(f"[Workflow] Error: {e}")

    def _wf_start(self, engine, template_name, topic=None):
        try:
            from agent_core.workflow.templates import WORKFLOW_TEMPLATES
            if template_name not in WORKFLOW_TEMPLATES:
                print(f"[Workflow] Unknown template: {template_name}")
                print(f"  Available: {', '.join(WORKFLOW_TEMPLATES.keys())}")
                return
            tmpl = WORKFLOW_TEMPLATES[template_name]
            if tmpl["needs_topic"] and not topic:
                print(f"[Workflow] Template '{template_name}' requires a topic")
                print(f"  Usage: /workflow start {template_name} <topic>")
                return

            if tmpl["needs_topic"]:
                steps = tmpl["factory"](topic)
            else:
                steps = tmpl["factory"]()

            desc = f"{tmpl['description']}" + (f": {topic}" if topic else "")
            wf = engine.create(template_name, desc, steps)
            engine.start(wf.workflow_id)
            print(f"[Workflow] Started: {wf.workflow_id[:12]} ({len(steps)} steps)")
        except Exception as e:
            print(f"[Workflow] Error: {e}")

    def _wf_control(self, engine, action, wf_id_prefix):
        # Find workflow by prefix
        wf = None
        for w in engine.list_workflows():
            if w["workflow_id"].startswith(wf_id_prefix):
                wf = w
                break
        if not wf:
            print(f"[Workflow] Not found: {wf_id_prefix}")
            return

        full_id = wf["workflow_id"]
        if action == "pause":
            ok = engine.pause(full_id)
        elif action == "resume":
            ok = engine.resume(full_id)
        elif action == "cancel":
            ok = engine.cancel(full_id, "operator")
        else:
            ok = False

        status = "OK" if ok else "failed"
        print(f"[Workflow] {action} {full_id[:12]}: {status}")

    def _wf_show_progress(self, engine, wf_id_prefix):
        # Find by prefix
        for w in engine.list_workflows():
            if w["workflow_id"].startswith(wf_id_prefix):
                progress = engine.get_progress(w["workflow_id"])
                if progress:
                    print(f"\n{'='*50}")
                    print(f"[WORKFLOW] {progress['name']}")
                    print(f"{'='*50}")
                    print(f"  Status:    {progress['status']}")
                    print(f"  Progress:  {progress['progress_pct']:.0f}% ({progress['completed_steps']}/{progress['total_steps']})")
                    if progress['current_action']:
                        print(f"  Current:   {progress['current_action']}")
                    if progress['error']:
                        print(f"  Error:     {progress['error']}")
                    print(f"  Duration:  {progress['total_duration_ms']:.0f}ms")
                    print()
                return
        print(f"[Workflow] Not found: {wf_id_prefix}")

    # --- Environment commands (Faza 6) ---

    def _cmd_env(self, args):
        """Handle /env commands."""
        mgr = self.ctx.environment_manager
        if not mgr:
            print("[Environment] Not initialized")
            return

        sub = args[0].lower() if args else "status"

        if sub in ("status", ""):
            self._env_show_status(mgr)
        elif sub == "list":
            self._env_list_modes(mgr)
        elif sub == "switch" and len(args) >= 2:
            self._env_switch(mgr, args[1])
        elif sub == "auto":
            self._env_enable_auto(mgr)
        else:
            print("[Environment] Usage: /env [list|switch <mode>|auto]")

    def _env_show_status(self, mgr):
        status = mgr.get_status()
        import datetime
        switched = datetime.datetime.fromtimestamp(status['switched_at']).strftime('%H:%M')
        print(f"\n{'='*50}")
        print("[ENVIRONMENT] Status")
        print(f"{'='*50}")
        print(f"  Mode:          {status['mode']}")
        print(f"  Description:   {status['description']}")
        print(f"  Switched at:   {switched} (by: {status['switched_by']})")
        print(f"  Auto-detect:   {'ON' if status['auto_detect_enabled'] else 'OFF'}")
        print(f"  Notifications: {status['notification_level']}")
        print(f"  LLM budget:    {status['llm_budget_multiplier']:.1f}x")
        if status['priority_actions']:
            print(f"  Priority:      {', '.join(status['priority_actions'])}")
        if status['blocked_actions']:
            print(f"  Blocked:       {', '.join(status['blocked_actions'])}")
        print()

    def _env_list_modes(self, mgr):
        modes = mgr.list_modes()
        print(f"\n{'='*50}")
        print("[ENVIRONMENT] Available Modes")
        print(f"{'='*50}")
        for m in modes:
            marker = " <-- active" if m['active'] else ""
            print(f"  {m['mode']:<15} {m['description']}{marker}")
        print(f"\n  Switch: /env switch <mode>")
        print()

    def _env_switch(self, mgr, mode_str):
        try:
            from agent_core.environment.environment_model import EnvironmentMode
            mode = EnvironmentMode(mode_str.lower())
            ok = mgr.switch(mode, by="operator")
            if ok:
                print(f"[Environment] Switched to: {mode.value}")
            else:
                print(f"[Environment] Already in mode: {mode.value}")
        except ValueError:
            valid = [m.value for m in EnvironmentMode]
            print(f"[Environment] Unknown mode: {mode_str}")
            print(f"  Valid modes: {', '.join(valid)}")

    def _env_enable_auto(self, mgr):
        mgr._state.auto_detect_enabled = True
        mgr.switch(EnvironmentMode.DEFAULT, by="operator")
        print("[Environment] Auto-detection enabled, switched to DEFAULT")

    def cleanup(self):
        if self._running:
            self._running = False


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
