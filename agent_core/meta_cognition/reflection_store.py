"""
ReflectionStore - JSONL persistence for K9 Meta-Cognition.

Storage: meta_data/reflections.jsonl
Pattern: IntentTracker (K8) - append-only, bounded reads, rewrite on update.
Kontrakt: docs/CONTRACTS.md - Kontrakt 9: Meta-Cognition
"""

import json
import logging
from pathlib import Path
from typing import List, Optional

from agent_core.meta_cognition.reflection_model import Reflection

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("meta_data/reflections.jsonl")
MAX_RECORDS = 5000


class ReflectionStore:
    """
    Persistent storage for Reflection records.

    Append-only JSONL. Rewrite on reflect() updates.
    Bounded: max MAX_RECORDS records in memory (oldest trimmed).
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _DEFAULT_PATH
        self._cache: List[Reflection] = []
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Load from JSONL if not yet loaded."""
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
                        self._cache.append(Reflection.from_dict(d))
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.debug(f"Skipping corrupt reflection record: {e}")
            # Trim to max
            if len(self._cache) > MAX_RECORDS:
                self._cache = self._cache[-MAX_RECORDS:]
        except OSError as e:
            logger.warning(f"Could not read reflections file: {e}")

    def append(self, reflection: Reflection) -> None:
        """Append a new reflection (phase 1: record_decision)."""
        self._ensure_loaded()
        self._cache.append(reflection)
        # Trim oldest if over limit
        if len(self._cache) > MAX_RECORDS:
            self._cache = self._cache[-MAX_RECORDS:]
            self._rewrite_jsonl()
        else:
            self._append_jsonl(reflection)

    def update(self, reflection_id: str, **fields) -> bool:
        """
        Update a reflection in-place (phase 2: reflect).
        Rewrites JSONL file.
        Returns True if found and updated.
        """
        self._ensure_loaded()
        for r in reversed(self._cache):
            if r.reflection_id == reflection_id:
                for key, value in fields.items():
                    if hasattr(r, key):
                        setattr(r, key, value)
                self._rewrite_jsonl()
                return True
        return False

    def get_by_plan_id(self, plan_id: str) -> Optional[Reflection]:
        """Find most recent reflection for a specific plan."""
        self._ensure_loaded()
        for r in reversed(self._cache):
            if r.plan_id == plan_id:
                return r
        return None

    def get_by_action_type(
        self, action_type: str, limit: int = 50
    ) -> List[Reflection]:
        """Get recent reflections by action type (newest first)."""
        self._ensure_loaded()
        result = []
        for r in reversed(self._cache):
            if r.action_type == action_type:
                result.append(r)
                if len(result) >= limit:
                    break
        return result

    def get_by_topic(self, topic: str, limit: int = 50) -> List[Reflection]:
        """Get recent reflections for a topic (newest first)."""
        self._ensure_loaded()
        topic_lower = topic.lower()
        result = []
        for r in reversed(self._cache):
            if r.topic.lower() == topic_lower:
                result.append(r)
                if len(result) >= limit:
                    break
        return result

    def get_recent(self, limit: int = 20) -> List[Reflection]:
        """Get N most recent reflections (newest first)."""
        self._ensure_loaded()
        return list(reversed(self._cache[-limit:]))

    def get_reflected(self, limit: int = 100) -> List[Reflection]:
        """Get only completed reflections (newest first)."""
        self._ensure_loaded()
        result = []
        for r in reversed(self._cache):
            if r.is_reflected:
                result.append(r)
                if len(result) >= limit:
                    break
        return result

    def count(self) -> int:
        """Total number of reflections in store."""
        self._ensure_loaded()
        return len(self._cache)

    def _append_jsonl(self, reflection: Reflection) -> None:
        """Append single record to JSONL file."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(reflection.to_dict(), ensure_ascii=False))
                f.write("\n")
        except OSError as e:
            logger.warning(f"Could not write reflection: {e}")

    def _rewrite_jsonl(self) -> None:
        """Rewrite entire JSONL from cache."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                for r in self._cache:
                    f.write(json.dumps(r.to_dict(), ensure_ascii=False))
                    f.write("\n")
        except OSError as e:
            logger.warning(f"Could not rewrite reflections file: {e}")
