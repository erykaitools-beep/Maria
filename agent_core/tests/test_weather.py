"""Tests for WeatherSensor, SalienceFilter, and MorningBrief integration."""

import time
from unittest.mock import MagicMock, patch

import pytest

from agent_core.weather.weather_sensor import WeatherData, WeatherSensor
from agent_core.weather.salience import is_weather_salient, format_weather_line


# --- Fixtures ---

def _sample_owm_response(temp=20, feels=19, icon="01d", desc="bezchmurnie", wind=3.5):
    """Minimal OWM API response."""
    return {
        "name": "Berlin",
        "main": {"temp": temp, "feels_like": feels, "humidity": 55},
        "weather": [{"description": desc, "icon": icon}],
        "wind": {"speed": wind},
        "sys": {"sunrise": 1700000000, "sunset": 1700040000},
    }


def _make_weather(temp=20, feels=19, icon="01d", desc="bezchmurnie", wind=3.5):
    """Create WeatherData for testing."""
    return WeatherData(
        city="Berlin",
        temp_c=temp,
        feels_like_c=feels,
        description=desc,
        humidity=55,
        wind_speed_ms=wind,
        icon=icon,
        sunrise=1700000000,
        sunset=1700040000,
        fetched_at=time.time(),
    )


# =============================================================================
# WeatherData
# =============================================================================

class TestWeatherData:
    def test_frozen(self):
        w = _make_weather()
        with pytest.raises(AttributeError):
            w.temp_c = 99

    def test_fields(self):
        w = _make_weather(temp=15.5, feels=13.2, icon="10d", desc="lekki deszcz")
        assert w.city == "Berlin"
        assert w.temp_c == 15.5
        assert w.feels_like_c == 13.2
        assert w.icon == "10d"
        assert w.description == "lekki deszcz"


# =============================================================================
# WeatherSensor
# =============================================================================

