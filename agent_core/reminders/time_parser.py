"""
Natural time parser for reminders.

Parses Polish and English time expressions:
  "za 30min", "za 2h", "o 14:30", "jutro 9:00",
  "in 30min", "at 14:30", "tomorrow 9:00"
"""

import re
import time
from datetime import datetime, timedelta
from typing import Optional


def parse_time(text: str) -> Optional[float]:
    """
    Parse natural time expression to Unix timestamp.

    Returns None if cannot parse.

    Examples:
        "za 30min" -> now + 30 minutes
        "za 2h" -> now + 2 hours
        "za 1d" -> now + 1 day
        "o 14:30" / "at 14:30" -> today at 14:30 (or tomorrow if past)
        "jutro 9:00" / "tomorrow 9:00" -> tomorrow at 9:00
        "pojutrze 12:00" -> day after tomorrow at 12:00
    """
    text = text.strip().lower()

    # --- Relative: "za Xmin", "za Xh", "in Xmin", "in Xh" ---
    m = re.match(r"(?:za|in)\s+(\d+)\s*(min|m|h|d|godzin[aey]?|minut[aey]?|dni|day[s]?|hour[s]?)", text)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        if unit in ("min", "m", "minut", "minuta", "minuty", "minute", "minutes"):
            return time.time() + amount * 60
        elif unit in ("h", "godzin", "godzina", "godziny", "hour", "hours"):
            return time.time() + amount * 3600
        elif unit in ("d", "dni", "day", "days"):
            return time.time() + amount * 86400
        return time.time() + amount * 60  # default: minutes

    # --- Absolute: "o HH:MM" / "at HH:MM" ---
    m = re.match(r"(?:o|at)\s+(\d{1,2}):(\d{2})", text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        return _next_time_today_or_tomorrow(hour, minute)

    # --- "jutro HH:MM" / "tomorrow HH:MM" ---
    m = re.match(r"(?:jutro|tomorrow)\s*(\d{1,2}):(\d{2})?", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        tomorrow = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=1)
        return tomorrow.timestamp()

    # --- "pojutrze HH:MM" ---
    m = re.match(r"pojutrze\s*(\d{1,2}):(\d{2})?", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        dt = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=2)
        return dt.timestamp()

    # --- Bare HH:MM ---
    m = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        return _next_time_today_or_tomorrow(hour, minute)

    # --- Bare "Xmin" / "Xh" (without "za/in") ---
    m = re.match(r"^(\d+)\s*(min|m|h|d)$", text)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        if unit in ("min", "m"):
            return time.time() + amount * 60
        elif unit == "h":
            return time.time() + amount * 3600
        elif unit == "d":
            return time.time() + amount * 86400

    return None


def _next_time_today_or_tomorrow(hour: int, minute: int) -> float:
    """Return timestamp for given hour:minute today, or tomorrow if already past."""
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target.timestamp()


def format_scheduled_time(ts: float) -> str:
    """Format timestamp as human-readable relative/absolute time."""
    now = time.time()
    dt = datetime.fromtimestamp(ts)
    today = datetime.now().date()

    if dt.date() == today:
        return f"dzis {dt.strftime('%H:%M')}"
    elif dt.date() == today + timedelta(days=1):
        return f"jutro {dt.strftime('%H:%M')}"
    else:
        return dt.strftime("%d.%m %H:%M")
