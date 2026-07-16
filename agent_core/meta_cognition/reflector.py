"""
Reflector - Outcome analysis and assumption checking.

Phase 1 (before exec): build_assumptions() - what do we assume?
Phase 2 (after exec): reflect() - did outcome match?
Periodic: analyze_patterns() - detect recurring wrong assumptions.

Kontrakt: docs/CONTRACTS.md - Kontrakt 9: Meta-Cognition
ADR-013: Rule-based, zero LLM, deterministic.
"""

import logging
import time
from typing import Any, Dict, List, Optional

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
)
from agent_core.meta_cognition.reflection_store import ReflectionStore
from agent_core.meta_cognition.confidence_tracker import ConfidenceTracker
from agent_core.planner.decision_filters import result_is_skipped

logger = logging.getLogger(__name__)

# Pattern detection thresholds
CONSECUTIVE_FAILURE_THRESHOLD = 3
WRONG_ASSUMPTION_THRESHOLD = 3
PATTERN_WINDOW = 20
STRUGGLING_CONFIDENCE = 0.3
STRUGGLING_MIN_ATTEMPTS = 3


class Reflector:
    """
    Core reflection engine.

    Builds assumptions from context, evaluates outcomes,
    detects patterns in failures.
    """

    def __init__(self, store: ReflectionStore, confidence: ConfidenceTracker):
        self._store = store
        self._confidence = confidence

    def build_assumptions(
        self,
        action_type: str,
        context: Dict[str, Any],
    ) -> List[Assumption]:
        """
        Infer assumptions for a plan BEFORE execution.

        Rules (deterministic, zero LLM):
        - LEARN -> TOPIC_LEARNABLE
        - EXAM -> EXAM_WILL_PASS
        - FETCH -> FETCH_RELEVANT
        - Any with retention > 0.7 -> RETENTION_STABLE
        - K8 strategy step -> STRATEGY_EFFECTIVE
        """
        assumptions = []

        topic = context.get("topic", "")
        action_params = context.get("action_params", {})

        if action_type == "learn":
            file_count = len(action_params.get("file_ids", []))
            assumptions.append(Assumption(
                assumption_type=AssumptionType.TOPIC_LEARNABLE,
                description=f"temat '{topic}' jest do nauczenia",
                basis=f"{file_count} plikow dostepnych" if file_count else
                      "pliki dostepne w input/",
            ))

        elif action_type == "exam":
            retention = context.get("retention_rate", 0.0)
            assumptions.append(Assumption(
                assumption_type=AssumptionType.EXAM_WILL_PASS,
                description=f"egzamin z '{topic}' zostanie zdany",
                basis=f"retention={retention:.2f}" if retention else
                      "brak danych o retention",
            ))

        elif action_type == "fetch":
            gaps = context.get("knowledge_gaps", [])
            assumptions.append(Assumption(
                assumption_type=AssumptionType.FETCH_RELEVANT,
                description="pobrane materialy beda przydatne",
                basis=f"{len(gaps)} luk w wiedzy" if gaps else
                      "eksploracja nowych tematow",
            ))

        elif action_type == "review":
            assumptions.append(Assumption(
                assumption_type=AssumptionType.TOPIC_LEARNABLE,
                description=f"powtorka '{topic}' poprawi retencje",
                basis="zaplanowana powtorka",
            ))

        # Retention stability assumption (if data available)
        retention = context.get("retention_rate")
        if retention is not None and retention > 0.7:
            assumptions.append(Assumption(
                assumption_type=AssumptionType.RETENTION_STABLE,
                description="retencja pozostanie stabilna",
                basis=f"retention={retention:.2f}",
            ))

        # K8 strategy assumption
        strategy_id = context.get("strategy_id")
        if strategy_id:
            template = context.get("template_name", "unknown")
            step_order = context.get("step_order", 0)
            assumptions.append(Assumption(
                assumption_type=AssumptionType.STRATEGY_EFFECTIVE,
                description=f"strategia '{template}' jest skuteczna",
                basis=f"krok {step_order}, strategy={strategy_id[:12]}",
            ))

        return assumptions

    def record_decision(
        self,
        plan_id: str,
        action_type: str,
        goal_id: Optional[str],
        topic: str,
        assumptions: List[Assumption],
        expected_success: bool,
        confidence_before: float,
        step_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Reflection:
        """
        Phase 1: Record decision with assumptions BEFORE execution.
        Creates Reflection and persists to store.
        """
        reflection = create_reflection(
            plan_id=plan_id,
            action_type=action_type,
            goal_id=goal_id,
            step_id=step_id,
            topic=topic,
            assumptions=assumptions,
            expected_success=expected_success,
            confidence_before=confidence_before,
            metadata=metadata,
        )
        self._store.append(reflection)
        logger.debug(
            f"[K9] Recorded decision: {action_type} "
            f"topic='{topic}' confidence={confidence_before:.2f} "
            f"assumptions={len(assumptions)}"
        )
        return reflection

    def reflect(
        self,
        plan_id: str,
        actual_success: bool,
        result: Dict[str, Any],
    ) -> Optional[Reflection]:
        """
        Phase 2: Compare outcome vs expectation AFTER execution.

        Updates the Reflection record with actual outcome,
        outcome match classification, confidence update, and lessons.
        """
        # A skipped attempt (declined before any work -- e.g. no fresh material
        # passed the filter) has no real outcome to evaluate. Leave its reflection
        # pending so it stays OUT of ConfidenceTracker (which only counts
        # is_reflected records): planner *rest* must not drag decision-confidence
        # down the way a genuine failure does. Same exclusion that self-analysis
        # sensors and the K7 failure breaker already apply to skips.
        if result_is_skipped(result):
            return None

        reflection = self._store.get_by_plan_id(plan_id)
        if reflection is None:
            logger.debug(f"[K9] No reflection found for plan {plan_id}")
            return None

        # Determine outcome match
        expected_score = 0.7 if reflection.expected_success else 0.3
        actual_score = result.get("score", result.get("exam_score"))
        if actual_score is None:
            actual_score = 0.8 if actual_success else 0.2

        outcome_match = determine_outcome_match(
            expected_score=expected_score,
            actual_score=actual_score,
            expected_success=reflection.expected_success,
            actual_success=actual_success,
        )

        # Set timestamp_finished before extracting lessons (duration_ms needs it)
        reflection.timestamp_finished = time.time()

        # Extract lessons
        lessons = self._extract_lessons(
            reflection, actual_success, result
        )

        # Updated confidence
        confidence_after = self._confidence.get_decision_confidence(
            reflection.action_type, reflection.topic
        )

        # Update reflection in store
        self._store.update(
            reflection.reflection_id,
            actual_success=actual_success,
            outcome_match=outcome_match,
            confidence_after=confidence_after,
            lessons=lessons,
            timestamp_finished=reflection.timestamp_finished,
        )

        logger.debug(
            f"[K9] Reflected: {reflection.action_type} "
            f"expected={reflection.expected_success} "
            f"actual={actual_success} "
            f"match={outcome_match.value} "
            f"lessons={len(lessons)}"
        )
        return reflection

    def analyze_patterns(self) -> Dict[str, Any]:
        """
        Periodic: detect recurring wrong assumptions.

        Scans last PATTERN_WINDOW reflected records for:
        - Consecutive failures per action_type
        - Recurring wrong assumption types
        - Topics with consistently low confidence
        """
        recent = self._store.get_reflected(limit=PATTERN_WINDOW)

        need_human = False
        need_human_reasons: List[str] = []
        wrong_assumptions: Dict[str, int] = {}
        consecutive_failures: Dict[str, int] = {}
        struggling_topics: List[str] = []

        # Count consecutive failures per action_type (most recent first)
        action_streak: Dict[str, int] = {}
        action_streak_broken: set = set()
        for r in recent:
            at = r.action_type
            if at in action_streak_broken:
                continue
            if r.actual_success:
                action_streak_broken.add(at)
            else:
                action_streak[at] = action_streak.get(at, 0) + 1

        for at, count in action_streak.items():
            if count >= CONSECUTIVE_FAILURE_THRESHOLD:
                consecutive_failures[at] = count
                need_human = True
                need_human_reasons.append(
                    NeedHumanReason.REPEATED_FAILURES.value
                )

        # Count wrong assumptions
        for r in recent:
            for lesson in r.lessons:
                if lesson.lesson_type == LessonType.WRONG_ASSUMPTION:
                    at_val = (
                        lesson.assumption_type.value
                        if lesson.assumption_type else "unknown"
                    )
                    wrong_assumptions[at_val] = (
                        wrong_assumptions.get(at_val, 0) + 1
                    )

        for at_val, count in wrong_assumptions.items():
            if count >= WRONG_ASSUMPTION_THRESHOLD:
                need_human = True
                if NeedHumanReason.ASSUMPTION_DRIFT.value not in need_human_reasons:
                    need_human_reasons.append(
                        NeedHumanReason.ASSUMPTION_DRIFT.value
                    )

        # Find struggling topics
        topic_map = self._confidence.get_topic_confidence_map()
        for topic, conf in topic_map.items():
            if conf < STRUGGLING_CONFIDENCE:
                topic_refs = self._store.get_by_topic(
                    topic, limit=STRUGGLING_MIN_ATTEMPTS
                )
                reflected_count = sum(
                    1 for r in topic_refs if r.is_reflected
                )
                if reflected_count >= STRUGGLING_MIN_ATTEMPTS:
                    struggling_topics.append(topic)
                    need_human = True
                    if NeedHumanReason.LOW_CONFIDENCE.value not in need_human_reasons:
                        need_human_reasons.append(
                            NeedHumanReason.LOW_CONFIDENCE.value
                        )

        return {
            "need_human": need_human,
            "need_human_reasons": need_human_reasons,
            "wrong_assumptions": wrong_assumptions,
            "struggling_topics": struggling_topics,
            "consecutive_failures": consecutive_failures,
        }

    def _extract_lessons(
        self,
        reflection: Reflection,
        actual_success: bool,
        result: Dict[str, Any],
    ) -> List[Lesson]:
        """
        Determine which assumptions were wrong.

        If actual_success != expected_success, each assumption
        is tagged as WRONG_ASSUMPTION.
        Special cases for exam scores and partial results.
        """
        lessons: List[Lesson] = []

        # Mismatch: expected success but failed
        if reflection.expected_success and not actual_success:
            for assumption in reflection.assumptions:
                lessons.append(Lesson(
                    lesson_type=LessonType.WRONG_ASSUMPTION,
                    assumption_type=assumption.assumption_type,
                    message=(
                        f"oczekiwano sukcesu ale porazka: "
                        f"{assumption.description}"
                    ),
                    severity=Severity.HIGH,
                ))

        # Unexpected success
        elif not reflection.expected_success and actual_success:
            lessons.append(Lesson(
                lesson_type=LessonType.UNEXPECTED_SUCCESS,
                assumption_type=None,
                message="niespodziewany sukces mimo niskiej pewnosci",
                severity=Severity.LOW,
            ))

        # Exam-specific: partial result (score exists but below threshold)
        exam_score = result.get("score", result.get("exam_score"))
        if (exam_score is not None
                and reflection.action_type == "exam"
                and 0.5 <= exam_score < 0.7
                and reflection.expected_success):
            lessons.append(Lesson(
                lesson_type=LessonType.PARTIAL_RESULT,
                assumption_type=AssumptionType.EXAM_WILL_PASS,
                message=f"egzamin zdany czesciowo (score={exam_score:.2f})",
                severity=Severity.MEDIUM,
            ))

        # Duration-based lesson (slow execution)
        duration = reflection.duration_ms
        if duration is not None and duration > 300_000:  # > 5 min
            lessons.append(Lesson(
                lesson_type=LessonType.SLOW_EXECUTION,
                assumption_type=None,
                message=f"dlugi czas wykonania ({duration/1000:.0f}s)",
                severity=Severity.LOW,
            ))

        return lessons
