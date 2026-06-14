"""
Phase 6: Authority Drills - Adversarial scenarios.

Tests edge cases and failure modes:
- Malformed tool args
- Unknown tool names
- Stale approvals
- Double approval
- Conflicting requests
- Authority downgrade during pending
- Cascade failure
"""

import time
from pathlib import Path

import pytest

from agent_core.autonomy.authority_level import AuthorityLevel, AuthorityManager
from agent_core.autonomy.approval_queue import ApprovalQueue
from agent_core.autonomy.tool_budget import ToolBudgetManager
from agent_core.autonomy import AutonomyPolicy
from agent_core.autonomy.escalation import EscalationHandler
from agent_core.effector.tool_specs import validate_args, is_tool_allowed


class TestMalformedToolArgs:

    def test_missing_required_args_rejected(self):
        """Exec without 'command' arg should be rejected."""
        valid, reason = validate_args("exec", {})
        assert not valid
        assert "command" in reason

    def test_read_without_path_rejected(self):
        valid, reason = validate_args("read", {})
        assert not valid
        assert "path" in reason

    def test_write_without_content_rejected(self):
        valid, reason = validate_args("write", {"path": "/tmp/test"})
        assert not valid
        assert "content" in reason

    def test_valid_args_accepted(self):
        valid, reason = validate_args("exec", {"command": "ls -la"})
        assert valid


class TestUnknownToolNames:

    def test_unknown_tool_not_allowed(self):
        assert not is_tool_allowed("rm_rf_slash")
        assert not is_tool_allowed("shell_exec")
        assert not is_tool_allowed("")

    def test_denied_tool_not_allowed(self):
        assert not is_tool_allowed("browser")
        assert not is_tool_allowed("sessions_spawn")

    def test_unknown_tool_dangerous_at_bounded(self, tmp_path):
        """BOUNDED + unknown tool = ESCALATE (treated as dangerous)."""
        mgr = AuthorityManager(config_path=tmp_path / "auth.json")
        mgr.set_level(AuthorityLevel.BOUNDED)
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(log_path=Path("/dev/null")),
            authority_manager=mgr,
        )
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "hacktool"},
        )
        assert not result.allowed
        assert result.decision == "escalate"
        # Regression (audit 2026-06-01 #4): the level is carried STRUCTURALLY so
        # the escalation handler routes BOUNDED+dangerous to the approval queue.
        # Before the fix it was parsed from the reason string, which for BOUNDED
        # had no 'authority_level=' token -> the request silently fell through to
        # a plain block and never reached HITL.
        assert result.authority_level == "bounded"

    def test_known_safe_tool_allowed_at_bounded(self, tmp_path):
        """BOUNDED + known safe tool = ALLOW."""
        mgr = AuthorityManager(config_path=tmp_path / "auth.json")
        mgr.set_level(AuthorityLevel.BOUNDED)
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(log_path=Path("/dev/null")),
            authority_manager=mgr,
        )
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "web_fetch"},
        )
        assert result.allowed
        assert result.decision == "allow"

    def test_unknown_tool_dangerous_at_confirm(self, tmp_path):
        """CONFIRM + unknown tool = ESCALATE."""
        mgr = AuthorityManager(config_path=tmp_path / "auth.json")
        mgr.set_level(AuthorityLevel.CONFIRM)
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(log_path=Path("/dev/null")),
            authority_manager=mgr,
        )
        result = policy.check(
            action_type="effector",
            action_params={"tool_name": "hacktool"},
        )
        assert not result.allowed
        assert result.decision == "escalate"

    def test_unknown_tool_allowed_at_unrestricted(self):
        """UNRESTRICTED + unknown tool = ALLOW."""
        from agent_core.autonomy.policy_rules import (
            PolicyContext,
            rule_effector_authority,
        )

        result = rule_effector_authority(PolicyContext(
            action_type="effector",
            authority_level=AuthorityLevel.UNRESTRICTED.value,
            tool_name="hacktool",
            tool_dangerous=True,
        ))
        assert result is None


class TestStaleApprovals:

    def test_approve_after_expiry(self, tmp_path):
        """Cannot approve a request after it expired."""
        queue = ApprovalQueue(
            log_path=tmp_path / "q.jsonl",
            expiry_sec=0.01,  # 10ms
        )
        req = queue.submit(plan_id="p1", tool_name="exec", tool_args={})
        time.sleep(0.02)
        result = queue.approve(req.request_id)
        assert result is None

    def test_pickup_expired_impossible(self, tmp_path):
        """Expired request cannot be picked up even if status changed."""
        queue = ApprovalQueue(
            log_path=tmp_path / "q.jsonl",
            expiry_sec=0.01,
        )
        req = queue.submit(plan_id="p1", tool_name="exec", tool_args={})
        time.sleep(0.02)
        # Even if we somehow change status, get_approved_ready checks expiry
        ready = queue.get_approved_ready()
        assert ready is None

    def test_expired_cleared_from_pending(self, tmp_path):
        queue = ApprovalQueue(
            log_path=tmp_path / "q.jsonl",
            expiry_sec=0.01,
        )
        queue.submit(plan_id="p1", tool_name="exec", tool_args={})
        time.sleep(0.02)
        pending = queue.get_pending()
        assert len(pending) == 0


