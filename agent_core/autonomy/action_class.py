"""
Action Classification for K7 Autonomy Policy.

Each ActionType has a classification that determines how it is governed:
- FREE: execute without restriction (learning loop core)
- ANALYTICAL: read-only self-reflection; runs in degraded modes
- GUARDED: execute with rate limiting and logging (state-modifying)
- RESTRICTED: requires conditions or human confirmation
- FORBIDDEN: never execute autonomously

ANALYTICAL is the self-reflection tier. Actions in this class are
READ-ONLY observers — they generate reports, recommendations, or
PROPOSED goals (which pass through human gates per ADR-011/ADR-020),
but never mutate production state autonomously. Because they do not
write to memory, beliefs, or the goal store, they are safe to run in
SLEEP/REDUCED modes — and they MUST run there for the organism to
keep developing during low-activity periods (weekends, idle nights).

Kontrakt: docs/CONTRACTS.md - Kontrakt 7: Autonomy Policy
"""

from enum import Enum
from typing import Dict


class ActionClassification(Enum):
    """How strictly an action type is governed."""
    FREE = "free"              # Core learning loop (learn, exam, evaluate)
    ANALYTICAL = "analytical"  # READ-ONLY self-reflection (K12, K13, critic)
    GUARDED = "guarded"        # Rate-limited + logged, mutates state (fetch, experiment)
    RESTRICTED = "restricted"  # Requires conditions or HITL (effector, smart home)
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
    "effector": ActionClassification.GUARDED,  # Post 24h test 2026-05-14: plank up from RESTRICTED to GUARDED (rate-limited + logged). Next iter: re-evaluate FREE.
    # ANALYTICAL: READ-ONLY self-reflection, NIM-first cascade, must run 7/7
    "self_analyze": ActionClassification.ANALYTICAL,  # K12: PROPOSED goals + advisory bulletin (ADR-020)
    "creative": ActionClassification.ANALYTICAL,      # K13: strategic reflection, PROPOSED meta-goals (ADR-011)
    "validate": ActionClassification.ANALYTICAL,      # Cross-LLM validation (Faza F), READ-ONLY
    "critique": ActionClassification.ANALYTICAL,      # Faza G: READ-ONLY knowledge critic (ADR-028)
    "ask_expert": ActionClassification.GUARDED,       # External API cost (ChatGPT) — keep rate-limited
    "fs_write": ActionClassification.GUARDED,         # B2: sandboxed file write (rate-limited + logged + K10-validated)
}


def classify_action(action_type_value: str, router=None) -> ActionClassification:
    """
    Get classification for an action type.

    Args:
        action_type_value: ActionType.value string (e.g. "learn", "fetch")
        router: Optional CapabilityRouter for registry-based lookup

    Returns:
        ActionClassification. Defaults to RESTRICTED for unknown actions
        (safe-by-default: unknown actions require explicit approval).
    """
    # Prefer router if available (single source of truth)
    if router is not None:
        k7_str = router.get_k7_classification(action_type_value)
        try:
            return ActionClassification(k7_str)
        except ValueError:
            return ActionClassification.RESTRICTED

    return DEFAULT_ACTION_CLASSIFICATIONS.get(
        action_type_value, ActionClassification.RESTRICTED
    )
