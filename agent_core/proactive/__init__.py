"""
Proactive Contact Module - Maria initiates contact with the operator.

Types of proactive contact:
- MORNING_SUMMARY: Daily briefing (7:00-9:00)
- EVENING_RECAP: Day summary (20:00-21:00)
- WEEKLY_REVIEW: Weekly stats (Sunday 19:00-20:00)
- GOAL_ACHIEVED: Goal completion notification (fired live via GoalStore observer)
- GOAL_PROPOSED: New PROPOSED goal needs operator approval
- IDLE_CHECKIN: Check-in after 48h+ of no contact

Integration:
    Runs as Phase 13 in homeostasis tick loop.
    Uses TelegramNotifier.send_raw() for delivery.
    Respects quiet hours (23:00-6:00) and daily limits (8/day).
"""

from agent_core.proactive.generators import ContentGenerators
from agent_core.proactive.proactive_model import (
    CONTACT_COOLDOWNS,
    CONTACT_WINDOWS,
    ContactReason,
    ProactiveContact,
    ProactiveState,
)
from agent_core.proactive.scheduler import ProactiveScheduler

__all__ = [
    "ContactReason",
    "ProactiveContact",
    "ProactiveState",
    "ProactiveScheduler",
    "ContentGenerators",
    "CONTACT_COOLDOWNS",
    "CONTACT_WINDOWS",
]
