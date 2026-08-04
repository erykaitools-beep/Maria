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
        ctx: Optional[object] = None,
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
            # --- Real telemetry, pulled from live stores (pull-model 2026-07-18).
            # These were read from an empty MemoryManager/LLMManager that only
            # returned hardcoded constants (get_semantic_coherence->0.95,
            # get_total_entries->0, ...) because production wired both managers
            # with no stores. We now read the real stores via shared_context.
            # Signals with NO honest cheap per-tick source are left neutral on
            # purpose -- their (dead) gates are removed in the consumer layer
            # rather than fed a fabricated number:
            #   context_coherence  : no real coherence measure exists in the tree
            #   contradiction_count: only the 8h critic pass computes this
            #   episodic_freshness : no per-tick accessor without touching the
            #                        (watch-sensitive) world_model or file I/O
            #   inference_latency  : GPU-era thresholds do not apply to a CPU box
            #                        (llm_tape p50 ~23s); freeze is covered live
            #                        by TickWatchdog + the resource sensor
            context_coherence = 1.0
            contradiction_count = 0
            episodic_freshness_sec = 0.0
            inference_latency_ms = 0.0
            memory_entries = 0
            context_tokens = 0

            if ctx is not None:
                try:
                    wm = getattr(ctx, "world_model", None)
                    if wm is not None:
                        memory_entries = int(wm.stats().get("total", 0))
                except Exception:
                    pass
                try:
                    brain = getattr(ctx, "brain", None)
                    nim = getattr(brain, "nim", None) if brain is not None else None
                    if nim is not None:
                        context_tokens = int(nim.get_last_usage().get("total_tokens", 0))
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

            # Real active-goal count (was self._current_goal_depth, updated only
            # by a set_goal_depth recorder that production never called -> 0).
            # Goals are effectively flat (K3 caps active at ~20), so this is the
            # active count, not a tree depth.
            goal_stack_depth = self._current_goal_depth
            if ctx is not None:
                try:
                    gs = getattr(ctx, "goal_store", None)
                    if gs is not None:
                        goal_stack_depth = len(gs.get_active())
                except Exception:
                    pass

            return CognitiveMetrics(
                timestamp=time.time(),
                context_coherence=context_coherence,
                context_tokens=context_tokens,
                inference_latency_ms=inference_latency_ms,
                latency_p50_ms=self._get_latency_percentile(50),
                latency_p99_ms=self._get_latency_percentile(99),
                error_count_1h=recent_errors,
                goal_stack_depth=goal_stack_depth,
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
