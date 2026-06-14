"""Tests for V3 Phase E: ProductShell + V3Module."""

import pytest
from unittest.mock import MagicMock, patch
from io import StringIO

from agent_core.orchestrator.product_shell import ProductShell
from agent_core.routing.capability_spec import CapabilitySpec
from agent_core.tests.spec_helpers import specced
from agent_core.registry.shared_context import SharedContext
from agent_core.homeostasis.core import HomeostasisCore
from types import SimpleNamespace
from agent_core.homeostasis.state_model import Mode
from agent_core.consciousness.identity_store import IdentityStore
from agent_core.consciousness.core import ConsciousnessCore
from agent_core.consciousness.self_model import SelfModelBuilder
from agent_core.routing.capability_router import CapabilityRouter
from agent_core.awareness.context_builder import ContextBuilder
from agent_core.goals.store import GoalStore


# ===========================================================================
# FIXTURES
# ===========================================================================

def _make_specs():
    return [
        CapabilitySpec(name="learn", description="Learn", required_subsystems=(),
                       k7_classification="free", tags=("learning",)),
        CapabilitySpec(name="exam", description="Exam", required_subsystems=(),
                       k7_classification="free", tags=("learning",)),
        CapabilitySpec(name="fetch", description="Fetch", required_subsystems=(),
                       k7_classification="guarded", tags=("web",)),
    ]


@pytest.fixture
def mock_ctx():
    # HomeostasisCore exposes the live mode at core.state.mode (real Mode enum);
    # attach a state stand-in via specced kwargs (state is an instance attr).
    hcore = specced(HomeostasisCore, state=SimpleNamespace(mode=Mode.ACTIVE))
    ctx = specced(SharedContext,
                  homeostasis_core=hcore,
                  autonomy_policy=None,
                  meta_cognition=None,
                  openclaw_client=None,
                  codex_client=None,
                  telegram_bridge=None,
                  brain=None,
                  llm_router=None,
                  planner_core=None,
                  trace_store=None,
                  llm_tape=None,
                  brain_model="llama3.1:8b")

    # Identity store
    identity = specced(IdentityStore, _data={"onboarding_completed": True})
    identity.get_identity_dict.return_value = {
        "session_count": 42, "total_uptime_hours": 100,
        "birth_date": "2025-11-14", "age_string": "5 miesiecy",
        "primary_user": "Operator",
    }
    ctx.identity_store = identity

    # Consciousness — self_model is an instance attr set in __init__, attach via specced
    self_model = specced(SelfModelBuilder)
    self_model.get_traits.return_value = ["ciekawska"]
    self_model.get_trait_scores.return_value = {}
    consciousness = specced(ConsciousnessCore, self_model=self_model)
    ctx.consciousness = consciousness

    # Capability router
    router = specced(CapabilityRouter)
    router.list_capabilities.return_value = _make_specs()
    router.is_available.return_value = True
    router.dispatch.return_value = {"success": True}
    ctx.capability_router = router

    # Context builder
    builder = specced(ContextBuilder)
    builder.get_detailed_file_list.return_value = [
        {"file": "fizyka.txt", "status": "learned"},
    ]
    builder.get_input_files.return_value = ["fizyka.txt"]
    ctx.context_builder = builder

    # Goal store
    goal_store = specced(GoalStore)
    goal_store.create.return_value = "goal-test"
    goal_store.get.return_value = None
    goal_store.get_active.return_value = []
    goal_store.get_all.return_value = []
    ctx.goal_store = goal_store

    return ctx


@pytest.fixture
def shell(mock_ctx):
    return ProductShell(mock_ctx)


# ===========================================================================
# ProductShell - Identity
# ===========================================================================

class TestProductShellIdentity:

    def test_who_am_i(self, shell):
        text = shell.who_am_i()
        assert "Maria" in text

    def test_what_can_i_do(self, shell):
        text = shell.what_can_i_do()
        assert "zdolnosci" in text

    def test_limitations(self, shell):
        text = shell.limitations()
        assert "Ograniczenia" in text

    def test_get_status(self, shell):
        status = shell.get_status()
        assert "identity" in status
        assert "capabilities" in status
        assert "budget" in status
        assert "limitations" in status
        assert status["onboarding_completed"] is True


# ===========================================================================
# ProductShell - Task Flow
# ===========================================================================

