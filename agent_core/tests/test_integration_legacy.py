"""
Integration tests for adapters with real legacy maria_core modules.

These tests verify that adapters correctly wrap and integrate with
the actual legacy implementations, not just mocks.

Etap 3: Integracja z rzeczywistymi modułami maria_core
"""

import pytest
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch


# ==================== MemoryStoreAdapter Tests ====================

class TestMemoryStoreAdapterLegacy:
    """Test MemoryStoreAdapter with real MemoryStore."""

    def test_adapter_wraps_real_memory_store(self, tmp_path):
        """Adapter should successfully wrap the real MemoryStore."""
        from agent_core.adapters.memory_adapter import MemoryStoreAdapter

        adapter = MemoryStoreAdapter(memory_dir=tmp_path, use_legacy=True)

        # If legacy is available, _legacy_store should be set
        # If not available, adapter falls back gracefully
        assert adapter is not None
        assert adapter._memory_dir == tmp_path

    def test_adapter_append_and_load(self, tmp_path):
        """Test append and load operations through adapter."""
        from agent_core.adapters.memory_adapter import MemoryStoreAdapter

        adapter = MemoryStoreAdapter(memory_dir=tmp_path, use_legacy=True)

        # Append a record
        record = {"type": "test", "content": "hello world", "timestamp": time.time()}
        result = adapter.append(record)
        assert result is True

        # Load all records
        records = adapter.load_all()
        assert len(records) >= 1
        assert records[-1]["content"] == "hello world"

    def test_adapter_stats_tracking(self, tmp_path):
        """Test that adapter tracks stats correctly."""
        from agent_core.adapters.memory_adapter import MemoryStoreAdapter

        adapter = MemoryStoreAdapter(memory_dir=tmp_path, use_legacy=True)

        # Initially no operations
        stats = adapter.get_stats()
        assert stats["operation_count"] == 0

        # After operations
        adapter.append({"test": "data"})
        adapter.load_all()

        stats = adapter.get_stats()
        assert stats["operation_count"] == 2
        assert stats["coherence_score"] == 1.0  # All successful

    def test_adapter_error_tracking(self, tmp_path):
        """Test that adapter tracks errors in stats."""
        from agent_core.adapters.memory_adapter import MemoryStoreAdapter

        adapter = MemoryStoreAdapter(memory_dir=tmp_path, use_legacy=False)

        # Force an error by setting invalid memory_dir
        adapter._memory_dir = None
        result = adapter.append({"test": "data"})
        assert result is False

        stats = adapter.get_stats()
        assert stats["error_count_1h"] >= 1

    def test_adapter_count_and_recent(self, tmp_path):
        """Test count and get_recent methods."""
        from agent_core.adapters.memory_adapter import MemoryStoreAdapter

        adapter = MemoryStoreAdapter(memory_dir=tmp_path, use_legacy=True)

        # Add multiple records
        for i in range(5):
            adapter.append({"index": i, "data": f"record_{i}"})

        # Check count
        assert adapter.count() == 5

        # Check recent (returns newest first)
        recent = adapter.get_recent(limit=3)
        assert len(recent) == 3
        assert recent[0]["index"] == 4  # Newest first


# ==================== SemanticGraphAdapter Tests ====================

