"""Tests for V3 Phase B: TaskDecomposer, ExecutionPlanBuilder, TaskOrchestrator."""

import time
import pytest
from unittest.mock import MagicMock, patch

from agent_core.orchestrator.task_decomposer import (
    TaskDecomposer,
    TaskCategory,
    TaskStep,
    DecomposedTask,
)
from agent_core.orchestrator.execution_plan import (
    ExecutionPlanBuilder,
    ExecutionPlan,
    StepConstraint,
)
from agent_core.orchestrator.task_orchestrator import (
    TaskOrchestrator,
    TaskStatus,
    TaskRecord,
    SubmitResult,
)
from agent_core.routing.capability_spec import CapabilitySpec


# ===========================================================================
# FIXTURES
# ===========================================================================

@pytest.fixture
def mock_ctx():
    """SharedContext with typical mocks."""
    ctx = MagicMock()
    ctx.homeostasis_core = MagicMock()
    mode = MagicMock()
    mode.name = "ACTIVE"
    ctx.homeostasis_core._current_mode = mode
    ctx.autonomy_policy = None
    ctx.capability_router = MagicMock()
    ctx.capability_router.is_available.return_value = True
    ctx.knowledge_analyzer = None
    ctx.goal_store = MagicMock()
    ctx.goal_store.create.return_value = "goal-test123"
    ctx.goal_store.get.return_value = None
    return ctx


@pytest.fixture
def decomposer(mock_ctx):
    return TaskDecomposer(mock_ctx)


@pytest.fixture
def plan_builder(mock_ctx):
    return ExecutionPlanBuilder(mock_ctx)


@pytest.fixture
def orchestrator(mock_ctx):
    return TaskOrchestrator(mock_ctx)


# ===========================================================================
# TaskDecomposer - Classification
# ===========================================================================

class TestTaskDecomposerClassify:

    def test_learn_keyword(self, decomposer):
        result = decomposer.decompose("naucz sie fizyki kwantowej")
        assert result.category == TaskCategory.LEARN_TOPIC

    def test_explore_keyword(self, decomposer):
        result = decomposer.decompose("znajdz informacje o genetyce")
        assert result.category == TaskCategory.EXPLORE_NEW

    def test_consolidate_keyword(self, decomposer):
        result = decomposer.decompose("powtorz material o chemii")
        assert result.category == TaskCategory.CONSOLIDATE

    def test_analyze_keyword(self, decomposer):
        result = decomposer.decompose("analizuj stan mojej wiedzy")
        assert result.category == TaskCategory.ANALYZE

    def test_fetch_keyword(self, decomposer):
        result = decomposer.decompose("pobierz z wikipedia o astronomii")
        assert result.category == TaskCategory.FETCH_INFO

    def test_system_keyword(self, decomposer):
        result = decomposer.decompose("diagnostyka systemu")
        assert result.category == TaskCategory.SYSTEM_CHECK

    def test_short_topic_defaults_to_learn(self, decomposer):
        result = decomposer.decompose("Python")
        assert result.category == TaskCategory.LEARN_TOPIC

    def test_english_keywords(self, decomposer):
        result = decomposer.decompose("learn about machine learning")
        assert result.category == TaskCategory.LEARN_TOPIC

    def test_unknown_long_text(self, decomposer):
        result = decomposer.decompose("ala ma kocura i psa a oni maja swoje budy i zabawki w domu")
        assert result.category == TaskCategory.UNKNOWN

    def test_exam_maps_to_consolidate(self, decomposer):
        result = decomposer.decompose("egzamin z biologii")
        assert result.category == TaskCategory.CONSOLIDATE


# ===========================================================================
# TaskDecomposer - Topic Extraction
# ===========================================================================

