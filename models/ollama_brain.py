# ollama_brain.py
# M.A.R.I.A. Brain V3.1 – Ulepszona logika z mechanizmem samonaprawy i celami nauki

import ollama
import json
import re
from typing import Optional, Dict, Any, List, Callable


class OllamaBrain:
    def __init__(
        self,
        model: str = "llama3.1:8b",  # Domyślny, silny model (masz go w ollama list)
        system_prompt: Optional[str] = None,
        verify_model: bool = False,
        log_fn: Optional[Callable[[str], None]] = None
    ):
        self.model = model
        self.log_fn = log_fn or print

        self.system_prompt = system_prompt or (
            "Jesteś M.A.R.I.A. – Meta Analysis Recalibration Intelligence Architecture.\n"
            "Działasz precyzyjnie. Twoim celem jest strukturyzacja wiedzy.\n"
            "Odpowiadasz po polsku, chyba że zadanie wymaga inaczej."
        )

        # Historia rozmowy – używana tylko przez think()
        self.history: List[Dict[str, str]] = [
            {"role": "system", "content": self.system_prompt}
        ]
        self.call_count = 0

        if verify_model:
            self._verify_model_exists()

    def _verify_model_exists(self):
        try:
            info = ollama.list()
            models_raw = info.get("models", [])

            # DEBUG: pokaż, co naprawdę zwraca ollama.list()
            available_names = []
            for m in models_raw:
                name = m.get("name") or m.get("model") or ""
                available_names.append(name)

            self.log_fn(f"[OllamaBrain] 🔍 Dostępne modele wg ollama.list(): {available_names}")

            # Akceptuj zarówno 'name', jak i 'model'
            available = set(available_names)
            if self.model not in available:
                self.log_fn(
                    f"[OllamaBrain] ⚠ UWAGA: Model '{self.model}' nie znaleziony w {available}."
                )
        except Exception as e:
            self.log_fn(f"[OllamaBrain] ⚠ Błąd podczas verify_model: {e}")
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
        Myślenie z historią rozmowy (do ogólnego dialogu i rozumowania).
        NIE używamy tego do strukturalnego JSON (tam jest _ask_once).
        """
        self.call_count += 1
        self.history.append({"role": "user", "content": prompt})

        try:
            content = self._chat(self.history, temperature=temperature, **kwargs)
            self.history.append({"role": "assistant", "content": content})
            return content
        except Exception as e:
            self.log_fn(f"[OllamaBrain] ❌ Błąd krytyczny API: {e}")
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
                self.log_fn(f"[OllamaBrain] ❌ Błąd API przy analizie zadania: {e}")
                break

            parsed = self._extract_json(response)

            if parsed is not None:
                break

            # Porażka - prosimy o poprawkę (Samonaprawa)
            self.log_fn(
                f"[OllamaBrain] ⚠ Próba {attempt + 1}: Zły JSON. Proszę model o poprawkę..."
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
