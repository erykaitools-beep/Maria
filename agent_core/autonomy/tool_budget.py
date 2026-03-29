"""
Per-Tool Budget Manager for Effector Safety (Phase 5).

Provides granular rate limiting and anti-cascade protection per tool,
separate from K7's global ActionRateLimiter (which tracks per action type).

Anti-cascade features:
- Per-tool rate limits (from AuthorityConfig)
- Consecutive failure locking with exponential backoff
- Duplicate request detection (same tool+args within dedup window)

ADR-026: Effector Safety Envelope.
"""

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_WINDOW_SEC = 3600.0  # 1 hour sliding window
MAX_BACKOFF_SEC = 3600.0     # Max 1 hour cooldown
DEDUP_WINDOW_SEC = 10.0      # Same tool+args within 10s = duplicate


@dataclass
class ToolBudgetState:
    """Per-tool tracking state."""
    tool_name: str
    invocation_timestamps: List[float] = field(default_factory=list)
    consecutive_failures: int = 0
    last_failure_ts: Optional[float] = None
    locked_until: Optional[float] = None  # None = not locked
    backoff_multiplier: int = 1           # doubles on each lock


class ToolBudgetManager:
    """
    Per-tool rate limits and anti-cascade guards.

    Thread-safe. Works alongside K7 ActionRateLimiter.
    Both must allow for an action to proceed.
    """

    def __init__(
        self,
        tool_rate_limits: Optional[Dict[str, int]] = None,
        failure_cooldown_sec: float = 300.0,
        max_consecutive_failures: int = 3,
        window_sec: float = DEFAULT_WINDOW_SEC,
    ):
        self._rate_limits = tool_rate_limits or {}
        self._failure_cooldown_sec = failure_cooldown_sec
        self._max_consecutive_failures = max_consecutive_failures
        self._window_sec = window_sec
        self._lock = threading.Lock()
        self._states: Dict[str, ToolBudgetState] = {}
        self._last_request_hash: Optional[str] = None
        self._last_request_ts: float = 0.0

    def _get_state(self, tool_name: str) -> ToolBudgetState:
        """Get or create state for a tool (must hold lock)."""
        if tool_name not in self._states:
            self._states[tool_name] = ToolBudgetState(tool_name=tool_name)
        return self._states[tool_name]

    def check_budget(
        self, tool_name: str, tool_args: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a tool invocation is allowed by budget.

        Returns:
            (allowed, reason) - reason is None if allowed, else explanation
        """
        with self._lock:
            state = self._get_state(tool_name)
            now = time.time()

            # Check 1: Is tool locked (failure cooldown)?
            if state.locked_until is not None:
                if now < state.locked_until:
                    remaining = state.locked_until - now
                    return False, (
                        f"tool_locked: {tool_name} locked for "
                        f"{remaining:.0f}s after {state.consecutive_failures} failures"
                    )
                else:
                    # Lock expired - allow one probe attempt
                    logger.info(
                        "[ToolBudget] Lock expired for %s, allowing probe",
                        tool_name,
                    )
                    state.locked_until = None
                    # Don't reset consecutive_failures yet - wait for success

            # Check 2: Rate limit
            limit = self._rate_limits.get(tool_name, 10)  # default 10/h
            # Clean old timestamps
            cutoff = now - self._window_sec
            state.invocation_timestamps = [
                ts for ts in state.invocation_timestamps if ts > cutoff
            ]
            if len(state.invocation_timestamps) >= limit:
                return False, (
                    f"rate_limited: {tool_name} at "
                    f"{len(state.invocation_timestamps)}/{limit} per "
                    f"{self._window_sec:.0f}s window"
                )

            # Check 3: Duplicate request detection
            if tool_args is not None:
                request_hash = self._hash_request(tool_name, tool_args)
                if (request_hash == self._last_request_hash
                        and (now - self._last_request_ts) < DEDUP_WINDOW_SEC):
                    return False, (
                        f"duplicate_request: same {tool_name} request "
                        f"within {DEDUP_WINDOW_SEC:.0f}s"
                    )

        return True, None

    def record_invocation(self, tool_name: str, success: bool) -> None:
        """
        Record a tool invocation outcome.

        On failure: increment consecutive counter, potentially lock.
        On success: reset counter and backoff.
        """
        with self._lock:
            state = self._get_state(tool_name)
            now = time.time()

            # Record timestamp for rate limiting
            state.invocation_timestamps.append(now)

            if success:
                state.consecutive_failures = 0
                state.last_failure_ts = None
                state.backoff_multiplier = 1
                state.locked_until = None
            else:
                state.consecutive_failures += 1
                state.last_failure_ts = now

                if state.consecutive_failures >= self._max_consecutive_failures:
                    # Lock with exponential backoff
                    cooldown = min(
                        self._failure_cooldown_sec * state.backoff_multiplier,
                        MAX_BACKOFF_SEC,
                    )
                    state.locked_until = now + cooldown
                    state.backoff_multiplier = min(
                        state.backoff_multiplier * 2, 12  # max 12x
                    )
                    logger.warning(
                        "[ToolBudget] Locking %s for %.0fs "
                        "(%d consecutive failures, backoff=%dx)",
                        tool_name, cooldown,
                        state.consecutive_failures,
                        state.backoff_multiplier,
                    )

    def record_request(
        self, tool_name: str, tool_args: Dict[str, Any]
    ) -> None:
        """Record a request for dedup tracking."""
        with self._lock:
            self._last_request_hash = self._hash_request(tool_name, tool_args)
            self._last_request_ts = time.time()

    def is_locked(self, tool_name: str) -> bool:
        """Check if a tool is currently locked."""
        with self._lock:
            state = self._get_state(tool_name)
            if state.locked_until is None:
                return False
            return time.time() < state.locked_until

    def get_stats(self) -> Dict[str, Any]:
        """Get budget statistics for all tracked tools."""
        with self._lock:
            now = time.time()
            stats = {}
            for name, state in self._states.items():
                cutoff = now - self._window_sec
                active = [ts for ts in state.invocation_timestamps if ts > cutoff]
                limit = self._rate_limits.get(name, 10)
                stats[name] = {
                    "invocations_this_window": len(active),
                    "rate_limit": limit,
                    "consecutive_failures": state.consecutive_failures,
                    "locked": (
                        state.locked_until is not None
                        and now < state.locked_until
                    ),
                    "locked_remaining_sec": max(
                        0, (state.locked_until or 0) - now
                    ),
                    "backoff_multiplier": state.backoff_multiplier,
                }
            return stats

    @staticmethod
    def _hash_request(tool_name: str, tool_args: Dict) -> str:
        """Create a hash of tool_name + args for dedup."""
        raw = json.dumps({"t": tool_name, "a": tool_args}, sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()
