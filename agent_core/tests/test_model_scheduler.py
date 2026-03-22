"""
Tests for Model Registry, Model Scheduler, and Routing Rules.

All Ollama and psutil calls are mocked - zero external dependencies.
"""

import json
import time
import threading
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

from agent_core.llm.model_registry import (
    ModelRole, ModelSpec, ConcurrencyClass, WarmState,
    get_model, list_models, get_warm_models, get_heavy_models,
    get_local_models, is_triage_configured, set_triage_model,
    RAM_EMERGENCY_FREE, LATENCY_UNHEALTHY_COUNT,
    _REGISTRY,
)
from agent_core.llm.model_scheduler import (
    ModelScheduler, LoadedModel, EnsureResult,
)
from agent_core.llm.routing_rules import (
    TaskType, route_task, heuristic_classify,
)


# ============================================================
# MODEL REGISTRY TESTS
# ============================================================

class TestModelRegistry:
    """Tests for model_registry.py."""

    def test_get_model_planner(self):
        spec = get_model(ModelRole.PLANNER)
        assert spec is not None
        assert spec.role == ModelRole.PLANNER
        assert spec.ollama_tag == "qwen3:8b"
        assert spec.ram_estimate_gb == 5.5
        assert spec.concurrency_class == ConcurrencyClass.HEAVY

    def test_get_model_executor(self):
        spec = get_model(ModelRole.EXECUTOR)
        assert spec is not None
        assert spec.ollama_tag == "llama3.1:8b"
        assert spec.warm_state == WarmState.WARM
        assert spec.idle_unload_s == 0.0  # keep warm

    def test_get_model_coder(self):
        spec = get_model(ModelRole.CODER)
        assert spec is not None
        assert spec.concurrency_class == ConcurrencyClass.HEAVY
        assert spec.block_if_heavy_active is True
        assert spec.fallback_role == ModelRole.EXECUTOR

    def test_get_model_triage_rule_based(self):
        spec = get_model(ModelRole.TRIAGE)
        assert spec is not None
        assert spec.ollama_tag == ""  # rule-based, no LLM
        assert spec.ram_estimate_gb == 0.0

    def test_get_model_memory_shared(self):
        spec = get_model(ModelRole.MEMORY)
        assert spec is not None
        assert spec.ram_estimate_gb == 0.0  # shared on EXECUTOR
        assert spec.ollama_tag == "llama3.1:8b"

    def test_get_model_external(self):
        spec = get_model(ModelRole.EXTERNAL)
        assert spec is not None
        assert spec.warm_state == WarmState.EXTERNAL
        assert spec.ram_estimate_gb == 0.0

    def test_list_models_returns_all(self):
        models = list_models()
        assert len(models) == 6
        roles = {m.role for m in models}
        assert roles == {
            ModelRole.PLANNER, ModelRole.EXECUTOR, ModelRole.CODER,
            ModelRole.TRIAGE, ModelRole.MEMORY, ModelRole.EXTERNAL,
        }

    def test_get_warm_models(self):
        warm = get_warm_models()
        roles = {m.role for m in warm}
        # EXECUTOR is warm, TRIAGE is rule-based (no ollama_tag)
        assert ModelRole.EXECUTOR in roles

    def test_get_heavy_models(self):
        heavy = get_heavy_models()
        roles = {m.role for m in heavy}
        assert roles == {ModelRole.PLANNER, ModelRole.CODER}

    def test_get_local_models(self):
        local = get_local_models()
        roles = {m.role for m in local}
        assert ModelRole.EXTERNAL not in roles
        assert ModelRole.TRIAGE not in roles  # rule-based, no ollama_tag
        assert ModelRole.EXECUTOR in roles

    def test_is_triage_configured_true(self):
        assert is_triage_configured() is True  # rule-based always available

    def test_set_triage_model(self):
        # Save original
        original = _REGISTRY[ModelRole.TRIAGE]
        try:
            set_triage_model("qwen2.5:3b", 2.5)
            spec = get_model(ModelRole.TRIAGE)
            assert spec.ollama_tag == "qwen2.5:3b"
            assert spec.ram_estimate_gb == 2.5
            assert spec.latency_budget_s == 3.0
            assert is_triage_configured() is True
        finally:
            # Restore
            _REGISTRY[ModelRole.TRIAGE] = original

    def test_model_spec_frozen(self):
        spec = get_model(ModelRole.EXECUTOR)
        with pytest.raises(AttributeError):
            spec.ollama_tag = "something_else"

    def test_latency_budgets(self):
        """Verify latency budgets match MODEL_REGISTRY.md."""
        assert get_model(ModelRole.TRIAGE).latency_budget_s == 0.001  # rule-based
        assert get_model(ModelRole.EXECUTOR).latency_budget_s == 20.0
        assert get_model(ModelRole.CODER).latency_budget_s == 30.0
        assert get_model(ModelRole.PLANNER).latency_budget_s == 60.0
        assert get_model(ModelRole.MEMORY).latency_budget_s == 15.0

    def test_idle_unload_times(self):
        """Verify idle unload times."""
        assert get_model(ModelRole.EXECUTOR).idle_unload_s == 0.0
        assert get_model(ModelRole.PLANNER).idle_unload_s == 300.0
        assert get_model(ModelRole.CODER).idle_unload_s == 300.0


