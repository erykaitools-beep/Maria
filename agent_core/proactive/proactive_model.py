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

    # Event-based (triggered by system state)
    GOAL_ACHIEVED = "goal_achieved"          # A goal was completed
    GOAL_PROPOSED = "goal_proposed"          # New PROPOSED goal needs operator approval
    LEARNING_MILESTONE = "learning_milestone"  # File completed / exam passed
    INTEREST_MATCH = "interest_match"        # New content matches user interests

    # Absence-based
    IDLE_CHECKIN = "idle_checkin"            # No operator contact in 48h+


# Cooldowns per reason (seconds) - prevents duplicate sends
CONTACT_COOLDOWNS: Dict[str, float] = {
    ContactReason.MORNING_SUMMARY.value: 72000,     # 20h (once per day)
    ContactReason.EVENING_RECAP.value: 72000,        # 20h
    ContactReason.WEEKLY_REVIEW.value: 604800,       # 7 days
    ContactReason.GOAL_ACHIEVED.value: 3600,         # 1h between goal notifications
    ContactReason.GOAL_PROPOSED.value: 600,          # 10min between PROPOSED-goal alerts
    ContactReason.LEARNING_MILESTONE.value: 7200,    # 2h between milestones
    ContactReason.INTEREST_MATCH.value: 14400,       # 4h
    ContactReason.IDLE_CHECKIN.value: 172800,         # 48h
}

# Time windows: (hour_start, hour_end) when each reason can fire
# None = any time (for event-based reasons)
CONTACT_WINDOWS: Dict[str, Optional[tuple]] = {
    ContactReason.MORNING_SUMMARY.value: (7, 9),
    ContactReason.EVENING_RECAP.value: (20, 21),
    ContactReason.WEEKLY_REVIEW.value: (19, 20),
    ContactReason.GOAL_ACHIEVED.value: None,         # any time (but not late night)
    ContactReason.GOAL_PROPOSED.value: None,         # any time (quiet hours still apply)
    ContactReason.LEARNING_MILESTONE.value: None,
    ContactReason.INTEREST_MATCH.value: None,
    ContactReason.IDLE_CHECKIN.value: (9, 21),       # only during day
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
            last_day=data.get("last_day", ""),
            last_operator_contact=data.get("last_operator_contact", 0.0),
            seen_proposed_goal_ids=list(data.get("seen_proposed_goal_ids", [])),
            max_contacts_per_day=data.get("max_contacts_per_day", 8),
        )
