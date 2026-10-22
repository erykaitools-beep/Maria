"""
Pytest configuration and shared fixtures.

Provides common test fixtures for homeostasis testing.
"""

import builtins
import io
import os
import pytest
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture(autouse=True)
def isolated_local_compute_coordinator():
    """Keep the process-wide thermal/compute latch from leaking across tests."""
    from agent_core.llm.local_compute import get_local_compute_coordinator

    coordinator = get_local_compute_coordinator()
    coordinator.reset_for_tests()
    coordinator.observe_temperature(50.0)
    yield coordinator
    coordinator.enter_cooling()
    deadline = time.monotonic() + 1.0
    while coordinator.snapshot()["active_kind"] and time.monotonic() < deadline:
        time.sleep(0.01)
    coordinator.reset_for_tests()


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
        # Runtime-profile defaults must not depend on the installed .env.
        # Tests of lean mode explicitly select it through monkeypatch.
        "MARIA_RUNTIME_PROFILE", "MARIA_MARKET_INTEGRATION",
        "MARIA_ROLE_KEEP_ALIVE", "MARIA_EMBEDDING_KEEP_ALIVE",
        "MARIA_VISION_KEEP_ALIVE", "VISION_CHANGE_BACKEND",
        "MARIA_CHAT_BACKEND", "MARIA_BACKGROUND_REASONING", "MARIA_CODEX_MODEL",
    ):
        monkeypatch.delenv(_flag, raising=False)


@pytest.fixture(autouse=True)
def sandbox_cwd(tmp_path_factory, request):
    """Run every test from a throwaway working directory.

    agent_core reaches its data through RELATIVE defaults -- Path("meta_data/..."),
    LOG_DIR = "logs" -- and a relative Path resolves at open() time, against the
    process cwd. pytest runs from the repo root, so those defaults pointed at the
    LIVE data directories and tests wrote straight into production.

    Measured 2026-07-26 with a probe hooking every write-mode open (full suite,
    7242 tests): 23 production files touched, worst of them
    meta_data/warm_recovery.json at 62 writes -- the crash-recovery state the
    daemon reads on boot. This fixture removed 9 of the 14 offending paths at a
    cost of ONE failing test (conversation_logger created its dir at import
    time; fixed at the source rather than papered over here).

    What it CANNOT reach: paths built from a module's own location, e.g.
    Path(__file__).resolve().parents[2] / "input" in the ask_expert save path.
    Those have no injection point at all and are handled per-caller.

    Deliberately NOT chdir'ing back to the repo root for reads: nothing in the
    suite reads fixtures by a path relative to cwd (proved by the same run), and
    sys.path is absolute (set at the top of this file), so imports are unaffected.
    """
    sandbox = tmp_path_factory.mktemp("cwd")
    original = os.getcwd()
    os.chdir(sandbox)
    try:
        yield sandbox
    finally:
        os.chdir(original)


@pytest.fixture(scope="session")
def _data_sandbox(tmp_path_factory):
    """One throwaway meta_data/ + input/ pair for the whole test session."""
    root = tmp_path_factory.mktemp("data_sandbox")
    (root / "meta_data").mkdir()
    (root / "input").mkdir()
    return root


@pytest.fixture(autouse=True)
def redirect_module_level_data_paths(monkeypatch, _data_sandbox):
    """Point module-level ABSOLUTE data paths at a sandbox.

    sandbox_cwd above handles everything reached by a relative default. What it
    cannot reach is the other idiom in this codebase:

        _DEFAULT_PATH = Path(__file__).resolve().parents[2] / "meta_data" / "..."

    -- an absolute path derived from the module's OWN location, so cwd is
    irrelevant and the only way out is to patch the constant. Between them the
    two fixtures close all 23 production files the write-probe found on
    2026-07-26.

    Every constant below was measured as actually written by the suite, not
    added defensively. The worst was the expert corpus: input/expert_fizyka.txt
    at 226 appends / 103 KB, ~40% of its blocks test payloads, against 214 of
    the other 217 expert files sitting at exactly one append.
    """
    meta = _data_sandbox / "meta_data"
    inp = _data_sandbox / "input"

    from agent_core.bulletin import bulletin_store
    from agent_core.routing import handlers
    from agent_core.telegram import notifier, outbox_store
    from agent_core.web_source import content_writer, fetch_registry
    from maria_core.sys import config as maria_config

    # web_dead_topics / web_exhausted_topics are derived from the registry path
    # via with_name(), so redirecting the registry covers all three.
    monkeypatch.setattr(fetch_registry, "_META_DIR", meta)
    monkeypatch.setattr(
        fetch_registry, "_DEFAULT_REGISTRY_PATH", meta / "web_fetch_registry.jsonl"
    )
    monkeypatch.setattr(
        bulletin_store, "_DEFAULT_PATH", meta / "cognitive_bulletin.jsonl"
    )
    monkeypatch.setattr(
        notifier, "_STARTUP_NOTIFY_FILE", meta / "last_startup_notify.txt"
    )
    monkeypatch.setattr(handlers, "EXPERT_INPUT_DIR", inp)
    monkeypatch.setattr(
        outbox_store, "DEFAULT_OUTBOX_PATH", meta / "telegram_outbox.jsonl"
    )
    monkeypatch.setattr(content_writer, "_DEFAULT_INPUT_DIR", inp)
    # Read lazily inside homeostasis_module (IntrospectionScheduler writes
    # meta_data/code_self_model.json under it). INPUT_DIR/MEMORY_DIR and friends
    # are computed from BASE_DIR at IMPORT time, so this rebind does not disturb
    # them -- it only reaches code that consults BASE_DIR at call time.
    monkeypatch.setattr(maria_config, "BASE_DIR", _data_sandbox)


