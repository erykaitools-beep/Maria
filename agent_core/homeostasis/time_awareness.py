"""
Time Awareness - Human-friendly time perception for Maria.

Provides natural language descriptions of time context:
- Time of day (rano, poludnie, wieczor, noc)
- Session duration (rozmawiamy 2 godziny)
- Idle time (nie pisales 3 godziny)
- Day context (weekend, poniedzialek rano)

Usage:
    from agent_core.homeostasis.time_awareness import TimeAwareness

    ctx = TimeAwareness.get_context()
    # -> "Jest 23:15, pozna noc. Rozmawiamy juz 2h 15min."
"""

from datetime import datetime
from typing import Optional


class TimeAwareness:
    """Human-friendly time perception."""

    # Time of day descriptions (Polish)
    TIME_OF_DAY = {
        (5, 9): "wczesny ranek",
        (9, 12): "przedpoludnie",
        (12, 14): "poludnie",
        (14, 17): "popoludnie",
        (17, 20): "wieczor",
        (20, 23): "pozny wieczor",
        (23, 24): "noc",
        (0, 5): "srodek nocy",
    }

    DAY_NAMES = {
        0: "poniedzialek",
        1: "wtorek",
        2: "sroda",
        3: "czwartek",
        4: "piatek",
        5: "sobota",
        6: "niedziela",
    }

    @classmethod
    def get_time_of_day(cls) -> str:
        """Get human description of current time of day."""
        hour = datetime.now().hour
        for (start, end), desc in cls.TIME_OF_DAY.items():
            if start <= hour < end:
                return desc
        return "noc"

    @classmethod
    def get_greeting(cls) -> str:
        """Get appropriate greeting for time of day."""
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return "Dzien dobry"
        elif 12 <= hour < 18:
            return "Czesc"
        elif 18 <= hour < 22:
            return "Dobry wieczor"
        else:
            return "Hej"

    @classmethod
    def format_duration(cls, seconds: float) -> str:
        """Format duration in human-readable Polish."""
        if seconds < 60:
            return f"{int(seconds)} sek"
        elif seconds < 3600:
            mins = int(seconds / 60)
            return f"{mins} min"
        else:
            hours = int(seconds / 3600)
            mins = int((seconds % 3600) / 60)
            if mins > 0:
                return f"{hours}h {mins}min"
            return f"{hours}h"

    @classmethod
    def format_time(cls) -> str:
        """Get current time as HH:MM."""
        return datetime.now().strftime("%H:%M")

    @classmethod
    def is_late_night(cls) -> bool:
        """Check if it's late (after 23:00 or before 6:00)."""
        hour = datetime.now().hour
        return hour >= 23 or hour < 6

    @classmethod
    def is_weekend(cls) -> bool:
        """Check if today is weekend."""
        return datetime.now().weekday() >= 5

    @classmethod
    def get_day_context(cls) -> str:
        """Get day context (e.g., 'sobota rano', 'poniedzialek wieczor')."""
        day = cls.DAY_NAMES[datetime.now().weekday()]
        time_of_day = cls.get_time_of_day()
        return f"{day}, {time_of_day}"

    @classmethod
    def get_context(
        cls,
        session_seconds: Optional[float] = None,
        idle_seconds: Optional[float] = None,
    ) -> str:
        """
        Get full time context string for Maria's perception.

        Args:
            session_seconds: How long session has been running
            idle_seconds: How long since last user interaction

        Returns:
            Human-readable context string in Polish
        """
        parts = []

        # Current time
        time_str = cls.format_time()
        time_of_day = cls.get_time_of_day()
        parts.append(f"Jest {time_str}, {time_of_day}")

        # Late night warning
        if cls.is_late_night():
            parts.append("(pozna pora)")

        # Weekend context
        if cls.is_weekend():
            parts.append("(weekend)")

        # Session duration
        if session_seconds is not None and session_seconds > 60:
            duration = cls.format_duration(session_seconds)
            parts.append(f"Rozmawiamy juz {duration}")

        # Idle time (if significant)
        if idle_seconds is not None and idle_seconds > 300:  # > 5 min
            idle_str = cls.format_duration(idle_seconds)
            parts.append(f"Nie pisales {idle_str}")

        return ". ".join(parts) + "."

    @classmethod
    def get_sleep_suggestion(cls, idle_seconds: float) -> Optional[str]:
        """
        Get suggestion about sleep if user has been idle long.

        Returns suggestion string or None if not applicable.
        """
        hour = datetime.now().hour

        # Late night + long idle = suggest sleep
        if cls.is_late_night() and idle_seconds > 1800:  # 30 min
            return "Jest pozno i dawno nie pisales. Moze pora spac?"

        # Very long session
        if idle_seconds > 7200:  # 2 hours
            return f"Nie pisales {cls.format_duration(idle_seconds)}. Wszystko ok?"

        return None

    @classmethod
    def get_wakeup_greeting(cls, sleep_seconds: float) -> str:
        """
        Get greeting when user returns after being idle.

        Args:
            sleep_seconds: How long user was away
        """
        greeting = cls.get_greeting()
        duration = cls.format_duration(sleep_seconds)
        time_of_day = cls.get_time_of_day()

        if sleep_seconds > 28800:  # > 8 hours
            return f"{greeting}! Spales dlugo - {duration}. Teraz jest {time_of_day}."
        elif sleep_seconds > 3600:  # > 1 hour
            return f"{greeting}! Nie bylo Cie {duration}."
        else:
            return f"Wracasz! ({duration} przerwy)"
