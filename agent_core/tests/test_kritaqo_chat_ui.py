"""Authenticated SocketIO -> real Maria brain -> context -> fake chat transport."""
from agent_core.tests.spec_helpers import specced
from agent_core.llm.codex_chat import CodexChatBackend
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from agent_core.tests.test_codex_chat_ui import ui, payloads
from models.ollama_brain import OllamaBrain
from agent_core.llm import kritaqo_context


def snapshot():
    return {"schemaVersion": 1, "success": True,
            "observedAt": "2026-10-16T10:00:00+00:00",
            "source": {"kind": "local-loopback", "application": "kritaqo",
                       "pid": 123, "version": "0.8.18-alpha.2", "verified": True},
            "sessionCleanup": "confirmed",
            "local": {"id": "mini", "name": "Mini fixture",
                      "projects": [{"id": "atlas", "name": "Atlas fixture", "updatedAt": 1000}],
                      "jobs": {"total": 0, "activeCount": 0, "statusCounts": {}, "active": [], "recent": []}},
            "peers": []}


def wire_real_brain(ui, monkeypatch, reader):
    monkeypatch.setenv("MARIA_KRITAQO_CONTEXT", "1")
    monkeypatch.setenv("MARIA_KRITAQO_DATA_DIR", str(ui.tmp / "kritaqo"))
    monkeypatch.setenv("MARIA_KRITAQO_BRIDGE_PATH", str(ui.tmp / "bridge.py"))
    cls = kritaqo_context.KritaqoContextProvider
    monkeypatch.setattr(kritaqo_context, "KritaqoContextProvider",
                        lambda data_dir, bridge_path: cls(data_dir, bridge_path, reader=reader))
    monkeypatch.setattr(ui.module, "OllamaBrain", OllamaBrain)
    monkeypatch.setattr(ui.module, "_build_work_context_for_brain", lambda: "")
    backend, sent = specced(CodexChatBackend, provider="codex", model="fixture-model", tool_provider=None), []
    def chat(messages, **kwargs):
        sent.append(deepcopy(list(messages)))
        return "Odpowiedz z testu transportu."
    backend.chat.side_effect = chat
    monkeypatch.setattr(ui.module, "create_chat_backend", lambda **kw: backend)
    return sent


def contexts(messages):
    return [json.loads(m["content"]) for m in messages
            if m["role"] == "system" and m["content"].startswith('{"type":"kritaqo_context"')]


@pytest.mark.parametrize("fast", ["0", "1"])
def test_authenticated_turn_delivers_metadata_and_next_normal_turn_does_not(ui, monkeypatch, fast):
    monkeypatch.setenv("CHAT_FAST_CONTEXT", fast)
    reader = Mock(return_value=snapshot())
    sent = wire_real_brain(ui, monkeypatch, reader)
    http, ws = ui.client()
    ws.get_received()
    reader.assert_not_called()  # factory + connect + status are side-effect free
    prompt = "Maria, jaki status projektow w Kritaqo?"
    ws.emit("chat_message", {"message": prompt})
    reply = payloads(ws, "chat_response")
    assert len(reply) == 1 and reply[0]["success"] and not reply[0]["fallback"]
    assert len(sent) == 1
    context = contexts(sent[0])[0]
    assert context["state"] == "available"
    assert context["UNTRUSTED_DATA"]["local"]["projects"][0]["name"] == "Atlas fixture"
    assert sent[0][-1] == {"role": "user", "content": prompt}
    reader.assert_called_once_with(str(ui.tmp / "kritaqo"))
    ws.emit("chat_message", {"message": "Dziekuje Mario."})
    assert payloads(ws, "chat_response")[0]["success"]
    assert not contexts(sent[1])
    reader.assert_called_once()
    history = http.get("/api/chat/history").json["messages"]
    assert len(history) == 4
    assert history[0]["content"] == prompt
    assert "UNTRUSTED_DATA" not in str(history)
    assert "Atlas fixture" not in str(ui.module._maria_brain.history)


def test_uncertain_cleanup_reaches_backend_as_unknown_without_success_data(ui, monkeypatch):
    class FailedCleanup(Exception):
        code = "cleanup_uncertain"
        session_cleanup = "uncertain"
    reader = Mock(side_effect=FailedCleanup("SECRET_SESSION_SENTINEL"))
    sent = wire_real_brain(ui, monkeypatch, reader)
    _, ws = ui.client()
    ws.get_received()
    ws.emit("chat_message", {"message": "Jaki status Kritaqo?"})
    assert payloads(ws, "chat_response")[0]["success"]
    context = contexts(sent[0])[0]
    assert context["state"] == "unknown"
    assert context["sessionCleanup"] == "uncertain"
    assert "UNTRUSTED_DATA" not in context
    assert "SECRET_SESSION_SENTINEL" not in str(sent)
    reader.assert_called_once()
