"""Tests for V3 Phase A orchestrator: UserFacingSelfModel + OnboardingFlow."""

import json
import tempfile
import shutil
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass

from agent_core.orchestrator.self_model_facade import (
    UserFacingSelfModel,
    _TAG_GROUPS,
    _MODE_LABELS,
)
from agent_core.orchestrator.onboarding import (
    OnboardingFlow,
    OnboardingStep,
    AUTONOMY_PRESETS,
)
from agent_core.routing.capability_spec import CapabilitySpec


# ===========================================================================
# FIXTURES
# ===========================================================================

@pytest.fixture
def mock_identity_store():
    """Mock IdentityStore with typical data."""
    store = MagicMock()
    store._data = {}
    store.get_identity_dict.return_value = {
        "session_count": 42,
        "total_uptime_hours": 120.5,
        "birth_date": "2025-11-14",
        "age_string": "4 miesiace",
        "primary_user": "Operator",
        "last_session_summary": "Nauka o fizyce",
    }
    store.get_session_count.return_value = 42
    return store


@pytest.fixture
def mock_consciousness():
    """Mock ConsciousnessCore with self_model."""
    consciousness = MagicMock()
    consciousness.self_model.get_traits.return_value = [
        "ciekawska", "systematyczna", "pomocna"
    ]
    consciousness.self_model.get_trait_scores.return_value = {
        "ciekawska": {"score": 0.85, "evidence_count": 12},
        "systematyczna": {"score": 0.78, "evidence_count": 8},
        "pomocna": {"score": 0.72, "evidence_count": 5},
    }
    return consciousness


@pytest.fixture
def mock_capability_router():
    """Mock CapabilityRouter with a few capabilities."""
    router = MagicMock()
    specs = [
        CapabilitySpec(
            name="learn",
            description="Learn new knowledge",
            required_subsystems=("teacher_agent",),
            k7_classification="free",
            tags=("learning", "teacher"),
        ),
        CapabilitySpec(
            name="exam",
            description="Run exam",
            required_subsystems=("teacher_agent",),
            k7_classification="free",
            tags=("learning",),
        ),
        CapabilitySpec(
            name="fetch",
            description="Fetch web content",
            required_subsystems=("knowledge_analyzer",),
            k7_classification="guarded",
            tags=("web", "learning"),
        ),
        CapabilitySpec(
            name="self_analyze",
            description="Self-analysis",
            required_subsystems=("self_analysis",),
            k7_classification="guarded",
            tags=("meta",),
        ),
        CapabilitySpec(
            name="effector",
            description="Execute via OpenClaw",
            required_subsystems=("openclaw_client",),
            k7_classification="restricted",
            tags=("external",),
        ),
    ]
    router.list_capabilities.return_value = specs
    router.is_available.return_value = True
    return router


@pytest.fixture
def mock_context_builder():
    """Mock ContextBuilder."""
    builder = MagicMock()
    builder.get_detailed_file_list.return_value = [
        {"file": "fizyka.txt", "status": "learned"},
        {"file": "chemia.txt", "status": "completed"},
        {"file": "biologia.txt", "status": "new"},
        {"file": "genetyka.txt", "status": "learning"},
    ]
    builder.get_input_files.return_value = [
        "fizyka.txt", "chemia.txt", "biologia.txt", "genetyka.txt"
    ]
    return builder


@pytest.fixture
def mock_homeostasis():
    """Mock HomeostasisCore."""
    core = MagicMock()
    mode = MagicMock()
    mode.name = "ACTIVE"
    core._current_mode = mode
    return core


@pytest.fixture
def mock_ctx(
    mock_identity_store,
    mock_consciousness,
    mock_capability_router,
    mock_context_builder,
    mock_homeostasis,
):
    """Full SharedContext mock."""
    ctx = MagicMock()
    ctx.identity_store = mock_identity_store
    ctx.consciousness = mock_consciousness
    ctx.capability_router = mock_capability_router
    ctx.context_builder = mock_context_builder
    ctx.homeostasis_core = mock_homeostasis
    ctx.openclaw_client = None  # Not available
    return ctx


