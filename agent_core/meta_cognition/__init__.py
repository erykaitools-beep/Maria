"""
K9 Meta-Cognition for M.A.R.I.A.

Self-reflection: track assumptions, evaluate outcomes, adjust confidence.
"The system should know what it doesn't know."

Pipeline (in PlannerCore._finalize_plan):
    1. BEFORE exec: meta_cognition.record_decision(plan_id, action_type, ...)
    2. AFTER exec:  meta_cognition.reflect(plan_id, success, result)
    3. BEFORE next: meta_cognition.get_decision_confidence(action, topic)
    4. Periodic:    meta_cognition.analyze_patterns()

Usage:
    from agent_core.meta_cognition import MetaCognition

    mc = MetaCognition()
    mc.record_decision("plan-1", "learn", topic="fizyka", context={...})
    mc.reflect("plan-1", success=True, result={"chunks_learned": 3})
    conf = mc.get_decision_confidence("learn", "fizyka")

Kontrakt: docs/CONTRACTS.md - Kontrakt 9: Meta-Cognition
ADR-013: Rule-based, zero LLM, deterministic, testable.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from agent_core.meta_cognition.reflection_store import ReflectionStore
from agent_core.meta_cognition.confidence_tracker import ConfidenceTracker
from agent_core.meta_cognition.reflector import Reflector

logger = logging.getLogger(__name__)


class MetaCognition:
    """
    K9 Meta-Cognition facade.

    6 public methods:
    1. record_decision() - Phase 1: before execution
    2. reflect() - Phase 2: after execution
    3. get_decision_confidence() - inform planner
    4. analyze_patterns() - periodic pattern detection
    5. need_human() - check if human help needed
    6. get_status() - REPL/Web UI
    """

    def __init__(self, reflections_path: Optional[Path] = None):
        self._store = ReflectionStore(path=reflections_path)
        self._confidence = ConfidenceTracker(store=self._store)
        self._reflector = Reflector(
            store=self._store, confidence=self._confidence
        )

    def record_decision(
        self,
        plan_id: str,
        action_type: str,
        goal_id: Optional[str] = None,
        topic: str = "",
        context: Optional[Dict[str, Any]] = None,
        step_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Phase 1: Record assumptions BEFORE execution.

        Called from PlannerCore._finalize_plan() before executor.execute().
        Builds assumptions from context automatically.
        """
        ctx = context or {}
        assumptions = self._reflector.build_assumptions(action_type, ctx)
        confidence = self._confidence.get_decision_confidence(
            action_type, topic
        )
        # Expect success unless very low confidence
        expected = confidence >= 0.4

        self._reflector.record_decision(
            plan_id=plan_id,
            action_type=action_type,
            goal_id=goal_id,
            topic=topic,
            assumptions=assumptions,
            expected_success=expected,
            confidence_before=confidence,
            step_id=step_id,
            metadata=metadata,
        )

    def reflect(
        self,
        plan_id: str,
        success: bool,
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Phase 2: Compare outcome vs expectation AFTER execution.

        Called from PlannerCore._finalize_plan() after executor.execute().
        """
        self._reflector.reflect(plan_id, success, result or {})

    def get_decision_confidence(
        self,
        action_type: str,
        topic: str = "",
    ) -> float:
        """
        Get confidence score for a potential decision.

        Returns 0.0 to 1.0.
        """
        return self._confidence.get_decision_confidence(action_type, topic)

    def analyze_patterns(self) -> Dict[str, Any]:
        """
        Periodic: detect wrong assumptions and recurring failures.
        """
        return self._reflector.analyze_patterns()

    def need_human(self) -> bool:
        """
        Check if meta-cognition recommends human intervention.

        Shortcut for analyze_patterns()["need_human"].
        """
        patterns = self._reflector.analyze_patterns()
        return patterns.get("need_human", False)

    def needs_human(self) -> bool:
        """Alias for need_human().

        Call sites (homeostasis core, planner_core, limitation_reporter) and the
        Telegram notifier all use the plural spelling. Without this alias their
        hasattr() guards resolved False and the K9 "I need a human" signal was
        silently dead.
        """
        return self.need_human()

    def get_status(self) -> Dict[str, Any]:
        """
        Status dict for REPL / Web UI.
        """
        patterns = self._reflector.analyze_patterns()
        return {
            "total_reflections": self._store.count(),
            "reflected_count": len(self._store.get_reflected(limit=1000)),
            "confidence_by_action": self._confidence.get_confidence_map(),
            "confidence_by_topic": self._confidence.get_topic_confidence_map(),
            "need_human": patterns.get("need_human", False),
            "need_human_reasons": patterns.get("need_human_reasons", []),
            "consecutive_failures": patterns.get("consecutive_failures", {}),
            "struggling_topics": patterns.get("struggling_topics", []),
            "wrong_assumptions": patterns.get("wrong_assumptions", {}),
        }
