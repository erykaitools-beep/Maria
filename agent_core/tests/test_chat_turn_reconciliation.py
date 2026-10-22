"""Real Socket.IO path with fake brain: retries are transport-only."""
from uuid import uuid4

from agent_core.tests.test_codex_chat_ui import ui, payloads
from maria_ui.chat_turns import ChatTurnStore


def test_reply_survives_socket_reconnect_without_second_model_call(ui, monkeypatch):
    store = ChatTurnStore(ui.tmp / "turns")
    monkeypatch.setattr(ui.module, "_chat_turn_store", store)
    http, ws = ui.client()
    ws.get_received()
    nonce = uuid4().hex
    brain = ui.module.get_maria_brain()
    ws.emit("chat_message", {"message": "Cześć Mario", "request_id": nonce})
    response = payloads(ws, "chat_response")[0]
    assert response["request_id"] == nonce
    assert len(brain.calls) == 1
    ws.disconnect()
    http2, ws2 = ui.client()
    assert http2.get("/api/chat/turn/" + nonce).json["response"]["message"] == brain.reply
    ws2.get_received()
    ws2.emit("chat_message", {"message": "Cześć Mario", "request_id": nonce})
    reply = payloads(ws2, "chat_response")[0]
    assert reply["replayed"] is True
    assert len(brain.calls) == 1
    assert len(ui.module.get_ui_chat_history()) == 2
    ws2.emit("chat_message", {"message": "Inne polecenie", "request_id": nonce})
    assert payloads(ws2, "chat_response")[0]["code"] == "request_conflict"
    assert len(brain.calls) == 1


def test_interrupted_receipt_and_busy_never_dispatch(ui, monkeypatch):
    store = ChatTurnStore(ui.tmp / "turns")
    old = uuid4().hex
    store.claim(old, "Polecenie")
    store = ChatTurnStore(ui.tmp / "turns")
    monkeypatch.setattr(ui.module, "_chat_turn_store", store)
    http, ws = ui.client()
    ws.get_received()
    brain = ui.module.get_maria_brain()
    ws.emit("chat_message", {"message": "Polecenie", "request_id": old})
    assert payloads(ws, "chat_ack")[0]["state"] == "unknown"
    assert not brain.calls
    nonce = uuid4().hex
    ui.module._chat_turn_lock.acquire()
    try:
        ws.emit("chat_message", {"message": "Cześć Mario", "request_id": nonce})
    finally:
        ui.module._chat_turn_lock.release()
    reply = payloads(ws, "chat_response")[0]
    assert reply["code"] == "busy" and reply["request_id"] == nonce
    assert store.lookup(nonce) is None
    assert not brain.calls
