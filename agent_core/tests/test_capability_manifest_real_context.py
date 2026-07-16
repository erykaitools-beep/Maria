"""DH-C regression: the REAL CapabilityManifest against the REAL SharedContext.

The original DH-C bug (2026-06-28) was invisible to test_capability_manifest.py
because that suite feeds a MagicMock ctx (getattr returns a truthy Mock for ANY
attribute name) and a hand-built _FakeManifest. So capability_spec names that did
NOT exist on the real SharedContext -- 'teacher_agent' (learn/exam/review) and
'llm_router' (ask_expert) -- read as available in tests but as UNAVAILABLE live
(702 false 'observe_would_block' steps in decision_traces.jsonl). An armed
CAPABILITY_GATE_ENABLED would then have skipped Maria's core learning loop.

These tests use the real objects so the spec/ctx name mismatch cannot hide.
"""

from agent_core.operator.capability_manifest import CapabilityManifest
from agent_core.registry.shared_context import SharedContext
from agent_core.routing.capability_router import CapabilityRouter
from agent_core.routing.capability_spec import DEFAULT_CAPABILITY_SPECS

CORE_LEARNING_ACTIONS = ("learn", "exam", "review", "ask_expert")


def _noop_handler(*_a, **_k):
    return {"success": True}


def _router_with(*names):
    router = CapabilityRouter()
    for name in names:
        router.register(name, _noop_handler, DEFAULT_CAPABILITY_SPECS[name])
    return router


def _manifest(router, ctx):
    m = CapabilityManifest()
    m.set_capability_router(router)
    m.set_context(ctx)
    return m


def _wire_runtime_subsystems(ctx):
    """Mirror the homeostasis_module wiring that exposes organs living elsewhere."""
    ctx.teacher_agent = object()   # canonical copy on core._teacher_agent
    ctx.llm_router = ctx.brain     # alias of the LLM router
    ctx.play_module = object()     # set on ctx during play wiring


class TestSpecSubsystemNamesAreReal:
    """Structural guard: every subsystem a spec needs must be carriable by ctx."""

    def test_every_spec_subsystem_is_a_known_shared_context_attr(self):
        field_names = set(SharedContext.__dataclass_fields__.keys())
        runtime_attrs = {"play_module"}  # populated at runtime, not a declared field
        known = field_names | runtime_attrs
        missing = {}
        for name, spec in DEFAULT_CAPABILITY_SPECS.items():
            for sub in spec.required_subsystems:
                if sub not in known:
                    missing.setdefault(name, []).append(sub)
        assert not missing, (
            "capability specs name subsystems that SharedContext cannot carry "
            f"(arming the gate would falsely skip them): {missing}"
        )


class TestRealManifestRealContext:
    def test_core_learning_actions_available_after_wiring(self):
        router = _router_with(*CORE_LEARNING_ACTIONS)
        ctx = SharedContext(brain=object())
        _wire_runtime_subsystems(ctx)
        manifest = _manifest(router, ctx)
        for name in CORE_LEARNING_ACTIONS:
            assert manifest.can_do(name), f"{name} must be available after wiring"

    def test_learn_unavailable_without_teacher_wiring(self):
        # The exact original bug: no teacher_agent on ctx -> learn reads unavailable.
        router = _router_with("learn")
        ctx = SharedContext(brain=object())  # teacher_agent intentionally unset
        manifest = _manifest(router, ctx)
        learn = next(c for c in manifest.get_capabilities() if c.name == "learn")
        assert not learn.available
        assert "teacher_agent" in learn.reason_unavailable

    def test_ask_expert_unavailable_without_router_wiring(self):
        router = _router_with("ask_expert")
        ctx = SharedContext()  # no brain, no llm_router
        manifest = _manifest(router, ctx)
        cap = next(c for c in manifest.get_capabilities() if c.name == "ask_expert")
        assert not cap.available
        assert "llm_router" in cap.reason_unavailable
