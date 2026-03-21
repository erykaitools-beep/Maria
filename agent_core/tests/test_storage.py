"""Tests for agent_core/storage/ - LogArchiver + DailySummary."""

import json
import time
import pytest
from pathlib import Path

from agent_core.storage import LogArchiver, DailySummary


# ── DailySummary tests ──────────────────────────────────────


class TestDailySummaryHomeostasis:
    def test_empty(self):
        result = DailySummary.summarize_homeostasis([])
        assert result["count"] == 0

    def test_basic_stats(self):
        records = [
            {
                "event_type": "state_snapshot",
                "health_score": 0.95,
                "mode": "active",
                "alerts_count": 0,
                "metrics": {
                    "ram_available_pct": 80.0,
                    "cpu_load": 0.1,
                    "temp_c": 35.0,
                    "process_rss_mb": 64.0,
                },
            },
            {
                "event_type": "state_snapshot",
                "health_score": 0.85,
                "mode": "active",
                "alerts_count": 1,
                "metrics": {
                    "ram_available_pct": 70.0,
                    "cpu_load": 0.5,
                    "temp_c": 55.0,
                    "process_rss_mb": 80.0,
                },
            },
        ]
        result = DailySummary.summarize_homeostasis(records)
        assert result["snapshots"] == 2
        assert result["health"]["min"] == 0.85
        assert result["health"]["max"] == 0.95
        assert result["modes"] == {"active": 2}
        assert result["total_alerts"] == 1
        assert result["metrics"]["cpu_load"]["avg"] == 0.3

    def test_mixed_events(self):
        records = [
            {"event_type": "mode_change", "from": "active", "to": "sleep"},
            {
                "event_type": "state_snapshot",
                "health_score": 0.9,
                "mode": "sleep",
                "alerts_count": 0,
                "metrics": {
                    "ram_available_pct": 90.0,
                    "cpu_load": 0.05,
                    "temp_c": 30.0,
                    "process_rss_mb": 60.0,
                },
            },
        ]
        result = DailySummary.summarize_homeostasis(records)
        assert result["count"] == 2
        assert result["snapshots"] == 1


class TestDailySummaryPlanner:
    def test_empty(self):
        assert DailySummary.summarize_planner([])["count"] == 0

    def test_action_counts(self):
        records = [
            {"action_type": "learn", "status": "completed", "goal_id": "g1", "duration_ms": 100},
            {"action_type": "exam", "status": "completed", "goal_id": "g1", "duration_ms": 50,
             "result": {"exams_run": 3, "exams_passed": 2}},
            {"action_type": "learn", "status": "completed", "goal_id": "g1", "duration_ms": 80},
        ]
        result = DailySummary.summarize_planner(records)
        assert result["count"] == 3
        assert result["actions"]["learn"] == 2
        assert result["actions"]["exam"] == 1
        assert result["exam_stats"]["total_run"] == 3
        assert result["exam_stats"]["total_passed"] == 2
        assert result["total_duration_ms"] == 230.0


class TestDailySummaryReflections:
    def test_empty(self):
        assert DailySummary.summarize_reflections([])["count"] == 0

    def test_outcomes_and_lessons(self):
        records = [
            {
                "outcome_match": "match",
                "confidence_before": 0.8,
                "confidence_after": 0.9,
                "lessons": [],
            },
            {
                "outcome_match": "mismatch",
                "confidence_before": 0.7,
                "confidence_after": 0.5,
                "lessons": [{"type": "slow", "message": "too slow"}],
            },
        ]
        result = DailySummary.summarize_reflections(records)
        assert result["count"] == 2
        assert result["outcomes"]["match"] == 1
        assert result["outcomes"]["mismatch"] == 1
        assert result["lessons_count"] == 1
        assert result["confidence"]["avg_before"] == 0.75


# ── LogArchiver tests ───────────────────────────────────────


