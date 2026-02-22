"""Tests for extracted REPL modules."""

import pytest
from unittest.mock import MagicMock, patch

from agent_core.registry import (
    MariaModule,
    CommandInfo,
    SharedContext,
    ModuleRegistry,
    CommandDispatcher,
)


# ====== Mock SharedContext factory ======

def make_ctx(**overrides):
    """Create a SharedContext with mock objects."""
    mock_brain = MagicMock()
    mock_brain.think.return_value = "Mock response"

    mock_brain_loop = MagicMock()
    mock_brain_loop.process_perception.return_value = {"reasoning": "test"}

    mock_semantic = MagicMock()
    mock_semantic.nodes = {
        "n1": {"label": "test", "type": "concept", "source": "self_learning",
               "confidence": 0.9, "attributes": {"definition": "a test"}},
    }
    mock_semantic.edges = {"e1": {}}

    ctx = SharedContext(
        brain=mock_brain,
        brain_loop=mock_brain_loop,
        semantic_memory=mock_semantic,
        episodic_memory=[{"timestamp": "2026-01-01", "success": True}],
    )

    for key, val in overrides.items():
        setattr(ctx, key, val)

    return ctx


# ====== CoreModule Tests ======

class TestCoreModule:
    def _make_module(self, ctx=None):
        from agent_core.modules.core_module import CoreModule
        m = CoreModule()
        m.init(ctx or make_ctx())
        return m

    def test_name(self):
        from agent_core.modules.core_module import CoreModule
        assert CoreModule.name == "core"

    def test_commands_registered(self):
        m = self._make_module()
        cmds = m.get_commands()
        names = [c.name for c in cmds]
        assert "/status" in names
        assert "/episodes" in names
        assert "/nodes" in names
        assert "/save" in names
        assert "/load" in names
        assert "/start" in names
        assert "/stop" in names
        assert "/reload" in names

    def test_help_lines(self):
        m = self._make_module()
        help_lines = m.get_help_lines()
        categories = [cat for cat, _ in help_lines]
        assert "[INFO] PODSTAWOWE" in categories
        assert "[AGENT] AGENT CONTROL" in categories

    def test_status_no_result(self, capsys):
        m = self._make_module()
        m._cmd_status([])
        output = capsys.readouterr().out
        assert "Brak danych" in output

    def test_status_with_result(self, capsys):
        ctx = make_ctx()
        ctx.last_result = {"learning_goals": ["g1"], "unknown_terms": ["t1"]}
        m = self._make_module(ctx)
        m._cmd_status([])
        output = capsys.readouterr().out
        assert "Status" in output

    def test_episodes_empty(self, capsys):
        ctx = make_ctx()
        ctx.episodic_memory = []
        m = self._make_module(ctx)
        m._cmd_episodes([])
        output = capsys.readouterr().out
        assert "Brak epizodow" in output

    def test_episodes_with_data(self, capsys):
        m = self._make_module()
        m._cmd_episodes([])
        output = capsys.readouterr().out
        assert "2026-01-01" in output

    def test_nodes_empty(self, capsys):
        ctx = make_ctx()
        ctx.semantic_memory.nodes = {}
        m = self._make_module(ctx)
        m._cmd_nodes([])
        output = capsys.readouterr().out
        assert "Brak wezlow" in output

    def test_nodes_with_data(self, capsys):
        m = self._make_module()
        m._cmd_nodes([])
        output = capsys.readouterr().out
        assert "test" in output

    def test_save(self, capsys):
        m = self._make_module()
        m._cmd_save([])
        output = capsys.readouterr().out
        assert "Zapisano" in output
        m.ctx.semantic_memory.save_to_json.assert_called_once_with("semantic_graph.json")

    def test_load(self, capsys):
        m = self._make_module()
        m._cmd_load([])
        output = capsys.readouterr().out
        assert "Wczytano" in output
        m.ctx.semantic_memory.load_from_json.assert_called_once_with("semantic_graph.json")

    def test_stop_not_running(self, capsys):
        m = self._make_module()
        m._cmd_stop([])
        output = capsys.readouterr().out
        assert "juz zatrzymany" in output

    def test_cleanup_stops_agent(self):
        m = self._make_module()
        m._agent_running = True
        m.cleanup()
        assert m._agent_should_stop is True


# ====== HomeostasisModule Tests ======