@pytest.fixture(scope="session")
def _fetch_decision_sink(tmp_path_factory):
    """One throwaway file for every fetch-decision record written under pytest."""
    return tmp_path_factory.mktemp("fetch_decisions") / "fetch_decisions.jsonl"


@pytest.fixture(autouse=True)
def redirect_fetch_decision_log(monkeypatch, _fetch_decision_sink):
    """Keep pytest out of the LIVE meta_data/fetch_decisions.jsonl.

    The mirror image of neutralize_armed_env_flags above: that one stops
    production leaking INTO tests, this one stops tests leaking INTO production.

    log_fetch_decision() defaults to Path("meta_data/fetch_decisions.jsonl") --
    a RELATIVE path, and pytest runs from the repo root, so every test that
    exercised a fetch path appended a record to the live audit log. Measured
    2026-07-26: 1586 of 3993 records (40%), spread over 46 days, were written by
    test runs. That is not cosmetic bookkeeping -- it is the file post-hoc
    analysis uses to answer "who triggered this fetch and why", and K12
    self_analysis reads the same behaviour to raise bulletins about fetch
    quality. It raised one ("fetch success rate 0.56") off a set that was two
    fifths invented.

    Redirect rather than assert-and-fail: the ~13 tests that hit this path do
    not care where the bytes land, and a guard that RAISED would be swallowed
    anyway -- log_fetch_decision wraps its write in `except Exception:
    logger.debug(...)`, so the write is best-effort by design and a raising
    guard would be invisible exactly where the damage happens.
    """
    from agent_core.web_source import decision_log

    monkeypatch.setattr(decision_log, "DEFAULT_LOG_PATH", _fetch_decision_sink)



# --- Ratchet: nothing in this suite may write into the live project data -----

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PRODUCTION_DIRS = tuple(
    (_PROJECT_ROOT / name).resolve()
    for name in ("meta_data", "memory", "input", "output", "processed", "logs")
)
_WRITE_MODES = ("w", "a", "+", "x")


def _production_target(path):
    """Resolved path if it lands in a live project data dir, else None."""
    try:
        resolved = Path(path).resolve()
    except (OSError, ValueError, TypeError):
        return None
    for guarded in _PRODUCTION_DIRS:
        try:
            resolved.relative_to(guarded)
            return resolved
        except ValueError:
            continue
    return None


@pytest.fixture(autouse=True)
def no_production_data_writes(
    monkeypatch,
    sandbox_cwd,
    redirect_module_level_data_paths,
    redirect_fetch_decision_log,
):
    """Fail any test that writes into the live project data directories.

    The three fixtures above are requested by name so this arms LAST, after the
    redirects are in place.

    Records violations and fails at TEARDOWN instead of raising at the write.
    Raising is useless here: the writers that caused this are best-effort by
    design (log_fetch_decision wraps its write in `except Exception:
    logger.debug(...)`, ContentWriter and the bulletin store swallow OSError),
    so a guard that raises is caught and discarded exactly where the damage
    happens, and the test still goes green. Recording survives the swallow.

    History (2026-07-26): a probe over the full suite found 23 production files
    written by tests -- meta_data/fetch_decisions.jsonl was 40% test rows across
    46 days, meta_data/warm_recovery.json took 62 writes, and
    input/expert_fizyka.txt had grown to 226 appends / 103 KB of which ~40% were
    test payloads, sitting in the corpus Maria learns from. None of it was
    visible: every one of those writes is best-effort and silent. This is the
    anti-regrowth ratchet, in the spirit of test_mock_hygiene_audit.py -- there
    is deliberately NO allowlist, because the measured count is now zero and the
    only honest baseline for "tests must not touch production data" is zero.
    """
    violations = []
    real_open, real_os_open, real_path_open = builtins.open, os.open, Path.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(m in mode for m in _WRITE_MODES):
            hit = _production_target(file)
            if hit is not None:
                violations.append(str(hit))
        return real_open(file, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND):
            hit = _production_target(path)
            if hit is not None:
                violations.append(str(hit))
        return real_os_open(path, flags, *args, **kwargs)

    def guarded_path_open(self, mode="r", *args, **kwargs):
        if any(m in mode for m in _WRITE_MODES):
            hit = _production_target(self)
            if hit is not None:
                violations.append(str(hit))
        return real_path_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)
    monkeypatch.setattr(os, "open", guarded_os_open)
    monkeypatch.setattr(Path, "open", guarded_path_open)

    yield

    monkeypatch.undo()
    if violations:
        unique = sorted(set(violations))
        pytest.fail(
            "Test pisal do ZYWYCH danych projektu (%d zapisow, %d plikow):\n  %s\n\n"
            "Przekaz sciezke tymczasowa (tmp_path) zamiast polegac na domyslnej, "
            "albo -- jesli domyslna jest stala modulowa -- przekieruj ja w "
            "redirect_module_level_data_paths w tym pliku."
            % (len(violations), len(unique), "\n  ".join(unique)),
            pytrace=False,
        )
