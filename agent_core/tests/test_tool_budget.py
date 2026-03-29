"""
Tests for Phase 5: Per-Tool Budget Manager + Anti-Cascade Guards.

Tests:
- Per-tool rate limits
- Consecutive failure locking
- Exponential backoff on repeated failures
- Lock expiry and probe
- Duplicate request detection
- Thread safety
"""

import time
import threading
from unittest.mock import patch

import pytest

from agent_core.autonomy.tool_budget import (
    ToolBudgetManager,
    ToolBudgetState,
    DEDUP_WINDOW_SEC,
    MAX_BACKOFF_SEC,
)


# ---- Basic rate limiting ----

class TestToolBudgetRateLimits:

    def test_within_limit_allowed(self):
        mgr = ToolBudgetManager(tool_rate_limits={"exec": 5})
        for _ in range(5):
            ok, reason = mgr.check_budget("exec")
            assert ok
            mgr.record_invocation("exec", success=True)

    def test_over_limit_blocked(self):
        mgr = ToolBudgetManager(tool_rate_limits={"exec": 3})
        for _ in range(3):
            mgr.record_invocation("exec", success=True)
        ok, reason = mgr.check_budget("exec")
        assert not ok
        assert "rate_limited" in reason

    def test_default_limit_used_for_unknown_tool(self):
        mgr = ToolBudgetManager(tool_rate_limits={})
        # Default is 10/h
        for _ in range(10):
            mgr.record_invocation("unknown", success=True)
        ok, reason = mgr.check_budget("unknown")
        assert not ok

    def test_different_tools_independent(self):
        mgr = ToolBudgetManager(tool_rate_limits={"exec": 2, "read": 5})
        mgr.record_invocation("exec", success=True)
        mgr.record_invocation("exec", success=True)
        # exec is at limit
        ok, _ = mgr.check_budget("exec")
        assert not ok
        # read still has budget
        ok, _ = mgr.check_budget("read")
        assert ok

    def test_window_expiry(self):
        mgr = ToolBudgetManager(
            tool_rate_limits={"exec": 2},
            window_sec=0.05,  # 50ms window
        )
        mgr.record_invocation("exec", success=True)
        mgr.record_invocation("exec", success=True)
        ok, _ = mgr.check_budget("exec")
        assert not ok
        # Wait for window to expire
        time.sleep(0.06)
        ok, _ = mgr.check_budget("exec")
        assert ok


# ---- Consecutive failure locking ----

class TestToolBudgetFailureLocking:

    def test_lock_after_max_failures(self):
        mgr = ToolBudgetManager(
            max_consecutive_failures=3,
            failure_cooldown_sec=10.0,
        )
        for _ in range(3):
            mgr.record_invocation("exec", success=False)
        assert mgr.is_locked("exec")
        ok, reason = mgr.check_budget("exec")
        assert not ok
        assert "tool_locked" in reason

    def test_no_lock_below_threshold(self):
        mgr = ToolBudgetManager(max_consecutive_failures=3)
        mgr.record_invocation("exec", success=False)
        mgr.record_invocation("exec", success=False)
        assert not mgr.is_locked("exec")

    def test_success_resets_failure_counter(self):
        mgr = ToolBudgetManager(max_consecutive_failures=3)
        mgr.record_invocation("exec", success=False)
        mgr.record_invocation("exec", success=False)
        mgr.record_invocation("exec", success=True)  # reset
        mgr.record_invocation("exec", success=False)
        mgr.record_invocation("exec", success=False)
        assert not mgr.is_locked("exec")

    def test_lock_expiry_allows_probe(self):
        mgr = ToolBudgetManager(
            max_consecutive_failures=2,
            failure_cooldown_sec=0.02,  # 20ms
        )
        mgr.record_invocation("exec", success=False)
        mgr.record_invocation("exec", success=False)
        assert mgr.is_locked("exec")
        time.sleep(0.03)
        # Lock expired, probe allowed
        ok, reason = mgr.check_budget("exec")
        assert ok

    def test_exponential_backoff(self):
        mgr = ToolBudgetManager(
            max_consecutive_failures=2,
            failure_cooldown_sec=100.0,
        )
        # First lock: 100s * 1 = 100s, backoff doubles to 2
        mgr.record_invocation("exec", success=False)
        mgr.record_invocation("exec", success=False)
        state = mgr._states["exec"]
        assert state.backoff_multiplier == 2
        assert state.locked_until is not None

        # Simulate lock expiry, then fail again
        # consecutive_failures stays at 2, so next failure (3) triggers lock again
        state.locked_until = time.time() - 1  # expired
        mgr.record_invocation("exec", success=False)  # 3rd -> lock (200s, backoff=4)
        assert state.backoff_multiplier == 4
        # Backoff increased from 2 to 4
        state.locked_until = time.time() - 1  # expire again
        mgr.record_invocation("exec", success=False)  # 4th -> lock (400s, backoff=8)
        assert state.backoff_multiplier == 8

    def test_success_resets_backoff(self):
        mgr = ToolBudgetManager(
            max_consecutive_failures=2,
            failure_cooldown_sec=100.0,
        )
        mgr.record_invocation("exec", success=False)
        mgr.record_invocation("exec", success=False)
        state = mgr._states["exec"]
        assert state.backoff_multiplier == 2
        mgr.record_invocation("exec", success=True)
        assert state.backoff_multiplier == 1
        assert state.locked_until is None

    def test_max_backoff_cap(self):
        mgr = ToolBudgetManager(
            max_consecutive_failures=1,
            failure_cooldown_sec=1000.0,
        )
        # Keep failing to ramp up backoff
        for _ in range(20):
            state = mgr._states.get("exec")
            if state and state.locked_until:
                state.locked_until = time.time() - 1  # expire
            mgr.record_invocation("exec", success=False)

        state = mgr._states["exec"]
        # Verify cooldown doesn't exceed MAX_BACKOFF_SEC
        if state.locked_until:
            remaining = state.locked_until - time.time()
            assert remaining <= MAX_BACKOFF_SEC + 1  # +1 for timing


