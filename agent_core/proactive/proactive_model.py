"""
Proactive Contact data model.

Maria initiates contact with the operator based on time, events, and system state.
Each contact reason has its own schedule and cooldown.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ContactReason(Enum):
    """Why Maria is reaching out proactively."""

    # Time-based (scheduled)
    MORNING_SUMMARY = "morning_summary"      # Daily 7:00-9:00
    EVENING_RECAP = "evening_recap"          # Daily 20:00-21:00
    WEEKLY_REVIEW = "weekly_review"          # Sunday 19:00-20:00

    # Conditional-scheduled: only fires when the condition holds (hot weather).
    # Daytime hydration care -- "drink water" nudge on hot days.
    HYDRATION_NUDGE = "hydration_nudge"      # Daily 11:00-20:00, only when hot

    # Event-based (triggered by system state)
    GOAL_ACHIEVED = "goal_achieved"          # A goal was completed
    GOAL_PROPOSED = "goal_proposed"          # New PROPOSED goal needs operator approval
    LEARNING_MILESTONE = "learning_milestone"  # Maria passed an exam / finished a file

    # Absence-based
    IDLE_CHECKIN = "idle_checkin"            # No operator contact in 48h+

    # Relationship-building (Faza 1 / K14.1): Maria asks ONE low-pressure
    # question/day to fill a high-value gap in her operator model. Flag-gated.
    OPERATOR_QUESTION = "operator_question"


# Cooldowns per reason (seconds) - prevents duplicate sends
CONTACT_COOLDOWNS: Dict[str, float] = {
    ContactReason.MORNING_SUMMARY.value: 72000,     # 20h (once per day)
    ContactReason.EVENING_RECAP.value: 72000,        # 20h
    ContactReason.WEEKLY_REVIEW.value: 604800,       # 7 days
    ContactReason.GOAL_ACHIEVED.value: 3600,         # 1h between goal notifications
    ContactReason.GOAL_PROPOSED.value: 600,          # 10min between PROPOSED-goal alerts
    # Learning is far more frequent than goals (many files/day) -> a longer
    # cooldown + the generator batching several passes into one message keeps it
    # from dominating the shared daily cap.
    ContactReason.LEARNING_MILESTONE.value: 7200,    # 2h between learning pings
    ContactReason.IDLE_CHECKIN.value: 172800,         # 48h
    ContactReason.OPERATOR_QUESTION.value: 86400,     # 24h (at most one ask/day)
    ContactReason.HYDRATION_NUDGE.value: 12600,       # 3.5h between water reminders
}

# Optional per-reason daily cap (separate from the global max_contacts_per_day).
# Absent reason = no per-reason cap (only the global cap applies).
MAX_PER_DAY_BY_REASON: Dict[str, int] = {
    ContactReason.HYDRATION_NUDGE.value: 2,           # gentle: at most 2 water nudges/day
}

# Time windows: (hour_start, hour_end) when each reason can fire
# None = any time (for event-based reasons)
CONTACT_WINDOWS: Dict[str, Optional[tuple]] = {
    ContactReason.MORNING_SUMMARY.value: (7, 9),
    ContactReason.EVENING_RECAP.value: (20, 21),
    ContactReason.WEEKLY_REVIEW.value: (19, 20),
    ContactReason.GOAL_ACHIEVED.value: None,         # any time (but not late night)
    ContactReason.GOAL_PROPOSED.value: None,         # any time (quiet hours still apply)
    ContactReason.LEARNING_MILESTONE.value: None,    # any time (quiet hours still apply)
    ContactReason.IDLE_CHECKIN.value: (9, 21),       # only during day
    ContactReason.OPERATOR_QUESTION.value: (10, 20),  # daytime only, never a nag
    ContactReason.HYDRATION_NUDGE.value: (11, 20),    # midday-to-evening heat window
}


@dataclass
class ProactiveContact:
    """A proactive message Maria wants to send."""

    reason: ContactReason
    message: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reason": self.reason.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class ProactiveState:
    """Persistent state for proactive scheduler."""

    enabled: bool = True
    last_sent: Dict[str, float] = field(default_factory=dict)  # reason -> ts
    contacts_today: int = 0
    sent_today_by_reason: Dict[str, int] = field(default_factory=dict)  # reason -> count today
    last_day: str = ""  # YYYY-MM-DD for daily counter reset
    last_operator_contact: float = 0.0  # ts of last Telegram message from operator
    seen_proposed_goal_ids: List[str] = field(default_factory=list)  # GOAL_PROPOSED dedup

    # Limits
    max_contacts_per_day: int = 8  # don't spam

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "last_sent": self.last_sent,
            "contacts_today": self.contacts_today,
            "sent_today_by_reason": dict(self.sent_today_by_reason),
            "last_day": self.last_day,
            "last_operator_contact": self.last_operator_contact,
            "seen_proposed_goal_ids": list(self.seen_proposed_goal_ids),
            "max_contacts_per_day": self.max_contacts_per_day,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProactiveState":
        return cls(
            enabled=data.get("enabled", True),
            last_sent=data.get("last_sent", {}),
            contacts_today=data.get("contacts_today", 0),
            sent_today_by_reason=data.get("sent_today_by_reason", {}),
            last_day=data.get("last_day", ""),
            last_operator_contact=data.get("last_operator_contact", 0.0),
            seen_proposed_goal_ids=list(data.get("seen_proposed_goal_ids", [])),
            max_contacts_per_day=data.get("max_contacts_per_day", 8),
        )
