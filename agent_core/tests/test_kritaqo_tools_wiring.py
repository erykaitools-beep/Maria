"""Authenticated chat routing and stable task identity; no model/network calls."""
from agent_core.introspection.query_router import OperationalQueryRouter
from agent_core.tests.spec_helpers import specced
from agent_core.llm.codex_chat import CodexChatBackend
from agent_core.introspection.evidence_collector import EvidenceCollector
from agent_core.introspection.response_builder import ResponseBuilder
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec

import pytest

from agent_core.tests.test_codex_chat_ui import ui, payloads
from agent_core.tests.test_codex_brain_integration import make_brain


def provider():
    return SimpleNamespace(accepts_prompt=lambda text: "Roblox" in text)


def test_actual_factory_exposes_provider_for_interactive_routing(monkeypatch):
    from agent_core.llm.chat_backend import create_chat_backend, interactive_tools_match
    from agent_core.llm import kritaqo_tools
    tools = provider()
    monkeypatch.setenv("MARIA_CHAT_BACKEND", "codex")
    monkeypatch.setattr(kritaqo_tools, "create_kritaqo_tools_provider", lambda: tools)
    backend = create_chat_backend()
    assert interactive_tools_match(backend, "Sprawdz Roblox", "a" * 32) is True
    assert interactive_tools_match(backend, "Dzien dobry", "a" * 32) is False
    assert interactive_tools_match(backend, "Sprawdz Roblox", None) is False


def test_scoped_tool_turn_bypasses_legacy_context_and_grounding():
    backend = specced(CodexChatBackend, provider="codex", model="fixture-model", tool_provider=None)
    backend.tool_provider = provider()
    backend.chat.return_value = "Roblox jest dostepny."
    brain = make_brain(backend)
    legacy = create_autospec(lambda prompt: None, side_effect=AssertionError("legacy snapshot must not replace live tool read"))
    brain._request_context_provider = legacy
    brain._query_router = specced(OperationalQueryRouter)
    brain._evidence_collector = specced(EvidenceCollector)
    brain._response_builder = specced(ResponseBuilder)
    prompt = "Sprawdz projekt Roblox na MSI"
    assert brain.think(prompt, interaction_id="a" * 32) == "Roblox jest dostepny."
    legacy.assert_not_called()
    brain._query_router.classify.assert_not_called()
    assert backend.chat.call_args.args[0][-1] == {"role": "user", "content": prompt}
    assert backend.chat.call_args.kwargs["interaction_id"] == "a" * 32


def test_json_generation_cannot_reuse_interactive_tools():
    backend = specced(CodexChatBackend, provider="codex", model="fixture-model", tool_provider=None)
    backend.tool_provider = provider()
    backend.chat.return_value = '{"ok":true}'
    brain = make_brain(backend)
    brain._chat([{"role": "user", "content": "Sprawdz Roblox"}],
                force_json=True, interaction_id="a" * 32)
    assert "interaction_id" not in backend.chat.call_args.kwargs


def test_one_shot_non_json_generation_cannot_inherit_tool_authority():
    backend = specced(CodexChatBackend, provider="codex", model="fixture-model", tool_provider=None)
    backend.tool_provider = provider()
    backend.chat.return_value = "analysis"
    brain = make_brain(backend)
    brain._ask_once("Sprawdz Roblox", interaction_id="a" * 32)
    assert "interaction_id" not in backend.chat.call_args.kwargs


