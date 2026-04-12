"""
WorkspaceSensor - File change detection in watched directories.

Tracks new/modified files in input/, docs/, meta_data/.
State persists across restarts via JSON file.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_STATE_FILE = Path("meta_data/workspace_sensor_state.json")
_IGNORE_SUFFIXES = {".pyc", ".tmp", ".bak", ".swp"}
_IGNORE_DIRS = {"__pycache__", ".git", ".pytest_cache", "venv"}


@dataclass(frozen=True)
class WorkspaceChange:
    """A single file change."""

    path: str
    change_type: str  # "new" | "modified"
    size_bytes: int
    mtime: float


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """Result of a workspace scan."""

    changes: Tuple[WorkspaceChange, ...]
    total_files: int
    new_input_files: int  # specifically new files in input/
    timestamp: float


class WorkspaceSensor:
    """Detects file changes in watched directories."""

    def __init__(
        self,
        watch_dirs: Optional[List[str]] = None,
        state_path: Optional[Path] = None,
        cache_ttl: int = 60,
    ):
        self._watch_dirs = watch_dirs or ["input", "docs"]
        self._state_path = state_path or _STATE_FILE
        self._cache_ttl = cache_ttl
        self._last_seen: Dict[str, float] = {}  # path -> mtime
        self._cached: Optional[WorkspaceSnapshot] = None
        self._cached_at: float = 0.0
        self._loaded = False

    def scan(self) -> WorkspaceSnapshot:
        """Scan for changes since last scan (cached with TTL)."""
        now = time.time()
        if self._cached and (now - self._cached_at) < self._cache_ttl:
            return self._cached

        self._ensure_loaded()
        changes = []
        current_files: Dict[str, float] = {}
        total_files = 0
        new_input = 0

        for watch_dir in self._watch_dirs:
            dir_path = Path(watch_dir)
            if not dir_path.exists():
                continue

            for entry in self._walk_dir(dir_path):
                rel = str(entry)
                total_files += 1

                try:
                    stat = os.stat(entry)
                    mtime = stat.st_mtime
                    size = stat.st_size
                except OSError:
                    continue

                current_files[rel] = mtime

                if rel not in self._last_seen:
                    change_type = "new"
                    if "input" in str(dir_path):
                        new_input += 1
                elif mtime > self._last_seen[rel]:
                    change_type = "modified"
                else:
                    continue

                changes.append(WorkspaceChange(
                    path=rel,
                    change_type=change_type,
                    size_bytes=size,
                    mtime=mtime,
                ))

        # Update state
        self._last_seen = current_files
        self._save_state()

        snapshot = WorkspaceSnapshot(
            changes=tuple(changes),
            total_files=total_files,
            new_input_files=new_input,
            timestamp=now,
        )
        self._cached = snapshot
        self._cached_at = now
        return snapshot

    def _walk_dir(self, dir_path: Path) -> List[Path]:
        """Walk directory (1 level for docs, recursive for input)."""
        results = []
        try:
            for entry in sorted(dir_path.iterdir()):
                if entry.name in _IGNORE_DIRS:
                    continue
                if entry.is_file() and entry.suffix not in _IGNORE_SUFFIXES:
                    results.append(entry)
                elif entry.is_dir() and str(dir_path) == "input":
                    # Recursive only for input/
                    for sub in sorted(entry.iterdir()):
                        if sub.is_file() and sub.suffix not in _IGNORE_SUFFIXES:
                            results.append(sub)
        except PermissionError:
            pass
        return results

    def _ensure_loaded(self) -> None:
        """Load last-seen state from JSON."""
        if self._loaded:
            return
        self._loaded = True
        try:
            if self._state_path.exists():
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                self._last_seen = data.get("files", {})
        except Exception as e:
            logger.debug("WorkspaceSensor: state load error: %s", e)

    def _save_state(self) -> None:
        """Save current state to JSON."""
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            data = json.dumps({"files": self._last_seen}, ensure_ascii=False)
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(data, encoding="utf-8")
            tmp.rename(self._state_path)
        except Exception as e:
            logger.debug("WorkspaceSensor: state save error: %s", e)
