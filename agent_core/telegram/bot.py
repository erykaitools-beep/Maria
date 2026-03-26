"""
Telegram Bot client for M.A.R.I.A.

Sends messages to operator and polls for incoming commands.
Uses Telegram Bot API directly via requests (zero extra deps).

Config: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Telegram Bot API base URL
_API_BASE = "https://api.telegram.org/bot{token}/{method}"

# Timeouts for HTTP calls (connect, read)
_TIMEOUT = (5, 10)

# Max message length (Telegram limit)
MAX_MESSAGE_LENGTH = 4096


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
    ):
        self._token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = chat_id or int(os.environ.get("TELEGRAM_CHAT_ID", "0"))
        self._last_update_id: int = 0

    @property
    def configured(self) -> bool:
        """Check if bot has valid token and chat_id."""
        return bool(self._token) and self._chat_id != 0

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
        if not self.configured:
            logger.warning("TelegramBot: not configured (missing token or chat_id)")
            return False

        target = chat_id or self._chat_id

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
                return True
            else:
                # Retry without parse_mode if Markdown fails
                if parse_mode and "parse" in str(data.get("description", "")).lower():
                    logger.debug("TelegramBot: Markdown failed, retrying plain text")
                    payload.pop("parse_mode", None)
                    resp2 = requests.post(
                        self._api_url("sendMessage"),
                        json=payload,
                        timeout=_TIMEOUT,
                    )
                    data2 = resp2.json()
                    if data2.get("ok"):
                        return True
                logger.warning(f"TelegramBot: send failed: {data.get('description')}")
                return False
        except requests.RequestException as e:
            logger.warning(f"TelegramBot: request error: {e}")
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

        params = {
            "offset": self._last_update_id + 1,
            "limit": limit,
            "timeout": 1,  # Short poll (called from tick loop)
        }

        try:
            resp = requests.get(
                self._api_url("getUpdates"),
                params=params,
                timeout=(5, 5),
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
                text = msg.get("text", "")
                if text:
                    messages.append({
                        "text": text,
                        "from": msg.get("from", {}).get("username", "unknown"),
                        "chat_id": msg.get("chat", {}).get("id", 0),
                        "date": msg.get("date", 0),
                        "message_id": msg.get("message_id", 0),
                    })

            return messages
        except requests.RequestException as e:
            logger.debug(f"TelegramBot: poll error: {e}")
            return []

    def get_status(self) -> Dict[str, Any]:
        """Status info for diagnostics."""
        return {
            "configured": self.configured,
            "chat_id": self._chat_id,
            "last_update_id": self._last_update_id,
        }
