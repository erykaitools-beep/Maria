"""Loop detector for recurring creative meta-goals (D3).

Background: K13 Creative regenerates meta-goals every reflection cycle. When
a class of meta-goals (fingerprinted by ``metadata.meta_goal_type``) keeps
recurring, Creative has no memory of the pattern — it just produces another
variation next cycle.

SOURCE (post-R1, 2026-05-29): Creative no longer writes goals to the GoalStore;
``goal_adapter`` posts an IMPROVEMENT bulletin advisory (reason_code
``creative_<type>``) instead. The original detector counted ABANDONED creative
GoalStore goals — a source R1 stopped feeding, so detect() silently saw 0 and
the same ~5-7 ideas spammed forever (diagnosed 2026-06-28). It now counts
RECURRING creative bulletin advisories by ``meta_goal_type`` within the window.
The GoalStore path is kept only as a legacy fallback when no bulletin is wired.

``CreativeModule.reflect()`` consults the suppression set before promoting
candidates so the loop short-circuits at source.

Properties:
    - Self-decaying: when no new advisories land in the window, the count
      drops below threshold and the suppression auto-lifts.
    - Coarse fingerprint by design: ``meta_goal_type`` is in the bulletin
      metadata, no migration needed.
    - Operator-overridable: the bulletin entry posted by the caller is the
      escape hatch — operator dismisses it to clear the streak signal.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Default policy knobs (conservative for Phase 1)
DEFAULT_ABANDON_THRESHOLD = 3
DEFAULT_WINDOW_DAYS = 7

# The detector's OWN suppression advisory is a creative_* bulletin too. It must
# be excluded from the recurrence count or it self-amplifies: suppressing a type
# posts an entry that counts as another recurrence -> suppression never lifts.
SUPPRESSION_REASON_CODE = "creative_loop_suppression"


@dataclass(frozen=True)
class LoopReport:
    """Result of a single ``detect()`` pass."""

    suppressed_types: Set[str]
    counts: Dict[str, int]
    window_days: int
    threshold: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "suppressed_types": sorted(self.suppressed_types),
            "counts": dict(self.counts),
            "window_days": self.window_days,
            "threshold": self.threshold,
        }


class LoopDetector:
    """Detects creative meta-goal patterns that keep getting abandoned."""

    def __init__(
        self,
        goal_store=None,
        bulletin_store=None,
        abandon_threshold: int = DEFAULT_ABANDON_THRESHOLD,
        window_days: int = DEFAULT_WINDOW_DAYS,
    ):
        self._goal_store = goal_store
        self._bulletin_store = bulletin_store
        self._threshold = max(1, int(abandon_threshold))
        self._window_days = max(1, int(window_days))

    def set_goal_store(self, store) -> None:
        """Late wiring (homeostasis init order). Legacy fallback source."""
        self._goal_store = store

    def set_bulletin_store(self, store) -> None:
        """Late wiring. Primary recurrence source post-R1 (creative advisories)."""
        self._bulletin_store = store

    def detect(self, now: Optional[float] = None) -> LoopReport:
        """Compute suppression set from recurring creative advisories.

        Prefers the live bulletin source (post-R1). Falls back to the
        now-historical GoalStore source only when no bulletin is wired, so
        legacy callers/tests keep working.

        Args:
            now: Override current time (for testing). Defaults to ``time.time()``.

        Returns:
            ``LoopReport`` with the suppressed meta-goal types and their counts.
            Empty report when no source is available.
        """
        now = now if now is not None else time.time()
        cutoff = now - self._window_days * 86400

        if self._bulletin_store is not None:
            counts = self._count_from_bulletin(cutoff)
        elif self._goal_store is not None:
            counts = self._count_from_goals(cutoff)
        else:
            return LoopReport(set(), {}, self._window_days, self._threshold)

        suppressed = {
            fp for fp, n in counts.items() if n >= self._threshold
        }
        return LoopReport(
            suppressed_types=suppressed,
            counts=counts,
            window_days=self._window_days,
            threshold=self._threshold,
        )

    def _count_from_bulletin(self, cutoff: float) -> Dict[str, int]:
        """Count recurring creative IMPROVEMENT advisories by meta_goal_type.

        Open advisories are the un-actioned recurrence signal; resolved ones
        were handled, so they correctly drop out (get_by_type returns open).
        """
        counts: Dict[str, int] = {}
        try:
            from agent_core.bulletin.bulletin_model import EntryType
            entries = self._bulletin_store.get_by_type(EntryType.IMPROVEMENT)
        except Exception as e:
            logger.debug(f"[LoopDetector] bulletin read failed: {e}")
            return counts
        for e in entries:
            try:
                rc = getattr(e, "reason_code", "") or ""
                if not rc.startswith("creative_") or rc == SUPPRESSION_REASON_CODE:
                    continue
                ts = getattr(e, "created_at", 0.0) or 0.0
                if ts < cutoff:
                    continue
                metadata = e.metadata if isinstance(e.metadata, dict) else {}
                fp = metadata.get("meta_goal_type")
                if not fp:
                    continue
                counts[fp] = counts.get(fp, 0) + 1
            except Exception:
                continue
        return counts

    def _count_from_goals(self, cutoff: float) -> Dict[str, int]:
        """Legacy fallback: count ABANDONED creative GoalStore goals (pre-R1)."""
        counts: Dict[str, int] = {}
        try:
            goals = self._goal_store.get_all()
        except Exception as e:
            logger.debug(f"[LoopDetector] get_all failed: {e}")
            return counts
        for g in goals:
            try:
                status_value = g.status.value if hasattr(g.status, "value") else str(g.status)
                if status_value != "abandoned":
                    continue
                if (g.created_by or "") != "creative":
                    continue
                ts = getattr(g, "updated_at", None) or getattr(g, "created_at", 0.0)
                if ts < cutoff:
                    continue
                metadata = g.metadata if isinstance(g.metadata, dict) else {}
                fp = metadata.get("meta_goal_type")
                if not fp:
                    continue
                counts[fp] = counts.get(fp, 0) + 1
            except Exception:
                continue
        return counts

    def filter_candidates(self, candidates: List[Any]) -> tuple[List[Any], List[Any]]:
        """Split candidates into (kept, suppressed) by current detect() result.

        Each candidate is expected to expose a ``goal_type`` enum-like attribute
        with a ``.value`` matching the strings used in goal metadata.
        """
        report = self.detect()
        if not report.suppressed_types:
            return list(candidates), []
        kept: List[Any] = []
        suppressed: List[Any] = []
        for c in candidates:
            try:
                gtype = c.goal_type.value
            except AttributeError:
                kept.append(c)
                continue
            if gtype in report.suppressed_types:
                suppressed.append(c)
            else:
                kept.append(c)
        return kept, suppressed
