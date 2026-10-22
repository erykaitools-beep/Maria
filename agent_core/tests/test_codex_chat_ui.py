"""Offline integration of the real Flask/SocketIO chat with fake transport."""
from collections import deque
import importlib
import json
from types import SimpleNamespace

import pytest


class FakeBrain:
    def __init__(self, **kwargs):
        self.arguments = kwargs
        self.history = deque([{"role": "system", "content": "test"}], maxlen=30)
        self.calls = []
        self.reply = "Czesc, jestem Maria."
        self.error = None

    def think(self, text, **kwargs):
        self.calls.append((text, kwargs))
        if self.error is not None:
            raise self.error
        return self.reply

    def set_user_profile(self, value):
        pass

    def set_llm_tape(self, value):
        pass

    def set_grounding_pipeline(self, *values):
        pass

    def set_work_context_provider(self, value):
        pass


@pytest.fixture
def ui(monkeypatch, tmp_path):
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    monkeypatch.chdir(tmp_path)
    for key, value in {
        "MARIA_CHAT_BACKEND": "codex", "MARIA_CODEX_MODEL": "gpt-6.1-sol",
        "MARIA_PIN": "246810", "MARIA_SECRET_KEY": "isolated-test-key",
        "MARIA_CORS_ORIGINS": "http://localhost:5000",
    }.items():
        monkeypatch.setenv(key, value)
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="", returncode=0))
    cfg = importlib.import_module("maria_ui.config")
    monkeypatch.setattr(cfg, "CHAT_LOG_FILE", tmp_path / "chat.jsonl")
    module = importlib.import_module("maria_ui.app")
    for key, value in {
        "CHAT_LOG_FILE": tmp_path / "chat.jsonl", "UI_PIN": "246810",
        "_maria_brain": None, "_ui_chat_history": [],
        "_ui_chat_history_loaded": True, "_rate_limit_data": {}, "_login_failures": {},
        "HOMEOSTASIS_AVAILABLE": False, "CONSCIOUSNESS_AVAILABLE": False,
        "OLLAMA_AVAILABLE": True,
    }.items():
        monkeypatch.setattr(module, key, value)
    monkeypatch.setitem(module.app.config, "SECRET_KEY", "isolated-test-key")
    monkeypatch.setitem(module.app.config, "TESTING", True)
    monkeypatch.setattr(module, "_get_identity_store", lambda: None)
    monkeypatch.setattr(module, "OllamaBrain", FakeBrain)
    sentinel = object()
    monkeypatch.setattr(module, "create_chat_backend", lambda **k: sentinel)
    monkeypatch.setattr(module, "_create_ui_router", lambda *_: pytest.fail("Codex must not construct NIM router"))
    backend = importlib.import_module("agent_core.llm.chat_backend")
    monkeypatch.setattr(backend.shutil, "which", lambda _: "/fake/codex")
    operator = importlib.import_module("agent_core.operator.operator_model")
    memory = SimpleNamespace(learn_from_message=lambda *_: None, record_interaction=lambda *_: None)
    monkeypatch.setattr(operator, "get_operator_model", lambda: memory)
    consciousness = importlib.import_module("agent_core.consciousness")
    monkeypatch.setattr(consciousness, "record_experience", lambda *a, **k: None)
    collector = importlib.import_module("agent_core.introspection.evidence_collector")
    monkeypatch.setattr(collector, "EvidenceCollector", lambda **k: SimpleNamespace(set_llm_tape=lambda *_: None))
    tape = importlib.import_module("agent_core.llm.llm_tape")
    monkeypatch.setattr(tape, "LLMTape", lambda **k: object())
    clients = []

    def client(authenticated=True):
        http = module.app.test_client()
        if authenticated:
            assert http.post("/login", data={"pin": "246810"}).status_code == 302
        ws = module.socketio.test_client(module.app, flask_test_client=http)
        clients.append(ws)
        return http, ws

    yield SimpleNamespace(module=module, config=cfg, client=client, sentinel=sentinel, tmp=tmp_path)
    for ws in clients:
        if ws.is_connected():
            ws.disconnect()


def payloads(ws, name):
    return [e["args"][0] for e in ws.get_received() if e["name"] == name]


def test_unauthenticated_http_and_socket_rejected(ui):
    http, ws = ui.client(authenticated=False)
    denied = http.get("/api/chat/history")
    assert denied.status_code == 302
    assert denied.headers["Location"].endswith("/login")
    assert not ws.is_connected()
    assert ui.module._maria_brain is None
    assert not (ui.tmp / "chat.jsonl").exists()


def test_codex_metadata_and_authenticated_message_flow(ui):
    http, ws = ui.client()
    connected = payloads(ws, "connected")[0]
    assert connected["chat_backend"] == {"provider": "codex", "model": "gpt-6.1-sol", "configured": True}
    status = http.get("/api/status")
    assert status.status_code == 200
    assert status.json["chat_backend"] == connected["chat_backend"]
    brain = ui.module._maria_brain
    assert isinstance(brain, FakeBrain)
    assert brain.arguments["chat_backend"] is ui.sentinel
    assert brain.arguments["verify_model"] is False
    ws.emit("chat_message", {"message": "Czesc Mario"})
    replies = payloads(ws, "chat_response")
    assert replies == [{"success": True, "message": brain.reply, "fallback": False}]
    assert brain.calls == [("Czesc Mario", {"raise_on_timeout": True})]
    history = http.get("/api/chat/history").json["messages"]
    assert [(m["role"], m["content"]) for m in history] == [("user", "Czesc Mario"), ("maria", brain.reply)]


@pytest.mark.parametrize("failure", ["timeout", "backend"])
def test_provider_failure_is_codex_fallback_without_retry(ui, failure):
    _, ws = ui.client()
    ws.get_received()
    brain = ui.module.get_maria_brain()
    brain.error = (ui.module.BrainTimeout("test timeout") if failure == "timeout"
                   else ui.module.BrainBackendError("test unavailable"))
    ws.emit("chat_message", {"message": "Czesc Mario"})
    replies = payloads(ws, "chat_response")
    assert len(replies) == 1
    reply = replies[0]
    assert reply["fallback"] is True
    assert "Codex" in reply["message"] and "Ollama" not in reply["message"]
    assert reply.get("timeout", False) is (failure == "timeout")
    assert len(brain.calls) == 1
    assert all(m["role"] != "maria" for m in ui.module.get_ui_chat_history())


def test_overlapping_chat_rejected_before_brain(ui):
    _, ws = ui.client()
    ws.get_received()
    brain = ui.module.get_maria_brain()
    ui.module._chat_turn_lock.acquire()
    try:
        ws.emit("chat_message", {"message": "Czesc Mario"})
    finally:
        ui.module._chat_turn_lock.release()
    assert payloads(ws, "chat_response")[0]["success"] is False
    assert not brain.calls
    assert not ui.module.get_ui_chat_history()


def test_tailscale_https_origin_is_exact(ui, monkeypatch):
    import subprocess

    def result(argv, **kwargs):
        text = ("100.64.0.7\n" if argv[1] == "ip" else
                json.dumps({"Self": {"DNSName": "maria.example-tail.ts.net."}}))
        return SimpleNamespace(stdout=text, returncode=0)

    monkeypatch.setattr(subprocess, "run", result)
    origins = ui.config._build_cors_origins()
    assert "https://maria.example-tail.ts.net" in origins
    assert "http://100.64.0.7:5000" in origins
    assert "*" not in origins
    assert "https://other.example-tail.ts.net" not in origins
    assert "https://maria.example-tail.ts.net.evil.example" not in origins