class TestDoubleApproval:

    def test_double_approve_idempotent(self, tmp_path):
        """Second approve returns None (already processed)."""
        queue = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req = queue.submit(plan_id="p1", tool_name="exec", tool_args={})
        first = queue.approve(req.request_id)
        assert first is not None
        second = queue.approve(req.request_id)
        assert second is None

    def test_approve_then_reject_idempotent(self, tmp_path):
        queue = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req = queue.submit(plan_id="p1", tool_name="exec", tool_args={})
        queue.approve(req.request_id)
        result = queue.reject(req.request_id)
        assert result is None  # already approved

    def test_reject_then_approve_idempotent(self, tmp_path):
        queue = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req = queue.submit(plan_id="p1", tool_name="exec", tool_args={})
        queue.reject(req.request_id)
        result = queue.approve(req.request_id)
        assert result is None  # already rejected


class TestConflictingRequests:

    def test_multiple_requests_same_tool(self, tmp_path):
        """Multiple pending requests for same tool should work."""
        queue = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req1 = queue.submit(plan_id="p1", tool_name="exec",
                            tool_args={"command": "ls"})
        req2 = queue.submit(plan_id="p2", tool_name="exec",
                            tool_args={"command": "df"})
        assert req1.request_id != req2.request_id
        assert len(queue.get_pending()) == 2

    def test_budget_handles_concurrent_same_tool(self):
        budget = ToolBudgetManager(tool_rate_limits={"exec": 5})
        budget.record_invocation("exec", success=True)
        budget.record_invocation("exec", success=True)
        ok, _ = budget.check_budget("exec")
        assert ok  # Still under limit


class TestAuthorityDowngradeDuringPending:

    def test_downgrade_rejects_all(self, tmp_path):
        """Authority downgrade rejects all pending requests."""
        queue = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        queue.submit(plan_id="p1", tool_name="exec", tool_args={})
        queue.submit(plan_id="p2", tool_name="write", tool_args={"path": "/tmp/x", "content": "y"})
        queue.submit(plan_id="p3", tool_name="read", tool_args={"path": "/tmp/y"})

        count = queue.reject_all_pending("authority_downgrade")
        assert count == 3
        assert len(queue.get_pending()) == 0

    def test_already_approved_not_affected(self, tmp_path):
        """Already approved requests are not rejected by downgrade."""
        queue = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        req = queue.submit(plan_id="p1", tool_name="exec", tool_args={})
        queue.approve(req.request_id)
        # Approved request should still be available
        count = queue.reject_all_pending("downgrade")
        assert count == 0
        ready = queue.get_approved_ready()
        assert ready is not None


class TestCascadeFailure:

    def test_three_failures_lock_tool(self):
        budget = ToolBudgetManager(
            max_consecutive_failures=3,
            failure_cooldown_sec=60.0,
        )
        for _ in range(3):
            budget.record_invocation("exec", success=False)
        assert budget.is_locked("exec")
        ok, reason = budget.check_budget("exec")
        assert not ok
        assert "tool_locked" in reason

    def test_lock_expires_allows_probe(self):
        budget = ToolBudgetManager(
            max_consecutive_failures=2,
            failure_cooldown_sec=0.01,
        )
        budget.record_invocation("exec", success=False)
        budget.record_invocation("exec", success=False)
        assert budget.is_locked("exec")
        time.sleep(0.02)
        ok, _ = budget.check_budget("exec")
        assert ok  # Probe allowed

    def test_probe_success_resets(self):
        budget = ToolBudgetManager(
            max_consecutive_failures=2,
            failure_cooldown_sec=0.01,
        )
        budget.record_invocation("exec", success=False)
        budget.record_invocation("exec", success=False)
        time.sleep(0.02)
        # Probe succeeds
        budget.record_invocation("exec", success=True)
        state = budget._states["exec"]
        assert state.consecutive_failures == 0
        assert state.backoff_multiplier == 1

    def test_probe_failure_re_locks_with_backoff(self):
        budget = ToolBudgetManager(
            max_consecutive_failures=2,
            failure_cooldown_sec=100.0,
        )
        budget.record_invocation("exec", success=False)
        budget.record_invocation("exec", success=False)  # locked
        state = budget._states["exec"]
        assert state.backoff_multiplier == 2

        # Simulate lock expiry
        state.locked_until = time.time() - 1
        # Probe fails
        budget.record_invocation("exec", success=False)  # re-locked
        assert state.backoff_multiplier == 4

    def test_duplicate_request_blocked(self):
        budget = ToolBudgetManager()
        args = {"command": "rm -rf /"}
        budget.record_request("exec", args)
        ok, reason = budget.check_budget("exec", tool_args=args)
        assert not ok
        assert "duplicate_request" in reason

    def test_different_tools_not_cascade(self):
        """Failure in one tool doesn't lock another."""
        budget = ToolBudgetManager(max_consecutive_failures=2)
        budget.record_invocation("exec", success=False)
        budget.record_invocation("exec", success=False)
        assert budget.is_locked("exec")
        assert not budget.is_locked("read")
