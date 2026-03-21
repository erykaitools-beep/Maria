"""
Parameter Registry - Known tunable parameters for K11 Experiment System.

Static registry of parameters Maria is allowed to experiment with.
Each parameter has bounds, risk level, and which K4 metric measures impact.

v1: ~12 parameters across 6 modules.
v2 path: add Smart Home, Vision, Code Agent parameters.

ADR-013: Deterministic, zero LLM.
"""

from typing import Dict, List, Optional

from agent_core.experiment.experiment_model import ParameterSpec, RiskLevel


# Registry keyed by param_id
_REGISTRY: Dict[str, ParameterSpec] = {}


def _r(param_id, module_path, constant_name, current_value, value_type,
       min_val, max_val, step, risk, metric, desc):
    """Register a parameter spec."""
    _REGISTRY[param_id] = ParameterSpec(
        param_id=param_id,
        module_path=module_path,
        constant_name=constant_name,
        current_value=current_value,
        value_type=value_type,
        min_value=min_val,
        max_value=max_val,
        step=step,
        risk_level=risk,
        impact_metric=metric,
        description=desc,
    )


# ── LOW risk (timing, cosmetics) ────────────────────────────────

_r("planner.ROUTINE_INTERVAL_TICKS",
   "agent_core.planner.planner_core", "ROUTINE_INTERVAL_TICKS",
   60, "int", 30, 180, 10, RiskLevel.LOW,
   "learning_velocity", "Planner cycle interval in ticks")

_r("planner.EVALUATION_INTERVAL_SEC",
   "agent_core.planner.planner_core", "EVALUATION_INTERVAL_SEC",
   3600, "int", 1800, 14400, 600, RiskLevel.LOW,
   "system_stability", "K4 evaluation report frequency (seconds)")

_r("homeostasis.TEACHER_IDLE_THRESHOLD",
   "agent_core.homeostasis.core", "TEACHER_IDLE_THRESHOLD",
   600, "int", 300, 1800, 60, RiskLevel.LOW,
   "learning_velocity", "Idle seconds before auto-learning triggers")

_r("homeostasis.TEACHER_MAX_ITERATIONS",
   "agent_core.homeostasis.core", "TEACHER_MAX_ITERATIONS",
   3, "int", 1, 10, 1, RiskLevel.LOW,
   "learning_velocity", "Max iterations per auto-learning session")

# ── MEDIUM risk (learning pipeline) ─────────────────────────────

_r("config.EXAM_PASS_THRESHOLD",
   "maria_core.sys.config", "EXAM_PASS_THRESHOLD",
   0.6, "float", 0.4, 0.9, 0.05, RiskLevel.MEDIUM,
   "retention_rate", "Score required to pass exam")

_r("config.TARGET_CHUNK_SIZE",
   "maria_core.sys.config", "TARGET_CHUNK_SIZE",
   1200, "int", 600, 2000, 100, RiskLevel.MEDIUM,
   "learning_velocity", "Target text chunk size in characters")

_r("config.EXAM_QUESTIONS_PER_CHUNK",
   "maria_core.sys.config", "EXAM_QUESTIONS_PER_CHUNK",
   1.5, "float", 0.5, 3.0, 0.25, RiskLevel.MEDIUM,
   "retention_rate", "Questions generated per learned chunk")

_r("planner.MIN_RETENTION_FOR_NEW_TOPICS",
   "agent_core.planner.planner_core", "MIN_RETENTION_FOR_NEW_TOPICS",
   0.6, "float", 0.3, 0.9, 0.05, RiskLevel.MEDIUM,
   "retention_rate", "Min retention before learning new topics")

_r("goal_selector.AGING_FACTOR_PER_HOUR",
   "agent_core.planner.goal_selector", "AGING_FACTOR_PER_HOUR",
   0.1, "float", 0.01, 0.5, 0.02, RiskLevel.MEDIUM,
   "knowledge_coverage", "Priority boost per hour for pending goals")

# ── HIGH risk (safety boundaries) ───────────────────────────────

_r("planner_guard.MIN_HEALTH_SCORE",
   "agent_core.planner.planner_guard", "MIN_HEALTH_SCORE",
   0.7, "float", 0.5, 0.95, 0.05, RiskLevel.HIGH,
   "system_stability", "Minimum health for planner to run")

_r("config.EXAM_MAX_ATTEMPTS",
   "maria_core.sys.config", "EXAM_MAX_ATTEMPTS",
   2, "int", 1, 5, 1, RiskLevel.HIGH,
   "retention_rate", "Failed exam attempts before hard_topic status")

_r("planner_guard.MIN_RETENTION_RATE",
   "agent_core.planner.planner_guard", "MIN_RETENTION_RATE",
   0.5, "float", 0.3, 0.8, 0.05, RiskLevel.HIGH,
   "retention_rate", "Min retention for planner to create learning plans")


# ── Public API ──────────────────────────────────────────────────


def get_parameter(param_id: str) -> Optional[ParameterSpec]:
    """Get parameter spec by ID."""
    return _REGISTRY.get(param_id)


def list_parameters() -> Dict[str, ParameterSpec]:
    """Get all registered parameters."""
    return dict(_REGISTRY)


def get_by_risk(risk: RiskLevel) -> Dict[str, ParameterSpec]:
    """Filter parameters by risk level."""
    return {k: v for k, v in _REGISTRY.items() if v.risk_level == risk}


def get_by_metric(metric: str) -> Dict[str, ParameterSpec]:
    """Filter parameters by impact metric."""
    return {k: v for k, v in _REGISTRY.items() if v.impact_metric == metric}


def validate_value(param_id: str, value: float) -> bool:
    """Check if value is within bounds for parameter."""
    spec = _REGISTRY.get(param_id)
    if spec is None:
        return False
    return spec.min_value <= value <= spec.max_value
