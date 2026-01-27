"""
Tests for API and event bus.

Spec reference: homeostasis_spec.md section 10 (lines 1350-1500)
"""

import pytest
import time
import threading
from unittest.mock import Mock, MagicMock

from agent_core.homeostasis.api import (
    HomeostasisInterface,
    HomeostasisEventBus,
    ResourceType,
    Priority,
)
from agent_core.homeostasis.state_model import Mode


class TestHomeostasisEventBus:
    """Tests for HomeostasisEventBus - spec lines 1350-1400."""

    @pytest.fixture
    def bus(self):
        return HomeostasisEventBus()

    def test_subscribe_and_emit_mode_changed(self, bus):
        """Should deliver mode_changed events to subscribers."""
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe("mode_changed", handler)
        bus.emit_mode_changed(Mode.ACTIVE, Mode.REDUCED, "test")

        assert len(received) == 1
        assert received[0]["old_mode"] == "active"
        assert received[0]["new_mode"] == "reduced"

    def test_multiple_subscribers(self, bus):
        """Multiple subscribers should all receive event."""
        results = []

        def handler1(event):
            results.append(("h1", event))

        def handler2(event):
            results.append(("h2", event))

        bus.subscribe("mode_changed", handler1)
        bus.subscribe("mode_changed", handler2)

        bus.emit_mode_changed(Mode.ACTIVE, Mode.REDUCED, "test")

        assert len(results) == 2

    def test_unsubscribe(self, bus):
        """Should be able to unsubscribe."""
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe("mode_changed", handler)
        bus.emit_mode_changed(Mode.ACTIVE, Mode.REDUCED, "test1")

        bus.unsubscribe("mode_changed", handler)
        bus.emit_mode_changed(Mode.REDUCED, Mode.ACTIVE, "test2")

        # Should only have first event
        assert len(received) == 1
        assert received[0]["new_mode"] == "reduced"

    def test_event_has_timestamp(self, bus):
        """Events should include timestamp."""
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe("mode_changed", handler)
        bus.emit_mode_changed(Mode.ACTIVE, Mode.REDUCED, "test")

        assert "timestamp" in received[0]
        assert received[0]["timestamp"] > 0

    def test_handler_exception_isolation(self, bus):
        """Exception in one handler shouldn't affect others."""
        results = []

        def bad_handler(event):
            raise ValueError("Intentional error")

        def good_handler(event):
            results.append(event)

        bus.subscribe("mode_changed", bad_handler)
        bus.subscribe("mode_changed", good_handler)

        # Should not raise
        bus.emit_mode_changed(Mode.ACTIVE, Mode.REDUCED, "test")

        # Good handler should still receive
        assert len(results) == 1


class TestEventTypes:
    """Tests for all event types - spec lines 1450-1500."""

    @pytest.fixture
    def bus(self):
        return HomeostasisEventBus()

    def test_emit_resource_reduced(self, bus):
        """resource_reduced event format."""
        received = []
        bus.subscribe("resource_reduced", lambda e: received.append(e))

        bus.emit_resource_reduced("memory", 512)

        event = received[0]
        assert "resource_type" in event
        assert "new_allocation" in event
        assert event["resource_type"] == "memory"
        assert event["new_allocation"] == 512

    def test_emit_alert_raised(self, bus):
        """alert_raised event format."""
        received = []
        bus.subscribe("alert_raised", lambda e: received.append(e))

        bus.emit_alert_raised("RAM_LOW", "critical", "Free up memory")

        event = received[0]
        assert "alert_type" in event
        assert "severity" in event
        assert "recommended_action" in event

    def test_emit_health_degraded(self, bus):
        """health_degraded event format."""
        received = []
        bus.subscribe("health_degraded", lambda e: received.append(e))

        bus.emit_health_degraded(0.5, "High CPU load")

        event = received[0]
        assert "health_score" in event
        assert "first_issue" in event
        assert event["health_score"] == 0.5

    def test_emit_recovery_started(self, bus):
        """recovery_started event format."""
        received = []
        bus.subscribe("recovery_started", lambda e: received.append(e))

        bus.emit_recovery_started("degraded", "automatic")

        event = received[0]
        assert "from_state" in event
        assert "recovery_type" in event


class TestHomeostasisInterface:
    """Tests for HomeostasisInterface - spec lines 1400-1450."""

    @pytest.fixture
    def interface(self):
        return HomeostasisInterface()

    def test_get_current_mode_without_core(self, interface):
        """Should return ACTIVE mode when no core set."""
        mode = interface.get_current_mode()
        assert mode == Mode.ACTIVE

    def test_get_health_score_without_core(self, interface):
        """Should return 1.0 when no core set."""
        health = interface.get_health_score()
        assert health == 1.0

    def test_get_alert_state_without_core(self, interface):
        """Should return empty list when no core set."""
        alerts = interface.get_alert_state()
        assert alerts == []

    def test_get_resource_headroom_without_core(self, interface):
        """Should return default headroom when no core set."""
        headroom = interface.get_resource_headroom()

        assert "ram_pct" in headroom
        assert "cpu_pct" in headroom
        assert "disk_pct" in headroom

    def test_get_telemetry_snapshot_without_core(self, interface):
        """Should return empty dict when no core set."""
        telemetry = interface.get_telemetry_snapshot()
        assert telemetry == {}

    def test_set_core(self, interface):
        """Should be able to set core reference."""
        mock_core = Mock()
        interface.set_core(mock_core)

        assert interface._core == mock_core


