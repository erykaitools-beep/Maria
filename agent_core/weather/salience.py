"""
Weather salience filter and formatting.

Default: do NOT show weather (per roadmap: "100 danych bez filtra = spam").
Weather only appears when actionable (extreme temp, rain, storm) or
when operator explicitly opts in via preference weather_always=True.
"""

from typing import Optional

from agent_core.weather.weather_sensor import WeatherData

# Icon prefixes that indicate precipitation or storm
_PRECIP_ICONS = {"09", "10", "11", "13"}  # rain, heavy rain, thunderstorm, snow

# Hydration nudge: feels-like OR actual temp at/above this is "hot enough" to
# remind the operator to drink water during the day (proactive care feature).
HYDRATION_THRESHOLD_C = 30.0


def needs_hydration_reminder(
    weather: WeatherData, threshold_c: float = HYDRATION_THRESHOLD_C
) -> bool:
    """True when it is hot enough to nudge the operator about drinking water.

    Uses the hotter of actual vs feels-like temperature so dry/windy days
    (where feels-like can dip below the real reading) still trigger on a
    genuinely hot day. Distinct from is_weather_salient(): salience decides
    whether to mention weather at all (also cold/rain/storm); this is the
    heat-specific gate for the during-day hydration nudge.
    """
    return max(weather.temp_c, weather.feels_like_c) >= threshold_c


def is_weather_salient(weather: WeatherData, operator_model=None) -> bool:
    """Check if weather is worth mentioning to operator.

    Returns True for: freezing, very hot, rain/snow/storm, or operator opt-in.
    """
    # Operator always-show preference
    if operator_model is not None:
        try:
            if operator_model.get_preference("weather_always", False):
                return True
        except Exception:
            pass

    # Temperature extremes
    if weather.temp_c < 0 or weather.feels_like_c < 0:
        return True
    if weather.temp_c > 30 or weather.feels_like_c > 33:
        return True

    # Precipitation / storm (check icon prefix)
    if weather.icon[:2] in _PRECIP_ICONS:
        return True

    # Strong wind (> 15 m/s ~ 54 km/h)
    if weather.wind_speed_ms > 15:
        return True

    return False


def format_weather_line(weather: WeatherData, salient: bool) -> Optional[str]:
    """Format a compact weather line for morning brief.

    Returns None if weather is not salient (should be skipped).
    """
    if not salient:
        return None

    temp = f"{weather.temp_c:.0f}"
    feels = f"{weather.feels_like_c:.0f}"

    # Base line
    parts = [f"Pogoda ({weather.city}): {temp}C"]
    if abs(weather.temp_c - weather.feels_like_c) >= 3:
        parts.append(f"odczuwalna {feels}C")
    parts.append(weather.description)

    line = ", ".join(parts)

    # Advisory suffix for extreme conditions
    if weather.temp_c < 0 or weather.feels_like_c < -5:
        line += ". Ubierz sie cieplo!"
    elif weather.temp_c > 30:
        line += ". Pamietaj o nawodnieniu!"
    elif weather.icon[:2] == "11":
        line += ". Uwaga na burze!"
    elif weather.icon[:2] == "13":
        line += ". Uwaga na snieg!"

    return line
