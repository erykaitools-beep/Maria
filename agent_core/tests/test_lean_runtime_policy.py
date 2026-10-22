import threading
import time

import pytest

from agent_core.llm.local_compute import LocalComputeBlocked, LocalComputeCoordinator
from agent_core.llm.model_scheduler import ModelScheduler
from agent_core.llm.model_registry import ModelRole
from agent_core.runtime_profile import lean_runtime, conductor_integration_enabled, model_keep_alive
from agent_core.semantic import indexer


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.001)


def test_text_overtakes_queued_embedding_and_keeps_single_slot():
    coordinator = LocalComputeCoordinator()
    order = []
    def request(kind):
        with coordinator.lease(kind, timeout_s=2):
            order.append(kind)
    threads = []
    try:
        with coordinator.lease("embedding"):
            for kind in ("embedding", "text"):
                thread = threading.Thread(target=request, args=(kind,))
                threads.append(thread)
                thread.start()
                wait_for(lambda: coordinator.snapshot()["waiting_requests"] == len(threads))
    finally:
        for thread in threads:
            thread.join(3)
    assert order == ["text", "embedding"]
    assert coordinator.snapshot()["waiting_requests"] == 0


def test_timed_out_priority_waiter_does_not_starve_background():
    coordinator = LocalComputeCoordinator()
    errors = []
    def text():
        try:
            with coordinator.lease("text", timeout_s=0.02):
                pytest.fail("occupied slot admitted concurrent inference")
        except LocalComputeBlocked as exc:
            errors.append(str(exc))
    with coordinator.lease("embedding"):
        thread = threading.Thread(target=text)
        thread.start()
        thread.join(2)
        assert not thread.is_alive()
    with coordinator.lease("embedding", timeout_s=0.1):
        pass
    assert errors == ["local compute slot timeout"]
    assert coordinator.snapshot()["waiting_requests"] == 0


def test_profile_preserves_standard_and_allows_conductor_override(monkeypatch):
    monkeypatch.delenv("MARIA_RUNTIME_PROFILE", raising=False)
    monkeypatch.delenv("MARIA_CONDUCTOR_INTEGRATION", raising=False)
    monkeypatch.delenv("MARIA_EMBEDDING_KEEP_ALIVE", raising=False)
    assert not lean_runtime()
    assert conductor_integration_enabled()
    assert model_keep_alive("embedding", "5m") == "5m"
    monkeypatch.setenv("MARIA_RUNTIME_PROFILE", "lean")
    assert not conductor_integration_enabled()
    assert model_keep_alive("embedding", "5m") == "60s"
    monkeypatch.setenv("MARIA_CONDUCTOR_INTEGRATION", "1")
    monkeypatch.setenv("MARIA_EMBEDDING_KEEP_ALIVE", "2m")
    assert conductor_integration_enabled()
    assert model_keep_alive("embedding", "5m") == "2m"
    monkeypatch.setenv("MARIA_RUNTIME_PROFILE", "typo")
    with pytest.raises(ValueError):
        lean_runtime()


def test_indexer_defers_busy_cpu_then_indexes(monkeypatch, tmp_path):
    coordinator = LocalComputeCoordinator()
    coordinator.observe_temperature(40)
    monkeypatch.setattr("agent_core.llm.local_compute.get_local_compute_coordinator", lambda: coordinator)
    calls = []
    loads = iter([90, 75, 0])
    monkeypatch.setattr(indexer, "run_initial_indexing", lambda *args, **kwargs: calls.append(kwargs))
    thread = indexer.start_background_indexing(
        object(), str(tmp_path), str(tmp_path), str(tmp_path), delay_sec=0,
        cpu_percent_fn=lambda: next(loads), retry_sec=0.001,
    )
    thread.join(2)
    assert not thread.is_alive()
    assert len(calls) == 1
    assert calls[0]["cancel_event"] is thread.cancel_event


def test_indexer_cancel_during_deferral_does_not_index(monkeypatch, tmp_path):
    coordinator = LocalComputeCoordinator()
    coordinator.observe_temperature(40)
    monkeypatch.setattr("agent_core.llm.local_compute.get_local_compute_coordinator", lambda: coordinator)
    read = threading.Event()
    calls = []
    monkeypatch.setattr(indexer, "run_initial_indexing", lambda *args, **kwargs: calls.append(1))
    thread = indexer.start_background_indexing(
        object(), str(tmp_path), str(tmp_path), str(tmp_path), delay_sec=0,
        cpu_percent_fn=lambda: read.set() or 90, retry_sec=30,
    )
    assert read.wait(1)
    thread.cancel_event.set()
    thread.join(2)
    assert not thread.is_alive()
    assert calls == []


