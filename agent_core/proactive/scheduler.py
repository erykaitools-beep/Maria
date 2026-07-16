"""
Proactive contact scheduler - tick-based, runs in homeostasis Phase 13.

Checks conditions on each tick (every ~60s) and fires proactive messages
when appropriate. Respects time windows, cooldowns, and daily limits.

Persistence: meta_data/proactive_state.json (survives restarts).
"""

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from agent_core.homeostasis.time_awareness import TimeAwareness
from agent_core.proactive.generators import ContentGenerators
from agent_core.proactive.proactive_model import (
    CONTACT_COOLDOWNS,
    CONTACT_WINDOWS,
    MAX_PER_DAY_BY_REASON,
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

# Learning-milestone dedup: don't re-announce the same file within this window
# (spaced-repetition re-exams a COMPLETED file and would otherwise re-ping).
_MILESTONE_DEDUP_SEC = 24 * 3600
_MILESTONE_BUFFER_CAP = 10

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

        # Event queue for triggered contacts (goal_achieved, etc.).
        # Written by trigger_event() from whatever thread mutates the goal
        # store (planner/teacher); drained by _process_events() on the tick
        # thread -- guard the queue so the snapshot+clear stays atomic.
        self._pending_events: List[ContactReason] = []
        self._events_lock = threading.Lock()

        # LEARNING_MILESTONE buffer: passed-exam milestones the generator drains
        # at send time (twin of GOAL_ACHIEVED's recent-achievements pull). Guarded
        # by _events_lock. _milestone_seen dedups the same file within 24h.
        self._milestone_buffer: List[Dict] = []
        self._milestone_seen: Dict[str, float] = {}

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
        with self._events_lock:
            if reason not in self._pending_events:
                self._pending_events.append(reason)

    def bind_goal_store(self, goal_store) -> None:
        """Wire live GOAL_ACHIEVED contacts to goal-store achievements.

        Registers a status observer on the store; any real transition into
        ACHIEVED queues a GOAL_ACHIEVED event (CONTACT_COOLDOWNS throttles to
        <=1/h, daily cap still applies). This is the production caller of
        trigger_event() -- without it the event path is dead code.

        The "achieved" status is matched by value to keep proactive decoupled
        from agent_core.goals (no import). Safe no-op if the store predates the
        observer API.
        """
        if goal_store is None or not hasattr(goal_store, "register_status_observer"):
            return

        def _on_goal_status(goal, old_status, new_status):
            if new_status == "achieved":
                self.trigger_event(ContactReason.GOAL_ACHIEVED)

        goal_store.register_status_observer(_on_goal_status)

    def note_learning_milestone(self, topic: str, score: float) -> None:
        """Record a passed-exam milestone and queue a LEARNING_MILESTONE contact.

        Called by the teacher when an exam PASSES (file finished + verified).
        The same file is deduped within 24h so spaced-repetition re-passes of
        already-learned material don't spam the operator. The actual send is
        still gated by the LEARNING_MILESTONE cooldown + daily cap; the generator
        drains this buffer at send time, batching several passes into one ping.
        """
        if not topic:
            return
        now = time.time()
        with self._events_lock:
            last = self._milestone_seen.get(topic, 0.0)
            if now - last < _MILESTONE_DEDUP_SEC:
                return  # already announced this file recently
            self._milestone_seen[topic] = now
            # Prune stale dedup entries so the map can't grow unbounded.
            self._milestone_seen = {
                k: v for k, v in self._milestone_seen.items()
                if now - v < _MILESTONE_DEDUP_SEC
            }
            self._milestone_buffer.append({"topic": topic, "score": score, "ts": now})
            if len(self._milestone_buffer) > _MILESTONE_BUFFER_CAP:
                self._milestone_buffer = self._milestone_buffer[-_MILESTONE_BUFFER_CAP:]
        # trigger_event takes _events_lock too -> call it OUTSIDE the block above.
        self.trigger_event(ContactReason.LEARNING_MILESTONE)

    def drain_recent_milestones(self) -> List[Dict]:
        """Return queued learning milestones and clear them (generator accessor).

        Drains rather than peeks so a milestone is announced once; if the ping is
        cooldown-dropped, generate() is never called, so the buffer is retained
        for the next eligible tick.
        """
        with self._events_lock:
            items = list(self._milestone_buffer)
            self._milestone_buffer.clear()
            return items

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

        # Reset daily counters
        today = datetime.now().strftime("%Y-%m-%d")
        if self._state.last_day != today:
            self._state.contacts_today = 0
            self._state.sent_today_by_reason = {}
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
        with self._events_lock:
            events = list(self._pending_events)
            self._pending_events.clear()

        for reason in events:
            # Cooldown-blocked events are intentionally dropped, not re-queued:
            # GOAL_ACHIEVED is not must-deliver -- the generator always pulls the
            # current recent-achievements list, so the next achievement re-fires
            # with fresh content. Add re-queue logic only if a must-survive event
            # type is introduced.
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

        # Faza 1 / K14.1: Maria asks one low-pressure question/day (ActiveLearner).
        # Flag-gated OFF; inherits this loop's window + cooldown + daily-cap, so it
        # can never nag. The generator returns None when there is nothing worth
        # asking or a question is already open.
        if os.environ.get("ACTIVE_LEARNER_ENABLED", "").strip().lower() in (
            "1", "true", "yes", "on",
        ):
            scheduled_reasons.append(ContactReason.OPERATOR_QUESTION)

        # Hot-weather hydration nudge (during-day care). Flag-gated, default ON:
        # the generator returns None unless it is genuinely hot, so mild days
        # are silent regardless. MAX_PER_DAY_BY_REASON caps it at 2/day.
        if os.environ.get("HYDRATION_NUDGE_ENABLED", "true").strip().lower() in (
            "1", "true", "yes", "on",
        ):
            scheduled_reasons.append(ContactReason.HYDRATION_NUDGE)

        for reason in scheduled_reasons:
            if not self._in_time_window(reason):
                continue
            if not self._can_send(reason):
                continue
            if not self._under_daily_reason_cap(reason):
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

    def _under_daily_reason_cap(self, reason: ContactReason) -> bool:
        """Check the optional per-reason daily cap (separate from the global cap).

        Most reasons have no entry in MAX_PER_DAY_BY_REASON and are unbounded
        here (only the global max_contacts_per_day + cooldown apply). The
        hydration nudge uses this to stay gentle (<=2/day) even though its
        3.5h cooldown would otherwise allow a third fire in the window.
        """
        cap = MAX_PER_DAY_BY_REASON.get(reason.value)
        if cap is None:
            return True
        return self._state.sent_today_by_reason.get(reason.value, 0) < cap

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
            self._state.sent_today_by_reason[contact.reason.value] = (
                self._state.sent_today_by_reason.get(contact.reason.value, 0) + 1
            )
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
