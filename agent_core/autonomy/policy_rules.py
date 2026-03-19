"""
Policy Rules for K7 Autonomy Policy.

Rule-based engine that evaluates whether an action should proceed.
Each rule is a pure function: context in, decision out.

Kontrakt: docs/CONTRACTS.md - Kontrakt 7: Autonomy Policy
ADR-013: Rule-based, zero LLM, deterministic, testable.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class PolicyDecision(Enum):
    """Result of a policy check."""
    ALLOW = "allow"
    RATE_LIMITED = "rate_limited"
    BLOCK = "block"
    ESCALATE = "escalate"  # HITL placeholder


@dataclass(frozen=True)
class PolicyContext:
    """
    Context available to policy rules at decision time.

    Gathered from K1-K6 subsystems before action execution.
    """
    action_type: str              # ActionType.value
    action_params: Dict[str, Any] = field(default_factory=dict)
    goal_id: Optional[str] = None
    goal_type: Optional[str] = None
    health_score: float = 1.0
    mode: str = "active"
    retention_rate: Optional[float] = None
    consecutive_failures: int = 0  # Same action type failures in a row


@dataclass
class PolicyResult:
    """Result of policy evaluation."""
    decision: PolicyDecision
    reasons: List[str] = field(default_factory=list)
    rule_name: Optional[str] = None  # Which rule triggered non-ALLOW

    @property
    def allowed(self) -> bool:
        return self.decision == PolicyDecision.ALLOW


# -- Built-in rules ------------------------------------------------

def rule_consecutive_failure_breaker(
    ctx: PolicyContext, threshold: int = 3
) -> Optional[PolicyResult]:
    """
    Block action after N consecutive failures of the same type.

    Prevents runaway loops like the fetch-fail incident (1430 attempts).
    """
    if ctx.consecutive_failures >= threshold:
        return PolicyResult(
            decision=PolicyDecision.BLOCK,
            reasons=[
                f"consecutive_failures: {ctx.action_type} "
                f"failed {ctx.consecutive_failures} times in a row "
                f"(threshold: {threshold})"
            ],
            rule_name="consecutive_failure_breaker",
        )
    return None


def rule_degraded_mode_restrict(ctx: PolicyContext) -> Optional[PolicyResult]:
    """
    In REDUCED/SLEEP modes, only allow FREE actions.

    GUARDED/RESTRICTED actions blocked when system is degraded.
    """
    if ctx.mode not in ("active",):
        from agent_core.autonomy.action_class import classify_action, ActionClassification
        classification = classify_action(ctx.action_type)
        if classification not in (ActionClassification.FREE,):
            return PolicyResult(
                decision=PolicyDecision.BLOCK,
                reasons=[
                    f"mode_restrict: {ctx.action_type} ({classification.value}) "
                    f"blocked in {ctx.mode} mode"
                ],
                rule_name="degraded_mode_restrict",
            )
    return None


def rule_restricted_actions_block(ctx: PolicyContext) -> Optional[PolicyResult]:
    """
    RESTRICTED and FORBIDDEN actions always blocked (until HITL is ready).

    Safe-by-default: unknown action types are RESTRICTED.
    """
    from agent_core.autonomy.action_class import classify_action, ActionClassification
    classification = classify_action(ctx.action_type)
    if classification == ActionClassification.FORBIDDEN:
        return PolicyResult(
            decision=PolicyDecision.BLOCK,
            reasons=[f"forbidden: {ctx.action_type} is never allowed autonomously"],
            rule_name="restricted_actions_block",
        )
    if classification == ActionClassification.RESTRICTED:
        return PolicyResult(
            decision=PolicyDecision.ESCALATE,
            reasons=[
                f"restricted: {ctx.action_type} requires confirmation "
                f"(not yet implemented, blocking)"
            ],
            rule_name="restricted_actions_block",
        )
    return None


# Rule type: callable(PolicyContext) -> Optional[PolicyResult]
# Returns None if rule does not apply (pass-through).
PolicyRule = Callable[[PolicyContext], Optional[PolicyResult]]

# Default rule chain, evaluated in order. First non-None result wins.
DEFAULT_RULES: List[PolicyRule] = [
    rule_restricted_actions_block,
    rule_degraded_mode_restrict,
    rule_consecutive_failure_breaker,
]


class PolicyEngine:
    """
    Evaluates policy rules in chain. First blocking rule wins.

    All rules are pure functions - no side effects.
    """

    def __init__(self, rules: Optional[List[PolicyRule]] = None):
        self._rules = list(rules) if rules is not None else list(DEFAULT_RULES)

    def evaluate(self, ctx: PolicyContext) -> PolicyResult:
        """
        Run all rules against context.

        Returns:
            PolicyResult with ALLOW if all rules pass,
            or first non-ALLOW result.
        """
        for rule in self._rules:
            try:
                result = rule(ctx)
                if result is not None:
                    logger.debug(
                        f"PolicyEngine: {result.rule_name} -> "
                        f"{result.decision.value} for {ctx.action_type}"
                    )
                    return result
            except Exception as e:
                logger.warning(f"PolicyEngine rule error: {e}")
                continue

        return PolicyResult(decision=PolicyDecision.ALLOW)

    def add_rule(self, rule: PolicyRule) -> None:
        """Append a rule to the chain."""
        self._rules.append(rule)