class TestTaskDecomposerTopic:

    def test_extracts_topic(self, decomposer):
        result = decomposer.decompose("naucz sie fizyki kwantowej")
        assert result.topic is not None
        assert "fizyk" in result.topic.lower()

    def test_short_input_is_topic(self, decomposer):
        result = decomposer.decompose("genetyka")
        assert result.topic is not None

    def test_removes_command_words(self, decomposer):
        result = decomposer.decompose("naucz sie o biologii")
        assert result.topic is not None
        assert "naucz" not in result.topic.lower()


# ===========================================================================
# TaskDecomposer - Step Building
# ===========================================================================

class TestTaskDecomposerSteps:

    def test_learn_topic_has_steps(self, decomposer):
        result = decomposer.decompose("naucz sie fizyki")
        assert len(result.steps) >= 3

    def test_learn_topic_starts_with_fetch_if_no_files(self, decomposer):
        # No knowledge_analyzer -> no files -> adds fetch step
        result = decomposer.decompose("naucz sie astronomii")
        actions = [s.action for s in result.steps]
        assert "fetch" in actions or "learn" in actions

    def test_explore_starts_with_fetch(self, decomposer):
        result = decomposer.decompose("znajdz informacje o kosmologii")
        assert result.steps[0].action == "fetch"

    def test_consolidate_starts_with_review(self, decomposer):
        result = decomposer.decompose("powtorz chemie")
        assert result.steps[0].action == "review"

    def test_analyze_has_evaluate_critique(self, decomposer):
        result = decomposer.decompose("analizuj stan wiedzy")
        actions = [s.action for s in result.steps]
        assert "evaluate" in actions
        assert "critique" in actions

    def test_fetch_info_single_step(self, decomposer):
        result = decomposer.decompose("pobierz z wikipedia o fizyce")
        assert len(result.steps) == 1
        assert result.steps[0].action == "fetch"

    def test_system_check_has_evaluate(self, decomposer):
        result = decomposer.decompose("diagnostyka systemu")
        actions = [s.action for s in result.steps]
        assert "evaluate" in actions

    def test_step_order_is_sequential(self, decomposer):
        result = decomposer.decompose("naucz sie biologii")
        orders = [s.order for s in result.steps]
        assert orders == sorted(orders)

    def test_learn_steps_have_fallbacks(self, decomposer):
        result = decomposer.decompose("naucz sie fizyki")
        exam_steps = [s for s in result.steps if s.action == "exam"]
        assert any(s.fallback_order is not None for s in exam_steps)

    def test_unknown_has_no_steps(self, decomposer):
        result = decomposer.decompose("ala ma kocura i psa a oni maja swoje budy i zabawki w domu")
        assert len(result.steps) == 0
        assert result.feasibility == "unclear"


# ===========================================================================
# TaskDecomposer - DecomposedTask
# ===========================================================================

class TestDecomposedTask:

    def test_to_dict(self, decomposer):
        result = decomposer.decompose("naucz sie fizyki")
        d = result.to_dict()
        assert "original_input" in d
        assert "category" in d
        assert "steps" in d
        assert isinstance(d["steps"], list)

    def test_total_estimated_actions(self, decomposer):
        result = decomposer.decompose("naucz sie fizyki")
        assert result.total_estimated_actions > 0

    def test_requires_network_for_explore(self, decomposer):
        result = decomposer.decompose("znajdz nowe materialy")
        assert result.requires_network is True

    def test_template_name_set(self, decomposer):
        result = decomposer.decompose("naucz sie fizyki")
        assert result.template_name == "learn_topic"

    def test_consolidate_template(self, decomposer):
        result = decomposer.decompose("powtorz biologie")
        assert result.template_name == "consolidate"

    def test_categories_list(self, decomposer):
        cats = decomposer.get_available_categories()
        assert len(cats) == 7  # 6 original + CODE
        assert all("category" in c for c in cats)


# ===========================================================================
# ExecutionPlanBuilder
# ===========================================================================

