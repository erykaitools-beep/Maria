# ollama_brain.py
# M.A.R.I.A. Brain V3.2 – Ulepszona logika z mechanizmem samonaprawy i celami nauki
# + Time Awareness (percepcja czasu)

import ollama
import json
import re
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

        # Session tracking for time awareness
        self._session_start = datetime.now()
        self._last_interaction = datetime.now()

        # Full system prompt (will include time context)
        self.system_prompt = self._build_system_prompt()

        # Historia rozmowy - uzywana tylko przez think()
        self.history: List[Dict[str, str]] = [
            {"role": "system", "content": self.system_prompt}
        ]
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

    def _get_awareness_context(self) -> str:
        """Get self-awareness context (files, memory, code, system)."""
        if not AWARENESS_AVAILABLE or _AWARENESS_BUILDER is None:
            return ""
        try:
            return _AWARENESS_BUILDER.build()
        except Exception:
            return ""

    def _build_system_prompt(self) -> str:
        """Build full system prompt with time, identity, conversation, and awareness context."""
        time_ctx = self._get_time_context()
        identity_ctx = self._get_identity_context()
        conversation_ctx = self._get_conversation_context()
        awareness_ctx = self._get_awareness_context()

        prompt = f"{self._base_system_prompt}\n\n[Kontekst czasowy: {time_ctx}]"
        if identity_ctx:
            prompt += f"\n[Tozsamosc: {identity_ctx}]"
        if conversation_ctx:
            prompt += f"\n{conversation_ctx}"
        if awareness_ctx:
            prompt += f"\n{awareness_ctx}"
        return prompt

    def refresh_time_context(self) -> None:
        """Refresh time context in system prompt and history."""
        self._last_interaction = datetime.now()
        self.system_prompt = self._build_system_prompt()

        # Update system message in history
        if self.history and self.history[0]["role"] == "system":
            self.history[0]["content"] = self.system_prompt

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
        options = {"temperature": temperature}
        options.update(kwargs)

        resp = ollama.chat(model=self.model, messages=messages, options=options)
        content = resp.get("message", {}).get("content", "")
        return content.strip()

    def _ask_once(self, prompt: str, temperature: float = 0.3, **kwargs) -> str:
        """
        Jednorazowe pytanie: system + user (bez historii).
        Idealne do zadań typu: 'zwróć mi JSON wg schematu'.
        """
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]
        return self._chat(messages, temperature=temperature, **kwargs)

    # === GŁÓWNE API – THINK Z HISTORIĄ ===

    def think(self, prompt: str, temperature: float = 0.3, **kwargs) -> str:
        """
        Myslenie z historia rozmowy (do ogolnego dialogu i rozumowania).
        NIE uzywamy tego do strukturalnego JSON (tam jest _ask_once).
        """
        self.call_count += 1

        # Refresh time context before each interaction
        self.refresh_time_context()

        self.history.append({"role": "user", "content": prompt})
        if self._conversation_memory:
            self._conversation_memory.save_turn("user", prompt)

        try:
            content = self._chat(self.history, temperature=temperature, **kwargs)
            self.history.append({"role": "assistant", "content": content})
            if self._conversation_memory:
                self._conversation_memory.save_turn("assistant", content)
            return content
        except Exception as e:
            self.log_fn(f"[OllamaBrain] [ERROR] Blad krytyczny API: {e}")
            return ""

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
