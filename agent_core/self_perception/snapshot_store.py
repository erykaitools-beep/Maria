"""JSONL-backed storage for self-perception snapshots."""

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

_DEFAULT_PATH = (
    Path(__file__).resolve().parents[2]
    / "meta_data"
    / "self_state_snapshots.jsonl"
)


class SnapshotStore:
    """Thin file-backed store for self-state snapshots."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _DEFAULT_PATH
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        """Return the JSONL path used by this store."""
        return self._path

    def save(self, snapshot: Dict[str, Any]) -> None:
        """Append a snapshot as a single JSON line."""
        line = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()

    def load_latest(self) -> Optional[Dict[str, Any]]:
        """Load the last persisted snapshot, if any."""
        with self._lock:
            if not self._path.exists():
                return None
            last_line = ""
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped:
                        last_line = stripped
            if not last_line:
                return None
            return json.loads(last_line)

    def load_recent(self, n: int) -> List[Dict[str, Any]]:
        """Load up to the last n persisted snapshots."""
        if n <= 0:
            return []
        with self._lock:
            if not self._path.exists():
                return []
            lines: List[str] = []
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped:
                        lines.append(stripped)
            return [json.loads(line) for line in lines[-n:]]
