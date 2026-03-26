"""
Tests for ASK_EXPERT action type (Phase B).

Verifies planner trigger, executor, K7 classification, rate limiting.
All LLM calls mocked.
"""

import pytest
from unittest.mock import MagicMock, patch

from agent_core.planner.planner_model import ActionType
from agent_core.planner.action_executor import ActionExecutor


class TestActionTypeAskExpert:
    """Verify ASK_EXPERT exists in ActionType enum."""

    def test_ask_expert_exists(self):
        assert hasattr(ActionType, "ASK_EXPERT")
        assert ActionType.ASK_EXPERT.value == "ask_expert"


class TestK7AskExpert:
    """Verify K7 classification and rate limiting."""

    def test_ask_expert_is_guarded(self):
        from agent_core.autonomy.action_class import (
            classify_action, ActionClassification,
        )
        assert classify_action("ask_expert") == ActionClassification.GUARDED

    def test_ask_expert_rate_limit(self):
        from agent_core.autonomy.rate_limiter import DEFAULT_RATE_LIMITS
        assert "ask_expert" in DEFAULT_RATE_LIMITS
        assert DEFAULT_RATE_LIMITS["ask_expert"] == 10

    def test_ask_expert_allowed_initially(self):
        from agent_core.autonomy import AutonomyPolicy
        policy = AutonomyPolicy()
        result = policy.check(action_type="ask_expert")
        assert result.allowed


class TestExecAskExpert:
    """Tests for _exec_ask_expert in ActionExecutor."""

    def _make_executor(self, encyclopedia_response="Expert answer"):
        executor = ActionExecutor()
        router = MagicMock()
        router.ask_encyclopedia = MagicMock(return_value=encyclopedia_response)
        executor.set_llm_router(router)
        return executor, router

    def _make_plan(self, **params):
        from agent_core.planner.planner_model import create_plan
        return create_plan(
            goal_id="goal-test",
            goal_description="Test",
            action_type=ActionType.ASK_EXPERT,
            action_params=params,
        )

    def test_ask_with_question(self):
        executor, router = self._make_executor()
        plan = self._make_plan(question="Co to jest DNA?", topic="genetyka")
        result = executor.execute(plan)
        assert result["success"] is True
        assert "Expert answer" in result["response"]
        router.ask_encyclopedia.assert_called_once()

    def test_ask_with_topic_only(self):
        executor, router = self._make_executor()
        plan = self._make_plan(topic="fotosynteza")
        result = executor.execute(plan)
        assert result["success"] is True
        # Should auto-generate question from topic
        call_args = router.ask_encyclopedia.call_args
        assert "fotosynteza" in call_args[1]["prompt"]

    def test_ask_no_question_no_topic(self):
        executor, router = self._make_executor()
        plan = self._make_plan()
        result = executor.execute(plan)
        assert result["success"] is False
        assert "No question or topic" in result["error"]

    def test_ask_empty_response(self):
        executor, _ = self._make_executor(encyclopedia_response="")
        plan = self._make_plan(question="test")
        result = executor.execute(plan)
        assert result["success"] is False

    def test_ask_no_router(self):
        executor = ActionExecutor()
        plan = self._make_plan(question="test")
        result = executor.execute(plan)
        assert result["success"] is False

    def test_ask_result_has_topic(self):
        executor, router = self._make_executor()
        plan = self._make_plan(
            question="Co to jest RNA?",
            topic="genetyka",
            source="test",
        )
        result = executor.execute(plan)
        assert result["success"] is True
        assert result.get("topic") == "genetyka"
        assert "saved_to_input" in result

    def test_ask_context_passed_to_router(self):
        executor, router = self._make_executor()
        plan = self._make_plan(question="test", topic="fizyka")
        plan.goal_id = "goal-123"
        executor.execute(plan)

        call_kwargs = router.ask_encyclopedia.call_args[1]
        assert call_kwargs["source"] == "planner"
        assert call_kwargs["context"]["goal_id"] == "goal-123"
        assert call_kwargs["context"]["topic"] == "fizyka"