class TestExecutionPlanBuilder:

    def test_build_from_decomposition(self, plan_builder, decomposer):
        decomposed = decomposer.decompose("naucz sie fizyki")
        plan = plan_builder.build(decomposed)
        assert isinstance(plan, ExecutionPlan)
        assert plan.total_steps == len(decomposed.steps)

    def test_plan_has_llm_estimates(self, plan_builder, decomposer):
        decomposed = decomposer.decompose("naucz sie fizyki")
        plan = plan_builder.build(decomposed)
        assert plan.total_llm_calls > 0

    def test_plan_feasible_in_active_mode(self, plan_builder, decomposer):
        decomposed = decomposer.decompose("naucz sie fizyki")
        plan = plan_builder.build(decomposed)
        assert plan.feasibility == "feasible"
        assert plan.is_executable is True

    def test_plan_warnings_in_reduced_mode(self, plan_builder, decomposer, mock_ctx):
        mode = MagicMock()
        mode.name = "REDUCED"
        mock_ctx.homeostasis_core._current_mode = mode
        decomposed = decomposer.decompose("naucz sie fizyki")
        plan = plan_builder.build(decomposed)
        assert any("REDUCED" in w for w in plan.warnings)

    def test_plan_no_blocked_by_default(self, plan_builder, decomposer):
        decomposed = decomposer.decompose("naucz sie fizyki")
        plan = plan_builder.build(decomposed)
        assert len(plan.blocked_steps) == 0

    def test_plan_to_dict(self, plan_builder, decomposer):
        decomposed = decomposer.decompose("powtorz chemie")
        plan = plan_builder.build(decomposed)
        d = plan.to_dict()
        assert "steps" in d
        assert "total_llm_calls" in d
        assert "is_executable" in d

    def test_plan_describe_text(self, plan_builder, decomposer):
        decomposed = decomposer.decompose("naucz sie fizyki")
        plan = plan_builder.build(decomposed)
        text = plan.describe()
        assert "Plan wykonania" in text
        assert "krokow" in text

    def test_plan_network_warning(self, plan_builder, decomposer):
        decomposed = decomposer.decompose("znajdz informacje o kosmologii")
        plan = plan_builder.build(decomposed)
        assert any("sieci" in w for w in plan.warnings)

    def test_step_constraints_have_fields(self, plan_builder, decomposer):
        decomposed = decomposer.decompose("naucz sie fizyki")
        plan = plan_builder.build(decomposed)
        for step in plan.steps:
            assert isinstance(step, StepConstraint)
            assert isinstance(step.estimated_llm_calls, int)
            assert isinstance(step.is_available, bool)
            assert isinstance(step.is_blocked, bool)

    def test_unavailable_action_still_not_blocked(self, plan_builder, decomposer, mock_ctx):
        # Unavailable != blocked (blocked = K7 forbidden)
        mock_ctx.capability_router.is_available.return_value = False
        decomposed = decomposer.decompose("naucz sie fizyki")
        plan = plan_builder.build(decomposed)
        assert all(not s.is_available for s in plan.steps)
        assert len(plan.blocked_steps) == 0  # Not forbidden, just unavailable


# ===========================================================================
# TaskOrchestrator - Submit
# ===========================================================================

