"""
PlannerCore - ReAct loop engine connecting K1-K4.

Synchronous, called from tick loop Phase 10.
No LLM. Deterministic. Testable.

Kontrakt: docs/CONTRACTS.md - Kontrakt 5: Planner
ADR-013: Planner v1 rule-based (no LLM)
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.planner.planner_model import (
    Plan, PlanStatus, PlannerState, ActionType, create_plan,
)
from agent_core.planner.planner_guard import PlannerGuard
from agent_core.planner.goal_selector import GoalSelector
from agent_core.planner.action_executor import ActionExecutor
from agent_core.tracing.episode import (
    generate_episode_id, current_episode_id, clear_episode_id,
    set_current_trace,
)
from agent_core.tracing.trace_model import DecisionTrace

logger = logging.getLogger(__name__)

# Default paths
_META_DIR = Path(__file__).resolve().parents[2] / "meta_data"
_DEFAULT_STATE_PATH = _META_DIR / "planner_state.json"
_DEFAULT_DECISIONS_PATH = _META_DIR / "planner_decisions.jsonl"

# Frequency constants
ROUTINE_INTERVAL_TICKS = 60         # Normal cycle every 60 ticks (60s)
EVALUATION_INTERVAL_SEC = 3600      # Trigger K4 report every 1h
RECOMMENDATION_COOLDOWN_SEC = 900   # 15 min cooldown on eval recommendations
VALIDATION_INTERVAL_SEC = 21600     # 6h between cross-validations (Faza F)
CRITIQUE_INTERVAL_SEC = 28800       # 8h between knowledge critiques (Faza G)

# High-priority event types that trigger immediate cycle
HIGH_PRIORITY_EVENTS = {
    "exam_result", "alert", "user_command", "sandbox_promoted",
}

# Max in-memory plan history
MAX_HISTORY_SIZE = 100

# Auto-learning goal limits
MAX_AUTO_LEARNING_GOALS = 3
AUTO_GOAL_COOLDOWN_SEC = 3600  # 1 hour
MIN_RETENTION_FOR_NEW_TOPICS = 0.6


class PlannerCore:
    """
    Central planner coordinating K1-K4 into a decision loop.

    Called from tick loop. Each cycle:
    1. GUARD: Check if planning is allowed
    2. PERCEIVE: Read high-priority events from PerceptionBuffer
    3. SELECT: Choose best goal (GoalSelector)
    4. PLAN: Create single-step Plan
    5. EXECUTE: Delegate to ActionExecutor
    6. EMIT: Push PerceptionEvent for the decision
    7. LOG: Persist to planner_decisions.jsonl
    """

    def __init__(
        self,
        state_path: Optional[Path] = None,
        decisions_path: Optional[Path] = None,
    ):
        self.guard = PlannerGuard()
        self.selector = GoalSelector()
        self.executor = ActionExecutor()

        self._state_path = Path(state_path or _DEFAULT_STATE_PATH)
        self._decisions_path = Path(decisions_path or _DEFAULT_DECISIONS_PATH)

        self._state = PlannerState()
        self._last_plans: List[Plan] = []

        # External references (set via set_* methods)
        self._homeostasis_core = None
        self._perception_buffer = None
        self._goal_store = None
        self._evaluation_observer = None
        self._teacher_agent = None
        self._knowledge_analyzer = None
        self._sandbox_manager = None
        self._world_model = None
        self._autonomy_policy = None
        self._deliberation = None
        self._meta_cognition = None
        self._action_safety = None
        self._experiment_system = None
        self._self_analysis = None
        self._creative_module = None
        self._critic_agent = None
        self._bulletin_store = None
        self._knowledge_auditor = None
        self._trace_store = None
        self._approval_queue = None
        self._telegram_notifier = None
        self._current_trace: Optional[DecisionTrace] = None

        # Load persisted state
        self._load_state()

    # -- Setup: inject dependencies --------------------------

    def set_homeostasis_core(self, core) -> None:
        self._homeostasis_core = core
        self.executor.set_homeostasis_core(core)

    def set_perception_buffer(self, buffer) -> None:
        self._perception_buffer = buffer

    def set_goal_store(self, store) -> None:
        self._goal_store = store
        self.executor.set_goal_store(store)

    def set_evaluation_observer(self, observer) -> None:
        self._evaluation_observer = observer
        self.executor.set_evaluation_observer(observer)

    def set_teacher_agent(self, agent) -> None:
        self._teacher_agent = agent
        self.executor.set_teacher_agent(agent)

    def set_knowledge_analyzer(self, analyzer) -> None:
        self._knowledge_analyzer = analyzer
        self.executor.set_knowledge_analyzer(analyzer)

    def set_sandbox_manager(self, manager) -> None:
        self._sandbox_manager = manager

    def set_world_model(self, world_model) -> None:
        self._world_model = world_model
        self.executor.set_world_model(world_model)

    def set_autonomy_policy(self, policy) -> None:
        self._autonomy_policy = policy

    def set_deliberation(self, deliberation) -> None:
        self._deliberation = deliberation

    def set_meta_cognition(self, meta_cognition) -> None:
        self._meta_cognition = meta_cognition

    def set_action_safety(self, action_safety) -> None:
        self._action_safety = action_safety

    def set_experiment_system(self, experiment_system) -> None:
        self._experiment_system = experiment_system
        self.executor.set_experiment_system(experiment_system)

    def set_openclaw_client(self, client) -> None:
        """Set OpenClaw client for EFFECTOR actions (ADR-016)."""
        self.executor.set_openclaw_client(client)

    def set_self_analysis(self, sa) -> None:
        """Set K12 SelfAnalysis for cognitive loop."""
        self._self_analysis = sa
        self.executor.set_self_analysis(sa)

    def set_creative_module(self, creative) -> None:
        """Set K13 Creative module for strategic reflection."""
        self._creative_module = creative
        self.executor.set_creative_module(creative)

    def set_approval_queue(self, queue) -> None:
        """Set ApprovalQueue for effector HITL (Phase 5)."""
        self._approval_queue = queue

    def set_cross_validator(self, validator) -> None:
        """Set CrossValidator for multi-source learning (Faza F)."""
        self.executor.set_cross_validator(validator)

    def set_critic_agent(self, critic) -> None:
        """Set CriticAgent for knowledge quality gate (Faza G)."""
        self._critic_agent = critic

    def set_telegram_notifier(self, notifier) -> None:
        """Set TelegramNotifier for effector request notifications (Phase 5)."""
        self._telegram_notifier = notifier

    def set_trace_store(self, store) -> None:
        """Set TraceStore for decision traceability (Phase 1)."""
        self._trace_store = store

    def set_capability_router(self, router) -> None:
        """Set CapabilityRouter for registry-based dispatch."""
        self.executor.set_capability_router(router)

    def set_bulletin_store(self, store) -> None:
        """Set BulletinStore for cognitive needs tracking (Learning Upgrade)."""
        self._bulletin_store = store
        self.executor.set_bulletin_store(store)

    def set_knowledge_auditor(self, auditor) -> None:
        """Set KnowledgeAuditor for pre-learn audit (Phase 2)."""
        self._knowledge_auditor = auditor

    # -- Internal: pre-check autonomy policy ----------------

    def _is_action_rate_limited(self, action_type_value: str) -> bool:
        """
        Quick check if action would be blocked by K7 (rate limit or consecutive failures).

        Used to avoid creating plans we know will be blocked.
        """
        if not getattr(self, '_autonomy_policy', None):
            return False
        try:
            check = self._autonomy_policy.check(
                action_type=action_type_value,
                action_params={},
            )
            return not check.allowed
        except Exception:
            return False

    # -- Main entry point (called from tick loop) -----------

    def should_run(self, tick_count: int) -> bool:
        """
        Determine if planner should run this tick.

        Hybrid frequency:
        - Every ROUTINE_INTERVAL_TICKS (60 ticks)
        - Immediately on high-priority events in PerceptionBuffer
        """
        # Routine check
        ticks_since = tick_count - self._state.last_cycle_tick
        # Handle tick discontinuity after daemon restart (tick resets to 0)
        if ticks_since < 0 or ticks_since >= ROUTINE_INTERVAL_TICKS:
            return True

        # Event-driven check: high-priority events since last cycle
        if self._perception_buffer is not None:
            last_ts = self._state.last_cycle_tick  # Using tick as proxy
            for event_type in HIGH_PRIORITY_EVENTS:
                events = self._perception_buffer.get_by_event_type(event_type)
                for ev in events:
                    if ev.timestamp > self._last_cycle_ts():
                        return True

        return False

    def run_cycle(self, tick_count: int) -> Optional[Plan]:
        """
        Execute one planner cycle. The core ReAct loop.

        Args:
            tick_count: Current tick count from homeostasis

        Returns:
            Plan that was executed (or None if guard blocked)
        """
        self._state.total_cycles += 1
        self._state.last_cycle_tick = tick_count

        # -- EPISODE TRACE: start --
        episode_id = generate_episode_id()
        trace = DecisionTrace(
            episode_id=episode_id,
            started_at=time.time(),
            tick_count=tick_count,
        )
        if self._homeostasis_core:
            state = self._homeostasis_core.get_state()
            trace.mode = state.mode.value
            trace.health_score = state.health_score
        self._current_trace = trace
        set_current_trace(trace)

        # -- STEP 1: GUARD --
        can_plan, block_reasons = self._check_guard()
        if not can_plan:
            logger.debug(f"Planner cycle skipped: {block_reasons}")
            trace.add_step("planner", "guard_check", "blocked",
                           {"reasons": block_reasons})
            trace.finalize(success=False, result_summary="guard_blocked")
            self._save_trace(trace)
            self._emit_cycle_complete(tick_count, guard_blocked=True,
                                      block_reasons=block_reasons)
            self._log_skip(tick_count, "guard_blocked", block_reasons)
            self._save_state()
            clear_episode_id()
            return None

        # -- STEP 1.5: CHECK APPROVED EFFECTOR REQUESTS (Phase 5) --
        if self._approval_queue:
            self._approval_queue.expire_stale()
            approved = self._approval_queue.get_approved_ready()
            if approved:
                plan = self._execute_approved_effector(approved, trace)
                if plan is not None:
                    return plan

        # -- STEP 2: PERCEIVE --
        context = self._gather_context()

        # -- STEP 2.5: CREATIVE CHECK (independent of goal cycle) --
        # Creative runs on its own cooldown, not competing with learn/fetch
        plan = self._maybe_creative(context)
        if plan is not None:
            return self._finalize_plan(plan)

        # -- STEP 3: SELECT GOAL with pivot (try next if NOOP/blocked) --
        ranked_goals = self._select_ranked_goals(context)
        if not ranked_goals:
            # Try to auto-create a learning goal with topic selection
            created = self._auto_create_learning_goal(context)
            if created:
                ranked_goals = self._select_ranked_goals(context)

        goal = None  # track last attempted goal for NOOP fallback
        for candidate in ranked_goals:
            goal = candidate
            if trace:
                trace.goal_id = goal.id
                trace.goal_description = goal.description
                trace.goal_priority = getattr(goal, "priority", 0.0)
                trace.add_step("planner", "goal_selected", "ok", {
                    "goal_id": goal.id,
                    "goal_type": goal.type.value if hasattr(goal.type, "value") else str(goal.type),
                    "priority": getattr(goal, "priority", 0.0),
                })
            # -- STEP 4: CREATE PLAN for goal --
            plan = self._create_plan_for_goal(goal, context)
            if plan.action_type == ActionType.NOOP:
                # Goal mapped to NOOP (e.g. all files completed, FETCH rate-limited)
                # -> pivot: try next goal in ranking before falling through
                logger.info(
                    f"Planner: goal {goal.id} mapped to NOOP, "
                    f"trying next goal (pivot)"
                )
                if trace:
                    trace.add_step("planner", "goal_pivot", "noop", {
                        "skipped_goal": goal.id,
                        "reason": plan.action_params.get("reason", "noop"),
                    })
                continue
            result = self._finalize_plan(plan)
            # If K7 blocked (autonomy_policy), try next goal
            blocked_by_k7 = (
                result.status == PlanStatus.FAILED
                and isinstance(result.result, dict)
                and result.result.get("blocked_by") == "autonomy_policy"
            )
            if blocked_by_k7:
                logger.info(
                    f"Planner: goal {goal.id} blocked by K7, "
                    f"trying next goal (pivot)"
                )
                if trace:
                    trace.add_step("planner", "goal_pivot", "k7_blocked", {
                        "skipped_goal": goal.id,
                    })
                continue
            return result

        # -- STEP 5: EVALUATE as fallback (no actionable goals or goal plan blocked) --
        plan = self._maybe_evaluate(context)
        if plan is not None:
            return self._finalize_plan(plan)

        # Faza F: Cross-validate learned knowledge (after evaluate, before critique)
        plan = self._maybe_validate(context)
        if plan is not None:
            return self._finalize_plan(plan)

        # Faza G: Knowledge quality critique (after validate, before self-analysis)
        plan = self._maybe_critique(context)
        if plan is not None:
            return self._finalize_plan(plan)

        # K12: Self-analysis (after critique, before giving up)
        plan = self._maybe_self_analyze(context)
        if plan is not None:
            return self._finalize_plan(plan)

        # K13: Creative reflection (after self-analysis, before NOOP)
        plan = self._maybe_creative(context)
        if plan is not None:
            return self._finalize_plan(plan)

        # If goal existed but resulted in NOOP, execute it
        if goal is not None:
            noop_plan = create_plan(
                goal_id=goal.id if goal else None,
                goal_description=goal.description if goal else "",
                action_type=ActionType.NOOP,
                action_params={},
            )
            return self._finalize_plan(noop_plan)

        # Nothing to do
        logger.debug("Planner: no feasible goal and no evaluation needed")
        if trace:
            trace.add_step("planner", "no_goals", "idle")
            trace.finalize(success=True, result_summary="no_goals")
            self._save_trace(trace)
        self._emit_cycle_complete(tick_count, no_goals=True)
        self._log_skip(tick_count, "no_goals", [])
        self._save_state()
        clear_episode_id()
        return None

    # -- Internal: guard ------------------------------------

    def _check_guard(self):
        """Check guard conditions using current system state."""
        health = 1.0
        mode = "active"
        sandbox_active = False
        retention = None
        teacher_running = False

        if self._homeostasis_core:
            state = self._homeostasis_core.get_state()
            health = state.health_score
            mode = state.mode.value

        if self._sandbox_manager:
            sandbox_active = self._sandbox_manager.has_active_session()

        # Check if teacher thread is running
        if self._homeostasis_core and hasattr(self._homeostasis_core, '_teacher_thread'):
            thread = self._homeostasis_core._teacher_thread
            teacher_running = thread is not None and thread.is_alive()

        # Get retention from last evaluation
        if self._evaluation_observer:
            try:
                reports = self._evaluation_observer.get_recent_reports(limit=1)
                if reports:
                    retention = reports[0].metrics.get("retention_rate")
            except Exception:
                pass

        return self.guard.can_plan(
            health_score=health,
            mode=mode,
            sandbox_active=sandbox_active,
            retention_rate=retention,
            is_teacher_running=teacher_running,
        )

    # -- Internal: perception context -----------------------

    def _gather_context(self) -> Dict[str, Any]:
        """Gather context from K1-K4 for decision making."""
        context = {
            "high_priority_events": [],
            "evaluation_metrics": {},
            "knowledge_snapshot": None,
            "recommendations": [],
        }

        # K1: Recent high-priority events
        if self._perception_buffer:
            context["high_priority_events"] = (
                self._perception_buffer.get_by_priority(min_priority=0.7)
            )

        # K4: Latest evaluation metrics
        if self._evaluation_observer:
            try:
                reports = self._evaluation_observer.get_recent_reports(limit=1)
                if reports:
                    context["evaluation_metrics"] = reports[0].metrics
                    context["recommendations"] = reports[0].recommendations
            except Exception:
                pass

        # Knowledge state (from analyzer, not LLM)
        if self._knowledge_analyzer:
            try:
                context["knowledge_snapshot"] = (
                    self._knowledge_analyzer.get_knowledge_snapshot()
                )
            except Exception:
                pass

        # K6: World Model beliefs and knowledge gaps
        if self._world_model:
            try:
                context["world_summary"] = (
                    self._world_model.query.get_world_summary()
                )
                context["knowledge_gaps"] = (
                    self._world_model.query.get_knowledge_gaps()[:5]
                )
            except Exception:
                pass

        # K9: Meta-cognition confidence and patterns
        if self._meta_cognition:
            try:
                context["meta_confidence"] = (
                    self._meta_cognition.get_status()
                )
            except Exception:
                pass

        return context

    # -- Internal: periodic evaluation ----------------------

    def _maybe_evaluate(self, context: Dict) -> Optional[Plan]:
        """
        Check if it's time for a periodic evaluation report.

        Evaluation interval scales with idle time:
        - Normal: every 1h (EVALUATION_INTERVAL_SEC)
        - Idle (no learning in last eval): every 6h
        """
        now = time.time()
        since_eval = now - self._state.last_evaluation_ts

        # Adaptive interval: if last eval showed no learning, slow down
        interval = EVALUATION_INTERVAL_SEC
        recs = context.get("recommendations", [])
        for rec in recs:
            if "No learning activity" in rec:
                interval = EVALUATION_INTERVAL_SEC * 6  # 6h when idle
                break

        if since_eval >= interval:
            self._state.last_evaluation_ts = now
            return create_plan(
                goal_id=None,
                goal_description="Periodic evaluation report",
                action_type=ActionType.EVALUATE,
                action_params={"period_hours": since_eval / 3600.0},
            )
        return None

    # K12: Self-analysis trigger
    SELF_ANALYSIS_INTERVAL_SEC = 14400  # 4h between self-analyses

    def _maybe_self_analyze(self, context: Dict) -> Optional[Plan]:
        """
        Check if K12 self-analysis should trigger.

        Triggers when:
        - Cooldown expired (24h)
        - K9 signals needs_human()
        - Retention rate dropped below 0.3 in two consecutive reports
        """
        if self._self_analysis is None:
            return None

        now = time.time()
        since_analysis = now - self._state.last_self_analysis_ts

        # Absolute minimum cooldown: 10 min (prevents rapid re-trigger)
        if since_analysis < 600:
            return None

        trigger = False
        trigger_reason = ""

        # Periodic trigger
        if since_analysis >= self.SELF_ANALYSIS_INTERVAL_SEC:
            trigger = True
            trigger_reason = "periodic"

        # K9 needs_human trigger
        if not trigger and self._meta_cognition and hasattr(self._meta_cognition, "needs_human"):
            try:
                if self._meta_cognition.needs_human():
                    trigger = True
                    trigger_reason = "k9_needs_human"
            except Exception:
                pass

        # Low retention trigger
        if not trigger:
            retention = context.get("retention_rate")
            if retention is not None and retention < 0.3:
                trigger = True
                trigger_reason = "low_retention"

        if trigger:
            self._state.last_self_analysis_ts = now
            logger.info(f"[K12] Self-analysis triggered: {trigger_reason}")
            return create_plan(
                goal_id=None,
                goal_description=f"K12 Self-analysis ({trigger_reason})",
                action_type=ActionType.SELF_ANALYZE,
                action_params={"trigger": trigger_reason, "period_days": 7},
            )

        return None

    # K13: Creative reflection trigger
    CREATIVE_INTERVAL_SEC = 7200  # 2h between creative reflections

    def _maybe_creative(self, context: Dict) -> Optional[Plan]:
        """
        Check if K13 Creative reflection should trigger.

        Triggers when:
        - Creative module is available
        - Cooldown expired (2h)
        - Not rate-limited by K7
        """
        if self._creative_module is None:
            return None

        # Check K7 rate limit
        if self._is_action_rate_limited("creative"):
            return None

        # Check if creative module itself says it's ready
        if not self._creative_module.should_reflect():
            return None

        logger.info("[K13] Creative reflection triggered")
        return create_plan(
            goal_id=None,
            goal_description="K13 Creative reflection",
            action_type=ActionType.CREATIVE,
            action_params={"trigger": "planner_idle"},
        )

    # Faza F: Cross-validation trigger

    def _maybe_validate(self, context: Dict) -> Optional[Plan]:
        """
        Check if cross-validation should trigger (Faza F).

        Triggers when:
        - CrossValidator is configured (NIM available)
        - Cooldown expired (6h)
        - Completed files exist for validation
        - Not rate-limited by K7
        """
        if not self.executor._cross_validator:
            return None

        # Check K7 rate limit
        if self._is_action_rate_limited("validate"):
            return None

        now = time.time()
        since_validation = now - self._state.last_validation_ts

        if since_validation < VALIDATION_INTERVAL_SEC:
            return None

        # Check if there are completed files to validate
        file_id = self.executor._pick_validation_candidate()
        if not file_id:
            return None

        self._state.last_validation_ts = now
        logger.info(f"[Faza F] Cross-validation triggered for {file_id}")
        return create_plan(
            goal_id=None,
            goal_description=f"Cross-validate: {file_id}",
            action_type=ActionType.VALIDATE,
            action_params={"file_id": file_id},
        )

    # Faza G: Knowledge critique trigger

    def _maybe_critique(self, context: Dict) -> Optional[Plan]:
        """
        Check if knowledge critique should trigger (Faza G).

        Triggers when:
        - CriticAgent is configured
        - Cooldown expired (8h)
        - Or post_validation / post_maintenance event
        - Not rate-limited by K7
        """
        if not hasattr(self, '_critic_agent') or self._critic_agent is None:
            return None

        # Check K7 rate limit
        if self._is_action_rate_limited("critique"):
            return None

        now = time.time()
        since_critique = now - self._state.last_critique_ts

        # Minimum 1h between critiques
        if since_critique < 3600:
            return None

        trigger = None
        if since_critique >= CRITIQUE_INTERVAL_SEC:
            trigger = "periodic"
        # Post-validation trigger (use fresh dispute data)
        elif context.get("last_action_type") == "validate":
            trigger = "post_validation"
        # Post-maintenance trigger (beliefs just maintained)
        elif context.get("last_action_type") == "evaluate":
            trigger = "post_maintenance"

        if trigger is None:
            return None

        self._state.last_critique_ts = now
        logger.info("[Faza G] Knowledge critique triggered: %s", trigger)
        return create_plan(
            goal_id=None,
            goal_description=f"Knowledge critique ({trigger})",
            action_type=ActionType.CRITIQUE,
            action_params={"trigger": trigger},
        )

    # -- Internal: goal selection ---------------------------

    def _select_goal(self, context: Dict):
        """Select best goal using GoalSelector."""
        if self._goal_store is None:
            return None

        active_goals = self._goal_store.get_active()
        return self.selector.select_goal(
            active_goals=active_goals,
            evaluation_metrics=context.get("evaluation_metrics", {}),
            knowledge_snapshot=context.get("knowledge_snapshot"),
            world_summary=context.get("world_summary"),
        )

    def _select_ranked_goals(self, context: Dict) -> list:
        """Return all feasible goals ranked by effective priority (descending)."""
        if self._goal_store is None:
            return []

        active_goals = self._goal_store.get_active()
        if not active_goals:
            return []

        metrics = context.get("evaluation_metrics", {})
        snapshot = context.get("knowledge_snapshot")

        # Use GoalSelector to filter feasible + rank
        scored = []
        for goal in active_goals:
            score = self.selector._compute_effective_priority(goal, time.time())
            feasible, _ = self.selector._check_feasibility(goal, metrics, snapshot)
            if feasible:
                scored.append((score, goal))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [g for _, g in scored]

    # -- Internal: plan creation ----------------------------

    def _create_plan_for_goal(self, goal, context: Dict) -> Plan:
        """Map a goal to a concrete single-step plan."""
        goal_type = goal.type.value
        snapshot = context.get("knowledge_snapshot")
        metrics = context.get("evaluation_metrics", {})

        # MAINTENANCE goals -> maintenance action
        if goal_type == "maintenance":
            return create_plan(
                goal_id=goal.id,
                goal_description=goal.description,
                action_type=ActionType.MAINTENANCE,
                action_params={"metric": goal.metadata.get("metric", "")},
            )

        # K8: Consult Deliberation for multi-step strategy
        if self._deliberation:
            delib_action = self._consult_deliberation(goal, context)
            if delib_action is not None:
                action_type_str = delib_action["action_type"]

                # Pre-check: skip exam if nothing to examine
                if action_type_str == "exam":
                    has_exam_candidates = bool(
                        snapshot and snapshot.get("files_by_status", {}).get("learned")
                    )
                    if not has_exam_candidates:
                        strategy_id = delib_action.get("strategy_id")
                        if strategy_id:
                            self._deliberation.abandon_strategy(
                                strategy_id, reason="no files to examine",
                            )
                        return create_plan(
                            goal_id=goal.id,
                            goal_description=goal.description,
                            action_type=ActionType.NOOP,
                            action_params={"reason": "no exam candidates"},
                        )

                # Pre-check: skip blocked actions from deliberation
                if self._is_action_rate_limited(action_type_str):
                    logger.debug(
                        f"Planner: deliberation suggested {action_type_str} "
                        f"but it's blocked by K7, abandoning strategy -> NOOP"
                    )
                    # Abandon strategy and return NOOP to break the loop
                    strategy_id = delib_action.get("strategy_id")
                    if strategy_id:
                        self._deliberation.abandon_strategy(
                            strategy_id,
                            reason=f"K7 blocks {action_type_str}",
                        )
                    return create_plan(
                        goal_id=goal.id,
                        goal_description=goal.description,
                        action_type=ActionType.NOOP,
                        action_params={"reason": f"K7 blocks {action_type_str}"},
                    )
                else:
                    try:
                        action = ActionType(action_type_str)
                    except ValueError:
                        action = ActionType.NOOP

                    action_params = delib_action.get("action_params", {})
                    # Merge topic filters from goal metadata
                    topics = goal.metadata.get("topics")
                    if topics and "topics" not in action_params:
                        action_params["topics"] = topics

                    return create_plan(
                        goal_id=goal.id,
                        goal_description=delib_action.get(
                            "step_description", goal.description
                        ),
                        action_type=action,
                        action_params=action_params,
                        metadata={
                            "strategy_id": delib_action.get("strategy_id"),
                            "step_order": delib_action.get("step_order"),
                            "strategy_intent": delib_action.get("strategy_intent", ""),
                        },
                    )

        # Fallback: LEARNING goals or META goal -> decide learn/exam/review
        action = self._decide_learning_action(snapshot, metrics)

        # Pass topic filters from goal metadata to action_params
        action_params = {}
        topics = goal.metadata.get("topics")
        if topics:
            action_params["topics"] = topics

            # Conversation-driven: if no files match topic, fetch first
            if action == ActionType.NOOP and goal.metadata.get("source") == "conversation":
                if not self._is_action_rate_limited("fetch"):
                    action = ActionType.FETCH
                    logger.info(
                        f"[Planner] Conversation goal '{topics[0]}': "
                        f"no matching files, switching to FETCH"
                    )

        # ASK_EXPERT: add topic and source
        if action == ActionType.ASK_EXPERT:
            topic = self._pick_expert_topic()
            if topic:
                action_params["topic"] = topic
                action_params["source"] = "planner"

        return create_plan(
            goal_id=goal.id,
            goal_description=goal.description,
            action_type=action,
            action_params=action_params,
        )

    def _consult_deliberation(self, goal, context: Dict) -> Optional[Dict]:
        """
        Ask K8 Deliberation for next action from a multi-step strategy.

        Returns action dict or None (fallback to _decide_learning_action).
        """
        snapshot = context.get("knowledge_snapshot")
        delib_context = {
            "intent": goal.description,
            "topic": (goal.metadata.get("topics") or [""])[0] if goal.metadata.get("topics") else "",
            "goal_type": goal.type.value,
            "new_files_available": bool(
                snapshot and snapshot.get("new_files_available")
            ),
            "weak_topics": [],
            "knowledge_snapshot": snapshot,
        }

        # Detect weak topics from world model
        if self._world_model:
            try:
                gaps = self._world_model.query.get_knowledge_gaps()
                delib_context["weak_topics"] = [g.get("topic", "") for g in gaps[:5]]
                delib_context["_knowledge_gaps"] = gaps[:5]
            except Exception:
                pass

        return self._deliberation.get_next_action(goal.id, delib_context)

    def _decide_learning_action(
        self, snapshot: Optional[Dict], metrics: Dict
    ) -> ActionType:
        """
        Decide which learning action to take based on knowledge state.

        Priority logic:
        - P1: Files in "learning" status -> LEARN (continue partial)
        - P2: Files in "learned" status (ready for exam) -> EXAM
        - P3: New/unindexed files available -> LEARN (start new)
        - P4: Low retention -> REVIEW (spaced repetition)
        - P5: No materials left -> FETCH (get new content from web)
        - P6: Nothing to do -> NOOP
        """
        if snapshot is None:
            return ActionType.LEARN  # Default to learning

        by_status = snapshot.get("files_by_status", {})

        # P1: Continue partial
        if by_status.get("learning"):
            return ActionType.LEARN

        # P2: Exam ready (only if not blocked by K7)
        if by_status.get("learned"):
            if not self._is_action_rate_limited("exam"):
                return ActionType.EXAM
            # Exam blocked by K7 -> force review to break deadlock
            return ActionType.REVIEW

        # P3: New files (indexed "new" status OR unindexed files in input/)
        if snapshot.get("new_files_available"):
            return ActionType.LEARN

        # P4: Review (check retention)
        retention = metrics.get("retention_rate", 1.0)
        if retention < 0.8:
            return ActionType.REVIEW

        # P5: All learned, fetch new content (if not rate-limited)
        if by_status.get("completed"):
            if not self._is_action_rate_limited("fetch"):
                return ActionType.FETCH

        # P6: Ask expert for new knowledge (when fetch exhausted)
        if not self._is_action_rate_limited("ask_expert"):
            # Build question from knowledge gaps
            topic = self._pick_expert_topic()
            if topic:
                return ActionType.ASK_EXPERT

        # P7: Post NEED_MATERIAL to bulletin board (instead of silent NOOP)
        self._post_need_material_if_missing()

        return ActionType.NOOP

    def _pick_expert_topic(self) -> Optional[str]:
        """Pick a topic to ask the expert about, based on knowledge gaps."""
        # K6: Use world model gaps
        if self._world_model:
            try:
                gaps = self._world_model.query.get_knowledge_gaps()
                if gaps:
                    return gaps[0].get("topic", "")
            except Exception:
                pass

        # Fallback: use topic suggester from web_source
        if self._knowledge_analyzer:
            try:
                topic_map = self._knowledge_analyzer.get_topic_file_map()
                if topic_map:
                    # Pick first topic (most files = most explored)
                    return next(iter(topic_map))
            except Exception:
                pass

        return None

    def _post_need_material_if_missing(self) -> None:
        """Audit topic knowledge and post appropriate need to bulletin board."""
        if not getattr(self, "_bulletin_store", None):
            return
        topic = self._get_current_goal_topic()
        if not topic:
            return
        goal_id = self._get_current_goal_id()

        try:
            from agent_core.bulletin.bulletin_model import EntryType

            # Phase 2: use auditor if available, otherwise simple NEED_MATERIAL
            auditor = getattr(self, "_knowledge_auditor", None)
            if auditor:
                report = auditor.audit_topic(topic)
                if not report.has_gaps:
                    return  # Topic well-covered, no need to post

                # Map audit gaps to bulletin entry types
                for action in report.suggested_actions:
                    entry_type_map = {
                        "need_material": EntryType.NEED_MATERIAL,
                        "need_test": EntryType.NEED_TEST,
                        "need_review": EntryType.NEED_REVIEW,
                    }
                    etype = entry_type_map.get(action, EntryType.NEED_MATERIAL)

                    # Use worst gap severity as priority
                    gap_desc = "; ".join(
                        g.description for g in report.gaps[:3]
                    )
                    self._bulletin_store.create_and_post(
                        entry_type=etype,
                        topic=topic,
                        reason_code=action,
                        summary=gap_desc or f"Audit: {action} for {topic}",
                        requested_by="auditor",
                        goal_id=goal_id,
                        priority=min(report.worst_gap_severity, 0.9),
                        metadata={"audit": report.to_dict()},
                    )
            else:
                # Fallback: simple NEED_MATERIAL without audit
                self._bulletin_store.create_and_post(
                    entry_type=EntryType.NEED_MATERIAL,
                    topic=topic,
                    reason_code="all_sources_exhausted",
                    summary=f"Wszystkie zrodla wyczerpane dla tematu: {topic}",
                    requested_by="planner",
                    goal_id=goal_id,
                    priority=0.7,
                )
        except Exception as e:
            logger.debug(f"[BULLETIN] Failed to post need: {e}")

    def _get_current_goal_topic(self) -> Optional[str]:
        """Extract topic from the goal currently being planned."""
        trace = self._current_trace
        if trace and trace.goal_description:
            # Strip "Nauka: " prefix if present
            desc = trace.goal_description
            if desc.lower().startswith("nauka:"):
                return desc[6:].strip()
            return desc
        return None

    def _get_current_goal_id(self) -> Optional[str]:
        """Get ID of the goal currently being planned."""
        trace = self._current_trace
        if trace and trace.goal_id:
            return trace.goal_id
        return None

    # -- Internal: finalize and persist ---------------------

    def _finalize_plan(self, plan: Plan) -> Plan:
        """Execute plan, emit event, log, save state."""
        trace = self._current_trace
        episode_id = current_episode_id()

        # Stamp plan with episode_id
        plan.trace_id = episode_id

        # Fill trace with plan info
        if trace:
            trace.plan_id = plan.plan_id
            trace.action_type = plan.action_type.value
            trace.action_params = plan.action_params
            trace.goal_id = plan.goal_id
            trace.goal_description = plan.goal_description

        # Phase 3: Degradation check - block heavy LLM actions in REDUCED mode
        _heavy_actions = {
            ActionType.LEARN, ActionType.EXAM, ActionType.REVIEW,
            ActionType.FETCH, ActionType.CREATIVE, ActionType.ASK_EXPERT,
            ActionType.VALIDATE,
        }
        if plan.action_type in _heavy_actions and self._homeostasis_core:
            _state = self._homeostasis_core.get_state()
            _allowed, _reason = self.guard.is_heavy_action_allowed(
                _state.mode.value, _state.health_score
            )
            if not _allowed:
                if trace:
                    trace.add_step("planner", "degradation_check", "blocked", {
                        "reason": _reason, "action": plan.action_type.value,
                    })
                plan.status = PlanStatus.SKIPPED
                plan.result = {"success": False, "blocked_by": "degradation", "reason": _reason}
                plan.message = f"Degradation: {_reason}"
                self._emit_cycle_complete(self._state.last_cycle_tick, plan=plan)
                self._log_decision(plan)
                if trace:
                    trace.finalize(success=False, result_summary=f"degradation: {_reason}")
                    self._save_trace(trace)
                self._save_state()
                clear_episode_id()
                return plan

        # K7: Autonomy Policy check before execution
        if self._autonomy_policy:
            health = 1.0
            mode = "active"
            if self._homeostasis_core:
                state = self._homeostasis_core.get_state()
                health = state.health_score
                mode = state.mode.value

            check = self._autonomy_policy.check(
                action_type=plan.action_type.value,
                action_params=plan.action_params,
                goal_id=plan.goal_id,
                health_score=health,
                mode=mode,
            )
            if not check.allowed:
                k7_decision = check.blocked_result.get("decision", "block") if check.blocked_result else "block"
                k7_reasons = check.blocked_result.get("reasons", []) if check.blocked_result else []
                k7_rule = check.rule_name or ""

                if trace:
                    trace.k7_decision = k7_decision
                    trace.k7_reasons = k7_reasons
                    trace.add_step("k7_policy", "check", "blocked", {
                        "decision": k7_decision,
                        "reasons": k7_reasons,
                        "rule": k7_rule,
                    })

                # Phase 5: Handle effector ESCALATE with authority-aware flow
                if (plan.action_type == ActionType.EFFECTOR
                        and k7_decision == "escalate"
                        and k7_rule == "effector_authority"):
                    return self._handle_effector_escalation(
                        plan, check, trace,
                    )

                plan.status = PlanStatus.FAILED
                plan.result = check.blocked_result or {
                    "success": False, "blocked_by": "autonomy_policy"
                }
                plan.message = self._format_message(plan)
                self._state.total_plans_executed += 1

                # Abandon K8 strategy entirely when K7 blocks
                # (prevents retry loops where strategy keeps suggesting blocked actions)
                if self._deliberation and plan.metadata.get("strategy_id"):
                    self._deliberation.abandon_strategy(
                        plan.metadata["strategy_id"],
                        reason=f"K7 blocked {plan.action_type.value}",
                    )

                if trace:
                    trace.finalize(success=False, result_summary=f"K7 blocked: {k7_decision}")
                    self._save_trace(trace)

                self._emit_cycle_complete(
                    self._state.last_cycle_tick, plan=plan,
                )
                self._log_decision(plan)
                self._save_state()
                return plan
            else:
                if trace:
                    trace.k7_decision = "allow"
                    trace.add_step("k7_policy", "check", "allowed")

        # K9: Record assumptions BEFORE execution
        if self._meta_cognition:
            try:
                # Extract topic from multiple sources (action_params, goal, strategy)
                topic = ""
                topics = plan.action_params.get("topics", [])
                if topics:
                    topic = topics[0]
                # Fallback: goal metadata may have topics
                if not topic and plan.goal_id and self._goal_store:
                    goal = self._goal_store.get(plan.goal_id)
                    if goal and goal.metadata.get("topics"):
                        topic = goal.metadata["topics"][0]
                # Fallback: strategy intent may describe topic
                if not topic and plan.metadata.get("strategy_intent"):
                    intent = plan.metadata["strategy_intent"]
                    # Extract topic from "Nauka tematu: X" or "Konsolidacja wiedzy: X"
                    for prefix in ("Nauka tematu: ", "Konsolidacja wiedzy: ",
                                   "Eksploracja materialow o: "):
                        if intent.startswith(prefix):
                            topic = intent[len(prefix):]
                            break

                mc_context = {
                    "action_params": plan.action_params,
                    "topic": topic,
                    **plan.metadata,
                }
                if self._homeostasis_core:
                    state = self._homeostasis_core.get_state()
                    mc_context["retention_rate"] = getattr(
                        state, "retention_rate", None
                    )
                self._meta_cognition.record_decision(
                    plan_id=plan.plan_id,
                    action_type=plan.action_type.value,
                    goal_id=plan.goal_id,
                    topic=topic,
                    context=mc_context,
                    step_id=plan.metadata.get("step_id"),
                )
            except Exception:
                pass

        # K10: Capture before-state and classify action
        safety_mode = None
        if self._action_safety:
            try:
                safety_mode = self._action_safety.before_action(
                    plan_id=plan.plan_id,
                    action_type=plan.action_type.value,
                    action_params=plan.action_params,
                    goal_id=plan.goal_id,
                    metadata=plan.metadata,
                )
                if trace:
                    sm_str = safety_mode.value if hasattr(safety_mode, 'value') else str(safety_mode or "")
                    trace.k10_safety_mode = sm_str
                    trace.add_step("k10_safety", "before_action", "captured", {
                        "safety_mode": sm_str,
                    })
            except Exception:
                pass

        if trace:
            trace.add_step("planner", "execute_start", "ok", {
                "action_type": plan.action_type.value,
            })

        plan.status = PlanStatus.EXECUTING
        start = time.time()

        result = self.executor.execute(plan)

        plan.result = result
        plan.duration_ms = (time.time() - start) * 1000
        plan.status = (
            PlanStatus.COMPLETED if result.get("success") else PlanStatus.FAILED
        )

        # K10: Capture after-state and validate effects
        if self._action_safety:
            try:
                validation = self._action_safety.after_action(
                    plan_id=plan.plan_id,
                    success=result.get("success", False),
                    result=result,
                    duration_ms=plan.duration_ms,
                )
                if trace:
                    val_str = validation.get("validation", "skipped") if isinstance(validation, dict) else str(validation or "skipped")
                    trace.k10_validation = val_str
                    trace.add_step("k10_safety", "after_action", val_str)
            except Exception:
                pass

        # K7: Record outcome for consecutive failure tracking + rate limiting
        if self._autonomy_policy:
            self._autonomy_policy.record_execution(
                plan.action_type.value, result.get("success", False)
            )
            # Successful review should reset exam failure counter
            # (review prepares for re-examination, breaks K7 deadlock)
            if (plan.action_type == ActionType.REVIEW
                    and result.get("success", False)):
                self._autonomy_policy.record_execution("exam", True)

        # K8: Report step outcome back to deliberation
        if self._deliberation and plan.metadata.get("strategy_id"):
            outcome = "pass" if result.get("success") else "fail"
            self._deliberation.report_step_outcome(
                plan.metadata["strategy_id"], outcome, result
            )

        # K9: Reflect on outcome AFTER execution
        if self._meta_cognition:
            try:
                self._meta_cognition.reflect(
                    plan_id=plan.plan_id,
                    success=result.get("success", False),
                    result=result,
                )
            except Exception:
                pass

        # Reset idle streak so Maria doesn't stay in SLEEP forever
        # after autonomous learning/exam/evaluation actions
        if plan.action_type != ActionType.NOOP and self._homeostasis_core:
            try:
                self._homeostasis_core.record_activity()
            except Exception:
                pass

        # K6: Update beliefs after exam results
        if (plan.action_type == ActionType.EXAM
                and result.get("success")
                and self._world_model):
            try:
                self._world_model.process_exam_result(result)
                self._world_model.save()
            except Exception:
                pass

        # K6: Rebuild beliefs after LEARN (new knowledge -> new beliefs)
        # and after EVALUATE (~1/hour periodic rebuild)
        if (plan.action_type in (ActionType.EVALUATE, ActionType.LEARN)
                and result.get("success")
                and self._world_model):
            try:
                self._world_model.build_all()
                self._world_model.save()
            except Exception:
                pass

        # Belief Store v2: maintenance after EVALUATE (~1/hour)
        # Runs: decay -> dedup -> prune -> compact
        if (plan.action_type == ActionType.EVALUATE
                and result.get("success")
                and self._world_model):
            try:
                self._world_model.maintain()
            except Exception:
                pass

        # Generate human-readable message and attach to plan
        plan.message = self._format_message(plan)

        self._state.total_plans_executed += 1
        self._state.current_plan_id = plan.plan_id

        # Emit perception events
        self._emit_decision_event(plan)
        self._emit_cycle_complete(
            self._state.last_cycle_tick, plan=plan,
        )

        # Finalize and persist trace
        if trace:
            trace.success = result.get("success", False)
            trace.result_summary = plan.message or plan.action_type.value
            trace.finalize(
                success=result.get("success", False),
                result_summary=plan.message or plan.action_type.value,
            )
            self._save_trace(trace)

        # Persist (with message)
        self._log_decision(plan)
        self._save_state()

        # Keep bounded in-memory history
        self._last_plans.append(plan)
        if len(self._last_plans) > MAX_HISTORY_SIZE:
            self._last_plans = self._last_plans[-50:]

        clear_episode_id()
        return plan

    # -- Internal: auto-create learning goals -----------------

    def _auto_create_learning_goal(self, context: Dict) -> bool:
        """
        Auto-create a LEARNING goal with topic when none exist.

        Safety checks:
        - No existing active LEARNING goals
        - System in ACTIVE mode
        - No active sandbox session
        - retention_rate >= MIN_RETENTION_FOR_NEW_TOPICS
        - Cooldown since last auto-goal creation
        - New files available to learn

        Returns True if a goal was created.
        """
        if self._goal_store is None or self._knowledge_analyzer is None:
            return False

        # Check for existing LEARNING goals
        active_goals = self._goal_store.get_active()
        learning_goals = [
            g for g in active_goals
            if g.type.value == "learning"
        ]
        if len(learning_goals) >= MAX_AUTO_LEARNING_GOALS:
            return False

        # Check cooldown - look at latest auto-created goal
        now = time.time()
        for g in learning_goals:
            if g.metadata.get("source") == "auto":
                if (now - g.created_at) < AUTO_GOAL_COOLDOWN_SEC:
                    return False

        # Safety: check mode is ACTIVE
        if self._homeostasis_core:
            state = self._homeostasis_core.get_state()
            if state.mode.value != "active":
                return False

        # Safety: no active sandbox
        if self._sandbox_manager and self._sandbox_manager.has_active_session():
            return False

        # Safety: retention OK (don't start new topics when review needed)
        metrics = context.get("evaluation_metrics", {})
        retention = metrics.get("retention_rate")
        if retention is not None and retention < MIN_RETENTION_FOR_NEW_TOPICS:
            return False

        # Check there are new files to learn
        snapshot = context.get("knowledge_snapshot")
        if not snapshot:
            return False
        new_files = snapshot.get("new_files_available", [])
        in_progress = snapshot.get("learning_in_progress", [])
        if not new_files and not in_progress:
            return False

        # Find best topic - topic with most unfinished files
        topic_map = self._knowledge_analyzer.get_topic_file_map()
        if not topic_map:
            # No topics available (no learned content yet) - skip topic selection
            return False

        # Get file statuses from snapshot
        completed_files = set()
        by_status = snapshot.get("files_by_status", {})
        for rec in by_status.get("completed", []):
            completed_files.add(rec.get("id", rec.get("file", "")))

        # Count unfinished files per topic
        topic_scores = {}
        for topic, files in topic_map.items():
            unfinished = [f for f in files if f not in completed_files]
            if unfinished:
                topic_scores[topic] = len(unfinished)

        if not topic_scores:
            return False

        # K6: Prefer topic with lowest confidence in World Model
        best_topic = None
        if self._world_model:
            try:
                conf_map = self._world_model.query.get_topic_confidence_map()
                # Filter to topics that have unfinished files
                candidates = {
                    t: conf_map.get(t, 0.0)
                    for t in topic_scores
                }
                if candidates:
                    best_topic = min(candidates, key=candidates.get)
            except Exception:
                pass

        # Fallback: pick topic with most unfinished files
        if best_topic is None:
            best_topic = max(topic_scores, key=topic_scores.get)

        # Don't duplicate existing LEARNING goals with same topic
        for g in learning_goals:
            existing_topics = g.metadata.get("topics", [])
            if best_topic in existing_topics:
                return False

        # Create the goal
        from agent_core.goals.goal_model import (
            GoalType, GoalStatus, create_goal,
        )

        goal = create_goal(
            goal_type=GoalType.LEARNING,
            description=f"Nauka tematu: {best_topic}",
            priority=0.8,
            status=GoalStatus.ACTIVE,
            created_by="planner",
            metadata={
                "topics": [best_topic],
                "source": "auto",
                "unfinished_files": topic_scores[best_topic],
            },
        )
        self._goal_store.create(goal)
        self._goal_store.save()

        logger.info(
            f"[Planner] Auto-created LEARNING goal: {best_topic} "
            f"({topic_scores[best_topic]} unfinished files)"
        )
        return True

    # -- Internal: human-readable messages -------------------

    # -- Phase 5: Effector approval flow --

    def _handle_effector_escalation(self, plan, check, trace):
        """
        Handle K7 ESCALATE for effector actions based on authority level.

        - SUGGEST: notify operator, mark FAILED (no queue)
        - CONFIRM/BOUNDED+dangerous: submit to approval queue, mark AWAITING_APPROVAL
        """
        from agent_core.tracing.episode import current_episode_id, clear_episode_id

        authority_level = ""
        reasons = check.blocked_result.get("reasons", []) if check.blocked_result else []
        for r in reasons:
            if "authority_level=" in r:
                # Extract level from reason string
                for part in r.split(","):
                    if "authority_level=" in part:
                        authority_level = part.split("=")[1].strip().split(":")[0]
                        break
                break

        tool_name = plan.action_params.get("tool_name", "")
        tool_args = plan.action_params.get("tool_args", {})
        episode_id = current_episode_id() or ""

        if authority_level == "suggest":
            # Notify operator but don't queue
            if self._telegram_notifier:
                try:
                    self._telegram_notifier.notify_effector_request(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        goal_description=plan.goal_description,
                        authority_level=authority_level,
                    )
                except Exception:
                    pass

            plan.status = PlanStatus.FAILED
            plan.result = {
                "success": False,
                "blocked_by": "authority_suggest",
                "tool_name": tool_name,
                "notification_sent": True,
            }
            plan.message = f"Sugestia: {tool_name} (operator powiadomiony)"

        elif authority_level in ("confirm", "bounded"):
            # Submit to approval queue
            if self._approval_queue:
                request = self._approval_queue.submit(
                    plan_id=plan.plan_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    goal_id=plan.goal_id,
                    goal_description=plan.goal_description,
                    authority_level=authority_level,
                    episode_id=episode_id,
                    action_params=plan.action_params,
                )

                # Notify operator
                if self._telegram_notifier:
                    try:
                        self._telegram_notifier.notify_effector_request(
                            tool_name=tool_name,
                            tool_args=tool_args,
                            goal_description=plan.goal_description,
                            authority_level=authority_level,
                            request_id=request.request_id,
                        )
                    except Exception:
                        pass

                plan.status = PlanStatus.AWAITING_APPROVAL
                plan.result = {
                    "success": False,
                    "awaiting_approval": True,
                    "request_id": request.request_id,
                    "tool_name": tool_name,
                }
                plan.message = f"Czekam na zatwierdzenie: {tool_name} ({request.request_id[:12]})"
            else:
                # No queue configured - fall back to FAILED
                plan.status = PlanStatus.FAILED
                plan.result = {"success": False, "blocked_by": "no_approval_queue"}
                plan.message = f"Brak kolejki zatwierdzen dla {tool_name}"
        else:
            # Other levels (observe) - standard block
            plan.status = PlanStatus.FAILED
            plan.result = check.blocked_result or {
                "success": False, "blocked_by": "authority_observe"
            }
            plan.message = f"Efektor zablokowany (level={authority_level})"

        self._state.total_plans_executed += 1

        if trace:
            trace.finalize(
                success=False,
                result_summary=f"effector_{authority_level}: {plan.status.value}",
            )
            self._save_trace(trace)

        self._emit_cycle_complete(self._state.last_cycle_tick, plan=plan)
        self._log_decision(plan)
        self._save_state()
        clear_episode_id()
        return plan

    def _execute_approved_effector(self, approved_request, trace):
        """
        Execute a previously approved effector request.

        Creates a Plan from the ApprovalRequest and runs through
        the normal K10 safety + ActionExecutor flow.
        """
        from agent_core.tracing.episode import clear_episode_id

        plan = create_plan(
            goal_id=approved_request.goal_id,
            goal_description=approved_request.goal_description,
            action_type=ActionType.EFFECTOR,
            action_params=approved_request.action_params or {
                "tool_name": approved_request.tool_name,
                "tool_args": approved_request.tool_args,
            },
        )
        plan.trace_id = approved_request.episode_id
        plan.message = f"Wykonuje zatwierdzony efektor: {approved_request.tool_name}"
        plan.metadata["approval_request_id"] = approved_request.request_id

        if trace:
            trace.plan_id = plan.plan_id
            trace.action_type = plan.action_type.value
            trace.action_params = plan.action_params
            trace.goal_id = plan.goal_id
            trace.goal_description = plan.goal_description
            trace.add_step("planner", "approved_effector", "executing", {
                "request_id": approved_request.request_id,
                "tool_name": approved_request.tool_name,
            })

        # K10: before_action
        if self._action_safety:
            try:
                self._action_safety.before_action(
                    plan_id=plan.plan_id,
                    action_type=plan.action_type.value,
                    action_params=plan.action_params,
                    goal_id=plan.goal_id,
                    metadata=plan.metadata,
                )
            except Exception:
                pass

        plan.status = PlanStatus.EXECUTING
        start = time.time()
        result = self.executor.execute(plan)
        plan.result = result
        plan.duration_ms = (time.time() - start) * 1000
        plan.status = (
            PlanStatus.COMPLETED if result.get("success") else PlanStatus.FAILED
        )

        # K10: after_action
        if self._action_safety:
            try:
                self._action_safety.after_action(
                    plan_id=plan.plan_id,
                    success=result.get("success", False),
                    result=result,
                    duration_ms=plan.duration_ms,
                )
            except Exception:
                pass

        # K7: record outcome
        if self._autonomy_policy:
            self._autonomy_policy.record_execution(
                plan.action_type.value, result.get("success", False),
            )

        # Notify operator of result
        if self._telegram_notifier:
            try:
                self._telegram_notifier.notify_effector_result(
                    tool_name=approved_request.tool_name,
                    success=result.get("success", False),
                    summary=str(result.get("tool_result", result.get("error", "")))[:200],
                )
            except Exception:
                pass

        self._state.total_plans_executed += 1

        if trace:
            trace.finalize(
                success=result.get("success", False),
                result_summary=f"effector_executed: {approved_request.tool_name}",
            )
            self._save_trace(trace)

        self._emit_cycle_complete(self._state.last_cycle_tick, plan=plan)
        self._log_decision(plan)
        self._save_state()
        clear_episode_id()
        return plan

    def _format_message(self, plan: Plan) -> str:
        """Generate human-readable message for a plan decision."""
        action = plan.action_type
        goal = plan.goal_description or ""

        if action == ActionType.LEARN:
            return f"Ucze sie: {goal}" if goal else "Ucze sie nowego materialu"
        elif action == ActionType.EXAM:
            return f"Egzamin z: {goal}" if goal else "Egzamin"
        elif action == ActionType.REVIEW:
            retention = plan.action_params.get("retention")
            if retention is not None:
                return f"Powtorka: {goal} (retention {retention:.0%})"
            return f"Powtorka: {goal}" if goal else "Powtorka materialu"
        elif action == ActionType.EVALUATE:
            return "Ewaluacja: raport okresowy"
        elif action == ActionType.MAINTENANCE:
            metric = plan.action_params.get("metric", "")
            return f"Konserwacja: {metric}" if metric else "Konserwacja systemu"
        elif action == ActionType.FETCH:
            return "Pobieram nowe materialy z internetu"
        elif action == ActionType.EXPERIMENT:
            return f"Eksperyment: {goal}" if goal else "Eksperyment z parametrem"
        elif action == ActionType.ASK_EXPERT:
            topic = plan.action_params.get("topic", "")
            return f"Pytam eksperta: {topic}" if topic else "Pytam eksperta o wiedze"
        elif action == ActionType.NOOP:
            return "Nic do zrobienia - czekam"
        return f"{action.value}: {goal}"

    # -- Internal: event emission ---------------------------

    def _emit_cycle_complete(
        self,
        tick_count: int,
        guard_blocked: bool = False,
        block_reasons: Optional[List[str]] = None,
        no_goals: bool = False,
        plan: Optional[Plan] = None,
    ) -> None:
        """Emit planner_cycle_complete PerceptionEvent at end of every cycle."""
        if self._homeostasis_core is None:
            return

        try:
            from agent_core.perception.event import (
                PerceptionSource, create_event,
            )

            if guard_blocked:
                message = f"Planowanie wstrzymane: {', '.join(block_reasons or [])}"
            elif no_goals:
                message = "Brak aktywnych celow - czekam"
            elif plan is not None:
                message = self._format_message(plan)
            else:
                message = "Cykl zakonczony"

            payload = {
                "tick": tick_count,
                "cycle": self._state.total_cycles,
                "guard_blocked": guard_blocked,
                "no_goals": no_goals,
                "message": message,
            }

            if plan is not None:
                payload["plan_id"] = plan.plan_id
                payload["action_type"] = plan.action_type.value
                payload["goal_description"] = plan.goal_description
                payload["success"] = plan.result.get("success", False)
                payload["duration_ms"] = plan.duration_ms

            event = create_event(
                source=PerceptionSource.PLANNER,
                event_type="planner_cycle_complete",
                payload=payload,
                priority=0.3,
            )
            self._homeostasis_core.push_external_event(event)
        except Exception as e:
            logger.debug(f"Could not emit cycle complete event: {e}")

    def _emit_decision_event(self, plan: Plan) -> None:
        """Push a planner_decision PerceptionEvent with rich payload."""
        if self._homeostasis_core is None:
            return

        try:
            from agent_core.perception.event import (
                PerceptionSource, create_event,
            )

            message = self._format_message(plan)

            event = create_event(
                source=PerceptionSource.PLANNER,
                event_type="planner_decision",
                payload={
                    "plan_id": plan.plan_id,
                    "goal_id": plan.goal_id,
                    "goal_description": plan.goal_description,
                    "action_type": plan.action_type.value,
                    "status": plan.status.value,
                    "success": plan.result.get("success", False),
                    "message": message,
                    "duration_ms": plan.duration_ms,
                    "result_details": plan.result,
                },
                priority=0.5,
            )
            self._homeostasis_core.push_external_event(event)
        except Exception as e:
            logger.debug(f"Could not emit planner event: {e}")

    # -- Persistence ----------------------------------------

    def _log_skip(self, tick_count: int, reason: str, details: list) -> None:
        """Log skipped cycle to planner_decisions.jsonl for debugging."""
        try:
            self._decisions_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "plan_id": None,
                "timestamp": time.time(),
                "action_type": "skip",
                "status": reason,
                "message": f"Cykl pominiety: {reason}",
                "result": {"reasons": details},
                "tick": tick_count,
            }
            with open(self._decisions_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except IOError:
            pass

    def _save_trace(self, trace: DecisionTrace) -> None:
        """Save decision trace to TraceStore (if available)."""
        if self._trace_store is None:
            return
        try:
            self._trace_store.record(trace)
        except Exception as e:
            logger.debug(f"Could not save trace: {e}")
        finally:
            self._current_trace = None

    def _log_decision(self, plan: Plan) -> None:
        """Append plan to planner_decisions.jsonl."""
        try:
            self._decisions_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._decisions_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(plan.to_dict(), ensure_ascii=False) + "\n")
        except IOError as e:
            logger.warning(f"Could not log planner decision: {e}")

    def _save_state(self) -> None:
        """Save planner state to JSON."""
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._state_path, "w", encoding="utf-8") as f:
                json.dump(self._state.to_dict(), f, indent=2)
        except IOError as e:
            logger.warning(f"Could not save planner state: {e}")

    def _load_state(self) -> None:
        """Load planner state from JSON."""
        if not self._state_path.exists():
            return
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._state = PlannerState.from_dict(data)
        except (IOError, json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Could not load planner state: {e}")
            self._state = PlannerState()

    def _last_cycle_ts(self) -> float:
        """Approximate timestamp of last cycle for event-driven checks."""
        # Use last_evaluation_ts as proxy, or 0 if never ran
        if self._state.last_evaluation_ts > 0:
            return self._state.last_evaluation_ts
        return 0.0

    # -- Status & History (for REPL) ------------------------

    def get_status(self) -> Dict[str, Any]:
        """Get planner status for /plan status command."""
        return {
            "total_cycles": self._state.total_cycles,
            "total_plans_executed": self._state.total_plans_executed,
            "last_cycle_tick": self._state.last_cycle_tick,
            "last_evaluation_ts": self._state.last_evaluation_ts,
            "current_plan_id": self._state.current_plan_id,
            "recent_plans": len(self._last_plans),
        }

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent plans from JSONL."""
        if not self._decisions_path.exists():
            return []
        records = []
        try:
            with open(self._decisions_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except IOError:
            return []
        return records[-limit:]
