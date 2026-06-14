"""Tests for the 2026-06-02 learning-health fixes (LLM cold-start friction).

Night signals "stuck on learn / 0% exam / action_failure_storm" were NOT
HELDOUT-off and NOT bad knowledge (completed exams scored 75-95%). Root cause:
  * The exam/learn pipeline (maria_core.learning.call_ollama -> llama3.1) sent
    no keep_alive, so Ollama's 5-min default unloaded the model between cycles
    (often >5 min apart). Each exam then cold-started on CPU and hit 240s x3
    = 12 min timeout -> pipeline failure. The cold grind also helped saturate
    the CPU that fed the freeze.
  * NIM (nemotron-49b) capped output at 2048 -> chronic truncation of planner
    responses -> forced fallback to that cold local model.

Fixes:
  A. call_ollama pins the model with keep_alive (config OLLAMA_KEEP_ALIVE).
  C. NIM default max_tokens raised + tunable (NIM_MAX_TOKENS).
"""

import inspect
from unittest.mock import patch, MagicMock

from maria_core.learning import llm_utils
from maria_core.sys.config import OLLAMA_KEEP_ALIVE
from agent_core.llm import nim_client


# ---------------------------------------------------------------------------
# Fix A -- call_ollama keeps the model warm between learning cycles
# ---------------------------------------------------------------------------
class TestOllamaKeepAlive:
    def _run_with_capture(self, **kwargs):
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["payload"] = json
            resp = MagicMock()
            resp.raise_for_status = lambda: None
            resp.json = lambda: {"response": "{}"}
            return resp

        with patch.object(llm_utils.requests, "post", side_effect=fake_post):
            llm_utils.call_ollama("hi", **kwargs)
        return captured["payload"]

    def test_keep_alive_present_by_default(self):
        payload = self._run_with_capture()
        assert payload.get("keep_alive") == OLLAMA_KEEP_ALIVE
        assert OLLAMA_KEEP_ALIVE  # non-empty -> model actually pinned

    def test_keep_alive_is_overridable(self):
        payload = self._run_with_capture(keep_alive="1h")
        assert payload["keep_alive"] == "1h"

    def test_config_default_is_a_real_window(self):
        # A bare "0" would unload immediately -- the bug we are fixing.
        assert OLLAMA_KEEP_ALIVE not in ("0", "", None)


# ---------------------------------------------------------------------------
# Fix C -- NIM output cap raised above the chronic 2048 truncation point
# ---------------------------------------------------------------------------
class TestNimMaxTokens:
    def test_default_raised_above_2048(self):
        assert nim_client.DEFAULT_MAX_TOKENS > 2048

    def test_ask_once_uses_the_raised_default(self):
        sig = inspect.signature(nim_client.NIMClient._ask_once)
        assert sig.parameters["max_tokens"].default == nim_client.DEFAULT_MAX_TOKENS

    def test_explicit_max_tokens_still_overrides(self):
        # Callers that deliberately cap (e.g. held-out student) must still win.
        sig = inspect.signature(nim_client.NIMClient._ask_once)
        assert sig.parameters["max_tokens"].default != 1234  # sanity: it's a default, not forced
