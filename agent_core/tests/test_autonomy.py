"""
Tests for K7 Autonomy Policy.

Tests cover:
- ActionClassification and default mapping
- ActionRateLimiter (sliding window)
- PolicyRules (consecutive failures, mode restrict, restricted actions)
- PolicyEngine (rule chain)
- AutonomyPolicy facade (check + record_execution)
- EscalationHandler (logging)
- PlannerCore integration (K7 blocks execution)
"""

import json
import time
import pytest
from pathlib import Path

from agent_core.autonomy.action_class import (
    ActionClassification,
    classify_action,
    DEFAULT_ACTION_CLASSIFICATIONS,
)
from agent_core.autonomy.rate_limiter import ActionRateLimiter
from agent_core.autonomy.policy_rules import (
    PolicyContext,
    PolicyDecision,
    PolicyEngine,
    PolicyResult,
    rule_consecutive_failure_breaker,
    rule_degraded_mode_restrict,
    rule_restricted_actions_block,
)
from agent_core.autonomy.escalation import EscalationHandler, EscalationRecord
from agent_core.autonomy import AutonomyPolicy, CheckResult


# ============================================================
# ActionClassification tests
# ============================================================

class TestActionClassification:
    def test_free_actions(self):
        for action in ("learn", "exam", "review", "evaluate", "noop"):
            assert classify_action(action) == ActionClassification.FREE

    def test_guarded_actions(self):
        for action in ("fetch", "maintenance", "experiment", "ask_expert"):
            assert classify_action(action) == ActionClassification.GUARDED

    def test_analytical_actions(self):
        # READ-ONLY self-reflection tier — must run in SLEEP/REDUCED.
        for action in ("self_analyze", "creative", "critique", "validate"):
            assert classify_action(action) == ActionClassification.ANALYTICAL

    def test_unknown_action_defaults_to_restricted(self):
        assert classify_action("smart_home") == ActionClassification.RESTRICTED
        assert classify_action("delete_data") == ActionClassification.RESTRICTED

    def test_enum_values(self):
        assert ActionClassification.FREE.value == "free"
        assert ActionClassification.ANALYTICAL.value == "analytical"
        assert ActionClassification.GUARDED.value == "guarded"
        assert ActionClassification.RESTRICTED.value == "restricted"
        assert ActionClassification.FORBIDDEN.value == "forbidden"


# ============================================================
# ActionRateLimiter tests
# ============================================================

class TestRateLimiter:
    def test_unlimited_action(self):
        limiter = ActionRateLimiter()
        allowed, reason = limiter.check("learn")
        assert allowed is True
        assert reason is None

    def test_within_limit(self):
        limiter = ActionRateLimiter(limits={"fetch": 3})
        now = time.time()
        limiter.record("fetch", now)
        limiter.record("fetch", now + 1)
        allowed, reason = limiter.check("fetch", now + 2)
        assert allowed is True

    def test_at_limit_blocked(self):
        limiter = ActionRateLimiter(limits={"fetch": 2}, window_sec=3600)
        now = time.time()
        limiter.record("fetch", now)
        limiter.record("fetch", now + 1)
        allowed, reason = limiter.check("fetch", now + 2)
        assert allowed is False
        assert "rate_limit" in reason
        assert "fetch" in reason

    def test_window_expiry(self):
        limiter = ActionRateLimiter(limits={"fetch": 2}, window_sec=60)
        now = time.time()
        limiter.record("fetch", now)
        limiter.record("fetch", now + 1)
        # After window expires
        allowed, reason = limiter.check("fetch", now + 61)
        assert allowed is True

    def test_get_remaining(self):
        limiter = ActionRateLimiter(limits={"fetch": 5})
        now = time.time()
        assert limiter.get_remaining("fetch", now) == 5
        limiter.record("fetch", now)
        limiter.record("fetch", now + 1)
        assert limiter.get_remaining("fetch", now + 2) == 3

    def test_get_remaining_unlimited(self):
        limiter = ActionRateLimiter()
        assert limiter.get_remaining("learn") is None

    def test_get_stats(self):
        limiter = ActionRateLimiter(limits={"fetch": 5})
        stats = limiter.get_stats()
        assert "fetch" in stats
        assert stats["fetch"]["limit"] == 5
        assert stats["fetch"]["remaining"] == 5

    def test_multiple_action_types(self):
        limiter = ActionRateLimiter(limits={"fetch": 2, "maintenance": 3})
        now = time.time()
        limiter.record("fetch", now)
        limiter.record("fetch", now)
        limiter.record("maintenance", now)
        assert limiter.check("fetch", now)[0] is False
        assert limiter.check("maintenance", now)[0] is True


