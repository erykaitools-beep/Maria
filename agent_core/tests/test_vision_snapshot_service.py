"""Fresh manual photos, exact frame ownership, single jobs, TTL and UI auth."""
import hashlib
import json
import threading
import time

import pytest

from agent_core.vision.cortex import VisionCortex
from agent_core.vision.modules.scene.analyzer import SceneModule
from agent_core.vision.snapshot_service import SnapshotBusy, VisionSnapshotService
from agent_core.vision.sensors.mock_sensor import MockSensor


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    assert predicate()


@pytest.fixture
def snapshot_camera():
    sensor = MockSensor()
    sensor.open()
    cortex = VisionCortex()
    cortex.add_sensor(sensor)
    scene = SceneModule()
    cortex.add_module(scene)
    yield cortex, scene
    sensor.close()


def test_snapshot_keeps_original_photo_while_ticks_and_buffer_changes_continue(snapshot_camera):
    cortex, scene = snapshot_camera
    entered, release = threading.Event(), threading.Event()
    expected = []

    def describe(prompt, image):
        expected.append(hashlib.sha256(cortex._last_frame_image.tobytes()).digest())
        entered.set()
        assert release.wait(3)
        return "Osoba przy biurku."

    scene._llava_describe = describe
    service = VisionSnapshotService(cortex, encoder=lambda image: hashlib.sha256(image.tobytes()).digest())
    try:
        job = service.request()
        assert entered.wait(1)
        assert service.result(job)["status"] == "running"
        with pytest.raises(SnapshotBusy):
            service.request()
        cortex.perceive()  # regular perception completes while manual VLM waits
        cortex._last_frame_image[:] = 0
        assert scene._llava_fn is None
        assert cortex.last_percept.scene.backend_used == "statistics"
        release.set()
        wait_for(lambda: service.result(job)["status"] == "done")
        assert service.result(job)["summary"] == "Osoba przy biurku."
        assert service.frame(job) == expected[0]
        assert cortex.last_percept.scene.backend_used == "statistics"
    finally:
        release.set()
        service.close()


def test_cooldown_expiry_and_last_job_only(snapshot_camera):
    cortex, _ = snapshot_camera
    now = [0.0]
    service = VisionSnapshotService(cortex, encoder=lambda _: b"jpeg", clock=lambda: now[0])
    try:
        first = service.request()
        wait_for(lambda: service.result(first)["status"] != "running")
        with pytest.raises(SnapshotBusy):
            service.request()
        result = service.result(first)
        result["summary"] = "tampered"
        assert service.result(first)["summary"] != "tampered"
        assert service.result("unknown") is None
        now[0] = 6
        second = service.request()
        assert first != second and service.result(first) is None
        wait_for(lambda: service.result(second)["status"] != "running")
        now[0] = 307
        assert service.result(second) is None and service.frame(second) is None
    finally:
        service.close()


def test_disconnected_camera_returns_failure_without_a_cached_photo():
    service = VisionSnapshotService(VisionCortex(), encoder=lambda _: pytest.fail("encoded a nonexistent photo"))
    try:
        job = service.request()
        wait_for(lambda: service.result(job)["status"] == "error")
        assert service.result(job)["success"] is False
        assert service.frame(job) is None
    finally:
        service.close()


def test_closed_service_rejects_new_work(snapshot_camera):
    service = VisionSnapshotService(snapshot_camera[0])
    service.close()
    with pytest.raises(SnapshotBusy):
        service.request()


@pytest.fixture
def ui_client(monkeypatch, tmp_path):
    import maria_ui.app as ui
    monkeypatch.setattr(ui, "_vision_publisher", None)
    monkeypatch.setattr(ui, "_vision_snapshots", None)
    path = tmp_path / "old-state.json"
    path.write_text(json.dumps({"last_percept": {"summary": "old cached scene", "timestamp": 1}}))
    monkeypatch.setattr(ui, "_VISION_STATE_PATH", path)
    client = ui.app.test_client()
    with client.session_transaction() as session:
        session["authenticated"] = True
    return ui, client


def test_ui_only_mode_cannot_report_old_state_as_a_new_snapshot(ui_client):
    _, client = ui_client
    response = client.post("/api/vision/snap")
    assert response.status_code == 503
    assert not response.json["success"]
    assert "old cached scene" not in response.get_data(as_text=True)


def test_live_preview_uses_memory_and_rejects_superseded_frame(ui_client, monkeypatch, tmp_path):
    from agent_core.vision.preview import VisionPreviewPublisher
    from types import SimpleNamespace
    ui, client = ui_client
    camera = SimpleNamespace(preview_snapshot=lambda: ({"last_percept": {"timestamp": 2, "summary": "new live room"}}, b"pixels"))
    publisher = VisionPreviewPublisher(camera, tmp_path, encoder=lambda _: b"live-jpeg")
    publisher._publish()
    monkeypatch.setattr(publisher, "touch_viewer", lambda: None)
    monkeypatch.setattr(ui, "_vision_publisher", publisher)
    state = client.get("/api/vision/state").json
    assert state["state"]["last_percept"]["summary"] == "new live room"
    assert client.get("/api/vision/frame?v=2").data == b"live-jpeg"
    assert client.get("/api/vision/frame?v=1").status_code == 409
    assert client.get("/api/vision/frame?v=2", headers={"If-None-Match": '"2"'}).status_code == 304


def test_failure_to_start_snapshot_thread_does_not_leave_a_running_job(snapshot_camera, monkeypatch):
    service = VisionSnapshotService(snapshot_camera[0])

    def fail_start(self):
        raise RuntimeError("thread unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, "start", fail_start)
        with pytest.raises(SnapshotBusy):
            service.request()
    assert service._job is None
    service.close()


def test_ui_snapshot_request_result_and_photo_are_authenticated(ui_client):
    ui, _ = ui_client
    guest = ui.app.test_client()
    for response in (guest.post("/api/vision/snap"),
                     guest.get("/api/vision/snap/unknown"),
                     guest.get("/api/vision/snap/unknown/frame"),
                     guest.get("/api/vision/state")):
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")


def test_ui_accepts_async_fresh_photo_without_blocking_request(ui_client, snapshot_camera, monkeypatch):
    ui, client = ui_client
    cortex, scene = snapshot_camera
    entered, release = threading.Event(), threading.Event()

    def describe(*args):
        entered.set()
        assert release.wait(3)
        return "Nowe zdjecie"

    scene._llava_describe = describe
    service = VisionSnapshotService(cortex, encoder=lambda _: b"exact-photo")
    monkeypatch.setattr(ui, "_vision_snapshots", service)
    try:
        response = client.post("/api/vision/snap")
        assert response.status_code == 202
        job = response.json["job_id"]
        assert entered.wait(1)
        assert client.get("/api/vision/snap/" + job).json["status"] == "running"
        assert client.post("/api/vision/snap").status_code == 409
        assert client.get("/api/vision/snap/unknown").status_code == 404
        assert client.get("/api/vision/snap/" + job + "/frame").status_code == 404
        release.set()
        wait_for(lambda: service.result(job)["status"] == "done")
        completed = client.get("/api/vision/snap/" + job).json
        assert completed["summary"] == "Nowe zdjecie"
        assert completed["percept"]["timestamp"] != 1
        assert client.get(completed["frame_url"]).data == b"exact-photo"
        assert client.get("/api/vision/state").json["state"]["last_percept"]["timestamp"] == 1
    finally:
        release.set()
        service.close()
