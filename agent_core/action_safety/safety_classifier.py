"""
Safety Classifier - maps ActionType to SafetyProfile.

Determines safety mode, reversibility, and effect type for each action.
Unknown actions default to STAGED (safe-by-default).

Kontrakt: docs/CONTRACTS.md - Kontrakt 10: Action Safety
ADR-013: Rule-based, zero LLM, deterministic.
"""

from typing import Dict

from agent_core.action_safety.safety_model import (
    EffectType,
    Reversibility,
    SafetyMode,
    SafetyProfile,
)


# Default safety profiles per ActionType.value string.
# learn/exam/review: AUTO_COMMIT, no snapshots (K2 Sandbox handles safety)
# maintenance/fetch: AUDIT_ONLY with before/after snapshots
# unknown: STAGED (safe-by-default, most restrictive)
DEFAULT_SAFETY_PROFILES: Dict[str, SafetyProfile] = {
    "learn": SafetyProfile(
        SafetyMode.AUTO_COMMIT, Reversibility.REVERSIBLE,
        EffectType.KNOWLEDGE, False, False,
    ),
    "exam": SafetyProfile(
        SafetyMode.AUTO_COMMIT, Reversibility.REVERSIBLE,
        EffectType.KNOWLEDGE, False, False,
    ),
    "review": SafetyProfile(
        SafetyMode.AUTO_COMMIT, Reversibility.REVERSIBLE,
        EffectType.KNOWLEDGE, False, False,
    ),
    "evaluate": SafetyProfile(
        SafetyMode.AUTO_COMMIT, Reversibility.REVERSIBLE,
        EffectType.NONE, False, False,
    ),
    "noop": SafetyProfile(
        SafetyMode.AUTO_COMMIT, Reversibility.REVERSIBLE,
        EffectType.NONE, False, False,
    ),
    "maintenance": SafetyProfile(
        SafetyMode.AUDIT_ONLY, Reversibility.REVERSIBLE,
        EffectType.GOAL_STATE, True, True,
    ),
    "fetch": SafetyProfile(
        SafetyMode.AUDIT_ONLY, Reversibility.PARTIALLY_REVERSIBLE,
        EffectType.FILESYSTEM, True, True,
    ),
    "experiment": SafetyProfile(
        SafetyMode.AUDIT_ONLY, Reversibility.REVERSIBLE,
        EffectType.CONFIGURATION, True, True,
    ),
    "effector": SafetyProfile(
        SafetyMode.AUDIT_ONLY, Reversibility.PARTIALLY_REVERSIBLE,
        EffectType.EXTERNAL_API, True, True,
    ),
}

# Safe-by-default profile for unknown action types
_UNKNOWN_PROFILE = SafetyProfile(
    SafetyMode.STAGED, Reversibility.IRREVERSIBLE,
    EffectType.EXTERNAL_API, True, True,
)


def get_safety_profile(action_type_value: str) -> SafetyProfile:
    """
    Get safety profile for an action type.

    Known actions get their configured profile.
    Unknown actions default to STAGED + IRREVERSIBLE (safe-by-default).
    """
    return DEFAULT_SAFETY_PROFILES.get(action_type_value, _UNKNOWN_PROFILE)
