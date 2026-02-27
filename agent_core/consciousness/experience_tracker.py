"""
ExperienceTracker - Records Maria's experiences for personality evolution.

Append-only JSONL log: meta_data/personality_experiences.jsonl
Thread-safe, buffered writes, non-blocking.

Usage:
    tracker = ExperienceTracker()
    tracker.record("learning_completed", {"file": "quantum.txt"})
    tracker.record("conversation_turn")

    # At checkpoint:
    counts = tracker.get_experience_counts()
    tracker.flush()
    tracker.clear_session()
"""

import json
import time
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import Counter

logger = logging.getLogger(__name__)


class ExperienceTracker:
    """
    Records experience events for personality evolution.

    Events are buffered in memory during the session and flushed
    to JSONL at checkpoint time. Thread-safe for use from
    homeostasis tick loop or other threads.
    """

    DEFAULT_LOG_PATH = Path("meta_data/personality_experiences.jsonl")

    def __init__(self, log_path: Optional[Path] = None, session_id: int = 0):
        """
        Initialize experience tracker.

        Args:
            log_path: Path for JSONL log file (default: meta_data/personality_experiences.jsonl)
            session_id: Current session number (for tagging events)
        """
        self.log_path = log_path or self.DEFAULT_LOG_PATH
        self.session_id = session_id
        self._buffer: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, event_type: str, details: Optional[Dict] = None) -> None:
        """
        Record an experience event.

        Thread-safe, non-blocking. Event is buffered in memory.

        Args:
            event_type: Type of event (e.g. "learning_completed", "conversation_turn")
            details: Optional dict with extra information
        """
        event = {
            "ts": time.time(),
            "event": event_type,
            "details": details or {},
            "session": self.session_id,
        }
        with self._lock:
            self._buffer.append(event)

    def get_session_experiences(self) -> List[Dict[str, Any]]:
        """
        Get all experiences recorded this session.

        Returns:
            Copy of the session buffer.
        """
        with self._lock:
            return list(self._buffer)

    def get_experience_counts(self) -> Dict[str, int]:
        """
        Count experiences by event type for this session.

        Returns:
            Dict mapping event_type -> count
        """
        with self._lock:
            counter = Counter(e["event"] for e in self._buffer)
            return dict(counter)

    def get_total_count(self) -> int:
        """Get total number of experiences this session."""
        with self._lock:
            return len(self._buffer)

    def flush(self) -> None:
        """
        Write buffered experiences to JSONL file.

        Appends to existing file. Creates parent directories if needed.
        """
        with self._lock:
            if not self._buffer:
                return
            to_write = list(self._buffer)

        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                for event in to_write:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            logger.debug(f"ExperienceTracker: flushed {len(to_write)} events")
        except IOError as e:
            logger.error(f"ExperienceTracker: flush failed: {e}")

    def clear_session(self) -> None:
        """Clear the session buffer (call after evolution)."""
        with self._lock:
            self._buffer.clear()
