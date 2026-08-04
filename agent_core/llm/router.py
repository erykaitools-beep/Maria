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
import os
import re
import time
from contextlib import nullcontext
from typing import Dict, Any, Optional

from agent_core.llm.execution_budget import (
    call_with_timeout,
    get_timeout_for_role,
    get_ollama_client,
)

try:
    import ollama as ollama_lib
except ImportError:
    ollama_lib = None

# httpx.TimeoutException is what the timeout-aware ollama client raises on a stall.
# It is NOT a subclass of the builtin TimeoutError (only of Exception), so the
# `except TimeoutError` guards below must name it explicitly or a real HTTP
# read-timeout would escape past the freeze-degradation handlers.
try:
    import httpx as _httpx
    _OLLAMA_TIMEOUT_EXC = (TimeoutError, _httpx.TimeoutException)
except Exception:  # pragma: no cover - httpx ships with ollama
    _OLLAMA_TIMEOUT_EXC = (TimeoutError,)

logger = logging.getLogger(__name__)

# Cap on the tape's route_reason field. Failure reasons embed the upstream error
# body; unbounded they would ride in every frame.
MAX_ROUTE_REASON = 160


def _learning_local_model() -> str:
    """Local model for the learning fallback (used once NIM is unavailable).

    Thinking must stay OFF whatever the model: with it on, qwen3's median was
    285s, past every budget in the chain, so it never returned a usable answer
    at all (0/30). That finding still holds.

    WHICH model, re-measured 2026-08-02 (30 real input/ fragments, production
    prompt via learn_chunk, evening load 4.4->7.1, strictly sequential, scored
    on what learn_chunk ACTUALLY validates -- summary/key_points/tags present):

        llama3.1:8b            30/30   median  84s   p90  97s   max 124s
        qwen3:8b think=False   30/30   median 103s   p90 122s   max 134s

    Both clear the 230s learning budget with ~42% headroom, and spot checks
    confirm substantive Polish output (summaries 218-474 chars, 5-7 key points,
    on-topic tags) rather than well-formed emptiness. Paired: 0 fixes, 0 breaks,
    p=1.000 -- a genuine tie on the contract, with llama ~18s faster per call.

    THE EARLIER NUMBERS WERE STALE, NOT WRONG. The measurement this docstring
    used to carry (llama 18/30, qwen3 27/30, medians 116s/143s, McNemar p=0.035)
    was committed in 8d20569 at 09:27 on 2026-07-26 -- three hours BEFORE
    c6074b6 and 028e8b6 landed at 12:31 the same day, which de-duplicated the
    persona (~1000 tokens) and made the prefix byte-stable so the KV cache can
    hit (prefill 117s -> 0.2s). Both models got materially faster and more
    reliable afterwards and nobody re-ran the comparison. `.env` pinned
    llama3.1:8b on the strength of a qwen3 latency risk that those fixes had
    already removed.

    So the default below is now a genuine toss-up on the measured contract.
    What is NOT settled: content quality. qwen3's summaries run consistently
    longer (337-474 chars vs 218-308); longer is not automatically better and
    no one has judged that. Pick on quality if you ever measure it; until then
    llama is the cheaper of two models that both clear the bar.

    Override with LEARNING_LOCAL_MODEL + restart.
    """
    return os.environ.get("LEARNING_LOCAL_MODEL", "qwen3:8b").strip() or "qwen3:8b"


# System prefix for the local learning call. SHORT and CONSTANT, both on purpose.
#
# The default persona is ~1000 tokens of identity, operator profile, conversation
# memory and operational state -- none of which a "return JSON from this
# fragment" task reads. It is also redundant: PROMPT_LEARN_NORMAL already opens
# with "Jestes M.A.R.I.A. - lokalna, autonomiczna inteligencja...", so Maria was
# introducing herself to the model twice per call.
#
# Worse, the persona carries a live clock refreshed on every chat turn, so the
# prefix is never byte-identical twice and Ollama's KV cache misses every call.
# Measured 2026-07-26 on this box: prefill 117.3s on a miss, 0.2s on a hit --
# the chat path already solved this (CHAT_FAST_CONTEXT: "never the per-call
# HH:MM"), the learning path never got the fix.
#
# Override with LEARNING_SYSTEM_PROMPT; set it to "-" to restore the persona.
_LEARNING_SYSTEM_DEFAULT = "Odpowiadasz wylacznie czystym JSON, bez komentarza."


