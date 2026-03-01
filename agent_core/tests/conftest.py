"""
Pytest configuration and shared fixtures.

Provides common test fixtures for homeostasis testing.
"""

import pytest
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture
def temp_data_dir():
    """Create temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_memory_manager():
    """Create mock memory manager."""
    manager = Mock()
    manager.get_stats.return_value = {
        'coherence_score': 0.95,
        'error_count_1h': 0,
        'total_memories': 100,
        'goal_stack_depth': 2,
    }
    manager.flush = Mock()
    return manager


@pytest.fixture
def mock_llm_manager():
    """Create mock LLM manager."""
    manager = Mock()
    manager.get_latency_percentiles.return_value = {
        'p50': 100,
        'p95': 300,
        'p99': 600,
    }
    manager.is_available.return_value = True
    return manager


@pytest.fixture
def mock_meta_controller():
    """Create mock meta-controller."""
    controller = Mock()
    controller.get_goal_stack.return_value = [
        {'goal': 'learn', 'priority': 1},
        {'goal': 'respond', 'priority': 2},
    ]
    controller.receive_signal = Mock()
    return controller


@pytest.fixture
def healthy_interpreted_state():
    """Create healthy interpreted state dictionary."""
    return {
        'ram_available_pct': 60,
        'cpu_load': 30,
        'disk_free_pct': 40,
        'temp_c': 55,
        'context_coherence': 0.95,
        'error_count_1h': 0,
        'goal_stack_depth': 2,
        'contradiction_count': 0,
        'task_completion_ratio': 0.9,
        'idle_seconds': 10,
        'is_night': False,
        'stable_ticks': 100,
    }


@pytest.fixture
def critical_interpreted_state():
    """Create critical interpreted state dictionary."""
    return {
        'ram_available_pct': 5,  # CRITICAL
        'cpu_load': 95,
        'disk_free_pct': 1,  # CRITICAL
        'temp_c': 90,  # CRITICAL
        'context_coherence': 0.3,  # ALERT
        'error_count_1h': 50,  # ALERT
        'goal_stack_depth': 20,  # WARNING - runaway
        'contradiction_count': 10,
        'task_completion_ratio': 0.2,
        'idle_seconds': 0,
        'is_night': False,
        'stable_ticks': 0,
    }


@pytest.fixture
def warning_interpreted_state():
    """Create warning-level interpreted state dictionary."""
    return {
        'ram_available_pct': 25,  # WARNING
        'cpu_load': 75,  # WARNING
        'disk_free_pct': 8,  # WARNING
        'temp_c': 72,  # WARNING
        'context_coherence': 0.8,
        'error_count_1h': 5,
        'goal_stack_depth': 8,  # Close to runaway
        'contradiction_count': 2,
        'task_completion_ratio': 0.7,
        'idle_seconds': 300,
        'is_night': False,
        'stable_ticks': 30,
    }


# Markers for test categories
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests"
    )


# Test timing helper
@pytest.fixture
def timer():
    """Simple timer for performance tests."""
    class Timer:
        def __init__(self):
            self.start_time = None
            self.end_time = None

        def start(self):
            self.start_time = time.time()
            return self

        def stop(self):
            self.end_time = time.time()
            return self

        @property
        def elapsed(self):
            if self.start_time and self.end_time:
                return self.end_time - self.start_time
            return None

    return Timer()


@pytest.fixture(autouse=True)
def isolated_event_logger(tmp_path):
    """Prevent tests from writing to production homeostasis_events.jsonl."""
    import agent_core.homeostasis.event_logger as logger_module

    original = logger_module._event_logger
    logger_module._event_logger = logger_module.HomeostasisEventLogger(
        log_path=tmp_path / "test_events.jsonl"
    )
    yield logger_module._event_logger
    logger_module._event_logger = original

