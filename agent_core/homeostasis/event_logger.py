"""
Homeostasis Event Logger - Lab-style event persistence

Logs all significant homeostasis events to JSONL for analysis:
- Mode transitions (with trigger metrics)
- Alerts and alarms
- Periodic state snapshots
- Recovery events

Format designed for post-hoc analysis ("lab reports").

Created: 2026-01-31
"""

import json
import time
import threading
import logging
from collections import deque
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum

from .state_model import Mode


logger = logging.getLogger(__name__)


class EventType(Enum):
    """Types of homeostasis events."""
    MODE_CHANGE = "mode_change"
    ALERT = "alert"
    STATE_SNAPSHOT = "state_snapshot"
    RECOVERY = "recovery"
    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    CORRECTIVE_ACTION = "corrective_action"


@dataclass
class ModeChangeEvent:
    """
    Detailed mode change event for lab analysis.

    Captures:
    - What changed (from → to)
    - Why (trigger constraint + value)
    - Context (full metrics at time of change)
    - Duration in previous mode
    """
    timestamp: float
    event_type: str  # "mode_change"
    from_mode: str
    to_mode: str
    trigger: Dict[str, Any]  # {"constraint": "ram_critical", "value": 18.5, "threshold": 20}
    metrics: Dict[str, Any]  # Full state snapshot
    duration_in_prev_mode_sec: float
    health_score: float
    tick_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AlertEvent:
    """Alert/alarm event."""
    timestamp: float
    event_type: str  # "alert"
    alert_type: str
    severity: str  # CRITICAL, ALERT, WARNING
    message: str
    value: Optional[float]
    threshold: Optional[float]
    metrics: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StateSnapshotEvent:
    """Periodic state snapshot."""
    timestamp: float
    event_type: str  # "state_snapshot"
    mode: str
    health_score: float
    metrics: Dict[str, Any]
    alerts_count: int
    tick_count: int
    uptime_sec: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HomeostasisEventLogger:
    """
    Persistent event logger for homeostasis system.

    Writes events to JSONL file for long-term analysis.
    Thread-safe with buffered writes.

    File format (one JSON object per line):
    {"ts": 1706700000.0, "event": "mode_change", "from": "active", ...}
    """

    # Configuration
    DEFAULT_LOG_PATH = Path("meta_data/homeostasis_events.jsonl")
    FLUSH_INTERVAL_SEC = 10  # Flush buffer every 10 seconds
    MAX_BUFFER_SIZE = 50     # Flush if buffer exceeds this
    MAX_LOG_LINES = 5000     # Rotate when file exceeds this
    ROTATE_KEEP_LINES = 2000  # Keep last N lines after rotation

    def __init__(
        self,
        log_path: Optional[Path] = None,
        auto_flush: bool = True,
        log_startup: bool = True,
    ):
        """
        Initialize event logger.

        Args:
            log_path: Path to JSONL file (default: meta_data/homeostasis_events.jsonl)
            auto_flush: Whether to auto-flush buffer periodically
            log_startup: Whether to log startup event (False for read-only usage)
        """
        self.log_path = log_path or self.DEFAULT_LOG_PATH
        self._buffer: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._start_time = time.time()
        self._last_mode_change_time = time.time()
        self._last_flush_time = time.time()
        self._auto_flush = auto_flush
        self._event_count = 0

        # Ensure directory exists
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        # Log startup (skip for read-only consumers like Web UI)
        if log_startup:
            self._log_startup()

    def _log_startup(self) -> None:
        """Log system startup event."""
        event = {
            "ts": time.time(),
            "event": EventType.STARTUP.value,
            "datetime": datetime.now().isoformat(),
            "message": "Homeostasis event logger initialized",
        }
        self._write_event(event)

    def log_mode_change(
        self,
        from_mode: Mode,
        to_mode: Mode,
        interpreted_state: Dict[str, Any],
        alerts: List[str],
        health_score: float,
        tick_count: int,
    ) -> None:
        """
        Log a mode transition with full context.

        Args:
            from_mode: Previous mode
            to_mode: New mode
            interpreted_state: Full metrics at time of change
            alerts: Active alerts that may have triggered change
            health_score: Current health score
            tick_count: Current tick count
        """
        now = time.time()
        duration_in_prev = now - self._last_mode_change_time

        # Determine trigger (what caused the change)
        trigger = self._determine_trigger(from_mode, to_mode, interpreted_state, alerts)

        # Extract key metrics for quick analysis
        metrics = {
            "ram_available_pct": interpreted_state.get("ram_available_pct", 0),
            "ram_available_mb": interpreted_state.get("ram_available_mb", 0),
            "memory_pressure": interpreted_state.get("memory_pressure", 0),
            "cpu_load": interpreted_state.get("cpu_load", 0),
            "temp_c": interpreted_state.get("temp_c", 0),
            "inference_latency_ms": interpreted_state.get("inference_latency_ms", 0),
            "coherence_score": interpreted_state.get("coherence_score", 1.0),
            "idle_seconds": interpreted_state.get("idle_seconds", 0),
            "goal_stack_depth": interpreted_state.get("goal_stack_depth", 0),
            "alerts_active": len(alerts),
        }

        event = ModeChangeEvent(
            timestamp=now,
            event_type=EventType.MODE_CHANGE.value,
            from_mode=from_mode.value,
            to_mode=to_mode.value,
            trigger=trigger,
            metrics=metrics,
            duration_in_prev_mode_sec=round(duration_in_prev, 1),
            health_score=round(health_score, 3),
            tick_count=tick_count,
        )

        self._write_event(event.to_dict())
        self._last_mode_change_time = now

        logger.info(
            f"Event logged: {from_mode.value} → {to_mode.value} "
            f"(trigger: {trigger.get('constraint', 'unknown')}, "
            f"duration: {duration_in_prev:.0f}s)"
        )

    def _determine_trigger(
        self,
        from_mode: Mode,
        to_mode: Mode,
        state: Dict[str, Any],
        alerts: List[str],
    ) -> Dict[str, Any]:
        """
        Determine what triggered the mode change.

        Returns dict with:
        - constraint: Name of violated constraint
        - value: Current value
        - threshold: Threshold that was crossed
        """
        # Check for critical alerts first
        for alert in alerts:
            if "CRITICAL" in alert:
                if "RAM" in alert.upper() or "MEMORY" in alert.upper():
                    return {
                        "constraint": "ram_critical",
                        "value": state.get("ram_available_pct", 0),
                        "threshold": 5,  # SURVIVAL threshold
                        "alert": alert,
                    }
                if "THERMAL" in alert.upper() or "TEMP" in alert.upper():
                    return {
                        "constraint": "thermal_critical",
                        "value": state.get("temp_c", 0),
                        "threshold": 95,
                        "alert": alert,
                    }
                if "LLM" in alert.upper() or "LATENCY" in alert.upper():
                    return {
                        "constraint": "llm_hang",
                        "value": state.get("inference_latency_ms", 0),
                        "threshold": 120000,
                        "alert": alert,
                    }

        # Transition-specific triggers
        if to_mode == Mode.SURVIVAL:
            return {
                "constraint": "ram_critical",
                "value": state.get("ram_available_pct", 0),
                "threshold": 5,
            }

        if to_mode == Mode.REDUCED and from_mode == Mode.ACTIVE:
            # Check what pushed us to REDUCED
            ram = state.get("ram_available_pct", 100)
            cpu = state.get("cpu_load", 0)
            temp = state.get("temp_c", 50)

            if ram < 20:
                return {"constraint": "ram_low", "value": ram, "threshold": 20}
            if cpu > 80:
                return {"constraint": "cpu_high", "value": cpu, "threshold": 80}
            if temp > 85:
                return {"constraint": "thermal_high", "value": temp, "threshold": 85}

        if to_mode == Mode.SLEEP:
            idle = state.get("idle_seconds", 0)
            return {"constraint": "idle_timeout", "value": idle, "threshold": 1800}  # 30 min

        if to_mode == Mode.ACTIVE and from_mode in (Mode.REDUCED, Mode.SLEEP):
            return {
                "constraint": "recovery_complete",
                "value": state.get("health_score", 1.0) if "health_score" in state else 1.0,
                "threshold": 0.7,
            }

        # Default: unknown trigger
        return {
            "constraint": "unknown",
            "value": None,
            "threshold": None,
            "alerts": alerts[:3] if alerts else [],
        }

    def log_alert(
        self,
        alert_type: str,
        severity: str,
        message: str,
        value: Optional[float] = None,
        threshold: Optional[float] = None,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log an alert event.

        Args:
            alert_type: Type of alert (e.g., 'ram_warning', 'thermal_critical')
            severity: CRITICAL, ALERT, or WARNING
            message: Human-readable message
            value: Current value that triggered alert
            threshold: Threshold that was crossed
            metrics: Optional full metrics snapshot
        """
        event = AlertEvent(
            timestamp=time.time(),
            event_type=EventType.ALERT.value,
            alert_type=alert_type,
            severity=severity,
            message=message,
            value=value,
            threshold=threshold,
            metrics=metrics or {},
        )

        self._write_event(event.to_dict())

    def log_state_snapshot(
        self,
        mode: Mode,
        health_score: float,
        interpreted_state: Dict[str, Any],
        alerts_count: int,
        tick_count: int,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log periodic state snapshot.

        Args:
            mode: Current mode
            health_score: Current health score
            interpreted_state: Full metrics
            alerts_count: Number of active alerts
            tick_count: Current tick count
            extra: Optional extra fields (e.g. process_rss_mb)
        """
        now = time.time()
        uptime = now - self._start_time

        metrics = {
            "ram_available_pct": interpreted_state.get("ram_available_pct", 0),
            "memory_pressure": interpreted_state.get("memory_pressure", 0),
            "cpu_load": interpreted_state.get("cpu_load", 0),
            "temp_c": interpreted_state.get("temp_c", 0),
            "inference_latency_ms": interpreted_state.get("inference_latency_ms", 0),
            "coherence_score": interpreted_state.get("coherence_score", 1.0),
        }
        if extra:
            metrics.update(extra)

        event = StateSnapshotEvent(
            timestamp=now,
            event_type=EventType.STATE_SNAPSHOT.value,
            mode=mode.value,
            health_score=round(health_score, 3),
            metrics=metrics,
            alerts_count=alerts_count,
            tick_count=tick_count,
            uptime_sec=round(uptime, 1),
        )

        self._write_event(event.to_dict())

    def log_corrective_action(
        self,
        action_type: str,
        target: str,
        action: str,
        reason: str,
        urgency: str,
    ) -> None:
        """Log a corrective action execution."""
        event = {
            "ts": time.time(),
            "event": EventType.CORRECTIVE_ACTION.value,
            "action_type": action_type,
            "target": target,
            "action": action,
            "reason": reason,
            "urgency": urgency,
        }
        self._write_event(event)

    def log_shutdown(self, reason: str = "normal") -> None:
        """Log system shutdown."""
        event = {
            "ts": time.time(),
            "event": EventType.SHUTDOWN.value,
            "reason": reason,
            "uptime_sec": round(time.time() - self._start_time, 1),
            "total_events": self._event_count,
        }
        self._write_event(event)
        self.flush()  # Ensure all events are written

    def _write_event(self, event: Dict[str, Any]) -> None:
        """
        Add event to buffer and flush if needed.

        Thread-safe.
        """
        with self._lock:
            self._buffer.append(event)
            self._event_count += 1

            # Check if we should flush
            now = time.time()
            should_flush = (
                len(self._buffer) >= self.MAX_BUFFER_SIZE or
                (self._auto_flush and now - self._last_flush_time > self.FLUSH_INTERVAL_SEC)
            )

            if should_flush:
                self._flush_buffer()

    def _flush_buffer(self) -> None:
        """
        Write buffer to file.

        Must be called with lock held.
        """
        if not self._buffer:
            return

        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                for event in self._buffer:
                    # Compact JSON format (one line per event)
                    json_line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    f.write(json_line + "\n")

            self._buffer.clear()
            self._last_flush_time = time.time()

            # Check if rotation needed
            self._maybe_rotate()

        except Exception as e:
            logger.error(f"Failed to flush event buffer: {e}")

    def _maybe_rotate(self) -> None:
        """Rotate log file if it exceeds MAX_LOG_LINES."""
        try:
            if not self.log_path.exists():
                return
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) <= self.MAX_LOG_LINES:
                return
            # Keep only last ROTATE_KEEP_LINES
            keep = lines[-self.ROTATE_KEEP_LINES:]
            with open(self.log_path, "w", encoding="utf-8") as f:
                f.writelines(keep)
            logger.info(
                f"Event log rotated: {len(lines)} -> {len(keep)} lines"
            )
        except Exception as e:
            logger.warning(f"Event log rotation failed: {e}")

    def flush(self) -> None:
        """Force flush buffer to disk."""
        with self._lock:
            self._flush_buffer()

    def get_recent_events(
        self,
        limit: int = 50,
        event_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Read recent events from log file.

        Args:
            limit: Maximum number of events to return
            event_type: Filter by event type (e.g., 'mode_change')

        Returns:
            List of events (newest first)
        """
        # First flush any buffered events
        self.flush()

        try:
            if not self.log_path.exists():
                return []

            # Use deque to keep only last N matching events (bounded memory)
            tail = deque(maxlen=limit)
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        evt = event.get("event") or event.get("event_type")
                        if event_type is None or evt == event_type:
                            tail.append(event)
                    except json.JSONDecodeError:
                        continue

            # Return newest first
            result = list(tail)
            result.reverse()
            return result

        except Exception as e:
            logger.error(f"Failed to read events: {e}")
            return []

    def get_mode_transitions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent mode transitions."""
        return self.get_recent_events(limit=limit, event_type=EventType.MODE_CHANGE.value)

    def get_session_summary(self) -> Dict[str, Any]:
        """
        Get summary of current session.

        Returns:
            Summary with event counts, mode changes, alerts, etc.
        """
        self.flush()

        mode_changes = 0
        alerts = {"CRITICAL": 0, "ALERT": 0, "WARNING": 0}
        modes_visited = set()

        try:
            if self.log_path.exists():
                with open(self.log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                            evt = event.get("event") or event.get("event_type")
                            if evt == "mode_change":
                                mode_changes += 1
                                modes_visited.add(event.get("to_mode", "unknown"))
                            elif evt == "alert":
                                severity = event.get("severity", "UNKNOWN")
                                if severity in alerts:
                                    alerts[severity] += 1
                        except json.JSONDecodeError:
                            continue
        except OSError:
            pass

        return {
            "uptime_sec": round(time.time() - self._start_time, 1),
            "total_events": self._event_count,
            "mode_changes": mode_changes,
            "modes_visited": list(modes_visited),
            "alerts": alerts,
            "log_file": str(self.log_path),
        }


# Singleton instance for global access
_event_logger: Optional[HomeostasisEventLogger] = None


def get_event_logger() -> HomeostasisEventLogger:
    """Get or create global event logger instance."""
    global _event_logger
    if _event_logger is None:
        _event_logger = HomeostasisEventLogger()
    return _event_logger


def init_event_logger(log_path: Optional[Path] = None) -> HomeostasisEventLogger:
    """Initialize global event logger with custom path."""
    global _event_logger
    _event_logger = HomeostasisEventLogger(log_path=log_path)
    return _event_logger
