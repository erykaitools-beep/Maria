"""
Cognitive Bulletin Board - JSONL-backed store.

Persistence: meta_data/cognitive_bulletin.jsonl (MERGE semantics on entry_id).
In-memory dict for fast lookups, lazy-loaded on first access.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.bulletin.bulletin_model import (
    BulletinEntry,
    EntryType,
    EntryStatus,
    TERMINAL_STATUSES,
    MAX_ENTRIES,
    STALE_TIMEOUT_SEC,
    create_entry,
)

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "meta_data" / "cognitive_bulletin.jsonl"


class BulletinStore:
    """JSONL-backed store for cognitive bulletin entries."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _DEFAULT_PATH
        self._entries: Optional[Dict[str, BulletinEntry]] = None

    # --- Load / Save ---

    def _ensure_loaded(self) -> None:
        if self._entries is not None:
            return
        self._entries = {}
        if not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        entry = BulletinEntry.from_dict(d)
                        self._entries[entry.entry_id] = entry  # MERGE
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.warning(
                            "Skipping corrupted JSONL line in %s (line %s): %s",
                            self._path,
                            line_no,
                            e,
                        )
        except OSError as e:
            logger.error(f"[BULLETIN] Cannot read {self._path}: {e}")

    def _append(self, entry: BulletinEntry) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except OSError as e:
            logger.error(f"[BULLETIN] Cannot write {self._path}: {e}")

    # --- CRUD ---

    def post(self, entry: BulletinEntry) -> None:
        """Add or update an entry on the board."""
        self._ensure_loaded()
        assert self._entries is not None
        self._entries[entry.entry_id] = entry
        self._append(entry)
        logger.info(
            f"[BULLETIN] Posted: {entry.entry_id} "
            f"type={entry.entry_type.value} topic={entry.topic!r}"
        )

    def create_and_post(
        self,
        entry_type: EntryType,
        topic: str,
        reason_code: str,
        summary: str,
        requested_by: str,
        goal_id: Optional[str] = None,
        priority: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BulletinEntry:
        """Create a new entry and post it. Returns the entry."""
        # Dedup: don't create if open entry for same topic+type exists
        existing = self.find_open(topic=topic, entry_type=entry_type)
        if existing:
            logger.debug(
                f"[BULLETIN] Dedup: open entry already exists for "
                f"topic={topic!r} type={entry_type.value}"
            )
            return existing[0]

        entry = create_entry(
            entry_type=entry_type,
            topic=topic,
            reason_code=reason_code,
            summary=summary,
            requested_by=requested_by,
            goal_id=goal_id,
            priority=priority,
            metadata=metadata,
        )
        self.post(entry)
        return entry

    def get(self, entry_id: str) -> Optional[BulletinEntry]:
        """Get entry by ID."""
        self._ensure_loaded()
        assert self._entries is not None
        return self._entries.get(entry_id)

    def update_status(
        self, entry_id: str, status: EntryStatus, reason: str = ""
    ) -> bool:
        """Update status of an entry. Returns True if found."""
        self._ensure_loaded()
        assert self._entries is not None
        entry = self._entries.get(entry_id)
        if entry is None:
            return False
        entry.status = status
        entry.updated_at = time.time()
        if reason:
            entry.metadata["last_status_reason"] = reason
        self._append(entry)  # MERGE on next load
        logger.info(
            f"[BULLETIN] Status update: {entry_id} -> {status.value}"
            + (f" ({reason})" if reason else "")
        )
        return True

    def resolve(self, entry_id: str, reason: str = "completed") -> bool:
        """Mark entry as resolved."""
        return self.update_status(entry_id, EntryStatus.RESOLVED, reason)

    # --- Queries ---

    def get_open(self) -> List[BulletinEntry]:
        """All non-resolved entries, sorted by priority descending."""
        self._ensure_loaded()
        assert self._entries is not None
        entries = [
            e for e in self._entries.values()
            if e.status not in TERMINAL_STATUSES
        ]
        entries.sort(key=lambda e: e.priority, reverse=True)
        return entries

    def get_by_type(self, entry_type: EntryType) -> List[BulletinEntry]:
        """All open entries of a given type."""
        return [e for e in self.get_open() if e.entry_type == entry_type]

    def get_actionable(self) -> List[BulletinEntry]:
        """Entries that planner can act on (OPEN or IN_PROGRESS, not BLOCKED)."""
        return [
            e for e in self.get_open()
            if e.status in (EntryStatus.OPEN, EntryStatus.IN_PROGRESS)
        ]

    def find_open(
        self,
        topic: Optional[str] = None,
        entry_type: Optional[EntryType] = None,
        goal_id: Optional[str] = None,
    ) -> List[BulletinEntry]:
        """Find open entries matching filters."""
        results = self.get_open()
        if topic is not None:
            topic_lower = topic.lower()
            results = [e for e in results if topic_lower in e.topic.lower()]
        if entry_type is not None:
            results = [e for e in results if e.entry_type == entry_type]
        if goal_id is not None:
            results = [e for e in results if e.goal_id == goal_id]
        return results

    def get_for_goal(self, goal_id: str) -> List[BulletinEntry]:
        """All entries linked to a specific goal."""
        self._ensure_loaded()
        assert self._entries is not None
        return [
            e for e in self._entries.values()
            if e.goal_id == goal_id
        ]

    # --- Maintenance ---

    def prune_stale(self, now: Optional[float] = None) -> int:
        """Resolve entries older than STALE_TIMEOUT_SEC. Returns count pruned."""
        if now is None:
            now = time.time()
        self._ensure_loaded()
        assert self._entries is not None
        pruned = 0
        for entry in list(self._entries.values()):
            if entry.status in TERMINAL_STATUSES:
                continue
            age = now - entry.updated_at
            if age > STALE_TIMEOUT_SEC:
                self.resolve(entry.entry_id, reason="stale_timeout")
                pruned += 1
        if pruned:
            logger.info(f"[BULLETIN] Pruned {pruned} stale entries")
        return pruned

    def compact(self) -> None:
        """Rewrite JSONL removing superseded records."""
        self._ensure_loaded()
        assert self._entries is not None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                for entry in self._entries.values():
                    f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
            logger.info(f"[BULLETIN] Compacted: {len(self._entries)} entries")
        except OSError as e:
            logger.error(f"[BULLETIN] Compact failed: {e}")

    def stats(self) -> Dict[str, Any]:
        """Summary stats for Telegram/Web UI."""
        self._ensure_loaded()
        assert self._entries is not None
        by_type = {}
        by_status = {}
        for e in self._entries.values():
            by_type[e.entry_type.value] = by_type.get(e.entry_type.value, 0) + 1
            by_status[e.status.value] = by_status.get(e.status.value, 0) + 1
        return {
            "total": len(self._entries),
            "open": len(self.get_open()),
            "actionable": len(self.get_actionable()),
            "by_type": by_type,
            "by_status": by_status,
        }
