"""
Storage Manager - persistent data management for M.A.R.I.A.

Manages two storage tiers:
- Active (SSD): meta_data/ - current logs, fast access
- Archive (HDD): /mnt/storage/ - historical data, compacted summaries

Key components:
- LogArchiver: rotates and compacts JSONL logs nightly
- DailySummary: compresses a day of events into one record

Designed to run during SLEEP phase (SleepProcessor integration).
"""

import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default paths
ACTIVE_DIR = Path("meta_data")
ARCHIVE_DIR = Path("/mnt/storage/data")
ARCHIVE_LOGS_DIR = ARCHIVE_DIR / "logs"
ARCHIVE_SUMMARIES_DIR = ARCHIVE_DIR / "summaries"


class DailySummary:
    """
    Compacts a day of JSONL records into a single summary record.

    Each log type has its own compaction logic:
    - homeostasis_events: health stats (min/max/avg), mode distribution, alert count
    - planner_decisions: action counts, goal distribution, success rate
    - reflections: outcome match rate, lessons learned
    """

    @staticmethod
    def summarize_homeostasis(records: List[Dict]) -> Dict[str, Any]:
        """Compact homeostasis state_snapshots into daily stats."""
        if not records:
            return {"count": 0}

        snapshots = [r for r in records if r.get("event_type") == "state_snapshot"]
        if not snapshots:
            return {"count": len(records), "snapshots": 0}

        healths = [s["health_score"] for s in snapshots if "health_score" in s]
        modes = {}
        for s in snapshots:
            m = s.get("mode", "unknown")
            modes[m] = modes.get(m, 0) + 1

        metrics_keys = ["ram_available_pct", "cpu_load", "temp_c", "process_rss_mb"]
        metrics_summary = {}
        for key in metrics_keys:
            vals = [s["metrics"][key] for s in snapshots
                    if "metrics" in s and key in s["metrics"]]
            if vals:
                metrics_summary[key] = {
                    "min": round(min(vals), 2),
                    "max": round(max(vals), 2),
                    "avg": round(sum(vals) / len(vals), 2),
                }

        alerts = sum(s.get("alerts_count", 0) for s in snapshots)

        return {
            "count": len(records),
            "snapshots": len(snapshots),
            "health": {
                "min": round(min(healths), 3) if healths else 0,
                "max": round(max(healths), 3) if healths else 0,
                "avg": round(sum(healths) / len(healths), 3) if healths else 0,
            },
            "modes": modes,
            "metrics": metrics_summary,
            "total_alerts": alerts,
        }

    @staticmethod
    def summarize_planner(records: List[Dict]) -> Dict[str, Any]:
        """Compact planner decisions into daily stats."""
        if not records:
            return {"count": 0}

        action_counts = {}
        status_counts = {}
        goal_counts = {}
        total_duration = 0.0

        for r in records:
            a = r.get("action_type", "unknown")
            action_counts[a] = action_counts.get(a, 0) + 1
            s = r.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1
            g = r.get("goal_id", "unknown")
            goal_counts[g] = goal_counts.get(g, 0) + 1
            total_duration += r.get("duration_ms", 0)

        # Exam stats
        exams = [r for r in records if r.get("action_type") == "exam"]
        exam_stats = {}
        if exams:
            results = [r.get("result", {}) for r in exams]
            total_run = sum(r.get("exams_run", 0) for r in results)
            total_passed = sum(r.get("exams_passed", 0) for r in results)
            exam_stats = {
                "sessions": len(exams),
                "total_run": total_run,
                "total_passed": total_passed,
                "pass_rate": round(total_passed / max(total_run, 1), 3),
            }

        return {
            "count": len(records),
            "actions": action_counts,
            "statuses": status_counts,
            "goals": goal_counts,
            "total_duration_ms": round(total_duration, 1),
            "exam_stats": exam_stats,
        }

    @staticmethod
    def summarize_reflections(records: List[Dict]) -> Dict[str, Any]:
        """Compact reflections into daily stats."""
        if not records:
            return {"count": 0}

        outcomes = {}
        for r in records:
            o = r.get("outcome_match", "unknown")
            outcomes[o] = outcomes.get(o, 0) + 1

        lessons = []
        for r in records:
            for lesson in r.get("lessons", []):
                if lesson:
                    lessons.append(lesson)

        conf_before = [r["confidence_before"] for r in records
                       if r.get("confidence_before") is not None]
        conf_after = [r["confidence_after"] for r in records
                      if r.get("confidence_after") is not None]

        return {
            "count": len(records),
            "outcomes": outcomes,
            "lessons_count": len(lessons),
            "lessons": lessons[:10],  # keep top 10
            "confidence": {
                "avg_before": round(sum(conf_before) / max(len(conf_before), 1), 3),
                "avg_after": round(sum(conf_after) / max(len(conf_after), 1), 3),
            } if conf_before else {},
        }

    @staticmethod
    def summarize_generic(records: List[Dict]) -> Dict[str, Any]:
        """Generic summary for logs without specialized compaction."""
        return {"count": len(records)}


