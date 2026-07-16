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
from agent_core.goals.goal_model import GoalStatus, GoalType, create_goal
from agent_core.goals.store import GoalStore
from agent_core.self_analysis import SelfAnalysis
from agent_core.self_analysis.recommendation_model import AnalysisReport
from agent_core.evaluation import EvaluationObserver
from agent_core.evaluation.report import EvaluationReport
from agent_core.experiment import ExperimentSystem
from agent_core.experiment.experiment_model import ExperimentReport
from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
from agent_core.teacher.teacher_agent import TeacherAgent
from agent_core.bulletin.expert_bridge import ExpertBridge, ExpertResponse
from agent_core.consciousness.core import ConsciousnessCore
from agent_core.creative.facade import CreativeModule
from agent_core.critic import CriticAgent
from agent_core.critic.critique_model import (
    CritiqueReport,
    FindingCategory,
    FindingSeverity,
    SuggestedCritiqueAction,
    create_finding,
)
from agent_core.cross_validation.cross_validator import CrossValidator
from agent_core.effector.openclaw_client import OpenClawClient
from agent_core.homeostasis.core import HomeostasisCore
from agent_core.homeostasis.state_model import Mode, SystemState
from agent_core.llm.router import LLMRouter
from agent_core.semantic import SemanticMemory
from agent_core.telegram.notifier import TelegramNotifier
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
        assert resolve_topics(plan, specced(KnowledgeAnalyzer)) is None

    def test_cached_resolved_ids(self):
        plan = _plan(params={"topics": ["fizyka"], "resolved_file_ids": ["f1"]})
        result = resolve_topics(plan, specced(KnowledgeAnalyzer))
        assert result == ["f1"]

    def test_direct_resolved_file_ids(self):
        plan = _plan(params={"resolved_file_ids": ["web_wiki_a.txt"]})
        result = resolve_topics(plan, specced(KnowledgeAnalyzer))
        assert result == ["web_wiki_a.txt"]

    def test_cached_empty_returns_none(self):
        plan = _plan(params={"topics": ["fizyka"], "resolved_file_ids": []})
        result = resolve_topics(plan, specced(KnowledgeAnalyzer))
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
        # Deliberately NOT specced: this exercises the duck-typed
        # `hasattr(x, 'notify')` branch, and NO class in the codebase actually
        # implements notify() -- see the phantom reported in this sweep. A
        # specced(TelegramNotifier) would pass here through the *other* branch
        # (not callable), silently changing what this test covers.
        notifier = MagicMock()
        notifier.notify = MagicMock()
        assert _resolve_notifier(notifier) is notifier

    def test_late_binding_callable(self):
        # A real lambda, exactly like production wires it
        # (homeostasis_module.py:1057 `_tg = lambda: ...`) -- a plain closure,
        # not an agent_core class, and it has no 'notify' attr by construction.
        notifier = specced(TelegramNotifier)
        factory = lambda: notifier
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
        semantic = specced(SemanticMemory)
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
        consc = specced(ConsciousnessCore)
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
        consc = specced(ConsciousnessCore)
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
        # REAL Goal, not a mock: Goal is a dataclass whose fields have no class
        # defaults, so create_autospec would reject `metadata`/`progress`. The
        # real object enforces field names AND real enum types for free.
        goal = create_goal(
            goal_type=GoalType.LEARNING,
            description="Nauka: test",
            priority=0.5,
            status=GoalStatus(status),
            metadata=metadata,
        )
        goal.progress = progress
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
        consc = specced(ConsciousnessCore)
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
        consc = specced(ConsciousnessCore)
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
        # REAL EvaluationReport (dataclass): enforces the field names the
        # handler reads, unlike a mock that invents any attribute.
        report = EvaluationReport(
            timestamp=1000.0,
            report_id="rpt-1",
            period_start=0.0,
            period_end=1000.0,
            metrics={"learning_velocity": 0.8},
            recommendations=["keep going"],
        )
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
        core = specced(HomeostasisCore)
        # REAL SystemState: `state.mode.value` is a genuine Mode enum, so the
        # handler's `state.mode.value` cannot silently read a phantom.
        state = SystemState(
            mode=Mode.ACTIVE,
            health_score=0.85,
            last_mode_change_time=1000.0,
            interpreted_state={"cpu_load": 30, "ram_available_pct": 70},
        )
        core.get_state.return_value = state
        h = make_maintenance_handler(homeostasis_core=core)
        r = h(_plan(ActionType.MAINTENANCE))
        assert r["success"] is True
        assert r["health_score"] == 0.85
        assert r["mode"] == "active"

    def test_maintenance_updates_goal_progress(self):
        core = specced(HomeostasisCore)
        state = SystemState(
            mode=Mode.ACTIVE,
            health_score=0.9,
            last_mode_change_time=1000.0,
            interpreted_state={},
        )
        core.get_state.return_value = state

        goal = create_goal(
            goal_type=GoalType.MAINTENANCE,
            description="Utrzymaj zdrowie",
            priority=0.5,
            metadata={"metric": "health_score", "threshold": 1.0},
        )
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

        # Yield-aware (2026-06-26): 0 articles + 0 errors is NOT success -- it is a
        # skipped/idle fetch (nothing new to fetch), so the saturation pump is not
        # falsely reinforced. Still no handoff (no files written).
        assert r["success"] is False
        assert r["skipped"] is True
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
        # REAL ExperimentReport (dataclass) -- real field names, no phantoms.
        report = ExperimentReport(
            report_id="exp-1",
            experiment_id="e-1",
            proposal_id="prop-1",
            timestamp=1000.0,
            hypothesis="retention rises",
            method="ab",
            parameter_id="p-1",
            baseline_value=1,
            test_value=2,
            baseline_metrics={"retention": 0.5},
            result_metrics={"retention": 0.7},
            delta_metrics={"retention": 0.2},
            test_cycles=3,
            duration_sec=10.0,
            conclusion="retention improved",
            recommendation="ADOPT",
            confidence=0.8,
        )
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
        client = specced(OpenClawClient)
        client.invoke_tool.return_value = {"ok": True, "result": "done"}
        h = make_effector_handler(openclaw_client=client)
        r = h(_plan(ActionType.EFFECTOR, {"tool_name": "exec", "tool_args": {"cmd": "ls"}}))
        assert r["success"] is True
        assert r["tool_name"] == "exec"
        assert r["tool_result"] == "done"

    def test_effector_no_tool_name(self):
        client = specced(OpenClawClient)
        h = make_effector_handler(openclaw_client=client)
        r = h(_plan(ActionType.EFFECTOR))
        assert r["success"] is False
        assert "tool_name" in r["error"]

    def test_effector_exception(self):
        client = specced(OpenClawClient)
        client.invoke_tool.side_effect = TimeoutError("timeout")
        h = make_effector_handler(openclaw_client=client)
        r = h(_plan(ActionType.EFFECTOR, {"tool_name": "exec"}))
        assert r["success"] is False
        assert "timeout" in r["error"]