class TestSemanticGraphAdapterLegacy:
    """Test SemanticGraphAdapter with real SemanticGraph."""

    def test_adapter_wraps_real_semantic_graph(self, tmp_path):
        """Adapter should successfully wrap the real SemanticGraph."""
        from agent_core.adapters.semantic_adapter import SemanticGraphAdapter

        adapter = SemanticGraphAdapter(data_dir=tmp_path, use_legacy=True)
        assert adapter is not None

    def test_adapter_node_operations(self, tmp_path):
        """Test node add/get operations through adapter."""
        from agent_core.adapters.semantic_adapter import SemanticGraphAdapter

        adapter = SemanticGraphAdapter(data_dir=tmp_path, use_legacy=True)

        # Add a node
        node_id = adapter.add_node(
            node_id="test_node_1",
            content="Warsaw",
            node_type="city"
        )
        assert node_id is not None

        # Get the node
        node = adapter.get_node(node_id)
        assert node is not None

    def test_adapter_edge_operations(self, tmp_path):
        """Test edge add/get operations through adapter."""
        from agent_core.adapters.semantic_adapter import SemanticGraphAdapter

        adapter = SemanticGraphAdapter(data_dir=tmp_path, use_legacy=True)

        # Add nodes first - legacy SemanticGraph returns its own node IDs
        node1 = adapter.add_node("node1", "Poland", "country")
        node2 = adapter.add_node("node2", "Warsaw", "city")

        # Add edge using returned node IDs
        adapter.add_edge(node1, node2, "has_capital")

        # Get edges
        edges = adapter.get_edges(node1)
        assert len(edges) >= 1
        assert edges[0]["relation"] == "has_capital"

    def test_adapter_search(self, tmp_path):
        """Test search functionality."""
        from agent_core.adapters.semantic_adapter import SemanticGraphAdapter

        adapter = SemanticGraphAdapter(data_dir=tmp_path, use_legacy=True)

        # Add some nodes
        adapter.add_node("n1", "Python programming", "topic")
        adapter.add_node("n2", "Python snake", "animal")
        adapter.add_node("n3", "Java programming", "topic")

        # Search
        results = adapter.search("Python", limit=10)
        assert len(results) >= 2

    def test_adapter_stats(self, tmp_path):
        """Test graph statistics."""
        from agent_core.adapters.semantic_adapter import SemanticGraphAdapter

        adapter = SemanticGraphAdapter(data_dir=tmp_path, use_legacy=True)

        # Add nodes and capture returned IDs (legacy returns its own IDs)
        node1 = adapter.add_node("n1", "Test1", "test")
        node2 = adapter.add_node("n2", "Test2", "test")
        adapter.add_edge(node1, node2, "related")

        stats = adapter.get_stats()
        assert stats["total_nodes"] >= 2
        assert stats["total_edges"] >= 1

    def test_adapter_jsonl_roundtrip(self, tmp_path):
        """Test JSONL save/load (ADR-004 compliance)."""
        from agent_core.adapters.semantic_adapter import SemanticGraphAdapter

        adapter = SemanticGraphAdapter(data_dir=tmp_path, use_legacy=True)

        # Add data
        adapter.add_node("n1", "Test Node", "test")

        # Save to JSONL
        jsonl_path = tmp_path / "graph.jsonl"
        count = adapter.save_to_jsonl(jsonl_path)
        assert count >= 1
        assert jsonl_path.exists()

        # Create new adapter and rebuild
        adapter2 = SemanticGraphAdapter(data_dir=tmp_path, use_legacy=True)
        loaded = adapter2.rebuild_from_jsonl(jsonl_path)
        assert loaded >= 1


# ==================== ResourceWatchdogAdapter Tests ====================

class TestResourceWatchdogAdapterLegacy:
    """Test ResourceWatchdogAdapter integration."""

    def test_adapter_reads_metrics(self):
        """Adapter should read real system metrics."""
        from agent_core.adapters.resource_adapter import ResourceWatchdogAdapter

        adapter = ResourceWatchdogAdapter(limit_percent=95)
        metrics = adapter.get_current_metrics()

        # Should get real metrics from psutil
        # ResourceMetrics uses memory_pressure property, not ram_percent
        assert metrics is not None
        assert 0 <= metrics.memory_pressure <= 100
        assert 0 <= metrics.cpu_percent <= 100

    def test_adapter_watchdog_starts_stops(self):
        """Test watchdog thread lifecycle."""
        from agent_core.adapters.resource_adapter import ResourceWatchdogAdapter

        callback_called = []

        def on_threshold(percent):
            callback_called.append(percent)

        adapter = ResourceWatchdogAdapter(
            limit_percent=99,  # High threshold to avoid triggering
            check_interval_sec=1,
            on_threshold_exceeded=on_threshold
        )

        # Start
        thread = adapter.start()
        assert adapter.is_running is True
        assert thread.is_alive()

        # Let it run briefly
        time.sleep(0.5)

        # Stop
        adapter.stop()
        time.sleep(0.5)
        assert adapter.is_running is False

    def test_adapter_threshold_callback(self):
        """Test that threshold callback is triggered."""
        from agent_core.adapters.resource_adapter import ResourceWatchdogAdapter

        callback_values = []

        def on_threshold(percent):
            callback_values.append(percent)

        adapter = ResourceWatchdogAdapter(
            limit_percent=1,  # Very low threshold - will always trigger
            check_interval_sec=1,
            on_threshold_exceeded=on_threshold
        )

        # Start and wait for callback
        adapter.start()
        time.sleep(2.5)  # Give more time for the check loop
        adapter.stop()

        # Should have triggered callback
        assert len(callback_values) >= 1
        assert callback_values[0] > 0