# ============================================================
# PolicyRules tests
# ============================================================

class TestPolicyRules:

    def test_consecutive_failure_breaker_passes(self):
        ctx = PolicyContext(action_type="fetch", consecutive_failures=2)
        result = rule_consecutive_failure_breaker(ctx)
        assert result is None  # passes through

    def test_consecutive_failure_breaker_blocks(self):
        ctx = PolicyContext(action_type="fetch", consecutive_failures=3)
        result = rule_consecutive_failure_breaker(ctx)
        assert result is not None
        assert result.decision == PolicyDecision.BLOCK
        assert "consecutive_failures" in result.reasons[0]

    def test_consecutive_failure_custom_threshold(self):
        ctx = PolicyContext(action_type="fetch", consecutive_failures=5)
        result = rule_consecutive_failure_breaker(ctx, threshold=10)
        assert result is None  # below custom threshold

    def test_degraded_mode_allows_free_actions(self):
        ctx = PolicyContext(action_type="learn", mode="reduced")
        result = rule_degraded_mode_restrict(ctx)
        assert result is None  # FREE action, passes

    def test_degraded_mode_allows_analytical_actions(self):
        # Self-reflection loop must keep running in SLEEP/REDUCED so the
        # organism keeps developing during idle/weekend windows.
        for action in ("self_analyze", "creative", "critique", "validate"):
            for mode in ("reduced", "sleep"):
                ctx = PolicyContext(action_type=action, mode=mode)
                result = rule_degraded_mode_restrict(ctx)
                assert result is None, (
                    f"{action} should be allowed in {mode} (ANALYTICAL tier)"
                )

    def test_degraded_mode_blocks_guarded_actions(self):
        ctx = PolicyContext(action_type="fetch", mode="reduced")
        result = rule_degraded_mode_restrict(ctx)
        assert result is not None
        assert result.decision == PolicyDecision.BLOCK
        assert "mode_restrict" in result.reasons[0]

    def test_degraded_mode_blocks_guarded_in_sleep(self):
        # GUARDED actions still blocked in sleep — only ANALYTICAL gets the
        # bypass. fetch/experiment/maintenance mutate state.
        for action in ("fetch", "experiment", "maintenance"):
            ctx = PolicyContext(action_type=action, mode="sleep")
            result = rule_degraded_mode_restrict(ctx)
            assert result is not None, (
                f"{action} (GUARDED) must be blocked in sleep"
            )
            assert result.decision == PolicyDecision.BLOCK

    def test_active_mode_allows_everything(self):
        ctx = PolicyContext(action_type="fetch", mode="active")
        result = rule_degraded_mode_restrict(ctx)
        assert result is None

    def test_restricted_action_escalates(self):
        ctx = PolicyContext(action_type="smart_home")
        result = rule_restricted_actions_block(ctx)
        assert result is not None
        assert result.decision == PolicyDecision.ESCALATE

    def test_forbidden_action_blocks(self):
        # Manually add a forbidden action for testing
        from agent_core.autonomy.action_class import DEFAULT_ACTION_CLASSIFICATIONS
        original = DEFAULT_ACTION_CLASSIFICATIONS.get("test_forbidden")
        DEFAULT_ACTION_CLASSIFICATIONS["test_forbidden"] = ActionClassification.FORBIDDEN
        try:
            ctx = PolicyContext(action_type="test_forbidden")
            result = rule_restricted_actions_block(ctx)
            assert result is not None
            assert result.decision == PolicyDecision.BLOCK
            assert "forbidden" in result.reasons[0]
        finally:
            if original is None:
                del DEFAULT_ACTION_CLASSIFICATIONS["test_forbidden"]
            else:
                DEFAULT_ACTION_CLASSIFICATIONS["test_forbidden"] = original

    def test_free_action_passes_restricted_check(self):
        ctx = PolicyContext(action_type="learn")
        result = rule_restricted_actions_block(ctx)
        assert result is None


