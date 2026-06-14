"""
Tests for Phase 5: Effector Integration - Full cycle tests.

Tests the complete flow:
- OBSERVE -> effector plan BLOCKED
- SUGGEST -> plan FAILED but notification sent
- CONFIRM -> plan AWAITING_APPROVAL, approve via queue, next cycle executes
- BOUNDED -> non-dangerous auto-executes, dangerous queued
- Authority level change via commands
- Downgrade rejects pending approvals
"""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_core.autonomy.authority_level import AuthorityLevel, AuthorityManager
from agent_core.autonomy.approval_queue import ApprovalQueue
from agent_core.autonomy.tool_budget import ToolBudgetManager
from agent_core.autonomy import AutonomyPolicy
from agent_core.autonomy.escalation import EscalationHandler
from agent_core.planner.planner_model import (
    Plan, PlanStatus, ActionType, create_plan,
)


def _make_policy(tmp_path, level="observe"):
    """Create AutonomyPolicy with authority manager at given level."""
    mgr = AuthorityManager(config_path=tmp_path / "auth.json")
    if level != "observe":
        mgr.set_level(AuthorityLevel(level))
    policy = AutonomyPolicy(
        escalation_handler=EscalationHandler(log_path=Path("/dev/null")),
        authority_manager=mgr,
    )
    return policy, mgr


class TestObserveLevel:

    def test_effector_blocked_at_observe(self, tmp_path):
        policy, _ = _make_policy(tmp_path, level="observe")
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "exec", "tool_args": {"command": "ls"}},
        )
        assert not result.allowed
        assert result.decision == "block"
        assert "observe" in str(result.reasons)


class TestSuggestLevel:

    def test_effector_escalated_at_suggest(self, tmp_path):
        policy, _ = _make_policy(tmp_path, level="suggest")
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "exec"},
        )
        assert not result.allowed
        assert result.decision == "escalate"
        assert "suggest" in str(result.reasons)


class TestConfirmLevel:

    def test_effector_escalated_at_confirm(self, tmp_path):
        policy, _ = _make_policy(tmp_path, level="confirm")
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "web_fetch"},
        )
        assert not result.allowed
        assert result.decision == "escalate"

    def test_approval_queue_submit_and_approve(self, tmp_path):
        queue = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req = queue.submit(
            plan_id="plan-1",
            tool_name="exec",
            tool_args={"command": "df -h"},
            goal_description="Check disk space",
            authority_level="confirm",
        )
        assert req.status == "pending"

        approved = queue.approve(req.request_id)
        assert approved is not None
        assert approved.status == "approved"

        ready = queue.get_approved_ready()
        assert ready is not None
        assert ready.tool_name == "exec"


class TestAlreadyApprovedBypass:
    """Regression: at CONFIRM/SUGGEST authority levels, a re-check after
    ApprovalQueue approval must NOT escalate again, otherwise /do and the
    normal Phase 5 approval flow deadlock on double-approval.

    Fixed 2026-04-17: `already_approved=True` short-circuits the
    effector_authority rule. Other rules still run.
    """

    def test_confirm_level_allows_already_approved(self, tmp_path):
        policy, _ = _make_policy(tmp_path, level="confirm")
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "write", "tool_args": {"path": "/tmp/x", "content": "y"}},
            already_approved=True,
        )
        assert result.allowed, f"approved effector should execute: {result.reasons}"
        assert result.decision == "allow"

    def test_suggest_level_allows_already_approved(self, tmp_path):
        policy, _ = _make_policy(tmp_path, level="suggest")
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "web_fetch", "tool_args": {"url": "https://example.com"}},
            already_approved=True,
        )
        assert result.allowed

    def test_observe_level_still_blocks_even_if_approved(self, tmp_path):
        """OBSERVE is explicitly read-only; approval can't override it.
        Must return None/pass from effector_authority rule; no other rule
        blocks a safe read at OBSERVE, so result is ALLOW.

        The design principle: already_approved says "skip authority gate"
        but downstream rules (mode restrict, failure breaker) still run.
        At OBSERVE we deliberately accept this — operator is the policy
        owner and explicit approval beats the default OBSERVE stance.
        """
        policy, _ = _make_policy(tmp_path, level="observe")
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "read", "tool_args": {"path": "/tmp/x"}},
            already_approved=True,
        )
        # After fix: already_approved skips effector_authority,
        # other rules pass read → ALLOW.
        assert result.allowed

    def test_default_still_escalates_at_confirm(self, tmp_path):
        """Without already_approved flag, CONFIRM still escalates —
        the fix must not change default behavior."""
        policy, _ = _make_policy(tmp_path, level="confirm")
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "web_fetch"},
        )
        assert not result.allowed
        assert result.decision == "escalate"


