"""
Tests for PerceptionBuffer.

Contract reference: docs/CONTRACTS.md - Kontrakt 1: Unified Perception
"""

import time

import pytest

from agent_core.perception.event import (
    PerceptionEvent,
    PerceptionSource,
    create_event,
)
from agent_core.perception.buffer import PerceptionBuffer


def _sensor_event(priority=0.3, ttl=5.0, timestamp=None, event_type="resource_reading", **payload_extra):
    """Helper: create a sensor PerceptionEvent."""
    payload = {"ram_available_mb": 18000.0, "cpu_percent": 10.0}
    payload.update(payload_extra)
    return create_event(
        source=PerceptionSource.SENSOR,
        event_type=event_type,
        payload=payload,
        priority=priority,
        ttl=ttl,
        timestamp=timestamp,
    )


def _user_event(text="hello", timestamp=None):
    """Helper: create a user message PerceptionEvent."""
    return create_event(
        source=PerceptionSource.USER,
        event_type="user_message",
        payload={"text": text, "channel": "repl"},
        timestamp=timestamp,
    )


def _system_event(event_type="mode_change", priority=0.8, timestamp=None, **payload):
    """Helper: create a system PerceptionEvent."""
    return create_event(
        source=PerceptionSource.SYSTEM,
        event_type=event_type,
        payload=payload,
        priority=priority,
        timestamp=timestamp,
    )


class TestBufferBasics:
    """Basic buffer operations."""

    def test_empty_buffer(self):
        """New buffer should be empty."""
        buf = PerceptionBuffer()
        assert len(buf) == 0
        assert buf.latest() is None

    def test_default_maxlen(self):
        """Default maxlen should be 200 per contract."""
        buf = PerceptionBuffer()
        assert buf.maxlen == 200

    def test_custom_maxlen(self):
        """Should accept custom maxlen."""
        buf = PerceptionBuffer(maxlen=50)
        assert buf.maxlen == 50

    def test_push_single(self):
        """Should add single event."""
        buf = PerceptionBuffer()
        event = _sensor_event()
        buf.push(event)
        assert len(buf) == 1

    def test_push_many(self):
        """push_many should add multiple events in order."""
        buf = PerceptionBuffer()
        events = [_sensor_event() for _ in range(5)]
        buf.push_many(events)
        assert len(buf) == 5

    def test_latest_returns_newest(self):
        """latest() should return the most recently pushed event."""
        buf = PerceptionBuffer()
        e1 = _sensor_event(timestamp=1000.0)
        e2 = _user_event(text="newer", timestamp=1001.0)
        buf.push(e1)
        buf.push(e2)
        assert buf.latest() == e2

    def test_maxlen_evicts_oldest(self):
        """When full, oldest event should be evicted."""
        buf = PerceptionBuffer(maxlen=3)
        events = [_sensor_event(timestamp=float(i)) for i in range(5)]
        for e in events:
            buf.push(e)

        assert len(buf) == 3
        all_events = buf.get_all()
        # Should keep events[2], events[3], events[4]
        assert all_events[0].timestamp == 2.0
        assert all_events[1].timestamp == 3.0
        assert all_events[2].timestamp == 4.0

    def test_clear(self):
        """clear() should empty the buffer."""
        buf = PerceptionBuffer()
        for _ in range(10):
            buf.push(_sensor_event())
        assert len(buf) == 10
        buf.clear()
        assert len(buf) == 0
        assert buf.latest() is None


