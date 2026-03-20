"""
AuditLog - JSONL persistence for K10 Action Safety.

Storage: meta_data/action_audit.jsonl
Pattern: EscalationHandler (K7) - append-only, bounded in-memory.
Kontrakt: docs/CONTRACTS.md - Kontrakt 10: Action Safety
"""

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.action_safety.safety_model import ActionRecord

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("meta_data/action_audit.jsonl")
MAX_RECENT = 200


class AuditLog:
    """
    Append-only JSONL log of all action executions with safety metadata.

    Bounded: keeps MAX_RECENT records in memory for queries.
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _DEFAULT_PATH
        self._recent: List[ActionRecord] = []
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Load recent records from JSONL if not yet loaded."""
        if self._loaded:
            return
        self._loaded = True
        if not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        self._recent.append(ActionRecord.from_dict(d))
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.debug(f"Skipping corrupt audit record: {e}")
            # Trim to max
            if len(self._recent) > MAX_RECENT:
                self._recent = self._recent[-MAX_RECENT:]
        except OSError as e:
            logger.warning(f"Could not read audit log: {e}")

    def record(self, action_record: ActionRecord) -> None:
        """Append completed ActionRecord to log."""
        self._ensure_loaded()
        self._recent.append(action_record)
        if len(self._recent) > MAX_RECENT:
            self._recent = self._recent[-MAX_RECENT:]
        self._append_jsonl(action_record)

    def get_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get N most recent records (newest first)."""
        self._ensure_loaded()
        return [
            r.to_dict() for r in reversed(self._recent[-limit:])
        ]

    def get_by_action_type(
        self, action_type: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Filter recent records by action type."""
        self._ensure_loaded()
        result = []
        for r in reversed(self._recent):
            if r.action_type == action_type:
                result.append(r.to_dict())
                if len(result) >= limit:
                    break
        return result

    def get_by_plan_id(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Find record for specific plan."""
        self._ensure_loaded()
        for r in reversed(self._recent):
            if r.plan_id == plan_id:
                return r.to_dict()
        return None

    def count(self) -> int:
        """Total records in memory."""
        self._ensure_loaded()
        return len(self._recent)

    def get_stats(self) -> Dict[str, Any]:
        """Summary stats: counts per action_type, per safety_mode, validation."""
        self._ensure_loaded()
        action_counts: Counter = Counter()
        mode_counts: Counter = Counter()
        validation_counts: Counter = Counter()
        success_count = 0
        fail_count = 0

        for r in self._recent:
            action_counts[r.action_type] += 1
            mode_counts[r.safety_mode] += 1
            validation_counts[r.validation] += 1
            if r.success is True:
                success_count += 1
            elif r.success is False:
                fail_count += 1

        return {
            "total": len(self._recent),
            "by_action_type": dict(action_counts),
            "by_safety_mode": dict(mode_counts),
            "by_validation": dict(validation_counts),
            "success": success_count,
            "failed": fail_count,
        }

    def _append_jsonl(self, record: ActionRecord) -> None:
        """Append single record to JSONL file."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False))
                f.write("\n")
        except OSError as e:
            logger.warning(f"Could not write audit record: {e}")
