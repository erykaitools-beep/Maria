"""
Experiment Model - dataclasses for K11 Experiment System.

Structured proposals, experiments, and reports for parameter tuning.
Frozen ParameterSpec, mutable Proposal/Experiment/ExperimentReport.

Kontrakt: docs/CONTRACTS.md - Kontrakt 11: Experiment System
ADR-013: Rule-based, zero LLM, deterministic.
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# -- Enums --------------------------------------------------------


class ProposalStatus(Enum):
    """Status of an experiment proposal."""
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ExperimentStatus(Enum):
    """Status of an experiment run."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class RiskLevel(Enum):
    """Risk level of a parameter change."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProposalSource(Enum):
    """What triggered the proposal."""
    K4_RECOMMENDATION = "k4_recommendation"
    K9_PATTERN = "k9_pattern"
    K9_STRUGGLING = "k9_struggling"
    MANUAL = "manual"
    K12_STRATEGIC_CHANGE = "k12_strategic_change"  # Most #2 step 1 (2026-05-08)


# -- ParameterSpec (frozen) ---------------------------------------


@dataclass(frozen=True)
class ParameterSpec:
    """
    Specification of one tunable parameter.

    Registered in ParameterRegistry. Defines bounds, risk, and
    which K4 metric to measure impact against.
    """
    param_id: str
    module_path: str
    constant_name: str
    current_value: Any
    value_type: str
    min_value: float
    max_value: float
    step: float
    risk_level: RiskLevel
    impact_metric: str
    description: str


# -- Proposal -----------------------------------------------------


@dataclass
class Proposal:
    """
    A structured change proposal generated from K9/K4 observations.

    Created by ProposalEngine, linked to a PROPOSED goal in K3.
    """
    proposal_id: str
    source: ProposalSource
    timestamp: float

    # What to change
    parameter_id: str
    current_value: Any
    proposed_value: Any

    # Why
    hypothesis: str
    rationale: str
    expected_outcome: str
    risk_assessment: str

    # Trigger data
    trigger_data: Dict[str, Any] = field(default_factory=dict)

    # Status and linkage
    status: ProposalStatus = ProposalStatus.DRAFT
    goal_id: Optional[str] = None
    experiment_id: Optional[str] = None

    # Human comments
    comments: List[Dict[str, Any]] = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "source": self.source.value,
            "timestamp": self.timestamp,
            "parameter_id": self.parameter_id,
            "current_value": self.current_value,
            "proposed_value": self.proposed_value,
            "hypothesis": self.hypothesis,
            "rationale": self.rationale,
            "expected_outcome": self.expected_outcome,
            "risk_assessment": self.risk_assessment,
            "trigger_data": self.trigger_data,
            "status": self.status.value,
            "goal_id": self.goal_id,
            "experiment_id": self.experiment_id,
            "comments": self.comments,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Proposal":
        return Proposal(
            proposal_id=d["proposal_id"],
            source=ProposalSource(d["source"]),
            timestamp=d.get("timestamp", 0.0),
            parameter_id=d["parameter_id"],
            current_value=d["current_value"],
            proposed_value=d["proposed_value"],
            hypothesis=d["hypothesis"],
            rationale=d["rationale"],
            expected_outcome=d["expected_outcome"],
            risk_assessment=d.get("risk_assessment", ""),
            trigger_data=d.get("trigger_data", {}),
            status=ProposalStatus(d.get("status", "draft")),
            goal_id=d.get("goal_id"),
            experiment_id=d.get("experiment_id"),
            comments=d.get("comments", []),
            metadata=d.get("metadata", {}),
        )

    def add_comment(self, text: str, author: str = "user") -> None:
        """Add a human comment to the proposal."""
        self.comments.append({
            "text": text,
            "author": author,
            "timestamp": time.time(),
        })


# -- Experiment ---------------------------------------------------


@dataclass
class Experiment:
    """
    An experiment run: applies parameter override, runs controlled test, measures.
    """
    experiment_id: str
    proposal_id: str
    parameter_id: str
    baseline_value: Any
    test_value: Any

    status: ExperimentStatus = ExperimentStatus.PENDING
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    max_duration_sec: float = 3600.0

    # Measurements
    baseline_metrics: Dict[str, float] = field(default_factory=dict)
    result_metrics: Dict[str, float] = field(default_factory=dict)
    test_cycles: int = 0
    target_cycles: int = 5

    # Outcome
    error: Optional[str] = None
    report_id: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_sec(self) -> Optional[float]:
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "proposal_id": self.proposal_id,
            "parameter_id": self.parameter_id,
            "baseline_value": self.baseline_value,
            "test_value": self.test_value,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "max_duration_sec": self.max_duration_sec,
            "baseline_metrics": self.baseline_metrics,
            "result_metrics": self.result_metrics,
            "test_cycles": self.test_cycles,
            "target_cycles": self.target_cycles,
            "error": self.error,
            "report_id": self.report_id,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Experiment":
        return Experiment(
            experiment_id=d["experiment_id"],
            proposal_id=d["proposal_id"],
            parameter_id=d["parameter_id"],
            baseline_value=d["baseline_value"],
            test_value=d["test_value"],
            status=ExperimentStatus(d.get("status", "pending")),
            started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
            max_duration_sec=d.get("max_duration_sec", 3600.0),
            baseline_metrics=d.get("baseline_metrics", {}),
            result_metrics=d.get("result_metrics", {}),
            test_cycles=d.get("test_cycles", 0),
            target_cycles=d.get("target_cycles", 5),
            error=d.get("error"),
            report_id=d.get("report_id"),
            metadata=d.get("metadata", {}),
        )


# -- ExperimentReport --------------------------------------------


@dataclass
class ExperimentReport:
    """Structured report from a completed experiment."""
    report_id: str
    experiment_id: str
    proposal_id: str
    timestamp: float

    hypothesis: str
    method: str
    parameter_id: str
    baseline_value: Any
    test_value: Any

    baseline_metrics: Dict[str, float]
    result_metrics: Dict[str, float]
    delta_metrics: Dict[str, float]
    test_cycles: int
    duration_sec: float

    conclusion: str
    recommendation: str
    confidence: float

    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "experiment_id": self.experiment_id,
            "proposal_id": self.proposal_id,
            "timestamp": self.timestamp,
            "hypothesis": self.hypothesis,
            "method": self.method,
            "parameter_id": self.parameter_id,
            "baseline_value": self.baseline_value,
            "test_value": self.test_value,
            "baseline_metrics": self.baseline_metrics,
            "result_metrics": self.result_metrics,
            "delta_metrics": self.delta_metrics,
            "test_cycles": self.test_cycles,
            "duration_sec": self.duration_sec,
            "conclusion": self.conclusion,
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ExperimentReport":
        return ExperimentReport(
            report_id=d["report_id"],
            experiment_id=d["experiment_id"],
            proposal_id=d["proposal_id"],
            timestamp=d.get("timestamp", 0.0),
            hypothesis=d["hypothesis"],
            method=d["method"],
            parameter_id=d["parameter_id"],
            baseline_value=d["baseline_value"],
            test_value=d["test_value"],
            baseline_metrics=d.get("baseline_metrics", {}),
            result_metrics=d.get("result_metrics", {}),
            delta_metrics=d.get("delta_metrics", {}),
            test_cycles=d.get("test_cycles", 0),
            duration_sec=d.get("duration_sec", 0.0),
            conclusion=d.get("conclusion", ""),
            recommendation=d.get("recommendation", "INCONCLUSIVE"),
            confidence=d.get("confidence", 0.0),
            metadata=d.get("metadata", {}),
        )


# -- Factory functions --------------------------------------------


def create_proposal(
    source: ProposalSource,
    parameter_id: str,
    current_value: Any,
    proposed_value: Any,
    hypothesis: str,
    rationale: str,
    expected_outcome: str,
    risk_assessment: str = "",
    trigger_data: Optional[Dict[str, Any]] = None,
) -> Proposal:
    """Create a new Proposal with generated ID and timestamp."""
    return Proposal(
        proposal_id=f"prop-{uuid.uuid4().hex[:12]}",
        source=source,
        timestamp=time.time(),
        parameter_id=parameter_id,
        current_value=current_value,
        proposed_value=proposed_value,
        hypothesis=hypothesis,
        rationale=rationale,
        expected_outcome=expected_outcome,
        risk_assessment=risk_assessment,
        trigger_data=trigger_data or {},
    )


def create_experiment(proposal: Proposal) -> Experiment:
    """Create an Experiment from an approved Proposal."""
    return Experiment(
        experiment_id=f"exp-{uuid.uuid4().hex[:12]}",
        proposal_id=proposal.proposal_id,
        parameter_id=proposal.parameter_id,
        baseline_value=proposal.current_value,
        test_value=proposal.proposed_value,
    )
