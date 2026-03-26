"""
LLM Router - Routes tasks to NIM or Ollama based on type and budget.

Routing rules:
- think() -> always Ollama (chat, offline, fast, local history)
- analyze_task() -> NIM if budget OK, else Ollama
- _ask_once() -> NIM if budget OK, else Ollama
- ask_as_role() -> ModelScheduler selects model by role (multi-organ)

Every NIM call updates token budget automatically.
"""

import logging
import time
from typing import Dict, Any, Optional

try:
    import ollama as ollama_lib
except ImportError:
    ollama_lib = None

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
        self._model_scheduler = None
        self._llm_tape = None
        self._codex_client = None

        # Stats
        self._nim_calls = 0
        self._nim_fallbacks = 0
        self._ollama_calls = 0
        self._codex_calls = 0

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
        start = time.time()
        response = self.ollama.think(prompt, temperature=temperature, **kwargs)
        self._record_tape("chat", self.ollama.model, prompt, response, start)
        return response

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
        start = time.time()
        if self._should_use_nim():
            try:
                result = self.nim._ask_once(
                    prompt, temperature=temperature, **kwargs
                )
                self._record_nim_usage()
                self._nim_calls += 1
                self._record_tape("learning", self.nim.model, prompt, result, start)
                return result
            except Exception as e:
                logger.warning(f"NIM _ask_once failed, falling back to Ollama: {e}")
                self._nim_fallbacks += 1

        # Fallback to Ollama
        self._ollama_calls += 1
        result = self.ollama._ask_once(
            prompt, temperature=temperature, **kwargs
        )
        self._record_tape("learning", self.ollama.model, prompt, result, start)
        return result

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
        """Record token usage and request timestamp from last NIM call."""
        if self.budget is not None and self.nim is not None:
            # RPM tracking (primary gate)
            self.budget.record_request()
            # Token tracking (observability)
            usage = self.nim.get_last_usage()
            if usage["total_tokens"] > 0:
                self.budget.record_usage(
                    prompt_tokens=usage["prompt_tokens"],
                    completion_tokens=usage["completion_tokens"],
                    model=self.nim.model,
                )

    # -------------------------------------------------
    # MODEL SCHEDULER (multi-organ routing)
    # -------------------------------------------------

    def set_llm_tape(self, tape) -> None:
        """Attach LLM Tape for recording all model interactions."""
        self._llm_tape = tape

    def _record_tape(
        self, role: str, model: str, prompt: str, response: str,
        start_time: float, success: bool = True,
    ) -> None:
        """Record LLM interaction to tape (if attached)."""
        if self._llm_tape is None:
            return
        try:
            from agent_core.llm.llm_tape import make_tape_entry
            latency_ms = (time.time() - start_time) * 1000
            is_success = success and bool(response and response.strip())
            entry = make_tape_entry(
                model=model or "unknown",
                role=role,
                prompt=prompt or "",
                response=response or "",
                latency_ms=latency_ms,
                success=is_success,
            )
            self._llm_tape.record(entry)
        except Exception:
            pass

    def set_model_scheduler(self, scheduler) -> None:
        """
        Attach ModelScheduler for multi-model routing.

        When set, ask_as_role() becomes available for role-based
        model selection. Existing methods (think, _ask_once,
        analyze_task) remain unchanged for backward compatibility.
        """
        self._model_scheduler = scheduler

    def ask_as_role(
        self, role, prompt: str, temperature: float = 0.3
    ) -> str:
        """
        Send a prompt to a specific model role via ModelScheduler.

        Ensures the model for the requested role is loaded,
        performs inference, records latency, and releases the model.

        Falls back to Ollama EXECUTOR if scheduler unavailable
        or model can't be loaded.

        Args:
            role: ModelRole enum value (e.g. ModelRole.PLANNER)
            prompt: The prompt text
            temperature: Sampling temperature

        Returns:
            Response text from the selected model
        """
        role_name = role.value if hasattr(role, "value") else str(role)

        # Normalize string role to ModelRole enum for scheduler
        if isinstance(role, str) and self._model_scheduler is not None:
            try:
                from agent_core.llm.model_registry import ModelRole
                role = ModelRole(role)
            except (ValueError, ImportError):
                pass  # Keep as string, will fall through to Ollama

        if self._model_scheduler is None:
            # No scheduler - fall through to default Ollama
            self._ollama_calls += 1
            ask_start = time.time()
            text = self.ollama._ask_once(prompt, temperature=temperature)
            self._record_tape(role_name, self.ollama.model, prompt, text, ask_start)
            return text

        result = self._model_scheduler.ensure_ready(role)

        if not result.success:
            logger.warning(
                f"[LLMRouter] Cannot load {role_name}: {result.reason}, "
                f"falling back to Ollama"
            )
            self._ollama_calls += 1
            ask_start = time.time()
            text = self.ollama._ask_once(prompt, temperature=temperature)
            self._record_tape(role_name, self.ollama.model, prompt, text, ask_start)
            return text

        # Use the model tag from scheduler (may be fallback)
        try:
            start = time.time()
            resp = ollama_lib.chat(
                model=result.ollama_tag,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": temperature},
            )
            latency = time.time() - start
            self._model_scheduler.record_request(result.role, latency)
            self._ollama_calls += 1

            text = resp.get("message", {}).get("content", "")
            text = text.strip()
            self._record_tape(role_name, result.ollama_tag, prompt, text, start)
            return text
        except Exception as e:
            logger.warning(
                f"[LLMRouter] ask_as_role({role.value}) inference failed: {e}"
            )
            self._ollama_calls += 1
            ask_start = time.time()
            text = self.ollama._ask_once(prompt, temperature=temperature)
            self._record_tape(role_name, self.ollama.model, prompt, text, ask_start, success=False)
            return text
        finally:
            self._model_scheduler.release(result.role)

    # -------------------------------------------------
    # ENCYCLOPEDIA (Codex CLI / ChatGPT)
    # -------------------------------------------------

    def set_codex_client(self, client) -> None:
        """Attach Codex CLI client for encyclopedia queries."""
        self._codex_client = client

    def ask_encyclopedia(
        self, prompt: str, source: str = "unknown", context=None,
    ) -> str:
        """
        Ask ChatGPT via Codex CLI for knowledge.

        Fallback cascade: Codex -> NIM -> Ollama.
        Every call logged to codex_interactions.jsonl + LLM Tape.

        Args:
            prompt: Knowledge question
            source: Calling module (creative, planner, k12, etc.)
            context: Optional metadata dict for logging

        Returns:
            Response text (always returns something via fallback)
        """
        start = time.time()

        # Try Codex first
        if self._codex_client:
            result = self._codex_client.ask(prompt, source=source, context=context)
            if result:
                self._codex_calls += 1
                self._record_tape(
                    "encyclopedia", "codex-chatgpt", prompt, result, start,
                )
                return result

        # Fallback: NIM
        if self._should_use_nim():
            try:
                result = self.nim._ask_once(prompt, temperature=0.3)
                self._record_nim_usage()
                self._nim_calls += 1
                self._record_tape("encyclopedia", self.nim.model, prompt, result, start)
                return result
            except Exception:
                self._nim_fallbacks += 1

        # Fallback: Ollama
        self._ollama_calls += 1
        result = self.ollama._ask_once(prompt, temperature=0.3)
        self._record_tape("encyclopedia", self.ollama.model, prompt, result, start)
        return result

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
            "codex_calls": self._codex_calls,
            "total_calls": self._nim_calls + self._ollama_calls + self._codex_calls,
        }

        if self.budget is not None:
            stats["budget"] = self.budget.get_status_dict()

        if self.nim is not None:
            stats["nim_model"] = self.nim.model
            stats["nim_available"] = bool(self.nim.api_key)
        else:
            stats["nim_model"] = None
            stats["nim_available"] = False

        if self._model_scheduler is not None:
            stats["scheduler"] = self._model_scheduler.get_status()

        if self._codex_client is not None:
            stats["codex"] = self._codex_client.get_stats()

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
