"""Paused autonomous reasoning must not disable explicit local conversation."""
from threading import Event
from types import SimpleNamespace

import pytest

from agent_core.llm.local_compute import LocalComputeBlocked, LocalComputeCoordinator
from agent_core.llm.work_priority import WorkPurpose, current_work_purpose, work_purpose


@pytest.mark.parametrize("kind", ["text", "embedding", "vision"])
@pytest.mark.parametrize("purpose", [None, *WorkPurpose])
@pytest.mark.parametrize("provider", [None, "ollama", "codex", "typo"])
@pytest.mark.parametrize("chat_only", [None, "0", "1"])
def test_pause_admits_only_interactive_text_and_embeddings(monkeypatch, kind, purpose, provider, chat_only):
    monkeypatch.setenv("MARIA_BACKGROUND_REASONING", "0")
    monkeypatch.delenv("MARIA_CHAT_BACKEND", raising=False)
    monkeypatch.delenv("MARIA_CHAT_ONLY", raising=False)
    if provider is not None:
        monkeypatch.setenv("MARIA_CHAT_BACKEND", provider)
    if chat_only is not None:
        monkeypatch.setenv("MARIA_CHAT_ONLY", chat_only)
    coordinator = LocalComputeCoordinator()

    def attempt():
        if purpose == WorkPurpose.INTERACTION and (
            kind == "embedding" or (kind == "text" and (chat_only == "1" or provider in {None, "ollama"}))
        ):
            with coordinator.lease(kind, timeout_s=0.1):
                assert coordinator.snapshot()["active_kind"] == kind
        else:
            with pytest.raises(LocalComputeBlocked, match="paused"):
                with coordinator.lease(kind, timeout_s=0.1):
                    pytest.fail("paused work was admitted")

    if purpose is None:
        attempt()
    else:
        with work_purpose(purpose):
            attempt()
    assert current_work_purpose() is None


def test_actual_chat_transport_is_lazy_and_uses_interaction_scope(monkeypatch):
    from models import ollama_brain

    monkeypatch.setenv("MARIA_BACKGROUND_REASONING", "0")
    monkeypatch.setenv("MARIA_CHAT_BACKEND", "ollama")
    coordinator = LocalComputeCoordinator()
    monkeypatch.setattr(ollama_brain, "get_local_compute_coordinator", lambda: coordinator)
    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        assert current_work_purpose() == WorkPurpose.INTERACTION
        return {"message": {"content": "Odpowiedź"}}

    brain = ollama_brain.OllamaBrain.__new__(ollama_brain.OllamaBrain)
    brain.model = "fixture-chat"
    brain._client = SimpleNamespace(chat=chat)
    assert calls == []  # Creating the compute gate does not warm a model.
    messages = [{"role": "user", "content": "Cześć"}]
    with pytest.raises(LocalComputeBlocked, match="paused"):
        brain._chat(messages)
    assert calls == []
    # Same ContextVar scope as maria_ui.app._serialize_chat_turn.
    with work_purpose(WorkPurpose.INTERACTION):
        assert brain._chat(messages) == "Odpowiedź"
    assert len(calls) == 1
    assert calls[0]["model"] == "fixture-chat"


@pytest.mark.parametrize("guard", ["thermal", "cancelled", "budget"])
def test_interactive_text_keeps_existing_safety_guards(monkeypatch, guard):
    monkeypatch.setenv("MARIA_BACKGROUND_REASONING", "0")
    monkeypatch.setenv("MARIA_CHAT_BACKEND", "ollama")
    coordinator = LocalComputeCoordinator()
    cancelled = Event()
    if guard == "thermal":
        coordinator.enter_cooling(85)
    elif guard == "cancelled":
        cancelled.set()
    else:
        coordinator._slot.acquire()
    try:
        with work_purpose(WorkPurpose.INTERACTION):
            with pytest.raises(LocalComputeBlocked, match={
                "thermal": "cooling", "cancelled": "cancelled", "budget": "timeout",
            }[guard]):
                with coordinator.lease("text", timeout_s=0.01, cancel_event=cancelled):
                    pytest.fail("safety guard was bypassed")
    finally:
        if guard == "budget":
            coordinator._slot.release()
