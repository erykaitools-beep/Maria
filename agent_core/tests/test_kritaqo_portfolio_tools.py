"""Composite tools and actual UI/brain seams; fake clients, no network/models."""
from agent_core.tests.spec_helpers import specced
from agent_core.llm.codex_chat import CodexChatBackend
from agent_core.introspection.evidence_collector import EvidenceCollector
from agent_core.introspection.response_builder import ResponseBuilder
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec

import pytest

from agent_core.llm.kritaqo_portfolio import (
    PortfolioToolsProvider, interactive_tools_used, suppress_legacy_tool_actions,
)
from agent_core.llm.chat_backend import interactive_tools_match
from agent_core.introspection.query_router import OperationalQueryRouter
from agent_core.tests.test_kritaqo_tools import FakeServer, k
from agent_core.tests.test_codex_brain_integration import make_brain
from agent_core.tests.test_codex_chat_tools import ToolProcess, call, backend, events
from agent_core.tests.test_codex_chat_ui import ui, payloads


class Client:
    def __init__(self):
        self.calls = []
        self.result = {"success": True, "sampledAt": "2026-10-19T12:00:00Z", "sessionCleanup": "confirmed",
                       "coverage": {"registered": 2, "fresh": 1, "unavailable": 1},
                       "projects": [{"id": "p1", "computer": "miniPC", "filesInspected": False}]}

    def review(self, cancelled=None):
        self.calls.append(("review", cancelled))
        return self.result

    def analyze(self, interaction_id, cancelled=None):
        self.calls.append(("analyze", interaction_id, cancelled))
        return {"success": True, "state": "pending", "sessionCleanup": "confirmed"}

    def status(self, cancelled=None):
        self.calls.append(("status", cancelled))
        return self.result


def composite(tmp_path, client=None):
    server = FakeServer()
    config = dict(data_dir=str(tmp_path), bridge_path=str(tmp_path / "unused.py"),
                  state_dir=str(tmp_path / "roblox-state"), peer_id="peer1", host_node_id="host1",
                  project_id="project1", workspace_revision=4, project_name="Roblox", computer_name="MSI")
    roblox = k.KritaqoToolsProvider(config, client_factory=server.client,
        record_reader=lambda _: {"pid": 44, "version": "0.8.18-alpha.2", "port": 8766, "token": "b" * 64})
    return PortfolioToolsProvider(roblox, client or Client()), server


def prepared(provider, text, ident="a" * 32, sid="socket1"):
    context = provider.prepare_turn(text, ident, sid)
    assert provider.accepts_context(text, ident, context)
    return context, provider.for_turn(text, ident, tool_context=context)


@pytest.mark.parametrize("text,exclusive", [("Cześć", False), ("Jak minął dzień?", False),
    ("jak wyglądają projekty", True), ("co trzeba dokończyć", True), ("co dalej", True)])
def test_general_availability_is_not_project_name_gated(tmp_path, text, exclusive):
    provider, server = composite(tmp_path)
    context, session = prepared(provider, text)
    assert suppress_legacy_tool_actions(True, context) is exclusive
    assert not interactive_tools_used(context)
    assert {s["name"] for s in session.specs} == {
        "kritaqo_portfolio_review", "kritaqo_portfolio_analyze", "kritaqo_portfolio_status"}
    assert not provider.client.calls and not server.calls
    for spec in session.specs:
        assert spec["inputSchema"] == {"type": "object", "properties": {}, "additionalProperties": False}
    session.close()


def test_dispatch_no_model_targets_and_roblox_authority_unchanged(tmp_path):
    provider, server = composite(tmp_path)
    text = "Sprawdź projekt Roblox na MSI"
    context, session = prepared(provider, text)
    names = {s["name"] for s in session.specs}
    assert {"kritaqo_roblox_submit", "kritaqo_portfolio_review"} <= names
    for arguments in ({"target": "evil"}, {"text": "injected"}, None, []):
        assert session.call("kritaqo_portfolio_review", arguments)["success"] is False
    assert not provider.client.calls and not interactive_tools_used(context)
    assert session.call("invented_tool", {})["success"] is False
    assert session.call("kritaqo_portfolio_review", {}) == provider.client.result
    assert interactive_tools_used(context)
    assert session.call("kritaqo_roblox_submit", {})["success"]
    assert len(server.mutations()) == 1 and server.mutations()[0]["payload"]["text"] == text
    assert session.call("kritaqo_portfolio_analyze", {})["state"] == "pending"
    assert provider.client.calls[-1][0:2] == ("analyze", "a" * 32)
    assert session.call("kritaqo_portfolio_status", {})["success"]
    session.close()
    assert session.call("kritaqo_portfolio_analyze", {})["success"] is False
    assert len(provider.client.calls) == 3


