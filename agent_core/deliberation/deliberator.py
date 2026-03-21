"""
Deliberator for K8 Deliberation.

Core logic: selects and advances strategies for goals.
Called by PlannerCore to get the next action from a multi-step plan.

v1: rule-based template selection (zero LLM, ADR-013).
v2 path: LLM-based select_strategy() with richer context.

Kontrakt: docs/CONTRACTS.md - Kontrakt 8: Deliberation
"""

import logging
import time
from typing import Any, Dict, List, Optional

from agent_core.deliberation.intent_tracker import IntentTracker
from agent_core.deliberation.strategy import (
    Step,
    StepOutcome,
    StepStatus,
    Strategy,
    StrategyStatus,
)
from agent_core.deliberation.strategy_templates import (
    TEMPLATE_REGISTRY,
    get_template,
    list_templates,
)

logger = logging.getLogger(__name__)


class Deliberator:
    """
    Selects and advances multi-step strategies for goals.

    Pipeline:
    1. get_next_action(goal_id, context) -> action dict or None
       - If active strategy exists -> advance it
       - If no strategy -> select_strategy() from context
       - If no template matches -> return None (fallback to planner)
    2. report_step_outcome(strategy_id, outcome) -> advance/fail strategy

    v1: rule-based template selection.
    v2 path: LLM select_strategy(), expression-based conditions.
    """

    # Max strategies kept in memory per goal (prevent unbounded growth)
    MAX_STRATEGIES_PER_GOAL = 5
    # Max total active strategies
    MAX_ACTIVE_STRATEGIES = 10

    def __init__(self, intent_tracker: Optional[IntentTracker] = None):
        self._strategies: Dict[str, Strategy] = {}  # strategy_id -> Strategy
        self._goal_strategies: Dict[str, List[str]] = {}  # goal_id -> [strategy_ids]
        self._intent_tracker = intent_tracker or IntentTracker()

    # -- Public API --

    def get_next_action(
        self,
        goal_id: str,
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Get next action for a goal from its strategy.

        Returns action dict compatible with PlannerCore:
            {"action_type": str, "action_params": dict, "strategy_id": str, "step_description": str}
        Or None if no strategy / strategy is terminal.

        Context keys (v1):
            - intent: str (what the goal wants)
            - topic: str (optional, for learn/consolidate)
            - new_files_available: bool
            - weak_topics: list[str]
            - knowledge_snapshot: dict
        """
        # 1. Check for active strategy
        strategy = self._get_active_strategy(goal_id)

        # 2. If no active strategy, try to select one
        if strategy is None:
            strategy = self._select_strategy(goal_id, context)
            if strategy is None:
                return None

        # 3. Get current step
        step = strategy.current_step
        if step is None or strategy.is_terminal:
            return None

        # 4. Activate step if pending
        if step.status == StepStatus.PENDING:
            step.status = StepStatus.ACTIVE
            strategy.updated_at = time.time()

        return {
            "action_type": step.action_type,
            "action_params": step.action_params,
            "strategy_id": strategy.strategy_id,
            "step_description": step.description,
            "step_order": step.order,
            "strategy_intent": strategy.intent,
        }

    def report_step_outcome(
        self,
        strategy_id: str,
        outcome: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Report outcome of current step execution.

        outcome: "pass", "fail", "timeout"
        Returns: new status string ("active", "completed", "abandoned") or None if not found.
        """
        strategy = self._strategies.get(strategy_id)
        if strategy is None or strategy.is_terminal:
            return None

        step = strategy.current_step
        if step is None:
            return None

        step.result = result or {}
        step.completed_at = time.time()
        strategy.updated_at = time.time()

        step_outcome = StepOutcome(outcome) if outcome in [e.value for e in StepOutcome] else StepOutcome.FAIL

        if step_outcome == StepOutcome.PASS or step_outcome == StepOutcome.ANY:
            return self._advance_on_success(strategy, step)
        elif step_outcome == StepOutcome.FAIL:
            return self._advance_on_failure(strategy, step)
        elif step_outcome == StepOutcome.TIMEOUT:
            return self._advance_on_failure(strategy, step)

        return strategy.status.value

    def get_strategy(self, strategy_id: str) -> Optional[Strategy]:
        """Get a strategy by ID."""
        return self._strategies.get(strategy_id)

    def get_active_strategy_for_goal(self, goal_id: str) -> Optional[Strategy]:
        """Get active strategy for a goal (if any)."""
        return self._get_active_strategy(goal_id)

    def get_all_strategies(self) -> List[Strategy]:
        """Get all tracked strategies."""
        return list(self._strategies.values())

    def abandon_strategy(self, strategy_id: str, reason: str = "") -> bool:
        """Manually abandon a strategy."""
        strategy = self._strategies.get(strategy_id)
        if strategy is None or strategy.is_terminal:
            return False
        strategy.status = StrategyStatus.ABANDONED
        strategy.updated_at = time.time()
        strategy.metadata["abandon_reason"] = reason
        self._intent_tracker.update_outcome(strategy_id, "abandoned")
        logger.info("Strategy %s abandoned: %s", strategy_id, reason)
        return True

    def get_status(self) -> Dict[str, Any]:
        """Status dict for REPL / Web UI."""
        active = [s for s in self._strategies.values() if s.status == StrategyStatus.ACTIVE]
        return {
            "total_strategies": len(self._strategies),
            "active_strategies": len(active),
            "active_details": [
                {
                    "strategy_id": s.strategy_id,
                    "goal_id": s.goal_id,
                    "template": s.template_name,
                    "progress": round(s.progress, 2),
                    "current_step": s.current_step.description if s.current_step else "---",
                    "intent": s.intent,
                }
                for s in active
            ],
            "templates_available": list_templates(),
            "recent_intents": [
                r.to_dict() for r in self._intent_tracker.query_recent(5)
            ],
        }

    # -- Strategy selection (v1: rule-based) --

    def _select_strategy(
        self,
        goal_id: str,
        context: Dict[str, Any],
    ) -> Optional[Strategy]:
        """
        Select a strategy template based on context.

        v1: simple rules matching context keys to templates.
        v2 path: LLM-based selection with richer context.
        """
        # Check active strategy limit
        active_count = sum(
            1 for s in self._strategies.values()
            if s.status == StrategyStatus.ACTIVE
        )
        if active_count >= self.MAX_ACTIVE_STRATEGIES:
            logger.warning("Max active strategies reached (%d), skipping", active_count)
            return None

        template_name = self._match_template(goal_id, context)
        if template_name is None:
            return None

        template_fn = get_template(template_name)
        if template_fn is None:
            return None

        # Build strategy from template
        intent = context.get("intent", "")
        topic = context.get("topic", "")

        # If explore_new was chosen because of weak topics, pass first weak topic
        if template_name == "explore_new" and not topic:
            weak_topics = context.get("weak_topics", [])
            if weak_topics:
                topic = weak_topics[0]

        strategy = template_fn(goal_id=goal_id, intent=intent, topic=topic)

        # Register
        self._strategies[strategy.strategy_id] = strategy
        if goal_id not in self._goal_strategies:
            self._goal_strategies[goal_id] = []
        self._goal_strategies[goal_id].append(strategy.strategy_id)

        # Trim old strategies per goal
        self._trim_goal_strategies(goal_id)

        # Record intent
        reason = self._infer_reason(context)
        self._intent_tracker.record(
            goal_id=goal_id,
            strategy_id=strategy.strategy_id,
            template_name=template_name,
            reason=reason,
            metadata={"topic": topic} if topic else {},
        )

        logger.info(
            "Selected strategy %s (%s) for goal %s: %s",
            strategy.strategy_id,
            template_name,
            goal_id,
            reason,
        )
        return strategy

    def _match_template(self, goal_id: str, context: Dict[str, Any]) -> Optional[str]:
        """
        Match context to a template name.

        v1.2 rules (priority order):
        1. If new_files_available -> learn_topic (learn local files first)
        2. If weak_topics with confidence < 0.5 -> consolidate
        3. If weak_topics but consolidate exhausted -> explore_new (fetch about weak topic)
        4. If topic specified -> learn_topic
        5. If no new files and no weak topics -> explore_new (fetch from web)
        6. Default for learning goals -> learn_topic

        v2 path: pluggable matchers, LLM selection.
        """
        new_files = context.get("new_files_available", False)
        weak_topics = context.get("weak_topics", [])
        topic = context.get("topic", "")
        goal_type = context.get("goal_type", "")

        # Filter weak_topics: only truly weak ones (confidence < 0.5)
        # Knowledge gaps come from world model with confidence values
        knowledge_gaps = context.get("_knowledge_gaps", [])
        truly_weak = [
            t for t in weak_topics
            if any(g.get("topic") == t and g.get("confidence", 0) < 0.5
                   for g in knowledge_gaps)
        ] if knowledge_gaps else weak_topics

        # Check if template was already tried and abandoned too many times
        def _not_exhausted(name: str) -> bool:
            return self._intent_tracker.count_failed_template(goal_id, name) < 5

        # P1: New local files -> learn them first
        if new_files and _not_exhausted("learn_topic"):
            return "learn_topic"

        # P2: Truly weak topics -> consolidate (if not exhausted)
        if truly_weak and _not_exhausted("consolidate"):
            return "consolidate"

        # P3: Truly weak topics but consolidate exhausted -> fetch new materials
        # about the weak topic instead of looping consolidate/learn on empty data
        if truly_weak and _not_exhausted("explore_new"):
            return "explore_new"

        # P4: Specific topic requested
        if topic and _not_exhausted("learn_topic"):
            return "learn_topic"

        # P5: Default for LEARNING goals (specific learning goal)
        if goal_type == "LEARNING" and _not_exhausted("learn_topic"):
            return "learn_topic"

        # P6: META goal with nothing to learn/consolidate -> explore web
        if (goal_type in ("META", "")
                and _not_exhausted("explore_new")):
            return "explore_new"

        # P7: Fallback learn_topic
        if _not_exhausted("learn_topic"):
            return "learn_topic"

        return None

    def _infer_reason(self, context: Dict[str, Any]) -> str:
        """Infer a human-readable reason from context."""
        if context.get("new_files_available"):
            return "new_files_available"
        if context.get("weak_topics"):
            topics = context["weak_topics"]
            return f"weak_topics_detected: {', '.join(topics[:3])}"
        if context.get("topic"):
            return f"topic_requested: {context['topic']}"
        return "default_learning"

    # -- Strategy advancement --

    def _advance_on_success(self, strategy: Strategy, step: Step) -> str:
        """Advance to next step after success."""
        step.status = StepStatus.COMPLETED
        next_order = step.order + 1

        # Find next step
        next_step = None
        for s in strategy.steps:
            if s.order == next_order:
                next_step = s
                break

        if next_step is None:
            # All steps done
            strategy.status = StrategyStatus.COMPLETED
            strategy.updated_at = time.time()
            self._intent_tracker.update_outcome(strategy.strategy_id, "completed")
            logger.info("Strategy %s completed", strategy.strategy_id)
            return "completed"

        strategy.current_step_order = next_order
        strategy.updated_at = time.time()
        return "active"

    def _advance_on_failure(self, strategy: Strategy, step: Step) -> str:
        """Handle step failure: retry or fallback."""
        step.retries_used += 1

        if step.retries_used < step.max_retries:
            # Retry same step
            step.status = StepStatus.ACTIVE
            strategy.updated_at = time.time()
            logger.info(
                "Strategy %s step %d retry %d/%d",
                strategy.strategy_id,
                step.order,
                step.retries_used,
                step.max_retries,
            )
            return "active"

        # Max retries exhausted
        step.status = StepStatus.FAILED

        if step.fallback_step_order is not None:
            # Jump to fallback step
            fallback = None
            for s in strategy.steps:
                if s.order == step.fallback_step_order:
                    fallback = s
                    break

            if fallback and fallback.status != StepStatus.FAILED:
                fallback.status = StepStatus.PENDING
                strategy.current_step_order = step.fallback_step_order
                strategy.updated_at = time.time()
                logger.info(
                    "Strategy %s step %d failed, fallback to step %d",
                    strategy.strategy_id,
                    step.order,
                    step.fallback_step_order,
                )
                return "active"

        # No fallback or fallback also failed -> abandon
        strategy.status = StrategyStatus.ABANDONED
        strategy.updated_at = time.time()
        self._intent_tracker.update_outcome(strategy.strategy_id, "abandoned")
        logger.info("Strategy %s abandoned after step %d failure", strategy.strategy_id, step.order)
        return "abandoned"

    # -- Helpers --

    def _get_active_strategy(self, goal_id: str) -> Optional[Strategy]:
        """Find active (non-terminal) strategy for a goal."""
        ids = self._goal_strategies.get(goal_id, [])
        for sid in reversed(ids):  # Most recent first
            s = self._strategies.get(sid)
            if s and s.status == StrategyStatus.ACTIVE:
                return s
        return None

    def _trim_goal_strategies(self, goal_id: str) -> None:
        """Keep only MAX_STRATEGIES_PER_GOAL per goal."""
        ids = self._goal_strategies.get(goal_id, [])
        if len(ids) <= self.MAX_STRATEGIES_PER_GOAL:
            return
        # Remove oldest non-active
        to_remove = []
        for sid in ids:
            s = self._strategies.get(sid)
            if s and s.is_terminal:
                to_remove.append(sid)
            if len(ids) - len(to_remove) <= self.MAX_STRATEGIES_PER_GOAL:
                break
        for sid in to_remove:
            del self._strategies[sid]
            ids.remove(sid)
