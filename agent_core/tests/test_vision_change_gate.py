"""Public gate configuration. No models, camera, or subprocess execution."""
import builtins
import importlib
import sys
from types import ModuleType

import pytest

from agent_core.vision.change_gate import (
    GateDecision, change_gate_backend, create_change_gate, gate_mode,
)


@pytest.mark.parametrize("value,expected", [
    (None,"off"),("","off"),("off","off"),("false","off"),("0","off"),
    ("observe","observe"),(" ON ","on"),("1","on"),("true","on"),
])
def test_gate_modes(monkeypatch, value, expected):
    monkeypatch.delenv("VISION_CHANGE_GATE", raising=False)
    if value is not None:
        monkeypatch.setenv("VISION_CHANGE_GATE",value)
    assert gate_mode() == expected


def test_invalid_mode_is_not_silently_disabled(monkeypatch):
    monkeypatch.setenv("VISION_CHANGE_GATE","obesrve")
    with pytest.raises(ValueError, match="VISION_CHANGE_GATE must"):
        gate_mode()


def test_default_and_explicit_backend_are_public_light_gate(monkeypatch):
    monkeypatch.delenv("VISION_CHANGE_BACKEND", raising=False)
    assert change_gate_backend() == "opencv"
    module = ModuleType("agent_core.vision.light_change_gate")
    class Light:
        pass
    module.OpenCVSceneChangeGate = Light
    monkeypatch.setitem(sys.modules,module.__name__,module)
    assert isinstance(create_change_gate(), Light)
    monkeypatch.setenv("VISION_CHANGE_BACKEND"," OpenCV ")
    assert isinstance(create_change_gate(), Light)


@pytest.mark.parametrize("value", ["", "unknown", "disabled-model"])
def test_unsupported_backend_has_no_fallback(monkeypatch,value):
    monkeypatch.setenv("VISION_CHANGE_BACKEND",value)
    with pytest.raises(ValueError,match="VISION_CHANGE_BACKEND must be opencv"):
        create_change_gate()


def test_factory_imports_no_optional_image_or_model_libraries(monkeypatch):
    import agent_core.vision.change_gate as module
    original = builtins.__import__
    def guarded(name,*args,**kwargs):
        assert name.split('.')[0] not in {"numpy","cv2","torch","subprocess"}
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,"__import__",guarded)
    importlib.reload(module)
    assert module.gate_mode() in {"off","observe","on"}


def test_gate_decision_preserves_honest_measurement_fields():
    assert GateDecision(False,0.98,0.016,"ta_sama_scena").to_dict() == {
        "is_new":False,"similarity":0.98,"seconds":0.02,"reason":"ta_sama_scena"}
    assert GateDecision(False,None,0,"chlodzenie").to_dict()["similarity"] is None
