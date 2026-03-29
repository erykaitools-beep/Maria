"""
Tests for Capability/Task Router.

Tests registry operations, dispatch, discovery, K7 integration,
and handler factories.
"""

import pytest
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

from agent_core.routing.capability_spec import CapabilitySpec, DEFAULT_CAPABILITY_SPECS
from agent_core.routing.capability_router import CapabilityRouter
from agent_core.routing import CapabilityRouter as ImportedRouter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class MockActionType(Enum):
    LEARN = "learn"
    EXAM = "exam"
    NOOP = "noop"
    FETCH = "fetch"
    EFFECTOR = "effector"
    UNKNOWN = "unknown_action"


@dataclass
class MockPlan:
    action_type: MockActionType
    action_params: Dict[str, Any]
    goal_id: Optional[str] = None
    goal_description: str = ""


@pytest.fixture
def router():
    return CapabilityRouter()


@pytest.fixture
def learn_spec():
    return DEFAULT_CAPABILITY_SPECS["learn"]


@pytest.fixture
def noop_spec():
    return DEFAULT_CAPABILITY_SPECS["noop"]


def _ok_handler(plan):
    return {"success": True, "action": plan.action_type.value}


def _fail_handler(plan):
    raise RuntimeError("handler exploded")


# ---------------------------------------------------------------------------
# CapabilitySpec tests
# ---------------------------------------------------------------------------

class TestCapabilitySpec:
    def test_frozen(self):
        spec = CapabilitySpec(
            name="test",
            description="Test capability",
            required_subsystems=("a", "b"),
            k7_classification="guarded",
        )
        with pytest.raises(AttributeError):
            spec.name = "changed"

    def test_default_tags(self):
        spec = CapabilitySpec(
            name="x", description="", required_subsystems=(),
            k7_classification="free",
        )
        assert spec.tags == ()

    def test_with_tags(self):
        spec = CapabilitySpec(
            name="x", description="", required_subsystems=(),
            k7_classification="free", tags=("a", "b"),
        )
        assert spec.tags == ("a", "b")

    def test_equality(self):
        s1 = CapabilitySpec("a", "d", (), "free")
        s2 = CapabilitySpec("a", "d", (), "free")
        assert s1 == s2

    def test_default_specs_complete(self):
        """All 13 known action types have specs."""
        expected = {
            "learn", "exam", "review", "evaluate", "noop",
            "maintenance", "fetch", "experiment", "effector",
            "self_analyze", "creative", "ask_expert", "validate",
        }
        assert set(DEFAULT_CAPABILITY_SPECS.keys()) == expected

    def test_default_specs_k7_values(self):
        """K7 classifications match action_class.py."""
        free = {"learn", "exam", "review", "evaluate", "noop"}
        guarded = {
            "maintenance", "fetch", "experiment", "self_analyze",
            "creative", "ask_expert", "validate",
        }
        restricted = {"effector"}

        for name in free:
            assert DEFAULT_CAPABILITY_SPECS[name].k7_classification == "free"
        for name in guarded:
            assert DEFAULT_CAPABILITY_SPECS[name].k7_classification == "guarded"
        for name in restricted:
            assert DEFAULT_CAPABILITY_SPECS[name].k7_classification == "restricted"

    def test_spec_name_matches_key(self):
        """Each spec's name field matches its dict key."""
        for key, spec in DEFAULT_CAPABILITY_SPECS.items():
            assert spec.name == key


# ---------------------------------------------------------------------------
# CapabilityRouter - registry tests
# ---------------------------------------------------------------------------

class TestRouterRegistry:
    def test_register_and_lookup(self, router, learn_spec):
        router.register("learn", _ok_handler, learn_spec)
        assert router.is_available("learn")
        assert router.get_spec("learn") == learn_spec

    def test_register_duplicate_raises(self, router, learn_spec):
        router.register("learn", _ok_handler, learn_spec)
        with pytest.raises(ValueError, match="already registered"):
            router.register("learn", _ok_handler, learn_spec)

    def test_register_name_mismatch_raises(self, router):
        spec = CapabilitySpec("wrong", "d", (), "free")
        with pytest.raises(ValueError, match="mismatch"):
            router.register("learn", _ok_handler, spec)

    def test_unregister(self, router, learn_spec):
        router.register("learn", _ok_handler, learn_spec)
        assert router.unregister("learn")
        assert not router.is_available("learn")

    def test_unregister_nonexistent(self, router):
        assert not router.unregister("ghost")

    def test_registered_count(self, router, learn_spec, noop_spec):
        assert router.registered_count == 0
        router.register("learn", _ok_handler, learn_spec)
        assert router.registered_count == 1
        router.register("noop", _ok_handler, noop_spec)
        assert router.registered_count == 2

    def test_is_available_false(self, router):
        assert not router.is_available("nonexistent")

    def test_get_spec_none(self, router):
        assert router.get_spec("nonexistent") is None


