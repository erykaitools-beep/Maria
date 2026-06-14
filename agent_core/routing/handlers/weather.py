"""Weather intent handler for IntentRouter."""

from __future__ import annotations

import re
from typing import Optional


_WEATHER_PATTERNS = [
    re.compile(
        r"\b(?:pogoda|prognoza)\b(?:\s+(?:w|we|dla|na))?\s+"
        r"(?P<city>[\w\s.'-]+?)(?:\?|$|\.)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bweather\b(?:\s+(?:in|for))?\s+"
        r"(?P<city>[\w\s.'-]+?)(?:\?|$|\.)",
        re.IGNORECASE,
    ),
]


def match_weather(task: str, weather_sensor) -> Optional["IntentMatch"]:
    """Match weather queries and return an IntentMatch."""
    if weather_sensor is None:
        return None

    text = (task or "").strip()
    if not text:
        return None

    for pattern in _WEATHER_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        city = _clean_city(match.group("city"))
        if not city:
            continue

        from agent_core.routing.intent_router import IntentMatch

        return IntentMatch(
            handler=lambda city=city: _format_current(weather_sensor, city),
            handler_name="weather",
            args={"city": city},
            path="local",
            confidence=0.95,
            est_cost_tokens=0,
            est_latency_ms=500,
        )

    return None


def _clean_city(city: str) -> str:
    return re.sub(r"\s+", " ", city or "").strip(" ?.,")


def _format_current(weather_sensor, city: str) -> str:
    if hasattr(weather_sensor, "format_current"):
        return weather_sensor.format_current(city)

    if hasattr(weather_sensor, "get_current"):
        return str(weather_sensor.get_current(city))

    if hasattr(weather_sensor, "fetch"):
        data = weather_sensor.fetch()
        if data is None:
            return f"Pogoda dla {city}: brak danych."
        name = getattr(data, "city", city)
        temp = getattr(data, "temp_c", None)
        desc = getattr(data, "description", "")
        humidity = getattr(data, "humidity", None)
        wind = getattr(data, "wind_speed_ms", None)
        parts = [f"Pogoda dla {name}:"]
        if temp is not None:
            parts.append(f"{temp:.1f}C")
        if desc:
            parts.append(str(desc))
        if humidity is not None:
            parts.append(f"wilgotnosc {humidity}%")
        if wind is not None:
            parts.append(f"wiatr {wind:.1f} m/s")
        return ", ".join(parts)

    raise AttributeError("weather_sensor has no supported weather method")


__all__ = ["match_weather"]
