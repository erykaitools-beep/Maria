# ollama_brain.py
# M.A.R.I.A. Brain V3.2 – Ulepszona logika z mechanizmem samonaprawy i celami nauki
# + Time Awareness (percepcja czasu)

import ollama
import json
import os
import re
from collections import deque
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable

# Time awareness - safe import
try:
    from agent_core.homeostasis.time_awareness import TimeAwareness
    TIME_AWARENESS_AVAILABLE = True
except ImportError:
    TIME_AWARENESS_AVAILABLE = False

# Awareness context - safe import
try:
    from agent_core.awareness import ContextBuilder
    _AWARENESS_BUILDER = ContextBuilder()
    AWARENESS_AVAILABLE = True
except Exception:
    _AWARENESS_BUILDER = None
    AWARENESS_AVAILABLE = False

# Master prompt - single source of truth
try:
    from agent_core.llm.master_prompt import build_full_prompt, build_base_prompt
    MASTER_PROMPT_AVAILABLE = True
except ImportError:
    MASTER_PROMPT_AVAILABLE = False

# HTTP read-timeout for the ollama client. The module-level ollama.chat() has no
# socket timeout, so a stalled inference hangs forever (2026-06-02 freeze root
# cause). We route every call through a timeout-aware ollama.Client instead.
try:
    from maria_core.sys.config import (
        OLLAMA_HTTP_TIMEOUT as _OLLAMA_HTTP_TIMEOUT,
        OLLAMA_KEEP_ALIVE as _OLLAMA_KEEP_ALIVE,
    )
except Exception:
    import os as _os
    _OLLAMA_HTTP_TIMEOUT = int(_os.environ.get("OLLAMA_HTTP_TIMEOUT", "240"))
    _OLLAMA_KEEP_ALIVE = _os.environ.get("OLLAMA_KEEP_ALIVE", "30m")


