"""Off-tick preview publication, bounded work and atomic compatibility files."""
import json
import threading
import time

import numpy as np
import pytest

from agent_core.homeostasis.core import HomeostasisCore
from agent_core.vision import preview
from agent_core.vision.cortex import VisionCortex
from agent_core.vision.sensors.mock_sensor import MockSensor


class Camera:
    def __init__(self):
        self.timestamp = 1
        self.image = np.ones((8, 8, 3), dtype=np.uint8)

    def preview_snapshot(self):
        return {"last_percept": {"timestamp": self.timestamp, "summary": "room"}}, self.image.copy()


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    assert predicate()


def test_slow_preview_io_does_not_hold_tick_or_grow_a_queue(tmp_path, monkeypatch):
    entered, release, done = (threading.Event() for _ in range(3))
    camera = Camera()
    encodes = []
    publisher = preview.VisionPreviewPublisher(camera, tmp_path, interval=0.01,
                                               encoder=lambda image: encodes.append(camera.timestamp) or b"jpeg")
    original = preview.atomic_write

    def slow_write(path, data):
        if not entered.is_set():
            entered.set()
            assert release.wait(3)
        original(path, data)

    monkeypatch.setattr(preview, "atomic_write", slow_write)
    core = object.__new__(HomeostasisCore)
    core._vision_publisher = publisher

    def tick_burst():
        for stamp in range(2, 1002):
            camera.timestamp = stamp
            core._write_vision_state(None)
        done.set()

    producer = threading.Thread(target=tick_burst)
    try:
        publisher.notify()
        assert entered.wait(1)
        producer.start()
        assert done.wait(1), "tick waited for blocked disk IO"
        release.set()
        wait_for(lambda: publisher.state()["last_percept"]["timestamp"] == 1001)
        # A burst leaves only the latest pending state, not 1000 disk writes.
        assert len(encodes) == 1
        assert len(list(tmp_path.iterdir())) == 2
    finally:
        release.set()
        if producer.ident is not None:
            producer.join(2)
        publisher.close()


def test_disk_writes_are_throttled_but_viewers_get_fresh_memory(tmp_path, monkeypatch):
    now, encodes, writes = [0.0], [], []
    camera = Camera()
    publisher = preview.VisionPreviewPublisher(camera, tmp_path, clock=lambda: now[0],
                                               encoder=lambda image: encodes.append(camera.timestamp) or b"jpeg")
    monkeypatch.setattr(publisher, "notify", lambda: None)
    monkeypatch.setattr(preview, "atomic_write", lambda path, content: writes.append(path.name))
    publisher._publish()
    for stamp in (1, 2, 3, 4):
        now[0] = stamp
        camera.timestamp += 1
        publisher._publish()
    assert len(writes) == 2 and len(encodes) == 1
    publisher.touch_viewer()
    publisher._publish()
    assert publisher.state()["frame_version"] == "5"
    assert len(encodes) == 2 and len(writes) == 2
    now[0] = 5
    camera.timestamp = 6
    publisher._publish()
    assert len(writes) == 4
    assert publisher.frame("6") == b"jpeg"
    assert publisher.frame("5") is None
    assert publisher.state()["last_percept"]["timestamp"] == 6
    now[0] = 21
    publisher._publish()  # compatibility write; no change -> no re-encode
    count = len(encodes)
    now[0] = 22
    camera.timestamp = 7
    publisher._publish()
    assert len(encodes) == count, "expired viewer kept JPEG encoding active"


def test_disk_failure_keeps_live_memory_and_throttles_retry(tmp_path, monkeypatch):
    now, attempts = [0.0], []
    camera = Camera()
    publisher = preview.VisionPreviewPublisher(camera, tmp_path, clock=lambda: now[0], encoder=lambda _: b"jpeg")

    def fail(path, content):
        attempts.append(path)
        raise OSError("disk unavailable")

    monkeypatch.setattr(preview, "atomic_write", fail)
    with pytest.raises(OSError):
        publisher._publish()
    assert publisher.state()["frame_available"]
    now[0] = 1
    camera.timestamp = 2
    publisher._publish()
    assert len(attempts) == 1
    assert publisher.state()["last_percept"]["timestamp"] == 2


def test_atomic_publication_preserves_complete_old_file_until_replace(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    target.write_text('{"version":"old"}')
    replace = preview.os.replace

    def inspect_before_replace(source, destination):
        assert json.loads(target.read_text()) == {"version": "old"}
        with open(source) as stream:
            assert json.load(stream) == {"version": "new"}
        replace(source, destination)

    monkeypatch.setattr(preview.os, "replace", inspect_before_replace)
    preview.atomic_write(target, b'{"version":"new"}')
    assert json.loads(target.read_text()) == {"version": "new"}
    assert list(tmp_path.iterdir()) == [target]


def test_preview_has_owned_image_and_forgets_frame_when_camera_disconnects():
    cortex = VisionCortex()
    sensor = MockSensor()
    sensor.open()
    cortex.add_sensor(sensor)
    cortex.perceive()
    state, image = cortex.preview_snapshot()
    assert state["last_percept"]["quality"] > 0
    assert image is not None
    image[:] = 0
    assert np.any(cortex.preview_snapshot()[1]), "preview exposed the shared frame"
    sensor.close()
    cortex.perceive()
    state, image = cortex.preview_snapshot()
    assert image is None
    assert state["last_percept"]["quality"] == 0


def test_closing_before_first_notification_does_not_start_a_worker(tmp_path):
    publisher = preview.VisionPreviewPublisher(Camera(), tmp_path)
    publisher.close()
    publisher.notify()
    assert publisher._thread is None
    assert not list(tmp_path.iterdir())


def test_pausing_homeostasis_does_not_break_preview_after_resume(tmp_path):
    from types import SimpleNamespace
    camera = Camera()
    publisher = preview.VisionPreviewPublisher(camera, tmp_path, interval=0.01, encoder=lambda _: b"jpeg")
    core = object.__new__(HomeostasisCore)
    core._vision_publisher = publisher
    core._watchdog_stop = threading.Event()
    core.event_logger = SimpleNamespace(log_shutdown=lambda **kwargs: None, flush=lambda: None)
    try:
        core.stop(reason="user_request")
        camera.timestamp = 2
        core._write_vision_state(None)
        wait_for(lambda: publisher.state() is not None and publisher.state()["last_percept"]["timestamp"] == 2)
        core.stop(reason="shutdown")
        assert not publisher._thread.is_alive()
    finally:
        publisher.close()