class TestGetRecent:
    """Tests for get_recent() method."""

    def test_get_recent_default(self):
        """Should return last 10 events by default."""
        buf = PerceptionBuffer()
        for i in range(20):
            buf.push(_sensor_event(timestamp=float(i)))
        recent = buf.get_recent()
        assert len(recent) == 10
        # Chronological order (oldest first)
        assert recent[0].timestamp == 10.0
        assert recent[-1].timestamp == 19.0

    def test_get_recent_custom_n(self):
        """Should return last N events."""
        buf = PerceptionBuffer()
        for i in range(10):
            buf.push(_sensor_event(timestamp=float(i)))
        recent = buf.get_recent(n=3)
        assert len(recent) == 3
        assert recent[0].timestamp == 7.0
        assert recent[-1].timestamp == 9.0

    def test_get_recent_n_larger_than_buffer(self):
        """Requesting more than available should return all."""
        buf = PerceptionBuffer()
        for i in range(3):
            buf.push(_sensor_event(timestamp=float(i)))
        recent = buf.get_recent(n=100)
        assert len(recent) == 3

    def test_get_recent_empty_buffer(self):
        """Empty buffer should return empty list."""
        buf = PerceptionBuffer()
        assert buf.get_recent() == []

    def test_get_recent_filter_by_source(self):
        """Should filter by PerceptionSource."""
        buf = PerceptionBuffer()
        buf.push(_sensor_event(timestamp=1.0))
        buf.push(_user_event(text="msg1", timestamp=2.0))
        buf.push(_sensor_event(timestamp=3.0))
        buf.push(_user_event(text="msg2", timestamp=4.0))
        buf.push(_sensor_event(timestamp=5.0))

        user_events = buf.get_recent(n=10, source=PerceptionSource.USER)
        assert len(user_events) == 2
        assert all(e.source == PerceptionSource.USER for e in user_events)

        sensor_events = buf.get_recent(n=10, source=PerceptionSource.SENSOR)
        assert len(sensor_events) == 3

    def test_get_recent_filter_by_event_type(self):
        """Should filter by event_type string."""
        buf = PerceptionBuffer()
        buf.push(_sensor_event(event_type="resource_reading", timestamp=1.0))
        buf.push(_sensor_event(event_type="thermal_reading", timestamp=2.0))
        buf.push(_sensor_event(event_type="resource_reading", timestamp=3.0))

        resource = buf.get_recent(n=10, event_type="resource_reading")
        assert len(resource) == 2
        assert all(e.event_type == "resource_reading" for e in resource)

    def test_get_recent_filter_combined(self):
        """Should filter by both source and event_type."""
        buf = PerceptionBuffer()
        buf.push(_sensor_event(event_type="resource_reading", timestamp=1.0))
        buf.push(_user_event(text="msg", timestamp=2.0))
        buf.push(_sensor_event(event_type="thermal_reading", timestamp=3.0))

        result = buf.get_recent(n=10, source=PerceptionSource.SENSOR, event_type="thermal_reading")
        assert len(result) == 1
        assert result[0].event_type == "thermal_reading"

    def test_get_recent_chronological_order(self):
        """Returned events should be in chronological order (oldest first)."""
        buf = PerceptionBuffer()
        for i in range(5):
            buf.push(_sensor_event(timestamp=float(i)))
        recent = buf.get_recent(n=5)
        timestamps = [e.timestamp for e in recent]
        assert timestamps == sorted(timestamps)


class TestGetByPriority:
    """Tests for get_by_priority() method."""

    def test_filter_by_priority(self):
        """Should return events with priority >= threshold."""
        buf = PerceptionBuffer()
        buf.push(_sensor_event(priority=0.1))
        buf.push(_sensor_event(priority=0.3))
        buf.push(_user_event())  # priority 0.9
        buf.push(_system_event(priority=1.0, alert_type="test", severity="critical", message="oom"))

        high = buf.get_by_priority(min_priority=0.5)
        assert len(high) == 2
        assert all(e.priority >= 0.5 for e in high)

    def test_default_threshold(self):
        """Default threshold should be 0.5."""
        buf = PerceptionBuffer()
        buf.push(_sensor_event(priority=0.3))
        buf.push(_sensor_event(priority=0.5))
        buf.push(_sensor_event(priority=0.7))

        result = buf.get_by_priority()
        assert len(result) == 2
        assert result[0].priority == 0.5
        assert result[1].priority == 0.7

    def test_empty_result(self):
        """Should return empty list when no events match."""
        buf = PerceptionBuffer()
        buf.push(_sensor_event(priority=0.1))
        buf.push(_sensor_event(priority=0.2))
        assert buf.get_by_priority(min_priority=0.9) == []


