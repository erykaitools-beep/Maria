"""World/task priority, real worker propagation, and unchanged refusal gates."""
import threading
import time
from types import SimpleNamespace

import pytest

from agent_core.llm.execution_budget import call_with_timeout
from agent_core.llm.local_compute import LocalComputeBlocked, LocalComputeCoordinator
from agent_core.llm.work_priority import WorkPurpose, current_work_purpose, work_purpose
from agent_core.planner.action_executor import ActionExecutor
from agent_core.planner.planner_model import ActionType, create_plan
from agent_core.vision.cortex import VisionCortex
from agent_core.vision.modules.scene.analyzer import SceneModule
from agent_core.vision.sensors.mock_sensor import MockSensor
from agent_core.vision.snapshot_service import VisionSnapshotService
from agent_core.vision.vision_advisor import VisionAdvisor
from agent_core.workflow.delegation import DelegationManager
from agent_core.workflow.workflow_model import WorkflowStep


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.001)


def test_world_and_task_overtake_text_upkeep_without_overlapping_inference():
    coordinator = LocalComputeCoordinator()
    order, errors, active = [], [], []
    purposes = [WorkPurpose.BACKGROUND, WorkPurpose.INTERACTION,
                WorkPurpose.ACTION, WorkPurpose.WORLD_EVENT]

    def request(purpose):
        try:
            with work_purpose(purpose), coordinator.lease(
                "vision" if purpose in purposes[2:] else "text", timeout_s=2,
            ):
                order.append(purpose)
                active.append(coordinator.snapshot()["active_purpose"])
        except Exception as exc:
            errors.append(exc)

    threads = []
    try:
        with coordinator.lease("embedding"):
            for purpose in purposes:
                thread = threading.Thread(target=request, args=(purpose,))
                threads.append(thread)
                thread.start()
                wait_for(lambda: coordinator.snapshot()["waiting_requests"] == len(threads))
                assert not order, "a queued request bypassed the occupied compute slot"
            state = coordinator.snapshot()
            assert state["waiting_world_events"] == state["waiting_actions"] == 1
            assert state["waiting_background"] == 1
    finally:
        for thread in threads:
            thread.join(3)
    assert all(not thread.is_alive() for thread in threads)
    assert not errors
    assert order == list(reversed(purposes))
    assert active == [p.value for p in order]
    assert coordinator.snapshot()["waiting_requests"] == 0
    assert coordinator.snapshot()["active_purpose"] is None


def test_nested_background_helper_cannot_demote_action_and_scopes_restore():
    assert current_work_purpose() is None
    with work_purpose(WorkPurpose.BACKGROUND):
        with work_purpose(WorkPurpose.ACTION):
            with work_purpose(WorkPurpose.BACKGROUND):
                assert current_work_purpose() == WorkPurpose.ACTION
        assert current_work_purpose() == WorkPurpose.BACKGROUND
    assert current_work_purpose() is None


def test_timeout_pool_inherits_purpose_and_restores_it_after_failure():
    def fail():
        assert current_work_purpose() == WorkPurpose.WORLD_EVENT
        raise ValueError("controlled failure")

    with work_purpose(WorkPurpose.WORLD_EVENT):
        assert call_with_timeout(current_work_purpose, 1) == WorkPurpose.WORLD_EVENT
        with pytest.raises(ValueError, match="controlled failure"):
            call_with_timeout(fail, 1)
    for _ in range(4):
        assert call_with_timeout(current_work_purpose, 1) is None


def test_timed_out_worker_keeps_own_purpose_until_completion():
    entered, release, done = (threading.Event() for _ in range(3))
    seen = []

    def slow():
        entered.set()
        try:
            assert release.wait(2)
            seen.append(current_work_purpose())
        finally:
            done.set()

    try:
        with work_purpose(WorkPurpose.ACTION):
            with pytest.raises(TimeoutError):
                call_with_timeout(slow, 0.05)
        assert entered.is_set() and current_work_purpose() is None
    finally:
        release.set()
        assert done.wait(2)
    assert seen == [WorkPurpose.ACTION]
    assert call_with_timeout(current_work_purpose, 1) is None