# ============================================================
# PolicyEngine tests
# ============================================================

class TestPolicyEngine:

    def test_all_rules_pass_returns_allow(self):
        engine = PolicyEngine()
        ctx = PolicyContext(action_type="learn", mode="active")
        result = engine.evaluate(ctx)
        assert result.allowed is True
        assert result.decision == PolicyDecision.ALLOW

    def test_first_blocking_rule_wins(self):
        engine = PolicyEngine()
        ctx = PolicyContext(
            action_type="fetch", mode="reduced", consecutive_failures=5
        )
        result = engine.evaluate(ctx)
        # degraded_mode_restrict should fire before consecutive_failure
        assert result.allowed is False
        assert result.rule_name == "degraded_mode_restrict"

    def test_empty_rules_allows_all(self):
        engine = PolicyEngine(rules=[])
        ctx = PolicyContext(action_type="fetch")
        result = engine.evaluate(ctx)
        assert result.allowed is True

    def test_custom_rule(self):
        def my_rule(ctx):
            if ctx.action_type == "block_me":
                return PolicyResult(
                    decision=PolicyDecision.BLOCK,
                    reasons=["custom block"],
                    rule_name="my_rule",
                )
            return None

        engine = PolicyEngine(rules=[my_rule])
        ctx = PolicyContext(action_type="block_me")
        result = engine.evaluate(ctx)
        assert result.decision == PolicyDecision.BLOCK
        assert result.rule_name == "my_rule"

    def test_add_rule(self):
        engine = PolicyEngine(rules=[])
        engine.add_rule(lambda ctx: None)
        assert len(engine._rules) == 1

    def test_broken_rule_skipped(self):
        def broken(ctx):
            raise RuntimeError("oops")

        engine = PolicyEngine(rules=[broken])
        ctx = PolicyContext(action_type="learn")
        result = engine.evaluate(ctx)
        assert result.allowed is True  # broken rule skipped


# ============================================================
# EscalationHandler tests
# ============================================================

class TestEscalationHandler:

    def test_handle_returns_blocked_result(self, tmp_path):
        handler = EscalationHandler(log_path=tmp_path / "autonomy.jsonl")
        result = handler.handle(
            action_type="fetch",
            decision="rate_limited",
            reasons=["too many"],
        )
        assert result["success"] is False
        assert result["blocked_by"] == "autonomy_policy"
        assert result["decision"] == "rate_limited"

    def test_handle_writes_to_log(self, tmp_path):
        log_path = tmp_path / "autonomy.jsonl"
        handler = EscalationHandler(log_path=log_path)
        handler.handle(
            action_type="fetch",
            decision="block",
            reasons=["test"],
            rule_name="test_rule",
            goal_id="goal-1",
        )
        assert log_path.exists()
        with open(log_path) as f:
            record = json.loads(f.readline())
        assert record["action_type"] == "fetch"
        assert record["decision"] == "block"
        assert record["rule_name"] == "test_rule"
        assert record["goal_id"] == "goal-1"

    def test_get_recent(self, tmp_path):
        handler = EscalationHandler(log_path=tmp_path / "autonomy.jsonl")
        handler.handle("a", "block", ["r1"])
        handler.handle("b", "block", ["r2"])
        handler.handle("c", "block", ["r3"])
        recent = handler.get_recent(limit=2)
        assert len(recent) == 2
        assert recent[-1]["action_type"] == "c"

    def test_escalation_record_to_dict(self):
        record = EscalationRecord(
            timestamp=1000.0,
            action_type="fetch",
            decision="block",
            reasons=["test"],
        )
        d = record.to_dict()
        assert d["ts"] == 1000.0
        assert d["action_type"] == "fetch"


# ============================================================
# AutonomyPolicy facade tests
# ============================================================

