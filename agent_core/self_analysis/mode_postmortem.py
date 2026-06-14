"""Mode post-mortem recorder (D4 W1, 2026-04-26).

Each REDUCED → ACTIVE transition produces a structured post-mortem record
that captures *why* Maria entered REDUCED, how long she stayed, what was
running at entry, and the recovery trajectory. ``ModeAnalyzer`` (W2) reads
these records to cluster recurring root causes; the planner (W3) reads the
resulting bulletin entries to defer heavy actions in dangerous windows.

The recorder is intentionally passive — homeostasis core calls
``note_entry`` when REDUCED is entered and ``note_exit`` (which writes the
JSONL line and returns the record) when the system is back ACTIVE. State
between the two calls lives in memory so a daemon restart in REDUCED
simply drops the unfinished episode rather than producing junk data.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path("meta_data/mode_postmortems.jsonl")
MAX_RECORDS = 500          # rotation safeguard for JSONL


def _gen_id() -> str:
    return f"pm-{uuid.uuid4().hex[:12]}"


@dataclass
class _EntrySnapshot:
    """In-memory record of the moment Maria entered REDUCED."""

    timestamp: float
    tick_count: int
    metrics: Dict[str, Any]
    alerts: List[str]
    trigger: Dict[str, Any] = field(default_factory=dict)
    active_action_type: Optional[str] = None
    active_goal_id: Optional[str] = None


@dataclass
class ModePostmortem:
    """Closed REDUCED episode + recovery context."""

    postmortem_id: str
    from_mode: str
    to_mode: str
    entry_ts: float
    exit_ts: float
    duration_sec: float
    hour_of_day_berlin: int
    alerts_signature: str
    entry_metrics: Dict[str, Any]
    exit_metrics: Dict[str, Any]
    entry_alerts: List[str]
    exit_alerts: List[str]
    entry_tick: int
    exit_tick: int
    entry_trigger: Dict[str, Any]
    exit_trigger: Dict[str, Any]
    active_action_type: Optional[str] = None
    active_goal_id: Optional[str] = None
    health_score_at_exit: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "postmortem_id": self.postmortem_id,
            "from_mode": self.from_mode,
            "to_mode": self.to_mode,
            "entry_ts": self.entry_ts,
            "exit_ts": self.exit_ts,
            "duration_sec": round(self.duration_sec, 2),
            "hour_of_day_berlin": self.hour_of_day_berlin,
            "alerts_signature": self.alerts_signature,
            "entry_metrics": self.entry_metrics,
            "exit_metrics": self.exit_metrics,
            "entry_alerts": self.entry_alerts,
            "exit_alerts": self.exit_alerts,
            "entry_tick": self.entry_tick,
            "exit_tick": self.exit_tick,
            "entry_trigger": self.entry_trigger,
            "exit_trigger": self.exit_trigger,
            "active_action_type": self.active_action_type,
            "active_goal_id": self.active_goal_id,
            "health_score_at_exit": round(self.health_score_at_exit, 3),
        }


def alerts_signature(alerts: List[str]) -> str:
    """Canonicalise the alert list into a stable comparison key.

    The raw alert strings carry numeric values that change every tick; we
    keep the qualitative tag (CPU / RAM / THERMAL / LLM / COHERENCE / …) so
    ``ModeAnalyzer`` can cluster across episodes without exploding into a
    cardinality fan-out.
    """
    if not alerts:
        return "none"
    tags: set = set()
    for raw in alerts:
        if not raw:
            continue
        upper = raw.upper()
        if "CPU" in upper:
            tags.add("cpu")
        if "RAM" in upper or "MEMORY" in upper:
            tags.add("ram")
        if "THERM" in upper or "TEMP" in upper:
            tags.add("thermal")
        if "LLM" in upper or "LATENCY" in upper or "INFERENCE" in upper:
            tags.add("llm")
        if "COHERENCE" in upper:
            tags.add("coherence")
        if "IDLE" in upper:
            tags.add("idle")
        if "GOAL" in upper or "STACK" in upper:
            tags.add("goal_stack")
    return "|".join(sorted(tags)) or "other"


class ModePostmortemRecorder:
    """Captures REDUCED episodes and persists them as post-mortems."""

    def __init__(self, postmortem_path: Optional[Path] = None):
        self._path = postmortem_path or DEFAULT_PATH
        self._pending: Optional[_EntrySnapshot] = None
        self._analyzer = None
        # MODE constants kept as strings — the recorder is decoupled from
        # the homeostasis Mode enum to make tests trivial.
        self._reduced_value = "reduced"
        self._active_value = "active"

    @property
    def has_pending(self) -> bool:
        return self._pending is not None

    def set_analyzer(self, analyzer) -> None:
        """Chain a ``ModeAnalyzer`` so each new post-mortem can trigger an
        immediate (cooldown-respecting) clustering pass."""
        self._analyzer = analyzer

    def note_entry(
        self,
        timestamp: Optional[float] = None,
        tick_count: int = 0,
        metrics: Optional[Dict[str, Any]] = None,
        alerts: Optional[List[str]] = None,
        trigger: Optional[Dict[str, Any]] = None,
        active_action_type: Optional[str] = None,
        active_goal_id: Optional[str] = None,
    ) -> None:
        """Record entry into REDUCED. Idempotent — last call wins."""
        self._pending = _EntrySnapshot(
            timestamp=timestamp if timestamp is not None else time.time(),
            tick_count=int(tick_count),
            metrics=dict(metrics or {}),
            alerts=list(alerts or []),
            trigger=dict(trigger or {}),
            active_action_type=active_action_type,
            active_goal_id=active_goal_id,
        )

    def discard_pending(self) -> None:
        """Drop the pending entry (used when leaving REDUCED for non-ACTIVE)."""
        self._pending = None

    def note_exit(
        self,
        timestamp: Optional[float] = None,
        tick_count: int = 0,
        metrics: Optional[Dict[str, Any]] = None,
        alerts: Optional[List[str]] = None,
        trigger: Optional[Dict[str, Any]] = None,
        health_score: float = 1.0,
    ) -> Optional[ModePostmortem]:
        """Close a REDUCED → ACTIVE episode and persist it.

        Returns ``None`` when there is no pending entry (e.g. the daemon
        started while already ACTIVE) so callers can short-circuit safely.
        """
        if self._pending is None:
            return None

        exit_ts = timestamp if timestamp is not None else time.time()
        signature = alerts_signature(self._pending.alerts)
        try:
            hour = datetime.fromtimestamp(
                self._pending.timestamp, tz=timezone.utc
            ).astimezone().hour
        except Exception:
            hour = -1

        record = ModePostmortem(
            postmortem_id=_gen_id(),
            from_mode=self._reduced_value,
            to_mode=self._active_value,
            entry_ts=self._pending.timestamp,
            exit_ts=exit_ts,
            duration_sec=max(0.0, exit_ts - self._pending.timestamp),
            hour_of_day_berlin=hour,
            alerts_signature=signature,
            entry_metrics=self._pending.metrics,
            exit_metrics=dict(metrics or {}),
            entry_alerts=self._pending.alerts,
            exit_alerts=list(alerts or []),
            entry_tick=self._pending.tick_count,
            exit_tick=int(tick_count),
            entry_trigger=self._pending.trigger,
            exit_trigger=dict(trigger or {}),
            active_action_type=self._pending.active_action_type,
            active_goal_id=self._pending.active_goal_id,
            health_score_at_exit=float(health_score),
        )
        self._pending = None
        self._append(record)
        logger.info(
            "[ModePostmortem] %s recorded: dur=%.1fs sig=%s hour=%s action=%s",
            record.postmortem_id,
            record.duration_sec,
            record.alerts_signature,
            record.hour_of_day_berlin,
            record.active_action_type,
        )
        # Trigger analyzer (cooldown-aware) so patterns surface as soon as
        # they cross the threshold instead of waiting for the next tick
        # callback. Failures are swallowed — recorder must stay simple.
        if self._analyzer is not None:
            try:
                self._analyzer.analyze()
            except Exception as e:
                logger.debug(f"[ModePostmortem] analyzer chain failed: {e}")
        return record

    def _append(self, record: ModePostmortem) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
            self._maybe_rotate()
        except OSError as e:
            logger.warning(f"[ModePostmortem] write failed: {e}")

    def _maybe_rotate(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) <= MAX_RECORDS:
                return
            keep = lines[-MAX_RECORDS:]
            with open(self._path, "w", encoding="utf-8") as f:
                f.writelines(keep)
        except OSError:
            pass

    def get_recent(self, window_seconds: float = 7 * 86400) -> List[Dict[str, Any]]:
        """Return post-mortem records newer than ``window_seconds``."""
        cutoff = time.time() - window_seconds
        if not self._path.exists():
            return []
        out: List[Dict[str, Any]] = []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if d.get("entry_ts", 0.0) >= cutoff:
                        out.append(d)
        except OSError as e:
            logger.debug(f"[ModePostmortem] read failed: {e}")
        return out
