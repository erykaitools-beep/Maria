"""Undo-suggestion monitor orchestration (autonomous SUGGEST side).

Mirrors ``agent_core/self_repair/monitor.py``: run the detector(s), gate each
candidate through ``UndoSuggestionCreator``, return created task IDs. The whole
subsystem is flag-gated (``EFFECTOR_UNDO_SUGGEST_ENABLED``, default OFF) so it
ships dark and is armed deliberately, observe-first.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, List, Optional

from agent_core.undo_suggest.detector import detect_orphaned_reversible_actions
from agent_core.undo_suggest.suggestion_creator import record_cooldown_active

logger = logging.getLogger("agent_core.undo_suggest")

# Modes in which a suggestion can actually become a task (mirrors the creator
# gate). Used to skip the expensive snapshot refresh in SLEEP/SURVIVAL.
_ELIGIBLE_MODES = ("ACTIVE", "REDUCED")


def undo_suggest_enabled() -> bool:
    """Autonomous undo-suggestion flag, default OFF (arm via .env)."""
    return os.environ.get("EFFECTOR_UNDO_SUGGEST_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


class UndoSuggestionMonitor:
    """Scan the undo journal for regret candidates and propose undos."""

    def __init__(
        self,
        self_perception: Any,
        conductor: Any,
        journal: Any,
        goal_store: Any,
        suggestion_creator: Any,
    ):
        self._self_perception = self_perception
        self._conductor = conductor
        self._journal = journal
        self._goal_store = goal_store
        self._creator = suggestion_creator
        if hasattr(suggestion_creator, "set_self_perception"):
            suggestion_creator.set_self_perception(self_perception)

    def scan_and_create(self) -> List[str]:
        """Run detector(s), gate candidates, return created task IDs.

        No-op (returns []) when the flag is off, so wiring it into the tick is
        harmless until armed. A glitch in any single step is contained -- the
        scan never raises into the tick loop.
        """
        if not undo_suggest_enabled():
            return []
        started = time.monotonic()
        try:
            candidates = detect_orphaned_reversible_actions(
                self._journal, self._goal_store, self._cooldown_lookup
            )
        except Exception:
            logger.warning("[UndoSuggest] detector failed", exc_info=True)
            return []

        if not candidates:
            return []

        # Mode gate UPSTREAM of the snapshot refresh (review F7): in SLEEP/SURVIVAL
        # the creator would refuse every candidate anyway (mode_not_eligible), so
        # refreshing the self-state snapshot first is pure churn (~every 10 min for
        # any standing orphan). Read the cheap cached mode; the creator gate stays
        # authoritative for the ACTIVE/REDUCED path.
        latest = (
            self._self_perception.get_latest()
            if self._self_perception is not None
            else None
        )
        mode = str(latest.get("mode", "")) if isinstance(latest, dict) else ""
        if mode not in _ELIGIBLE_MODES:
            return []

        # Mirror self-repair finding #4: the creator gate needs a snapshot
        # younger than 5 min, but Phase 18 only snapshots every ~30 min. Refresh
        # on demand ONLY when something fired, so a healthy/idle scan pays nothing.
        snapshot_id = self._refresh_snapshot()

        created: List[str] = []
        for candidate in candidates:
            try:
                task_id = self._creator.create(candidate, snapshot_id)
                if task_id:
                    created.append(task_id)
            except Exception:
                logger.warning(
                    "[UndoSuggest] suggestion creation failed for %s",
                    candidate.undo_record_id,
                    exc_info=True,
                )

        elapsed_ms = (time.monotonic() - started) * 1000
        if elapsed_ms > 500:
            logger.warning("[UndoSuggest] scan exceeded budget: %.1fms", elapsed_ms)
        return created

    def _refresh_snapshot(self) -> str:
        latest = (
            self._self_perception.get_latest()
            if self._self_perception is not None
            else None
        )
        if self._self_perception is not None and hasattr(
            self._self_perception, "take_snapshot"
        ):
            try:
                self._self_perception.take_snapshot()
                latest = self._self_perception.get_latest()
            except Exception:
                logger.warning(
                    "[UndoSuggest] on-demand snapshot refresh failed", exc_info=True
                )
        return str(latest.get("snapshot_id", "")) if isinstance(latest, dict) else ""

    def _cooldown_lookup(self, undo_record_id: str) -> bool:
        """True if an open/recent same-record proposal should suppress a new one.

        Delegates to the shared rule used by the creator gate, so the detector
        pre-filter and the authoritative gate cannot diverge (review F1/F2).
        """
        return record_cooldown_active(self._conductor, undo_record_id)
