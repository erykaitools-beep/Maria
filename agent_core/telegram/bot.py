"""
Telegram Bot client for M.A.R.I.A.

Sends messages to operator and polls for incoming commands.
Uses Telegram Bot API directly via requests (zero extra deps).

Config: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from agent_core.telegram.outbox_store import TelegramOutboxStore

logger = logging.getLogger(__name__)

# Telegram Bot API base URL
_API_BASE = "https://api.telegram.org/bot{token}/{method}"

# Timeouts for HTTP calls (connect, read)
_TIMEOUT = (5, 10)

# Max message length (Telegram limit)
MAX_MESSAGE_LENGTH = 4096


def _parse_chat_id(raw: Optional[str]) -> int:
    """Parse a Telegram chat id from env, tolerating empty/garbage values.

    int("") and int("notanumber") raise ValueError; an unset or malformed
    TELEGRAM_CHAT_ID must degrade to 0 ("not configured"), never crash the
    TelegramBot constructor -- which runs at wiring time outside any
    try/except. Keeps negative ids (Telegram group/supergroup chats are
    negative, e.g. -1001234567890).
    """
    try:
        return int((raw or "").strip())
    except (TypeError, ValueError):
        return 0


class TelegramBot:
    """
    Low-level Telegram Bot API client.

    Handles send_message and getUpdates polling.
    Token and chat_id loaded from env vars or passed directly.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        chat_id: Optional[int] = None,
        outbox_path: Optional[Path] = None,
        outbox_store: Optional[TelegramOutboxStore] = None,
    ):
        self._token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = chat_id or _parse_chat_id(os.environ.get("TELEGRAM_CHAT_ID", "0"))
        self._last_update_id: int = 0
        self._outbox = outbox_store or TelegramOutboxStore(outbox_path)

    @property
    def configured(self) -> bool:
        """Check if bot has valid token and chat_id."""
        return bool(self._token) and self._chat_id != 0

    def flush_pending(self) -> None:
        """Skip all pending updates (call on startup to avoid re-processing old commands)."""
        if not self.configured:
            return
        try:
            resp = requests.get(
                self._api_url("getUpdates"),
                params={"offset": -1, "limit": 1, "timeout": 0},
                timeout=(5, 5),
            )
            data = resp.json()
            results = data.get("result", [])
            if results:
                self._last_update_id = results[-1].get("update_id", 0)
                logger.debug(f"TelegramBot: flushed pending, offset now {self._last_update_id}")
        except Exception as e:
            logger.debug(f"TelegramBot: flush error: {e}")

    def _api_url(self, method: str) -> str:
        return _API_BASE.format(token=self._token, method=method)

    def send_message(
        self,
        text: str,
        parse_mode: Optional[str] = "Markdown",
        chat_id: Optional[int] = None,
    ) -> bool:
        """
        Send a text message to the operator.

        Args:
            text: Message text (max 4096 chars, will be truncated)
            parse_mode: Telegram parse mode (Markdown, HTML, None)
            chat_id: Override default chat_id

        Returns:
            True if sent successfully, False otherwise.
        """
        target = chat_id or self._chat_id
        if not self.configured:
            logger.warning("TelegramBot: not configured (missing token or chat_id)")
            self._record_outbox(
                kind="send_message",
                success=False,
                chat_id=target,
                text=text,
                parse_mode=parse_mode,
                error="not_configured",
            )
            return False

        # Truncate if needed
        if len(text) > MAX_MESSAGE_LENGTH:
            text = text[:MAX_MESSAGE_LENGTH - 20] + "\n\n[...obcieto]"

        payload = {
            "chat_id": target,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            resp = requests.post(
                self._api_url("sendMessage"),
                json=payload,
                timeout=_TIMEOUT,
            )
            data = resp.json()
            if data.get("ok"):
                logger.debug(f"TelegramBot: message sent ({len(text)} chars)")
                self._record_outbox(
                    kind="send_message",
                    success=True,
                    chat_id=target,
                    text=text,
                    parse_mode=parse_mode,
                    telegram_message_id=_message_id(data),
                )
                return True
            else:
                retry = ""
                # Retry without parse_mode if Markdown fails
                if parse_mode and "parse" in str(data.get("description", "")).lower():
                    logger.debug("TelegramBot: Markdown failed, retrying plain text")
                    retry = "markdown_fallback"
                    payload.pop("parse_mode", None)
                    resp2 = requests.post(
                        self._api_url("sendMessage"),
                        json=payload,
                        timeout=_TIMEOUT,
                    )
                    data2 = resp2.json()
                    if data2.get("ok"):
                        self._record_outbox(
                            kind="send_message",
                            success=True,
                            chat_id=target,
                            text=text,
                            parse_mode=None,
                            telegram_message_id=_message_id(data2),
                            retry=retry,
                        )
                        return True
                    data = data2
                error = str(data.get("description", "send_failed"))
                logger.warning(f"TelegramBot: send failed: {error}")
                self._record_outbox(
                    kind="send_message",
                    success=False,
                    chat_id=target,
                    text=text,
                    parse_mode=parse_mode,
                    error=error,
                    retry=retry,
                )
                return False
        except requests.RequestException as e:
            logger.warning(f"TelegramBot: request error: {e}")
            self._record_outbox(
                kind="send_message",
                success=False,
                chat_id=target,
                text=text,
                parse_mode=parse_mode,
                error=str(e),
            )
            return False

    def send_document(
        self,
        file_path: str,
        caption: Optional[str] = None,
        chat_id: Optional[int] = None,
    ) -> bool:
        """
        Send a document (file) to the operator.

        Args:
            file_path: Local path to the file to send
            caption: Optional caption (max 1024 chars)
            chat_id: Override default chat_id

        Returns:
            True if sent successfully, False otherwise.
        """
        target = chat_id or self._chat_id
        if not self.configured:
            self._record_outbox(
                kind="send_document",
                success=False,
                chat_id=target,
                text=caption,
                file_path=file_path,
                error="not_configured",
            )
            return False

        caption_to_send = caption[:1024] if caption else None

        try:
            with open(file_path, "rb") as f:
                data = {"chat_id": target}
                if caption_to_send:
                    data["caption"] = caption_to_send
                resp = requests.post(
                    self._api_url("sendDocument"),
                    data=data,
                    files={"document": f},
                    timeout=(5, 30),
                )
            result = resp.json()
            if result.get("ok"):
                logger.debug("TelegramBot: document sent: %s", file_path)
                self._record_outbox(
                    kind="send_document",
                    success=True,
                    chat_id=target,
                    text=caption_to_send,
                    file_path=file_path,
                    telegram_message_id=_message_id(result),
                )
                return True
            error = str(result.get("description", "send_document_failed"))
            logger.warning("TelegramBot: sendDocument failed: %s", error)
            self._record_outbox(
                kind="send_document",
                success=False,
                chat_id=target,
                text=caption_to_send,
                file_path=file_path,
                error=error,
            )
            return False
        except Exception as e:
            logger.warning("TelegramBot: sendDocument error: %s", e)
            self._record_outbox(
                kind="send_document",
                success=False,
                chat_id=target,
                text=caption_to_send,
                file_path=file_path,
                error=str(e),
            )
            return False

    def get_updates(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Poll for new messages from operator.

        Uses long polling with offset to avoid re-reading old messages.

        Returns:
            List of message dicts: [{"text": ..., "from": ..., "date": ...}]
        """
        if not self.configured:
            return []

        # P3 fix 2026-05-08: was timeout=1 (long-poll) + HTTP (5,5).
        # Long-polling held the main tick thread for ~1s on every poll
        # (we already poll every 30s so long-polling adds no value here).
        # Now: instant-return poll + tighter HTTP timeout to keep tick budget.
        params = {
            "offset": self._last_update_id + 1,
            "limit": limit,
            "timeout": 0,  # Instant return; we poll every 30s anyway.
        }

        try:
            resp = requests.get(
                self._api_url("getUpdates"),
                params=params,
                timeout=(3, 3),
            )
            data = resp.json()
            if not data.get("ok"):
                return []

            messages = []
            for update in data.get("result", []):
                update_id = update.get("update_id", 0)
                if update_id > self._last_update_id:
                    self._last_update_id = update_id

                msg = update.get("message", {})
                text = msg.get("text", "") or msg.get("caption", "")
                entry = {
                    "text": text,
                    "from": msg.get("from", {}).get("username", "unknown"),
                    "chat_id": msg.get("chat", {}).get("id", 0),
                    "date": msg.get("date", 0),
                    "message_id": msg.get("message_id", 0),
                }

                # Handle file attachments (document, photo)
                doc = msg.get("document")
                if doc:
                    entry["document"] = {
                        "file_id": doc.get("file_id", ""),
                        "file_name": doc.get("file_name", "unknown"),
                        "mime_type": doc.get("mime_type", ""),
                        "file_size": doc.get("file_size", 0),
                    }

                if text or doc:
                    messages.append(entry)

            return messages
        except requests.RequestException as e:
            logger.debug(f"TelegramBot: poll error: {e}")
            return []

    def download_file(self, file_id: str, dest_path: str) -> bool:
        """
        Download a file from Telegram servers.

        Args:
            file_id: Telegram file_id from document message
            dest_path: Local path to save the file

        Returns:
            True if downloaded successfully.
        """
        if not self.configured:
            return False

        try:
            # Step 1: get file path from Telegram
            resp = requests.get(
                self._api_url("getFile"),
                params={"file_id": file_id},
                timeout=_TIMEOUT,
            )
            data = resp.json()
            if not data.get("ok"):
                logger.warning("TelegramBot: getFile failed: %s", data.get("description"))
                return False

            file_path = data["result"].get("file_path", "")
            if not file_path:
                return False

            # Step 2: download file content
            file_url = f"https://api.telegram.org/file/bot{self._token}/{file_path}"
            file_resp = requests.get(file_url, timeout=(5, 30))
            if file_resp.status_code != 200:
                return False

            # Step 3: save to dest
            from pathlib import Path
            Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(file_resp.content)

            logger.info("TelegramBot: downloaded %s -> %s (%d bytes)",
                        file_id[:12], dest_path, len(file_resp.content))
            return True

        except Exception as e:
            logger.warning("TelegramBot: download error: %s", e)
            return False

    def get_status(self) -> Dict[str, Any]:
        """Status info for diagnostics."""
        return {
            "configured": self.configured,
            "chat_id": self._chat_id,
            "last_update_id": self._last_update_id,
        }

    def _record_outbox(
        self,
        *,
        kind: str,
        success: bool,
        chat_id: int,
        text: Optional[str] = None,
        parse_mode: Optional[str] = None,
        telegram_message_id: Optional[int] = None,
        file_path: str = "",
        error: str = "",
        retry: str = "",
    ) -> None:
        metadata: Dict[str, Any] = {}
        if parse_mode:
            metadata["parse_mode"] = parse_mode
        if retry:
            metadata["retry"] = retry
        self._outbox.record_attempt(
            kind=kind,
            success=success,
            chat_id=chat_id,
            text=text,
            telegram_message_id=telegram_message_id,
            file_path=file_path,
            error=error,
            metadata=metadata,
        )


def _message_id(data: Dict[str, Any]) -> Optional[int]:
    result = data.get("result")
    if isinstance(result, dict):
        message_id = result.get("message_id")
        if isinstance(message_id, int):
            return message_id
    return None
