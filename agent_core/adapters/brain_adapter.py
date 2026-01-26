"""
Brain Memory Adapter

Bridges legacy maria_core.memory_engine.brain_memory_integration to agent_core.
The legacy BrainMemoryLoop handles perception processing and LLM interaction.
This adapter integrates it with homeostasis cognitive sensing.

Legacy: maria_core/memory_engine/brain_memory_integration.py
"""

import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

logger = logging.getLogger(__name__)


class BrainMemoryAdapter:
    """
    Adapter that wraps legacy BrainMemoryLoop for homeostasis integration.

    The legacy BrainMemoryLoop:
    - Processes perceptions through LLM
    - Extracts facts to semantic graph
    - Tracks learning goals and unknown terms
    - Records episodes

    This adapter:
    - Provides cognitive metrics for CognitiveSensor
    - Tracks error rates and coherence
    - Integrates episode storage with homeostasis
    - Reports to event bus
    """

    def __init__(
        self,
        semantic_memory=None,
        episodic_memory: Optional[List[Dict]] = None,
        maria_brain=None,
        chunk_size: int = 1500,
        log_fn: Optional[Callable[[str], None]] = None,
        use_legacy: bool = True,
    ):
        """
        Initialize adapter.

        Args:
            semantic_memory: Semantic graph instance
            episodic_memory: List for episodic storage
            maria_brain: OllamaBrain instance
            chunk_size: Chunk size for text splitting
            log_fn: Logging function
            use_legacy: If True, wrap legacy BrainMemoryLoop
        """
        self._semantic = semantic_memory
        self._episodic = episodic_memory or []
        self._maria_brain = maria_brain
        self._chunk_size = chunk_size
        self._log_fn = log_fn or logger.info
        self._use_legacy = use_legacy
        self._legacy_loop = None

        # Cognitive metrics tracking
        self._error_timestamps: List[float] = []
        self._processing_times: List[float] = []
        self._coherence_scores: List[float] = []
        self._goal_stack: List[Dict[str, Any]] = []

        if use_legacy:
            self._init_legacy()

    def _init_legacy(self) -> None:
        """Initialize legacy BrainMemoryLoop."""
        try:
            from maria_core.memory_engine.brain_memory_integration import BrainMemoryLoop

            self._legacy_loop = BrainMemoryLoop(
                semantic_memory=self._semantic,
                episodic_memory=self._episodic,
                maria_brain=self._maria_brain,
                chunk_size=self._chunk_size,
                log_fn=self._log_fn,
            )
            logger.info("[Adapter] Legacy BrainMemoryLoop initialized")

        except ImportError as e:
            logger.warning(f"[Adapter] Legacy BrainMemoryLoop not available: {e}")
            self._use_legacy = False

    def get_cognitive_metrics(self) -> Dict[str, Any]:
        """
        Get cognitive metrics for CognitiveSensor.

        Returns:
            Dictionary with coherence, errors, goal depth, latencies
        """
        # Clean old timestamps (keep only last hour)
        cutoff = time.time() - 3600
        self._error_timestamps = [t for t in self._error_timestamps if t > cutoff]

        # Calculate coherence (average of recent scores, or 1.0 if none)
        if self._coherence_scores:
            coherence = sum(self._coherence_scores[-100:]) / len(self._coherence_scores[-100:])
        else:
            coherence = 1.0

        # Calculate latency percentiles
        latencies = self._processing_times[-1000:] if self._processing_times else [0]
        sorted_latencies = sorted(latencies)
        n = len(sorted_latencies)

        p50 = sorted_latencies[int(n * 0.5)] if n > 0 else 0
        p95 = sorted_latencies[int(n * 0.95)] if n > 0 else 0
        p99 = sorted_latencies[int(n * 0.99)] if n > 0 else 0

        return {
            "context_coherence": coherence,
            "error_count_1h": len(self._error_timestamps),
            "goal_stack_depth": len(self._goal_stack),
            "latency_p50_ms": p50 * 1000,
            "latency_p95_ms": p95 * 1000,
            "latency_p99_ms": p99 * 1000,
            "episode_count": len(self._episodic),
        }

    def process_perception(
        self,
        perception: str,
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process perception through brain.

        This wraps legacy process_perception and adds metrics tracking.

        Args:
            perception: Input text to process
            context: Optional context description

        Returns:
            Processing result with stats
        """
        start_time = time.time()

        try:
            if self._use_legacy and self._legacy_loop:
                result = self._legacy_loop.process_perception(perception, context)
            else:
                result = self._process_simple(perception, context)

            # Track metrics
            processing_time = time.time() - start_time
            self._processing_times.append(processing_time)

            # Estimate coherence from result
            stats = result.get("stats", {})
            if stats.get("facts", 0) > 0:
                error_ratio = stats.get("errors", 0) / (stats.get("facts", 1) + stats.get("errors", 0))
                coherence = 1.0 - error_ratio
            else:
                coherence = 0.5  # No facts extracted = uncertain coherence

            self._coherence_scores.append(coherence)

            # Track learning goals as goal stack items
            for goal in result.get("learning_goals", []):
                self._add_goal(goal)

            return result

        except Exception as e:
            logger.error(f"[Adapter] Perception processing error: {e}")
            self._error_timestamps.append(time.time())

            return {
                "status": "error",
                "error": str(e),
                "stats": {"facts": 0, "errors": 1},
            }

    def _process_simple(
        self,
        perception: str,
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Simple perception processing without legacy loop.

        This is a fallback when legacy code is not available.
        """
        episode = {
            "timestamp": datetime.now().isoformat(),
            "input_snippet": perception[:80],
            "context": context,
            "stats": {"facts": 0, "errors": 0},
            "success": True,
        }

        self._episodic.append(episode)

        return {
            "status": "completed_simple",
            "reasoning": "Simple processing (legacy not available)",
            "stats": {"facts": 0, "errors": 0},
            "episode": episode,
        }

    def _add_goal(self, goal: str) -> None:
        """Add goal to goal stack."""
        self._goal_stack.append({
            "goal": goal,
            "added_at": time.time(),
            "priority": len(self._goal_stack) + 1,
        })

        # Limit goal stack size
        if len(self._goal_stack) > 20:
            self._goal_stack = self._goal_stack[-20:]

    def get_goal_stack(self) -> List[Dict[str, Any]]:
        """Get current goal stack."""
        return self._goal_stack.copy()

    def pop_goal(self) -> Optional[Dict[str, Any]]:
        """Pop top goal from stack."""
        if self._goal_stack:
            return self._goal_stack.pop()
        return None

    def get_episodes(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get recent episodes.

        Args:
            limit: Maximum episodes to return

        Returns:
            List of recent episodes
        """
        return self._episodic[-limit:]

    @property
    def episodic_memory(self) -> List[Dict[str, Any]]:
        """Direct access to episodic memory list."""
        return self._episodic

    @property
    def semantic_memory(self):
        """Direct access to semantic memory."""
        return self._semantic


def get_adapted_brain_loop(
    semantic_memory=None,
    episodic_memory: Optional[List[Dict]] = None,
    maria_brain=None,
) -> BrainMemoryAdapter:
    """
    Get adapted brain loop instance.

    Drop-in replacement for BrainMemoryLoop instantiation.

    Args:
        semantic_memory: Semantic graph
        episodic_memory: Episode list
        maria_brain: OllamaBrain instance

    Returns:
        BrainMemoryAdapter instance
    """
    return BrainMemoryAdapter(
        semantic_memory=semantic_memory,
        episodic_memory=episodic_memory,
        maria_brain=maria_brain,
    )

