"""
User Adapter - mapuje REPL/WebUI input na PerceptionEvent.

Obsluguje:
- user_message - zwykla wiadomosc tekstowa
- user_command - komenda REPL (np. /learn, /homeostasis)

Kontrakt: docs/CONTRACTS.md - Event Type Registry
"""

from typing import Optional

from agent_core.perception.event import (
    PerceptionEvent,
    PerceptionSource,
    create_event,
)


class UserAdapter:
    """Konwertuje user input na PerceptionEvent."""

    @staticmethod
    def from_message(
        text: str,
        channel: str = "repl",
        user_id: Optional[str] = None,
        parent_event_id: Optional[str] = None,
    ) -> PerceptionEvent:
        """
        Wiadomosc tekstowa -> PerceptionEvent(user_message).

        Args:
            text: Tresc wiadomosci
            channel: Kanal ("repl", "webui")
            user_id: opcjonalny identyfikator uzytkownika
            parent_event_id: opcjonalny event_id przyczyny
        """
        payload = {
            "text": text,
            "channel": channel,
        }
        if user_id is not None:
            payload["user_id"] = user_id

        return create_event(
            source=PerceptionSource.USER,
            event_type="user_message",
            payload=payload,
            parent_event_id=parent_event_id,
        )

    @staticmethod
    def from_command(
        command: str,
        args: str = "",
        channel: str = "repl",
        parent_event_id: Optional[str] = None,
    ) -> PerceptionEvent:
        """
        Komenda REPL -> PerceptionEvent(user_command).

        Args:
            command: Nazwa komendy (np. "/learn", "/homeostasis")
            args: Argumenty komendy
            channel: Kanal ("repl", "webui")
            parent_event_id: opcjonalny event_id przyczyny
        """
        payload = {
            "command": command,
            "args": args,
        }
        if channel != "repl":
            payload["channel"] = channel

        return create_event(
            source=PerceptionSource.USER,
            event_type="user_command",
            payload=payload,
            parent_event_id=parent_event_id,
        )
