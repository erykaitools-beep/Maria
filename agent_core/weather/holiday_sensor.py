"""
HolidaySensor - Polish and German public holidays.

Static data with Easter-dependent date computation.
No API keys, no dependencies beyond stdlib.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HolidayInfo:
    """A single public holiday."""

    name_pl: str
    name_de: Optional[str]
    country: str  # "PL", "DE", "PL+DE"
    holiday_date: date


def _easter_date(year: int) -> date:
    """Compute Easter Sunday using Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _build_holidays(year: int) -> List[HolidayInfo]:
    """Build holiday list for a given year."""
    easter = _easter_date(year)
    holidays = []

    # --- Fixed PL+DE ---
    holidays.append(HolidayInfo("Nowy Rok", "Neujahr", "PL+DE", date(year, 1, 1)))
    holidays.append(HolidayInfo("Swieto Pracy", "Tag der Arbeit", "PL+DE", date(year, 5, 1)))

    # --- Fixed PL only ---
    holidays.append(HolidayInfo("Trzech Kroli", None, "PL", date(year, 1, 6)))
    holidays.append(HolidayInfo("Swieto Konstytucji 3 Maja", None, "PL", date(year, 5, 3)))
    holidays.append(HolidayInfo("Wniebowziecie NMP", None, "PL", date(year, 8, 15)))
    holidays.append(HolidayInfo("Wszystkich Swietych", None, "PL", date(year, 11, 1)))
    holidays.append(HolidayInfo("Swieto Niepodleglosci", None, "PL", date(year, 11, 11)))
    holidays.append(HolidayInfo("Boze Narodzenie", "1. Weihnachtstag", "PL+DE", date(year, 12, 25)))
    holidays.append(HolidayInfo("Drugi dzien Bozego Narodzenia", "2. Weihnachtstag", "PL+DE", date(year, 12, 26)))

    # --- Fixed DE only (national) ---
    holidays.append(HolidayInfo("Dzien Jednosci Niemiec", "Tag der Deutschen Einheit", "DE", date(year, 10, 3)))

    # --- Easter-dependent PL+DE ---
    holidays.append(HolidayInfo("Wielkanoc", "Ostersonntag", "PL+DE", easter))
    holidays.append(HolidayInfo("Poniedzialek Wielkanocny", "Ostermontag", "PL+DE", easter + timedelta(days=1)))

    # --- Easter-dependent PL only ---
    holidays.append(HolidayInfo("Zielone Swiatki", "Pfingstsonntag", "PL+DE", easter + timedelta(days=49)))
    holidays.append(HolidayInfo("Boze Cialo", "Fronleichnam", "PL+DE", easter + timedelta(days=60)))

    # --- Easter-dependent DE only ---
    holidays.append(HolidayInfo("Wielki Piatek", "Karfreitag", "DE", easter - timedelta(days=2)))
    holidays.append(HolidayInfo("Wniebowstapienie", "Christi Himmelfahrt", "DE", easter + timedelta(days=39)))
    holidays.append(HolidayInfo("Poniedzialek Zielonoswiatkowy", "Pfingstmontag", "DE", easter + timedelta(days=50)))

    return sorted(holidays, key=lambda h: h.holiday_date)


class HolidaySensor:
    """Static holiday data for PL and DE."""

    def __init__(self):
        self._cache: Dict[int, List[HolidayInfo]] = {}

    def _get_year(self, year: int) -> List[HolidayInfo]:
        if year not in self._cache:
            self._cache[year] = _build_holidays(year)
        return self._cache[year]

    def get_today(self) -> Optional[HolidayInfo]:
        """Get holiday if today is a public holiday."""
        today = date.today()
        for h in self._get_year(today.year):
            if h.holiday_date == today:
                return h
        return None

    def get_upcoming(self, days: int = 7) -> List[HolidayInfo]:
        """Get holidays in the next N days (excluding today)."""
        today = date.today()
        end = today + timedelta(days=days)
        result = []
        # Check current year and possibly next year
        for year in (today.year, today.year + 1):
            for h in self._get_year(year):
                if today < h.holiday_date <= end:
                    result.append(h)
        return result

    def get_next(self) -> Optional[HolidayInfo]:
        """Get the nearest upcoming holiday."""
        today = date.today()
        for year in (today.year, today.year + 1):
            for h in self._get_year(year):
                if h.holiday_date > today:
                    return h
        return None

    def format_today(self) -> Optional[str]:
        """Format today's holiday for display. Returns None if not a holiday."""
        h = self.get_today()
        if not h:
            return None
        if h.name_de:
            return f"Dzis swieto: {h.name_pl} ({h.name_de})"
        return f"Dzis swieto: {h.name_pl}"

    def format_upcoming(self, days: int = 3) -> Optional[str]:
        """Format nearest upcoming holiday if within N days."""
        upcoming = self.get_upcoming(days)
        if not upcoming:
            return None
        h = upcoming[0]
        delta = (h.holiday_date - date.today()).days
        if delta == 1:
            prefix = "Jutro"
        else:
            prefix = f"Za {delta} dni"
        if h.name_de:
            return f"{prefix}: {h.name_pl} ({h.name_de})"
        return f"{prefix}: {h.name_pl}"
