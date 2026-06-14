"""Detects developmental contradictions, stagnation, repetition, and unrealized potential.

Rule-based tension detection from strategic context.
Zero LLM - deterministic, testable.

Tensions detected:
- REPETITION: high noop ratio, same actions repeated
- STAGNATION: no learning progress, zero velocity
- UNDER_EXPLORATION: high coverage but no new directions
- EPISTEMIC_GAP: known weak topics not addressed
- OVER_RESTRICTION: too many actions blocked by K7/safety
- MISALIGNMENT: goals exist but no progress made
- FRAGILE_COORDINATION: high failure rate in actions
"""

import logging
from typing import Any, Dict, List

from agent_core.creative.creative_model import (
    DetectedTension, TensionCategory,
)
from agent_core.planner.decision_filters import IDLE_ACTION_TYPES

logger = logging.getLogger(__name__)

# Thresholds
NOOP_RATIO_THRESHOLD = 0.7       # >70% NOOPs = repetition
STAGNATION_VELOCITY = 0.01       # Near-zero learning velocity
HIGH_COVERAGE_THRESHOLD = 0.9    # >90% coverage = need new directions
FAILURE_RATIO_THRESHOLD = 0.3    # >30% failed actions = fragile coordination
STALE_GOAL_THRESHOLD = 2         # 2+ stale goals = misalignment


class TensionDetector:
    """Detect developmental tensions from strategic context."""

    def detect(self, context: Dict[str, Any]) -> List[DetectedTension]:
        """
        Analyze strategic context and return detected tensions.

        Args:
            context: Output from StrategicContext.build()

        Returns:
            List of DetectedTension, sorted by severity (highest first).
        """
        tensions: List[DetectedTension] = []

        action_pattern = context.get("action_pattern", {})
        learning_state = context.get("learning_state", {})
        goal_state = context.get("goal_state", {})
        period_hours = context.get("period_hours", 24)
        window = f"{period_hours}h"

        # 1. REPETITION: mostly doing nothing
        noop_ratio = action_pattern.get("noop_ratio", 0)
        total_actions = action_pattern.get("total", 0)
        if noop_ratio > NOOP_RATIO_THRESHOLD and total_actions > 10:
            tensions.append(DetectedTension.create(
                category=TensionCategory.REPETITION,
                description=(
                    f"System jest w petli NOOP ({noop_ratio:.0%} akcji to 'nic do zrobienia'). "
                    f"Z {total_actions} cykli planera, wiekszosc nie prowadzi do zadnej pracy."
                ),
                severity=min(noop_ratio, 0.9),
                evidence_refs=[f"planner_decisions:{total_actions}_actions"],
                pattern_window=window,
            ))

        # 2. STAGNATION: no learning progress
        velocity = learning_state.get("learning_velocity")
        coverage = learning_state.get("coverage", 0)
        if velocity is not None and velocity <= STAGNATION_VELOCITY and coverage < 1.0:
            tensions.append(DetectedTension.create(
                category=TensionCategory.STAGNATION,
                description=(
                    f"Predkosc nauki wynosi {velocity:.3f} - praktycznie zero. "
                    f"Pokrycie wiedzy: {coverage:.0%}. System nie robi postepu."
                ),
                severity=0.7,
                evidence_refs=["evaluation_reports:learning_velocity"],
                pattern_window=window,
            ))

        # 3. UNDER_EXPLORATION: everything learned, nothing new
        if coverage >= HIGH_COVERAGE_THRESHOLD:
            recent_meta_goals = context.get("recent_meta_goals", [])
            dist = action_pattern.get("distribution", {})
            fetch_count = dist.get("fetch", 0)
            learn_count = dist.get("learn", 0)

            if learn_count == 0 and not recent_meta_goals:
                tensions.append(DetectedTension.create(
                    category=TensionCategory.UNDER_EXPLORATION,
                    description=(
                        f"Pokrycie wiedzy {coverage:.0%} - prawie wszystko przyswojone. "
                        f"Brak nowych kierunkow eksploracji. System potrzebuje nowych celow "
                        f"lub materialow wykraczajacych poza dotychczasowe tematy."
                    ),
                    severity=0.8,
                    evidence_refs=[
                        f"knowledge_index:coverage={coverage:.2f}",
                        f"planner_decisions:learn_count={learn_count}",
                    ],
                    pattern_window=window,
                ))

        # 4. EPISTEMIC_GAP: low retention on known topics
        retention = learning_state.get("retention_rate")
        if retention is not None and retention < 0.7:
            tensions.append(DetectedTension.create(
                category=TensionCategory.EPISTEMIC_GAP,
                description=(
                    f"Retencja wiedzy {retention:.0%} - ponizej akceptowalnego poziomu. "
                    f"Przyswojony material nie jest utrzymywany w pamieci."
                ),
                severity=0.6,
                evidence_refs=["evaluation_reports:retention_rate"],
                pattern_window=window,
            ))

        # 5. MISALIGNMENT: goals exist but no progress
        stale_goals = goal_state.get("stale_goals", [])
        active_goals = goal_state.get("active", 0)
        if len(stale_goals) >= STALE_GOAL_THRESHOLD:
            tensions.append(DetectedTension.create(
                category=TensionCategory.MISALIGNMENT,
                description=(
                    f"{len(stale_goals)} celow aktywnych bez postepu (>72h). "
                    f"Planner nie posuwa celow do przodu: {', '.join(stale_goals[:3])}."
                ),
                severity=0.6,
                evidence_refs=[f"goals:stale_count={len(stale_goals)}"],
                pattern_window=window,
            ))

        # 6. FRAGILE_COORDINATION: high failure rate
        failed_ratio = action_pattern.get("failed_ratio", 0)
        if failed_ratio > FAILURE_RATIO_THRESHOLD and total_actions > 5:
            tensions.append(DetectedTension.create(
                category=TensionCategory.FRAGILE_COORDINATION,
                description=(
                    f"{failed_ratio:.0%} akcji konczy sie bledem. "
                    f"Koordynacja miedzy modulami jest niestabilna."
                ),
                severity=0.5,
                evidence_refs=[f"planner_decisions:failed_ratio={failed_ratio:.2f}"],
                pattern_window=window,
            ))

        # 7. OVER_RESTRICTION: actions blocked but not by resource limits
        dist = action_pattern.get("distribution", {})
        # T-LEARN-008: idle markery to "skip" i "noop" -- samo "noop" bylo zawsze ~0
        noop_count = sum(dist.get(a, 0) for a in IDLE_ACTION_TYPES)
        # If lots of NOOPs and we have active goals, something is blocking
        if noop_count > 20 and active_goals > 1 and noop_ratio > 0.8:
            tensions.append(DetectedTension.create(
                category=TensionCategory.OVER_RESTRICTION,
                description=(
                    f"System ma {active_goals} aktywnych celow ale {noop_ratio:.0%} "
                    f"cykli to NOOP. Cos blokuje wykonywanie celow - moze zbyt restrykcyjna "
                    f"polityka autonomii (K7) lub brak wykonalnych akcji."
                ),
                severity=0.5,
                evidence_refs=[
                    f"goals:active={active_goals}",
                    f"planner_decisions:noop_ratio={noop_ratio:.2f}",
                ],
                pattern_window=window,
            ))

        # Sort by severity (highest first)
        tensions.sort(key=lambda t: t.severity, reverse=True)

        if tensions:
            logger.info(
                f"[CREATIVE] Detected {len(tensions)} tensions: "
                f"{', '.join(t.category.value for t in tensions)}"
            )

        return tensions
