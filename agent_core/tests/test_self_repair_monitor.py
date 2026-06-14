import json
import time

from agent_core.conductor.task_model import Assignee, TaskStatus, create_task
from agent_core.self_repair.detectors import (
    ACTION_FAILURE_STORM,
    MODEL_UNAVAILABLE,
    THREAD_UNHEALTHY,
    THREAD_WEDGE_SECONDS,
    detect_action_failure_storm,
    detect_dispatcher_stuck,
    detect_model_unavailable,
    detect_thread_unhealthy,
)


class SnapshotStoreStub:
    def __init__(self, snapshots):
        self._snapshots = snapshots

    def load_recent(self, n):
        return self._snapshots[-n:]


class ConductorStub:
    def __init__(self, tasks):
        self._tasks = tasks

    def list_tasks(self, project=None, status=None):
        out = list(self._tasks)
        if project is not None:
            out = [task for task in out if task.project == project]
        if status is not None:
            out = [task for task in out if task.status == status]
        return out


def _snapshot(snapshot_id, status):
    return {
        "snapshot_id": snapshot_id,
        "external_services": [
            {"name": "NVIDIA NIM API", "status": status},
            {"name": "Ollama (local LLM)", "status": "available"},
            {"name": "OpenClaw Effector", "status": "available"},
        ],
    }


def _task(project, status=TaskStatus.IN_PROGRESS, updated_at=None):
    task = create_task(
        project=project,
        phase="phase",
        title="Task",
        description="",
        assignee=Assignee.CODEX,
    )
    task.status = status
    task.updated_at = updated_at if updated_at is not None else time.time()
    return task


def test_detect_model_unavailable_positive():
    store = SnapshotStoreStub([
        _snapshot("s1", "available"),
        _snapshot("s2", "unavailable"),
        _snapshot("s3", "unavailable"),
    ])

    candidates = detect_model_unavailable(store, lambda kind, subject: False)

    assert len(candidates) == 1
    assert candidates[0].repair_kind == MODEL_UNAVAILABLE
    assert candidates[0].evidence_summary["service_name"] == "NVIDIA NIM API"


def test_detect_model_unavailable_cooldown():
    store = SnapshotStoreStub([
        _snapshot("s1", "available"),
        _snapshot("s2", "unavailable"),
        _snapshot("s3", "unavailable"),
    ])

    candidates = detect_model_unavailable(store, lambda kind, subject: True)

    assert candidates == []


def test_detect_dispatcher_stuck_positive():
    conductor = ConductorStub([
        _task("market_agent", updated_at=time.time() - 65 * 60),
    ])

    candidates = detect_dispatcher_stuck(conductor, lambda kind, subject: False)

    assert len(candidates) == 1
    assert candidates[0].repair_kind == "dispatcher_stuck"
    assert candidates[0].evidence_summary["project"] == "market_agent"


def test_detect_dispatcher_stuck_skips_maria():
    conductor = ConductorStub([
        _task("maria", updated_at=time.time() - 65 * 60),
    ])

    candidates = detect_dispatcher_stuck(conductor, lambda kind, subject: False)

    assert candidates == []


def test_detect_action_failure_storm_positive(tmp_path):
    audit_path = tmp_path / "action_audit.jsonl"
    now = time.time()
    records = [
        {"timestamp": now - i, "success": i >= 5, "action_type": "learn"}
        for i in range(12)
    ]
    audit_path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    candidates = detect_action_failure_storm(
        audit_path,
        lambda kind, subject: False,
    )

    assert len(candidates) == 1
    assert candidates[0].repair_kind == ACTION_FAILURE_STORM
    assert candidates[0].evidence_summary["failures"] == 5


def test_detect_action_failure_storm_insufficient_sample(tmp_path):
    audit_path = tmp_path / "action_audit.jsonl"
    now = time.time()
    records = [
        {"timestamp": now - i, "success": i >= 6, "action_type": "learn"}
        for i in range(8)
    ]
    audit_path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    candidates = detect_action_failure_storm(
        audit_path,
        lambda kind, subject: False,
    )

    assert candidates == []


def test_detect_action_failure_storm_excludes_skipped(tmp_path):
    # T-LEARN-003: skipped actions are audited with success=False but were never
    # attempted -- they must NOT trigger a storm (the false "4/10" exam storms).
    audit_path = tmp_path / "action_audit.jsonl"
    now = time.time()
    records = [
        {"timestamp": now - i, "success": False, "skipped": True,
         "action_type": "exam"}
        for i in range(6)
    ] + [
        {"timestamp": now - i, "success": True, "action_type": "evaluate"}
        for i in range(6)
    ]
    audit_path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    candidates = detect_action_failure_storm(
        audit_path,
        lambda kind, subject: False,
    )

    # 6/12 are success=False but all skipped -> zero real failures -> no storm.
    assert candidates == []