# ---------------------------------------------------------------------------
# CapabilityRouter - dispatch tests
# ---------------------------------------------------------------------------

class TestRouterDispatch:
    def test_dispatch_success(self, router, learn_spec):
        router.register("learn", _ok_handler, learn_spec)
        plan = MockPlan(MockActionType.LEARN, {})
        result = router.dispatch(plan)
        assert result["success"] is True
        assert result["action"] == "learn"
        assert "duration_ms" in result

    def test_dispatch_unknown_action(self, router):
        plan = MockPlan(MockActionType.UNKNOWN, {})
        result = router.dispatch(plan)
        assert result["success"] is False
        assert "No handler registered" in result["error"]

    def test_dispatch_handler_exception(self, router, learn_spec):
        router.register("learn", _fail_handler, learn_spec)
        plan = MockPlan(MockActionType.LEARN, {})
        result = router.dispatch(plan)
        assert result["success"] is False
        assert "handler exploded" in result["error"]
        assert "duration_ms" in result

    def test_dispatch_timing(self, router, noop_spec):
        router.register("noop", _ok_handler, noop_spec)
        plan = MockPlan(MockActionType.NOOP, {})
        result = router.dispatch(plan)
        assert result["duration_ms"] >= 0

    def test_dispatch_preserves_result_keys(self, router, learn_spec):
        def rich_handler(plan):
            return {"success": True, "chunks": 5, "extra": "data"}

        router.register("learn", rich_handler, learn_spec)
        plan = MockPlan(MockActionType.LEARN, {})
        result = router.dispatch(plan)
        assert result["chunks"] == 5
        assert result["extra"] == "data"
        assert "duration_ms" in result


# ---------------------------------------------------------------------------
# CapabilityRouter - discovery tests
# ---------------------------------------------------------------------------

class TestRouterDiscovery:
    def test_list_capabilities_empty(self, router):
        assert router.list_capabilities() == []

    def test_list_capabilities_sorted(self, router, learn_spec, noop_spec):
        router.register("noop", _ok_handler, noop_spec)
        router.register("learn", _ok_handler, learn_spec)
        caps = router.list_capabilities()
        assert [c.name for c in caps] == ["learn", "noop"]

    def test_get_status(self, router, learn_spec):
        router.register("learn", _ok_handler, learn_spec)
        status = router.get_status()
        assert status["registered"] == 1
        assert len(status["capabilities"]) == 1
        cap = status["capabilities"][0]
        assert cap["name"] == "learn"
        assert cap["classification"] == "free"
        assert cap["tags"] == ["learning", "teacher"]


# ---------------------------------------------------------------------------
# CapabilityRouter - K7 integration
# ---------------------------------------------------------------------------

class TestRouterK7:
    def test_classification_known(self, router, learn_spec):
        router.register("learn", _ok_handler, learn_spec)
        assert router.get_k7_classification("learn") == "free"

    def test_classification_unknown_defaults_restricted(self, router):
        assert router.get_k7_classification("unknown") == "restricted"

    def test_classification_guarded(self, router):
        spec = DEFAULT_CAPABILITY_SPECS["fetch"]
        router.register("fetch", _ok_handler, spec)
        assert router.get_k7_classification("fetch") == "guarded"

    def test_classification_restricted(self, router):
        spec = DEFAULT_CAPABILITY_SPECS["effector"]
        router.register("effector", _ok_handler, spec)
        assert router.get_k7_classification("effector") == "restricted"


# ---------------------------------------------------------------------------
# Handler factory tests
# ---------------------------------------------------------------------------

