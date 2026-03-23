# ollama_brain.py
# M.A.R.I.A. Brain V3.2 – Ulepszona logika z mechanizmem samonaprawy i celami nauki
# + Time Awareness (percepcja czasu)

import ollama
import json
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


class OllamaBrain:
    def __init__(
        self,
        model: str = "llama3.1:8b",  # Domyślny, silny model (masz go w ollama list)
        system_prompt: Optional[str] = None,
        verify_model: bool = False,
        log_fn: Optional[Callable[[str], None]] = None,
        identity_store=None,
    ):
        self.model = model
        self.log_fn = log_fn or print
        self._identity_store = identity_store
        self._conversation_memory = None

        # Base system prompt (static part)
        self._base_system_prompt = system_prompt or (
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

    def set_llm_tape(self, tape) -> None:
        """Attach LLM Tape for recording chat interactions."""
        self._llm_tape = tape

    def _record_tape(self, role: str, prompt: str, response: str,
                     start_time: float, success: bool = True) -> None:
        """Record interaction to tape if attached."""
        if self._llm_tape is None:
            return
        try:
            from agent_core.llm.llm_tape import make_tape_entry
            import time as _time
            entry = make_tape_entry(
                model=self.model,
                role=role,
                prompt=prompt or "",
                response=response or "",
                latency_ms=(_time.time() - start_time) * 1000,
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

        prompt = f"{self._base_system_prompt}\n\n[Kontekst czasowy: {time_ctx}]"
        if identity_ctx:
            prompt += f"\n[Tozsamosc: {identity_ctx}]"
        if work_ctx:
            prompt += f"\n[Aktualna praca: {work_ctx}]"
        if conversation_ctx:
            prompt += f"\n{conversation_ctx}"

        # Compact operational summary (replaces/supplements awareness context)
        op_summary = ""
        if self._evidence_collector:
            try:
                op_summary = self._evidence_collector.build_compact_summary()
            except Exception:
                pass
        if op_summary:
            prompt += f"\n{op_summary}"
        elif awareness_ctx:
            prompt += f"\n{awareness_ctx}"

        # Grounding instruction
        if self._query_router:
            prompt += (
                "\nGdy operator pyta o Twoj stan, logi lub bledy, "
                "odpowiadaj na podstawie danych operacyjnych. "
                "Mow 'Widze w logach...', 'Zrodlo danych: ...'. "
                "Nigdy nie wymyslaj informacji o wlasnym stanie."
            )

        return prompt

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
            info = ollama.list()
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

    def _chat(self, messages: List[Dict[str, str]], temperature: float = 0.3, **kwargs) -> str:
        """Surowe wywołanie ollama.chat z listą wiadomości."""
        options = {"temperature": temperature, "num_ctx": 4096}
        options.update(kwargs)

        resp = ollama.chat(model=self.model, messages=messages, options=options)
        content = resp.get("message", {}).get("content", "")
        return content.strip()

    def _ask_once(self, prompt: str, temperature: float = 0.3, **kwargs) -> str:
        """
        Jednorazowe pytanie: system + user (bez historii).
        Idealne do zadań typu: 'zwróć mi JSON wg schematu'.
        """
        import time as _time
        start = _time.time()
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]
        result = self._chat(messages, temperature=temperature, **kwargs)
        self._record_tape("learning", prompt, result, start)
        return result

    # === GŁÓWNE API – THINK Z HISTORIĄ ===

    def think(self, prompt: str, temperature: float = 0.3, **kwargs) -> str:
        """
        Myslenie z historia rozmowy (do ogolnego dialogu i rozumowania).
        NIE uzywamy tego do strukturalnego JSON (tam jest _ask_once).

        If the grounding pipeline is wired and the question is about
        Maria's operational state, the answer is built from evidence
        (logs, runtime objects) instead of letting LLM hallucinate.
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

        # Normal chat path
        self.history.append({"role": "user", "content": prompt})
        if self._conversation_memory:
            self._conversation_memory.save_turn("user", prompt)

        try:
            content = self._chat(self.history, temperature=temperature, **kwargs)
            self.history.append({"role": "assistant", "content": content})
            if self._conversation_memory:
                self._conversation_memory.save_turn("assistant", content)
            self._record_tape("chat", prompt, content, start)
            return content
        except Exception as e:
            self.log_fn(f"[OllamaBrain] [ERROR] Blad krytyczny API: {e}")
            self._record_tape("chat", prompt, "", start, success=False)
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
        evidence = self._evidence_collector.collect_for_mode(mode)
        grounded = self._response_builder.build(mode, evidence, prompt)

        # 2. Try LLM formatting (optional improvement)
        try:
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
