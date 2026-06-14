"""Bounded-farewell tests for the llm-timeout pool (audyt 2026-06-12).

Since Python 3.9 ThreadPoolExecutor threads are NON-daemon, so interpreter
exit waits for any abandoned in-flight LLM call (observed 191 s on
2026-06-12: /restart hit a reflection session; "Shutdown complete" at
17:43:37, real exit 17:46:48). maria._finalize_exit gives stragglers a
short grace via wait_for_llm_workers, then exits hard -- AFTER the
consciousness checkpoint, so nothing durable is at risk.
"""

import threading
import time

import pytest

from agent_core.llm.execution_budget import (
    call_with_timeout,
    llm_workers_busy,
    wait_for_llm_workers,
)


class TestWaitForLlmWorkers:
    def test_idle_pool_returns_true_immediately(self):
        t0 = time.monotonic()
        assert wait_for_llm_workers(grace_sec=5.0) is True
        assert time.monotonic() - t0 < 1.0  # nie czeka pelnej gracji

    def test_abandoned_call_holds_pool_then_clears(self):
        """Porzucone przez timeout wywolanie wciaz biegnie w puli --
        wait_for_llm_workers ma to widziec (False przy krotkiej gracji)
        i zwolnic po faktycznym koncu wywolania."""
        release = threading.Event()

        def slow():
            release.wait(5.0)
            return "done"

        with pytest.raises(TimeoutError):
            call_with_timeout(slow, timeout_sec=0.1, label="test-slow")

        # Caller odblokowany, ale worker dalej trzyma wywolanie.
        assert llm_workers_busy() >= 1
        assert wait_for_llm_workers(grace_sec=0.3) is False

        release.set()
        assert wait_for_llm_workers(grace_sec=3.0) is True
        assert llm_workers_busy() == 0

    def test_successful_call_leaves_pool_idle(self):
        assert call_with_timeout(lambda: 42, timeout_sec=5.0) == 42
        assert wait_for_llm_workers(grace_sec=1.0) is True