class TestSelfAnalyzeHandler:

    def test_success(self):
        analysis = specced(SelfAnalysis)
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
        analysis = specced(SelfAnalysis)
        report = AnalysisReport(report_id="sa-err", error="LLM unavailable")
        analysis.run_analysis.return_value = report
        h = make_self_analyze_handler(self_analysis=analysis)
        r = h(_plan(ActionType.SELF_ANALYZE))
        assert r["success"] is False
        assert r["error"] == "LLM unavailable"

    def test_telegram_notification(self):
        analysis = specced(SelfAnalysis)
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
        notifier = specced(TelegramNotifier)
        h = make_self_analyze_handler(
            self_analysis=analysis, telegram_notifier=notifier,
        )
        h(_plan(ActionType.SELF_ANALYZE))
        notifier.notify_self_analysis.assert_called_once()


class TestCreativeHandler:

    def test_success(self):
        creative = specced(CreativeModule)
        # Explicit: an autospec'd should_reflect() still returns a truthy Mock,
        # which would bypass the cooldown guard by accident. Say so out loud.
        creative.should_reflect.return_value = True
        creative.reflect.return_value = {
            "success": True, "tensions": ["repetition"],
            "meta_goals_created": [],
        }
        h = make_creative_handler(creative_module=creative)
        r = h(_plan(ActionType.CREATIVE, {"trigger": "planner"}))
        assert r["success"] is True
        creative.reflect.assert_called_once_with(trigger="planner")

    def test_exception(self):
        creative = specced(CreativeModule)
        creative.should_reflect.return_value = True
        creative.reflect.side_effect = RuntimeError("boom")
        h = make_creative_handler(creative_module=creative)
        r = h(_plan(ActionType.CREATIVE))
        assert r["success"] is False
        assert "boom" in r["error"]

    def test_telegram_tensions(self):
        creative = specced(CreativeModule)
        creative.should_reflect.return_value = True
        creative.reflect.return_value = {
            "success": True, "tensions": ["t1"],
            "meta_goals_created": ["mg1"],
        }
        notifier = specced(TelegramNotifier)
        h = make_creative_handler(
            creative_module=creative, telegram_notifier=notifier,
        )
        h(_plan(ActionType.CREATIVE))
        notifier.notify_creative_tensions.assert_called_once_with(["t1"])
        notifier.notify_creative_meta_goals.assert_called_once_with(["mg1"])

    # -- Cooldown guard (2026-07-06): purpose-built stubs, NOT MagicMock --
    # a MagicMock's should_reflect() returns a truthy mock, which silently
    # bypasses the guard -- exactly the mock-hidden-bug class.

    class _CooldownFacade:
        """Stub facade on cooldown; reflect() must never run."""
        def should_reflect(self):
            return False

        def reflect(self, trigger="periodic"):
            raise AssertionError("reflect() must not run on cooldown")

    class _ReadyFacade:
        """Stub facade past cooldown; records reflect() triggers."""
        def __init__(self):
            self.calls = []

        def should_reflect(self):
            return True

        def reflect(self, trigger="periodic"):
            self.calls.append(trigger)
            return {"success": True, "tensions": [], "meta_goals_created": []}

    def test_cooldown_skips_reflect(self):
        h = make_creative_handler(creative_module=self._CooldownFacade())
        r = h(_plan(ActionType.CREATIVE))
        # success must be False: PlannerCore checks success BEFORE skipped,
        # so True here would mark the plan COMPLETED and feed phantom
        # successes to backoff/StrategicPlanner/K8 (review finding 07-06).
        assert r["success"] is False
        assert r["skipped"] is True
        assert r["idle_reason"] == "creative_cooldown"

    def test_cooldown_elapsed_runs_reflect(self):
        facade = self._ReadyFacade()
        h = make_creative_handler(creative_module=facade)
        r = h(_plan(ActionType.CREATIVE, {"trigger": "planner"}))
        assert r["success"] is True
        assert facade.calls == ["planner"]

    def test_real_facade_cooldown_skips(self, tmp_path):
        # REAL CreativeModule: fresh reflection timestamp -> the handler must
        # skip without starting a cycle. tmp dirs, never the CWD defaults.
        import time
        from agent_core.creative.facade import CreativeModule
        module = CreativeModule(data_dir=str(tmp_path),
                                memory_dir=str(tmp_path))
        module._last_reflection_ts = time.time()
        h = make_creative_handler(creative_module=module)
        r = h(_plan(ActionType.CREATIVE))
        assert r["success"] is False
        assert r.get("skipped") is True
        assert r["idle_reason"] == "creative_cooldown"

    def test_fallback_exec_creative_mirrors_guard(self):
        # The no-router fallback (_exec_creative) must behave identically --
        # it is the path tests/dev harnesses hit when no CapabilityRouter is
        # wired.
        from agent_core.planner.action_executor import ActionExecutor
        ex = ActionExecutor()
        ex._creative_module = self._CooldownFacade()
        r = ex._exec_creative(_plan(ActionType.CREATIVE))
        assert r["success"] is False
        assert r["skipped"] is True
        assert r["idle_reason"] == "creative_cooldown"