class TestHandlerFactories:
    """Test handler factories with mocked subsystems."""

    def test_make_noop_handler(self):
        from agent_core.routing.handlers import make_noop_handler
        handler = make_noop_handler()
        plan = MockPlan(MockActionType.NOOP, {})
        result = handler(plan)
        assert result == {"success": True, "action": "noop"}

    def test_make_learn_handler_no_teacher(self):
        from agent_core.routing.handlers import make_learn_handler
        handler = make_learn_handler(teacher_agent=None)
        plan = MockPlan(MockActionType.LEARN, {})
        result = handler(plan)
        assert result["success"] is False
        assert "No teacher" in result["error"]

    def test_make_learn_handler_success(self):
        from agent_core.routing.handlers import make_learn_handler
        teacher = MagicMock()
        teacher.run_session.return_value = {
            "stats": {"chunks_learned": 3, "strategies_executed": 1}
        }
        handler = make_learn_handler(teacher_agent=teacher)
        plan = MockPlan(MockActionType.LEARN, {})
        result = handler(plan)
        assert result["success"] is True
        assert result["chunks_learned"] == 3

    def test_make_learn_handler_idle(self):
        from agent_core.routing.handlers import make_learn_handler
        teacher = MagicMock()
        teacher.run_session.return_value = {
            "stats": {"chunks_learned": 0, "idle_reason": "no_files", "filtered_out_count": 5}
        }
        handler = make_learn_handler(teacher_agent=teacher)
        plan = MockPlan(MockActionType.LEARN, {})
        result = handler(plan)
        assert result["success"] is False
        assert result["idle_reason"] == "no_files"
        assert result["filtered_out_count"] == 5

    def test_make_exam_handler_no_teacher(self):
        from agent_core.routing.handlers import make_exam_handler
        handler = make_exam_handler(teacher_agent=None)
        plan = MockPlan(MockActionType.EXAM, {})
        result = handler(plan)
        assert result["success"] is False

    def test_make_exam_handler_success(self):
        from agent_core.routing.handlers import make_exam_handler
        teacher = MagicMock()
        teacher.run_session.return_value = {
            "stats": {
                "exams_run": 1, "exams_passed": 1,
                "last_exam_score": 0.85, "last_exam_file": "test.txt",
            }
        }
        handler = make_exam_handler(teacher_agent=teacher)
        plan = MockPlan(MockActionType.EXAM, {})
        result = handler(plan)
        assert result["success"] is True
        assert result["score"] == 0.85

    def test_make_review_handler_success(self):
        from agent_core.routing.handlers import make_review_handler
        teacher = MagicMock()
        teacher.run_session.return_value = {
            "stats": {"strategies_executed": 2}
        }
        handler = make_review_handler(teacher_agent=teacher)
        plan = MockPlan(MockActionType.LEARN, {})
        result = handler(plan)
        assert result["success"] is True
        assert result["strategies_executed"] == 2

    def test_make_evaluate_handler_no_observer(self):
        from agent_core.routing.handlers import make_evaluate_handler
        handler = make_evaluate_handler(evaluation_observer=None)
        plan = MockPlan(MockActionType.LEARN, {})
        result = handler(plan)
        assert result["success"] is False

    def test_make_evaluate_handler_success(self):
        from agent_core.routing.handlers import make_evaluate_handler
        observer = MagicMock()
        report = MagicMock()
        report.report_id = "rpt-1"
        report.metrics = {"learning_velocity": 0.5}
        report.recommendations = ["study more"]
        observer.generate_report.return_value = report
        handler = make_evaluate_handler(evaluation_observer=observer)
        plan = MockPlan(MockActionType.LEARN, {"period_hours": 2.0})
        result = handler(plan)
        assert result["success"] is True
        assert result["report_id"] == "rpt-1"

    def test_make_maintenance_handler_no_core(self):
        from agent_core.routing.handlers import make_maintenance_handler
        handler = make_maintenance_handler(homeostasis_core=None)
        plan = MockPlan(MockActionType.LEARN, {})
        result = handler(plan)
        assert result["success"] is True
        assert result["action"] == "maintenance_noop"

    def test_make_maintenance_handler_success(self):
        from agent_core.routing.handlers import make_maintenance_handler
        core = MagicMock()
        state = MagicMock()
        state.health_score = 0.95
        state.interpreted_state = {"cpu_load": 0.3}
        state.mode = MagicMock()
        state.mode.value = "active"
        core.get_state.return_value = state
        handler = make_maintenance_handler(homeostasis_core=core)
        plan = MockPlan(MockActionType.LEARN, {})
        result = handler(plan)
        assert result["success"] is True
        assert result["health_score"] == 0.95

    def test_make_fetch_handler_no_analyzer(self):
        from agent_core.routing.handlers import make_fetch_handler
        handler = make_fetch_handler(knowledge_analyzer=None)
        plan = MockPlan(MockActionType.FETCH, {})
        result = handler(plan)
        assert result["success"] is False

    def test_make_experiment_handler_no_system(self):
        from agent_core.routing.handlers import make_experiment_handler
        handler = make_experiment_handler(experiment_system=None)
        plan = MockPlan(MockActionType.LEARN, {})
        result = handler(plan)
        assert result["success"] is False

    def test_make_experiment_handler_no_proposal(self):
        from agent_core.routing.handlers import make_experiment_handler
        system = MagicMock()
        handler = make_experiment_handler(experiment_system=system)
        plan = MockPlan(MockActionType.LEARN, {})
        result = handler(plan)
        assert result["success"] is False
        assert "proposal_id" in result["error"]

    def test_make_experiment_handler_success(self):
        from agent_core.routing.handlers import make_experiment_handler
        system = MagicMock()
        report = MagicMock()
        report.report_id = "exp-1"
        report.recommendation = "ADOPT"
        report.confidence = 0.8
        report.conclusion = "Works well"
        system.run_experiment.return_value = report
        handler = make_experiment_handler(experiment_system=system)
        plan = MockPlan(MockActionType.LEARN, {"proposal_id": "p-1"})
        result = handler(plan)
        assert result["success"] is True
        assert result["recommendation"] == "ADOPT"

    def test_make_effector_handler_no_client(self):
        from agent_core.routing.handlers import make_effector_handler
        handler = make_effector_handler(openclaw_client=None)
        plan = MockPlan(MockActionType.EFFECTOR, {})
        result = handler(plan)
        assert result["success"] is False

    def test_make_effector_handler_no_tool_name(self):
        from agent_core.routing.handlers import make_effector_handler
        client = MagicMock()
        handler = make_effector_handler(openclaw_client=client)
        plan = MockPlan(MockActionType.EFFECTOR, {})
        result = handler(plan)
        assert result["success"] is False
        assert "tool_name" in result["error"]

    def test_make_effector_handler_success(self):
        from agent_core.routing.handlers import make_effector_handler
        client = MagicMock()
        client.invoke_tool.return_value = {"ok": True, "result": "done"}
        handler = make_effector_handler(openclaw_client=client)
        plan = MockPlan(MockActionType.EFFECTOR, {"tool_name": "exec", "tool_args": {"cmd": "ls"}})
        result = handler(plan)
        assert result["success"] is True
        assert result["tool_result"] == "done"

    def test_make_self_analyze_handler_no_sa(self):
        from agent_core.routing.handlers import make_self_analyze_handler
        handler = make_self_analyze_handler(self_analysis=None)
        plan = MockPlan(MockActionType.LEARN, {})
        result = handler(plan)
        assert result["success"] is False

    def test_make_self_analyze_handler_success(self):
        from agent_core.routing.handlers import make_self_analyze_handler
        sa = MagicMock()
        report = MagicMock()
        report.error = None
        report.report_id = "sa-1"
        report.recommendations = ["rec1"]
        report.goals_created = 1
        report.duration_ms = 500
        report.analysis_text = "All good"
        sa.run_analysis.return_value = report
        handler = make_self_analyze_handler(self_analysis=sa)
        plan = MockPlan(MockActionType.LEARN, {})
        result = handler(plan)
        assert result["success"] is True
        assert result["recommendations"] == 1

    def test_make_creative_handler_no_module(self):
        from agent_core.routing.handlers import make_creative_handler
        handler = make_creative_handler(creative_module=None)
        plan = MockPlan(MockActionType.LEARN, {})
        result = handler(plan)
        assert result["success"] is False

    def test_make_creative_handler_success(self):
        from agent_core.routing.handlers import make_creative_handler
        creative = MagicMock()
        creative.reflect.return_value = {
            "success": True,
            "tensions": ["repetition"],
            "meta_goals_created": [],
        }
        handler = make_creative_handler(creative_module=creative)
        plan = MockPlan(MockActionType.LEARN, {"trigger": "test"})
        result = handler(plan)
        assert result["success"] is True

    def test_make_ask_expert_handler_no_router(self):
        from agent_core.routing.handlers import make_ask_expert_handler
        handler = make_ask_expert_handler(llm_router=None)
        plan = MockPlan(MockActionType.LEARN, {})
        result = handler(plan)
        assert result["success"] is False

    def test_make_ask_expert_handler_success(self):
        from agent_core.routing.handlers import make_ask_expert_handler
        llm = MagicMock()
        llm.ask_encyclopedia.return_value = "Python jest jezykiem programowania."
        handler = make_ask_expert_handler(llm_router=llm)
        plan = MockPlan(
            MockActionType.LEARN,
            {"topic": "Python", "source": "test"},
        )
        result = handler(plan)
        assert result["success"] is True
        assert result["topic"] == "Python"
        assert result["response_length"] > 0

    def test_make_ask_expert_no_question_no_topic(self):
        from agent_core.routing.handlers import make_ask_expert_handler
        llm = MagicMock()
        handler = make_ask_expert_handler(llm_router=llm)
        plan = MockPlan(MockActionType.LEARN, {})
        result = handler(plan)
        assert result["success"] is False
        assert "No question" in result["error"]

    def test_make_validate_handler_no_validator(self):
        from agent_core.routing.handlers import make_validate_handler
        handler = make_validate_handler(cross_validator=None)
        plan = MockPlan(MockActionType.LEARN, {})
        result = handler(plan)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Shared utility tests
