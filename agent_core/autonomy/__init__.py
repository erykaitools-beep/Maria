"""
K7 Autonomy Policy / Governance for M.A.R.I.A.

Classifies actions, enforces rate limits, evaluates policy rules,
and handles escalation. Sits between PlannerGuard and ActionExecutor.

Pipeline:
    PlannerGuard.can_plan() -> AutonomyPolicy.check() -> ActionExecutor.execute()

Usage:
    from agent_core.autonomy import AutonomyPolicy

    policy = AutonomyPolicy()
    result = policy.check(action_type="fetch", goal_id="goal-meta-learn")
    if result.allowed:
        executor.execute(plan)
    else:
        # blocked or escalated
        result.blocked_result  # dict for planner

Kontrakt: docs/CONTRACTS.md - Kontrakt 7: Autonomy Policy
ADR-013: Rule-based, zero LLM, deterministic, testable.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.autonomy.action_class import (
    ActionClassification,
    classify_action,
)
from agent_core.autonomy.policy_rules import (
    PolicyContext,
    PolicyDecision,
    PolicyEngine,
    PolicyResult,
)
from agent_core.autonomy.rate_limiter import ActionRateLimiter
from agent_core.autonomy.escalation import EscalationHandler

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """Result of AutonomyPolicy.check()."""
    allowed: bool
    decision: str              # PolicyDecision.value
    classification: str        # ActionClassification.value
    reasons: List[str] = field(default_factory=list)
    rule_name: Optional[str] = None
    blocked_result: Optional[Dict[str, Any]] = None  # Ready-made action result


class AutonomyPolicy:
    """
    K7 Autonomy Policy facade.

    Combines:
    - Action classification (FREE/GUARDED/RESTRICTED/FORBIDDEN)
    - Rate limiting (per action type, sliding window)
    - Policy rules (chain of pure functions)
    - Escalation handling (logging, blocking, HITL placeholder)
    """

    def __init__(
        self,
        engine: Optional[PolicyEngine] = None,
        rate_limiter: Optional[ActionRateLimiter] = None,
        escalation_handler: Optional[EscalationHandler] = None,
        log_path: Optional[Path] = None,
    ):
        self._engine = engine or PolicyEngine()
        self._rate_limiter = rate_limiter or ActionRateLimiter()
        self._escalation = escalation_handler or EscalationHandler(
            log_path=log_path
        )
        # Track consecutive failures per action type
        self._consecutive_failures: Dict[str, int] = {}

    def check(
        self,
        action_type: str,
        action_params: Optional[Dict[str, Any]] = None,
        goal_id: Optional[str] = None,
        goal_type: Optional[str] = None,
        health_score: float = 1.0,
        mode: str = "active",
        retention_rate: Optional[float] = None,
    ) -> CheckResult:
        """
        Check if an action is allowed by autonomy policy.

        Args:
            action_type: ActionType.value string
            action_params: Plan action parameters
            goal_id: Associated goal ID
            goal_type: Goal type (meta/user/learning/maintenance)
            health_score: Current system health
            mode: Current homeostasis mode
            retention_rate: K4 retention metric

        Returns:
            CheckResult with allowed flag and details.
        """
        classification = classify_action(action_type)

        # Step 1: Rate limit check (for GUARDED actions)
        if classification == ActionClassification.GUARDED:
            rate_ok, rate_reason = self._rate_limiter.check(action_type)
            if not rate_ok:
                blocked = self._escalation.handle(
                    action_type=action_type,
                    decision=PolicyDecision.RATE_LIMITED.value,
                    reasons=[rate_reason],
                    rule_name="rate_limiter",
                    goal_id=goal_id,
                )
                return CheckResult(
                    allowed=False,
                    decision=PolicyDecision.RATE_LIMITED.value,
                    classification=classification.value,
                    reasons=[rate_reason],
                    rule_name="rate_limiter",
                    blocked_result=blocked,
                )

        # Step 2: Policy rules check
        ctx = PolicyContext(
            action_type=action_type,
            action_params=action_params or {},
            goal_id=goal_id,
            goal_type=goal_type,
            health_score=health_score,
            mode=mode,
            retention_rate=retention_rate,
            consecutive_failures=self._consecutive_failures.get(
                action_type, 0
            ),
        )

        result = self._engine.evaluate(ctx)

        if not result.allowed:
            blocked = self._escalation.handle(
                action_type=action_type,
                decision=result.decision.value,
                reasons=result.reasons,
                rule_name=result.rule_name,
                goal_id=goal_id,
                context_snapshot={
                    "health_score": health_score,
                    "mode": mode,
                    "consecutive_failures": ctx.consecutive_failures,
                },
            )
            return CheckResult(
                allowed=False,
                decision=result.decision.value,
                classification=classification.value,
                reasons=result.reasons,
                rule_name=result.rule_name,
                blocked_result=blocked,
            )

        return CheckResult(
            allowed=True,
            decision=PolicyDecision.ALLOW.value,
            classification=classification.value,
        )

    def record_execution(self, action_type: str, success: bool) -> None:
        """
        Record action outcome for consecutive failure tracking and rate limiting.

        Must be called after every action execution.

        Args:
            action_type: ActionType.value string
            success: Whether the action succeeded
        """
        # Rate limiter: record all executions (successful or not)
        self._rate_limiter.record(action_type)

        # Consecutive failure tracking
        if success:
            self._consecutive_failures[action_type] = 0
        else:
            self._consecutive_failures[action_type] = (
                self._consecutive_failures.get(action_type, 0) + 1
            )

    def get_status(self) -> Dict[str, Any]:
        """Get autonomy policy status for REPL/Web UI."""
        return {
            "rate_limits": self._rate_limiter.get_stats(),
            "consecutive_failures": dict(self._consecutive_failures),
            "recent_escalations": self._escalation.get_recent(limit=5),
        }

    def get_recent_escalations(self, limit: int = 10) -> List[Dict]:
        """Get recent escalation records."""
        return self._escalation.get_recent(limit=limit)