def _learning_system_prompt() -> Optional[str]:
    """Constant system prefix for learning, or None to keep the full persona."""
    raw = os.environ.get("LEARNING_SYSTEM_PROMPT")
    if raw is None:
        return _LEARNING_SYSTEM_DEFAULT
    raw = raw.strip()
    return None if raw == "-" else (raw or _LEARNING_SYSTEM_DEFAULT)


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
        use_nim_for_chat: bool = False,
    ):
        """
        Initialize LLM router.

        Args:
            ollama_brain: OllamaBrain instance (required, always available)
            nim_client: NIMClient instance (optional, for learning)
            token_budget: TokenBudget instance (optional, for tracking)
            use_nim_for_chat: Route chat (think) through NIM instead of Ollama
        """
        self.ollama = ollama_brain
        self.nim = nim_client
        self.budget = token_budget
        self.use_nim_for_chat = use_nim_for_chat
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
        Chat with history - uses NIM if use_nim_for_chat enabled, else Ollama.

        Grounded queries (vision, status, errors) ALWAYS go through Ollama
        because the grounding pipeline (evidence collector, camera) lives there.
        Only regular chat is routed through NIM.

        Args:
            prompt: User message
            temperature: Sampling temperature

        Returns:
            Response text
        """
        start = time.time()

        # Grounded queries MUST go through Ollama (camera, logs, evidence)
        needs_grounding = self._is_grounded_query(prompt)

        # Personal/user queries need Ollama (user profile in system prompt)
        if not needs_grounding:
            needs_grounding = self._is_personal_query(prompt)

        # NIM chat path (with Ollama fallback) - only for regular chat
        if (self.use_nim_for_chat and self._should_use_nim()
                and not needs_grounding):
            try:
                response = self.nim.think(prompt, temperature=temperature)
                self._record_nim_usage()
                self._nim_calls += 1
                self._record_tape("chat", self.nim.model, prompt, response, start,
                                  route_reason="chat_nim_enabled")
                return response
            except Exception as e:
                logger.warning(f"NIM chat failed, falling back to Ollama: {e}")
                self._nim_fallbacks += 1
                self._record_tape("chat", self.nim.model, prompt, "", start,
                                  success=False,
                                  route_reason=f"nim_failed: {e}")

        # Default: Ollama (always for grounded, fallback for NIM failure)
        self._ollama_calls += 1
        response = self.ollama.think(prompt, temperature=temperature, **kwargs)
        if needs_grounding:
            reason = "grounded_query_always_ollama"
        elif self.use_nim_for_chat:
            reason = "nim_chat_fallback"
        else:
            reason = "chat_always_ollama"
        self._record_tape("chat", self.ollama.model, prompt, response, start,
                          route_reason=reason)
        return response

    def translate_to_polish(self, text: str, temperature: float = 0.2) -> str:
        """Render an English description as natural, fluent Polish, NIM-first.

        Used by the vision advisor: the local vision model describes the scene in
        English (its strength) and this turns it into clean Polish for the operator
        ping -- a 4-7B vision model writes broken Polish (invented words, English
        fragments), whereas NIM is fluent. Budget/rate-guarded NIM-first; on any failure
        falls back to the local model, then to the original English text, so a ping
        is never empty or garbled."""
        if not text or not text.strip():
            return text
        prompt = (
            "Translate the following image/scene description into natural, fluent "
            "Polish. Output ONLY the Polish translation, 1-2 sentences, no preamble, "
            "no quotes, no English:\n\n" + text.strip()
        )
        # NIM-first (fluent Polish), guarded by availability + budget.
        if self._should_use_nim():
            try:
                start = time.time()
                out = self.nim._ask_once(prompt, temperature=temperature)
                self._record_nim_usage()
                self._nim_calls += 1
                self._record_tape("vision_translate", self.nim.model, prompt, out,
                                  start, route_reason="vision_translate_nim")
                if out and out.strip():
                    return out.strip()
            except Exception as e:
                logger.warning(f"[LLMRouter] vision translate NIM failed: {e}")
                self._nim_fallbacks += 1
                self._record_tape("vision_translate", self.nim.model, prompt, "",
                                  start, success=False,
                                  route_reason=f"nim_failed: {e}")
        # Local fallback: weaker Polish, but far better than the vision model's.
        try:
            out = self.ollama.think(prompt, temperature=temperature)
            if out and out.strip():
                return out.strip()
        except Exception as e:
            logger.warning(f"[LLMRouter] vision translate local failed: {e}")
        return text  # last resort: honest English beats garbled Polish

    def _is_grounded_query(self, prompt: str) -> bool:
        """Check if prompt needs grounding pipeline (vision, status, etc).

        Grounded queries must go through OllamaBrain which has the
        evidence collector, camera access, and response builder wired.
        """
        if not hasattr(self.ollama, '_query_router') or not self.ollama._query_router:
            return False
        try:
            mode = self.ollama._query_router.classify(prompt)
            return self.ollama._query_router.is_grounded(mode)
        except Exception:
            return False

    _PERSONAL_PATTERNS = re.compile(
        r"co\s+wiesz\s+o\s+mnie|"
        r"znasz\s+mnie|"
        r"kim\s+jestem|"
        r"co\s+o\s+mnie\s+wiesz|"
        r"co\s+pamietasz|"
        r"co\s+pami.tasz|"
        r"moje\s+(?:zainteresowania|preferencje|dane|profil|harmonogram)|"
        r"what\s+do\s+you\s+know\s+about\s+me",
        re.IGNORECASE,
    )

    def _is_personal_query(self, prompt: str) -> bool:
        """Check if prompt asks about the user/operator.

        These need Ollama because user profile is in system prompt.
        """
        return bool(self._PERSONAL_PATTERNS.search(prompt))

    def _ask_once(
        self, prompt: str, temperature: float = 0.3,
        force_json: bool = False, **kwargs
    ) -> str:
        """
        One-shot question - uses NIM if available and budget OK.

        Args:
            prompt: User prompt
            temperature: Sampling temperature
            force_json: Request server-side JSON output (propagates to NIM/Ollama)

        Returns:
            Response text
        """
        start = time.time()
        if self._should_use_nim():
            try:
                result = self.nim._ask_once(
                    prompt, temperature=temperature,
                    force_json=force_json, **kwargs
                )
                self._record_nim_usage()
                self._nim_calls += 1
                self._record_tape("learning", self.nim.model, prompt, result, start,
                                  route_reason="nim_budget_ok")
                return result
            except Exception as e:
                logger.warning(f"NIM _ask_once failed, falling back to Ollama: {e}")
                self._nim_fallbacks += 1
                self._record_tape("learning", self.nim.model, prompt, "", start,
                                  success=False,
                                  route_reason=f"nim_failed: {e}")

        # Fallback to Ollama -- bounded so a wedged Ollama cannot hang the caller
        # forever (the 2026-06-02 freeze went through unbounded _ask_once paths).
        reason = "nim_fallback" if self._nim_fallbacks > 0 else "nim_unavailable_or_budget"
        self._ollama_calls += 1
        # This Ollama fallback runs a heavy LOCAL model (learn/gap-analysis).
        # Serialize it on the scheduler's heavy mutex so it never overlaps the
        # exam answer / K12 on the CPU. No-op until SCHEDULER_ENFORCE_MUTEX is set.
        # getattr: bare/test routers built via __new__ may lack the attribute.
        _scheduler = getattr(self, "_model_scheduler", None)
        _guard = (_scheduler.heavy_lease("ask_once_ollama_fallback")
                  if _scheduler is not None else nullcontext())
        learn_model = _learning_local_model()
        try:
            with _guard:
                result = call_with_timeout(
                    lambda: self.ollama._ask_once(
                        prompt, temperature=temperature,
                        force_json=force_json,
                        model=learn_model,
                        # Constant, task-shaped prefix instead of the persona:
                        # ~1000 tokens lighter AND byte-stable, so Ollama's KV
                        # cache can actually hit. See _learning_system_prompt.
                        system=_learning_system_prompt(),
                        # think=False matters more than the model choice: qwen3
                        # is a reasoning model and its thinking tokens are pure
                        # cost here, since this prompt wants a JSON record, not
                        # a derivation. Measured 208s -> 64s on an idle box.
                        # Harmless on non-thinking models (verified on
                        # llama3.1:8b: HTTP 200, normal answer).
                        think=False,
                        **kwargs
                    ),
                    # "learning", not "executor": this path runs a full learning
                    # prompt through a local 8B model, which is measurably slower
                    # than what the executor budget was sized for. See the
                    # DEFAULT_TIMEOUTS["learning"] comment for the measurement.
                    timeout_sec=get_timeout_for_role("learning"),
                    label="router._ask_once(ollama)",
                )
        except _OLLAMA_TIMEOUT_EXC:
            logger.warning("[LLMRouter] _ask_once Ollama fallback timed out -> empty")
            result = ""
        self._record_tape("learning", learn_model, prompt, result, start,
                          route_reason=reason)
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

    def _is_nim_primary_role(self, role_name: str) -> bool:
        """
        Check if given role should route to NIM first (before local scheduler).

        Controlled by env var NIM_PRIMARY_ROLES (comma-separated role names).
        Empty/unset disables NIM-first routing for ask_as_role().

        Why: thinking models (e.g. glm-5.1) give qualitatively better
        reasoning for planner/learning/critic roles vs small local models.
        Fallback to scheduler on NIM failure preserves resilience.
        """
        primary = os.environ.get("NIM_PRIMARY_ROLES", "").strip()
        if not primary:
            return False
        roles = {r.strip() for r in primary.split(",") if r.strip()}
        return role_name in roles and self._should_use_nim()

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
        route_reason: str = "",
    ) -> None:
        """Record LLM interaction to tape (if attached)."""
        latency_ms = (time.time() - start_time) * 1000

        # Update current episode trace with LLM call stats
        try:
            from agent_core.tracing.episode import get_current_trace
            trace = get_current_trace()
            if trace is not None:
                trace.total_llm_calls += 1
                trace.total_llm_latency_ms += latency_ms
                if model and model not in trace.models_used:
                    trace.models_used.append(model)
        except (ImportError, AttributeError):
            pass

        if self._llm_tape is None:
            return
        try:
            from agent_core.llm.llm_tape import make_tape_entry
            is_success = success and bool(response and response.strip())
            entry = make_tape_entry(
                model=model or "unknown",
                role=role,
                prompt=prompt or "",
                response=response or "",
                latency_ms=latency_ms,
                success=is_success,
                # Failure reasons carry the upstream error body (NIM returns up
                # to 500 chars of JSON). Unbounded, that rides along in EVERY
                # frame -- the same shape as the 201 MB tap blowup (5d1710c).
                route_reason=(route_reason or "")[:MAX_ROUTE_REASON],
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

    def get_model_scheduler(self):
        """Return the attached ModelScheduler (or None).

        Lets heavy LOCAL paths that call Ollama directly (e.g. the exam student
        answer in teacher_module) reach scheduler.heavy_lease() to serialize on
        the shared heavy mutex instead of bypassing it.
        """
        return self._model_scheduler

    def _bounded_ask_once(
        self, prompt: str, temperature: float, role_name: str
    ) -> str:
        """Ollama fallback bounded by the role timeout.

        ask_as_role() falls back to a direct ollama._ask_once() whenever the
        model scheduler cannot serve a role. Those calls used to be unbounded:
        on 2026-06-02 a wedged Ollama turned one into a permanent block that
        froze the entire tick loop for 10.5h. call_with_timeout() cannot cancel
        the underlying request, but it hands control back to the caller (and so
        the tick loop) after the role deadline; the empty string then degrades
        gracefully through the existing parse/fallback paths. Non-timeout errors
        still propagate exactly as before.
        """
        try:
            return call_with_timeout(
                lambda: self.ollama._ask_once(prompt, temperature=temperature),
                timeout_sec=get_timeout_for_role(role_name),
                label=f"ask_as_role_fallback({role_name})",
            )
        except _OLLAMA_TIMEOUT_EXC:
            logger.warning(
                "[LLMRouter] Ollama fallback for %s exceeded deadline -> empty",
                role_name,
            )
            return ""

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

        # NIM-first for primary cognitive roles (glm-5.1 test mode).
        # On failure: fall through to existing scheduler/Ollama path.
        if self._is_nim_primary_role(role_name):
            try:
                nim_start = time.time()
                text = self.nim._ask_once(prompt, temperature=temperature)
                self._record_nim_usage()
                self._nim_calls += 1
                self._record_tape(
                    role_name, self.nim.model, prompt, text, nim_start,
                    route_reason=f"nim_primary:{role_name}",
                )
                return text
            except Exception as e:
                logger.warning(
                    f"[LLMRouter] NIM primary failed for {role_name}: {e}, "
                    f"falling back to local scheduler"
                )
                self._nim_fallbacks += 1
                self._record_tape(
                    role_name, self.nim.model, prompt, "", nim_start,
                    success=False, route_reason=f"nim_primary_failed: {e}",
                )
                # Continue to scheduler/Ollama path below

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
            text = self._bounded_ask_once(prompt, temperature, role_name)
            self._record_tape(role_name, self.ollama.model, prompt, text, ask_start,
                              route_reason="no_scheduler_fallback_ollama")
            return text

        result = self._model_scheduler.ensure_ready(role)

        if not result.success:
            logger.warning(
                f"[LLMRouter] Cannot load {role_name}: {result.reason}, "
                f"falling back to Ollama"
            )
            self._ollama_calls += 1
            ask_start = time.time()
            text = self._bounded_ask_once(prompt, temperature, role_name)
            self._record_tape(role_name, self.ollama.model, prompt, text, ask_start,
                              route_reason=f"scheduler_fail:{result.reason}")
            return text

        # Use the model tag from scheduler (may be fallback)
        try:
            from agent_core.llm.execution_budget import call_with_timeout, get_timeout_for_role
            timeout = get_timeout_for_role(role_name)

            start = time.time()
            # Timeout-aware client (NOT the bare ollama_lib): this scheduler-success
            # branch is the PRIMARY live cognitive path on the tick thread. The bare
            # module client has no socket timeout, so the 2026-06-02 wedge here left
            # an immortal zombie holding a pool slot even though call_with_timeout
            # unblocked the caller. The shared client's httpx read-timeout tears the
            # socket down so the zombie actually dies and frees its slot.
            _client = get_ollama_client()
            resp = call_with_timeout(
                lambda: _client.chat(
                    model=result.ollama_tag,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": temperature},
                ),
                timeout_sec=timeout,
                label=f"ask_as_role({role_name}:{result.ollama_tag})",
            )
            latency = time.time() - start
            self._model_scheduler.record_request(result.role, latency)
            self._ollama_calls += 1

            text = resp.get("message", {}).get("content", "")
            text = text.strip()
            self._record_tape(role_name, result.ollama_tag, prompt, text, start,
                              route_reason=f"scheduler:{role_name}:{result.ollama_tag}")
            return text
        except Exception as e:
            logger.warning(
                f"[LLMRouter] ask_as_role({role.value}) inference failed: {e}"
            )
            self._ollama_calls += 1
            ask_start = time.time()
            text = self._bounded_ask_once(prompt, temperature, role_name)
            self._record_tape(role_name, self.ollama.model, prompt, text, ask_start,
                              success=False, route_reason=f"scheduler_inference_fail:{e}")
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
            except Exception as e:
                self._nim_fallbacks += 1
                self._record_tape("encyclopedia", self.nim.model, prompt, "", start,
                                  success=False,
                                  route_reason=f"nim_failed: {e}")

        # Fallback: Ollama -- bounded (see _bounded_ask_once); a wedged Ollama
        # must not hang an encyclopedia lookup that may run on the tick path.
        self._ollama_calls += 1
        result = self._bounded_ask_once(prompt, 0.3, "encyclopedia")
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
            stats["nim_chat_enabled"] = self.use_nim_for_chat
        else:
            stats["nim_model"] = None
            stats["nim_available"] = False
            stats["nim_chat_enabled"] = False

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
        """Get conversation history (from active chat backend)."""
        if self.use_nim_for_chat and self.nim is not None:
            return getattr(self.nim, "history", [])
        return getattr(self.ollama, "history", [])

    @history.setter
    def history(self, value):
        """Set conversation history (delegated to active chat backend)."""
        if self.use_nim_for_chat and self.nim is not None:
            if hasattr(self.nim, "history"):
                self.nim.history = value
        if hasattr(self.ollama, "history"):
            self.ollama.history = value