# ---------------------------------------------------------------------------

class TestResolveTopics:
    def test_no_topics(self):
        from agent_core.routing.handlers import resolve_topics
        plan = MockPlan(MockActionType.LEARN, {})
        assert resolve_topics(plan, None) is None

    def test_already_resolved(self):
        from agent_core.routing.handlers import resolve_topics
        plan = MockPlan(MockActionType.LEARN, {
            "topics": ["python"],
            "resolved_file_ids": ["file1.txt"],
        })
        assert resolve_topics(plan, None) == ["file1.txt"]

    def test_no_analyzer(self):
        from agent_core.routing.handlers import resolve_topics
        plan = MockPlan(MockActionType.LEARN, {"topics": ["python"]})
        result = resolve_topics(plan, None)
        assert result == []
        assert plan.action_params["resolved_file_ids"] == []

    def test_with_analyzer(self):
        from agent_core.routing.handlers import resolve_topics
        analyzer = MagicMock()
        analyzer.get_files_for_topics.return_value = [
            ("file1.txt", 3.0), ("file2.txt", 1.5),
        ]
        plan = MockPlan(MockActionType.LEARN, {"topics": ["python"]})
        result = resolve_topics(plan, analyzer)
        assert result == ["file1.txt", "file2.txt"]
        assert plan.action_params["resolution_report"]["matches"] == 2

    def test_empty_results(self):
        from agent_core.routing.handlers import resolve_topics
        analyzer = MagicMock()
        analyzer.get_files_for_topics.return_value = []
        plan = MockPlan(MockActionType.LEARN, {"topics": ["nonexistent"]})
        result = resolve_topics(plan, analyzer)
        assert result is None  # empty list -> None


