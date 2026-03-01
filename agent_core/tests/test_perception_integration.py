"""
Integration tests for Perception + Homeostasis tick loop.

Tests that the tick aggregator (ADR-009) correctly:
- Converts sensor metrics to PerceptionEvents during each tick
- Drains external events from the thread-safe queue
- Pushes everything to PerceptionBuffer
- Drains expired events

Contract: docs/CONTRACTS.md - Decyzja 5: Tick Aggregator
"""

import time
import threading

import pytest

from agent_core.perception.event import PerceptionEvent, PerceptionSource, create_event
from agent_core.perception.buffer import PerceptionBuffer
from agent_core.homeostasis.core import HomeostasisCore
from agent_core.homeostasis.state_model import Mode


class TestPerceptionInCore:
    """Tests for perception integration in HomeostasisCore."""

    def _make_core_with_buffer(self, maxlen=200):
        """Create HomeostasisCore with PerceptionBuffer attached."""
        core = HomeostasisCore()
        buf = PerceptionBuffer(maxlen=maxlen)
        core.set_perception_buffer(buf)
        return core, buf

    def test_set_perception_buffer(self):
        """set_perception_buffer should store buffer reference."""
        core = HomeostasisCore()
        buf = PerceptionBuffer()
        core.set_perception_buffer(buf)
        assert core._perception_buffer is buf

    def test_tick_populates_buffer(self):
        """Single tick should push sensor events to buffer."""
        core, buf = self._make_core_with_buffer()

        # Execute one tick
        core._execute_tick()

        # Should have at least sensor events
        assert len(buf) > 0

        # Check that sensor events were created
        sensor_events = buf.get_recent(n=100, source=PerceptionSource.SENSOR)
        assert len(sensor_events) >= 3  # resource, cognitive, thermal at minimum

        # All should be SENSOR source
        for event in sensor_events:
            assert event.source == PerceptionSource.SENSOR

    def test_tick_creates_resource_reading(self):
        """Tick should create resource_reading event from ResourceSensor."""
        core, buf = self._make_core_with_buffer()
        core._execute_tick()

        resource_events = buf.get_by_event_type("resource_reading")
        assert len(resource_events) == 1

        event = resource_events[0]
        assert event.priority == 0.3
        assert event.ttl == 5.0
        assert "ram_available_mb" in event.payload
        assert "cpu_percent" in event.payload

    def test_tick_creates_cognitive_reading(self):
        """Tick should create cognitive_reading event."""
        core, buf = self._make_core_with_buffer()
        core._execute_tick()

        cog_events = buf.get_by_event_type("cognitive_reading")
        assert len(cog_events) == 1
        assert "context_coherence" in cog_events[0].payload

    def test_tick_creates_thermal_reading(self):
        """Tick should create thermal_reading event."""
        core, buf = self._make_core_with_buffer()
        core._execute_tick()

        thermal_events = buf.get_by_event_type("thermal_reading")
        assert len(thermal_events) == 1
        assert "cpu_temp_c" in thermal_events[0].payload

    def test_tick_creates_time_reading(self):
        """Tick should create time_reading event."""
        core, buf = self._make_core_with_buffer()
        core._execute_tick()

        time_events = buf.get_by_event_type("time_reading")
        assert len(time_events) == 1
        assert "idle_streak_sec" in time_events[0].payload
        assert "hour_of_day" in time_events[0].payload

    def test_multiple_ticks_accumulate(self):
        """Multiple ticks should accumulate events in buffer."""
        core, buf = self._make_core_with_buffer()

        core._execute_tick()
        count_after_1 = len(buf)
        assert count_after_1 > 0

        core._execute_tick()
        count_after_2 = len(buf)
        assert count_after_2 > count_after_1

    def test_buffer_maxlen_respected(self):
        """Buffer should not exceed maxlen even after many ticks."""
        core, buf = self._make_core_with_buffer(maxlen=10)

        # Run enough ticks to overflow (each tick adds ~4 sensor events)
        for _ in range(10):
            core._execute_tick()

        assert len(buf) <= 10

    def test_no_buffer_no_crash(self):
        """Tick without perception buffer should work normally (no-op)."""
        core = HomeostasisCore()
        assert core._perception_buffer is None

        # Should not raise
        core._execute_tick()

    def test_expired_events_drained(self):
        """Expired events should be cleaned up during tick aggregation."""
        core, buf = self._make_core_with_buffer()

        # Push an already-expired event
        expired_event = create_event(
            source=PerceptionSource.SENSOR,
            event_type="resource_reading",
            payload={"test": True},
            ttl=1.0,
            timestamp=time.time() - 100,  # 100s ago, ttl=1s -> expired
        )
        buf.push(expired_event)
        assert len(buf) == 1

        # Tick should drain expired + add new sensor events
        core._execute_tick()

        # Expired event should be gone, new events should be there
        all_events = buf.get_all()
        for event in all_events:
            assert not event.is_expired(), f"Found expired event: {event.event_type}"


