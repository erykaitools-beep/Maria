"""
Tests for HomeostasisEventLogger

Tests:
- Event logging (mode changes, alerts, snapshots)
- JSONL file persistence
- Buffer flushing
- Event retrieval
- Session summary
"""

import json
import time
import pytest
import tempfile
from pathlib import Path

from agent_core.homeostasis.event_logger import (
    HomeostasisEventLogger,
    EventType,
    ModeChangeEvent,
    AlertEvent,
    StateSnapshotEvent,
)
from agent_core.homeostasis.state_model import Mode


class TestHomeostasisEventLogger:
    """Test HomeostasisEventLogger functionality."""

    @pytest.fixture
    def temp_log_path(self):
        """Create a temporary log file path."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        yield path
        # Cleanup
        if path.exists():
            path.unlink()

    @pytest.fixture
    def logger(self, temp_log_path):
        """Create a logger with temp file."""
        return HomeostasisEventLogger(log_path=temp_log_path, auto_flush=False)

    def test_init_creates_startup_event(self, temp_log_path):
        """Test that initialization logs startup event."""
        logger = HomeostasisEventLogger(log_path=temp_log_path, auto_flush=False)
        logger.flush()

        with open(temp_log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) >= 1
        event = json.loads(lines[0])
        assert event["event"] == "startup"
        assert "timestamp" in event or "ts" in event

    def test_log_mode_change(self, logger, temp_log_path):
        """Test logging mode transitions."""
        interpreted_state = {
            "ram_available_pct": 25.5,
            "memory_pressure": 74.5,
            "cpu_load": 45.0,
            "temp_c": 65.0,
        }

        logger.log_mode_change(
            from_mode=Mode.ACTIVE,
            to_mode=Mode.REDUCED,
            interpreted_state=interpreted_state,
            alerts=["ALERT: RAM below 30%"],
            health_score=0.72,
            tick_count=100,
        )
        logger.flush()

        events = logger.get_mode_transitions(limit=5)
        assert len(events) >= 1

        # Find mode_change event
        mode_events = [e for e in events if e.get("event_type") == "mode_change"]
        assert len(mode_events) >= 1

        event = mode_events[0]
        assert event["from_mode"] == "active"
        assert event["to_mode"] == "reduced"
        assert event["health_score"] == 0.72
        assert "trigger" in event
        assert "metrics" in event
        assert event["metrics"]["ram_available_pct"] == 25.5

    def test_log_mode_change_determines_trigger(self, logger):
        """Test that trigger is correctly determined."""
        # Test RAM critical trigger
        state = {"ram_available_pct": 4.0, "cpu_load": 30.0}
        alerts = ["CRITICAL: RAM below 5%"]

        logger.log_mode_change(
            from_mode=Mode.REDUCED,
            to_mode=Mode.SURVIVAL,
            interpreted_state=state,
            alerts=alerts,
            health_score=0.2,
            tick_count=200,
        )
        logger.flush()

        events = logger.get_mode_transitions(limit=1)
        event = events[0]

        assert event["trigger"]["constraint"] == "ram_critical"
        assert event["trigger"]["value"] == 4.0

    def test_log_alert(self, logger, temp_log_path):
        """Test logging alerts."""
        logger.log_alert(
            alert_type="ram_warning",
            severity="WARNING",
            message="RAM below 30%",
            value=28.5,
            threshold=30.0,
        )
        logger.flush()

        events = logger.get_recent_events(limit=10, event_type="alert")
        assert len(events) >= 1

        event = events[0]
        assert event["alert_type"] == "ram_warning"
        assert event["severity"] == "WARNING"
        assert event["value"] == 28.5
        assert event["threshold"] == 30.0

    def test_log_state_snapshot(self, logger):
        """Test logging state snapshots."""
        state = {
            "ram_available_pct": 45.0,
            "memory_pressure": 55.0,
            "cpu_load": 35.0,
            "temp_c": 55.0,
        }

        logger.log_state_snapshot(
            mode=Mode.ACTIVE,
            health_score=0.95,
            interpreted_state=state,
            alerts_count=0,
            tick_count=60,
        )
        logger.flush()

        events = logger.get_recent_events(limit=10, event_type="state_snapshot")
        assert len(events) >= 1

        event = events[0]
        assert event["mode"] == "active"
        assert event["health_score"] == 0.95
        assert event["alerts_count"] == 0
        assert "uptime_sec" in event

    def test_log_shutdown(self, logger, temp_log_path):
        """Test logging shutdown event."""
        # Simulate some uptime
        time.sleep(0.1)

        logger.log_shutdown(reason="test_shutdown")

        with open(temp_log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Find shutdown event
        shutdown_events = [
            json.loads(line)
            for line in lines
            if json.loads(line).get("event") == "shutdown"
        ]
        assert len(shutdown_events) >= 1

        event = shutdown_events[-1]
        assert event["reason"] == "test_shutdown"
        assert event["uptime_sec"] > 0

    def test_buffer_flush_on_size(self, temp_log_path):
        """Test that buffer flushes when size threshold is reached."""
        logger = HomeostasisEventLogger(log_path=temp_log_path, auto_flush=False)
        logger.MAX_BUFFER_SIZE = 5  # Lower threshold for testing

        # Log enough events to trigger flush
        for i in range(10):
            logger.log_alert(
                alert_type="test",
                severity="WARNING",
                message=f"Test alert {i}",
            )

        # Force final flush
        logger.flush()

        with open(temp_log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Should have startup + 10 alerts
        assert len(lines) >= 10

    def test_get_recent_events_limit(self, logger):
        """Test that get_recent_events respects limit."""
        for i in range(20):
            logger.log_alert(
                alert_type="test",
                severity="WARNING",
                message=f"Alert {i}",
            )
        logger.flush()

        events = logger.get_recent_events(limit=5)
        assert len(events) == 5

        # Should be newest first
        assert "Alert 19" in events[0]["message"]

    def test_get_recent_events_filter(self, logger):
        """Test filtering events by type."""
        logger.log_alert(alert_type="test", severity="WARNING", message="Alert")
        logger.log_state_snapshot(
            mode=Mode.ACTIVE,
            health_score=1.0,
            interpreted_state={},
            alerts_count=0,
            tick_count=1,
        )
        logger.log_alert(alert_type="test2", severity="CRITICAL", message="Critical")
        logger.flush()

        alerts = logger.get_recent_events(limit=10, event_type="alert")
        snapshots = logger.get_recent_events(limit=10, event_type="state_snapshot")

        assert len(alerts) >= 2
        assert len(snapshots) >= 1

    def test_session_summary(self, logger):
        """Test session summary generation."""
        # Generate some events
        logger.log_mode_change(
            from_mode=Mode.ACTIVE,
            to_mode=Mode.REDUCED,
            interpreted_state={"ram_available_pct": 20},
            alerts=[],
            health_score=0.7,
            tick_count=100,
        )
        logger.log_alert(alert_type="test", severity="CRITICAL", message="Test")
        logger.log_alert(alert_type="test", severity="WARNING", message="Test")
        logger.log_alert(alert_type="test", severity="WARNING", message="Test")
        logger.flush()

        summary = logger.get_session_summary()

        assert summary["total_events"] >= 4  # startup + mode_change + 3 alerts
        assert summary["mode_changes"] >= 1
        assert "reduced" in summary["modes_visited"]
        assert summary["alerts"]["CRITICAL"] >= 1
        assert summary["alerts"]["WARNING"] >= 2
        assert summary["uptime_sec"] >= 0

    def test_duration_tracking(self, logger):
        """Test that duration in previous mode is tracked."""
        # First mode change
        logger.log_mode_change(
            from_mode=Mode.ACTIVE,
            to_mode=Mode.REDUCED,
            interpreted_state={},
            alerts=[],
            health_score=0.7,
            tick_count=100,
        )

        # Wait a bit
        time.sleep(0.2)

        # Second mode change
        logger.log_mode_change(
            from_mode=Mode.REDUCED,
            to_mode=Mode.ACTIVE,
            interpreted_state={},
            alerts=[],
            health_score=0.9,
            tick_count=200,
        )
        logger.flush()

        events = logger.get_mode_transitions(limit=2)

        # Most recent first
        assert events[0]["from_mode"] == "reduced"
        assert events[0]["duration_in_prev_mode_sec"] >= 0.1

    def test_corrective_action_logging(self, logger):
        """Test logging corrective actions."""
        logger.log_corrective_action(
            action_type="signal_module",
            target="learning_engine",
            action="pause",
            reason="CPU saturation at 85%",
            urgency="soon",
        )
        logger.flush()

        events = logger.get_recent_events(limit=10, event_type="corrective_action")
        assert len(events) >= 1

        event = events[0]
        assert event["target"] == "learning_engine"
        assert event["action"] == "pause"
        assert "CPU" in event["reason"]


class TestEventDataclasses:
    """Test event dataclasses."""

    def test_mode_change_event_to_dict(self):
        """Test ModeChangeEvent serialization."""
        event = ModeChangeEvent(
            timestamp=time.time(),
            event_type="mode_change",
            from_mode="active",
            to_mode="reduced",
            trigger={"constraint": "ram_low", "value": 18.5},
            metrics={"ram_available_pct": 18.5},
            duration_in_prev_mode_sec=3600.0,
            health_score=0.72,
            tick_count=100,
        )

        d = event.to_dict()

        assert d["from_mode"] == "active"
        assert d["to_mode"] == "reduced"
        assert d["trigger"]["constraint"] == "ram_low"
        assert d["duration_in_prev_mode_sec"] == 3600.0

    def test_alert_event_to_dict(self):
        """Test AlertEvent serialization."""
        event = AlertEvent(
            timestamp=time.time(),
            event_type="alert",
            alert_type="thermal_warning",
            severity="WARNING",
            message="Temperature above 80C",
            value=82.5,
            threshold=80.0,
            metrics={"temp_c": 82.5},
        )

        d = event.to_dict()

        assert d["severity"] == "WARNING"
        assert d["value"] == 82.5
        assert d["threshold"] == 80.0

    def test_state_snapshot_event_to_dict(self):
        """Test StateSnapshotEvent serialization."""
        event = StateSnapshotEvent(
            timestamp=time.time(),
            event_type="state_snapshot",
            mode="active",
            health_score=0.95,
            metrics={"ram_available_pct": 45.0},
            alerts_count=0,
            tick_count=60,
            uptime_sec=3600.0,
        )

        d = event.to_dict()

        assert d["mode"] == "active"
        assert d["health_score"] == 0.95
        assert d["uptime_sec"] == 3600.0


class TestThreadSafety:
    """Test thread safety of event logger."""

    def test_concurrent_logging(self, tmp_path):
        """Test logging from multiple threads."""
        import threading

        log_path = tmp_path / "concurrent_test.jsonl"
        logger = HomeostasisEventLogger(log_path=log_path, auto_flush=False)

        def log_alerts(thread_id, count):
            for i in range(count):
                logger.log_alert(
                    alert_type=f"thread_{thread_id}",
                    severity="WARNING",
                    message=f"Alert {i} from thread {thread_id}",
                )

        threads = []
        for t_id in range(5):
            t = threading.Thread(target=log_alerts, args=(t_id, 20))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        logger.flush()

        # Count events
        events = logger.get_recent_events(limit=1000)
        alert_events = [e for e in events if e.get("event_type") == "alert"]

        # Should have 5 threads * 20 alerts = 100 alerts
        assert len(alert_events) == 100