# ============================================================
# MODEL SCHEDULER TESTS
# ============================================================

@pytest.fixture
def scheduler(tmp_path):
    """Create a ModelScheduler with temp health path."""
    return ModelScheduler(health_path=str(tmp_path / "model_health.json"))


@pytest.fixture
def mock_psutil():
    """Mock psutil.virtual_memory to return controllable RAM."""
    with patch("agent_core.llm.model_scheduler.psutil") as mock:
        mem = Mock()
        mem.available = 20 * (1024 ** 3)  # 20 GB free
        mock.virtual_memory.return_value = mem
        yield mock


@pytest.fixture
def mock_ollama():
    """Mock ollama library."""
    with patch("agent_core.llm.model_scheduler.ollama_lib") as mock:
        mock.generate.return_value = {"response": ""}
        mock.ps.return_value = {"models": []}
        yield mock


class TestModelSchedulerEnsureReady:
    """Tests for ensure_ready()."""

    def test_already_loaded(self, scheduler, mock_psutil, mock_ollama):
        """If model already loaded and healthy, return immediately."""
        scheduler.register_running_model(ModelRole.EXECUTOR, "llama3.1:8b")
        result = scheduler.ensure_ready(ModelRole.EXECUTOR)
        assert result.success is True
        assert result.ollama_tag == "llama3.1:8b"
        assert result.fallback_used is False
        mock_ollama.generate.assert_not_called()

    def test_load_cold_model(self, scheduler, mock_psutil, mock_ollama):
        """Cold model should be loaded via Ollama."""
        result = scheduler.ensure_ready(ModelRole.PLANNER)
        assert result.success is True
        assert result.ollama_tag == "qwen3:8b"
        mock_ollama.generate.assert_called_once()

    def test_external_model_always_ready(self, scheduler, mock_psutil, mock_ollama):
        """External (NIM) model should always return success."""
        result = scheduler.ensure_ready(ModelRole.EXTERNAL)
        assert result.success is True
        assert result.reason == "External model (NIM)"
        mock_ollama.generate.assert_not_called()

    def test_triage_rule_based_no_load(self, scheduler, mock_psutil, mock_ollama):
        """Triage is rule-based (no ollama_tag) - always ready, no model needed."""
        result = scheduler.ensure_ready(ModelRole.TRIAGE)
        assert result.success is True
        assert result.fallback_used is False
        assert result.role == ModelRole.TRIAGE
        assert "Rule-based" in result.reason
        mock_ollama.generate.assert_not_called()

    def test_insufficient_ram_fallback(self, scheduler, mock_psutil, mock_ollama):
        """If not enough RAM, should try fallback."""
        # Set free RAM to only 5 GB
        mock_psutil.virtual_memory.return_value.available = 5 * (1024 ** 3)
        scheduler.register_running_model(ModelRole.EXECUTOR, "llama3.1:8b")

        result = scheduler.ensure_ready(ModelRole.PLANNER)
        # PLANNER needs 12 GB free, only 5 available -> fallback to EXECUTOR
        assert result.success is True
        assert result.fallback_used is True
        assert result.role == ModelRole.EXECUTOR

    def test_load_failure_fallback(self, scheduler, mock_psutil, mock_ollama):
        """If Ollama load fails, should try fallback."""
        mock_ollama.generate.side_effect = Exception("Connection refused")
        scheduler.register_running_model(ModelRole.EXECUTOR, "llama3.1:8b")

        result = scheduler.ensure_ready(ModelRole.PLANNER)
        assert result.success is True
        assert result.fallback_used is True
        assert result.role == ModelRole.EXECUTOR

    def test_heavy_mutex_blocks(self, scheduler, mock_psutil, mock_ollama):
        """Loading CODER while PLANNER holds mutex should fallback."""
        # Simulate PLANNER holding the heavy lock
        scheduler._heavy_lock.acquire()
        scheduler.register_running_model(ModelRole.EXECUTOR, "llama3.1:8b")

        # CODER should timeout quickly and fallback
        result = scheduler.ensure_ready(ModelRole.CODER, timeout_s=0.1)
        assert result.success is True
        assert result.fallback_used is True
        assert result.role == ModelRole.EXECUTOR

        scheduler._heavy_lock.release()


