"""Vision must initialize even when earlier optional modules are unavailable."""

import builtins
import socket
import threading
from types import SimpleNamespace

from agent_core.modules import homeostasis_module
from agent_core.registry import SharedContext
from agent_core.vision.cortex import VisionCortex
from agent_core.vision.sensors.usb_webcam import USBWebcamSensor


def test_vision_starts_after_optional_initializers_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MARIA_BACKGROUND_REASONING", "0")
    monkeypatch.setenv("MARIA_TELEGRAM_INTEGRATION", "0")
    monkeypatch.setenv("MARIA_MARKET_INTEGRATION", "0")
    monkeypatch.setenv("VISION_OBJECT_DETECTOR", "")
    allowed_imports = {
        "agent_core.vision.cortex",
        "agent_core.vision.preprocessing.preprocessor",
        "agent_core.vision.modules.motion.detector",
        "agent_core.vision.modules.scene.analyzer",
        "agent_core.vision.sensors.usb_webcam",
    }
    original_import = builtins.__import__
    unavailable = []

    def import_with_optional_modules_unavailable(name, globals=None, locals=None,
                                                 fromlist=(), level=0):
        # Exercise the real initializer with unavailable optional components.
        # Their real stores, providers and workers must never start in this test.
        if (globals or {}).get("__name__") == homeostasis_module.__name__:
            if name not in allowed_imports:
                unavailable.append(name)
                raise ImportError("Optional component unavailable in startup test")
        return original_import(name, globals, locals, fromlist, level)

    forbidden_attempts = []

    def forbidden(*args, **kwargs):
        forbidden_attempts.append(True)
        raise AssertionError("Startup test attempted network or background work")

    opened = []
    monkeypatch.setattr(USBWebcamSensor, "open", lambda sensor: opened.append(sensor) or True)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(threading.Thread, "start", forbidden)
    monkeypatch.setattr(builtins, "__import__", import_with_optional_modules_unavailable)
    mounted = []
    core = SimpleNamespace(set_vision_cortex=mounted.append)
    ctx = SharedContext(homeostasis_core=core)

    assert homeostasis_module.HomeostasisModule().init(ctx) is True
    assert "agent_core.llm.model_scheduler" in unavailable
    assert isinstance(ctx.vision_cortex, VisionCortex)
    assert mounted == [ctx.vision_cortex]
    assert len(opened) == 1
    assert opened[0].sensor_id == "usb-0"
    assert not forbidden_attempts
