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


@pytest.fixture(autouse=True)
def isolated_reasoning_journal(tmp_path):
    """Prevent tests from writing to production reasoning_journal.jsonl.

    The capture hooks (creative safe_llm_call, K12 analyze, teacher nim_gap)
    reach the journal via the module singleton; any test driving those paths
    with a stub LLM would otherwise append to the live notebook."""
    from agent_core.tracing import reasoning_journal as rj

    rj.set_reasoning_journal(
        rj.ReasoningJournal(tmp_path / "test_reasoning_journal.jsonl")
    )
    yield
    rj.set_reasoning_journal(None)


@pytest.fixture(autouse=True)
def always_learning_window(monkeypatch):
    """Make is_learning_window() always return True in tests.

    Without this, tests that exercise learn/exam/fetch actions
    would fail depending on the time of day they run."""
    try:
        import agent_core.environment.environment_model as env_mod
        monkeypatch.setattr(env_mod, "is_learning_window", lambda now=None: True)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def neutralize_armed_env_flags(monkeypatch):
    """Tests must assert the CODE default, not whatever the operator has armed in
    the live .env. load_dotenv() (via maria_core.sys.config, pulled in
    transitively by e.g. models.ollama_brain) leaks armed flags such as
    FS_WRITE_ENABLED into os.environ at import time, so a fragile test that reads
    the flag without delenv sees the operator's live arming and fails depending
    on collection order. Clear the behaviour flags here; a test that genuinely
    wants one ON still does monkeypatch.setenv (which runs after this and wins)."""
    for _flag in (
        "FS_WRITE_ENABLED", "LEARNING_NOTES_ENABLED", "TELEGRAM_CHAT_ENABLED",
        "PLAY_ENABLED",
        # Etap B (sub-goal trees + deadlines): operator toggles read live from
        # os.environ -> leak through load_dotenv exactly like the flags above.
        "GOAL_ROLLUP_ENABLED", "GOAL_DEADLINE_ENABLED", "GOAL_DEADLINE_REAP_ENABLED",
        # Etap A (effector undo): journal + execute toggles, same leak story.
        "EFFECTOR_UNDO_JOURNAL_ENABLED", "EFFECTOR_UNDO_EXECUTE_ENABLED",
        # Later arming (06-25..06-28): undo-suggest (observe-first), hydration
        # nudge, Super-META situational self, self-dev bridge -- all read live
        # from os.environ and leak through load_dotenv exactly like the above.
        "EFFECTOR_UNDO_SUGGEST_ENABLED", "HYDRATION_NUDGE_ENABLED",
        "SELF_CONTEXT_CHAT_ENABLED", "VISION_SUPPRESS_WHEN_PRESENT",
        "PROACTIVE_SITUATIONAL", "SELF_DEV_BRIDGE_ENABLED",
    ):
        monkeypatch.delenv(_flag, raising=False)