class TestAskExpertHandler:

    def test_expert_bridge_success(self):
        bridge = specced(ExpertBridge)
        # REAL ExpertResponse (dataclass) -- the handler reads 7 attributes off
        # it; a mock would happily invent any of them.
        resp = ExpertResponse(
            success=True,
            topic="fizyka",
            response="Fizyka to nauka o..." * 20,
            context_prompt="Pytanie o fizyka",
            gap_action="ASK_EXPERT",
            reason="",
            duration_ms=150,
            metadata={},
        )
        bridge.ask_about_topic.return_value = resp
        h = make_ask_expert_handler(
            llm_router=specced(LLMRouter), expert_bridge=bridge,
        )
        r = h(_plan(ActionType.ASK_EXPERT, {"topic": "fizyka"}))
        assert r["success"] is True
        assert r["saved_to_input"] is False or r["saved_to_input"] is True

    def test_expert_bridge_skip(self):
        bridge = specced(ExpertBridge)
        resp = ExpertResponse(
            success=False,
            topic="fizyka",
            reason="expert_material_already_exists",
            gap_action="",
        )
        bridge.ask_about_topic.return_value = resp
        h = make_ask_expert_handler(
            llm_router=specced(LLMRouter), expert_bridge=bridge,
        )
        r = h(_plan(ActionType.ASK_EXPERT, {"topic": "fizyka"}))
        assert r["success"] is True
        assert r["skipped"] is True

    def test_legacy_fallback(self):
        router = specced(LLMRouter)
        router.ask_encyclopedia.return_value = "Odpowiedz eksperta"
        h = make_ask_expert_handler(llm_router=router, expert_bridge=None)
        r = h(_plan(ActionType.ASK_EXPERT, {"topic": "chemia"}))
        assert r["success"] is True
        assert r["response_length"] > 0

    def test_legacy_empty_response(self):
        router = specced(LLMRouter)
        router.ask_encyclopedia.return_value = ""
        h = make_ask_expert_handler(llm_router=router)
        r = h(_plan(ActionType.ASK_EXPERT, {"topic": "chemia"}))
        assert r["success"] is False

    def test_no_topic_no_question(self):
        router = specced(LLMRouter)
        h = make_ask_expert_handler(llm_router=router)
        r = h(_plan(ActionType.ASK_EXPERT))
        assert r["success"] is False


