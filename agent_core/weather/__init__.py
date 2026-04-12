"""Weather perception module - OpenWeatherMap sensor with salience filtering."""

from agent_core.weather.weather_sensor import WeatherData, WeatherSensor
from agent_core.weather.salience import format_weather_line, is_weather_salient

__all__ = [
    "WeatherData",
    "WeatherSensor",
    "format_weather_line",
    "is_weather_salient",
]