class TestInterfaceWithCore:
    """Tests for HomeostasisInterface with mock core."""

    @pytest.fixture
    def interface_with_core(self):
        interface = HomeostasisInterface()

        # Create mock core
        mock_core = Mock()
        mock_core.state = Mock()
        mock_core.state.mode = Mode.REDUCED
        mock_core.state.health_score = 0.75
        mock_core.state.alerts = ["WARNING: Test"]
        mock_core.state.interpreted_state = {
            "ram_available_pct": 30,
            "cpu_load": 60,
            "disk_used_pct": 50,
            "thermal_stress": 0.2,
        }
        mock_core.get_telemetry.return_value = {"mode": "reduced"}

        interface.set_core(mock_core)
        return interface

    def test_get_current_mode_with_core(self, interface_with_core):
        """Should return mode from core."""
        mode = interface_with_core.get_current_mode()
        assert mode == Mode.REDUCED

    def test_get_health_score_with_core(self, interface_with_core):
        """Should return health from core."""
        health = interface_with_core.get_health_score()
        assert health == 0.75

    def test_get_alert_state_with_core(self, interface_with_core):
        """Should return alerts from core."""
        alerts = interface_with_core.get_alert_state()
        assert "WARNING: Test" in alerts

    def test_get_resource_headroom_with_core(self, interface_with_core):
        """Should calculate headroom from core state."""
        headroom = interface_with_core.get_resource_headroom()

        assert headroom["ram_pct"] == 30
        assert headroom["cpu_pct"] == 40  # 100 - 60

    def test_get_telemetry_snapshot_with_core(self, interface_with_core):
        """Should return telemetry from core."""
        telemetry = interface_with_core.get_telemetry_snapshot()
        assert telemetry == {"mode": "reduced"}


class TestResourceAllocation:
    """Tests for resource allocation requests."""

    @pytest.fixture
    def interface(self):
        interface = HomeostasisInterface()

        # Set up with mock core in ACTIVE mode
        mock_core = Mock()
        mock_core.state = Mock()
        mock_core.state.mode = Mode.ACTIVE
        mock_core.state.interpreted_state = {
            "ram_available_pct": 50,
            "cpu_load": 30,
        }

        interface.set_core(mock_core)
        return interface

    def test_request_allocation_granted(self, interface):
        """Should grant resource allocation in ACTIVE mode."""
        result = interface.request_resource_allocation(
            module_name="test_module",
            resource_type="memory",
            quantity=100,
            duration_seconds=60,
            priority="normal",
        )

        assert result == True

    def test_get_active_allocations(self, interface):
        """Should track active allocations."""
        interface.request_resource_allocation(
            module_name="test_module",
            resource_type="memory",
            quantity=100,
            duration_seconds=60,
            priority="normal",
        )

        allocations = interface.get_active_allocations()
        assert len(allocations) == 1
        assert allocations[0].module_name == "test_module"


class TestModuleState:
    """Tests for module state reporting."""

    @pytest.fixture
    def interface(self):
        return HomeostasisInterface()

    def test_notify_module_state(self, interface):
        """Should accept module state notifications."""
        interface.notify_module_state(
            module_name="llm",
            state={"inference_latency_ms": 150, "tokens_used": 1000},
        )

        states = interface.get_module_states()
        assert "llm" in states
        assert states["llm"].state["inference_latency_ms"] == 150

    def test_module_state_has_timestamp(self, interface):
        """Module state should have timestamp."""
        interface.notify_module_state(
            module_name="memory",
            state={"coherence": 0.95},
        )

        states = interface.get_module_states()
        assert states["memory"].timestamp > 0


class TestThreadSafety:
    """Tests for thread-safe event handling."""

    def test_concurrent_emit(self):
        """Should handle concurrent emits."""
        bus = HomeostasisEventBus()
        received = []
        lock = threading.Lock()

        def handler(event):
            with lock:
                received.append(event)

        bus.subscribe("mode_changed", handler)

        # Emit from multiple threads
        threads = []
        for i in range(10):
            t = threading.Thread(
                target=lambda n=i: bus.emit_mode_changed(
                    Mode.ACTIVE, Mode.REDUCED, f"test_{n}"
                )
            )
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # All events should be received
        assert len(received) == 10

    def test_concurrent_subscribe(self):
        """Should handle concurrent subscriptions."""
        bus = HomeostasisEventBus()
        handlers_added = []
        lock = threading.Lock()

        def make_handler(n):
            def handler(event):
                with lock:
                    handlers_added.append(n)
            return handler

        # Subscribe from multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(
                target=lambda n=i: bus.subscribe("mode_changed", make_handler(n))
            )
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Emit to trigger all handlers
        bus.emit_mode_changed(Mode.ACTIVE, Mode.REDUCED, "test")

        # All handlers should be called
        assert len(handlers_added) == 5


class TestPriority:
    """Tests for resource priority levels."""

    def test_priority_enum(self):
        """Priority enum should have all levels."""
        assert Priority.CRITICAL.value == "critical"
        assert Priority.HIGH.value == "high"
        assert Priority.NORMAL.value == "normal"
        assert Priority.BACKGROUND.value == "background"


class TestResourceType:
    """Tests for resource type enum."""

    def test_resource_type_enum(self):
        """ResourceType enum should have all types."""
        assert ResourceType.CPU.value == "cpu"
        assert ResourceType.MEMORY.value == "memory"
        assert ResourceType.GPU_MEMORY.value == "gpu_memory"
        assert ResourceType.INFERENCE_TOKENS.value == "inference_tokens"