class TestHomeostasisModule:
    def test_name(self):
        from agent_core.modules.homeostasis_module import HomeostasisModule
        assert HomeostasisModule.name == "homeostasis"

    def test_commands(self):
        from agent_core.modules.homeostasis_module import HomeostasisModule
        m = HomeostasisModule()
        cmds = m.get_commands()
        assert len(cmds) == 1
        assert cmds[0].name == "/homeostasis"

    def test_help_category(self):
        from agent_core.modules.homeostasis_module import HomeostasisModule
        m = HomeostasisModule()
        # Need to init first for get_commands to work
        ctx = make_ctx()
        # Provide a mock homeostasis_core
        mock_core = MagicMock()
        mock_core.state.mode.value = "active"
        mock_core.state.health_score = 0.95
        mock_core.state.mode_duration_seconds = 100
        mock_core.state.idle_seconds = 10
        mock_core.state.alerts = []
        mock_core.get_telemetry.return_value = {}
        ctx.homeostasis_core = mock_core
        m.init(ctx)
        help_lines = m.get_help_lines()
        categories = [cat for cat, _ in help_lines]
        assert "[HEART] HOMEOSTASIS" in categories

    def test_status_command(self, capsys):
        from agent_core.modules.homeostasis_module import HomeostasisModule
        m = HomeostasisModule()
        ctx = make_ctx()
        mock_core = MagicMock()
        mock_core.state.mode.value = "active"
        mock_core.state.health_score = 0.95
        mock_core.state.mode_duration_seconds = 100
        mock_core.state.idle_seconds = 10
        mock_core.state.alerts = []
        mock_core.get_telemetry.return_value = {}
        ctx.homeostasis_core = mock_core
        m.init(ctx)
        m._cmd_homeostasis([])
        output = capsys.readouterr().out
        assert "HOMEOSTASIS STATUS" in output
        assert "ACTIVE" in output

    def test_unknown_subcommand(self, capsys):
        from agent_core.modules.homeostasis_module import HomeostasisModule
        m = HomeostasisModule()
        ctx = make_ctx()
        ctx.homeostasis_core = MagicMock()
        m.init(ctx)
        m._cmd_homeostasis(["xyz"])
        output = capsys.readouterr().out
        assert "Unknown subcommand" in output

    def test_stop_not_running(self, capsys):
        from agent_core.modules.homeostasis_module import HomeostasisModule
        m = HomeostasisModule()
        ctx = make_ctx()
        ctx.homeostasis_core = MagicMock()
        m.init(ctx)
        m._cmd_homeostasis(["stop"])
        output = capsys.readouterr().out
        assert "Not running" in output

    def test_cleanup(self):
        from agent_core.modules.homeostasis_module import HomeostasisModule
        m = HomeostasisModule()
        m._running = True
        m.cleanup()
        assert m._running is False


# ====== IntrospectionModule Tests ======

class TestIntrospectionModule:
    def test_name(self):
        from agent_core.modules.introspection_module import IntrospectionModule
        assert IntrospectionModule.name == "introspection"

    def test_commands(self):
        from agent_core.modules.introspection_module import IntrospectionModule
        m = IntrospectionModule()
        cmds = m.get_commands()
        assert len(cmds) == 1
        assert cmds[0].name == "/introspect"

    def test_help_category(self):
        from agent_core.modules.introspection_module import IntrospectionModule
        m = IntrospectionModule()
        ctx = make_ctx()
        m.init(ctx)
        help_lines = m.get_help_lines()
        categories = [cat for cat, _ in help_lines]
        assert "[MIRROR] CODE INTROSPECTION" in categories


# ====== LearningModule Tests ======

class TestLearningModule:
    def test_name(self):
        from agent_core.modules.learning_module import LearningModule
        assert LearningModule.name == "learning"

    def test_commands(self):
        from agent_core.modules.learning_module import LearningModule
        m = LearningModule()
        cmds = m.get_commands()
        names = [c.name for c in cmds]
        assert "/learn" in names
        assert "/learn-web" in names
        assert "/hybrid" in names

    def test_help_category(self):
        from agent_core.modules.learning_module import LearningModule
        m = LearningModule()
        ctx = make_ctx()
        m.init(ctx)
        help_lines = m.get_help_lines()
        categories = [cat for cat, _ in help_lines]
        assert "[LEARN] AUTO-LEARNING" in categories


# ====== KnowledgeModule Tests ======

class TestKnowledgeModule:
    def test_name(self):
        from agent_core.modules.knowledge_module import KnowledgeModule
        assert KnowledgeModule.name == "knowledge"

    def test_commands(self):
        from agent_core.modules.knowledge_module import KnowledgeModule
        m = KnowledgeModule()
        cmds = m.get_commands()
        names = [c.name for c in cmds]
        assert "/export-learned" in names
        assert "/report" in names

    def test_export_learned(self, capsys, tmp_path, monkeypatch):
        from agent_core.modules.knowledge_module import KnowledgeModule
        monkeypatch.chdir(tmp_path)

        m = KnowledgeModule()
        m.init(make_ctx())
        m._cmd_export_learned([])
        output = capsys.readouterr().out
        assert "Exported" in output

    def test_report(self, capsys, tmp_path, monkeypatch):
        from agent_core.modules.knowledge_module import KnowledgeModule
        monkeypatch.chdir(tmp_path)

        m = KnowledgeModule()
        m.init(make_ctx())
        m._cmd_report([])
        output = capsys.readouterr().out
        assert "REPORT" in output


