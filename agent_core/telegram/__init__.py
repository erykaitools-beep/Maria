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

        Returns:
            List of unhandled messages (non-command texts).
        """
        if not self.configured:
            return []

        messages = self.bot.get_updates()
        unhandled = []

        for msg in messages:
            text = msg.get("text", "").strip()
            if not text:
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

    def get_status(self):
        """Combined status from bot + notifier."""
        return {
            "bot": self.bot.get_status(),
            "notifier": self.notifier.get_status(),
        }
