"""
VisionMemory - Super-META E1: Maria remembers what she saw.

Today the camera detects motion, describes the scene (LLaVA -> Polish), sends the
caption to the operator, and then FORGETS it. Ask "co ostatnio widzialas?" and she
has no answer -- a glaring not-a-person gap. This is the missing brick: a small,
thread-safe ring buffer of the last N vision descriptions + timestamps, persisted
so the memory survives restarts and can be consulted by any organ (SelfContext in
E2/E3, chat "what did you see?" answers, the /lastseen command).

VisionAdvisor records here right after it renders a caption (off the tick thread).
Readers take latest()/recent(). Capped at max_entries and rewritten in full on
each add, so the backing file never grows.
"""

import json
import logging
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_PATH = "meta_data/vision_memory.json"
DEFAULT_MAX_ENTRIES = 10


def _ago(seconds: float) -> str:
    """Human-readable Polish 'how long ago' for a positive seconds delta."""
    s = max(0, int(seconds))
    if s < 15:
        return "przed chwila"
    if s < 60:
        return f"{s}s temu"
    m = s // 60
    if m < 60:
        return f"{m} min temu"
    h = m // 60
    if h < 24:
        return f"{h} godz temu"
    return f"{h // 24} dni temu"


class VisionMemory:
    """Thread-safe ring buffer of recent vision descriptions (last N + time)."""

    def __init__(
        self,
        path: Optional[Any] = None,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ):
        self._path = Path(path) if path is not None else Path(DEFAULT_PATH)
        self._max = max(1, int(max_entries))
        self._lock = threading.Lock()
        self._entries: Deque[Dict[str, Any]] = deque(maxlen=self._max)
        self._load()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(
        self,
        description: str,
        source: str = "motion",
        timestamp: Optional[float] = None,
    ) -> None:
        """Remember one thing seen. Empty/whitespace descriptions are ignored."""
        text = (description or "").strip()
        if not text:
            return
        ts = float(timestamp) if timestamp is not None else time.time()
        entry = {
            "description": text[:500],
            "source": str(source),
            "timestamp": ts,
            "iso": datetime.fromtimestamp(ts).replace(microsecond=0).isoformat(),
        }
        with self._lock:
            self._entries.append(entry)
            self._persist()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def latest(self) -> Optional[Dict[str, Any]]:
        """Most recent entry, or None if nothing seen yet."""
        with self._lock:
            return dict(self._entries[-1]) if self._entries else None

    def recent(self, n: int = 5) -> List[Dict[str, Any]]:
        """Up to n most recent entries, newest first."""
        with self._lock:
            items = list(self._entries)[-max(1, int(n)):]
        return [dict(e) for e in reversed(items)]

    def is_empty(self) -> bool:
        with self._lock:
            return not self._entries

    def format_for_telegram(self, n: int = 5) -> str:
        """Polish answer to 'co ostatnio widzialas?'."""
        items = self.recent(n)
        if not items:
            return "Jeszcze nic nie zapamietalam z kamery."
        now = time.time()
        lines = ["[Co ostatnio widzialam]"]
        for e in items:
            ts = e.get("timestamp")
            ago = _ago(now - float(ts)) if isinstance(ts, (int, float)) else "?"
            lines.append(f"  {ago}: {e.get('description', '')}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence (full rewrite, atomic; file is capped so never grows)
    # ------------------------------------------------------------------

    def _persist(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(list(self._entries), f, ensure_ascii=False)
            tmp.replace(self._path)  # atomic swap
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("VisionMemory persist failed: %s", e)

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for e in data[-self._max:]:
                    if isinstance(e, dict) and e.get("description"):
                        self._entries.append(e)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("VisionMemory load failed: %s", e)
