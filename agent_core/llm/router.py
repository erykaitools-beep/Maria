"""
LLM Router - Routes tasks to NIM or Ollama based on type and budget.

Routing rules:
- think() -> always Ollama (chat, offline, fast, local history)
- analyze_task() -> NIM if budget OK, else Ollama
- _ask_once() -> NIM if budget OK, else Ollama

Every NIM call updates token budget automatically.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class LLMRouter:
    """
    Routes LLM calls between NIM API and local Ollama.

    NIM is used for learning tasks (stronger model, better results).
    Ollama is used for chat (offline, fast, no token cost).

    If NIM is unavailable or budget is depleted, all calls go to Ollama.

    Usage:
        router = LLMRouter(
            ollama_brain=brain,
            nim_client=nim,
            token_budget=budget,
        )
        # Chat -> Ollama
        response = router.think("Czesc, jak sie masz?")

        # Learning -> NIM (with fallback)
        analysis = router.analyze_task("Fotosynteza to proces...")
    """

    def __init__(
        self,
        ollama_brain,
        nim_client=None,
        token_budget=None,
    ):
        """
        Initialize LLM router.

        Args:
            ollama_brain: OllamaBrain instance (required, always available)
            nim_client: NIMClient instance (optional, for learning)
            token_budget: TokenBudget instance (optional, for tracking)
        """
        self.ollama = ollama_brain
        self.nim = nim_client
        self.budget = token_budget

        # Stats
        self._nim_calls = 0
        self._nim_fallbacks = 0
        self._ollama_calls = 0

    # -------------------------------------------------
    # MAIN API (compatible with OllamaBrain)
    # -------------------------------------------------

    def think(self, prompt: str, temperature: float = 0.3, **kwargs) -> str:
        """
        Chat with history - always uses Ollama.

        Args:
            prompt: User message
            temperature: Sampling temperature

        Returns:
            Response text
        """
        self._ollama_calls += 1
        return self.ollama.think(prompt, temperature=temperature, **kwargs)

    def _ask_once(
        self, prompt: str, temperature: float = 0.3, **kwargs
    ) -> str:
        """
        One-shot question - uses NIM if available and budget OK.

        Args:
            prompt: User prompt
            temperature: Sampling temperature

        Returns:
            Response text
        """
        if self._should_use_nim():
            try:
                result = self.nim._ask_once(
                    prompt, temperature=temperature, **kwargs
                )
                self._record_nim_usage()
                self._nim_calls += 1
                return result
            except Exception as e:
                logger.warning(f"NIM _ask_once failed, falling back to Ollama: {e}")
                self._nim_fallbacks += 1

        # Fallback to Ollama
        self._ollama_calls += 1
        return self.ollama._ask_once(
            prompt, temperature=temperature, **kwargs
        )

    def analyze_task(self, task: str, retries: int = 2) -> Dict[str, Any]:
        """
        Analyze task - uses NIM if available and budget OK.

        Args:
            task: Text to analyze
            retries: Retry attempts for bad JSON

        Returns:
            Structured analysis dict
        """
        if self._should_use_nim():
            try:
                result = self.nim.analyze_task(task, retries=retries)
                self._record_nim_usage()
                self._nim_calls += 1
                return result
            except Exception as e:
                logger.warning(
                    f"NIM analyze_task failed, falling back to Ollama: {e}"
                )
                self._nim_fallbacks += 1

        # Fallback to Ollama
        self._ollama_calls += 1
        return self.ollama.analyze_task(task, retries=retries)

    # -------------------------------------------------
    # ROUTING DECISIONS
    # -------------------------------------------------

    def _should_use_nim(self) -> bool:
        """
        Decide whether to use NIM for this call.

        Returns:
            True if NIM is available and budget allows
        """
        # No NIM client configured
        if self.nim is None:
            return False

        # No API key
        if not self.nim.api_key:
            return False

        # Budget check
        if self.budget is not None and not self.budget.can_use_nim():
            logger.debug("NIM skipped: token budget depleted")
            return False

        return True

    def _record_nim_usage(self) -> None:
        """Record token usage from last NIM call to budget."""
        if self.budget is not None and self.nim is not None:
            usage = self.nim.get_last_usage()
            if usage["total_tokens"] > 0:
                self.budget.record_usage(
                    prompt_tokens=usage["prompt_tokens"],
                    completion_tokens=usage["completion_tokens"],
                    model=self.nim.model,
                )

    # -------------------------------------------------
    # STATUS & REPORTING
    # -------------------------------------------------

    def get_active_backend(self) -> str:
        """
        Get current active backend name.

        Returns:
            "hybrid" - NIM for learning, Ollama for chat
            "ollama" - Ollama only (NIM unavailable or depleted)
            "nim" - NIM only (unlikely in practice)
        """
        if self._should_use_nim():
            return "hybrid"
        return "ollama"

    def get_budget_status(self) -> str:
        """
        Get token budget status text.

        Returns:
            Human-readable budget status or "No budget tracking"
        """
        if self.budget is not None:
            return self.budget.get_status_text()
        return "Brak sledzenia budzetu tokenow."

    def get_stats(self) -> Dict[str, Any]:
        """
        Get routing statistics.

        Returns:
            Stats dict with call counts and backend info
        """
        stats = {
            "active_backend": self.get_active_backend(),
            "nim_calls": self._nim_calls,
            "nim_fallbacks": self._nim_fallbacks,
            "ollama_calls": self._ollama_calls,
            "total_calls": self._nim_calls + self._ollama_calls,
        }

        if self.budget is not None:
            stats["budget"] = self.budget.get_status_dict()

        if self.nim is not None:
            stats["nim_model"] = self.nim.model
            stats["nim_available"] = bool(self.nim.api_key)
        else:
            stats["nim_model"] = None
            stats["nim_available"] = False

        return stats

    # -------------------------------------------------
    # PASSTHROUGH (OllamaBrain compatibility)
    # -------------------------------------------------

    def refresh_time_context(self) -> None:
        """Refresh time context (delegated to Ollama)."""
        if hasattr(self.ollama, "refresh_time_context"):
            self.ollama.refresh_time_context()

    @property
    def model(self) -> str:
        """Get primary model name (Ollama)."""
        return getattr(self.ollama, "model", "unknown")

    @property
    def call_count(self) -> int:
        """Get total call count."""
        return self._nim_calls + self._ollama_calls

    @property
    def history(self):
        """Get conversation history (from Ollama)."""
        return getattr(self.ollama, "history", [])

    @history.setter
    def history(self, value):
        """Set conversation history (delegated to Ollama)."""
        if hasattr(self.ollama, "history"):
            self.ollama.history = value
