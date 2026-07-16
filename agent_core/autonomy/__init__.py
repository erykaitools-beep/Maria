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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.autonomy.action_class import (
    ActionClassification,
    classify_action,
)
from agent_core.autonomy.authority_level import (
    AuthorityLevel,
    AuthorityManager,
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
    # AuthorityLevel.value for effector escalations -- carried structurally so
    # the escalation handler routes on the enum value, not a token parsed out of
    # a reason string (the BOUNDED reason had no token -> silent block).
    authority_level: str = ""


class AutonomyPolicy:
    """
    K7 Autonomy Policy facade.

    Combines:
    - Action classification (FREE/GUARDED/RESTRICTED/FORBIDDEN)
    - Rate limiting (per action type, sliding window)
    - Policy rules (chain of pure functions)
    - Escalation handling (logging, blocking, HITL placeholder)
    """

    # After this many seconds without any attempt, consecutive failure
    # counter resets to 0. Prevents permanent blocking after transient errors.
    FAILURE_DECAY_SEC = 1800  # 30 minutes

    def __init__(
        self,
        engine: Optional[PolicyEngine] = None,
        rate_limiter: Optional[ActionRateLimiter] = None,
        escalation_handler: Optional[EscalationHandler] = None,
        log_path: Optional[Path] = None,
        authority_manager: Optional[AuthorityManager] = None,
    ):
        self._engine = engine or PolicyEngine()
        self._rate_limiter = rate_limiter or ActionRateLimiter()
        self._escalation = escalation_handler or EscalationHandler(
            log_path=log_path
        )
        self._authority = authority_manager
        # Track consecutive failures per action type
        self._consecutive_failures: Dict[str, int] = {}
        # Track when the last failure was recorded per action type
        self._failure_timestamps: Dict[str, float] = {}

    def check(
        self,
        action_type: str,
        action_params: Optional[Dict[str, Any]] = None,
        goal_id: Optional[str] = None,
        goal_type: Optional[str] = None,
        health_score: float = 1.0,
        mode: str = "active",
        retention_rate: Optional[float] = None,
        already_approved: bool = False,
        precheck: bool = False,
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
            precheck: True when the caller is only ASKING ("would this be
                allowed?") before planning, not attempting the action. A
                blocked precheck returns allowed=False but does NOT go
                through the escalation handler -- the planner asks for every
                rotation candidate every cycle (~60s at night), and logging
                each "no" would flood autonomy_decisions.jsonl with
                thousands of non-events per night. Real attempts (execution
                gate) keep full escalation logging.

        Returns:
            CheckResult with allowed flag and details.
        """
        classification = classify_action(action_type)

        # Step 0: Time-based decay of consecutive failure counter
        if action_type in self._failure_timestamps:
            elapsed = time.time() - self._failure_timestamps[action_type]
            if elapsed >= self.FAILURE_DECAY_SEC:
                old_count = self._consecutive_failures.get(action_type, 0)
                if old_count > 0:
                    logger.info(
                        "failure_decay: resetting %s consecutive failures "
                        "(%d -> 0) after %.0fs idle",
                        action_type, old_count, elapsed,
                    )
                self._consecutive_failures[action_type] = 0
                del self._failure_timestamps[action_type]

        # Step 1: Rate limit check for the frequency-governed classes:
        # GUARDED (mutating, e.g. fetch/effector) and ANALYTICAL (reflection,
        # e.g. self_analyze/creative/critique/validate). FREE actions
        # (learn/exam/review/evaluate/noop/play) stay deliberately unlimited
        # -- learning must run freely in-window, and evaluate/review are the
        # cheap, zero/local-LLM floor actions the design never meant to cap.
        #
        # Before 2026-07-07 this was gated to GUARDED only, so the configured
        # ANALYTICAL limits (self_analyze 2/h, critique 1/h, ...) were dead:
        # record_execution() fed the limiter but check() never asked it. The
        # off-window night rotation then ground K12 through the 70B NIM every
        # ~60s (~370 runs/night). Adding ANALYTICAL here arms exactly the
        # NIM-burning reflection actions without touching the FREE-class
        # day-paths (P4 retention REVIEW, maintenance-theme EVALUATE, the
        # exam-deadlock forced REVIEW), which select without prechecking and
        # would otherwise start hitting this gate as loud FAILED plans.
        #
        # "ANALYTICAL must run 7/7" is a MODE guarantee (policy_rules), not an
        # unlimited-frequency guarantee -- the limiter still lets it run in
        # reduced/sleep, just not every cycle.
        if classification in (
            ActionClassification.GUARDED,
            ActionClassification.ANALYTICAL,
        ):
            rate_ok, rate_reason = self._rate_limiter.check(action_type)
            if not rate_ok:
                blocked = None
                if not precheck:
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
        # Phase 5: populate authority context for effector actions
        authority_level = "observe"
        tool_name = ""
        tool_dangerous = False
        if action_type == "effector":
            if self._authority:
                authority_level = self._authority.get_level().value
            params = action_params or {}
            tool_name = params.get("tool_name", "")
            if tool_name:
                try:
                    from agent_core.effector.tool_specs import get_tool_spec
                    spec = get_tool_spec(tool_name)
                    tool_dangerous = spec.dangerous if spec else True  # unknown = dangerous
                except Exception:
                    tool_dangerous = True  # unknown tool = treat as dangerous

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
            authority_level=authority_level,
            tool_name=tool_name,
            tool_dangerous=tool_dangerous,
            already_approved=already_approved,
        )

        result = self._engine.evaluate(ctx)

        if not result.allowed:
            blocked = None
            if not precheck:
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
                authority_level=authority_level,
            )

        return CheckResult(
            allowed=True,
            decision=PolicyDecision.ALLOW.value,
            classification=classification.value,
        )

    def record_execution(
        self, action_type: str, success: bool, skipped: bool = False
    ) -> None:
        """
        Record action outcome for consecutive failure tracking and rate limiting.

        Must be called after every action execution.

        Args:
            action_type: ActionType.value string
            success: Whether the action succeeded
            skipped: True if the executor declined the action before doing any
                work (e.g. no fresh material passed the candidate filter --
                ``idle_reason="filtered_out_all_candidates"``). A skip is NEITHER
                a success nor a failure: it must not trip the
                consecutive_failure_breaker, and must not reset a real failure
                streak. Counting these skips as failures is what deadlocked
                ``learn`` -- 3 thin-material skips tripped the breaker, which then
                blocked every learn so the counter could never reset on a success.
        """
        # A skipped attempt never ran -- it is a non-event for both the failure
        # breaker and the rate budget. Leaving the failure timestamp untouched
        # also lets FAILURE_DECAY_SEC clear a real streak during a skip drought.
        if skipped:
            return

        # Rate limiter: record all real executions (successful or not)
        self._rate_limiter.record(action_type)

        # Consecutive failure tracking
        if success:
            self._consecutive_failures[action_type] = 0
            self._failure_timestamps.pop(action_type, None)
        else:
            self._consecutive_failures[action_type] = (
                self._consecutive_failures.get(action_type, 0) + 1
            )
            self._failure_timestamps[action_type] = time.time()

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

    # -- Phase 5: Authority management -----------------------------------

    def set_authority_manager(self, manager: AuthorityManager) -> None:
        """Set authority manager (for late wiring)."""
        self._authority = manager

    def get_authority_level(self) -> AuthorityLevel:
        """Get current effector authority level."""
        if self._authority:
            return self._authority.get_level()
        return AuthorityLevel.OBSERVE

    def set_authority_level(self, level: AuthorityLevel) -> bool:
        """Change effector authority level. Returns False if blocked."""
        if not self._authority:
            logger.warning("No authority manager configured")
            return False
        return self._authority.set_level(level)

    def get_authority_status(self) -> Dict:
        """Get authority status for REPL/Telegram."""
        if self._authority:
            return self._authority.get_status()
        return {"authority_level": "observe", "note": "no manager configured"}
