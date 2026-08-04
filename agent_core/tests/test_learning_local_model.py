"""Local learning fallback: model choice and thinking must actually reach Ollama.

Guards the path that takes over when the NIM key expires (18.08.2026). Two
things here are silent when they break, which is why they are pinned:

1. `think` and `model` are TOP-LEVEL chat arguments. OllamaBrain._chat funnels
   everything left in **kwargs into `options`, so passing them that way looks
   correct at the call site and is dropped by the server -- thinking would stay
   ON and the model would silently be the instance default.

2. Thinking is the whole point. Measured 2026-07-26 on 30 real fragments with
   the production learning prompt: qwen3:8b thinking ON had a 285s median and
   returned nothing usable inside any budget in the chain (0/30); with thinking
   OFF, median 143s and 27/30 against what learn_chunk actually validates,
   versus 18/30 for llama3.1:8b (paired McNemar p=0.035).
"""

import os
import re
from unittest.mock import MagicMock, patch

import pytest

from agent_core.llm.router import _learning_local_model, _learning_system_prompt
from models.ollama_brain import OllamaBrain


class TestLearningModelSelection:
    def test_defaults_to_qwen3(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LEARNING_LOCAL_MODEL", None)
            assert _learning_local_model() == "qwen3:8b"

    def test_env_override_allows_rollback(self):
        with patch.dict(os.environ, {"LEARNING_LOCAL_MODEL": "llama3.1:8b"}):
            assert _learning_local_model() == "llama3.1:8b"

    def test_blank_env_falls_back_to_default(self):
        with patch.dict(os.environ, {"LEARNING_LOCAL_MODEL": "   "}):
            assert _learning_local_model() == "qwen3:8b"


class TestLearningSystemPrefix:
    """The prefix must be short AND constant -- both, for different reasons."""

    def test_defaults_to_a_short_constant(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LEARNING_SYSTEM_PROMPT", None)
            p = _learning_system_prompt()
        assert p and len(p) < 200, "the point is to stop sending ~1000 persona tokens"

    def test_is_byte_stable_across_calls(self):
        """A prefix that changes busts Ollama's KV cache on every call.

        The persona carries a live clock refreshed on each chat turn, so the
        learning path re-prefilled ~2000 tokens every time: measured 117.3s on
        a cache miss vs 0.2s on a hit.
        """
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LEARNING_SYSTEM_PROMPT", None)
            first = _learning_system_prompt()
            second = _learning_system_prompt()
        assert first == second

    def test_carries_no_clock_or_date(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LEARNING_SYSTEM_PROMPT", None)
            p = _learning_system_prompt() or ""
        assert not re.search(r"\d{1,2}:\d{2}", p), "a clock in the prefix kills the cache"
        assert not re.search(r"\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}", p)

    def test_dash_restores_the_persona(self):
        with patch.dict(os.environ, {"LEARNING_SYSTEM_PROMPT": "-"}):
            assert _learning_system_prompt() is None


class TestThinkAndModelReachTheClient:
    """They must arrive as top-level chat args, never buried in `options`."""

    def _brain_with_fake_client(self):
        brain = OllamaBrain.__new__(OllamaBrain)
        brain.model = "llama3.1:8b"
        brain.system_prompt = "sys"
        brain._llm_tape = None
        brain._client = MagicMock()
        brain._client.chat.return_value = {"message": {"content": "{}"}}
        return brain

    def test_think_is_top_level_not_an_option(self):
        brain = self._brain_with_fake_client()
        brain._ask_once("p", think=False)
        kwargs = brain._client.chat.call_args.kwargs
        assert kwargs["think"] is False
        assert "think" not in kwargs["options"], (
            "think landed in options -- the server ignores it there and the "
            "model keeps thinking, at ~2x the latency"
        )

    def test_model_override_is_top_level_and_wins(self):
        brain = self._brain_with_fake_client()
        brain._ask_once("p", model="qwen3:8b")
        kwargs = brain._client.chat.call_args.kwargs
        assert kwargs["model"] == "qwen3:8b"
        assert "model" not in kwargs["options"]

    def test_instance_model_used_when_not_overridden(self):
        brain = self._brain_with_fake_client()
        brain._ask_once("p")
        assert brain._client.chat.call_args.kwargs["model"] == "llama3.1:8b"

    def test_system_override_replaces_the_persona(self):
        brain = self._brain_with_fake_client()
        brain._ask_once("p", system="ZWIEZLE")
        msgs = brain._client.chat.call_args.kwargs["messages"]
        assert msgs[0]["role"] == "system" and msgs[0]["content"] == "ZWIEZLE"

    def test_persona_used_when_system_not_given(self):
        """Default must not change for every other caller."""
        brain = self._brain_with_fake_client()
        brain._ask_once("p")
        msgs = brain._client.chat.call_args.kwargs["messages"]
        assert msgs[0]["content"] == "sys"

    def test_think_absent_when_not_requested(self):
        """Never send `think` unasked -- leave non-reasoning models untouched."""
        brain = self._brain_with_fake_client()
        brain._ask_once("p")
        assert "think" not in brain._client.chat.call_args.kwargs

    def test_tape_records_the_model_that_actually_ran(self):
        """A tape naming the wrong model poisons every later measurement."""
        brain = self._brain_with_fake_client()
        brain._llm_tape = MagicMock()
        brain._ask_once("p", model="qwen3:8b")
        entry = brain._llm_tape.record.call_args.args[0]
        assert getattr(entry, "model", None) == "qwen3:8b"