class TestModelSchedulerRelease:
    """Tests for release()."""

    def test_release_updates_last_used(self, scheduler, mock_psutil, mock_ollama):
        scheduler.register_running_model(ModelRole.EXECUTOR, "llama3.1:8b")
        time.sleep(0.01)
        scheduler.release(ModelRole.EXECUTOR)
        loaded = scheduler._loaded[ModelRole.EXECUTOR]
        assert loaded.last_used > loaded.loaded_at

    def test_release_heavy_releases_mutex(self, scheduler, mock_psutil, mock_ollama):
        """Release on a heavy model should release heavy mutex."""
        scheduler._heavy_lock.acquire()
        scheduler.register_running_model(ModelRole.PLANNER, "qwen3:8b")
        scheduler.release(ModelRole.PLANNER)
        # Mutex should be released - we should be able to acquire it
        acquired = scheduler._heavy_lock.acquire(timeout=0.1)
        assert acquired is True
        scheduler._heavy_lock.release()


class TestModelSchedulerForceUnload:
    """Tests for force_unload()."""

    def test_force_unload_removes_model(self, scheduler, mock_psutil, mock_ollama):
        scheduler.register_running_model(ModelRole.PLANNER, "qwen3:8b")
        assert ModelRole.PLANNER in scheduler._loaded

        result = scheduler.force_unload(ModelRole.PLANNER)
        assert result is True
        assert ModelRole.PLANNER not in scheduler._loaded
        mock_ollama.generate.assert_called_once()

    def test_force_unload_nonexistent(self, scheduler, mock_psutil, mock_ollama):
        result = scheduler.force_unload(ModelRole.PLANNER)
        assert result is False

    def test_force_unload_calls_ollama(self, scheduler, mock_psutil, mock_ollama):
        scheduler.register_running_model(ModelRole.CODER, "qwen2.5-coder:7b")
        scheduler.force_unload(ModelRole.CODER)
        mock_ollama.generate.assert_called_once_with(
            model="qwen2.5-coder:7b",
            prompt="",
            options={"num_predict": 1},
            keep_alive="0",
        )


