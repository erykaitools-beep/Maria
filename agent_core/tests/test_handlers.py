"""
Tests for routing/handlers.py - handler factories for CapabilityRouter.

All subsystem dependencies are mocked. Tests verify:
- Each factory returns a callable
- Correct delegation to subsystems
- Result shape (success, error keys)
- None-subsystem fallback (graceful error)
- Edge cases (missing params, empty responses)
"""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass
from typing import Any, Dict, Optional

from agent_core.planner.planner_model import ActionType, create_plan
from agent_core.goals.goal_model import GoalType
from agent_core.goals.store import GoalStore
from agent_core.self_analysis.recommendation_model import AnalysisReport
from agent_core.evaluation import EvaluationObserver
from agent_core.experiment import ExperimentSystem
from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
from agent_core.teacher.teacher_agent import TeacherAgent
from agent_core.tests.spec_helpers import specced
from agent_core.routing.handlers import (
    resolve_topics,
    save_expert_response,
    _classify_expert_response,
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

    def test_direct_resolved_file_ids(self):
        plan = _plan(params={"resolved_file_ids": ["web_wiki_a.txt"]})
        result = resolve_topics(plan, MagicMock())
        assert result == ["web_wiki_a.txt"]

    def test_cached_empty_returns_none(self):
        plan = _plan(params={"topics": ["fizyka"], "resolved_file_ids": []})
        result = resolve_topics(plan, MagicMock())
        # Empty list is falsy -> returns None
        assert result is None

    def test_resolves_via_analyzer(self):
        analyzer = specced(KnowledgeAnalyzer)
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
        analyzer = specced(KnowledgeAnalyzer)
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


class TestExpertResponseGuard:
    """D1.5 fix (2026-04-21): save_expert_response rejects garbage.

    Motivated by finding that input/expert_*.txt accumulated LLM
    hallucinations ("yyy" x200, "zzz" x200, "Expert answer" stubs)
    over ~a week, and Maria tried to learn from them, producing 0
    chunks in ~77ms — the dominant cause of the 791 unproductive
    strategies observed in the glm-5.1 test 72h window.
    """

    def test_valid_response_passes(self):
        body = (
            "Genetyka to dział biologii zajmujący się dziedziczeniem cech. "
            "DNA koduje informację przekazywaną między pokoleniami. "
            "Współczesna genetyka korzysta z sekwencjonowania i edycji genów. "
            "Kluczowe pojęcia to gen, allel, fenotyp i genotyp."
        )
        assert _classify_expert_response(body) is None

    def test_placeholder_expert_answer_rejected(self):
        assert "placeholder" in _classify_expert_response("Expert answer")

    def test_placeholder_legacy_answer_rejected(self):
        assert "placeholder" in _classify_expert_response("Legacy answer")

    def test_placeholder_odpowiedz_eksperta_rejected(self):
        assert "placeholder" in _classify_expert_response("Odpowiedz eksperta")

    def test_empty_rejected(self):
        assert _classify_expert_response("") == "empty"
        assert _classify_expert_response("   \n  ") == "empty"

    def test_too_short_rejected(self):
        body = "Krótka odpowiedź o rozsądnej różnorodności liter."
        reason = _classify_expert_response(body)
        assert reason is not None and "too_short" in reason

    def test_repeated_char_rejected(self):
        body = "Wstęp prawidłowy. " + ("y" * 200) + " końcówka."
        reason = _classify_expert_response(body)
        assert reason is not None and "repeated_char" in reason

    def test_low_variety_rejected(self):
        body = "aaaaaaabbbbbbb " * 20  # 2 unique chars + space
        reason = _classify_expert_response(body)
        assert reason is not None and (
            "low_variety" in reason or "repeated_char" in reason
        )

    def test_save_raises_valueerror_on_garbage(self, tmp_path):
        with pytest.raises(ValueError, match="garbage_response"):
            save_expert_response("test", "test question", "Expert answer")

    def test_save_raises_on_repeated_char(self, tmp_path):
        with pytest.raises(ValueError, match="garbage_response"):
            save_expert_response("test", "test question", "z" * 300)


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
        teacher = specced(TeacherAgent)
        teacher.run_session.return_value = {
            "stats": {"chunks_learned": 3, "strategies_executed": 1}
        }
        h = make_learn_handler(teacher_agent=teacher)
        r = h(_plan(ActionType.LEARN))
        assert r["success"] is True
        assert r["chunks_learned"] == 3

    def test_learn_idle(self):
        teacher = specced(TeacherAgent)
        teacher.run_session.return_value = {
            "stats": {"chunks_learned": 0, "strategies_executed": 0,
                      "idle_reason": "no_files"}
        }
        h = make_learn_handler(teacher_agent=teacher)
        r = h(_plan(ActionType.LEARN))
        assert r["success"] is False
        assert r["idle_reason"] == "no_files"

    def test_learn_with_topics(self):
        teacher = specced(TeacherAgent)
        teacher.run_session.return_value = {
            "stats": {"chunks_learned": 1, "strategies_executed": 1}
        }
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_files_for_topics.return_value = [("phys.txt", 0.9)]
        h = make_learn_handler(teacher_agent=teacher, knowledge_analyzer=analyzer)
        plan = _plan(ActionType.LEARN, {"topics": ["fizyka"]})
        r = h(plan)
        teacher.run_session.assert_called_once_with(
            max_iterations=1, filter_file_ids=["phys.txt"],
        )

    def test_learn_triggers_incremental_index(self):
        teacher = specced(TeacherAgent)
        teacher.run_session.return_value = {
            "stats": {"chunks_learned": 1, "strategies_executed": 1}
        }
        semantic = MagicMock()
        h = make_learn_handler(teacher_agent=teacher, semantic_search=semantic)
        with patch("agent_core.routing.handlers.incremental_index") as mock_idx:
            h(_plan(ActionType.LEARN))
            mock_idx.assert_called_once_with(semantic)

    def test_learn_emits_personality_signal_on_success(self):
        # C6 fix: handler must feed `learning_completed` to consciousness.
        teacher = specced(TeacherAgent)
        teacher.run_session.return_value = {
            "stats": {"chunks_learned": 4, "strategies_executed": 2}
        }
        consc = MagicMock()
        h = make_learn_handler(teacher_agent=teacher, consciousness=consc)
        h(_plan(ActionType.LEARN, {"topics": ["fizyka"]}))
        events = [c.args[0] for c in consc.record_experience.call_args_list]
        assert "learning_completed" in events
        assert "unknown_terms_found" in events  # topics provided

    def test_learn_no_signal_when_idle(self):
        teacher = specced(TeacherAgent)
        teacher.run_session.return_value = {
            "stats": {"chunks_learned": 0, "idle_reason": "no_files"}
        }
        consc = MagicMock()
        h = make_learn_handler(teacher_agent=teacher, consciousness=consc)
        h(_plan(ActionType.LEARN))
        consc.record_experience.assert_not_called()

    def test_learn_skipped_when_non_chunking_strategy(self):
        # B3 fix (audit 2026-05-17): when teacher executes a strategy that
        # does not chunk (e.g. REVIEW with no fresh files), the handler must
        # mark result as skipped so planner does not count it as a learn
        # failure that triggers K7 backoff / K9 negative reflection.
        teacher = specced(TeacherAgent)
        teacher.run_session.return_value = {
            "stats": {"chunks_learned": 0, "strategies_executed": 1}
        }
        h = make_learn_handler(teacher_agent=teacher)
        r = h(_plan(ActionType.LEARN))
        assert r["success"] is False
        assert r["skipped"] is True
        assert r["reason"] == "non_chunking_strategy"
        assert r["strategies_executed"] == 1

    def test_learn_skipped_when_filtered_out(self):
        # B3 fix (audit 2026-05-17): idle_reason from teacher must propagate
        # to result["reason"] and mark skipped=True so the planner backs off
        # the goal gracefully instead of treating it as a hard failure.
        teacher = specced(TeacherAgent)
        teacher.run_session.return_value = {
            "stats": {
                "chunks_learned": 0,
                "strategies_executed": 0,
                "idle_reason": "filtered_out_all_candidates",
                "filtered_out_count": 12,
            }
        }
        h = make_learn_handler(teacher_agent=teacher)
        r = h(_plan(ActionType.LEARN))
        assert r["success"] is False
        assert r["skipped"] is True
        assert r["reason"] == "filtered_out_all_candidates"
        assert r["idle_reason"] == "filtered_out_all_candidates"
        assert r["filtered_out_count"] == 12


class TestUpdateLearningGoalProgress:
    """Plank 2: goal progress = fraction of owned files INDEPENDENTLY exam-
    verified. Fixes the id-vs-record matching bug (topic goals always scored 0)
    and aligns completion with the keystone -- merely-learned (or only
    self-graded 'completed') material does not count as done.
    """

    @pytest.fixture(autouse=True)
    def _treat_completed_as_verified(self, monkeypatch):
        # These tests isolate the progress-FRACTION logic, not the independence
        # gate (which has dedicated tests): treat every 'completed' file the
        # mock analyzer reports as also independently verified.
        self._verified_ids = set()
        monkeypatch.setattr(
            "agent_core.goals.success_criteria.independently_verified_file_ids",
            lambda *a, **k: self._verified_ids,
        )

    def _analyzer(self, completed_ids=(), learned_ids=(), topic_files=None):
        """Mock KnowledgeAnalyzer with a records-shaped snapshot."""
        self._verified_ids = set(completed_ids)
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_knowledge_snapshot.return_value = {
            "files_by_status": {
                "completed": [{"id": f, "file": f} for f in completed_ids],
                "learned": [{"id": f, "file": f} for f in learned_ids],
            }
        }
        if topic_files is not None:
            analyzer.get_files_for_topics.return_value = [
                (f, 1.0) for f in topic_files
            ]
        return analyzer

    def _goal(self, metadata, progress=0.0, status="active"):
        goal = MagicMock()
        goal.type = MagicMock(value="learning")
        goal.progress = progress
        goal.metadata = metadata
        goal.description = "Nauka: test"
        goal.status = MagicMock(value=status)
        return goal

    def test_topic_goal_counts_completed(self):
        """Regression: topic match compares ids to record ids (was always 0)."""
        goal = self._goal({"topics": ["chemia"]})
        store = specced(GoalStore)
        store.get.return_value = goal
        analyzer = self._analyzer(completed_ids=["c.txt"], topic_files=["c.txt"])

        update_learning_goal(
            _plan(ActionType.EXAM, goal_id="g1"),
            {"exams_passed": 1}, store, analyzer, None,
        )

        store.update_progress.assert_called_once_with("g1", 1.0)

    def test_singular_topic_key_accepted(self):
        """Goals storing 'topic' (singular) resolve files too."""
        goal = self._goal({"topic": "chemia"})
        store = specced(GoalStore)
        store.get.return_value = goal
        analyzer = self._analyzer(completed_ids=["c.txt"], topic_files=["c.txt"])

        update_learning_goal(
            _plan(ActionType.EXAM, goal_id="g1b"),
            {"exams_passed": 1}, store, analyzer, None,
        )

        store.update_progress.assert_called_once_with("g1b", 1.0)

    def test_learned_not_completed_does_not_progress(self):
        """Keystone: merely-learned (not exam-passed) material is not done."""
        goal = self._goal({"file_ids": ["x.txt", "y.txt"]})
        store = specced(GoalStore)
        store.get.return_value = goal
        analyzer = self._analyzer(completed_ids=[], learned_ids=["x.txt"])

        update_learning_goal(
            _plan(ActionType.LEARN, goal_id="g2"),
            {"chunks_learned": 3}, store, analyzer, None,
        )

        # file-based path is authoritative -> 0.0, no increment fallback
        store.update_progress.assert_not_called()

    def test_scoped_goal_partial_completion(self):
        """Handoff goal: progress = completed fraction of its file_ids."""
        goal = self._goal({"file_ids": ["a.txt", "b.txt", "c.txt", "d.txt"]})
        store = specced(GoalStore)
        store.get.return_value = goal
        analyzer = self._analyzer(completed_ids=["a.txt", "b.txt"])

        update_learning_goal(
            _plan(ActionType.EXAM, goal_id="g3"),
            {"exams_passed": 1}, store, analyzer, None,
        )

        store.update_progress.assert_called_once_with("g3", 0.5)

    def test_resolved_file_ids_used_when_goal_has_none(self):
        """Files resolved for THIS action are used when goal carries no files."""
        goal = self._goal({})
        store = specced(GoalStore)
        store.get.return_value = goal
        analyzer = self._analyzer(completed_ids=["r.txt"])

        update_learning_goal(
            _plan(ActionType.LEARN, goal_id="g4",
                  params={"resolved_file_ids": ["r.txt", "s.txt"]}),
            {"chunks_learned": 1}, store, analyzer, None,
        )

        store.update_progress.assert_called_once_with("g4", 0.5)

    def test_self_graded_completed_does_not_reach_done(self):
        """Audit 2026-06-01: 'completed' but only SELF-graded files do not
        credit progress, so the goal cannot auto-ACHIEVE on self-assessment
        (the second closure door, alongside reconciliation)."""
        goal = self._goal({"file_ids": ["a.txt", "b.txt"]})
        store = specced(GoalStore)
        store.get.return_value = goal
        analyzer = self._analyzer(completed_ids=["a.txt", "b.txt"])
        self._verified_ids = set()   # 'completed' in the index, but not verified

        update_learning_goal(
            _plan(ActionType.EXAM, goal_id="gs"),
            {"exams_passed": 1}, store, analyzer, None,
        )

        # file-based path is authoritative -> progress 0.0 -> no update, no close
        store.update_progress.assert_not_called()

    def test_fallback_increment_when_no_files_resolvable(self):
        """No file basis at all -> increment fallback still moves progress."""
        goal = self._goal({})
        store = specced(GoalStore)
        store.get.return_value = goal
        analyzer = self._analyzer()

        update_learning_goal(
            _plan(ActionType.LEARN, goal_id="g5"),
            {"chunks_learned": 2}, store, analyzer, None,
        )

        store.update_progress.assert_called_once_with("g5", 0.1)


class TestExamHandler:

    def test_exam_success(self):
        teacher = specced(TeacherAgent)
        teacher.run_session.return_value = {
            "stats": {"exams_run": 1, "exams_passed": 1,
                      "last_exam_score": 0.85, "last_exam_file": "f1.txt"}
        }
        h = make_exam_handler(teacher_agent=teacher)
        r = h(_plan(ActionType.EXAM))
        assert r["success"] is True
        assert r["score"] == 0.85

    def test_exam_idle_is_skip_not_fail(self):
        # C fix (2026-06-05): run_session idle (nothing to examine -- all files
        # completed or parked in the 6h exam cooldown) is a SKIP, not an exam
        # failure. It must NOT report success=False (that inflated the
        # action_failure_storm: 23/40 of the 06-01..06-05 storm were idle no-ops).
        teacher = specced(TeacherAgent)
        teacher.run_session.return_value = {
            "stats": {"exams_run": 0, "exams_passed": 0,
                      "idle_reason": "no_ready_files"}
        }
        h = make_exam_handler(teacher_agent=teacher)
        r = h(_plan(ActionType.EXAM))
        assert r["success"] is True
        assert r["skipped"] is True
        assert r["idle_reason"] == "no_ready_files"

    def test_exam_redirect_to_nonexam_strategy_is_skip(self):
        # run_session(1) chose a non-exam strategy (learn/fill_gap): work was
        # done, just not an exam -> skip, not fail.
        teacher = specced(TeacherAgent)
        teacher.run_session.return_value = {
            "stats": {"exams_run": 0, "exams_passed": 0, "strategies_executed": 1}
        }
        h = make_exam_handler(teacher_agent=teacher)
        r = h(_plan(ActionType.EXAM))
        assert r["success"] is True
        assert r["skipped"] is True

    def test_exam_genuine_pipeline_failure_still_fails(self):
        # A real exam attempt that failed (timeout/parse) raises
        # exam_pipeline_failures -- this MUST remain success=False so the storm
        # detector and K12 still see genuine exam breakage. Guards against the
        # C fix masking real failures.
        teacher = specced(TeacherAgent)
        teacher.run_session.return_value = {
            "stats": {"exams_run": 0, "exams_passed": 0,
                      "exam_pipeline_failures": 1, "strategies_executed": 1}
        }
        h = make_exam_handler(teacher_agent=teacher)
        r = h(_plan(ActionType.EXAM))
        assert r["success"] is False
        assert not r.get("skipped")

    def test_exam_emits_passed_signal(self):
        # C6 fix: passed exam → exam_passed (systematyczna+).
        teacher = specced(TeacherAgent)
        teacher.run_session.return_value = {
            "stats": {"exams_run": 1, "exams_passed": 1,
                      "last_exam_score": 0.85, "last_exam_file": "f1.txt"}
        }
        consc = MagicMock()
        h = make_exam_handler(teacher_agent=teacher, consciousness=consc)
        h(_plan(ActionType.EXAM))
        consc.record_experience.assert_called_once()
        assert consc.record_experience.call_args.args[0] == "exam_passed"

    def test_exam_emits_failed_signal_when_run_but_not_passed(self):
        # C6 fix: ran but failed → exam_failed (systematyczna−).
        teacher = specced(TeacherAgent)
        teacher.run_session.return_value = {
            "stats": {"exams_run": 1, "exams_passed": 0,
                      "last_exam_score": 0.3, "last_exam_file": "f2.txt"}
        }
        consc = MagicMock()
        h = make_exam_handler(teacher_agent=teacher, consciousness=consc)
        h(_plan(ActionType.EXAM))
        consc.record_experience.assert_called_once()
        assert consc.record_experience.call_args.args[0] == "exam_failed"


class TestReviewHandler:

    def test_review_success(self):
        teacher = specced(TeacherAgent)
        teacher.run_session.return_value = {
            "stats": {"strategies_executed": 2}
        }
        h = make_review_handler(teacher_agent=teacher)
        r = h(_plan(ActionType.REVIEW))
        assert r["success"] is True
        assert r["strategies_executed"] == 2


class TestEvaluateHandler:

    def test_evaluate_success(self):
        observer = specced(EvaluationObserver)
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
        observer = specced(EvaluationObserver)
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
        goal_store = specced(GoalStore)
        goal_store.get.return_value = goal

        h = make_maintenance_handler(homeostasis_core=core, goal_store=goal_store)
        plan = _plan(ActionType.MAINTENANCE, goal_id="g-maint")
        h(plan)
        goal_store.update_progress.assert_called_once_with("g-maint", 0.9)


class TestFetchHandler:

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_fetch_success(self, _window):
        analyzer = specced(KnowledgeAnalyzer)
        with patch("agent_core.web_source.run_fetch_session") as mock_fetch:
            mock_fetch.return_value = {
                "articles_fetched": 2, "topics_searched": 3, "errors": 0,
            }
            h = make_fetch_handler(knowledge_analyzer=analyzer)
            r = h(_plan(ActionType.FETCH))
            assert r["success"] is True
            assert r["articles_fetched"] == 2

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_fetch_success_creates_durable_learn_handoff(self, _window, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        for name in ("web_wiki_alpha.txt", "web_wiki_beta.txt"):
            (input_dir / name).write_text(
                "# Tytul: test\n# ---\n\n" + ("material edukacyjny " * 30),
                encoding="utf-8",
            )
        index_path = tmp_path / "memory" / "knowledge_index.jsonl"
        goals_path = tmp_path / "meta_data" / "goals.jsonl"

        analyzer = specced(KnowledgeAnalyzer)
        analyzer.input_dir = input_dir
        analyzer.index_path = index_path
        goal_store = GoalStore(goals_path)

        with patch("agent_core.web_source.run_fetch_session") as mock_fetch:
            mock_fetch.return_value = {
                "articles_fetched": 2,
                "fetched_files": ["web_wiki_alpha.txt", "web_wiki_beta.txt"],
                "topics_searched": 2,
                "errors": 0,
            }
            h = make_fetch_handler(
                knowledge_analyzer=analyzer,
                goal_store=goal_store,
            )
            r = h(_plan(ActionType.FETCH, goal_id="goal-meta"))

        assert r["success"] is True
        assert r["learn_handoff_files"] == [
            "web_wiki_alpha.txt", "web_wiki_beta.txt",
        ]

        reloaded = GoalStore(goals_path)
        reloaded.load()
        handoffs = [
            goal for goal in reloaded.get_active(GoalType.LEARNING)
            if goal.metadata.get("source") == "fetch_handoff"
        ]
        assert len(handoffs) == 1
        assert handoffs[0].metadata["file_ids"] == [
            "web_wiki_alpha.txt", "web_wiki_beta.txt",
        ]

        indexed = [
            json.loads(line)
            for line in index_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert {row["id"] for row in indexed} == {
            "web_wiki_alpha.txt", "web_wiki_beta.txt",
        }

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_fetch_zero_articles_does_not_create_handoff(self, _window, tmp_path):
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.input_dir = tmp_path / "input"
        analyzer.index_path = tmp_path / "memory" / "knowledge_index.jsonl"
        goal_store = GoalStore(tmp_path / "meta_data" / "goals.jsonl")

        with patch("agent_core.web_source.run_fetch_session") as mock_fetch:
            mock_fetch.return_value = {
                "articles_fetched": 0,
                "fetched_files": [],
                "topics_searched": 2,
                "errors": 0,
            }
            h = make_fetch_handler(
                knowledge_analyzer=analyzer,
                goal_store=goal_store,
            )
            r = h(_plan(ActionType.FETCH))

        assert r["success"] is True
        assert goal_store.get_active(GoalType.LEARNING) == []

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_fetch_with_errors_still_creates_handoff(self, _window, tmp_path):
        # P1: a session that wrote real files but also hit an error on another
        # topic (errors > 0) must STILL bind a learn-obligation -- the old
        # `errors == 0` gate orphaned those bytes (the live web_rss_* leak,
        # 7 files unbound on disk). fetched_files is the trigger now, not errors.
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "web_rss_orphan.txt").write_text(
            "# Tytul: test\n# ---\n\n" + ("material edukacyjny " * 30),
            encoding="utf-8",
        )
        index_path = tmp_path / "memory" / "knowledge_index.jsonl"
        goals_path = tmp_path / "meta_data" / "goals.jsonl"

        analyzer = specced(KnowledgeAnalyzer)
        analyzer.input_dir = input_dir
        analyzer.index_path = index_path
        goal_store = GoalStore(goals_path)

        with patch("agent_core.web_source.run_fetch_session") as mock_fetch:
            mock_fetch.return_value = {
                "articles_fetched": 1,
                "fetched_files": ["web_rss_orphan.txt"],
                "topics_searched": 3,
                "errors": 1,
            }
            h = make_fetch_handler(
                knowledge_analyzer=analyzer,
                goal_store=goal_store,
            )
            r = h(_plan(ActionType.FETCH, goal_id="goal-meta"))

        # The outcome still reports the error for telemetry...
        assert r["success"] is False
        assert r["errors"] == 1
        # ...but the obligation to learn the file we DID write was bound anyway.
        assert r["learn_handoff_files"] == ["web_rss_orphan.txt"]

        reloaded = GoalStore(goals_path)
        reloaded.load()
        handoffs = [
            goal for goal in reloaded.get_active(GoalType.LEARNING)
            if goal.metadata.get("source") == "fetch_handoff"
        ]
        assert len(handoffs) == 1
        assert handoffs[0].metadata["file_ids"] == ["web_rss_orphan.txt"]

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_fetch_with_errors(self, _window):
        analyzer = specced(KnowledgeAnalyzer)
        with patch("agent_core.web_source.run_fetch_session") as mock_fetch:
            mock_fetch.return_value = {
                "articles_fetched": 1, "topics_searched": 3, "errors": 2,
            }
            h = make_fetch_handler(knowledge_analyzer=analyzer)
            r = h(_plan(ActionType.FETCH))
            assert r["success"] is False
            assert r["errors"] == 2

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_fetch_exception(self, _window):
        analyzer = specced(KnowledgeAnalyzer)
        with patch("agent_core.web_source.run_fetch_session") as mock_fetch:
            mock_fetch.side_effect = ConnectionError("offline")
            h = make_fetch_handler(knowledge_analyzer=analyzer)
            r = h(_plan(ActionType.FETCH))
            assert r["success"] is False
            assert "offline" in r["error"]


class TestExperimentHandler:

    def test_experiment_success(self):
        system = specced(ExperimentSystem)
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
        system = specced(ExperimentSystem)
        h = make_experiment_handler(experiment_system=system)
        r = h(_plan(ActionType.EXPERIMENT))
        assert r["success"] is False
        assert "proposal_id" in r["error"]

    def test_experiment_returns_none(self):
        system = specced(ExperimentSystem)
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
        # Real AnalysisReport: the analyzer's text output is raw_response, NOT
        # analysis_text (a phantom). A real dataclass makes that regress red (bug #1).
        report = AnalysisReport(
            report_id="sa-1",
            recommendations=["improve retention"],
            goals_created=["g1"],
            duration_ms=500,
            raw_response="system looks healthy",
            error=None,
        )
        analysis.run_analysis.return_value = report
        h = make_self_analyze_handler(self_analysis=analysis)
        r = h(_plan(ActionType.SELF_ANALYZE, {"period_days": 3}))
        assert r["success"] is True
        assert r["recommendations"] == 1
        analysis.run_analysis.assert_called_once_with(period_days=3)

    def test_error_in_report(self):
        analysis = MagicMock()
        report = AnalysisReport(report_id="sa-err", error="LLM unavailable")
        analysis.run_analysis.return_value = report
        h = make_self_analyze_handler(self_analysis=analysis)
        r = h(_plan(ActionType.SELF_ANALYZE))
        assert r["success"] is False
        assert r["error"] == "LLM unavailable"

    def test_telegram_notification(self):
        analysis = MagicMock()
        # Real AnalysisReport guards bug #1: if production reads the phantom
        # analysis_text again, the notify branch raises (swallowed) and the
        # assert_called_once below fails.
        report = AnalysisReport(
            report_id="sa-2",
            recommendations=["rec1"],
            goals_created=[],
            duration_ms=100,
            raw_response="text",
            error=None,
        )
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
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_knowledge_snapshot.return_value = {
            "files_by_status": {"completed": []}
        }
        h = make_validate_handler(
            cross_validator=validator, knowledge_analyzer=analyzer,
        )
        r = h(_plan(ActionType.VALIDATE))
        assert r["success"] is False
        assert "No files" in r["error"]

    def test_accepts_dict_file_id(self, tmp_path, monkeypatch):
        """B2 regression: production passes a knowledge-index dict as file_id."""
        import maria_core.sys.config as config

        file_id = "input_001_bajka_o_miescie.txt"
        file_id_dict = {
            "id": file_id,
            "folder": "root",
            "file": file_id,
            "status": "completed",
            "priority": 73.0,
            "hash": "3d602fecd85d800a36d761c3f401259cb5a35f466019bd264023b5ccc251ec23",
            "created_at": "2026-02-01T09:09:12.442951Z",
            "updated_at": "2026-03-22T10:21:36.193986Z",
            "exam_attempts": 2,
            "last_scores": [0.83, 0.83],
            "chunks_learned": 1,
            "total_chunks": 1,
        }

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / file_id).write_text(
            "Ala ma kota. To jest material do walidacji. " * 20,
            encoding="utf-8",
        )
        memory_path = tmp_path / "maria_longterm_memory.jsonl"
        memory_path.write_text(
            json.dumps({"source_file": file_id, "text": "Ala ma kota."}) + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(config, "INPUT_DIR", input_dir)
        monkeypatch.setattr(config, "LONGTERM_MEMORY", memory_path)

        validator = MagicMock()
        validator.validate_file.return_value = {
            "chunks_validated": 1,
            "chunks_agreed": 1,
            "chunks_disputed": 0,
            "avg_confidence": 0.83,
        }
        h = make_validate_handler(cross_validator=validator)

        r = h(_plan(ActionType.VALIDATE, params={"file_id": file_id_dict}))

        assert r["success"] is True
        assert r["file_id"] == file_id
        validator.validate_file.assert_called_once()
        assert validator.validate_file.call_args.kwargs["file_id"] == file_id

    def test_rejects_unknown_file_id_shape(self):
        """B2 regression: unsupported file_id shape returns an error."""
        validator = MagicMock()
        h = make_validate_handler(cross_validator=validator)

        r = h(_plan(ActionType.VALIDATE, params={"file_id": 123}))

        assert r["success"] is False
        assert "unsupported type int" in r["error"]
        validator.validate_file.assert_not_called()

    def test_dict_file_id_without_id_or_file_keys(self):
        """B2 regression: malformed file_id dict returns an error."""
        validator = MagicMock()
        h = make_validate_handler(cross_validator=validator)

        r = h(_plan(ActionType.VALIDATE, params={"file_id": {"folder": "root"}}))

        assert r["success"] is False
        assert "missing 'id' and 'file'" in r["error"]
        validator.validate_file.assert_not_called()

    def test_belief_revisions_counted_and_persisted(self, tmp_path, monkeypatch):
        """Dead store.flush() regression (found 2026-06-10): BeliefStore
        persists via save(), flush() never existed -- the AttributeError
        fell into the broad except, so the handler reported
        beliefs_updated=0 despite applying revisions in memory. MUST use
        a REAL BeliefStore: a MagicMock world_model invents flush() and
        hides the bug (mock-hidden, like auto_promotion)."""
        import maria_core.sys.config as config
        from types import SimpleNamespace

        from agent_core.world_model.belief_model import (
            BeliefSource,
            BeliefType,
            EntityType,
            create_belief,
        )
        from agent_core.world_model.belief_store import BeliefStore

        file_id = "input_001_bajka_o_miescie.txt"
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / file_id).write_text(
            "Ala ma kota. To jest material do walidacji. " * 20,
            encoding="utf-8",
        )
        memory_path = tmp_path / "maria_longterm_memory.jsonl"
        memory_path.write_text(
            json.dumps({"source_file": file_id, "text": "Ala ma kota."}) + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(config, "INPUT_DIR", input_dir)
        monkeypatch.setattr(config, "LONGTERM_MEMORY", memory_path)

        beliefs_path = tmp_path / "beliefs.jsonl"
        store = BeliefStore(beliefs_path)
        store.add(create_belief(
            entity="bajka o miescie",
            entity_type=EntityType.TOPIC,
            belief_type=BeliefType.OBSERVATION,
            content="Miasto w bajce ma rynek",
            confidence=0.5,
            source=BeliefSource.LEARNING,
            source_id=file_id,
        ))
        store.save()

        validator = MagicMock()
        validator.validate_file.return_value = {
            "chunks_validated": 1,
            "chunks_agreed": 1,
            "chunks_disputed": 0,
            "avg_confidence": 0.83,
        }
        h = make_validate_handler(
            cross_validator=validator,
            world_model=SimpleNamespace(store=store),
        )

        r = h(_plan(ActionType.VALIDATE, params={"file_id": file_id}))

        assert r["success"] is True
        assert r["beliefs_updated"] == 1  # was 0 with the dead flush()
        assert store._dirty == set()      # save() ran inside the handler

        # The revision survives a cold reload -- it reached the JSONL.
        reloaded = BeliefStore(beliefs_path)
        reloaded.load()
        current = [
            b for b in reloaded.get_current() if b.source_id == file_id
        ]
        assert len(current) == 1
        assert current[0].confidence == pytest.approx(0.5 * 0.6 + 0.83 * 0.4)
        assert current[0].belief_type == BeliefType.FACT  # 0.83 promotes


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
        store = specced(GoalStore)
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
        store = specced(GoalStore)
        store.get.return_value = goal
        update_learning_goal(
            _plan(goal_id="g-1"), {"chunks_learned": 2},
            goal_store=store, knowledge_analyzer=None, telegram_notifier=None,
        )
        store.update_progress.assert_called_once_with("g-1", 0.1)


class TestIndependentlyVerifiedCompletedIds:
    """The trusted-DONE set (audit 2026-06-01): a file may force-close a goal
    only when it is 'completed' AND an independent examiner verified it. A
    duplicate inherits verification from its canonical -- but only a genuinely
    verified canonical."""

    def _snap(self, completed=(), duplicates=()):
        return {"files_by_status": {
            "completed": [{"id": f, "file": f} for f in completed],
            "duplicate": [{"id": d, "file": d, "duplicate_of": c}
                          for d, c in duplicates],
        }}

    def test_excludes_self_graded_completed(self):
        from agent_core.routing.handlers import independently_verified_completed_ids
        snap = self._snap(completed=["a.txt", "b.txt"])
        # a.txt independently verified; b.txt 'completed' but self-graded.
        out = independently_verified_completed_ids(snap, verified_ids={"a.txt"})
        assert out == {"a.txt"}

    def test_duplicate_inherits_verified_canonical(self):
        from agent_core.routing.handlers import independently_verified_completed_ids
        snap = self._snap(completed=["canon.txt"],
                          duplicates=[("dup.txt", "canon.txt")])
        out = independently_verified_completed_ids(snap, verified_ids={"canon.txt"})
        assert out == {"canon.txt", "dup.txt"}

    def test_duplicate_of_unverified_not_credited(self):
        from agent_core.routing.handlers import independently_verified_completed_ids
        snap = self._snap(completed=["canon.txt"],
                          duplicates=[("dup.txt", "canon.txt")])
        out = independently_verified_completed_ids(snap, verified_ids=set())
        assert out == set()
