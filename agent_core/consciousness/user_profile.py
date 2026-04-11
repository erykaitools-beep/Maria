"""
UserProfile - Persistent knowledge about the operator/user.

Maria learns about her user from conversations, commands, and explicit
statements. This module consolidates all user knowledge into a single
structured profile that grows over time.

Persistence: meta_data/user_profile.json (single file, atomic writes)

Integration:
- ConversationMemory.user_facts -> auto-extracted into profile
- OllamaBrain system prompt -> user context injection
- Telegram/Web UI -> channel tracking
- Planner -> user-aware decisions
"""

import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_PATH = Path("meta_data/user_profile.json")


class UserProfile:
    """
    Structured, persistent knowledge about the operator.

    Categories of knowledge:
    - identity: name, language, timezone
    - preferences: communication style, autonomy level, topics of interest
    - schedule: routines, work hours, recurring patterns
    - facts: free-form facts learned from conversations
    - channels: which communication channels the user uses
    - stats: interaction statistics

    Thread-safe. All mutations auto-save to disk.
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path or DEFAULT_PROFILE_PATH)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data = self._load_or_create()
        self._last_mtime = self._get_mtime()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_or_create(self) -> Dict[str, Any]:
        """Load existing profile or create default.

        Never overwrites existing data - if file exists and has content,
        always load it (even if schema is outdated, _ensure_schema fixes that).
        """
        if self._path.exists() and self._path.stat().st_size > 2:
            # Retry up to 2 times (file might be mid-write by another process)
            for attempt in range(2):
                try:
                    with open(self._path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    logger.info("[UserProfile] Loaded from %s", self._path)
                    return self._ensure_schema(data)
                except (json.JSONDecodeError, IOError) as e:
                    if attempt == 0:
                        time.sleep(0.1)  # brief wait, maybe mid-write
                    else:
                        logger.warning("[UserProfile] Load failed after retry: %s", e)

        return self._create_default()

    def _create_default(self) -> Dict[str, Any]:
        """Default profile for first run. Only writes if file doesn't exist."""
        data = {
            "version": 1,
            "identity": {
                "name": os.environ.get("MARIA_OPERATOR_NAME", "Operator"),
                "language": "pl",
                "timezone": "Europe/Warsaw",
            },
            "preferences": {
                "response_style": "casual",
                "autonomy_level": "medium",
                "notify_channel": "telegram",
            },
            "interests": [],
            "schedule": {
                "notes": [],
            },
            "facts": [],
            "channels": {
                "telegram": True,
                "web_ui": True,
                "repl": False,
            },
            "stats": {
                "first_seen": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "total_messages": 0,
                "sessions_count": 0,
            },
            "updated_at": datetime.now().isoformat(),
        }
        # Only write default if file truly doesn't exist (avoid race with other process)
        if not self._path.exists():
            self._save(data)
        return data

    def _ensure_schema(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure all required fields exist after load."""
        defaults = self._create_default()
        for section in ("identity", "preferences", "schedule", "stats", "channels"):
            if section not in data:
                data[section] = defaults[section]
            elif isinstance(data[section], dict) and isinstance(defaults[section], dict):
                for k, v in defaults[section].items():
                    if k not in data[section]:
                        data[section][k] = v
        if "interests" not in data:
            data["interests"] = []
        if "facts" not in data:
            data["facts"] = []
        if "version" not in data:
            data["version"] = 1
        return data

    def _get_mtime(self) -> float:
        """Get file modification time."""
        try:
            return self._path.stat().st_mtime if self._path.exists() else 0.0
        except OSError:
            return 0.0

    def _reload_if_changed(self) -> None:
        """Reload from disk if file was modified by another process."""
        current_mtime = self._get_mtime()
        if current_mtime > self._last_mtime:
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._data = self._ensure_schema(data)
                self._last_mtime = current_mtime
            except (json.JSONDecodeError, IOError):
                pass

    def _save(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Atomic save to disk."""
        if data is None:
            data = self._data
        data["updated_at"] = datetime.now().isoformat()
        try:
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp.replace(self._path)
            self._last_mtime = self._get_mtime()
        except IOError as e:
            logger.warning("[UserProfile] Save failed: %s", e)

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    def get_name(self) -> str:
        return self._data.get("identity", {}).get("name", "operator")

    def set_name(self, name: str) -> None:
        with self._lock:
            self._data["identity"]["name"] = name.strip()[:50]
            self._save()

    def get_language(self) -> str:
        return self._data.get("identity", {}).get("language", "pl")

    def get_timezone(self) -> str:
        return self._data.get("identity", {}).get("timezone", "Europe/Warsaw")

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    def get_preference(self, key: str, default: Any = None) -> Any:
        return self._data.get("preferences", {}).get(key, default)

    def set_preference(self, key: str, value: Any) -> None:
        with self._lock:
            self._data["preferences"][key] = value
            self._save()

    def get_preferences(self) -> Dict[str, Any]:
        return dict(self._data.get("preferences", {}))

    # ------------------------------------------------------------------
    # Interests
    # ------------------------------------------------------------------

    def get_interests(self) -> List[str]:
        return list(self._data.get("interests", []))

    def add_interest(self, interest: str) -> bool:
        """Add interest if not already tracked. Returns True if new."""
        interest = interest.strip().lower()
        if not interest or len(interest) > 100:
            return False
        with self._lock:
            current = self._data.get("interests", [])
            existing = {i.lower() for i in current}
            if interest in existing:
                return False
            current.append(interest)
            # Cap at 50 interests
            self._data["interests"] = current[-50:]
            self._save()
            return True

    def remove_interest(self, interest: str) -> bool:
        """Remove interest. Returns True if found and removed."""
        interest_lower = interest.strip().lower()
        with self._lock:
            current = self._data.get("interests", [])
            new = [i for i in current if i.lower() != interest_lower]
            if len(new) == len(current):
                return False
            self._data["interests"] = new
            self._save()
            return True

    # ------------------------------------------------------------------
    # Schedule / routines
    # ------------------------------------------------------------------

    def add_schedule_note(self, note: str) -> None:
        """Add a schedule/routine note (e.g. 'pracuje 9-17', 'piatek wolny')."""
        note = note.strip()
        if not note or len(note) > 200:
            return
        with self._lock:
            notes = self._data["schedule"].get("notes", [])
            # Dedup by exact match
            if note not in notes:
                notes.append(note)
                # Cap at 30
                self._data["schedule"]["notes"] = notes[-30:]
                self._save()

    def get_schedule_notes(self) -> List[str]:
        return list(self._data.get("schedule", {}).get("notes", []))

    def remove_schedule_note(self, note: str) -> bool:
        """Remove a schedule note. Returns True if removed."""
        with self._lock:
            notes = self._data["schedule"].get("notes", [])
            new = [n for n in notes if n != note]
            if len(new) == len(notes):
                return False
            self._data["schedule"]["notes"] = new
            self._save()
            return True

    # ------------------------------------------------------------------
    # Facts (free-form knowledge about the user)
    # ------------------------------------------------------------------

    def get_facts(self) -> List[str]:
        return list(self._data.get("facts", []))

    def add_fact(self, fact: str) -> bool:
        """Add a fact about the user. Deduplicates. Returns True if new."""
        fact = fact.strip()
        if not fact or len(fact) > 300:
            return False
        with self._lock:
            current = self._data.get("facts", [])
            existing_lower = {f.lower() for f in current}
            if fact.lower() in existing_lower:
                return False
            current.append(fact)
            # Cap at 100 facts
            self._data["facts"] = current[-100:]
            self._save()
            return True

    def remove_fact(self, fact: str) -> bool:
        """Remove a fact. Returns True if found."""
        fact_lower = fact.strip().lower()
        with self._lock:
            current = self._data.get("facts", [])
            new = [f for f in current if f.lower() != fact_lower]
            if len(new) == len(current):
                return False
            self._data["facts"] = new
            self._save()
            return True

    # ------------------------------------------------------------------
    # Channels
    # ------------------------------------------------------------------

    def record_channel_use(self, channel: str) -> None:
        """Mark that user interacted via this channel."""
        if channel not in ("telegram", "web_ui", "repl"):
            return
        with self._lock:
            self._data["channels"][channel] = True
            self._save()

    def get_active_channels(self) -> List[str]:
        return [ch for ch, active in self._data.get("channels", {}).items() if active]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def record_interaction(self, channel: str = "") -> None:
        """Record a user interaction (message, command, etc.)."""
        with self._lock:
            self._data["stats"]["last_seen"] = datetime.now().isoformat()
            self._data["stats"]["total_messages"] = (
                self._data["stats"].get("total_messages", 0) + 1
            )
            if channel:
                self.record_channel_use(channel)
            self._save()

    def record_session(self) -> None:
        """Record a new session start."""
        with self._lock:
            self._data["stats"]["sessions_count"] = (
                self._data["stats"].get("sessions_count", 0) + 1
            )
            self._save()

    def get_stats(self) -> Dict[str, Any]:
        return dict(self._data.get("stats", {}))

    # ------------------------------------------------------------------
    # Fact extraction from conversation (auto-learn)
    # ------------------------------------------------------------------

    def learn_from_user_facts(self, user_facts: List[str]) -> int:
        """
        Ingest user_facts from ConversationMemory condensation.

        Parses structured facts like "operator: Name" and free-form ones.
        Returns number of new facts added.

        Args:
            user_facts: List of fact strings from session summary
        """
        added = 0
        for raw in user_facts:
            raw = raw.strip()
            if not raw:
                continue

            # Parse "key: value" style facts
            parsed = self._parse_structured_fact(raw)
            if parsed:
                continue  # Already handled by _parse_structured_fact

            # Free-form fact
            if self.add_fact(raw):
                added += 1

        return added

    def learn_from_message(self, message: str) -> int:
        """
        Extract user facts from a single message.

        Looks for explicit statements about the user:
        - "mam na imie X" / "jestem X"
        - "interesuje mnie X" / "lubie X"
        - "pracuje od X do Y" / "pracuje jako X"
        - "moje urodziny to X"
        - "mieszkam w X"

        Returns number of new facts added.
        """
        if not message or len(message) < 5:
            return 0

        added = 0
        msg_lower = message.lower().strip()

        # Name patterns
        for pattern in [
            r"mam na imi[eę] (\w+)",
            r"jestem (\w+)",
            r"nazywam si[eę] (\w+)",
        ]:
            m = re.search(pattern, msg_lower)
            if m:
                name = m.group(1).capitalize()
                if len(name) >= 2 and name.lower() not in ("maria", "tu", "tutaj"):
                    self.set_name(name)

        # Interest patterns
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

        # Work/schedule patterns
        for pattern in [
            r"pracuj[eę] (?:od )?(.+?)(?:\.|$)",
            r"(?:moje )?godziny pracy(?::| to) (.+?)(?:\.|$)",
        ]:
            m = re.search(pattern, msg_lower)
            if m:
                note = m.group(1).strip()[:100]
                if len(note) >= 3:
                    self.add_schedule_note(f"praca: {note}")
                    added += 1

        # Birthday
        m = re.search(r"(?:moje )?urodziny (?:sa |to |mam )(.+?)(?:\.|$)", msg_lower)
        if m:
            birthday = m.group(1).strip()[:30]
            if self.add_fact(f"urodziny: {birthday}"):
                added += 1

        # Location
        m = re.search(r"mieszkam w (.+?)(?:\.|,|$)", msg_lower)
        if m:
            location = m.group(1).strip()[:50]
            if self.add_fact(f"mieszka w: {location}"):
                added += 1

        return added

    def _parse_structured_fact(self, raw: str) -> bool:
        """
        Parse "key: value" structured facts from ConversationMemory.

        Returns True if handled (even if duplicate).
        """
        if ":" not in raw:
            return False

        key, _, value = raw.partition(":")
        key = key.strip().lower()
        value = value.strip()

        if not value:
            return False

        if key in ("operator", "imie", "name", "uzytkownik"):
            self.set_name(value)
            return True

        if key in ("jezyk", "language"):
            with self._lock:
                self._data["identity"]["language"] = value[:5]
                self._save()
            return True

        if key in ("strefa", "timezone"):
            with self._lock:
                self._data["identity"]["timezone"] = value[:30]
                self._save()
            return True

        if key in ("zainteresowanie", "interest", "hobby"):
            self.add_interest(value)
            return True

        # Generic - store as fact
        return False

    # ------------------------------------------------------------------
    # Context for system prompt
    # ------------------------------------------------------------------

    def get_context_for_prompt(self) -> str:
        """
        Build user context string for LLM system prompt.

        Compact format injected into OllamaBrain._build_system_prompt().
        Auto-reloads from disk if modified by another process (e.g. Telegram).
        """
        self._reload_if_changed()
        parts = []
        name = self.get_name()
        parts.append(f"Operator: {name}")

        # Interests
        interests = self.get_interests()
        if interests:
            parts.append(f"Zainteresowania: {', '.join(interests[:8])}")

        # Schedule
        notes = self.get_schedule_notes()
        if notes:
            parts.append(f"Harmonogram: {'; '.join(notes[:5])}")

        # Key facts (max 5)
        facts = self.get_facts()
        if facts:
            parts.append(f"Fakty: {'; '.join(facts[:5])}")

        # Preferences
        style = self.get_preference("response_style", "casual")
        parts.append(f"Styl odpowiedzi: {style}")

        return "[Profil uzytkownika] " + ". ".join(parts) + "."

    # ------------------------------------------------------------------
    # Full profile for API / display
    # ------------------------------------------------------------------

    def get_full_profile(self) -> Dict[str, Any]:
        """Return complete profile data for API."""
        self._reload_if_changed()
        with self._lock:
            return json.loads(json.dumps(self._data))

    def get_summary(self) -> str:
        """Human-readable summary of what Maria knows about the user."""
        self._reload_if_changed()
        name = self.get_name()
        interests = self.get_interests()
        facts = self.get_facts()
        notes = self.get_schedule_notes()
        stats = self.get_stats()

        lines = [f"Operator: {name}"]
        if interests:
            lines.append(f"Zainteresowania ({len(interests)}): {', '.join(interests[:10])}")
        if notes:
            lines.append(f"Harmonogram ({len(notes)}):")
            for n in notes[:5]:
                lines.append(f"  - {n}")
        if facts:
            lines.append(f"Fakty ({len(facts)}):")
            for f in facts[:10]:
                lines.append(f"  - {f}")
        lines.append(f"Wiadomosci: {stats.get('total_messages', 0)}, "
                      f"Ostatnio: {stats.get('last_seen', '?')[:10]}")
        return "\n".join(lines)
