"""
Sensor Adapter - mapuje homeostasis sensors na PerceptionEvent.

Obsluguje 5 typow sensorow:
- ResourceSensor -> resource_reading
- CognitiveSensor -> cognitive_reading
- ThermalSensor -> thermal_reading
- PowerSensor -> power_reading
- TimeSensor -> time_reading

Kontrakt: docs/CONTRACTS.md - Event Type Registry
"""

from typing import Optional

from agent_core.perception.event import (
    PerceptionEvent,
    PerceptionSource,
    create_event,
)


class SensorAdapter:
    """Konwertuje homeostasis sensor metrics na PerceptionEvent."""

    @staticmethod
    def from_resource_metrics(metrics, parent_event_id: Optional[str] = None) -> PerceptionEvent:
        """
        ResourceMetrics -> PerceptionEvent(resource_reading).

        Args:
            metrics: ResourceMetrics dataclass z state_model.py
            parent_event_id: opcjonalny event_id przyczyny
        """
        return create_event(
            source=PerceptionSource.SENSOR,
            event_type="resource_reading",
            payload={
                "ram_available_mb": metrics.ram_available_mb,
                "ram_available_pct": metrics.ram_available_pct,
                "cpu_percent": metrics.cpu_percent,
                "temp_c": metrics.temp_c,
                "disk_used_pct": metrics.disk_used_pct,
                "inference_latency_ms": metrics.inference_latency_ms,
                "swap_used_pct": metrics.swap_used_pct,
                "load_avg_1m": metrics.load_avg_1m,
            },
            timestamp=metrics.timestamp,
            parent_event_id=parent_event_id,
        )

    @staticmethod
    def from_cognitive_metrics(metrics, parent_event_id: Optional[str] = None) -> PerceptionEvent:
        """
        CognitiveMetrics -> PerceptionEvent(cognitive_reading).

        Args:
            metrics: CognitiveMetrics dataclass z state_model.py
            parent_event_id: opcjonalny event_id przyczyny
        """
        return create_event(
            source=PerceptionSource.SENSOR,
            event_type="cognitive_reading",
            payload={
                "context_coherence": metrics.context_coherence,
                "inference_latency_ms": metrics.inference_latency_ms,
                "error_count_1h": metrics.error_count_1h,
                "goal_stack_depth": metrics.goal_stack_depth,
                "memory_entries": metrics.memory_entries,
                "contradiction_count": metrics.contradiction_count,
                "attention_fragmentation": metrics.attention_fragmentation,
            },
            timestamp=metrics.timestamp,
            parent_event_id=parent_event_id,
        )

    @staticmethod
    def from_thermal_metrics(metrics, parent_event_id: Optional[str] = None) -> PerceptionEvent:
        """
        ThermalMetrics -> PerceptionEvent(thermal_reading).

        Args:
            metrics: ThermalMetrics dataclass z thermal_sensor.py
            parent_event_id: opcjonalny event_id przyczyny
        """
        payload = {
            "cpu_temp_c": metrics.cpu_temp_c,
            "is_throttling": metrics.is_throttling,
        }
        if metrics.fan_speed_rpm is not None:
            payload["fan_speed_rpm"] = metrics.fan_speed_rpm

        return create_event(
            source=PerceptionSource.SENSOR,
            event_type="thermal_reading",
            payload=payload,
            timestamp=metrics.timestamp,
            parent_event_id=parent_event_id,
        )

    @staticmethod
    def from_power_metrics(metrics, parent_event_id: Optional[str] = None) -> PerceptionEvent:
        """
        PowerMetrics -> PerceptionEvent(power_reading).

        Args:
            metrics: PowerMetrics dataclass z power_sensor.py
            parent_event_id: opcjonalny event_id przyczyny
        """
        payload = {
            "uptime_seconds": metrics.uptime_seconds,
            "is_on_battery": metrics.is_on_battery,
        }
        if metrics.voltage_v is not None:
            payload["voltage_v"] = metrics.voltage_v

        return create_event(
            source=PerceptionSource.SENSOR,
            event_type="power_reading",
            payload=payload,
            timestamp=metrics.timestamp,
            parent_event_id=parent_event_id,
        )

    @staticmethod
    def from_time_metrics(metrics, parent_event_id: Optional[str] = None) -> PerceptionEvent:
        """
        TimeMetrics -> PerceptionEvent(time_reading).

        Args:
            metrics: TimeMetrics dataclass z time_sensor.py
            parent_event_id: opcjonalny event_id przyczyny
        """
        return create_event(
            source=PerceptionSource.SENSOR,
            event_type="time_reading",
            payload={
                "idle_streak_sec": metrics.idle_streak_sec,
                "hour_of_day": metrics.hour_of_day,
                "session_duration_sec": metrics.session_duration_sec,
                "day_of_week": metrics.day_of_week,
            },
            timestamp=metrics.timestamp,
            parent_event_id=parent_event_id,
        )