class TestTaskOrchestratorSubmit:

    def test_submit_returns_result(self, orchestrator):
        result = orchestrator.submit("naucz sie fizyki")
        assert isinstance(result, SubmitResult)
        assert result.task_id.startswith("task-")

    def test_submit_creates_decomposition(self, orchestrator):
        result = orchestrator.submit("naucz sie fizyki")
        assert result.decomposition.category == TaskCategory.LEARN_TOPIC

    def test_submit_creates_plan(self, orchestrator):
        result = orchestrator.submit("naucz sie fizyki")
        assert result.plan.total_steps > 0

    def test_submit_without_auto_approve(self, orchestrator):
        result = orchestrator.submit("naucz sie fizyki")
        assert result.auto_approved is False
        assert result.goal_id is None

    def test_submit_with_auto_approve(self, orchestrator, mock_ctx):
        result = orchestrator.submit("naucz sie fizyki", auto_approve=True)
        assert result.auto_approved is True
        assert result.goal_id == "goal-test123"
        mock_ctx.goal_store.create.assert_called_once()
        mock_ctx.goal_store.save.assert_called_once()

    def test_submit_stores_task(self, orchestrator):
        result = orchestrator.submit("naucz sie fizyki")
        task = orchestrator.get_task(result.task_id)
        assert task is not None
        assert task["description"] == "naucz sie fizyki"

    def test_submit_result_to_dict(self, orchestrator):
        result = orchestrator.submit("naucz sie fizyki")
        d = result.to_dict()
        assert "task_id" in d
        assert "plan" in d
        assert "decomposition" in d


# ===========================================================================
# TaskOrchestrator - Approve / Cancel
# ===========================================================================

class TestTaskOrchestratorApproveCancel:

    def test_approve_creates_goal(self, orchestrator, mock_ctx):
        result = orchestrator.submit("naucz sie fizyki")
        goal_id = orchestrator.approve(result.task_id)
        assert goal_id == "goal-test123"
        mock_ctx.goal_store.create.assert_called_once()

    def test_approve_changes_status(self, orchestrator):
        result = orchestrator.submit("naucz sie fizyki")
        orchestrator.approve(result.task_id)
        task = orchestrator.get_task(result.task_id)
        assert task["status"] == TaskStatus.APPROVED

    def test_approve_nonexistent_returns_none(self, orchestrator):
        assert orchestrator.approve("task-nonexistent") is None

    def test_approve_twice_returns_goal_id(self, orchestrator):
        result = orchestrator.submit("naucz sie fizyki")
        orchestrator.approve(result.task_id)
        goal_id = orchestrator.approve(result.task_id)
        assert goal_id == "goal-test123"

    def test_cancel_task(self, orchestrator):
        result = orchestrator.submit("naucz sie fizyki")
        assert orchestrator.cancel(result.task_id) is True
        task = orchestrator.get_task(result.task_id)
        assert task["status"] == TaskStatus.CANCELLED

    def test_cancel_nonexistent(self, orchestrator):
        assert orchestrator.cancel("task-nonexistent") is False

    def test_cancel_already_cancelled(self, orchestrator):
        result = orchestrator.submit("naucz sie fizyki")
        orchestrator.cancel(result.task_id)
        assert orchestrator.cancel(result.task_id) is False


# ===========================================================================
# TaskOrchestrator - Progress
# ===========================================================================

class TestTaskOrchestratorProgress:

    def test_get_progress(self, orchestrator):
        result = orchestrator.submit("naucz sie fizyki")
        progress = orchestrator.get_progress(result.task_id)
        assert progress is not None
        assert progress["status"] == TaskStatus.PLANNED
        assert progress["progress"] == 0.0

    def test_get_progress_nonexistent(self, orchestrator):
        assert orchestrator.get_progress("task-nonexistent") is None

    def test_progress_syncs_from_goal(self, orchestrator, mock_ctx):
        result = orchestrator.submit("naucz sie fizyki", auto_approve=True)

        # Simulate goal progress
        mock_goal = MagicMock()
        mock_goal.progress = 0.6
        mock_goal.status.value = "active"
        mock_goal.is_terminal = False
        mock_ctx.goal_store.get.return_value = mock_goal

        progress = orchestrator.get_progress(result.task_id)
        assert progress["progress"] == 0.6
        assert progress["status"] == TaskStatus.EXECUTING

    def test_progress_syncs_completed(self, orchestrator, mock_ctx):
        result = orchestrator.submit("naucz sie fizyki", auto_approve=True)

        mock_goal = MagicMock()
        mock_goal.progress = 1.0
        mock_goal.status.value = "achieved"
        mock_goal.outcome = {"score": 0.9}
        mock_ctx.goal_store.get.return_value = mock_goal

        progress = orchestrator.get_progress(result.task_id)
        assert progress["status"] == TaskStatus.COMPLETED


