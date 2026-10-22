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

import gzip
import json
import logging
import os
import shutil
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
    episode_id: str = ""    # Correlation ID from tracing.episode (Phase 1)
    route_reason: str = ""  # Why this model was chosen (Phase 3 telemetry)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Omit empty optional fields (backward compat)
        if not d.get("episode_id"):
            d.pop("episode_id", None)
        if not d.get("route_reason"):
            d.pop("route_reason", None)
        return d

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
            episode_id=d.get("episode_id", ""),
            route_reason=d.get("route_reason", ""),
        )


def make_tape_entry(
    model: str,
    role: str,
    prompt: str,
    response: str,
    latency_ms: float,
    success: bool = True,
    episode_id: str = "",
    route_reason: str = "",
) -> TapeEntry:
    """Helper to create a TapeEntry with truncation."""
    # Auto-read episode_id from thread-local if not provided
    if not episode_id:
        try:
            from agent_core.tracing.episode import current_episode_id
            episode_id = current_episode_id()
        except ImportError:
            pass
    return TapeEntry(
        ts=time.time(),
        model=model,
        role=role,
        prompt_summary=(prompt or "")[:MAX_PROMPT_SUMMARY],
        raw_response=(response or "")[:MAX_RAW_RESPONSE],
        tokens_est=len(response or "") // 4,
        latency_ms=round(latency_ms, 1),
        success=success,
        episode_id=episode_id,
        route_reason=route_reason,
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

            # Top up from archives when the live tape is short. Right after a
            # rotation it holds a handful of lines, and EvidenceCollector /
            # K12 would silently see almost no history -- the rotation would
            # look like "the model went quiet" to every consumer.
            if len(entries) < limit:
                entries = self._backfill(limit - len(entries)) + entries
            return entries
        except Exception as e:
            logger.debug(f"[LLMTape] get_recent failed: {e}")
            return []

    def _backfill(self, want: int) -> List[Dict[str, Any]]:
        """Newest `want` entries from the archives, oldest-first in the result."""
        collected: List[Dict[str, Any]] = []
        for archive in self.archives():
            try:
                with self._open_any(archive) as handle:
                    rows = [line.strip() for line in handle if line.strip()]
            except Exception:
                continue
            for line in reversed(rows):
                try:
                    collected.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if len(collected) >= want:
                    break
            if len(collected) >= want:
                break
        collected.reverse()
        return collected

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
        """Read entries newer than cutoff timestamp, across archives if needed.

        get_stats(period_hours=24) runs through here. If the window reaches back
        past the start of the live tape -- which it does for a full day after
        every rotation -- the answer has to come partly from the archive, or a
        24h stats call would report the few minutes since rotation and call it
        a day.
        """
        entries: List[Dict[str, Any]] = []

        def harvest(opener, path) -> Optional[float]:
            """Append matching rows; return the oldest ts seen in this file."""
            oldest: Optional[float] = None
            try:
                with opener(path) as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        ts = row.get("ts", 0)
                        if oldest is None or ts < oldest:
                            oldest = ts
                        if ts >= cutoff_ts:
                            entries.append(row)
            except Exception as e:
                logger.debug(f"[LLMTape] _read_since failed on {path}: {e}")
            return oldest

        oldest_seen: Optional[float] = None
        if self._path.exists():
            oldest_seen = harvest(
                lambda p: open(p, "r", encoding="utf-8", errors="replace"), self._path
            )

        # Only reach into archives while the window is still not covered.
        if oldest_seen is None or oldest_seen > cutoff_ts:
            for archive in self.archives():
                oldest_seen = harvest(self._open_any, archive)
                if oldest_seen is not None and oldest_seen <= cutoff_ts:
                    break

        entries.sort(key=lambda r: r.get("ts", 0))
        return entries

    @property
    def archive_dir(self) -> Path:
        """Where rotated tapes live. Sibling of the tape, not a suffix of it."""
        return self._path.parent / f"{self._path.stem}_archive"

    def archives(self) -> List[Path]:
        """Rotated tapes, NEWEST FIRST. Timestamped names sort chronologically."""
        directory = self.archive_dir
        if not directory.exists():
            return []
        found = list(directory.glob(f"{self._path.stem}-*.jsonl")) + list(
            directory.glob(f"{self._path.stem}-*.jsonl.gz")
        )
        return sorted(found, key=lambda p: p.name, reverse=True)

    @staticmethod
    def _open_any(path: Path):
        """Open a plain or gzipped archive transparently."""
        if path.suffix == ".gz":
            return gzip.open(path, "rt", encoding="utf-8", errors="replace")
        return open(path, "r", encoding="utf-8", errors="replace")

    def _rotate_if_needed(self) -> None:
        """Move the tape into a timestamped archive once it exceeds max size.

        The previous scheme renamed onto a single ``.jsonl.bak`` and deleted
        whatever the last rotation had left there. With one file holding 139 days
        of every LLM call this box has made, that meant the first rotation split
        the history and the second destroyed half of it -- silently, since
        rotation only ever logged at INFO.

        Archives are never deleted. At the observed ~355 KB/day the tape reaches
        50 MB about every 140 days, and gzip takes that to a few MB, so a decade
        of history costs less than the tape does today.
        """
        if not self._path.exists():
            return
        try:
            size = self._path.stat().st_size
            if size < self._max_size:
                return

            directory = self.archive_dir
            directory.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
            # Never rename onto an existing archive. The stamp has one-second
            # resolution and production rotations sit ~140 days apart, so a
            # collision "cannot happen" -- which is precisely the assumption
            # this whole change exists to remove. Caught by the round-trip test,
            # which lost entries until this loop went in.
            target = directory / f"{self._path.stem}-{stamp}.jsonl"
            suffix = 1
            while target.exists() or target.with_suffix(".jsonl.gz").exists():
                target = directory / f"{self._path.stem}-{stamp}-{suffix}.jsonl"
                suffix += 1

            # Rename BEFORE compressing: the rename is atomic, so the history is
            # safe the instant it completes. Compressing in place would leave a
            # window where a crash loses the file to a half-written archive.
            self._path.rename(target)
            logger.warning(
                "[LLMTape] Rotated %s (%.1f MB) -> %s",
                self._path.name, size / 1_000_000, target.name,
            )
            self._compress(target)
        except Exception as e:
            logger.warning(f"[LLMTape] rotation failed: {e}")

    @staticmethod
    def _compress(path: Path) -> None:
        """Gzip an archive in place. The plain file goes only once the gz is good."""
        try:
            packed = path.with_suffix(".jsonl.gz")
            with open(path, "rb") as src, gzip.open(packed, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if packed.exists() and packed.stat().st_size > 0:
                path.unlink()
        except Exception as e:
            # A failed compression is not a failed rotation: the plain archive is
            # already on disk and readable, which is the part that matters.
            logger.warning(f"[LLMTape] archive compression failed: {e}")
