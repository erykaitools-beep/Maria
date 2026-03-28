"""
TraceStore - JSONL persistence for DecisionTrace records.

Storage: meta_data/decision_traces.jsonl
Pattern: same as AuditLog (K10) - append-only, bounded in-memory.
"""

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.tracing.trace_model import DecisionTrace

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("meta_data/decision_traces.jsonl")
MAX_RECENT = 200


class TraceStore:
    """
    Append-only JSONL store for decision traces.

    Keeps MAX_RECENT traces in memory for fast queries.
    Thread-safe via lock.
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _DEFAULT_PATH
        self._recent: List[DecisionTrace] = []
        self._loaded = False
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def record(self, trace: DecisionTrace) -> None:
        """Append finalized trace to store."""
        with self._lock:
            self._ensure_loaded()
            self._recent.append(trace)
            if len(self._recent) > MAX_RECENT:
                self._recent = self._recent[-MAX_RECENT:]
            self._append_jsonl(trace)

    def get_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get N most recent traces (newest first)."""
        with self._lock:
            self._ensure_loaded()
            return [
                t.to_dict() for t in reversed(self._recent[-limit:])
            ]

    def get_by_episode_id(self, episode_id: str) -> Optional[Dict[str, Any]]:
        """Find a specific trace by episode ID."""
        with self._lock:
            self._ensure_loaded()
            for t in reversed(self._recent):
                if t.episode_id == episode_id:
                    return t.to_dict()
        return None

    def get_by_goal_id(self, goal_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Find traces related to a specific goal."""
        with self._lock:
            self._ensure_loaded()
            result = []
            for t in reversed(self._recent):
                if t.goal_id == goal_id:
                    result.append(t.to_dict())
                    if len(result) >= limit:
                        break
            return result

    def get_failed(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent failed traces for debugging."""
        with self._lock:
            self._ensure_loaded()
            result = []
            for t in reversed(self._recent):
                if t.success is False:
                    result.append(t.to_dict())
                    if len(result) >= limit:
                        break
            return result

    def get_stats(self, limit: int = 100) -> Dict[str, Any]:
        """Aggregate stats from recent traces."""
        with self._lock:
            self._ensure_loaded()
            traces = self._recent[-limit:]

        if not traces:
            return {"total": 0, "success": 0, "failed": 0, "avg_duration_ms": 0.0}

        total = len(traces)
        success = sum(1 for t in traces if t.success is True)
        failed = sum(1 for t in traces if t.success is False)
        durations = [t.duration_ms for t in traces if t.duration_ms > 0]
        avg_dur = round(sum(durations) / len(durations), 1) if durations else 0.0
        llm_calls = sum(t.total_llm_calls for t in traces)

        # Action type breakdown
        action_counts: Dict[str, int] = {}
        for t in traces:
            a = t.action_type or "unknown"
            action_counts[a] = action_counts.get(a, 0) + 1

        # K7 blocks
        k7_blocks = sum(1 for t in traces if t.k7_decision in ("block", "rate_limited"))

        return {
            "total": total,
            "success": success,
            "failed": failed,
            "avg_duration_ms": avg_dur,
            "total_llm_calls": llm_calls,
            "k7_blocks": k7_blocks,
            "action_types": action_counts,
        }

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
                        self._recent.append(DecisionTrace.from_dict(d))
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.debug(f"Skipping corrupt trace record: {e}")
            if len(self._recent) > MAX_RECENT:
                self._recent = self._recent[-MAX_RECENT:]
        except OSError as e:
            logger.warning(f"Could not read trace store: {e}")

    def _append_jsonl(self, trace: DecisionTrace) -> None:
        """Append single trace to JSONL file."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(trace.to_dict(), ensure_ascii=False) + "\n"
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            logger.warning(f"Could not write trace: {e}")