class TestGetByEventType:
    """Tests for get_by_event_type() method."""

    def test_get_by_event_type(self):
        """Should return all events of given type."""
        buf = PerceptionBuffer()
        buf.push(_sensor_event(event_type="resource_reading"))
        buf.push(_sensor_event(event_type="thermal_reading"))
        buf.push(_sensor_event(event_type="resource_reading"))

        resource = buf.get_by_event_type("resource_reading")
        assert len(resource) == 2
        assert all(e.event_type == "resource_reading" for e in resource)

    def test_no_matching_type(self):
        """Should return empty list for non-existent type."""
        buf = PerceptionBuffer()
        buf.push(_sensor_event())
        assert buf.get_by_event_type("nonexistent") == []


class TestGetChildren:
    """Tests for get_children() - causal chain traversal."""

    def test_find_children(self):
        """Should find direct children by parent_event_id."""
        buf = PerceptionBuffer()

        parent = create_event(
            source=PerceptionSource.TEACHER,
            event_type="teacher_decision",
            payload={"strategy_type": "continue", "target_file_id": "physics.txt"},
        )
        buf.push(parent)

        child1 = create_event(
            source=PerceptionSource.LEARNING,
            event_type="chunk_learned",
            payload={"file_id": "physics.txt", "chunk_index": 1, "chunks_total": 5},
            parent_event_id=parent.event_id,
        )
        buf.push(child1)

        child2 = create_event(
            source=PerceptionSource.EXAM,
            event_type="exam_result",
            payload={"file_id": "physics.txt", "score": 0.8, "passed": True, "attempt": 1},
            parent_event_id=parent.event_id,
        )
        buf.push(child2)

        # Unrelated event
        buf.push(_sensor_event())

        children = buf.get_children(parent.event_id)
        assert len(children) == 2
        assert child1 in children
        assert child2 in children

    def test_no_children(self):
        """Should return empty list when no children exist."""
        buf = PerceptionBuffer()
        buf.push(_sensor_event())
        assert buf.get_children("nonexistent-id") == []


class TestDrainExpired:
    """Tests for drain_expired() method."""

    def test_drain_expired_events(self):
        """Should remove events past their TTL."""
        now = 1000.0
        buf = PerceptionBuffer()

        # Expired: created at t=990, ttl=5s, now=1000 -> age=10 > 5
        buf.push(_sensor_event(timestamp=990.0, ttl=5.0))
        # Not expired: created at t=998, ttl=5s, now=1000 -> age=2 < 5
        buf.push(_sensor_event(timestamp=998.0, ttl=5.0))
        # No TTL: never expires
        buf.push(_user_event(timestamp=900.0))

        assert len(buf) == 3
        removed = buf.drain_expired(now=now)
        assert removed == 1
        assert len(buf) == 2

    def test_drain_keeps_no_ttl_events(self):
        """Events with ttl=0 should never be drained."""
        buf = PerceptionBuffer()
        old_event = _user_event(timestamp=1.0)  # ttl=0 (user messages)
        buf.push(old_event)
        removed = buf.drain_expired(now=999999.0)
        assert removed == 0
        assert len(buf) == 1

    def test_drain_empty_buffer(self):
        """Should handle empty buffer gracefully."""
        buf = PerceptionBuffer()
        removed = buf.drain_expired()
        assert removed == 0

    def test_drain_all_expired(self):
        """Should drain all events if all expired."""
        buf = PerceptionBuffer()
        for i in range(5):
            buf.push(_sensor_event(timestamp=float(i), ttl=1.0))

        removed = buf.drain_expired(now=100.0)
        assert removed == 5
        assert len(buf) == 0

    def test_drain_preserves_order(self):
        """Remaining events should maintain chronological order."""
        now = 100.0
        buf = PerceptionBuffer()
        buf.push(_sensor_event(timestamp=90.0, ttl=5.0))   # expired
        buf.push(_sensor_event(timestamp=97.0, ttl=5.0))   # alive
        buf.push(_sensor_event(timestamp=91.0, ttl=5.0))   # expired
        buf.push(_sensor_event(timestamp=99.0, ttl=5.0))   # alive

        buf.drain_expired(now=now)
        remaining = buf.get_all()
        assert len(remaining) == 2
        assert remaining[0].timestamp == 97.0
        assert remaining[1].timestamp == 99.0


