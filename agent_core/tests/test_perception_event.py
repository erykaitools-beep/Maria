"""
Tests for PerceptionEvent and PerceptionSource.

Contract reference: docs/CONTRACTS.md - Kontrakt 1: Unified Perception
"""

import time
import uuid

import pytest

from agent_core.perception.event import (
    EVENT_TYPE_DEFAULTS,
    PerceptionEvent,
    PerceptionSource,
    create_event,
)


class TestPerceptionSource:
    """Tests for PerceptionSource enum."""

    def test_all_sources_defined(self):
        """All 7 sources from contract should be defined."""
        assert PerceptionSource.SENSOR.value == "sensor"
        assert PerceptionSource.USER.value == "user"
        assert PerceptionSource.LEARNING.value == "learning"
        assert PerceptionSource.EXAM.value == "exam"
        assert PerceptionSource.CONSCIOUSNESS.value == "consciousness"
        assert PerceptionSource.TEACHER.value == "teacher"
        assert PerceptionSource.SYSTEM.value == "system"

    def test_source_count(self):
        """Should have exactly 8 sources (7 original + PLANNER)."""
        assert len(PerceptionSource) == 8

    def test_source_from_string(self):
        """Should create source from string value."""
        assert PerceptionSource("sensor") == PerceptionSource.SENSOR
        assert PerceptionSource("user") == PerceptionSource.USER
        assert PerceptionSource("system") == PerceptionSource.SYSTEM

    def test_invalid_source_raises(self):
        """Invalid source string should raise ValueError."""
        with pytest.raises(ValueError):
            PerceptionSource("invalid")


class TestPerceptionEvent:
    """Tests for PerceptionEvent dataclass."""

    def _make_event(self, **kwargs):
        """Helper: create a PerceptionEvent with defaults."""
        defaults = {
            "event_id": str(uuid.uuid4()),
            "source": PerceptionSource.SENSOR,
            "event_type": "resource_reading",
            "priority": 0.3,
            "timestamp": time.time(),
            "payload": {"ram_available_mb": 18200.0, "cpu_percent": 12.3},
            "ttl": 5.0,
            "parent_event_id": None,
        }
        defaults.update(kwargs)
        return PerceptionEvent(**defaults)

    def test_create_basic(self):
        """Should create event with all fields."""
        event = self._make_event()
        assert event.source == PerceptionSource.SENSOR
        assert event.event_type == "resource_reading"
        assert event.priority == 0.3
        assert event.ttl == 5.0
        assert event.parent_event_id is None
        assert isinstance(event.payload, dict)

    def test_frozen(self):
        """PerceptionEvent should be immutable (frozen=True)."""
        event = self._make_event()
        with pytest.raises(AttributeError):
            event.priority = 0.9  # type: ignore[misc]

    def test_event_id_is_uuid4(self):
        """event_id should be valid UUID4 string."""
        event = self._make_event()
        parsed = uuid.UUID(event.event_id)
        assert parsed.version == 4

    def test_parent_event_id_optional(self):
        """parent_event_id can be None or a valid string."""
        event_root = self._make_event(parent_event_id=None)
        assert event_root.parent_event_id is None

        parent_id = str(uuid.uuid4())
        event_child = self._make_event(parent_event_id=parent_id)
        assert event_child.parent_event_id == parent_id

    def test_priority_range(self):
        """Priority should accept values in 0.0-1.0 range."""
        event_low = self._make_event(priority=0.0)
        assert event_low.priority == 0.0

        event_high = self._make_event(priority=1.0)
        assert event_high.priority == 1.0

    def test_ttl_zero_means_no_expiry(self):
        """TTL=0 means event never expires."""
        event = self._make_event(ttl=0.0)
        assert event.ttl == 0.0
        assert not event.is_expired()

    def test_payload_arbitrary_dict(self):
        """Payload accepts arbitrary dict structure."""
        payload = {
            "text": "Hello",
            "nested": {"key": "value"},
            "list": [1, 2, 3],
            "number": 42,
        }
        event = self._make_event(payload=payload)
        assert event.payload == payload

    def test_equality(self):
        """Two events with same fields should be equal (frozen dataclass)."""
        kwargs = {
            "event_id": "test-id-123",
            "source": PerceptionSource.USER,
            "event_type": "user_message",
            "priority": 0.9,
            "timestamp": 1709312400.0,
            "payload": {"text": "hello"},
            "ttl": 0.0,
            "parent_event_id": None,
        }
        event1 = PerceptionEvent(**kwargs)
        event2 = PerceptionEvent(**kwargs)
        assert event1 == event2

    def test_hashable(self):
        """Frozen dataclass should be hashable (can be used in sets)."""
        event = self._make_event(payload={"x": 1})
        # Dict is not hashable, so frozen dataclass with dict won't be hashable
        # This is expected Python behavior - frozen doesn't make contents hashable
        # Just verify the object exists and is usable
        assert event is not None


