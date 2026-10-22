"""Request evidence must reach chat without becoming conversation history."""
from agent_core.tests.spec_helpers import specced
from agent_core.llm.codex_chat import CodexChatBackend
from agent_core.introspection.evidence_collector import EvidenceCollector
from agent_core.introspection.response_builder import ResponseBuilder
from agent_core.consciousness.identity_store import IdentityStore
from agent_core.consciousness.conversation_memory import ConversationMemory
from copy import deepcopy
from unittest.mock import Mock, create_autospec

import pytest

from models.ollama_brain import OllamaBrain
from agent_core.introspection.query_router import OperationalQueryRouter


def make_brain(provider):
    backend = specced(CodexChatBackend, provider="codex", model="fixture-model", tool_provider=None)
    sent = []
    def chat(messages, **kwargs):
        sent.append(deepcopy(list(messages)))
        return "Odpowiedz."
    backend.chat.side_effect = chat
    brain = OllamaBrain(chat_backend=backend, request_context_provider=provider,
                        log_fn=lambda *_: None)
    brain._client = Mock(spec=["chat", "generate", "embed", "embeddings", "list", "show"])
    brain._identity_store = specced(IdentityStore)
    brain._identity_store.get_identity_context.return_value = "TOZSAMOSC_MARII"
    memory = specced(ConversationMemory)
    memory.get_conversation_context.return_value = "PAMIEC_ROZMOWY"
    brain._conversation_memory = memory
    collector = specced(EvidenceCollector)
    collector.build_compact_summary.return_value = ""
    brain.set_grounding_pipeline(OperationalQueryRouter(), collector, specced(ResponseBuilder))
    brain._grounded_think = Mock(return_value="STAN_MARII")
    return brain, sent, memory


@pytest.mark.parametrize("fast", ["0", "1"])
def test_named_status_uses_fresh_context_once_without_storing_it(monkeypatch, fast):
    monkeypatch.setenv("CHAT_FAST_CONTEXT", fast)
    provider = create_autospec(lambda prompt: None, side_effect=['{"snapshot":"FIRST"}', '{"snapshot":"SECOND"}', None])
    brain, sent, memory = make_brain(provider)
    first = "Maria, jaki status projektow w Kritaqo?"
    second = "Jakie projekty mamy w Kritaqo?"
    brain.think(first)
    brain.think(second)
    brain.think("Dziekuje.")
    assert provider.call_count == 3
    brain._grounded_think.assert_not_called()
    brain._client.chat.assert_not_called()
    assert sent[0][-2] == {"role": "system", "content": '{"snapshot":"FIRST"}'}
    assert sent[0][-1] == {"role": "user", "content": first}
    assert "TOZSAMOSC_MARII" in sent[0][0]["content"]
    assert "PAMIEC_ROZMOWY" in str(sent[0])
    assert any(m["content"] == first for m in sent[1])
    assert '"snapshot":"SECOND"' in str(sent[1])
    assert '"snapshot":"FIRST"' not in str(sent[1])
    assert "snapshot" not in str(sent[2])
    assert "snapshot" not in str(brain.history)
    assert "snapshot" not in str(memory.save_turn.call_args_list)
    assert memory.save_turn.call_count == 6


def test_ordinary_operational_question_keeps_grounded_route():
    provider = create_autospec(lambda prompt: None, return_value=None)
    brain, sent, _ = make_brain(provider)
    assert brain.think("Jaki masz status?") == "STAN_MARII"
    provider.assert_called_once_with("Jaki masz status?")
    brain._grounded_think.assert_called_once()
    assert not sent


def test_single_use_structured_call_never_reads_projects():
    provider = create_autospec(lambda prompt: None, side_effect=AssertionError("must not call"))
    brain, sent, _ = make_brain(provider)
    brain._ask_once("Kritaqo: zwroc JSON", force_json=True)
    provider.assert_not_called()
    assert len(sent) == 1


@pytest.mark.parametrize("value", ["", "x" * 4001, {"invalid": "type"}, RuntimeError("SECRET_BODY")])
def test_bad_provider_output_is_explicit_unavailable_not_stale_or_maria_status(value):
    provider = create_autospec(lambda prompt: None)
    if isinstance(value, Exception):
        provider.side_effect = value
    else:
        provider.return_value = value
    brain, sent, _ = make_brain(provider)
    brain.think("Jaki status w Kritaqo?")
    brain._grounded_think.assert_not_called()
    assert "niedostepne" in sent[0][-2]["content"]
    assert "SECRET_BODY" not in str(sent)
    assert "niedostepne" not in str(brain.history)


def test_unavailable_after_success_does_not_reuse_snapshot():
    provider = create_autospec(lambda prompt: None, side_effect=['{"snapshot":"OLD_VALUE"}', '{"state":"unavailable"}'])
    brain, sent, _ = make_brain(provider)
    brain.think("Projekty Kritaqo?")
    brain.think("Jaki status Kritaqo?")
    assert "OLD_VALUE" not in str(sent[1])
    assert '"state":"unavailable"' in sent[1][-2]["content"]
    brain._grounded_think.assert_not_called()
