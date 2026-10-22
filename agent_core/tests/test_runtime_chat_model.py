"""Selected runtime instance is evidence, not provider attestation."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from models.ollama_brain import OllamaBrain
from agent_core.llm.codex_chat import CodexChatBackend
from agent_core.introspection.evidence_collector import EvidenceCollector
from agent_core.introspection.query_router import OperationalQueryRouter, ResponseMode
from agent_core.introspection.response_builder import ResponseBuilder


def brain_for(backend):
    brain = OllamaBrain(model='unrelated-default', chat_backend=backend, log_fn=lambda *_: None)
    brain.refresh_time_context = lambda: None
    brain._conversation_memory = None
    brain._user_profile = None
    return brain


@pytest.mark.parametrize('fast', ['0', '1'])
def test_instance_context_off_history_with_kritaqo(monkeypatch, fast):
    monkeypatch.setenv('CHAT_FAST_CONTEXT', fast)
    monkeypatch.setenv('MARIA_CODEX_MODEL', 'wrong-environment')
    sent = []
    backend = SimpleNamespace(provider='codex', model='gpt-6.1-sol',
        chat=lambda messages, **kw: sent.append(deepcopy(messages)) or 'ok')
    brain = brain_for(backend)
    provider = Mock(return_value='KRITAQO_FRESH_SNAPSHOT')
    brain._request_context_provider = provider
    brain.think('Co w Kritaqo?')
    text = '\n'.join(m['content'] for m in sent[0])
    assert 'gpt-6.1-sol' in text and 'wrong-environment' not in text
    assert 'KRITAQO_FRESH_SNAPSHOT' in text and 'provider_confirmed_model' in text
    assert sent[0][-1] == {'role': 'user', 'content': 'Co w Kritaqo?'}
    assert not any('current_chat_instance' in m['content'] or 'KRITAQO_FRESH_SNAPSHOT' in m['content'] for m in brain.history)
    assert provider.call_count == 1
    backend.model = 'selected-next-model'
    brain.think('Dziekuje')
    assert 'selected-next-model' in '\n'.join(m['content'] for m in sent[1])


def test_grounded_formatter_and_raw_fallback(tmp_path):
    sent = []
    def fail(messages, **kw):
        sent.append(deepcopy(messages))
        raise RuntimeError('fake unavailable')
    brain = brain_for(SimpleNamespace(provider='codex', model='gpt-6.1-sol', chat=fail))
    collector = EvidenceCollector(str(tmp_path))
    brain.set_grounding_pipeline(OperationalQueryRouter(), collector, ResponseBuilder())
    text = brain.think('Kim jesteś?')
    assert 'gpt-6.1-sol' in text and 'current_chat_instance' in text
    assert 'llama3.1:8b' not in text and '8B parametrow' not in text
    assert 'gpt-6.1-sol' in sent[0][1]['content']
    assert not any('provider_confirmed_model' in m['content'] for m in brain.history if m['role'] == 'system')


def test_structured_calls_unaffected():
    seen = []
    brain = brain_for(SimpleNamespace(provider='codex', model='gpt-6.1-sol',
        chat=lambda messages, **kw: seen.append(messages) or '{}'))
    brain._ask_once('extract', system='fixed', force_json=True)
    assert seen == [[{'role': 'system', 'content': 'fixed'}, {'role': 'user', 'content': 'extract'}]]


def test_local_and_unknown_instance_not_environment(monkeypatch):
    monkeypatch.setenv('MARIA_CHAT_MODEL', 'wrong-env')
    brain = OllamaBrain.__new__(OllamaBrain)
    brain.model = 'local-selected'
    brain._chat_backend = None
    assert 'local-selected' in brain.runtime_chat_context()
    brain._chat_backend = object()
    assert 'local-selected' not in brain.runtime_chat_context()
    assert 'unknown' in brain.runtime_chat_context()
    brain._chat_backend = SimpleNamespace(provider='codex', model='unsafe\nINSTRUCTIONS')
    assert 'INSTRUCTIONS' not in brain.runtime_chat_context()


def test_unknown_reader_never_leaks_exception(tmp_path):
    collector = EvidenceCollector(str(tmp_path))
    for reader in (None, lambda: (_ for _ in ()).throw(RuntimeError('SECRET'))):
        collector.set_chat_runtime_reader(reader)
        value = next(e.value for e in collector.collect_identity() if e.key == 'identity_backend')
        assert 'unknown' in value and 'SECRET' not in value


def test_model_is_not_mode():
    router = OperationalQueryRouter()
    assert router.classify('Jaki model generuje twoje odpowiedzi?') == ResponseMode.NORMAL
    assert router.classify('what mode is active?') == ResponseMode.GROUNDED_STATUS


def test_codex_descriptor_without_execution():
    backend = CodexChatBackend(model='gpt-6.1-sol', codex_bin='/not-executed')
    assert backend.provider == 'codex' and backend.model == 'gpt-6.1-sol'
