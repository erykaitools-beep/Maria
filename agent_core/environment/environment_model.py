"""
Environment model - modes, profiles, and their configurations.

Per roadmap: "6 trybow na papierze. Zaczac od 1 ktory dziala."
We start with 4 practical modes, each actually changing behavior.
Core identity (K1-K13, personality) is INVARIANT across modes.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, Optional, Tuple


class EnvironmentMode(Enum):
    """Operating environment modes."""
    DEFAULT = "default"           # Standard balanced operation
    LEARNING = "learning"         # Focus on knowledge acquisition
    MONITORING = "monitoring"     # System health focus, minimal LLM usage
    QUIET = "quiet"               # Minimal activity, essential ops only


@dataclass(frozen=True)
class EnvironmentProfile:
    """
    Configuration profile for an environment mode.

    Defines what changes when mode switches - NOT who Maria is,
    but what she focuses on and how she allocates resources.
    """
    mode: EnvironmentMode
    description: str

    # Action priorities: higher weight = more likely to be selected by planner
    priority_actions: Tuple[str, ...] = ()     # Preferred ActionTypes
    deprioritized_actions: Tuple[str, ...] = ()  # Lower priority ActionTypes
    blocked_actions: Tuple[str, ...] = ()      # Blocked ActionTypes

    # Notification behavior
    notification_level: str = "normal"  # "all", "normal", "important", "critical"

    # LLM budget adjustment
    llm_budget_multiplier: float = 1.0  # 1.0 = normal, 0.5 = reduced

    # Planner interval adjustment (multiplier on ROUTINE_INTERVAL_TICKS)
    planner_interval_multiplier: float = 1.0

    # Extra context for LLM prompt (appended to system prompt)
    prompt_addition: str = ""

    # Auto-trigger conditions
    auto_trigger_hours: Tuple[int, ...] = ()   # Hours when this mode activates
    auto_trigger_days: Tuple[int, ...] = ()     # Days of week (0=Mon, 6=Sun)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "description": self.description,
            "priority_actions": list(self.priority_actions),
            "deprioritized_actions": list(self.deprioritized_actions),
            "blocked_actions": list(self.blocked_actions),
            "notification_level": self.notification_level,
            "llm_budget_multiplier": self.llm_budget_multiplier,
            "planner_interval_multiplier": self.planner_interval_multiplier,
            "prompt_addition": self.prompt_addition,
            "auto_trigger_hours": list(self.auto_trigger_hours),
            "auto_trigger_days": list(self.auto_trigger_days),
        }

    @staticmethod
    def from_dict(d: dict) -> "EnvironmentProfile":
        return EnvironmentProfile(
            mode=EnvironmentMode(d["mode"]),
            description=d.get("description", ""),
            priority_actions=tuple(d.get("priority_actions", ())),
            deprioritized_actions=tuple(d.get("deprioritized_actions", ())),
            blocked_actions=tuple(d.get("blocked_actions", ())),
            notification_level=d.get("notification_level", "normal"),
            llm_budget_multiplier=d.get("llm_budget_multiplier", 1.0),
            planner_interval_multiplier=d.get("planner_interval_multiplier", 1.0),
            prompt_addition=d.get("prompt_addition", ""),
            auto_trigger_hours=tuple(d.get("auto_trigger_hours", ())),
            auto_trigger_days=tuple(d.get("auto_trigger_days", ())),
        )


# --- Pre-built profiles ---

PROFILE_DEFAULT = EnvironmentProfile(
    mode=EnvironmentMode.DEFAULT,
    description="Standard balanced operation - all systems active",
    priority_actions=(),
    deprioritized_actions=(),
    blocked_actions=(),
    notification_level="normal",
    llm_budget_multiplier=1.0,
    planner_interval_multiplier=1.0,
    prompt_addition="",
)

PROFILE_LEARNING = EnvironmentProfile(
    mode=EnvironmentMode.LEARNING,
    description="Knowledge acquisition focus - learning and exams prioritized",
    priority_actions=("learn", "exam", "review", "fetch", "ask_expert"),
    deprioritized_actions=("creative", "self_analyze", "experiment"),
    blocked_actions=(),
    notification_level="important",
    llm_budget_multiplier=1.5,      # More LLM budget for learning
    planner_interval_multiplier=0.5,  # Faster cycles
    prompt_addition="Tryb nauki: skupiam sie na przyswajaniu wiedzy. "
                    "Priorytet na nauke, egzaminy i powtorki.",
    # 2026-06-20: widened 4h (09-10,14-15, Mon-Fri) -> 10h every day (09:00-18:59
    # Berlin, all 7 days). The narrow window throttled throughput: she was ACTIVE
    # (and thus able to fetch/learn -- GUARDED fetch is blocked in SLEEP) only ~4h
    # on weekdays, slept ~70%, and exhausted goals could not refetch the rest of
    # the day. Widening makes the regulator keep her awake through the window
    # (mode_regulator wakes on is_learning_window), lets fetch/learn run without
    # the OFF_WINDOW_LEARN_BUDGET cap, and -- because mode_detector selects
    # PROFILE_LEARNING by hour -- deprioritizes reflection in favour of
    # learn/exam/fetch. QUIET 22-06 stays (night consolidation/rest); 19-22 + 06-09
    # remain DEFAULT (gentle wind-down / ramp).
    auto_trigger_hours=tuple(range(9, 19)),       # 09:00-18:59 Berlin (10h)
    auto_trigger_days=tuple(range(7)),            # all 7 days
)

PROFILE_MONITORING = EnvironmentProfile(
    mode=EnvironmentMode.MONITORING,
    description="System health focus - evaluation and maintenance prioritized",
    priority_actions=("evaluate", "maintenance", "self_analyze", "critique"),
    deprioritized_actions=("learn", "fetch", "ask_expert", "creative"),
    blocked_actions=("experiment",),
    notification_level="all",
    llm_budget_multiplier=0.5,      # Conserve LLM budget
    planner_interval_multiplier=2.0,  # Slower cycles, less CPU
    prompt_addition="Tryb monitorowania: skupiam sie na zdrowiu systemu "
                    "i jakosci wiedzy. Minimalne zuzycie zasobow.",
)

PROFILE_QUIET = EnvironmentProfile(
    mode=EnvironmentMode.QUIET,
    description="Minimal activity - only essential operations, no proactive actions",
    priority_actions=("evaluate", "maintenance"),
    deprioritized_actions=("learn", "exam", "fetch", "creative", "self_analyze",
                           "ask_expert", "experiment", "validate", "critique"),
    blocked_actions=("effector",),
    notification_level="critical",
    llm_budget_multiplier=0.2,       # Minimal LLM usage
    planner_interval_multiplier=3.0,  # Very slow cycles
    prompt_addition="Tryb cichy: minimalna aktywnosc, "
                    "tylko niezbedne operacje. Operator nie chce byc niepokojony.",
    auto_trigger_hours=(22, 23, 0, 1, 2, 3, 4, 5, 6),  # 22:00-06:59 Berlin
)

# Registry: mode -> profile
ENVIRONMENT_PROFILES = {
    EnvironmentMode.DEFAULT: PROFILE_DEFAULT,
    EnvironmentMode.LEARNING: PROFILE_LEARNING,
    EnvironmentMode.MONITORING: PROFILE_MONITORING,
    EnvironmentMode.QUIET: PROFILE_QUIET,
}


def berlin_now():
    """Current time in Europe/Berlin -- the one zone every learning/quiet window
    is expressed in (the operator's local time).

    Pinned explicitly instead of a naive datetime.now() so the window is
    DST-correct year-round AND immune to OS timezone changes. The 2026-05-29
    switch from Etc/UTC to Europe/Warsaw silently shifted the old naive window by
    2h (auto_trigger_hours had been UTC-authored), starving daytime learning.
    This is the single source of truth for "now" across all window checks.
    """
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo
    return dt.now(ZoneInfo("Europe/Berlin"))


def is_learning_window(now=None) -> bool:
    """
    Check if current time falls within LEARNING profile's auto-trigger window.

    Uses PROFILE_LEARNING.auto_trigger_hours (Berlin wall-clock) and
    auto_trigger_days. When now is None it defaults to berlin_now(), so the
    window is computed in Europe/Berlin regardless of the OS timezone.
    Returns True if now is within a configured learning window.
    If no auto_trigger_hours defined, returns True (no restriction).
    """
    if now is None:
        now = berlin_now()
    profile = ENVIRONMENT_PROFILES[EnvironmentMode.LEARNING]
    if not profile.auto_trigger_hours:
        return True
    hour_match = now.hour in profile.auto_trigger_hours
    day_match = (not profile.auto_trigger_days) or (now.weekday() in profile.auto_trigger_days)
    return hour_match and day_match


@dataclass
class EnvironmentState:
    """Persistent state for environment management."""
    active_mode: EnvironmentMode = EnvironmentMode.DEFAULT
    switched_at: float = field(default_factory=time.time)
    switched_by: str = "system"  # "operator", "auto", "system"
    auto_detect_enabled: bool = True
    override_until: Optional[float] = None  # Manual override expiry

    def to_dict(self) -> dict:
        return {
            "active_mode": self.active_mode.value,
            "switched_at": self.switched_at,
            "switched_by": self.switched_by,
            "auto_detect_enabled": self.auto_detect_enabled,
            "override_until": self.override_until,
        }

    @staticmethod
    def from_dict(d: dict) -> "EnvironmentState":
        return EnvironmentState(
            active_mode=EnvironmentMode(d.get("active_mode", "default")),
            switched_at=d.get("switched_at", 0.0),
            switched_by=d.get("switched_by", "system"),
            auto_detect_enabled=d.get("auto_detect_enabled", True),
            override_until=d.get("override_until"),
        )
