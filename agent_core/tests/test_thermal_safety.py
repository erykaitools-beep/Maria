"""Regression tests for the 2026-08-05 mini-PC thermal incident."""

import threading
import time

import pytest

from agent_core.executor.module_executor import ModuleExecutor
from agent_core.homeostasis.actions import CorrectiveActionGenerator
from agent_core.homeostasis.core import HomeostasisCore
from agent_core.homeostasis.event_logger import HomeostasisEventLogger
from agent_core.homeostasis.mode_regulator import ModeRegulator
from agent_core.homeostasis.state_model import Mode
from agent_core.llm.local_compute import LocalComputeBlocked
from agent_core.llm.manager import LLMManager
from agent_core.memory.manager import MemoryManager
from agent_core.modules.homeostasis_module import _wire_executor_modules


class _CapturingExecutor(ModuleExecutor):
    def __init__(self):
        super().__init__()
        self.responses = []

    def signal_module(self, module_name, signal_type, **kwargs):
        response = super().signal_module(module_name, signal_type, **kwargs)
        self.responses.append((module_name, signal_type, response))
        return response


class _Teacher:
    def __init__(self):
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1


class _Scheduler:
    def __init__(self):
        self.unload_calls = 0

    def emergency_unload_all(self):
        self.unload_calls += 1
        return {
            "requested": ["llama3.1:8b", "qwen3:8b", "bge-m3:latest"],
            "unloaded": ["qwen3:8b"],
            "failed": [],
        }


def test_critical_temperature_cancels_and_stays_latched_until_safe(
    tmp_path, isolated_local_compute_coordinator,
):
    """Exercise Thermal stress -> executor -> real cooling effect end to end."""
    coordinator = isolated_local_compute_coordinator
    executor = _CapturingExecutor()
    llm = LLMManager()
    logger = HomeostasisEventLogger(tmp_path / "homeostasis.jsonl")
    core = HomeostasisCore(
        memory_manager=MemoryManager(),
        llm_manager=llm,
        executor=executor,
        event_logger=logger,
    )
    core._teacher_agent = _Teacher()
    core._model_scheduler = _Scheduler()
    _wire_executor_modules(
        executor, core, core.memory, llm,
        compute_coordinator=coordinator,
    )

    cancelled = threading.Event()
    token = coordinator.register_background_task(
        "running-indexer", cancelled.set,
    )
    try:
        hot = core.action_generator.generate_actions({"temp_c": 85.0}, alerts=[])
        core._execute_corrective_actions(hot)

        llm_response = next(
            response for module, signal, response in executor.responses
            if (module, signal) == ("llm", "reduce_batch_size")
        )
        assert llm_response["effect"] == "thermal_cooling_active"
        assert llm_response["effect"] != "recorded_only"
        assert coordinator.cooling is True
        assert cancelled.is_set()
        assert core._teacher_agent.stop_calls == 1
        assert core._model_scheduler.unload_calls == 1
        assert llm.health_check()["batch_size_factor"] == 0.5

        # New text/vision/embedding work all use this lease and must fail closed.
        for kind in ("text", "vision", "embedding"):
            with pytest.raises(LocalComputeBlocked, match="cooling"):
                with coordinator.lease(kind, timeout_s=0.01):
                    pass

        # No pause/resume flap in the hysteresis band.
        assert core.action_generator.generate_actions(
            {"temp_c": 80.0}, alerts=[]
        ) == []
        assert coordinator.cooling is True

        recovered = core.action_generator.generate_actions(
            {"temp_c": 70.0}, alerts=[]
        )
        core._execute_corrective_actions(recovered)
        assert coordinator.cooling is False
        assert llm.health_check()["batch_size_factor"] == 1.0

        with coordinator.lease("text", timeout_s=0.01):
            pass
    finally:
        coordinator.unregister_background_task(token)


def test_text_vision_and_embedding_never_overlap(
    isolated_local_compute_coordinator,
):
    coordinator = isolated_local_compute_coordinator
    live = 0
    maximum = 0
    lock = threading.Lock()
    start = threading.Barrier(3)

    def worker(kind):
        nonlocal live, maximum
        start.wait(timeout=2)
        with coordinator.lease(kind, timeout_s=2.0):
            with lock:
                live += 1
                maximum = max(maximum, live)
            time.sleep(0.03)
            with lock:
                live -= 1

    threads = [
        threading.Thread(target=worker, args=(kind,))
        for kind in ("text", "vision", "embedding")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert all(not thread.is_alive() for thread in threads)
    assert maximum == 1


def test_thermal_pressure_bypasses_startup_cpu_grace_and_has_hysteresis():
    regulator = ModeRegulator()
    hot = {
        "ram_available_pct": 80,
        "cpu_load": 10,
        "temp_c": 85.0,
        "idle_seconds": 0,
    }
    assert regulator.decide_mode(hot, alerts=[]) == Mode.REDUCED
    regulator.transition_to(Mode.REDUCED)

    middle = dict(hot, temp_c=80.0)
    assert regulator.decide_mode(middle, alerts=[]) == Mode.REDUCED
    assert regulator._thermal_cooling is True

    safe = dict(hot, temp_c=70.0)
    regulator.decide_mode(safe, alerts=[])
    assert regulator._thermal_cooling is False


def test_operator_active_override_cannot_bypass_thermal_cooling():
    regulator = ModeRegulator()
    regulator.request_mode_override(
        Mode.ACTIVE,
        duration_seconds=300,
        reason="test override",
        state={"idle_seconds": 0},
        alerts=[],
    )

    mode = regulator.decide_mode(
        {
            "ram_available_pct": 80,
            "cpu_load": 10,
            "temp_c": 85.0,
            "idle_seconds": 0,
        },
        alerts=[],
    )

    assert mode == Mode.REDUCED


def test_missing_sensor_reading_cannot_fake_thermal_recovery(
    isolated_local_compute_coordinator,
):
    """The ThermalSensor fallback value (50C) is not a valid resume signal."""
    coordinator = isolated_local_compute_coordinator
    coordinator.observe_temperature(85.0)

    result = coordinator.observe_temperature(50.0, reading_available=False)

    assert result == "unavailable"
    assert coordinator.cooling is True
    assert coordinator.startup_background_allowed() is False

    generator = CorrectiveActionGenerator()
    generator.generate_actions(
        {"temp_c": 85.0, "temp_available": True}, alerts=[]
    )
    assert generator.generate_actions(
        {"temp_c": 50.0, "temp_available": False}, alerts=[]
    ) == []
