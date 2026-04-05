"""Tests for V3 Phase C: CostEstimator, TimeEstimator, FreeVsPaidPlanner."""

import pytest
from unittest.mock import MagicMock

from agent_core.orchestrator.cost_estimator import (
    CostEstimator,
    ActionCost,
    PlanCost,
    BudgetStatus,
)
from agent_core.orchestrator.time_estimator import (
    TimeEstimator,
    TimeEstimate,
    PlanTimeEstimate,
    _format_duration,
)
from agent_core.orchestrator.free_vs_paid import (
    FreeVsPaidPlanner,
    ResourceStrategy,
    ActionRecommendation,
    PlanRecommendation,
)


# ===========================================================================
# FIXTURES
# ===========================================================================

@pytest.fixture
def mock_ctx():
    ctx = MagicMock()
    ctx.homeostasis_core = MagicMock()
    mode = MagicMock()
    mode.name = "ACTIVE"
    ctx.homeostasis_core._current_mode = mode
    ctx.brain = None
    ctx.llm_router = None
    ctx.codex_client = None
    ctx.claude_client = None
    ctx.llm_tape = None
    return ctx


@pytest.fixture
def cost_estimator(mock_ctx):
    return CostEstimator(mock_ctx)


@pytest.fixture
def time_estimator(mock_ctx):
    return TimeEstimator(mock_ctx)


@pytest.fixture
def fvp_planner(mock_ctx):
    return FreeVsPaidPlanner(mock_ctx)


@pytest.fixture
def mock_plan():
    """Mock ExecutionPlan with a few steps."""
    plan = MagicMock()
    step1 = MagicMock()
    step1.action = "learn"
    step2 = MagicMock()
    step2.action = "exam"
    step3 = MagicMock()
    step3.action = "self_analyze"
    plan.steps = [step1, step2, step3]
    return plan


@pytest.fixture
def free_plan():
    """Mock plan with only free actions."""
    plan = MagicMock()
    step1 = MagicMock()
    step1.action = "learn"
    step2 = MagicMock()
    step2.action = "exam"
    step3 = MagicMock()
    step3.action = "evaluate"
    plan.steps = [step1, step2, step3]
    return plan


# ===========================================================================
# CostEstimator - ActionCost
# ===========================================================================

class TestCostEstimatorAction:

    def test_learn_is_free(self, cost_estimator):
        cost = cost_estimator.estimate_action("learn")
        assert cost.is_free is True
        assert cost.local_llm_calls == 3
        assert cost.nim_tokens == 0

    def test_exam_is_free(self, cost_estimator):
        cost = cost_estimator.estimate_action("exam")
        assert cost.is_free is True
        assert cost.local_llm_calls == 2

    def test_self_analyze_uses_nim(self, cost_estimator):
        cost = cost_estimator.estimate_action("self_analyze")
        assert cost.is_free is False
        assert cost.nim_tokens == 2500

    def test_creative_uses_nim(self, cost_estimator):
        cost = cost_estimator.estimate_action("creative")
        assert cost.nim_tokens == 1500

    def test_evaluate_zero_cost(self, cost_estimator):
        cost = cost_estimator.estimate_action("evaluate")
        assert cost.is_free is True
        assert cost.local_llm_calls == 0
        assert cost.nim_tokens == 0

    def test_ask_expert_external(self, cost_estimator):
        cost = cost_estimator.estimate_action("ask_expert")
        assert cost.external_calls == 1

    def test_multiplier(self, cost_estimator):
        cost = cost_estimator.estimate_action("learn", multiplier=3)
        assert cost.local_llm_calls == 9

    def test_unknown_action(self, cost_estimator):
        cost = cost_estimator.estimate_action("unknown_action")
        assert cost.local_llm_calls == 1  # Default

    def test_action_cost_to_dict(self, cost_estimator):
        cost = cost_estimator.estimate_action("learn")
        d = cost.to_dict()
        assert "action" in d
        assert "is_free" in d
        assert d["action"] == "learn"


# ===========================================================================
# CostEstimator - PlanCost
# ===========================================================================

