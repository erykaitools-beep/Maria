"""
Proposal Engine - Rule-based proposal generation from K9/K4 observations.

Scans K4 evaluation metrics and K9 pattern analysis to generate
structured Proposals for parameter changes.

v1: 4 rules (LOW_RETENTION, CONSECUTIVE_FAILURES, HIGH_COVERAGE, SLOW_EXECUTION).
v2 path: configurable rules from JSONL, more trigger sources.

ADR-013: Rule-based, zero LLM, deterministic.
Kontrakt: docs/CONTRACTS.md - Kontrakt 11: Experiment System
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agent_core.experiment.experiment_model import (
    Proposal,
    ProposalSource,
    ProposalStatus,
    create_proposal,
)
from agent_core.experiment import parameter_registry

logger = logging.getLogger(__name__)

_DEFAULT_PROPOSALS_PATH = Path("meta_data/experiment_proposals.jsonl")

# Limits
MAX_ACTIVE_PROPOSALS = 3
PROPOSAL_COOLDOWN_SEC = 3600  # 1h between proposals for same parameter
MAX_PROPOSALS_PER_DAY = 5

# Rule thresholds
LOW_RETENTION_THRESHOLD = 0.6
LOW_RETENTION_CONSECUTIVE = 2
CONSECUTIVE_FAILURE_THRESHOLD = 3
HIGH_COVERAGE_THRESHOLD = 0.9
SLOW_EXECUTION_LESSON_COUNT = 3


class ProposalEngine:
    """
    Generates Proposals from K9/K4 observations.

    Each rule maps an observation pattern to a parameter change.
    Rules are checked in priority order; first match wins per parameter.
    """

    def __init__(self, proposals_path: Optional[Path] = None):
        self._proposals_path = Path(proposals_path or _DEFAULT_PROPOSALS_PATH)
        self._proposals: List[Proposal] = []
        self._low_retention_streak: int = 0
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._proposals = self._load_proposals()

    def scan(
        self,
        k4_metrics: Dict[str, float],
        k4_recommendations: List[str],
        k9_patterns: Dict[str, Any],
    ) -> List[Proposal]:
        """
        Scan K4/K9 output and generate proposals if rules match.

        Args:
            k4_metrics: Dict with keys like "retention_rate", "knowledge_coverage"
            k4_recommendations: List of recommendation strings from K4
            k9_patterns: Dict from MetaCognition.analyze_patterns()

        Returns:
            List of newly created proposals (may be empty).
        """
        self._ensure_loaded()

        # Check daily limit
        today_count = self._count_today_proposals()
        if today_count >= MAX_PROPOSALS_PER_DAY:
            return []

        # Check active limit
        active = [p for p in self._proposals
                  if p.status in (ProposalStatus.DRAFT, ProposalStatus.PROPOSED)]
        if len(active) >= MAX_ACTIVE_PROPOSALS:
            return []

        new_proposals = []

        for rule_fn in self._rules():
            if today_count + len(new_proposals) >= MAX_PROPOSALS_PER_DAY:
                break
            if len(active) + len(new_proposals) >= MAX_ACTIVE_PROPOSALS:
                break

            proposal = rule_fn(k4_metrics, k4_recommendations, k9_patterns)
            if proposal is not None:
                # Check cooldown for this parameter
                if not self._is_on_cooldown(proposal.parameter_id):
                    new_proposals.append(proposal)
                    self._proposals.append(proposal)
                    self._save_proposal(proposal)
                    logger.info(
                        f"[K11] New proposal: {proposal.proposal_id} "
                        f"({proposal.parameter_id}: {proposal.current_value} "
                        f"-> {proposal.proposed_value})"
                    )

        return new_proposals

    def get_active_proposals(self) -> List[Proposal]:
        """Get proposals in DRAFT or PROPOSED status."""
        self._ensure_loaded()
        return [p for p in self._proposals
                if p.status in (ProposalStatus.DRAFT, ProposalStatus.PROPOSED)]

    def get_all_proposals(self) -> List[Proposal]:
        """Get all proposals."""
        self._ensure_loaded()
        return list(self._proposals)

    def get_proposal(self, proposal_id: str) -> Optional[Proposal]:
        """Get proposal by ID."""
        self._ensure_loaded()
        for p in self._proposals:
            if p.proposal_id == proposal_id:
                return p
        return None

    def update_status(
        self,
        proposal_id: str,
        status: ProposalStatus,
        goal_id: Optional[str] = None,
        experiment_id: Optional[str] = None,
    ) -> bool:
        """Update proposal status and persist."""
        self._ensure_loaded()
        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            return False

        proposal.status = status
        if goal_id is not None:
            proposal.goal_id = goal_id
        if experiment_id is not None:
            proposal.experiment_id = experiment_id

        self._rewrite_proposals()
        return True

    def add_comment(self, proposal_id: str, text: str, author: str = "user") -> bool:
        """Add a human comment to a proposal."""
        self._ensure_loaded()
        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            return False

        proposal.add_comment(text, author)
        self._rewrite_proposals()
        return True

    def get_status(self) -> Dict[str, Any]:
        """Status dict for REPL / Web UI."""
        self._ensure_loaded()
        by_status = {}
        for p in self._proposals:
            s = p.status.value
            by_status[s] = by_status.get(s, 0) + 1

        return {
            "total_proposals": len(self._proposals),
            "by_status": by_status,
            "active": len(self.get_active_proposals()),
            "today_count": self._count_today_proposals(),
            "daily_limit": MAX_PROPOSALS_PER_DAY,
        }

    # ── Rules ────────────────────────────────────────────────────

    def _rules(self) -> List[Callable]:
        """Return list of rule functions in priority order."""
        return [
            self._rule_low_retention,
            self._rule_consecutive_failures,
            self._rule_high_coverage,
            self._rule_slow_execution,
        ]

    def _rule_low_retention(
        self,
        k4_metrics: Dict[str, float],
        k4_recs: List[str],
        k9_patterns: Dict[str, Any],
    ) -> Optional[Proposal]:
        """
        LOW_RETENTION: retention_rate < 0.6 for 2+ consecutive scans
        -> propose raising EXAM_PASS_THRESHOLD +0.05
        """
        retention = k4_metrics.get("retention_rate", 1.0)

        if retention < LOW_RETENTION_THRESHOLD:
            self._low_retention_streak += 1
        else:
            self._low_retention_streak = 0
            return None

        if self._low_retention_streak < LOW_RETENTION_CONSECUTIVE:
            return None

        spec = parameter_registry.get_parameter("config.EXAM_PASS_THRESHOLD")
        if spec is None:
            return None

        new_value = round(spec.current_value + spec.step, 2)
        if not parameter_registry.validate_value(spec.param_id, new_value):
            return None

        return create_proposal(
            source=ProposalSource.K4_RECOMMENDATION,
            parameter_id=spec.param_id,
            current_value=spec.current_value,
            proposed_value=new_value,
            hypothesis=(
                f"Podniesienie EXAM_PASS_THRESHOLD z {spec.current_value} "
                f"do {new_value} poprawi retention_rate"
            ),
            rationale=(
                f"K4 raportuje retention_rate={retention:.2f} "
                f"ponizej {LOW_RETENTION_THRESHOLD} przez "
                f"{self._low_retention_streak} kolejnych skanow"
            ),
            expected_outcome=(
                f"retention_rate wzrosnie powyzej {LOW_RETENTION_THRESHOLD}"
            ),
            risk_assessment="MEDIUM: wyzszy prog = trudniejsze egzaminy, odwracalne",
            trigger_data={"retention_rate": retention, "streak": self._low_retention_streak},
        )

    def _rule_consecutive_failures(
        self,
        k4_metrics: Dict[str, float],
        k4_recs: List[str],
        k9_patterns: Dict[str, Any],
    ) -> Optional[Proposal]:
        """
        CONSECUTIVE_FAILURES: K9 exam failures >= 3
        -> propose lowering EXAM_PASS_THRESHOLD -0.05
        """
        consecutive = k9_patterns.get("consecutive_failures", {})
        exam_failures = consecutive.get("exam", 0)

        if exam_failures < CONSECUTIVE_FAILURE_THRESHOLD:
            return None

        spec = parameter_registry.get_parameter("config.EXAM_PASS_THRESHOLD")
        if spec is None:
            return None

        new_value = round(spec.current_value - spec.step, 2)
        if not parameter_registry.validate_value(spec.param_id, new_value):
            return None

        return create_proposal(
            source=ProposalSource.K9_PATTERN,
            parameter_id=spec.param_id,
            current_value=spec.current_value,
            proposed_value=new_value,
            hypothesis=(
                f"Obnizenie EXAM_PASS_THRESHOLD z {spec.current_value} "
                f"do {new_value} zmniejszy liczbe porazek"
            ),
            rationale=(
                f"K9 wykryl {exam_failures} kolejnych porazek "
                f"egzaminowych (prog: {CONSECUTIVE_FAILURE_THRESHOLD})"
            ),
            expected_outcome="mniej consecutive failures, plynniejsza nauka",
            risk_assessment="MEDIUM: nizszy prog = latwiejsze egzaminy, odwracalne",
            trigger_data={"exam_failures": exam_failures},
        )

    def _rule_high_coverage(
        self,
        k4_metrics: Dict[str, float],
        k4_recs: List[str],
        k9_patterns: Dict[str, Any],
    ) -> Optional[Proposal]:
        """
        HIGH_COVERAGE: coverage > 0.9 + no new files
        -> propose decreasing ROUTINE_INTERVAL_TICKS (faster planning)
        """
        coverage = k4_metrics.get("knowledge_coverage", 0.0)
        new_files = k4_metrics.get("new_files_count", 0)

        if coverage < HIGH_COVERAGE_THRESHOLD:
            return None
        if new_files > 0:
            return None

        spec = parameter_registry.get_parameter("planner.ROUTINE_INTERVAL_TICKS")
        if spec is None:
            return None

        new_value = int(spec.current_value - spec.step)
        if not parameter_registry.validate_value(spec.param_id, new_value):
            return None

        return create_proposal(
            source=ProposalSource.K4_RECOMMENDATION,
            parameter_id=spec.param_id,
            current_value=spec.current_value,
            proposed_value=new_value,
            hypothesis=(
                f"Skrocenie interwalu planera z {spec.current_value} "
                f"do {new_value} tickow przyspieszy przetwarzanie"
            ),
            rationale=(
                f"K4: coverage={coverage:.0%}, brak nowych plikow. "
                f"System jest w fazie konsolidacji, szybszy planer moze pomoc."
            ),
            expected_outcome="szybsza reakcja planera na zmiany",
            risk_assessment="LOW: zmiana timing, odwracalne, brak wplywu na dane",
            trigger_data={"coverage": coverage, "new_files": new_files},
        )

    def _rule_slow_execution(
        self,
        k4_metrics: Dict[str, float],
        k4_recs: List[str],
        k9_patterns: Dict[str, Any],
    ) -> Optional[Proposal]:
        """
        SLOW_EXECUTION: K9 slow_execution lessons >= 3
        -> propose decreasing TARGET_CHUNK_SIZE by step
        """
        # Count slow_execution lessons from k9 patterns
        wrong_assumptions = k9_patterns.get("wrong_assumptions", {})
        # Lessons are tracked differently - check for slow pattern
        slow_count = 0
        recent_lessons = k9_patterns.get("recent_lessons", [])
        for lesson in recent_lessons:
            if isinstance(lesson, dict):
                if lesson.get("lesson_type") == "slow_execution":
                    slow_count += 1
            elif isinstance(lesson, str) and "slow" in lesson.lower():
                slow_count += 1

        if slow_count < SLOW_EXECUTION_LESSON_COUNT:
            return None

        spec = parameter_registry.get_parameter("config.TARGET_CHUNK_SIZE")
        if spec is None:
            return None

        new_value = int(spec.current_value - 200)
        if not parameter_registry.validate_value(spec.param_id, new_value):
            return None

        return create_proposal(
            source=ProposalSource.K9_PATTERN,
            parameter_id=spec.param_id,
            current_value=spec.current_value,
            proposed_value=new_value,
            hypothesis=(
                f"Zmniejszenie TARGET_CHUNK_SIZE z {spec.current_value} "
                f"do {new_value} przyspieszy przetwarzanie chunkow"
            ),
            rationale=(
                f"K9 zarejestrowa {slow_count} lekcji 'slow_execution' "
                f"(prog: {SLOW_EXECUTION_LESSON_COUNT}). "
                f"Mniejsze chunki = szybszy inference LLM."
            ),
            expected_outcome="krotszy czas przetwarzania chunkow",
            risk_assessment="MEDIUM: mniejsze chunki = wiecej iteracji, odwracalne",
            trigger_data={"slow_count": slow_count},
        )

    # ── Helpers ──────────────────────────────────────────────────

    def _is_on_cooldown(self, parameter_id: str) -> bool:
        """Check if we recently proposed a change to this parameter."""
        now = time.time()
        for p in reversed(self._proposals):
            if (p.parameter_id == parameter_id
                    and now - p.timestamp < PROPOSAL_COOLDOWN_SEC):
                return True
        return False

    def _count_today_proposals(self) -> int:
        """Count proposals created today."""
        today_start = time.time() - 86400
        return sum(
            1 for p in self._proposals
            if p.timestamp >= today_start
        )

    # ── Persistence ──────────────────────────────────────────────

    def _load_proposals(self) -> List[Proposal]:
        """Load proposals from JSONL."""
        if not self._proposals_path.exists():
            return []

        proposals = []
        try:
            with open(self._proposals_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            proposals.append(Proposal.from_dict(json.loads(line)))
                        except (json.JSONDecodeError, KeyError, ValueError):
                            continue
        except OSError:
            pass
        return proposals

    def _save_proposal(self, proposal: Proposal) -> None:
        """Append a single proposal to JSONL."""
        try:
            self._proposals_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._proposals_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(proposal.to_dict(), ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning(f"Failed to save proposal: {e}")

    def _rewrite_proposals(self) -> None:
        """Rewrite entire proposals file (after status update)."""
        try:
            self._proposals_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._proposals_path, "w", encoding="utf-8") as f:
                for p in self._proposals:
                    f.write(json.dumps(p.to_dict(), ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning(f"Failed to rewrite proposals: {e}")
