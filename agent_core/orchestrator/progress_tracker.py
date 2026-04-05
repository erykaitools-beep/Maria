"""
TaskProgressTracker (V3 Phase D, Module 12)

Tracks task execution progress across planner episodes.
Aggregates data from GoalStore, PlannerCore decisions, and TraceStore.

Wraps V2: GoalStore, planner_state, decision_traces.

Usage:
    tracker = TaskProgressTracker(ctx)
    progress = tracker.get_task_progress(task_id)
    active = tracker.get_active_tasks()
    timeline = tracker.get_timeline(task_id)
"""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TaskProgressTracker:
    """Tracks and reports task execution progress."""

    def __init__(self, ctx):
        self._ctx = ctx

    def get_task_progress(self, goal_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed progress for a task/goal.

        Args:
            goal_id: Goal ID to track

        Returns:
            Progress dict or None if not found.
        """
        goal_store = self._ctx.goal_store
        if not goal_store:
            return None

        goal = goal_store.get(goal_id)
        if not goal:
            return None

        # Get related planner decisions
        decisions = self._get_decisions_for_goal(goal_id)

        # Get related traces
        traces = self._get_traces_for_goal(goal_id)

        return {
            "goal_id": goal.id,
            "description": goal.description,
            "type": goal.type.value,
            "status": goal.status.value,
            "progress": goal.progress,
            "priority": goal.priority,
            "created_at": goal.created_at,
            "updated_at": goal.updated_at,
            "metadata": goal.metadata,
            "outcome": goal.outcome,
            "decisions_count": len(decisions),
            "recent_decisions": decisions[:5],
            "traces_count": len(traces),
            "recent_traces": traces[:3],
            "audit_trail": [a.to_dict() for a in goal.audit_trail[-5:]],
        }

    def get_active_tasks(self) -> List[Dict[str, Any]]:
        """
        List all active goals with progress info.

        Returns:
            List of active task summaries.
        """
        goal_store = self._ctx.goal_store
        if not goal_store:
            return []

        active = goal_store.get_active()
        results = []
        for goal in active:
            results.append({
                "goal_id": goal.id,
                "description": goal.description,
                "type": goal.type.value,
                "status": goal.status.value,
                "progress": goal.progress,
                "priority": goal.priority,
                "source": goal.metadata.get("source", goal.created_by),
                "created_at": goal.created_at,
            })
        return sorted(results, key=lambda r: r["priority"], reverse=True)

    def get_completed_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        List recently completed goals.

        Args:
            limit: Max results

        Returns:
            List of completed task summaries.
        """
        goal_store = self._ctx.goal_store
        if not goal_store:
            return []

        all_goals = goal_store.get_all()
        completed = [
            g for g in all_goals
            if g.status.value in ("achieved", "failed", "abandoned")
        ]
        completed.sort(key=lambda g: g.updated_at, reverse=True)

        return [
            {
                "goal_id": g.id,
                "description": g.description,
                "status": g.status.value,
                "progress": g.progress,
                "outcome": g.outcome,
                "updated_at": g.updated_at,
            }
            for g in completed[:limit]
        ]

    def get_timeline(self, goal_id: str) -> List[Dict[str, Any]]:
        """
        Get chronological timeline of events for a goal.

        Combines audit trail entries and planner decisions.

        Args:
            goal_id: Goal ID

        Returns:
            Sorted list of timeline events.
        """
        events = []

        # Audit trail
        goal_store = self._ctx.goal_store
        if goal_store:
            goal = goal_store.get(goal_id)
            if goal:
                for entry in goal.audit_trail:
                    events.append({
                        "timestamp": entry.timestamp,
                        "type": "status_change",
                        "detail": f"{entry.old_status} -> {entry.new_status}",
                        "reason": entry.reason,
                        "actor": entry.actor,
                    })

        # Planner decisions
        for dec in self._get_decisions_for_goal(goal_id):
            events.append({
                "timestamp": dec.get("timestamp", 0),
                "type": "decision",
                "detail": dec.get("action", "?"),
                "reason": dec.get("message", ""),
                "actor": "planner",
            })

        events.sort(key=lambda e: e["timestamp"])
        return events

    def get_planner_stats(self) -> Dict[str, Any]:
        """
        Get planner-level statistics.

        Returns:
            Dict with cycle counts, recent actions, throughput.
        """
        planner = self._ctx.planner_core
        if not planner:
            return {"available": False}

        state = getattr(planner, "_state", None)
        if not state:
            return {"available": True, "state": "no_state"}

        return {
            "available": True,
            "total_cycles": getattr(state, "total_cycles", 0),
            "total_plans": getattr(state, "total_plans", 0),
            "last_plan_time": getattr(state, "last_plan_time", 0),
            "last_action": getattr(state, "last_action_type", "?"),
        }

    def get_summary(self) -> Dict[str, Any]:
        """High-level progress summary."""
        active = self.get_active_tasks()
        completed = self.get_completed_tasks(limit=5)

        return {
            "active_count": len(active),
            "active_tasks": active[:5],
            "recently_completed": completed,
            "planner": self.get_planner_stats(),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_decisions_for_goal(self, goal_id: str) -> List[Dict]:
        """Get planner decisions related to a goal."""
        planner = self._ctx.planner_core
        if not planner:
            return []

        history = getattr(planner, "_history", [])
        results = []
        for plan in history:
            if hasattr(plan, "goal_id") and plan.goal_id == goal_id:
                results.append({
                    "timestamp": plan.timestamp,
                    "action": plan.action_type.value if hasattr(plan.action_type, "value") else str(plan.action_type),
                    "status": plan.status.value if hasattr(plan.status, "value") else str(plan.status),
                    "message": getattr(plan, "message", ""),
                    "duration_ms": getattr(plan, "duration_ms", 0),
                })
        return results

    def _get_traces_for_goal(self, goal_id: str) -> List[Dict]:
        """Get decision traces related to a goal."""
        trace_store = self._ctx.trace_store
        if not trace_store:
            return []

        try:
            recent = trace_store.get_recent(limit=50)
            results = []
            for trace in recent:
                trace_goal = trace.get("goal_id", "")
                if trace_goal == goal_id:
                    results.append({
                        "episode_id": trace.get("episode_id", ""),
                        "timestamp": trace.get("timestamp", 0),
                        "steps_count": len(trace.get("steps", [])),
                        "llm_calls": trace.get("total_llm_calls", 0),
                    })
            return results
        except Exception:
            return []
