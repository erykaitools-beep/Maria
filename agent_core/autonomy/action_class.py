"""
Action Classification for K7 Autonomy Policy.

Each ActionType has a classification that determines how it is governed:
- FREE: execute without restriction
- GUARDED: execute with rate limiting and logging
- RESTRICTED: requires conditions or human confirmation
- FORBIDDEN: never execute autonomously

Kontrakt: docs/CONTRACTS.md - Kontrakt 7: Autonomy Policy
"""

from enum import Enum
from typing import Dict


class ActionClassification(Enum):
    """How strictly an action type is governed."""
    FREE = "free"              # No restrictions (learning, exams)
    GUARDED = "guarded"        # Rate-limited + logged (fetch, maintenance)
    RESTRICTED = "restricted"  # Requires conditions or HITL (future: smart home)
    FORBIDDEN = "forbidden"    # Never autonomous (future: delete data, system modify)


# Default classification per ActionType value.
# Keys are ActionType.value strings to avoid circular import with planner_model.
DEFAULT_ACTION_CLASSIFICATIONS: Dict[str, ActionClassification] = {
    "learn": ActionClassification.FREE,
    "exam": ActionClassification.FREE,
    "review": ActionClassification.FREE,
    "evaluate": ActionClassification.FREE,
    "noop": ActionClassification.FREE,
    "maintenance": ActionClassification.GUARDED,
    "fetch": ActionClassification.GUARDED,
    "experiment": ActionClassification.GUARDED,
}


def classify_action(action_type_value: str) -> ActionClassification:
    """
    Get classification for an action type.

    Args:
        action_type_value: ActionType.value string (e.g. "learn", "fetch")

    Returns:
        ActionClassification. Defaults to RESTRICTED for unknown actions
        (safe-by-default: unknown actions require explicit approval).
    """
    return DEFAULT_ACTION_CLASSIFICATIONS.get(
        action_type_value, ActionClassification.RESTRICTED
    )
