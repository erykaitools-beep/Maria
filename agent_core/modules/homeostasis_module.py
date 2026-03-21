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
                    from agent_core.autonomy import AutonomyPolicy
                    autonomy_policy = AutonomyPolicy()
                    planner.set_autonomy_policy(autonomy_policy)
                    ctx.autonomy_policy = autonomy_policy
                    print("[Homeostasis] [OK] AutonomyPolicy wired (K7)")
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
