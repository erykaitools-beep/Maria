"""
K8 Deliberation / Strategic Planning.

Facade module providing multi-step strategy planning for goals.
Wraps Deliberator + IntentTracker + Strategy Templates.

Usage:
    deliberation = Deliberation()
    action = deliberation.get_next_action(goal_id, context)
    # ... execute action ...
    deliberation.report_step_outcome(strategy_id, "pass", result)

Integration with PlannerCore:
    planner.set_deliberation(deliberation)
    # PlannerCore._create_plan_for_goal() consults deliberation first,
    # falls back to _decide_learning_action() if no strategy.

Kontrakt: docs/CONTRACTS.md - Kontrakt 8: Deliberation
ADR-013: Rule-based, zero LLM, deterministic.
ADR-011: Strategies as data.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.deliberation.deliberator import Deliberator
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


class Deliberation:
    """
    Facade for K8 Deliberation subsystem.

    Provides:
    - get_next_action(goal_id, context) -> action dict or None
    - report_step_outcome(strategy_id, outcome, result)
    - get_status() -> status dict for REPL/Web UI
    - abandon_strategy(strategy_id)

    v1: rule-based template selection, sequential steps with fallbacks.
    v2 path: LLM selection, DAG strategies, expression conditions.
    """

    def __init__(self, intent_path: Optional[Path] = None):
        self._intent_tracker = IntentTracker(path=intent_path)
        self._deliberator = Deliberator(intent_tracker=self._intent_tracker)

    def get_next_action(
        self,
        goal_id: str,
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Get next action for a goal from its multi-step strategy.

        Returns dict with action_type, action_params, strategy_id, etc.
        Returns None if no strategy matches (caller should use fallback logic).
        """
        return self._deliberator.get_next_action(goal_id, context)

    def report_step_outcome(
        self,
        strategy_id: str,
        outcome: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Report step outcome ("pass", "fail", "timeout").

        Returns strategy status ("active", "completed", "abandoned") or None.
        """
        return self._deliberator.report_step_outcome(strategy_id, outcome, result)

    def get_active_strategy(self, goal_id: str) -> Optional[Strategy]:
        """Get active strategy for a goal."""
        return self._deliberator.get_active_strategy_for_goal(goal_id)

    def abandon_strategy(self, strategy_id: str, reason: str = "") -> bool:
        """Abandon a strategy."""
        return self._deliberator.abandon_strategy(strategy_id, reason)

    def get_status(self) -> Dict[str, Any]:
        """Status dict for REPL / Web UI."""
        return self._deliberator.get_status()

    @property
    def deliberator(self) -> Deliberator:
        """Direct access to Deliberator (for advanced use)."""
        return self._deliberator

    @property
    def intent_tracker(self) -> IntentTracker:
        """Direct access to IntentTracker."""
        return self._intent_tracker
