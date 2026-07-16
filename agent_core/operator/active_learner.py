"""ActiveLearner (Faza 1 / K14.1) -- Maria asks AT MOST one low-pressure question
per day to fill a high-value gap in her operator model, naturally, never as a
survey.

Design (the "Relacja" gap):
- pick_gap(): a pure, privacy-aware ranker over a small CURATED set of worth-asking
  facts. Picks the highest-value fact that is MISSING (or low-confidence), whose
  topic the operator has not made off-limits (PrivacyGuard), and which was not
  asked recently. Returns None when there is nothing worth asking.
- one pending question at a time: never stack a second question on an unanswered
  one (anti-survey).
- consume_answer(): the operator's next free-text reply to a pending question is
  stored back into the operator model (source="asked:telegram", so "where do I
  know this from" stays answerable).
- persistence: pending + per-key asked-timestamps survive restarts (a small JSON
  file), so the daily/cooldown discipline holds across the daemon lifecycle.

The actual "ask" is delivered by the ProactiveScheduler as a new
ContactReason.OPERATOR_QUESTION, which inherits its quiet-hours / daily-cap /
cooldown rate-limiting for free. Flag-gated OFF (ACTIVE_LEARNER_ENABLED).
"""

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Don't re-ask the same gap for a fortnight even if the operator dodges it.
_PER_KEY_COOLDOWN_SEC = 14 * 24 * 3600
# A fact this confident is "known enough" -- not a gap worth asking about.
_GAP_CONFIDENCE_FLOOR = 0.5
# A pending question older than this is abandoned (never answered): we stop
# treating the next unrelated message as its answer, and unwedge asking.
_PENDING_TTL_SEC = 6 * 3600
# A captured answer is a heuristic (the next message after we asked), so store it
# a notch below an explicit statement -- a later direct claim can override it.
_ANSWER_CONFIDENCE = 0.8


@dataclass(frozen=True)
class GapCandidate:
    """A fact worth asking about, with a natural Polish question + value weight."""

    key: str
    question: str
    weight: float


# Curated, deliberately small. High-value + relationship-building, low-pressure,
# privacy-safe. NOT an onboarding form -- the ranker surfaces ONE at a time.
GAP_CANDIDATES: List[GapCandidate] = [
    GapCandidate(
        "city",
        "Z jakiego miasta jestes? Chcialabym lepiej rozumiec Twoj kontekst.",
        0.9,
    ),
    GapCandidate(
        "personal_goal",
        "Masz jakis wiekszy cel na ten rok, w ktorym moglabym Ci pomoc?",
        0.7,
    ),
    GapCandidate(
        "weekend_routine",
        "Co lubisz robic w weekend, jak masz chwile wolnego?",
        0.5,
    ),
    GapCandidate(
        "favorite_music",
        "Czego ostatnio sluchasz? Lubie poznawac Twoje gusta.",
        0.4,
    ),
]


class ActiveLearner:
    """Decides what ONE thing to ask the operator next, and captures the answer."""

    def __init__(self, state_path: Optional[Path] = None):
        self._state_path = Path(state_path) if state_path else Path(
            "meta_data/active_learner_state.json"
        )
        self._lock = threading.Lock()  # proactive-tick ask vs poll-thread answer
        self._pending: Optional[str] = None
        self._pending_at: float = 0.0  # when the pending question was asked
        self._asked: dict = {}  # key -> last-asked epoch seconds
        self._load()

    # -- persistence --

    def _load(self) -> None:
        try:
            if self._state_path.exists():
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                self._pending = data.get("pending")
                self._pending_at = float(data.get("pending_at", 0.0) or 0.0)
                self._asked = {
                    k: float(v) for k, v in (data.get("asked") or {}).items()
                }
        except Exception as e:
            logger.debug("ActiveLearner state load failed: %s", e)

    def _save(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps({
                    "pending": self._pending,
                    "pending_at": self._pending_at,
                    "asked": self._asked,
                }),
                encoding="utf-8",
            )
            tmp.replace(self._state_path)
        except Exception as e:
            logger.debug("ActiveLearner state save failed: %s", e)

    # -- decision core (pure-ish: only reads the operator model) --

    def has_pending(self) -> bool:
        return bool(self._pending)

    def pending_key(self) -> Optional[str]:
        return self._pending

    def pick_gap(self, operator_model, now: Optional[float] = None) -> Optional[str]:
        """Highest-value gap worth asking about, or None.

        A candidate is a gap when the fact is missing or below the confidence
        floor, the operator has not put the topic off-limits (PrivacyGuard), and
        it was not asked within the per-key cooldown."""
        now = time.time() if now is None else now
        for cand in sorted(GAP_CANDIDATES, key=lambda c: c.weight, reverse=True):
            fact = None
            try:
                fact = operator_model.get_fact(cand.key)
            except Exception:
                pass
            if fact is not None and getattr(fact, "confidence", 1.0) >= _GAP_CONFIDENCE_FLOOR:
                continue  # known well enough
            # Privacy: never ask across an operator-defined boundary.
            try:
                if not operator_model.is_allowed(cand.key):
                    continue
            except Exception:
                pass  # if privacy can't be checked, don't block (boundaries empty by default)
            last = self._asked.get(cand.key, 0.0)
            if now - last < _PER_KEY_COOLDOWN_SEC:
                continue  # asked recently
            return cand.key
        return None

    def question_for(self, key: str) -> Optional[str]:
        for cand in GAP_CANDIDATES:
            if cand.key == key:
                return cand.question
        return None

    def _clear_stale_pending(self, now: float) -> None:
        """Drop a pending question never answered within the TTL: so a much-later
        unrelated message isn't mis-captured as its answer, and a question whose
        delivery failed doesn't wedge asking forever. Caller holds the lock. The
        asked-timestamp stays, so the same gap isn't re-asked immediately."""
        if self._pending and (now - self._pending_at) > _PENDING_TTL_SEC:
            self._pending = None
            self._save()

    def next_question(self, operator_model, now: Optional[float] = None) -> Optional[str]:
        """The full 'should I ask, and what' step the generator calls.

        Returns the question text (and records it as pending + asked) or None.
        Never stacks a second question on an unanswered (fresh) one."""
        now = time.time() if now is None else now
        with self._lock:
            self._clear_stale_pending(now)
            if self._pending:
                return None  # one open question at a time
            key = self.pick_gap(operator_model, now=now)
            if not key:
                return None
            q = self.question_for(key)
            if not q:
                return None
            self._pending = key
            self._pending_at = now
            self._asked[key] = now
            self._save()
            return q

    def consume_answer(
        self, text: str, operator_model, now: Optional[float] = None
    ) -> Optional[str]:
        """If a FRESH question is pending, store the operator's reply as its answer
        and clear the pending slot. Returns the fact key filled, or None.

        Stored with source='asked:telegram' (provenance answerable) at a hedged
        confidence -- it's a heuristic capture (the next message after we asked),
        not a parsed statement. A stale pending is dropped, not answered. set_fact
        enforces privacy itself."""
        now = time.time() if now is None else now
        value = (text or "").strip()
        with self._lock:
            self._clear_stale_pending(now)
            if not self._pending or not value:
                return None
            key = self._pending
            try:
                operator_model.set_fact(
                    key, value, confidence=_ANSWER_CONFIDENCE, source="asked:telegram"
                )
            except Exception as e:
                logger.debug("ActiveLearner consume_answer set_fact failed: %s", e)
                return None
            self._pending = None
            self._save()
            return key
