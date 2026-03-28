"""
Execution Budget - timeout and resource limits for LLM calls.

Phase 3 of Stabilization Roadmap: deterministic model orchestration under pressure.

Problem: ollama_lib.chat() has no timeout - can block indefinitely.
Solution: wrap calls with ThreadPoolExecutor deadline.

Usage:
    from agent_core.llm.execution_budget import call_with_timeout

    result = call_with_timeout(
        lambda: ollama_lib.chat(model="llama3.1:8b", ...),
        timeout_sec=120.0,
        label="planner inference",
    )
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Default timeouts per model role (seconds)
DEFAULT_TIMEOUTS = {
    "executor": 120.0,     # llama3.1:8b - main brain, sometimes slow on complex prompts
    "planner": 180.0,      # qwen3:8b - reasoning can be slow
    "coder": 120.0,        # qwen2.5-coder:7b
    "memory": 30.0,        # nomic-embed-text - should be fast
    "external": 45.0,      # NIM API (already has own timeout, this is belt+suspenders)
    "encyclopedia": 120.0, # Codex CLI (already has subprocess timeout)
    "default": 120.0,      # Unknown roles
}

# Shared executor for timeout wrapping (daemon threads, won't block shutdown)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="llm-timeout")


def get_timeout_for_role(role: str) -> float:
    """Get timeout in seconds for a model role."""
    return DEFAULT_TIMEOUTS.get(role.lower(), DEFAULT_TIMEOUTS["default"])


def call_with_timeout(
    fn: Callable[[], T],
    timeout_sec: float = 120.0,
    label: str = "llm_call",
) -> T:
    """
    Execute a callable with a timeout deadline.

    If the call exceeds timeout_sec, raises TimeoutError.
    The underlying thread continues running (Ollama has no cancellation),
    but the caller is unblocked.

    Args:
        fn: Zero-arg callable to execute.
        timeout_sec: Maximum seconds to wait.
        label: Human-readable label for logging.

    Returns:
        Whatever fn() returns.

    Raises:
        TimeoutError: If fn() exceeds deadline.
        Any exception that fn() raises.
    """
    future = _executor.submit(fn)
    try:
        return future.result(timeout=timeout_sec)
    except FuturesTimeout:
        logger.warning(
            f"[BUDGET] {label} exceeded {timeout_sec:.0f}s timeout"
        )
        raise TimeoutError(
            f"LLM call '{label}' exceeded {timeout_sec:.0f}s deadline"
        )


@dataclass
class EpisodeBudget:
    """
    Per-episode resource budget.

    Tracks cumulative LLM usage within one planner cycle.
    Prevents runaway episodes from consuming too many resources.
    """
    max_llm_calls: int = 10           # Max LLM calls per episode
    max_total_latency_ms: float = 300_000  # 5 minutes total LLM time per episode
    max_retries: int = 3              # Max retries across all calls

    # Counters (reset per episode)
    llm_calls: int = 0
    total_latency_ms: float = 0.0
    retries: int = 0

    def can_call(self) -> bool:
        """Check if budget allows another LLM call."""
        return (
            self.llm_calls < self.max_llm_calls
            and self.total_latency_ms < self.max_total_latency_ms
        )

    def can_retry(self) -> bool:
        """Check if budget allows a retry."""
        return self.retries < self.max_retries

    def record_call(self, latency_ms: float) -> None:
        """Record an LLM call against the budget."""
        self.llm_calls += 1
        self.total_latency_ms += latency_ms

    def record_retry(self) -> None:
        """Record a retry against the budget."""
        self.retries += 1

    def reset(self) -> None:
        """Reset counters for a new episode."""
        self.llm_calls = 0
        self.total_latency_ms = 0.0
        self.retries = 0

    def summary(self) -> Dict[str, Any]:
        """Budget usage summary."""
        return {
            "llm_calls": f"{self.llm_calls}/{self.max_llm_calls}",
            "latency_ms": f"{self.total_latency_ms:.0f}/{self.max_total_latency_ms:.0f}",
            "retries": f"{self.retries}/{self.max_retries}",
            "exhausted": not self.can_call(),
        }
