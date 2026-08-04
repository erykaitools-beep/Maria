"""
Environment model - modes, profiles, and the learning-window clock.

Per roadmap: "6 trybow na papierze. Zaczac od 1 ktory dziala."
Core identity (K1-K13, personality) is INVARIANT across modes.

What is actually LIVE here (phantom hunt r2, 2026-07-19):
- berlin_now() / is_learning_window() / PROFILE_LEARNING.auto_trigger_hours --
  the time SSoT consumed directly by planner window enforcement, the mode
  regulator wake/sleep gating, and the teacher gate.
- The mode state machine (detector + manager) as a mode-of-record for /env
  and the manual teacher-gate override.

The behavioral payload the profiles used to carry (blocked/deprioritized
actions, budget/interval multipliers, prompt additions, notification levels)
was CUT: it reached nothing but the status display, and every concern it
encoded is handled by a live mechanism reading the real signal (planner
guard health gating, is_learning_window, NOOP backoff cadence, K7 effector
gates, notifier _can_send). Do not re-add payload without first fixing the
detector's degradation rule (REDUCED->QUIET), which makes daytime mode a
30-min-stale sample of normal CPU bursts.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple


class EnvironmentMode(Enum):
    """Operating environment modes."""
    DEFAULT = "default"           # Standard balanced operation
    LEARNING = "learning"         # Focus on knowledge acquisition
    MONITORING = "monitoring"     # System health focus, minimal LLM usage
    QUIET = "quiet"               # Minimal activity, essential ops only


@dataclass(frozen=True)
class EnvironmentProfile:
    """
    Profile for an environment mode: identity + auto-trigger window.

    Behavioral payload fields (blocked/deprioritized/priority actions,
    multipliers, prompt additions, notification levels) were CUT 2026-07-19:
    no runtime path ever consumed them (see module docstring).
    """
    mode: EnvironmentMode
    description: str

    # Auto-trigger conditions
    auto_trigger_hours: Tuple[int, ...] = ()   # Hours when this mode activates
    auto_trigger_days: Tuple[int, ...] = ()     # Days of week (0=Mon, 6=Sun)


# --- Pre-built profiles ---

PROFILE_DEFAULT = EnvironmentProfile(
    mode=EnvironmentMode.DEFAULT,
    description="Standard balanced operation - all systems active",
)

PROFILE_LEARNING = EnvironmentProfile(
    mode=EnvironmentMode.LEARNING,
    description="Knowledge acquisition focus - learning and exams prioritized",
    # 2026-06-20: widened 4h (09-10,14-15, Mon-Fri) -> 10h every day (09:00-18:59
    # Berlin, all 7 days). The narrow window throttled throughput: she was ACTIVE
    # (and thus able to fetch/learn -- GUARDED fetch is blocked in SLEEP) only ~4h
    # on weekdays, slept ~70%, and exhausted goals could not refetch the rest of
    # the day. Widening makes the regulator keep her awake through the window
    # (mode_regulator wakes on is_learning_window) and lets fetch/learn run
    # without the OFF_WINDOW_LEARN_BUDGET cap. QUIET 22-06 stays (night
    # consolidation/rest); 19-22 + 06-09 remain DEFAULT (wind-down / ramp).
    auto_trigger_hours=tuple(range(9, 19)),       # 09:00-18:59 Berlin (10h)
    auto_trigger_days=tuple(range(7)),            # all 7 days
)

PROFILE_MONITORING = EnvironmentProfile(
    mode=EnvironmentMode.MONITORING,
    description="System health focus - evaluation and maintenance prioritized",
)

PROFILE_QUIET = EnvironmentProfile(
    mode=EnvironmentMode.QUIET,
    description="Minimal activity - only essential operations, no proactive actions",
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