class TestWeatherSensor:
    @patch("agent_core.weather.weather_sensor.requests.get")
    def test_fetch_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _sample_owm_response(temp=22.3, feels=21.0)
        mock_get.return_value = mock_resp

        sensor = WeatherSensor(api_key="test_key", city="Berlin,DE")
        result = sensor.fetch()

        assert result is not None
        assert result.city == "Berlin"
        assert result.temp_c == 22.3
        assert result.feels_like_c == 21.0
        assert result.description == "bezchmurnie"
        mock_get.assert_called_once()

    @patch("agent_core.weather.weather_sensor.requests.get")
    def test_fetch_uses_cache(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _sample_owm_response()
        mock_get.return_value = mock_resp

        sensor = WeatherSensor(api_key="key", city="Berlin", cache_ttl=3600)
        r1 = sensor.fetch()
        r2 = sensor.fetch()

        assert r1 is r2  # same object from cache
        assert mock_get.call_count == 1  # only one HTTP call

    @patch("agent_core.weather.weather_sensor.requests.get")
    def test_cache_expired(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _sample_owm_response()
        mock_get.return_value = mock_resp

        sensor = WeatherSensor(api_key="key", city="Berlin", cache_ttl=0)
        sensor.fetch()
        sensor.fetch()

        assert mock_get.call_count == 2  # cache expired, two HTTP calls

    @patch("agent_core.weather.weather_sensor.requests.get")
    def test_fetch_network_error_returns_none(self, mock_get):
        import requests as req
        mock_get.side_effect = req.ConnectionError("no network")

        sensor = WeatherSensor(api_key="key", city="Berlin")
        result = sensor.fetch()
        assert result is None

    @patch("agent_core.weather.weather_sensor.requests.get")
    def test_fetch_network_error_returns_stale_cache(self, mock_get):
        import requests as req
        mock_resp = MagicMock()
        mock_resp.json.return_value = _sample_owm_response(temp=15)
        mock_get.return_value = mock_resp

        sensor = WeatherSensor(api_key="key", city="Berlin", cache_ttl=0)
        first = sensor.fetch()
        assert first.temp_c == 15

        # Now network fails
        mock_get.side_effect = req.ConnectionError("no network")
        result = sensor.fetch()
        assert result is not None  # stale cache
        assert result.temp_c == 15

    @patch("agent_core.weather.weather_sensor.requests.get")
    def test_fetch_invalid_json_returns_none(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": "bad key"}
        mock_get.return_value = mock_resp

        sensor = WeatherSensor(api_key="bad", city="Berlin")
        result = sensor.fetch()
        assert result is None

    @patch("agent_core.weather.weather_sensor.requests.get")
    def test_fetch_params(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _sample_owm_response()
        mock_get.return_value = mock_resp

        sensor = WeatherSensor(api_key="mykey", city="Hamburg,DE", lang="pl")
        sensor.fetch()

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["q"] == "Hamburg,DE"
        assert params["appid"] == "mykey"
        assert params["units"] == "metric"
        assert params["lang"] == "pl"

    def test_city_property(self):
        sensor = WeatherSensor(api_key="k", city="Warsaw")
        assert sensor.city == "Warsaw"


# =============================================================================
# SalienceFilter
# =============================================================================

class TestSalienceFilter:
    def test_normal_weather_not_salient(self):
        w = _make_weather(temp=20, feels=19, icon="01d")
        assert is_weather_salient(w) is False

    def test_freezing_is_salient(self):
        w = _make_weather(temp=-2, feels=-5, icon="01d")
        assert is_weather_salient(w) is True

    def test_feels_like_freezing_is_salient(self):
        w = _make_weather(temp=2, feels=-1, icon="01d")
        assert is_weather_salient(w) is True

    def test_hot_is_salient(self):
        w = _make_weather(temp=35, feels=38, icon="01d")
        assert is_weather_salient(w) is True

    def test_rain_is_salient(self):
        w = _make_weather(temp=15, icon="10d", desc="lekki deszcz")
        assert is_weather_salient(w) is True

    def test_heavy_rain_is_salient(self):
        w = _make_weather(temp=15, icon="09d")
        assert is_weather_salient(w) is True

    def test_thunderstorm_is_salient(self):
        w = _make_weather(temp=20, icon="11d")
        assert is_weather_salient(w) is True

    def test_snow_is_salient(self):
        w = _make_weather(temp=-1, icon="13d")
        assert is_weather_salient(w) is True

    def test_strong_wind_is_salient(self):
        w = _make_weather(temp=15, wind=16.0)
        assert is_weather_salient(w) is True

    def test_moderate_wind_not_salient(self):
        w = _make_weather(temp=15, wind=8.0)
        assert is_weather_salient(w) is False

    def test_preference_always_show(self):
        w = _make_weather(temp=20, icon="01d")  # normal weather
        om = MagicMock()
        om.get_preference.return_value = True
        assert is_weather_salient(w, operator_model=om) is True

    def test_preference_not_set(self):
        w = _make_weather(temp=20, icon="01d")
        om = MagicMock()
        om.get_preference.return_value = False
        assert is_weather_salient(w, operator_model=om) is False

    def test_operator_model_none(self):
        w = _make_weather(temp=20, icon="01d")
        assert is_weather_salient(w, operator_model=None) is False


# =============================================================================
# format_weather_line
# =============================================================================

class TestFormatWeatherLine:
    def test_not_salient_returns_none(self):
        w = _make_weather(temp=20)
        assert format_weather_line(w, salient=False) is None

    def test_salient_returns_string(self):
        w = _make_weather(temp=-3, feels=-7, desc="lekki snieg")
        line = format_weather_line(w, salient=True)
        assert line is not None
        assert "Pogoda" in line
        assert "-3" in line
        assert "lekki snieg" in line
        assert "Berlin" in line

    def test_cold_advisory(self):
        w = _make_weather(temp=-5, feels=-10)
        line = format_weather_line(w, salient=True)
        assert "cieplo" in line

    def test_hot_advisory(self):
        w = _make_weather(temp=35, feels=38)
        line = format_weather_line(w, salient=True)
        assert "nawodnieniu" in line

    def test_storm_advisory(self):
        w = _make_weather(temp=20, icon="11d")
        line = format_weather_line(w, salient=True)
        assert "burze" in line

    def test_snow_advisory(self):
        w = _make_weather(temp=1, feels=0, icon="13d")
        line = format_weather_line(w, salient=True)
        assert "snieg" in line

    def test_feels_like_shown_when_different(self):
        w = _make_weather(temp=-2, feels=-8)
        line = format_weather_line(w, salient=True)
        assert "odczuwalna" in line
        assert "-8" in line

    def test_feels_like_hidden_when_similar(self):
        w = _make_weather(temp=31, feels=32)
        line = format_weather_line(w, salient=True)
        assert "odczuwalna" not in line


# =============================================================================
# MorningBrief integration
# =============================================================================

class TestMorningBriefWeather:
    def test_weather_line_in_morning_brief(self):
        from agent_core.proactive.generators import ContentGenerators
        gen = ContentGenerators()
        gen.set_user_name_fn(lambda: "Eryk")
        gen.set_weather_fn(lambda: "Pogoda (Berlin): -3C, snieg. Ubierz sie cieplo!")

        contact = gen._morning_summary()
        assert contact is not None
        assert "Pogoda" in contact.message
        assert "snieg" in contact.message

    def test_no_weather_when_none(self):
        from agent_core.proactive.generators import ContentGenerators
        gen = ContentGenerators()
        gen.set_user_name_fn(lambda: "Eryk")
        gen.set_weather_fn(lambda: None)

        contact = gen._morning_summary()
        assert contact is not None
        assert "Pogoda" not in contact.message

    def test_no_weather_when_not_wired(self):
        from agent_core.proactive.generators import ContentGenerators
        gen = ContentGenerators()
        gen.set_user_name_fn(lambda: "Eryk")
        # weather fn not set

        contact = gen._morning_summary()
        assert contact is not None
        assert "Pogoda" not in contact.message
