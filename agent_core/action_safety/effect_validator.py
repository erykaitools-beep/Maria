"""
EffectValidator - Before/after state capture and comparison.

Captures system state snapshots and validates that action effects
match expectations. v1: simple numeric diffs.

Kontrakt: docs/CONTRACTS.md - Kontrakt 10: Action Safety
ADR-013: Rule-based, zero LLM, deterministic.
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from agent_core.action_safety.safety_model import (
    StateSnapshot,
    ValidationResult,
)

logger = logging.getLogger(__name__)

# Validation thresholds
HEALTH_DROP_THRESHOLD = 0.3     # Health drop > 0.3 = UNEXPECTED
MAX_GOAL_INCREASE = 5           # Goals increasing by > 5 in one action = UNEXPECTED

# Input directory for file counting
_INPUT_DIR = Path(__file__).resolve().parents[2] / "input"


class EffectValidator:
    """
    Captures before/after state snapshots and validates action effects.

    v1: simple numeric diff (file counts, goal counts, health delta).
    v2 path: per-action-type validation rules, rollback handlers.
    """

    def __init__(self):
        self._goal_store = None
        self._knowledge_analyzer = None
        self._homeostasis_core = None

    def set_goal_store(self, store) -> None:
        self._goal_store = store

    def set_knowledge_analyzer(self, analyzer) -> None:
        self._knowledge_analyzer = analyzer

    def set_homeostasis_core(self, core) -> None:
        self._homeostasis_core = core

    def capture_state(self, action_type: str = "") -> StateSnapshot:
        """
        Capture current system state relevant to the action type.

        For AUDIT_ONLY/STAGED actions, captures:
        - input/ file count (for fetch)
        - active goal count (for maintenance)
        - health score and mode
        - knowledge file count
        """
        snapshot = StateSnapshot(timestamp=time.time())

        # Health and mode from homeostasis
        if self._homeostasis_core:
            try:
                state = self._homeostasis_core.get_state()
                snapshot.health_score = state.health_score
                snapshot.mode = state.mode.value
            except Exception:
                pass

        # Active goal count
        if self._goal_store:
            try:
                active = self._goal_store.get_active()
                snapshot.goal_active_count = len(active)
            except Exception:
                pass

        # Knowledge file count
        if self._knowledge_analyzer:
            try:
                ks = self._knowledge_analyzer.get_knowledge_snapshot()
                total = sum(
                    len(files)
                    for files in ks.get("files_by_status", {}).values()
                )
                snapshot.knowledge_file_count = total
            except Exception:
                pass

        # Input directory file count
        try:
            if _INPUT_DIR.exists():
                snapshot.input_file_count = sum(
                    1 for f in _INPUT_DIR.iterdir() if f.is_file()
                )
        except Exception:
            pass

        return snapshot

    def validate_effects(
        self,
        action_type: str,
        before: StateSnapshot,
        after: StateSnapshot,
        result: Dict[str, Any],
    ) -> Tuple[ValidationResult, Dict[str, Any]]:
        """
        Compare before/after state and validate effects.

        Returns (ValidationResult, details_dict).

        v1 rules:
        - fetch: input_file_count should not decrease
        - maintenance: goal count should not increase dramatically
        - any: health_score drop > 0.3 = UNEXPECTED
        - none/knowledge: SKIPPED
        """
        details: Dict[str, Any] = {}

        # Actions without side effects -> SKIPPED
        if action_type in ("noop", "evaluate", "learn", "exam", "review"):
            return ValidationResult.SKIPPED, details

        unexpected = False

        # Health drop check (all audited actions)
        health_delta = before.health_score - after.health_score
        details["health_delta"] = round(health_delta, 3)
        if health_delta > HEALTH_DROP_THRESHOLD:
            unexpected = True
            details["health_drop_unexpected"] = True

        # Fetch-specific: input files should not decrease
        if action_type == "fetch":
            files_delta = after.input_file_count - before.input_file_count
            details["input_files_delta"] = files_delta
            if files_delta < 0:
                unexpected = True
                details["input_files_decreased"] = True

        # Maintenance-specific: goal count should not explode
        if action_type == "maintenance":
            goal_delta = after.goal_active_count - before.goal_active_count
            details["goal_count_delta"] = goal_delta
            if goal_delta > MAX_GOAL_INCREASE:
                unexpected = True
                details["goal_count_explosion"] = True

        # Phase 5: Effector-specific validation
        if action_type == "effector":
            tool_name = result.get("tool_name", "")
            details["tool_name"] = tool_name
            success = result.get("success", False)
            tool_result = result.get("tool_result")

            # Empty result on reported success = suspicious
            if success and (tool_result is None or tool_result == ""):
                unexpected = True
                details["empty_result_on_success"] = True

            # Check for error indicators in result
            error = result.get("error", "")
            if error and success:
                unexpected = True
                details["error_on_success"] = str(error)[:200]

        # B2: filesystem write -- re-stat the target (the real external check:
        # "did the file the action claims to have written actually appear?").
        if action_type == "fs_write":
            path = result.get("path")
            success = result.get("success", False)
            exists = bool(path) and Path(path).is_file()
            details["path"] = path
            details["file_exists"] = exists
            details["size"] = result.get("size")
            if success and not exists:
                unexpected = True
                details["file_missing_on_success"] = True

        if unexpected:
            return ValidationResult.UNEXPECTED, details

        return ValidationResult.VALID, details
