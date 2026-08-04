"""Tests for CapabilityManifest (K15)."""

from unittest.mock import MagicMock

import pytest

from agent_core.operator.capability_manifest import (
    CapabilityEntry,
    CapabilityManifest,
    Limitation,
)
from agent_core.routing.capability_router import CapabilityRouter
from agent_core.routing.capability_spec import CapabilitySpec
from agent_core.tests.spec_helpers import specced


def _make_router(specs_with_handlers=None):
    """Create a mock CapabilityRouter with specs and handlers."""
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
    router = specced(CapabilityRouter, _specs=specs, _handlers=handlers)
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


class TestSummaryExecutionCounts:
    """get_summary shows raw execution counts from real planner history.

    Uses a REAL HonestyProtocol over a tmp decisions file (repo lesson:
    mocks swallow phantom integrations). Wiring is two-way like prod
    (honesty<->manifest), so any future edit that routes the summary
    through check_capability_claim explodes here with RecursionError.
    """

    @staticmethod
    def _rec(action, success):
        import json as _json  # noqa: F401  (kept local pattern explicit)
        return {
            "action_type": action,
            "status": "completed" if success else "failed",
            "result": {"success": success},
            "timestamp": 1700000000,
        }

    def _manifest_with_history(self, tmp_path, records, caps=None):
        import json
        from agent_core.operator.honesty_protocol import HonestyProtocol

        decisions = tmp_path / "planner_decisions.jsonl"
        with open(decisions, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        m = CapabilityManifest()
        router = _make_router(caps or {"learn": True, "exam": True})
        ctx = MagicMock()
        ctx.test_sub = MagicMock()
        m.set_capability_router(router)
        m.set_context(ctx)
        m.set_mode_fn(lambda: "ACTIVE")

        honesty = HonestyProtocol(decisions_path=decisions)
        honesty.set_capability_manifest(m)  # prod-shaped two-way wiring
        m.set_honesty_protocol(honesty)
        return m

    def test_counts_shown_for_evidenced_capability(self, tmp_path):
        records = [self._rec("learn", True)] * 3 + [self._rec("learn", False)]
        m = self._manifest_with_history(tmp_path, records)
        summary = m.get_summary()
        assert "(3/4 ok)" in summary
        # The static confidence percent fiction is gone from this view.
        assert "%" not in summary

    def test_no_history_no_number(self, tmp_path):
        records = [self._rec("learn", True)] * 3
        m = self._manifest_with_history(tmp_path, records)
        summary = m.get_summary()
        exam_line = next(l for l in summary.splitlines() if "Test exam" in l)
        assert "(" not in exam_line  # honest blank, no fabricated prior

    def test_below_min_attempts_no_number(self, tmp_path):
        records = [self._rec("learn", True)] * 2  # < MIN_EVIDENCE_ATTEMPTS
        m = self._manifest_with_history(tmp_path, records)
        learn_line = next(
            l for l in m.get_summary().splitlines() if "Test learn" in l
        )
        assert "ok)" not in learn_line

    def test_degradation_rest_not_counted(self, tmp_path):
        degr = {
            "action_type": "learn",
            "status": "skipped",
            "result": {"success": False, "skipped": True,
                       "blocked_by": "degradation",
                       "reason": "mode=reduced: heavy LLM actions blocked"},
            "timestamp": 1700000000,
        }
        records = [self._rec("learn", True)] * 3 + [degr] * 12
        m = self._manifest_with_history(tmp_path, records)
        assert "(3/3 ok)" in m.get_summary()  # 12 blocked rests invisible

    def test_no_honesty_wired_summary_still_works(self):
        m = CapabilityManifest()
        router = _make_router({"learn": True})
        ctx = MagicMock()
        ctx.test_sub = MagicMock()
        m.set_capability_router(router)
        m.set_context(ctx)
        m.set_mode_fn(lambda: "ACTIVE")
        summary = m.get_summary()
        assert "mozliwosci" in summary.lower()
        assert "ok)" not in summary
