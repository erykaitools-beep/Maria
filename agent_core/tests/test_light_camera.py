"""Light camera regressions; synthetic frames, no camera, network or weights."""

import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from agent_core.vision.change_gate import create_change_gate
from agent_core.vision.cortex import VisionCortex
from agent_core.vision.light_change_gate import OpenCVSceneChangeGate
from agent_core.vision.vision_advisor import VisionAdvisor


def _room():
    image = np.full((72, 96, 3), 80, dtype=np.uint8)
    image[12:60, 12:40] = (40, 100, 180)
    image[30:55, 60:85] = (160, 80, 40)
    return image


def _save(tmp_path, image, name="frame.png"):
    path = str(tmp_path / name)
    assert cv2.imwrite(path, image)
    return path


def test_repeated_image_is_suppressed(tmp_path):
    gate = OpenCVSceneChangeGate()
    path = _save(tmp_path, _room())
    assert gate.evaluate(path).is_new
    decision = gate.evaluate(path)
    assert not decision.is_new
    assert decision.reason == "ta_sama_scena"


def test_global_brightness_does_not_look_like_a_new_room(tmp_path):
    gate = OpenCVSceneChangeGate()
    gate.evaluate(_save(tmp_path, _room()))
    dimmed = (_room().astype(np.float32) * 0.5).astype(np.uint8)
    assert not gate.evaluate(_save(tmp_path, dimmed, "dimmed.png")).is_new


def test_rearrangement_with_same_colours_is_detected(tmp_path):
    gate = OpenCVSceneChangeGate()
    gate.evaluate(_save(tmp_path, _room()))
    # The histogram is identical; the spatial arrangement is different.
    moved = np.flip(_room(), axis=1).copy()
    assert gate.evaluate(_save(tmp_path, moved, "moved.png")).is_new


def test_local_change_is_detected(tmp_path):
    gate = OpenCVSceneChangeGate()
    gate.evaluate(_save(tmp_path, _room()))
    changed = _room()
    changed[5:20, 50:65] = (200, 180, 160)
    assert gate.evaluate(_save(tmp_path, changed, "changed.png")).is_new


def test_reference_does_not_follow_slow_drift(tmp_path):
    gate = OpenCVSceneChangeGate()
    gate.evaluate(_save(tmp_path, _room()))
    reference = gate._reference.copy()
    changed = _room()
    changed[0:2, 0:2] = 160
    assert not gate.evaluate(_save(tmp_path, changed)).is_new
    np.testing.assert_array_equal(gate._reference, reference)
    changed[0:20, 0:20] = 160
    assert gate.evaluate(_save(tmp_path, changed)).is_new


def test_measurement_without_remembering_does_not_set_reference(tmp_path):
    gate = OpenCVSceneChangeGate()
    assert gate.evaluate(_save(tmp_path, _room()), remember=False).is_new
    assert not gate.has_reference


def test_broken_image_cannot_silence_vision(tmp_path):
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"not an image")
    gate = OpenCVSceneChangeGate()
    decision = gate.evaluate(str(path))
    assert decision.is_new
    assert decision.reason == "blad_pomiaru"
    assert not gate.has_reference


def test_cooling_refuses_work_before_reading_image(monkeypatch, tmp_path,
                                                 isolated_local_compute_coordinator):
    isolated_local_compute_coordinator.enter_cooling(80.0)

    def forbidden(*args, **kwargs):
        pytest.fail("image processing started during thermal cooling")

    monkeypatch.setattr(cv2, "imread", forbidden)
    gate = OpenCVSceneChangeGate(coordinator=isolated_local_compute_coordinator)
    decision = gate.evaluate(str(tmp_path / "missing.jpg"))
    assert not decision.is_new
    assert decision.reason == "chlodzenie"
    assert not gate.has_reference


