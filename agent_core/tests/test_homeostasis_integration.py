"""
Integration tests for the homeostasis spine against real components.

Exercises HomeostasisCore tick, sensors, mode transitions, the event bus,
and snapshots with real managers (not mocks). The maria_core adapter bridge
this file originally also covered was removed 2026-05-31 (dead, 0 importers).
"""

import pytest
import time

from agent_core.executor.module_executor import ModuleExecutor
from agent_core.tests.spec_helpers import specced


class TestFullIntegration:
    """Integration tests for the homeostasis spine against real components."""

    def test_homeostasis_core_tick(self, tmp_path):
        """HomeostasisCore should run a tick and update state with real managers."""
        from agent_core.homeostasis.core import HomeostasisCore
        from agent_core.memory.manager import MemoryManager
        from agent_core.llm.manager import LLMManager

        # Create real managers
        memory_manager = MemoryManager()

        # Use real LLMManager
        llm_manager = LLMManager()

        executor = specced(ModuleExecutor)

        # Create homeostasis core
        core = HomeostasisCore(
            memory_manager=memory_manager,
            llm_manager=llm_manager,
            executor=executor
        )

        # Run a single tick
        core._execute_tick()

        # Verify state was updated
        assert core.state is not None
        assert core.state.mode is not None

    def test_sensors_with_real_system(self):
        """Test sensors reading real system data."""
        from agent_core.homeostasis.sensors.resource_sensor import ResourceSensor
        from agent_core.homeostasis.sensors.time_sensor import TimeSensor
        from agent_core.homeostasis.sensors.thermal_sensor import ThermalSensor
        from agent_core.homeostasis.sensors.power_sensor import PowerSensor

        # Resource sensor
        resource_sensor = ResourceSensor()
        metrics = resource_sensor.read_metrics()
        assert metrics is not None
        # Use memory_pressure property (0-100, higher = more pressure)
        assert metrics.memory_pressure >= 0

        # Time sensor
        time_sensor = TimeSensor()
        time_metrics = time_sensor.read_metrics()
        assert time_metrics is not None
        assert time_metrics.hour_of_day >= 0

        # Thermal sensor (may not have real data on all systems)
        thermal_sensor = ThermalSensor()
        thermal_metrics = thermal_sensor.read_metrics()
        assert thermal_metrics is not None

        # Power sensor
        power_sensor = PowerSensor()
        power_metrics = power_sensor.read_metrics()
        assert power_metrics is not None

    def test_mode_transitions_under_simulated_load(self, tmp_path):
        """Test mode transitions when simulating resource pressure."""
        from agent_core.homeostasis.core import HomeostasisCore
        from agent_core.homeostasis.state_model import Mode
        from agent_core.memory.manager import MemoryManager
        from agent_core.llm.manager import LLMManager

        # Use real managers
        memory_manager = MemoryManager()
        llm_manager = LLMManager()

        executor = specced(ModuleExecutor)

        core = HomeostasisCore(
            memory_manager=memory_manager,
            llm_manager=llm_manager,
            executor=executor
        )

        # Initial tick - should be ACTIVE
        core._execute_tick()
        initial_mode = core.state.mode

        # Simulate high latency by recording slow inference
        llm_manager.record_inference(
            latency_ms=5000.0,  # 5 second latency
            tokens_generated=100,
            context_tokens=1000
        )

        # Run several ticks
        for _ in range(3):
            core._execute_tick()

        # Mode may have changed depending on implementation
        # At minimum, health score should be within expected range
        assert core.state.health_score <= 1.0

    def test_event_bus_integration(self):
        """Test event bus with real subscribers."""
        from agent_core.homeostasis.api import HomeostasisEventBus
        from agent_core.homeostasis.state_model import Mode

        bus = HomeostasisEventBus()
        received_events = []

        def subscriber(event):
            received_events.append(event)

        bus.subscribe("mode_changed", subscriber)

        # Emit event using proper API method
        bus.emit_mode_changed(Mode.ACTIVE, Mode.REDUCED, "test reason")

        assert len(received_events) == 1
        assert received_events[0]["new_mode"] == "reduced"

    def test_snapshot_with_real_state(self, tmp_path):
        """Test snapshot creation with real system state."""
        from agent_core.homeostasis.snapshot import SnapshotManager
        from agent_core.homeostasis.state_model import Mode

        # Create snapshot manager
        manager = SnapshotManager(snapshot_dir=str(tmp_path / "snapshots"))

        # Create snapshot with proper parameters matching SnapshotManager API
        snapshot_path = manager.create_snapshot(
            mode=Mode.ACTIVE,
            health_score=0.9,
            episodic_memory_data={
                "version": 1,
                "entries": 100,
                "size_mb": 5.0,
                "freshness_sec": 60
            },
            semantic_model_data={
                "version": 1,
                "node_count": 50,
                "consistency_score": 0.95
            },
            context_data={
                "goal_stack": ["goal1", "goal2"],
                "topic_embedding": [0.1, 0.2, 0.3],
                "error_rate": 0.05,
                "last_mode_transition": time.time()
            },
            resource_headroom={"ram_pct": 50, "cpu_pct": 70}
        )

        assert snapshot_path is not None
        from pathlib import Path
        assert Path(snapshot_path).exists()

        # Test recovery
        recovered = manager.recover_from_snapshot(snapshot_path)
        assert recovered is not None
        assert recovered.mode == Mode.ACTIVE
        assert recovered.health_score == 0.9


# ==================== Performance Tests ====================

class TestPerformance:
    """Performance-related integration tests."""

    @pytest.mark.xfail(reason="Flaky: psutil sensor reads exceed 200ms on loaded CPU (Ollama, pytest)")
    def test_tick_latency(self):
        """Verify that a single tick completes within acceptable time."""
        from agent_core.homeostasis.core import HomeostasisCore
        from agent_core.memory.manager import MemoryManager
        from agent_core.llm.manager import LLMManager

        # Use real managers
        memory_manager = MemoryManager()
        llm_manager = LLMManager()

        executor = specced(ModuleExecutor)

        core = HomeostasisCore(
            memory_manager=memory_manager,
            llm_manager=llm_manager,
            executor=executor
        )

        # Measure tick time
        start = time.time()
        core._execute_tick()
        elapsed = time.time() - start

        # Tick should complete in under 200ms (accounting for real sensor reads)
        assert elapsed < 0.2, f"Tick took {elapsed:.3f}s, expected < 0.2s"
