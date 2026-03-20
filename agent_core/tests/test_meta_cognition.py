"""
Tests for K9 Meta-Cognition / Self-Reflection.

Tests cover:
- Reflection model (dataclasses, serialization, properties, enums)
- OutcomeMatch threshold logic
- ReflectionStore (JSONL persistence, queries, bounded cache)
- ConfidenceTracker (exponential decay, per-action, per-topic, combined)
- Reflector (build assumptions, record, reflect, analyze patterns, lessons)
- MetaCognition facade
- PlannerCore integration (record_decision before exec, reflect after exec)
"""

import json
import time
from pathlib import Path

import pytest

from agent_core.meta_cognition.reflection_model import (
    Assumption,
    AssumptionType,
    Lesson,
    LessonType,
    NeedHumanReason,
    OutcomeMatch,
    Reflection,
    Severity,
    create_reflection,
    determine_outcome_match,
    MATCH_THRESHOLD,
    PARTIAL_THRESHOLD,
)
from agent_core.meta_cognition.reflection_store import ReflectionStore, MAX_RECORDS
from agent_core.meta_cognition.confidence_tracker import (
    ConfidenceTracker,
    DEFAULT_CONFIDENCE,
    DECAY_WEIGHT,
    MIN_SAMPLES,
    LOW_CONFIDENCE_THRESHOLD,
)
from agent_core.meta_cognition.reflector import (
    Reflector,
    CONSECUTIVE_FAILURE_THRESHOLD,
    WRONG_ASSUMPTION_THRESHOLD,
    PATTERN_WINDOW,
)
from agent_core.meta_cognition import MetaCognition


# ===================== Reflection Model =====================


class TestAssumption:
    def test_create_assumption(self):
        a = Assumption(
            assumption_type=AssumptionType.TOPIC_LEARNABLE,
            description="temat jest do nauczenia",
            basis="5 plikow dostepnych",
        )
        assert a.assumption_type == AssumptionType.TOPIC_LEARNABLE
        assert "nauczenia" in a.description

    def test_assumption_serialization(self):
        a = Assumption(
            assumption_type=AssumptionType.EXAM_WILL_PASS,
            description="egzamin zostanie zdany",
            basis="retention=0.85",
        )
        d = a.to_dict()
        restored = Assumption.from_dict(d)
        assert restored.assumption_type == AssumptionType.EXAM_WILL_PASS
        assert restored.description == a.description
        assert restored.basis == a.basis

    def test_assumption_type_values(self):
        assert len(AssumptionType) == 5
        assert AssumptionType.STRATEGY_EFFECTIVE.value == "strategy_effective"


class TestLesson:
    def test_create_lesson(self):
        l = Lesson(
            lesson_type=LessonType.WRONG_ASSUMPTION,
            assumption_type=AssumptionType.EXAM_WILL_PASS,
            message="oczekiwano sukcesu ale porazka",
            severity=Severity.HIGH,
        )
        assert l.lesson_type == LessonType.WRONG_ASSUMPTION
        assert l.severity == Severity.HIGH

    def test_lesson_serialization(self):
        l = Lesson(
            lesson_type=LessonType.PARTIAL_RESULT,
            assumption_type=AssumptionType.EXAM_WILL_PASS,
            message="egzamin czesciowy",
            severity=Severity.MEDIUM,
        )
        d = l.to_dict()
        restored = Lesson.from_dict(d)
        assert restored.lesson_type == LessonType.PARTIAL_RESULT
        assert restored.assumption_type == AssumptionType.EXAM_WILL_PASS
        assert restored.message == l.message

    def test_lesson_none_assumption_type(self):
        l = Lesson(
            lesson_type=LessonType.UNEXPECTED_SUCCESS,
            assumption_type=None,
            message="niespodziewany sukces",
            severity=Severity.LOW,
        )
        d = l.to_dict()
        assert d["assumption_type"] is None
        restored = Lesson.from_dict(d)
        assert restored.assumption_type is None


