"""Loop detector for repeated abandoned creative meta-goals (D3).

Background: K13 Creative regenerates meta-goals every reflection cycle. When
a class of meta-goals (fingerprinted by ``metadata.meta_goal_type``) keeps
getting abandoned, Creative has no memory of the pattern — it just produces
another variation next cycle. History shows 41 abandoned ``capability_meta``
+ 11 ``architectural_meta`` orphans accumulated in the goal store.

LoopDetector scans the goal store for ABANDONED creative meta-goals within
a sliding window and returns the set of meta-goal types that crossed the
abandon threshold. ``CreativeModule.reflect()`` consults the suppression set
before promoting candidates so the loop short-circuits at source.

Properties:
    - Self-decaying: when no new abandons land in the window, the count
      drops below threshold and the suppression auto-lifts.
    - Coarse fingerprint by design: ``meta_goal_type`` is already in goal
      metadata, no model migration needed. A finer fingerprint (e.g.
      ``+ source_tension_category``) is a Phase 2 follow-up.
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
        abandon_threshold: int = DEFAULT_ABANDON_THRESHOLD,
        window_days: int = DEFAULT_WINDOW_DAYS,
    ):
        self._goal_store = goal_store
        self._threshold = max(1, int(abandon_threshold))
        self._window_days = max(1, int(window_days))

    def set_goal_store(self, store) -> None:
        """Late wiring (homeostasis init order)."""
        self._goal_store = store

    def detect(self, now: Optional[float] = None) -> LoopReport:
        """Compute suppression set from goal store history.

        Args:
            now: Override current time (for testing). Defaults to ``time.time()``.

        Returns:
            ``LoopReport`` with the suppressed meta-goal types and their counts.
            Empty report when goal_store is unavailable.
        """
        if self._goal_store is None:
            return LoopReport(set(), {}, self._window_days, self._threshold)

        now = now if now is not None else time.time()
        cutoff = now - self._window_days * 86400

        try:
            goals = self._goal_store.get_all()
        except Exception as e:
            logger.debug(f"[LoopDetector] get_all failed: {e}")
            return LoopReport(set(), {}, self._window_days, self._threshold)

        counts: Dict[str, int] = {}
        for g in goals:
            try:
                status_value = g.status.value if hasattr(g.status, "value") else str(g.status)
                if status_value != "abandoned":
                    continue
                if (g.created_by or "") != "creative":
                    continue
                # Use updated_at when available — the abandon timestamp is more
                # accurate than created_at for recency.
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

        suppressed = {
            fp for fp, n in counts.items() if n >= self._threshold
        }
        return LoopReport(
            suppressed_types=suppressed,
            counts=counts,
            window_days=self._window_days,
            threshold=self._threshold,
        )

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
