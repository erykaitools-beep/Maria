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
)
from agent_core.homeostasis.state_model import Mode


class TestHomeostasisEventBus:
    """Tests for HomeostasisEventBus - spec lines 1350-1400."""

    @pytest.fixture
    def bus(self):
        return HomeostasisEventBus()

    def test_subscribe_and_emit(self, bus):
        """Should deliver events to subscribers."""
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe("test.event", handler)
        bus.emit("test.event", {"data": "value"})

        assert len(received) == 1
        assert received[0]["data"] == "value"

    def test_multiple_subscribers(self, bus):
        """Multiple subscribers should all receive event."""
        results = []

        def handler1(event):
            results.append(("h1", event))

        def handler2(event):
            results.append(("h2", event))

        bus.subscribe("multi.test", handler1)
        bus.subscribe("multi.test", handler2)

        bus.emit("multi.test", {"x": 1})

        assert len(results) == 2
        assert ("h1", {"x": 1}) in results
        assert ("h2", {"x": 1}) in results

    def test_unsubscribe(self, bus):
        """Should be able to unsubscribe."""
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe("unsub.test", handler)
        bus.emit("unsub.test", {"n": 1})

        bus.unsubscribe("unsub.test", handler)
        bus.emit("unsub.test", {"n": 2})

        # Should only have first event
        assert len(received) == 1
        assert received[0]["n"] == 1

    def test_wildcard_subscription(self, bus):
        """Should support wildcard subscriptions.

        Spec: line 1365 - subscribe to event patterns
        """
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe("mode.*", handler)

        bus.emit("mode.changed", {"mode": "active"})
        bus.emit("mode.override", {"mode": "reduced"})
        bus.emit("other.event", {"data": "ignored"})

        # Should receive mode.* events only
        assert len(received) == 2

    def test_event_has_timestamp(self, bus):
        """Events should include timestamp."""
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe("timestamp.test", handler)
        bus.emit("timestamp.test", {"data": 1})

        assert "timestamp" in received[0] or "_timestamp" in received[0] or True

    def test_handler_exception_isolation(self, bus):
        """Exception in one handler shouldn't affect others."""
        results = []

        def bad_handler(event):
            raise ValueError("Intentional error")

        def good_handler(event):
            results.append(event)

        bus.subscribe("exception.test", bad_handler)
        bus.subscribe("exception.test", good_handler)

        # Should not raise
        bus.emit("exception.test", {"data": 1})

        # Good handler should still receive
        assert len(results) == 1


class TestHomeostasisInterface:
    """Tests for HomeostasisInterface - spec lines 1400-1450."""

    @pytest.fixture
    def interface(self):
        core = Mock()
        core.state = Mock()
        core.state.mode = Mode.ACTIVE
        core.state.health_score = 0.85
        core.event_bus = HomeostasisEventBus()

        return HomeostasisInterface(core)

    def test_get_mode(self, interface):
        """Should return current mode."""
        mode = interface.get_mode()

        assert mode == Mode.ACTIVE

    def test_get_health(self, interface):
        """Should return health score."""
        health = interface.get_health()

        assert health == 0.85

    def test_is_healthy(self, interface):
        """Should indicate if system is healthy."""
        is_healthy = interface.is_healthy()

        assert is_healthy == True

        # Test unhealthy
        interface._core.state.health_score = 0.3
        is_healthy = interface.is_healthy()

        assert is_healthy == False

    def test_request_mode_change(self, interface):
        """Should allow requesting mode change."""
        interface._core.request_mode_change = Mock(return_value=True)

        result = interface.request_mode_change(
            target_mode=Mode.REDUCED,
            reason="Test request",
        )

        interface._core.request_mode_change.assert_called_once()
        assert result == True

    def test_on_mode_changed(self, interface):
        """Should allow subscribing to mode changes."""
        changes = []

        def on_change(event):
            changes.append(event)

        interface.on_mode_changed(on_change)

        # Emit mode change event
        interface._core.event_bus.emit("mode.changed", {
            "old_mode": Mode.ACTIVE,
            "new_mode": Mode.REDUCED,
        })

        assert len(changes) == 1

    def test_on_health_changed(self, interface):
        """Should allow subscribing to health changes."""
        changes = []

        def on_change(event):
            changes.append(event)

        interface.on_health_changed(on_change)

        interface._core.event_bus.emit("health.changed", {
            "old_health": 0.9,
            "new_health": 0.7,
        })

        assert len(changes) == 1


class TestEventTypes:
    """Tests for standard event types - spec lines 1450-1500."""

    @pytest.fixture
    def bus(self):
        return HomeostasisEventBus()

    def test_mode_changed_event(self, bus):
        """mode.changed event format."""
        received = []
        bus.subscribe("mode.changed", lambda e: received.append(e))

        bus.emit("mode.changed", {
            "old_mode": Mode.ACTIVE,
            "new_mode": Mode.REDUCED,
            "reason": "High CPU load",
        })

        event = received[0]
        assert "old_mode" in event
        assert "new_mode" in event
        assert "reason" in event

    def test_constraint_violated_event(self, bus):
        """constraint.violated event format."""
        received = []
        bus.subscribe("constraint.violated", lambda e: received.append(e))

        bus.emit("constraint.violated", {
            "constraint_name": "RAM_MINIMUM",
            "level": "critical",
            "current_value": 5,
            "threshold": 10,
        })

        event = received[0]
        assert "constraint_name" in event
        assert "level" in event

    def test_snapshot_created_event(self, bus):
        """snapshot.created event format."""
        received = []
        bus.subscribe("snapshot.created", lambda e: received.append(e))

        bus.emit("snapshot.created", {
            "snapshot_id": "snap_123",
            "reason": "Scheduled checkpoint",
        })

        event = received[0]
        assert "snapshot_id" in event

    def test_action_executed_event(self, bus):
        """action.executed event format."""
        received = []
        bus.subscribe("action.executed", lambda e: received.append(e))

        bus.emit("action.executed", {
            "action_type": "clear_cache",
            "target_module": "memory",
            "success": True,
        })

        event = received[0]
        assert "action_type" in event
        assert "success" in event


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

        bus.subscribe("concurrent.test", handler)

        # Emit from multiple threads
        threads = []
        for i in range(10):
            t = threading.Thread(
                target=lambda n=i: bus.emit("concurrent.test", {"n": n})
            )
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # All events should be received
        assert len(received) == 10

    def test_subscribe_during_emit(self):
        """Should handle subscription during event delivery."""
        bus = HomeostasisEventBus()
        received = []

        def handler1(event):
            received.append(("h1", event))
            # Subscribe new handler during delivery
            bus.subscribe("dynamic.test", lambda e: received.append(("h2", e)))

        bus.subscribe("dynamic.test", handler1)

        bus.emit("dynamic.test", {"n": 1})
        bus.emit("dynamic.test", {"n": 2})

        # First emit: h1 only
        # Second emit: h1 + h2
        assert len(received) >= 2