class TestModelSchedulerRecordRequest:
    """Tests for record_request()."""

    def test_record_increments_count(self, scheduler, mock_psutil, mock_ollama):
        scheduler.register_running_model(ModelRole.EXECUTOR, "llama3.1:8b")
        scheduler.record_request(ModelRole.EXECUTOR, 2.0)
        assert scheduler._loaded[ModelRole.EXECUTOR].total_requests == 1

    def test_record_latency_violation(self, scheduler, mock_psutil, mock_ollama):
        scheduler.register_running_model(ModelRole.EXECUTOR, "llama3.1:8b")
        # EXECUTOR budget is 20s, send 25s
        scheduler.record_request(ModelRole.EXECUTOR, 25.0)
        assert scheduler._loaded[ModelRole.EXECUTOR].latency_violations == 1
        assert scheduler._loaded[ModelRole.EXECUTOR].healthy is True

    def test_record_unhealthy_after_threshold(self, scheduler, mock_psutil, mock_ollama):
        scheduler.register_running_model(ModelRole.EXECUTOR, "llama3.1:8b")
        for _ in range(LATENCY_UNHEALTHY_COUNT):
            scheduler.record_request(ModelRole.EXECUTOR, 25.0)
        assert scheduler._loaded[ModelRole.EXECUTOR].healthy is False

    def test_record_nonexistent_model(self, scheduler, mock_psutil, mock_ollama):
        # Should not raise
        scheduler.record_request(ModelRole.PLANNER, 5.0)


class TestModelSchedulerTick:
    """Tests for tick() - idle timeouts and RAM pressure."""

    def test_tick_unloads_idle_cold_model(self, scheduler, mock_psutil, mock_ollama):
        """Cold model past idle timeout should be unloaded."""
        scheduler.register_running_model(ModelRole.PLANNER, "qwen3:8b")
        # Fake the last_used to be 6 minutes ago (timeout is 5 min = 300s)
        scheduler._loaded[ModelRole.PLANNER].last_used = time.time() - 360

        scheduler.tick()
        assert ModelRole.PLANNER not in scheduler._loaded

    def test_tick_keeps_warm_model(self, scheduler, mock_psutil, mock_ollama):
        """Warm model (EXECUTOR) should never be idle-unloaded."""
        scheduler.register_running_model(ModelRole.EXECUTOR, "llama3.1:8b")
        scheduler._loaded[ModelRole.EXECUTOR].last_used = time.time() - 3600

        scheduler.tick()
        assert ModelRole.EXECUTOR in scheduler._loaded

    def test_tick_ram_pressure(self, scheduler, mock_psutil, mock_ollama):
        """RAM pressure should trigger emergency unload of cold models."""
        # Set free RAM below threshold
        mock_psutil.virtual_memory.return_value.available = 5 * (1024 ** 3)

        scheduler.register_running_model(ModelRole.PLANNER, "qwen3:8b")
        scheduler.tick()

        assert scheduler._ram_pressure_events == 1

    def test_tick_saves_health_periodically(self, scheduler, tmp_path, mock_psutil, mock_ollama):
        """Health should be saved every 60 ticks."""
        health_path = tmp_path / "model_health.json"
        scheduler._health_path = health_path

        # Run 60 ticks
        for _ in range(60):
            scheduler.tick()

        assert health_path.exists()

    def test_tick_no_crash_empty(self, scheduler, mock_psutil, mock_ollama):
        """Tick with no loaded models should not crash."""
        scheduler.tick()
        assert scheduler._tick_count == 1


