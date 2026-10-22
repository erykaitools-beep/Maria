import threading

import pytest

from agent_core.vision.cortex import VisionCortex
from agent_core.vision.modules.scene.analyzer import SceneModule
from agent_core.vision.sensors.mock_sensor import MockSensor


@pytest.mark.parametrize("method", ["describe_scene_llava", "perceive_snapshot"])
def test_manual_description_does_not_enter_or_block_tick(method):
    entered, release, tick_done = (threading.Event() for _ in range(3))
    calls, results = [], []
    sensor = MockSensor()
    sensor.open()
    cortex = VisionCortex()
    cortex.add_sensor(sensor)
    scene = SceneModule()

    def describe(prompt, image):
        calls.append(image)
        entered.set()
        assert release.wait(3)
        return "Osoba przy biurku."

    scene._llava_describe = describe
    cortex.add_module(scene)
    manual = threading.Thread(target=lambda: results.append(getattr(cortex, method)()))
    tick_results = []

    def tick():
        tick_results.append(cortex.perceive())
        tick_done.set()

    tick_thread = threading.Thread(target=tick)
    try:
        manual.start()
        assert entered.wait(2)
        tick_thread.start()
        assert tick_done.wait(1), "slow manual VLM blocked the regular tick"
        assert scene._llava_fn is None
        assert tick_results[0].scene.backend_used == "statistics"
        assert len(calls) == 1
    finally:
        release.set()
        manual.join(3)
        if tick_thread.ident is not None:
            tick_thread.join(3)
        sensor.close()
    assert not manual.is_alive()
    if method == "perceive_snapshot":
        assert results[0].scene.description == "Osoba przy biurku."
        assert results[0].scene.backend_used == "llava"
        assert cortex.last_percept is tick_results[0]
    else:
        assert results == ["Osoba przy biurku."]


def test_manual_snapshot_without_sensor_does_not_reuse_old_frame():
    cortex = VisionCortex()
    sensor = MockSensor()
    sensor.open()
    cortex.add_sensor(sensor)
    scene = SceneModule()
    calls = []
    scene._llava_describe = lambda *args: calls.append(args) or "opis"
    cortex.add_module(scene)
    cortex.perceive()
    sensor.close()
    assert cortex.perceive_snapshot().quality == 0
    assert calls == []


def test_repl_snap_displays_private_description_without_changing_tick(capsys):
    from types import SimpleNamespace
    from agent_core.modules.vision_module import VisionModule
    sensor = MockSensor()
    sensor.open()
    cortex = VisionCortex()
    cortex.add_sensor(sensor)
    scene = SceneModule()
    scene._llava_describe = lambda prompt, image: "Osoba przy biurku."
    cortex.add_module(scene)
    command = VisionModule()
    command.init(SimpleNamespace(vision_cortex=cortex))
    try:
        command._snap()
        assert "Osoba przy biurku." in capsys.readouterr().out
        assert scene._llava_fn is None
        assert cortex.last_percept.scene.backend_used == "statistics"
    finally:
        sensor.close()
