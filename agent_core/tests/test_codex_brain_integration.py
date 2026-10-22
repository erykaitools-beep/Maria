"""The remote transport must retain Maria context and never fall back locally."""
from agent_core.tests.spec_helpers import specced
from agent_core.llm.codex_chat import CodexChatBackend
from agent_core.consciousness.identity_store import IdentityStore
from agent_core.consciousness.conversation_memory import ConversationMemory
from unittest.mock import Mock

import pytest

from models.ollama_brain import OllamaBrain, BrainBackendError, BrainTimeout
from agent_core.llm.chat_backend import chat_backend_config, create_chat_backend
from agent_core.llm.local_compute import LocalComputeCoordinator, LocalComputeBlocked
from agent_core.llm.work_priority import WorkPurpose, work_purpose


def make_brain(backend):
    brain = OllamaBrain(model="gpt-6.1-sol", system_prompt="Jestes Maria, rozmawiasz z operatorem.",
                        chat_backend=backend, log_fn=lambda *_: None)
    brain._client = Mock(spec=["chat", "generate", "embed", "embeddings", "list", "show"])
    return brain


def test_two_turns_keep_identity_and_history(monkeypatch):
    monkeypatch.delenv("CHAT_FAST_CONTEXT", raising=False)
    backend = specced(CodexChatBackend, provider="codex", model="fixture-model", tool_provider=None)
    backend.chat.side_effect = ["Zapamietalam: projekt Jantar.", "Jantar."]
    brain = make_brain(backend)
    identity = specced(IdentityStore)
    identity.get_identity_context.return_value = "Wspolny projekt z operatorem od wiosny."
    brain._identity_store = identity
    memory = specced(ConversationMemory)
    brain._conversation_memory = memory
    memory.get_conversation_context.return_value = ""
    assert brain.think("Nasz projekt nazywa sie Jantar.") == "Zapamietalam: projekt Jantar."
    assert brain.think("Jak nazywa sie projekt?") == "Jantar."
    messages = backend.chat.call_args.args[0]
    assert "M.A.R.I.A." in messages[0]["content"]
    assert "Wspolny projekt z operatorem od wiosny." in messages[0]["content"]
    assert any(m["content"] == "Nasz projekt nazywa sie Jantar." for m in messages)
    assert any(m["content"] == "Zapamietalam: projekt Jantar." for m in messages)
    assert messages[-1]["content"] == "Jak nazywa sie projekt?"
    assert memory.save_turn.call_count == 4
    brain._client.chat.assert_not_called()


@pytest.mark.parametrize("failure,expected", [(RuntimeError("login unavailable"), BrainBackendError),
                                             (TimeoutError("deadline"), BrainTimeout)])
def test_remote_errors_are_visible_without_local_fallback(failure, expected):
    backend = specced(CodexChatBackend, provider="codex", model="fixture-model", tool_provider=None)
    backend.chat.side_effect = failure
    brain = make_brain(backend)
    with pytest.raises(expected):
        brain.think("Czesc", raise_on_timeout=True)
    backend.chat.assert_called_once()
    brain._client.chat.assert_not_called()
    assert not any(m["role"] == "assistant" for m in brain.history)


def test_json_request_uses_same_remote_backend():
    backend = specced(CodexChatBackend, provider="codex", model="fixture-model", tool_provider=None)
    backend.chat.return_value = '{"ok":true}'
    brain = make_brain(backend)
    assert brain._ask_once("Zwroc JSON", force_json=True) == '{"ok":true}'
    assert backend.chat.call_args.kwargs["force_json"] is True
    brain._client.chat.assert_not_called()


def test_default_and_invalid_provider(monkeypatch):
    monkeypatch.delenv("MARIA_CHAT_BACKEND", raising=False)
    assert create_chat_backend() is None
    monkeypatch.setenv("MARIA_CHAT_BACKEND", "typo")
    with pytest.raises(ValueError):
        chat_backend_config()


@pytest.mark.parametrize("kind", ["text", "vision", "embedding"])
def test_paused_runtime_cannot_start_unscoped_local_models(monkeypatch, kind):
    monkeypatch.setenv("MARIA_BACKGROUND_REASONING", "0")
    coordinator = LocalComputeCoordinator()
    with pytest.raises(LocalComputeBlocked, match="paused"):
        with coordinator.lease(kind, timeout_s=1):
            pytest.fail("local model admitted")


def test_interactive_embedding_still_respects_thermal_gate(monkeypatch):
    monkeypatch.setenv("MARIA_BACKGROUND_REASONING", "0")
    coordinator = LocalComputeCoordinator()
    with work_purpose(WorkPurpose.INTERACTION):
        with coordinator.lease("embedding", timeout_s=1):
            pass
        with pytest.raises(LocalComputeBlocked):
            with coordinator.lease("text", timeout_s=1):
                pytest.fail("local generative fallback admitted")
        coordinator.enter_cooling(85)
        with pytest.raises(LocalComputeBlocked, match="cooling"):
            with coordinator.lease("embedding", timeout_s=1):
                pytest.fail("hot model admitted")
