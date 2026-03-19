"""
Strategy and Step dataclasses for K8 Deliberation.

A Strategy is a multi-step plan for achieving a goal.
v1: sequential list of Steps with success/fail conditions.
v2 path: DAG with step.next_on_success / step.next_on_fail.

Kontrakt: docs/CONTRACTS.md - Kontrakt 8: Deliberation
ADR-013: Rule-based, zero LLM, deterministic, testable.
ADR-011: Strategies as data (not hardcoded logic).
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class StepStatus(Enum):
    """Status of a single step in a strategy."""
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepOutcome(Enum):
    """
    Outcome condition for step transitions.

    v1: simple enum.
    v2 path: expressions like "confidence > 0.7".
    """
    PASS = "pass"          # Action succeeded (e.g. exam passed)
    FAIL = "fail"          # Action failed
    TIMEOUT = "timeout"    # Step took too long
    ANY = "any"            # Always matches (unconditional transition)


class StrategyStatus(Enum):
    """Status of a strategy."""
    ACTIVE = "active"
    PAUSED = "paused"        # Temporarily stopped (mode change, etc.)
    COMPLETED = "completed"  # All steps done successfully
    ABANDONED = "abandoned"  # Gave up (too many failures, goal cancelled)


@dataclass
class Step:
    """
    A single step in a strategy.

    Each step maps to one ActionType execution.
    """
    step_id: str
    order: int                          # Position in sequence (0-based)
    action_type: str                    # ActionType.value (e.g. "learn", "exam")
    action_params: Dict[str, Any] = field(default_factory=dict)
    description: str = ""               # Human-readable (e.g. "Egzamin z tematu")
    status: StepStatus = StepStatus.PENDING
    max_retries: int = 1                # How many times to retry on fail
    retries_used: int = 0
    result: Dict[str, Any] = field(default_factory=dict)
    completed_at: Optional[float] = None

    # Transition rules (v1: simple, v2 path: expressions)
    on_success: StepOutcome = StepOutcome.PASS  # What counts as success
    fallback_step_order: Optional[int] = None   # On fail, jump to this step (v1)

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "order": self.order,
            "action_type": self.action_type,
            "action_params": self.action_params,
            "description": self.description,
            "status": self.status.value,
            "max_retries": self.max_retries,
            "retries_used": self.retries_used,
            "result": self.result,
            "completed_at": self.completed_at,
            "on_success": self.on_success.value,
            "fallback_step_order": self.fallback_step_order,
        }

    @staticmethod
    def from_dict(d: dict) -> "Step":
        return Step(
            step_id=d["step_id"],
            order=d["order"],
            action_type=d["action_type"],
            action_params=d.get("action_params", {}),
            description=d.get("description", ""),
            status=StepStatus(d.get("status", "pending")),
            max_retries=d.get("max_retries", 1),
            retries_used=d.get("retries_used", 0),
            result=d.get("result", {}),
            completed_at=d.get("completed_at"),
            on_success=StepOutcome(d.get("on_success", "pass")),
            fallback_step_order=d.get("fallback_step_order"),
        )


@dataclass
class Strategy:
    """
    A multi-step plan for achieving a goal.

    v1: sequential steps with optional fallback jumps.
    v2 path: DAG structure via step.next_on_success / step.next_on_fail.
    """
    strategy_id: str
    goal_id: str                        # Which goal this strategy serves
    template_name: str                  # Which template created this
    status: StrategyStatus = StrategyStatus.ACTIVE
    steps: List[Step] = field(default_factory=list)
    current_step_order: int = 0         # Which step we're on
    created_at: float = 0.0
    updated_at: float = 0.0
    intent: str = ""                    # Why this strategy was chosen
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def current_step(self) -> Optional[Step]:
        """Get the current active step, or None if strategy is done."""
        for step in self.steps:
            if step.order == self.current_step_order:
                return step
        return None

    @property
    def is_terminal(self) -> bool:
        return self.status in (StrategyStatus.COMPLETED, StrategyStatus.ABANDONED)

    @property
    def progress(self) -> float:
        """Fraction of steps completed (0.0 to 1.0)."""
        if not self.steps:
            return 0.0
        completed = sum(1 for s in self.steps if s.status == StepStatus.COMPLETED)
        return completed / len(self.steps)

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "goal_id": self.goal_id,
            "template_name": self.template_name,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "current_step_order": self.current_step_order,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "intent": self.intent,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(d: dict) -> "Strategy":
        return Strategy(
            strategy_id=d["strategy_id"],
            goal_id=d["goal_id"],
            template_name=d.get("template_name", ""),
            status=StrategyStatus(d.get("status", "active")),
            steps=[Step.from_dict(s) for s in d.get("steps", [])],
            current_step_order=d.get("current_step_order", 0),
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
            intent=d.get("intent", ""),
            metadata=d.get("metadata", {}),
        )


def create_step(
    order: int,
    action_type: str,
    description: str = "",
    action_params: Optional[Dict[str, Any]] = None,
    max_retries: int = 1,
    fallback_step_order: Optional[int] = None,
) -> Step:
    """Factory for creating a Step."""
    return Step(
        step_id=f"step-{uuid.uuid4().hex[:8]}",
        order=order,
        action_type=action_type,
        description=description,
        action_params=action_params or {},
        max_retries=max_retries,
        fallback_step_order=fallback_step_order,
    )


def create_strategy(
    goal_id: str,
    template_name: str,
    steps: List[Step],
    intent: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Strategy:
    """Factory for creating a Strategy."""
    now = time.time()
    return Strategy(
        strategy_id=f"strat-{uuid.uuid4().hex[:12]}",
        goal_id=goal_id,
        template_name=template_name,
        steps=steps,
        intent=intent,
        created_at=now,
        updated_at=now,
        metadata=metadata or {},
    )
