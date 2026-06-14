"""
Execution Budget - timeout and resource limits for LLM calls.

Phase 3 of Stabilization Roadmap: deterministic model orchestration under pressure.

Problem: ollama_lib.chat() has no timeout - can block indefinitely.
Two complementary defenses, both needed (2026-06-02 freeze taught us why):
  1. call_with_timeout(): a ThreadPoolExecutor deadline that unblocks the CALLER.
     It cannot cancel the in-flight request -- the orphaned call keeps running.
  2. get_ollama_client(): a shared ollama.Client with a real httpx read-timeout
     so the socket is torn down and the orphaned call actually DIES, freeing its
     pool slot. Every daemon-path ollama call must go through this client.

Usage:
    from agent_core.llm.execution_budget import call_with_timeout, get_ollama_client

    result = call_with_timeout(
        lambda: get_ollama_client().chat(model="llama3.1:8b", ...),
        timeout_sec=120.0,
        label="planner inference",
    )
"""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, TypeVar

try:
    import ollama as _ollama_lib
except Exception:  # pragma: no cover - ollama always present in prod
    _ollama_lib = None

try:
    from maria_core.sys.config import OLLAMA_HTTP_TIMEOUT as _OLLAMA_HTTP_TIMEOUT
except Exception:
    _OLLAMA_HTTP_TIMEOUT = int(os.environ.get("OLLAMA_HTTP_TIMEOUT", "240"))

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

# Shared executor for timeout wrapping.
# UWAGA (audyt 2026-06-12): od Pythona 3.9 watki ThreadPoolExecutor sa
# NIE-daemonowe i interpreter CZEKA na nie przy wyjsciu — stary komentarz
# "daemon threads, won't block shutdown" byl prawdziwy tylko do 3.8.
# Skutek: /restart trafiajacy w trwajace wywolanie LLM wisial ~191 s
# ("Shutdown complete" 17:43:37 -> exit 17:46:48). maria.py domyka to
# przez wait_for_llm_workers() + twarde wyjscie PO checkpoincie.
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="llm-timeout")

# Licznik wywolan w locie (submit -> done-callback); patrz wait_for_llm_workers.
_inflight_lock = threading.Lock()
_inflight = 0


def _track_submitted() -> None:
    global _inflight
    with _inflight_lock:
        _inflight += 1


def _track_done(_future) -> None:
    global _inflight
    with _inflight_lock:
        _inflight -= 1


def llm_workers_busy() -> int:
    """Number of LLM calls currently submitted to the timeout pool."""
    with _inflight_lock:
        return _inflight


def wait_for_llm_workers(grace_sec: float = 15.0) -> bool:
    """Give in-flight LLM calls a bounded chance to finish before exit.

    The pool threads are non-daemon (Python 3.9+), so a plain sys.exit()
    waits the FULL residual LLM timeout for any abandoned call -- nothing
    durable depends on that result (the process is exiting; the reply is
    discarded). Poll until the pool is idle or the grace period ends.

    Returns True when idle, False when a call is still running after grace.
    """
    deadline = time.monotonic() + grace_sec
    while time.monotonic() < deadline:
        if llm_workers_busy() == 0:
            return True
        time.sleep(0.2)
    return llm_workers_busy() == 0


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
    _track_submitted()
    future.add_done_callback(_track_done)
    try:
        return future.result(timeout=timeout_sec)
    except FuturesTimeout:
        logger.warning(
            f"[BUDGET] {label} exceeded {timeout_sec:.0f}s timeout"
        )
        raise TimeoutError(
            f"LLM call '{label}' exceeded {timeout_sec:.0f}s deadline"
        )


# ---------------------------------------------------------------------------
# Shared timeout-aware Ollama client
# ---------------------------------------------------------------------------
# call_with_timeout() above unblocks the CALLER but cannot cancel the in-flight
# HTTP request -- the orphaned ollama.chat()/generate() keeps running and holds
# one of the 2 worker slots. The 2026-06-02 freeze was exactly this: the router
# scheduler branch (ask_as_role) and ModelScheduler load/unload called the bare
# module-level ollama client (timeout=None == wait forever), so a wedged Ollama
# left immortal zombies that starved the pool until the loop froze for 10.5h.
# This shared client gives every such call a real httpx read-timeout, so the
# socket is torn down and the zombie dies. It pairs with call_with_timeout: the
# role budget unblocks the caller first (graceful degrade), this kills the zombie
# second, and the 300s watchdog hard-restarts only if both somehow fail. The
# timeout (OLLAMA_HTTP_TIMEOUT, default 240s) is sized ABOVE every role budget
# (so degrade fires first) and BELOW the watchdog (so this fires before restart).
_ollama_client = None
_ollama_client_lock = threading.Lock()


def get_ollama_client():
    """Process-wide ollama client with a real HTTP read-timeout.

    Every daemon-path ollama.chat()/generate()/ps() must go through this so a
    wedged Ollama raises (httpx timeout) instead of hanging forever. Returns the
    bare module on an older lib lacking Client(timeout=...), or None only if the
    ollama library is entirely absent.
    """
    global _ollama_client
    if _ollama_lib is None:
        return None
    if _ollama_client is None:
        with _ollama_client_lock:
            if _ollama_client is None:
                try:
                    _ollama_client = _ollama_lib.Client(timeout=_OLLAMA_HTTP_TIMEOUT)
                except Exception as e:  # pragma: no cover - very old ollama lib
                    logger.warning(
                        "[BUDGET] ollama.Client(timeout) unavailable, "
                        "falling back to module API (no timeout): %s", e
                    )
                    _ollama_client = _ollama_lib
    return _ollama_client


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