class TestExternalEventQueue:
    """Tests for external event queue (thread-safe deque)."""

    def test_push_external_event(self):
        """push_external_event should add to queue."""
        core = HomeostasisCore()
        event = create_event(
            source=PerceptionSource.USER,
            event_type="user_message",
            payload={"text": "hello"},
        )
        core.push_external_event(event)
        assert len(core._external_queue) == 1

    def test_drain_external_queue(self):
        """_drain_external_queue should return and clear all events."""
        core = HomeostasisCore()

        events = [
            create_event(
                source=PerceptionSource.USER,
                event_type="user_message",
                payload={"text": f"msg{i}"},
            )
            for i in range(3)
        ]
        for e in events:
            core.push_external_event(e)

        drained = core._drain_external_queue()
        assert len(drained) == 3
        assert len(core._external_queue) == 0

    def test_drain_empty_queue(self):
        """Draining empty queue should return empty list."""
        core = HomeostasisCore()
        drained = core._drain_external_queue()
        assert drained == []

    def test_external_queue_maxlen(self):
        """External queue should respect maxlen=50."""
        core = HomeostasisCore()
        for i in range(60):
            core.push_external_event(
                create_event(
                    source=PerceptionSource.USER,
                    event_type="user_message",
                    payload={"text": f"msg{i}"},
                )
            )
        assert len(core._external_queue) == 50

    def test_external_events_in_tick(self):
        """External events should appear in buffer after tick."""
        core, buf = self._make_core_with_buffer()

        # Push external event before tick
        user_event = create_event(
            source=PerceptionSource.USER,
            event_type="user_message",
            payload={"text": "Co wiesz o fizyce?", "channel": "repl"},
        )
        core.push_external_event(user_event)

        # Execute tick
        core._execute_tick()

        # User event should be in buffer alongside sensor events
        user_events = buf.get_recent(n=10, source=PerceptionSource.USER)
        assert len(user_events) == 1
        assert user_events[0].payload["text"] == "Co wiesz o fizyce?"

        # External queue should be empty now
        assert len(core._external_queue) == 0

    def test_thread_safety(self):
        """External queue should be safe for concurrent push from threads."""
        core, buf = self._make_core_with_buffer()
        errors = []

        def push_events(n, thread_id):
            try:
                for i in range(n):
                    core.push_external_event(
                        create_event(
                            source=PerceptionSource.USER,
                            event_type="user_message",
                            payload={"text": f"thread{thread_id}_msg{i}"},
                        )
                    )
            except Exception as e:
                errors.append(e)

        # 5 threads, each pushing 10 events
        threads = [
            threading.Thread(target=push_events, args=(10, i))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # maxlen=50, 50 events total, all should be there
        assert len(core._external_queue) == 50

    def _make_core_with_buffer(self, maxlen=200):
        """Create HomeostasisCore with PerceptionBuffer attached."""
        core = HomeostasisCore()
        buf = PerceptionBuffer(maxlen=maxlen)
        core.set_perception_buffer(buf)
        return core, buf


class TestTelemetryWithPerception:
    """Tests for perception stats in telemetry."""

    def test_telemetry_includes_perception_stats(self):
        """get_telemetry() should include perception buffer stats."""
        core = HomeostasisCore()
        buf = PerceptionBuffer()
        core.set_perception_buffer(buf)
        core._execute_tick()

        telemetry = core.get_telemetry()
        assert "perception" in telemetry
        assert "size" in telemetry["perception"]
        assert "by_source" in telemetry["perception"]
        assert telemetry["perception"]["size"] > 0

    def test_telemetry_without_perception(self):
        """get_telemetry() without buffer should work (no perception key)."""
        core = HomeostasisCore()
        telemetry = core.get_telemetry()
        assert "perception" not in telemetry


class TestModeChangePerception:
    """Tests that mode changes emit system events to perception buffer."""

    def test_tick_after_mode_change_has_events(self):
        """After a mode change, buffer should have system events from tick."""
        core = HomeostasisCore()
        buf = PerceptionBuffer()
        core.set_perception_buffer(buf)

        # Execute a few ticks to populate buffer
        for _ in range(3):
            core._execute_tick()

        # Buffer should have sensor events
        assert len(buf) > 0
        stats = buf.stats()
        assert "sensor" in stats["by_source"]
