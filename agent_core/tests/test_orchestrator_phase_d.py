"""Tests for V3 Phase D: ExecutionRouter, ToolCapabilityRegistry, TaskProgressTracker, LimitationReporter."""

import time
import pytest
from unittest.mock import MagicMock

from agent_core.orchestrator.execution_router import ExecutionRouter
from agent_core.orchestrator.tool_registry import ToolCapabilityRegistry
from agent_core.orchestrator.progress_tracker import TaskProgressTracker
from agent_core.orchestrator.limitation_reporter import LimitationReporter
from agent_core.routing.capability_spec import CapabilitySpec
from agent_core.routing.capability_router import CapabilityRouter
from agent_core.goals.store import GoalStore
from agent_core.goals.goal_model import AuditEntry
from agent_core.registry.shared_context import SharedContext
from agent_core.homeostasis.state_model import Mode
from agent_core.autonomy import AutonomyPolicy
from agent_core.tests.spec_helpers import specced


# ===========================================================================
# FIXTURES
# ===========================================================================

def _make_specs():
    return [
        CapabilitySpec(name="learn", description="Learn", required_subsystems=(),
                       k7_classification="free", tags=("learning",)),
        CapabilitySpec(name="exam", description="Exam", required_subsystems=(),
                       k7_classification="free", tags=("learning",)),
        CapabilitySpec(name="fetch", description="Fetch web", required_subsystems=(),
                       k7_classification="guarded", tags=("web",)),
        CapabilitySpec(name="effector", description="OpenClaw", required_subsystems=(),
                       k7_classification="restricted", tags=("external",)),
        CapabilitySpec(name="self_analyze", description="K12", required_subsystems=(),
                       k7_classification="guarded", tags=("meta",)),
    ]


@pytest.fixture
def mock_ctx():
    ctx = specced(SharedContext)
    # HomeostasisCore exposes the live mode at core.state.mode (real Mode enum).
    # Guards bug #4: if production regresses to the phantom `_current_mode`, the
    # mode-dependent tests below go red (a MagicMock _current_mode.name != "SLEEP").
    ctx.homeostasis_core = MagicMock()
    ctx.homeostasis_core.state.mode = Mode.ACTIVE
    ctx.autonomy_policy = None
    ctx.meta_cognition = None
    ctx.openclaw_client = None
    ctx.codex_client = None
    ctx.telegram_bridge = None
    ctx.brain = None
    ctx.llm_router = None
    ctx.planner_core = None
    ctx.trace_store = None
    ctx.brain_model = "llama3.1:8b"

    router = specced(CapabilityRouter)
    router.list_capabilities.return_value = _make_specs()
    router.is_available.return_value = True
    router.dispatch.return_value = {"success": True, "chunks_learned": 3}
    ctx.capability_router = router

    goal_store = specced(GoalStore)
    goal_store.get.return_value = None
    goal_store.get_active.return_value = []
    goal_store.get_all.return_value = []
    ctx.goal_store = goal_store

    return ctx


@pytest.fixture
def exec_router(mock_ctx):
    return ExecutionRouter(mock_ctx)


@pytest.fixture
def tool_registry(mock_ctx):
    return ToolCapabilityRegistry(mock_ctx)


@pytest.fixture
def progress_tracker(mock_ctx):
    return TaskProgressTracker(mock_ctx)


@pytest.fixture
def limitation_reporter(mock_ctx):
    return LimitationReporter(mock_ctx)


# ===========================================================================
# ExecutionRouter
# ===========================================================================

class TestExecutionRouterCanExecute:

    def test_can_execute_available(self, exec_router):
        result = exec_router.can_execute("learn")
        assert result["can_execute"] is True
        assert result["available"] is True

    def test_can_execute_has_cost(self, exec_router):
        result = exec_router.can_execute("learn")
        assert "cost" in result
        assert "time_estimate" in result

    def test_cannot_execute_unavailable(self, exec_router, mock_ctx):
        mock_ctx.capability_router.is_available.return_value = False
        result = exec_router.can_execute("learn")
        assert result["can_execute"] is False


class TestExecutionRouterExecute:

    def test_execute_success(self, exec_router):
        result = exec_router.execute("learn", {"topics": ["fizyka"]})
        assert result["success"] is True
        assert "elapsed_ms" in result
        assert "cost" in result

    def test_execute_blocked(self, exec_router, mock_ctx):
        mock_ctx.capability_router.is_available.return_value = False
        result = exec_router.execute("learn")
        assert result["success"] is False

    def test_execute_no_router(self, mock_ctx):
        del mock_ctx.capability_router
        router = ExecutionRouter(mock_ctx)
        result = router.execute("learn")
        assert result["success"] is False