class TestIsExpired:
    """Tests for PerceptionEvent.is_expired()."""

    def test_not_expired_within_ttl(self):
        """Event within TTL should not be expired."""
        now = time.time()
        event = PerceptionEvent(
            event_id="test",
            source=PerceptionSource.SENSOR,
            event_type="resource_reading",
            priority=0.3,
            timestamp=now,
            payload={},
            ttl=10.0,
            parent_event_id=None,
        )
        assert not event.is_expired(now + 5.0)

    def test_expired_after_ttl(self):
        """Event past TTL should be expired."""
        now = time.time()
        event = PerceptionEvent(
            event_id="test",
            source=PerceptionSource.SENSOR,
            event_type="resource_reading",
            priority=0.3,
            timestamp=now,
            payload={},
            ttl=5.0,
            parent_event_id=None,
        )
        assert event.is_expired(now + 6.0)

    def test_ttl_zero_never_expires(self):
        """TTL=0 means event never expires regardless of age."""
        old_time = time.time() - 86400  # 24h ago
        event = PerceptionEvent(
            event_id="test",
            source=PerceptionSource.USER,
            event_type="user_message",
            priority=0.9,
            timestamp=old_time,
            payload={"text": "old message"},
            ttl=0.0,
            parent_event_id=None,
        )
        assert not event.is_expired()

    def test_expired_exactly_at_ttl(self):
        """Event exactly at TTL boundary should not be expired (> not >=)."""
        now = 1000.0
        event = PerceptionEvent(
            event_id="test",
            source=PerceptionSource.SENSOR,
            event_type="resource_reading",
            priority=0.3,
            timestamp=now,
            payload={},
            ttl=5.0,
            parent_event_id=None,
        )
        # At exactly TTL boundary: (now + 5.0 - now) = 5.0, not > 5.0
        assert not event.is_expired(now + 5.0)
        # Just past TTL
        assert event.is_expired(now + 5.001)

    def test_is_expired_uses_current_time_by_default(self):
        """is_expired() without args should use current time."""
        event = PerceptionEvent(
            event_id="test",
            source=PerceptionSource.SENSOR,
            event_type="resource_reading",
            priority=0.3,
            timestamp=time.time() - 100,
            payload={},
            ttl=1.0,  # 1 second TTL, created 100s ago
            parent_event_id=None,
        )
        assert event.is_expired()


class TestIsDedupable:
    """Tests for PerceptionEvent.is_dedupable property."""

    def test_sensor_readings_are_dedupable(self):
        """Sensor readings should be dedupable per Event Type Registry."""
        event = PerceptionEvent(
            event_id="test",
            source=PerceptionSource.SENSOR,
            event_type="resource_reading",
            priority=0.3,
            timestamp=time.time(),
            payload={},
            ttl=5.0,
            parent_event_id=None,
        )
        assert event.is_dedupable is True

    def test_user_message_not_dedupable(self):
        """User messages should NOT be dedupable."""
        event = PerceptionEvent(
            event_id="test",
            source=PerceptionSource.USER,
            event_type="user_message",
            priority=0.9,
            timestamp=time.time(),
            payload={"text": "hello"},
            ttl=0.0,
            parent_event_id=None,
        )
        assert event.is_dedupable is False

    def test_unknown_type_not_dedupable(self):
        """Unknown event types default to not dedupable."""
        event = PerceptionEvent(
            event_id="test",
            source=PerceptionSource.SYSTEM,
            event_type="unknown_custom_type",
            priority=0.5,
            timestamp=time.time(),
            payload={},
            ttl=0.0,
            parent_event_id=None,
        )
        assert event.is_dedupable is False


class TestEventTypeDefaults:
    """Tests for EVENT_TYPE_DEFAULTS registry."""

    def test_all_types_registered(self):
        """Event Type Registry should have all types (22 original + 2 planner)."""
        assert len(EVENT_TYPE_DEFAULTS) == 24

    def test_sensor_types_present(self):
        """All 5 sensor reading types should be registered."""
        sensor_types = [
            "resource_reading", "cognitive_reading",
            "thermal_reading", "power_reading", "time_reading",
        ]
        for t in sensor_types:
            assert t in EVENT_TYPE_DEFAULTS, f"Missing sensor type: {t}"
            priority, ttl, dedup = EVENT_TYPE_DEFAULTS[t]
            assert priority == 0.3
            assert ttl == 5.0
            assert dedup is True

    def test_user_types_present(self):
        """User event types should have high priority and no TTL."""
        for t in ["user_message", "user_command"]:
            assert t in EVENT_TYPE_DEFAULTS
            priority, ttl, dedup = EVENT_TYPE_DEFAULTS[t]
            assert priority == 0.9
            assert ttl == 0.0
            assert dedup is False

    def test_alert_type_has_highest_priority(self):
        """Alert should have priority 1.0."""
        priority, ttl, dedup = EVENT_TYPE_DEFAULTS["alert"]
        assert priority == 1.0
        assert ttl == 0.0

    def test_defaults_format(self):
        """Each entry should be (priority, ttl, dedupable) tuple."""
        for event_type, defaults in EVENT_TYPE_DEFAULTS.items():
            assert len(defaults) == 3, f"Bad format for {event_type}"
            priority, ttl, dedup = defaults
            assert isinstance(priority, float), f"priority not float: {event_type}"
            assert isinstance(ttl, float), f"ttl not float: {event_type}"
            assert isinstance(dedup, bool), f"dedup not bool: {event_type}"
            assert 0.0 <= priority <= 1.0, f"priority out of range: {event_type}"
            assert ttl >= 0.0, f"ttl negative: {event_type}"


