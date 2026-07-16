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

    def test_skipped_attempt_does_not_trip_breaker(self):
        # A skip (candidates filtered out, no fresh material) is neither success
        # nor failure. 3 skips must NOT block -- unlike 3 real failures. This is
        # the learn deadlock: filtered_out_all_candidates skips tripped the
        # breaker, which then blocked every learn so it could never recover.
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(log_path=Path("/dev/null")),
        )
        policy.record_execution("learn", False, skipped=True)
        policy.record_execution("learn", False, skipped=True)
        policy.record_execution("learn", False, skipped=True)
        result = policy.check(action_type="learn")
        assert result.allowed is True

    def test_skipped_attempt_does_not_reset_real_streak(self):
        # A skip is neutral: it must not mask a real failure streak either.
        # 2 real failures + a skip + a 3rd real failure still trips the breaker.
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(log_path=Path("/dev/null")),
        )
        policy.record_execution("learn", False)
        policy.record_execution("learn", False)
        policy.record_execution("learn", False, skipped=True)  # neutral, no reset
        policy.record_execution("learn", False)  # 3rd real failure
        result = policy.check(action_type="learn")
        assert result.allowed is False
        assert "consecutive_failures" in result.reasons[0]

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


class TestRateLimitByClass:
    """Rate limits bind for GUARDED + ANALYTICAL, never for FREE.

    Historically check() consulted the rate limiter only for GUARDED
    actions, leaving the configured ANALYTICAL limits (self_analyze 2/h,
    critique 1/h, ...) dead: record_execution() fed the limiter but
    check() never asked it. The night rotation then ground K12 through
    NIM every ~60s all night (2026-07-07). The fix arms ANALYTICAL too,
    but deliberately leaves FREE (learn/exam/review/evaluate/noop/play)
    unlimited -- those are the cheap floor actions the design never meant
    to cap, and their day-path selection sites do not precheck, so capping
    them would surface as loud FAILED plans at the execution gate.
    """

    def test_analytical_action_rate_limited_at_default_limit(self):
        # Default limits: self_analyze = 1/h (zejscie z 2/h 07-07: limiter
        # jest jedynym hamulcem nocnej rotacji). Second check must block.
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(log_path=Path("/dev/null")),
        )
        policy.record_execution("self_analyze", True)
        result = policy.check(action_type="self_analyze")
        assert result.allowed is False
        assert result.decision == "rate_limited"
        assert result.classification == "analytical"

    def test_analytical_critique_rate_limited_at_one_per_hour(self):
        # critique = 1/h (the tightest ANALYTICAL cap). Second check blocks.
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(log_path=Path("/dev/null")),
        )
        policy.record_execution("critique", True)
        result = policy.check(action_type="critique")
        assert result.allowed is False
        assert result.decision == "rate_limited"

    def test_analytical_under_limit_still_runs_in_degraded_modes(self):
        # The 7/7 guarantee is about MODES, not frequency: under the
        # limit (0/1 used), ANALYTICAL actions still run in reduced/sleep.
        policy = AutonomyPolicy()
        for mode in ("reduced", "sleep"):
            result = policy.check(action_type="self_analyze", mode=mode)
            assert result.allowed is True, mode

    def test_free_action_with_configured_limit_stays_unlimited(self):
        # evaluate is FREE and HAS a dict limit (2/h), but FREE is never
        # consulted -- capping it would arm un-prechecked day-paths (K4
        # report, maintenance EVALUATE) into loud FAILED plans. Pin that
        # the FREE class overrides the stale dict entry.
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(log_path=Path("/dev/null")),
        )
        for _ in range(10):
            policy.record_execution("evaluate", True)
        result = policy.check(action_type="evaluate")
        assert result.allowed is True

    def test_free_review_stays_unlimited(self):
        # review = 5/h in the dict but FREE: the exam-deadlock breaker's
        # forced REVIEW must never be rate-blocked.
        policy = AutonomyPolicy()
        for _ in range(10):
            policy.record_execution("review", True)
        result = policy.check(action_type="review")
        assert result.allowed is True

    def test_free_action_without_limit_stays_unlimited(self):
        policy = AutonomyPolicy()
        for _ in range(20):
            policy.record_execution("learn", True)
        result = policy.check(action_type="learn")
        assert result.allowed is True

    def test_guarded_action_still_rate_limited(self):
        # Pre-existing GUARDED behavior must be unchanged by the widening.
        policy = AutonomyPolicy(
            rate_limiter=ActionRateLimiter(limits={"fetch": 2}),
            escalation_handler=EscalationHandler(log_path=Path("/dev/null")),
        )
        policy.record_execution("fetch", True)
        policy.record_execution("fetch", True)
        result = policy.check(action_type="fetch")
        assert result.allowed is False
        assert result.decision == "rate_limited"


class TestPrecheckQuiet:
    """precheck=True answers "would this be allowed?" without side effects.

    The planner asks for every rotation candidate every cycle (~60s at
    night). Without precheck, each blocked "no" would land in
    autonomy_decisions.jsonl -- thousands of non-events per night (the
    log had 146 fs_write lines/night from the SLEEP-mode question alone).
    """

    def test_precheck_rate_limit_block_skips_escalation(self, tmp_path):
        log = tmp_path / "decisions.jsonl"
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(log_path=log),
        )
        policy.record_execution("self_analyze", True)  # 1/1 -- limit reached
        result = policy.check(action_type="self_analyze", precheck=True)
        assert result.allowed is False
        assert result.decision == "rate_limited"
        assert result.blocked_result is None
        assert not log.exists()
        assert policy.get_recent_escalations() == []

    def test_real_check_rate_limit_block_records_escalation(self, tmp_path):
        log = tmp_path / "decisions.jsonl"
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(log_path=log),
        )
        policy.record_execution("self_analyze", True)  # 1/1 -- limit reached
        result = policy.check(action_type="self_analyze")
        assert result.allowed is False
        assert result.blocked_result is not None
        assert log.exists()
        assert len(policy.get_recent_escalations()) == 1

    def test_precheck_rule_block_skips_escalation(self, tmp_path):
        # Mode-rule blocks (e.g. fs_write in SLEEP) are quiet too when
        # the caller is only asking.
        log = tmp_path / "decisions.jsonl"
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(log_path=log),
        )
        result = policy.check(
            action_type="fs_write", mode="sleep", precheck=True,
        )
        assert result.allowed is False
        assert result.blocked_result is None
        assert not log.exists()
        assert policy.get_recent_escalations() == []

    def test_precheck_allowed_action_unaffected(self):
        policy = AutonomyPolicy()
        result = policy.check(action_type="self_analyze", precheck=True)
        assert result.allowed is True


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