class TestModelSchedulerRAM:
    """Tests for RAM management."""

    def test_can_load_sufficient_ram(self, scheduler, mock_psutil, mock_ollama):
        spec = get_model(ModelRole.EXECUTOR)
        ok, reason = scheduler._can_load(spec)
        assert ok is True

    def test_can_load_insufficient_ram(self, scheduler, mock_psutil, mock_ollama):
        mock_psutil.virtual_memory.return_value.available = 5 * (1024 ** 3)
        spec = get_model(ModelRole.PLANNER)  # needs 12 GB free
        ok, reason = scheduler._can_load(spec)
        assert ok is False
        assert "RAM" in reason

    def test_can_load_heavy_mutex_conflict(self, scheduler, mock_psutil, mock_ollama):
        """Can't load CODER if PLANNER is already loaded."""
        scheduler.register_running_model(ModelRole.PLANNER, "qwen3:8b")
        spec = get_model(ModelRole.CODER)
        ok, reason = scheduler._can_load(spec)
        assert ok is False
        assert "mutex" in reason.lower() or "Heavy" in reason

    def test_try_free_ram_unloads_cold(self, scheduler, mock_psutil, mock_ollama):
        """try_free_ram should unload cold models."""
        scheduler.register_running_model(ModelRole.PLANNER, "qwen3:8b")
        scheduler._loaded[ModelRole.PLANNER].last_used = time.time() - 100

        freed = scheduler._try_free_ram(5.0)
        assert freed is True
        assert ModelRole.PLANNER not in scheduler._loaded

    def test_try_free_ram_skips_warm(self, scheduler, mock_psutil, mock_ollama):
        """try_free_ram should NOT unload warm models."""
        scheduler.register_running_model(ModelRole.EXECUTOR, "llama3.1:8b")
        scheduler._loaded[ModelRole.EXECUTOR].last_used = time.time() - 3600

        freed = scheduler._try_free_ram(4.0)
        assert freed is False  # nothing cold to unload
        assert ModelRole.EXECUTOR in scheduler._loaded

    def test_get_free_ram_gb(self, scheduler, mock_psutil, mock_ollama):
        mock_psutil.virtual_memory.return_value.available = 16 * (1024 ** 3)
        assert abs(scheduler._get_free_ram_gb() - 16.0) < 0.01

    def test_get_total_loaded_ram(self, scheduler, mock_psutil, mock_ollama):
        scheduler.register_running_model(ModelRole.EXECUTOR, "llama3.1:8b")
        scheduler.register_running_model(ModelRole.PLANNER, "qwen3:8b")
        total = scheduler._get_total_loaded_ram_gb()
        assert total == 10.5  # 5.0 + 5.5


class TestModelSchedulerHealth:
    """Tests for health persistence."""

    def test_save_health(self, scheduler, tmp_path, mock_psutil, mock_ollama):
        health_path = tmp_path / "model_health.json"
        scheduler._health_path = health_path
        scheduler.register_running_model(ModelRole.EXECUTOR, "llama3.1:8b")

        scheduler.save_health()
        assert health_path.exists()

        data = json.loads(health_path.read_text())
        assert "executor" in data["models"]
        assert data["models"]["executor"]["ollama_tag"] == "llama3.1:8b"

    def test_load_health(self, scheduler, tmp_path, mock_psutil, mock_ollama):
        health_path = tmp_path / "model_health.json"
        health_path.write_text(json.dumps({
            "last_updated": time.time(),
            "ram_pressure_events": 5,
            "models": {},
        }))
        scheduler._health_path = health_path

        scheduler.load_health()
        assert scheduler._ram_pressure_events == 5

    def test_load_health_missing_file(self, scheduler, tmp_path, mock_psutil, mock_ollama):
        scheduler._health_path = tmp_path / "nonexistent.json"
        scheduler.load_health()  # Should not raise
        assert scheduler._ram_pressure_events == 0


class TestModelSchedulerStatus:
    """Tests for status reporting."""

    def test_get_status(self, scheduler, mock_psutil, mock_ollama):
        scheduler.register_running_model(ModelRole.EXECUTOR, "llama3.1:8b")
        status = scheduler.get_status()
        assert status["loaded_count"] == 1
        assert "executor" in status["loaded_models"]
        assert status["loaded_models"]["executor"]["healthy"] is True

    def test_get_health_metrics(self, scheduler, mock_psutil, mock_ollama):
        scheduler.register_running_model(ModelRole.EXECUTOR, "llama3.1:8b")
        metrics = scheduler.get_health_metrics()
        assert metrics["loaded_count"] == 1
        assert "executor" in metrics["models"]

    def test_register_running_model(self, scheduler, mock_psutil, mock_ollama):
        scheduler.register_running_model(ModelRole.EXECUTOR, "llama3.1:8b")
        assert ModelRole.EXECUTOR in scheduler._loaded
        loaded = scheduler._loaded[ModelRole.EXECUTOR]
        assert loaded.ollama_tag == "llama3.1:8b"
        assert loaded.healthy is True