def test_highest_priority_keeps_cooling_timeout_and_cancellation_gates():
    coordinator = LocalComputeCoordinator()
    with work_purpose(WorkPurpose.WORLD_EVENT):
        coordinator.enter_cooling(80)
        with pytest.raises(LocalComputeBlocked, match="cooling"):
            with coordinator.lease("vision"):
                pytest.fail("priority bypassed cooling")
        assert not coordinator.exit_cooling(75)["transitioned"]
        coordinator.exit_cooling(70)
        cancelled = threading.Event()
        cancelled.set()
        with pytest.raises(LocalComputeBlocked, match="cancelled"):
            with coordinator.lease("vision", cancel_event=cancelled):
                pytest.fail("priority bypassed cancellation")
        with pytest.raises(LocalComputeBlocked, match="timeout"):
            with coordinator.lease("vision", timeout_s=0):
                pytest.fail("priority bypassed timeout")
    assert coordinator.snapshot()["waiting_requests"] == 0
    with coordinator.lease("text", timeout_s=1):
        pass


@pytest.mark.parametrize("action,params,purpose", [
    (ActionType.EFFECTOR, {}, WorkPurpose.ACTION),
    (ActionType.FS_WRITE, {}, WorkPurpose.ACTION),
    (ActionType.LEARN, {}, WorkPurpose.BACKGROUND),
    (ActionType.LEARN, {"source": "operator_command"}, WorkPurpose.ACTION),
])
@pytest.mark.parametrize("routed", [True, False])
def test_action_purpose_reaches_both_execution_paths(action, params, purpose, routed, monkeypatch):
    executor = ActionExecutor()
    seen = []

    def execute(plan):
        seen.append(current_work_purpose())
        return {"success": False, "blocked_by": "test_refusal"}

    if routed:
        executor.set_capability_router(SimpleNamespace(dispatch=execute))
    else:
        monkeypatch.setattr(executor, executor._ACTION_MAP[action], execute)
    plan = create_plan(None, "purpose test", action, params)
    with work_purpose(WorkPurpose.BACKGROUND):
        result = executor.execute(plan)
        assert current_work_purpose() == WorkPurpose.BACKGROUND
    assert result["success"] is False and result["blocked_by"] == "test_refusal"
    assert seen == [purpose]
    assert current_work_purpose() is None


def test_workflow_priority_does_not_fall_through_an_unwired_k7(monkeypatch):
    delegation = DelegationManager()
    seen = []

    class Router:
        def is_available(self, action):
            return True

        def dispatch(self, plan):
            pytest.fail("unwired K7 dispatched a tool")

    delegation.set_capability_router(Router())
    delegation.set_plan_factory(lambda *args: pytest.fail("unwired K7 constructed a plan"))
    original = delegation._k7_check

    def gate(*args):
        seen.append(current_work_purpose())
        return original(*args)

    monkeypatch.setattr(delegation, "_k7_check", gate)
    step = WorkflowStep(order=0, action="effector", description="task", params={})
    result = delegation.delegate(step)
    assert result.success is False
    assert result.result["blocked_by"] == "autonomy_policy"
    assert seen == [WorkPurpose.ACTION]
    assert current_work_purpose() is None


def test_camera_event_and_manual_job_carry_correct_purpose_in_real_workers(tmp_path, monkeypatch):
    monkeypatch.setenv("VISION_CHANGE_GATE", "off")
    sensor = MockSensor()
    sensor.open()
    cortex = VisionCortex()
    cortex.add_sensor(sensor)
    coordinator, seen, pings = LocalComputeCoordinator(), [], []
    scene = SceneModule()

    def describe(prompt, image):
        with coordinator.lease("vision", timeout_s=1):
            seen.append((current_work_purpose(), coordinator.snapshot()["active_priority"]))
        return "Osoba przy biurku."

    scene._llava_describe = describe
    cortex.add_module(scene)
    advisor = VisionAdvisor(cortex, notify_fn=pings.append, snapshot_path=str(tmp_path / "event.jpg"))
    service = VisionSnapshotService(cortex, encoder=lambda image: b"test-photo")
    try:
        assert advisor.maybe_react([SimpleNamespace(event_type="vision_motion", payload={})])
        advisor._thread.join(2)
        assert not advisor._thread.is_alive() and pings
        job = service.request()
        wait_for(lambda: service.result(job)["status"] != "running")
        assert service.result(job)["success"] and service.frame(job) == b"test-photo"
    finally:
        service.close()
        sensor.close()
    assert seen == [(WorkPurpose.WORLD_EVENT, -20), (WorkPurpose.ACTION, -10)]
    assert current_work_purpose() is None
