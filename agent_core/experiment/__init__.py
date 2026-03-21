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
from agent_core.experiment.experiment_runner import ExperimentRunner
from agent_core.experiment.report_generator import ReportGenerator

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)
_DEFAULT_REPORTS_PATH = Path("meta_data/experiment_reports.jsonl")


class ExperimentSystem:
    """
    K11 Facade - orchestrates proposals, experiments, and reports.

    Pipeline:
        ProposalEngine.scan() -> approve() -> run_experiment() -> report
    """

    def __init__(self, reports_path: Optional[Path] = None):
        self.proposal_engine = ProposalEngine()
        self.runner = ExperimentRunner()
        self.report_generator = ReportGenerator()
        self._reports_path = Path(reports_path or _DEFAULT_REPORTS_PATH)
        self._reports: List[ExperimentReport] = []
        self._reports_loaded = False

    # ── Dependency injection ─────────────────────────────────

    def set_teacher_agent(self, agent) -> None:
        self.runner.set_teacher_agent(agent)

    def set_evaluation_observer(self, observer) -> None:
        self.runner.set_evaluation_observer(observer)

    def set_homeostasis_core(self, core) -> None:
        self.runner.set_homeostasis_core(core)

    # ── Proposal flow ────────────────────────────────────────

    def scan_for_proposals(
        self,
        k4_metrics: Dict[str, float],
        k4_recommendations: List[str],
        k9_patterns: Dict[str, Any],
    ) -> List[Proposal]:
        """Scan K4/K9 and generate proposals."""
        return self.proposal_engine.scan(
            k4_metrics, k4_recommendations, k9_patterns,
        )

    def approve(self, proposal_id: str) -> bool:
        """Approve a proposal for experimentation."""
        return self.proposal_engine.update_status(
            proposal_id, ProposalStatus.APPROVED,
        )

    def reject(self, proposal_id: str) -> bool:
        """Reject a proposal."""
        return self.proposal_engine.update_status(
            proposal_id, ProposalStatus.REJECTED,
        )

    def add_comment(self, proposal_id: str, text: str, author: str = "user") -> bool:
        """Add human comment to a proposal."""
        return self.proposal_engine.add_comment(proposal_id, text, author)

    # ── Experiment execution ─────────────────────────────────

    def run_experiment(self, proposal_id: str) -> Optional[ExperimentReport]:
        """
        Run experiment for an approved proposal.

        Full pipeline: create experiment -> run -> generate report -> save.

        Returns:
            ExperimentReport on success, None on failure.
        """
        proposal = self.proposal_engine.get_proposal(proposal_id)
        if proposal is None:
            _logger.warning(f"[K11] Proposal {proposal_id} not found")
            return None

        if proposal.status != ProposalStatus.APPROVED:
            _logger.warning(
                f"[K11] Proposal {proposal_id} not approved "
                f"(status: {proposal.status.value})"
            )
            return None

        # Create experiment from proposal
        experiment = create_experiment(proposal)
        experiment.metadata["hypothesis"] = proposal.hypothesis

        # Link experiment to proposal
        self.proposal_engine.update_status(
            proposal_id, ProposalStatus.APPROVED,
            experiment_id=experiment.experiment_id,
        )

        # Run
        experiment = self.runner.run(experiment)

        # Generate report
        report = None
        if experiment.status in (ExperimentStatus.COMPLETED, ExperimentStatus.ABORTED):
            report = self.report_generator.generate(experiment)
            if report:
                self._ensure_reports_loaded()
                self._reports.append(report)
                self._save_report(report)

        return report

    # ── Reports ──────────────────────────────────────────────

    def get_report(self, report_id: str) -> Optional[ExperimentReport]:
        """Get report by ID."""
        self._ensure_reports_loaded()
        for r in self._reports:
            if r.report_id == report_id:
                return r
        return None

    def get_all_reports(self) -> List[ExperimentReport]:
        """Get all reports."""
        self._ensure_reports_loaded()
        return list(self._reports)

    # ── Status ───────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Status dict for REPL / Web UI."""
        self._ensure_reports_loaded()
        proposal_status = self.proposal_engine.get_status()
        return {
            "proposals": proposal_status,
            "current_experiment": (
                self.runner.get_current().to_dict()
                if self.runner.is_running else None
            ),
            "total_reports": len(self._reports),
            "last_report": (
                self._reports[-1].to_dict() if self._reports else None
            ),
        }

    # ── Persistence ──────────────────────────────────────────

    def _ensure_reports_loaded(self) -> None:
        if self._reports_loaded:
            return
        self._reports_loaded = True
        self._reports = self._load_reports()

    def _load_reports(self) -> List[ExperimentReport]:
        if not self._reports_path.exists():
            return []
        reports = []
        try:
            with open(self._reports_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            reports.append(
                                ExperimentReport.from_dict(json.loads(line))
                            )
                        except (json.JSONDecodeError, KeyError, ValueError):
                            continue
        except OSError:
            pass
        return reports

    def _save_report(self, report: ExperimentReport) -> None:
        try:
            self._reports_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._reports_path, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(report.to_dict(), ensure_ascii=False) + "\n"
                )
        except OSError as e:
            _logger.warning(f"[K11] Failed to save report: {e}")


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
    "ExperimentRunner",
    "ReportGenerator",
    "ExperimentSystem",
    "get_parameter",
    "list_parameters",
    "get_by_risk",
    "get_by_metric",
    "validate_value",
]
