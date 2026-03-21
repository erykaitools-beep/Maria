"""
Rate Limiter for K7 Autonomy Policy.

Per-action-type sliding window rate limits.
Prevents runaway loops (e.g. 1430 fetch attempts in 24h).

Kontrakt: docs/CONTRACTS.md - Kontrakt 7: Autonomy Policy
"""

import logging
import time
from collections import deque
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# Default hourly limits per action type value.
# None means unlimited (FREE actions).
DEFAULT_RATE_LIMITS: Dict[str, int] = {
    "fetch": 5,
    "maintenance": 10,
    "experiment": 1,  # K11: max 1 experiment per 6h (window override below)
}

# Sliding window size
WINDOW_SEC = 3600  # 1 hour


class ActionRateLimiter:
    """
    Sliding-window rate limiter per action type.

    Tracks execution timestamps and blocks when hourly limit exceeded.
    """

    def __init__(
        self,
        limits: Optional[Dict[str, int]] = None,
        window_sec: float = WINDOW_SEC,
    ):
        """
        Args:
            limits: {action_type_value: max_per_window}. None = use defaults.
            window_sec: Sliding window size in seconds (default 3600).
        """
        self._limits = dict(limits) if limits else dict(DEFAULT_RATE_LIMITS)
        self._window_sec = window_sec
        # {action_type_value: deque of timestamps}
        self._history: Dict[str, deque] = {}

    def check(
        self, action_type_value: str, now: Optional[float] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if action is within rate limit.

        Args:
            action_type_value: ActionType.value string
            now: Current timestamp (default: time.time())

        Returns:
            (allowed, reason). reason is None if allowed.
        """
        limit = self._limits.get(action_type_value)
        if limit is None:
            return True, None

        now = now or time.time()
        self._prune(action_type_value, now)

        history = self._history.get(action_type_value, deque())
        if len(history) >= limit:
            oldest = history[0]
            wait_sec = oldest + self._window_sec - now
            reason = (
                f"rate_limit: {action_type_value} "
                f"{len(history)}/{limit} per {self._window_sec}s "
                f"(next slot in {wait_sec:.0f}s)"
            )
            return False, reason

        return True, None

    def record(
        self, action_type_value: str, now: Optional[float] = None
    ) -> None:
        """
        Record an action execution.

        Args:
            action_type_value: ActionType.value string
            now: Current timestamp (default: time.time())
        """
        now = now or time.time()
        if action_type_value not in self._history:
            self._history[action_type_value] = deque()
        self._history[action_type_value].append(now)

    def get_remaining(
        self, action_type_value: str, now: Optional[float] = None
    ) -> Optional[int]:
        """
        Get remaining executions allowed in current window.

        Returns:
            Remaining count, or None if unlimited.
        """
        limit = self._limits.get(action_type_value)
        if limit is None:
            return None

        now = now or time.time()
        self._prune(action_type_value, now)
        used = len(self._history.get(action_type_value, deque()))
        return max(0, limit - used)

    def get_stats(self) -> Dict[str, Dict]:
        """Get rate limiter statistics for all tracked action types."""
        now = time.time()
        stats = {}
        for action, limit in self._limits.items():
            self._prune(action, now)
            used = len(self._history.get(action, deque()))
            stats[action] = {
                "limit": limit,
                "used": used,
                "remaining": max(0, limit - used),
                "window_sec": self._window_sec,
            }
        return stats

    def _prune(self, action_type_value: str, now: float) -> None:
        """Remove entries outside the sliding window."""
        if action_type_value not in self._history:
            return
        cutoff = now - self._window_sec
        history = self._history[action_type_value]
        while history and history[0] < cutoff:
            history.popleft()