class TestReflection:
    def test_create_reflection(self):
        r = create_reflection(
            plan_id="plan-1",
            action_type="learn",
            topic="fizyka",
        )
        assert r.reflection_id.startswith("refl-")
        assert r.plan_id == "plan-1"
        assert r.action_type == "learn"
        assert r.topic == "fizyka"
        assert r.expected_success is True
        assert r.confidence_before == 0.5
        assert r.timestamp_started > 0
        assert r.is_reflected is False

    def test_reflection_with_step_id(self):
        r = create_reflection(
            plan_id="plan-1",
            action_type="exam",
            step_id="step-abc",
            goal_id="goal-1",
        )
        assert r.step_id == "step-abc"
        assert r.goal_id == "goal-1"

    def test_duration_ms_none_before_reflect(self):
        r = create_reflection(plan_id="p1", action_type="learn")
        assert r.duration_ms is None

    def test_duration_ms_after_reflect(self):
        r = create_reflection(plan_id="p1", action_type="learn")
        r.timestamp_started = 100.0
        r.timestamp_finished = 102.5
        assert r.duration_ms == 2500.0

    def test_is_reflected_false_initially(self):
        r = create_reflection(plan_id="p1", action_type="learn")
        assert r.is_reflected is False

    def test_is_reflected_true_after_outcome(self):
        r = create_reflection(plan_id="p1", action_type="learn")
        r.actual_success = True
        assert r.is_reflected is True

    def test_is_reflected_true_even_on_failure(self):
        r = create_reflection(plan_id="p1", action_type="learn")
        r.actual_success = False
        assert r.is_reflected is True

    def test_reflection_serialization_full(self):
        r = create_reflection(
            plan_id="plan-2",
            action_type="exam",
            goal_id="goal-42",
            step_id="step-xyz",
            topic="matematyka",
            assumptions=[
                Assumption(AssumptionType.EXAM_WILL_PASS, "zdane", "ret=0.9")
            ],
            expected_success=True,
            confidence_before=0.72,
            metadata={"source": "test"},
        )
        r.actual_success = True
        r.outcome_match = OutcomeMatch.MATCH
        r.confidence_after = 0.78
        r.lessons = [
            Lesson(LessonType.UNEXPECTED_SUCCESS, None, "ok", Severity.LOW)
        ]
        r.timestamp_finished = time.time()

        d = r.to_dict()
        restored = Reflection.from_dict(d)
        assert restored.plan_id == "plan-2"
        assert restored.step_id == "step-xyz"
        assert restored.topic == "matematyka"
        assert restored.outcome_match == OutcomeMatch.MATCH
        assert len(restored.assumptions) == 1
        assert len(restored.lessons) == 1
        assert restored.confidence_after == 0.78
        assert restored.metadata == {"source": "test"}


class TestOutcomeMatch:
    def test_match_within_threshold(self):
        result = determine_outcome_match(0.7, 0.72, True, True)
        assert result == OutcomeMatch.MATCH

    def test_match_exact(self):
        result = determine_outcome_match(0.8, 0.8, True, True)
        assert result == OutcomeMatch.MATCH

    def test_partial_delta(self):
        result = determine_outcome_match(0.7, 0.45, True, False)
        assert result == OutcomeMatch.PARTIAL

    def test_mismatch_large_delta(self):
        result = determine_outcome_match(0.7, 0.2, True, False)
        assert result == OutcomeMatch.MISMATCH

    def test_fallback_bool_match(self):
        result = determine_outcome_match(None, None, True, True)
        assert result == OutcomeMatch.MATCH

    def test_fallback_bool_mismatch(self):
        result = determine_outcome_match(None, None, True, False)
        assert result == OutcomeMatch.MISMATCH

    def test_boundary_match_partial(self):
        # delta = 0.15 -> MATCH (<=)
        result = determine_outcome_match(0.7, 0.55, True, True)
        assert result == OutcomeMatch.MATCH

    def test_boundary_partial_mismatch(self):
        # delta = 0.4 -> PARTIAL (<=)
        result = determine_outcome_match(0.7, 0.3, True, False)
        assert result == OutcomeMatch.PARTIAL


# ===================== ReflectionStore =====================


