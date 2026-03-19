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

logger = logging.getLogger(__name__)

# Default paths
_META_DIR = Path(__file__).resolve().parents[2] / "meta_data"
_DEFAULT_STATE_PATH = _META_DIR / "planner_state.json"
_DEFAULT_DECISIONS_PATH = _META_DIR / "planner_decisions.jsonl"

# Frequency constants
ROUTINE_INTERVAL_TICKS = 60         # Normal cycle every 60 ticks (60s)
EVALUATION_INTERVAL_SEC = 3600      # Trigger K4 report every 1h
RECOMMENDATION_COOLDOWN_SEC = 900   # 15 min cooldown on eval recommendations

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

    def set_autonomy_policy(self, policy) -> None:
        self._autonomy_policy = policy

    def set_deliberation(self, deliberation) -> None:
        self._deliberation = deliberation

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

        # -- STEP 1: GUARD --
        can_plan, block_reasons = self._check_guard()
        if not can_plan:
            logger.debug(f"Planner cycle skipped: {block_reasons}")
            self._emit_cycle_complete(tick_count, guard_blocked=True,
                                      block_reasons=block_reasons)
            self._log_skip(tick_count, "guard_blocked", block_reasons)
            self._save_state()
            return None

        # -- STEP 2: PERCEIVE --
        context = self._gather_context()

        # -- STEP 3: SELECT GOAL (learning/exam/review first) --
        goal = self._select_goal(context)
        if goal is None:
            # Try to auto-create a learning goal with topic selection
            created = self._auto_create_learning_goal(context)
            if created:
                goal = self._select_goal(context)

        if goal is not None:
            # -- STEP 4: CREATE PLAN for goal --
            plan = self._create_plan_for_goal(goal, context)
            return self._finalize_plan(plan)

        # -- STEP 5: EVALUATE as fallback (no actionable goals) --
        plan = self._maybe_evaluate(context)
        if plan is not None:
            return self._finalize_plan(plan)

        # Nothing to do
        logger.debug("Planner: no feasible goal and no evaluation needed")
        self._emit_cycle_complete(tick_count, no_goals=True)
        self._log_skip(tick_count, "no_goals", [])
        self._save_state()
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

        # P2: Exam ready
        if by_status.get("learned"):
            return ActionType.EXAM

        # P3: New files (indexed "new" status OR unindexed files in input/)
        if snapshot.get("new_files_available"):
            return ActionType.LEARN

        # P4: Review (check retention)
        retention = metrics.get("retention_rate", 1.0)
        if retention < 0.8:
            return ActionType.REVIEW

        # P5: All learned, fetch new content
        if by_status.get("completed"):
            return ActionType.FETCH

        return ActionType.NOOP

    # -- Internal: finalize and persist ---------------------

    def _finalize_plan(self, plan: Plan) -> Plan:
        """Execute plan, emit event, log, save state."""
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
                plan.status = PlanStatus.FAILED
                plan.result = check.blocked_result or {
                    "success": False, "blocked_by": "autonomy_policy"
                }
                plan.message = self._format_message(plan)
                self._state.total_plans_executed += 1
                self._emit_cycle_complete(
                    self._state.last_cycle_tick, plan=plan,
                )
                self._log_decision(plan)
                self._save_state()
                return plan

        plan.status = PlanStatus.EXECUTING
        start = time.time()

        result = self.executor.execute(plan)

        plan.result = result
        plan.duration_ms = (time.time() - start) * 1000
        plan.status = (
            PlanStatus.COMPLETED if result.get("success") else PlanStatus.FAILED
        )

        # K7: Record outcome for consecutive failure tracking + rate limiting
        if self._autonomy_policy:
            self._autonomy_policy.record_execution(
                plan.action_type.value, result.get("success", False)
            )

        # K8: Report step outcome back to deliberation
        if self._deliberation and plan.metadata.get("strategy_id"):
            outcome = "pass" if result.get("success") else "fail"
            self._deliberation.report_step_outcome(
                plan.metadata["strategy_id"], outcome, result
            )

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

        # Generate human-readable message and attach to plan
        plan.message = self._format_message(plan)

        self._state.total_plans_executed += 1
        self._state.current_plan_id = plan.plan_id

        # Emit perception events
        self._emit_decision_event(plan)
        self._emit_cycle_complete(
            self._state.last_cycle_tick, plan=plan,
        )

        # Persist (with message)
        self._log_decision(plan)
        self._save_state()

        # Keep bounded in-memory history
        self._last_plans.append(plan)
        if len(self._last_plans) > MAX_HISTORY_SIZE:
            self._last_plans = self._last_plans[-50:]

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