class TestProductShellDo:

    def test_do_returns_rich_result(self, shell):
        result = shell.do("naucz sie fizyki")
        assert "task_id" in result
        assert "plan" in result
        assert "cost" in result
        assert "time" in result
        assert "resources" in result
        assert "plan_describe" in result
        assert "cost_describe" in result

    def test_do_has_text_descriptions(self, shell):
        result = shell.do("naucz sie fizyki")
        assert isinstance(result["plan_describe"], str)
        assert isinstance(result["cost_describe"], str)
        assert isinstance(result["time_describe"], str)

    def test_do_is_executable(self, shell):
        result = shell.do("naucz sie fizyki")
        assert result["is_executable"] is True

    def test_do_auto_approve(self, shell, mock_ctx):
        result = shell.do("naucz sie fizyki", auto_approve=True)
        assert result["auto_approved"] is True
        assert result["goal_id"] == "goal-test"

    def test_do_and_describe(self, shell):
        text = shell.do_and_describe("naucz sie fizyki")
        assert "Zadanie:" in text
        assert "Plan wykonania:" in text
        assert "koszt" in text.lower()
        assert "Task ID:" in text


class TestProductShellApproveCancel:

    def test_approve(self, shell, mock_ctx):
        result = shell.do("naucz sie fizyki")
        goal_id = shell.approve(result["task_id"])
        assert goal_id == "goal-test"

    def test_cancel(self, shell):
        result = shell.do("naucz sie fizyki")
        assert shell.cancel(result["task_id"]) is True

    def test_progress(self, shell):
        result = shell.do("naucz sie fizyki")
        prog = shell.progress(result["task_id"])
        assert prog is not None
        assert prog["status"] == "planned"

    def test_tasks_list(self, shell):
        shell.do("naucz sie fizyki")
        shell.do("powtorz chemie")
        tasks = shell.tasks()
        assert len(tasks) == 2


# ===========================================================================
# ProductShell - Execution
# ===========================================================================

class TestProductShellExecute:

    def test_can_execute(self, shell):
        result = shell.can_execute("learn")
        assert result["can_execute"] is True

    def test_execute(self, shell):
        result = shell.execute("learn")
        assert result["success"] is True


# ===========================================================================
# V3Module (REPL)
# ===========================================================================

class TestV3Module:

    def test_module_init(self, mock_ctx):
        from agent_core.modules.v3_module import V3Module
        mod = V3Module()
        assert mod.init(mock_ctx) is True

    def test_module_commands(self, mock_ctx):
        from agent_core.modules.v3_module import V3Module
        mod = V3Module()
        mod.init(mock_ctx)
        commands = mod.get_commands()
        assert len(commands) == 1
        assert commands[0].name == "/v3"

    def test_module_status(self, mock_ctx, capsys):
        from agent_core.modules.v3_module import V3Module
        mod = V3Module()
        mod.init(mock_ctx)
        mod._cmd_v3([])
        captured = capsys.readouterr()
        assert "V3 Product Shell" in captured.out

    def test_module_who(self, mock_ctx, capsys):
        from agent_core.modules.v3_module import V3Module
        mod = V3Module()
        mod.init(mock_ctx)
        mod._cmd_v3(["who"])
        captured = capsys.readouterr()
        assert "Maria" in captured.out

    def test_module_what(self, mock_ctx, capsys):
        from agent_core.modules.v3_module import V3Module
        mod = V3Module()
        mod.init(mock_ctx)
        mod._cmd_v3(["what"])
        captured = capsys.readouterr()
        assert "zdolnosci" in captured.out

    def test_module_do_no_args(self, mock_ctx, capsys):
        from agent_core.modules.v3_module import V3Module
        mod = V3Module()
        mod.init(mock_ctx)
        mod._cmd_v3(["do"])
        captured = capsys.readouterr()
        assert "Uzyj" in captured.out

    def test_module_do_with_task(self, mock_ctx, capsys):
        from agent_core.modules.v3_module import V3Module
        mod = V3Module()
        mod.init(mock_ctx)
        mod._cmd_v3(["do", "naucz", "sie", "fizyki"])
        captured = capsys.readouterr()
        assert "Plan wykonania" in captured.out

    def test_module_tasks_empty(self, mock_ctx, capsys):
        from agent_core.modules.v3_module import V3Module
        mod = V3Module()
        mod.init(mock_ctx)
        mod._cmd_v3(["tasks"])
        captured = capsys.readouterr()
        assert "Brak zadan" in captured.out

    def test_module_budget(self, mock_ctx, capsys):
        from agent_core.modules.v3_module import V3Module
        mod = V3Module()
        mod.init(mock_ctx)
        mod._cmd_v3(["budget"])
        captured = capsys.readouterr()
        assert "NIM" in captured.out

    def test_module_limits(self, mock_ctx, capsys):
        from agent_core.modules.v3_module import V3Module
        mod = V3Module()
        mod.init(mock_ctx)
        mod._cmd_v3(["limits"])
        captured = capsys.readouterr()
        assert "Ograniczenia" in captured.out

    def test_module_tools(self, mock_ctx, capsys):
        from agent_core.modules.v3_module import V3Module
        mod = V3Module()
        mod.init(mock_ctx)
        mod._cmd_v3(["tools"])
        captured = capsys.readouterr()
        assert "Serwisy" in captured.out
