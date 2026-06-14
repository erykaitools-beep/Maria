"""
PlannerCore - ReAct loop engine connecting K1-K4.

Synchronous, called from tick loop Phase 10.
No LLM. Deterministic. Testable.

Kontrakt: docs/CONTRACTS.md - Kontrakt 5: Planner
ADR-013: Planner v1 rule-based (no LLM)
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.planner.planner_model import (
    Plan, PlanStatus, PlannerState, ActionType, create_plan,
)
from agent_core.planner.planner_guard import PlannerGuard
from agent_core.planner.goal_selector import GoalSelector
from agent_core.planner.action_executor import ActionExecutor
from agent_core.planner.stuck_handler import StuckHandler
from agent_core.planner.time_context import TimeContext
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

# Stuck detection
STUCK_THRESHOLD = 3              # consecutive identical failures -> stuck
STUCK_COOLDOWN_SEC = 1800        # 30 min cooldown for stuck goal
STUCK_HISTORY_SIZE = 10          # track last N failure fingerprints
# Non-productive loop: same (goal, reflection action) repeated N times with
# status=COMPLETED (not caught by stuck_history). Target: meta-goals that
# lack decomposable steps and keep triggering evaluate/critique forever.
NONPRODUCTIVE_REPEAT_THRESHOLD = 20
GOAL_CYCLE_THRESHOLD = 5        # T-B4-001: goal attempts without progress

# Auto-learning goal limits
MAX_AUTO_LEARNING_GOALS = 3
AUTO_GOAL_COOLDOWN_SEC = 3600  # 1 hour
MIN_RETENTION_FOR_NEW_TOPICS = 0.6

# Actions that require an open learning window. If K8 Deliberation suggests
# one of these outside the window for a non-USER goal, the planner rewrites
# the plan to NOOP instead of letting the executor reject it downstream
# (848/889 learn fails observed during glm-5.1 test 2026-04-21).
LEARNING_WINDOW_ACTIONS = frozenset({
    ActionType.LEARN,
    ActionType.EXAM,
    ActionType.REVIEW,
    ActionType.FETCH,
    ActionType.ASK_EXPERT,
})

# 8b: max learn-family actions allowed OUTSIDE the learning window per day.
# The window stays the *preferred* learning time; this daily budget lets the
# planner still make a little progress off-window (weekends/nights) instead of
# skipping 100% of cycles, while capping attempts so a failing learn loop can't
# hammer the executor the way it did before the window existed (264+/day).
OFF_WINDOW_LEARN_BUDGET = 8


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
        # 8a: per-goal infeasibility reasons from the last goal-ranking pass,
        # surfaced in the no_goals skip log instead of a bare empty list.
        self._last_skip_reasons: list = []
        # 8b: set by _enforce_learning_window when it approves a learn-family
        # action off-window against the daily budget, so run_cycle can mark the
        # plan and the executor's own window gate honors that decision.
        self._last_off_window_approved: bool = False
        self._time_ctx = TimeContext()

        # Action failure memory: {action_key -> (fail_count, last_fail_ts)}
        # action_key = "action_type:goal_id" or just "action_type"
        self._action_failures: Dict[str, tuple] = {}
        # Max failures before backoff (skip until conditions change)
        self._MAX_ACTION_FAILURES = 3
        # Backoff expiry: clear failure memory after this (conditions may have changed)
        self._FAILURE_MEMORY_TTL = 3600  # 1 hour

        # External references (set via set_* methods)
        self._homeostasis_core = None
        self._perception_buffer = None
        self._goal_store = None
        self._evaluation_observer = None
        self._teacher_agent = None
        self._knowledge_analyzer = None
        self._sandbox_manager = None
        self._world_model = None
        self._semantic_memory = None
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
        self._gap_planner = None
        self._trace_store = None
        self._strategic_planner = None  # v2 Phase B
        # #9: when true, the strategist's plan actually steers the tactical loop
        # (blocked_goals filter, next_action focus, idle_strategy). Default OFF
        # -> wired but dormant until observed in vivo, then flip the env var.
        self._strategic_drives = os.environ.get(
            "STRATEGIC_PLANNER_DRIVES", "false"
        ).strip().lower() in {"1", "true", "yes", "on"}
        # B2: when true, the planner autonomously emits a sandboxed FS_WRITE to
        # satisfy a goal's file_exists criterion (the first real effector action).
        # Default OFF -> wired but dormant until observed in vivo, then flip.
        self._fs_write_enabled = os.environ.get(
            "FS_WRITE_ENABLED", "false"
        ).strip().lower() in {"1", "true", "yes", "on"}
        # B4: when true, the planner autonomously emits an EXAM for a goal that
        # carries an unmet exam_independent criterion, so the goal can close on
        # an INDEPENDENT examiner's verdict (not self-report). Default OFF ->
        # wired but dormant until observed; mirror of _fs_write_enabled (B2).
        self._heldout_enabled = os.environ.get(
            "HELDOUT_GRADER_ENABLED", "false"
        ).strip().lower() in {"1", "true", "yes", "on"}
        # Override for the FS_WRITE sandbox root (None -> canonical
        # meta_data/fs_sandbox under BASE_DIR). Settable for tests / relocation.
        self._fs_sandbox_root = None
        self._approval_queue = None
        self._telegram_notifier = None
        self._current_trace: Optional[DecisionTrace] = None
        self._stuck_handler = StuckHandler()

        # Per-tick log dedup for K12 bulletin advisory (P1 fix 2026-05-08).
        # Without this, planner pivot loop logs the same advisory once per
        # blocked goal (e.g. 6× per tick when 6 maintenance goals are
        # all K7-blocked in SLEEP mode). Cleared at start of each run_cycle.
        self._advisory_logged_this_tick: set = set()

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
        self._stuck_handler.set_goal_store(store)

    def set_evaluation_observer(self, observer) -> None:
        self._evaluation_observer = observer
        self.executor.set_evaluation_observer(observer)

    def set_teacher_agent(self, agent) -> None:
        self._teacher_agent = agent
        self.executor.set_teacher_agent(agent)

    def set_knowledge_analyzer(self, analyzer) -> None:
        self._knowledge_analyzer = analyzer
        self.executor.set_knowledge_analyzer(analyzer)
        self._stuck_handler.set_knowledge_analyzer(analyzer)

    def set_sandbox_manager(self, manager) -> None:
        self._sandbox_manager = manager

    def set_world_model(self, world_model) -> None:
        self._world_model = world_model
        self.executor.set_world_model(world_model)

    def set_semantic_memory(self, semantic_memory) -> None:
        """Wire SemanticMemory so maintain() can run SEMANTIC dedup.

        Without this, run_maintenance gets semantic_memory=None and the
        embedding-similarity phase silently never runs (wired-but-dead
        class, found 2026-06-10).
        """
        self._semantic_memory = semantic_memory

    def set_autonomy_policy(self, policy) -> None:
        self._autonomy_policy = policy
        self._stuck_handler.set_autonomy_policy(policy)

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

    def set_incident_memory(self, incident_memory) -> None:
        """Set IncidentMemory for recording action failures (Faza 7)."""
        self.executor.set_incident_memory(incident_memory)

    def set_telegram_notifier(self, notifier) -> None:
        """Set TelegramNotifier for effector request notifications (Phase 5)."""
        self._telegram_notifier = notifier

    def set_trace_store(self, store) -> None:
        """Set TraceStore for decision traceability (Phase 1)."""
        self._trace_store = store

    def set_strategic_planner(self, planner) -> None:
        """Set StrategicPlanner for LLM-powered planning (v2 Phase B)."""
        self._strategic_planner = planner

    def set_strategic_drives(self, enabled: bool) -> None:
        """Runtime toggle for #9 (Telegram /strategic). Flips whether the
        strategist steers the tactical loop without a restart, so the in-vivo
        drill can be driven from the phone and rolled back instantly. Runtime
        only -- resets to the STRATEGIC_PLANNER_DRIVES env default on restart."""
        self._strategic_drives = bool(enabled)
        logger.info("[#9] strategic drives -> %s (runtime toggle)",
                    self._strategic_drives)

    def set_fs_write_enabled(self, enabled: bool) -> None:
        """Runtime toggle for B2 autonomous FS_WRITE (Telegram /fs_write). Flips
        the first-effector-action loop without a restart, so the in-vivo drill
        can be driven from the phone and rolled back instantly. Runtime only --
        resets to the FS_WRITE_ENABLED env default on restart."""
        self._fs_write_enabled = bool(enabled)
        logger.info("[B2] fs_write autonomous loop -> %s (runtime toggle)",
                    "ON" if self._fs_write_enabled else "OFF")

    def set_heldout_enabled(self, enabled: bool) -> None:
        """Runtime toggle for B4 autonomous held-out exam (Telegram /heldout).
        Drives the in-vivo drill: when ON the planner re-examines files behind
        exam_independent criteria so their goals close on an independent
        examiner's verdict. Pairs with the HELDOUT_GRADER_ENABLED env flag the
        exam pipeline reads to actually grade held-out (set together by the
        command). Runtime only -- resets to the env default on restart."""
        self._heldout_enabled = bool(enabled)
        logger.info("[B4] held-out exam autonomous loop -> %s (runtime toggle)",
                    "ON" if self._heldout_enabled else "OFF")

    def strategic_status_text(self) -> str:
        """Human-readable #9 status for Telegram /strategic: whether the
        strategist is driving + a summary of its current plan (if any)."""
        state = "ON" if self._strategic_drives else "OFF"
        lines = [f"StrategicPlanner DRIVES: {state}"]
        sp = self._strategic_planner
        if sp is None:
            lines.append("(strateg nie wired)")
            return "\n".join(lines)
        plan = sp.current_plan
        if plan is None:
            lines.append("Brak aktywnego planu (jeszcze nie replanowal / wygasl).")
        else:
            lines.append(plan.summary())
            lines.append(f"model: {plan.model_used}")
        return "\n".join(lines)

    def _strategic_plan_active(self):
        """Single gate for all #9 wiring: return the strategist's current plan
        IFF it should drive tactical decisions (STRATEGIC_PLANNER_DRIVES on and
        a non-expired plan exists), else None. Flag off -> None -> every wiring
        point is a no-op, so behaviour is identical to the advisory era."""
        if not self._strategic_drives:
            return None
        if self._strategic_planner is None:
            return None
        return self._strategic_planner.current_plan  # None if expired

    def _strategic_replan_due(self) -> bool:
        """True iff the strategist should run its (blocking, LLM-backed) replan
        this cycle. Gated on _strategic_drives: when strategic planning is not
        driving tactics its plan is discarded by _strategic_plan_active() anyway,
        so paying for the call was pure waste -- and on 2026-06-02 one such wasted
        call hung Ollama and froze the tick loop for 10.5h. Off => no call, which
        also makes Telegram /strategic off a real kill switch for this path."""
        return bool(
            self._strategic_drives
            and self._strategic_planner is not None
            and self._strategic_planner.should_replan()
        )

    def _apply_strategic_focus(self, ranked_goals: list) -> list:
        """#9 Wire B: bring the strategist's next_action goal to the front of
        the already-feasible ranking so it gets first attempt. The tactical loop
        still decides the concrete action and keeps every safety gate -- the
        strategist only steers WHICH goal, not HOW. If its target is not
        feasible this round, skip that action so the plan advances (is_exhausted
        -> should_replan) instead of fixating on a dead goal. No-op when not
        driving."""
        sp = self._strategic_plan_active()
        if not sp:
            return ranked_goals
        nxt = sp.next_action
        if not nxt or not nxt.goal_id:
            return ranked_goals
        if any(g.id == nxt.goal_id for g in ranked_goals):
            focused = [g for g in ranked_goals if g.id == nxt.goal_id]
            rest = [g for g in ranked_goals if g.id != nxt.goal_id]
            return focused + rest
        # focused goal not feasible now -> let the plan move on next cycle
        sp.mark_action(nxt, skipped=True)
        return ranked_goals

    def _record_strategic_outcome(self, goal, *, completed: bool = False,
                                  skipped: bool = False) -> None:
        """#9 Wire B loop-closure: advance the strategist's plan when the
        tactical loop commits (or NOOP-skips) the goal it asked for next, so the
        plan lifecycle is real -- is_exhausted/should_replan react to work done,
        not just the 30-min clock. No-op unless driving and the goal matches the
        current next_action."""
        sp = self._strategic_plan_active()
        if not sp or goal is None:
            return
        nxt = sp.next_action
        if nxt and nxt.goal_id and nxt.goal_id == goal.id:
            sp.mark_action(nxt, completed=completed, skipped=skipped)

    def _fallback_action(self, context: Dict) -> Optional[Plan]:
        """STEP 5 idle fallback when no goal is actionable: the analytical
        cascade then creative. #9 Wire C lets the strategist's idle_strategy
        bias it -- "creative" promotes reflection ahead of the cascade, "wait"
        skips the heavier trailing creative (the cheap READ-ONLY cascade still
        runs), "evaluate"/None keep the original order. Returns a raw Plan (the
        caller finalizes) or None."""
        sp = self._strategic_plan_active()
        idle_strategy = sp.idle_strategy if sp else None

        # #9 Wire C: "creative" -> reflection takes priority over the analytical
        # cascade (else evaluate/validate/critique can starve it).
        if idle_strategy == "creative":
            plan = self._maybe_creative(context)
            if plan is not None:
                return plan

        # Evaluate as fallback
        plan = self._maybe_evaluate(context)
        if plan is not None:
            return plan
        # Faza F: cross-validate learned knowledge
        plan = self._maybe_validate(context)
        if plan is not None:
            return plan
        # Faza G: knowledge quality critique
        plan = self._maybe_critique(context)
        if plan is not None:
            return plan
        # K12: self-analysis
        plan = self._maybe_self_analyze(context)
        if plan is not None:
            return plan
        # K11: experiment proposal scan
        plan = self._maybe_experiment_scan(context)
        if plan is not None:
            return plan

        # K13: creative reflection (before NOOP). #9 Wire C: "wait" skips this
        # heavier idle action; the cheap analytical cascade above still ran.
        if idle_strategy != "wait":
            plan = self._maybe_creative(context)
            if plan is not None:
                return plan
        return None

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

    def set_gap_planner(self, planner) -> None:
        """Set GapPlanner for gap-driven learning decisions (Phase 3)."""
        self._gap_planner = planner

    # -- Internal: pre-check autonomy policy ----------------

    def _is_action_rate_limited(self, action_type_value: str) -> bool:
        """
        Quick check if action would be blocked by K7 (rate limit, mode, or consecutive failures).

        Used to avoid creating plans we know will be blocked.
        """
        if not getattr(self, '_autonomy_policy', None):
            return False
        try:
            # Pass current mode so K7 can block GUARDED actions in SLEEP/REDUCED
            mode = "active"
            health = 1.0
            if self._homeostasis_core:
                state = self._homeostasis_core.get_state()
                mode = state.mode.value
                health = state.health_score
            check = self._autonomy_policy.check(
                action_type=action_type_value,
                action_params={},
                mode=mode,
                health_score=health,
            )
            return not check.allowed
        except Exception:
            return False

    # -- Action failure memory (Planner v2 Phase A) ----------

    def _action_key(self, action_type: str, goal_id: Optional[str] = None) -> str:
        """Build key for failure tracking."""
        if goal_id:
            return f"{action_type}:{goal_id}"
        return action_type

    def record_action_failure(self, action_type: str, goal_id: Optional[str] = None) -> None:
        """Record a failed action for backoff tracking."""
        key = self._action_key(action_type, goal_id)
        count, _ = self._action_failures.get(key, (0, 0))
        self._action_failures[key] = (count + 1, time.time())

    def record_action_success(self, action_type: str, goal_id: Optional[str] = None) -> None:
        """Clear failure memory on success."""
        key = self._action_key(action_type, goal_id)
        self._action_failures.pop(key, None)

    def is_action_backed_off(self, action_type: str, goal_id: Optional[str] = None) -> bool:
        """Check if action should be skipped due to repeated failures."""
        key = self._action_key(action_type, goal_id)
        if key not in self._action_failures:
            return False
        count, last_ts = self._action_failures[key]
        # TTL expired - clear and allow
        if time.time() - last_ts > self._FAILURE_MEMORY_TTL:
            del self._action_failures[key]
            return False
        return count >= self._MAX_ACTION_FAILURES

    def _get_idle_reason(self) -> str:
        """Get human-readable reason why planner is idle (for traces/logs)."""
        tc = self._time_ctx
        if tc.is_quiet_hours:
            return f"quiet hours ({tc.berlin_now.strftime('%H:%M')} Berlin)"
        if not tc.is_learning_window:
            return f"outside learning window (next in {tc.minutes_to_next_window}min)"
        return "no feasible goals"

    # -- Main entry point (called from tick loop) -----------

    def should_run(self, tick_count: int) -> bool:
        """
        Determine if planner should run this tick.

        Hybrid frequency:
        - Every ROUTINE_INTERVAL_TICKS (60 ticks)
        - Immediately on high-priority events in PerceptionBuffer
        """
        # Routine check with NOOP backoff:
        # After consecutive NOOPs, extend interval (60s -> 120s -> 300s -> 600s max)
        noop_count = self._state.consecutive_noop_count
        if noop_count >= 3:
            backoff_multiplier = min(noop_count - 1, 10)  # cap at 10x
            interval = ROUTINE_INTERVAL_TICKS * backoff_multiplier
        else:
            interval = ROUTINE_INTERVAL_TICKS
        ticks_since = tick_count - self._state.last_cycle_tick
        # Handle tick discontinuity after daemon restart (tick resets to 0)
        if ticks_since < 0 or ticks_since >= interval:
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

        # P1 fix: reset per-tick advisory dedup for this cycle
        self._advisory_logged_this_tick.clear()

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

        # -- STEP 1.7: STRATEGIC PLANNING (v2 Phase B) --
        # Gated on _strategic_drives (see _strategic_replan_due): off => no
        # blocking LLM replan, which is both free and freeze-proof.
        if self._strategic_replan_due():
            try:
                strategic_plan = self._strategic_planner.plan(
                    action_failures=self._action_failures
                )
                if strategic_plan and trace:
                    trace.add_step(
                        "strategic_planner", "replan",
                        f"{len(strategic_plan.action_queue)} actions, "
                        f"idle={strategic_plan.idle_strategy}",
                    )
                    logger.info(
                        f"[Strategic] New plan: {strategic_plan.summary()}"
                    )
            except Exception as e:
                logger.warning(f"Strategic planning failed: {e}")

        # -- STEP 2: PERCEIVE --
        context = self._gather_context()

        # -- STEP 2.3: RECONCILE completed learning goals (Plank 2b) --
        # Harvest goals whose material is already exam-verified before we
        # select/plan -- they have no work left to trigger a progress credit.
        self._reconcile_learning_goals(context)

        # -- STEP 2.4: BACKFILL orphaned fetched files (P4, #4) --
        # Bind any 'new', never-examined, fetched file that has no handoff goal
        # so it can never sit unlearned forever (drains the live web_rss_* leak).
        self._sweep_orphan_fetches(context)

        # -- STEP 2.5: CREATIVE CHECK (independent of goal cycle) --
        # Creative runs on its own cooldown, not competing with learn/fetch
        plan = self._maybe_creative(context)
        if plan is not None:
            return self._finalize_plan(plan)

        # -- STEP 2.6: FS_WRITE (B2) -- first real effector action, flag-gated --
        # When a goal carries an unmet file_exists success criterion, write the
        # file so the goal can close on EXTERNAL evidence. Behind FS_WRITE_ENABLED
        # (default OFF) -> no-op, so the loop below is unchanged until observed.
        plan = self._maybe_fs_write(context)
        if plan is not None:
            return self._finalize_plan(plan)

        # -- STEP 2.7: HELD-OUT EXAM (B4) -- prove a learning goal by an
        # INDEPENDENT examiner. When a goal carries an unmet exam_independent
        # criterion, re-examine its file (held-out static grader) so it closes
        # on recorded evidence. Behind the heldout flag (default OFF) -> no-op.
        plan = self._maybe_run_heldout_exam(context)
        if plan is not None:
            return self._finalize_plan(plan)

        # -- STEP 3: SELECT GOAL with pivot (try next if NOOP/blocked) --
        ranked_goals = self._select_ranked_goals(context)
        if not ranked_goals:
            # Try to auto-create a learning goal with topic selection
            created = self._auto_create_learning_goal(context)
            if created:
                ranked_goals = self._select_ranked_goals(context)

        # #9 Wire B: focus. Bring the strategist's next_action goal to the front
        # of the feasible ranking so it gets first attempt (tactical loop still
        # decides the concrete action and keeps every safety gate).
        ranked_goals = self._apply_strategic_focus(ranked_goals)

        # Plank 1: promote a goal PENDING->ACTIVE the moment the planner
        # commits real work to it (see activation block below). GoalStatus
        # imported here following this module's local-import convention.
        from agent_core.goals.goal_model import GoalStatus

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
            self._last_off_window_approved = False
            plan = self._create_plan_for_goal(goal, context)
            if self._last_off_window_approved and plan.action_type != ActionType.NOOP:
                # 8b: this learn-family action was approved off-window against
                # the daily budget -> tell the executor's own window gate to
                # honor it instead of re-blocking as "outside_learning_window".
                plan.metadata["off_window_approved"] = True
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
                # #9 Wire B: if this NOOP'd goal is the strategist's focus,
                # advance its plan so we don't re-focus a dead-end every cycle.
                self._record_strategic_outcome(goal, skipped=True)
                continue

            # -- Plank 1: ACTIVATE the goal now that real work is committed --
            # Goals are born PENDING and nothing ever promoted them to ACTIVE.
            # update_progress() only auto-ACHIEVES goals that are ACTIVE, so
            # learning goals could never close autonomously -> they all died
            # "stale" (1118 abandoned, 0 autonomous completions before this).
            # Promote here, before execution, so the executor's progress update
            # can carry the goal to ACHIEVED in the same cycle.
            if goal.status == GoalStatus.PENDING:
                self._goal_store.update_status(
                    goal.id, GoalStatus.ACTIVE,
                    f"planner started work (action={plan.action_type.value})",
                    "planner",
                )
                self._goal_store.save()
                if trace:
                    trace.add_step("planner", "goal_activated", "pending->active", {
                        "goal_id": goal.id,
                        "action_type": plan.action_type.value,
                    })

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
            # #9 Wire B: real work committed on the strategist's focus goal ->
            # mark its action done so the plan advances toward exhaustion.
            self._record_strategic_outcome(goal, completed=True)
            return result

        # -- STEP 5: idle fallback (analytical cascade + creative). #9 Wire C
        # lets the strategist's idle_strategy bias which idle action runs. --
        plan = self._fallback_action(context)
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
        self._state.consecutive_noop_count += 1
        logger.debug(
            "Planner: no feasible goal and no evaluation needed "
            "(noop streak: %d)", self._state.consecutive_noop_count,
        )
        if trace:
            trace.add_step("planner", "no_goals", "idle")
            trace.finalize(success=True, result_summary="no_goals")
            self._save_trace(trace)
        self._emit_cycle_complete(tick_count, no_goals=True)
        self._log_skip(tick_count, "no_goals", list(self._last_skip_reasons))
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

    def _reconcile_learning_goals(self, context: Dict) -> None:
        """Plank 2b: credit learning-goal progress from the current knowledge
        state, independent of any LEARN/EXAM action.

        Progress is otherwise credited only as a side effect of a successful
        learn/exam (handlers.update_learning_goal). A goal whose material was
        already mastered -- its files exam-passed while another goal drove
        them, or in a prior session -- has nothing left to run and so could
        never close: it sat at progress 0 until it died 'stale'. This sweep
        harvests such goals: when a goal's owned files are all INDEPENDENTLY
        exam-verified (a different model graded the recall, not the student's
        own self-grading), it is marked ACHIEVED.
        """
        if self._goal_store is None or self._knowledge_analyzer is None:
            return
        snapshot = context.get("knowledge_snapshot")
        if not snapshot:
            return

        from agent_core.goals.goal_model import GoalType, GoalStatus
        from agent_core.routing.handlers import (
            resolve_goal_files, independently_verified_completed_ids,
        )

        # Only INDEPENDENTLY exam-verified files may force-close a goal -- never
        # the self-graded 'completed' status (audit 2026-06-01: closing on
        # 'completed' bypassed the B4 keystone and falsely marked goals
        # 'exam-verified' on the student's own self-grading).
        verified = independently_verified_completed_ids(snapshot)
        if not verified:
            return

        harvested = []
        changed = False
        for goal in self._goal_store.get_active(GoalType.LEARNING):
            files = resolve_goal_files(goal, None, self._knowledge_analyzer)
            if not files:
                continue
            frac = sum(1 for fid in files if fid in verified) / len(files)
            if frac <= goal.progress:
                continue
            # update_progress auto-ACHIEVES an ACTIVE goal at >= 1.0; a PENDING
            # goal needs the transition made explicitly.
            self._goal_store.update_progress(goal.id, frac)
            changed = True
            if frac >= 1.0:
                refreshed = self._goal_store.get(goal.id)
                if refreshed and refreshed.status != GoalStatus.ACHIEVED:
                    self._goal_store.update_status(
                        goal.id, GoalStatus.ACHIEVED,
                        "all material independently exam-verified (reconciliation)",
                        "planner",
                    )
                self._goal_store.set_outcome(goal.id, {
                    "completed_at": time.time(),
                    "files_total": len(files),
                    "reconciled": True,
                })
                harvested.append(goal.description)
                logger.info(
                    "[Plank2b] Learning goal ACHIEVED by reconciliation: "
                    f"{goal.id} ({goal.description[:60]})"
                )

        if changed:
            self._goal_store.save()
        if harvested and self._telegram_notifier:
            try:
                lines = "\n".join(f"- {d[:60]}" for d in harvested[:8])
                more = (
                    f"\n(+{len(harvested) - 8} wiecej)"
                    if len(harvested) > 8 else ""
                )
                self._telegram_notifier.notify(
                    "learning_complete",
                    f"*Cele domkniete (inwentaryzacja): {len(harvested)}*\n"
                    f"{lines}{more}",
                )
            except Exception:
                pass

    def _sweep_orphan_fetches(self, context: Dict) -> None:
        """P4 (#4): bind a learn-obligation for fetched files that reached the
        index with NO handoff goal.

        The forward bind (P1/P2) only fires on the fetch action path; a file can
        still land in the index unbound -- written by a pre-handoff fetch, or by
        a session whose bind the fixes missed. Such files sit status='new'
        forever (only the best-effort teacher 'new file' loop might reach them).
        This sweep drains them: every 'new', never-examined, fetched file with no
        obligation is bound into a (backfill) fetch_handoff goal -- reusing the
        one goal-creation path so it inherits selector priority + the 30d window.

        Tightly scoped to avoid sweeping material the operator let decay:
          - only web_*/codex_* names (fetched), never expert_* re-study seeds;
          - only exam_attempts == 0 (a re-study file that lost 'completed' has
            attempts > 0, e.g. expert_fizyka.txt with 14);
          - only files not already obligated by an active/pending handoff goal.
        Binding an obligation is clean state, not an action, so it is NOT gated
        by the learning window (the learning it triggers is gated later).
        """
        if self._goal_store is None or self._knowledge_analyzer is None:
            return
        snapshot = context.get("knowledge_snapshot")
        if not snapshot:
            return

        from agent_core.goals.goal_model import GoalType
        from agent_core.routing.handlers import _register_fetch_handoff_goal

        fetched_prefixes = ("web_", "codex_")
        already_bound = set()
        for goal in self._goal_store.get_active(GoalType.LEARNING):
            if goal.metadata.get("source") == "fetch_handoff":
                already_bound.update(goal.metadata.get("file_ids", []))

        orphans = []
        for rec in snapshot.get("files_by_status", {}).get("new", []):
            fid = rec.get("id") or rec.get("file")
            if not fid or not fid.startswith(fetched_prefixes):
                continue
            if rec.get("exam_attempts", 0) > 0:
                continue
            if fid in already_bound:
                continue
            orphans.append(fid)

        if not orphans:
            return

        _register_fetch_handoff_goal(
            None, {"fetched_files": orphans},
            self._knowledge_analyzer, self._goal_store, backfill=True,
        )
        logger.info(
            "[P4] orphan-sweep bound %d unlearned fetched file(s): %s",
            len(orphans), ", ".join(orphans[:5]),
        )

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
        - Planner-level cooldown expired (2h)
        - Creative module itself says it's ready
        - Not rate-limited by K7

        Planner-level cooldown is belt-and-suspenders over
        creative_module.should_reflect() — we observed back-to-back
        reflections on 2026-04-18 despite the facade cooldown. Origin of
        the duplicate call is still unknown; this check guarantees at
        least the planner path respects 2h spacing.
        """
        if self._creative_module is None:
            return None

        # Check K7 rate limit
        if self._is_action_rate_limited("creative"):
            return None

        # Planner-level cooldown (independent of facade)
        now = time.time()
        since_creative = now - self._state.last_creative_ts
        if since_creative < self.CREATIVE_INTERVAL_SEC:
            return None

        # Check if creative module itself says it's ready
        if not self._creative_module.should_reflect():
            return None

        self._state.last_creative_ts = now
        logger.info("[K13] Creative reflection triggered")
        return create_plan(
            goal_id=None,
            goal_description="K13 Creative reflection",
            action_type=ActionType.CREATIVE,
            action_params={"trigger": "planner_idle"},
        )

    def _maybe_fs_write(self, context: Dict) -> Optional[Plan]:
        """B2: emit a sandboxed-write plan to satisfy a goal's file_exists
        success criterion -- the first real effector action ("hands").

        When an active goal carries an unmet success_criteria of type
        file_exists, write the criterion's target file so the goal can close on
        EXTERNAL evidence (K10 re-stats the file; the closer re-checks the
        criterion). Behind FS_WRITE_ENABLED (default OFF): flag off -> no-op,
        behaviour identical to today.
        """
        if not self._fs_write_enabled or self._goal_store is None:
            return None
        if self._is_action_rate_limited("fs_write"):
            return None

        from pathlib import Path
        from agent_core.goals.goal_model import GoalStatus
        from agent_core.goals.success_criteria import evaluate_criteria
        from agent_core.hands.sandbox_writer import default_sandbox_root
        sandbox_root = self._fs_sandbox_root
        if not sandbox_root:
            try:
                from maria_core.sys.config import BASE_DIR
                sandbox_root = default_sandbox_root(BASE_DIR)
            except Exception:
                sandbox_root = default_sandbox_root(".")

        try:
            active = self._goal_store.get_active()
        except Exception:
            return None

        for goal in active:
            crits = getattr(goal, "success_criteria", None)
            if not crits:
                continue
            file_crit = next(
                (c for c in crits
                 if isinstance(c, dict) and c.get("type") == "file_exists"),
                None,
            )
            if not file_crit:
                continue
            # Already satisfied? leave it for the closer/reconcile -- don't rewrite.
            passed, _ = evaluate_criteria(crits, sandbox_root=sandbox_root)
            if passed:
                continue

            target = file_crit.get("path") or ""
            filename = Path(target).name or "maria_action"
            content = (goal.metadata or {}).get("fs_write_content") or (
                f"Maria's first real action.\n"
                f"goal: {goal.id}\n{goal.description}\n"
            )

            # Plank-1 idiom: committing real work promotes PENDING->ACTIVE so
            # update_progress can auto-achieve on closure.
            if goal.status == GoalStatus.PENDING:
                try:
                    self._goal_store.update_status(
                        goal.id, GoalStatus.ACTIVE,
                        "planner committed fs_write", "planner",
                    )
                except Exception:
                    pass

            logger.info("[B2] fs_write plan for goal %s -> %s", goal.id, filename)
            return create_plan(
                goal_id=goal.id,
                goal_description=goal.description,
                action_type=ActionType.FS_WRITE,
                action_params={
                    "filename": filename,
                    "content": content,
                    "sandbox_root": sandbox_root,
                },
            )
        return None

    def _maybe_run_heldout_exam(self, context: Dict) -> Optional[Plan]:
        """B4: emit an EXAM plan to satisfy a goal's exam_independent criterion.

        The learning sibling of _maybe_fs_write (B2): when an active goal carries
        an unmet exam_independent criterion, re-examine its file through the
        held-out static grader so the goal closes on an INDEPENDENT examiner's
        recorded verdict (grader_independent=True in exam_results.jsonl), not the
        student grading its own homework. Behind the heldout flag (default OFF):
        flag off -> no-op, behaviour identical to today.
        """
        if not self._heldout_enabled or self._goal_store is None:
            return None
        if self._is_action_rate_limited("exam"):
            return None

        from agent_core.goals.goal_model import GoalStatus
        from agent_core.goals.success_criteria import evaluate_criteria

        try:
            active = self._goal_store.get_active()
        except Exception:
            return None

        for goal in active:
            crits = getattr(goal, "success_criteria", None)
            if not crits:
                continue
            exam_crit = next(
                (c for c in crits
                 if isinstance(c, dict) and c.get("type") == "exam_independent"),
                None,
            )
            if not exam_crit:
                continue
            file_id = exam_crit.get("file") or exam_crit.get("file_id")
            if not file_id:
                continue
            # Already proven by an independent exam on record? Close it NOW
            # instead of re-examining -- and crucially, instead of leaving it
            # ACTIVE. A satisfied exam_independent goal that is not closed gets
            # re-picked as a learn target every cycle and loops to STUCK (the
            # exam handler only closes a goal it just examined, so a criterion
            # met by an EARLIER recorded exam had no closer). Mirrors
            # close_goal_on_criteria's idempotent update_progress(1.0).
            passed, evidence = evaluate_criteria(crits)
            if passed:
                try:
                    self._goal_store.update_progress(goal.id, 1.0)
                    refreshed = self._goal_store.get(goal.id)
                    if refreshed and refreshed.status.value == "achieved":
                        import time as _t
                        self._goal_store.set_outcome(goal.id, {
                            "closed_by": "success_criteria",
                            "evidence": evidence,
                            "completed_at": _t.time(),
                        })
                        self._goal_store.save()
                        logger.info(
                            "[B4] closed already-proven goal %s (recorded "
                            "independent exam)", goal.id)
                except Exception as exc:
                    logger.debug("[B4] close already-proven skipped: %s", exc)
                continue

            # Plank-1 idiom (mirrors B2): committing real work promotes
            # PENDING->ACTIVE so update_progress can auto-achieve on closure.
            if goal.status == GoalStatus.PENDING:
                try:
                    self._goal_store.update_status(
                        goal.id, GoalStatus.ACTIVE,
                        "planner committed held-out exam", "planner",
                    )
                except Exception:
                    pass

            logger.info("[B4] held-out exam plan for goal %s -> %s",
                        goal.id, file_id)
            return create_plan(
                goal_id=goal.id,
                goal_description=goal.description,
                action_type=ActionType.EXAM,
                action_params={
                    "target_file_id": file_id,
                    "source": "heldout_drill",
                },
            )
        return None

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

    # K11: Experiment proposal scan trigger
    EXPERIMENT_SCAN_INTERVAL_SEC = 14400  # 4h between scans

    def _maybe_experiment_scan(self, context: Dict) -> Optional[Plan]:
        """
        Scan K4/K9 for experiment proposals (K11).

        Triggers every 4h. If proposals are generated, the first approved
        one becomes an EXPERIMENT plan. Proposals require manual approval
        via /experiment approve or Telegram.
        """
        if self._experiment_system is None:
            return None

        if self._is_action_rate_limited("experiment"):
            return None

        now = time.time()
        since_scan = now - self._state.last_experiment_scan_ts

        if since_scan < self.EXPERIMENT_SCAN_INTERVAL_SEC:
            return None

        self._state.last_experiment_scan_ts = now

        # Gather K4 metrics and K9 patterns
        metrics = context.get("evaluation_metrics", {})
        recommendations = context.get("recommendations", [])
        k9_patterns = {}
        if self._meta_cognition:
            try:
                k9_patterns = self._meta_cognition.analyze_patterns()
            except Exception:
                pass

        # Scan for proposals
        proposals = self._experiment_system.scan_for_proposals(
            k4_metrics=metrics,
            k4_recommendations=recommendations,
            k9_patterns=k9_patterns,
        )

        if not proposals:
            return None

        logger.info(
            "[K11] Experiment scan: %d new proposals generated",
            len(proposals),
        )

        # Check if any approved proposal is ready to run
        approved = [
            p for p in self._experiment_system.proposal_engine.get_active_proposals()
            if p.status.value == "approved"
        ]
        if approved:
            proposal = approved[0]
            return create_plan(
                goal_id=None,
                goal_description=f"Experiment: {proposal.hypothesis}",
                action_type=ActionType.EXPERIMENT,
                action_params={"proposal_id": proposal.proposal_id},
            )

        return None

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

        # Auto-abandon stale goals: PENDING > 7 days with no progress
        self._cleanup_stale_goals()

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

        # Auto-abandon stale goals before ranking
        self._cleanup_stale_goals()
        self._last_skip_reasons = []

        active_goals = self._goal_store.get_active()
        if not active_goals:
            return []

        metrics = context.get("evaluation_metrics", {})
        snapshot = context.get("knowledge_snapshot")

        # 8b: off-window learning is allowed up to a daily budget, so goals are
        # not hard-filtered just because we are outside the learning window.
        off_window_allowed = self._off_window_budget_remaining() > 0

        # Use GoalSelector to filter feasible + rank. Capture per-goal reasons
        # for the infeasible ones so a no_goals skip can explain itself (8a).
        scored = []
        infeasible = []
        for goal in active_goals:
            score = self.selector._compute_effective_priority(goal, time.time())
            feasible, reason = self.selector._check_feasibility(
                goal, metrics, snapshot,
                off_window_learning_allowed=off_window_allowed,
            )
            if feasible:
                scored.append((score, goal))
            else:
                infeasible.append({
                    "goal_id": goal.id,
                    "type": goal.type.value if hasattr(goal.type, "value")
                    else str(goal.type),
                    "reason": reason,
                })
        self._last_skip_reasons = infeasible
        scored.sort(key=lambda x: x[0], reverse=True)

        # Filter out stuck-cooled goals
        now = time.time()
        expired = [gid for gid, until_ts in self._state.stuck_cooldowns.items()
                   if until_ts <= now]
        for gid in expired:
            del self._state.stuck_cooldowns[gid]

        scored = [(s, g) for s, g in scored
                  if self._state.stuck_cooldowns.get(g.id, 0) <= now]

        # #9 Wire A: honor the strategist's blocked_goals. When the strategist
        # is driving, drop goals it explicitly told us to skip this round (e.g.
        # "backed off after 3 fails, review first"). Purely subtractive -> can
        # only narrow the already-feasible set, never force an action. The skip
        # reason is recorded so a no_goals cycle can still explain itself (8a).
        sp = self._strategic_plan_active()
        if sp and sp.blocked_goals:
            kept = []
            for s, g in scored:
                block_reason = sp.blocked_goals.get(g.id)
                if block_reason:
                    self._last_skip_reasons.append({
                        "goal_id": g.id,
                        "type": g.type.value if hasattr(g.type, "value")
                        else str(g.type),
                        "reason": f"strategist_blocked: {block_reason}",
                    })
                else:
                    kept.append((s, g))
            scored = kept

        return [g for _, g in scored]

    # -- Internal: plan creation ----------------------------

    def _create_plan_for_goal(self, goal, context: Dict) -> Plan:
        """Map a goal to a concrete single-step plan."""
        goal_type = goal.type.value
        snapshot = context.get("knowledge_snapshot")
        metrics = context.get("evaluation_metrics", {})

        # Forced action from operator (conversation command)
        forced = goal.metadata.get("forced_action_type")
        if forced:
            try:
                action = ActionType(forced)
            except ValueError:
                action = ActionType.NOOP
            action_params = {}
            topics = goal.metadata.get("topics")
            if topics:
                action_params["topics"] = topics
            topic = goal.metadata.get("topic")
            if topic:
                action_params["topic"] = topic
            action_params["source"] = "operator_command"
            return create_plan(
                goal_id=goal.id,
                goal_description=goal.description,
                action_type=action,
                action_params=action_params,
            )

        # v2 Phase A: Skip goals that have failed too many times
        if self.is_action_backed_off("learn", goal.id) and goal_type == "learning":
            logger.debug(f"Skipping goal {goal.id}: backed off after repeated failures")
            return create_plan(
                goal_id=goal.id,
                goal_description=goal.description,
                action_type=ActionType.NOOP,
                action_params={"reason": "backed_off_failures"},
            )

        # MAINTENANCE goals -> action based on theme_tag (P2a fix 2026-05-08).
        # Plain MAINTENANCE handler is NO-OP (returns success without doing
        # anything), so K12-escalator goals never close and K12 keeps emitting
        # "100% failure" advisory. Route by theme to a handler that actually
        # bumps progress. Unknown themes fall back to MAINTENANCE.
        if goal_type == "maintenance":
            theme = (goal.metadata or {}).get("theme_tag", "")
            theme_to_action = {
                "learn_failures": ActionType.LEARN,
                "passive_drift": ActionType.LEARN,
                "retention_low": ActionType.REVIEW,
                "skip_overuse": ActionType.EVALUATE,
                "stale_goals": ActionType.EVALUATE,
                # VALIDATE here was wrong: _exec_validate needs a file_id that
                # K12-escalator goals never carry → always returns
                # "No files ready for validation" → planner loops. EVALUATE
                # runs the K4 report instead, surfaces metrics, and closes
                # the goal without creating another validate cascade.
                "validate_failures": ActionType.EVALUATE,
                # exam_failures advisory → REVIEW is the logical response
                # (re-study the material that failed). Falls back to MAINTENANCE
                # (no-op) without this entry.
                "exam_failures": ActionType.REVIEW,
            }
            routed = theme_to_action.get(theme, ActionType.MAINTENANCE)
            return create_plan(
                goal_id=goal.id,
                goal_description=goal.description,
                action_type=routed,
                action_params={
                    "metric": goal.metadata.get("metric", ""),
                    "theme": theme,
                },
            )

        # D1.5c (2026-04-22): saturation META-learning goals route to FETCH
        # directly. K8 Deliberation almost always picks learn_topic for goals
        # with a concrete topic, so without this bypass saturated goals never
        # pull new materials from the web even though explore_new exists.
        # Window guard (_enforce_learning_window) still runs below.
        from agent_core.planner.goal_selector import is_saturation_meta_goal
        if (is_saturation_meta_goal(goal, snapshot)
                and not self._is_action_rate_limited("fetch")):
            action = ActionType.FETCH
            action_params: Dict[str, Any] = {}
            topics = goal.metadata.get("topics")
            if topics:
                action_params["topics"] = topics
            action, override_reason = self._enforce_learning_window(goal, action)
            if override_reason:
                return create_plan(
                    goal_id=goal.id,
                    goal_description=goal.description,
                    action_type=action,
                    action_params={"reason": override_reason},
                )
            logger.info(
                f"[Planner] Saturation META goal {goal.id}: library full, "
                f"routing to FETCH"
            )
            return create_plan(
                goal_id=goal.id,
                goal_description=goal.description,
                action_type=action,
                action_params=action_params,
                metadata={"trigger": "saturation_meta_fetch"},
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

                    # Window guard: K8 may propose a learn-family action even
                    # when we're outside the learning window. Redirect to NOOP
                    # so the executor does not reject it downstream.
                    action, override_reason = self._enforce_learning_window(
                        goal, action, delib_action=delib_action,
                    )
                    if override_reason:
                        return create_plan(
                            goal_id=goal.id,
                            goal_description=goal.description,
                            action_type=action,
                            action_params={"reason": override_reason},
                        )

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

        # Fallback: LEARNING goals or META goal -> decide learn/exam/review.
        # Fetch handoff goals carry explicit file scope and must not be
        # displaced by generic exam/review candidates in the global snapshot.
        from agent_core.planner.goal_selector import is_fetch_handoff_goal
        if is_fetch_handoff_goal(goal):
            action = ActionType.LEARN
        else:
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

        file_ids = (
            goal.metadata.get("file_ids")
            or goal.metadata.get("fetched_file_ids")
        )
        if file_ids:
            action_params["resolved_file_ids"] = file_ids

        # ASK_EXPERT: add topic and source
        if action == ActionType.ASK_EXPERT:
            topic = self._pick_expert_topic()
            if topic:
                action_params["topic"] = topic
                action_params["source"] = "planner"

        # Window guard (defense in depth for non-K8 path).
        action, override_reason = self._enforce_learning_window(goal, action)
        if override_reason:
            return create_plan(
                goal_id=goal.id,
                goal_description=goal.description,
                action_type=action,
                action_params={"reason": override_reason},
            )

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

    def _enforce_learning_window(
        self,
        goal,
        action: ActionType,
        delib_action: Optional[Dict] = None,
    ) -> tuple:
        """Block learning-family actions outside the learning window.

        Returns (action, override_reason). override_reason is None when the
        original action is preserved; otherwise NOOP is returned along with
        the reason that will surface in plan.action_params.

        Bypasses:
            - goal.type.value == "user" (operator-driven)
            - goal.metadata["forced_action_type"] (explicit operator override)

        Side effect: abandons the K8 strategy tied to delib_action so the
        deliberation layer rethinks its plan next tick instead of re-issuing
        the same blocked step.
        """
        if action not in LEARNING_WINDOW_ACTIONS:
            return action, None
        try:
            if goal.type.value == "user":
                return action, None
        except AttributeError:
            return action, None
        if goal.metadata.get("forced_action_type"):
            return action, None
        try:
            from agent_core.environment.environment_model import is_learning_window
            if is_learning_window():
                return action, None
        except Exception:
            return action, None

        # 8b: off-window, allow a bounded number of learn-family actions per day
        # (rhythm/budget) rather than blocking every one. The window is now the
        # *preferred* time; the daily budget is the throttle. Only spend budget
        # when the current mode/health would actually let the action execute --
        # otherwise the degradation gate in _finalize_plan blocks it (REDUCED /
        # low health) and we would burn budget on a no-op.
        if (self._off_window_budget_remaining() > 0
                and self._heavy_action_mode_ok()):
            self._consume_off_window_budget()
            self._last_off_window_approved = True
            logger.info(
                f"[Planner] Goal {goal.id} action={action.value} allowed "
                f"off-window ({self._state.off_window_learn_used}/"
                f"{OFF_WINDOW_LEARN_BUDGET} off-window budget used today)"
            )
            return action, None

        if delib_action and self._deliberation:
            strategy_id = delib_action.get("strategy_id")
            if strategy_id:
                try:
                    self._deliberation.abandon_strategy(
                        strategy_id, reason="outside_learning_window",
                    )
                except Exception as e:
                    logger.debug(
                        f"[Planner] abandon_strategy failed for "
                        f"{strategy_id}: {e}"
                    )

        logger.info(
            f"[Planner] Goal {goal.id} action={action.value} redirected to "
            f"NOOP: outside_learning_window (off-window daily budget exhausted)"
        )
        return ActionType.NOOP, "outside_learning_window"

    @staticmethod
    def _berlin_date_key() -> str:
        """Today's date in Europe/Berlin (P3 #5).

        The off-window budget resets at the SAME midnight the learning window
        uses, so it stays consistent even if the OS timezone changes. It was
        naive time.localtime() before, which would drift from the Berlin-pinned
        window after an OS re-zone (the class of bug that caused #5).
        """
        from agent_core.environment.environment_model import berlin_now
        return berlin_now().strftime("%Y-%m-%d")

    def _off_window_budget_remaining(self) -> int:
        """Learn-family actions still allowed off-window today (8b).

        Resets at Berlin midnight. Irrelevant while the window is open (the
        window check short-circuits before the budget is ever consulted).
        """
        today = self._berlin_date_key()
        if self._state.off_window_learn_date != today:
            return OFF_WINDOW_LEARN_BUDGET
        return max(0, OFF_WINDOW_LEARN_BUDGET - self._state.off_window_learn_used)

    def _consume_off_window_budget(self) -> None:
        """Record one off-window learn-family action against today's budget (8b)."""
        today = self._berlin_date_key()
        if self._state.off_window_learn_date != today:
            self._state.off_window_learn_date = today
            self._state.off_window_learn_used = 0
        self._state.off_window_learn_used += 1

    def _heavy_action_mode_ok(self) -> bool:
        """True if the current mode/health would let a heavy LLM action run.

        Used by the 8b off-window budget so it is only spent on actions that
        will actually execute -- the degradation gate in _finalize_plan blocks
        heavy work in REDUCED / low health, and spending budget there would
        silently drain the daily allowance before an ACTIVE/SLEEP window.
        Defaults to True when no homeostasis core is wired (e.g. unit tests).
        """
        core = getattr(self, "_homeostasis_core", None)
        if core is None:
            return True
        try:
            st = core.get_state()
            allowed, _ = self.guard.is_heavy_action_allowed(
                st.mode.value, st.health_score
            )
            return allowed
        except Exception:
            return True

    def _decide_learning_action(
        self, snapshot: Optional[Dict], metrics: Dict
    ) -> ActionType:
        """
        Decide which learning action to take based on knowledge state.

        Priority logic:
        - P0: Outside learning window -> redirect to non-learning actions
        - P1: Files in "learning" status -> LEARN (continue partial)
        - P2: Files in "learned" status (ready for exam) -> EXAM
        - P2.5: Weak beliefs (confidence < 0.3) -> REVIEW weak topic
        - P3: New/unindexed files available -> LEARN (start new)
        - P4: Low retention -> REVIEW (spaced repetition)
        - P5: No materials left -> FETCH (get new content from web)
        - P6: Nothing to do -> NOOP
        """
        # P0: Outside learning window -> skip all learning, do other work
        try:
            from agent_core.environment.environment_model import is_learning_window
            if not is_learning_window():
                return self._decide_non_learning_action(metrics)
        except Exception:
            pass

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

        # P2.5: Weak beliefs - prioritize gap-filling over new content
        weak_file = self._find_weak_topic_file(snapshot)
        if weak_file:
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

    def _decide_non_learning_action(self, metrics: Dict) -> ActionType:
        """Pick a productive action when outside learning window.

        Instead of learn/exam/fetch, Maria does reflection and maintenance:
        creative, self_analyze, critique, evaluate, validate, experiment.
        """
        # Priority: creative > self_analyze > critique > evaluate > validate
        candidates = [
            ("creative", ActionType.CREATIVE),
            ("self_analyze", ActionType.SELF_ANALYZE),
            ("critique", ActionType.CRITIQUE),
            ("evaluate", ActionType.EVALUATE),
            ("validate", ActionType.VALIDATE),
        ]
        for name, action_type in candidates:
            if not self._is_action_rate_limited(name):
                return action_type

        # Everything rate-limited -> maintenance or NOOP
        return ActionType.NOOP

    def _find_weak_topic_file(self, snapshot: Optional[Dict]) -> Optional[str]:
        """
        Find a file associated with weak beliefs (confidence < 0.3).

        Checks world_model for low-confidence topics, then maps them to
        completed/hard_topic files in knowledge_index via topic_file_map.
        Rate-limited to 1 review per 2h to avoid infinite review loops.

        Returns:
            file_id string if a weak topic file is found, None otherwise.
        """
        if not getattr(self, "_world_model", None):
            return None
        if self._is_action_rate_limited("review"):
            return None

        try:
            gaps = self._world_model.query.get_knowledge_gaps()
            weak_topics = [
                g["topic"] for g in gaps
                if g.get("confidence", 1.0) < 0.3
            ]
            if not weak_topics:
                return None

            # Map topics to files via knowledge_analyzer
            topic_file_map = {}
            if getattr(self, "_knowledge_analyzer", None):
                topic_file_map = self._knowledge_analyzer.get_topic_file_map()

            # Also check hard_topic and completed files
            by_status = (snapshot or {}).get("files_by_status", {})
            reviewable = set()
            for f in by_status.get("hard_topic", []):
                reviewable.add(f.get("id", f.get("file", "")))
            for f in by_status.get("completed", []):
                reviewable.add(f.get("id", f.get("file", "")))

            # Find first weak topic that maps to a reviewable file
            for topic in weak_topics:
                mapped_files = topic_file_map.get(topic, [])
                for fid in mapped_files:
                    if fid in reviewable:
                        logger.info(
                            f"[PLANNER] P2.5: weak topic '{topic}' "
                            f"(file={fid}) prioritized over new content"
                        )
                        return fid

        except Exception as exc:
            logger.debug(f"[PLANNER] _find_weak_topic_file error: {exc}")

        return None

    def _pick_expert_topic(self) -> Optional[str]:
        """Pick a topic to ask the expert about, based on knowledge gaps.

        Skips topics that already have expert material in input/
        to avoid ask_expert loops on the same topic.
        """
        # K6: Use world model gaps
        if self._world_model:
            try:
                gaps = self._world_model.query.get_knowledge_gaps()
                for gap in gaps:
                    topic = gap.get("topic", "")
                    if topic and not self._has_expert_material(topic):
                        return topic
            except Exception:
                pass

        # Fallback: use topic suggester from web_source
        if self._knowledge_analyzer:
            try:
                topic_map = self._knowledge_analyzer.get_topic_file_map()
                for topic in topic_map:
                    if not self._has_expert_material(topic):
                        return topic
            except Exception:
                pass

        return None

    def _has_expert_material(self, topic: str) -> bool:
        """Check if expert material already exists for a topic in input/.

        Uses same path resolution as ExpertBridge (project root, not CWD)
        and same size threshold (>5000 bytes = substantial content).
        """
        import re
        slug = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")
        project_root = Path(__file__).resolve().parents[2]
        input_dir = project_root / "input"
        if not input_dir.exists():
            return False
        # Check both expert_<slug>.txt and web_wiki_<slug>.txt
        for name in (f"expert_{slug}.txt", f"web_wiki_{slug}.txt"):
            fpath = input_dir / name
            try:
                if fpath.exists() and fpath.stat().st_size > 5000:
                    return True
            except OSError:
                pass
        return False

    def _is_gap_learnable_goal(self, goal_id: Optional[str]) -> bool:
        """Check whether a goal represents a learnable topic (not meta-strategy).

        GapPlanner expects a concrete knowledge topic (e.g. 'fizyka'). Meta,
        MAINTENANCE, and creative capability_meta goals have prose descriptions
        like 'Zmiana mechanizmu uczenia' that are strategies, not topics.
        Feeding them into audit+gap pipeline produces absurd 'Maria nie ma
        wiedzy o Zmiana mechanizmu uczenia' bulletin entries.

        Returns:
            True if goal is LEARNING/USER (or cannot be resolved — allow by
            default to preserve legacy behavior when no store/goal exists).
        """
        if not goal_id or self._goal_store is None:
            return True  # Preserve legacy: no goal info -> allow
        try:
            goal = self._goal_store.get(goal_id)
        except Exception:
            return True
        if goal is None:
            return True
        # Compare by string to handle both enum and raw string goal_type fields
        gtype_raw = getattr(goal, "goal_type", None)
        gtype = getattr(gtype_raw, "value", gtype_raw)
        if not isinstance(gtype, str):
            return True
        gtype_lower = gtype.lower()
        # Block strategic / capability / maintenance goals from gap pipeline
        if gtype_lower in {"meta", "maintenance"}:
            return False
        if gtype_lower.startswith("capability"):
            return False
        return True

    def _post_need_material_if_missing(self) -> None:
        """Audit topic, plan gaps, post targeted needs to bulletin board.

        Gate 1 (goal type): meta / capability_meta / maintenance goals carry
        strategy descriptions, not learnable topics — skip gap pipeline for
        them to avoid template'd 'no knowledge of <strategy>' bulletins.
        """
        if not getattr(self, "_bulletin_store", None):
            return
        topic = self._get_current_goal_topic()
        if not topic:
            return
        goal_id = self._get_current_goal_id()
        if not self._is_gap_learnable_goal(goal_id):
            logger.debug(
                f"[GAP_PLANNER] Skipping non-learnable goal "
                f"(id={goal_id}, topic-desc={topic[:50]!r})"
            )
            return
        goal_desc = ""
        if self._current_trace:
            goal_desc = self._current_trace.goal_description or ""

        try:
            from agent_core.bulletin.bulletin_model import EntryType
            from agent_core.bulletin.gap_planner import GapAction

            # Phase 3: audit + gap plan -> targeted bulletin entries
            auditor = getattr(self, "_knowledge_auditor", None)
            gap_planner = getattr(self, "_gap_planner", None)

            if auditor and gap_planner:
                report = auditor.audit_topic(topic)
                if not report.has_gaps:
                    return  # Topic well-covered

                plan = gap_planner.plan_for_topic(report, goal_desc)

                # Warstwa 2 backstop: GapPlanner may return NO_ACTION for
                # prose topics that slipped past Warstwa 1. Don't create a
                # bulletin for those.
                if plan.action == GapAction.NO_ACTION:
                    logger.debug(
                        f"[GAP_PLANNER] NO_ACTION for '{topic[:60]}' "
                        f"(reason={plan.reason})"
                    )
                    return

                # Map GapAction to EntryType
                action_to_entry = {
                    GapAction.FETCH_MATERIAL: EntryType.NEED_MATERIAL,
                    GapAction.ASK_EXPERT: EntryType.NEED_MATERIAL,
                    GapAction.RUN_EXAM: EntryType.NEED_TEST,
                    GapAction.REVIEW: EntryType.NEED_REVIEW,
                    GapAction.DECOMPOSE: EntryType.WAITING_HUMAN,
                    GapAction.WAIT_HUMAN: EntryType.WAITING_HUMAN,
                }
                etype = action_to_entry.get(plan.action, EntryType.NEED_MATERIAL)

                metadata = plan.metadata or {}
                metadata["gap_plan"] = plan.to_dict()
                if plan.context_prompt:
                    metadata["context_prompt"] = plan.context_prompt

                self._bulletin_store.create_and_post(
                    entry_type=etype,
                    topic=topic,
                    reason_code=plan.reason,
                    summary=plan.context_prompt or plan.reason,
                    requested_by="gap_planner",
                    goal_id=goal_id,
                    priority=plan.priority,
                    metadata=metadata,
                )

                # For DECOMPOSE: also post sub-topic entries
                if plan.action == GapAction.DECOMPOSE:
                    for sub in plan.subtopics[:3]:
                        self._bulletin_store.create_and_post(
                            entry_type=EntryType.NEED_MATERIAL,
                            topic=sub,
                            reason_code="decomposed_subtopic",
                            summary=f"Podtemat z: {topic}",
                            requested_by="gap_planner",
                            goal_id=goal_id,
                            priority=plan.priority * 0.9,
                        )

                logger.info(
                    f"[GAP_PLANNER] {plan.action.value} for '{topic}' "
                    f"(reason={plan.reason}, priority={plan.priority:.2f})"
                )

            elif auditor:
                # Phase 2 fallback: audit without gap planner
                report = auditor.audit_topic(topic)
                if not report.has_gaps:
                    return
                for action in report.suggested_actions:
                    etype = {
                        "need_material": EntryType.NEED_MATERIAL,
                        "need_test": EntryType.NEED_TEST,
                        "need_review": EntryType.NEED_REVIEW,
                    }.get(action, EntryType.NEED_MATERIAL)
                    gap_desc = "; ".join(g.description for g in report.gaps[:3])
                    self._bulletin_store.create_and_post(
                        entry_type=etype, topic=topic,
                        reason_code=action,
                        summary=gap_desc or f"Audit: {action} for {topic}",
                        requested_by="auditor", goal_id=goal_id,
                        priority=min(report.worst_gap_severity, 0.9),
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

    # -- D2: K12 -> bulletin -> planner advisory ------------

    def _apply_bulletin_advisory(self, plan: Plan, trace) -> None:
        """Annotate plan/trace if bulletin flags this action as broken.

        Reads IMPROVEMENT entries posted by K12 (or other observers) whose
        ``metadata["action_hint"]`` matches the plan's action_type. The
        highest-priority match is recorded in plan.metadata and the trace
        but execution is NOT blocked at this stage (Phase 1 advisory).
        """
        if self._bulletin_store is None:
            return
        try:
            from agent_core.bulletin.bulletin_model import EntryType
        except Exception:
            return

        try:
            action_str = plan.action_type.value
        except AttributeError:
            return

        try:
            entries = self._bulletin_store.get_actionable()
        except Exception as e:
            logger.debug(f"[Planner] bulletin advisory read failed: {e}")
            return

        candidates = []
        for entry in entries:
            if entry.entry_type != EntryType.IMPROVEMENT:
                continue
            metadata = entry.metadata if isinstance(entry.metadata, dict) else {}
            hint = metadata.get("action_hint")
            if hint and hint == action_str:
                candidates.append(entry)

        if not candidates:
            return

        candidates.sort(key=lambda e: e.priority, reverse=True)
        top = candidates[0]
        top_meta = top.metadata if isinstance(top.metadata, dict) else {}

        plan.metadata["bulletin_advisory"] = {
            "entry_id": top.entry_id,
            "summary": (top.summary or "")[:120],
            "priority": top.priority,
            "match_count": len(candidates),
            "mode_aware": bool(top_meta.get("mode_aware")),
            "hour_bucket": top_meta.get("hour_bucket"),
        }
        if trace is not None:
            try:
                trace.add_step(
                    "bulletin", "advisory_match", "noted",
                    {
                        "entry_id": top.entry_id,
                        "topic": (top.topic or "")[:80],
                        "action": action_str,
                        "match_count": len(candidates),
                        "mode_aware": bool(top_meta.get("mode_aware")),
                    },
                )
            except Exception:
                pass
        # P1 fix: dedup advisory log per action_type per tick.
        # Plan metadata + trace step are still recorded (above) — we only
        # suppress the redundant log line emitted in the pivot loop.
        if action_str not in self._advisory_logged_this_tick:
            self._advisory_logged_this_tick.add(action_str)
            logger.info(
                f"[Planner] K12 advisory for {action_str}: "
                f"{(top.summary or '')[:80]}"
            )

    # -- D4 W3: mode-aware defer ---------------------------

    def _current_hour_bucket(self) -> str:
        """Wrapper for testability — patched in tests to control time."""
        try:
            from agent_core.self_analysis.mode_analyzer import _hour_bucket
            from datetime import datetime
            return _hour_bucket(datetime.now().hour)
        except Exception:
            return "unknown"

    def _apply_mode_aware_defer(self, plan: Plan, trace) -> None:
        """Soft-defer heavy actions when ModeAnalyzer flagged them for the
        current hour bucket (D4 W3).

        Triggered only when the bulletin advisory carries
        ``metadata["mode_aware"] = True`` and the current hour bucket
        matches the entry's ``hour_bucket``. The plan is rewritten to
        NOOP so the executor skips it; the original action_type is
        preserved in ``plan.action_params["deferred_action"]`` for
        observability.
        """
        adv = plan.metadata.get("bulletin_advisory") if isinstance(plan.metadata, dict) else None
        if not adv or not adv.get("mode_aware"):
            return

        target_bucket = adv.get("hour_bucket")
        if not target_bucket or target_bucket == "unknown":
            return

        current_bucket = self._current_hour_bucket()
        if current_bucket != target_bucket:
            return

        try:
            original_action = plan.action_type.value
        except AttributeError:
            return

        if original_action == ActionType.NOOP.value:
            return

        plan.action_type = ActionType.NOOP
        plan.action_params = {
            "reason": f"mode_aware_defer:{adv.get('entry_id', '?')}",
            "deferred_action": original_action,
            "hour_bucket": current_bucket,
        }
        if trace is not None:
            try:
                trace.add_step(
                    "mode_aware", "defer", "applied",
                    {
                        "entry_id": adv.get("entry_id"),
                        "deferred_action": original_action,
                        "hour_bucket": current_bucket,
                    },
                )
            except Exception:
                pass
        logger.info(
            f"[Planner] Mode-aware defer: {original_action} -> NOOP "
            f"(entry {adv.get('entry_id')}, bucket={current_bucket})"
        )

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

        # D2 (2026-04-26): K12 advisory layer. If bulletin holds an
        # IMPROVEMENT entry flagging this action_type as broken/suboptimal,
        # surface it via trace + plan metadata + log. Phase 1 is
        # advisory-only — does not block execution. Phase 2 (separate
        # D-task) may add penalty/skip semantics with operator override.
        self._apply_bulletin_advisory(plan, trace)

        # D4 W3 (2026-04-26): mode-aware defer. When the matched advisory
        # comes from ModeAnalyzer (mode_aware=True) and the entry's
        # hour_bucket matches the current bucket, soft-defer the action by
        # rewriting it to NOOP. The original action is preserved in
        # action_params["deferred_action"] for trace/diagnostic visibility.
        self._apply_mode_aware_defer(plan, trace)

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

                # Fallback 4: derive topic from file_ids (LEARN/EXAM/REVIEW actions).
                # Without this, K9 records topic='' for every learn, which
                # collapses topic-level confidence tracking.
                if not topic:
                    file_ids = plan.action_params.get("file_ids", []) or []
                    if file_ids:
                        # input_008_logika_formalna.txt -> "logika formalna"
                        # expert_fizyka.txt -> "fizyka"
                        # web_wiki_astrofizyka.txt -> "astrofizyka"
                        import re as _re
                        first = file_ids[0]
                        stem = first.replace(".txt", "").replace(".md", "")
                        # Strip known prefixes
                        for pref in ("input_", "expert_", "web_wiki_", "web_rss_"):
                            if stem.startswith(pref):
                                stem = stem[len(pref):]
                                break
                        # Strip leading digits_ pattern (e.g., "008_")
                        stem = _re.sub(r"^\d+_", "", stem)
                        # Replace underscores with spaces
                        topic = stem.replace("_", " ").strip()

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
        if result.get("success"):
            plan.status = PlanStatus.COMPLETED
        elif result.get("skipped"):
            # T-LEARN-003: a skipped action (outside window, no material) was
            # never attempted -- it is not a failure. Record it honestly so
            # self-analysis sensors don't count planner rest as a failed action.
            plan.status = PlanStatus.SKIPPED
        else:
            plan.status = PlanStatus.FAILED

        # v2 Phase A: track action success/failure for backoff
        if result.get("success"):
            self.record_action_success(plan.action_type.value, plan.goal_id)
        elif not result.get("skipped"):
            self.record_action_failure(plan.action_type.value, plan.goal_id)

        # v2 Phase B: feed execution result back to strategic planner
        if self._strategic_planner:
            self._strategic_planner.record_action(
                plan.action_type.value, plan.goal_id,
                success=result.get("success", False),
                duration_ms=plan.duration_ms,
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

        # Reset idle streak only for actions that produce real work.
        # Reflection actions (creative, self_analyze, critique, evaluate, validate)
        # outside learning window are "thinking in circles" and should NOT
        # prevent Maria from entering SLEEP mode.
        _productive_actions = {
            ActionType.LEARN, ActionType.EXAM, ActionType.REVIEW,
            ActionType.FETCH, ActionType.ASK_EXPERT, ActionType.MAINTENANCE,
            ActionType.EXPERIMENT, ActionType.EFFECTOR,
        }
        if plan.action_type in _productive_actions and self._homeostasis_core:
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

        # K6: Rebuild beliefs after plan execution (throttled).
        self._maybe_rebuild_beliefs(plan, result)

        # Belief Store v2: maintenance after EVALUATE (~1/hour)
        # Runs: decay -> dedup -> prune -> compact. semantic_memory enables
        # the SEMANTIC dedup phase (flag-gated, SEMANTIC_DEDUP_ENABLED) --
        # before 2026-06-10 maintain() was always called bare, so embedding
        # dedup never ran in production despite being fully implemented.
        if (plan.action_type == ActionType.EVALUATE
                and result.get("success")
                and self._world_model):
            try:
                self._world_model.maintain(semantic_memory=self._semantic_memory)
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

        # Track consecutive NOOPs for backoff
        if plan.action_type == ActionType.NOOP:
            self._state.consecutive_noop_count += 1
        else:
            self._state.consecutive_noop_count = 0

        # Non-productive loop detection: same goal + same reflection action
        # repeated N times. COMPLETED evaluates/critiques on an undecomposable
        # meta-goal don't trigger stuck_history (below) — this catches them.
        self._track_nonproductive_repeat(plan)
        self._track_goal_cycle(plan, plan.result or {})

        # Stuck detection: track repeated failures on the same goal+action
        if plan.status == PlanStatus.FAILED and plan.goal_id:
            error_reason = (
                (plan.result or {}).get("error", "")
                or (plan.result or {}).get("reason", "")
            )
            fingerprint = {
                "action": plan.action_type.value,
                "goal_id": plan.goal_id,
                "reason": str(error_reason)[:100],
            }
            self._state.stuck_history.append(fingerprint)
            if len(self._state.stuck_history) > STUCK_HISTORY_SIZE:
                self._state.stuck_history = self._state.stuck_history[-STUCK_HISTORY_SIZE:]

            recent = self._state.stuck_history[-STUCK_THRESHOLD:]
            if len(recent) == STUCK_THRESHOLD and all(
                r["action"] == fingerprint["action"]
                and r["goal_id"] == fingerprint["goal_id"]
                and r["reason"] == fingerprint["reason"]
                for r in recent
            ):
                self._handle_stuck(plan, fingerprint, STUCK_THRESHOLD)
        elif plan.status == PlanStatus.COMPLETED:
            # Success clears stuck history (cycle is working)
            self._state.stuck_history.clear()

        # Persist (with message)
        self._log_decision(plan)
        self._save_state()

        # Keep bounded in-memory history
        self._last_plans.append(plan)
        if len(self._last_plans) > MAX_HISTORY_SIZE:
            self._last_plans = self._last_plans[-50:]

        clear_episode_id()
        return plan

    # -- Internal: stale goal cleanup -------------------------

    # Per-type stale threshold. K12/critic mass-produce LEARNING goals and
    # K13/creative mass-produces META goals — they decay faster than USER
    # goals (which represent explicit operator intent).
    _STALE_THRESHOLDS_SEC = {
        "learning": 3 * 24 * 3600,    # 3d: mostly k12/critic auto-created
        "meta": 5 * 24 * 3600,        # 5d: creative meta-goals
        "user": 14 * 24 * 3600,       # 14d: operator-requested
        "maintenance": 30 * 24 * 3600,  # 30d: system goals
    }
    _STALE_DEFAULT_SEC = 7 * 24 * 3600
    # Plank 3: an ACTIVE learning goal that never makes progress wedges --
    # Plank 1 promotes goals into ACTIVE, which the PENDING-only net above
    # can't reap, and the goal-cycle detector only cools-down/escalates,
    # never terminates. Reap zero-progress ACTIVE learning goals past this
    # (longer) threshold; goals with ANY progress are spared -- they are
    # still working toward completion (reactivation over the trash heap).
    _ACTIVE_STUCK_SEC = 7 * 24 * 3600
    # P3 (#4): fetch_handoff goals point at real downloaded bytes on disk,
    # unlike the k12/critic auto-goals the 3d learning threshold was tuned for.
    # Give them a 30d window (matches maintenance) before abandoning -- the live
    # handoff cleared the old 3d PENDING reaper by only 2.5h, so 3d demonstrably
    # orphans real material under any learning delay. Applied to BOTH the PENDING
    # and the ACTIVE-stuck branch: Plank 1 promotes handoffs to ACTIVE early, so
    # a handoff spends most of its life ACTIVE -- exempting only PENDING would
    # leave the hole exactly where the goal lives.
    _FETCH_HANDOFF_STALE_SEC = 30 * 24 * 3600

    def _cleanup_stale_goals(self) -> None:
        """Auto-abandon goals that are PENDING past their per-type threshold.

        Safety net against goals that can never be fulfilled (e.g. camera
        commands parsed as learning goals, abstract meta-goals without
        decomposition, actions without completion logic).
        Runs once per cycle - lightweight (iterates active goals only).
        """
        if self._goal_store is None:
            return

        now = time.time()
        from agent_core.goals.goal_model import GoalStatus, GoalType

        stale_count = 0
        for goal in self._goal_store.get_active():
            is_fetch_handoff = goal.metadata.get("source") == "fetch_handoff"
            threshold = self._STALE_THRESHOLDS_SEC.get(
                goal.type.value, self._STALE_DEFAULT_SEC,
            )
            if is_fetch_handoff:
                threshold = self._FETCH_HANDOFF_STALE_SEC
            age_sec = now - goal.created_at
            if (age_sec > threshold
                    and goal.progress <= 0.0
                    and goal.status == GoalStatus.PENDING):
                logger.warning(
                    f"Planner: auto-abandoning stale {goal.type.value} goal "
                    f"{goal.id} ({goal.description[:50]}) - pending "
                    f"{age_sec / 3600:.0f}h with no progress "
                    f"(threshold {threshold / 3600:.0f}h)"
                )
                self._goal_store.update_status(
                    goal.id, GoalStatus.ABANDONED,
                    reason=(
                        f"stale: pending {age_sec / 3600:.0f}h "
                        f"with no progress"
                    ),
                    actor="planner_stale_cleanup",
                )
                stale_count += 1
            elif (goal.status == GoalStatus.ACTIVE
                    and goal.type == GoalType.LEARNING
                    and goal.progress <= 0.0
                    and age_sec > (self._FETCH_HANDOFF_STALE_SEC
                                   if is_fetch_handoff
                                   else self._ACTIVE_STUCK_SEC)):
                # Plank 3: a learning goal the planner activated but that never
                # moved -- the goal-cycle detector cooled it down and escalated
                # to K12, but nothing ever terminated it. Reap it so the active
                # set stays healthy (else MAX_ACTIVE_GOALS silently fills with
                # un-completable goals and blocks new ones).
                logger.warning(
                    f"Planner: auto-abandoning wedged ACTIVE learning goal "
                    f"{goal.id} ({goal.description[:50]}) - active "
                    f"{age_sec / 3600:.0f}h with no progress"
                )
                self._goal_store.update_status(
                    goal.id, GoalStatus.ABANDONED,
                    reason=(
                        f"active goal stuck: no progress in "
                        f"{age_sec / 3600:.0f}h"
                    ),
                    actor="planner_active_stuck_cleanup",
                )
                self._state.actions_since_progress.pop(goal.id, None)
                self._state.stuck_cooldowns.pop(goal.id, None)
                stale_count += 1

        if stale_count > 0:
            self._goal_store.save()
            logger.info(
                "Planner stale cleanup: abandoned %d goals this cycle",
                stale_count,
            )

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

        # Authority level is read STRUCTURALLY from the check; the reason-string
        # parse is only a defensive fallback. The BOUNDED escalate reason carried
        # no "authority_level=" token, so the old parse-only path silently missed
        # it -> the dangerous-tool request fell through to a plain block and never
        # reached the approval queue (audit 2026-06-01 #4).
        authority_level = getattr(check, "authority_level", "") or ""
        if not authority_level:
            reasons = check.blocked_result.get("reasons", []) if check.blocked_result else []
            for r in reasons:
                if "authority_level=" in r:
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

        else:
            # Any other escalating level -- confirm, bounded, or an
            # unrecognized elevated level -- needs operator approval. This
            # handler runs ONLY for effector ESCALATE decisions, so an
            # escalation must never silently fall through to a plain block;
            # route it to the approval queue (safe HITL default).
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

        # K7: Validate even approved effectors through autonomy policy.
        # `already_approved=True` short-circuits the authority-level rule
        # (operator already consented via ApprovalQueue) but keeps all
        # other rules active — mode/health restrictions and consecutive
        # failure breakers still apply.
        if self._autonomy_policy:
            check = self._autonomy_policy.check(
                action_type="effector",
                action_params=plan.action_params,
                goal_id=plan.goal_id,
                already_approved=True,
            )
            if not check.allowed:
                plan.status = PlanStatus.FAILED
                plan.result = check.blocked_result or {
                    "success": False,
                    "error": f"K7 blocked approved effector: {check.reasons}",
                }
                if trace:
                    trace.add_step("k7", "blocked_approved", "rejected", {
                        "reasons": check.reasons,
                    })
                    trace.finalize(success=False, result_summary="k7_blocked_approved")
                    self._save_trace(trace)
                self._log_decision(plan)
                return plan

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
        if result.get("success"):
            plan.status = PlanStatus.COMPLETED
        elif result.get("skipped"):
            # T-LEARN-003: a skipped action (outside window, no material) was
            # never attempted -- it is not a failure. Record it honestly so
            # self-analysis sensors don't count planner rest as a failed action.
            plan.status = PlanStatus.SKIPPED
        else:
            plan.status = PlanStatus.FAILED

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

    def _handle_stuck(self, plan: Plan, fingerprint: dict, count: int) -> None:
        """Handle detected stuck loop: diagnose -> repair -> escalate."""
        goal_id = fingerprint["goal_id"]
        action = fingerprint["action"]
        reason = fingerprint["reason"]

        # Level 4: Diagnose
        fingerprint_with_goal = {**fingerprint, "goal_id": goal_id}
        diagnosis = self._stuck_handler.diagnose(
            fingerprint_with_goal, plan.result or {},
        )

        # Level 5: Try self-repair
        diagnosis = self._stuck_handler.try_repair(diagnosis)

        logger.warning(
            "[STUCK] %s on goal %s failed %d times. "
            "Cause: %s. Repair: %s (%s). Cooldown %d min.",
            action, goal_id, count,
            diagnosis.cause.value,
            diagnosis.repair_action.value,
            "OK" if diagnosis.repair_succeeded else "FAILED",
            STUCK_COOLDOWN_SEC // 60,
        )

        # Cooldown goal (even if repair succeeded - give system breathing room)
        cooldown_until = time.time() + STUCK_COOLDOWN_SEC
        self._state.stuck_cooldowns[goal_id] = cooldown_until

        # Level 6: Telegram alert with diagnosis context
        if self._telegram_notifier:
            try:
                message = self._stuck_handler.format_escalation(
                    diagnosis, fingerprint, count,
                    cooldown_minutes=STUCK_COOLDOWN_SEC // 60,
                )
                self._telegram_notifier.notify_stuck(message)
            except Exception:
                pass

        # Clear history to avoid re-triggering immediately
        self._state.stuck_history.clear()

    # Reflection actions that don't move goals forward on their own. Repeating
    # the same one on the same goal forever == loop, not progress.
    _NONPRODUCTIVE_ACTIONS = frozenset([
        ActionType.EVALUATE, ActionType.CRITIQUE, ActionType.VALIDATE,
        ActionType.SELF_ANALYZE, ActionType.CREATIVE,
    ])

    def _plan_made_progress(self, plan: Plan, result: Dict[str, Any]) -> bool:
        """T-B4-001: did this plan execution move its goal forward?"""
        if not result.get("success"):
            return False
        if result.get("skipped"):
            return False
        action = plan.action_type
        if action == ActionType.LEARN:
            return result.get("chunks_learned", 0) > 0
        if action == ActionType.EXAM:
            return result.get("exams_passed", 0) > 0
        if action == ActionType.REVIEW:
            return result.get("reviews_done", 0) > 0
        return True

    def _track_goal_cycle(self, plan: Plan, result: Dict[str, Any]) -> None:
        """T-B4-001: increment per-goal cycle counter; escalate at threshold."""
        goal_id = plan.goal_id
        if not goal_id:
            return

        if self._plan_made_progress(plan, result):
            self._state.actions_since_progress.pop(goal_id, None)
            return

        count = self._state.actions_since_progress.get(goal_id, 0) + 1
        self._state.actions_since_progress[goal_id] = count

        if count >= GOAL_CYCLE_THRESHOLD:
            self._escalate_goal_cycle(goal_id, count)
            self._state.actions_since_progress.pop(goal_id, None)

    def _escalate_goal_cycle(self, goal_id: str, count: int) -> None:
        """T-B4-001: cooldown + K12 IMPROVEMENT bulletin for exhausted cycle."""
        self._state.stuck_cooldowns[goal_id] = time.time() + STUCK_COOLDOWN_SEC

        goal_desc = ""
        if self._goal_store:
            try:
                goal = self._goal_store.get(goal_id)
                if goal:
                    goal_desc = (goal.description or "")[:120]
            except Exception as exc:
                logger.debug("[Planner] goal lookup for cycle escalation: %s", exc)

        if self._bulletin_store is not None:
            try:
                from agent_core.bulletin.bulletin_model import (
                    BulletinEntry,
                    EntryStatus,
                    EntryType,
                )

                topic = goal_desc or goal_id[:24]
                entry = BulletinEntry(
                    entry_id=f"cbb-goal-cycle-{goal_id[:12]}-{int(time.time())}",
                    goal_id=goal_id,
                    entry_type=EntryType.IMPROVEMENT,
                    priority=0.85,
                    status=EntryStatus.OPEN,
                    topic=topic[:120],
                    reason_code="goal_exhausted_cycle",
                    summary=(
                        f"Cel '{topic[:60]}' nie poczynil postepu w {count} "
                        "probach. K12 powinno przeanalizowac."
                    ),
                    requested_by="planner_goal_cycle_detector",
                    metadata={
                        "category": "goal_exhausted_cycle",
                        "goal_id": goal_id,
                        "actions_attempted": count,
                        "threshold": GOAL_CYCLE_THRESHOLD,
                        "action_hint": "self_analyze",
                    },
                )
                self._bulletin_store.post(entry)
            except Exception as exc:
                logger.warning(
                    "[Planner] failed to post goal_exhausted bulletin: %s", exc,
                )

        logger.warning(
            "[Planner] Goal %s exhausted after %d cycles without progress - "
            "posted IMPROVEMENT bulletin",
            goal_id[:12], count,
        )

    def _track_nonproductive_repeat(self, plan: Plan) -> None:
        """Abandon goal when a reflection action repeats N times without progress.

        Productive actions (LEARN/EXAM/FETCH/...) naturally repeat — we only
        track reflection actions that can't change goal state.
        """
        if not plan.goal_id or plan.action_type not in self._NONPRODUCTIVE_ACTIONS:
            self._state.last_goal_action_key = None
            self._state.goal_action_repeat_count = 0
            return

        key = f"{plan.goal_id}:{plan.action_type.value}"
        if key == self._state.last_goal_action_key:
            self._state.goal_action_repeat_count += 1
        else:
            self._state.last_goal_action_key = key
            self._state.goal_action_repeat_count = 1

        if self._state.goal_action_repeat_count >= NONPRODUCTIVE_REPEAT_THRESHOLD:
            self._abandon_nonproductive_goal(
                plan.goal_id, plan.action_type.value,
                self._state.goal_action_repeat_count,
            )
            self._state.last_goal_action_key = None
            self._state.goal_action_repeat_count = 0

    def _abandon_nonproductive_goal(
        self, goal_id: str, action: str, count: int,
    ) -> None:
        """Abandon a goal stuck in a non-productive reflection loop."""
        if self._goal_store is None:
            return
        from agent_core.goals.goal_model import GoalStatus
        reason = (
            f"non-productive loop: {count} consecutive {action} "
            f"actions without progress"
        )
        try:
            updated = self._goal_store.update_status(
                goal_id, GoalStatus.ABANDONED, reason=reason,
                actor="planner_nonproductive_detector",
            )
            if updated:
                self._goal_store.save()
                logger.warning(
                    "[Planner] Abandoned goal %s after %d consecutive %s "
                    "actions without progress", goal_id[:12], count, action,
                )
        except Exception as e:
            logger.warning(
                "Failed to abandon non-productive goal %s: %s", goal_id, e,
            )

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

    # -- Internal: K6 throttled belief rebuild -------------------

    _BELIEF_BUILD_COOLDOWN_SEC: float = 3600.0

    def _maybe_rebuild_beliefs(self, plan: Plan, result: Dict[str, Any]) -> None:
        """Rebuild beliefs after successful LEARN always; after EVALUATE
        only once per cooldown window.

        The builder enumerates every concept in longterm memory (~22k),
        which is then pruned to cap=2000. Running this every EVALUATE
        burned CPU on build->prune cycles for zero progress (observed
        ~19.8k supersedes/minute on 2026-04-17). LEARN still triggers
        unconditionally because it reflects real new knowledge.
        """
        if not (result.get("success") and self._world_model):
            return
        if plan.action_type == ActionType.LEARN:
            pass  # always rebuild
        elif plan.action_type == ActionType.EVALUATE:
            elapsed = time.time() - self._state.last_belief_build_ts
            if elapsed < self._BELIEF_BUILD_COOLDOWN_SEC:
                return
        else:
            return

        try:
            stats = self._world_model.build()
            self._world_model.save()
            self._state.last_belief_build_ts = time.time()
            if stats and any(stats.values()):
                logger.info(
                    f"[K6] Beliefs rebuilt after {plan.action_type.value}: "
                    f"+{stats.get('topics',0)} topics, "
                    f"+{stats.get('files',0)} files, "
                    f"+{stats.get('concepts',0)} concepts"
                )
        except Exception as e:
            # Historical bug: silent swallow hid AttributeError
            # (build_all vs build) for a full month. Log now so regressions
            # surface immediately.
            logger.warning(f"[K6] build/save failed after {plan.action_type.value}: {e}")

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
