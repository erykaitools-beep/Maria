"""
PlannerGuard - Gating rules for planner execution.

Prevents planning when system is degraded.
Kontrakt: docs/CONTRACTS.md - Kontrakt 5: Planner
"""

import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# Guard thresholds
MIN_HEALTH_SCORE = 0.7
MIN_RETENTION_RATE = 0.5
EVALUATION_COOLDOWN_SEC = 900  # 15 min cooldown on eval recommendations


class PlannerGuard:
    """
    Gating rules that determine if planning should proceed.

    All checks are pure functions - no side effects.
    Returns (can_plan: bool, reasons: List[str]).
    """

    def can_plan(
        self,
        health_score: float,
        mode: str,
        sandbox_active: bool,
        retention_rate: Optional[float],
        is_teacher_running: bool = False,
    ) -> Tuple[bool, List[str]]:
        """
        Check if planner should run this cycle.

        Args:
            health_score: Current system health (0.0-1.0)
            mode: Current homeostasis mode string
            sandbox_active: Whether a sandbox session exists
            retention_rate: K4 retention rate metric (None if no data)
            is_teacher_running: Whether teacher is currently executing

        Returns:
            (can_plan, list_of_block_reasons)
        """
        reasons = []

        if health_score < MIN_HEALTH_SCORE:
            reasons.append(
                f"health_score {health_score:.2f} < {MIN_HEALTH_SCORE}"
            )

        if mode != "active":
            reasons.append(f"mode is {mode}, not active")

        if sandbox_active:
            reasons.append("sandbox session active")

        # retention_rate=0.0 means "no exam data" (no exams taken yet),
        # NOT "bad retention". Only gate when we have real exam results.
        if (retention_rate is not None
                and retention_rate > 0.0
                and retention_rate < MIN_RETENTION_RATE):
            reasons.append(
                f"retention_rate {retention_rate:.2f} < {MIN_RETENTION_RATE}"
            )

        if is_teacher_running:
            reasons.append("teacher session currently running")

        can = len(reasons) == 0
        if not can:
            logger.debug(f"PlannerGuard blocked: {reasons}")

        return can, reasons
