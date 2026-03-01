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

    def set_sandbox_manager(self, manager) -> None:
        self._sandbox_manager = manager

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
        if ticks_since >= ROUTINE_INTERVAL_TICKS:
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
            self._save_state()
            return None

        # -- STEP 2: PERCEIVE --
        context = self._gather_context()

        # -- STEP 3: CHECK if evaluation needed --
        plan = self._maybe_evaluate(context)
        if plan is not None:
            return self._finalize_plan(plan)

        # -- STEP 4: SELECT GOAL --
        goal = self._select_goal(context)
        if goal is None:
            logger.debug("Planner: no feasible goal found")
            self._save_state()
            return None

        # -- STEP 5: CREATE PLAN --
        plan = self._create_plan_for_goal(goal, context)

        # -- STEP 6: EXECUTE --
        return self._finalize_plan(plan)

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

        return context

    # -- Internal: periodic evaluation ----------------------

    def _maybe_evaluate(self, context: Dict) -> Optional[Plan]:
        """Check if it's time for a periodic evaluation report."""
        now = time.time()
        since_eval = now - self._state.last_evaluation_ts

        if since_eval >= EVALUATION_INTERVAL_SEC:
            self._state.last_evaluation_ts = now
            return create_plan(
                goal_id=None,
                goal_description="Periodic evaluation report",
                action_type=ActionType.EVALUATE,
                action_params={"period_hours": 1.0},
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

        # LEARNING goals or META goal -> decide learn/exam/review
        action = self._decide_learning_action(snapshot, metrics)
        return create_plan(
            goal_id=goal.id,
            goal_description=goal.description,
            action_type=action,
            action_params={},
        )

    def _decide_learning_action(
        self, snapshot: Optional[Dict], metrics: Dict
    ) -> ActionType:
        """
        Decide which learning action to take based on knowledge state.

        Mirrors Teacher P1-P6 priority logic but at planner level:
        - Files in "learning" status -> LEARN (continue partial)
        - Files in "learned" status (ready for exam) -> EXAM
        - New files available -> LEARN (start new)
        - Low retention -> REVIEW (spaced repetition)
        - Otherwise -> NOOP
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

        # P3: New files
        if snapshot.get("new_files_available"):
            return ActionType.LEARN

        # P4: Review (check retention)
        retention = metrics.get("retention_rate", 1.0)
        if retention < 0.8:
            return ActionType.REVIEW

        return ActionType.NOOP

    # -- Internal: finalize and persist ---------------------

    def _finalize_plan(self, plan: Plan) -> Plan:
        """Execute plan, emit event, log, save state."""
        plan.status = PlanStatus.EXECUTING
        start = time.time()

        result = self.executor.execute(plan)

        plan.result = result
        plan.duration_ms = (time.time() - start) * 1000
        plan.status = (
            PlanStatus.COMPLETED if result.get("success") else PlanStatus.FAILED
        )

        self._state.total_plans_executed += 1
        self._state.current_plan_id = plan.plan_id

        # Emit perception event
        self._emit_decision_event(plan)

        # Persist
        self._log_decision(plan)
        self._save_state()

        # Keep bounded in-memory history
        self._last_plans.append(plan)
        if len(self._last_plans) > MAX_HISTORY_SIZE:
            self._last_plans = self._last_plans[-50:]

        return plan

    def _emit_decision_event(self, plan: Plan) -> None:
        """Push a planner_decision PerceptionEvent."""
        if self._homeostasis_core is None:
            return

        try:
            from agent_core.perception.event import (
                PerceptionSource, create_event,
            )

            event = create_event(
                source=PerceptionSource.PLANNER,
                event_type="planner_decision",
                payload={
                    "plan_id": plan.plan_id,
                    "goal_id": plan.goal_id,
                    "action_type": plan.action_type.value,
                    "status": plan.status.value,
                    "success": plan.result.get("success", False),
                },
                priority=0.5,
            )
            self._homeostasis_core.push_external_event(event)
        except Exception as e:
            logger.debug(f"Could not emit planner event: {e}")

    # -- Persistence ----------------------------------------

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