def test_detect_action_failure_storm_counts_only_real_failures(tmp_path):
    # Mixed: real failures still fire, but skipped ones are not counted.
    audit_path = tmp_path / "action_audit.jsonl"
    now = time.time()
    records = (
        [{"timestamp": now - i, "success": False, "action_type": "learn"}
         for i in range(4)]
        + [{"timestamp": now - i, "success": False, "skipped": True,
            "action_type": "exam"} for i in range(4)]
        + [{"timestamp": now - i, "success": True, "action_type": "fetch"}
           for i in range(4)]
    )
    audit_path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    candidates = detect_action_failure_storm(
        audit_path,
        lambda kind, subject: False,
    )

    # 4 real failures / 12 = 0.33 > 0.30 -> storm, but the 4 skips are excluded.
    assert len(candidates) == 1
    assert candidates[0].evidence_summary["failures"] == 4
    assert candidates[0].evidence_summary["by_action_type"]["exam"]["failures"] == 0


# ── 7b: heartbeat / thread-liveness detector ─────────────────────────────


def _thread(name, kind, alive, age_sec=None):
    return {"name": name, "kind": kind, "alive": alive, "age_sec": age_sec}


def test_detect_thread_unhealthy_persistent_dead():
    health = [_thread("TelegramPoll", "persistent", alive=False)]

    candidates = detect_thread_unhealthy(health, lambda kind, subject: False)

    assert len(candidates) == 1
    assert candidates[0].repair_kind == THREAD_UNHEALTHY
    assert candidates[0].evidence_summary["subject"] == "TelegramPoll"
    assert candidates[0].evidence_summary["condition"] == "dead"


def test_detect_thread_unhealthy_persistent_alive_ok():
    health = [_thread("TickWatchdog", "persistent", alive=True)]

    candidates = detect_thread_unhealthy(health, lambda kind, subject: False)

    assert candidates == []


def test_detect_thread_unhealthy_transient_wedged():
    health = [
        _thread("PlannerCycle", "transient", alive=True,
                age_sec=THREAD_WEDGE_SECONDS + 60),
    ]

    candidates = detect_thread_unhealthy(health, lambda kind, subject: False)

    assert len(candidates) == 1
    assert candidates[0].evidence_summary["condition"] == "wedged"
    assert candidates[0].evidence_summary["subject"] == "PlannerCycle"


def test_detect_thread_unhealthy_transient_running_ok():
    # A transient worker mid-cycle (well under the wedge ceiling) is healthy.
    health = [_thread("PlannerCycle", "transient", alive=True, age_sec=300)]

    candidates = detect_thread_unhealthy(health, lambda kind, subject: False)

    assert candidates == []


def test_detect_thread_unhealthy_transient_idle_ok():
    # Not alive between cycles is NORMAL for a transient worker, not a death.
    health = [_thread("TeacherAutoSession", "transient", alive=False)]

    candidates = detect_thread_unhealthy(health, lambda kind, subject: False)

    assert candidates == []


def test_detect_thread_unhealthy_cooldown():
    health = [_thread("TelegramPoll", "persistent", alive=False)]

    candidates = detect_thread_unhealthy(health, lambda kind, subject: True)

    assert candidates == []


def test_detect_thread_unhealthy_cooldown_is_per_thread():
    # Watchdog is in cooldown; a separate dead TelegramPoll must still fire.
    health = [
        _thread("TickWatchdog", "persistent", alive=False),
        _thread("TelegramPoll", "persistent", alive=False),
    ]

    def cooldown(kind, subject):
        return subject == "TickWatchdog"

    candidates = detect_thread_unhealthy(health, cooldown)

    assert [c.evidence_summary["subject"] for c in candidates] == ["TelegramPoll"]


# ── Finding #4: on-demand snapshot refresh when a detector fires ──────────


class _SnapshotStoreStub:
    def __init__(self, snapshots=None):
        self._snapshots = list(snapshots or [])

    def load_recent(self, n):
        return self._snapshots[-n:]


class _SelfPerceptionForMonitor:
    """Tracks take_snapshot() calls so we can assert on-demand refresh."""

    def __init__(self):
        self._store = _SnapshotStoreStub()
        self.snapshot_calls = 0

    def get_latest(self):
        return {"snapshot_id": "snap-current", "mode": "ACTIVE"}

    def take_snapshot(self):
        self.snapshot_calls += 1
        return self.get_latest()


class _CreatorSpy:
    def __init__(self):
        self.created = []

    def set_self_perception(self, sp):
        self.sp = sp

    def create(self, candidate, snapshot_id=""):
        self.created.append((candidate.repair_kind, snapshot_id))
        return f"cdt-{len(self.created)}"


def _monitor(conductor, self_perception, creator, heartbeat_provider=None):
    from pathlib import Path
    from agent_core.self_repair.monitor import SystemFailureMonitor

    return SystemFailureMonitor(
        self_perception=self_perception,
        conductor=conductor,
        audit_path=Path("/nonexistent/action_audit.jsonl"),
        repair_task_creator=creator,
        heartbeat_provider=heartbeat_provider,
    )