class TestModelSchedulerOllama:
    """Tests for Ollama integration."""

    def test_ollama_load(self, scheduler, mock_psutil, mock_ollama):
        result = scheduler._ollama_load("qwen3:8b")
        assert result is True
        mock_ollama.generate.assert_called_once_with(
            model="qwen3:8b",
            prompt=" ",
            options={"num_predict": 1},
            keep_alive="10m",
        )

    def test_ollama_load_failure(self, scheduler, mock_psutil, mock_ollama):
        mock_ollama.generate.side_effect = Exception("Connection refused")
        result = scheduler._ollama_load("qwen3:8b")
        assert result is False

    def test_ollama_unload(self, scheduler, mock_psutil, mock_ollama):
        result = scheduler._ollama_unload("qwen3:8b")
        assert result is True
        mock_ollama.generate.assert_called_once_with(
            model="qwen3:8b",
            prompt="",
            options={"num_predict": 1},
            keep_alive="0",
        )

    def test_ollama_list_running(self, scheduler, mock_psutil, mock_ollama):
        mock_ollama.ps.return_value = {
            "models": [{"name": "llama3.1:8b"}, {"name": "qwen3:8b"}]
        }
        running = scheduler._ollama_list_running()
        assert running == ["llama3.1:8b", "qwen3:8b"]

    def test_ollama_not_available(self, scheduler, mock_psutil):
        """If ollama library is None, methods should handle gracefully."""
        with patch("agent_core.llm.model_scheduler.ollama_lib", None):
            assert scheduler._ollama_load("test") is False
            assert scheduler._ollama_unload("test") is False
            assert scheduler._ollama_list_running() == []


# ============================================================
# ROUTING RULES TESTS
# ============================================================

class TestRoutingRules:
    """Tests for routing_rules.py."""

    def test_route_chat(self):
        assert route_task(TaskType.CHAT) == ModelRole.EXECUTOR

    def test_route_learn(self):
        assert route_task(TaskType.LEARN) == ModelRole.EXTERNAL

    def test_route_exam(self):
        assert route_task(TaskType.EXAM) == ModelRole.EXTERNAL

    def test_route_plan(self):
        assert route_task(TaskType.PLAN) == ModelRole.PLANNER

    def test_route_code(self):
        assert route_task(TaskType.CODE) == ModelRole.CODER

    def test_route_classify(self):
        assert route_task(TaskType.CLASSIFY) == ModelRole.TRIAGE

    def test_route_summarize(self):
        assert route_task(TaskType.SUMMARIZE) == ModelRole.MEMORY

    def test_route_general(self):
        assert route_task(TaskType.GENERAL) == ModelRole.EXECUTOR

    def test_heuristic_code_keywords(self):
        assert heuristic_classify("Write a pytest for this function") == TaskType.CODE
        assert heuristic_classify("Fix the bug in def calculate()") == TaskType.CODE
        assert heuristic_classify("refactor the import statements") == TaskType.CODE

    def test_heuristic_plan_keywords(self):
        assert heuristic_classify("Design the architecture for this module") == TaskType.PLAN
        assert heuristic_classify("Create a strategy for deployment") == TaskType.PLAN

    def test_heuristic_summary_keywords(self):
        assert heuristic_classify("Summarize this document into key points") == TaskType.SUMMARIZE
        assert heuristic_classify("Extract the main highlights") == TaskType.SUMMARIZE

    def test_heuristic_classify_keywords(self):
        assert heuristic_classify("Classify this intent into a category") == TaskType.CLASSIFY

    def test_heuristic_general_fallback(self):
        assert heuristic_classify("Hello world") == TaskType.GENERAL
        assert heuristic_classify("") == TaskType.GENERAL
        assert heuristic_classify("ab") == TaskType.GENERAL

    def test_heuristic_truncates_long_input(self):
        # Should not crash on very long input
        long_text = "plan " * 1000
        result = heuristic_classify(long_text)
        assert result == TaskType.PLAN


