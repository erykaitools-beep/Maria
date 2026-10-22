"""First-chat mode uses the authenticated real UI without task side effects."""
from types import SimpleNamespace

import pytest

from agent_core.tests.test_codex_chat_ui import ui, payloads


def forbidden(*args, **kwargs):
    pytest.fail("chat-only invoked an execution/provider boundary")


def test_chat_only_forces_local_without_constructing_remote_integrations(ui, monkeypatch):
    monkeypatch.setenv("MARIA_CHAT_ONLY", "1")
    monkeypatch.setenv("MARIA_CHAT_MODEL", "fixture-local")
    monkeypatch.setattr(ui.module, "create_chat_backend", forbidden)
    import agent_core.llm.kritaqo_context as context
    monkeypatch.setattr(context, "create_kritaqo_context_provider", forbidden)
    monkeypatch.setattr(ui.module, "prepare_interactive_tools", forbidden)
    monkeypatch.setattr(ui.module, "interactive_tools_match", forbidden)
    _, ws = ui.client()
    connected = payloads(ws, "connected")[0]
    assert connected["chat_backend"] == {"provider": "ollama", "model": "fixture-local", "configured": True}
    brain = ui.module.get_maria_brain()
    assert brain.arguments["chat_backend"] is None
    assert brain.arguments["request_context_provider"] is None
    assert brain.arguments["verify_model"] is False
    assert "Tryb tylko rozmowy" in brain.history[0]["content"]
    ws.emit("chat_message", {"message": "Cześć Mario"})
    assert payloads(ws, "chat_response")[0]["message"] == brain.reply
    assert len(brain.calls) == 1


@pytest.mark.parametrize("text", [
    "naucz się astronomii", "przestań uczyć się astronomii",
    "pobierz nowe materiały", "Przygotuj raport projektu w Kritaqo",
    "Uruchom zadanie projektu", "Anuluj zadanie projektu",
    "Zleć pracę w Roblox", "Zleć raport przez Kritaqo", "Zapisz plik raport.txt",
])
def test_work_commands_explain_limitation_without_goals_or_model(ui, monkeypatch, text):
    monkeypatch.setenv("MARIA_CHAT_ONLY", "1")
    from agent_core.goals import store
    monkeypatch.setattr(store, "GoalStore", forbidden)
    monkeypatch.setattr(ui.module, "prepare_interactive_tools", forbidden)
    _, ws = ui.client()
    ws.get_received()
    brain = ui.module.get_maria_brain()
    ws.emit("chat_message", {"message": text})
    reply = payloads(ws, "chat_response")[0]
    assert reply["success"] and "tryb tylko rozmowy" in reply["message"]
    assert not brain.calls
    assert not (ui.tmp / "meta_data" / "goals.jsonl").exists()
    assert ui.module.get_ui_chat_history()[-1]["content"] == reply["message"]


@pytest.mark.parametrize("text", ["stwórz wiersz", "create a poem", "przygotuj plan"])
def test_chat_only_allows_in_chat_creative_and_planning_requests(ui, monkeypatch, text):
    monkeypatch.setenv("MARIA_CHAT_ONLY", "1")
    from agent_core.goals import store
    monkeypatch.setattr(store, "GoalStore", forbidden)
    _, ws = ui.client()
    ws.get_received()
    brain = ui.module.get_maria_brain()
    ws.emit("chat_message", {"message": text})
    assert payloads(ws, "chat_response")[0]["message"] == brain.reply
    assert brain.calls[0][0] == text


def test_model_response_never_enqueues_its_own_promised_action(ui, monkeypatch):
    monkeypatch.setenv("MARIA_CHAT_ONLY", "1")
    from agent_core.goals import store
    from agent_core.perception import maria_speech_intent
    monkeypatch.setattr(store, "GoalStore", forbidden)
    monkeypatch.setattr(maria_speech_intent, "detect_maria_intent", forbidden)
    _, ws = ui.client()
    ws.get_received()
    brain = ui.module.get_maria_brain()
    brain.reply = "Pobiorę nowe materiały z internetu."
    ws.emit("chat_message", {"message": "Porozmawiajmy o astronomii"})
    assert payloads(ws, "chat_response")[0]["success"]
    assert len(brain.calls) == 1


def test_chat_only_template_and_observer_do_not_initialize_work_service(ui, monkeypatch):
    monkeypatch.setenv("MARIA_CHAT_ONLY", "1")
    from agent_core.llm import kritaqo_work_service
    monkeypatch.setattr(kritaqo_work_service, "get_work_service", forbidden)
    monkeypatch.setattr(ui.module.threading, "Thread", forbidden)
    monkeypatch.setattr(ui.module, "render_template", lambda name, **kwargs: kwargs)
    http, ws = ui.client()
    assert ws.is_connected()
    assert http.get("/").json == {"active_page": "chat", "chat_only": True}
    assert ui.module._get_work_service() is None
    ui.module.start_notification_monitor()


def test_unset_keeps_codex_and_existing_operational_goal_path(ui, monkeypatch):
    monkeypatch.delenv("MARIA_CHAT_ONLY", raising=False)
    from agent_core.goals import store
    from agent_core.perception import learning_intent
    calls = []
    fake = SimpleNamespace(load=lambda: None, create=lambda goal: calls.append(goal), save=lambda: None)
    monkeypatch.setattr(store, "GoalStore", lambda **kwargs: fake)
    monkeypatch.setattr(learning_intent, "detect_learning_intent", lambda _: None)
    monkeypatch.setattr(learning_intent, "detect_cancel_intent", lambda _: None)
    monkeypatch.setattr(learning_intent, "detect_operational_intent", lambda _: {"action": "fetch"})
    _, ws = ui.client()
    assert payloads(ws, "connected")[0]["chat_backend"]["provider"] == "codex"
    brain = ui.module.get_maria_brain()
    assert brain.arguments["chat_backend"] is ui.sentinel
    ws.emit("chat_message", {"message": "pobierz nowe materiały"})
    assert payloads(ws, "chat_response")[0]["success"]
    assert len(calls) == 1
    assert calls[0].metadata["forced_action_type"] == "fetch"
    assert not brain.calls
