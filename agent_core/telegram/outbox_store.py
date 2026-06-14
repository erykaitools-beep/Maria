"""
Telegram outbox proof-of-delivery log.

Append-only JSONL: meta_data/telegram_outbox.jsonl.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_OUTBOX_PATH = (
    Path(__file__).resolve().parents[2] / "meta_data" / "telegram_outbox.jsonl"
)
PREVIEW_CHARS = 500


@dataclass
class TelegramOutboxRecord:
    outbox_id: str
    ts: float
    channel: str
    kind: str
    status: str
    success: bool
    chat_id: int
    text_preview: str = ""
    text_sha256: str = ""
    text_len: int = 0
    telegram_message_id: Optional[int] = None
    file_path: str = ""
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TelegramOutboxRecord":
        return cls(
            outbox_id=data.get("outbox_id", ""),
            ts=float(data.get("ts", 0.0)),
            channel=data.get("channel", "telegram"),
            kind=data.get("kind", ""),
            status=data.get("status", ""),
            success=bool(data.get("success", False)),
            chat_id=int(data.get("chat_id", 0) or 0),
            text_preview=data.get("text_preview", ""),
            text_sha256=data.get("text_sha256", ""),
            text_len=int(data.get("text_len", 0) or 0),
            telegram_message_id=data.get("telegram_message_id"),
            file_path=data.get("file_path", ""),
            error=data.get("error", ""),
            metadata=data.get("metadata", {}) or {},
        )


class TelegramOutboxStore:
    """Small append-only JSONL writer for outgoing Telegram attempts."""

    _lock = threading.Lock()

    def __init__(self, path: Optional[Path] = None):
        self._path = path or DEFAULT_OUTBOX_PATH

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: TelegramOutboxRecord) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record.to_dict(), ensure_ascii=False)
            with self._lock:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError as exc:
            logger.warning("Telegram outbox write failed: %s", exc)

    def record_attempt(
        self,
        *,
        kind: str,
        success: bool,
        chat_id: int,
        text: Optional[str] = None,
        telegram_message_id: Optional[int] = None,
        file_path: str = "",
        error: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TelegramOutboxRecord:
        record = TelegramOutboxRecord(
            outbox_id=f"tgo-{uuid.uuid4().hex[:12]}",
            ts=time.time(),
            channel="telegram",
            kind=kind,
            status="sent" if success else "failed",
            success=success,
            chat_id=int(chat_id or 0),
            text_preview=_preview(text),
            text_sha256=_sha256(text),
            text_len=len(text or ""),
            telegram_message_id=telegram_message_id,
            file_path=file_path,
            error=error,
            metadata=metadata or {},
        )
        self.append(record)
        return record

    def tail(self, limit: int = 100) -> list[TelegramOutboxRecord]:
        if not self._path.exists():
            return []
        out: list[TelegramOutboxRecord] = []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(TelegramOutboxRecord.from_dict(json.loads(line)))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
        except OSError as exc:
            logger.warning("Telegram outbox read failed: %s", exc)
            return []
        return out[-limit:]


def _preview(text: Optional[str]) -> str:
    if not text:
        return ""
    return text[:PREVIEW_CHARS]


def _sha256(text: Optional[str]) -> str:
    if text is None:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