class TestExecutionRouterList:

    def test_list_available(self, exec_router):
        actions = exec_router.list_available()
        assert len(actions) == 5
        assert all("cost" in a for a in actions)
        assert all("time_estimate" in a for a in actions)

    def test_status(self, exec_router):
        status = exec_router.get_status()
        assert status["total_capabilities"] == 5
        assert status["available_capabilities"] == 5
        assert "budget" in status


# ===========================================================================
# ToolCapabilityRegistry
# ===========================================================================

class TestToolRegistryList:

    def test_list_all(self, tool_registry):
        tools = tool_registry.list_all()
        assert len(tools) == 5
        assert all("category" in t for t in tools)

    def test_list_by_category(self, tool_registry):
        grouped = tool_registry.list_by_category()
        assert "Nauka" in grouped
        assert len(grouped["Nauka"]) == 2  # learn + exam

    def test_requires_approval(self, tool_registry):
        tools = tool_registry.list_all()
        effector = [t for t in tools if t["name"] == "effector"][0]
        assert effector["requires_approval"] is True
        learn = [t for t in tools if t["name"] == "learn"][0]
        assert learn["requires_approval"] is False


class TestToolRegistryExternal:

    def test_list_external_services(self, tool_registry):
        services = tool_registry.list_external_services()
        assert len(services) >= 4
        names = [s["name"] for s in services]
        assert "Ollama (local LLM)" in names
        assert "OpenClaw Effector" in names

    def test_ollama_always_available(self, tool_registry):
        services = tool_registry.list_external_services()
        ollama = [s for s in services if "Ollama" in s["name"]][0]
        assert ollama["status"] == "available"

    def test_openclaw_disconnected(self, tool_registry):
        services = tool_registry.list_external_services()
        oc = [s for s in services if "OpenClaw" in s["name"]][0]
        assert oc["status"] == "disconnected"


class TestToolRegistrySearch:

    def test_search_by_name(self, tool_registry):
        results = tool_registry.search("effector")
        assert len(results) == 1
        assert results[0]["name"] == "effector"

    def test_search_by_tag(self, tool_registry):
        results = tool_registry.search("learning")
        assert len(results) == 2

    def test_search_no_results(self, tool_registry):
        results = tool_registry.search("nonexistent")
        assert len(results) == 0


class TestToolRegistrySummary:

    def test_summary(self, tool_registry):
        summary = tool_registry.get_summary()
        assert summary["total_capabilities"] == 5
        assert summary["free"] == 2
        assert summary["guarded"] == 2
        assert summary["restricted"] == 1

    def test_describe(self, tool_registry):
        text = tool_registry.describe()
        assert "zdolnosci" in text
        assert "Nauka" in text


# ===========================================================================
# TaskProgressTracker
# ===========================================================================

class TestProgressTrackerActive:

    def test_get_active_empty(self, progress_tracker):
        active = progress_tracker.get_active_tasks()
        assert active == []

    def test_get_active_with_goals(self, progress_tracker, mock_ctx):
        goal = MagicMock()
        goal.id = "g1"
        goal.description = "Nauka fizyki"
        goal.type.value = "learning"
        goal.status.value = "active"
        goal.progress = 0.5
        goal.priority = 0.8
        goal.metadata = {"source": "orchestrator"}
        goal.created_at = time.time()
        mock_ctx.goal_store.get_active.return_value = [goal]

        active = progress_tracker.get_active_tasks()
        assert len(active) == 1
        assert active[0]["progress"] == 0.5

    def test_get_completed_empty(self, progress_tracker):
        completed = progress_tracker.get_completed_tasks()
        assert completed == []


class TestProgressTrackerGoal:

    def test_get_progress_not_found(self, progress_tracker):
        assert progress_tracker.get_task_progress("nonexistent") is None

    def test_get_progress_found(self, progress_tracker, mock_ctx):
        goal = MagicMock()
        goal.id = "g1"
        goal.description = "Test"
        goal.type.value = "learning"
        goal.status.value = "active"
        goal.progress = 0.3
        goal.priority = 0.8
        goal.created_at = time.time()
        goal.updated_at = time.time()
        goal.metadata = {}
        goal.outcome = None
        goal.audit_trail = []
        mock_ctx.goal_store.get.return_value = goal

        progress = progress_tracker.get_task_progress("g1")
        assert progress is not None
        assert progress["progress"] == 0.3
        assert progress["goal_id"] == "g1"