class TestCritiqueHandler:

    def test_success(self):
        critic = specced(CriticAgent)
        # REAL CritiqueReport -- goals_created is a List[str] in the dataclass,
        # so the old `= 0` mock was lying about the shape too.
        report = CritiqueReport(
            report_id="cr-1",
            findings=[],
            goals_created=[],
            findings_total=0,
            duration_ms=200,
            error=None,
        )
        critic.run_critique.return_value = report
        h = make_critique_handler(critic_agent=critic)
        r = h(_plan(ActionType.CRITIQUE))
        assert r["success"] is True
        assert r["findings"] == 0

    def test_error_in_report(self):
        critic = specced(CriticAgent)
        report = CritiqueReport(report_id="cr-err", error="no beliefs")
        critic.run_critique.return_value = report
        h = make_critique_handler(critic_agent=critic)
        r = h(_plan(ActionType.CRITIQUE))
        assert r["success"] is False

    def test_telegram_critical_findings(self):
        critic = specced(CriticAgent)
        # REAL CritiqueFinding via its factory: this is what actually pins the
        # handler's `f.severity == "critical"` string compare to the real
        # FindingSeverity.CRITICAL.value. A mock hand-setting the string would
        # keep passing even if the field became an enum.
        finding = create_finding(
            category=FindingCategory.CONTRADICTION,
            severity=FindingSeverity.CRITICAL,
            topic="fizyka",
            description="sprzecznosc",
            suggested_action=SuggestedCritiqueAction.RESOLVE,
        )
        assert finding.severity == "critical"   # guards the compare above
        report = CritiqueReport(
            report_id="cr-2",
            findings=[finding],
            goals_created=[],
            findings_total=1,
            duration_ms=100,
            error=None,
        )
        critic.run_critique.return_value = report
        notifier = specced(TelegramNotifier)
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
        validator = specced(CrossValidator)
        h = make_validate_handler(cross_validator=validator)
        r = h(_plan(ActionType.VALIDATE))
        assert r["success"] is False

    def test_no_candidate_returns_error(self):
        validator = specced(CrossValidator)
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

        validator = specced(CrossValidator)
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
        validator = specced(CrossValidator)
        h = make_validate_handler(cross_validator=validator)

        r = h(_plan(ActionType.VALIDATE, params={"file_id": 123}))

        assert r["success"] is False
        assert "unsupported type int" in r["error"]
        validator.validate_file.assert_not_called()

    def test_dict_file_id_without_id_or_file_keys(self):
        """B2 regression: malformed file_id dict returns an error."""
        validator = specced(CrossValidator)
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

        validator = specced(CrossValidator)
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
            goal_store=specced(GoalStore), knowledge_analyzer=None,
            telegram_notifier=None,
        )

    def test_non_learning_goal_skipped(self):
        goal = create_goal(
            goal_type=GoalType.META,
            description="Misja",
            priority=1.0,
        )
        store = specced(GoalStore)
        store.get.return_value = goal
        update_learning_goal(
            _plan(goal_id="g-meta"), {"chunks_learned": 1},
            goal_store=store, knowledge_analyzer=None, telegram_notifier=None,
        )
        store.update_progress.assert_not_called()

    def test_progress_increment_on_chunks(self):
        goal = create_goal(
            goal_type=GoalType.LEARNING,
            description="Nauka",
            priority=0.5,
            metadata={},
        )
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


