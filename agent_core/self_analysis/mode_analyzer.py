"""Mode pattern analyzer (D4 W2, 2026-04-26).

Reads recent post-mortems written by ``ModePostmortemRecorder`` and clusters
recurring REDUCED root causes by ``(alerts_signature, hour_bucket,
active_action_type)``. When a pattern crosses the threshold the analyzer
posts a single ``IMPROVEMENT`` entry to the bulletin so the planner (W3)
can soft-defer matching heavy actions.

Design notes:
- Stateless: every ``analyze()`` reads JSONL and recomputes patterns.
- Idempotent bulletin posts: dedup by topic via ``BulletinStore.find_open``.
  Topic is fingerprint-derived so a re-run does not spam.
- Threshold conservative for Phase 1 (``2`` matching post-mortems within
  the window); operator can resolve the bulletin entry to clear it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 2
DEFAULT_WINDOW_SEC = 7 * 86400
DEFAULT_COOLDOWN_SEC = 1800  # 30 min between full analyses


def _hour_bucket(hour: int) -> str:
    if hour < 0:
        return "unknown"
    if 6 <= hour < 12:
        return "morning"  # learning window 09-11 sits here
    if 12 <= hour < 18:
        return "afternoon"  # learning window 14-16 sits here
    if 18 <= hour < 22:
        return "evening"
    return "night"


@dataclass(frozen=True)
class ModePattern:
    """One clustered root-cause pattern."""

    alerts_signature: str
    hour_bucket: str
    active_action_type: Optional[str]
    count: int
    sample_ids: List[str]
    avg_duration_sec: float
    last_entry_ts: float

    @property
    def fingerprint(self) -> str:
        action = self.active_action_type or "any"
        return f"{self.alerts_signature}|{self.hour_bucket}|{action}"

    def to_summary(self, window_days: int) -> str:
        action = self.active_action_type or "(unspecified action)"
        return (
            f"REDUCED loop: {self.count}x in {window_days}d during "
            f"{self.hour_bucket} with alerts [{self.alerts_signature}] "
            f"while running '{action}'. Avg dwell {self.avg_duration_sec:.0f}s."
        )


@dataclass
class AnalyzerReport:
    """Summary of one analyze() pass."""

    patterns: List[ModePattern] = field(default_factory=list)
    posted_bulletin_ids: List[str] = field(default_factory=list)
    total_postmortems: int = 0


class ModeAnalyzer:
    """Detects recurring REDUCED root causes from post-mortems."""

    def __init__(
        self,
        postmortem_recorder=None,
        bulletin_store=None,
        threshold: int = DEFAULT_THRESHOLD,
        window_sec: float = DEFAULT_WINDOW_SEC,
        cooldown_sec: float = DEFAULT_COOLDOWN_SEC,
    ):
        self._recorder = postmortem_recorder
        self._bulletin = bulletin_store
        self._threshold = max(2, int(threshold))
        self._window_sec = float(window_sec)
        self._cooldown_sec = float(cooldown_sec)
        self._last_run_ts: float = 0.0

    def set_postmortem_recorder(self, recorder) -> None:
        self._recorder = recorder

    def set_bulletin_store(self, store) -> None:
        self._bulletin = store

    def should_run(self, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        return (now - self._last_run_ts) >= self._cooldown_sec

    def analyze(
        self,
        now: Optional[float] = None,
        force: bool = False,
    ) -> AnalyzerReport:
        """Cluster recent post-mortems and post bulletin entries.

        Returns:
            ``AnalyzerReport`` summarising patterns found and bulletin
            entries posted this run.
        """
        if not force and not self.should_run(now):
            return AnalyzerReport()

        if self._recorder is None:
            self._last_run_ts = now if now is not None else time.time()
            return AnalyzerReport()

        records = self._recorder.get_recent(window_seconds=self._window_sec)
        report = AnalyzerReport(total_postmortems=len(records))
        if not records:
            self._last_run_ts = now if now is not None else time.time()
            return report

        clusters: Dict[Tuple[str, str, Optional[str]], List[Dict[str, Any]]] = {}
        for r in records:
            key = (
                r.get("alerts_signature", "none"),
                _hour_bucket(int(r.get("hour_of_day_berlin", -1))),
                r.get("active_action_type"),
            )
            clusters.setdefault(key, []).append(r)

        for (signature, hour_bucket, action), bucket in clusters.items():
            if len(bucket) < self._threshold:
                continue
            avg_dur = sum(r.get("duration_sec", 0) for r in bucket) / len(bucket)
            last_ts = max(r.get("entry_ts", 0) for r in bucket)
            pattern = ModePattern(
                alerts_signature=signature,
                hour_bucket=hour_bucket,
                active_action_type=action,
                count=len(bucket),
                sample_ids=[r.get("postmortem_id", "?") for r in bucket[:5]],
                avg_duration_sec=avg_dur,
                last_entry_ts=last_ts,
            )
            report.patterns.append(pattern)
            entry_id = self._post_pattern_to_bulletin(pattern)
            if entry_id:
                report.posted_bulletin_ids.append(entry_id)

        self._last_run_ts = now if now is not None else time.time()
        if report.patterns:
            logger.info(
                "[ModeAnalyzer] %d pattern(s) detected from %d post-mortem(s); "
                "posted=%d",
                len(report.patterns),
                len(records),
                len(report.posted_bulletin_ids),
            )
        return report

    # --- Bulletin integration ---------------------------------

    def _post_pattern_to_bulletin(self, pattern: ModePattern) -> Optional[str]:
        if self._bulletin is None:
            return None
        try:
            from agent_core.bulletin.bulletin_model import EntryType
        except Exception:
            return None

        topic = f"mode_loop:{pattern.fingerprint}"
        # Dedup: skip when an open entry for the same topic already exists.
        try:
            existing = self._bulletin.find_open(
                topic=topic, entry_type=EntryType.IMPROVEMENT,
            )
        except Exception:
            existing = []
        if existing:
            return existing[0].entry_id

        window_days = int(round(self._window_sec / 86400))
        summary = pattern.to_summary(window_days)
        priority = min(0.95, 0.6 + 0.05 * pattern.count)

        try:
            entry = self._bulletin.create_and_post(
                entry_type=EntryType.IMPROVEMENT,
                topic=topic,
                reason_code="mode_aware_pattern",
                summary=summary,
                requested_by="mode_analyzer",
                priority=priority,
                metadata={
                    "alerts_signature": pattern.alerts_signature,
                    "hour_bucket": pattern.hour_bucket,
                    "action_hint": pattern.active_action_type,
                    "mode_aware": True,
                    "abandon_count": pattern.count,
                    "sample_postmortem_ids": pattern.sample_ids,
                    "avg_duration_sec": round(pattern.avg_duration_sec, 1),
                    "window_days": window_days,
                },
            )
            return entry.entry_id
        except Exception as e:
            logger.debug(f"[ModeAnalyzer] bulletin post failed: {e}")
            return None
