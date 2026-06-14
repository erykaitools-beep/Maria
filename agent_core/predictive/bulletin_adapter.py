"""SurpriseBulletinAdapter: predictive layer -> BulletinStore output sink.

The only sanctioned exit point of the predictive layer (B0/B0.1).
Constructs a single :py:class:`BulletinEntry` of type SURPRISE with the
payload schema from B0_IMPLEMENTATION_SHORTLIST rev 4 punkt 6, then
hands it to an injected :py:class:`BulletinStore.post`.

What this module does NOT do:
  - score / detect surprise (that is surprise_scorer.py)
  - calibrate thresholds (threshold_calibrator.py)
  - touch K7 / K9 / K10 / K12 -- consumers wire to the bulletin board
    on their own schedule (B4 stage and beyond)
  - execute any action -- bulletin emit only (decision: punkt 6 SHORTLIST)

The store is injected (not imported) so the adapter stays trivially
unit-testable with a fake bulletin sink.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from agent_core.bulletin.bulletin_model import (
    BulletinEntry,
    EntryStatus,
    EntryType,
)


# Reason codes correspond to the two B0 emit paths.
REASON_B0_GLOBAL = "predictive_b0_global"
REASON_B0_1_ACTION = "predictive_b0_1_action"

# requested_by tag for audit -- consistent across all surprise entries.
REQUESTED_BY = "predictive"


class SurpriseBulletinAdapter:
    """Emit a SURPRISE bulletin entry from a predictive surprise event.

    Stateless: holds only the injected post callable. Construction is
    cheap so callers may build per-tick if helpful.
    """

    def __init__(self, post_fn: Callable[[BulletinEntry], Any]):
        """post_fn is called with the constructed BulletinEntry.

        Production wiring: ``BulletinStore.post`` (instance method bound
        to the live store). Tests pass a lambda capturing into a list.
        """
        self._post = post_fn

    def emit_surprise(
        self,
        *,
        # Raw sub-scores (always present, decision #1)
        semantic_distance: float,
        numeric_distance: float,
        # Combined surprise (default max(z_semantic, z_numeric), decision #5b)
        combined_surprise: float,
        # Source path -- B0 global or B0.1 action-aware
        source: str,
        # Numeric features actually used (decision #9)
        numeric_features_used: List[str],
        # State summaries for audit
        state_t_summary: str,
        state_t1_summary: str,
        # B0.1-only: action context + z-scores (None for b0_global)
        action_type: Optional[str] = None,
        z_semantic: Optional[float] = None,
        z_numeric: Optional[float] = None,
        # Optional diagnostic (NOT a distance feature, decision #9)
        health_score: Optional[float] = None,
        # Tracing (ADR-022)
        episode_id: Optional[str] = None,
        # Override-able for deterministic tests
        timestamp: Optional[float] = None,
        priority: float = 0.5,
    ) -> BulletinEntry:
        """Build and post a SURPRISE BulletinEntry, return it for inspection.

        Validation:
          - source must be ``"b0_global"`` or ``"b0_1_action"``.
          - For ``"b0_1_action"`` the action_type, z_semantic, z_numeric
            triple is required (else ValueError) -- B0.1 contract is
            useless without per-action context.

        Returns the entry that was posted so the caller (typically the
        scorer) can log / trace it.
        """
        if source not in ("b0_global", "b0_1_action"):
            raise ValueError(
                f"source must be 'b0_global' or 'b0_1_action', got {source!r}"
            )
        if source == "b0_1_action":
            if action_type is None or z_semantic is None or z_numeric is None:
                raise ValueError(
                    "b0_1_action source requires action_type, z_semantic, z_numeric"
                )

        if timestamp is None:
            timestamp = time.time()

        reason_code = (
            REASON_B0_GLOBAL if source == "b0_global" else REASON_B0_1_ACTION
        )

        topic = _build_topic(source, action_type, combined_surprise)
        summary = _build_summary(
            source=source,
            action_type=action_type,
            semantic_distance=semantic_distance,
            numeric_distance=numeric_distance,
            combined_surprise=combined_surprise,
        )

        payload: Dict[str, Any] = {
            "semantic_distance": float(semantic_distance),
            "numeric_distance": float(numeric_distance),
            "combined_surprise": float(combined_surprise),
            "z_semantic": z_semantic,
            "z_numeric": z_numeric,
            "numeric_features_used": list(numeric_features_used),
            "health_score": health_score,
            "source": source,
            "action_type": action_type,
            "state_t_summary": state_t_summary,
            "state_t1_summary": state_t1_summary,
            "timestamp": float(timestamp),
            "episode_id": episode_id,
        }

        entry = BulletinEntry(
            entry_id=f"surp-{uuid.uuid4().hex[:12]}",
            goal_id=None,
            entry_type=EntryType.SURPRISE,
            priority=float(priority),
            status=EntryStatus.OPEN,
            topic=topic,
            reason_code=reason_code,
            summary=summary,
            requested_by=REQUESTED_BY,
            created_at=float(timestamp),
            updated_at=float(timestamp),
            metadata=payload,
        )

        self._post(entry)
        return entry


def _build_topic(
    source: str,
    action_type: Optional[str],
    combined_surprise: float,
) -> str:
    """Short identifier for the entry, useful for grep/dedup downstream."""
    if source == "b0_1_action" and action_type:
        return f"surprise:b0_1:{action_type}"
    return "surprise:b0_global"


def _build_summary(
    source: str,
    action_type: Optional[str],
    semantic_distance: float,
    numeric_distance: float,
    combined_surprise: float,
) -> str:
    """Human-readable one-liner, surfaced in cognitive_bulletin.jsonl."""
    if source == "b0_1_action":
        return (
            f"Action-aware surprise on '{action_type}': "
            f"combined={combined_surprise:.2f} "
            f"(sem={semantic_distance:.3f} num={numeric_distance:.3f})"
        )
    return (
        f"Global surprise: combined={combined_surprise:.2f} "
        f"(sem={semantic_distance:.3f} num={numeric_distance:.3f})"
    )