class TestCostEstimatorPlan:

    def test_plan_cost_aggregates(self, cost_estimator, mock_plan):
        plan_cost = cost_estimator.estimate_plan(mock_plan)
        assert isinstance(plan_cost, PlanCost)
        assert plan_cost.total_local_calls == 5  # learn(3) + exam(2)
        assert plan_cost.total_nim_tokens == 2500  # self_analyze

    def test_free_plan(self, cost_estimator, free_plan):
        plan_cost = cost_estimator.estimate_plan(free_plan)
        assert plan_cost.is_free is True
        assert plan_cost.total_nim_tokens == 0

    def test_plan_cost_to_dict(self, cost_estimator, mock_plan):
        plan_cost = cost_estimator.estimate_plan(mock_plan)
        d = plan_cost.to_dict()
        assert "total_nim_tokens" in d
        assert "step_costs" in d
        assert len(d["step_costs"]) == 3

    def test_plan_cost_describe(self, cost_estimator, mock_plan):
        plan_cost = cost_estimator.estimate_plan(mock_plan)
        text = plan_cost.describe()
        assert "koszt" in text.lower()


# ===========================================================================
# CostEstimator - BudgetStatus
# ===========================================================================

class TestCostEstimatorBudget:

    def test_budget_defaults(self, cost_estimator):
        budget = cost_estimator.get_budget_status()
        assert isinstance(budget, BudgetStatus)
        assert budget.nim_remaining_today == 100000
        assert budget.nim_status == "OK"
        assert budget.local_available is True

    def test_budget_to_dict(self, cost_estimator):
        budget = cost_estimator.get_budget_status()
        d = budget.to_dict()
        assert "nim_remaining_today" in d
        assert "claude_calls_remaining_hour" in d


# ===========================================================================
# TimeEstimator - ActionTime
# ===========================================================================

class TestTimeEstimatorAction:

    def test_learn_time(self, time_estimator):
        est = time_estimator.estimate_action("learn")
        assert est.seconds == 180.0
        assert est.confidence == "medium"

    def test_evaluate_fast(self, time_estimator):
        est = time_estimator.estimate_action("evaluate")
        assert est.seconds == 5.0
        assert est.confidence == "high"

    def test_noop_zero(self, time_estimator):
        est = time_estimator.estimate_action("noop")
        assert est.seconds == 0.0

    def test_fetch_low_confidence(self, time_estimator):
        est = time_estimator.estimate_action("fetch")
        assert est.confidence == "low"

    def test_multiplier(self, time_estimator):
        est = time_estimator.estimate_action("learn", multiplier=2)
        assert est.seconds == 360.0

    def test_label_format(self, time_estimator):
        est = time_estimator.estimate_action("learn")
        assert "min" in est.label

    def test_to_dict(self, time_estimator):
        est = time_estimator.estimate_action("exam")
        d = est.to_dict()
        assert d["action"] == "exam"
        assert "seconds" in d


# ===========================================================================
# TimeEstimator - PlanTime
# ===========================================================================

class TestTimeEstimatorPlan:

    def test_plan_total(self, time_estimator, mock_plan):
        plan_time = time_estimator.estimate_plan(mock_plan)
        assert isinstance(plan_time, PlanTimeEstimate)
        # learn(180) + exam(120) + self_analyze(30) + cold_start(15)
        assert plan_time.total_seconds >= 330

    def test_plan_includes_model_loading(self, time_estimator, mock_plan):
        plan_time = time_estimator.estimate_plan(mock_plan)
        assert plan_time.includes_model_loading is True  # self_analyze needs planner

    def test_free_plan_no_cold_start(self, time_estimator, free_plan):
        plan_time = time_estimator.estimate_plan(free_plan)
        assert plan_time.includes_model_loading is False

    def test_plan_label(self, time_estimator, mock_plan):
        plan_time = time_estimator.estimate_plan(mock_plan)
        assert plan_time.label != ""

    def test_plan_to_dict(self, time_estimator, mock_plan):
        plan_time = time_estimator.estimate_plan(mock_plan)
        d = plan_time.to_dict()
        assert "total_seconds" in d
        assert "step_estimates" in d

    def test_plan_describe(self, time_estimator, mock_plan):
        plan_time = time_estimator.estimate_plan(mock_plan)
        text = plan_time.describe()
        assert "czas" in text.lower()


# ===========================================================================
# TimeEstimator - format_duration
# ===========================================================================