class TestReflectionStore:
    def test_append_and_count(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        r = create_reflection(plan_id="p1", action_type="learn")
        store.append(r)
        assert store.count() == 1

    def test_get_by_plan_id(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        r = create_reflection(plan_id="plan-abc", action_type="learn")
        store.append(r)
        found = store.get_by_plan_id("plan-abc")
        assert found is not None
        assert found.reflection_id == r.reflection_id

    def test_get_by_plan_id_not_found(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        assert store.get_by_plan_id("nonexistent") is None

    def test_get_by_action_type(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        for at in ["learn", "learn", "exam", "learn"]:
            store.append(create_reflection(plan_id=f"p-{at}", action_type=at))
        result = store.get_by_action_type("learn")
        assert len(result) == 3

    def test_get_by_topic(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        store.append(create_reflection(plan_id="p1", action_type="learn", topic="fizyka"))
        store.append(create_reflection(plan_id="p2", action_type="learn", topic="chemia"))
        store.append(create_reflection(plan_id="p3", action_type="exam", topic="fizyka"))
        result = store.get_by_topic("fizyka")
        assert len(result) == 2

    def test_get_by_topic_case_insensitive(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        store.append(create_reflection(plan_id="p1", action_type="learn", topic="Fizyka"))
        result = store.get_by_topic("fizyka")
        assert len(result) == 1

    def test_get_recent(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        for i in range(5):
            store.append(create_reflection(plan_id=f"p{i}", action_type="learn"))
        result = store.get_recent(limit=3)
        assert len(result) == 3
        # Newest first
        assert result[0].plan_id == "p4"

    def test_get_reflected(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        r1 = create_reflection(plan_id="p1", action_type="learn")
        r1.actual_success = True
        store.append(r1)
        r2 = create_reflection(plan_id="p2", action_type="learn")
        store.append(r2)
        result = store.get_reflected()
        assert len(result) == 1
        assert result[0].plan_id == "p1"

    def test_update_reflection(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        r = create_reflection(plan_id="p1", action_type="learn")
        store.append(r)
        updated = store.update(
            r.reflection_id,
            actual_success=True,
            outcome_match=OutcomeMatch.MATCH,
        )
        assert updated is True
        found = store.get_by_plan_id("p1")
        assert found.actual_success is True
        assert found.outcome_match == OutcomeMatch.MATCH

    def test_update_nonexistent(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        assert store.update("nonexistent", actual_success=True) is False

    def test_persistence_across_instances(self, tmp_path):
        path = tmp_path / "r.jsonl"
        store1 = ReflectionStore(path=path)
        store1.append(create_reflection(plan_id="p1", action_type="learn", topic="bio"))
        store1.append(create_reflection(plan_id="p2", action_type="exam", topic="bio"))

        store2 = ReflectionStore(path=path)
        assert store2.count() == 2
        assert store2.get_by_plan_id("p1") is not None

    def test_bounded_max_records(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        for i in range(MAX_RECORDS + 10):
            store.append(create_reflection(plan_id=f"p{i}", action_type="learn"))
        assert store.count() == MAX_RECORDS
        # Oldest trimmed
        assert store.get_by_plan_id("p0") is None
        assert store.get_by_plan_id(f"p{MAX_RECORDS + 9}") is not None

    def test_corrupt_record_skipped(self, tmp_path):
        path = tmp_path / "r.jsonl"
        with open(path, "w") as f:
            f.write("not json\n")
            r = create_reflection(plan_id="p1", action_type="learn")
            f.write(json.dumps(r.to_dict()) + "\n")
        store = ReflectionStore(path=path)
        assert store.count() == 1


# ===================== ConfidenceTracker =====================


def _make_reflected(store, action_type, topic, success, n=1):
    """Helper: add N reflected records to store."""
    for _ in range(n):
        r = create_reflection(plan_id=f"p-{time.time()}", action_type=action_type, topic=topic)
        r.actual_success = success
        store.append(r)


class TestConfidenceTracker:
    def test_default_confidence_no_data(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        ct = ConfidenceTracker(store=store)
        assert ct.get_action_confidence("learn") == DEFAULT_CONFIDENCE

    def test_default_confidence_below_min_samples(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        _make_reflected(store, "learn", "", True, n=2)
        ct = ConfidenceTracker(store=store)
        assert ct.get_action_confidence("learn") == DEFAULT_CONFIDENCE

    def test_all_success(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        _make_reflected(store, "learn", "", True, n=5)
        ct = ConfidenceTracker(store=store)
        conf = ct.get_action_confidence("learn")
        assert conf > 0.95  # All success -> near 1.0

    def test_all_failure(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        _make_reflected(store, "learn", "", False, n=5)
        ct = ConfidenceTracker(store=store)
        conf = ct.get_action_confidence("learn")
        assert conf < 0.05  # All failure -> near 0.0

    def test_mixed_results(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        _make_reflected(store, "learn", "", True, n=3)
        _make_reflected(store, "learn", "", False, n=3)
        ct = ConfidenceTracker(store=store)
        conf = ct.get_action_confidence("learn")
        # Recent failures weighted more -> below 0.5
        assert 0.1 < conf < 0.5

    def test_recent_bias(self, tmp_path):
        """Recent success after early failures should raise confidence."""
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        _make_reflected(store, "learn", "", False, n=3)
        _make_reflected(store, "learn", "", True, n=3)
        ct = ConfidenceTracker(store=store)
        conf = ct.get_action_confidence("learn")
        # Recent success -> above 0.5
        assert conf > 0.5

    def test_topic_confidence_empty_topic(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        ct = ConfidenceTracker(store=store)
        assert ct.get_topic_confidence("") == DEFAULT_CONFIDENCE

    def test_topic_confidence_with_data(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        _make_reflected(store, "learn", "fizyka", True, n=5)
        ct = ConfidenceTracker(store=store)
        conf = ct.get_topic_confidence("fizyka")
        assert conf > 0.9

    def test_combined_confidence(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        _make_reflected(store, "learn", "fizyka", True, n=5)
        ct = ConfidenceTracker(store=store)
        combined = ct.get_decision_confidence("learn", "fizyka")
        action = ct.get_action_confidence("learn")
        topic = ct.get_topic_confidence("fizyka")
        expected = 0.6 * action + 0.4 * topic
        assert abs(combined - expected) < 0.01

    def test_combined_no_topic(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        _make_reflected(store, "learn", "", True, n=5)
        ct = ConfidenceTracker(store=store)
        combined = ct.get_decision_confidence("learn", "")
        action = ct.get_action_confidence("learn")
        assert combined == action

    def test_is_low_confidence(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        _make_reflected(store, "learn", "", False, n=5)
        ct = ConfidenceTracker(store=store)
        assert ct.is_low_confidence("learn") is True

    def test_confidence_map(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        _make_reflected(store, "learn", "", True, n=3)
        _make_reflected(store, "exam", "", False, n=3)
        ct = ConfidenceTracker(store=store)
        cmap = ct.get_confidence_map()
        assert "learn" in cmap
        assert "exam" in cmap

    def test_topic_confidence_map(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        _make_reflected(store, "learn", "fizyka", True, n=3)
        _make_reflected(store, "learn", "chemia", False, n=3)
        ct = ConfidenceTracker(store=store)
        tmap = ct.get_topic_confidence_map()
        assert "fizyka" in tmap
        assert "chemia" in tmap


# ===================== Reflector =====================


class TestReflectorBuildAssumptions:
    def _make_reflector(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        ct = ConfidenceTracker(store=store)
        return Reflector(store=store, confidence=ct), store

    def test_learn_assumptions(self, tmp_path):
        ref, _ = self._make_reflector(tmp_path)
        assumptions = ref.build_assumptions("learn", {
            "topic": "fizyka",
            "action_params": {"file_ids": ["f1", "f2"]},
        })
        assert len(assumptions) >= 1
        types = [a.assumption_type for a in assumptions]
        assert AssumptionType.TOPIC_LEARNABLE in types

    def test_exam_assumptions(self, tmp_path):
        ref, _ = self._make_reflector(tmp_path)
        assumptions = ref.build_assumptions("exam", {
            "topic": "matematyka",
            "retention_rate": 0.85,
        })
        types = [a.assumption_type for a in assumptions]
        assert AssumptionType.EXAM_WILL_PASS in types
        assert AssumptionType.RETENTION_STABLE in types

    def test_fetch_assumptions(self, tmp_path):
        ref, _ = self._make_reflector(tmp_path)
        assumptions = ref.build_assumptions("fetch", {
            "knowledge_gaps": ["fizyka kwantowa"],
        })
        types = [a.assumption_type for a in assumptions]
        assert AssumptionType.FETCH_RELEVANT in types

    def test_strategy_assumption(self, tmp_path):
        ref, _ = self._make_reflector(tmp_path)
        assumptions = ref.build_assumptions("learn", {
            "topic": "bio",
            "strategy_id": "strat-abc123456789",
            "template_name": "learn_topic",
            "step_order": 1,
        })
        types = [a.assumption_type for a in assumptions]
        assert AssumptionType.STRATEGY_EFFECTIVE in types

    def test_review_assumptions(self, tmp_path):
        ref, _ = self._make_reflector(tmp_path)
        assumptions = ref.build_assumptions("review", {"topic": "fizyka"})
        types = [a.assumption_type for a in assumptions]
        assert AssumptionType.TOPIC_LEARNABLE in types


class TestReflectorRecordAndReflect:
    def _make_reflector(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        ct = ConfidenceTracker(store=store)
        return Reflector(store=store, confidence=ct), store

    def test_record_decision(self, tmp_path):
        ref, store = self._make_reflector(tmp_path)
        assumptions = [Assumption(AssumptionType.TOPIC_LEARNABLE, "test", "basis")]
        r = ref.record_decision(
            plan_id="plan-1",
            action_type="learn",
            goal_id="g1",
            topic="fizyka",
            assumptions=assumptions,
            expected_success=True,
            confidence_before=0.6,
        )
        assert store.count() == 1
        assert r.plan_id == "plan-1"
        assert r.confidence_before == 0.6

    def test_reflect_success(self, tmp_path):
        ref, store = self._make_reflector(tmp_path)
        ref.record_decision("plan-1", "learn", None, "fizyka", [], True, 0.6)
        result = ref.reflect("plan-1", True, {"score": 0.8})
        assert result is not None
        found = store.get_by_plan_id("plan-1")
        assert found.actual_success is True
        assert found.outcome_match in (OutcomeMatch.MATCH, OutcomeMatch.PARTIAL)

    def test_reflect_failure_with_lessons(self, tmp_path):
        ref, store = self._make_reflector(tmp_path)
        assumptions = [Assumption(AssumptionType.EXAM_WILL_PASS, "zdane", "ret=0.9")]
        ref.record_decision("plan-2", "exam", None, "fizyka", assumptions, True, 0.7)
        ref.reflect("plan-2", False, {"score": 0.3})
        found = store.get_by_plan_id("plan-2")
        assert found.actual_success is False
        assert len(found.lessons) >= 1
        assert found.lessons[0].lesson_type == LessonType.WRONG_ASSUMPTION

    def test_reflect_unexpected_success(self, tmp_path):
        ref, store = self._make_reflector(tmp_path)
        ref.record_decision("plan-3", "learn", None, "fizyka", [], False, 0.2)
        ref.reflect("plan-3", True, {})
        found = store.get_by_plan_id("plan-3")
        assert any(
            l.lesson_type == LessonType.UNEXPECTED_SUCCESS
            for l in found.lessons
        )

    def test_reflect_partial_exam(self, tmp_path):
        ref, store = self._make_reflector(tmp_path)
        assumptions = [Assumption(AssumptionType.EXAM_WILL_PASS, "zdane", "ret=0.8")]
        ref.record_decision("plan-4", "exam", None, "fizyka", assumptions, True, 0.6)
        ref.reflect("plan-4", True, {"score": 0.55})
        found = store.get_by_plan_id("plan-4")
        partial = [l for l in found.lessons if l.lesson_type == LessonType.PARTIAL_RESULT]
        assert len(partial) == 1
        assert partial[0].severity == Severity.MEDIUM

    def test_reflect_nonexistent_plan(self, tmp_path):
        ref, _ = self._make_reflector(tmp_path)
        result = ref.reflect("no-such-plan", True, {})
        assert result is None

    def test_reflect_slow_execution(self, tmp_path):
        ref, store = self._make_reflector(tmp_path)
        ref.record_decision("plan-5", "learn", None, "fizyka", [], True, 0.5)
        # Manually set early timestamp to simulate slow execution
        r = store.get_by_plan_id("plan-5")
        r.timestamp_started = time.time() - 600  # 10 minutes ago
        ref.reflect("plan-5", True, {})
        found = store.get_by_plan_id("plan-5")
        slow = [l for l in found.lessons if l.lesson_type == LessonType.SLOW_EXECUTION]
        assert len(slow) == 1


class TestReflectorAnalyzePatterns:
    def _make_reflector(self, tmp_path):
        store = ReflectionStore(path=tmp_path / "r.jsonl")
        ct = ConfidenceTracker(store=store)
        return Reflector(store=store, confidence=ct), store

    def test_no_patterns_clean_history(self, tmp_path):
        ref, store = self._make_reflector(tmp_path)
        for i in range(5):
            r = create_reflection(plan_id=f"p{i}", action_type="learn", topic="fizyka")
            r.actual_success = True
            r.lessons = []
            store.append(r)
        patterns = ref.analyze_patterns()
        assert patterns["need_human"] is False
        assert len(patterns["consecutive_failures"]) == 0

    def test_consecutive_failures_trigger(self, tmp_path):
        ref, store = self._make_reflector(tmp_path)
        for i in range(CONSECUTIVE_FAILURE_THRESHOLD):
            r = create_reflection(plan_id=f"p{i}", action_type="learn")
            r.actual_success = False
            r.lessons = []
            store.append(r)
        patterns = ref.analyze_patterns()
        assert patterns["need_human"] is True
        assert "learn" in patterns["consecutive_failures"]
        assert NeedHumanReason.REPEATED_FAILURES.value in patterns["need_human_reasons"]

    def test_consecutive_failures_broken_by_success(self, tmp_path):
        ref, store = self._make_reflector(tmp_path)
        # 2 failures then 1 success -> streak broken
        for i in range(2):
            r = create_reflection(plan_id=f"p{i}", action_type="learn")
            r.actual_success = False
            r.lessons = []
            store.append(r)
        r = create_reflection(plan_id="p-ok", action_type="learn")
        r.actual_success = True
        r.lessons = []
        store.append(r)
        patterns = ref.analyze_patterns()
        assert patterns["need_human"] is False

    def test_wrong_assumptions_trigger(self, tmp_path):
        ref, store = self._make_reflector(tmp_path)
        for i in range(WRONG_ASSUMPTION_THRESHOLD):
            r = create_reflection(plan_id=f"p{i}", action_type="learn")
            r.actual_success = True
            r.lessons = [Lesson(
                LessonType.WRONG_ASSUMPTION,
                AssumptionType.TOPIC_LEARNABLE,
                "wrong",
                Severity.HIGH,
            )]
            store.append(r)
        patterns = ref.analyze_patterns()
        assert patterns["need_human"] is True
        assert NeedHumanReason.ASSUMPTION_DRIFT.value in patterns["need_human_reasons"]
        assert "topic_learnable" in patterns["wrong_assumptions"]


# ===================== MetaCognition Facade =====================


class TestMetaCognitionFacade:
    def test_record_and_reflect(self, tmp_path):
        mc = MetaCognition(reflections_path=tmp_path / "r.jsonl")
        mc.record_decision(
            plan_id="plan-1",
            action_type="learn",
            topic="fizyka",
            context={"topic": "fizyka"},
        )
        mc.reflect("plan-1", True, {"score": 0.8})
        status = mc.get_status()
        assert status["total_reflections"] == 1
        assert status["reflected_count"] == 1

    def test_get_decision_confidence_default(self, tmp_path):
        mc = MetaCognition(reflections_path=tmp_path / "r.jsonl")
        conf = mc.get_decision_confidence("learn", "fizyka")
        assert conf == DEFAULT_CONFIDENCE

    def test_need_human_false_initially(self, tmp_path):
        mc = MetaCognition(reflections_path=tmp_path / "r.jsonl")
        assert mc.need_human() is False

    def test_analyze_patterns_empty(self, tmp_path):
        mc = MetaCognition(reflections_path=tmp_path / "r.jsonl")
        patterns = mc.analyze_patterns()
        assert patterns["need_human"] is False

    def test_full_workflow(self, tmp_path):
        mc = MetaCognition(reflections_path=tmp_path / "r.jsonl")
        # Record + reflect 5 successes
        for i in range(5):
            mc.record_decision(f"plan-{i}", "learn", topic="fizyka",
                               context={"topic": "fizyka"})
            mc.reflect(f"plan-{i}", True, {"score": 0.8})
        conf = mc.get_decision_confidence("learn", "fizyka")
        assert conf > 0.8
        assert mc.need_human() is False

    def test_get_status_structure(self, tmp_path):
        mc = MetaCognition(reflections_path=tmp_path / "r.jsonl")
        status = mc.get_status()
        assert "total_reflections" in status
        assert "reflected_count" in status
        assert "confidence_by_action" in status
        assert "confidence_by_topic" in status
        assert "need_human" in status
        assert "need_human_reasons" in status
        assert "consecutive_failures" in status
        assert "struggling_topics" in status
        assert "wrong_assumptions" in status


# ===================== PlannerCore Integration =====================


class TestPlannerCoreIntegration:
    """Test that planner_core.py accepts meta_cognition wiring."""

    def test_set_meta_cognition(self):
        from agent_core.planner.planner_core import PlannerCore
        planner = PlannerCore()
        mc = MetaCognition()
        planner.set_meta_cognition(mc)
        assert planner._meta_cognition is mc

    def test_meta_cognition_none_by_default(self):
        from agent_core.planner.planner_core import PlannerCore
        planner = PlannerCore()
        assert planner._meta_cognition is None


# ===================== SharedContext =====================


class TestSharedContextK9:
    def test_meta_cognition_field_exists(self):
        from agent_core.registry.shared_context import SharedContext
        ctx = SharedContext()
        assert hasattr(ctx, "meta_cognition")
        assert ctx.meta_cognition is None
