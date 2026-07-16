"""
Planner Model - dataclasses for Planner decisions.

Kontrakt: docs/CONTRACTS.md - Kontrakt 5: Planner
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


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
    CRITIQUE = "critique"        # Faza G: Knowledge quality gate
    FS_WRITE = "fs_write"        # B2: first real effector primitive (sandboxed file write)
    PLAY = "play"                # Self-time: ungraded free musing ("spacer po wlasnej glowie")


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
    last_validation_ts: float = 0.0       # Faza F: Last cross-validation cycle
    last_critique_ts: float = 0.0         # Faza G: Last knowledge critique
    last_experiment_scan_ts: float = 0.0  # K11: Last experiment proposal scan
    last_belief_build_ts: float = 0.0     # K6: Throttle periodic rebuilds
    last_belief_maintenance_ts: float = 0.0  # K6: Throttle maintain() after EVALUATE
    total_cycles: int = 0
    total_plans_executed: int = 0
    consecutive_noop_count: int = 0         # Backoff: NOOPs in a row
    current_plan_id: Optional[str] = None
    # Stuck detection: track recent failure fingerprints
    stuck_history: List[Dict[str, str]] = field(default_factory=list)
    stuck_cooldowns: Dict[str, float] = field(default_factory=dict)  # goal_id -> until_ts
    # Non-productive loop detection: same goal + same reflection action repeated
    # without progress. COMPLETED doesn't touch stuck_history, so meta-goals
    # without decomposable steps can lock in evaluate/critique loops unnoticed.
    last_goal_action_key: Optional[str] = None   # f"{goal_id}:{action_type}"
    goal_action_repeat_count: int = 0
    # B4 (T-B4-001): track productive-action cycles per goal. Counter
    # increments on every plan executed for a goal_id; resets on any plan
    # that produces measurable progress. Triggers K12 IMPROVEMENT advisory
    # when GOAL_CYCLE_THRESHOLD is reached.
    actions_since_progress: Dict[str, int] = field(default_factory=dict)
    last_creative_ts: float = 0.0    # K13 creative reflection cooldown
    last_play_ts: float = 0.0        # Self-time (PLAY) cooldown
    # 8b rhythm/budget: cap on learn-family actions executed OUTSIDE the
    # learning window per day. Replaces the all-or-nothing window block so the
    # organism still learns a little on weekends/nights, while the daily cap
    # preserves the original throttle (the window stopped ~791 unproductive
    # learn attempts in 72h, glm-5.1 test 2026-04-21).
    off_window_learn_date: str = ""   # YYYY-MM-DD of the current budget day
    off_window_learn_used: int = 0    # learn-family actions used off-window today

    def to_dict(self) -> dict:
        return {
            "last_cycle_tick": self.last_cycle_tick,
            "last_evaluation_ts": self.last_evaluation_ts,
            "last_recommendation_ts": self.last_recommendation_ts,
            "last_self_analysis_ts": self.last_self_analysis_ts,
            "last_validation_ts": self.last_validation_ts,
            "last_critique_ts": self.last_critique_ts,
            "last_experiment_scan_ts": self.last_experiment_scan_ts,
            "last_belief_build_ts": self.last_belief_build_ts,
            "last_belief_maintenance_ts": self.last_belief_maintenance_ts,
            "total_cycles": self.total_cycles,
            "total_plans_executed": self.total_plans_executed,
            "consecutive_noop_count": self.consecutive_noop_count,
            "current_plan_id": self.current_plan_id,
            "stuck_history": self.stuck_history,
            "stuck_cooldowns": self.stuck_cooldowns,
            "last_goal_action_key": self.last_goal_action_key,
            "goal_action_repeat_count": self.goal_action_repeat_count,
            "actions_since_progress": dict(self.actions_since_progress),
            "last_creative_ts": self.last_creative_ts,
            "last_play_ts": self.last_play_ts,
            "off_window_learn_date": self.off_window_learn_date,
            "off_window_learn_used": self.off_window_learn_used,
        }

    @staticmethod
    def from_dict(d: dict) -> "PlannerState":
        return PlannerState(
            last_cycle_tick=d.get("last_cycle_tick", 0),
            last_evaluation_ts=d.get("last_evaluation_ts", 0.0),
            last_recommendation_ts=d.get("last_recommendation_ts", 0.0),
            last_self_analysis_ts=d.get("last_self_analysis_ts", 0.0),
            last_validation_ts=d.get("last_validation_ts", 0.0),
            last_critique_ts=d.get("last_critique_ts", 0.0),
            last_experiment_scan_ts=d.get("last_experiment_scan_ts", 0.0),
            last_belief_build_ts=d.get("last_belief_build_ts", 0.0),
            last_belief_maintenance_ts=d.get("last_belief_maintenance_ts", 0.0),
            total_cycles=d.get("total_cycles", 0),
            total_plans_executed=d.get("total_plans_executed", 0),
            consecutive_noop_count=d.get("consecutive_noop_count", 0),
            current_plan_id=d.get("current_plan_id"),
            stuck_history=d.get("stuck_history", []),
            stuck_cooldowns=d.get("stuck_cooldowns", {}),
            last_goal_action_key=d.get("last_goal_action_key"),
            goal_action_repeat_count=d.get("goal_action_repeat_count", 0),
            actions_since_progress=d.get("actions_since_progress", {}),
            last_creative_ts=d.get("last_creative_ts", 0.0),
            last_play_ts=d.get("last_play_ts", 0.0),
            off_window_learn_date=d.get("off_window_learn_date", ""),
            off_window_learn_used=d.get("off_window_learn_used", 0),
        )