class TestLogArchiver:
    def _write_jsonl(self, path: Path, records: list):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def _read_jsonl(self, path: Path) -> list:
        if not path.exists():
            return []
        records = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def test_archive_empty_file(self, tmp_path):
        active = tmp_path / "active"
        archive = tmp_path / "archive"
        active.mkdir()
        (active / "homeostasis_events.jsonl").write_text("")

        archiver = LogArchiver(active_dir=active, archive_dir=archive)
        result = archiver.run_archival()
        assert result["total_archived"] == 0

    def test_archive_no_old_records(self, tmp_path):
        active = tmp_path / "active"
        archive = tmp_path / "archive"

        # All records are recent (timestamp = now)
        now = time.time()
        records = [
            {"timestamp": now, "event_type": "state_snapshot",
             "health_score": 0.9, "mode": "active", "alerts_count": 0,
             "metrics": {"ram_available_pct": 90, "cpu_load": 0.1,
                         "temp_c": 30, "process_rss_mb": 60}},
        ]
        self._write_jsonl(active / "homeostasis_events.jsonl", records)

        archiver = LogArchiver(active_dir=active, archive_dir=archive)
        result = archiver.run_archival()
        assert result["total_archived"] == 0
        assert result["total_kept"] == 0  # skipped files don't count

    def test_archive_splits_old_and_recent(self, tmp_path):
        active = tmp_path / "active"
        archive = tmp_path / "archive"

        now = time.time()
        old_ts = now - 3 * 86400  # 3 days ago
        records = [
            {"timestamp": old_ts, "event_type": "state_snapshot",
             "health_score": 0.8, "mode": "active", "alerts_count": 0,
             "metrics": {"ram_available_pct": 80, "cpu_load": 0.2,
                         "temp_c": 40, "process_rss_mb": 70}},
            {"timestamp": old_ts + 60, "event_type": "state_snapshot",
             "health_score": 0.85, "mode": "active", "alerts_count": 0,
             "metrics": {"ram_available_pct": 82, "cpu_load": 0.15,
                         "temp_c": 38, "process_rss_mb": 68}},
            {"timestamp": now, "event_type": "state_snapshot",
             "health_score": 0.95, "mode": "active", "alerts_count": 0,
             "metrics": {"ram_available_pct": 90, "cpu_load": 0.1,
                         "temp_c": 30, "process_rss_mb": 60}},
        ]
        self._write_jsonl(active / "homeostasis_events.jsonl", records)

        archiver = LogArchiver(active_dir=active, archive_dir=archive)
        result = archiver.run_archival()

        # 2 old records archived, 1 recent kept
        homeo = result["files"]["homeostasis_events.jsonl"]
        assert homeo["archived_records"] == 2
        assert homeo["kept_records"] == 1
        assert homeo["daily_summaries"] == 1

        # Active file now has only 1 record
        active_records = self._read_jsonl(active / "homeostasis_events.jsonl")
        assert len(active_records) == 1
        assert active_records[0]["health_score"] == 0.95

        # Archive has 2 raw records
        archive_records = self._read_jsonl(archive / "logs" / "homeostasis_events.jsonl")
        assert len(archive_records) == 2

        # Summary exists
        summary_records = self._read_jsonl(
            archive / "summaries" / "homeostasis_events_daily.jsonl"
        )
        assert len(summary_records) == 1
        assert summary_records[0]["summary"]["snapshots"] == 2

    def test_archive_planner_decisions(self, tmp_path):
        active = tmp_path / "active"
        archive = tmp_path / "archive"

        now = time.time()
        old_ts = now - 2 * 86400
        records = [
            {"timestamp": old_ts, "action_type": "learn", "status": "completed",
             "goal_id": "g1", "duration_ms": 100},
            {"timestamp": old_ts, "action_type": "exam", "status": "completed",
             "goal_id": "g1", "duration_ms": 50,
             "result": {"exams_run": 5, "exams_passed": 4}},
            {"timestamp": now, "action_type": "learn", "status": "completed",
             "goal_id": "g1", "duration_ms": 80},
        ]
        self._write_jsonl(active / "planner_decisions.jsonl", records)

        archiver = LogArchiver(active_dir=active, archive_dir=archive)
        result = archiver.run_archival()

        planner = result["files"]["planner_decisions.jsonl"]
        assert planner["archived_records"] == 2
        assert planner["kept_records"] == 1

        # Check summary has exam stats
        summaries = self._read_jsonl(
            archive / "summaries" / "planner_decisions_daily.jsonl"
        )
        assert summaries[0]["summary"]["exam_stats"]["total_run"] == 5

    def test_archive_preserves_data(self, tmp_path):
        """Archival never loses data - raw records always in archive."""
        active = tmp_path / "active"
        archive = tmp_path / "archive"

        now = time.time()
        old_ts = now - 5 * 86400
        records = [
            {"timestamp": old_ts + i * 60, "event_type": "state_snapshot",
             "health_score": 0.9, "mode": "active", "alerts_count": 0,
             "metrics": {"ram_available_pct": 90, "cpu_load": 0.1,
                         "temp_c": 30, "process_rss_mb": 60}}
            for i in range(100)
        ]
        self._write_jsonl(active / "homeostasis_events.jsonl", records)

        archiver = LogArchiver(active_dir=active, archive_dir=archive)
        archiver.run_archival()

        # All 100 raw records in archive
        archived = self._read_jsonl(archive / "logs" / "homeostasis_events.jsonl")
        assert len(archived) == 100

        # Active file is empty (all records were old)
        active_records = self._read_jsonl(active / "homeostasis_events.jsonl")
        assert len(active_records) == 0

    def test_archive_idempotent(self, tmp_path):
        """Running archival twice doesn't duplicate data."""
        active = tmp_path / "active"
        archive = tmp_path / "archive"

        now = time.time()
        records = [
            {"timestamp": now - 3 * 86400, "event_type": "state_snapshot",
             "health_score": 0.9, "mode": "active", "alerts_count": 0,
             "metrics": {"ram_available_pct": 90, "cpu_load": 0.1,
                         "temp_c": 30, "process_rss_mb": 60}},
            {"timestamp": now, "event_type": "state_snapshot",
             "health_score": 0.95, "mode": "active", "alerts_count": 0,
             "metrics": {"ram_available_pct": 92, "cpu_load": 0.05,
                         "temp_c": 28, "process_rss_mb": 58}},
        ]
        self._write_jsonl(active / "homeostasis_events.jsonl", records)

        archiver = LogArchiver(active_dir=active, archive_dir=archive)

        # First run
        archiver.run_archival()
        # Second run - should have nothing to archive
        result2 = archiver.run_archival()
        assert result2["total_archived"] == 0

        # Archive still has exactly 1 record (not duplicated)
        archived = self._read_jsonl(archive / "logs" / "homeostasis_events.jsonl")
        assert len(archived) == 1

    def test_archive_stats(self, tmp_path):
        active = tmp_path / "active"
        archive = tmp_path / "archive"

        now = time.time()
        records = [
            {"timestamp": now - 3 * 86400, "event_type": "state_snapshot",
             "health_score": 0.9, "mode": "active", "alerts_count": 0,
             "metrics": {"ram_available_pct": 90, "cpu_load": 0.1,
                         "temp_c": 30, "process_rss_mb": 60}},
        ]
        self._write_jsonl(active / "homeostasis_events.jsonl", records)

        archiver = LogArchiver(active_dir=active, archive_dir=archive)
        archiver.run_archival()

        stats = archiver.get_archive_stats()
        assert "homeostasis_events.jsonl" in stats["archive_logs"]
        assert "homeostasis_events_daily.jsonl" in stats["summaries"]

    def test_missing_storage_graceful(self, tmp_path):
        """Archiver handles missing files gracefully."""
        active = tmp_path / "active"
        archive = tmp_path / "archive"
        active.mkdir()

        archiver = LogArchiver(active_dir=active, archive_dir=archive)
        result = archiver.run_archival()
        # All files skipped, no errors
        assert result["total_archived"] == 0

    def test_multiple_days_grouped(self, tmp_path):
        active = tmp_path / "active"
        archive = tmp_path / "archive"

        now = time.time()
        records = [
            {"timestamp": now - 5 * 86400, "event_type": "state_snapshot",
             "health_score": 0.8, "mode": "active", "alerts_count": 0,
             "metrics": {"ram_available_pct": 80, "cpu_load": 0.2,
                         "temp_c": 40, "process_rss_mb": 70}},
            {"timestamp": now - 3 * 86400, "event_type": "state_snapshot",
             "health_score": 0.9, "mode": "active", "alerts_count": 0,
             "metrics": {"ram_available_pct": 90, "cpu_load": 0.1,
                         "temp_c": 30, "process_rss_mb": 60}},
            {"timestamp": now, "event_type": "state_snapshot",
             "health_score": 0.95, "mode": "active", "alerts_count": 0,
             "metrics": {"ram_available_pct": 92, "cpu_load": 0.05,
                         "temp_c": 28, "process_rss_mb": 58}},
        ]
        self._write_jsonl(active / "homeostasis_events.jsonl", records)

        archiver = LogArchiver(active_dir=active, archive_dir=archive)
        result = archiver.run_archival()

        homeo = result["files"]["homeostasis_events.jsonl"]
        assert homeo["archived_records"] == 2
        assert homeo["daily_summaries"] == 2  # two different days
        assert len(homeo["dates_archived"]) == 2