class LogArchiver:
    """
    Rotates and compacts JSONL log files.

    Pipeline (runs during SLEEP):
    1. For each managed log file:
       a. Read all records
       b. Split into: today's records vs older records
       c. Compact older records into daily summaries
       d. Archive raw old records to /mnt/storage/data/logs/
       e. Keep only today's records in active meta_data/
       f. Save summaries to /mnt/storage/data/summaries/

    Safe: reads before writing, keeps originals in archive.
    """

    # Which files to manage and how to summarize them
    MANAGED_LOGS = {
        "homeostasis_events.jsonl": {
            "summarizer": "homeostasis",
            "ts_field": "timestamp",
            "min_age_days": 1,
        },
        "planner_decisions.jsonl": {
            "summarizer": "planner",
            "ts_field": "timestamp",
            "min_age_days": 1,
        },
        "reflections.jsonl": {
            "summarizer": "reflections",
            "ts_field": "timestamp_finished",
            "min_age_days": 1,
        },
        "action_audit.jsonl": {
            "summarizer": "generic",
            "ts_field": "timestamp",
            "min_age_days": 2,
        },
        "evaluation_reports.jsonl": {
            "summarizer": "generic",
            "ts_field": "timestamp",
            "min_age_days": 2,
        },
        "autonomy_decisions.jsonl": {
            "summarizer": "generic",
            "ts_field": "timestamp",
            "min_age_days": 2,
        },
        "teacher_plans.jsonl": {
            "summarizer": "generic",
            "ts_field": "timestamp",
            "min_age_days": 3,
        },
        "decision_traces.jsonl": {
            "summarizer": "generic",
            "ts_field": "started_at",
            "min_age_days": 7,
        },
        "critique_reports.jsonl": {
            "summarizer": "generic",
            "ts_field": "timestamp",
            "min_age_days": 7,
        },
        "creative_events.jsonl": {
            "summarizer": "generic",
            "ts_field": "timestamp",
            "min_age_days": 7,
        },
        "dream_log.jsonl": {
            "summarizer": "generic",
            "ts_field": "timestamp",
            "min_age_days": 7,
        },
    }

    SUMMARIZERS = {
        "homeostasis": DailySummary.summarize_homeostasis,
        "planner": DailySummary.summarize_planner,
        "reflections": DailySummary.summarize_reflections,
        "generic": DailySummary.summarize_generic,
    }

    def __init__(
        self,
        active_dir: Optional[Path] = None,
        archive_dir: Optional[Path] = None,
    ):
        self._active_dir = Path(active_dir or ACTIVE_DIR)
        archive_root = Path(archive_dir or ARCHIVE_DIR)
        self._archive_logs = archive_root / "logs"
        self._archive_summaries = archive_root / "summaries"

    def run_archival(self) -> Dict[str, Any]:
        """
        Run full archival cycle for all managed logs.

        Returns:
            Stats dict with per-file results.
        """
        # Ensure archive dirs exist
        self._archive_logs.mkdir(parents=True, exist_ok=True)
        self._archive_summaries.mkdir(parents=True, exist_ok=True)

        results = {}
        for filename, config in self.MANAGED_LOGS.items():
            try:
                result = self._archive_file(filename, config)
                results[filename] = result
            except Exception as e:
                logger.warning(f"Archival failed for {filename}: {e}")
                results[filename] = {"error": str(e)}

        total_archived = sum(
            r.get("archived_records", 0) for r in results.values()
            if isinstance(r, dict) and "archived_records" in r
        )
        total_kept = sum(
            r.get("kept_records", 0) for r in results.values()
            if isinstance(r, dict) and "kept_records" in r
        )

        logger.info(
            f"Archival complete: {total_archived} records archived, "
            f"{total_kept} kept active"
        )

        return {
            "timestamp": time.time(),
            "files": results,
            "total_archived": total_archived,
            "total_kept": total_kept,
        }

    def _archive_file(self, filename: str, config: Dict) -> Dict[str, Any]:
        """Archive a single JSONL file."""
        active_path = self._active_dir / filename
        if not active_path.exists():
            return {"skipped": True, "reason": "file not found"}

        ts_field = config["ts_field"]
        min_age_days = config["min_age_days"]
        summarizer_name = config["summarizer"]
        summarizer_fn = self.SUMMARIZERS.get(summarizer_name, DailySummary.summarize_generic)

        # 1. Read all records
        records = self._read_jsonl(active_path)
        if not records:
            return {"skipped": True, "reason": "empty file"}

        # 2. Split: today vs old
        cutoff = time.time() - (min_age_days * 86400)
        recent = []
        old = []
        for r in records:
            ts = r.get(ts_field, 0)
            if isinstance(ts, (int, float)) and ts >= cutoff:
                recent.append(r)
            else:
                old.append(r)

        if not old:
            return {"skipped": True, "reason": "no old records", "total": len(records)}

        # 3. Group old records by date
        daily_groups = self._group_by_date(old, ts_field)

        # 4. Create daily summaries
        summaries = []
        for date_str, day_records in daily_groups.items():
            summary = {
                "date": date_str,
                "source": filename,
                "summary": summarizer_fn(day_records),
                "created_at": time.time(),
            }
            summaries.append(summary)

        # 5. Archive raw old records
        archive_path = self._archive_logs / filename
        self._append_jsonl(archive_path, old)

        # 6. Save summaries
        stem = filename.replace(".jsonl", "")
        summary_path = self._archive_summaries / f"{stem}_daily.jsonl"
        self._append_jsonl(summary_path, summaries)

        # 7. Rewrite active file with only recent records
        self._write_jsonl(active_path, recent)

        return {
            "archived_records": len(old),
            "kept_records": len(recent),
            "daily_summaries": len(summaries),
            "dates_archived": list(daily_groups.keys()),
        }

    def _group_by_date(self, records: List[Dict], ts_field: str) -> Dict[str, List[Dict]]:
        """Group records by date string."""
        groups = {}
        for r in records:
            ts = r.get(ts_field, 0)
            if isinstance(ts, (int, float)) and ts > 0:
                date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            else:
                date_str = "unknown"
            if date_str not in groups:
                groups[date_str] = []
            groups[date_str].append(r)
        return groups

    @staticmethod
    def _read_jsonl(path: Path, max_lines: int = 50000) -> List[Dict]:
        """Read JSONL file with bounded line count."""
        records = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i >= max_lines:
                        break
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError:
            pass
        return records

    @staticmethod
    def _write_jsonl(path: Path, records: List[Dict]) -> None:
        """Overwrite JSONL file with records."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    @staticmethod
    def _append_jsonl(path: Path, records: List[Dict]) -> None:
        """Append records to JSONL file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def get_archive_stats(self) -> Dict[str, Any]:
        """Get stats about archived data."""
        stats = {}
        if self._archive_logs.exists():
            for f in self._archive_logs.iterdir():
                if f.suffix == ".jsonl":
                    size = f.stat().st_size
                    stats[f.name] = {"size_bytes": size, "size_mb": round(size / 1048576, 2)}

        summary_stats = {}
        if self._archive_summaries.exists():
            for f in self._archive_summaries.iterdir():
                if f.suffix == ".jsonl":
                    lines = sum(1 for _ in open(f, encoding="utf-8"))
                    summary_stats[f.name] = {"daily_records": lines}

        return {
            "archive_logs": stats,
            "summaries": summary_stats,
        }
