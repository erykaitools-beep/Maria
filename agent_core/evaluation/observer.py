"""
Evaluation Observer - READ-ONLY metrics computation.

Kontrakt: docs/CONTRACTS.md - Kontrakt 4: Agent Evaluation
Pattern: knowledge_analyzer.py (reads JSONL, zero side effects).
Writes ONLY to meta_data/evaluation_reports.jsonl.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.evaluation.report import EvaluationReport, create_report

logger = logging.getLogger(__name__)


class EvaluationObserver:
    """READ-ONLY observer computing 5 key metrics from JSONL sources."""

    def __init__(
        self,
        knowledge_index_path: Path,
        exam_results_path: Path,
        teacher_plans_path: Path,
        homeostasis_events_path: Path,
        personality_experiences_path: Path,
        reports_path: Path,
    ):
        self._paths = {
            "knowledge_index": knowledge_index_path,
            "exam_results": exam_results_path,
            "teacher_plans": teacher_plans_path,
            "homeostasis_events": homeostasis_events_path,
            "personality_experiences": personality_experiences_path,
        }
        self._reports_path = reports_path

    # ---- Main entry point ----

    def generate_report(self, period_hours: float = 1.0) -> EvaluationReport:
        """Generate a full evaluation report. Pure computation, no side effects except report save."""
        now = time.time()
        period_start = now - (period_hours * 3600)

        report = create_report(period_start=period_start, period_end=now)

        # Compute each metric
        lv, lv_details = self._compute_learning_velocity(period_start, now)
        rr, rr_details = self._compute_retention_rate()
        kc, kc_details = self._compute_knowledge_coverage()
        ss, ss_details = self._compute_system_stability(period_start, now)
        pg, pg_details = self._compute_personality_growth()

        report.metrics = {
            "learning_velocity": lv,
            "retention_rate": rr,
            "knowledge_coverage": kc,
            "system_stability": ss,
            "personality_growth": pg,
        }

        report.details = {
            "learning_velocity": lv_details,
            "retention_rate": rr_details,
            "knowledge_coverage": kc_details,
            "system_stability": ss_details,
            "personality_growth": pg_details,
        }

        report.data_sources = {k: str(v) for k, v in self._paths.items()}
        report.recommendations = self._generate_recommendations(report.metrics, report.details)

        # Save report (the ONLY write operation)
        self._save_report(report)

        return report

    # ---- Metric 1: Learning Velocity ----

    def _compute_learning_velocity(
        self, period_start: float, period_end: float
    ) -> tuple:
        """chunks/hour from teacher_plans.jsonl."""
        records = self._read_jsonl(self._paths["teacher_plans"])

        chunks_in_period = 0
        chunks_24h = 0
        cutoff_24h = period_end - 86400

        for rec in records:
            ts = rec.get("timestamp", 0)
            result = rec.get("result", {})
            if not result or not result.get("success"):
                continue
            rtype = result.get("type", "")
            if rtype not in ("learn", "fill_gap"):
                continue

            if ts >= cutoff_24h:
                chunks_24h += 1
            if ts >= period_start:
                chunks_in_period += 1

        period_hours = max((period_end - period_start) / 3600, 0.001)
        velocity = chunks_in_period / period_hours

        # Trend: compare first half vs second half of 24h window
        trend = "stable"
        if chunks_24h > 2:
            mid_24h = cutoff_24h + 43200
            first_half = sum(
                1 for r in records
                if r.get("timestamp", 0) >= cutoff_24h
                and r.get("timestamp", 0) < mid_24h
                and r.get("result", {}).get("success")
                and r.get("result", {}).get("type") in ("learn", "fill_gap")
            )
            second_half = chunks_24h - first_half
            if second_half > first_half * 1.5:
                trend = "increasing"
            elif first_half > second_half * 1.5:
                trend = "decreasing"

        details = {
            "chunks_last_1h": chunks_in_period,
            "chunks_last_24h": chunks_24h,
            "trend": trend,
        }
        return round(velocity, 2), details

    # ---- Metric 2: Retention Rate ----

    def _compute_retention_rate(self) -> tuple:
        """exams_passed / exams_total from exam_results.jsonl."""
        records = self._read_jsonl(self._paths["exam_results"])

        total = len(records)
        # Support both formats: explicit "passed" bool, or derive from score
        passed = sum(
            1 for r in records
            if r.get("passed") is True or r.get("score", 0) >= 0.7
        )

        rate = passed / total if total > 0 else 0.0

        # Last 5 scores
        last_5 = [r.get("score", 0.0) for r in records[-5:]]

        details = {
            "exams_passed": passed,
            "exams_total": total,
            "last_5_scores": last_5,
        }
        return round(rate, 3), details

    # ---- Metric 3: Knowledge Coverage ----

    def _compute_knowledge_coverage(self) -> tuple:
        """completed_files / total_files from knowledge_index.jsonl."""
        records = self._read_jsonl(self._paths["knowledge_index"])

        # knowledge_index uses merge semantics: last record per id wins
        by_id: Dict[str, dict] = {}
        for rec in records:
            fid = rec.get("id") or rec.get("file_id") or rec.get("file", "")
            if fid:
                by_id[fid] = rec

        total = len(by_id)
        completed = sum(
            1 for r in by_id.values()
            if r.get("status") == "completed"
        )
        hard = sum(
            1 for r in by_id.values()
            if r.get("status") == "hard_topic"
        )
        new = sum(
            1 for r in by_id.values()
            if r.get("status") == "new"
        )

        coverage = completed / total if total > 0 else 0.0

        details = {
            "completed_files": completed,
            "total_files": total,
            "hard_topics": hard,
            "new_files": new,
        }
        return round(coverage, 3), details

    # ---- Metric 4: System Stability ----

    def _compute_system_stability(
        self, period_start: float, period_end: float
    ) -> tuple:
        """avg health_score from homeostasis_events.jsonl state_snapshot events."""
        records = self._read_jsonl(self._paths["homeostasis_events"])

        scores_1h = []
        scores_24h = []
        mode_changes_24h = 0
        critical_24h = 0
        cutoff_24h = period_end - 86400

        for rec in records:
            ts = rec.get("ts", rec.get("timestamp", 0))
            event_type = rec.get("event", rec.get("event_type", ""))

            if ts >= cutoff_24h:
                if event_type == "mode_change":
                    mode_changes_24h += 1
                if event_type == "alert" and rec.get("severity") == "CRITICAL":
                    critical_24h += 1

            if event_type == "state_snapshot":
                hs = rec.get("health_score", 0)
                if ts >= cutoff_24h:
                    scores_24h.append(hs)
                if ts >= period_start:
                    scores_1h.append(hs)

        avg_1h = sum(scores_1h) / len(scores_1h) if scores_1h else 0.0
        avg_24h = sum(scores_24h) / len(scores_24h) if scores_24h else 0.0

        # Use 1h average as the primary metric
        stability = avg_1h if scores_1h else avg_24h

        details = {
            "avg_health_1h": round(avg_1h, 3),
            "avg_health_24h": round(avg_24h, 3),
            "mode_changes_24h": mode_changes_24h,
            "critical_alerts_24h": critical_24h,
        }
        return round(stability, 3), details

    # ---- Metric 5: Personality Growth ----

    def _compute_personality_growth(self) -> tuple:
        """Event count deltas from personality_experiences.jsonl."""
        records = self._read_jsonl(self._paths["personality_experiences"])

        if not records:
            return 0.0, {
                "traits_emerged": [],
                "traits_faded": [],
                "total_trait_delta": 0.0,
                "sessions_analyzed": 0,
            }

        # Group events by session
        sessions: Dict[int, Dict[str, int]] = {}
        for rec in records:
            sess = rec.get("session", 0)
            event = rec.get("event", "unknown")
            if sess not in sessions:
                sessions[sess] = {}
            sessions[sess][event] = sessions[sess].get(event, 0) + 1

        # Analyze last 5 sessions for growth
        sorted_sessions = sorted(sessions.keys())
        recent = sorted_sessions[-5:] if len(sorted_sessions) >= 2 else sorted_sessions

        # Event types that indicate traits
        # learning_completed -> curiosity, exam_passed -> persistence
        trait_events = {
            "learning_completed": "ciekawska",     # curiosity
            "exam_passed": "wytrwala",             # persistence
            "exam_failed": "wytrwala",             # persistence (attempts)
            "conversation_turn": "empatyczna",     # empathy
        }

        emerged = []
        faded = []
        total_delta = 0.0

        if len(recent) >= 2:
            first_sess = sessions.get(recent[0], {})
            last_sess = sessions.get(recent[-1], {})

            for event_type, trait_name in trait_events.items():
                old_count = first_sess.get(event_type, 0)
                new_count = last_sess.get(event_type, 0)
                delta = new_count - old_count
                total_delta += abs(delta)

                if delta > 2 and old_count == 0:
                    emerged.append(trait_name)
                elif delta < -2 and new_count == 0:
                    faded.append(trait_name)

        # Normalize to 0-1 range (rough scaling)
        growth = min(total_delta / 10.0, 1.0) if total_delta > 0 else 0.0

        details = {
            "traits_emerged": emerged,
            "traits_faded": faded,
            "total_trait_delta": round(total_delta, 2),
            "sessions_analyzed": len(recent),
        }
        return round(growth, 3), details

    # ---- Recommendations ----

    def _generate_recommendations(
        self, metrics: Dict[str, float], details: Dict[str, Any]
    ) -> List[str]:
        """Threshold-based recommendations. Pure logic, zero LLM."""
        recs = []

        rr = metrics.get("retention_rate", 0)
        if rr < 0.6:
            recs.append("Retention critically low (< 60%) - consider simplifying prompts")
        elif rr < 0.8:
            recs.append("Retention rate < 80% - consider more reviews (P4)")

        lv = metrics.get("learning_velocity", 0)
        if lv == 0:
            chunks_24h = details.get("learning_velocity", {}).get("chunks_last_24h", 0)
            if chunks_24h == 0:
                recs.append("No learning activity in 24h - consider resuming")

        kc = metrics.get("knowledge_coverage", 0)
        if kc > 0.9:
            recs.append("Coverage > 90% - almost everything learned, seek new materials")

        ss = metrics.get("system_stability", 0)
        if ss < 0.7 and ss > 0:
            recs.append("System stability < 70% - check resources")

        pg = metrics.get("personality_growth", 0)
        sessions = details.get("personality_growth", {}).get("sessions_analyzed", 0)
        if pg == 0 and sessions >= 3:
            recs.append("No personality evolution in recent sessions")

        hard = details.get("knowledge_coverage", {}).get("hard_topics", 0)
        if hard >= 2:
            recs.append(f"{hard} hard topics - consider retry after completing more files")

        critical = details.get("system_stability", {}).get("critical_alerts_24h", 0)
        if critical > 0:
            recs.append(f"{critical} critical alerts in 24h - investigate system health")

        return recs

    # ---- I/O helpers ----

    def _read_jsonl(self, path: Path) -> List[dict]:
        """Read JSONL file. Returns empty list if file missing or corrupt."""
        if not path.exists():
            return []
        result = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        result.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        except OSError:
            pass
        return result

    def _save_report(self, report: EvaluationReport) -> None:
        """Append report to evaluation_reports.jsonl."""
        self._reports_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._reports_path, "a", encoding="utf-8") as f:
                line = json.dumps(report.to_dict(), ensure_ascii=False)
                f.write(line + "\n")
        except OSError as e:
            logger.error(f"Cannot write evaluation report: {e}")

    def get_recent_reports(self, limit: int = 5) -> List[EvaluationReport]:
        """Read recent reports from evaluation_reports.jsonl."""
        records = self._read_jsonl(self._reports_path)
        reports = []
        for rec in records[-limit:]:
            try:
                reports.append(EvaluationReport.from_dict(rec))
            except (KeyError, ValueError):
                pass
        return reports
