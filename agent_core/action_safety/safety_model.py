"""
Safety Model - dataclasses for K10 Action Safety Layer.

Unified audit records for all action executions.
Kontrakt: docs/CONTRACTS.md - Kontrakt 10: Action Safety
ADR-013: Rule-based, zero LLM, deterministic.
ADR-011: Data as structure.
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


# -- Enums --------------------------------------------------------


class SafetyMode(Enum):
    """How an action is executed from a safety perspective."""
    AUTO_COMMIT = "auto_commit"    # Execute immediately, log after (safe actions)
    AUDIT_ONLY = "audit_only"      # Execute + log with before/after state
    STAGED = "staged"              # Require approval before commit (future HITL)


class Reversibility(Enum):
    """Whether an action's effects can be undone."""
    REVERSIBLE = "reversible"
    PARTIALLY_REVERSIBLE = "partial"
    IRREVERSIBLE = "irreversible"


class EffectType(Enum):
    """Category of side effect an action produces."""
    NONE = "none"                  # NOOP, EVALUATE (read-only)
    KNOWLEDGE = "knowledge"        # LEARN, EXAM, REVIEW (sandboxed by K2)
    FILESYSTEM = "filesystem"      # FETCH (writes to input/)
    GOAL_STATE = "goal_state"      # MAINTENANCE (modifies goal progress)
    EXTERNAL_API = "external_api"  # FETCH (HTTP calls), future: smart home
    DEVICE = "device"              # Future: smart home physical actions
    CONFIGURATION = "configuration"  # K11: temporary parameter override


class ValidationResult(Enum):
    """Outcome of effect validation."""
    VALID = "valid"                # Effects match expectation
    UNEXPECTED = "unexpected"      # Effects differ from expectation
    SKIPPED = "skipped"            # No validation possible


# -- Dataclasses --------------------------------------------------


@dataclass
class StateSnapshot:
    """Compact snapshot of relevant system state before/after action."""
    timestamp: float = 0.0
    knowledge_file_count: int = 0
    goal_active_count: int = 0
    input_file_count: int = 0
    health_score: float = 1.0
    mode: str = "active"
    custom: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "knowledge_file_count": self.knowledge_file_count,
            "goal_active_count": self.goal_active_count,
            "input_file_count": self.input_file_count,
            "health_score": self.health_score,
            "mode": self.mode,
            "custom": self.custom,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "StateSnapshot":
        return StateSnapshot(
            timestamp=d.get("timestamp", 0.0),
            knowledge_file_count=d.get("knowledge_file_count", 0),
            goal_active_count=d.get("goal_active_count", 0),
            input_file_count=d.get("input_file_count", 0),
            health_score=d.get("health_score", 1.0),
            mode=d.get("mode", "active"),
            custom=d.get("custom", {}),
        )


@dataclass(frozen=True)
class SafetyProfile:
    """Safety properties for an action type."""
    safety_mode: SafetyMode
    reversibility: Reversibility
    effect_type: EffectType
    needs_before_snapshot: bool
    needs_after_snapshot: bool


@dataclass
class ActionRecord:
    """
    Complete audit record for one action execution.

    Created by before_action(), completed by after_action().
    Persisted to action_audit.jsonl.
    """
    record_id: str
    plan_id: str
    action_type: str
    safety_mode: str           # SafetyMode.value
    reversibility: str         # Reversibility.value
    effect_type: str           # EffectType.value
    action_params: Dict[str, Any]
    goal_id: Optional[str]

    # State snapshots
    before_state: Optional[Dict[str, Any]] = None
    after_state: Optional[Dict[str, Any]] = None

    # Outcome
    success: Optional[bool] = None
    validation: str = "skipped"    # ValidationResult.value
    validation_details: Dict[str, Any] = field(default_factory=dict)
    rollback_available: bool = False

    # Timing
    timestamp: float = 0.0
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "plan_id": self.plan_id,
            "action_type": self.action_type,
            "safety_mode": self.safety_mode,
            "reversibility": self.reversibility,
            "effect_type": self.effect_type,
            "action_params": self.action_params,
            "goal_id": self.goal_id,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "success": self.success,
            "validation": self.validation,
            "validation_details": self.validation_details,
            "rollback_available": self.rollback_available,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ActionRecord":
        return ActionRecord(
            record_id=d["record_id"],
            plan_id=d["plan_id"],
            action_type=d["action_type"],
            safety_mode=d.get("safety_mode", "auto_commit"),
            reversibility=d.get("reversibility", "reversible"),
            effect_type=d.get("effect_type", "none"),
            action_params=d.get("action_params", {}),
            goal_id=d.get("goal_id"),
            before_state=d.get("before_state"),
            after_state=d.get("after_state"),
            success=d.get("success"),
            validation=d.get("validation", "skipped"),
            validation_details=d.get("validation_details", {}),
            rollback_available=d.get("rollback_available", False),
            timestamp=d.get("timestamp", 0.0),
            duration_ms=d.get("duration_ms", 0.0),
            metadata=d.get("metadata", {}),
        )


def create_action_record(
    plan_id: str,
    action_type: str,
    profile: SafetyProfile,
    action_params: Optional[Dict[str, Any]] = None,
    before_state: Optional[StateSnapshot] = None,
    goal_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> ActionRecord:
    """Factory function for creating an ActionRecord."""
    return ActionRecord(
        record_id=f"arec-{uuid.uuid4().hex[:12]}",
        plan_id=plan_id,
        action_type=action_type,
        safety_mode=profile.safety_mode.value,
        reversibility=profile.reversibility.value,
        effect_type=profile.effect_type.value,
        action_params=action_params or {},
        goal_id=goal_id,
        before_state=before_state.to_dict() if before_state else None,
        timestamp=time.time(),
        metadata=metadata or {},
    )
