"""
NVIDIA NIM API Client - OpenAI-compatible LLM client.

Provides the same interface as OllamaBrain (think, _ask_once, analyze_task)
but calls NVIDIA NIM API instead of local Ollama.

Used for learning tasks (stronger model, better results).
Chat stays on local Ollama (offline, fast).
"""

import json
import logging
import re
import time
import requests
from typing import Dict, Any, Optional, List, Callable

logger = logging.getLogger(__name__)


class NIMClient:
    """
    NVIDIA NIM API client with OpenAI-compatible interface.

    Compatible with OllamaBrain API:
    - think(prompt) -> str          (chat with history)
    - _ask_once(prompt) -> str      (one-shot, no history)
    - analyze_task(task) -> Dict    (JSON extraction with retry)

    Additional features:
    - Token usage tracking per call
    - Retry with exponential backoff (rate limits)
    - Health check and availability detection
    """

    # Default NIM API endpoint
    DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"

    # Retry settings
    MAX_RETRIES = 3          # used for rate limit (429)
    MAX_TIMEOUT_RETRIES = 1  # fail fast on timeout, fallback to Ollama
    RETRY_BASE_DELAY = 1.0   # seconds
    RETRY_BACKOFF = 2.0      # exponential multiplier

    def __init__(
        self,
        api_key: str,
        model: str = "nvidia/llama-3.1-nemotron-70b-instruct",
        base_url: Optional[str] = None,
        timeout: int = 45,
        system_prompt: Optional[str] = None,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize NIM API client.

        Args:
            api_key: NVIDIA NIM API key
            model: Model identifier
            base_url: API base URL (default: NIM cloud)
            timeout: Request timeout in seconds
            system_prompt: System prompt for conversations
            log_fn: Logging function (default: print)
        """
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.log_fn = log_fn or print

        self.system_prompt = system_prompt or (
            "Jestes M.A.R.I.A. - Meta Analysis Recalibration Intelligence Architecture.\n"
            "Dzialasz precyzyjnie. Twoim celem jest strukturyzacja wiedzy.\n"
            "Odpowiadasz po polsku, chyba ze zadanie wymaga inaczej."
        )

        # Conversation history (for think())
        self.history: List[Dict[str, str]] = [
            {"role": "system", "content": self.system_prompt}
        ]
        self.call_count = 0

        # Token tracking (per-call, last call)
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0

    # -------------------------------------------------
    # LOW-LEVEL API CALL
    # -------------------------------------------------

    def _chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> str:
        """
        Raw API call to NIM (OpenAI-compatible format).

        Args:
            messages: Chat messages [{"role": "...", "content": "..."}]
            temperature: Sampling temperature
            max_tokens: Maximum response tokens

        Returns:
            Response content text

        Raises:
            NIMAPIError: On API failure after retries
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        last_error = None
        timeout_count = 0
        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )

                # Rate limit - retry with backoff
                if response.status_code == 429:
                    delay = self.RETRY_BASE_DELAY * (
                        self.RETRY_BACKOFF ** attempt
                    )
                    logger.warning(
                        f"NIM rate limit hit, retry in {delay:.1f}s "
                        f"(attempt {attempt + 1}/{self.MAX_RETRIES})"
                    )
                    time.sleep(delay)
                    continue

                # Other HTTP errors
                if response.status_code != 200:
                    error_msg = response.text[:500]
                    logger.error(
                        f"NIM API error {response.status_code}: {error_msg}"
                    )
                    raise NIMAPIError(
                        f"HTTP {response.status_code}: {error_msg}"
                    )

                # Parse response
                data = response.json()

                # Extract token usage
                usage = data.get("usage", {})
                self.last_prompt_tokens = usage.get("prompt_tokens", 0)
                self.last_completion_tokens = usage.get(
                    "completion_tokens", 0
                )
                self.last_total_tokens = usage.get("total_tokens", 0)

                # Extract content
                choices = data.get("choices", [])
                if not choices:
                    return ""
                content = choices[0].get("message", {}).get("content", "")
                return content.strip()

            except requests.exceptions.Timeout:
                timeout_count += 1
                last_error = NIMAPIError(
                    f"Timeout after {self.timeout}s"
                )
                # Fail fast on timeout - model is cold/overloaded,
                # retrying wastes minutes before Ollama fallback
                if timeout_count >= self.MAX_TIMEOUT_RETRIES:
                    logger.warning(
                        f"NIM timeout ({self.timeout}s), giving up "
                        f"after {timeout_count} timeout(s)"
                    )
                    raise last_error
                delay = self.RETRY_BASE_DELAY
                logger.warning(
                    f"NIM timeout ({self.timeout}s), retry in {delay:.1f}s "
                    f"(timeout {timeout_count}/{self.MAX_TIMEOUT_RETRIES})"
                )
                time.sleep(delay)
                continue

            except requests.exceptions.ConnectionError as e:
                logger.error(f"NIM connection error: {e}")
                raise NIMAPIError(f"Connection error: {e}")

            except NIMAPIError:
                raise

            except Exception as e:
                logger.error(f"NIM unexpected error: {e}")
                raise NIMAPIError(f"Unexpected error: {e}")

        # All retries exhausted
        raise last_error or NIMAPIError("All retries exhausted")

    # -------------------------------------------------
    # MAIN API (compatible with OllamaBrain)
    # -------------------------------------------------

    def _ask_once(
        self, prompt: str, temperature: float = 0.3, **kwargs
    ) -> str:
        """
        One-shot question (no history).

        Ideal for structured tasks like JSON extraction.

        Args:
            prompt: User prompt
            temperature: Sampling temperature

        Returns:
            Response text
        """
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]
        return self._chat(messages, temperature=temperature)

    def think(
        self, prompt: str, temperature: float = 0.3, **kwargs
    ) -> str:
        """
        Think with conversation history.

        Args:
            prompt: User prompt
            temperature: Sampling temperature

        Returns:
            Response text
        """
        self.call_count += 1
        self.history.append({"role": "user", "content": prompt})

        try:
            content = self._chat(self.history, temperature=temperature)
            self.history.append({"role": "assistant", "content": content})
            return content
        except NIMAPIError as e:
            self.log_fn(f"[NIMClient] [ERROR] API error: {e}")
            return ""

    # -------------------------------------------------
    # JSON EXTRACTION (same as OllamaBrain)
    # -------------------------------------------------

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Extract JSON from potentially messy text.

        Args:
            text: Raw response text

        Returns:
            Parsed dict or None
        """
        if not text:
            return None

        # Strip markdown code fences
        cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
        cleaned = cleaned.replace("```", "").strip()

        # Try clean parse
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Find first JSON object
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            candidate = match.group().strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                return None

        return None

    def analyze_task(self, task: str, retries: int = 2) -> Dict[str, Any]:
        """
        Analyze task and return structured JSON.

        Same schema as OllamaBrain.analyze_task() for compatibility.

        Args:
            task: Text to analyze
            retries: Number of retry attempts for bad JSON

        Returns:
            Structured analysis dict
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
            f"Zwroc TYLKO JSON zgodny z tym schematem: {schema}\n"
            f"Jesli czegos nie wiesz, wpisz pusta liste lub 'low' dla priorytetu."
        )

        prompt = base_prompt
        parsed: Optional[Dict[str, Any]] = None

        for attempt in range(retries + 1):
            try:
                response = self._ask_once(prompt, temperature=0.1)
            except NIMAPIError as e:
                self.log_fn(
                    f"[NIMClient] [ERROR] API error during analyze_task: {e}"
                )
                break

            parsed = self._extract_json(response)
            if parsed is not None:
                break

            self.log_fn(
                f"[NIMClient] [WARN] Attempt {attempt + 1}: "
                f"Bad JSON. Asking model to fix..."
            )
            prompt = (
                "Twoj poprzedni JSON byl niepoprawny skladniowo. "
                "Wyslij teraz sam CZYSTY JSON zgodny ze schematem, "
                "bez zadnych komentarzy ani tekstu."
            )

        # Fallback
        if parsed is None or not isinstance(parsed, dict):
            return {
                "main_task": task[:100],
                "subtasks": ["Analiza nieudana - wymagana interwencja"],
                "memory_facts": [],
                "learning_goals": [],
                "unknown_terms": [],
                "priority": "high",
            }

        # Normalize fields
        parsed.setdefault("main_task", task[:100])
        parsed.setdefault("subtasks", [])
        parsed.setdefault("memory_facts", [])
        parsed.setdefault("learning_goals", [])
        parsed.setdefault("unknown_terms", [])
        parsed.setdefault("priority", "low")

        # Type safety
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

    # -------------------------------------------------
    # HEALTH & AVAILABILITY
    # -------------------------------------------------

    def health_check(self) -> Dict[str, Any]:
        """
        Check NIM API health and connectivity.

        Returns:
            Health status dict
        """
        if not self.api_key:
            return {
                "healthy": False,
                "error": "No API key configured",
                "latency_ms": 0,
            }

        start = time.time()
        try:
            # Simple test call
            response = self._ask_once("Respond with: OK", temperature=0.0)
            latency_ms = (time.time() - start) * 1000

            return {
                "healthy": bool(response),
                "latency_ms": round(latency_ms, 1),
                "model": self.model,
                "last_prompt_tokens": self.last_prompt_tokens,
                "last_completion_tokens": self.last_completion_tokens,
            }
        except NIMAPIError as e:
            latency_ms = (time.time() - start) * 1000
            return {
                "healthy": False,
                "error": str(e),
                "latency_ms": round(latency_ms, 1),
                "model": self.model,
            }

    def is_available(self) -> bool:
        """
        Quick check if NIM API is reachable.

        Returns:
            True if API key is set and we can connect
        """
        if not self.api_key:
            return False
        try:
            url = f"{self.base_url}/models"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            response = requests.get(url, headers=headers, timeout=10)
            return response.status_code == 200
        except Exception:
            return False

    # -------------------------------------------------
    # TOKEN USAGE (for integration with TokenBudget)
    # -------------------------------------------------

    def get_last_usage(self) -> Dict[str, int]:
        """
        Get token usage from the last API call.

        Returns:
            Dict with prompt_tokens, completion_tokens, total_tokens
        """
        return {
            "prompt_tokens": self.last_prompt_tokens,
            "completion_tokens": self.last_completion_tokens,
            "total_tokens": self.last_total_tokens,
        }


class NIMAPIError(Exception):
    """Exception raised for NIM API errors."""
    pass
