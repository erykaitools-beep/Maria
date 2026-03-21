"""
K11 Experiment System for M.A.R.I.A.

Autonomous parameter tuning through structured experiments.
Pipeline: OBSERVE (K9/K4) -> PROPOSE -> EXPERIMENT -> REPORT -> HUMAN GATE (K3)

v1: 4 proposal rules, 12 tunable parameters, rule-based reports.

Kontrakt: docs/CONTRACTS.md - Kontrakt 11: Experiment System
ADR-013: Rule-based, zero LLM, deterministic, testable.
"""

from agent_core.experiment.experiment_model import (
    Proposal,
    ProposalSource,
    ProposalStatus,
    Experiment,
    ExperimentStatus,
    ExperimentReport,
    ParameterSpec,
    RiskLevel,
    create_proposal,
    create_experiment,
)
from agent_core.experiment.parameter_registry import (
    get_parameter,
    list_parameters,
    get_by_risk,
    get_by_metric,
    validate_value,
)
from agent_core.experiment.proposal_engine import ProposalEngine

__all__ = [
    "Proposal",
    "ProposalSource",
    "ProposalStatus",
    "Experiment",
    "ExperimentStatus",
    "ExperimentReport",
    "ParameterSpec",
    "RiskLevel",
    "create_proposal",
    "create_experiment",
    "ProposalEngine",
    "get_parameter",
    "list_parameters",
    "get_by_risk",
    "get_by_metric",
    "validate_value",
]