class TestAutonomyPolicy:

    def test_free_action_allowed(self):
        policy = AutonomyPolicy()
        result = policy.check(action_type="learn")
        assert result.allowed is True
        assert result.classification == "free"

    def test_guarded_action_allowed_initially(self):
        policy = AutonomyPolicy()
        result = policy.check(action_type="fetch")
        assert result.allowed is True
        assert result.classification == "guarded"

    def test_guarded_action_rate_limited(self):
        policy = AutonomyPolicy(
            rate_limiter=ActionRateLimiter(
                limits={"fetch": 2}, window_sec=3600,
            ),
            escalation_handler=EscalationHandler(
                log_path=Path("/dev/null")
            ),
        )
        now = time.time()
        policy.record_execution("fetch", True)
        policy.record_execution("fetch", True)
        result = policy.check(action_type="fetch")
        assert result.allowed is False
        assert result.decision == "rate_limited"

    def test_restricted_action_blocked(self):
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(
                log_path=Path("/dev/null")
            ),
        )
        result = policy.check(action_type="smart_home")
        assert result.allowed is False
        assert result.decision == "escalate"

    def test_consecutive_failures_tracked(self):
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(
                log_path=Path("/dev/null")
            ),
        )
        policy.record_execution("fetch", False)
        policy.record_execution("fetch", False)
        policy.record_execution("fetch", False)
        result = policy.check(action_type="fetch")
        assert result.allowed is False
        assert "consecutive_failures" in result.reasons[0]

    def test_consecutive_failures_reset_on_success(self):
        policy = AutonomyPolicy()
        policy.record_execution("fetch", False)
        policy.record_execution("fetch", False)
        policy.record_execution("fetch", True)  # reset
        result = policy.check(action_type="fetch")
        assert result.allowed is True

    def test_degraded_mode_blocks_guarded(self):
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(
                log_path=Path("/dev/null")
            ),
        )
        result = policy.check(action_type="fetch", mode="reduced")
        assert result.allowed is False

    def test_degraded_mode_allows_free(self):
        policy = AutonomyPolicy()
        result = policy.check(action_type="learn", mode="reduced")
        assert result.allowed is True

    def test_get_status(self):
        policy = AutonomyPolicy()
        status = policy.get_status()
        assert "rate_limits" in status
        assert "consecutive_failures" in status
        assert "recent_escalations" in status

    def test_record_execution_updates_rate_limiter(self):
        policy = AutonomyPolicy(
            rate_limiter=ActionRateLimiter(
                limits={"fetch": 3}, window_sec=3600,
            ),
        )
        policy.record_execution("fetch", True)
        remaining = policy._rate_limiter.get_remaining("fetch")
        assert remaining == 2


# ============================================================
# PlannerCore integration tests
# ============================================================

class TestPlannerAutonomyIntegration:
    """Test that PlannerCore correctly uses K7."""

    def test_planner_has_autonomy_setter(self):
        from agent_core.planner.planner_core import PlannerCore
        planner = PlannerCore(
            state_path=Path("/dev/null"),
            decisions_path=Path("/dev/null"),
        )
        assert planner._autonomy_policy is None
        policy = AutonomyPolicy()
        planner.set_autonomy_policy(policy)
        assert planner._autonomy_policy is policy

    def test_planner_none_policy_no_crash(self):
        """Backward compatible: no policy = no crash."""
        from agent_core.planner.planner_core import PlannerCore
        from agent_core.planner.planner_model import (
            Plan, ActionType, PlanStatus, create_plan,
        )
        planner = PlannerCore(
            state_path=Path("/dev/null"),
            decisions_path=Path("/dev/null"),
        )
        # _autonomy_policy is None by default
        plan = create_plan(
            goal_id="goal-1",
            goal_description="test",
            action_type=ActionType.NOOP,
        )
        # _finalize_plan should work without autonomy policy
        result = planner._finalize_plan(plan)
        assert result.status == PlanStatus.COMPLETED

    def test_planner_blocked_by_policy(self, tmp_path):
        """K7 blocks restricted actions at finalize time."""
        from agent_core.planner.planner_core import PlannerCore
        from agent_core.planner.planner_model import (
            ActionType, create_plan,
        )

        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )

        # Policy that blocks "fetch" after 3 consecutive failures
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(
                log_path=tmp_path / "autonomy.jsonl"
            ),
        )
        policy.record_execution("fetch", False)
        policy.record_execution("fetch", False)
        policy.record_execution("fetch", False)
        planner.set_autonomy_policy(policy)

        plan = create_plan(
            goal_id="goal-1",
            goal_description="fetch test",
            action_type=ActionType.FETCH,
        )
        result = planner._finalize_plan(plan)
        assert result.result.get("blocked_by") == "autonomy_policy"


