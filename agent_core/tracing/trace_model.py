"""
DecisionTrace - normalized trace object for one cognitive episode.

Collects data from: planner, K7 policy, K8 deliberation, K9 metacognition,
K10 action safety, LLM calls, effector commands.

Written once per planner cycle to decision_traces.jsonl.
Read by Web UI and Telegram for operator inspection.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TraceStep:
    """
    One step within an episode trace.

    Steps are collected during the episode and stored as a list.
    Each step represents a subsystem decision point.
    """
    subsystem: str          # planner|k7_policy|k8_deliberation|k9_metacognition|k10_safety|llm|effector|creative|k12
    action: str             # what happened: "goal_selected", "policy_check", "model_call", etc.
    result: str             # outcome: "allowed", "blocked", "success", "failed"
    detail: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subsystem": self.subsystem,
            "action": self.action,
            "result": self.result,
            "detail": self.detail,
            "ts": self.timestamp or time.time(),
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TraceStep":
        return TraceStep(
            subsystem=d.get("subsystem", ""),
            action=d.get("action", ""),
            result=d.get("result", ""),
            detail=d.get("detail", {}),
            timestamp=d.get("ts", 0.0),
        )


@dataclass
class DecisionTrace:
    """
    Complete trace of one cognitive episode.

    Created at the start of a planner cycle, finalized at the end.
    Contains all decision points traversed during the episode.
    """
    episode_id: str
    started_at: float = 0.0
    finished_at: float = 0.0

    # Context at episode start
    tick_count: int = 0
    mode: str = ""
    health_score: float = 1.0

    # Goal selection
    goal_id: Optional[str] = None
    goal_description: str = ""
    goal_priority: float = 0.0

    # Planning outcome
    plan_id: Optional[str] = None
    action_type: str = ""
    action_params: Dict[str, Any] = field(default_factory=dict)

    # Policy + safety
    k7_decision: str = ""           # allow|block|rate_limited
    k7_reasons: List[str] = field(default_factory=list)
    k10_safety_mode: str = ""       # auto_commit|audit_only|staged
    k10_validation: str = ""        # valid|unexpected|skipped

    # Model usage
    models_used: List[str] = field(default_factory=list)
    total_llm_calls: int = 0
    total_llm_latency_ms: float = 0.0

    # Result
    success: Optional[bool] = None
    result_summary: str = ""

    # Detailed steps (ordered)
    steps: List[TraceStep] = field(default_factory=list)

    # Duration
    duration_ms: float = 0.0

    def add_step(
        self,
        subsystem: str,
        action: str,
        result: str,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add a trace step to this episode."""
        self.steps.append(TraceStep(
            subsystem=subsystem,
            action=action,
            result=result,
            detail=detail or {},
            timestamp=time.time(),
        ))

    def finalize(self, success: bool, result_summary: str = "") -> None:
        """Mark episode as complete."""
        self.finished_at = time.time()
        self.success = success
        self.result_summary = result_summary
        self.duration_ms = round((self.finished_at - self.started_at) * 1000, 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "tick_count": self.tick_count,
            "mode": self.mode,
            "health_score": self.health_score,
            "goal_id": self.goal_id,
            "goal_description": self.goal_description,
            "goal_priority": self.goal_priority,
            "plan_id": self.plan_id,
            "action_type": self.action_type,
            "action_params": self.action_params,
            "k7_decision": self.k7_decision,
            "k7_reasons": self.k7_reasons,
            "k10_safety_mode": self.k10_safety_mode,
            "k10_validation": self.k10_validation,
            "models_used": self.models_used,
            "total_llm_calls": self.total_llm_calls,
            "total_llm_latency_ms": self.total_llm_latency_ms,
            "success": self.success,
            "result_summary": self.result_summary,
            "steps": [s.to_dict() for s in self.steps],
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "DecisionTrace":
        trace = DecisionTrace(
            episode_id=d["episode_id"],
            started_at=d.get("started_at", 0.0),
            finished_at=d.get("finished_at", 0.0),
            duration_ms=d.get("duration_ms", 0.0),
            tick_count=d.get("tick_count", 0),
            mode=d.get("mode", ""),
            health_score=d.get("health_score", 1.0),
            goal_id=d.get("goal_id"),
            goal_description=d.get("goal_description", ""),
            goal_priority=d.get("goal_priority", 0.0),
            plan_id=d.get("plan_id"),
            action_type=d.get("action_type", ""),
            action_params=d.get("action_params", {}),
            k7_decision=d.get("k7_decision", ""),
            k7_reasons=d.get("k7_reasons", []),
            k10_safety_mode=d.get("k10_safety_mode", ""),
            k10_validation=d.get("k10_validation", ""),
            models_used=d.get("models_used", []),
            total_llm_calls=d.get("total_llm_calls", 0),
            total_llm_latency_ms=d.get("total_llm_latency_ms", 0.0),
            success=d.get("success"),
            result_summary=d.get("result_summary", ""),
        )
        trace.steps = [
            TraceStep.from_dict(s) for s in d.get("steps", [])
        ]
        return trace

    def to_compact(self) -> str:
        """
        One-line human-readable summary for Telegram/logs.

        Format: [ep-xxx] LEARN goal="topic" -> success (245ms, 2 LLM calls)
        """
        status = "OK" if self.success else ("FAIL" if self.success is False else "?")
        goal = self.goal_description[:30] if self.goal_description else "no goal"
        action = self.action_type or "noop"
        k7 = f" K7:{self.k7_decision}" if self.k7_decision and self.k7_decision != "allow" else ""
        llm = f", {self.total_llm_calls} LLM" if self.total_llm_calls else ""
        eid_short = self.episode_id[-8:] if self.episode_id else "?"
        return f"[{eid_short}] {action.upper()} goal=\"{goal}\" -> {status}{k7} ({self.duration_ms:.0f}ms{llm})"
