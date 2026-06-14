"""
Tests for IntentRouter Phase 1 isolated library.

All sensors are mocked. OpenClaw execution is intentionally represented by
placeholder strings until T-002 wiring.
"""

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock

import pytest

from agent_core.homeostasis.time_awareness import TimeAwareness
from agent_core.memory.query import MemoryQuery
from agent_core.orchestrator.self_model_facade import UserFacingSelfModel
from agent_core.routing import IntentMatch, IntentRouter
from agent_core.tests.spec_helpers import specced


@pytest.fixture
def mock_weather():
    sensor = MagicMock()
    sensor.format_current.return_value = "Berlin 15C, cloudy"
    return sensor


@pytest.fixture
def mock_time():
    sensor = specced(TimeAwareness)
    sensor.get_context.return_value = "Jest 12:00, poludnie."
    return sensor


@pytest.fixture
def mock_memory():
    query = specced(MemoryQuery)
    query.get_topic_summary.return_value = {
        "known": True,
        "topic": "logice formalnej",
        "total_results": 2,
    }
    query.get_knowledge_gaps.return_value = [
        {"topic": "algebra", "confidence": 0.2},
    ]
    return query


@pytest.fixture
def mock_self_model():
    model = specced(UserFacingSelfModel)
    model.describe_self.return_value = "Jestem Maria."
    model.describe_capabilities_text.return_value = "Moje zdolnosci: nauka."
    return model


@pytest.fixture
def router(mock_weather, mock_time, mock_memory, mock_self_model):
    return IntentRouter(
        weather_sensor=mock_weather,
        time_awareness=mock_time,
        memory_query=mock_memory,
        self_model=mock_self_model,
        enabled=True,
    )


class TestIntentRouterModel:
    def test_intent_match_is_frozen(self):
        match = IntentMatch(
            handler=lambda: "ok",
            handler_name="test",
            args={},
            path="local",
            confidence=1.0,
            est_cost_tokens=0,
            est_latency_ms=1,
        )

        with pytest.raises(FrozenInstanceError):
            match.path = "changed"

    def test_export_from_routing_package(self):
        assert IntentRouter is not None
        assert IntentMatch is not None


class TestIntentRouterFlag:
    def test_default_disabled_routes_to_legacy(self, monkeypatch, mock_weather):
        monkeypatch.delenv("INTENT_ROUTER_ENABLED", raising=False)
        router = IntentRouter(weather_sensor=mock_weather)

        match = router.route("pogoda w Berlinie")

        assert match.path == "openclaw_raw"
        assert match.handler_name == "legacy"
        assert match.confidence == 0.0

    def test_env_enabled_turns_router_on(self, monkeypatch, mock_weather):
        monkeypatch.setenv("INTENT_ROUTER_ENABLED", "true")
        router = IntentRouter(weather_sensor=mock_weather)

        match = router.route("pogoda w Berlinie")

        assert match.path == "local"
        assert match.handler_name == "weather"


class TestIntentRouterLocal:
    def test_weather_polish(self, router):
        match = router.route("pogoda w Berlinie")

        assert match.path == "local"
        assert match.handler_name == "weather"
        assert match.args["city"] == "Berlinie"
        assert match.est_cost_tokens == 0

    def test_weather_english(self, router):
        match = router.route("weather in London?")

        assert match.path == "local"
        assert match.handler_name == "weather"
        assert match.args["city"] == "London"

    def test_weather_without_sensor_falls_back_raw(self):
        router = IntentRouter(enabled=True)

        match = router.route("pogoda w Berlinie")

        assert match.path == "openclaw_raw"

    def test_time_query_polish(self, router):
        match = router.route("Ktora godzina?")

        assert match.path == "local"
        assert match.handler_name == "time"

    def test_time_query_english(self, router):
        match = router.route("what time is it?")

        assert match.path == "local"
        assert match.handler_name == "time"

    def test_time_without_sensor_falls_back_raw(self):
        router = IntentRouter(enabled=True)

        match = router.route("jaka godzina")

        assert match.path == "openclaw_raw"

    def test_memory_query_topic(self, router):
        match = router.route("co wiesz o logice formalnej")

        assert match.path == "local"
        assert match.handler_name == "memory"
        assert match.args["topic"] == "logice formalnej"

    def test_memory_query_pamietasz(self, router):
        match = router.route("pamietasz rachunek lambda?")

        assert match.path == "local"
        assert match.handler_name == "memory"
        assert match.args["topic"] == "rachunek lambda"

    def test_memory_gaps(self, router):
        match = router.route("show gaps")

        assert match.path == "local"
        assert match.handler_name == "memory"
        assert match.args["query_type"] == "gaps"

    def test_memory_without_sensor_falls_back_raw(self):
        router = IntentRouter(enabled=True)

        match = router.route("co wiesz o logice")

        assert match.path == "openclaw_raw"

    def test_self_model_identity(self, router):
        match = router.route("kim jestes?")

        assert match.path == "local"
        assert match.handler_name == "self_model"
        assert match.args["query_type"] == "identity"

    def test_self_model_capabilities(self, router):
        match = router.route("co umiesz?")

        assert match.path == "local"
        assert match.handler_name == "self_model"
        assert match.args["query_type"] == "capabilities"

    def test_self_model_without_sensor_falls_back_raw(self):
        router = IntentRouter(enabled=True)

        match = router.route("kim jestes")

        assert match.path == "openclaw_raw"