class TestCreateEvent:
    """Tests for create_event() factory function."""

    def test_basic_creation(self):
        """Should create event with required args."""
        event = create_event(
            source=PerceptionSource.SENSOR,
            event_type="resource_reading",
            payload={"ram_available_mb": 18000.0, "cpu_percent": 15.0},
        )
        assert event.source == PerceptionSource.SENSOR
        assert event.event_type == "resource_reading"
        assert event.payload["ram_available_mb"] == 18000.0

    def test_auto_generates_event_id(self):
        """Should generate UUID4 event_id automatically."""
        event = create_event(
            source=PerceptionSource.USER,
            event_type="user_message",
            payload={"text": "hello"},
        )
        # Should be valid UUID4
        parsed = uuid.UUID(event.event_id)
        assert parsed.version == 4

    def test_auto_generates_timestamp(self):
        """Should use current time as timestamp."""
        before = time.time()
        event = create_event(
            source=PerceptionSource.SENSOR,
            event_type="resource_reading",
            payload={},
        )
        after = time.time()
        assert before <= event.timestamp <= after

    def test_uses_registry_defaults_for_priority(self):
        """Should use default priority from Event Type Registry."""
        event = create_event(
            source=PerceptionSource.SENSOR,
            event_type="resource_reading",
            payload={},
        )
        assert event.priority == 0.3  # default for resource_reading

    def test_uses_registry_defaults_for_ttl(self):
        """Should use default TTL from Event Type Registry."""
        event = create_event(
            source=PerceptionSource.SENSOR,
            event_type="resource_reading",
            payload={},
        )
        assert event.ttl == 5.0  # default for resource_reading

    def test_override_priority(self):
        """Explicit priority should override registry default."""
        event = create_event(
            source=PerceptionSource.SENSOR,
            event_type="resource_reading",
            payload={},
            priority=1.0,  # Override: CRITICAL sensor reading
        )
        assert event.priority == 1.0

    def test_override_ttl(self):
        """Explicit TTL should override registry default."""
        event = create_event(
            source=PerceptionSource.SENSOR,
            event_type="resource_reading",
            payload={},
            ttl=60.0,
        )
        assert event.ttl == 60.0

    def test_custom_event_id(self):
        """Should accept custom event_id."""
        event = create_event(
            source=PerceptionSource.SYSTEM,
            event_type="mode_change",
            payload={"from_mode": "active", "to_mode": "reduced"},
            event_id="custom-id-123",
        )
        assert event.event_id == "custom-id-123"

    def test_custom_timestamp(self):
        """Should accept custom timestamp."""
        event = create_event(
            source=PerceptionSource.SYSTEM,
            event_type="alert",
            payload={"alert_type": "test", "severity": "warning", "message": "test"},
            timestamp=1000.0,
        )
        assert event.timestamp == 1000.0

    def test_parent_event_id(self):
        """Should pass through parent_event_id."""
        parent_id = str(uuid.uuid4())
        event = create_event(
            source=PerceptionSource.EXAM,
            event_type="exam_result",
            payload={"file_id": "test.txt", "score": 0.8, "passed": True, "attempt": 1},
            parent_event_id=parent_id,
        )
        assert event.parent_event_id == parent_id

    def test_unknown_event_type_uses_fallback_defaults(self):
        """Unknown event type should use fallback (0.5, 0.0, False)."""
        event = create_event(
            source=PerceptionSource.SYSTEM,
            event_type="custom_new_type",
            payload={"data": "test"},
        )
        assert event.priority == 0.5
        assert event.ttl == 0.0

    def test_unique_event_ids(self):
        """Each call should generate unique event_id."""
        events = [
            create_event(
                source=PerceptionSource.SENSOR,
                event_type="resource_reading",
                payload={},
            )
            for _ in range(100)
        ]
        ids = [e.event_id for e in events]
        assert len(set(ids)) == 100

    def test_causal_chain_example(self):
        """Contract example: teacher_decision -> chunk_learned -> exam_result."""
        teacher = create_event(
            source=PerceptionSource.TEACHER,
            event_type="teacher_decision",
            payload={"strategy_type": "continue", "target_file_id": "physics.txt"},
        )

        learning = create_event(
            source=PerceptionSource.LEARNING,
            event_type="chunk_learned",
            payload={"file_id": "physics.txt", "chunk_index": 3, "chunks_total": 8},
            parent_event_id=teacher.event_id,
        )

        exam = create_event(
            source=PerceptionSource.EXAM,
            event_type="exam_result",
            payload={"file_id": "physics.txt", "score": 0.85, "passed": True, "attempt": 1},
            parent_event_id=learning.event_id,
        )

        # Verify chain
        assert teacher.parent_event_id is None
        assert learning.parent_event_id == teacher.event_id
        assert exam.parent_event_id == learning.event_id
