"""
K12 Self-Analysis: Closing the Cognitive Loop.

Maria collects her own cognitive state, sends it to a stronger AI model
for analysis, and converts recommendations into PROPOSED learning goals.

Pipeline: StateCollector -> ExternalAnalyzer -> RecommendationApplier

Usage:
    sa = SelfAnalysis(project_root="/home/maria/maria")
    sa.set_llm_fn(router.ask_as_role_fn(ModelRole.PLANNER))
    sa.set_goal_store(goal_store)
    sa.set_world_model(world_model)

    report = sa.run_analysis()
    # report.recommendations -> list of AnalysisRecommendation
    # report.goals_created -> list of goal IDs
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional, Callable

from .recommendation_model import (
    AnalysisReport,
    AnalysisRecommendation,
    AnalyzerBackend,
    MAX_RECOMMENDATIONS_PER_REPORT,
    MAX_PROPOSED_GOALS_FROM_ANALYSIS,
)
from .state_collector import StateCollector
from .external_analyzer import ExternalAnalyzer
from .recommendation_applier import RecommendationApplier

logger = logging.getLogger(__name__)

# Persistence
_REPORTS_FILENAME = "self_analysis_reports.jsonl"

# Cooldown
DEFAULT_COOLDOWN_SEC = 14400  # 4 hours between analyses


class SelfAnalysis:
    """
    K12 Self-Analysis facade.

    Orchestrates: collect state -> analyze -> apply recommendations.
    All goals created as PROPOSED (human gate).
    """

    def __init__(
        self,
        project_root: str = ".",
        cooldown_sec: float = DEFAULT_COOLDOWN_SEC,
    ):
        self._root = Path(project_root)
        self._meta = self._root / "meta_data"
        self._reports_path = self._meta / _REPORTS_FILENAME
        self._cooldown_sec = cooldown_sec

        self._collector = StateCollector(project_root)
        self._analyzer = ExternalAnalyzer()
        self._applier = RecommendationApplier(project_root=project_root)

        self._last_analysis_ts: float = 0.0
        self._load_last_timestamp()

    # --- Dependency injection ---

    def set_llm_fn(self, fn: Callable[[str], str]):
        """Set LLM function for ExternalAnalyzer."""
        self._analyzer.set_llm_fn(fn)

    def set_goal_store(self, store):
        """Set K3 GoalStore for RecommendationApplier."""
        self._applier.set_goal_store(store)

    def set_world_model(self, wm):
        """Set K6 WorldModel for belief updates."""
        self._applier.set_world_model(wm)

    # --- Main API ---

    def run_analysis(self, period_days: int = 7) -> AnalysisReport:
        """
        Run full self-analysis cycle:
        1. Collect compressed state from JSONL logs
        2. Send to external analyzer (stronger model)
        3. Apply recommendations (create PROPOSED goals + topic hints)
        4. Persist report

        Returns AnalysisReport (always, even on failure).
        """
        logger.info("[K12] Starting self-analysis cycle")
        start = time.time()

        # 1. Collect state
        state_summary = self._collector.collect_with_prompt(period_days)
        logger.info(
            f"[K12] State collected: {len(json.dumps(state_summary))} bytes, "
            f"{len(state_summary.get('knowledge_gaps', []))} gaps"
        )

        # 2. Analyze
        report = self._analyzer.analyze(state_summary)

        if report.error:
            logger.warning(f"[K12] Analysis error: {report.error}")
        else:
            logger.info(
                f"[K12] Analysis complete: {len(report.recommendations)} recommendations"
            )

        # 3. Apply recommendations (even if partial)
        if report.recommendations:
            apply_result = self._applier.apply(report)
            logger.info(
                f"[K12] Applied: {len(apply_result['goals_created'])} goals, "
                f"{apply_result['hints_written']} hints"
            )

        # 4. Persist report
        self._save_report(report)
        self._last_analysis_ts = time.time()

        report.duration_ms = (time.time() - start) * 1000
        logger.info(f"[K12] Self-analysis complete in {report.duration_ms:.0f}ms")

        return report

    def should_analyze(
        self,
        needs_human: bool = False,
        retention_rate: Optional[float] = None,
    ) -> bool:
        """
        Check if self-analysis should trigger.

        Triggers when:
        - Cooldown expired (default 24h)
        - K9 signals needs_human()
        - Retention rate dropped below 0.3
        """
        now = time.time()
        since = now - self._last_analysis_ts

        # Absolute minimum: 1 hour between analyses (no matter what)
        min_cooldown = 3600
        if since < min_cooldown:
            return False

        # Event-driven triggers (bypass periodic cooldown but respect 1h minimum)
        if needs_human:
            logger.info("[K12] Trigger: K9 needs_human()")
            return True

        if retention_rate is not None and retention_rate < 0.3:
            logger.info(f"[K12] Trigger: low retention ({retention_rate:.2f})")
            return True

        # Periodic trigger (default 24h)
        if since >= self._cooldown_sec:
            logger.info("[K12] Trigger: periodic (cooldown expired)")
            return True

        return False

    def get_last_report(self) -> Optional[AnalysisReport]:
        """Get most recent analysis report from JSONL."""
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
            return AnalysisReport.from_dict(json.loads(last_line))
        except (json.JSONDecodeError, Exception):
            return None

    def get_status(self) -> Dict[str, Any]:
        """Status dict for REPL / Web UI."""
        last_report = self.get_last_report()
        return {
            "available": self._analyzer._llm_fn is not None,
            "last_analysis_ts": self._last_analysis_ts,
            "cooldown_sec": self._cooldown_sec,
            "last_report_id": last_report.report_id if last_report else None,
            "last_recommendations": len(last_report.recommendations) if last_report else 0,
            "last_goals_created": len(last_report.goals_created) if last_report else 0,
        }

    # --- Persistence ---

    def _save_report(self, report: AnalysisReport):
        """Append report to JSONL."""
        try:
            self._meta.mkdir(parents=True, exist_ok=True)
            with open(self._reports_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(report.to_dict(), ensure_ascii=False) + "\n")
        except IOError as e:
            logger.error(f"[K12] Could not save report: {e}")

    def _load_last_timestamp(self):
        """Load timestamp of last analysis from JSONL."""
        last = self.get_last_report()
        if last:
            self._last_analysis_ts = last.timestamp