@pytest.mark.parametrize("clear", ["clear_context", "clear_all_contexts"])
def test_clear_cancels_inflight_and_never_dispatches_after_revocation(tmp_path, clear):
    entered = threading.Event(); released = threading.Event()
    class Waiting(Client):
        def analyze(self, interaction_id, cancelled=None):
            self.calls.append(("analyze", interaction_id, cancelled)); entered.set()
            assert cancelled.wait(1)
            released.set()
            return {"success": True, "state": "pending"}
    provider, _ = composite(tmp_path, Waiting())
    context, session = prepared(provider, "Zbadaj foldery projektów")
    results = []
    worker = threading.Thread(target=lambda: results.append(session.call("kritaqo_portfolio_analyze", {})))
    worker.start()
    assert entered.wait(1)
    getattr(provider, clear)("socket1") if clear == "clear_context" else provider.clear_all_contexts()
    worker.join(2)
    assert released.is_set() and not worker.is_alive()
    assert results == [{"success": False, "state": "unknown", "reason": "cancelled"}]
    assert not provider.accepts_context(context.text, context.interaction_id, context)
    assert not session.call("kritaqo_portfolio_review", {})["success"]
    assert len(provider.client.calls) == 1


def test_forged_context_and_explicit_camera_do_not_get_portfolio(tmp_path):
    provider, server = composite(tmp_path)
    context, session = prepared(provider, "Cześć")
    assert not provider.accepts_context("changed", "a" * 32, context)
    assert not provider.accepts_context(context.text, "b" * 32, context)
    assert not provider.accepts_context(context.text, "a" * 32, {})
    assert provider.for_turn(context.text, "a" * 32, tool_context=object()) is None
    assert provider.prepare_turn("Co widzisz w kamerze?", "b" * 32, "socket1") is None
    assert not provider.accepts_context(context.text, "a" * 32, context)
    assert not provider.client.calls and not server.calls
    session.close()


def test_safe_exception_and_serialization_errors_do_not_leak(tmp_path):
    client = Client()
    client.review = Mock(side_effect=RuntimeError("SECRET credentials"))
    provider, _ = composite(tmp_path, client)
    context, session = prepared(provider, "Jakie mamy projekty?")
    assert session.call("kritaqo_portfolio_review", {}) == {
        "success": False, "state": "unknown", "reason": "portfolio_unavailable"}
    client.review = lambda **kw: {"text": float("nan")}
    assert "SECRET" not in json.dumps(session.call("kritaqo_portfolio_review", {}))
    assert interactive_tools_used(context)


@pytest.mark.parametrize("prompt", ["jak wyglądają projekty i co trzeba dokończyć?", "Jaki jest status Kritaqo?"])
def test_real_brain_protocol_reads_portfolio_without_camera_or_stale_metadata(tmp_path, prompt):
    provider, server = composite(tmp_path)
    context, session = prepared(provider, prompt)
    session.close()
    # Backend cleanup closes its session, not the frozen retry authority.
    context = provider.prepare_turn(prompt, "b" * 32, "socket1")
    proc = ToolProcess(events=events(call(name="kritaqo_portfolio_review")))
    api = backend(tmp_path, proc, provider)
    brain = make_brain(api)
    brain._query_router = OperationalQueryRouter()
    brain._evidence_collector = specced(EvidenceCollector); brain._response_builder = specced(ResponseBuilder)
    brain._request_context_provider = create_autospec(lambda prompt: None, side_effect=AssertionError("stale metadata"))
    assert brain.think(prompt, interaction_id="b" * 32, tool_context=context) == "Finished"
    assert len(provider.client.calls) == 1 and provider.client.calls[0][0] == "review"
    assert interactive_tools_used(context)
    brain._evidence_collector.collect_for_mode.assert_not_called()
    brain._request_context_provider.assert_not_called()
    assert not server.mutations()