class TestIntentRouterExecute:
    def test_execute_weather_path(self, router, mock_weather):
        result = router.route_and_execute("pogoda w Berlinie")

        assert "Berlin" in result
        assert "15C" in result
        mock_weather.format_current.assert_called_once_with("Berlinie")

    def test_execute_time_path(self, router, mock_time):
        result = router.route_and_execute("ktora godzina")

        assert "12:00" in result
        mock_time.get_context.assert_called_once_with()

    def test_execute_memory_topic(self, router, mock_memory):
        result = router.route_and_execute("co wiesz o logice formalnej")

        assert "logice formalnej" in result
        mock_memory.get_topic_summary.assert_called_once_with("logice formalnej")

    def test_execute_self_model_capabilities(self, router, mock_self_model):
        result = router.route_and_execute("co umiesz?")

        assert "zdolnosci" in result
        mock_self_model.describe_capabilities_text.assert_called_once_with()

    def test_local_handler_failure_uses_openclaw_placeholder(self, router, mock_weather):
        mock_weather.format_current.side_effect = RuntimeError("api down")

        result = router.route_and_execute("pogoda w Berlinie")

        assert result == "[INTENT_ROUTER] would dispatch to OpenClaw: pogoda w Berlinie"


class TestIntentRouterFallback:
    def test_openclaw_pattern_match_write(self, router):
        match = router.route("napisz plik /tmp/x.txt z trescia hello")

        assert match.path == "openclaw_pattern"
        assert match.handler_name == "write"
        assert match.args["tool_name"] == "write"
        assert match.args["tool_args"]["path"] == "/tmp/x.txt"
        assert match.fallback.path == "openclaw_raw"

    def test_openclaw_pattern_match_search(self, router):
        match = router.route("wyszukaj python asyncio")

        assert match.path == "openclaw_pattern"
        assert match.handler_name == "web_search"
        assert match.args["tool_args"]["query"] == "python asyncio"

    def test_raw_openclaw_fallback(self, router):
        match = router.route("jakies bardzo dziwne niezrozumiale zadanie")

        assert match.path == "openclaw_raw"
        assert match.handler_name == "openclaw_raw"
        assert match.args["task"] == "jakies bardzo dziwne niezrozumiale zadanie"

    def test_execute_openclaw_pattern_returns_placeholder(self, router):
        result = router.route_and_execute("przeczytaj plik /tmp/x.txt")

        assert result == (
            "[INTENT_ROUTER] would dispatch to OpenClaw: "
            "przeczytaj plik /tmp/x.txt"
        )

    def test_execute_raw_openclaw_returns_placeholder(self, router):
        result = router.route_and_execute("niejasne zadanie")

        assert result == "[INTENT_ROUTER] would dispatch to OpenClaw: niejasne zadanie"


class TestIntentRouterListHandlers:
    def test_list_handlers_has_four_local_and_two_openclaw(self, router):
        handlers = router.list_handlers()

        names = [h["name"] for h in handlers]
        assert names == [
            "weather",
            "time",
            "memory",
            "self_model",
            "openclaw_pattern",
            "openclaw_raw",
        ]

    def test_list_handlers_shape(self, router):
        for item in router.list_handlers():
            assert set(item) == {"name", "regex_summary", "est_latency_ms"}
            assert isinstance(item["regex_summary"], str)
            assert isinstance(item["est_latency_ms"], int)