@pytest.fixture
def self_model(mock_ctx):
    """UserFacingSelfModel with full mock context."""
    return UserFacingSelfModel(mock_ctx)


@pytest.fixture
def onboarding(mock_ctx, self_model):
    """OnboardingFlow with full mock context."""
    return OnboardingFlow(mock_ctx, self_model)


# ===========================================================================
# UserFacingSelfModel - get_identity
# ===========================================================================

class TestUserFacingSelfModelIdentity:

    def test_identity_has_name(self, self_model):
        identity = self_model.get_identity()
        assert identity["name"] == "Maria"
        assert identity["full_name"] == "M.A.R.I.A."

    def test_identity_has_session_from_store(self, self_model):
        identity = self_model.get_identity()
        assert identity["session_count"] == 42

    def test_identity_has_uptime(self, self_model):
        identity = self_model.get_identity()
        assert identity["total_uptime_hours"] == 120.5

    def test_identity_has_purpose(self, self_model):
        identity = self_model.get_identity()
        assert "nauka" in identity["purpose"]

    def test_identity_fallback_without_store(self):
        ctx = MagicMock()
        ctx.identity_store = None
        ctx.consciousness = None
        model = UserFacingSelfModel(ctx)
        identity = model.get_identity()
        assert identity["name"] == "Maria"
        assert "session_count" not in identity

    def test_identity_has_age(self, self_model):
        identity = self_model.get_identity()
        assert identity["age_string"] == "4 miesiace"

    def test_identity_has_operator(self, self_model):
        identity = self_model.get_identity()
        assert identity["primary_user"] == "Operator"


# ===========================================================================
# UserFacingSelfModel - get_personality
# ===========================================================================

class TestUserFacingSelfModelPersonality:

    def test_personality_has_traits(self, self_model):
        personality = self_model.get_personality()
        assert "ciekawska" in personality["traits"]
        assert len(personality["traits"]) == 3

    def test_personality_has_scores(self, self_model):
        personality = self_model.get_personality()
        assert "ciekawska" in personality["trait_scores"]
        assert personality["trait_scores"]["ciekawska"]["score"] == 0.85

    def test_personality_fallback_no_consciousness(self):
        ctx = MagicMock()
        ctx.consciousness = None
        model = UserFacingSelfModel(ctx)
        personality = model.get_personality()
        assert personality["traits"] == []
        assert personality["trait_scores"] == {}


# ===========================================================================
# UserFacingSelfModel - get_capabilities
# ===========================================================================

class TestUserFacingSelfModelCapabilities:

    def test_all_capabilities(self, self_model):
        caps = self_model.get_capabilities()
        assert len(caps) == 5
        names = [c["name"] for c in caps]
        assert "learn" in names
        assert "effector" in names

    def test_capabilities_have_fields(self, self_model):
        caps = self_model.get_capabilities()
        for cap in caps:
            assert "name" in cap
            assert "description" in cap
            assert "tags" in cap
            assert "k7_classification" in cap
            assert "available" in cap

    def test_filter_by_tag(self, self_model):
        caps = self_model.get_capabilities(tag="learning")
        names = [c["name"] for c in caps]
        assert "learn" in names
        assert "exam" in names
        assert "effector" not in names

    def test_filter_by_meta_tag(self, self_model):
        caps = self_model.get_capabilities(tag="meta")
        assert len(caps) == 1
        assert caps[0]["name"] == "self_analyze"

    def test_empty_without_router(self):
        ctx = MagicMock()
        ctx.consciousness = None
        ctx.identity_store = None
        del ctx.capability_router  # AttributeError -> getattr returns None
        model = UserFacingSelfModel(ctx)
        assert model.get_capabilities() == []

    def test_capabilities_grouped(self, self_model):
        grouped = self_model.get_capabilities_grouped()
        assert "Nauka" in grouped
        assert any(c["name"] == "learn" for c in grouped["Nauka"])

    def test_capabilities_grouped_meta(self, self_model):
        grouped = self_model.get_capabilities_grouped()
        assert "Samoanaliza" in grouped
        assert any(c["name"] == "self_analyze" for c in grouped["Samoanaliza"])


