"""
Telegram integration for M.A.R.I.A.

Provides bidirectional communication with operator:
- Maria -> Operator: alerts, tensions, recommendations, health drops
- Operator -> Maria: commands (status, approve, reject)

Usage:
    from agent_core.telegram import TelegramBridge

    bridge = TelegramBridge()
    bridge.notify_startup()
    messages = bridge.poll()  # returns new messages from operator
"""

import logging
import threading

from agent_core.telegram.bot import TelegramBot
from agent_core.telegram.notifier import TelegramNotifier

logger = logging.getLogger(__name__)

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
        # Last poll raw texts (for OperatorModel learning)
        self.last_poll_texts = []

        # Optional fallback for plain (non-slash) operator text -> Maria's chat
        # brain. None = historical "command console" behaviour (free-text gets no
        # reply). Installed by register_telegram_commands when TELEGRAM_CHAT_ENABLED.
        self._chat_handler = None
        # Chat replies run on detached threads so a slow (cold-CPU, up to ~240s)
        # brain reply never blocks the single poll loop -- otherwise the is_alive
        # guard in the tick suppresses ALL subsequent polls and even slash commands
        # stall. One reply composed at a time (the brain history is shared).
        self._chat_lock = threading.Lock()
        self._last_chat_thread = None  # for tests to join
        self._last_file_thread = None  # for tests to join (file-delivery dispatch)

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

    def set_chat_handler(self, handler):
        """Install the plain-text fallback: a callable(text) -> reply_text routed
        to Maria's chat brain. Without it, non-command messages are still consumed
        for OperatorModel learning but get no reply (the command-console default).
        Only plain (non-slash) text reaches it; slash commands stay untouched.
        """
        self._chat_handler = handler

    def _dispatch_chat_reply(self, text):
        """Answer plain text on a detached daemon thread, so a slow brain reply
        never blocks the poll loop (and thus never stalls slash-command intake).
        Replies serialize under _chat_lock so the shared brain history isn't raced
        and the cold CPU isn't piled on. Failures degrade to a soft 'busy' line."""
        handler = self._chat_handler
        if handler is None:  # defensive: never spawn a worker for a missing handler
            return

        def _worker():
            with self._chat_lock:
                try:
                    reply = handler(text)
                except Exception as e:
                    logger.warning("Telegram chat handler failed: %s", e)
                    reply = None
                if reply:
                    # Compose bridge: a "write X and send it as a file" request
                    # gets the reply written to a real file + sent for real; any
                    # phantom /wyslij Maria invents is stripped (2026-06-22).
                    try:
                        from agent_core.telegram.compose_bridge import (
                            maybe_deliver_compose,
                        )
                        reply = maybe_deliver_compose(
                            text, reply, send_document=self.bot.send_document,
                        )
                    except Exception as e:
                        logger.warning("Telegram compose bridge failed: %s", e)
                try:
                    self.bot.send_message(
                        reply or "Jestem teraz zajeta, sprobuj za chwile."
                    )
                except Exception as e:
                    logger.warning("Telegram chat send failed: %s", e)

        t = threading.Thread(target=_worker, daemon=True, name="TelegramChatReply")
        self._last_chat_thread = t
        t.start()

    def _dispatch_file_request(self, fr):
        """Fulfil a detected file-delivery request on a detached thread (a 30s
        upload must never block the poll loop). 'send' actually delivers the
        whitelisted document via the bot; 'redirect' replies with honest guidance
        (the /wyslij command) instead of letting the chat brain confabulate that
        it sent a file -- the 2026-06-22 morning failure. Serialized under
        _chat_lock so it cannot race the chat brain / pile on the cold CPU."""
        def _worker():
            with self._chat_lock:
                try:
                    if fr.kind == "send" and fr.path:
                        ok = self.bot.send_document(
                            fr.path, caption=(fr.message or "")[:1024]
                        )
                        if not ok:
                            self.bot.send_message(
                                "Nie udalo sie wyslac pliku (blad Telegrama)."
                            )
                    else:
                        self.bot.send_message(fr.message)
                except Exception as e:
                    logger.warning("Telegram file-request dispatch failed: %s", e)

        t = threading.Thread(target=_worker, daemon=True, name="TelegramFileSend")
        self._last_file_thread = t
        t.start()

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
        self.last_poll_texts = []
        unhandled = []

        # Security: only the configured master chat may drive the bot. Without
        # this, poll_and_respond dispatched every command for any sender, so
        # anyone who messaged the bot could run /restart, /do, /codex, etc.
        # (replies only ever went to the master chat anyway). master_active is
        # False when no numeric master is configured (mock bots in tests /
        # unconfigured) -> no gating; production always has a real int chat_id
        # because poll returns early above when the bot is not configured.
        master = getattr(self.bot, "_chat_id", 0)
        master_active = isinstance(master, int) and master != 0

        for msg in messages:
            if master_active and msg.get("chat_id") != master:
                logger.warning(
                    "Telegram: ignored message from non-master chat %s",
                    msg.get("chat_id"),
                )
                continue
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
                # Unknown SLASH command -> tell the operator instead of silently
                # dropping it. A /teacher or /task typo used to look like a no-op
                # (the message was consumed, fed to OperatorModel, no reply) which
                # cost trust + session time. Plain (non-slash) text is genuine
                # chat/intent -> still flows to `unhandled` unchanged.
                if text.startswith("/"):
                    self.bot.send_message(
                        f"Nieznana komenda: /{cmd}. Wyslij /help po liste komend."
                    )
                elif self._chat_handler is not None and not doc:
                    # Plain (non-slash) text = genuine chat -> Maria's brain, on a
                    # detached thread so a slow reply never blocks the poll loop
                    # (and thus never stalls slash-command intake). Documents are
                    # excluded: their caption carries an injected "[plik: ...]"
                    # token meant for /claude-style flows, not a chat prompt.
                    #
                    # First, a conservative check: if this is a "send me file X"
                    # request, fulfil it for real (or redirect to /wyslij) instead
                    # of letting the brain confabulate "przesylam plik..." for a
                    # file it cannot send -- the 2026-06-22 morning failure.
                    fr = None
                    try:
                        from agent_core.telegram.doc_sender import detect_file_request
                        fr = detect_file_request(text)
                    except Exception as e:
                        logger.warning("Telegram file-request detect failed: %s", e)
                    if fr is not None:
                        self._dispatch_file_request(fr)
                    else:
                        self._dispatch_chat_reply(text)
                unhandled.append(msg)
                self.last_poll_texts.append(text)

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