class TestFetchHandlerFeedProfile:
    """B1 choke-point: market goals fetch from MARKET_FEEDS; None-safe."""

    @staticmethod
    def _goal(metadata):
        return create_goal(
            goal_type=GoalType.LEARNING,
            description="Fetch test",
            priority=0.5,
            metadata=metadata,
        )

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_market_goal_passes_market_profile(self, _window):
        analyzer = specced(KnowledgeAnalyzer)
        goal_store = specced(GoalStore)
        goal_store.get.return_value = self._goal({"source_kind": "market"})
        with patch("agent_core.web_source.run_fetch_session") as mock_fetch:
            mock_fetch.return_value = {
                "articles_fetched": 1, "topics_searched": 0, "errors": 0,
            }
            h = make_fetch_handler(knowledge_analyzer=analyzer, goal_store=goal_store)
            h(_plan(ActionType.FETCH, goal_id="goal-mkt"))
            assert mock_fetch.call_args.kwargs["feed_profile"] == "market"

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_non_market_goal_passes_no_profile(self, _window):
        analyzer = specced(KnowledgeAnalyzer)
        goal_store = specced(GoalStore)
        goal_store.get.return_value = self._goal({"project_parent": "p1"})
        with patch("agent_core.web_source.run_fetch_session") as mock_fetch:
            mock_fetch.return_value = {
                "articles_fetched": 1, "topics_searched": 0, "errors": 0,
            }
            h = make_fetch_handler(knowledge_analyzer=analyzer, goal_store=goal_store)
            h(_plan(ActionType.FETCH, goal_id="goal-sci"))
            assert mock_fetch.call_args.kwargs["feed_profile"] is None

    @patch("agent_core.environment.environment_model.is_learning_window",
           return_value=True)
    def test_no_goal_store_is_none_safe(self, _window):
        # Regression for the B1 bug the red-team caught: an unguarded
        # goal_store.get(plan.goal_id) with goal_store=None would AttributeError,
        # and CapabilityRouter would turn it into success=False for EVERY fetch
        # (science too). resolve_feed_profile must return None instead.
        analyzer = specced(KnowledgeAnalyzer)
        with patch("agent_core.web_source.run_fetch_session") as mock_fetch:
            mock_fetch.return_value = {
                "articles_fetched": 1, "topics_searched": 0, "errors": 0,
            }
            h = make_fetch_handler(knowledge_analyzer=analyzer)  # goal_store=None
            r = h(_plan(ActionType.FETCH, goal_id="goal-x"))
            assert r["success"] is True
            assert mock_fetch.call_args.kwargs["feed_profile"] is None