# ===========================================================================
# UserFacingSelfModel - get_awareness
# ===========================================================================

class TestUserFacingSelfModelAwareness:

    def test_files_total(self, self_model):
        awareness = self_model.get_awareness()
        assert awareness["files_total"] == 4

    def test_files_by_status(self, self_model):
        awareness = self_model.get_awareness()
        assert awareness["files_by_status"]["learned"] == 1
        assert awareness["files_by_status"]["new"] == 1

    def test_input_files_count(self, self_model):
        awareness = self_model.get_awareness()
        assert awareness["input_files_count"] == 4

    def test_awareness_empty_without_builder(self):
        ctx = MagicMock()
        del ctx.context_builder
        model = UserFacingSelfModel(ctx)
        awareness = model.get_awareness()
        assert awareness == {}


# ===========================================================================
# UserFacingSelfModel - mode and limitations
# ===========================================================================

class TestUserFacingSelfModelMode:

    def test_current_mode(self, self_model):
        assert self_model.get_current_mode() == "ACTIVE"

    def test_mode_unknown_without_core(self):
        ctx = MagicMock()
        ctx.homeostasis_core = None
        model = UserFacingSelfModel(ctx)
        assert model.get_current_mode() == "UNKNOWN"

    def test_limitations_list(self, self_model):
        lims = self_model.get_limitations()
        assert len(lims) >= 3
        assert any("llama3.1" in l for l in lims)

    def test_limitations_include_openclaw_missing(self, self_model):
        lims = self_model.get_limitations()
        assert any("OpenClaw" in l for l in lims)


# ===========================================================================
# UserFacingSelfModel - get_status (full)
# ===========================================================================

class TestUserFacingSelfModelStatus:

    def test_status_has_all_sections(self, self_model):
        status = self_model.get_status()
        assert "identity" in status
        assert "personality" in status
        assert "capabilities" in status
        assert "capabilities_grouped" in status
        assert "awareness" in status
        assert "limitations" in status
        assert "mode" in status
        assert "mode_label" in status

    def test_mode_label_polish(self, self_model):
        status = self_model.get_status()
        assert status["mode_label"] == "aktywna"


# ===========================================================================
# UserFacingSelfModel - describe_self
# ===========================================================================

class TestUserFacingSelfModelDescribe:

    def test_describe_contains_name(self, self_model):
        text = self_model.describe_self()
        assert "Maria" in text
        assert "M.A.R.I.A." in text

    def test_describe_contains_traits(self, self_model):
        text = self_model.describe_self()
        assert "ciekawska" in text

    def test_describe_contains_capabilities_count(self, self_model):
        text = self_model.describe_self()
        assert "5 zdolnosci" in text

    def test_describe_contains_mode(self, self_model):
        text = self_model.describe_self()
        assert "aktywna" in text

    def test_describe_contains_files(self, self_model):
        text = self_model.describe_self()
        assert "4 plikow" in text

    def test_describe_capabilities_text(self, self_model):
        text = self_model.describe_capabilities_text()
        assert "Moje zdolnosci:" in text
        assert "learn:" in text
        assert "Nauka" in text


# ===========================================================================
# UserFacingSelfModel - system prompt context
# ===========================================================================

class TestUserFacingSelfModelSystemPrompt:

    def test_system_prompt_compact(self, self_model):
        ctx = self_model.get_system_prompt_context()
        assert "Jestes Maria" in ctx
        assert "Cel:" in ctx
        assert "Umiesz:" in ctx
        assert "Stan:" in ctx

    def test_system_prompt_has_traits(self, self_model):
        ctx = self_model.get_system_prompt_context()
        assert "ciekawska" in ctx

    def test_system_prompt_has_limitations(self, self_model):
        ctx = self_model.get_system_prompt_context()
        assert "Ograniczenia:" in ctx


