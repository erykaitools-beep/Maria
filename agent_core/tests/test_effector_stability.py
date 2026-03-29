"""
Phase 6: Long-Duration Stability Tests for Effector Safety.

Scenario tests (all mocked, no real OpenClaw):
- Marathon: 100 cycles with BOUNDED authority
- Authority level transitions
- Concurrent access (4 threads)
- Clock simulation for window/expiry
"""

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_core.autonomy.authority_level import AuthorityLevel, AuthorityManager
from agent_core.autonomy.approval_queue import ApprovalQueue
from agent_core.autonomy.tool_budget import ToolBudgetManager
from agent_core.autonomy import AutonomyPolicy
from agent_core.autonomy.escalation import EscalationHandler


class TestMarathonRun:
    """Simulate many cycles of effector usage at BOUNDED level."""

    def test_100_cycles_safe_tools(self, tmp_path):
        """100 cycles of safe tool requests at BOUNDED."""
        mgr = AuthorityManager(config_path=tmp_path / "auth.json")
        mgr.set_level(AuthorityLevel.BOUNDED)
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(log_path=Path("/dev/null")),
            authority_manager=mgr,
        )
        budget = ToolBudgetManager(
            tool_rate_limits={"web_fetch": 200, "read": 200},
        )
        queue = ApprovalQueue(log_path=tmp_path / "q.jsonl")

        allowed_count = 0
        blocked_count = 0

        for i in range(100):
            tool = "web_fetch" if i % 2 == 0 else "read"
            result = policy.check(
                action_type="effector",
                action_params={"tool_name": tool},
            )
            if result.allowed:
                ok, _ = budget.check_budget(tool)
                if ok:
                    budget.record_invocation(tool, success=True)
                    allowed_count += 1
                else:
                    blocked_count += 1
            else:
                blocked_count += 1

            # Expire stale queue entries periodically
            if i % 10 == 0:
                queue.expire_stale()

        assert allowed_count == 100
        assert blocked_count == 0

    def test_100_cycles_mixed_tools(self, tmp_path):
        """100 cycles mixing safe and dangerous tools."""
        mgr = AuthorityManager(config_path=tmp_path / "auth.json")
        mgr.set_level(AuthorityLevel.BOUNDED)
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(log_path=Path("/dev/null")),
            authority_manager=mgr,
        )
        queue = ApprovalQueue(log_path=tmp_path / "q.jsonl")

        auto_exec = 0
        escalated = 0
        tools = ["web_fetch", "exec", "read", "write", "web_search", "message"]

        for i in range(100):
            tool = tools[i % len(tools)]
            result = policy.check(
                action_type="effector",
                action_params={"tool_name": tool},
            )
            if result.allowed:
                auto_exec += 1
            else:
                escalated += 1
                # Simulate some approvals
                if i % 3 == 0:
                    req = queue.submit(
                        plan_id=f"p{i}",
                        tool_name=tool,
                        tool_args={},
                    )
                    queue.approve(req.request_id)
                    queue.get_approved_ready()

        # Safe tools (web_fetch, read, web_search) = 3/6 of tools
        # Dangerous (exec, write, message) = 3/6 -> escalated
        assert auto_exec > 0
        assert escalated > 0
        assert auto_exec + escalated == 100

    def test_rate_limit_across_cycles(self):
        """Verify rate limits hold across many invocations."""
        budget = ToolBudgetManager(
            tool_rate_limits={"exec": 5},
            window_sec=3600,
        )
        blocked_at = None
        for i in range(20):
            ok, _ = budget.check_budget("exec")
            if not ok:
                blocked_at = i
                break
            budget.record_invocation("exec", success=True)

        assert blocked_at == 5  # Blocked after 5 invocations