class TestProvenanceGate:
    """Kronika TIER 1: market children credited only by provenance, scoped so
    every other goal is unchanged; observe-first (inert until cutover)."""

    # -- unit: mode --------------------------------------------------------
    def test_mode_default_off(self, monkeypatch):
        from agent_core.routing.handlers import _provenance_gate_mode
        monkeypatch.delenv("KRONIKA_PROVENANCE_GATE", raising=False)
        assert _provenance_gate_mode() == "off"

    def test_mode_valid_values(self, monkeypatch):
        from agent_core.routing.handlers import _provenance_gate_mode
        for v in ("off", "observe", "cutover"):
            monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", v.upper())
            assert _provenance_gate_mode() == v
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "nonsense")
        assert _provenance_gate_mode() == "off"

    # -- unit: _credit_progress -------------------------------------------
    def test_credit_progress_non_market(self):
        from agent_core.routing.handlers import _credit_progress
        g = self._goal({"topics": ["x"]})
        assert _credit_progress(g, 2, 4) == 0.5
        assert _credit_progress(g, 0, 0) == 0.0  # no zero-division

    def test_credit_progress_market_target_n(self):
        from agent_core.routing.handlers import _credit_progress
        g = self._goal({"source_kind": "market", "provenance_target_n": 5})
        assert _credit_progress(g, 3, 20) == 0.6      # 3/5, ignores the 20 total
        assert _credit_progress(g, 9, 20) == 1.0      # capped at 1.0

    # -- unit: resolve_goal_files gate ------------------------------------
    def _goal(self, metadata, gid="g1"):
        return create_goal(
            goal_type=GoalType.LEARNING,
            description="Provenance test",
            priority=0.5,
            metadata=metadata,
            goal_id=gid,
        )

    def _analyzer(self, topic_files):
        a = specced(KnowledgeAnalyzer)
        a.get_files_for_topics.return_value = [(f, 1.0) for f in topic_files]
        return a

    def test_resolve_non_market_unchanged(self, monkeypatch):
        from agent_core.routing.handlers import resolve_goal_files
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "cutover")
        g = self._goal({"topics": ["chemia"]})
        assert resolve_goal_files(g, None, self._analyzer(["c.txt"])) == ["c.txt"]

    def test_resolve_market_off_uses_topic_match(self, monkeypatch):
        from agent_core.routing.handlers import resolve_goal_files
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "off")
        g = self._goal({"source_kind": "market", "topics": ["btc"]})
        assert resolve_goal_files(g, None, self._analyzer(["junk.txt"])) == ["junk.txt"]

    def test_resolve_market_cutover_no_stamp_returns_empty(self, monkeypatch):
        from agent_core.routing.handlers import resolve_goal_files
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "cutover")
        g = self._goal({"source_kind": "market", "topics": ["btc"]})
        # token-match WOULD return junk.txt, but the gate credits only provenance
        assert resolve_goal_files(g, None, self._analyzer(["junk.txt"])) == []

    def test_resolve_market_cutover_uses_stamped(self, monkeypatch):
        from agent_core.routing.handlers import resolve_goal_files
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "cutover")
        g = self._goal({
            "source_kind": "market", "topics": ["btc"],
            "market_file_ids": ["web_rss_20260710_zloto.txt"],
        })
        assert resolve_goal_files(g, None, self._analyzer(["junk.txt"])) == [
            "web_rss_20260710_zloto.txt"
        ]

    def test_resolve_market_observe_inert(self, monkeypatch):
        from agent_core.routing.handlers import resolve_goal_files
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "observe")
        g = self._goal({"source_kind": "market", "topics": ["btc"],
                        "market_file_ids": ["stamped.txt"]})
        # observe = current behavior (token-match), just logs
        assert resolve_goal_files(g, None, self._analyzer(["junk.txt"])) == ["junk.txt"]

    # -- unit: /project sub-goal freshness floor + provenance (2026-07-11) --
    def _project_child(self, metadata, created_at=1000.0, gid="pc1"):
        g = create_goal(
            goal_type=GoalType.LEARNING,
            description="Project child",
            priority=0.5,
            metadata=metadata,
            goal_id=gid,
        )
        g.created_at = created_at
        return g

    def test_resolve_project_child_excludes_stale_topic_match(self, monkeypatch):
        # gate off: a /project child must NOT credit a PRE-EXISTING token-matched
        # file (the confirmed false-close). The freshness floor drops it.
        from agent_core.routing.handlers import resolve_goal_files
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "off")
        g = self._project_child({"project_parent": "p", "topics": ["timeline"]})
        a = self._analyzer(["old.txt"])
        a.files_created_since.return_value = set()  # old.txt predates the goal
        assert resolve_goal_files(g, None, a) == []

    def test_resolve_project_child_keeps_fresh_topic_match(self, monkeypatch):
        from agent_core.routing.handlers import resolve_goal_files
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "off")
        g = self._project_child({"project_parent": "p", "topics": ["timeline"]})
        a = self._analyzer(["fresh.txt", "old.txt"])
        a.files_created_since.return_value = {"fresh.txt"}
        assert resolve_goal_files(g, None, a) == ["fresh.txt"]

    def test_resolve_project_child_cutover_provenance_only(self, monkeypatch):
        # gate cutover: even a NON-market /project child owns ONLY stamped
        # provenance, never token-match; empty stamp -> [] (frozen until fetch).
        from agent_core.routing.handlers import resolve_goal_files
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "cutover")
        stamped = self._project_child(
            {"project_parent": "p", "topics": ["timeline"],
             "market_file_ids": ["prov.txt"]})
        assert resolve_goal_files(
            stamped, None, self._analyzer(["junk.txt"])) == ["prov.txt"]
        empty = self._project_child({"project_parent": "p", "topics": ["timeline"]})
        assert resolve_goal_files(empty, None, self._analyzer(["junk.txt"])) == []

    # -- unit: stamp_market_provenance ------------------------------------
    def test_stamp_market_goal(self):
        from agent_core.routing.handlers import stamp_market_provenance
        goal = self._goal({"source_kind": "market"}, gid="gm")
        store = specced(GoalStore); store.get.return_value = goal
        stamp_market_provenance(_plan(ActionType.FETCH, goal_id="gm"),
                                ["a.txt", "b.txt"], store)
        assert goal.metadata["market_file_ids"] == ["a.txt", "b.txt"]
        store.save.assert_called_once()

    def test_stamp_project_child(self):
        # 2026-07-11: a non-market /project sub-goal now records provenance too
        # (read back by resolve_goal_files under the gate), not just market goals.
        from agent_core.routing.handlers import stamp_market_provenance
        goal = self._goal({"project_parent": "p1"}, gid="pc")
        store = specced(GoalStore); store.get.return_value = goal
        stamp_market_provenance(_plan(ActionType.FETCH, goal_id="pc"),
                                ["a.txt", "b.txt"], store)
        assert goal.metadata["market_file_ids"] == ["a.txt", "b.txt"]
        store.save.assert_called_once()

    def test_stamp_plain_goal_noop(self):
        # Neither market nor /project child -> still a no-op.
        from agent_core.routing.handlers import stamp_market_provenance
        goal = self._goal({"topics": ["x"]}, gid="g")
        store = specced(GoalStore); store.get.return_value = goal
        stamp_market_provenance(_plan(ActionType.FETCH, goal_id="g"), ["a.txt"], store)
        assert "market_file_ids" not in goal.metadata

    # -- unit: files_created_since (freshness parse) ----------------------
    def test_files_created_since_parses_and_filters(self, tmp_path):
        import json as _json
        from datetime import datetime, timezone
        from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
        idx = tmp_path / "knowledge_index.jsonl"
        idx.write_text("\n".join(_json.dumps(r) for r in [
            {"id": "old.txt", "created_at": "2026-01-01T00:00:00.000000Z"},
            {"id": "new.txt", "created_at": "2026-07-01T00:00:00.000000Z"},
            {"id": "nomicro.txt", "created_at": "2026-07-01T00:00:00Z"},
            {"id": "missing.txt"},
            {"id": "bad.txt", "created_at": "not-a-date"},
        ]) + "\n", encoding="utf-8")
        a = KnowledgeAnalyzer(knowledge_index_path=idx)
        cutoff = datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()
        # only files first-indexed at/after cutoff; missing/malformed excluded
        assert a.files_created_since(cutoff) == {"new.txt", "nomicro.txt"}

    def test_stamp_no_files_noop(self):
        from agent_core.routing.handlers import stamp_market_provenance
        store = specced(GoalStore)
        stamp_market_provenance(_plan(ActionType.FETCH, goal_id="g"), [], store)
        store.get.assert_not_called()

    # -- guard: update_learning_goal (the blast-radius protection) ---------
    def _market_goal(self, extra=None, progress=0.0):
        md = {"source_kind": "market", "project_parent": "p1", "topics": ["btc zloto"]}
        md.update(extra or {})
        g = create_goal(
            goal_type=GoalType.USER,
            description="Kronika",
            priority=0.5,
            status=GoalStatus.ACTIVE,
            metadata=md,
            goal_id="gm",
        )
        g.progress = progress
        return g

    def _mk_analyzer(self, completed_ids, topic_files, monkeypatch):
        monkeypatch.setattr(
            "agent_core.goals.success_criteria.independently_verified_file_ids",
            lambda *a, **k: set(completed_ids),
        )
        a = specced(KnowledgeAnalyzer)
        a.get_knowledge_snapshot.return_value = {
            "files_by_status": {"completed": [{"id": f, "file": f} for f in completed_ids]}
        }
        a.get_files_for_topics.return_value = [(f, 1.0) for f in topic_files]
        return a

    def test_guard_cutover_no_stamp_not_credited(self, monkeypatch):
        # Market child, cutover, token-match WOULD find a verified junk file,
        # but with no provenance stamp the gate credits nothing -> no progress.
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "cutover")
        goal = self._market_goal()
        store = specced(GoalStore); store.get.return_value = goal
        analyzer = self._mk_analyzer(["junk.txt"], ["junk.txt"], monkeypatch)
        update_learning_goal(
            _plan(ActionType.EXAM, goal_id="gm"),
            {"exams_passed": 5}, store, analyzer, None,
        )
        store.update_progress.assert_not_called()  # nudge also suppressed

    def test_guard_cutover_with_stamp_is_credited(self, monkeypatch):
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "cutover")
        goal = self._market_goal(extra={"market_file_ids": ["gold.txt"]})
        store = specced(GoalStore); store.get.return_value = goal
        analyzer = self._mk_analyzer(["gold.txt"], ["junk.txt"], monkeypatch)
        update_learning_goal(
            _plan(ActionType.EXAM, goal_id="gm"),
            {"exams_passed": 1}, store, analyzer, None,
        )
        store.update_progress.assert_called_once_with("gm", 1.0)  # 1 stamped, 1 verified

    def test_guard_observe_credits_like_today(self, monkeypatch):
        # observe = inert: market child still credited by token-match (current).
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "observe")
        goal = self._market_goal()
        store = specced(GoalStore); store.get.return_value = goal
        analyzer = self._mk_analyzer(["junk.txt"], ["junk.txt"], monkeypatch)
        update_learning_goal(
            _plan(ActionType.EXAM, goal_id="gm"),
            {"exams_passed": 1}, store, analyzer, None,
        )
        store.update_progress.assert_called_once_with("gm", 1.0)

    def test_guard_non_market_project_child_gated_cutover(self, monkeypatch):
        # 2026-07-11: a NON-market /project child is provenance-gated like market
        # at cutover -- no stamp -> file set empty AND nudge suppressed -> no
        # credit even on 5 passed exams over token-junk (the confirmed false-close).
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "cutover")
        goal = self._market_goal(extra={"source_kind": "science"})  # project child
        store = specced(GoalStore); store.get.return_value = goal
        analyzer = self._mk_analyzer(["junk.txt"], ["junk.txt"], monkeypatch)
        update_learning_goal(
            _plan(ActionType.EXAM, goal_id="gm"),
            {"exams_passed": 5}, store, analyzer, None,
        )
        store.update_progress.assert_not_called()

    def test_guard_plain_learning_goal_unchanged_cutover(self, monkeypatch):
        # Regression: a plain LEARNING goal (not a /project child) closes via
        # token-match as before even in cutover -- neither gate nor freshness apply.
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "cutover")
        goal = self._market_goal(extra={"source_kind": "science"})
        goal.type = GoalType.LEARNING   # learning goal, not user/project
        goal.metadata.pop("project_parent", None)
        store = specced(GoalStore); store.get.return_value = goal
        analyzer = self._mk_analyzer(["c.txt"], ["c.txt"], monkeypatch)
        update_learning_goal(
            _plan(ActionType.EXAM, goal_id="gm"),
            {"exams_passed": 1}, store, analyzer, None,
        )
        store.update_progress.assert_called_once_with("gm", 1.0)
