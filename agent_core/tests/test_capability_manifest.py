"""Tests for CapabilityManifest (K15)."""

from unittest.mock import MagicMock

import pytest

from agent_core.operator.capability_manifest import (
    CapabilityEntry,
    CapabilityManifest,
    Limitation,
)
from agent_core.routing.capability_spec import CapabilitySpec


def _make_router(specs_with_handlers=None):
    """Create a mock CapabilityRouter with specs and handlers."""
    router = MagicMock()
    specs = {}
    handlers = {}
    for name, has_handler in (specs_with_handlers or {}).items():
        specs[name] = CapabilitySpec(
            name=name,
            description=f"Test {name}",
            required_subsystems=("test_sub",) if name != "noop" else (),
            k7_classification="free",
            tags=("test",),
        )
        if has_handler:
            handlers[name] = MagicMock()
    router._specs = specs
    router._handlers = handlers
    return router


def _make_ctx(**subsystems):
    """Create a mock SharedContext with specific subsystems."""
    ctx = MagicMock()
    # Reset all attributes to None first
    ctx.configure_mock(**{k: MagicMock() if v else None for k, v in subsystems.items()})
    return ctx


class TestCapabilityEntry:
    def test_to_dict(self):
        entry = CapabilityEntry(
            name="learn",
            description="Learn chunks",
            available=True,
            confidence=0.95,
            classification="free",
            tags=("learning",),
        )
        d = entry.to_dict()
        assert d["name"] == "learn"
        assert d["available"] is True
        assert d["confidence"] == 0.95
        assert "reason_unavailable" not in d

    def test_to_dict_unavailable(self):
        entry = CapabilityEntry(
            name="effector",
            description="OpenClaw",
            available=False,
            confidence=0.0,
            classification="restricted",
            reason_unavailable="brak: openclaw_client",
        )
        d = entry.to_dict()
        assert d["available"] is False
        assert "openclaw" in d["reason_unavailable"]


class TestLimitation:
    def test_to_dict(self):
        lim = Limitation(
            category="hardware",
            description="No GPU",
            severity="warning",
        )
        d = lim.to_dict()
        assert d["category"] == "hardware"
        assert d["severity"] == "warning"


class TestCapabilityManifest:
    @pytest.fixture
    def manifest(self):
        m = CapabilityManifest()
        router = _make_router({
            "learn": True,
            "exam": True,
            "noop": True,
            "effector": True,
        })
        ctx = MagicMock()
        ctx.test_sub = MagicMock()  # subsystem available
        m.set_capability_router(router)
        m.set_context(ctx)
        m.set_mode_fn(lambda: "ACTIVE")
        return m

    def test_get_capabilities(self, manifest):
        caps = manifest.get_capabilities()
        assert len(caps) == 4
        names = [c.name for c in caps]
        assert "learn" in names
        assert "noop" in names

    def test_all_available(self, manifest):
        available = manifest.get_available()
        assert len(available) == 4

    def test_handler_missing(self):
        m = CapabilityManifest()
        router = _make_router({"learn": True, "exam": False})
        m.set_capability_router(router)
        caps = m.get_capabilities()
        exam = next(c for c in caps if c.name == "exam")
        assert exam.available is False
        assert "handler" in exam.reason_unavailable

    def test_subsystem_missing(self):
        m = CapabilityManifest()
        router = _make_router({"learn": True})
        ctx = MagicMock(spec=[])  # empty context, no attributes
        m.set_capability_router(router)
        m.set_context(ctx)
        caps = m.get_capabilities()
        learn = next(c for c in caps if c.name == "learn")
        assert learn.available is False
        assert "test_sub" in learn.reason_unavailable

    def test_can_do(self, manifest):
        assert manifest.can_do("learn") is True
        assert manifest.can_do("nonexistent") is False

    def test_get_limitations(self, manifest):
        limits = manifest.get_limitations()
        assert len(limits) >= 3
        categories = [l.category for l in limits]
        assert "hardware" in categories

    def test_get_limitations_non_active_mode(self):
        m = CapabilityManifest()
        m.set_mode_fn(lambda: "REDUCED")
        limits = m.get_limitations()
        mode_limits = [l for l in limits if "REDUCED" in l.description]
        assert len(mode_limits) == 1

    def test_get_summary(self, manifest):
        summary = manifest.get_summary()
        assert "mozliwosci" in summary.lower()
        assert "learn" in summary.lower() or "Learn" in summary

    def test_to_dict(self, manifest):
        data = manifest.to_dict()
        assert "capabilities" in data
        assert "limitations" in data
        assert data["available_count"] == 4
        assert data["mode"] == "ACTIVE"

    def test_no_router(self):
        m = CapabilityManifest()
        assert m.get_capabilities() == []
        assert m.can_do("learn") is False

    def test_confidence_levels(self, manifest):
        caps = manifest.get_capabilities()
        learn = next(c for c in caps if c.name == "learn")
        effector = next(c for c in caps if c.name == "effector")
        # Internal = high confidence, effector = lower
        assert learn.confidence > effector.confidence

    def test_sorted_available_first(self, manifest):
        """Available capabilities come before unavailable."""
        # Make one unavailable
        m = CapabilityManifest()
        router = _make_router({"learn": True, "exam": False})
        ctx = MagicMock()
        ctx.test_sub = MagicMock()
        m.set_capability_router(router)
        m.set_context(ctx)
        caps = m.get_capabilities()
        # First should be available, last should be unavailable
        assert caps[0].available is True
        assert caps[-1].available is False
