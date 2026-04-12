"""
OpenWeatherMap sensor with TTL-based caching.

Fetches current weather for a given city. Returns frozen WeatherData
or None on failure. Cache prevents excessive API calls (30 min TTL).
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# OWM Current Weather endpoint
_OWM_URL = "https://api.openweathermap.org/data/2.5/weather"


@dataclass(frozen=True)
class WeatherData:
    """Snapshot of current weather conditions."""

    city: str
    temp_c: float
    feels_like_c: float
    description: str  # Polish description from OWM (lang=pl)
    humidity: int  # percent
    wind_speed_ms: float
    icon: str  # OWM icon code e.g. "10d"
    sunrise: int  # unix timestamp
    sunset: int  # unix timestamp
    fetched_at: float  # unix timestamp


class WeatherSensor:
    """OpenWeatherMap client with in-memory TTL cache."""

    def __init__(
        self,
        api_key: str,
        city: str,
        lang: str = "pl",
        cache_ttl: int = 1800,
        timeout: int = 10,
    ):
        self._api_key = api_key
        self._city = city
        self._lang = lang
        self._cache_ttl = cache_ttl
        self._timeout = timeout
        self._cached: Optional[WeatherData] = None
        self._cached_at: float = 0.0

    @property
    def city(self) -> str:
        return self._city

    def fetch(self) -> Optional[WeatherData]:
        """Fetch current weather. Returns cached result if within TTL."""
        now = time.time()
        if self._cached and (now - self._cached_at) < self._cache_ttl:
            return self._cached

        try:
            resp = requests.get(
                _OWM_URL,
                params={
                    "q": self._city,
                    "appid": self._api_key,
                    "units": "metric",
                    "lang": self._lang,
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            weather = WeatherData(
                city=data.get("name", self._city),
                temp_c=float(data["main"]["temp"]),
                feels_like_c=float(data["main"]["feels_like"]),
                description=data["weather"][0]["description"],
                humidity=int(data["main"]["humidity"]),
                wind_speed_ms=float(data["wind"]["speed"]),
                icon=data["weather"][0]["icon"],
                sunrise=int(data.get("sys", {}).get("sunrise", 0)),
                sunset=int(data.get("sys", {}).get("sunset", 0)),
                fetched_at=now,
            )

            self._cached = weather
            self._cached_at = now
            logger.debug("Weather fetched: %s %.1fC %s", weather.city, weather.temp_c, weather.description)
            return weather

        except requests.RequestException as e:
            logger.warning("Weather fetch failed: %s", e)
            # Return stale cache if available
            if self._cached:
                logger.debug("Returning stale weather cache")
                return self._cached
            return None
        except (KeyError, ValueError, IndexError) as e:
            logger.warning("Weather parse failed: %s", e)
            return None