class TestGetAll:
    """Tests for get_all() method."""

    def test_returns_copy(self):
        """get_all() should return a copy, not the internal buffer."""
        buf = PerceptionBuffer()
        buf.push(_sensor_event())
        all1 = buf.get_all()
        all2 = buf.get_all()
        assert all1 == all2
        assert all1 is not all2  # Different list objects


class TestStats:
    """Tests for stats() method."""

    def test_stats_empty(self):
        """Stats of empty buffer."""
        buf = PerceptionBuffer(maxlen=100)
        stats = buf.stats()
        assert stats["size"] == 0
        assert stats["maxlen"] == 100
        assert stats["by_source"] == {}
        assert stats["by_type"] == {}

    def test_stats_with_events(self):
        """Stats should count by source and type."""
        buf = PerceptionBuffer()
        buf.push(_sensor_event(event_type="resource_reading"))
        buf.push(_sensor_event(event_type="resource_reading"))
        buf.push(_sensor_event(event_type="thermal_reading"))
        buf.push(_user_event())

        stats = buf.stats()
        assert stats["size"] == 4
        assert stats["by_source"] == {"sensor": 3, "user": 1}
        assert stats["by_type"] == {
            "resource_reading": 2,
            "thermal_reading": 1,
            "user_message": 1,
        }


class TestIntegration:
    """Integration scenarios matching contract examples."""

    def test_contract_sensor_reading_example(self):
        """Contract example: sensor reading -> PerceptionEvent."""
        event = create_event(
            source=PerceptionSource.SENSOR,
            event_type="resource_reading",
            payload={
                "ram_available_mb": 18200.0,
                "ram_available_pct": 56.8,
                "cpu_percent": 12.3,
                "temp_c": 52.0,
                "disk_used_pct": 34.2,
                "inference_latency_ms": 450.0,
            },
        )
        assert event.priority == 0.3
        assert event.ttl == 5.0
        assert event.source == PerceptionSource.SENSOR
        assert event.payload["ram_available_mb"] == 18200.0

    def test_contract_user_message_example(self):
        """Contract example: user message -> PerceptionEvent."""
        event = create_event(
            source=PerceptionSource.USER,
            event_type="user_message",
            payload={
                "text": "Co wiesz o fizyce kwantowej?",
                "channel": "repl",
            },
        )
        assert event.priority == 0.9
        assert event.ttl == 0.0
        assert not event.is_expired()

    def test_tick_loop_scenario(self):
        """Simulate a tick loop: sensors + external events merged in buffer."""
        buf = PerceptionBuffer(maxlen=200)
        now = time.time()

        # Phase 1: 5 sensor readings (per tick)
        for sensor_type in ["resource_reading", "cognitive_reading", "thermal_reading", "power_reading", "time_reading"]:
            buf.push(create_event(
                source=PerceptionSource.SENSOR,
                event_type=sensor_type,
                payload={"value": 42},
                timestamp=now,
            ))

        # External events (from REPL thread)
        buf.push(create_event(
            source=PerceptionSource.USER,
            event_type="user_command",
            payload={"command": "/learn", "args": ""},
            timestamp=now + 0.1,
        ))

        assert len(buf) == 6

        # High priority events only
        high = buf.get_by_priority(min_priority=0.8)
        assert len(high) == 1  # Only user_command (0.9)

        # Recent sensor events
        sensors = buf.get_recent(n=10, source=PerceptionSource.SENSOR)
        assert len(sensors) == 5

    def test_buffer_over_time(self):
        """Buffer sliding window over multiple ticks."""
        buf = PerceptionBuffer(maxlen=10)

        # 20 ticks, 1 event per tick
        for tick in range(20):
            buf.push(_sensor_event(timestamp=float(tick)))

        assert len(buf) == 10
        all_events = buf.get_all()
        # Should have ticks 10-19
        assert all_events[0].timestamp == 10.0
        assert all_events[-1].timestamp == 19.0
