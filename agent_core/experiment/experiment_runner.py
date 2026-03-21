"""
Experiment Runner - Executes parameter experiments in isolation.

Applies parameter override via setattr, runs N learning cycles,
captures before/after K4 metrics, restores original value.

Safety:
- Max 1 experiment at a time
- Max 1h duration (configurable)
- Health guard: abort if health < 0.8 (HIGH risk needs > 0.9)
- Restore parameter ALWAYS (finally block)

ADR-013: Rule-based, zero LLM, deterministic.
Kontrakt: docs/CONTRACTS.md - Kontrakt 11: Experiment System
"""

import importlib
import logging
import time
from typing import Any, Dict, Optional

from agent_core.experiment.experiment_model import (
    Experiment,
    ExperimentStatus,
    RiskLevel,
)
from agent_core.experiment import parameter_registry

logger = logging.getLogger(__name__)

# Safety thresholds
MIN_HEALTH_FOR_EXPERIMENT = 0.8
MIN_HEALTH_FOR_HIGH_RISK = 0.9
MAX_DURATION_SEC = 3600  # 1 hour
DEFAULT_TARGET_CYCLES = 5


class ExperimentRunner:
    """
    Runs a single experiment: override parameter, run cycles, measure.

    Usage:
        runner = ExperimentRunner()
        runner.set_teacher_agent(teacher)
        runner.set_evaluation_observer(observer)
        runner.set_homeostasis_core(core)
        experiment = runner.run(experiment)
    """

    def __init__(self):
        self._teacher_agent = None
        self._evaluation_observer = None
        self._homeostasis_core = None
        self._current_experiment: Optional[Experiment] = None

    def set_teacher_agent(self, agent) -> None:
        self._teacher_agent = agent

    def set_evaluation_observer(self, observer) -> None:
        self._evaluation_observer = observer

    def set_homeostasis_core(self, core) -> None:
        self._homeostasis_core = core

    @property
    def is_running(self) -> bool:
        return (self._current_experiment is not None
                and self._current_experiment.status == ExperimentStatus.RUNNING)

    def run(self, experiment: Experiment) -> Experiment:
        """
        Run an experiment end-to-end.

        1. Validate preconditions (no concurrent, health OK)
        2. Capture baseline K4 metrics
        3. Apply parameter override (setattr)
        4. Run target_cycles learning cycles
        5. Capture result K4 metrics
        6. Restore original parameter (ALWAYS, via finally)

        Args:
            experiment: Experiment with PENDING status.

        Returns:
            Updated Experiment with COMPLETED/FAILED/ABORTED status.
        """
        if self.is_running:
            experiment.status = ExperimentStatus.FAILED
            experiment.error = "Another experiment is already running"
            return experiment

        # Validate parameter exists
        spec = parameter_registry.get_parameter(experiment.parameter_id)
        if spec is None:
            experiment.status = ExperimentStatus.FAILED
            experiment.error = f"Unknown parameter: {experiment.parameter_id}"
            return experiment

        # Validate test value in bounds
        if not parameter_registry.validate_value(
            experiment.parameter_id, experiment.test_value
        ):
            experiment.status = ExperimentStatus.FAILED
            experiment.error = (
                f"Test value {experiment.test_value} out of bounds "
                f"[{spec.min_value}, {spec.max_value}]"
            )
            return experiment

        # Health guard
        health_ok, health_msg = self._check_health(spec.risk_level)
        if not health_ok:
            experiment.status = ExperimentStatus.ABORTED
            experiment.error = health_msg
            return experiment

        # Resolve module and constant
        module, original_value = self._resolve_parameter(spec)
        if module is None:
            experiment.status = ExperimentStatus.FAILED
            experiment.error = f"Cannot resolve module: {spec.module_path}"
            return experiment

        # Start experiment
        self._current_experiment = experiment
        experiment.status = ExperimentStatus.RUNNING
        experiment.started_at = time.time()
        experiment.baseline_value = original_value

        logger.info(
            f"[K11] Experiment {experiment.experiment_id} started: "
            f"{spec.constant_name} = {original_value} -> {experiment.test_value}"
        )

        try:
            # 1. Capture baseline metrics
            experiment.baseline_metrics = self._capture_metrics()

            # 2. Apply parameter override
            setattr(module, spec.constant_name, experiment.test_value)

            # 3. Run learning cycles
            cycles_done = self._run_cycles(
                experiment,
                spec.risk_level,
            )
            experiment.test_cycles = cycles_done

            # 4. Capture result metrics
            experiment.result_metrics = self._capture_metrics()

            experiment.status = ExperimentStatus.COMPLETED

        except _ExperimentAborted as e:
            experiment.status = ExperimentStatus.ABORTED
            experiment.error = str(e)
            logger.warning(f"[K11] Experiment aborted: {e}")

        except Exception as e:
            experiment.status = ExperimentStatus.FAILED
            experiment.error = str(e)
            logger.error(f"[K11] Experiment failed: {e}")

        finally:
            # ALWAYS restore original value
            try:
                setattr(module, spec.constant_name, original_value)
                logger.info(
                    f"[K11] Restored {spec.constant_name} = {original_value}"
                )
            except Exception as e:
                logger.error(f"[K11] CRITICAL: Failed to restore parameter: {e}")

            experiment.finished_at = time.time()
            self._current_experiment = None

        return experiment

    def get_current(self) -> Optional[Experiment]:
        """Get currently running experiment (or None)."""
        return self._current_experiment

    # ── Health check ─────────────────────────────────────────

    def _check_health(self, risk_level: RiskLevel) -> tuple:
        """Check system health before starting experiment."""
        if self._homeostasis_core is None:
            # No health monitoring - allow (tests, REPL without homeostasis)
            return True, ""

        try:
            state = self._homeostasis_core.get_state()
            health = state.health_score
        except Exception:
            return True, ""  # Can't read health, allow

        threshold = MIN_HEALTH_FOR_EXPERIMENT
        if risk_level == RiskLevel.HIGH:
            threshold = MIN_HEALTH_FOR_HIGH_RISK

        if health < threshold:
            return False, (
                f"Health {health:.2f} below threshold {threshold:.2f} "
                f"for {risk_level.value} risk experiment"
            )

        return True, ""

    def _check_health_during(self, risk_level: RiskLevel) -> bool:
        """Check health during experiment (for abort)."""
        ok, _ = self._check_health(risk_level)
        return ok

    # ── Parameter resolution ─────────────────────────────────

    def _resolve_parameter(self, spec) -> tuple:
        """
        Import module and get current value of constant.

        Returns:
            (module, current_value) or (None, None) on failure.
        """
        try:
            mod = importlib.import_module(spec.module_path)
            current = getattr(mod, spec.constant_name)
            return mod, current
        except (ImportError, AttributeError) as e:
            logger.warning(f"[K11] Cannot resolve {spec.module_path}.{spec.constant_name}: {e}")
            return None, None

    # ── Metrics capture ──────────────────────────────────────

    def _capture_metrics(self) -> Dict[str, float]:
        """Capture K4 metrics snapshot."""
        if self._evaluation_observer is None:
            return {}

        try:
            report = self._evaluation_observer.generate_report(period_hours=1.0)
            return dict(report.metrics)
        except Exception as e:
            logger.warning(f"[K11] Cannot capture metrics: {e}")
            return {}

    # ── Learning cycles ──────────────────────────────────────

    def _run_cycles(
        self,
        experiment: Experiment,
        risk_level: RiskLevel,
    ) -> int:
        """
        Run target_cycles learning iterations.

        Checks health + timeout between each cycle.
        Raises _ExperimentAborted if guard triggers.
        """
        target = experiment.target_cycles or DEFAULT_TARGET_CYCLES
        cycles_done = 0

        for i in range(target):
            # Timeout check
            elapsed = time.time() - experiment.started_at
            if elapsed > experiment.max_duration_sec:
                raise _ExperimentAborted(
                    f"Timeout after {elapsed:.0f}s (max {experiment.max_duration_sec:.0f}s)"
                )

            # Health check
            if not self._check_health_during(risk_level):
                raise _ExperimentAborted(
                    f"Health dropped below threshold during cycle {i+1}"
                )

            # Run one learning cycle
            if self._teacher_agent is not None:
                try:
                    self._teacher_agent.run_session(max_iterations=1)
                except Exception as e:
                    logger.warning(f"[K11] Cycle {i+1} error: {e}")
                    # Continue - one failed cycle doesn't abort experiment

            cycles_done += 1

        return cycles_done


class _ExperimentAborted(Exception):
    """Internal signal for experiment abort."""
    pass
