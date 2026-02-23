"""
IdentityStore - Persistent identity tracking across restarts.

Maria's sense of self persists in meta_data/consciousness_identity.json.
Tracks: birth date, session count, total uptime, last session summary.
"""

import json
import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional


# Maria's birth - the day the project started
MARIA_BIRTH_TIMESTAMP = "2025-11-14T00:00:00"
MARIA_BIRTH_DATE = "2025-11-14"

# Default primary user
DEFAULT_PRIMARY_USER = "Eryk"


class IdentityStore:
    """
    Persistent identity for Maria across restarts.

    Stores identity in JSON file. Each start_session() increments
    the session counter. end_session() updates total uptime.

    Usage:
        store = IdentityStore()
        store.start_session()
        # ... Maria works ...
        store.end_session(summary="Learned about NIM API")
    """

    DEFAULT_FILE = "consciousness_identity.json"

    def __init__(self, data_dir: str = "meta_data"):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._file_path = self._data_dir / self.DEFAULT_FILE
        self._lock = threading.Lock()

        self._data = self._load_or_create()
        self._session_start_time = time.time()

    def _load_or_create(self) -> Dict[str, Any]:
        """Load existing identity or create new one."""
        if self._file_path.exists():
            try:
                with open(self._file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Ensure all required fields exist
                return self._ensure_fields(data)
            except (json.JSONDecodeError, IOError) as e:
                print(f"[Identity] [WARN] Could not load identity: {e}")

        # First run - create identity
        return self._create_initial_identity()

    def _create_initial_identity(self) -> Dict[str, Any]:
        """Create identity for the first time."""
        data = {
            "birth_timestamp": MARIA_BIRTH_TIMESTAMP,
            "birth_date": MARIA_BIRTH_DATE,
            "name": "Maria",
            "full_name": "M.A.R.I.A.",
            "full_name_expanded": "Meta Analysis Recalibration Intelligence Architecture",
            "total_uptime_seconds": 0,
            "session_count": 0,
            "current_session_start": None,
            "restart_count": 0,
            "primary_user": DEFAULT_PRIMARY_USER,
            "last_session_summary": "",
            "last_shutdown_timestamp": None,
        }
        self._save(data)
        return data

    def _ensure_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure all required fields exist in loaded data."""
        defaults = {
            "birth_timestamp": MARIA_BIRTH_TIMESTAMP,
            "birth_date": MARIA_BIRTH_DATE,
            "name": "Maria",
            "full_name": "M.A.R.I.A.",
            "full_name_expanded": "Meta Analysis Recalibration Intelligence Architecture",
            "total_uptime_seconds": 0,
            "session_count": 0,
            "current_session_start": None,
            "restart_count": 0,
            "primary_user": DEFAULT_PRIMARY_USER,
            "last_session_summary": "",
            "last_shutdown_timestamp": None,
        }
        for key, default in defaults.items():
            if key not in data:
                data[key] = default
        return data

    def _save(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Save identity to disk."""
        if data is None:
            data = self._data
        try:
            with open(self._file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(f"[Identity] [ERROR] Could not save identity: {e}")

    # -------------------------------------------------
    # SESSION LIFECYCLE
    # -------------------------------------------------

    def start_session(self) -> None:
        """Call at startup. Increments session count."""
        with self._lock:
            self._data["session_count"] += 1
            self._data["restart_count"] = max(
                0, self._data["session_count"] - 1
            )
            self._data["current_session_start"] = datetime.now().isoformat()
            self._session_start_time = time.time()
            self._save()

    def end_session(self, summary: str = "") -> None:
        """Call at shutdown. Updates uptime and summary."""
        with self._lock:
            # Calculate session duration
            session_duration = time.time() - self._session_start_time
            self._data["total_uptime_seconds"] += session_duration
            self._data["last_shutdown_timestamp"] = datetime.now().isoformat()
            if summary:
                self._data["last_session_summary"] = summary
            self._save()

    # -------------------------------------------------
    # IDENTITY QUERIES
    # -------------------------------------------------

    def get_identity_context(self) -> str:
        """
        Human-readable identity context for system prompt.

        Returns:
            "Jestem Maria (M.A.R.I.A.). Sesja 25. Uptime: 15.8h. Urodziny: 2025-11-14."
        """
        with self._lock:
            d = self._data
            uptime_h = d["total_uptime_seconds"] / 3600
            session_uptime = (time.time() - self._session_start_time) / 3600

            parts = [
                f"Jestem {d['name']} ({d['full_name']})",
                f"Sesja nr {d['session_count']}",
                f"Calkowity uptime: {uptime_h + session_uptime:.1f}h",
                f"Urodziny: {d['birth_date']}",
            ]

            if d.get("primary_user"):
                parts.append(f"Moj operator: {d['primary_user']}")

            if d.get("last_session_summary"):
                parts.append(
                    f"Ostatnia sesja: {d['last_session_summary']}"
                )

            return ". ".join(parts) + "."

    def get_identity_dict(self) -> Dict[str, Any]:
        """
        Raw identity data for API and status display.

        Returns:
            Full identity dictionary with computed fields.
        """
        with self._lock:
            d = dict(self._data)
            # Add computed fields
            session_duration = time.time() - self._session_start_time
            d["current_session_uptime_seconds"] = session_duration
            d["current_session_uptime_hours"] = session_duration / 3600
            d["total_uptime_hours"] = (
                d["total_uptime_seconds"] + session_duration
            ) / 3600
            return d

    def get_session_count(self) -> int:
        """Get current session number."""
        return self._data.get("session_count", 0)

    def get_total_uptime_hours(self) -> float:
        """Get total uptime in hours (including current session)."""
        session_duration = time.time() - self._session_start_time
        return (self._data["total_uptime_seconds"] + session_duration) / 3600

    def get_birth_date(self) -> str:
        """Get birth date string."""
        return self._data.get("birth_date", MARIA_BIRTH_DATE)

    def get_name(self) -> str:
        """Get Maria's name."""
        return self._data.get("name", "Maria")

    def get_primary_user(self) -> str:
        """Get primary user name."""
        return self._data.get("primary_user", DEFAULT_PRIMARY_USER)

    def get_last_session_summary(self) -> str:
        """Get summary of last session."""
        return self._data.get("last_session_summary", "")
