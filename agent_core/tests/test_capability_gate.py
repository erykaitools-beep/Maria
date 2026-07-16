"""DH-C: the planner consults the self-model (CapabilityManifest) before acting.

"samowiedza -> dzialanie": no point dispatching an action whose subsystems are
absent -- it would only fail. Orthogonal to K7 (authority). Observe-only unless
CAPABILITY_GATE_ENABLED. Tested in isolation (cleanup methods mocked -> no writes).
"""

from unittest.mock import MagicMock

from agent_core.planner.planner_core import PlannerCore
from agent_core.planner.planner_model import Plan, PlanStatus, ActionType
from agent_core.operator.capability_manifest import CapabilityEntry


class _FakeManifest:
    def __init__(self, caps):
        self._caps = caps

    def get_capabilities(self):
        return self._caps


def _cap(name, available, reason=""):
    return CapabilityEntry(name=name, description="", available=available,
                           confidence=0.5, classification="guarded",
                           reason_unavailable=reason)


def _plan(action_type=ActionType.FETCH):
    return Plan(plan_id="p1", timestamp=0.0, goal_id="g1", goal_description="t",
                action_type=action_type, action_params={}, status=PlanStatus.PENDING)


def _planner(caps):
    p = PlannerCore()
    p._capability_manifest = _FakeManifest(caps)
    # mock the file-writing cleanup so the gate can be exercised without I/O
    p._emit_cycle_complete = MagicMock()
    p._log_decision = MagicMock()
    p._save_trace = MagicMock()
    p._save_state = MagicMock()
    return p


def test_enforced_gate_skips_unavailable(monkeypatch):
    monkeypatch.setenv("CAPABILITY_GATE_ENABLED", "1")
    p = _planner([_cap("fetch", False, "brak: knowledge_analyzer")])
    plan = _plan(ActionType.FETCH)
    out = p._capability_gate(plan, trace=None)
    assert out is plan and plan.status == PlanStatus.SKIPPED
    assert plan.result["blocked_by"] == "capability_unavailable"
    assert "knowledge_analyzer" in plan.result["reason"]
    p._log_decision.assert_called_once()


def test_observe_off_does_not_block_but_records(monkeypatch):
    monkeypatch.delenv("CAPABILITY_GATE_ENABLED", raising=False)
    p = _planner([_cap("fetch", False, "brak: knowledge_analyzer")])
    plan = _plan(ActionType.FETCH)
    trace = MagicMock()
    out = p._capability_gate(plan, trace=trace)
    assert out is None and plan.status == PlanStatus.PENDING      # NOT blocked
    assert "observe_would_block" in trace.add_step.call_args.args  # but observed
    p._log_decision.assert_not_called()


def test_available_capability_passes(monkeypatch):
    monkeypatch.setenv("CAPABILITY_GATE_ENABLED", "1")
    p = _planner([_cap("fetch", True)])
    assert p._capability_gate(_plan(ActionType.FETCH), trace=None) is None


def test_unknown_action_left_to_k7(monkeypatch):
    monkeypatch.setenv("CAPABILITY_GATE_ENABLED", "1")
    p = _planner([_cap("learn", False, "x")])      # no 'fetch' entry in manifest
    assert p._capability_gate(_plan(ActionType.FETCH), trace=None) is None


def test_noop_never_gated(monkeypatch):
    monkeypatch.setenv("CAPABILITY_GATE_ENABLED", "1")
    p = _planner([_cap("noop", False, "x")])
    assert p._capability_gate(_plan(ActionType.NOOP), trace=None) is None


def test_no_manifest_no_gate(monkeypatch):
    monkeypatch.setenv("CAPABILITY_GATE_ENABLED", "1")
    p = PlannerCore()
    p._capability_manifest = None
    assert p._capability_gate(_plan(ActionType.FETCH), trace=None) is None


def test_get_capability_entry_lookup():
    p = _planner([_cap("fetch", True), _cap("learn", False)])
    assert p._get_capability_entry("learn").available is False
    assert p._get_capability_entry("nope") is None


def test_broken_manifest_does_not_crash():
    p = PlannerCore()
    broken = MagicMock()
    broken.get_capabilities.side_effect = RuntimeError("boom")
    p._capability_manifest = broken
    assert p._get_capability_entry("fetch") is None        # swallowed, never raises


def test_set_capability_manifest_wires_field():
    p = PlannerCore()
    m = _FakeManifest([])
    p.set_capability_manifest(m)
    assert p._capability_manifest is m
