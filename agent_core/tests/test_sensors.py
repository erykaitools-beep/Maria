"""
Tests for homeostasis sensors.

Spec reference: homeostasis_spec.md section 2 (lines 80-249)
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock

from agent_core.homeostasis.sensors.resource_sensor import ResourceSensor
from agent_core.homeostasis.sensors.cognitive_sensor import CognitiveSensor
from agent_core.homeostasis.sensors.thermal_sensor import ThermalSensor
from agent_core.homeostasis.sensors.power_sensor import PowerSensor
from agent_core.homeostasis.sensors.time_sensor import TimeSensor
from agent_core.homeostasis.state_model import ResourceMetrics, CognitiveMetrics


class TestResourceSensor:
    """Tests for ResourceSensor - spec lines 80-140."""

    def test_read_metrics_returns_resource_metrics(self):
        """Sensor should return ResourceMetrics dataclass."""
        sensor = ResourceSensor()
        metrics = sensor.read_metrics()

        assert metrics is not None
        assert isinstance(metrics, ResourceMetrics)

    def test_ram_metrics_in_valid_range(self):
        """RAM metrics should be in valid range."""
        sensor = ResourceSensor()
        metrics = sensor.read_metrics()

        # ram_available_mb should be positive
        assert metrics.ram_available_mb >= 0
        # ram_used_mb should be positive
        assert metrics.ram_used_mb >= 0
        # ram_total_mb should be positive
        assert metrics.ram_total_mb >= 0

    def test_cpu_metrics_in_valid_range(self):
        """CPU metrics should be in valid percentage range."""
        sensor = ResourceSensor()
        metrics = sensor.read_metrics()

        assert 0 <= metrics.cpu_percent <= 100

    def test_disk_metrics_in_valid_range(self):
        """Disk metrics should be in valid percentage range."""
        sensor = ResourceSensor()
        metrics = sensor.read_metrics()

        assert 0 <= metrics.disk_used_pct <= 100

    def test_fallback_on_psutil_failure(self):
        """Sensor should return worst-case values on failure.

        Spec: lines 969-974 - fallback to worst-case
        """
        sensor = ResourceSensor()

        with patch('psutil.virtual_memory', side_effect=Exception("Test error")):
            with patch('psutil.cpu_percent', side_effect=Exception("Test error")):
                with patch('psutil.disk_usage', side_effect=Exception("Test error")):
                    with patch('psutil.swap_memory', side_effect=Exception("Test error")):
                        metrics = sensor.read_metrics()

        # Should return fallback values, not None
        assert metrics is not None
        # Fallback values indicate worst case
        assert metrics.cpu_percent == 100
        assert metrics.disk_used_pct == 100

    def test_sensor_has_timestamp(self):
        """Metrics should include timestamp."""
        sensor = ResourceSensor()
        metrics = sensor.read_metrics()

        assert hasattr(metrics, 'timestamp')
        assert metrics.timestamp > 0
        assert metrics.timestamp <= time.time()

    def test_get_memory_pressure(self):
        """Should calculate memory pressure."""
        sensor = ResourceSensor()
        pressure = sensor.get_memory_pressure()

        assert 0 <= pressure <= 100


class TestCognitiveSensor:
    """Tests for CognitiveSensor - spec lines 141-200."""

    def test_read_metrics_with_mock_managers(self):
        """Sensor should read from memory and LLM managers."""
        sensor = CognitiveSensor()

        # Mock managers
        memory_manager = Mock()
        memory_manager.get_semantic_coherence.return_value = 0.95
        memory_manager.get_total_entries.return_value = 100
        memory_manager.get_contradiction_count.return_value = 0
        memory_manager.get_episodic_freshness.return_value = 60

        llm_manager = Mock()
        llm_manager.get_last_latency_ms.return_value = 150.0
        llm_manager.get_context_tokens.return_value = 1000

        metrics = sensor.read_metrics(memory_manager, llm_manager)

        assert metrics is not None
        assert isinstance(metrics, CognitiveMetrics)

    def test_coherence_in_valid_range(self):
        """Coherence should be between 0 and 1."""
        sensor = CognitiveSensor()

        memory_manager = Mock()
        memory_manager.get_semantic_coherence.return_value = 0.85
        memory_manager.get_total_entries.return_value = 0
        memory_manager.get_contradiction_count.return_value = 0
        memory_manager.get_episodic_freshness.return_value = 0

        llm_manager = Mock()
        llm_manager.get_last_latency_ms.return_value = 100.0
        llm_manager.get_context_tokens.return_value = 0

        metrics = sensor.read_metrics(memory_manager, llm_manager)

        assert 0 <= metrics.context_coherence <= 1

    def test_goal_stack_depth_tracking(self):
        """Should track goal stack depth for runaway detection.

        Spec: line 164 - goal_stack_depth > 10 indicates runaway
        """
        sensor = CognitiveSensor()

        # Set goal depth manually
        sensor.set_goal_depth(15)

        metrics = sensor.read_metrics(None, None)

        assert metrics.goal_stack_depth == 15

    def test_record_error_tracking(self):
        """Should track error occurrences."""
        sensor = CognitiveSensor()

        # Record some errors
        for _ in range(5):
            sensor.record_error()

        metrics = sensor.read_metrics(None, None)

        assert metrics.error_count_1h == 5

    def test_task_result_tracking(self):
        """Should track task completion ratio."""
        sensor = CognitiveSensor()

        # Record some task results
        sensor.record_task_result(True)
        sensor.record_task_result(True)
        sensor.record_task_result(False)
        sensor.record_task_result(True)

        metrics = sensor.read_metrics(None, None)

        # 3 success out of 4 = 0.75
        assert metrics.task_completion_ratio == 0.75


class TestThermalSensor:
    """Tests for ThermalSensor - spec lines 201-230."""

    def test_read_metrics(self):
        """Should return ThermalMetrics dataclass."""
        sensor = ThermalSensor()
        metrics = sensor.read_metrics()

        assert metrics is not None
        assert hasattr(metrics, 'cpu_temp_c')
        assert hasattr(metrics, 'is_throttling')

    def test_get_temperature(self):
        """Should return temperature in Celsius."""
        sensor = ThermalSensor()
        temp = sensor.get_temperature()

        # Temperature should be reasonable (0-150C for most systems)
        assert 0 <= temp <= 150

    def test_cross_platform_fallback(self):
        """Should handle different platforms gracefully."""
        sensor = ThermalSensor()

        # This should not raise, even on unsupported platforms
        temp = sensor.get_temperature()

        # May return default if no temp available
        assert isinstance(temp, (int, float))

    def test_is_critical_check(self):
        """Should detect critical temperature."""
        sensor = ThermalSensor()

        # Check method exists and returns bool
        result = sensor.is_critical()
        assert isinstance(result, bool)

    def test_is_warning_check(self):
        """Should detect warning temperature."""
        sensor = ThermalSensor()

        result = sensor.is_warning()
        assert isinstance(result, bool)


class TestPowerSensor:
    """Tests for PowerSensor - spec lines 231-249."""

    def test_read_power_metrics(self):
        """Should return PowerMetrics dataclass."""
        sensor = PowerSensor()
        metrics = sensor.read_metrics()

        assert metrics is not None
        assert hasattr(metrics, 'uptime_seconds')
        assert hasattr(metrics, 'voltage_v')
        assert hasattr(metrics, 'is_on_battery')

    def test_uptime_positive(self):
        """Uptime should be positive."""
        sensor = PowerSensor()
        metrics = sensor.read_metrics()

        assert metrics.uptime_seconds > 0

    def test_get_uptime(self):
        """Should return uptime directly."""
        sensor = PowerSensor()
        uptime = sensor.get_uptime()

        assert uptime > 0


class TestTimeSensor:
    """Tests for TimeSensor - circadian and idle tracking."""

    def test_read_metrics(self):
        """Should return TimeMetrics dataclass."""
        sensor = TimeSensor()
        metrics = sensor.read_metrics()

        assert metrics is not None
        assert hasattr(metrics, 'hour_of_day')
        assert hasattr(metrics, 'day_of_week')
        assert hasattr(metrics, 'idle_streak_sec')

    def test_hour_in_valid_range(self):
        """Hour should be 0-23."""
        sensor = TimeSensor()
        metrics = sensor.read_metrics()

        assert 0 <= metrics.hour_of_day <= 23

    def test_day_of_week_in_valid_range(self):
        """Day of week should be 0-6."""
        sensor = TimeSensor()
        metrics = sensor.read_metrics()

        assert 0 <= metrics.day_of_week <= 6

    def test_idle_seconds_tracking(self):
        """Should track idle seconds since last activity."""
        sensor = TimeSensor()

        # Record activity
        sensor.record_activity()

        # Small delay
        time.sleep(0.1)

        idle = sensor.get_idle_streak_seconds()
        assert idle >= 0.1

    def test_record_interaction(self):
        """Should reset idle on interaction."""
        sensor = TimeSensor()

        # Wait a bit
        time.sleep(0.1)

        # Record interaction
        sensor.record_interaction()

        # Idle should be reset
        idle = sensor.get_idle_seconds()
        assert idle < 0.1

    def test_is_night_hours(self):
        """Should detect night hours."""
        sensor = TimeSensor()

        # Method should return bool
        result = sensor.is_night_hours()
        assert isinstance(result, bool)

    def test_is_weekend(self):
        """Should detect weekend."""
        sensor = TimeSensor()

        result = sensor.is_weekend()
        assert isinstance(result, bool)

    def test_should_enter_sleep(self):
        """Should detect when idle threshold for sleep reached."""
        sensor = TimeSensor()

        # Just after activity, should not suggest sleep
        sensor.record_interaction()
        assert sensor.should_enter_sleep() == False


class TestSensorIntegration:
    """Integration tests for all sensors working together."""

    def test_all_sensors_instantiate(self):
        """All sensors should instantiate without errors."""
        resource = ResourceSensor()
        cognitive = CognitiveSensor()
        thermal = ThermalSensor()
        power = PowerSensor()
        time_sensor = TimeSensor()

        assert all([resource, cognitive, thermal, power, time_sensor])

    def test_sensors_are_independent(self):
        """Each sensor failure should not affect others."""
        resource = ResourceSensor()
        thermal = ThermalSensor()

        # Even if one has issues, others should work
        r_metrics = resource.read_metrics()
        t_metrics = thermal.read_metrics()

        # Both should succeed on any platform
        assert r_metrics is not None
        assert t_metrics is not None

    def test_all_sensors_produce_valid_output(self):
        """All sensors should produce valid, non-None output."""
        resource = ResourceSensor()
        cognitive = CognitiveSensor()
        thermal = ThermalSensor()
        power = PowerSensor()
        time_sensor = TimeSensor()

        assert resource.read_metrics() is not None
        assert cognitive.read_metrics(None, None) is not None
        assert thermal.read_metrics() is not None
        assert power.read_metrics() is not None
        assert time_sensor.read_metrics() is not None
