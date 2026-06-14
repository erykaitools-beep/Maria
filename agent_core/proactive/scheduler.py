"""
Proactive contact scheduler - tick-based, runs in homeostasis Phase 13.

Checks conditions on each tick (every ~60s) and fires proactive messages
when appropriate. Respects time windows, cooldowns, and daily limits.

Persistence: meta_data/proactive_state.json (survives restarts).
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from agent_core.homeostasis.time_awareness import TimeAwareness
from agent_core.proactive.generators import ContentGenerators
from agent_core.proactive.proactive_model import (
    CONTACT_COOLDOWNS,
    CONTACT_WINDOWS,
    ContactReason,
    ProactiveContact,
    ProactiveState,
)

logger = logging.getLogger(__name__)

# Check every N ticks (1 tick ~ 1s, check every 60s)
CHECK_INTERVAL_TICKS = 60

# Late night block: no proactive contact 23:00-6:00
QUIET_HOURS_START = 23
QUIET_HOURS_END = 6

# Default persistence path
_META_DIR = Path(__file__).resolve().parents[2] / "meta_data"
_STATE_FILE = _META_DIR / "proactive_state.json"

# History log (append-only, for tracking)
_HISTORY_FILE = _META_DIR / "proactive_contacts.jsonl"


class ProactiveScheduler:
    """
    Tick-based proactive contact scheduler.

    Usage:
        scheduler = ProactiveScheduler()
        scheduler.set_notify_fn(telegram_send_raw)
        scheduler.generators.set_evaluation_fn(...)
        # In homeostasis tick loop:
        scheduler.tick()
    """

    def __init__(self, state_path: Optional[Path] = None):
        self._state_path = state_path or _STATE_FILE
        self._history_path = _HISTORY_FILE
        self._state = self._load_state()
        self._generators = ContentGenerators()
        self._notify_fn: Optional[Callable[[str], None]] = None
        self._tick_count = 0

        # Event queue for triggered contacts (goal_achieved, etc.)
        self._pending_events: List[ContactReason] = []

    @property
    def generators(self) -> ContentGenerators:
        return self._generators

    @property
    def state(self) -> ProactiveState:
        return self._state

    @property
    def enabled(self) -> bool:
        return self._state.enabled

    def set_notify_fn(self, fn: Callable[[str], None]) -> None:
        """Set Telegram send function."""
        self._notify_fn = fn

    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable proactive contact."""
        self._state.enabled = enabled
        self._save_state()

    def record_operator_contact(self) -> None:
        """Record that operator sent a message (resets idle timer)."""
        self._state.last_operator_contact = time.time()
        self._save_state()

    def trigger_event(self, reason: ContactReason) -> None:
        """Queue an event-based contact (e.g. goal achieved)."""
        if reason not in self._pending_events:
            self._pending_events.append(reason)

    def tick(self) -> int:
        """
        Called every homeostasis tick. Returns number of contacts sent.

        Only checks every CHECK_INTERVAL_TICKS ticks (~60s).
        """
        self._tick_count += 1
        if self._tick_count % CHECK_INTERVAL_TICKS != 0:
            return 0

        if not self._state.enabled:
            return 0

        if not self._notify_fn:
            return 0

        # Reset daily counter
        today = datetime.now().strftime("%Y-%m-%d")
        if self._state.last_day != today:
            self._state.contacts_today = 0
            self._state.last_day = today

        # Daily limit check
        if self._state.contacts_today >= self._state.max_contacts_per_day:
            return 0

        # Quiet hours check (global)
        if self._is_quiet_hours():
            return 0

        sent = 0

        # 1. Process event queue first
        sent += self._process_events()

        # 2. Check scheduled contacts
        sent += self._check_scheduled()

        # 3. Check idle checkin
        sent += self._check_idle()

        # 4. Check for new PROPOSED goals (escalator / planner / etc.)
        # Always runs — also syncs seen-set when no notify is needed,
        # so seen_proposed_goal_ids reflects current goal_store snapshot.
        sent += self._check_proposed_goals()

        if sent > 0:
            self._save_state()

        return sent

    def _process_events(self) -> int:
        """Process queued event-based contacts."""
        sent = 0
        events = list(self._pending_events)
        self._pending_events.clear()

        for reason in events:
            if not self._can_send(reason):
                continue
            contact = self._generators.generate(reason)
            if contact:
                self._send(contact)
                sent += 1

        return sent

    def _check_scheduled(self) -> int:
        """Check time-based contacts (morning, evening, weekly)."""
        sent = 0
        now = datetime.now()

        scheduled_reasons = [
            ContactReason.MORNING_SUMMARY,
            ContactReason.EVENING_RECAP,
        ]

        # Weekly review only on Sunday
        if now.weekday() == 6:
            scheduled_reasons.append(ContactReason.WEEKLY_REVIEW)

        for reason in scheduled_reasons:
            if not self._in_time_window(reason):
                continue
            if not self._can_send(reason):
                continue
            contact = self._generators.generate(reason)
            if contact:
                self._send(contact)
                sent += 1

        return sent

    def _check_idle(self) -> int:
        """Check if operator has been absent long enough for idle checkin."""
        if not self._can_send(ContactReason.IDLE_CHECKIN):
            return 0
        if not self._in_time_window(ContactReason.IDLE_CHECKIN):
            return 0

        last_contact = self._state.last_operator_contact
        if last_contact <= 0:
            return 0  # Never contacted - skip (startup grace)

        idle_sec = time.time() - last_contact
        cooldown = CONTACT_COOLDOWNS.get(
            ContactReason.IDLE_CHECKIN.value, 172800
        )

        if idle_sec < cooldown:
            return 0

        contact = self._generators.generate(ContactReason.IDLE_CHECKIN)
        if contact:
            self._send(contact)
            return 1
        return 0

    def _check_proposed_goals(self) -> int:
        """Detect newly created PROPOSED goals and notify operator.

        Compares the current PROPOSED goal IDs against seen_proposed_goal_ids
        in state. If new ones appear and cooldown allows, sends one alert
        (single or batch format chosen by the generator). The seen-set is
        always synchronised to the current snapshot — confirmed/rejected
        goals drop out, so a future re-PROPOSE with the same id (unlikely
        in practice but possible) would re-notify only after re-creation.
        """
        accessor = self._generators._get_proposed_goals
        if accessor is None:
            return 0

        try:
            current = accessor() or []
        except Exception as e:
            logger.debug(f"Proposed-goals accessor failed: {e}")
            return 0

        seen = set(self._state.seen_proposed_goal_ids)
        current_ids = [
            g.get("id") for g in current if isinstance(g, dict) and g.get("id")
        ]
        current_id_set = set(current_ids)

        new_ids = current_id_set - seen
        if not new_ids:
            # Sync seen-set to current (drop confirmed/rejected ids) but don't notify.
            if seen != current_id_set:
                self._state.seen_proposed_goal_ids = list(current_id_set)
                self._save_state()
            return 0

        if not self._can_send(ContactReason.GOAL_PROPOSED):
            # Cooldown active — don't notify and don't update seen-set,
            # so the next eligible tick still sees these as new.
            return 0

        if not self._in_time_window(ContactReason.GOAL_PROPOSED):
            return 0

        new_goals = [g for g in current if g.get("id") in new_ids]
        contact = self._generators.proposed_goal_alert(new_goals)
        if contact is None:
            return 0

        self._send(contact)
        # Mark all currently-PROPOSED ids as seen (covers both notified
        # new ones and any pre-existing ones already in the set).
        self._state.seen_proposed_goal_ids = list(current_id_set)
        return 1

    def _can_send(self, reason: ContactReason) -> bool:
        """Check cooldown for this reason."""
        cooldown = CONTACT_COOLDOWNS.get(reason.value, 3600)
        last = self._state.last_sent.get(reason.value, 0)
        return (time.time() - last) >= cooldown

    def _in_time_window(self, reason: ContactReason) -> bool:
        """Check if current time is in the allowed window for this reason."""
        window = CONTACT_WINDOWS.get(reason.value)
        if window is None:
            # No window restriction, but still block quiet hours
            return not self._is_quiet_hours()

        hour = datetime.now().hour
        start, end = window
        return start <= hour < end

    def _is_quiet_hours(self) -> bool:
        """Check if we're in quiet hours (late night)."""
        hour = datetime.now().hour
        return hour >= QUIET_HOURS_START or hour < QUIET_HOURS_END

    def _send(self, contact: ProactiveContact) -> None:
        """Send a proactive contact and update state."""
        try:
            self._notify_fn(contact.message)
            self._state.last_sent[contact.reason.value] = time.time()
            self._state.contacts_today += 1
            self._log_contact(contact)
            logger.info(
                "Proactive contact sent: %s (today: %d)",
                contact.reason.value,
                self._state.contacts_today,
            )
        except Exception as e:
            logger.warning("Failed to send proactive contact: %s", e)

    def _log_contact(self, contact: ProactiveContact) -> None:
        """Append contact to history JSONL."""
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._history_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(contact.to_dict(), ensure_ascii=False) + "\n")
        except OSError:
            pass

    # -- Persistence --

    def _load_state(self) -> ProactiveState:
        """Load state from JSON file."""
        try:
            if self._state_path.exists():
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                return ProactiveState.from_dict(data)
        except (json.JSONDecodeError, OSError, KeyError) as e:
            logger.debug("Failed to load proactive state: %s", e)
        return ProactiveState()

    def _save_state(self) -> None:
        """Save state to JSON file."""
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps(self._state.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.debug("Failed to save proactive state: %s", e)

    # -- Status --

    def get_status(self) -> Dict:
        """Get scheduler status for diagnostics."""
        now = time.time()
        cooldown_status = {}
        for reason in ContactReason:
            cooldown = CONTACT_COOLDOWNS.get(reason.value, 3600)
            last = self._state.last_sent.get(reason.value, 0)
            remaining = max(0, cooldown - (now - last)) if last > 0 else 0
            cooldown_status[reason.value] = {
                "cooldown_sec": cooldown,
                "remaining_sec": round(remaining),
                "last_sent": last,
            }

        idle_sec = (
            now - self._state.last_operator_contact
            if self._state.last_operator_contact > 0
            else 0
        )

        return {
            "enabled": self._state.enabled,
            "contacts_today": self._state.contacts_today,
            "max_per_day": self._state.max_contacts_per_day,
            "quiet_hours": self._is_quiet_hours(),
            "current_hour": datetime.now().hour,
            "operator_idle_sec": round(idle_sec),
            "operator_idle_human": TimeAwareness.format_duration(idle_sec) if idle_sec > 0 else "n/a",
            "cooldowns": cooldown_status,
        }

    def get_history(self, limit: int = 10) -> List[Dict]:
        """Read recent proactive contacts from history."""
        if not self._history_path.exists():
            return []
        records = []
        try:
            with open(self._history_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except OSError:
            pass
        return records[-limit:]
