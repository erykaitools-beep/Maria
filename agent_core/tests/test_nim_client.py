"""
Tests for NVIDIA NIM API client, Token Budget, and LLM Router.

All tests use mocks - no real API calls needed.
"""

import json
import os
import tempfile
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import date

from agent_core.llm.token_budget import TokenBudget
from agent_core.llm.nim_client import NIMClient, NIMAPIError
from agent_core.llm.router import LLMRouter


# =============================================================
# TOKEN BUDGET TESTS
# =============================================================

class TestTokenBudget:
    """Tests for TokenBudget manager."""

    @pytest.fixture
    def budget_file(self, tmp_path):
        """Create a temporary budget file path."""
        return str(tmp_path / "test_budget.json")

    @pytest.fixture
    def budget(self, budget_file):
        """Create a TokenBudget instance with temp file."""
        return TokenBudget(
            daily_limit=10_000,
            monthly_limit=100_000,
            budget_file=budget_file,
        )

    def test_init_defaults(self, budget):
        """Budget starts with zero usage."""
        assert budget.daily_limit == 10_000
        assert budget.monthly_limit == 100_000
        assert budget.get_today_usage()["total_tokens"] == 0
        assert budget.can_use_nim() is True

    def test_record_usage(self, budget):
        """Recording usage updates counters."""
        budget.record_usage(prompt_tokens=100, completion_tokens=50)
        today = budget.get_today_usage()
        assert today["prompt_tokens"] == 100
        assert today["completion_tokens"] == 50
        assert today["total_tokens"] == 150
        assert today["calls"] == 1

    def test_record_multiple_usage(self, budget):
        """Multiple recordings accumulate."""
        budget.record_usage(prompt_tokens=100, completion_tokens=50)
        budget.record_usage(prompt_tokens=200, completion_tokens=100)
        today = budget.get_today_usage()
        assert today["prompt_tokens"] == 300
        assert today["completion_tokens"] == 150
        assert today["total_tokens"] == 450
        assert today["calls"] == 2

    def test_remaining_today(self, budget):
        """Remaining tokens decrease after usage."""
        assert budget.get_remaining_today() == 10_000
        budget.record_usage(prompt_tokens=3000, completion_tokens=2000)
        assert budget.get_remaining_today() == 5_000

    def test_remaining_month(self, budget):
        """Monthly remaining decreases after usage."""
        assert budget.get_remaining_month() == 100_000
        budget.record_usage(prompt_tokens=5000, completion_tokens=5000)
        assert budget.get_remaining_month() == 90_000

    def test_can_use_nim_true(self, budget):
        """can_use_nim returns True when budget available."""
        budget.record_usage(prompt_tokens=1000, completion_tokens=500)
        assert budget.can_use_nim() is True

    def test_can_use_nim_rpm_depleted(self, budget):
        """can_use_nim returns False when RPM limit reached."""
        import time as _time
        now = _time.time()
        # Fill up RPM window with 40 timestamps
        budget._request_timestamps = [now - i * 0.5 for i in range(40)]
        assert budget.can_use_nim() is False

    def test_can_use_nim_rpm_window_expires(self, budget):
        """can_use_nim returns True when old requests fall outside window."""
        import time as _time
        # All timestamps are 61 seconds ago -> outside RPM window
        old = _time.time() - 61.0
        budget._request_timestamps = [old - i for i in range(40)]
        assert budget.can_use_nim() is True

    def test_budget_status_ok(self, budget):
        """Status is OK when plenty of budget."""
        assert budget.get_budget_status() == "OK"

    def test_budget_status_low(self, budget):
        """Status is LOW when RPM >= 80% of limit."""
        import time as _time
        now = _time.time()
        # 33 requests in last minute = 82.5% of 40 limit
        budget._request_timestamps = [now - i * 0.5 for i in range(33)]
        assert budget.get_budget_status() == "LOW"

    def test_budget_status_depleted(self, budget):
        """Status is DEPLETED when RPM limit reached."""
        import time as _time
        now = _time.time()
        budget._request_timestamps = [now - i * 0.5 for i in range(40)]
        assert budget.get_budget_status() == "DEPLETED"

    def test_persistence_save_load(self, budget_file):
        """Usage persists across instances."""
        budget1 = TokenBudget(
            daily_limit=10_000,
            monthly_limit=100_000,
            budget_file=budget_file,
        )
        budget1.record_usage(prompt_tokens=500, completion_tokens=300)

        # Create new instance - should load saved data
        budget2 = TokenBudget(
            daily_limit=10_000,
            monthly_limit=100_000,
            budget_file=budget_file,
        )
        today = budget2.get_today_usage()
        assert today["total_tokens"] == 800

    def test_persistence_file_created(self, budget_file, budget):
        """Budget file is created on first save."""
        budget.record_usage(prompt_tokens=100, completion_tokens=50)
        assert os.path.exists(budget_file)

        with open(budget_file, "r") as f:
            data = json.load(f)
        assert "usage" in data
        assert "daily_limit" in data

    def test_load_missing_file(self, tmp_path):
        """Handles missing budget file gracefully."""
        budget = TokenBudget(
            budget_file=str(tmp_path / "nonexistent.json")
        )
        assert budget.get_today_usage()["total_tokens"] == 0
        assert budget.can_use_nim() is True

    def test_status_text(self, budget):
        """Status text is readable Polish."""
        budget.record_usage(prompt_tokens=500, completion_tokens=300)
        text = budget.get_status_text()
        assert "800" in text  # total tokens
        assert "tokenow" in text.lower()
        assert "RPM" in text

    def test_status_text_depleted(self, budget):
        """Status text shows RPM depletion message."""
        import time as _time
        now = _time.time()
        budget._request_timestamps = [now - i * 0.5 for i in range(40)]
        text = budget.get_status_text()
        assert "Ollama" in text

    def test_status_dict(self, budget):
        """Status dict has correct structure."""
        budget.record_usage(prompt_tokens=100, completion_tokens=50)
        d = budget.get_status_dict()
        assert "status" in d
        assert "can_use_nim" in d
        assert "rpm" in d
        assert d["rpm"]["limit"] == 40
        assert "daily" in d
        assert "monthly" in d
        assert d["daily"]["used"] == 150
        assert d["daily"]["limit"] == 10_000

    def test_month_usage_accumulates_days(self, budget_file):
        """Monthly usage sums across multiple days."""
        budget = TokenBudget(
            daily_limit=10_000,
            monthly_limit=100_000,
            budget_file=budget_file,
        )
        # Simulate previous day
        today = date.today().isoformat()
        month = date.today().strftime("%Y-%m")
        prev_day = f"{month}-01" if today[-2:] != "01" else f"{month}-02"

        budget._usage[prev_day] = {
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "total_tokens": 1500,
            "calls": 5,
        }
        budget.record_usage(prompt_tokens=200, completion_tokens=100)

        month_usage = budget.get_month_usage()
        assert month_usage["total_tokens"] == 1800  # 1500 + 300

    def test_today_key_format(self):
        """Today key is ISO format date."""
        key = TokenBudget._today_key()
        # Should be YYYY-MM-DD
        assert len(key) == 10
        assert key[4] == "-"
        assert key[7] == "-"


