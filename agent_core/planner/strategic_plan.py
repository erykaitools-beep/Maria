"""
StrategicPlan - Model for LLM-generated strategic plans.

Output of StrategicPlanner. Read by tactical loop (PlannerCore).
Planner v2 Phase B.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class PlannedAction:
    """Single action recommended by strategic planner."""
    action_type: str               # ActionType value: "learn", "exam", "review", etc.
    goal_id: Optional[str] = None  # Target goal (None for goalless actions like creative)
    reason: str = ""               # Why this action (from LLM)
    max_attempts: int = 3          # Give up after this many tries
    attempts: int = 0              # Current attempt count
    completed: bool = False        # Marked done after execution
    skipped: bool = False          # Marked skipped (backed off or blocked)


@dataclass
class StrategicPlan:
    """Output of a strategic planning session."""
    created_at: float = field(default_factory=time.time)
    valid_until: float = 0.0            # Plan expiry timestamp
    action_queue: List[PlannedAction] = field(default_factory=list)
    blocked_goals: Dict[str, str] = field(default_factory=dict)  # goal_id -> reason
    idle_strategy: str = "wait"         # What to do when queue empty
    notes: str = ""                     # LLM reasoning (for traces)
    model_used: str = ""                # Which model produced this plan

    @property
    def is_expired(self) -> bool:
        return time.time() > self.valid_until

    @property
    def next_action(self) -> Optional[PlannedAction]:
        """Get next uncompleted, unskipped action."""
        for a in self.action_queue:
            if not a.completed and not a.skipped:
                return a
        return None

    @property
    def is_exhausted(self) -> bool:
        """All actions completed or skipped."""
        return all(a.completed or a.skipped for a in self.action_queue)

    def mark_completed(self, index: int) -> None:
        """Mark action at index as completed."""
        if 0 <= index < len(self.action_queue):
            self.action_queue[index].completed = True

    def mark_skipped(self, index: int, reason: str = "") -> None:
        """Mark action at index as skipped."""
        if 0 <= index < len(self.action_queue):
            self.action_queue[index].skipped = True

    def mark_action(self, action: "PlannedAction", completed: bool = False,
                    skipped: bool = False) -> bool:
        """Mark a specific action (by identity, not equality) completed and/or
        skipped. Returns True if the action was found in the queue. Used by the
        tactical loop (#9) to close the plan lifecycle as work is done."""
        for a in self.action_queue:
            if a is action:
                if completed:
                    a.completed = True
                if skipped:
                    a.skipped = True
                return True
        return False

    def to_dict(self) -> dict:
        return {
            "created_at": self.created_at,
            "valid_until": self.valid_until,
            "action_queue": [
                {
                    "action_type": a.action_type,
                    "goal_id": a.goal_id,
                    "reason": a.reason,
                    "max_attempts": a.max_attempts,
                    "attempts": a.attempts,
                    "completed": a.completed,
                    "skipped": a.skipped,
                }
                for a in self.action_queue
            ],
            "blocked_goals": self.blocked_goals,
            "idle_strategy": self.idle_strategy,
            "notes": self.notes,
            "model_used": self.model_used,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StrategicPlan":
        """Rehydrate a plan from to_dict() output (warm recovery, Klocek 9b).

        Tolerant of missing keys AND wrong types (defaults applied) so a
        slightly older, partial, or manually-edited snapshot still loads rather
        than raising -- a torn write or schema drift degrades to a usable
        (possibly emptier) plan, not an exception."""
        raw_queue = data.get("action_queue")
        if not isinstance(raw_queue, list):
            raw_queue = []
        raw_blocked = data.get("blocked_goals")
        if not isinstance(raw_blocked, dict):
            raw_blocked = {}
        return cls(
            created_at=data.get("created_at", 0.0),
            valid_until=data.get("valid_until", 0.0),
            action_queue=[
                PlannedAction(
                    action_type=a.get("action_type", ""),
                    goal_id=a.get("goal_id"),
                    reason=a.get("reason", ""),
                    max_attempts=a.get("max_attempts", 3),
                    attempts=a.get("attempts", 0),
                    completed=a.get("completed", False),
                    skipped=a.get("skipped", False),
                )
                for a in raw_queue
                if isinstance(a, dict)
            ],
            blocked_goals=dict(raw_blocked),
            idle_strategy=data.get("idle_strategy", "wait"),
            notes=data.get("notes", ""),
            model_used=data.get("model_used", ""),
        )

    def summary(self) -> str:
        """Human-readable summary for logs/Telegram."""
        remaining = [a for a in self.action_queue if not a.completed and not a.skipped]
        done = sum(1 for a in self.action_queue if a.completed)
        lines = [f"Plan ({done}/{len(self.action_queue)} done, {len(remaining)} remaining):"]
        for a in remaining[:5]:
            goal_str = f" [{a.goal_id[:12]}]" if a.goal_id else ""
            lines.append(f"  - {a.action_type}{goal_str}: {a.reason[:50]}")
        if self.idle_strategy != "wait":
            lines.append(f"  idle: {self.idle_strategy}")
        if self.blocked_goals:
            lines.append(f"  blocked: {len(self.blocked_goals)} goals")
        return "\n".join(lines)
