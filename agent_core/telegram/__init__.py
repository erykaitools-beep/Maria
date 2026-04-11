"""
Telegram integration for M.A.R.I.A.

Provides bidirectional communication with operator:
- Maria -> Eryk: alerts, tensions, recommendations, health drops
- Eryk -> Maria: commands (status, approve, reject)

Usage:
    from agent_core.telegram import TelegramBridge

    bridge = TelegramBridge()
    bridge.notify_startup()
    messages = bridge.poll()  # returns new messages from operator
"""

from agent_core.telegram.bot import TelegramBot
from agent_core.telegram.notifier import TelegramNotifier

__all__ = ["TelegramBot", "TelegramNotifier", "TelegramBridge"]


class TelegramBridge:
    """
    Facade combining TelegramBot + TelegramNotifier.

    Single entry point for homeostasis integration.
    Polls for operator messages and dispatches notifications.
    """

    def __init__(self, bot=None, notifier=None):
        self.bot = bot or TelegramBot()
        self.notifier = notifier or TelegramNotifier(self.bot)

        # Command handlers: command_text -> callable(args_text) -> response_text
        self._command_handlers = {}

        # Track operator messages for proactive contact module
        self.last_poll_message_count = 0

    @property
    def configured(self):
        return self.bot.configured

    def register_command(self, command, handler):
        """
        Register a command handler.

        Args:
            command: Command string (e.g. "status", "approve")
            handler: Callable(args_str) -> str (response text)
        """
        self._command_handlers[command.lower()] = handler

    def poll_and_respond(self):
        """
        Poll for new messages and handle commands.
        Supports file attachments with caption as command.

        Returns:
            List of unhandled messages (non-command texts).
        """
        if not self.configured:
            return []

        messages = self.bot.get_updates()
        self.last_poll_message_count = len(messages)
        unhandled = []

        for msg in messages:
            text = msg.get("text", "").strip()

            # Handle document with caption as command
            doc = msg.get("document")
            if doc and text:
                file_path = self._handle_document(doc, text)
                if file_path:
                    # Inject file path into command args
                    text = text + f" [plik: {file_path}]"

            if not text:
                if doc:
                    # Document without caption
                    file_path = self._handle_document(doc, "")
                    if file_path:
                        self.bot.send_message(
                            f"Plik zapisany: {file_path}\n"
                            f"Uzyj: /claude przeanalizuj {file_path}"
                        )
                continue

            # Parse command: first word is command, rest is args
            parts = text.split(None, 1)
            cmd = parts[0].lower().lstrip("/")
            args = parts[1] if len(parts) > 1 else ""

            handler = self._command_handlers.get(cmd)
            if handler:
                try:
                    response = handler(args)
                    if response:
                        self.bot.send_message(response)
                except Exception as e:
                    self.bot.send_message(f"Blad: {e}")
            else:
                unhandled.append(msg)

        return unhandled

    def _handle_document(self, doc: dict, caption: str) -> str:
        """Download document from Telegram and save to docs/incoming/.

        Returns local file path or empty string on failure.
        """
        import os
        file_id = doc.get("file_id", "")
        file_name = doc.get("file_name", "unknown")
        if not file_id:
            return ""

        # Only accept safe file types
        allowed_ext = {".pdf", ".md", ".txt", ".py", ".json", ".csv"}
        ext = os.path.splitext(file_name)[1].lower()
        if ext not in allowed_ext:
            self.bot.send_message(
                f"Nieobslugiwany typ pliku: {ext}\n"
                f"Dozwolone: {', '.join(sorted(allowed_ext))}"
            )
            return ""

        # Save to docs/incoming/
        from pathlib import Path
        incoming_dir = Path(__file__).resolve().parents[2] / "docs" / "incoming"
        incoming_dir.mkdir(parents=True, exist_ok=True)
        dest = str(incoming_dir / file_name)

        if self.bot.download_file(file_id, dest):
            return dest
        return ""

    def get_status(self):
        """Combined status from bot + notifier."""
        return {
            "bot": self.bot.get_status(),
            "notifier": self.notifier.get_status(),
        }