# --- Fast chat context (cache-stable prefix) -------------------------------
# On a CPU-only box, prefill runs at ~16 tok/s, so a full 4096-token chat
# history takes ~260s -- past the 240s HTTP read-timeout, so the chat dies
# before generating a token (confirmed live 2026-06-08, two turns at 221.9s /
# 240.4s for one-sentence prompts). Ollama DOES reuse the KV cache across
# separate /api/chat calls when the leading messages are byte identical
# (measured: stable prefix 1.7s vs a one-line system-message change 88.5s) --
# but refresh_time_context() rewrote the system message with the live clock
# every turn, busting that cache and forcing a full re-prefill each time.
# CHAT_FAST_CONTEXT keeps the system prefix byte-stable (only a COARSE date /
# part-of-day clock that shifts a few times a day, never the per-call HH:MM or
# session duration), sends each user turn clean==stored so the cache matches a
# turn back, and bounds the cold-cache context so even a MISS stays under the
# timeout. Ships OFF; set CHAT_FAST_CONTEXT=1 in .env and restart to verify
# live, then cut over.
def _fast_context_enabled() -> bool:
    return os.environ.get("CHAT_FAST_CONTEXT", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


# Cold-cache safety net: cap the actual context so a cache MISS (cold start, a
# slot eviction by interleaved Ollama work, or a coarse-time/trim prefix change)
# still prefills FAST. ~4 chars/token at ~16 tok/s: HIGH 4000 chars ~ 1000 tok
# ~ 64s cold prefill (measured: 3710 chars -> 64.7s end-to-end). This is sized
# to stay UNDER the UI chat read-timeout (config.CHAT_HTTP_TIMEOUT, default 75s)
# so the first chat after a restart does not trip the graceful "busy" path;
# keep HIGH/64 (~ cold seconds) comfortably below CHAT_TIMEOUT if you retune
# either. Hysteresis (trim to LOW only when over HIGH) keeps trims to ~1 per few
# exchanges: between trims the prefix is stable so warm turns hit the KV cache
# (~2-13s); the trim turn re-prefills the retained LOW (~2000 chars ~32s). Lower
# HIGH for snappier-but-shorter chat memory; raise it (with CHAT_TIMEOUT) for
# more context at the cost of a slower cold/trim turn.
_CHAT_CTX_HIGH_CHARS = int(os.environ.get("CHAT_CTX_HIGH_CHARS", "4000"))
_CHAT_CTX_LOW_CHARS = int(os.environ.get("CHAT_CTX_LOW_CHARS", "2000"))


# httpx underlies the ollama client. We need it to recognise a read/connect
# timeout explicitly: httpx.TimeoutException is NOT a subclass of the builtin
# TimeoutError (2026-06-02 freeze lesson), so `except TimeoutError` silently
# lets an HTTP read-timeout through. Guarded import in case the lib is absent.
try:
    import httpx as _httpx
except Exception:
    _httpx = None


class BrainTimeout(Exception):
    """The local model stalled and the HTTP call hit its read-timeout.

    Distinct from a normal empty result: think() returns "" for ordinary
    degrade (bad reply, non-timeout error) but raises THIS when the request
    actually timed out, so an interactive caller (Web UI chat) can tell the
    operator "I'm busy thinking" instead of showing nothing. Opt-in via
    think(..., raise_on_timeout=True); default callers still get "".
    """


def _is_timeout_error(e: Exception) -> bool:
    """True if the exception is a read/connect timeout (httpx OR builtin).

    httpx.TimeoutException (ReadTimeout/ConnectTimeout/...) is named explicitly
    because it does NOT inherit from the builtin TimeoutError/socket.timeout.
    The string check is a backstop for libs that surface the timeout only in
    the message (the live 2026-06-08 case logged a bare 'timed out').
    """
    if isinstance(e, TimeoutError):  # builtin; socket.timeout aliases this (py3.10+)
        return True
    if _httpx is not None and isinstance(e, _httpx.TimeoutException):
        return True
    msg = str(e).lower()
    return "timed out" in msg or "timeout" in msg


class OllamaBrain:
    def __init__(
        self,
        model: str = "llama3.1:8b",  # Domyślny, silny model (masz go w ollama list)
        system_prompt: Optional[str] = None,
        verify_model: bool = False,
        log_fn: Optional[Callable[[str], None]] = None,
        identity_store=None,
        http_timeout: Optional[int] = None,
    ):
        self.model = model
        self.log_fn = log_fn or print
        self._identity_store = identity_store
        # Per-instance HTTP read-timeout. Defaults to the shared OLLAMA_HTTP_TIMEOUT
        # (240s, learning-sized); the UI chat brain passes a shorter CHAT_HTTP_TIMEOUT
        # so an interactive turn fails fast instead of hanging for 4 minutes.
        self._http_timeout = (
            http_timeout if http_timeout is not None else _OLLAMA_HTTP_TIMEOUT
        )

        # Timeout-aware client: the module-level ollama.chat() has no socket
        # timeout, so a stalled inference would hang forever and zombie the
        # router's bounded call (2026-06-02 freeze). A real httpx read-timeout
        # tears the socket down so the call dies instead. Fall back to the
        # module-level API if an older ollama lib lacks Client(timeout=...).
        try:
            self._client = ollama.Client(timeout=self._http_timeout)
        except Exception as e:
            self.log_fn(f"[OllamaBrain] [WARN] Client(timeout) niedostepny, fallback bez timeoutu: {e}")
            self._client = ollama
        self._conversation_memory = None
        self._user_profile = None

        # Base system prompt (from master_prompt.py or fallback)
        if system_prompt:
            self._base_system_prompt = system_prompt
        elif MASTER_PROMPT_AVAILABLE:
            self._base_system_prompt = build_base_prompt()
        else:
            self._base_system_prompt = (
                "Jestes M.A.R.I.A. - Meta Analysis Recalibration Intelligence Architecture.\n"
                "Dzialasz precyzyjnie. Twoim celem jest strukturyzacja wiedzy.\n"
                "Odpowiadasz po polsku, chyba ze zadanie wymaga inaczej."
            )

        # Work context provider (set via set_work_context_provider)
        self._work_context_provider = None

        # LLM Tape for recording interactions (set via set_llm_tape)
        self._llm_tape = None

        # State-grounded operator response pipeline (Phase 2)
        self._query_router = None
        self._evidence_collector = None
        self._response_builder = None

        # Session tracking for time awareness
        self._session_start = datetime.now()
        self._last_interaction = datetime.now()

        # Full system prompt (will include time context)
        self.system_prompt = self._build_system_prompt()

        # Historia rozmowy - uzywana tylko przez think()
        # deque(maxlen=50) zapobiega nieograniczonemu wzrostowi pamieci
        self.history: deque = deque(maxlen=50)
        self.history.append({"role": "system", "content": self.system_prompt})
        self.call_count = 0

        if verify_model:
            self._verify_model_exists()

    def _get_time_context(self) -> str:
        """Get current time context for Maria's awareness."""
        now = datetime.now()

        # Calculate session duration
        session_seconds = (now - self._session_start).total_seconds()

        if TIME_AWARENESS_AVAILABLE:
            # Use TimeAwareness for rich context
            day_name = TimeAwareness.DAY_NAMES.get(now.weekday(), "")
            time_of_day = TimeAwareness.get_time_of_day()
            date_str = now.strftime("%d.%m.%Y")
            time_str = now.strftime("%H:%M")

            ctx = f"Teraz jest {day_name}, {date_str}, godzina {time_str} ({time_of_day})."

            if session_seconds > 300:  # > 5 min
                duration = TimeAwareness.format_duration(session_seconds)
                ctx += f" Rozmawiamy juz {duration}."

            if TimeAwareness.is_late_night():
                ctx += " Jest pozna pora."

            return ctx
        else:
            # Fallback - basic time info
            return f"Teraz jest {now.strftime('%A, %d.%m.%Y, %H:%M')}."

    def _get_identity_context(self) -> str:
        """Get identity context for system prompt."""
        if self._identity_store is None:
            return ""
        try:
            return self._identity_store.get_identity_context()
        except Exception:
            return ""

    def _get_conversation_context(self) -> str:
        """Get conversation memory context for system prompt."""
        if self._conversation_memory is None:
            return ""
        try:
            return self._conversation_memory.get_conversation_context(limit=3)
        except Exception:
            return ""

    def set_conversation_memory(self, memory) -> None:
        """
        Attach conversation memory for persistence. Call before first think().

        Restores previous session messages into history.

        Args:
            memory: ConversationMemory instance
        """
        self._conversation_memory = memory
        if memory:
            restored = memory.restore_history()
            if restored:
                for msg in restored:
                    self.history.append(msg)

    def set_user_profile(self, profile) -> None:
        """Attach user profile for context injection."""
        self._user_profile = profile

    def set_llm_tape(self, tape) -> None:
        """Attach LLM Tape for recording chat interactions."""
        self._llm_tape = tape

    def _record_tape(self, role: str, prompt: str, response: str,
                     start_time: float, success: bool = True) -> None:
        """Record interaction to tape if attached."""
        import time as _time
        latency_ms = (_time.time() - start_time) * 1000

        # Update current episode trace with LLM call stats
        try:
            from agent_core.tracing.episode import get_current_trace
            trace = get_current_trace()
            if trace is not None:
                trace.total_llm_calls += 1
                trace.total_llm_latency_ms += latency_ms
                if self.model and self.model not in trace.models_used:
                    trace.models_used.append(self.model)
        except (ImportError, AttributeError):
            pass

        if self._llm_tape is None:
            return
        try:
            from agent_core.llm.llm_tape import make_tape_entry
            entry = make_tape_entry(
                model=self.model,
                role=role,
                prompt=prompt or "",
                response=response or "",
                latency_ms=latency_ms,
                success=success and bool(response and response.strip()),
            )
            self._llm_tape.record(entry)
        except Exception:
            pass

    def set_grounding_pipeline(self, query_router, evidence_collector, response_builder):
        """
        Wire the state-grounded operator response pipeline.

        When operator asks about Maria's state, the pipeline:
        1. QueryRouter classifies the question (rule-based, zero LLM)
        2. EvidenceCollector gathers facts from logs/runtime
        3. ResponseBuilder creates structured answer from evidence
        4. Optional: LLM formats the answer (but evidence is the truth)
        """
        self._query_router = query_router
        self._evidence_collector = evidence_collector
        self._response_builder = response_builder

    def set_work_context_provider(self, provider) -> None:
        """
        Set a callable that returns current work status as text.

        Called during system prompt build to inject planner/experiment/learning context.
        The provider should return a short string (max ~200 chars) or empty string.
        """
        self._work_context_provider = provider

    def _get_work_context(self) -> str:
        """Get current work status from planner/experiment/learning systems."""
        if self._work_context_provider is None:
            return ""
        try:
            return self._work_context_provider()
        except Exception:
            return ""

    def _get_awareness_context(self) -> str:
        """Get self-awareness context (files, memory, code, system)."""
        if not AWARENESS_AVAILABLE or _AWARENESS_BUILDER is None:
            return ""
        try:
            return _AWARENESS_BUILDER.build()
        except Exception:
            return ""

    def _build_system_prompt(self) -> str:
        """Build full system prompt with time, identity, conversation, work, and awareness context."""
        time_ctx = self._get_time_context()
        identity_ctx = self._get_identity_context()
        conversation_ctx = self._get_conversation_context()
        work_ctx = self._get_work_context()
        awareness_ctx = self._get_awareness_context()

        # User profile context
        user_ctx = ""
        if self._user_profile:
            try:
                user_ctx = self._user_profile.get_context_for_prompt()
            except Exception:
                pass

        # Operational summary (replaces awareness if available)
        op_summary = ""
        if self._evidence_collector:
            try:
                op_summary = self._evidence_collector.build_compact_summary()
            except Exception:
                pass

        if MASTER_PROMPT_AVAILABLE:
            return build_full_prompt(
                time_context=time_ctx,
                identity_context=identity_ctx,
                user_context=user_ctx,
                work_context=work_ctx,
                conversation_context=conversation_ctx,
                awareness_context=awareness_ctx,
                operational_summary=op_summary,
                grounding_active=bool(self._query_router),
            )

        # Fallback: inline assembly (same logic as master_prompt.build_full_prompt)
        prompt = f"{self._base_system_prompt}\n\n[Kontekst czasowy: {time_ctx}]"
        if identity_ctx:
            prompt += f"\n[Tozsamosc: {identity_ctx}]"
        if user_ctx:
            prompt += f"\n{user_ctx}"
        if work_ctx:
            prompt += f"\n[Aktualna praca: {work_ctx}]"
        if conversation_ctx:
            prompt += f"\n{conversation_ctx}"
        if op_summary:
            prompt += f"\n{op_summary}"
        elif awareness_ctx:
            prompt += f"\n{awareness_ctx}"
        if self._query_router:
            prompt += (
                "\nGdy operator pyta o Twoj stan, logi lub bledy, "
                "odpowiadaj na podstawie danych operacyjnych. "
                "Mow 'Widze w logach...', 'Zrodlo danych: ...'. "
                "Nigdy nie wymyslaj informacji o wlasnym stanie."
            )
        return prompt

    # === CACHE-STABLE CHAT CONTEXT (CHAT_FAST_CONTEXT) ===

    def _build_stable_system_prompt(self) -> str:
        """System prompt WITHOUT volatile per-call context (clock/work/op).

        This is the cached KV prefix. Keeping it byte-identical across calls
        lets Ollama reuse the prefill instead of recomputing the whole context
        every turn (the measured ~90-260s -> ~2s win). The volatile bits live
        in _build_situational_tail() and ride on the latest user message, so
        they sit AFTER the cached prefix and never invalidate it.
        """
        identity_ctx = self._get_identity_context()
        conversation_ctx = self._get_conversation_context()
        user_ctx = ""
        if self._user_profile:
            try:
                user_ctx = self._user_profile.get_context_for_prompt()
            except Exception:
                pass

        if MASTER_PROMPT_AVAILABLE:
            return build_full_prompt(
                time_context=self._get_coarse_time_context(),
                identity_context=identity_ctx,
                user_context=user_ctx,
                work_context="",
                conversation_context=conversation_ctx,
                awareness_context="",
                operational_summary="",
                grounding_active=bool(self._query_router),
            )
        prompt = self._base_system_prompt
        coarse_time = self._get_coarse_time_context()
        if coarse_time:
            prompt += f"\n\n[Kontekst czasowy: {coarse_time}]"
        if identity_ctx:
            prompt += f"\n[Tozsamosc: {identity_ctx}]"
        if user_ctx:
            prompt += f"\n{user_ctx}"
        if conversation_ctx:
            prompt += f"\n{conversation_ctx}"
        return prompt

    def _get_coarse_time_context(self) -> str:
        """Coarse, slowly-changing time for the CACHED prefix: date + part of day.

        Deliberately excludes HH:MM and session duration -- those change every
        call and would bust the KV cache (the 2026-06-08 bug: rewriting the
        clock each turn forced a full re-prefill -> 240s timeout). Coarse time
        shifts only a handful of times a day (part-of-day / date), so the prefix
        stays cache-stable for hours. Precise time/state queries go through the
        grounded pipeline, which rebuilds fresh anyway.
        """
        now = datetime.now()
        if TIME_AWARENESS_AVAILABLE:
            day_name = TimeAwareness.DAY_NAMES.get(now.weekday(), "")
            time_of_day = TimeAwareness.get_time_of_day()
            date_str = now.strftime("%d.%m.%Y")
            return f"{day_name}, {date_str} ({time_of_day})"
        return now.strftime("%A, %d.%m.%Y")

    def _trim_turns_to_budget(self, turns: List[Dict[str, str]],
                              base_chars: int) -> List[Dict[str, str]]:
        """Hysteresis-bound the conversation turns sent to Ollama.

        Drops the OLDEST turns only when the total context exceeds HIGH, down
        to LOW -- so trims happen once every few exchanges rather than every
        call, keeping the warm-cache prefix stable between trims. Always keeps
        at least the most recent turn.
        """
        def total(ts: List[Dict[str, str]]) -> int:
            return base_chars + sum(len(m.get("content", "")) for m in ts)

        if total(turns) <= _CHAT_CTX_HIGH_CHARS:
            return turns
        trimmed = list(turns)
        while len(trimmed) > 1 and total(trimmed) > _CHAT_CTX_LOW_CHARS:
            trimmed.pop(0)
        return trimmed

    def _compose_send_messages(self, prompt: str) -> List[Dict[str, str]]:
        """Bounded, cache-stable message list for a normal chat turn.

        [stable system prefix] + [recent turns within budget] + [latest user
        turn, CLEAN]. The new user turn is sent exactly as it will be stored
        (no per-call decoration), so on the next turn the cached prefix matches
        byte-for-byte through this message and Ollama re-prefills only the new
        tokens (~2-10s) instead of the whole history (~260s -> read-timeout).
        Sending a decorated copy while storing a clean one would diverge the
        cache one turn back on every call -- the trap an earlier draft hit.
        """
        stable_sys = self._build_stable_system_prompt()
        turns = [m for m in self.history if m.get("role") != "system"]
        turns = self._trim_turns_to_budget(turns, len(stable_sys))
        return (
            [{"role": "system", "content": stable_sys}]
            + turns
            + [{"role": "user", "content": prompt}]
        )

    def refresh_time_context(self) -> None:
        """Refresh time context in system prompt and history."""
        self._last_interaction = datetime.now()
        self.system_prompt = self._build_system_prompt()

        # Update system message in history (or re-insert if rotated out by deque)
        if self.history and self.history[0]["role"] == "system":
            self.history[0]["content"] = self.system_prompt
        else:
            self.history.appendleft({"role": "system", "content": self.system_prompt})

    def _verify_model_exists(self):
        try:
            # Timeout-aware client so a hung daemon can't block startup verify.
            info = self._client.list()
            models_raw = info.get("models", [])

            # DEBUG: pokaż, co naprawdę zwraca ollama.list()
            available_names = []
            for m in models_raw:
                name = m.get("name") or m.get("model") or ""
                available_names.append(name)

            self.log_fn(f"[OllamaBrain] [SCAN] Dostepne modele wg ollama.list(): {available_names}")

            # Akceptuj zarówno 'name', jak i 'model'
            available = set(available_names)
            if self.model not in available:
                self.log_fn(
                    f"[OllamaBrain] [WARN] UWAGA: Model '{self.model}' nie znaleziony w {available}."
                )
        except Exception as e:
            self.log_fn(f"[OllamaBrain] [WARN] Blad podczas verify_model: {e}")
            # Nie chcemy, żeby brak połączenia ubił cały mózg
            pass


    # === NISKI POZIOM – SUROWE WYWOŁANIA ===

    def _chat(self, messages: List[Dict[str, str]], temperature: float = 0.3,
              force_json: bool = False, **kwargs) -> str:
        """Surowe wywołanie ollama.chat z listą wiadomości."""
        options = {"temperature": temperature, "num_ctx": 4096}
        options.update(kwargs)

        # Pin the model warm between calls (mirrors the learning path's b12dd7f
        # fix). Without it the server's 5-min default unloads the model, so the
        # next call cold-starts on CPU (~240s) and can hit the HTTP read-timeout
        # -> a spurious empty result. keep_alive keeps cold-starts rare.
        chat_kwargs = {
            "model": self.model,
            "messages": messages,
            "options": options,
            "keep_alive": _OLLAMA_KEEP_ALIVE,
        }
        if force_json:
            chat_kwargs["format"] = "json"

        # Use the timeout-aware client (see __init__). On a stall, httpx raises a
        # TimeoutException here instead of hanging forever; it propagates like any
        # other Ollama error (think() catches it, router bounds it, callers degrade).
        resp = self._client.chat(**chat_kwargs)
        content = resp.get("message", {}).get("content", "")
        return content.strip()

    def _ask_once(self, prompt: str, temperature: float = 0.3,
                  force_json: bool = False, **kwargs) -> str:
        """
        Jednorazowe pytanie: system + user (bez historii).
        Idealne do zadań typu: 'zwróć mi JSON wg schematu'.
        Caller may set force_json=True to enable Ollama native JSON mode.
        """
        import time as _time
        start = _time.time()
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]
        result = self._chat(messages, temperature=temperature,
                            force_json=force_json, **kwargs)
        self._record_tape("learning", prompt, result, start)
        return result

    # === GŁÓWNE API – THINK Z HISTORIĄ ===

    def think(self, prompt: str, temperature: float = 0.3,
              raise_on_timeout: bool = False, **kwargs) -> str:
        """
        Myslenie z historia rozmowy (do ogolnego dialogu i rozumowania).
        NIE uzywamy tego do strukturalnego JSON (tam jest _ask_once).

        If the grounding pipeline is wired and the question is about
        Maria's operational state, the answer is built from evidence
        (logs, runtime objects) instead of letting LLM hallucinate.

        raise_on_timeout: when True, a real HTTP read-timeout is re-raised as
        BrainTimeout instead of being swallowed into "" -- lets an interactive
        caller (Web UI chat) distinguish "model stalled" from "empty reply" and
        show a graceful busy message. Default False preserves the historical
        degrade-to-"" contract for every other caller (router, REPL, daemon).
        """
        self.call_count += 1
        import time as _time
        start = _time.time()

        # Refresh time context before each interaction
        self.refresh_time_context()

        # State-grounded pipeline: check if this is an operational query
        if self._query_router and self._evidence_collector and self._response_builder:
            try:
                mode = self._query_router.classify(prompt)
                if self._query_router.is_grounded(mode):
                    return self._grounded_think(prompt, mode, temperature, start, **kwargs)
            except Exception:
                pass  # Fallback to normal chat

        # Normal chat path. CHAT_FAST_CONTEXT sends a cache-stable, bounded
        # message list (byte-stable system prefix with only a coarse clock, plus
        # budgeted recent turns, the new user turn sent clean==stored) so Ollama
        # reuses the KV cache instead of re-prefilling the whole history every
        # turn (~260s -> read-timeout on this CPU box). Compose BEFORE storing
        # the new turn so the cached prefix matches a turn back; legacy path
        # (flag off) sends the full mutable history object unchanged.
        fast = _fast_context_enabled()
        if fast:
            messages = self._compose_send_messages(prompt)
        self.history.append({"role": "user", "content": prompt})
        if not fast:
            messages = self.history
        if self._conversation_memory:
            self._conversation_memory.save_turn("user", prompt)
        if self._user_profile:
            try:
                self._user_profile.learn_from_message(prompt)
                self._user_profile.record_interaction()
            except Exception:
                pass

        try:
            content = self._chat(messages, temperature=temperature, **kwargs)
            self.history.append({"role": "assistant", "content": content})
            if self._conversation_memory:
                self._conversation_memory.save_turn("assistant", content)
            self._record_tape("chat", prompt, content, start)
            return content
        except Exception as e:
            self._record_tape("chat", prompt, "", start, success=False)
            # A real read-timeout is a different failure than a bad/empty reply:
            # the model is alive but busy (planner/learning on CPU, or cold-start).
            # Surface it as a typed error so an interactive caller can say so,
            # instead of returning "" that looks identical to "no answer".
            if _is_timeout_error(e):
                self.log_fn(f"[OllamaBrain] [TIMEOUT] Model stall (read-timeout): {e}")
                if raise_on_timeout:
                    raise BrainTimeout(str(e) or "read-timeout") from e
                return ""
            self.log_fn(f"[OllamaBrain] [ERROR] Blad krytyczny API: {e}")
            return ""

    def _grounded_think(self, prompt: str, mode, temperature: float,
                        start_time: float, **kwargs) -> str:
        """
        Answer operational question from evidence, not hallucination.

        Pipeline:
        1. Collect evidence for the detected mode
        2. Build structured grounded response (no LLM)
        3. Try LLM formatting for nicer output (optional)
        4. Fallback: return raw grounded text
        """
        import time as _time

        # 1. Collect evidence
        evidence = self._evidence_collector.collect_for_mode(mode, query_text=prompt)
        grounded = self._response_builder.build(mode, evidence, prompt)

        # 2. Try LLM formatting (optional improvement)
        try:
            from agent_core.introspection.query_router import ResponseMode as _RM
            if mode == _RM.GROUNDED_VISION:
                format_prompt = (
                    f"Operator pyta: {prompt}\n\n"
                    f"Masz kamere USB (oko) i widzisz otoczenie. "
                    f"Oto co teraz widzisz:\n"
                    f"{grounded.text}\n\n"
                    f"Odpowiedz naturalnie po polsku opisujac co widzisz. "
                    f"Mow w pierwszej osobie: 'Widze...', 'Przed soba mam...'. "
                    f"NIE dodawaj informacji spoza danych."
                )
            else:
                format_prompt = (
                    f"Operator pyta: {prompt}\n\n"
                    f"Odpowiedz WYLACZNIE na podstawie tych danych operacyjnych:\n"
                    f"{grounded.text}\n\n"
                    f"Formatuj naturalnie po polsku. NIE dodawaj informacji spoza danych. "
                    f"Uzyj zwrotow: 'Widze w logach...', 'Ostatnia akcja to...'. "
                    f"Podaj zrodla danych."
                )
            # Use a fresh message list (not history) for grounded formatting
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": format_prompt},
            ]
            formatted = self._chat(messages, temperature=0.2, **kwargs)

            if formatted and formatted.strip():
                grounded.formatted_text = formatted
                # Save to history as if normal conversation
                self.history.append({"role": "user", "content": prompt})
                self.history.append({"role": "assistant", "content": formatted})
                if self._conversation_memory:
                    self._conversation_memory.save_turn("user", prompt)
                    self._conversation_memory.save_turn("assistant", formatted)
                self._record_tape("chat_grounded", prompt, formatted, start_time)
                return formatted
        except Exception:
            pass

        # 3. Fallback: raw grounded text (always works, no LLM needed)
        self.history.append({"role": "user", "content": prompt})
        self.history.append({"role": "assistant", "content": grounded.text})
        if self._conversation_memory:
            self._conversation_memory.save_turn("user", prompt)
            self._conversation_memory.save_turn("assistant", grounded.text)
        self._record_tape("chat_grounded_raw", prompt, grounded.text, start_time)
        return grounded.text

    # === JSON HELPER ===

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Pomocnicza funkcja wyciągająca JSON z brudnego tekstu.
        - Czyści ``` ``` otoczki
        - Próbujemy 'na czysto'
        - Jak się nie uda, szukamy pierwszego bloku {...}
        """
        if not text:
            return None

        # usuń ewentualne ```json ... ``` / ``` ... ```
        cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
        cleaned = cleaned.replace("```", "").strip()

        # 1. Próba czysta
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 2. Szukanie klamerek – wersja bardziej ostrożna
        match = re.search(r"\{.*?\}", cleaned, re.DOTALL)
        if match:
            candidate = match.group().strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                return None

        return None

    # === ANALIZA ZADANIA Z SAMONAPRAWĄ ===

    def analyze_task(self, task: str, retries: int = 2) -> Dict[str, Any]:
        """
        Analiza zadania z mechanizmem SAMONAPRAWY (Retry Logic).
        Jeśli model zwróci zły JSON, prosimy go o poprawkę.

        DODATKOWO:
        - learning_goals: lista celów do nauki
        - unknown_terms: pojęcia, które wymagają wyjaśnienia
        """
        schema = """
        {
            "main_task": "str",
            "subtasks": ["str", "str"],
            "memory_facts": [["podmiot", "relacja", "obiekt"]],
            "learning_goals": ["str"],
            "unknown_terms": ["str"],
            "priority": "low|medium|high"
        }
        """

        base_prompt = (
            f"Przeanalizuj to: '{task}'. "
            f"Zwróć TYLKO JSON zgodny z tym schematem: {schema}\n"
            f"Jeśli czegoś nie wiesz, wpisz pustą listę lub 'low' dla priorytetu."
        )

        prompt = base_prompt
        parsed: Optional[Dict[str, Any]] = None

        for attempt in range(retries + 1):
            try:
                response = self._ask_once(prompt, temperature=0.1)
            except Exception as e:
                self.log_fn(f"[OllamaBrain] [ERROR] Blad API przy analizie zadania: {e}")
                break

            parsed = self._extract_json(response)

            if parsed is not None:
                break

            # Porażka - prosimy o poprawkę (Samonaprawa)
            self.log_fn(
                f"[OllamaBrain] [WARN] Proba {attempt + 1}: Zly JSON. Prosze model o poprawke..."
            )
            prompt = (
                "Twój poprzedni JSON był niepoprawny składniowo. "
                "Wyślij teraz sam CZYSTY JSON zgodny ze schematem, bez żadnych komentarzy ani tekstu."
            )

        # Fallback albo normalizacja wyniku
        if parsed is None or not isinstance(parsed, dict):
            return {
                "main_task": task[:100],
                "subtasks": ["Analiza nieudana - wymagana interwencja"],
                "memory_facts": [],
                "learning_goals": [],
                "unknown_terms": [],
                "priority": "high",
            }

        # Normalizacja pól – żebyś zawsze miał komplet kluczy
        parsed.setdefault("main_task", task[:100])
        parsed.setdefault("subtasks", [])
        parsed.setdefault("memory_facts", [])
        parsed.setdefault("learning_goals", [])
        parsed.setdefault("unknown_terms", [])
        parsed.setdefault("priority", "low")

        # Bezpieczeństwo typów
        if not isinstance(parsed["subtasks"], list):
            parsed["subtasks"] = [str(parsed["subtasks"])]

        if not isinstance(parsed["memory_facts"], list):
            parsed["memory_facts"] = []

        if not isinstance(parsed["learning_goals"], list):
            parsed["learning_goals"] = []

        if not isinstance(parsed["unknown_terms"], list):
            parsed["unknown_terms"] = []

        priority = str(parsed.get("priority", "low")).lower()
        if priority not in ("low", "medium", "high"):
            priority = "low"
        parsed["priority"] = priority

        return parsed