def test_public_configuration_defaults_to_light_opencv(monkeypatch):
    monkeypatch.delenv("VISION_CHANGE_BACKEND", raising=False)
    assert isinstance(create_change_gate(), OpenCVSceneChangeGate)
    monkeypatch.setenv("VISION_CHANGE_BACKEND", "opencv")
    assert isinstance(create_change_gate(), OpenCVSceneChangeGate)


def test_invalid_backend_is_reported(monkeypatch):
    monkeypatch.setenv("VISION_CHANGE_BACKEND", "typo")
    with pytest.raises(ValueError, match="VISION_CHANGE_BACKEND"):
        create_change_gate()


class _ImageCortex:
    def __init__(self, image):
        self.image = image
        self.vlm_calls = 0

    def save_last_frame(self, path):
        return cv2.imwrite(path, self.image)

    def describe_snapshot(self, **kwargs):
        self.vlm_calls += 1
        raise AssertionError("a confident YOLO result must not wake the VLM")


def test_yolo_probe_does_not_wake_vlm_and_repeat_does_not_ping(monkeypatch, tmp_path):
    monkeypatch.setenv("VISION_CHANGE_GATE", "on")
    monkeypatch.setenv("VISION_CHANGE_BACKEND", "opencv")
    pings = []
    cortex = _ImageCortex(_room())
    advisor = VisionAdvisor(cortex, notify_fn=pings.append,
                            snapshot_path=str(tmp_path / "snapshot.png"))
    advisor._describe_and_notify(fast_description="Rozpoznaje osobe.")
    assert len(pings) == 1
    advisor._describe_and_notify(probe=True, fast_description="Rozpoznaje osobe.")
    assert len(pings) == 1
    cortex.image = np.flip(_room(), axis=1).copy()
    advisor._describe_and_notify(probe=True, fast_description="Rozpoznaje osobe.")
    assert len(pings) == 2
    assert cortex.vlm_calls == 0
    assert advisor._probe_pings == 1


def test_yolo_probe_without_fresh_photo_cannot_reuse_old_photo(monkeypatch, tmp_path):
    monkeypatch.setenv("VISION_CHANGE_GATE", "on")
    monkeypatch.setenv("VISION_CHANGE_BACKEND", "opencv")
    pings = []
    cortex = _ImageCortex(_room())
    advisor = VisionAdvisor(cortex, notify_fn=pings.append,
                            snapshot_path=str(tmp_path / "snapshot.png"))
    advisor._describe_and_notify(fast_description="Rozpoznaje osobe.")
    monkeypatch.setattr(cortex, "save_last_frame", lambda path: False)
    advisor._describe_and_notify(probe=True, fast_description="Rozpoznaje osobe.")
    assert len(pings) == 1
    assert cortex.vlm_calls == 0


def test_importing_camera_types_does_not_import_onnxruntime():
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; from agent_core.vision.cortex import VisionCortex; "
         "assert 'onnxruntime' not in sys.modules"],
        capture_output=True, text=True, timeout=15,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode == 0, result.stderr


def test_background_yolo_photo_keeps_triggering_frame(monkeypatch, tmp_path):
    from types import SimpleNamespace

    class DeferredThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args

        def start(self):
            pass

        def is_alive(self):
            return False

    monkeypatch.setenv("VISION_CHANGE_GATE", "off")
    monkeypatch.setattr("agent_core.vision.vision_advisor.threading.Thread", DeferredThread)
    cortex = VisionCortex()
    original = _room()
    cortex._last_frame_image = original.copy()
    snapshot = str(tmp_path / "photo.png")
    pings = []
    advisor = VisionAdvisor(cortex, notify_fn=pings.append, snapshot_path=snapshot)
    event = SimpleNamespace(event_type="vision_motion",
                            payload={"objects_summary": "Rozpoznaje osobe."})
    assert advisor.maybe_react([event], now=1000.0)
    # Simulate the next camera tick before the worker is scheduled.
    cortex._last_frame_image = np.flip(original, axis=1).copy()
    advisor._thread.target(*advisor._thread.args)
    np.testing.assert_array_equal(cv2.imread(snapshot), original)
    assert len(pings) == 1