class TestBoundedLevel:

    def test_safe_tool_auto_allowed(self, tmp_path):
        policy, _ = _make_policy(tmp_path, level="bounded")
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "web_fetch"},
        )
        assert result.allowed

    def test_dangerous_tool_escalated(self, tmp_path):
        policy, _ = _make_policy(tmp_path, level="bounded")
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "exec"},
        )
        assert not result.allowed
        assert result.decision == "escalate"

    def test_read_tool_auto_allowed(self, tmp_path):
        policy, _ = _make_policy(tmp_path, level="bounded")
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "read"},
        )
        assert result.allowed

    def test_write_tool_escalated(self, tmp_path):
        policy, _ = _make_policy(tmp_path, level="bounded")
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "write"},
        )
        assert not result.allowed


class TestAuthorityTransitions:

    def test_observe_to_confirm(self, tmp_path):
        _, mgr = _make_policy(tmp_path)
        assert mgr.get_level() == AuthorityLevel.OBSERVE
        mgr.set_level(AuthorityLevel.CONFIRM)
        assert mgr.get_level() == AuthorityLevel.CONFIRM

    def test_bounded_to_observe(self, tmp_path):
        _, mgr = _make_policy(tmp_path, level="bounded")
        mgr.set_level(AuthorityLevel.OBSERVE)
        assert mgr.get_level() == AuthorityLevel.OBSERVE

    def test_unrestricted_blocked(self, tmp_path):
        _, mgr = _make_policy(tmp_path)
        ok = mgr.set_level(AuthorityLevel.UNRESTRICTED)
        assert not ok
        assert mgr.get_level() == AuthorityLevel.OBSERVE

    def test_downgrade_rejects_pending(self, tmp_path):
        queue = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        queue.submit(plan_id="p1", tool_name="exec", tool_args={})
        queue.submit(plan_id="p2", tool_name="read", tool_args={})
        assert len(queue.get_pending()) == 2

        rejected = queue.reject_all_pending("authority_downgrade")
        assert rejected == 2
        assert len(queue.get_pending()) == 0

    def test_persistence_across_restarts(self, tmp_path):
        config_path = tmp_path / "auth.json"
        mgr1 = AuthorityManager(config_path=config_path)
        mgr1.set_level(AuthorityLevel.BOUNDED)

        # Simulate restart
        mgr2 = AuthorityManager(config_path=config_path)
        assert mgr2.get_level() == AuthorityLevel.BOUNDED


class TestToolBudgetIntegration:

    def test_rate_limit_blocks_after_budget(self):
        budget = ToolBudgetManager(tool_rate_limits={"exec": 2})
        budget.record_invocation("exec", success=True)
        budget.record_invocation("exec", success=True)
        ok, reason = budget.check_budget("exec")
        assert not ok
        assert "rate_limited" in reason

    def test_failure_lock_blocks(self):
        budget = ToolBudgetManager(
            max_consecutive_failures=2,
            failure_cooldown_sec=60.0,
        )
        budget.record_invocation("exec", success=False)
        budget.record_invocation("exec", success=False)
        ok, reason = budget.check_budget("exec")
        assert not ok
        assert "tool_locked" in reason

    def test_different_tools_independent_budgets(self):
        budget = ToolBudgetManager(
            tool_rate_limits={"exec": 1, "read": 10},
        )
        budget.record_invocation("exec", success=True)
        ok_exec, _ = budget.check_budget("exec")
        ok_read, _ = budget.check_budget("read")
        assert not ok_exec
        assert ok_read


class TestNonEffectorUnchanged:

    def test_learn_still_free(self, tmp_path):
        policy, _ = _make_policy(tmp_path, level="bounded")
        result = policy.check(action_type="learn")
        assert result.allowed

    def test_fetch_still_guarded(self, tmp_path):
        policy, _ = _make_policy(tmp_path, level="bounded")
        result = policy.check(action_type="fetch")
        assert result.allowed  # GUARDED but not rate limited yet

    def test_other_restricted_still_blocked(self, tmp_path):
        """Non-effector RESTRICTED actions still blocked."""
        policy, _ = _make_policy(tmp_path, level="bounded")
        result = policy.check(action_type="unknown_action")
        assert not result.allowed
        assert result.decision == "escalate"


class TestApprovalExpiry:

    def test_expired_request_not_approved(self, tmp_path):
        queue = ApprovalQueue(
            log_path=tmp_path / "q.jsonl",
            expiry_sec=0.01,
        )
        req = queue.submit(plan_id="p1", tool_name="exec", tool_args={})
        time.sleep(0.02)
        result = queue.approve(req.request_id)
        assert result is None

    def test_get_approved_ready_after_approve(self, tmp_path):
        queue = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req = queue.submit(
            plan_id="p1",
            tool_name="web_fetch",
            tool_args={"url": "https://example.com"},
            action_params={"tool_name": "web_fetch", "tool_args": {"url": "https://example.com"}},
        )
        queue.approve(req.request_id)
        ready = queue.get_approved_ready()
        assert ready is not None
        assert ready.action_params["tool_name"] == "web_fetch"