# =============================================================
# NIM CLIENT TESTS
# =============================================================

class TestNIMClient:
    """Tests for NIMClient API wrapper."""

    @pytest.fixture
    def client(self):
        """Create a NIMClient with test config."""
        return NIMClient(
            api_key="test-key-123",
            model="test-model",
            base_url="https://test.api.nvidia.com/v1",
            timeout=30,
        )

    def test_init(self, client):
        """Client initializes with correct config."""
        assert client.api_key == "test-key-123"
        assert client.model == "test-model"
        assert client.base_url == "https://test.api.nvidia.com/v1"
        assert client.timeout == 30
        assert client.call_count == 0

    def test_init_default_url(self):
        """Default URL points to NIM cloud."""
        client = NIMClient(api_key="key", model="model")
        assert "integrate.api.nvidia.com" in client.base_url

    @patch("agent_core.llm.nim_client.requests.post")
    def test_chat_success(self, mock_post, client):
        """Successful API call returns content."""
        mock_post.return_value = Mock(
            status_code=200,
            json=lambda: {
                "choices": [{"message": {"content": "Hello!"}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )
        result = client._chat([{"role": "user", "content": "Hi"}])
        assert result == "Hello!"
        assert client.last_total_tokens == 15

    @patch("agent_core.llm.nim_client.requests.post")
    def test_chat_tracks_tokens(self, mock_post, client):
        """Token usage is tracked after each call."""
        mock_post.return_value = Mock(
            status_code=200,
            json=lambda: {
                "choices": [{"message": {"content": "OK"}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
            },
        )
        client._chat([{"role": "user", "content": "test"}])
        assert client.last_prompt_tokens == 100
        assert client.last_completion_tokens == 50
        assert client.last_total_tokens == 150

    @patch("agent_core.llm.nim_client.requests.post")
    def test_think_with_history(self, mock_post, client):
        """think() maintains conversation history."""
        mock_post.return_value = Mock(
            status_code=200,
            json=lambda: {
                "choices": [{"message": {"content": "Czesc!"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )
        result = client.think("Hej")
        assert result == "Czesc!"
        assert client.call_count == 1
        assert len(client.history) == 3  # system + user + assistant

    @patch("agent_core.llm.nim_client.requests.post")
    def test_ask_once_no_history(self, mock_post, client):
        """_ask_once() doesn't modify history."""
        mock_post.return_value = Mock(
            status_code=200,
            json=lambda: {
                "choices": [{"message": {"content": "OK"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            },
        )
        history_before = len(client.history)
        client._ask_once("Quick question")
        assert len(client.history) == history_before

    @patch("agent_core.llm.nim_client.requests.post")
    def test_chat_rate_limit_retry(self, mock_post, client):
        """Retries on 429 rate limit."""
        mock_post.side_effect = [
            Mock(status_code=429, text="Rate limited"),
            Mock(
                status_code=200,
                json=lambda: {
                    "choices": [{"message": {"content": "OK"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
                },
            ),
        ]
        # Override retry delay for fast test
        client.RETRY_BASE_DELAY = 0.01
        result = client._chat([{"role": "user", "content": "test"}])
        assert result == "OK"
        assert mock_post.call_count == 2

    @patch("agent_core.llm.nim_client.requests.post")
    def test_chat_http_error(self, mock_post, client):
        """Raises NIMAPIError on HTTP errors."""
        mock_post.return_value = Mock(
            status_code=500, text="Internal Server Error"
        )
        with pytest.raises(NIMAPIError):
            client._chat([{"role": "user", "content": "test"}])

    @patch("agent_core.llm.nim_client.requests.post")
    def test_chat_timeout(self, mock_post, client):
        """Retries on timeout, then raises NIMAPIError."""
        import requests as req
        mock_post.side_effect = req.exceptions.Timeout("Timeout")
        client.RETRY_BASE_DELAY = 0.01
        with pytest.raises(NIMAPIError):
            client._chat([{"role": "user", "content": "test"}])

    @patch("agent_core.llm.nim_client.requests.post")
    def test_chat_connection_error(self, mock_post, client):
        """Raises NIMAPIError on connection error."""
        import requests as req
        mock_post.side_effect = req.exceptions.ConnectionError("No route")
        with pytest.raises(NIMAPIError):
            client._chat([{"role": "user", "content": "test"}])

    @patch("agent_core.llm.nim_client.requests.post")
    def test_analyze_task_success(self, mock_post, client):
        """analyze_task returns structured dict."""
        mock_post.return_value = Mock(
            status_code=200,
            json=lambda: {
                "choices": [{"message": {"content": json.dumps({
                    "main_task": "Test task",
                    "subtasks": ["step1"],
                    "memory_facts": [],
                    "learning_goals": ["learn X"],
                    "unknown_terms": [],
                    "priority": "medium",
                })}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80},
            },
        )
        result = client.analyze_task("Test task")
        assert result["main_task"] == "Test task"
        assert result["priority"] == "medium"

    @patch("agent_core.llm.nim_client.requests.post")
    def test_analyze_task_bad_json_fallback(self, mock_post, client):
        """analyze_task returns fallback on bad JSON."""
        mock_post.return_value = Mock(
            status_code=200,
            json=lambda: {
                "choices": [{"message": {"content": "Not JSON at all"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )
        result = client.analyze_task("Some task")
        assert result["priority"] == "high"  # fallback priority
        assert "interwencja" in result["subtasks"][0]

    def test_extract_json_clean(self, client):
        """Extracts clean JSON."""
        result = client._extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_extract_json_markdown(self, client):
        """Extracts JSON from markdown code block."""
        text = '```json\n{"key": "value"}\n```'
        result = client._extract_json(text)
        assert result == {"key": "value"}

    def test_extract_json_messy(self, client):
        """Extracts JSON from messy text."""
        text = 'Here is the answer: {"key": "value"} hope it helps'
        result = client._extract_json(text)
        assert result == {"key": "value"}

    def test_extract_json_none(self, client):
        """Returns None for non-JSON text."""
        result = client._extract_json("No JSON here")
        assert result is None

    def test_extract_json_empty(self, client):
        """Returns None for empty text."""
        assert client._extract_json("") is None
        assert client._extract_json(None) is None

    def test_get_last_usage(self, client):
        """get_last_usage returns token counts."""
        client.last_prompt_tokens = 100
        client.last_completion_tokens = 50
        client.last_total_tokens = 150
        usage = client.get_last_usage()
        assert usage["prompt_tokens"] == 100
        assert usage["total_tokens"] == 150

    def test_health_check_no_key(self):
        """Health check fails without API key."""
        client = NIMClient(api_key="", model="test")
        result = client.health_check()
        assert result["healthy"] is False
        assert "No API key" in result["error"]

    @patch("agent_core.llm.nim_client.requests.get")
    def test_is_available_true(self, mock_get, client):
        """is_available returns True when API responds."""
        mock_get.return_value = Mock(status_code=200)
        assert client.is_available() is True

    @patch("agent_core.llm.nim_client.requests.get")
    def test_is_available_false(self, mock_get, client):
        """is_available returns False on error."""
        mock_get.side_effect = Exception("Connection refused")
        assert client.is_available() is False

    def test_is_available_no_key(self):
        """is_available returns False without key."""
        client = NIMClient(api_key="", model="test")
        assert client.is_available() is False


# =============================================================
# LLM ROUTER TESTS
# =============================================================

class TestLLMRouter:
    """Tests for LLMRouter routing logic."""

    @pytest.fixture
    def ollama(self):
        """Create mock OllamaBrain."""
        mock = Mock()
        mock.think.return_value = "Ollama response"
        mock._ask_once.return_value = "Ollama ask_once"
        mock.analyze_task.return_value = {
            "main_task": "test",
            "subtasks": [],
            "memory_facts": [],
            "learning_goals": [],
            "unknown_terms": [],
            "priority": "low",
        }
        mock.model = "llama3.1:8b"
        mock.history = []
        mock._query_router = None  # No grounding pipeline in tests
        return mock

    @pytest.fixture
    def nim(self):
        """Create mock NIMClient."""
        mock = Mock()
        mock.api_key = "test-key"
        mock.model = "nvidia/glm"
        mock._ask_once.return_value = "NIM ask_once"
        mock.analyze_task.return_value = {
            "main_task": "test",
            "subtasks": [],
            "memory_facts": [],
            "learning_goals": [],
            "unknown_terms": [],
            "priority": "medium",
        }
        mock.get_last_usage.return_value = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
        return mock

    @pytest.fixture
    def budget(self, tmp_path):
        """Create TokenBudget with temp file."""
        return TokenBudget(
            daily_limit=10_000,
            monthly_limit=100_000,
            budget_file=str(tmp_path / "test_budget.json"),
        )

    @pytest.fixture
    def router(self, ollama, nim, budget):
        """Create LLMRouter with all components."""
        return LLMRouter(
            ollama_brain=ollama,
            nim_client=nim,
            token_budget=budget,
        )

    # --- think() always Ollama ---

    def test_think_uses_ollama(self, router, ollama):
        """think() always routes to Ollama."""
        result = router.think("Hello")
        assert result == "Ollama response"
        ollama.think.assert_called_once_with("Hello", temperature=0.3)

    def test_think_ignores_nim(self, router, nim):
        """think() never calls NIM."""
        router.think("Hello")
        nim.think.assert_not_called()

    # --- analyze_task() routes to NIM ---

    def test_analyze_task_uses_nim(self, router, nim, ollama):
        """analyze_task() uses NIM when available and budget OK."""
        result = router.analyze_task("Test task")
        nim.analyze_task.assert_called_once()
        ollama.analyze_task.assert_not_called()

    def test_analyze_task_records_budget(self, router, budget):
        """analyze_task() records token usage in budget."""
        router.analyze_task("Test task")
        today = budget.get_today_usage()
        assert today["total_tokens"] == 150

    # --- _ask_once() routes to NIM ---

    def test_ask_once_uses_nim(self, router, nim, ollama):
        """_ask_once() uses NIM when available."""
        result = router._ask_once("Quick question")
        assert result == "NIM ask_once"
        nim._ask_once.assert_called_once()
        ollama._ask_once.assert_not_called()

    # --- Fallback to Ollama ---

    def test_analyze_task_fallback_on_nim_error(self, router, nim, ollama):
        """Falls back to Ollama when NIM raises error."""
        nim.analyze_task.side_effect = Exception("NIM down")
        result = router.analyze_task("Test task")
        ollama.analyze_task.assert_called_once()
        assert router._nim_fallbacks == 1

    def test_ask_once_fallback_on_nim_error(self, router, nim, ollama):
        """_ask_once falls back to Ollama on NIM error."""
        nim._ask_once.side_effect = Exception("NIM down")
        result = router._ask_once("Question")
        assert result == "Ollama ask_once"
        ollama._ask_once.assert_called_once()

    # --- Budget depleted -> Ollama ---

    def test_analyze_task_ollama_when_rpm_depleted(
        self, ollama, nim, tmp_path
    ):
        """Uses Ollama when RPM limit is reached."""
        import time as _time
        budget = TokenBudget(
            daily_limit=100_000,
            monthly_limit=100_000,
            budget_file=str(tmp_path / "b.json"),
        )
        now = _time.time()
        budget._request_timestamps = [now - i * 0.5 for i in range(40)]

        router = LLMRouter(ollama, nim, budget)
        router.analyze_task("Test")
        ollama.analyze_task.assert_called_once()
        nim.analyze_task.assert_not_called()

    # --- No NIM configured ---

    def test_ollama_only_mode(self, ollama):
        """Works with Ollama only (no NIM)."""
        router = LLMRouter(ollama_brain=ollama)
        result = router.think("Hello")
        assert result == "Ollama response"
        result = router.analyze_task("Task")
        ollama.analyze_task.assert_called_once()

    def test_no_nim_backend_status(self, ollama):
        """Backend is 'ollama' when no NIM configured."""
        router = LLMRouter(ollama_brain=ollama)
        assert router.get_active_backend() == "ollama"

    # --- Status and stats ---

    def test_active_backend_hybrid(self, router):
        """Backend is 'hybrid' when NIM available."""
        assert router.get_active_backend() == "hybrid"

    def test_get_stats(self, router):
        """Stats include all counters."""
        router.think("chat")
        router.analyze_task("learn")
        stats = router.get_stats()
        assert stats["ollama_calls"] == 1
        assert stats["nim_calls"] == 1
        assert stats["total_calls"] == 2
        assert stats["active_backend"] == "hybrid"
        assert stats["nim_model"] == "nvidia/glm"

    def test_get_budget_status(self, router):
        """Budget status delegates to TokenBudget."""
        text = router.get_budget_status()
        assert "tokenow" in text.lower()

    def test_get_budget_status_no_budget(self, ollama):
        """Budget status message when no budget configured."""
        router = LLMRouter(ollama_brain=ollama)
        assert "budzetu" in router.get_budget_status().lower()

    # --- Passthrough ---

    def test_model_property(self, router):
        """model property returns Ollama model."""
        assert router.model == "llama3.1:8b"

    def test_call_count(self, router):
        """call_count sums NIM and Ollama calls."""
        router.think("a")
        router.analyze_task("b")
        assert router.call_count == 2

    def test_refresh_time_context(self, router, ollama):
        """Delegates refresh_time_context to Ollama."""
        router.refresh_time_context()
        ollama.refresh_time_context.assert_called_once()

    # --- NIM Chat mode ---

    def test_think_nim_chat_enabled(self, ollama, nim, budget):
        """think() routes through NIM when use_nim_for_chat=True."""
        nim.think.return_value = "NIM chat response"
        router = LLMRouter(ollama, nim, budget, use_nim_for_chat=True)
        result = router.think("Czesc")
        assert result == "NIM chat response"
        nim.think.assert_called_once()
        ollama.think.assert_not_called()

    def test_think_nim_chat_fallback_on_error(self, ollama, nim, budget):
        """think() falls back to Ollama when NIM chat fails."""
        nim.think.side_effect = Exception("NIM timeout")
        router = LLMRouter(ollama, nim, budget, use_nim_for_chat=True)
        result = router.think("Czesc")
        assert result == "Ollama response"
        ollama.think.assert_called_once()

    def test_think_nim_chat_respects_budget(self, ollama, nim, budget):
        """think() uses Ollama when NIM budget depleted even with chat enabled."""
        # Exhaust RPM budget (40 requests in default window)
        for _ in range(50):
            budget.record_request()
        router = LLMRouter(ollama, nim, budget, use_nim_for_chat=True)
        result = router.think("Czesc")
        assert result == "Ollama response"
        nim.think.assert_not_called()

    def test_think_nim_chat_disabled_default(self, ollama, nim, budget):
        """use_nim_for_chat defaults to False."""
        router = LLMRouter(ollama, nim, budget)
        assert router.use_nim_for_chat is False
        router.think("Czesc")
        ollama.think.assert_called_once()
        nim.think.assert_not_called()

    def test_history_returns_nim_when_chat_enabled(self, ollama, nim, budget):
        """history property returns NIM history when NIM chat enabled."""
        nim.history = [{"role": "user", "content": "test"}]
        router = LLMRouter(ollama, nim, budget, use_nim_for_chat=True)
        assert router.history == nim.history

    def test_history_returns_ollama_when_chat_disabled(self, router):
        """history property returns Ollama history when NIM chat disabled."""
        assert router.history == router.ollama.history

    def test_stats_include_nim_chat_flag(self, ollama, nim, budget):
        """get_stats() includes nim_chat_enabled flag."""
        router = LLMRouter(ollama, nim, budget, use_nim_for_chat=True)
        stats = router.get_stats()
        assert stats["nim_chat_enabled"] is True

    def test_think_nim_chat_records_usage(self, ollama, nim, budget):
        """think() with NIM chat records token usage to budget."""
        nim.think.return_value = "NIM response"
        router = LLMRouter(ollama, nim, budget, use_nim_for_chat=True)
        requests_before = len(budget._request_timestamps)
        router.think("Test")
        assert len(budget._request_timestamps) == requests_before + 1

    def test_think_nim_chat_grounded_uses_ollama(self, ollama, nim, budget):
        """Grounded queries (vision, status) bypass NIM and use Ollama."""
        from unittest.mock import Mock as _Mock
        nim.think.return_value = "NIM response"
        # Wire a query router that detects grounded queries
        qr = _Mock()
        qr.classify.return_value = "grounded_vision"
        qr.is_grounded.return_value = True
        ollama._query_router = qr
        router = LLMRouter(ollama, nim, budget, use_nim_for_chat=True)
        result = router.think("co widzisz?")
        assert result == "Ollama response"
        nim.think.assert_not_called()
        ollama.think.assert_called_once()

    def test_think_nim_chat_normal_skips_grounding(self, ollama, nim, budget):
        """Normal chat goes through NIM even with query router wired."""
        from unittest.mock import Mock as _Mock
        nim.think.return_value = "NIM response"
        qr = _Mock()
        qr.classify.return_value = "normal"
        qr.is_grounded.return_value = False
        ollama._query_router = qr
        router = LLMRouter(ollama, nim, budget, use_nim_for_chat=True)
        result = router.think("Czesc, jak sie masz?")
        assert result == "NIM response"
        nim.think.assert_called_once()
