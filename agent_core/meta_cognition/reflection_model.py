"""
Reflection Model - dataclasses for K9 Meta-Cognition.

Records decision assumptions + outcomes for self-reflection.
Kontrakt: docs/CONTRACTS.md - Kontrakt 9: Meta-Cognition
ADR-013: Rule-based, zero LLM, deterministic.
ADR-011: Reflections as data.
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Enums ──────────────────────────────────────────────


class AssumptionType(Enum):
    """Types of assumptions Maria can make before executing a plan."""
    TOPIC_LEARNABLE = "topic_learnable"
    EXAM_WILL_PASS = "exam_will_pass"
    FETCH_RELEVANT = "fetch_relevant"
    RETENTION_STABLE = "retention_stable"
    STRATEGY_EFFECTIVE = "strategy_effective"


class OutcomeMatch(Enum):
    """How well outcome matched expectation."""
    MATCH = "match"          # delta <= 0.15
    PARTIAL = "partial"      # delta 0.15 - 0.4
    MISMATCH = "mismatch"    # delta > 0.4
    UNKNOWN = "unknown"      # no numeric data


class LessonType(Enum):
    """Types of lessons learned from reflection."""
    WRONG_ASSUMPTION = "wrong_assumption"
    UNEXPECTED_SUCCESS = "unexpected_success"
    SLOW_EXECUTION = "slow_execution"
    PARTIAL_RESULT = "partial_result"


class Severity(Enum):
    """Lesson severity level."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class NeedHumanReason(Enum):
    """Reasons for signaling human intervention needed."""
    LOW_CONFIDENCE = "low_confidence"
    REPEATED_FAILURES = "repeated_failures"
    ASSUMPTION_DRIFT = "assumption_drift"


# ── Threshold constants for OutcomeMatch ───────────────

MATCH_THRESHOLD = 0.15      # |expected - actual| <= 0.15
PARTIAL_THRESHOLD = 0.4     # delta 0.15 - 0.4


# ── Dataclasses ────────────────────────────────────────


@dataclass
class Assumption:
    """A single assumption made before a decision."""
    assumption_type: AssumptionType
    description: str
    basis: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.assumption_type.value,
            "description": self.description,
            "basis": self.basis,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Assumption":
        return Assumption(
            assumption_type=AssumptionType(d["type"]),
            description=d["description"],
            basis=d.get("basis", ""),
        )


@dataclass
class Lesson:
    """A structured lesson learned from reflection."""
    lesson_type: LessonType
    assumption_type: Optional[AssumptionType]
    message: str
    severity: Severity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lesson_type": self.lesson_type.value,
            "assumption_type": (
                self.assumption_type.value if self.assumption_type else None
            ),
            "message": self.message,
            "severity": self.severity.value,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Lesson":
        at = d.get("assumption_type")
        return Lesson(
            lesson_type=LessonType(d["lesson_type"]),
            assumption_type=AssumptionType(at) if at else None,
            message=d["message"],
            severity=Severity(d.get("severity", "medium")),
        )


@dataclass
class Reflection:
    """
    A single reflection record: assumptions + expected outcome + actual outcome.

    Created in two phases:
    1. record_decision(): fills assumptions, expected_success, plan info
    2. reflect(): fills actual_success, outcome_match, lessons
    """
    reflection_id: str
    plan_id: str
    step_id: Optional[str]             # Future: one plan -> many steps -> many reflections
    action_type: str
    goal_id: Optional[str]
    topic: str

    # Phase 1 (before execution)
    assumptions: List[Assumption] = field(default_factory=list)
    expected_success: bool = True
    confidence_before: float = 0.5
    timestamp_started: float = 0.0

    # Phase 2 (after execution)
    actual_success: Optional[bool] = None
    outcome_match: OutcomeMatch = OutcomeMatch.UNKNOWN
    confidence_after: Optional[float] = None
    lessons: List[Lesson] = field(default_factory=list)
    timestamp_finished: Optional[float] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> Optional[float]:
        """Execution duration in milliseconds."""
        if self.timestamp_started and self.timestamp_finished:
            return (self.timestamp_finished - self.timestamp_started) * 1000
        return None

    @property
    def is_reflected(self) -> bool:
        """Whether phase 2 (reflect) has been completed."""
        return self.actual_success is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reflection_id": self.reflection_id,
            "plan_id": self.plan_id,
            "step_id": self.step_id,
            "action_type": self.action_type,
            "goal_id": self.goal_id,
            "topic": self.topic,
            "assumptions": [a.to_dict() for a in self.assumptions],
            "expected_success": self.expected_success,
            "confidence_before": self.confidence_before,
            "timestamp_started": self.timestamp_started,
            "actual_success": self.actual_success,
            "outcome_match": self.outcome_match.value,
            "confidence_after": self.confidence_after,
            "lessons": [l.to_dict() for l in self.lessons],
            "timestamp_finished": self.timestamp_finished,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Reflection":
        return Reflection(
            reflection_id=d["reflection_id"],
            plan_id=d["plan_id"],
            step_id=d.get("step_id"),
            action_type=d["action_type"],
            goal_id=d.get("goal_id"),
            topic=d.get("topic", ""),
            assumptions=[
                Assumption.from_dict(a) for a in d.get("assumptions", [])
            ],
            expected_success=d.get("expected_success", True),
            confidence_before=d.get("confidence_before", 0.5),
            timestamp_started=d.get("timestamp_started", 0.0),
            actual_success=d.get("actual_success"),
            outcome_match=OutcomeMatch(d.get("outcome_match", "unknown")),
            confidence_after=d.get("confidence_after"),
            lessons=[Lesson.from_dict(l) for l in d.get("lessons", [])],
            timestamp_finished=d.get("timestamp_finished"),
            metadata=d.get("metadata", {}),
        )


def create_reflection(
    plan_id: str,
    action_type: str,
    goal_id: Optional[str] = None,
    step_id: Optional[str] = None,
    topic: str = "",
    assumptions: Optional[List[Assumption]] = None,
    expected_success: bool = True,
    confidence_before: float = 0.5,
    metadata: Optional[Dict[str, Any]] = None,
) -> Reflection:
    """Factory function for creating a Reflection (Phase 1)."""
    return Reflection(
        reflection_id=f"refl-{uuid.uuid4().hex[:12]}",
        plan_id=plan_id,
        step_id=step_id,
        action_type=action_type,
        goal_id=goal_id,
        topic=topic,
        assumptions=assumptions or [],
        expected_success=expected_success,
        confidence_before=confidence_before,
        timestamp_started=time.time(),
        metadata=metadata or {},
    )


def determine_outcome_match(
    expected_score: Optional[float],
    actual_score: Optional[float],
    expected_success: bool,
    actual_success: bool,
) -> OutcomeMatch:
    """
    Determine OutcomeMatch using threshold logic.

    If numeric scores available:
      MATCH: |expected - actual| <= 0.15
      PARTIAL: delta 0.15 - 0.4
      MISMATCH: delta > 0.4

    Fallback (no numeric scores):
      MATCH: expected_success == actual_success
      MISMATCH: expected_success != actual_success
    """
    if expected_score is not None and actual_score is not None:
        delta = abs(expected_score - actual_score)
        if delta <= MATCH_THRESHOLD:
            return OutcomeMatch.MATCH
        elif delta <= PARTIAL_THRESHOLD:
            return OutcomeMatch.PARTIAL
        else:
            return OutcomeMatch.MISMATCH

    # Fallback: boolean comparison
    if expected_success == actual_success:
        return OutcomeMatch.MATCH
    else:
        return OutcomeMatch.MISMATCH