class TestFormatDuration:

    def test_seconds(self):
        assert "sek" in _format_duration(30)

    def test_minutes(self):
        assert "min" in _format_duration(180)

    def test_one_minute(self):
        assert "1 min" in _format_duration(90)

    def test_hours(self):
        assert "godz" in _format_duration(7200)


# ===========================================================================
# FreeVsPaidPlanner - ActionRecommendation
# ===========================================================================

class TestFreeVsPaidAction:

    def test_learn_local_only(self, fvp_planner):
        rec = fvp_planner.recommend("learn")
        assert rec.strategy == ResourceStrategy.LOCAL_ONLY
        assert rec.backend == "ollama"

    def test_exam_local_only(self, fvp_planner):
        rec = fvp_planner.recommend("exam")
        assert rec.strategy == ResourceStrategy.LOCAL_ONLY

    def test_evaluate_local(self, fvp_planner):
        rec = fvp_planner.recommend("evaluate")
        assert rec.strategy == ResourceStrategy.LOCAL_ONLY

    def test_fetch_local(self, fvp_planner):
        rec = fvp_planner.recommend("fetch")
        assert rec.strategy == ResourceStrategy.LOCAL_ONLY

    def test_self_analyze_prefers_nim(self, fvp_planner):
        rec = fvp_planner.recommend("self_analyze")
        # Default budget is OK -> prefer NIM
        assert rec.backend == "nim"
        assert rec.fallback_backend == "ollama"

    def test_creative_uses_nim(self, fvp_planner):
        rec = fvp_planner.recommend("creative")
        assert rec.backend == "nim"

    def test_ask_expert_uses_codex(self, fvp_planner):
        rec = fvp_planner.recommend("ask_expert")
        # Default: codex available (10/h)
        assert rec.backend == "codex"

    def test_unknown_action_local(self, fvp_planner):
        rec = fvp_planner.recommend("some_future_action")
        assert rec.strategy == ResourceStrategy.LOCAL_ONLY

    def test_recommendation_to_dict(self, fvp_planner):
        rec = fvp_planner.recommend("learn")
        d = rec.to_dict()
        assert d["strategy"] == "local_only"
        assert d["backend"] == "ollama"


# ===========================================================================
# FreeVsPaidPlanner - PlanRecommendation
# ===========================================================================

class TestFreeVsPaidPlan:

    def test_free_plan_local_only(self, fvp_planner, free_plan):
        rec = fvp_planner.recommend_for_plan(free_plan)
        assert rec.overall_strategy == ResourceStrategy.LOCAL_ONLY
        assert rec.estimated_nim_spend == 0

    def test_mixed_plan(self, fvp_planner, mock_plan):
        rec = fvp_planner.recommend_for_plan(mock_plan)
        # Has both local (learn, exam) and nim (self_analyze)
        assert rec.overall_strategy in (
            ResourceStrategy.MIXED,
            ResourceStrategy.PREFER_PAID,
        )
        assert rec.estimated_nim_spend > 0

    def test_plan_savings(self, fvp_planner, mock_plan):
        rec = fvp_planner.recommend_for_plan(mock_plan)
        assert rec.savings_if_local == rec.estimated_nim_spend

    def test_budget_ok(self, fvp_planner, mock_plan):
        rec = fvp_planner.recommend_for_plan(mock_plan)
        assert rec.nim_budget_ok is True  # Default 100k budget

    def test_plan_to_dict(self, fvp_planner, mock_plan):
        rec = fvp_planner.recommend_for_plan(mock_plan)
        d = rec.to_dict()
        assert "overall_strategy" in d
        assert "step_recommendations" in d

    def test_plan_describe(self, fvp_planner, mock_plan):
        rec = fvp_planner.recommend_for_plan(mock_plan)
        text = rec.describe()
        assert "Strategia" in text


# ===========================================================================
# FreeVsPaidPlanner - get_summary
# ===========================================================================

class TestFreeVsPaidSummary:

    def test_summary_fields(self, fvp_planner):
        summary = fvp_planner.get_summary()
        assert "nim_available" in summary
        assert "claude_available" in summary
        assert "codex_available" in summary
        assert "local_available" in summary
        assert summary["recommended_default"] == "ollama"

    def test_summary_defaults(self, fvp_planner):
        summary = fvp_planner.get_summary()
        assert summary["nim_available"] is True
        assert summary["local_available"] is True