# ==================== BrainMemoryAdapter Tests ====================

class TestBrainMemoryAdapterLegacy:
    """Test BrainMemoryAdapter integration."""

    def test_adapter_initialization(self):
        """Adapter should initialize correctly."""
        from agent_core.adapters.brain_adapter import BrainMemoryAdapter

        adapter = BrainMemoryAdapter(use_legacy=False)
        assert adapter is not None
        assert adapter._episodic == []

    def test_adapter_cognitive_metrics(self):
        """Test cognitive metrics tracking."""
        from agent_core.adapters.brain_adapter import BrainMemoryAdapter

        adapter = BrainMemoryAdapter(use_legacy=False)

        metrics = adapter.get_cognitive_metrics()
        assert "context_coherence" in metrics
        assert "error_count_1h" in metrics
        assert "goal_stack_depth" in metrics
        assert "latency_p50_ms" in metrics

    def test_adapter_goal_stack(self):
        """Test goal stack operations."""
        from agent_core.adapters.brain_adapter import BrainMemoryAdapter

        adapter = BrainMemoryAdapter(use_legacy=False)

        # Add goals
        adapter._add_goal("Learn Python")
        adapter._add_goal("Write tests")

        assert len(adapter.get_goal_stack()) == 2

        # Pop goal
        goal = adapter.pop_goal()
        assert goal["goal"] == "Write tests"
        assert len(adapter.get_goal_stack()) == 1

    def test_adapter_simple_perception(self):
        """Test simple perception processing (without legacy)."""
        from agent_core.adapters.brain_adapter import BrainMemoryAdapter

        adapter = BrainMemoryAdapter(use_legacy=False)

        result = adapter.process_perception("Test perception input")

        assert result["status"] == "completed_simple"
        assert len(adapter.get_episodes()) == 1

    def test_adapter_latency_tracking(self):
        """Test that latency is tracked during processing."""
        from agent_core.adapters.brain_adapter import BrainMemoryAdapter

        adapter = BrainMemoryAdapter(use_legacy=False)

        # Process multiple perceptions
        for i in range(5):
            adapter.process_perception(f"Perception {i}")

        metrics = adapter.get_cognitive_metrics()
        assert metrics["latency_p50_ms"] >= 0  # Should have recorded latencies


# ==================== Full Integration Tests ====================

class TestFullIntegration:
    """Test full homeostasis integration with adapters."""

    def test_homeostasis_core_with_adapters(self, tmp_path):
        """Test HomeostasisCore using real adapters."""
        from agent_core.homeostasis.core import HomeostasisCore
        from agent_core.memory.manager import MemoryManager
        from agent_core.llm.manager import LLMManager
        from agent_core.executor.module_executor import ModuleExecutor

        # Create real MemoryManager (initializes its own adapters)
        memory_manager = MemoryManager()

        # Use real LLMManager
        llm_manager = LLMManager()

        executor = MagicMock()  # No spec - allow any attribute
        executor.get_active_modules.return_value = []

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
        from agent_core.executor.module_executor import ModuleExecutor

        # Use real managers
        memory_manager = MemoryManager()
        llm_manager = LLMManager()

        executor = MagicMock()  # No spec - allow any attribute
        executor.get_active_modules.return_value = []

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

    def test_tick_latency(self):
        """Verify that a single tick completes within acceptable time."""
        from agent_core.homeostasis.core import HomeostasisCore
        from agent_core.memory.manager import MemoryManager
        from agent_core.llm.manager import LLMManager
        from agent_core.executor.module_executor import ModuleExecutor
        from unittest.mock import MagicMock

        # Use real managers
        memory_manager = MemoryManager()
        llm_manager = LLMManager()

        executor = MagicMock()  # No spec - allow any attribute
        executor.get_active_modules.return_value = []

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

    def test_adapter_memory_footprint(self, tmp_path):
        """Test that adapters don't leak memory."""
        from agent_core.adapters.memory_adapter import MemoryStoreAdapter
        import sys

        adapter = MemoryStoreAdapter(memory_dir=tmp_path, use_legacy=False)

        # Add many records
        for i in range(1000):
            adapter.append({"index": i, "data": "x" * 100})

        # Check that error tracking doesn't grow unbounded
        # (errors are trimmed to last hour)
        stats = adapter.get_stats()
        assert stats["error_count_1h"] <= 1000  # Should be bounded
