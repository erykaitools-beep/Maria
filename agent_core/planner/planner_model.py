"""
Planner Model - dataclasses for Planner decisions.

Kontrakt: docs/CONTRACTS.md - Kontrakt 5: Planner
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class PlanStatus(Enum):
    """Status of a plan."""
    PENDING = "pending"          # Created, not yet executed
    EXECUTING = "executing"      # Currently being executed
    COMPLETED = "completed"      # Executed successfully
    FAILED = "failed"            # Execution failed
    SKIPPED = "skipped"          # Skipped by guard
    AWAITING_APPROVAL = "awaiting_approval"  # Phase 5: waiting for operator


class ActionType(Enum):
    """Type of action the planner can delegate."""
    LEARN = "learn"              # Delegate to Teacher -> learn chunk
    EXAM = "exam"                # Delegate to Teacher -> run exam
    REVIEW = "review"            # Delegate to Teacher -> spaced repetition
    EVALUATE = "evaluate"        # Trigger EvaluationObserver report
    MAINTENANCE = "maintenance"  # Maintenance action (update goal progress)
    NOOP = "noop"                # Nothing to do (idle)
    FETCH = "fetch"              # Fetch web content (agent_core/web_source/)
    EXPERIMENT = "experiment"    # K11: Run parameter experiment
    EFFECTOR = "effector"        # Execute via OpenClaw tools (ADR-016)
    SELF_ANALYZE = "self_analyze"  # K12: Self-analysis cognitive loop
    CREATIVE = "creative"        # K13: Creative reflection cycle
    ASK_EXPERT = "ask_expert"    # Ask ChatGPT/Codex for knowledge (encyclopedia)
    VALIDATE = "validate"        # Cross-validate learned knowledge (Faza F)


@dataclass
class Plan:
    """
    A single-step plan from one planner cycle.

    v1 is deliberately simple: one goal, one action, one result.
    No tree/graph structure. KISS principle.
    """
    plan_id: str
    timestamp: float
    goal_id: Optional[str]         # Which goal this plan serves
    goal_description: str          # Human-readable (for logging)
    action_type: ActionType
    action_params: Dict[str, Any]  # Parameters for the executor
    status: PlanStatus
    result: Dict[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None  # Optional correlation id
    duration_ms: float = 0.0
    message: str = ""               # Human-readable decision message
    metadata: Dict[str, Any] = field(default_factory=dict)  # K8: strategy_id, step_order

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "timestamp": self.timestamp,
            "goal_id": self.goal_id,
            "goal_description": self.goal_description,
            "action_type": self.action_type.value,
            "action_params": self.action_params,
            "status": self.status.value,
            "result": self.result,
            "trace_id": self.trace_id,
            "duration_ms": self.duration_ms,
            "message": self.message,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(d: dict) -> "Plan":
        return Plan(
            plan_id=d["plan_id"],
            timestamp=d["timestamp"],
            goal_id=d.get("goal_id"),
            goal_description=d.get("goal_description", ""),
            action_type=ActionType(d["action_type"]),
            action_params=d.get("action_params", {}),
            status=PlanStatus(d["status"]),
            result=d.get("result", {}),
            trace_id=d.get("trace_id"),
            duration_ms=d.get("duration_ms", 0.0),
            message=d.get("message", ""),
            metadata=d.get("metadata", {}),
        )


def create_plan(
    goal_id: Optional[str],
    goal_description: str,
    action_type: ActionType,
    action_params: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Plan:
    """Factory function for creating a Plan."""
    return Plan(
        plan_id=f"plan-{uuid.uuid4().hex[:12]}",
        timestamp=time.time(),
        goal_id=goal_id,
        goal_description=goal_description,
        action_type=action_type,
        action_params=action_params or {},
        status=PlanStatus.PENDING,
        trace_id=trace_id,
        metadata=metadata or {},
    )


@dataclass
class PlannerState:
    """
    Persistent planner state (saved to planner_state.json).

    Tracks current cycle info and cooldowns.
    """
    last_cycle_tick: int = 0
    last_evaluation_ts: float = 0.0        # Last EvaluationObserver report
    last_recommendation_ts: float = 0.0    # Last acted-on recommendation
    last_self_analysis_ts: float = 0.0     # K12: Last self-analysis cycle
    total_cycles: int = 0
    total_plans_executed: int = 0
    current_plan_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "last_cycle_tick": self.last_cycle_tick,
            "last_evaluation_ts": self.last_evaluation_ts,
            "last_recommendation_ts": self.last_recommendation_ts,
            "last_self_analysis_ts": self.last_self_analysis_ts,
            "total_cycles": self.total_cycles,
            "total_plans_executed": self.total_plans_executed,
            "current_plan_id": self.current_plan_id,
        }

    @staticmethod
    def from_dict(d: dict) -> "PlannerState":
        return PlannerState(
            last_cycle_tick=d.get("last_cycle_tick", 0),
            last_evaluation_ts=d.get("last_evaluation_ts", 0.0),
            last_recommendation_ts=d.get("last_recommendation_ts", 0.0),
            last_self_analysis_ts=d.get("last_self_analysis_ts", 0.0),
            total_cycles=d.get("total_cycles", 0),
            total_plans_executed=d.get("total_plans_executed", 0),
            current_plan_id=d.get("current_plan_id"),
        )
