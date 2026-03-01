"""
Goal System - Kontrakt K3.

Explicit, observable, auditable goals replacing implicit hardcoded thresholds.
Persistence: meta_data/goals.jsonl (append-only, last record per id wins).
"""

from agent_core.goals.goal_model import (
    GoalType,
    GoalStatus,
    AuditEntry,
    Goal,
)
from agent_core.goals.store import GoalStore

__all__ = [
    "GoalType",
    "GoalStatus",
    "AuditEntry",
    "Goal",
    "GoalStore",
]