# ============================================================
# Failure decay (time-based auto-reset) tests
# ============================================================

class TestFailureDecay:
    """Test that consecutive failure counter resets after FAILURE_DECAY_SEC."""

    def test_counter_resets_after_decay_period(self):
        """After 30min without attempts, failure counter resets to 0."""
        policy = AutonomyPolicy()
        policy.record_execution("fetch", False)
        policy.record_execution("fetch", False)
        policy.record_execution("fetch", False)
        assert policy._consecutive_failures["fetch"] == 3

        # Simulate 31 minutes passing
        policy._failure_timestamps["fetch"] = (
            time.time() - AutonomyPolicy.FAILURE_DECAY_SEC - 1
        )

        result = policy.check(action_type="fetch")
        assert result.allowed is True
        assert policy._consecutive_failures["fetch"] == 0

    def test_counter_does_not_reset_before_decay_period(self):
        """Before 30min, failure counter stays intact and blocks."""
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(
                log_path=Path("/dev/null")
            ),
        )
        policy.record_execution("fetch", False)
        policy.record_execution("fetch", False)
        policy.record_execution("fetch", False)

        # Simulate only 10 minutes passing
        policy._failure_timestamps["fetch"] = time.time() - 600

        result = policy.check(action_type="fetch")
        assert result.allowed is False
        assert policy._consecutive_failures["fetch"] == 3

    def test_success_still_resets_counter_immediately(self):
        """Success resets counter and cleans up timestamp."""
        policy = AutonomyPolicy()
        policy.record_execution("fetch", False)
        policy.record_execution("fetch", False)
        assert policy._consecutive_failures["fetch"] == 2
        assert "fetch" in policy._failure_timestamps

        policy.record_execution("fetch", True)
        assert policy._consecutive_failures["fetch"] == 0
        assert "fetch" not in policy._failure_timestamps

    def test_multiple_action_types_tracked_independently(self):
        """Decay for one action type does not affect another."""
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(
                log_path=Path("/dev/null")
            ),
        )
        # Both fail 3 times
        for _ in range(3):
            policy.record_execution("fetch", False)
            policy.record_execution("maintenance", False)

        # Only fetch decays (31 min ago)
        policy._failure_timestamps["fetch"] = (
            time.time() - AutonomyPolicy.FAILURE_DECAY_SEC - 1
        )
        # maintenance is recent (5 min ago)
        policy._failure_timestamps["maintenance"] = time.time() - 300

        fetch_result = policy.check(action_type="fetch")
        assert fetch_result.allowed is True

        maint_result = policy.check(action_type="maintenance")
        assert maint_result.allowed is False

    def test_decay_constant_is_30_minutes(self):
        """Verify the decay constant value."""
        assert AutonomyPolicy.FAILURE_DECAY_SEC == 1800

    def test_failure_timestamp_set_on_failure(self):
        """record_execution(success=False) sets failure timestamp."""
        policy = AutonomyPolicy()
        before = time.time()
        policy.record_execution("fetch", False)
        after = time.time()
        assert "fetch" in policy._failure_timestamps
        assert before <= policy._failure_timestamps["fetch"] <= after

    def test_failure_timestamp_cleared_on_success(self):
        """record_execution(success=True) removes failure timestamp."""
        policy = AutonomyPolicy()
        policy.record_execution("fetch", False)
        assert "fetch" in policy._failure_timestamps
        policy.record_execution("fetch", True)
        assert "fetch" not in policy._failure_timestamps

    def test_no_timestamp_no_crash(self):
        """check() works fine when no failures have been recorded."""
        policy = AutonomyPolicy()
        result = policy.check(action_type="fetch")
        assert result.allowed is True


# ============================================================
# SharedContext integration
# ============================================================

class TestSharedContextAutonomy:
    def test_shared_context_has_autonomy_field(self):
        from agent_core.registry.shared_context import SharedContext
        ctx = SharedContext()
        assert hasattr(ctx, "autonomy_policy")
        assert ctx.autonomy_policy is None