class TestAuthorityTransitions:
    """Test authority level upgrades and downgrades."""

    def test_observe_to_bounded_and_back(self, tmp_path):
        mgr = AuthorityManager(config_path=tmp_path / "auth.json")
        policy = AutonomyPolicy(
            escalation_handler=EscalationHandler(log_path=Path("/dev/null")),
            authority_manager=mgr,
        )
        queue = ApprovalQueue(log_path=tmp_path / "q.jsonl")

        # Start: OBSERVE - blocked
        r = policy.check(action_type="effector", action_params={"tool_name": "read"})
        assert not r.allowed

        # Upgrade to BOUNDED
        mgr.set_level(AuthorityLevel.BOUNDED)
        r = policy.check(action_type="effector", action_params={"tool_name": "read"})
        assert r.allowed

        # Submit a request for dangerous tool
        req = queue.submit(plan_id="p1", tool_name="exec", tool_args={})

        # Downgrade to OBSERVE
        mgr.set_level(AuthorityLevel.OBSERVE)
        rejected = queue.reject_all_pending("downgrade")
        assert rejected == 1

        # Now read is blocked again
        r = policy.check(action_type="effector", action_params={"tool_name": "read"})
        assert not r.allowed

    def test_config_survives_reload(self, tmp_path):
        """Authority config persists and reloads."""
        path = tmp_path / "auth.json"
        mgr1 = AuthorityManager(config_path=path)
        mgr1.set_level(AuthorityLevel.CONFIRM)

        mgr2 = AuthorityManager(config_path=path)
        assert mgr2.get_level() == AuthorityLevel.CONFIRM

    def test_queue_not_leaked_across_transitions(self, tmp_path):
        """Pending approvals are cleaned on downgrade."""
        queue = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        for i in range(5):
            queue.submit(plan_id=f"p{i}", tool_name="exec", tool_args={})
        assert len(queue.get_pending()) == 5

        queue.reject_all_pending("downgrade")
        assert len(queue.get_pending()) == 0
        # Queue is still functional
        req = queue.submit(plan_id="pnew", tool_name="read", tool_args={})
        assert req.status == "pending"


class TestConcurrentAccess:
    """Thread safety stress tests."""

    def test_concurrent_approvals(self, tmp_path):
        """Multiple threads approving/rejecting simultaneously."""
        queue = ApprovalQueue(log_path=tmp_path / "q.jsonl")
        requests = []
        for i in range(10):
            req = queue.submit(plan_id=f"p{i}", tool_name="exec", tool_args={})
            requests.append(req)

        results = []
        errors = []

        def approve_worker(req):
            try:
                result = queue.approve(req.request_id)
                results.append(("approved", req.request_id, result))
            except Exception as e:
                errors.append(e)

        def reject_worker(req):
            try:
                result = queue.reject(req.request_id)
                results.append(("rejected", req.request_id, result))
            except Exception as e:
                errors.append(e)

        threads = []
        for i, req in enumerate(requests):
            if i % 2 == 0:
                t = threading.Thread(target=approve_worker, args=(req,))
            else:
                t = threading.Thread(target=reject_worker, args=(req,))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # Each request should have been processed exactly once
        processed = [r for r in results if r[2] is not None]
        assert len(processed) == 10

    def test_concurrent_budget_check(self):
        """Multiple threads checking and recording budgets."""
        budget = ToolBudgetManager(tool_rate_limits={"exec": 100})
        errors = []

        def worker(idx):
            try:
                for _ in range(20):
                    budget.check_budget("exec")
                    budget.record_invocation("exec", success=True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        stats = budget.get_stats()
        assert stats["exec"]["invocations_this_window"] == 80  # 4 * 20


class TestClockSimulation:
    """Test time-dependent behavior without real delays."""

    def test_approval_expiry_simulation(self, tmp_path):
        """Fast-forward time to test expiry."""
        queue = ApprovalQueue(
            log_path=tmp_path / "q.jsonl",
            expiry_sec=300,  # 5 min
        )
        req = queue.submit(plan_id="p1", tool_name="exec", tool_args={})

        # Manually set created_at to 6 minutes ago
        req.created_at = time.time() - 360
        expired = queue.expire_stale()
        assert expired == 1

    def test_budget_window_simulation(self):
        """Fast-forward rate limit window."""
        budget = ToolBudgetManager(
            tool_rate_limits={"exec": 2},
            window_sec=3600,
        )
        budget.record_invocation("exec", success=True)
        budget.record_invocation("exec", success=True)

        # At limit
        ok, _ = budget.check_budget("exec")
        assert not ok

        # Manually expire timestamps
        state = budget._states["exec"]
        state.invocation_timestamps = [t - 3601 for t in state.invocation_timestamps]

        # Now within limit again
        ok, _ = budget.check_budget("exec")
        assert ok

    def test_lock_expiry_simulation(self):
        """Fast-forward tool lock."""
        budget = ToolBudgetManager(
            max_consecutive_failures=2,
            failure_cooldown_sec=300,
        )
        budget.record_invocation("exec", success=False)
        budget.record_invocation("exec", success=False)
        assert budget.is_locked("exec")

        # Fast-forward past lock
        state = budget._states["exec"]
        state.locked_until = time.time() - 1

        assert not budget.is_locked("exec")
        ok, _ = budget.check_budget("exec")
        assert ok  # probe allowed