# ===========================================================================
# OnboardingStep
# ===========================================================================

class TestOnboardingStep:

    def test_step_creation(self):
        step = OnboardingStep(
            key="test",
            title="Test Step",
            content="Hello",
        )
        assert step.key == "test"
        assert step.completed is False

    def test_step_to_dict(self):
        step = OnboardingStep(
            key="test",
            title="Test",
            content="Hello",
            data={"foo": "bar"},
        )
        d = step.to_dict()
        assert d["key"] == "test"
        assert d["data"]["foo"] == "bar"
        assert d["completed"] is False


# ===========================================================================
# OnboardingFlow - should_run
# ===========================================================================

class TestOnboardingFlowDetection:

    def test_should_run_first_time(self, onboarding):
        assert onboarding.should_run() is True

    def test_should_not_run_after_completion(self, onboarding, mock_identity_store):
        mock_identity_store._data["onboarding_completed"] = True
        assert onboarding.should_run() is False

    def test_is_completed_inverse(self, onboarding, mock_identity_store):
        assert onboarding.is_completed() is False
        mock_identity_store._data["onboarding_completed"] = True
        assert onboarding.is_completed() is True

    def test_should_run_without_identity(self):
        ctx = MagicMock()
        ctx.identity_store = None
        model = UserFacingSelfModel(ctx)
        flow = OnboardingFlow(ctx, model)
        assert flow.should_run() is True


# ===========================================================================
# OnboardingFlow - get_steps
# ===========================================================================

class TestOnboardingFlowSteps:

    def test_steps_count(self, onboarding):
        steps = onboarding.get_steps()
        assert len(steps) == 5

    def test_step_keys(self, onboarding):
        steps = onboarding.get_steps()
        keys = [s["key"] for s in steps]
        assert keys == ["introduction", "capabilities", "learning", "limitations", "ready"]

    def test_step_titles(self, onboarding):
        steps = onboarding.get_steps()
        assert steps[0]["title"] == "Kim jestem?"
        assert steps[1]["title"] == "Co potrafie?"
        assert steps[2]["title"] == "Jak sie ucze?"
        assert steps[3]["title"] == "Moje ograniczenia"
        assert steps[4]["title"] == "Gotowa!"

    def test_introduction_step_content(self, onboarding):
        steps = onboarding.get_steps()
        intro = steps[0]
        assert "Maria" in intro["content"]
        assert "M.A.R.I.A." in intro["content"]
        assert "ciekawska" in intro["content"]

    def test_capabilities_step_data(self, onboarding):
        steps = onboarding.get_steps()
        caps_step = steps[1]
        assert "capabilities_grouped" in caps_step["data"]
        assert caps_step["data"]["total"] == 5

    def test_learning_step_has_file_info(self, onboarding):
        steps = onboarding.get_steps()
        learning = steps[2]
        assert "4 plikow" in learning["content"]

    def test_limitations_step_lists(self, onboarding):
        steps = onboarding.get_steps()
        lims = steps[3]
        assert "ograniczenia" in lims["title"].lower()
        assert "llama3.1" in lims["content"]

    def test_ready_step_has_presets(self, onboarding):
        steps = onboarding.get_steps()
        ready = steps[4]
        assert "autonomy_presets" in ready["data"]

    def test_get_single_step(self, onboarding):
        onboarding.get_steps()  # Build steps first
        step = onboarding.get_step("capabilities")
        assert step is not None
        assert step["key"] == "capabilities"

    def test_get_step_missing(self, onboarding):
        onboarding.get_steps()
        step = onboarding.get_step("nonexistent")
        assert step is None


# ===========================================================================
# OnboardingFlow - run
# ===========================================================================

