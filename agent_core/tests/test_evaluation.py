"""Tests for Agent Evaluation (Kontrakt K4)."""

import json
import time
import pytest
from pathlib import Path

from agent_core.evaluation.report import EvaluationReport, create_report
from agent_core.evaluation.observer import EvaluationObserver


# ============================================================
# Helpers
# ============================================================

def write_jsonl(path: Path, records: list):
    """Write list of dicts as JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def make_observer(tmp_path, **overrides):
    """Create observer with default empty JSONL files."""
    paths = {
        "knowledge_index_path": tmp_path / "knowledge_index.jsonl",
        "exam_results_path": tmp_path / "exam_results.jsonl",
        "teacher_plans_path": tmp_path / "teacher_plans.jsonl",
        "homeostasis_events_path": tmp_path / "homeostasis_events.jsonl",
        "personality_experiences_path": tmp_path / "personality_experiences.jsonl",
        "reports_path": tmp_path / "evaluation_reports.jsonl",
    }
    paths.update(overrides)
    return EvaluationObserver(**paths)


# ============================================================
# Report Tests
# ============================================================

class TestEvaluationReport:
    def test_create_report(self):
        r = create_report(1000.0, 2000.0)
        assert r.period_start == 1000.0
        assert r.period_end == 2000.0
        assert r.report_id.startswith("eval-")
        assert r.metrics == {}
        assert r.recommendations == []

    def test_to_dict(self):
        r = create_report(1000.0, 2000.0)
        r.metrics = {"learning_velocity": 2.0}
        r.recommendations = ["Test rec"]
        d = r.to_dict()
        assert d["metrics"]["learning_velocity"] == 2.0
        assert d["recommendations"] == ["Test rec"]

    def test_from_dict(self):
        d = {
            "timestamp": 1000.0,
            "report_id": "eval-abc",
            "period_start": 500.0,
            "period_end": 1000.0,
            "metrics": {"retention_rate": 0.8},
            "details": {},
            "data_sources": {},
            "recommendations": ["Rec 1"],
        }
        r = EvaluationReport.from_dict(d)
        assert r.report_id == "eval-abc"
        assert r.metrics["retention_rate"] == 0.8

    def test_roundtrip(self):
        r = create_report(1000.0, 2000.0)
        r.metrics = {"a": 1.0, "b": 2.0}
        r.details = {"a": {"x": 1}}
        r.recommendations = ["Do something"]
        d = r.to_dict()
        restored = EvaluationReport.from_dict(d)
        assert restored.metrics == r.metrics
        assert restored.recommendations == r.recommendations


# ============================================================
# Observer: Learning Velocity
# ============================================================

class TestLearningVelocity:
    def test_no_plans(self, tmp_path):
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert report.metrics["learning_velocity"] == 0.0

    def test_chunks_in_period(self, tmp_path):
        now = time.time()
        plans = [
            {"timestamp": now - 1800, "result": {"success": True, "type": "learn"}},
            {"timestamp": now - 900, "result": {"success": True, "type": "learn"}},
            {"timestamp": now - 300, "result": {"success": True, "type": "fill_gap"}},
        ]
        write_jsonl(tmp_path / "teacher_plans.jsonl", plans)
        obs = make_observer(tmp_path)
        report = obs.generate_report(period_hours=1.0)
        assert report.metrics["learning_velocity"] == 3.0
        assert report.details["learning_velocity"]["chunks_last_1h"] == 3

    def test_only_successful(self, tmp_path):
        now = time.time()
        plans = [
            {"timestamp": now - 300, "result": {"success": True, "type": "learn"}},
            {"timestamp": now - 200, "result": {"success": False, "type": "learn"}},
            {"timestamp": now - 100, "result": {"success": True, "type": "exam"}},
        ]
        write_jsonl(tmp_path / "teacher_plans.jsonl", plans)
        obs = make_observer(tmp_path)
        report = obs.generate_report(period_hours=1.0)
        # Only 1 successful learn (exam type doesn't count)
        assert report.metrics["learning_velocity"] == 1.0

    def test_trend_stable(self, tmp_path):
        now = time.time()
        plans = [
            {"timestamp": now - 3600, "result": {"success": True, "type": "learn"}},
            {"timestamp": now - 300, "result": {"success": True, "type": "learn"}},
        ]
        write_jsonl(tmp_path / "teacher_plans.jsonl", plans)
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert report.details["learning_velocity"]["trend"] == "stable"


# ============================================================
# Observer: Retention Rate
# ============================================================

class TestRetentionRate:
    def test_no_exams(self, tmp_path):
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert report.metrics["retention_rate"] == 0.0

    def test_all_passed(self, tmp_path):
        exams = [
            {"file": "a.txt", "passed": True, "score": 0.9},
            {"file": "b.txt", "passed": True, "score": 0.8},
        ]
        write_jsonl(tmp_path / "exam_results.jsonl", exams)
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert report.metrics["retention_rate"] == 1.0
        assert report.details["retention_rate"]["exams_passed"] == 2

    def test_mixed(self, tmp_path):
        exams = [
            {"file": "a.txt", "passed": True, "score": 0.9},
            {"file": "b.txt", "passed": False, "score": 0.4},
            {"file": "c.txt", "passed": True, "score": 0.7},
        ]
        write_jsonl(tmp_path / "exam_results.jsonl", exams)
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert abs(report.metrics["retention_rate"] - 0.667) < 0.01

    def test_last_5_scores(self, tmp_path):
        exams = [{"file": f"f{i}.txt", "passed": True, "score": 0.1 * i} for i in range(8)]
        write_jsonl(tmp_path / "exam_results.jsonl", exams)
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert len(report.details["retention_rate"]["last_5_scores"]) == 5


# ============================================================
# Observer: Knowledge Coverage
# ============================================================

class TestKnowledgeCoverage:
    def test_no_files(self, tmp_path):
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert report.metrics["knowledge_coverage"] == 0.0

    def test_all_completed(self, tmp_path):
        index = [
            {"id": "a.txt", "status": "completed"},
            {"id": "b.txt", "status": "completed"},
        ]
        write_jsonl(tmp_path / "knowledge_index.jsonl", index)
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert report.metrics["knowledge_coverage"] == 1.0

    def test_mixed_statuses(self, tmp_path):
        index = [
            {"id": "a.txt", "status": "completed"},
            {"id": "b.txt", "status": "learning"},
            {"id": "c.txt", "status": "new"},
            {"id": "d.txt", "status": "hard_topic"},
        ]
        write_jsonl(tmp_path / "knowledge_index.jsonl", index)
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert report.metrics["knowledge_coverage"] == 0.25
        details = report.details["knowledge_coverage"]
        assert details["completed_files"] == 1
        assert details["total_files"] == 4
        assert details["hard_topics"] == 1
        assert details["new_files"] == 1

    def test_merge_semantics(self, tmp_path):
        # Last record per id wins
        index = [
            {"id": "a.txt", "status": "learning"},
            {"id": "a.txt", "status": "completed"},
        ]
        write_jsonl(tmp_path / "knowledge_index.jsonl", index)
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert report.metrics["knowledge_coverage"] == 1.0
        assert report.details["knowledge_coverage"]["total_files"] == 1


# ============================================================
# Observer: System Stability
# ============================================================

class TestSystemStability:
    def test_no_events(self, tmp_path):
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert report.metrics["system_stability"] == 0.0

    def test_healthy(self, tmp_path):
        now = time.time()
        events = [
            {"ts": now - 300, "event": "state_snapshot", "health_score": 0.9},
            {"ts": now - 200, "event": "state_snapshot", "health_score": 0.95},
            {"ts": now - 100, "event": "state_snapshot", "health_score": 0.85},
        ]
        write_jsonl(tmp_path / "homeostasis_events.jsonl", events)
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert report.metrics["system_stability"] == 0.9

    def test_mode_changes_counted(self, tmp_path):
        now = time.time()
        events = [
            {"ts": now - 300, "event": "state_snapshot", "health_score": 0.8},
            {"ts": now - 200, "event": "mode_change", "from_mode": "ACTIVE", "to_mode": "REDUCED"},
            {"ts": now - 100, "event": "mode_change", "from_mode": "REDUCED", "to_mode": "ACTIVE"},
        ]
        write_jsonl(tmp_path / "homeostasis_events.jsonl", events)
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert report.details["system_stability"]["mode_changes_24h"] == 2

    def test_critical_alerts(self, tmp_path):
        now = time.time()
        events = [
            {"ts": now - 100, "event": "state_snapshot", "health_score": 0.5},
            {"ts": now - 50, "event": "alert", "severity": "CRITICAL", "alert_type": "oom"},
        ]
        write_jsonl(tmp_path / "homeostasis_events.jsonl", events)
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert report.details["system_stability"]["critical_alerts_24h"] == 1


# ============================================================
# Observer: Personality Growth
# ============================================================

class TestPersonalityGrowth:
    def test_no_experiences(self, tmp_path):
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert report.metrics["personality_growth"] == 0.0

    def test_single_session(self, tmp_path):
        experiences = [
            {"ts": 1000, "event": "learning_completed", "session": 1},
            {"ts": 1001, "event": "exam_passed", "session": 1},
        ]
        write_jsonl(tmp_path / "personality_experiences.jsonl", experiences)
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        # Only 1 session, can't compute delta
        assert report.details["personality_growth"]["sessions_analyzed"] == 1

    def test_growth_across_sessions(self, tmp_path):
        experiences = [
            {"ts": 1000, "event": "learning_completed", "session": 1},
            {"ts": 2000, "event": "learning_completed", "session": 2},
            {"ts": 2001, "event": "learning_completed", "session": 2},
            {"ts": 2002, "event": "learning_completed", "session": 2},
            {"ts": 2003, "event": "exam_passed", "session": 2},
        ]
        write_jsonl(tmp_path / "personality_experiences.jsonl", experiences)
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert report.metrics["personality_growth"] > 0
        assert report.details["personality_growth"]["sessions_analyzed"] == 2


# ============================================================
# Observer: Recommendations
# ============================================================

class TestRecommendations:
    def test_low_retention(self, tmp_path):
        exams = [
            {"file": "a.txt", "passed": False, "score": 0.3},
            {"file": "b.txt", "passed": False, "score": 0.4},
            {"file": "c.txt", "passed": True, "score": 0.7},
        ]
        write_jsonl(tmp_path / "exam_results.jsonl", exams)
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        recs = report.recommendations
        assert any("Retention" in r for r in recs)

    def test_critical_retention(self, tmp_path):
        exams = [
            {"file": "a.txt", "passed": False, "score": 0.2},
            {"file": "b.txt", "passed": False, "score": 0.3},
        ]
        write_jsonl(tmp_path / "exam_results.jsonl", exams)
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        recs = report.recommendations
        assert any("critically low" in r for r in recs)

    def test_high_coverage(self, tmp_path):
        index = [{"id": f"f{i}.txt", "status": "completed"} for i in range(10)]
        index.append({"id": "last.txt", "status": "learning"})
        write_jsonl(tmp_path / "knowledge_index.jsonl", index)
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert any("90%" in r for r in report.recommendations)

    def test_hard_topics(self, tmp_path):
        index = [
            {"id": "a.txt", "status": "hard_topic"},
            {"id": "b.txt", "status": "hard_topic"},
            {"id": "c.txt", "status": "completed"},
        ]
        write_jsonl(tmp_path / "knowledge_index.jsonl", index)
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert any("hard topic" in r for r in report.recommendations)

    def test_no_recommendations_when_healthy(self, tmp_path):
        now = time.time()
        # Good exam results
        exams = [{"file": f"f{i}.txt", "passed": True, "score": 0.9} for i in range(5)]
        write_jsonl(tmp_path / "exam_results.jsonl", exams)
        # Some learning
        plans = [{"timestamp": now - 300, "result": {"success": True, "type": "learn"}}]
        write_jsonl(tmp_path / "teacher_plans.jsonl", plans)
        # Good health
        events = [{"ts": now - 100, "event": "state_snapshot", "health_score": 0.95}]
        write_jsonl(tmp_path / "homeostasis_events.jsonl", events)
        # Medium coverage
        index = [
            {"id": "a.txt", "status": "completed"},
            {"id": "b.txt", "status": "learning"},
        ]
        write_jsonl(tmp_path / "knowledge_index.jsonl", index)

        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert report.recommendations == []


# ============================================================
# Observer: Persistence
# ============================================================

class TestObserverPersistence:
    def test_report_saved(self, tmp_path):
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        reports_path = tmp_path / "evaluation_reports.jsonl"
        assert reports_path.exists()
        lines = reports_path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["report_id"] == report.report_id

    def test_multiple_reports_appended(self, tmp_path):
        obs = make_observer(tmp_path)
        obs.generate_report()
        obs.generate_report()
        obs.generate_report()
        reports_path = tmp_path / "evaluation_reports.jsonl"
        lines = reports_path.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_get_recent_reports(self, tmp_path):
        obs = make_observer(tmp_path)
        obs.generate_report()
        obs.generate_report()
        recent = obs.get_recent_reports(limit=5)
        assert len(recent) == 2
        assert all(isinstance(r, EvaluationReport) for r in recent)


# ============================================================
# Observer: Data Sources
# ============================================================

class TestDataSources:
    def test_sources_in_report(self, tmp_path):
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert "knowledge_index" in report.data_sources
        assert "exam_results" in report.data_sources
        assert "teacher_plans" in report.data_sources
        assert "homeostasis_events" in report.data_sources
        assert "personality_experiences" in report.data_sources


# ============================================================
# Observer: Missing Files
# ============================================================

class TestMissingFiles:
    def test_all_missing(self, tmp_path):
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        assert report.metrics["learning_velocity"] == 0.0
        assert report.metrics["retention_rate"] == 0.0
        assert report.metrics["knowledge_coverage"] == 0.0
        assert report.metrics["system_stability"] == 0.0
        assert report.metrics["personality_growth"] == 0.0

    def test_corrupt_jsonl(self, tmp_path):
        path = tmp_path / "exam_results.jsonl"
        path.write_text('{"passed": true, "score": 0.9}\n{bad json\n{"passed": false, "score": 0.3}\n')
        obs = make_observer(tmp_path)
        report = obs.generate_report()
        # Should handle gracefully: 1 passed + 1 failed = 0.5
        assert report.metrics["retention_rate"] == 0.5


class TestObserverE2E:
    """Full integration test with realistic data."""

    def test_realistic_session(self, tmp_path):
        now = time.time()

        # Knowledge: 3 completed, 2 learning, 1 new, 1 hard
        index = [
            {"id": "physics.txt", "status": "completed"},
            {"id": "chemistry.txt", "status": "completed"},
            {"id": "biology.txt", "status": "completed"},
            {"id": "math.txt", "status": "learning"},
            {"id": "history.txt", "status": "learning"},
            {"id": "art.txt", "status": "new"},
            {"id": "quantum.txt", "status": "hard_topic"},
        ]
        write_jsonl(tmp_path / "knowledge_index.jsonl", index)

        # Exams: 5 passed, 2 failed
        exams = [
            {"file": "physics.txt", "passed": True, "score": 0.9},
            {"file": "chemistry.txt", "passed": True, "score": 0.85},
            {"file": "biology.txt", "passed": True, "score": 0.7},
            {"file": "math.txt", "passed": False, "score": 0.4},
            {"file": "history.txt", "passed": True, "score": 0.75},
            {"file": "quantum.txt", "passed": False, "score": 0.3},
            {"file": "physics.txt", "passed": True, "score": 0.95},
        ]
        write_jsonl(tmp_path / "exam_results.jsonl", exams)

        # Teacher plans: 2 chunks in last hour
        plans = [
            {"timestamp": now - 2400, "result": {"success": True, "type": "learn"}},
            {"timestamp": now - 1200, "result": {"success": True, "type": "learn"}},
        ]
        write_jsonl(tmp_path / "teacher_plans.jsonl", plans)

        # Homeostasis: stable
        events = [
            {"ts": now - 600, "event": "state_snapshot", "health_score": 0.88},
            {"ts": now - 300, "event": "state_snapshot", "health_score": 0.92},
            {"ts": now - 60, "event": "state_snapshot", "health_score": 0.90},
        ]
        write_jsonl(tmp_path / "homeostasis_events.jsonl", events)

        # Personality: 2 sessions
        experiences = [
            {"ts": 1000, "event": "learning_completed", "session": 1},
            {"ts": 2000, "event": "learning_completed", "session": 2},
            {"ts": 2001, "event": "learning_completed", "session": 2},
            {"ts": 2002, "event": "exam_passed", "session": 2},
        ]
        write_jsonl(tmp_path / "personality_experiences.jsonl", experiences)

        obs = make_observer(tmp_path)
        report = obs.generate_report()

        # Verify all 5 metrics are computed
        assert report.metrics["learning_velocity"] == 2.0
        assert abs(report.metrics["retention_rate"] - 0.714) < 0.01
        assert abs(report.metrics["knowledge_coverage"] - 0.429) < 0.01
        assert report.metrics["system_stability"] == 0.9
        assert report.metrics["personality_growth"] >= 0

        # Should have retention recommendation (< 80%)
        assert any("Retention" in r for r in report.recommendations)

        # Report should be saved
        assert (tmp_path / "evaluation_reports.jsonl").exists()