@pytest.mark.parametrize("prompt", ["Co robisz?", "Czego się uczysz?", "Co widzisz w kamerze?"])
def test_actual_brain_retains_operational_and_camera_grounding(tmp_path, prompt):
    provider, _ = composite(tmp_path)
    api = specced(CodexChatBackend, provider="codex", model="fixture-model", tool_provider=None); api.tool_provider = provider
    context = provider.prepare_turn(prompt, "a" * 32, "socket1")
    brain = make_brain(api)
    brain._query_router = OperationalQueryRouter()
    brain._evidence_collector = specced(EvidenceCollector); brain._response_builder = specced(ResponseBuilder)
    brain._grounded_think = Mock(return_value="grounded")
    assert brain.think(prompt, interaction_id="a" * 32, tool_context=context) == "grounded"
    brain._grounded_think.assert_called_once()
    api.chat.assert_not_called()


def test_ui_preserves_legacy_detectors_until_a_generic_tool_is_actually_used(ui, monkeypatch):
    provider, _ = composite(ui.tmp)
    _, ws = ui.client()
    brain = ui.module.get_maria_brain()
    brain._chat_backend = SimpleNamespace(tool_provider=provider)
    from agent_core.perception import learning_intent, maria_speech_intent
    learning = Mock(return_value=None); cancellation = Mock(return_value=None); response = Mock(return_value=None)
    monkeypatch.setattr(learning_intent, "detect_learning_intent", learning)
    monkeypatch.setattr(learning_intent, "detect_cancel_intent", cancellation)
    monkeypatch.setattr(maria_speech_intent, "detect_maria_intent", response)
    ws.emit("chat_message", {"message": "Cześć"})
    learning.assert_called_once(); cancellation.assert_called_once(); response.assert_called_once()
    def think(text, **kwargs):
        session = provider.for_turn(text, kwargs["interaction_id"], tool_context=kwargs["tool_context"])
        session.call("kritaqo_portfolio_review", {})
        session.close()
        return "Mogę zaproponować kolejne kroki na podstawie raportu."
    brain.think = think
    ws.emit("chat_message", {"message": "Pomóż mi się zorientować"})
    assert learning.call_count == 2 and cancellation.call_count == 2
    assert response.call_count == 1
    assert len(provider.client.calls) == 1
    ws.disconnect()


def test_session_cleanup_preserves_exact_retry_context_and_close_cancels_only_own_call(tmp_path):
    provider, _ = composite(tmp_path)
    context, first = prepared(provider, "Sprawdź wszystkie projekty")
    first.close()
    assert provider.accepts_context(context.text, context.interaction_id, context)
    assert not first.call("kritaqo_portfolio_review", {})["success"]
    second = provider.for_turn(context.text, context.interaction_id, tool_context=context)
    assert second is not None and second.call("kritaqo_portfolio_analyze", {})["state"] == "pending"
    assert provider.client.calls[-1][1] == context.interaction_id
    provider.clear_context(context.conversation_id)
    assert second._cancelled.is_set() and not second.call("kritaqo_portfolio_status", {})["success"]


def test_actual_factory_wraps_configured_roblox_and_keeps_disabled_case(monkeypatch, tmp_path):
    from agent_core.llm import kritaqo_tools, kritaqo_portfolio_client
    provider, _ = composite(tmp_path)
    monkeypatch.setattr(kritaqo_tools.KritaqoToolsProvider, "from_env", lambda: provider.roblox)
    client = Client()
    constructor = Mock(return_value=client)
    monkeypatch.setattr(kritaqo_portfolio_client, "PortfolioClient", constructor)
    actual = kritaqo_tools.create_kritaqo_tools_provider()
    assert actual.roblox is provider.roblox and actual.client is client
    constructor.assert_called_once_with(provider.roblox.config)
    assert not client.calls
    monkeypatch.setattr(kritaqo_tools.KritaqoToolsProvider, "from_env", lambda: None)
    assert kritaqo_tools.create_kritaqo_tools_provider() is None