# ===========================================================================
# TaskOrchestrator - List
# ===========================================================================

class TestTaskOrchestratorList:

    def test_list_empty(self, orchestrator):
        assert orchestrator.list_tasks() == []

    def test_list_after_submit(self, orchestrator):
        orchestrator.submit("naucz sie fizyki")
        orchestrator.submit("powtorz chemie")
        tasks = orchestrator.list_tasks()
        assert len(tasks) == 2

    def test_list_filtered(self, orchestrator):
        orchestrator.submit("naucz sie fizyki")
        r2 = orchestrator.submit("powtorz chemie")
        orchestrator.approve(r2.task_id)
        planned = orchestrator.list_tasks(status=TaskStatus.PLANNED)
        assert len(planned) == 1
        approved = orchestrator.list_tasks(status=TaskStatus.APPROVED)
        assert len(approved) == 1

    def test_list_has_required_fields(self, orchestrator):
        orchestrator.submit("naucz sie fizyki")
        tasks = orchestrator.list_tasks()
        task = tasks[0]
        assert "task_id" in task
        assert "description" in task
        assert "status" in task
        assert "category" in task
        assert "steps" in task


# ===========================================================================
# TaskOrchestrator - Convenience
# ===========================================================================

class TestTaskOrchestratorConvenience:

    def test_submit_and_approve(self, orchestrator, mock_ctx):
        result = orchestrator.submit_and_approve("naucz sie fizyki")
        assert result.auto_approved is True
        assert result.goal_id == "goal-test123"

    def test_get_decomposer(self, orchestrator):
        assert isinstance(orchestrator.get_decomposer(), TaskDecomposer)

    def test_get_plan_builder(self, orchestrator):
        assert isinstance(orchestrator.get_plan_builder(), ExecutionPlanBuilder)

    def test_trim_old_tasks(self, orchestrator):
        for i in range(60):
            r = orchestrator.submit(f"task {i}")
            orchestrator.cancel(r.task_id)
        # Should be trimmed to MAX_TASKS
        assert len(orchestrator._tasks) <= orchestrator.MAX_TASKS


# ===========================================================================
# TaskOrchestrator - No GoalStore
# ===========================================================================

class TestTaskOrchestratorNoGoalStore:

    def test_approve_without_goal_store(self, mock_ctx):
        mock_ctx.goal_store = None
        orch = TaskOrchestrator(mock_ctx)
        result = orch.submit("naucz sie fizyki")
        goal_id = orch.approve(result.task_id)
        assert goal_id is None

    def test_auto_approve_without_goal_store(self, mock_ctx):
        mock_ctx.goal_store = None
        orch = TaskOrchestrator(mock_ctx)
        result = orch.submit("naucz sie fizyki", auto_approve=True)
        # No goal store means auto_approve can't create goal
        # Plan is still executable but no goal created
        assert result.goal_id is None


# ===========================================================================
# TaskStep frozen dataclass
# ===========================================================================

class TestTaskStep:

    def test_frozen(self):
        step = TaskStep(order=0, action="learn", description="test")
        with pytest.raises(AttributeError):
            step.order = 1

    def test_defaults(self):
        step = TaskStep(order=0, action="learn", description="test")
        assert step.estimated_actions == 1
        assert step.requires_llm is False
        assert step.k7_classification == "free"


# ===========================================================================
# StepConstraint frozen dataclass
# ===========================================================================

class TestStepConstraint:

    def test_frozen(self):
        sc = StepConstraint(
            step_order=0, action="learn", description="test",
            estimated_llm_calls=3, k7_classification="free",
            is_available=True, is_blocked=False, block_reason="",
            requires_approval=False,
        )
        with pytest.raises(AttributeError):
            sc.step_order = 1