def test_socket_retry_preserves_server_identity_and_ignores_client_id(ui, monkeypatch):
    _, ws = ui.client()
    ws.get_received()
    brain = ui.module.get_maria_brain()
    brain._chat_backend = SimpleNamespace(tool_provider=provider())
    calls = []

    def think(text, **kwargs):
        calls.append((text, kwargs))
        if len(calls) == 1:
            raise RuntimeError("simulated post-send bookkeeping failure")
        return "Zlecenie juz przyjete."

    brain.think = think
    import time
    monkeypatch.setattr(time, "sleep", lambda _: None)
    ws.emit("chat_message", {"message": "Zlec w Roblox: sprawdz strukture", "interaction_id": "client-chosen"})
    assert payloads(ws, "chat_response")[0]["success"] is True
    assert len(calls) == 2
    first, second = (call[1]["interaction_id"] for call in calls)
    assert first == second and len(first) == 32 and first != "client-chosen"


def test_tool_cancel_never_enters_legacy_learning_cancel(ui, monkeypatch):
    _, ws = ui.client()
    ws.get_received()
    brain = ui.module.get_maria_brain()
    brain._chat_backend = SimpleNamespace(tool_provider=provider())
    import agent_core.perception.learning_intent as intents
    for name in ("detect_cancel_intent", "detect_learning_intent", "detect_operational_intent"):
        monkeypatch.setattr(intents, name, Mock(side_effect=AssertionError("wrong dispatcher")))
    ws.emit("chat_message", {"message": "Anuluj zadanie Roblox"})
    assert payloads(ws, "chat_response")[0]["success"] is True
    assert len(brain.calls) == 1 and "interaction_id" in brain.calls[0][1]
    intents.detect_cancel_intent.assert_not_called()


def test_tool_response_does_not_create_unrelated_legacy_goal(ui, monkeypatch):
    _, ws = ui.client()
    ws.get_received()
    brain = ui.module.get_maria_brain()
    brain._chat_backend = SimpleNamespace(tool_provider=provider())
    brain.reply = "Pobiore pliki Roblox."
    import agent_core.perception.maria_speech_intent as speech
    detector = Mock(return_value={"action": "fetch", "topic": "Roblox"})
    monkeypatch.setattr(speech, "detect_maria_intent", detector)
    ws.emit("chat_message", {"message": "Zlec w Roblox: sprawdz strukture"})
    assert payloads(ws, "chat_response")[0]["success"] is True
    detector.assert_not_called()


def scoped_provider(root):
    from agent_core.llm.kritaqo_tools import KritaqoToolsProvider
    return KritaqoToolsProvider(dict(
        data_dir=str(root), bridge_path=str(root / "bridge.py"),
        state_dir=str(root / "tool-state"), peer_id="peer1", host_node_id="host1",
        project_id="project1", workspace_revision=4,
        project_name="Roblox", computer_name="MSI"))


def test_socket_natural_request_and_followup_use_same_project(ui, monkeypatch):
    monkeypatch.setattr(ui.module, "RATE_LIMIT_MESSAGES", 20)
    _, ws = ui.client()
    brain = ui.module.get_maria_brain()
    tools = scoped_provider(ui.tmp)
    brain._chat_backend = SimpleNamespace(tool_provider=tools)
    ws.emit("chat_message", {"message": "Jaki jest wynik zadania Roblox?"})
    prompt = "Maria, mogłabyś zrobić projekt reklamowy na Halloween, jakiś plakat?"
    ws.emit("chat_message", {"message": prompt})
    text, kwargs = brain.calls[-1]
    session = tools.for_turn(text, kwargs["interaction_id"], tool_context=kwargs["tool_context"])
    assert "kritaqo_roblox_submit" in {s["name"] for s in session.specs}
    ws.emit("chat_message", {"message": "Jaki jest wynik zatania roboksz?"})
    text, kwargs = brain.calls[-1]
    session = tools.for_turn(text, kwargs["interaction_id"], tool_context=kwargs["tool_context"])
    assert {s["name"] for s in session.specs} == {"kritaqo_roblox_status", "kritaqo_roblox_result"}


