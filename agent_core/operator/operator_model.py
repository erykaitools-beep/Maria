"""
OperatorModel - 5-dimensional understanding of the operator.

Replaces flat UserProfile with structured, confidence-scored knowledge.
Persistence: meta_data/operator_model.json (atomic writes, cross-process safe).

Dimensions:
1. Durable Facts - structured knowledge (name, job, city) with confidence + source
2. Preferences - communication and autonomy settings
3. Day Rhythm - temporal patterns from interaction history
4. Current Context - volatile state with auto-expiry
5. Privacy Boundaries - hard limits (via PrivacyGuard)

Migration: auto-imports from user_profile.json on first use.
"""

import json
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent_core.operator.privacy_guard import PrivacyGuard

logger = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = Path("meta_data/operator_model.json")
LEGACY_PROFILE_PATH = Path("meta_data/user_profile.json")


# ── Data structures ──────────────────────────────────────────────


@dataclass
class OperatorFact:
    """A single fact about the operator with provenance."""

    value: str
    confidence: float = 1.0  # 1.0=explicit, 0.6=inferred, 0.4=pattern
    source: str = ""  # e.g. "telegram:message", "explicit:/profile set"
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "OperatorFact":
        return cls(
            value=str(d.get("value", "")),
            confidence=float(d.get("confidence", 1.0)),
            source=str(d.get("source", "")),
            updated_at=str(d.get("updated_at", "")),
        )


@dataclass
class DayRhythm:
    """Detected temporal patterns in operator's behavior."""

    typical_wake_hour: int = 7
    typical_sleep_hour: int = 23
    work_hours: List[int] = field(default_factory=lambda: [9, 17])
    weekend_days: List[int] = field(default_factory=lambda: [5, 6])  # Sat=5, Sun=6
    confidence: float = 0.0  # 0.0 = defaults, higher = more data
    sample_count: int = 0
    last_analyzed: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DayRhythm":
        return cls(
            typical_wake_hour=int(d.get("typical_wake_hour", 7)),
            typical_sleep_hour=int(d.get("typical_sleep_hour", 23)),
            work_hours=list(d.get("work_hours", [9, 17])),
            weekend_days=list(d.get("weekend_days", [5, 6])),
            confidence=float(d.get("confidence", 0.0)),
            sample_count=int(d.get("sample_count", 0)),
            last_analyzed=str(d.get("last_analyzed", "")),
        )


@dataclass
class CurrentContext:
    """Volatile operator context with auto-expiry."""

    text: Optional[str] = None
    set_at: Optional[float] = None  # unix timestamp
    expires_at: Optional[float] = None  # unix timestamp

    def is_active(self) -> bool:
        if self.text is None:
            return False
        if self.expires_at is not None and time.time() > self.expires_at:
            return False
        return True

    def get_text(self) -> Optional[str]:
        """Return text if active, None if expired."""
        if self.is_active():
            return self.text
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "set_at": self.set_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CurrentContext":
        return cls(
            text=d.get("text"),
            set_at=d.get("set_at"),
            expires_at=d.get("expires_at"),
        )


# ── Main class ───────────────────────────────────────────────────