class TestPlannerAskExpertTrigger:
    """Tests for _decide_learning_action P6 (ASK_EXPERT)."""

    def test_ask_expert_after_fetch_exhausted(self):
        from agent_core.planner.planner_core import PlannerCore
        planner = PlannerCore()

        # Mock K7 to block fetch but allow ask_expert
        policy = MagicMock()
        fetch_blocked = MagicMock()
        fetch_blocked.allowed = False
        expert_allowed = MagicMock()
        expert_allowed.allowed = True

        def _check_mock(action_type, **kwargs):
            if action_type == "fetch":
                return fetch_blocked
            if action_type == "ask_expert":
                return expert_allowed
            return expert_allowed

        policy.check = _check_mock
        planner._autonomy_policy = policy

        # Mock world model with a gap
        world_model = MagicMock()
        world_model.query.get_knowledge_gaps.return_value = [
            {"topic": "kwantowa fizyka"}
        ]
        planner._world_model = world_model

        snapshot = {
            "files_by_status": {"completed": [{"id": "f1"}]},
            "new_files_available": [],
        }
        action = planner._decide_learning_action(snapshot, {"retention_rate": 1.0})
        assert action == ActionType.ASK_EXPERT

    def test_noop_when_expert_also_blocked(self):
        from agent_core.planner.planner_core import PlannerCore
        planner = PlannerCore()

        # Block everything
        policy = MagicMock()
        blocked = MagicMock()
        blocked.allowed = False
        policy.check = MagicMock(return_value=blocked)
        planner._autonomy_policy = policy

        snapshot = {
            "files_by_status": {"completed": [{"id": "f1"}]},
            "new_files_available": [],
        }
        action = planner._decide_learning_action(snapshot, {"retention_rate": 1.0})
        assert action == ActionType.NOOP

    def test_pick_expert_topic_from_world_model(self):
        from agent_core.planner.planner_core import PlannerCore
        planner = PlannerCore()

        world_model = MagicMock()
        world_model.query.get_knowledge_gaps.return_value = [
            {"topic": "biologia molekularna"}
        ]
        planner._world_model = world_model

        topic = planner._pick_expert_topic()
        assert topic == "biologia molekularna"

    def test_pick_expert_topic_fallback_to_analyzer(self):
        from agent_core.planner.planner_core import PlannerCore
        planner = PlannerCore()
        planner._world_model = None

        analyzer = MagicMock()
        analyzer.get_topic_file_map.return_value = {"chemia": ["f1", "f2"]}
        planner._knowledge_analyzer = analyzer

        topic = planner._pick_expert_topic()
        assert topic == "chemia"

    def test_pick_expert_topic_none(self):
        from agent_core.planner.planner_core import PlannerCore
        planner = PlannerCore()
        assert planner._pick_expert_topic() is None


class TestFormatMessageAskExpert:
    """Test human-readable message for ASK_EXPERT."""

    def test_format_with_topic(self):
        from agent_core.planner.planner_core import PlannerCore
        from agent_core.planner.planner_model import create_plan
        planner = PlannerCore()
        plan = create_plan(
            goal_id=None,
            goal_description="test",
            action_type=ActionType.ASK_EXPERT,
            action_params={"topic": "genetyka"},
        )
        msg = planner._format_message(plan)
        assert "genetyka" in msg
        assert "ekspert" in msg.lower()

    def test_format_without_topic(self):
        from agent_core.planner.planner_core import PlannerCore
        from agent_core.planner.planner_model import create_plan
        planner = PlannerCore()
        plan = create_plan(
            goal_id=None,
            goal_description="test",
            action_type=ActionType.ASK_EXPERT,
            action_params={},
        )
        msg = planner._format_message(plan)
        assert "ekspert" in msg.lower()
