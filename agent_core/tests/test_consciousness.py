"""Tests for consciousness module: IdentityStore, SelfModelBuilder, HumanStateMapper, ConsciousnessCore."""

import json
import os
import time
import tempfile
import shutil
import pytest
from unittest.mock import MagicMock, patch

from agent_core.consciousness.identity_store import (
    IdentityStore,
    MARIA_BIRTH_DATE,
    MARIA_BIRTH_TIMESTAMP,
    DEFAULT_PRIMARY_USER,
)
from agent_core.consciousness.human_state import HumanStateMapper
from agent_core.consciousness.self_model import SelfModelBuilder
from agent_core.consciousness.core import ConsciousnessCore


# ===========================================================================
# FIXTURES
# ===========================================================================

@pytest.fixture
def tmp_data_dir():
    """Create temporary directory for identity data."""
    d = tempfile.mkdtemp(prefix="maria_test_identity_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def identity_store(tmp_data_dir):
    """Create fresh IdentityStore in temp dir."""
    return IdentityStore(data_dir=tmp_data_dir)


@pytest.fixture
def mock_graph():
    """Create mock SemanticGraph."""
    graph = MagicMock()
    graph.nodes = {}
    graph.edges = []
    graph.find_node_by_label = MagicMock(return_value=None)
    graph.find_nodes_by_type = MagicMock(return_value=[])
    graph.add_node = MagicMock(return_value="node_maria_001")
    graph.add_edge = MagicMock()
    return graph


@pytest.fixture
def self_model(mock_graph):
    """Create SelfModelBuilder with mock graph."""
    return SelfModelBuilder(mock_graph)


@pytest.fixture
def state_mapper():
    """Create HumanStateMapper."""
    return HumanStateMapper()


@pytest.fixture
def consciousness(tmp_data_dir, mock_graph):
    """Create full ConsciousnessCore for testing."""
    store = IdentityStore(data_dir=tmp_data_dir)
    core = ConsciousnessCore(
        semantic_memory=mock_graph,
        identity_store=store,
    )
    return core


# ===========================================================================
# IDENTITY STORE TESTS
# ===========================================================================

class TestIdentityStore:
    """Test persistent identity tracking."""

    def test_create_new_identity(self, identity_store):
        """First run creates identity with correct defaults."""
        d = identity_store.get_identity_dict()
        assert d["name"] == "Maria"
        assert d["full_name"] == "M.A.R.I.A."
        assert d["birth_date"] == MARIA_BIRTH_DATE
        assert d["birth_timestamp"] == MARIA_BIRTH_TIMESTAMP
        assert d["session_count"] == 0
        assert d["total_uptime_seconds"] == 0
        assert d["primary_user"] == DEFAULT_PRIMARY_USER

    def test_identity_file_created(self, tmp_data_dir, identity_store):
        """Identity JSON file is created on disk."""
        path = os.path.join(tmp_data_dir, "consciousness_identity.json")
        assert os.path.exists(path)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["name"] == "Maria"

    def test_start_session_increments_counter(self, identity_store):
        """start_session() increments session_count."""
        assert identity_store.get_session_count() == 0
        identity_store.start_session()
        assert identity_store.get_session_count() == 1
        identity_store.start_session()
        assert identity_store.get_session_count() == 2

    def test_start_session_sets_restart_count(self, identity_store):
        """restart_count = session_count - 1."""
        identity_store.start_session()
        d = identity_store.get_identity_dict()
        assert d["restart_count"] == 0  # First session, no restarts

        identity_store.start_session()
        d = identity_store.get_identity_dict()
        assert d["restart_count"] == 1

    def test_end_session_updates_uptime(self, identity_store):
        """end_session() adds session duration to total uptime."""
        identity_store.start_session()
        # Wait a tiny bit for measurable duration
        time.sleep(0.05)
        identity_store.end_session(summary="test session")

        d = identity_store.get_identity_dict()
        assert d["total_uptime_seconds"] > 0

    def test_end_session_saves_summary(self, identity_store):
        """end_session() stores session summary."""
        identity_store.start_session()
        identity_store.end_session(summary="Worked on consciousness")

        assert identity_store.get_last_session_summary() == "Worked on consciousness"

    def test_identity_persists_across_instances(self, tmp_data_dir):
        """Identity survives creating new IdentityStore instance."""
        store1 = IdentityStore(data_dir=tmp_data_dir)
        store1.start_session()
        store1.start_session()
        store1.end_session(summary="session 2 done")

        # Create new instance from same dir
        store2 = IdentityStore(data_dir=tmp_data_dir)
        assert store2.get_session_count() == 2
        assert store2.get_last_session_summary() == "session 2 done"

    def test_get_identity_context_string(self, identity_store):
        """get_identity_context() returns human-readable string."""
        identity_store.start_session()
        ctx = identity_store.get_identity_context()

        assert "Maria" in ctx
        assert "M.A.R.I.A." in ctx
        assert "Sesja nr 1" in ctx
        assert MARIA_BIRTH_DATE in ctx

    def test_get_identity_dict_has_computed_fields(self, identity_store):
        """get_identity_dict() includes computed uptime fields."""
        identity_store.start_session()
        d = identity_store.get_identity_dict()

        assert "current_session_uptime_seconds" in d
        assert "current_session_uptime_hours" in d
        assert "total_uptime_hours" in d
        assert d["current_session_uptime_seconds"] >= 0
        assert d["total_uptime_hours"] >= 0

    def test_get_birth_date(self, identity_store):
        """get_birth_date() returns correct date."""
        assert identity_store.get_birth_date() == MARIA_BIRTH_DATE

    def test_get_name(self, identity_store):
        """get_name() returns Maria."""
        assert identity_store.get_name() == "Maria"

    def test_get_primary_user(self, identity_store):
        """get_primary_user() returns Eryk."""
        assert identity_store.get_primary_user() == "Eryk"

    def test_get_total_uptime_hours(self, identity_store):
        """get_total_uptime_hours() includes current session."""
        identity_store.start_session()
        hours = identity_store.get_total_uptime_hours()
        assert hours >= 0

    def test_ensure_fields_adds_missing(self, tmp_data_dir):
        """Loading identity with missing fields fills defaults."""
        # Write minimal identity file
        path = os.path.join(tmp_data_dir, "consciousness_identity.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"name": "Maria", "session_count": 5}, f)

        store = IdentityStore(data_dir=tmp_data_dir)
        d = store.get_identity_dict()
        assert d["session_count"] == 5
        assert d["birth_date"] == MARIA_BIRTH_DATE  # Added by ensure_fields
        assert d["total_uptime_seconds"] == 0  # Default

    def test_end_session_without_summary(self, identity_store):
        """end_session() without summary preserves old summary."""
        identity_store.start_session()
        identity_store.end_session(summary="old summary")
        identity_store.start_session()
        identity_store.end_session()  # No summary

        assert identity_store.get_last_session_summary() == "old summary"

    def test_full_name_expanded(self, identity_store):
        """Full expanded name is correct."""
        d = identity_store.get_identity_dict()
        assert d["full_name_expanded"] == "Meta Analysis Recalibration Intelligence Architecture"


# ===========================================================================
# HUMAN STATE MAPPER TESTS
# ===========================================================================

class TestHumanStateMapper:
    """Test technical state to human language mapping."""

    def test_describe_feeling_returns_string(self, state_mapper):
        """describe_feeling() returns non-empty Polish string."""
        result = state_mapper.describe_feeling()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_describe_with_data_includes_brackets(self, state_mapper):
        """describe_with_data() includes lab data in brackets."""
        result = state_mapper.describe_with_data()
        assert "[RAM:" in result
        assert "CPU:" in result
        assert "Mode:" in result

    def test_describe_feeling_with_mode(self, state_mapper):
        """describe_feeling() respects mode parameter."""
        active = state_mapper.describe_feeling(mode="ACTIVE")
        assert isinstance(active, str)

        survival = state_mapper.describe_feeling(mode="SURVIVAL")
        assert "daje rade" in survival

    def test_describe_with_data_mode(self, state_mapper):
        """describe_with_data() shows mode in data."""
        result = state_mapper.describe_with_data(mode="REDUCED")
        assert "REDUCED" in result

    def test_get_mode_feeling_active(self, state_mapper):
        """Active mode returns energetic feeling."""
        assert "energii" in state_mapper.get_mode_feeling("ACTIVE")

    def test_get_mode_feeling_reduced(self, state_mapper):
        """Reduced mode returns saving energy."""
        assert "Oszczedzam" in state_mapper.get_mode_feeling("REDUCED")

    def test_get_mode_feeling_sleep(self, state_mapper):
        """Sleep mode returns sleeping."""
        assert "rzemie" in state_mapper.get_mode_feeling("SLEEP")

    def test_get_mode_feeling_survival(self, state_mapper):
        """Survival mode returns struggling."""
        assert "daje rade" in state_mapper.get_mode_feeling("SURVIVAL")

    def test_get_mode_feeling_unknown(self, state_mapper):
        """Unknown mode returns default."""
        result = state_mapper.get_mode_feeling("NONEXISTENT")
        assert "nie wiem" in result.lower() or "Nie wiem" in result

    def test_get_metrics_returns_tuple(self, state_mapper):
        """get_metrics() returns (ram, cpu) tuple."""
        ram, cpu = state_mapper.get_metrics()
        assert isinstance(ram, float)
        assert isinstance(cpu, float)
        assert 0 <= ram <= 100
        assert 0 <= cpu <= 100

    def test_ram_feelings_high(self, state_mapper):
        """High RAM produces heavy feeling."""
        feeling = state_mapper._get_ram_feeling(95)
        assert "ciezka" in feeling

    def test_ram_feelings_low(self, state_mapper):
        """Low RAM produces light feeling."""
        feeling = state_mapper._get_ram_feeling(20)
        assert "lekka" in feeling or "pelno" in feeling

    def test_cpu_feelings_high(self, state_mapper):
        """High CPU produces intense thinking."""
        feeling = state_mapper._get_cpu_feeling(95)
        assert "pelnych obrotach" in feeling or "mysle" in feeling

    def test_cpu_feelings_low(self, state_mapper):
        """Low CPU produces resting."""
        feeling = state_mapper._get_cpu_feeling(10)
        assert "odpoczywam" in feeling

    @patch("agent_core.consciousness.human_state.PSUTIL_AVAILABLE", False)
    def test_get_metrics_without_psutil(self):
        """Without psutil, returns zeros."""
        mapper = HumanStateMapper()
        ram, cpu = mapper.get_metrics()
        assert ram == 0.0
        assert cpu == 0.0


# ===========================================================================
# SELF MODEL BUILDER TESTS
# ===========================================================================

class TestSelfModelBuilder:
    """Test self-concept in semantic graph."""

    def test_ensure_self_model_creates_nodes(self, self_model, mock_graph):
        """ensure_self_model() creates self-concept node."""
        node_id = self_model.ensure_self_model()
        assert node_id == "node_maria_001"
        mock_graph.add_node.assert_called()

    def test_ensure_self_model_creates_goal(self, self_model, mock_graph):
        """ensure_self_model() creates goal node."""
        self_model.ensure_self_model()
        # Should be called at least twice (self + goal)
        assert mock_graph.add_node.call_count >= 2

    def test_ensure_self_model_creates_edge(self, self_model, mock_graph):
        """ensure_self_model() creates has_goal edge."""
        self_model.ensure_self_model()
        mock_graph.add_edge.assert_called_once()
        args = mock_graph.add_edge.call_args
        assert args[0][1] == "has_goal"  # relation type

    def test_ensure_self_model_idempotent(self, self_model, mock_graph):
        """Second call doesn't create duplicate nodes."""
        # First call - no existing node
        mock_graph.find_node_by_label.return_value = None
        self_model.ensure_self_model()
        first_call_count = mock_graph.add_node.call_count

        # Second call - node exists
        mock_graph.find_node_by_label.return_value = {
            "id": "node_maria_001",
            "label": "maria",
            "type": "self_concept",
        }
        self_model.ensure_self_model()
        assert mock_graph.add_node.call_count == first_call_count

    def test_get_self_description_before_init(self, self_model):
        """get_self_description() before ensure returns fallback."""
        desc = self_model.get_self_description()
        assert "Maria" in desc
        assert "nie znam" in desc

    def test_get_self_description_after_init(self, mock_graph):
        """get_self_description() after ensure returns full description."""
        # Setup graph to return node
        mock_graph.find_node_by_label.return_value = None
        mock_graph.add_node.return_value = "node_maria_001"

        builder = SelfModelBuilder(mock_graph)
        builder.ensure_self_model()

        # Now make it find the node
        mock_graph.nodes = {
            "node_maria_001": {
                "id": "node_maria_001",
                "label": "maria",
                "type": "self_concept",
                "attributes": {
                    "name": "Maria",
                    "full_name": "M.A.R.I.A.",
                    "purpose": "autonomiczna nauka z plikow tekstowych",
                    "traits": ["ciekawska", "systematyczna"],
                    "capabilities": ["uczenie sie z plikow"],
                },
            }
        }

        desc = builder.get_self_description()
        assert "Maria" in desc
        assert "M.A.R.I.A." in desc
        assert "nauka" in desc
        assert "ciekawska" in desc

    def test_get_traits_default(self, self_model):
        """get_traits() returns initial traits when not initialized."""
        traits = self_model.get_traits()
        assert "ciekawska" in traits
        assert "systematyczna" in traits
        assert "pomocna" in traits

    def test_initial_traits_list(self):
        """INITIAL_TRAITS has expected values."""
        assert "ciekawska" in SelfModelBuilder.INITIAL_TRAITS
        assert "systematyczna" in SelfModelBuilder.INITIAL_TRAITS
        assert "pomocna" in SelfModelBuilder.INITIAL_TRAITS

    def test_get_self_summary_not_initialized(self, self_model):
        """get_self_summary() before init returns initialized=False."""
        summary = self_model.get_self_summary()
        assert summary["initialized"] is False

    def test_self_model_node_type(self, self_model, mock_graph):
        """Self-concept node uses correct type."""
        self_model.ensure_self_model()
        # Check the first add_node call
        call_args = mock_graph.add_node.call_args_list[0]
        assert call_args[1]["node_type"] == "self_concept" or call_args[0][1] == "self_concept"

    def test_self_model_source(self, self_model, mock_graph):
        """Self-concept node has source='consciousness'."""
        self_model.ensure_self_model()
        call_kwargs = mock_graph.add_node.call_args_list[0][1]
        assert call_kwargs.get("source") == "consciousness"


# ===========================================================================
# CONSCIOUSNESS CORE TESTS
# ===========================================================================

class TestConsciousnessCore:
    """Test consciousness orchestrator."""

    def test_initialize(self, consciousness, mock_graph):
        """initialize() starts session and ensures self-model."""
        consciousness.initialize()
        assert consciousness._initialized is True
        assert consciousness.identity.get_session_count() == 1
        mock_graph.add_node.assert_called()  # self_model.ensure_self_model()

    def test_get_current_feeling(self, consciousness):
        """get_current_feeling() returns human-language string."""
        feeling = consciousness.get_current_feeling()
        assert isinstance(feeling, str)
        assert len(feeling) > 0
        # Should include lab data
        assert "[RAM:" in feeling

    def test_get_feeling_short(self, consciousness):
        """get_feeling_short() returns single sentence."""
        feeling = consciousness.get_feeling_short()
        assert isinstance(feeling, str)
        assert len(feeling) > 0
        # Should NOT include lab data
        assert "[RAM:" not in feeling

    def test_get_identity_summary(self, consciousness, mock_graph):
        """get_identity_summary() returns multi-line string."""
        consciousness.initialize()
        summary = consciousness.get_identity_summary()
        assert isinstance(summary, str)
        assert MARIA_BIRTH_DATE in summary
        assert "Sesja:" in summary

    def test_checkpoint(self, consciousness):
        """checkpoint() saves session data."""
        consciousness.initialize()
        consciousness.checkpoint(summary="test checkpoint")
        assert consciousness.identity.get_last_session_summary() == "test checkpoint"

    def test_get_startup_greeting_with_brain(self, consciousness):
        """get_startup_greeting() uses brain to generate greeting."""
        consciousness.initialize()

        mock_brain = MagicMock()
        mock_brain.think.return_value = "Witaj Eryk! Dobrze Cie widziec."

        greeting = consciousness.get_startup_greeting(mock_brain)
        assert "Witaj" in greeting or "Eryk" in greeting
        mock_brain.think.assert_called_once()

    def test_get_startup_greeting_fallback(self, consciousness):
        """get_startup_greeting() falls back on brain failure."""
        consciousness.initialize()

        mock_brain = MagicMock()
        mock_brain.think.side_effect = Exception("Ollama offline")

        greeting = consciousness.get_startup_greeting(mock_brain)
        assert "M.A.R.I.A." in greeting
        assert "gotowa" in greeting.lower() or "sesja" in greeting.lower()

    def test_get_startup_greeting_includes_context(self, consciousness):
        """get_startup_greeting() passes identity context to brain."""
        consciousness.initialize()

        mock_brain = MagicMock()
        mock_brain.think.return_value = "Witaj!"

        consciousness.get_startup_greeting(mock_brain)

        # Check that the prompt included session info
        call_args = mock_brain.think.call_args
        prompt = call_args[0][0]
        assert "sesja" in prompt.lower() or "sesj" in prompt.lower()

    def test_multiple_sessions(self, tmp_data_dir, mock_graph):
        """Multiple init/checkpoint cycles track correctly."""
        store = IdentityStore(data_dir=tmp_data_dir)
        core = ConsciousnessCore(
            semantic_memory=mock_graph,
            identity_store=store,
        )
        core.initialize()
        core.checkpoint(summary="session 1")

        # "Restart" - new core, same store
        store2 = IdentityStore(data_dir=tmp_data_dir)
        core2 = ConsciousnessCore(
            semantic_memory=mock_graph,
            identity_store=store2,
        )
        core2.initialize()
        assert store2.get_session_count() == 2
        assert store2.get_last_session_summary() == "session 1"


# ===========================================================================
# INTEGRATION TESTS
# ===========================================================================

class TestConsciousnessIntegration:
    """Integration tests combining multiple components."""

    def test_full_lifecycle(self, tmp_data_dir, mock_graph):
        """Full lifecycle: create -> init -> feel -> greeting -> checkpoint."""
        store = IdentityStore(data_dir=tmp_data_dir)
        core = ConsciousnessCore(
            semantic_memory=mock_graph,
            identity_store=store,
        )

        # Initialize
        core.initialize()
        assert store.get_session_count() == 1

        # Check feeling
        feeling = core.get_current_feeling()
        assert isinstance(feeling, str)
        assert len(feeling) > 0

        # Get greeting
        mock_brain = MagicMock()
        mock_brain.think.return_value = "Witaj!"
        greeting = core.get_startup_greeting(mock_brain)
        assert isinstance(greeting, str)

        # Checkpoint
        core.checkpoint(summary="Integration test complete")
        assert store.get_last_session_summary() == "Integration test complete"

    def test_import_from_package(self):
        """All public classes are importable from package."""
        from agent_core.consciousness import (
            IdentityStore,
            SelfModelBuilder,
            HumanStateMapper,
            ConsciousnessCore,
        )
        assert IdentityStore is not None
        assert SelfModelBuilder is not None
        assert HumanStateMapper is not None
        assert ConsciousnessCore is not None

    def test_identity_in_system_prompt(self, tmp_data_dir):
        """Identity context appears in OllamaBrain system prompt."""
        store = IdentityStore(data_dir=tmp_data_dir)
        store.start_session()

        # Mock OllamaBrain's identity integration
        ctx = store.get_identity_context()
        assert "Maria" in ctx
        assert "Sesja nr 1" in ctx

    def test_consciousness_module_commands(self, tmp_data_dir, mock_graph):
        """ConsciousnessModule returns correct commands."""
        from agent_core.modules.consciousness_module import ConsciousnessModule

        module = ConsciousnessModule()
        commands = module.get_commands()
        command_names = [c.name for c in commands]

        assert "/identity" in command_names
        assert "/feel" in command_names