# ============================================================
# LLM ROUTER INTEGRATION TESTS
# ============================================================

class TestLLMRouterWithScheduler:
    """Tests for LLMRouter multi-model integration."""

    def test_router_without_scheduler_backward_compat(self):
        """Router without scheduler works exactly as before."""
        from agent_core.llm.router import LLMRouter

        mock_brain = Mock()
        mock_brain.think.return_value = "hello"
        mock_brain._ask_once.return_value = "answer"
        mock_brain.analyze_task.return_value = {"key": "value"}

        router = LLMRouter(ollama_brain=mock_brain)
        assert router.think("test") == "hello"
        assert router._ask_once("test") == "answer"
        assert router.analyze_task("test") == {"key": "value"}

    def test_router_set_model_scheduler(self):
        """set_model_scheduler should wire the scheduler."""
        from agent_core.llm.router import LLMRouter

        mock_brain = Mock()
        router = LLMRouter(ollama_brain=mock_brain)
        assert router._model_scheduler is None

        mock_scheduler = Mock()
        router.set_model_scheduler(mock_scheduler)
        assert router._model_scheduler is mock_scheduler

    def test_ask_as_role_no_scheduler(self):
        """ask_as_role without scheduler falls back to Ollama."""
        from agent_core.llm.router import LLMRouter

        mock_brain = Mock()
        mock_brain._ask_once.return_value = "ollama_response"

        router = LLMRouter(ollama_brain=mock_brain)
        result = router.ask_as_role(ModelRole.PLANNER, "test prompt")
        assert result == "ollama_response"
        mock_brain._ask_once.assert_called_once()

    def test_ask_as_role_scheduler_fails(self):
        """ask_as_role with failed ensure_ready falls back to Ollama."""
        from agent_core.llm.router import LLMRouter

        mock_brain = Mock()
        mock_brain._ask_once.return_value = "fallback"
        mock_scheduler = Mock()
        mock_scheduler.ensure_ready.return_value = EnsureResult(
            success=False, reason="RAM insufficient"
        )

        router = LLMRouter(ollama_brain=mock_brain)
        router.set_model_scheduler(mock_scheduler)
        result = router.ask_as_role(ModelRole.PLANNER, "test")
        assert result == "fallback"

    @patch("agent_core.llm.router.ollama_lib")
    def test_ask_as_role_success(self, mock_ollama_router):
        """ask_as_role with successful ensure_ready uses scheduled model."""
        from agent_core.llm.router import LLMRouter

        mock_brain = Mock()
        mock_scheduler = Mock()
        mock_scheduler.ensure_ready.return_value = EnsureResult(
            success=True, ollama_tag="qwen3:8b", role=ModelRole.PLANNER,
        )

        mock_ollama_router.chat.return_value = {
            "message": {"content": "planned response"}
        }

        router = LLMRouter(ollama_brain=mock_brain)
        router.set_model_scheduler(mock_scheduler)

        result = router.ask_as_role(ModelRole.PLANNER, "design a plan")
        assert result == "planned response"
        mock_scheduler.record_request.assert_called_once()
        mock_scheduler.release.assert_called_once()

    def test_get_stats_includes_scheduler(self):
        """get_stats should include scheduler status when available."""
        from agent_core.llm.router import LLMRouter

        mock_brain = Mock()
        mock_brain.model = "llama3.1:8b"
        mock_scheduler = Mock()
        mock_scheduler.get_status.return_value = {"loaded_count": 1}

        router = LLMRouter(ollama_brain=mock_brain)
        router.set_model_scheduler(mock_scheduler)
        stats = router.get_stats()
        assert "scheduler" in stats
        assert stats["scheduler"]["loaded_count"] == 1

    def test_get_stats_no_scheduler(self):
        """get_stats without scheduler should not include scheduler key."""
        from agent_core.llm.router import LLMRouter

        mock_brain = Mock()
        mock_brain.model = "llama3.1:8b"

        router = LLMRouter(ollama_brain=mock_brain)
        stats = router.get_stats()
        assert "scheduler" not in stats