# ---- Duplicate request detection ----

class TestToolBudgetDedup:

    def test_duplicate_blocked(self):
        mgr = ToolBudgetManager()
        args = {"command": "ls -la"}
        mgr.record_request("exec", args)
        ok, reason = mgr.check_budget("exec", tool_args=args)
        assert not ok
        assert "duplicate_request" in reason

    def test_different_args_allowed(self):
        mgr = ToolBudgetManager()
        mgr.record_request("exec", {"command": "ls"})
        ok, _ = mgr.check_budget("exec", tool_args={"command": "df -h"})
        assert ok

    def test_different_tool_allowed(self):
        mgr = ToolBudgetManager()
        mgr.record_request("exec", {"command": "ls"})
        ok, _ = mgr.check_budget("read", tool_args={"command": "ls"})
        assert ok

    def test_dedup_expires(self):
        mgr = ToolBudgetManager()
        args = {"command": "ls"}
        mgr.record_request("exec", args)
        # Manually expire
        mgr._last_request_ts = time.time() - DEDUP_WINDOW_SEC - 1
        ok, _ = mgr.check_budget("exec", tool_args=args)
        assert ok

    def test_no_args_no_dedup(self):
        mgr = ToolBudgetManager()
        mgr.record_request("exec", {"command": "ls"})
        # check_budget without tool_args skips dedup
        ok, _ = mgr.check_budget("exec")
        assert ok


# ---- Stats ----

class TestToolBudgetStats:

    def test_stats_empty(self):
        mgr = ToolBudgetManager()
        assert mgr.get_stats() == {}

    def test_stats_after_usage(self):
        mgr = ToolBudgetManager(tool_rate_limits={"exec": 5})
        mgr.record_invocation("exec", success=True)
        mgr.record_invocation("exec", success=False)
        stats = mgr.get_stats()
        assert "exec" in stats
        assert stats["exec"]["invocations_this_window"] == 2
        assert stats["exec"]["consecutive_failures"] == 1
        assert stats["exec"]["rate_limit"] == 5

    def test_is_locked_false_default(self):
        mgr = ToolBudgetManager()
        assert not mgr.is_locked("exec")


# ---- Thread safety ----

class TestToolBudgetThreadSafety:

    def test_concurrent_check_and_record(self):
        mgr = ToolBudgetManager(tool_rate_limits={"exec": 100})
        errors = []

        def worker(idx):
            try:
                for _ in range(10):
                    ok, _ = mgr.check_budget("exec")
                    mgr.record_invocation("exec", success=True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        stats = mgr.get_stats()
        assert stats["exec"]["invocations_this_window"] == 40
