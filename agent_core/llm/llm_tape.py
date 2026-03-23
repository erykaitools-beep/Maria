"""
LLM Tape - Records all LLM interactions to JSONL for audit and introspection.

Every call to any model (llama3.1:8b, qwen3:8b, NIM, etc.) is logged with:
- prompt summary, raw response, model, role, latency, success flag.

Used by:
- EvidenceCollector (Phase 2): reads recent errors/stats for grounded answers
- K12 Self-Analysis: includes tape data in analysis context
- Debugging: "what did the model actually return?"

Thread-safe (lock on append). File rotated at 50MB.
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Limits
MAX_PROMPT_SUMMARY = 200
MAX_RAW_RESPONSE = 2000
DEFAULT_MAX_SIZE_BYTES = 50_000_000  # 50MB


@dataclass
class TapeEntry:
    """Single LLM interaction record."""
    ts: float
    model: str
    role: str               # "chat", "planner", "learning", "exam", "analyzer"
    prompt_summary: str     # first MAX_PROMPT_SUMMARY chars
    raw_response: str       # first MAX_RAW_RESPONSE chars
    tokens_est: int         # rough estimate
    latency_ms: float
    success: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TapeEntry":
        return cls(
            ts=d.get("ts", 0.0),
            model=d.get("model", "unknown"),
            role=d.get("role", "unknown"),
            prompt_summary=d.get("prompt_summary", ""),
            raw_response=d.get("raw_response", ""),
            tokens_est=d.get("tokens_est", 0),
            latency_ms=d.get("latency_ms", 0.0),
            success=d.get("success", True),
        )


def make_tape_entry(
    model: str,
    role: str,
    prompt: str,
    response: str,
    latency_ms: float,
    success: bool = True,
) -> TapeEntry:
    """Helper to create a TapeEntry with truncation."""
    return TapeEntry(
        ts=time.time(),
        model=model,
        role=role,
        prompt_summary=(prompt or "")[:MAX_PROMPT_SUMMARY],
        raw_response=(response or "")[:MAX_RAW_RESPONSE],
        tokens_est=len(response or "") // 4,
        latency_ms=round(latency_ms, 1),
        success=success,
    )


class LLMTape:
    """
    Append-only JSONL recorder for LLM interactions.

    Thread-safe. Rotates file when size exceeds max_size_bytes.
    Supports tail-read for recent entries without scanning entire file.
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
    ):
        self._path = Path(path) if path else Path("meta_data/llm_tape.jsonl")
        self._max_size = max_size_bytes
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def record(self, entry: TapeEntry) -> None:
        """Append entry to tape. Thread-safe."""
        with self._lock:
            try:
                self._rotate_if_needed()
                line = json.dumps(entry.to_dict(), ensure_ascii=False) + "\n"
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception as e:
                logger.debug(f"[LLMTape] record failed: {e}")

    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Read last N entries from tape (tail read)."""
        if not self._path.exists():
            return []

        try:
            # Read from end of file for efficiency
            entries = []
            with open(self._path, "r", encoding="utf-8") as f:
                # For files under 1MB, just read all lines
                file_size = self._path.stat().st_size
                if file_size < 1_000_000:
                    lines = f.readlines()
                else:
                    # Seek to approximate position for large files
                    # ~300 bytes per entry average
                    seek_pos = max(0, file_size - limit * 500)
                    f.seek(seek_pos)
                    if seek_pos > 0:
                        f.readline()  # skip partial line
                    lines = f.readlines()

                for line in lines[-limit:]:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            return entries
        except Exception as e:
            logger.debug(f"[LLMTape] get_recent failed: {e}")
            return []

    def get_stats(self, period_hours: int = 24) -> Dict[str, Any]:
        """Aggregate stats for the last N hours."""
        cutoff = time.time() - period_hours * 3600
        entries = self._read_since(cutoff)

        if not entries:
            return {
                "period_hours": period_hours,
                "total_calls": 0,
                "error_count": 0,
                "error_rate": 0.0,
                "avg_latency_ms": 0.0,
                "models_used": [],
                "roles_used": [],
            }

        total = len(entries)
        errors = sum(1 for e in entries if not e.get("success", True))
        latencies = [e.get("latency_ms", 0) for e in entries]
        models = list(set(e.get("model", "") for e in entries))
        roles = list(set(e.get("role", "") for e in entries))

        return {
            "period_hours": period_hours,
            "total_calls": total,
            "error_count": errors,
            "error_rate": round(errors / total, 3) if total > 0 else 0.0,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
            "models_used": sorted(models),
            "roles_used": sorted(roles),
        }

    def get_recent_errors(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get last N failed entries."""
        recent = self.get_recent(limit=limit * 5)  # oversample
        errors = [e for e in recent if not e.get("success", True)]
        return errors[-limit:]

    def _read_since(self, cutoff_ts: float) -> List[Dict[str, Any]]:
        """Read entries newer than cutoff timestamp."""
        if not self._path.exists():
            return []

        entries = []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        if d.get("ts", 0) >= cutoff_ts:
                            entries.append(d)
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            logger.debug(f"[LLMTape] _read_since failed: {e}")

        return entries

    def _rotate_if_needed(self) -> None:
        """Rotate file if it exceeds max size."""
        if not self._path.exists():
            return
        try:
            size = self._path.stat().st_size
            if size >= self._max_size:
                backup = self._path.with_suffix(".jsonl.bak")
                if backup.exists():
                    backup.unlink()
                self._path.rename(backup)
                logger.info(
                    f"[LLMTape] Rotated {self._path.name} ({size // 1_000_000}MB)"
                )
        except Exception as e:
            logger.debug(f"[LLMTape] rotation failed: {e}")
