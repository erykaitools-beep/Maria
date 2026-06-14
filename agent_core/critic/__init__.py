"""
Faza G: CriticAgent - Knowledge Quality Gate.

Analyzes Maria's knowledge for coherence, calibration, support depth,
dispute state, exam coverage, and freshness. NOT a truth engine.

Pipeline: KnowledgeCritic.analyze() -> CritiqueApplier.apply() -> persist

Usage:
    critic = CriticAgent(project_root="/home/maria/maria")
    critic.set_belief_store(belief_store)
    critic.set_goal_store(goal_store)

    report = critic.run_critique()
    # report.findings -> list of CritiqueFinding
    # report.goals_created -> list of goal IDs

ADR-028: Coherence/calibration critic, not truth engine.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .critique_model import (
    CritiqueReport,
    CritiqueFinding,
    DEFAULT_CRITIQUE_COOLDOWN_SEC,
    MAX_FINDINGS_PER_REPORT,
)
from .knowledge_critic import KnowledgeCritic
from .critique_applier import CritiqueApplier

logger = logging.getLogger(__name__)

_REPORTS_FILENAME = "critique_reports.jsonl"


class CriticAgent:
    """
    Faza G: Knowledge quality gate facade.

    Orchestrates: analyze knowledge -> apply findings -> persist report.
    All goals created as PROPOSED (human gate).
    """

    def __init__(
        self,
        project_root: str = ".",
        cooldown_sec: float = DEFAULT_CRITIQUE_COOLDOWN_SEC,
    ):
        self._root = Path(project_root)
        self._meta = self._root / "meta_data"
        self._reports_path = self._meta / _REPORTS_FILENAME
        self._cooldown_sec = cooldown_sec

        # Subsystems (wired via dependency injection)
        self._belief_store = None
        self._dispute_log = None
        self._applier = CritiqueApplier()

        self._last_critique_ts: float = 0.0
        self._load_last_timestamp()

    # --- Dependency injection ---

    def set_belief_store(self, store):
        """Set K6 BeliefStore (required for analysis)."""
        self._belief_store = store

    def set_dispute_log(self, log):
        """Set Faza F DisputeLog (optional, for dispute analysis)."""
        self._dispute_log = log

    def set_goal_store(self, store):
        """Deprecated (R1): retained for wiring compat; critic uses bulletin."""
        self._applier.set_goal_store(store)

    def set_bulletin_store(self, store):
        """Set the bulletin board for NEED_REVIEW advisories (R1)."""
        self._applier.set_bulletin_store(store)

    def set_llm_fn(self, fn: Callable[[str], str]):
        """Set LLM function for summary decoration."""
        self._applier.set_llm_fn(fn)

    # --- Main API ---

    def run_critique(self, trigger: str = "periodic") -> CritiqueReport:
        """
        Run full critique cycle:
        1. Analyze knowledge (KnowledgeCritic, rule-based, READ-ONLY)
        2. Apply findings (CritiqueApplier, creates PROPOSED goals)
        3. Persist report to JSONL

        Returns CritiqueReport (always, even on failure).
        """
        logger.info("[Critic] Starting critique cycle (trigger=%s)", trigger)
        start = time.time()

        report = CritiqueReport(trigger=trigger)

        try:
            # 1. Analyze (READ-ONLY, zero side effects)
            critic = KnowledgeCritic(
                belief_store=self._belief_store,
                dispute_log=self._dispute_log,
                project_root=str(self._root),
            )
            findings, total = critic.analyze()

            report.findings = findings
            report.findings_total = total
            report.suppressed_duplicates = total - len(findings)

            # Compute stats
            by_cat: Dict[str, int] = {}
            by_sev: Dict[str, int] = {}
            for f in findings:
                by_cat[f.category] = by_cat.get(f.category, 0) + 1
                by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
            report.findings_by_category = by_cat
            report.findings_by_severity = by_sev

            logger.info(
                "[Critic] Analysis: %d findings (%d total, %d suppressed)",
                len(findings), total, report.suppressed_duplicates,
            )

            # 2. Apply (create PROPOSED goals + optional LLM summary)
            if findings:
                apply_result = self._applier.apply(report)
                logger.info(
                    "[Critic] Applied: %d goals created",
                    len(apply_result["goals_created"]),
                )

        except Exception as e:
            report.error = str(e)
            logger.error("[Critic] Critique cycle failed: %s", e)

        # 3. Persist
        report.duration_ms = (time.time() - start) * 1000
        self._save_report(report)
        self._last_critique_ts = time.time()

        logger.info(
            "[Critic] Critique complete in %.0fms", report.duration_ms,
        )

        return report

    def should_critique(
        self,
        post_validation: bool = False,
        post_maintenance: bool = False,
    ) -> bool:
        """
        Check if critique should trigger.

        Triggers:
        - Periodic cooldown expired (default 8h)
        - Post-validation event (fresh dispute data available)
        - Post-maintenance event (beliefs just maintained)

        Respects 1-hour minimum between critiques.
        """
        now = time.time()
        since = now - self._last_critique_ts

        # Absolute minimum: 1h
        min_cooldown = 3600
        if since < min_cooldown:
            return False

        # Event-driven triggers (bypass periodic but respect 1h)
        if post_validation:
            logger.info("[Critic] Trigger: post_validation")
            return True

        if post_maintenance:
            logger.info("[Critic] Trigger: post_maintenance")
            return True

        # Periodic trigger
        if since >= self._cooldown_sec:
            logger.info("[Critic] Trigger: periodic (cooldown expired)")
            return True

        return False

    def get_last_report(self) -> Optional[CritiqueReport]:
        """Get most recent critique report from JSONL."""
        if not self._reports_path.exists():
            return None

        last_line = ""
        try:
            with open(self._reports_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        last_line = line.strip()
        except IOError:
            return None

        if not last_line:
            return None

        try:
            return CritiqueReport.from_dict(json.loads(last_line))
        except (json.JSONDecodeError, Exception):
            return None

    def get_status(self) -> Dict[str, Any]:
        """Status dict for REPL / Web UI / Telegram."""
        last_report = self.get_last_report()
        return {
            "available": self._belief_store is not None,
            "last_critique_ts": self._last_critique_ts,
            "cooldown_sec": self._cooldown_sec,
            "last_report_id": last_report.report_id if last_report else None,
            "last_findings": len(last_report.findings) if last_report else 0,
            "last_goals_created": len(last_report.goals_created) if last_report else 0,
            "last_findings_total": last_report.findings_total if last_report else 0,
        }

    # --- Persistence ---

    def _save_report(self, report: CritiqueReport):
        """Append report to JSONL."""
        try:
            self._meta.mkdir(parents=True, exist_ok=True)
            with open(self._reports_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(report.to_dict(), ensure_ascii=False) + "\n")
        except IOError as e:
            logger.error("[Critic] Could not save report: %s", e)

    def _load_last_timestamp(self):
        """Load timestamp of last critique from JSONL."""
        last = self.get_last_report()
        if last:
            self._last_critique_ts = last.timestamp
