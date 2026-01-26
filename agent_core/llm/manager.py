"""
LLM Manager - Language model interface for homeostasis

Provides:
- Latency tracking
- Batch size control
- Health reporting
- Minimize mode for SURVIVAL

Adapter for: models/ollama_brain.py
"""

import time
import logging
from typing import Dict, Any, Optional
from collections import deque

logger = logging.getLogger(__name__)


class LLMManager:
    """
    LLM interface for homeostasis system.

    Wraps OllamaBrain and provides metrics needed by
    cognitive sensor and corrective actions.
    """

    def __init__(self):
        """Initialize LLM manager."""
        self._last_latency_ms = 0.0
        self._latency_history: deque = deque(maxlen=100)
        self._context_tokens = 0
        self._batch_size_factor = 1.0  # 1.0 = full, 0.5 = half
        self._minimized = False

        # Try to wrap legacy module
        self._init_legacy_adapter()

    def _init_legacy_adapter(self) -> None:
        """Initialize adapter for legacy OllamaBrain."""
        try:
            from models.ollama_brain import OllamaBrain
            self._legacy_brain = OllamaBrain
        except ImportError:
            self._legacy_brain = None
            logger.debug("Legacy OllamaBrain not available")

    # ─────────────────────────────────────────────
    # HOMEOSTASIS INTERFACE (for sensors)
    # ─────────────────────────────────────────────

    def get_last_latency_ms(self) -> float:
        """
        Get last inference latency.

        Returns:
            Latency in milliseconds
        """
        return self._last_latency_ms

    def get_context_tokens(self) -> int:
        """
        Get current context token count.

        Returns:
            Number of tokens in context
        """
        return self._context_tokens

    def get_latency_percentile(self, percentile: int) -> float:
        """
        Get latency percentile from history.

        Args:
            percentile: Percentile to calculate (e.g., 50, 99)

        Returns:
            Latency at percentile in milliseconds
        """
        if not self._latency_history:
            return 0.0

        sorted_latencies = sorted(self._latency_history)
        idx = int(len(sorted_latencies) * percentile / 100)
        idx = min(idx, len(sorted_latencies) - 1)
        return sorted_latencies[idx]

    # ─────────────────────────────────────────────
    # CORRECTIVE ACTIONS (from homeostasis)
    # ─────────────────────────────────────────────

    def reduce_batch_size(self, factor: float = 0.5) -> None:
        """
        Reduce inference batch size.

        Args:
            factor: Reduction factor (0.5 = half)
        """
        self._batch_size_factor = max(0.1, min(1.0, factor))
        logger.info(f"LLM batch size reduced to {self._batch_size_factor:.1%}")

    def restore_batch_size(self) -> None:
        """Restore full batch size."""
        self._batch_size_factor = 1.0
        logger.info("LLM batch size restored to 100%")

    def minimize(self) -> None:
        """
        Enter minimal mode for SURVIVAL.

        Unloads model from memory if possible.
        """
        self._minimized = True
        logger.info("LLM entering minimal mode")
        # In real implementation, would unload model

    def restore(self) -> None:
        """
        Restore from minimal mode.

        Reloads model if it was unloaded.
        """
        self._minimized = False
        logger.info("LLM restored from minimal mode")

    def is_minimized(self) -> bool:
        """Check if in minimal mode."""
        return self._minimized

    # ─────────────────────────────────────────────
    # METRICS RECORDING (called after inference)
    # ─────────────────────────────────────────────

    def record_inference(
        self,
        latency_ms: float,
        tokens_generated: int,
        context_tokens: int,
    ) -> None:
        """
        Record inference metrics.

        Called after each inference to update metrics.

        Args:
            latency_ms: Time taken in milliseconds
            tokens_generated: Number of tokens generated
            context_tokens: Current context size
        """
        self._last_latency_ms = latency_ms
        self._latency_history.append(latency_ms)
        self._context_tokens = context_tokens

    # ─────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────

    def health_check(self) -> Dict[str, Any]:
        """
        Get LLM health status.

        Returns:
            Health status dictionary
        """
        avg_latency = 0.0
        if self._latency_history:
            avg_latency = sum(self._latency_history) / len(self._latency_history)

        return {
            "healthy": not self._minimized and self._last_latency_ms < 60000,
            "minimized": self._minimized,
            "batch_size_factor": self._batch_size_factor,
            "last_latency_ms": self._last_latency_ms,
            "avg_latency_ms": avg_latency,
            "context_tokens": self._context_tokens,
        }

    # ─────────────────────────────────────────────
    # SHUTDOWN
    # ─────────────────────────────────────────────

    def shutdown_prepare(self, grace_period_seconds: int = 30) -> Dict[str, Any]:
        """
        Prepare for shutdown.

        Args:
            grace_period_seconds: Time available for cleanup

        Returns:
            Acknowledgment dictionary
        """
        logger.info(f"LLM preparing for shutdown (grace: {grace_period_seconds}s)")
        return {
            "ready_shutdown": True,
            "final_latency_ms": self._last_latency_ms,
        }
