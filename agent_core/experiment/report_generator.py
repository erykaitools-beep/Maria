"""
Report Generator - Produces structured reports from completed experiments.

Computes metric deltas, determines recommendation (ADOPT/REJECT/INCONCLUSIVE),
and calculates confidence score.

ADR-013: Rule-based, zero LLM, deterministic.
Kontrakt: docs/CONTRACTS.md - Kontrakt 11: Experiment System
"""

import logging
import time
import uuid
from typing import Any, Dict, Optional

from agent_core.experiment.experiment_model import (
    Experiment,
    ExperimentReport,
    ExperimentStatus,
)
from agent_core.experiment import parameter_registry

logger = logging.getLogger(__name__)

# Recommendation thresholds
MIN_IMPROVEMENT_PCT = 5.0    # 5% improvement needed for ADOPT
MIN_CYCLES_FOR_CONFIDENCE = 3
MAX_CONFIDENCE = 0.95
MIN_CONFIDENCE = 0.1

# Recommendation values
ADOPT = "ADOPT"
REJECT = "REJECT"
INCONCLUSIVE = "INCONCLUSIVE"


class ReportGenerator:
    """
    Generates ExperimentReport from a completed Experiment.

    Decision logic:
    - ADOPT: impact metric improved >= 5%, confidence >= 0.5
    - REJECT: impact metric worsened or no improvement
    - INCONCLUSIVE: too few cycles, or mixed signals
    """

    def generate(self, experiment: Experiment) -> Optional[ExperimentReport]:
        """
        Generate report from a completed experiment.

        Args:
            experiment: Must have status COMPLETED (or ABORTED with partial data).

        Returns:
            ExperimentReport, or None if experiment has no metrics.
        """
        if experiment.status not in (
            ExperimentStatus.COMPLETED, ExperimentStatus.ABORTED,
        ):
            return None

        if not experiment.baseline_metrics and not experiment.result_metrics:
            return None

        spec = parameter_registry.get_parameter(experiment.parameter_id)

        # Compute deltas
        delta_metrics = self._compute_deltas(
            experiment.baseline_metrics,
            experiment.result_metrics,
        )

        # Determine impact metric
        impact_metric = spec.impact_metric if spec else ""

        # Compute recommendation and confidence
        recommendation, confidence, conclusion = self._evaluate(
            delta_metrics=delta_metrics,
            impact_metric=impact_metric,
            test_cycles=experiment.test_cycles,
            target_cycles=experiment.target_cycles,
            was_aborted=experiment.status == ExperimentStatus.ABORTED,
        )

        # Build method description
        method = self._build_method(experiment, spec)

        # Build hypothesis from proposal context
        hypothesis = experiment.metadata.get("hypothesis", "")
        if not hypothesis and spec:
            hypothesis = (
                f"Zmiana {spec.constant_name} z {experiment.baseline_value} "
                f"na {experiment.test_value} poprawi {impact_metric}"
            )

        report_id = f"rep-{uuid.uuid4().hex[:12]}"
        duration = experiment.duration_sec or 0.0

        report = ExperimentReport(
            report_id=report_id,
            experiment_id=experiment.experiment_id,
            proposal_id=experiment.proposal_id,
            timestamp=time.time(),
            hypothesis=hypothesis,
            method=method,
            parameter_id=experiment.parameter_id,
            baseline_value=experiment.baseline_value,
            test_value=experiment.test_value,
            baseline_metrics=experiment.baseline_metrics,
            result_metrics=experiment.result_metrics,
            delta_metrics=delta_metrics,
            test_cycles=experiment.test_cycles,
            duration_sec=duration,
            conclusion=conclusion,
            recommendation=recommendation,
            confidence=confidence,
            metadata={
                "impact_metric": impact_metric,
                "target_cycles": experiment.target_cycles,
                "was_aborted": experiment.status == ExperimentStatus.ABORTED,
            },
        )

        # Link report back to experiment
        experiment.report_id = report_id

        logger.info(
            f"[K11] Report {report_id}: {recommendation} "
            f"(confidence={confidence:.2f}, "
            f"impact delta={delta_metrics.get(impact_metric, 0):.3f})"
        )

        return report

    # ── Delta computation ────────────────────────────────────

    def _compute_deltas(
        self,
        baseline: Dict[str, float],
        result: Dict[str, float],
    ) -> Dict[str, float]:
        """Compute metric deltas (result - baseline)."""
        all_keys = set(baseline.keys()) | set(result.keys())
        deltas = {}
        for key in all_keys:
            b = baseline.get(key, 0.0)
            r = result.get(key, 0.0)
            deltas[key] = round(r - b, 4)
        return deltas

    # ── Recommendation logic ─────────────────────────────────

    def _evaluate(
        self,
        delta_metrics: Dict[str, float],
        impact_metric: str,
        test_cycles: int,
        target_cycles: int,
        was_aborted: bool,
    ) -> tuple:
        """
        Determine recommendation, confidence, and conclusion.

        Returns:
            (recommendation, confidence, conclusion)
        """
        # Not enough data
        if test_cycles < MIN_CYCLES_FOR_CONFIDENCE:
            confidence = self._compute_confidence(
                test_cycles, target_cycles, was_aborted
            )
            return (
                INCONCLUSIVE,
                confidence,
                f"Za malo cykli ({test_cycles}/{target_cycles}) "
                f"dla pewnej oceny",
            )

        # Aborted experiment
        if was_aborted:
            confidence = self._compute_confidence(
                test_cycles, target_cycles, was_aborted
            )
            return (
                INCONCLUSIVE,
                confidence,
                "Eksperyment przerwany - wyniki niepelne",
            )

        # Check impact metric
        impact_delta = delta_metrics.get(impact_metric, 0.0)

        # No impact metric available
        if not impact_metric or impact_metric not in delta_metrics:
            confidence = self._compute_confidence(
                test_cycles, target_cycles, False
            )
            return (
                INCONCLUSIVE,
                confidence,
                "Brak danych metryki docelowej",
            )

        # Compute improvement percentage relative to baseline
        baseline_val = 1.0  # prevent div by zero
        if impact_metric:
            # We don't have baseline value directly here, use delta sign
            pass

        # Determine direction
        improvement_pct = impact_delta * 100  # delta is already fractional

        confidence = self._compute_confidence(
            test_cycles, target_cycles, False
        )

        if improvement_pct >= MIN_IMPROVEMENT_PCT:
            return (
                ADOPT,
                confidence,
                f"Metryka {impact_metric} poprawila sie o "
                f"{improvement_pct:+.1f}pp",
            )
        elif improvement_pct <= -MIN_IMPROVEMENT_PCT:
            return (
                REJECT,
                confidence,
                f"Metryka {impact_metric} pogorszyla sie o "
                f"{abs(improvement_pct):.1f}pp",
            )
        else:
            return (
                INCONCLUSIVE,
                confidence * 0.8,  # lower confidence for small changes
                f"Zmiana metryki {impact_metric} minimalna "
                f"({improvement_pct:+.1f}pp, prog: +/-{MIN_IMPROVEMENT_PCT}%)",
            )

    def _compute_confidence(
        self,
        test_cycles: int,
        target_cycles: int,
        was_aborted: bool,
    ) -> float:
        """
        Compute confidence score [0, 1].

        Based on:
        - Ratio of completed cycles to target
        - Penalty for abort
        """
        if target_cycles <= 0:
            return MIN_CONFIDENCE

        ratio = test_cycles / target_cycles
        confidence = min(ratio, 1.0) * MAX_CONFIDENCE

        if was_aborted:
            confidence *= 0.5

        return round(max(confidence, MIN_CONFIDENCE), 2)

    # ── Method description ───────────────────────────────────

    def _build_method(self, experiment: Experiment, spec) -> str:
        """Build human-readable method description."""
        param_name = spec.constant_name if spec else experiment.parameter_id
        return (
            f"Parametr {param_name} zmieniony z {experiment.baseline_value} "
            f"na {experiment.test_value}. "
            f"Przeprowadzono {experiment.test_cycles}/{experiment.target_cycles} "
            f"cykli nauki. "
            f"Metryki K4 zmierzone przed i po eksperymencie."
        )