def test_lean_tick_returns_while_maintenance_waits_and_uses_one_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("MARIA_RUNTIME_PROFILE", "lean")
    coordinator = LocalComputeCoordinator()
    monkeypatch.setattr("agent_core.llm.model_scheduler.get_local_compute_coordinator", lambda: coordinator)
    entered, release = threading.Event(), threading.Event()
    scheduler = ModelScheduler(str(tmp_path / "health.json"))
    def idle():
        entered.set()
        assert release.wait(2)
    monkeypatch.setattr(scheduler, "_check_idle_timeouts", idle)
    monkeypatch.setattr(scheduler, "_check_ram_pressure", lambda: None)
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"models": [{"name": "bge-m3:latest", "size": 1234}]}
    monkeypatch.setattr("agent_core.llm.model_scheduler.requests.get", lambda *args, **kwargs: Response())
    try:
        scheduler.tick()
        assert entered.wait(1)
        first = scheduler._maintenance_thread
        for _ in range(20):
            scheduler.tick()
        assert scheduler._maintenance_thread is first
    finally:
        release.set()
        scheduler._maintenance_thread.join(3)
    assert scheduler.get_status()["resident_models"][0]["size"] == 1234
    assert scheduler.get_status()["residency_checked_at"] is not None


def test_accepted_unload_keeps_record_until_residency_confirms_absence(monkeypatch, tmp_path):
    monkeypatch.setenv("MARIA_RUNTIME_PROFILE", "lean")
    coordinator = LocalComputeCoordinator()
    monkeypatch.setattr("agent_core.llm.model_scheduler.get_local_compute_coordinator", lambda: coordinator)
    scheduler = ModelScheduler(str(tmp_path / "health.json"))
    scheduler.register_running_model(ModelRole.MEMORY, "bge-m3")
    monkeypatch.setattr(scheduler, "_ollama_unload", lambda tag: True)
    assert scheduler.force_unload(ModelRole.MEMORY)
    assert ModelRole.MEMORY in scheduler._loaded
    monkeypatch.setattr(scheduler, "_check_idle_timeouts", lambda: None)
    monkeypatch.setattr(scheduler, "_check_ram_pressure", lambda: None)
    models = [{"name": "bge-m3:latest"}]
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"models": models}
    monkeypatch.setattr("agent_core.llm.model_scheduler.requests.get", lambda *args, **kwargs: Response())
    scheduler._start_maintenance()
    scheduler._maintenance_thread.join(2)
    assert ModelRole.MEMORY in scheduler._loaded
    models.clear()
    scheduler._start_maintenance()
    scheduler._maintenance_thread.join(2)
    assert ModelRole.MEMORY not in scheduler._loaded


def test_failed_residency_probe_does_not_report_empty_ram_or_erase_records(monkeypatch, tmp_path):
    monkeypatch.setenv("MARIA_RUNTIME_PROFILE", "lean")
    coordinator = LocalComputeCoordinator()
    monkeypatch.setattr("agent_core.llm.model_scheduler.get_local_compute_coordinator", lambda: coordinator)
    scheduler = ModelScheduler(str(tmp_path / "health.json"))
    scheduler.register_running_model(ModelRole.MEMORY, "bge-m3")
    monkeypatch.setattr(scheduler, "_check_idle_timeouts", lambda: None)
    monkeypatch.setattr(scheduler, "_check_ram_pressure", lambda: None)
    def fail(*args, **kwargs):
        raise OSError("probe unavailable")
    monkeypatch.setattr("agent_core.llm.model_scheduler.requests.get", fail)
    scheduler._start_maintenance()
    scheduler._maintenance_thread.join(2)
    assert scheduler.get_status()["resident_models"] is None
    assert scheduler.get_status()["residency_checked_at"] is None
    assert ModelRole.MEMORY in scheduler._loaded
    assert scheduler._maintenance_lock.acquire(blocking=False)
    scheduler._maintenance_lock.release()