class TestProgressTrackerTimeline:

    def test_timeline_empty(self, progress_tracker, mock_ctx):
        mock_ctx.goal_store.get.return_value = None
        timeline = progress_tracker.get_timeline("g1")
        assert timeline == []

    def test_timeline_with_audit(self, progress_tracker, mock_ctx):
        ts = time.time()
        entry = specced(AuditEntry, timestamp=ts, old_status=None,
                        new_status="active", reason="created", actor="user")
        entry.to_dict.return_value = {"timestamp": ts}

        goal = MagicMock()
        goal.audit_trail = [entry]
        mock_ctx.goal_store.get.return_value = goal

        timeline = progress_tracker.get_timeline("g1")
        assert len(timeline) == 1
        assert timeline[0]["type"] == "status_change"


class TestProgressTrackerSummary:

    def test_summary(self, progress_tracker):
        summary = progress_tracker.get_summary()
        assert "active_count" in summary
        assert "planner" in summary

    def test_planner_stats_no_planner(self, progress_tracker):
        stats = progress_tracker.get_planner_stats()
        assert stats["available"] is False


# ===========================================================================
# LimitationReporter
# ===========================================================================

class TestLimitationReporterLimitations:

    def test_active_mode_no_mode_limits(self, limitation_reporter):
        lims = limitation_reporter.get_current_limitations()
        mode_lims = [l for l in lims if l["category"] == "mode"]
        assert len(mode_lims) == 0

    def test_reduced_mode_has_warning(self, limitation_reporter, mock_ctx):
        mock_ctx.homeostasis_core.state.mode = Mode.REDUCED
        lims = limitation_reporter.get_current_limitations()
        mode_lims = [l for l in lims if l["category"] == "mode"]
        assert len(mode_lims) == 1
        assert mode_lims[0]["severity"] == "warning"

    def test_sleep_mode_critical(self, limitation_reporter, mock_ctx):
        mock_ctx.homeostasis_core.state.mode = Mode.SLEEP
        lims = limitation_reporter.get_current_limitations()
        mode_lims = [l for l in lims if l["category"] == "mode"]
        assert mode_lims[0]["severity"] == "critical"

    def test_hardware_limitations_always_present(self, limitation_reporter):
        lims = limitation_reporter.get_current_limitations()
        hw_lims = [l for l in lims if l["category"] == "hardware"]
        assert len(hw_lims) >= 2  # LLM + input files + maybe OpenClaw

    def test_openclaw_missing_reported(self, limitation_reporter):
        lims = limitation_reporter.get_current_limitations()
        oc_lims = [l for l in lims if "OpenClaw" in l["description"]]
        assert len(oc_lims) == 1


class TestLimitationReporterCanDo:

    def test_can_do_learn(self, limitation_reporter):
        result = limitation_reporter.can_do("learn")
        assert result["can_do"] is True
        assert result["reasons"] == []

    def test_cannot_do_in_sleep(self, limitation_reporter, mock_ctx):
        mock_ctx.homeostasis_core.state.mode = Mode.SLEEP
        result = limitation_reporter.can_do("learn")
        assert result["can_do"] is False
        assert len(result["reasons"]) > 0

    def test_can_do_noop_in_sleep(self, limitation_reporter, mock_ctx):
        mock_ctx.homeostasis_core.state.mode = Mode.SLEEP
        result = limitation_reporter.can_do("noop")
        assert result["can_do"] is True

    def test_restricted_has_suggestion(self, limitation_reporter, mock_ctx):
        # Bug #3 guard: K7 classify_action is a MODULE function (action_class.py),
        # NOT a method on AutonomyPolicy -- limitation_reporter must call the module
        # func. policy here only needs to be truthy ("is K7 wired"). An unregistered
        # action classifies RESTRICTED (safe-by-default) -> "/approve" suggestion.
        # If production regresses to policy.classify_action(...) this goes red.
        mock_ctx.autonomy_policy = specced(AutonomyPolicy)

        result = limitation_reporter.can_do("some_unregistered_action_xyz")
        assert any("approve" in s.lower() for s in result["suggestions"])


class TestLimitationReporterBlocked:

    def test_get_blocked_actions_active(self, limitation_reporter):
        blocked = limitation_reporter.get_blocked_actions()
        assert len(blocked) == 0  # ACTIVE mode, all available

    def test_get_blocked_in_sleep(self, limitation_reporter, mock_ctx):
        mock_ctx.homeostasis_core.state.mode = Mode.SLEEP
        blocked = limitation_reporter.get_blocked_actions()
        assert len(blocked) > 0  # Most actions blocked in SLEEP


class TestLimitationReporterReport:

    def test_report_structure(self, limitation_reporter):
        report = limitation_reporter.get_report()
        assert "total_limitations" in report
        assert "by_severity" in report
        assert "blocked_actions" in report
        assert "mode" in report

    def test_describe(self, limitation_reporter):
        text = limitation_reporter.describe()
        assert "Ograniczenia" in text