def test_socket_context_is_not_global_or_client_supplied(ui):
    _, first = ui.client()
    _, second = ui.client()
    brain = ui.module.get_maria_brain()
    brain._chat_backend = SimpleNamespace(tool_provider=scoped_provider(ui.tmp))
    first.emit("chat_message", {"message": "Jaki jest status Roblox?"})
    second.emit("chat_message", {"message": "Przygotuj plakat na Halloween",
                                 "tool_context": {"project": "Roblox"},
                                 "interaction_id": "a" * 32})
    assert "tool_context" not in brain.calls[-1][1]
    assert "interaction_id" not in brain.calls[-1][1]


def test_socket_retry_keeps_context_identity(ui, monkeypatch):
    _, ws = ui.client()
    brain = ui.module.get_maria_brain()
    brain._chat_backend = SimpleNamespace(tool_provider=scoped_provider(ui.tmp))
    ws.emit("chat_message", {"message": "Jaki jest status Roblox?"})
    calls = []

    def think(text, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("simulated response failure")
        return "Przyjete."

    brain.think = think
    import time
    monkeypatch.setattr(time, "sleep", lambda _: None)
    ws.emit("chat_message", {"message": "Mogłabyś przygotować plakat na Halloween?"})
    assert len(calls) == 2
    assert calls[0]["interaction_id"] == calls[1]["interaction_id"]
    assert calls[0]["tool_context"] is calls[1]["tool_context"]


def test_clear_history_and_disconnect_forget_project(ui, monkeypatch):
    monkeypatch.setattr(ui.module, "RATE_LIMIT_MESSAGES", 20)
    _, ws = ui.client()
    brain = ui.module.get_maria_brain()
    tools = scoped_provider(ui.tmp)
    brain._chat_backend = SimpleNamespace(tool_provider=tools)
    ws.emit("chat_message", {"message": "Jaki jest status Roblox?"})
    first_text, first_kwargs = brain.calls[-1]
    ws.emit("clear_history")
    assert not tools.accepts_context(first_text, first_kwargs["interaction_id"], first_kwargs["tool_context"])
    ws.emit("chat_message", {"message": "Przygotuj plakat na Halloween"})
    assert "tool_context" not in brain.calls[-1][1]
    ws.emit("chat_message", {"message": "Jaki jest status Roblox?"})
    text, kwargs = brain.calls[-1]
    ws.disconnect()
    assert not tools.accepts_context(text, kwargs["interaction_id"], kwargs["tool_context"])


def test_contextual_followup_bypasses_brain_operational_routing(tmp_path):
    backend = specced(CodexChatBackend, provider="codex", model="fixture-model", tool_provider=None)
    tools = scoped_provider(tmp_path)
    backend.tool_provider = tools
    backend.chat.return_value = "Sprawdzam wynik zlecenia."
    tools.prepare_turn("Jaki jest status Roblox?", "a" * 32, "socket-1")
    prompt = "Gdzie leży problem, że nie możesz zacząć pracy nad tym plakatem?"
    context = tools.prepare_turn(prompt, "b" * 32, "socket-1")
    assert context is not None
    brain = make_brain(backend)
    brain._request_context_provider = create_autospec(lambda prompt: None, side_effect=AssertionError("wrong metadata route"))
    brain._query_router = specced(OperationalQueryRouter)
    brain._evidence_collector = specced(EvidenceCollector)
    brain._response_builder = specced(ResponseBuilder)
    assert brain.think(prompt, interaction_id="b" * 32, tool_context=context) == backend.chat.return_value
    brain._request_context_provider.assert_not_called()
    brain._query_router.classify.assert_not_called()
    assert backend.chat.call_args.kwargs["tool_context"] is context


def test_socket_acknowledgement_keeps_result_tools_read_only(ui, monkeypatch):
    monkeypatch.setattr(ui.module, "RATE_LIMIT_MESSAGES", 20)
    _, ws = ui.client()
    brain = ui.module.get_maria_brain()
    tools = scoped_provider(ui.tmp)
    brain._chat_backend = SimpleNamespace(tool_provider=tools)
    ws.emit("chat_message", {"message": "Przygotuj plakat Halloween w Roblox na MSI"})
    for text in ("dziękuję. Powiadom mnie jak będzie gotowe",
                 "jak wygląda plakat zrobiłaś, skończony czy jak możesz mieć potwierdzić"):
        ws.emit("chat_message", {"message": text})
        actual, kwargs = brain.calls[-1]
        assert actual == text
        session = tools.for_turn(text, kwargs["interaction_id"], tool_context=kwargs["tool_context"])
        assert {s["name"] for s in session.specs} == {"kritaqo_roblox_status", "kritaqo_roblox_result"}


@pytest.mark.parametrize("scope", ["active", "expired", "other_socket"])
def test_real_brain_never_substitutes_camera_for_poster_result(tmp_path, monkeypatch, scope):
    from agent_core.introspection.query_router import OperationalQueryRouter
    from agent_core.llm import kritaqo_tools
    tools = scoped_provider(tmp_path)
    backend = specced(CodexChatBackend, provider="codex", model="fixture-model", tool_provider=None)
    backend.tool_provider = tools
    backend.chat.return_value = "Wynik z Kritaqo albo prośba o wskazanie projektu."
    brain = make_brain(backend)
    brain._request_context_provider = None
    brain._query_router = OperationalQueryRouter()
    brain._evidence_collector = Mock(side_effect=AssertionError("camera must not be read"))
    brain._response_builder = specced(ResponseBuilder)
    with monkeypatch.context() as clock:
        clock.setattr(kritaqo_tools.time, "monotonic", lambda: 100)
        tools.prepare_turn("Przygotuj plakat w Roblox", "a" * 32, "phone")
        tools.prepare_turn("dziękuję. Powiadom mnie jak będzie gotowe", "b" * 32, "phone")
        clock.setattr(kritaqo_tools.time, "monotonic", lambda: 701 if scope == "expired" else 101)
        text = "jak wygląda plakat zrobiłaś, skończony czy jak możesz mieć potwierdzić"
        context = tools.prepare_turn(text, "c" * 32, "tv" if scope == "other_socket" else "phone")
        assert (context is not None) == (scope == "active")
        brain.think(text, interaction_id="c" * 32, tool_context=context)
    brain._evidence_collector.collect_for_mode.assert_not_called()
    brain._response_builder.build.assert_not_called()
    messages = backend.chat.call_args.args[0]
    notes = [m["content"] for m in messages if m["role"] == "system"]
    if scope == "active":
        assert backend.chat.call_args.kwargs["tool_context"] is context
        assert not any("Nie masz świeżego odczytu wyniku Kritaqo" in n for n in notes)
    else:
        assert any("Nie masz świeżego odczytu wyniku Kritaqo" in n for n in notes)
        assert "tool_context" not in backend.chat.call_args.kwargs
        assert tools.for_turn(text, "c" * 32) is None


def test_camera_request_in_project_conversation_uses_camera_not_tools(tmp_path):
    from agent_core.introspection.query_router import OperationalQueryRouter, ResponseMode
    tools = scoped_provider(tmp_path)
    tools.prepare_turn("Przygotuj plakat Roblox", "a" * 32, "phone")
    text = "Opisz plakat Roblox przed kamerą"
    assert tools.prepare_turn(text, "b" * 32, "phone") is None
    assert tools.for_turn(text, "b" * 32) is None
    backend = specced(CodexChatBackend, provider="codex", model="fixture-model", tool_provider=None)
    backend.tool_provider = tools
    backend.chat.return_value = "Widok kamery."
    brain = make_brain(backend)
    brain._request_context_provider = None
    brain._query_router = OperationalQueryRouter()
    brain._evidence_collector = specced(EvidenceCollector)
    brain._response_builder = specced(ResponseBuilder)
    brain._response_builder.build.return_value = SimpleNamespace(text="Rzeczywisty obraz USB.")
    assert brain.think(text) == "Widok kamery."
    brain._evidence_collector.collect_for_mode.assert_called_once_with(ResponseMode.GROUNDED_VISION, query_text=text)


def test_socket_unknown_asr_then_remaining_work_recovers_read_only(ui, monkeypatch):
    monkeypatch.setattr(ui.module, "RATE_LIMIT_MESSAGES", 20)
    _, ws = ui.client()
    brain = ui.module.get_maria_brain()
    tools = scoped_provider(ui.tmp)
    brain._chat_backend = SimpleNamespace(tool_provider=tools)
    first = "jaki jest wynik zadania Halloween w Roblox na MSI"
    ws.emit("chat_message", {"message": first})
    _, initial = brain.calls[-1]
    ws.emit("chat_message", {"message": "Jingue"})
    assert brain.calls[-1][0] == "Jingue"
    assert "tool_context" not in brain.calls[-1][1]
    assert "interaction_id" not in brain.calls[-1][1]
    assert not tools.accepts_context(first, initial["interaction_id"], initial["tool_context"])

    question = "co jeszcze zostało do zrobienia"
    ws.emit("chat_message", {"message": question})
    actual, kwargs = brain.calls[-1]
    assert actual == question
    assert kwargs["tool_context"].read_only
    session = tools.for_turn(question, kwargs["interaction_id"], tool_context=kwargs["tool_context"])
    assert {spec["name"] for spec in session.specs} == {"kritaqo_roblox_status", "kritaqo_roblox_result"}
    assert first in session.payload_text
    assert "Jingue" not in session.payload_text

    ws.emit("chat_message", {"message": "Dodaj logo do plakatu"})
    assert "tool_context" not in brain.calls[-1][1]
    assert "interaction_id" not in brain.calls[-1][1]
    ws.emit("chat_message", {"message": "Dodaj logo do plakatu w Roblox na MSI"})
    actual, kwargs = brain.calls[-1]
    session = tools.for_turn(actual, kwargs["interaction_id"], tool_context=kwargs["tool_context"])
    assert session.can_submit
    assert not tools.accepts_context(first, initial["interaction_id"], initial["tool_context"])


@pytest.mark.parametrize("ending", ["clear_history", "disconnect"])
def test_socket_suspended_context_cannot_survive_session_end(ui, monkeypatch, ending):
    monkeypatch.setattr(ui.module, "RATE_LIMIT_MESSAGES", 20)
    _, ws = ui.client()
    brain = ui.module.get_maria_brain()
    brain._chat_backend = SimpleNamespace(tool_provider=scoped_provider(ui.tmp))
    ws.emit("chat_message", {"message": "Jaki jest wynik zadania Roblox?"})
    ws.emit("chat_message", {"message": "Jingue"})
    if ending == "clear_history":
        ws.emit("clear_history")
    else:
        ws.disconnect()
        _, ws = ui.client()
    ws.emit("chat_message", {"message": "Co jeszcze zostało do zrobienia?"})
    assert "tool_context" not in brain.calls[-1][1]
    assert "interaction_id" not in brain.calls[-1][1]


@pytest.mark.parametrize("ack", ["Jingue", "Dziękuję", "Siękuję", "niewyraźny dźwięk"])
def test_brain_remaining_work_after_interjection_uses_current_tool_context(tmp_path, ack):
    backend = specced(CodexChatBackend, provider="codex", model="fixture-model", tool_provider=None)
    tools = scoped_provider(tmp_path)
    backend.tool_provider = tools
    backend.chat.return_value = "Odczytany wynik zadania."
    tools.prepare_turn("Jaki jest wynik zadania Halloween w Roblox na MSI?", "a" * 32, "phone")
    tools.prepare_turn(ack, "b" * 32, "phone")
    prompt = "co jeszcze zostało do zrobienia"
    context = tools.prepare_turn(prompt, "c" * 32, "phone")
    assert context is not None
    brain = make_brain(backend)
    brain._request_context_provider = create_autospec(lambda prompt: None, side_effect=AssertionError("legacy metadata must not replace result"))
    brain._query_router = specced(OperationalQueryRouter)
    brain._evidence_collector = specced(EvidenceCollector)
    brain._response_builder = specced(ResponseBuilder)
    assert brain.think(prompt, interaction_id="c" * 32, tool_context=context) == backend.chat.return_value
    assert backend.chat.call_args.kwargs["tool_context"] is context
    brain._request_context_provider.assert_not_called()
    brain._query_router.classify.assert_not_called()
    brain._evidence_collector.collect_for_mode.assert_not_called()


def test_socket_cold_asr_project_then_thanks_and_remaining_work(ui, monkeypatch):
    monkeypatch.setattr(ui.module, "RATE_LIMIT_MESSAGES", 20)
    _, ws = ui.client()
    brain = ui.module.get_maria_brain()
    tools = scoped_provider(ui.tmp)
    brain._chat_backend = SimpleNamespace(tool_provider=tools)
    first = "jaki jest wynik zadania halloween w roblok się na MSI"
    ws.emit("chat_message", {"message": first})
    actual, initial = brain.calls[-1]
    assert actual == first
    assert initial["tool_context"].text == first
    assert initial["tool_context"].read_only
    session = tools.for_turn(actual, initial["interaction_id"], tool_context=initial["tool_context"])
    assert {spec["name"] for spec in session.specs} == {"kritaqo_roblox_status", "kritaqo_roblox_result"}

    ws.emit("chat_message", {"message": "JinKu"})
    assert brain.calls[-1][0] == "JinKu"
    assert "tool_context" not in brain.calls[-1][1]
    assert not tools.accepts_context(first, initial["interaction_id"], initial["tool_context"])
    question = "co jeszcze zostało do zrobienia"
    ws.emit("chat_message", {"message": question})
    actual, final = brain.calls[-1]
    assert actual == question
    assert final["tool_context"].read_only
    recovered = tools.for_turn(actual, final["interaction_id"], tool_context=final["tool_context"])
    assert first in recovered.payload_text
    assert "JinKu" not in recovered.payload_text
    assert {spec["name"] for spec in recovered.specs} == {"kritaqo_roblox_status", "kritaqo_roblox_result"}
    ws.emit("chat_message", {"message": "Dodaj logo do plakatu"})
    assert "tool_context" not in brain.calls[-1][1]
    assert "interaction_id" not in brain.calls[-1][1]


def test_brain_cold_asr_project_query_routes_trusted_read_context(tmp_path):
    backend = specced(CodexChatBackend, provider="codex", model="fixture-model", tool_provider=None)
    tools = scoped_provider(tmp_path)
    backend.tool_provider = tools
    backend.chat.return_value = "Odczytany raport zadania Roblox na MSI."
    prompt = "jaki jest wynik zadania halloween w roblok się na MSI"
    context = tools.prepare_turn(prompt, "d" * 32, "new-phone")
    assert context is not None and context.read_only
    brain = make_brain(backend)
    brain._request_context_provider = create_autospec(lambda prompt: None, side_effect=AssertionError("legacy report must not replace fresh read"))
    brain._query_router = specced(OperationalQueryRouter)
    brain._evidence_collector = specced(EvidenceCollector)
    brain._response_builder = specced(ResponseBuilder)
    assert brain.think(prompt, interaction_id="d" * 32, tool_context=context) == backend.chat.return_value
    assert backend.chat.call_args.kwargs["tool_context"] is context
    assert backend.chat.call_args.args[0][-1] == {"role": "user", "content": prompt}
    brain._request_context_provider.assert_not_called()
    brain._query_router.classify.assert_not_called()
    brain._evidence_collector.collect_for_mode.assert_not_called()
