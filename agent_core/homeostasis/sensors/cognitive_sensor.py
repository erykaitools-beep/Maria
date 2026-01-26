"""
Cognitive Sensor - LLM and memory state monitoring

Monitors (spec section 1.1.B):
- LLM Context: token count, qualitative state, response latency (p50, p99)
- Memory Coherence: episodic freshness, semantic graph integrity, contradiction count
- Intent Stability: goal stack depth, conversation drift, attention fragmentation
- Affect metadata: error density, uncertainty, task completion ratio

Spec reference: homeostasis_spec.md lines 44-65
"""

import time
from typing import Optional, TYPE_CHECKING
from collections import deque
from statistics import median

from ..state_model import CognitiveMetrics

if TYPE_CHECKING:
    from ...memory.manager import MemoryManager
    from ...llm.manager import LLMManager


class CognitiveSensor:
    """
    Reads cognitive state metrics from memory and LLM modules.

    Tracks historical data for latency percentiles and error rates.
    """

    def __init__(self):
        """Initialize cognitive sensor with history buffers."""
        # Latency history for percentile calculation (last 100 measurements)
        self._latency_history: deque = deque(maxlen=100)

        # Error history (timestamps of errors in last hour)
        self._error_timestamps: deque = deque(maxlen=1000)

        # Task completion history
        self._task_results: deque = deque(maxlen=100)  # (timestamp, success: bool)

        # Goal stack tracking
        self._current_goal_depth = 0

        # Attention tracking
        self._active_topics: set = set()

    def read_metrics(
        self,
        memory_manager: Optional["MemoryManager"] = None,
        llm_manager: Optional["LLMManager"] = None,
    ) -> CognitiveMetrics:
        """
        Read cognitive state metrics.

        Args:
            memory_manager: Memory module for coherence metrics
            llm_manager: LLM module for inference metrics

        Returns:
            CognitiveMetrics with current values

        Spec: homeostasis_spec.md lines 990-1012
        """
        try:
            # Get coherence from memory module
            context_coherence = 1.0
            memory_entries = 0
            contradiction_count = 0
            episodic_freshness_sec = 0

            if memory_manager:
                try:
                    context_coherence = memory_manager.get_semantic_coherence()
                    memory_entries = memory_manager.get_total_entries()
                    contradiction_count = memory_manager.get_contradiction_count()
                    episodic_freshness_sec = memory_manager.get_episodic_freshness()
                except Exception:
                    pass

            # Get latency from LLM module
            inference_latency_ms = 0.0
            context_tokens = 0

            if llm_manager:
                try:
                    inference_latency_ms = llm_manager.get_last_latency_ms()
                    context_tokens = llm_manager.get_context_tokens()
                    self._latency_history.append(inference_latency_ms)
                except Exception:
                    pass

            # Calculate error rate (errors per hour)
            now = time.time()
            hour_ago = now - 3600
            recent_errors = sum(1 for ts in self._error_timestamps if ts > hour_ago)

            # Calculate task completion ratio
            recent_tasks = [(ts, success) for ts, success in self._task_results if ts > hour_ago]
            if recent_tasks:
                task_completion_ratio = sum(1 for _, s in recent_tasks if s) / len(recent_tasks)
            else:
                task_completion_ratio = 1.0

            # Calculate attention fragmentation (0-1, higher = more fragmented)
            attention_fragmentation = min(1.0, len(self._active_topics) / 10.0)

            return CognitiveMetrics(
                timestamp=time.time(),
                context_coherence=context_coherence,
                context_tokens=context_tokens,
                inference_latency_ms=inference_latency_ms,
                latency_p50_ms=self._get_latency_percentile(50),
                latency_p99_ms=self._get_latency_percentile(99),
                error_count_1h=recent_errors,
                goal_stack_depth=self._current_goal_depth,
                memory_entries=memory_entries,
                contradiction_count=contradiction_count,
                episodic_freshness_sec=episodic_freshness_sec,
                attention_fragmentation=attention_fragmentation,
                task_completion_ratio=task_completion_ratio,
            )

        except Exception:
            # Sensor failure: assume critical state (spec lines 1007-1012)
            return CognitiveMetrics(
                timestamp=time.time(),
                context_coherence=0.5,
                context_tokens=0,
                inference_latency_ms=9999,
                latency_p50_ms=9999,
                latency_p99_ms=9999,
                error_count_1h=100,
                goal_stack_depth=50,
                memory_entries=0,
                contradiction_count=100,
                episodic_freshness_sec=99999,
                attention_fragmentation=1.0,
                task_completion_ratio=0.0,
            )

    def record_error(self) -> None:
        """Record an error occurrence for rate tracking."""
        self._error_timestamps.append(time.time())

    def record_task_result(self, success: bool) -> None:
        """Record task completion result."""
        self._task_results.append((time.time(), success))

    def set_goal_depth(self, depth: int) -> None:
        """Update current goal stack depth."""
        self._current_goal_depth = depth

    def add_active_topic(self, topic: str) -> None:
        """Add topic to active attention set."""
        self._active_topics.add(topic)

    def remove_active_topic(self, topic: str) -> None:
        """Remove topic from active attention set."""
        self._active_topics.discard(topic)

    def clear_active_topics(self) -> None:
        """Clear all active topics."""
        self._active_topics.clear()

    def _get_latency_percentile(self, percentile: int) -> float:
        """Calculate latency percentile from history."""
        if not self._latency_history:
            return 0.0

        sorted_latencies = sorted(self._latency_history)
        idx = int(len(sorted_latencies) * percentile / 100)
        idx = min(idx, len(sorted_latencies) - 1)
        return sorted_latencies[idx]