# ====== QueryModule Tests ======

class TestQueryModule:
    def test_name(self):
        from agent_core.modules.query_module import QueryModule
        assert QueryModule.name == "query"

    def test_commands(self):
        from agent_core.modules.query_module import QueryModule
        m = QueryModule()
        cmds = m.get_commands()
        names = [c.name for c in cmds]
        assert "/ask" in names
        assert "/teach" in names

    def test_ask_no_question(self, capsys):
        from agent_core.modules.query_module import QueryModule
        m = QueryModule()
        m.init(make_ctx())
        m._cmd_ask([])
        output = capsys.readouterr().out
        assert "Brak pytania" in output

    def test_ask_with_question(self, capsys):
        from agent_core.modules.query_module import QueryModule
        m = QueryModule()
        ctx = make_ctx()
        m.init(ctx)
        m._cmd_ask(["Co", "to", "jest", "LLM?"])
        output = capsys.readouterr().out
        assert "Maria:" in output
        ctx.brain.think.assert_called_once()

    def test_ask_no_brain(self, capsys):
        from agent_core.modules.query_module import QueryModule
        m = QueryModule()
        ctx = make_ctx()
        ctx.brain = None
        m.init(ctx)
        m._cmd_ask(["test"])
        output = capsys.readouterr().out
        assert "not initialized" in output


# ====== Full Registry Integration Tests ======

class TestFullRegistryIntegration:
    """Test modules working together through the registry."""

    def test_register_all_modules(self):
        """All modules can register and init."""
        from agent_core.modules.core_module import CoreModule
        from agent_core.modules.knowledge_module import KnowledgeModule
        from agent_core.modules.query_module import QueryModule

        reg = ModuleRegistry()
        reg.register(CoreModule())
        reg.register(KnowledgeModule())
        reg.register(QueryModule())

        ctx = make_ctx()
        reg.init_all(ctx)

        assert reg.is_available("core")
        assert reg.is_available("knowledge")
        assert reg.is_available("query")

    def test_dispatcher_routes_commands(self):
        """Dispatcher correctly routes to module commands."""
        from agent_core.modules.core_module import CoreModule
        from agent_core.modules.query_module import QueryModule

        reg = ModuleRegistry()
        reg.register(CoreModule())
        reg.register(QueryModule())

        ctx = make_ctx()
        reg.init_all(ctx)

        disp = CommandDispatcher(reg)

        # Known commands
        assert disp.dispatch("/episodes", []) is True
        assert disp.dispatch("/nodes", []) is True
        assert disp.dispatch("/ask", ["test"]) is True

        # Unknown
        assert disp.dispatch("/nonexistent", []) is False

    def test_help_aggregation(self):
        """Help from all modules is aggregated."""
        from agent_core.modules.core_module import CoreModule
        from agent_core.modules.knowledge_module import KnowledgeModule

        reg = ModuleRegistry()
        reg.register(CoreModule())
        reg.register(KnowledgeModule())
        reg.init_all(make_ctx())

        disp = CommandDispatcher(reg)
        help_items = disp.get_all_help()
        categories = [cat for cat, _ in help_items]

        assert "[INFO] PODSTAWOWE" in categories
        assert "[KNOWLEDGE] KNOWLEDGE MANAGEMENT" in categories

    def test_try_register_graceful_degradation(self):
        """Modules that fail to import are gracefully skipped."""
        from agent_core.modules.core_module import CoreModule

        reg = ModuleRegistry()
        reg.register(CoreModule())

        # Simulate failing module
        def bad_factory():
            raise ImportError("vision not installed")

        reg.try_register(bad_factory, "vision")

        ctx = make_ctx()
        reg.init_all(ctx)

        assert reg.is_available("core")
        assert not reg.is_available("vision")

        status = reg.get_status()
        assert status["core"] == "active"
        assert "failed" in status["vision"]

    def test_command_names_from_all_modules(self):
        """All command names are collected across modules."""
        from agent_core.modules.core_module import CoreModule
        from agent_core.modules.query_module import QueryModule

        reg = ModuleRegistry()
        reg.register(CoreModule())
        reg.register(QueryModule())
        reg.init_all(make_ctx())

        disp = CommandDispatcher(reg)
        names = disp.get_command_names()

        assert "/status" in names
        assert "/ask" in names
        assert "/teach" in names

    def test_cleanup_all_modules(self):
        """Cleanup is called on all modules."""
        from agent_core.modules.core_module import CoreModule
        from agent_core.modules.query_module import QueryModule

        reg = ModuleRegistry()
        core = CoreModule()
        reg.register(core)
        reg.register(QueryModule())

        ctx = make_ctx()
        reg.init_all(ctx)

        # Simulate running agent
        core._agent_running = True
        reg.cleanup_all()

        assert core._agent_should_stop is True
