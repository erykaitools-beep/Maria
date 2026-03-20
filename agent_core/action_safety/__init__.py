"""
K10 Action Safety Layer for M.A.R.I.A.

Unified action audit, effect validation, and safety classification.
Generalizes K2 Sandbox pattern to all action types.

Pipeline (in PlannerCore._finalize_plan):
    1. BEFORE exec: action_safety.before_action(plan_id, action_type, ...)
    2. executor.execute(plan)
    3. AFTER exec:  action_safety.after_action(plan_id, success, result)

Usage:
    from agent_core.action_safety import ActionSafety

    safety = ActionSafety()
    mode = safety.before_action("plan-1", "fetch", {"max_articles": 3})
    # ... execute action ...
    validation = safety.after_action("plan-1", True, {"articles_fetched": 3})

Kontrakt: docs/CONTRACTS.md - Kontrakt 10: Action Safety
ADR-013: Rule-based, zero LLM, deterministic, testable.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.action_safety.safety_model import (
    ActionRecord,
    SafetyMode,
    StateSnapshot,
    ValidationResult,
    create_action_record,
)
from agent_core.action_safety.safety_classifier import get_safety_profile
from agent_core.action_safety.audit_log import AuditLog
from agent_core.action_safety.effect_validator import EffectValidator

logger = logging.getLogger(__name__)


class ActionSafety:
    """
    K10 Action Safety Layer facade.

    Sits between K7 check and ActionExecutor.execute() in _finalize_plan().

    v1: AUTO_COMMIT and AUDIT_ONLY modes only.
    v2 path: STAGED mode with HITL approval queue for Smart Home/Code Agent.
    """

    def __init__(
        self,
        audit_log: Optional[AuditLog] = None,
        effect_validator: Optional[EffectValidator] = None,
        log_path: Optional[Path] = None,
    ):
        self._audit = audit_log or AuditLog(path=log_path)
        self._validator = effect_validator or EffectValidator()
        self._pending: Dict[str, ActionRecord] = {}  # plan_id -> in-progress

    # -- Dependency forwarding ------------------------------------

    def set_goal_store(self, store) -> None:
        self._validator.set_goal_store(store)

    def set_knowledge_analyzer(self, analyzer) -> None:
        self._validator.set_knowledge_analyzer(analyzer)

    def set_homeostasis_core(self, core) -> None:
        self._validator.set_homeostasis_core(core)

    # -- Main API -------------------------------------------------

    def before_action(
        self,
        plan_id: str,
        action_type: str,
        action_params: Optional[Dict[str, Any]] = None,
        goal_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SafetyMode:
        """
        Phase 1: Classify action, capture before-state, create pending record.

        Returns SafetyMode so the caller knows how to proceed:
        - AUTO_COMMIT / AUDIT_ONLY: proceed with execution
        - STAGED: do NOT execute (v2: queue for approval)
        """
        profile = get_safety_profile(action_type)

        # Capture before-state if profile requires it
        before_state = None
        if profile.needs_before_snapshot:
            before_state = self._validator.capture_state(action_type)

        # Create pending record
        record = create_action_record(
            plan_id=plan_id,
            action_type=action_type,
            profile=profile,
            action_params=action_params,
            before_state=before_state,
            goal_id=goal_id,
            metadata=metadata,
        )
        self._pending[plan_id] = record

        logger.debug(
            f"[K10] before_action: {action_type} "
            f"mode={profile.safety_mode.value} "
            f"snapshot={'yes' if before_state else 'no'}"
        )

        return profile.safety_mode

    def after_action(
        self,
        plan_id: str,
        success: bool,
        result: Optional[Dict[str, Any]] = None,
        duration_ms: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Phase 2: Capture after-state, validate effects, write audit record.

        Returns validation summary:
            {"validation": "valid"/"unexpected"/"skipped", "details": {...}}
        """
        record = self._pending.pop(plan_id, None)
        if record is None:
            # No pending record (before_action was not called or already completed)
            return {"validation": "skipped", "details": {}}

        record.success = success
        record.duration_ms = duration_ms

        profile = get_safety_profile(record.action_type)
        validation = ValidationResult.SKIPPED
        validation_details: Dict[str, Any] = {}

        # Capture after-state and validate if profile requires it
        if profile.needs_after_snapshot and record.before_state:
            after_state = self._validator.capture_state(record.action_type)
            record.after_state = after_state.to_dict()

            before_snapshot = StateSnapshot.from_dict(record.before_state)
            validation, validation_details = self._validator.validate_effects(
                action_type=record.action_type,
                before=before_snapshot,
                after=after_state,
                result=result or {},
            )

        record.validation = validation.value
        record.validation_details = validation_details
        record.rollback_available = (
            profile.reversibility.value != "irreversible"
        )

        # Write to audit log
        self._audit.record(record)

        logger.debug(
            f"[K10] after_action: {record.action_type} "
            f"success={success} validation={validation.value}"
        )

        return {
            "validation": validation.value,
            "details": validation_details,
        }

    def is_staged(self, action_type: str) -> bool:
        """Quick check if action type requires staging (v2: HITL approval)."""
        profile = get_safety_profile(action_type)
        return profile.safety_mode == SafetyMode.STAGED

    # -- Query API ------------------------------------------------

    def get_audit_stats(self) -> Dict[str, Any]:
        """Get summary stats from audit log."""
        return self._audit.get_stats()

    def get_recent_records(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent audit records."""
        return self._audit.get_recent(limit=limit)

    def get_status(self) -> Dict[str, Any]:
        """Status dict for REPL / Web UI."""
        stats = self._audit.get_stats()
        return {
            "total_records": stats.get("total", 0),
            "pending_actions": len(self._pending),
            "by_action_type": stats.get("by_action_type", {}),
            "by_safety_mode": stats.get("by_safety_mode", {}),
            "by_validation": stats.get("by_validation", {}),
            "success": stats.get("success", 0),
            "failed": stats.get("failed", 0),
        }