# ---------------------------------------------------------------------------
# Import test
# ---------------------------------------------------------------------------

class TestImports:
    def test_import_from_package(self):
        assert ImportedRouter is CapabilityRouter

    def test_import_default_specs(self):
        from agent_core.routing import DEFAULT_CAPABILITY_SPECS as specs
        assert "learn" in specs


# ---------------------------------------------------------------------------
# Full registration flow
# ---------------------------------------------------------------------------

class TestFullFlow:
    def test_register_all_defaults_and_dispatch(self):
        """Register all 13 default capabilities and dispatch noop."""
        router = CapabilityRouter()
        for name, spec in DEFAULT_CAPABILITY_SPECS.items():
            router.register(name, _ok_handler, spec)

        assert router.registered_count == 13
        plan = MockPlan(MockActionType.NOOP, {})
        result = router.dispatch(plan)
        assert result["success"] is True

    def test_discovery_after_full_registration(self):
        router = CapabilityRouter()
        for name, spec in DEFAULT_CAPABILITY_SPECS.items():
            router.register(name, _ok_handler, spec)

        caps = router.list_capabilities()
        names = [c.name for c in caps]
        assert "learn" in names
        assert "effector" in names
        assert names == sorted(names)

    def test_status_after_full_registration(self):
        router = CapabilityRouter()
        for name, spec in DEFAULT_CAPABILITY_SPECS.items():
            router.register(name, _ok_handler, spec)

        status = router.get_status()
        assert status["registered"] == 13
        free_count = sum(
            1 for c in status["capabilities"]
            if c["classification"] == "free"
        )
        assert free_count == 5  # learn, exam, review, evaluate, noop
