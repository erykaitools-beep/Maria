"""Atomic TASK_BOARD.md echo for self-repair tasks."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from zoneinfo import ZoneInfo

logger = logging.getLogger("agent_core.self_repair")


class TaskBoardWriter:
    """Append repair task visibility entries to the orchestration board."""

    _lock = threading.Lock()

    def __init__(
        self,
        board_path: Path = Path("docs/orchestration/TASK_BOARD.md"),
    ):
        self._board_path = board_path

    def append_repair_entry(
        self,
        task_id: str,
        title: str,
        repair_kind: str,
        evidence_summary: Dict[str, Any],
        expires_at: float,
    ) -> bool:
        """Atomic append. Returns False when the Open tasks marker is absent."""
        with self._lock:
            try:
                text = self._board_path.read_text(encoding="utf-8")
            except OSError:
                logger.warning("[SelfRepair] TASK_BOARD read failed", exc_info=True)
                return False

            marker = "## Open tasks"
            marker_index = text.find(marker)
            if marker_index < 0:
                logger.warning("[SelfRepair] TASK_BOARD marker not found: %s", marker)
                return False

            insert_at = text.find("\n### ", marker_index)
            if insert_at < 0:
                insert_at = len(text)
            else:
                insert_at += 1

            entry = self._format_entry(
                task_id=task_id,
                title=title,
                repair_kind=repair_kind,
                evidence_summary=evidence_summary,
                expires_at=expires_at,
            )
            new_text = text[:insert_at] + entry + text[insert_at:]
            tmp_path = self._board_path.with_suffix(self._board_path.suffix + ".tmp")
            try:
                tmp_path.write_text(new_text, encoding="utf-8")
                os.replace(tmp_path, self._board_path)
            except OSError:
                logger.warning("[SelfRepair] TASK_BOARD write failed", exc_info=True)
                return False
            return True

    def _format_entry(
        self,
        task_id: str,
        title: str,
        repair_kind: str,
        evidence_summary: Dict[str, Any],
        expires_at: float,
    ) -> str:
        short_id = task_id[-4:]
        created = _berlin_datetime(datetime.now().timestamp()).strftime(
            "%Y-%m-%d %H:%M Berlin"
        )
        expires = datetime.fromtimestamp(expires_at).replace(microsecond=0).isoformat()
        evidence = _one_line_evidence(evidence_summary)
        return (
            f"### T-REPAIR-{short_id} — {title} [PENDING — operator gate]\n"
            f"- **Status:** pending (created by maria_self_diagnosis {created})\n"
            "- **Owner:** codex (autonomous after /approve_repair)\n"
            f"- **Repair kind:** {repair_kind}\n"
            f"- **Conductor task_id:** {task_id}\n"
            f"- **Evidence:** {evidence}\n"
            f"- **Expires:** {expires}\n"
            f"- **Approve:** `/approve_repair {task_id}` (Telegram)\n\n"
        )


def _one_line_evidence(evidence_summary: Dict[str, Any]) -> str:
    if "one_line" in evidence_summary:
        return str(evidence_summary["one_line"])[:240]
    return str(evidence_summary)[:240]


def _berlin_datetime(timestamp: float) -> datetime:
    try:
        return datetime.fromtimestamp(timestamp, ZoneInfo("Europe/Berlin"))
    except Exception:
        return datetime.fromtimestamp(timestamp)