class TestOnboardingFlowRun:

    def test_run_returns_text(self, onboarding):
        result = onboarding.run()
        assert "text" in result
        assert result["completed"] is True
        assert result["steps_count"] == 5

    def test_run_text_has_header(self, onboarding):
        result = onboarding.run()
        assert "M.A.R.I.A." in result["text"]
        assert "Onboarding zakonczony" in result["text"]

    def test_run_text_contains_all_steps(self, onboarding):
        result = onboarding.run()
        text = result["text"]
        assert "Kim jestem?" in text
        assert "Co potrafie?" in text
        assert "Jak sie ucze?" in text
        assert "Moje ograniczenia" in text
        assert "Gotowa!" in text

    def test_run_marks_completed(self, onboarding, mock_identity_store):
        onboarding.run()
        assert mock_identity_store._data.get("onboarding_completed") is True

    def test_run_then_should_not_run(self, onboarding):
        onboarding.run()
        assert onboarding.should_run() is False


# ===========================================================================
# OnboardingFlow - mark_completed / reset
# ===========================================================================

class TestOnboardingFlowPersistence:

    def test_mark_completed(self, onboarding, mock_identity_store):
        onboarding.mark_completed()
        assert mock_identity_store._data["onboarding_completed"] is True

    def test_mark_completed_with_preferences(self, onboarding, mock_identity_store):
        prefs = {"autonomy": "medium", "language": "pl"}
        onboarding.mark_completed(preferences=prefs)
        assert mock_identity_store._data["onboarding_preferences"] == prefs

    def test_reset(self, onboarding, mock_identity_store):
        onboarding.mark_completed()
        assert onboarding.should_run() is False
        onboarding.reset()
        assert onboarding.should_run() is True

    def test_mark_completed_without_identity(self):
        ctx = MagicMock()
        ctx.identity_store = None
        model = UserFacingSelfModel(ctx)
        flow = OnboardingFlow(ctx, model)
        # Should not raise
        flow.mark_completed()


# ===========================================================================
# OnboardingFlow - empty context edge cases
# ===========================================================================

class TestOnboardingFlowEdgeCases:

    def test_flow_with_no_capabilities(self):
        ctx = MagicMock()
        ctx.identity_store = MagicMock()
        ctx.identity_store._data = {}
        ctx.identity_store.get_identity_dict.return_value = {
            "session_count": 1,
            "birth_date": "2025-11-14",
        }
        ctx.consciousness = None
        ctx.homeostasis_core = None
        ctx.openclaw_client = None
        del ctx.capability_router
        del ctx.context_builder
        model = UserFacingSelfModel(ctx)
        flow = OnboardingFlow(ctx, model)
        steps = flow.get_steps()
        assert len(steps) == 5
        # Capabilities step shows 0
        caps_step = steps[1]
        assert caps_step["data"]["total"] == 0

    def test_flow_with_empty_awareness(self):
        ctx = MagicMock()
        ctx.identity_store = MagicMock()
        ctx.identity_store._data = {}
        ctx.identity_store.get_identity_dict.return_value = {}
        ctx.consciousness = None
        ctx.homeostasis_core = None
        ctx.openclaw_client = None
        ctx.capability_router = MagicMock()
        ctx.capability_router.list_capabilities.return_value = []
        ctx.capability_router.is_available.return_value = False
        ctx.context_builder = MagicMock()
        ctx.context_builder.get_detailed_file_list.return_value = []
        ctx.context_builder.get_input_files.return_value = []
        model = UserFacingSelfModel(ctx)
        flow = OnboardingFlow(ctx, model)
        result = flow.run()
        assert result["completed"] is True
        assert "pusta" in result["text"]


# ===========================================================================
# AUTONOMY_PRESETS
# ===========================================================================

class TestAutonomyPresets:

    def test_presets_have_required_keys(self):
        for key, preset in AUTONOMY_PRESETS.items():
            assert "label" in preset
            assert "description" in preset
            assert "authority_level" in preset

    def test_three_levels(self):
        assert len(AUTONOMY_PRESETS) == 3
        assert "low" in AUTONOMY_PRESETS
        assert "medium" in AUTONOMY_PRESETS
        assert "high" in AUTONOMY_PRESETS