class OperatorModel:
    """
    5-dimensional operator understanding with confidence scoring.

    Thread-safe. All mutations auto-save to disk.
    Cross-process safe via mtime check on reads.
    """

    VERSION = 2

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path or DEFAULT_MODEL_PATH)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Re-entrant: readers take the lock and then call _reload_if_changed,
        # which also takes the lock (E1 race fix). A plain Lock would deadlock.
        self._lock = threading.RLock()
        self._last_mtime: float = 0.0

        # Initialize sub-objects first (needed by _save)
        self._privacy = PrivacyGuard()
        self._rhythm = DayRhythm()
        self._context = CurrentContext()

        # Load or migrate
        if self._path.exists() and self._path.stat().st_size > 2:
            self._data = self._load()
        elif LEGACY_PROFILE_PATH.exists():
            self._data = self._migrate_from_user_profile()
        else:
            self._data = self._create_default()
            self._save()

        self._last_mtime = self._get_mtime()

        # Re-initialize sub-objects from loaded data
        self._privacy = PrivacyGuard.from_list(
            self._data.get("privacy_boundaries", [])
        )
        self._rhythm = DayRhythm.from_dict(self._data.get("day_rhythm", {}))
        self._context = CurrentContext.from_dict(
            self._data.get("current_context", {})
        )

    # ── Persistence ─────────────────────────────��────────────

    def _create_default(self) -> Dict[str, Any]:
        return {
            "version": self.VERSION,
            "durable_facts": {
                "name": OperatorFact(
                    value="Operator", confidence=0.1, source="default"
                ).to_dict(),
            },
            "preferences": {
                "response_style": "casual",
                "autonomy_level": "medium",
                "notify_channel": "telegram",
                "detail_level": "normal",
                "quiet_hours": [23, 6],
            },
            "interests": [],
            "schedule_notes": [],
            "day_rhythm": DayRhythm().to_dict(),
            "current_context": CurrentContext().to_dict(),
            "privacy_boundaries": [],
            "stats": {
                "first_seen": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "total_messages": 0,
                "sessions_count": 0,
            },
            "updated_at": datetime.now().isoformat(),
        }

    def _load(self) -> Dict[str, Any]:
        """Load from disk with retry."""
        for attempt in range(2):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data = self._ensure_schema(data)
                logger.info("[OperatorModel] Loaded from %s", self._path)
                return data
            except (json.JSONDecodeError, IOError) as e:
                if attempt == 0:
                    time.sleep(0.1)
                else:
                    logger.warning("[OperatorModel] Load failed: %s", e)
        return self._create_default()

    def _ensure_schema(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure all required sections exist."""
        defaults = self._create_default()
        for section in (
            "durable_facts", "preferences", "stats",
            "day_rhythm", "current_context",
        ):
            if section not in data:
                data[section] = defaults[section]
        if "interests" not in data:
            data["interests"] = []
        if "schedule_notes" not in data:
            data["schedule_notes"] = []
        # E2: migrate the legacy single 'schedule_note' durable fact (which every
        # add_schedule_note call overwrote, discarding all prior notes) into the
        # accumulating list. Idempotent: pop removes it so reloads do not re-add.
        legacy_note = data.get("durable_facts", {}).pop("schedule_note", None)
        if isinstance(legacy_note, dict) and legacy_note.get("value"):
            if legacy_note["value"] not in data["schedule_notes"]:
                data["schedule_notes"].append(legacy_note["value"])
        if "privacy_boundaries" not in data:
            data["privacy_boundaries"] = []
        if "version" not in data:
            data["version"] = self.VERSION
        return data

    def _get_mtime(self) -> float:
        try:
            return self._path.stat().st_mtime if self._path.exists() else 0.0
        except OSError:
            return 0.0

    def _reload_if_changed(self) -> None:
        """Reload from disk if modified by another process.

        Runs the rebind under self._lock (RLock) so _data/_privacy/_rhythm/
        _context are swapped atomically versus concurrent writers and other
        readers -- a reader iterating _data must never observe a half-swapped
        model, nor have the dict rebound mid-iteration (E1). Cheap mtime check
        first (double-checked locking) keeps the common no-change path lock-free.
        """
        if self._get_mtime() <= self._last_mtime:
            return
        with self._lock:
            mtime = self._get_mtime()
            if mtime <= self._last_mtime:
                return
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._data = self._ensure_schema(data)
                self._privacy = PrivacyGuard.from_list(
                    data.get("privacy_boundaries", [])
                )
                self._rhythm = DayRhythm.from_dict(data.get("day_rhythm", {}))
                self._context = CurrentContext.from_dict(
                    data.get("current_context", {})
                )
                self._last_mtime = mtime
            except (json.JSONDecodeError, IOError):
                pass

    def _save(self) -> None:
        """Atomic save to disk."""
        self._data["updated_at"] = datetime.now().isoformat()
        self._data["privacy_boundaries"] = self._privacy.to_list()
        self._data["day_rhythm"] = self._rhythm.to_dict()
        self._data["current_context"] = self._context.to_dict()
        try:
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            tmp.replace(self._path)
            self._last_mtime = self._get_mtime()
        except IOError as e:
            logger.warning("[OperatorModel] Save failed: %s", e)

    # ── Migration from UserProfile ───────────────────────────

    def _migrate_from_user_profile(self) -> Dict[str, Any]:
        """One-time migration from legacy user_profile.json."""
        logger.info("[OperatorModel] Migrating from user_profile.json")
        try:
            with open(LEGACY_PROFILE_PATH, "r", encoding="utf-8") as f:
                old = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("[OperatorModel] Migration failed: %s", e)
            return self._create_default()

        data = self._create_default()
        now = datetime.now().isoformat()

        # Identity -> durable_facts
        identity = old.get("identity", {})
        if identity.get("name") and identity["name"] != "Operator":
            data["durable_facts"]["name"] = OperatorFact(
                value=identity["name"],
                confidence=1.0,
                source="migrated:user_profile",
                updated_at=now,
            ).to_dict()

        if identity.get("language"):
            data["durable_facts"]["language"] = OperatorFact(
                value=identity["language"],
                confidence=1.0,
                source="migrated:user_profile",
                updated_at=now,
            ).to_dict()

        if identity.get("timezone"):
            data["durable_facts"]["timezone"] = OperatorFact(
                value=identity["timezone"],
                confidence=1.0,
                source="migrated:user_profile",
                updated_at=now,
            ).to_dict()

        # Parse structured facts from free-form facts list
        for fact_text in old.get("facts", []):
            self._parse_fact_into(data["durable_facts"], fact_text, now)

        # Preferences
        prefs = old.get("preferences", {})
        for key in ("response_style", "autonomy_level", "notify_channel"):
            if key in prefs:
                data["preferences"][key] = prefs[key]

        # Interests
        data["interests"] = list(old.get("interests", []))

        # Schedule notes -> store as facts
        for note in old.get("schedule", {}).get("notes", []):
            if "praca:" in note.lower() or "work:" in note.lower():
                # Try to extract work hours
                m = re.search(r"(\d{1,2})-(\d{1,2})", note)
                if m:
                    data["day_rhythm"]["work_hours"] = [
                        int(m.group(1)), int(m.group(2))
                    ]
                    data["day_rhythm"]["confidence"] = 0.6
                data["durable_facts"]["work_schedule"] = OperatorFact(
                    value=note,
                    confidence=0.8,
                    source="migrated:user_profile",
                    updated_at=now,
                ).to_dict()

        # Stats
        data["stats"] = old.get("stats", data["stats"])

        self._save_data(data)
        logger.info("[OperatorModel] Migration complete")
        return data

    def _save_data(self, data: Dict[str, Any]) -> None:
        """Save specific data dict (used during migration)."""
        data["updated_at"] = datetime.now().isoformat()
        try:
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp.replace(self._path)
        except IOError as e:
            logger.warning("[OperatorModel] Save failed: %s", e)

    @staticmethod
    def _parse_fact_into(
        facts_dict: Dict[str, Any], text: str, now: str
    ) -> None:
        """Parse free-form fact text into structured durable_facts."""
        text_lower = text.lower().strip()

        # Age: "mam 32lata", "mam 32 lat"
        m = re.search(r"mam\s+(\d{1,3})\s*lat", text_lower)
        if m:
            facts_dict["age"] = OperatorFact(
                value=m.group(1),
                confidence=1.0,
                source="migrated:parsed",
                updated_at=now,
            ).to_dict()

        # Job: "pracuje jako X", "pracuje obecnie jako X"
        m = re.search(
            r"pracuj[eę]\s+(?:obecnie\s+)?jako\s+(.+?)(?:\s+w\s+|\s*[,.]|$)",
            text_lower,
        )
        if m:
            facts_dict["job"] = OperatorFact(
                value=m.group(1).strip(),
                confidence=1.0,
                source="migrated:parsed",
                updated_at=now,
            ).to_dict()

        # Job location: "w Niemczech", "w Polsce", "w Berlinie"
        m = re.search(r"w\s+(niemczech|polsce|[\w]+u|[\w]+ie|[\w]+ach)\b", text_lower)
        if m:
            facts_dict["job_location"] = OperatorFact(
                value=m.group(1).strip().capitalize(),
                confidence=0.8,
                source="migrated:parsed",
                updated_at=now,
            ).to_dict()

        # City: "mieszkam w X"
        m = re.search(r"mieszkam\s+w\s+(\w+)", text_lower)
        if m:
            facts_dict["city"] = OperatorFact(
                value=m.group(1).strip().capitalize(),
                confidence=1.0,
                source="migrated:parsed",
                updated_at=now,
            ).to_dict()

    # ── Durable Facts ────────────────────────────────────────

    def set_fact(
        self,
        key: str,
        value: str,
        confidence: float = 1.0,
        source: str = "",
    ) -> None:
        """Set a durable fact about the operator."""
        key = key.strip().lower()
        if not key or not value:
            return
        # Privacy check
        if not self._privacy.is_allowed(key) or not self._privacy.is_allowed(value):
            logger.debug("[OperatorModel] Blocked by privacy: %s", key)
            return
        with self._lock:
            self._reload_if_changed()  # E3: read-modify-write (whole-doc save)
            self._data["durable_facts"][key] = OperatorFact(
                value=value.strip()[:200],
                confidence=min(max(confidence, 0.0), 1.0),
                source=source,
                updated_at=datetime.now().isoformat(),
            ).to_dict()
            self._save()

    def get_fact(self, key: str) -> Optional[OperatorFact]:
        """Get a durable fact. Returns None if not found."""
        self._reload_if_changed()
        raw = self._data.get("durable_facts", {}).get(key.strip().lower())
        if raw is None:
            return None
        return OperatorFact.from_dict(raw)

    def get_fact_value(self, key: str, default: str = "") -> str:
        """Get just the value of a fact."""
        fact = self.get_fact(key)
        return fact.value if fact else default

    def get_all_facts(self) -> Dict[str, OperatorFact]:
        """Get all durable facts."""
        with self._lock:  # E1: iterate durable_facts under lock (no torn read)
            self._reload_if_changed()
            result = {}
            for key, raw in self._data.get("durable_facts", {}).items():
                if isinstance(raw, dict):
                    result[key] = OperatorFact.from_dict(raw)
            return result

    def is_allowed(self, topic: str) -> bool:
        """Public privacy check: may Maria ask about / store this topic or value?

        Used by ActiveLearner before asking about a gap -- never ask across an
        operator-defined boundary. Defaults to allowed when privacy can't decide
        (boundaries are empty by default)."""
        try:
            return self._privacy.is_allowed(topic)
        except Exception:
            return True

    def remove_fact(self, key: str) -> bool:
        """Remove a fact. Returns True if found."""
        key = key.strip().lower()
        with self._lock:
            self._reload_if_changed()  # E3
            if key in self._data.get("durable_facts", {}):
                del self._data["durable_facts"][key]
                self._save()
                return True
        return False

    # ── Preferences ────────────────────────────────���─────────

    def get_preference(self, key: str, default: Any = None) -> Any:
        self._reload_if_changed()
        return self._data.get("preferences", {}).get(key, default)

    def set_preference(self, key: str, value: Any) -> None:
        with self._lock:
            self._reload_if_changed()  # E3
            self._data.setdefault("preferences", {})[key] = value
            self._save()

    def get_preferences(self) -> Dict[str, Any]:
        with self._lock:  # E1: copy under lock
            self._reload_if_changed()
            return dict(self._data.get("preferences", {}))

    # ── Interests ────────────────────────────────────────────

    def get_interests(self) -> List[str]:
        with self._lock:  # E1: copy under lock
            self._reload_if_changed()
            return list(self._data.get("interests", []))

    def add_interest(self, interest: str) -> bool:
        """Add interest if not duplicate. Returns True if new."""
        interest = interest.strip().lower()
        if not interest or len(interest) > 100:
            return False
        if not self._privacy.is_allowed(interest):
            return False
        with self._lock:
            self._reload_if_changed()  # E3
            current = self._data.get("interests", [])
            if interest in [i.lower() for i in current]:
                return False
            current.append(interest)
            self._data["interests"] = current[-50:]
            self._save()
            return True

    def remove_interest(self, interest: str) -> bool:
        interest_lower = interest.strip().lower()
        with self._lock:
            self._reload_if_changed()  # E3
            current = self._data.get("interests", [])
            new = [i for i in current if i.lower() != interest_lower]
            if len(new) == len(current):
                return False
            self._data["interests"] = new
            self._save()
            return True

    # ── Day Rhythm ───────────────────────────────────────────

    @property
    def rhythm(self) -> DayRhythm:
        self._reload_if_changed()
        return self._rhythm

    def set_rhythm(self, rhythm: DayRhythm) -> None:
        with self._lock:
            self._reload_if_changed()  # E3
            self._rhythm = rhythm
            self._save()

    def is_likely_active(self) -> bool:
        """Is the operator likely awake/active right now?"""
        hour = datetime.now().hour
        return self._rhythm.typical_wake_hour <= hour < self._rhythm.typical_sleep_hour

    def is_likely_working(self) -> bool:
        """Is the operator likely at work right now?"""
        now = datetime.now()
        if now.weekday() in self._rhythm.weekend_days:
            return False
        if len(self._rhythm.work_hours) >= 2:
            return self._rhythm.work_hours[0] <= now.hour < self._rhythm.work_hours[1]
        return False

    # ── Current Context ──────────────────────────────────────

    def set_context(self, text: str, expires_hours: int = 24) -> None:
        """Set volatile operator context with auto-expiry."""
        with self._lock:
            self._reload_if_changed()  # E3
            now = time.time()
            self._context = CurrentContext(
                text=text.strip()[:300],
                set_at=now,
                expires_at=now + expires_hours * 3600,
            )
            self._save()

    def get_context(self) -> Optional[str]:
        """Get active context, or None if expired/unset."""
        self._reload_if_changed()
        return self._context.get_text()

    def clear_context(self) -> None:
        with self._lock:
            self._reload_if_changed()  # E3
            self._context = CurrentContext()
            self._save()

    # ── Privacy Boundaries ───────────────────────────────────

    @property
    def privacy(self) -> PrivacyGuard:
        return self._privacy

    def add_boundary(self, topic: str) -> bool:
        result = self._privacy.add_boundary(topic)
        if result:
            with self._lock:
                self._save()
        return result

    def remove_boundary(self, topic: str) -> bool:
        result = self._privacy.remove_boundary(topic)
        if result:
            with self._lock:
                self._save()
        return result

    def get_boundaries(self) -> List[str]:
        return self._privacy.get_boundaries()

    # ── Stats ────────────────────────────────────────────────

    def record_interaction(self, channel: str = "") -> None:
        with self._lock:
            self._reload_if_changed()  # E3
            self._data["stats"]["last_seen"] = datetime.now().isoformat()
            self._data["stats"]["total_messages"] = (
                self._data["stats"].get("total_messages", 0) + 1
            )
            self._save()

    def record_session(self) -> None:
        with self._lock:
            self._reload_if_changed()  # E3
            self._data["stats"]["sessions_count"] = (
                self._data["stats"].get("sessions_count", 0) + 1
            )
            self._save()

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:  # E1: copy under lock
            self._reload_if_changed()
            return dict(self._data.get("stats", {}))

    # ── Fact Extraction from Messages ────────────────────────

    def learn_from_message(self, message: str) -> int:
        """
        Extract operator facts from a single message.

        Respects privacy boundaries. Returns number of new facts added.
        """
        if not message or len(message) < 5:
            return 0

        added = 0
        msg_lower = message.lower().strip()
        now_iso = datetime.now().isoformat()
        source = "inferred:message"

        # Name
        for pattern in [
            r"mam na imi[eę] (\w+)",
            r"jestem (\w+)",
            r"nazywam si[eę] (\w+)",
        ]:
            m = re.search(pattern, msg_lower)
            if m:
                name = m.group(1).capitalize()
                skip = {"maria", "tu", "tutaj", "tak", "nie", "ok", "dobrze"}
                if len(name) >= 2 and name.lower() not in skip:
                    self.set_fact("name", name, 1.0, source)
                    added += 1
                    break

        # Age
        m = re.search(r"mam\s+(\d{1,3})\s*lat", msg_lower)
        if m:
            age = m.group(1)
            if 1 <= int(age) <= 150:
                self.set_fact("age", age, 1.0, source)
                added += 1

        # Job
        m = re.search(
            r"pracuj[eę]\s+(?:obecnie\s+)?jako\s+(.+?)(?:\s+w\s+|\s*[,.]|$)",
            msg_lower,
        )
        if m:
            job = m.group(1).strip()
            if len(job) >= 2:
                self.set_fact("job", job, 1.0, source)
                added += 1

        # Job location: "pracuje w X", "w Niemczech"
        m = re.search(
            r"(?:pracuj[eę]|jestem)\s+(?:.*?\s+)?w\s+(\w+(?:ch|ce|ii|ie|ach))\b",
            msg_lower,
        )
        if m:
            loc = m.group(1).strip().capitalize()
            if len(loc) >= 3:
                self.set_fact("job_location", loc, 0.8, source)
                added += 1

        # City
        m = re.search(r"mieszkam\s+w\s+(\w+)", msg_lower)
        if m:
            city = m.group(1).strip().capitalize()
            if len(city) >= 2:
                self.set_fact("city", city, 1.0, source)
                added += 1

        # Interests
        for pattern in [
            r"interesuj[eę] (?:si[eę] |mnie )(.+?)(?:\.|,|$)",
            r"lubi[eę] (.+?)(?:\.|,|$)",
            r"pasjonuj[eę] (?:si[eę] |mnie )(.+?)(?:\.|,|$)",
            r"(?:moje )?hobby to (.+?)(?:\.|,|$)",
        ]:
            m = re.search(pattern, msg_lower)
            if m:
                interest = m.group(1).strip()[:80]
                if len(interest) >= 2 and self.add_interest(interest):
                    added += 1

        # Schedule
        for pattern in [
            r"pracuj[eę] (?:od )?(\d{1,2})\s*[-do]+\s*(\d{1,2})",
            r"godziny pracy(?::| to)\s*(\d{1,2})\s*[-do]+\s*(\d{1,2})",
        ]:
            m = re.search(pattern, msg_lower)
            if m:
                start_h, end_h = int(m.group(1)), int(m.group(2))
                if 0 <= start_h <= 23 and 0 <= end_h <= 23:
                    self.set_fact(
                        "work_schedule",
                        f"{start_h}-{end_h}",
                        1.0,
                        source,
                    )
                    with self._lock:
                        self._rhythm.work_hours = [start_h, end_h]
                        self._rhythm.confidence = max(self._rhythm.confidence, 0.6)
                        self._save()
                    added += 1

        # Birthday
        m = re.search(
            r"(?:moje )?urodziny (?:sa |to |mam )(.+?)(?:\.|$)", msg_lower
        )
        if m:
            birthday = m.group(1).strip()[:30]
            if self._privacy.is_allowed("urodziny"):
                self.set_fact("birthday", birthday, 1.0, source)
                added += 1

        return added

    # ── Context for LLM Prompt ───────────────────────────────

    def get_context_for_prompt(self) -> str:
        """
        Build compact user context for LLM system prompt.

        Auto-reloads from disk if modified by another process.
        """
        self._reload_if_changed()
        parts = []

        # Name
        name = self.get_fact_value("name", "Operator")
        parts.append(f"Operator: {name}")

        # Key facts
        job = self.get_fact_value("job")
        if job:
            loc = self.get_fact_value("job_location")
            parts.append(f"Zawod: {job}" + (f" ({loc})" if loc else ""))

        # Interests
        interests = self.get_interests()
        if interests:
            parts.append(f"Zainteresowania: {', '.join(interests[:8])}")

        # Current context
        ctx = self.get_context()
        if ctx:
            parts.append(f"Aktualny kontekst: {ctx}")

        # Preferences
        style = self.get_preference("response_style", "casual")
        parts.append(f"Styl: {style}")

        return "[Profil operatora] " + ". ".join(parts) + "."

    # ── Operator Brief (human-readable) ──────────────────────

    def get_operator_brief(self) -> str:
        """
        Human-readable summary of what Maria knows about the operator.
        Used for /profile command and internal diagnostics.
        """
        self._reload_if_changed()
        lines = []

        # Durable facts
        facts = self.get_all_facts()
        name = facts.get("name")
        lines.append(f"Operator: {name.value if name else 'nieznany'}")

        for key, fact in sorted(facts.items()):
            if key == "name":
                continue
            conf_str = f" ({fact.confidence:.0%})" if fact.confidence < 1.0 else ""
            lines.append(f"  {key}: {fact.value}{conf_str}")

        # Interests
        interests = self.get_interests()
        if interests:
            lines.append(f"Zainteresowania: {', '.join(interests)}")

        # Rhythm
        r = self._rhythm
        if r.confidence > 0:
            lines.append(
                f"Rytm dnia: wstaje ~{r.typical_wake_hour}:00, "
                f"praca {r.work_hours[0]}-{r.work_hours[1]}, "
                f"spi od ~{r.typical_sleep_hour}:00 "
                f"(confidence: {r.confidence:.0%}, samples: {r.sample_count})"
            )
        else:
            lines.append("Rytm dnia: brak danych (uzywam domyslnych)")

        # Context
        ctx = self.get_context()
        if ctx:
            lines.append(f"Kontekst: {ctx}")

        # Privacy
        boundaries = self.get_boundaries()
        if boundaries:
            lines.append(f"Granice prywatnosci: {', '.join(boundaries)}")

        # Stats
        stats = self.get_stats()
        lines.append(
            f"Wiadomosci: {stats.get('total_messages', 0)}, "
            f"ostatnio: {stats.get('last_seen', '?')[:10]}"
        )

        return "\n".join(lines)

    # ── Full Data (for API) ──────────────────────────────────

    def get_full_data(self) -> Dict[str, Any]:
        """Return complete model data for API endpoints."""
        with self._lock:  # E1: reload + serialize atomically (was reload outside lock)
            self._reload_if_changed()
            return json.loads(json.dumps(self._data))

    # ── Convenience: name shortcut ───────────────────────────

    def get_name(self) -> str:
        return self.get_fact_value("name", "Operator")

    def set_name(self, name: str) -> None:
        self.set_fact("name", name.strip()[:50], 1.0, "explicit")

    # ── Backward compat with UserProfile API ─────────────────

    def add_fact(self, fact: str) -> bool:
        """Legacy: add free-form fact. Tries structured extraction first."""
        if not fact or len(fact) > 300:
            return False
        if not self._privacy.is_allowed(fact):
            return False
        # Try to parse into structured facts
        now = datetime.now().isoformat()
        before = dict(self._data.get("durable_facts", {}))
        self._parse_fact_into(
            self._data.get("durable_facts", {}), fact, now
        )
        if self._data.get("durable_facts", {}) != before:
            with self._lock:
                self._save()
            return True
        # Fallback: store as freeform fact
        key = f"fact_{int(time.time())}"
        self.set_fact(key, fact, 0.6, "freeform")
        return True

    def get_facts(self) -> List[str]:
        """Legacy: return facts as flat string list."""
        result = []
        for key, fact in self.get_all_facts().items():
            if key == "name":
                continue
            if isinstance(fact, OperatorFact):
                result.append(f"{key}: {fact.value}")
        return result

    def add_schedule_note(self, note: str) -> None:
        """Add a schedule/routine note. Notes accumulate as a capped list
        (max 30, dedup by exact match).

        E2: previously every note overwrote the single durable fact
        'schedule_note', silently discarding all prior notes -- a regression
        versus legacy UserProfile introduced when the Web UI was rewired onto
        OperatorModel (b890e7b). Now mirrors the legacy list semantics.
        """
        note = (note or "").strip()
        if not note or len(note) > 200:
            return
        if not self._privacy.is_allowed(note):
            return
        with self._lock:
            self._reload_if_changed()  # E3
            notes = self._data.setdefault("schedule_notes", [])
            if note in notes:
                return
            notes.append(note)
            self._data["schedule_notes"] = notes[-30:]
            self._save()

    def get_schedule_notes(self) -> List[str]:
        """Return the operator's schedule notes (oldest first, newest last)."""
        with self._lock:
            self._reload_if_changed()
            return list(self._data.get("schedule_notes", []))

    def remove_schedule_note(self, note: str) -> bool:
        """Remove a schedule note. Returns True if it was present."""
        note = (note or "").strip()
        with self._lock:
            self._reload_if_changed()  # E3
            notes = self._data.get("schedule_notes", [])
            new = [n for n in notes if n != note]
            if len(new) == len(notes):
                return False
            self._data["schedule_notes"] = new
            self._save()
            return True

    def get_summary(self) -> str:
        """Alias for get_operator_brief (backward compat)."""
        return self.get_operator_brief()

    def get_full_profile(self) -> Dict[str, Any]:
        """Alias for get_full_data (backward compat)."""
        return self.get_full_data()

    def get_profile_card(self) -> Dict[str, Any]:
        """Return the operator profile in the flat shape the Web UI profile
        page (profile.js) expects: identity / preferences / interests /
        schedule / facts / stats.

        OperatorModel's own structure is richer (durable_facts / day_rhythm /
        current_context / ...); this maps it to the legacy UserProfile "card"
        so the front-end stays byte-for-byte unchanged while the Web UI reads
        from the one shared OperatorModel instead of a separate
        user_profile.json (Plank 3, split-brain #5). The front-end degrades
        gracefully on any missing leaf (|| '?' / || 0), so partial preferences
        or stats never break the page.
        """
        self._reload_if_changed()
        return {
            "identity": {
                "name": self.get_name(),
                "language": self.get_language(),
                "timezone": self.get_fact_value("timezone", "Europe/Warsaw"),
            },
            "preferences": self.get_preferences(),
            "interests": self.get_interests(),
            "schedule": {"notes": self.get_schedule_notes()},
            "facts": self.get_facts(),
            "stats": self.get_stats(),
        }

    def get_language(self) -> str:
        return self.get_fact_value("language", "pl")

    def record_channel_use(self, channel: str) -> None:
        """Legacy no-op (channels tracked via stats)."""
        pass

    def get_active_channels(self) -> List[str]:
        """Legacy: return active channels."""
        return ["telegram", "web_ui"]

    def learn_from_user_facts(self, user_facts: List[str]) -> int:
        """Legacy: ingest facts from ConversationMemory condensation."""
        added = 0
        for raw in user_facts:
            raw = raw.strip()
            if not raw:
                continue
            if self.add_fact(raw):
                added += 1
        return added


# ── Process-wide singleton ───────────────────────────────────────────────
# One in-memory OperatorModel shared by the daemon and the Web UI (same
# process under maria.py UnifiedLauncher). Previously the daemon held its own
# OperatorModel while the UI lazy-init'd a separate UserProfile, so facts
# learned in one channel never reached the other (split-brain, audit v2 #3).
# Sharing a single instance makes OperatorModel the one source of truth for
# operator identity across Telegram, Web UI chat, and autonomy.
#
# In split modes (`maria.py --daemon` / `--ui` = two processes) each process
# gets its own singleton; cross-process consistency falls back to the file +
# _reload_if_changed(), the pre-existing behaviour.
_SINGLETON: Optional["OperatorModel"] = None
_SINGLETON_LOCK = threading.Lock()


def get_operator_model(path: Optional[Path] = None) -> "OperatorModel":
    """Return the process-wide shared OperatorModel, creating it on first call.

    Both the homeostasis daemon and the Web UI must go through this accessor so
    they mutate the same in-memory instance (single source of truth). The
    optional ``path`` only applies when the singleton is first created.
    """
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = OperatorModel(path=path)
    return _SINGLETON


def reset_operator_model_singleton() -> None:
    """Reset the shared singleton (tests only)."""
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = None


# ── Quiet hours (operator's sleep) ────────────────────────────
#
# SSoT for "the operator is asleep, do not make noise". Lives here because
# quiet_hours is an operator PREFERENCE, and OperatorModel owns those.
#
# Before 2026-07-15 every caller rolled its own: mode_detector.py:129 read
# prefs["quiet_hours_start"]/["quiet_hours_end"] -- fields nobody writes (the
# preference is stored as the list quiet_hours=[23, 6]), so get() returned None,
# the guard `if quiet_start is not None` was never true and operator quiet hours
# NEVER APPLIED. Meanwhile proactive/scheduler.py hardcoded 23-6 and
# planner/time_context.py hardcoded 22-7 -- three definitions, one dead.
# Read the window through these helpers; do not re-parse the preference.


def quiet_hours_window(prefs: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """Operator's quiet window as (start_hour, end_hour), or None if unusable.

    Accepts the stored shape: ``{"quiet_hours": [23, 6]}``.
    """
    raw = prefs.get("quiet_hours") if isinstance(prefs, dict) else None
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return None
    try:
        start, end = int(raw[0]), int(raw[1])
    except (TypeError, ValueError):
        return None
    if not (0 <= start <= 23 and 0 <= end <= 23):
        return None
    return start, end


def in_quiet_hours(hour: int, window: Optional[Tuple[int, int]]) -> bool:
    """Is ``hour`` inside the quiet window? Handles wrap past midnight.

    start == end means a zero-length window (never quiet), NOT all-day quiet --
    an operator who wants silence forever would say so another way, and
    accidentally muting the agent forever is the worse failure.
    """
    if window is None:
        return False
    start, end = window
    if start == end:
        return False
    if start < end:
        return start <= hour < end      # same day, e.g. 1-5
    return hour >= start or hour < end  # wraps midnight, e.g. 23-6