def test_scan_refreshes_snapshot_on_demand_when_candidate_found():
    # A stuck market_agent dispatcher makes detect_dispatcher_stuck fire.
    conductor = ConductorStub([
        _task("market_agent", updated_at=time.time() - 65 * 60),
    ])
    sp = _SelfPerceptionForMonitor()
    creator = _CreatorSpy()

    created = _monitor(conductor, sp, creator).scan_and_create()

    # Snapshot refreshed exactly once because a candidate was found, and the
    # fresh snapshot_id flowed into task creation.
    assert sp.snapshot_calls == 1
    assert created == ["cdt-1"]
    assert creator.created[0][1] == "snap-current"


def test_scan_skips_snapshot_when_no_candidate():
    # Healthy system: nothing stuck, no snapshots, no audit file.
    conductor = ConductorStub([])
    sp = _SelfPerceptionForMonitor()
    creator = _CreatorSpy()

    created = _monitor(conductor, sp, creator).scan_and_create()

    # No candidate => no on-demand snapshot work, no tasks.
    assert sp.snapshot_calls == 0
    assert created == []


# ── 7b: heartbeat detector wiring through the monitor (flag-gated) ─────────


class _HeartbeatProviderStub:
    def __init__(self, health):
        self._health = health

    def get_thread_health(self):
        return list(self._health)


_DEAD_WATCHDOG = [
    {"name": "TickWatchdog", "kind": "persistent", "alive": False, "age_sec": None},
]


def test_heartbeat_detector_off_by_default(monkeypatch):
    # Parallel-run: flag unset -> a dead persistent thread is NOT picked up.
    monkeypatch.delenv("HEARTBEAT_DETECTOR_ENABLED", raising=False)
    creator = _CreatorSpy()
    monitor = _monitor(
        ConductorStub([]), _SelfPerceptionForMonitor(), creator,
        _HeartbeatProviderStub(_DEAD_WATCHDOG),
    )

    assert monitor.scan_and_create() == []
    assert creator.created == []


def test_heartbeat_detector_on_creates_task(monkeypatch):
    # Flag on + dead persistent thread -> a thread_unhealthy repair task.
    monkeypatch.setenv("HEARTBEAT_DETECTOR_ENABLED", "1")
    creator = _CreatorSpy()
    monitor = _monitor(
        ConductorStub([]), _SelfPerceptionForMonitor(), creator,
        _HeartbeatProviderStub(_DEAD_WATCHDOG),
    )

    created = monitor.scan_and_create()

    assert created == ["cdt-1"]
    assert creator.created[0][0] == THREAD_UNHEALTHY


def test_heartbeat_detector_on_but_no_provider(monkeypatch):
    # Flag on but provider absent (heartbeat unwired) -> no crash, no task.
    monkeypatch.setenv("HEARTBEAT_DETECTOR_ENABLED", "1")
    creator = _CreatorSpy()
    monitor = _monitor(
        ConductorStub([]), _SelfPerceptionForMonitor(), creator,
        heartbeat_provider=None,
    )

    assert monitor.scan_and_create() == []


def test_heartbeat_provider_glitch_does_not_break_scan(monkeypatch):
    # A throwing provider must never break the core three detectors / the scan.
    monkeypatch.setenv("HEARTBEAT_DETECTOR_ENABLED", "1")

    class _BoomProvider:
        def get_thread_health(self):
            raise RuntimeError("boom")

    creator = _CreatorSpy()
    monitor = _monitor(
        ConductorStub([]), _SelfPerceptionForMonitor(), creator, _BoomProvider(),
    )

    assert monitor.scan_and_create() == []  # no crash, scan completed


def test_core_get_thread_health_classification():
    # Drive HomeostasisCore.get_thread_health with a duck-typed self carrying
    # real thread objects -- proves persistent/transient classification, the
    # wedge-age computation, and that never-started (None) threads are omitted.
    import threading
    import time as _time
    from types import SimpleNamespace

    from agent_core.homeostasis.core import HomeostasisCore

    dead = threading.Thread(target=lambda: None)  # persistent that has exited
    dead.start()
    dead.join()

    stop = threading.Event()
    alive = threading.Thread(target=stop.wait, daemon=True)  # transient, held open
    alive.start()
    try:
        fake = SimpleNamespace(
            _watchdog_thread=dead,
            _telegram_poll_thread=None,
            _telegram_poll_thread_started=None,
            _planner_thread=alive,
            _planner_thread_started=_time.monotonic() - 9999,
            _teacher_thread=None,
            _teacher_thread_started=None,
        )
        health = HomeostasisCore.get_thread_health(fake)
    finally:
        stop.set()

    by_name = {h["name"]: h for h in health}
    assert by_name["TickWatchdog"]["kind"] == "persistent"
    assert by_name["TickWatchdog"]["alive"] is False
    assert by_name["PlannerCycle"]["kind"] == "transient"
    assert by_name["PlannerCycle"]["alive"] is True
    assert by_name["PlannerCycle"]["age_sec"] >= 9999
    # Never-started threads are omitted, never mistaken for a death.
    assert "TelegramPoll" not in by_name
    assert "TeacherAutoSession" not in by_name
