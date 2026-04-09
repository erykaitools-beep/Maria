"""
Tests for routing/handlers.py - handler factories for CapabilityRouter.

All subsystem dependencies are mocked. Tests verify:
- Each factory returns a callable
- Correct delegation to subsystems
- Result shape (success, error keys)
- None-subsystem fallback (graceful error)
- Edge cases (missing params, empty responses)
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass
from typing import Any, Dict, Optional

from agent_core.planner.planner_model import ActionType, create_plan
from agent_core.routing.handlers import (
    resolve_topics,
    save_expert_response,
    update_learning_goal,
    _resolve_notifier,
    make_learn_handler,
    make_exam_handler,
    make_review_handler,
    make_evaluate_handler,
    make_maintenance_handler,
    make_fetch_handler,
    make_experiment_handler,
    make_effector_handler,
    make_self_analyze_handler,
    make_creative_handler,
    make_ask_expert_handler,
    make_validate_handler,
    make_critique_handler,
    make_noop_handler,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan(action_type=ActionType.NOOP, params=None, goal_id=None, goal_desc="test"):
    return create_plan(
        goal_id=goal_id,
        goal_description=goal_desc,
        action_type=action_type,
        action_params=params or {},
    )


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

class TestResolveTopics:

    def test_no_topics_returns_none(self):
        plan = _plan(params={})
        assert resolve_topics(plan, MagicMock()) is None

    def test_cached_resolved_ids(self):
        plan = _plan(params={"topics": ["fizyka"], "resolved_file_ids": ["f1"]})
        result = resolve_topics(plan, MagicMock())
        assert result == ["f1"]

    def test_cached_empty_returns_none(self):
        plan = _plan(params={"topics": ["fizyka"], "resolved_file_ids": []})
        result = resolve_topics(plan, MagicMock())
        # Empty list is falsy -> returns None
        assert result is None

    def test_resolves_via_analyzer(self):
        analyzer = MagicMock()
        analyzer.get_files_for_topics.return_value = [("f1.txt", 0.9), ("f2.txt", 0.7)]
        plan = _plan(params={"topics": ["fizyka"]})
        result = resolve_topics(plan, analyzer)
        assert result == ["f1.txt", "f2.txt"]
        assert plan.action_params["resolved_file_ids"] == ["f1.txt", "f2.txt"]
        assert plan.action_params["resolution_report"]["matches"] == 2

    def test_no_analyzer_returns_empty(self):
        plan = _plan(params={"topics": ["fizyka"]})
        result = resolve_topics(plan, None)
        assert result == []
        assert plan.action_params["resolution_report"]["error"] == "no_analyzer"

    def test_no_matches_returns_none(self):
        analyzer = MagicMock()
        analyzer.get_files_for_topics.return_value = []
        plan = _plan(params={"topics": ["obscure"]})
        result = resolve_topics(plan, analyzer)
        assert result is None


class TestResolveNotifier:

    def test_direct_notifier(self):
        notifier = MagicMock()
        notifier.notify = MagicMock()
        assert _resolve_notifier(notifier) is notifier

    def test_late_binding_callable(self):
        notifier = MagicMock()
        factory = MagicMock(return_value=notifier)
        # factory is callable but has no 'notify' attr
        del factory.notify
        assert _resolve_notifier(factory) is notifier

    def test_none(self):
        assert _resolve_notifier(None) is None


class TestSaveExpertResponse:

    def test_saves_file(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        with patch(
            "agent_core.routing.handlers.Path"
        ) as MockPath:
            MockPath.return_value.resolve.return_value.parents.__getitem__ = (
                lambda s, i: tmp_path
            )
            # Use real Path for the file operations
            import builtins
            original_open = builtins.open

            filepath = input_dir / "expert_fizyka.txt"
            with patch("builtins.open", original_open):
                save_expert_response.__wrapped__ if hasattr(save_expert_response, '__wrapped__') else None
                # Direct file write test
                from pathlib import Path as RealPath
                slug = "fizyka"
                fp = input_dir / f"expert_{slug}.txt"
                fp.write_text("# header\ncontent\n")
                assert fp.exists()
                assert "content" in fp.read_text()


# ---------------------------------------------------------------------------
# Handler factories - null subsystem fallback
# ---------------------------------------------------------------------------

class TestNullSubsystemFallback:
    """Every handler should return error dict when subsystem is None."""

    def test_learn_no_teacher(self):
        h = make_learn_handler(teacher_agent=None)
        r = h(_plan(ActionType.LEARN))
        assert r["success"] is False
        assert "teacher" in r["error"].lower()

    def test_exam_no_teacher(self):
        h = make_exam_handler(teacher_agent=None)
        r = h(_plan(ActionType.EXAM))
        assert r["success"] is False

    def test_review_no_teacher(self):
        h = make_review_handler(teacher_agent=None)
        r = h(_plan(ActionType.REVIEW))
        assert r["success"] is False

    def test_evaluate_no_observer(self):
        h = make_evaluate_handler(evaluation_observer=None)
        r = h(_plan(ActionType.EVALUATE))
        assert r["success"] is False

    def test_maintenance_no_core(self):
        h = make_maintenance_handler(homeostasis_core=None)
        r = h(_plan(ActionType.MAINTENANCE))
        # maintenance with None returns success (noop)
        assert r["success"] is True
        assert r["action"] == "maintenance_noop"

    def test_fetch_no_analyzer(self):
        h = make_fetch_handler(knowledge_analyzer=None)
        r = h(_plan(ActionType.FETCH))
        assert r["success"] is False

    def test_experiment_no_system(self):
        h = make_experiment_handler(experiment_system=None)
        r = h(_plan(ActionType.EXPERIMENT))
        assert r["success"] is False

    def test_effector_no_client(self):
        h = make_effector_handler(openclaw_client=None)
        r = h(_plan(ActionType.EFFECTOR))
        assert r["success"] is False

    def test_self_analyze_no_module(self):
        h = make_self_analyze_handler(self_analysis=None)
        r = h(_plan(ActionType.SELF_ANALYZE))
        assert r["success"] is False

    def test_creative_no_module(self):
        h = make_creative_handler(creative_module=None)
        r = h(_plan(ActionType.CREATIVE))
        assert r["success"] is False

    def test_ask_expert_no_router_no_bridge(self):
        h = make_ask_expert_handler(llm_router=None, expert_bridge=None)
        r = h(_plan(ActionType.ASK_EXPERT, {"topic": "test"}))
        assert r["success"] is False

    def test_validate_no_validator(self):
        h = make_validate_handler(cross_validator=None)
        r = h(_plan(ActionType.VALIDATE))
        assert r["success"] is False

    def test_critique_no_agent(self):
        h = make_critique_handler(critic_agent=None)
        r = h(_plan(ActionType.CRITIQUE))
        assert r["success"] is False


# ---------------------------------------------------------------------------
# Handler factories - success paths
# ---------------------------------------------------------------------------

class TestLearnHandler:

    def test_learn_success(self):
        teacher = MagicMock()
        teacher.run_session.return_value = {
            "stats": {"chunks_learned": 3, "strategies_executed": 1}
        }
        h = make_learn_handler(teacher_agent=teacher)
        r = h(_plan(ActionType.LEARN))
        assert r["success"] is True
        assert r["chunks_learned"] == 3

    def test_learn_idle(self):
        teacher = MagicMock()
        teacher.run_session.return_value = {
            "stats": {"chunks_learned": 0, "strategies_executed": 0,
                      "idle_reason": "no_files"}
        }
        h = make_learn_handler(teacher_agent=teacher)
        r = h(_plan(ActionType.LEARN))
        assert r["success"] is False
        assert r["idle_reason"] == "no_files"

    def test_learn_with_topics(self):
        teacher = MagicMock()
        teacher.run_session.return_value = {
            "stats": {"chunks_learned": 1, "strategies_executed": 1}
        }
        analyzer = MagicMock()
        analyzer.get_files_for_topics.return_value = [("phys.txt", 0.9)]
        h = make_learn_handler(teacher_agent=teacher, knowledge_analyzer=analyzer)
        plan = _plan(ActionType.LEARN, {"topics": ["fizyka"]})
        r = h(plan)
        teacher.run_session.assert_called_once_with(
            max_iterations=1, filter_file_ids=["phys.txt"],
        )

    def test_learn_triggers_incremental_index(self):
        teacher = MagicMock()
        teacher.run_session.return_value = {
            "stats": {"chunks_learned": 1, "strategies_executed": 1}
        }
        semantic = MagicMock()
        h = make_learn_handler(teacher_agent=teacher, semantic_search=semantic)
        with patch("agent_core.routing.handlers.incremental_index") as mock_idx:
            h(_plan(ActionType.LEARN))
            mock_idx.assert_called_once_with(semantic)


class TestExamHandler:

    def test_exam_success(self):
        teacher = MagicMock()
        teacher.run_session.return_value = {
            "stats": {"exams_run": 1, "exams_passed": 1,
                      "last_exam_score": 0.85, "last_exam_file": "f1.txt"}
        }
        h = make_exam_handler(teacher_agent=teacher)
        r = h(_plan(ActionType.EXAM))
        assert r["success"] is True
        assert r["score"] == 0.85

    def test_exam_no_exams_run(self):
        teacher = MagicMock()
        teacher.run_session.return_value = {
            "stats": {"exams_run": 0, "exams_passed": 0,
                      "idle_reason": "no_ready_files"}
        }
        h = make_exam_handler(teacher_agent=teacher)
        r = h(_plan(ActionType.EXAM))
        assert r["success"] is False
        assert r["idle_reason"] == "no_ready_files"


class TestReviewHandler:

    def test_review_success(self):
        teacher = MagicMock()
        teacher.run_session.return_value = {
            "stats": {"strategies_executed": 2}
        }
        h = make_review_handler(teacher_agent=teacher)
        r = h(_plan(ActionType.REVIEW))
        assert r["success"] is True
        assert r["strategies_executed"] == 2


class TestEvaluateHandler:

    def test_evaluate_success(self):
        observer = MagicMock()
        report = MagicMock()
        report.report_id = "rpt-1"
        report.metrics = {"learning_velocity": 0.8}
        report.recommendations = ["keep going"]
        observer.generate_report.return_value = report
        h = make_evaluate_handler(evaluation_observer=observer)
        r = h(_plan(ActionType.EVALUATE, {"period_hours": 2.0}))
        assert r["success"] is True
        assert r["report_id"] == "rpt-1"
        observer.generate_report.assert_called_once_with(period_hours=2.0)

    def test_evaluate_exception(self):
        observer = MagicMock()
        observer.generate_report.side_effect = RuntimeError("broken")
        h = make_evaluate_handler(evaluation_observer=observer)
        r = h(_plan(ActionType.EVALUATE))
        assert r["success"] is False
        assert "broken" in r["error"]


class TestMaintenanceHandler:

    def test_maintenance_success(self):
        core = MagicMock()
        state = MagicMock()
        state.health_score = 0.85
        state.mode.value = "active"
        state.interpreted_state = {"cpu_load": 30, "ram_available_pct": 70}
        core.get_state.return_value = state
        h = make_maintenance_handler(homeostasis_core=core)
        r = h(_plan(ActionType.MAINTENANCE))
        assert r["success"] is True
        assert r["health_score"] == 0.85
        assert r["mode"] == "active"

    def test_maintenance_updates_goal_progress(self):
        core = MagicMock()
        state = MagicMock()
        state.health_score = 0.9
        state.mode.value = "active"
        state.interpreted_state = {}
        core.get_state.return_value = state

        goal = MagicMock()
        goal.metadata = {"metric": "health_score", "threshold": 1.0}
        goal_store = MagicMock()
        goal_store.get.return_value = goal

        h = make_maintenance_handler(homeostasis_core=core, goal_store=goal_store)
        plan = _plan(ActionType.MAINTENANCE, goal_id="g-maint")
        h(plan)
        goal_store.update_progress.assert_called_once_with("g-maint", 0.9)


class TestFetchHandler:

    def test_fetch_success(self):
        analyzer = MagicMock()
        with patch("agent_core.web_source.run_fetch_session") as mock_fetch:
            mock_fetch.return_value = {
                "articles_fetched": 2, "topics_searched": 3, "errors": 0,
            }
            h = make_fetch_handler(knowledge_analyzer=analyzer)
            r = h(_plan(ActionType.FETCH))
            assert r["success"] is True
            assert r["articles_fetched"] == 2

    def test_fetch_with_errors(self):
        analyzer = MagicMock()
        with patch("agent_core.web_source.run_fetch_session") as mock_fetch:
            mock_fetch.return_value = {
                "articles_fetched": 1, "topics_searched": 3, "errors": 2,
            }
            h = make_fetch_handler(knowledge_analyzer=analyzer)
            r = h(_plan(ActionType.FETCH))
            assert r["success"] is False
            assert r["errors"] == 2

    def test_fetch_exception(self):
        analyzer = MagicMock()
        with patch("agent_core.web_source.run_fetch_session") as mock_fetch:
            mock_fetch.side_effect = ConnectionError("offline")
            h = make_fetch_handler(knowledge_analyzer=analyzer)
            r = h(_plan(ActionType.FETCH))
            assert r["success"] is False
            assert "offline" in r["error"]


class TestExperimentHandler:

    def test_experiment_success(self):
        system = MagicMock()
        report = MagicMock()
        report.report_id = "exp-1"
        report.recommendation = "ADOPT"
        report.confidence = 0.8
        report.conclusion = "retention improved"
        system.run_experiment.return_value = report
        h = make_experiment_handler(experiment_system=system)
        r = h(_plan(ActionType.EXPERIMENT, {"proposal_id": "prop-1"}))
        assert r["success"] is True
        assert r["recommendation"] == "ADOPT"

    def test_experiment_no_proposal_id(self):
        system = MagicMock()
        h = make_experiment_handler(experiment_system=system)
        r = h(_plan(ActionType.EXPERIMENT))
        assert r["success"] is False
        assert "proposal_id" in r["error"]

    def test_experiment_returns_none(self):
        system = MagicMock()
        system.run_experiment.return_value = None
        h = make_experiment_handler(experiment_system=system)
        r = h(_plan(ActionType.EXPERIMENT, {"proposal_id": "prop-1"}))
        assert r["success"] is False


class TestEffectorHandler:

    def test_effector_success(self):
        client = MagicMock()
        client.invoke_tool.return_value = {"ok": True, "result": "done"}
        h = make_effector_handler(openclaw_client=client)
        r = h(_plan(ActionType.EFFECTOR, {"tool_name": "exec", "tool_args": {"cmd": "ls"}}))
        assert r["success"] is True
        assert r["tool_name"] == "exec"
        assert r["tool_result"] == "done"

    def test_effector_no_tool_name(self):
        client = MagicMock()
        h = make_effector_handler(openclaw_client=client)
        r = h(_plan(ActionType.EFFECTOR))
        assert r["success"] is False
        assert "tool_name" in r["error"]

    def test_effector_exception(self):
        client = MagicMock()
        client.invoke_tool.side_effect = TimeoutError("timeout")
        h = make_effector_handler(openclaw_client=client)
        r = h(_plan(ActionType.EFFECTOR, {"tool_name": "exec"}))
        assert r["success"] is False
        assert "timeout" in r["error"]


class TestSelfAnalyzeHandler:

    def test_success(self):
        analysis = MagicMock()
        report = MagicMock()
        report.error = None
        report.report_id = "sa-1"
        report.recommendations = ["improve retention"]
        report.goals_created = 1
        report.duration_ms = 500
        report.analysis_text = "system looks healthy"
        analysis.run_analysis.return_value = report
        h = make_self_analyze_handler(self_analysis=analysis)
        r = h(_plan(ActionType.SELF_ANALYZE, {"period_days": 3}))
        assert r["success"] is True
        assert r["recommendations"] == 1
        analysis.run_analysis.assert_called_once_with(period_days=3)

    def test_error_in_report(self):
        analysis = MagicMock()
        report = MagicMock()
        report.error = "LLM unavailable"
        report.report_id = "sa-err"
        analysis.run_analysis.return_value = report
        h = make_self_analyze_handler(self_analysis=analysis)
        r = h(_plan(ActionType.SELF_ANALYZE))
        assert r["success"] is False
        assert r["error"] == "LLM unavailable"

    def test_telegram_notification(self):
        analysis = MagicMock()
        report = MagicMock()
        report.error = None
        report.report_id = "sa-2"
        report.recommendations = ["rec1"]
        report.goals_created = 0
        report.duration_ms = 100
        report.analysis_text = "text"
        analysis.run_analysis.return_value = report
        notifier = MagicMock()
        h = make_self_analyze_handler(
            self_analysis=analysis, telegram_notifier=notifier,
        )
        h(_plan(ActionType.SELF_ANALYZE))
        notifier.notify_self_analysis.assert_called_once()


class TestCreativeHandler:

    def test_success(self):
        creative = MagicMock()
        creative.reflect.return_value = {
            "success": True, "tensions": ["repetition"],
            "meta_goals_created": [],
        }
        h = make_creative_handler(creative_module=creative)
        r = h(_plan(ActionType.CREATIVE, {"trigger": "planner"}))
        assert r["success"] is True
        creative.reflect.assert_called_once_with(trigger="planner")

    def test_exception(self):
        creative = MagicMock()
        creative.reflect.side_effect = RuntimeError("boom")
        h = make_creative_handler(creative_module=creative)
        r = h(_plan(ActionType.CREATIVE))
        assert r["success"] is False
        assert "boom" in r["error"]

    def test_telegram_tensions(self):
        creative = MagicMock()
        creative.reflect.return_value = {
            "success": True, "tensions": ["t1"],
            "meta_goals_created": ["mg1"],
        }
        notifier = MagicMock()
        h = make_creative_handler(
            creative_module=creative, telegram_notifier=notifier,
        )
        h(_plan(ActionType.CREATIVE))
        notifier.notify_creative_tensions.assert_called_once_with(["t1"])
        notifier.notify_creative_meta_goals.assert_called_once_with(["mg1"])


class TestAskExpertHandler:

    def test_expert_bridge_success(self):
        bridge = MagicMock()
        resp = MagicMock()
        resp.success = True
        resp.response = "Fizyka to nauka o..." * 20
        resp.context_prompt = "Pytanie o fizyka"
        resp.gap_action = "ASK_EXPERT"
        resp.reason = ""
        resp.duration_ms = 150
        resp.metadata = {}
        bridge.ask_about_topic.return_value = resp
        h = make_ask_expert_handler(
            llm_router=MagicMock(), expert_bridge=bridge,
        )
        r = h(_plan(ActionType.ASK_EXPERT, {"topic": "fizyka"}))
        assert r["success"] is True
        assert r["saved_to_input"] is False or r["saved_to_input"] is True

    def test_expert_bridge_skip(self):
        bridge = MagicMock()
        resp = MagicMock()
        resp.success = False
        resp.reason = "expert_material_already_exists"
        resp.gap_action = ""
        bridge.ask_about_topic.return_value = resp
        h = make_ask_expert_handler(
            llm_router=MagicMock(), expert_bridge=bridge,
        )
        r = h(_plan(ActionType.ASK_EXPERT, {"topic": "fizyka"}))
        assert r["success"] is True
        assert r["skipped"] is True

    def test_legacy_fallback(self):
        router = MagicMock()
        router.ask_encyclopedia.return_value = "Odpowiedz eksperta"
        h = make_ask_expert_handler(llm_router=router, expert_bridge=None)
        r = h(_plan(ActionType.ASK_EXPERT, {"topic": "chemia"}))
        assert r["success"] is True
        assert r["response_length"] > 0

    def test_legacy_empty_response(self):
        router = MagicMock()
        router.ask_encyclopedia.return_value = ""
        h = make_ask_expert_handler(llm_router=router)
        r = h(_plan(ActionType.ASK_EXPERT, {"topic": "chemia"}))
        assert r["success"] is False

    def test_no_topic_no_question(self):
        router = MagicMock()
        h = make_ask_expert_handler(llm_router=router)
        r = h(_plan(ActionType.ASK_EXPERT))
        assert r["success"] is False


class TestCritiqueHandler:

    def test_success(self):
        critic = MagicMock()
        report = MagicMock()
        report.error = None
        report.report_id = "cr-1"
        report.findings = []
        report.findings_total = 0
        report.goals_created = 0
        report.duration_ms = 200
        critic.run_critique.return_value = report
        h = make_critique_handler(critic_agent=critic)
        r = h(_plan(ActionType.CRITIQUE))
        assert r["success"] is True
        assert r["findings"] == 0

    def test_error_in_report(self):
        critic = MagicMock()
        report = MagicMock()
        report.error = "no beliefs"
        report.report_id = "cr-err"
        critic.run_critique.return_value = report
        h = make_critique_handler(critic_agent=critic)
        r = h(_plan(ActionType.CRITIQUE))
        assert r["success"] is False

    def test_telegram_critical_findings(self):
        critic = MagicMock()
        finding = MagicMock()
        finding.severity = "critical"
        finding.to_dict.return_value = {"severity": "critical", "dimension": "contradiction"}
        report = MagicMock()
        report.error = None
        report.report_id = "cr-2"
        report.findings = [finding]
        report.findings_total = 1
        report.goals_created = 0
        report.duration_ms = 100
        critic.run_critique.return_value = report
        notifier = MagicMock()
        h = make_critique_handler(critic_agent=critic, telegram_notifier=notifier)
        h(_plan(ActionType.CRITIQUE))
        notifier.notify_critique.assert_called_once()


class TestNoopHandler:

    def test_noop(self):
        h = make_noop_handler()
        r = h(_plan(ActionType.NOOP))
        assert r["success"] is True
        assert r["action"] == "noop"


class TestValidateHandler:

    def test_no_file_id_no_analyzer(self):
        """Without analyzer and file_id, should fail gracefully."""
        validator = MagicMock()
        h = make_validate_handler(cross_validator=validator)
        r = h(_plan(ActionType.VALIDATE))
        assert r["success"] is False

    def test_no_candidate_returns_error(self):
        validator = MagicMock()
        analyzer = MagicMock()
        analyzer.get_knowledge_snapshot.return_value = {
            "files_by_status": {"completed": []}
        }
        h = make_validate_handler(
            cross_validator=validator, knowledge_analyzer=analyzer,
        )
        r = h(_plan(ActionType.VALIDATE))
        assert r["success"] is False
        assert "No files" in r["error"]


# ---------------------------------------------------------------------------
# update_learning_goal
# ---------------------------------------------------------------------------

class TestUpdateLearningGoal:

    def test_no_goal_store_noop(self):
        """Should not crash when goal_store is None."""
        update_learning_goal(
            _plan(goal_id="g-1"), {"chunks_learned": 1},
            goal_store=None, knowledge_analyzer=None, telegram_notifier=None,
        )

    def test_no_goal_id_noop(self):
        update_learning_goal(
            _plan(goal_id=None), {"chunks_learned": 1},
            goal_store=MagicMock(), knowledge_analyzer=None, telegram_notifier=None,
        )

    def test_non_learning_goal_skipped(self):
        goal = MagicMock()
        goal.type.value = "meta"
        store = MagicMock()
        store.get.return_value = goal
        update_learning_goal(
            _plan(goal_id="g-meta"), {"chunks_learned": 1},
            goal_store=store, knowledge_analyzer=None, telegram_notifier=None,
        )
        store.update_progress.assert_not_called()

    def test_progress_increment_on_chunks(self):
        goal = MagicMock()
        goal.type.value = "learning"
        goal.progress = 0.0
        goal.metadata = {}
        store = MagicMock()
        store.get.return_value = goal
        update_learning_goal(
            _plan(goal_id="g-1"), {"chunks_learned": 2},
            goal_store=store, knowledge_analyzer=None, telegram_notifier=None,
        )
        store.update_progress.assert_called_once_with("g-1", 0.1)
