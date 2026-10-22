"""
Tests for K12 Self-Analysis module.

Tests cover: recommendation_model, state_collector, external_analyzer,
recommendation_applier, SelfAnalysis facade, and planner integration.
"""

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_core.self_analysis.recommendation_model import (
    AnalysisRecommendation,
    AnalysisReport,
    RecommendationCategory,
    SuggestedAction,
    AnalyzerBackend,
    MAX_RECOMMENDATIONS_PER_REPORT,
    format_report_for_telegram,
    MAX_SYSTEMIC_ISSUES,
    _gen_id,
)
from agent_core.self_analysis.recommendation_applier import _is_searchable_topic
from agent_core.self_analysis.state_collector import StateCollector
from agent_core.self_analysis.external_analyzer import ExternalAnalyzer
from agent_core.self_analysis.recommendation_applier import RecommendationApplier
from agent_core.self_analysis import SelfAnalysis
from agent_core.planner.planner_model import Plan, ActionType, PlanStatus
from agent_core.goals.store import GoalStore
from agent_core.world_model import WorldModel
from agent_core.bulletin.bulletin_store import BulletinStore
from agent_core.consciousness.core import ConsciousnessCore
from agent_core.tests.spec_helpers import specced


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory with JSONL files."""
    meta = tmp_path / "meta_data"
    meta.mkdir()
    memory = tmp_path / "memory"
    memory.mkdir()
    return tmp_path


@pytest.fixture
def populated_project(tmp_project):
    """Project with realistic JSONL data."""
    meta = tmp_project / "meta_data"

    # evaluation_reports.jsonl
    reports = []
    for i in range(5):
        reports.append({
            "report_id": f"eval-{i:04d}",
            "period_end": time.time() - (4 - i) * 3600,
            "timestamp": time.time() - (4 - i) * 3600,
            "metrics": {
                "learning_velocity": 5.0 + i * 0.5,
                "retention_rate": 0.7 + i * 0.05,
                "knowledge_coverage": 0.15 + i * 0.02,
                "system_stability": 0.95,
            },
            "recommendations": [],
        })
    _write_jsonl(meta / "evaluation_reports.jsonl", reports)

    # beliefs.jsonl
    beliefs = [
        {"belief_id": "b1", "entity": "fizyka", "confidence": 0.3, "source": "learning"},
        {"belief_id": "b2", "entity": "biologia", "confidence": 0.8, "source": "learning"},
        {"belief_id": "b3", "entity": "chemia", "confidence": 0.2, "source": "learning"},
        {"belief_id": "b4", "entity": "matematyka", "confidence": 0.5, "source": "learning"},
    ]
    _write_jsonl(meta / "beliefs.jsonl", beliefs)

    # planner_decisions.jsonl
    decisions = []
    for i in range(20):
        decisions.append({
            "timestamp": time.time() - (20 - i) * 60,
            "action_type": "learn" if i % 3 != 0 else "exam",
            "status": "completed" if i % 4 != 0 else "failed",
            "result": {"success": i % 4 != 0},
        })
    _write_jsonl(meta / "planner_decisions.jsonl", decisions)

    # reflections.jsonl
    reflections = [
        {
            "reflection_id": "r1",
            "timestamp": time.time() - 100,
            "outcome_match": "mismatch",
            "actual_success": False,
            "assumptions": [{"description": "fizyka quantum easy"}],
        },
        {
            "reflection_id": "r2",
            "timestamp": time.time() - 50,
            "outcome_match": "mismatch",
            "actual_success": False,
            "assumptions": [{"description": "fizyka quantum easy"}],
        },
        {
            "reflection_id": "r3",
            "timestamp": time.time() - 30,
            "outcome_match": "match",
            "actual_success": True,
            "assumptions": [{"description": "biologia ok"}],
        },
    ]
    _write_jsonl(meta / "reflections.jsonl", reflections)

    # teacher_plans.jsonl
    plans = []
    for i in range(10):
        plans.append({
            "timestamp": time.time() - (10 - i) * 120,
            "strategy": {"strategy_type": "learn_new", "target_file_id": f"file_{i}.txt"},
            "result": {"success": i % 3 != 0},
        })
    _write_jsonl(meta / "teacher_plans.jsonl", plans)

    # goals.jsonl
    goals = [
        {"id": "g1", "status": "ACTIVE", "description": "Learn fizyka",
         "created_at": time.time() - 5 * 86400},
        {"id": "g2", "status": "COMPLETED", "description": "Learn biologia",
         "created_at": time.time() - 2 * 86400},
    ]
    _write_jsonl(meta / "goals.jsonl", goals)

    # homeostasis_events.jsonl
    events = []
    for i in range(10):
        events.append({
            "event_type": "state_snapshot",
            "timestamp": time.time() - (10 - i) * 60,
            "health_score": 0.85 + (i * 0.01),
            "mode": "active",
        })
    _write_jsonl(meta / "homeostasis_events.jsonl", events)

    # knowledge_index.jsonl (in memory/)
    ki = [
        {"id": "f1.txt", "status": "completed"},
        {"id": "f2.txt", "status": "completed"},
        {"id": "f3.txt", "status": "learning"},
        {"id": "f4.txt", "status": "new"},
        {"id": "f5.txt", "status": "new"},
    ]
    _write_jsonl(tmp_project / "memory" / "knowledge_index.jsonl", ki)

    return tmp_project


def _write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# =============================================================================
# recommendation_model.py
# =============================================================================

class TestRecommendationModel:

    def test_gen_id(self):
        id1 = _gen_id("sa")
        id2 = _gen_id("sa")
        assert id1.startswith("sa-")
        assert id2.startswith("sa-")
        assert id1 != id2

    def test_recommendation_to_dict(self):
        rec = AnalysisRecommendation(
            rec_id="rec-123",
            category="knowledge_gap",
            topic="fizyka",
            description="Low confidence",
            priority=0.9,
            suggested_action="fetch",
        )
        d = rec.to_dict()
        assert d["rec_id"] == "rec-123"
        assert d["topic"] == "fizyka"
        assert d["priority"] == 0.9

    def test_recommendation_from_dict(self):
        d = {"category": "new_topic", "topic": "chemia", "priority": 0.7,
             "suggested_action": "learn", "description": "test"}
        rec = AnalysisRecommendation.from_dict(d)
        assert rec.topic == "chemia"
        assert rec.priority == 0.7
        assert rec.rec_id.startswith("rec-")

    def test_recommendation_from_dict_defaults(self):
        rec = AnalysisRecommendation.from_dict({})
        assert rec.topic == "unknown"
        assert rec.priority == 0.5
        assert rec.category == "knowledge_gap"

    def test_report_to_dict(self):
        rec = AnalysisRecommendation(
            rec_id="r1", category="knowledge_gap", topic="t",
            description="d", priority=0.5, suggested_action="learn",
        )
        report = AnalysisReport(
            report_id="sa-test",
            recommendations=[rec],
            goals_created=["g1"],
        )
        d = report.to_dict()
        assert d["report_id"] == "sa-test"
        assert "model" in d
        assert d["model"] is None
        assert len(d["recommendations"]) == 1
        assert d["goals_created"] == ["g1"]

    def test_report_from_dict(self):
        d = {
            "report_id": "sa-abc",
            "analyzer": "claude_cli",
            "recommendations": [
                {"topic": "fizyka", "priority": 0.8, "description": "gap",
                 "suggested_action": "fetch"}
            ],
        }
        report = AnalysisReport.from_dict(d)
        assert report.report_id == "sa-abc"
        assert report.analyzer == "claude_cli"
        assert report.model is None
        assert len(report.recommendations) == 1
        assert report.recommendations[0].topic == "fizyka"

    def test_report_roundtrip(self):
        rec = AnalysisRecommendation(
            rec_id="r1", category="knowledge_gap", topic="math",
            description="test", priority=0.6, suggested_action="learn",
        )
        original = AnalysisReport(recommendations=[rec], analyzer="local_planner")
        d = original.to_dict()
        restored = AnalysisReport.from_dict(d)
        assert restored.recommendations[0].topic == "math"
        assert restored.analyzer == "local_planner"
        assert restored.model is None


# =============================================================================
# state_collector.py
# =============================================================================

class TestStateCollector:

    def test_collect_empty_project(self, tmp_project):
        (tmp_project / "meta_data").mkdir(exist_ok=True)
        collector = StateCollector(str(tmp_project))
        result = collector.collect(period_days=7)
        assert "input_hash" in result
        assert result["knowledge_gaps"] == []
        assert result["struggling_topics"] == []

    def test_collect_populated_project(self, populated_project):
        collector = StateCollector(str(populated_project))
        result = collector.collect(period_days=7)

        # Metrics trend should have data
        assert len(result["metrics_trend"]["learning_velocity"]) > 0
        assert len(result["metrics_trend"]["retention_rate"]) > 0

        # Knowledge gaps: fizyka (0.3) and chemia (0.2) should be gaps
        gaps = result["knowledge_gaps"]
        gap_topics = [g["topic"] for g in gaps]
        assert "chemia" in gap_topics
        assert "fizyka" in gap_topics
        assert "biologia" not in gap_topics  # 0.8 > 0.6 threshold

        # Struggling topics (fizyka quantum appeared 2x as mismatch)
        assert len(result["struggling_topics"]) > 0

        # Action distribution
        dist = result["action_distribution"]
        assert "learn" in dist
        assert dist["learn"]["count"] > 0

        # Stale goals (g1 is 5 days old and ACTIVE)
        stale = result["stale_goals"]
        assert len(stale) > 0
        assert stale[0]["days_stale"] > 2

        # Learning progress
        progress = result["learning_progress"]
        assert progress["total_files"] == 5
        assert progress["by_status"]["completed"] == 2
        assert progress["by_status"]["new"] == 2

    def test_learning_progress_excludes_skips(self, tmp_path):
        """recent_learn_success_rate counts ATTEMPTED learns only -- skipped
        teacher plans (declined, no material) are neither success nor failure,
        so they must not deflate the rate (T-LEARN-003 phantom-failure guard)."""
        meta = tmp_path / "meta_data"
        meta.mkdir(parents=True)
        (tmp_path / "memory").mkdir()
        plans = [
            {"result": {"success": True}},
            {"result": {"success": True}},
            {"result": {"success": False}},                    # real failure
            {"result": {"skipped": True, "success": False}},   # skip -> excluded
            {"result": {"skipped": True, "success": False}},   # skip -> excluded
            {"result": {"skipped": True}},                     # skip -> excluded
        ]
        with open(meta / "teacher_plans.jsonl", "w", encoding="utf-8") as f:
            for p in plans:
                f.write(json.dumps(p) + "\n")
        prog = StateCollector(str(tmp_path))._collect_learning_progress()
        # 3 attempted (2 success, 1 fail); the 3 skips are excluded from both
        # numerator and denominator -> 0.67, NOT 2/6 = 0.33.
        assert prog["recent_learn_count"] == 3
        assert prog["recent_learn_success_rate"] == round(2 / 3, 2)

    def test_collect_with_prompt(self, populated_project):
        collector = StateCollector(str(populated_project))
        result = collector.collect_with_prompt()
        assert "analysis_prompt" in result
        assert "recommendations" in result["analysis_prompt"]

    def test_input_hash_present(self, populated_project):
        """Hash is generated (not necessarily deterministic due to timestamps)."""
        collector = StateCollector(str(populated_project))
        r1 = collector.collect()
        assert "input_hash" in r1
        assert len(r1["input_hash"]) == 16

    def test_system_health(self, populated_project):
        collector = StateCollector(str(populated_project))
        result = collector.collect()
        health = result["system_health"]
        assert health["avg_health"] > 0.8
        assert "active" in health["mode_distribution"]

    def _stale_project(self, tmp_path, goals):
        meta = tmp_path / "meta_data"
        meta.mkdir(parents=True, exist_ok=True)
        (tmp_path / "memory").mkdir(exist_ok=True)
        with open(meta / "goals.jsonl", "w", encoding="utf-8") as f:
            for g in goals:
                f.write(json.dumps(g) + "\n")
        return StateCollector(str(tmp_path))

    def test_working_goal_is_not_stale_however_old(self, tmp_path):
        """Staleness is time since it MOVED, not time since it was created.

        The age rule this replaced reported a goal that had worked 90 minutes
        earlier as "28.1 days stale", and flagged the always-on mission for
        every day of its 143-day life. K12, the MISALIGNMENT tension rule and
        the K12->K11 AGING_FACTOR heuristic all read that number.
        """
        now = time.time()
        collector = self._stale_project(tmp_path, [
            {"id": "veteran", "status": "ACTIVE", "description": "stary, pracuje",
             "created_at": now - 30 * 86400, "updated_at": now - 3600},
        ])
        assert collector._collect_stale_goals(now) == []

    def test_idle_goal_is_stale_and_keeps_its_age(self, tmp_path):
        now = time.time()
        collector = self._stale_project(tmp_path, [
            {"id": "idle", "status": "ACTIVE", "description": "stoi",
             "created_at": now - 30 * 86400, "updated_at": now - 10 * 86400},
        ])
        stale = collector._collect_stale_goals(now)
        assert len(stale) == 1
        assert stale[0]["days_stale"] == 10.0
        assert stale[0]["days_old"] == 30.0, "age signal lost, not just demoted"

    def test_never_touched_goal_counts_from_creation(self, tmp_path):
        """No updated_at at all -> fall back to created_at, do not go silent."""
        now = time.time()
        collector = self._stale_project(tmp_path, [
            {"id": "orphan", "status": "ACTIVE", "description": "nigdy nietkniety",
             "created_at": now - 9 * 86400},
        ])
        stale = collector._collect_stale_goals(now)
        assert len(stale) == 1
        assert stale[0]["days_stale"] == 9.0

    def test_mission_heartbeat_clears_it_from_the_stale_list(self, tmp_path):
        """Both halves of the 2026-07-22 fix meet here.

        The counter writing coverage bumps updated_at; the collector reads
        updated_at. Without the counter the mission has no heartbeat to read,
        and without the collector fix the heartbeat would not have been read.
        """
        now = time.time()
        collector = self._stale_project(tmp_path, [
            {"id": "goal-meta-learn", "status": "ACTIVE", "type": "meta",
             "description": "Autonomiczna nauka", "progress": 0.606,
             "created_at": now - 143 * 86400, "updated_at": now - 300},
        ])
        assert collector._collect_stale_goals(now) == []


# =============================================================================
# external_analyzer.py
# =============================================================================

class TestExternalAnalyzer:

    def test_analyze_no_llm(self):
        analyzer = ExternalAnalyzer(llm_fn=None)
        report = analyzer.analyze({"input_hash": "test"})
        assert report.error is not None
        assert "No LLM" in report.error
        assert report.recommendations == []

    def test_analyze_json_response(self):
        response_json = json.dumps({
            "recommendations": [
                {"category": "knowledge_gap", "topic": "fizyka",
                 "description": "Low confidence", "priority": 0.9,
                 "suggested_action": "fetch"},
                {"category": "new_topic", "topic": "chemia",
                 "description": "New area", "priority": 0.7,
                 "suggested_action": "learn"},
            ],
            "summary": "Agent needs more science materials",
        })

        mock_llm = MagicMock(return_value=response_json)
        analyzer = ExternalAnalyzer(llm_fn=mock_llm)
        report = analyzer.analyze({"input_hash": "test", "analysis_prompt": "analyze"})

        assert report.error is None
        assert len(report.recommendations) == 2
        assert report.recommendations[0].topic == "fizyka"
        assert report.recommendations[1].topic == "chemia"
        mock_llm.assert_called_once()

    def test_analyze_sets_local_model(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_PLANNER_MODEL", "test-model:latest")
        response_json = json.dumps({
            "recommendations": [
                {"category": "knowledge_gap", "topic": "fizyka",
                 "description": "Low confidence", "priority": 0.9,
                 "suggested_action": "fetch"},
            ],
        })

        analyzer = ExternalAnalyzer(llm_fn=MagicMock(return_value=response_json))
        report = analyzer.analyze({"input_hash": "test", "analysis_prompt": "analyze"})

        assert report.error is None
        assert report.model == "test-model:latest"
        assert report.to_dict()["model"] == "test-model:latest"

    def test_analyze_markdown_wrapped_json(self):
        response = """Here are my recommendations:
```json
{"recommendations": [{"category": "knowledge_gap", "topic": "math", "description": "gap", "priority": 0.8, "suggested_action": "learn"}]}
```"""
        mock_llm = MagicMock(return_value=response)
        analyzer = ExternalAnalyzer(llm_fn=mock_llm)
        report = analyzer.analyze({"input_hash": "test", "analysis_prompt": "analyze"})

        assert len(report.recommendations) == 1
        assert report.recommendations[0].topic == "math"

    def test_analyze_freetext_fallback(self):
        response = """Based on analysis:
1. fizyka kwantowa: Agent has low confidence, needs foundational materials
2. chemia organiczna: New topic to explore for cross-domain knowledge
3. matematyka: Review needed, several exam failures"""

        mock_llm = MagicMock(return_value=response)
        analyzer = ExternalAnalyzer(llm_fn=mock_llm)
        report = analyzer.analyze({"input_hash": "test", "analysis_prompt": "analyze"})

        assert len(report.recommendations) >= 2
        topics = [r.topic for r in report.recommendations]
        assert any("fizyka" in t for t in topics)

    def test_freetext_markdown_headings_not_emitted_as_junk(self):
        """Regression (2026-06-15): markdown headings/emphasis in the freetext
        fallback used to become junk recs (topic='*Najpierw', description='**').
        A bullet now needs a space after the marker, and topics are stripped of
        markdown, so '**Najpierw:**' is never a recommendation."""
        response = """**Najpierw:**
1. fizyka kwantowa: needs foundational materials
**Przerwa w naukach**
2. chemia organiczna: new topic to explore"""
        analyzer = ExternalAnalyzer(llm_fn=MagicMock(return_value=response))
        report = analyzer.analyze({"input_hash": "t", "analysis_prompt": "a"})

        topics = [r.topic for r in report.recommendations]
        # No markdown leaked into any topic.
        assert all("*" not in t and "#" not in t for t in topics), topics
        assert all(t.strip() for t in topics), topics
        # The real items still parsed.
        assert any("fizyka" in t for t in topics), topics

    def test_is_searchable_topic_rejects_markdown_junk(self):
        """The fetch-queue filter must reject markdown artifacts while keeping
        real Wikipedia-shaped topics."""
        assert _is_searchable_topic("Mechanika kwantowa") is True
        assert _is_searchable_topic("Jezyk C#") is True  # mid-string '#' ok
        for junk in ("*Najpierw", "**", "**Przerwa w naukach**", "# Heading",
                     "- bullet", "---", "`code`"):
            assert _is_searchable_topic(junk) is False, junk

    def test_format_report_for_telegram_is_clean(self):
        """The K12 Telegram card must carry a clean summary + recommendation
        lines, never raw_response JSON or str(dataclass) reprs (2026-06-15)."""
        report = AnalysisReport(
            analyzer="local_planner",
            model="qwen3:8b",
            raw_response='{"recommendations": [{"topic": "x"}]}  <-- must NOT appear',
            recommendations=[
                AnalysisRecommendation(
                    rec_id="rec-1", category="knowledge_gap", topic="fizyka",
                    description="brak podstaw mechaniki", priority=0.8,
                    suggested_action="learn",
                ),
            ],
        )
        summary, recs, _ = format_report_for_telegram(report)
        assert "raw_response" not in summary and "{" not in summary
        assert "qwen3:8b" in summary and "1" in summary
        assert recs == ["fizyka -> learn: brak podstaw mechaniki"]
        assert all("AnalysisRecommendation(" not in r for r in recs)

    def test_format_report_keeps_the_finding_and_its_number(self):
        """Regression (2026-07-16): the description carries WHAT is wrong and HOW
        bad. Dropping it turned "exam success rate is low (0.19)" into a bare
        "exam strategy -> experiment" -- the operator's optimism filter."""
        report = AnalysisReport(
            model="dracarys",
            recommendations=[
                AnalysisRecommendation(
                    rec_id="rec-1", category="retention_problem",
                    topic="exam strategy",
                    description="exam success rate is low (0.19), adjust strategy",
                    priority=0.9, suggested_action="experiment",
                ),
            ],
        )
        _, recs, _ = format_report_for_telegram(report)
        assert recs == [
            "exam strategy -> experiment: exam success rate is low (0.19), adjust strategy"
        ]
        assert "0.19" in recs[0]

    def test_format_report_head_survives_long_description(self):
        """A very long reason is trimmed; the 'topic -> action' head stays whole."""
        long_desc = "x" * 400
        report = AnalysisReport(
            recommendations=[
                AnalysisRecommendation(
                    rec_id="rec-1", category="knowledge_gap", topic="fizyka",
                    description=long_desc, priority=0.5, suggested_action="learn",
                ),
            ],
        )
        _, recs, _ = format_report_for_telegram(report)
        line = recs[0]
        assert line.startswith("fizyka -> learn: ")
        assert line.endswith("...")
        assert len(line) <= 240

    def test_format_report_falls_back_when_no_description(self):
        """Empty description degrades to the old 'topic -> action' form."""
        report = AnalysisReport(
            recommendations=[
                AnalysisRecommendation(
                    rec_id="rec-1", category="knowledge_gap", topic="fizyka",
                    description="", priority=0.5, suggested_action="learn",
                ),
            ],
        )
        _, recs, _ = format_report_for_telegram(report)
        assert recs == ["fizyka -> learn"]

    def test_format_report_neutralises_telegram_markdown(self):
        """Snake_case topics and stray markers from the LLM must not become
        formatting -- 'system_stability' would italicise or be eaten silently
        (no API error, so the bot's plain-text fallback never fires). 32% of live
        recommendations carry an underscore."""
        report = AnalysisReport(
            model="local_planner",
            recommendations=[
                AnalysisRecommendation(
                    rec_id="rec-1", category="strategy_change",
                    topic="system_stability",
                    description="CPU/ram at *90%* `high`, see [ref]",
                    priority=0.7, suggested_action="experiment",
                ),
            ],
        )
        summary, recs, _ = format_report_for_telegram(report)
        for bad in ("_", "*", "`", "[", "]"):
            assert bad not in recs[0], f"{bad!r} leaked into a recommendation line"
            assert bad not in summary, f"{bad!r} leaked into the summary"
        # readable, not mangled: underscores became spaces, content intact
        assert "system stability -> experiment" in recs[0]
        assert "90%" in recs[0] and "high" in recs[0]
        assert "local planner" in summary

    def test_analyze_empty_response(self):
        mock_llm = MagicMock(return_value="")
        analyzer = ExternalAnalyzer(llm_fn=mock_llm)
        report = analyzer.analyze({"input_hash": "test", "analysis_prompt": "analyze"})
        assert report.error is not None

    def test_analyze_llm_exception(self):
        mock_llm = MagicMock(side_effect=RuntimeError("model unavailable"))
        analyzer = ExternalAnalyzer(llm_fn=mock_llm)
        report = analyzer.analyze({"input_hash": "test", "analysis_prompt": "analyze"})
        assert report.error is not None
        assert "model unavailable" in report.error

    def test_max_recommendations_enforced(self):
        recs = [{"category": "knowledge_gap", "topic": f"t{i}",
                 "description": "d", "priority": 0.5, "suggested_action": "learn"}
                for i in range(10)]
        response_json = json.dumps({"recommendations": recs})
        mock_llm = MagicMock(return_value=response_json)
        analyzer = ExternalAnalyzer(llm_fn=mock_llm)
        report = analyzer.analyze({"input_hash": "test", "analysis_prompt": "analyze"})
        assert len(report.recommendations) <= MAX_RECOMMENDATIONS_PER_REPORT

    def test_set_llm_fn(self):
        analyzer = ExternalAnalyzer()
        assert analyzer._llm_fn is None
        mock_fn = MagicMock()
        analyzer.set_llm_fn(mock_fn)
        assert analyzer._llm_fn is mock_fn


# =============================================================================
# recommendation_applier.py
# =============================================================================

class TestRecommendationApplier:

    def test_apply_empty_report(self, tmp_project):
        applier = RecommendationApplier(project_root=str(tmp_project))
        report = AnalysisReport()
        result = applier.apply(report)
        assert result["goals_created"] == []
        assert result["hints_written"] == 0

    def test_apply_creates_topic_hints(self, tmp_project):
        applier = RecommendationApplier(project_root=str(tmp_project))
        rec = AnalysisRecommendation(
            rec_id="r1", category="knowledge_gap", topic="fizyka",
            description="Low confidence", priority=0.9, suggested_action="fetch",
        )
        report = AnalysisReport(recommendations=[rec])

        result = applier.apply(report)
        assert result["hints_written"] == 1

        # Check hints file
        hints_path = tmp_project / "meta_data" / "topic_hints.jsonl"
        assert hints_path.exists()
        with open(hints_path) as f:
            hint = json.loads(f.readline())
        assert hint["topic"] == "fizyka"
        assert hint["source"] == "self_analysis"
        assert hint["consumed"] is False

    def test_apply_learn_rec_no_goal_writes_hint(self, tmp_project):
        # R1 (2026-05-29): non-strategic recs no longer create PROPOSED goals
        # (99.9% were never worked). A learn rec writes a topic hint instead,
        # which is what actually drives the WebSource learning pipeline.
        mock_store = specced(GoalStore)
        mock_store.propose = MagicMock(return_value="goal-123")

        applier = RecommendationApplier(
            goal_store=mock_store,
            project_root=str(tmp_project),
        )
        rec = AnalysisRecommendation(
            rec_id="r1", category="knowledge_gap", topic="fizyka",
            description="test", priority=0.9, suggested_action="learn",
        )
        report = AnalysisReport(report_id="sa-test", recommendations=[rec])

        result = applier.apply(report)
        assert result["goals_created"] == []
        mock_store.propose.assert_not_called()
        assert result["hints_written"] == 1

    def test_apply_many_recs_no_goals(self, tmp_project):
        # R1: a batch of non-strategic learn recs produces zero goals -
        # no goal-queue flooding (was the source of 549 abandoned orphans).
        mock_store = specced(GoalStore)
        mock_store.propose = MagicMock(side_effect=lambda **kw: "goal-x")

        applier = RecommendationApplier(
            goal_store=mock_store,
            project_root=str(tmp_project),
        )
        recs = [
            AnalysisRecommendation(
                rec_id=f"r{i}", category="knowledge_gap", topic=f"topic_{i}",
                description=f"desc_{i}", priority=0.9 - i * 0.1,
                suggested_action="learn",
            )
            for i in range(5)
        ]
        report = AnalysisReport(recommendations=recs)
        result = applier.apply(report)

        assert result["goals_created"] == []
        mock_store.propose.assert_not_called()

    def test_apply_with_world_model(self, tmp_project):
        # spec-blocked: add_belief is a phantom (no production WorldModel has it);
        # this test intentionally exercises the hasattr-guarded hypothetical path
        mock_wm = MagicMock()
        mock_wm.add_belief = MagicMock()

        applier = RecommendationApplier(
            world_model=mock_wm,
            project_root=str(tmp_project),
        )
        rec = AnalysisRecommendation(
            rec_id="r1", category="knowledge_gap", topic="fizyka",
            description="Low confidence", priority=0.9, suggested_action="learn",
        )
        report = AnalysisReport(recommendations=[rec])

        result = applier.apply(report)
        assert result["beliefs_updated"] == 1
        mock_wm.add_belief.assert_called_once()

    def test_apply_with_real_world_model_reports_zero(self, tmp_project, tmp_path):
        """Audyt 2026-06-12: zaden produkcyjny WorldModel nie ma add_belief
        (test wyzej fabrykuje ja na mocku). Licznik beliefs_updated rosl
        bezwarunkowo i raport klamal "N beliefs" przy zerze zapisow.
        Na PRAWDZIWYM WorldModelu licznik musi uczciwie zwrocic 0."""
        from agent_core.world_model import WorldModel

        wm = WorldModel(
            beliefs_path=tmp_path / "beliefs.jsonl",
            knowledge_index_path=tmp_path / "ki.jsonl",
            longterm_memory_path=tmp_path / "ltm.jsonl",
            exam_results_path=tmp_path / "exam.jsonl",
        )
        assert not hasattr(wm, "add_belief")  # dokumentuje stan API

        applier = RecommendationApplier(
            world_model=wm,
            project_root=str(tmp_project),
        )
        rec = AnalysisRecommendation(
            rec_id="r1", category="knowledge_gap", topic="fizyka",
            description="Low confidence", priority=0.9, suggested_action="learn",
        )
        result = applier.apply(AnalysisReport(recommendations=[rec]))

        assert result["beliefs_updated"] == 0

    # R2.1.1 (2026-05-05) — registry-aware filter
    @staticmethod
    def _seed_registry(project_root, *topics):
        """Helper: write fetch_registry entries for given topics."""
        path = project_root / "meta_data" / "web_fetch_registry.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            for t in topics:
                f.write(json.dumps({
                    "topic": t,
                    "title": t,
                    "url": "https://example/",
                    "source_type": "wikipedia",
                    "char_count": 1234,
                    "fetched_at": "2026-05-01T00:00:00Z",
                    "ts": 1777680000.0,
                    "output_file": f"input/web_wiki_{t}.txt",
                }) + "\n")

    def test_already_fetched_topic_filters_hint(self, tmp_project):
        self._seed_registry(tmp_project, "wnioskowanie")
        applier = RecommendationApplier(project_root=str(tmp_project))
        rec = AnalysisRecommendation(
            rec_id="r1", category="new_topic", topic="wnioskowanie",
            description="K12 thinks new", priority=0.7, suggested_action="fetch",
        )
        report = AnalysisReport(recommendations=[rec])
        result = applier.apply(report)
        assert result["hints_written"] == 0
        # File should not be created (or be empty)
        hints_path = tmp_project / "meta_data" / "topic_hints.jsonl"
        if hints_path.exists():
            assert hints_path.read_text().strip() == ""

    def test_already_fetched_topic_filters_goal(self, tmp_project):
        self._seed_registry(tmp_project, "wnioskowanie")
        mock_store = specced(GoalStore)
        mock_store.propose = MagicMock(return_value="goal-should-not-fire")
        applier = RecommendationApplier(
            goal_store=mock_store, project_root=str(tmp_project),
        )
        rec = AnalysisRecommendation(
            rec_id="r1", category="knowledge_gap", topic="wnioskowanie",
            description="...", priority=0.9, suggested_action="learn",
        )
        report = AnalysisReport(recommendations=[rec])
        result = applier.apply(report)
        assert result["goals_created"] == []
        mock_store.propose.assert_not_called()

    def test_not_in_registry_passes_filter(self, tmp_project):
        self._seed_registry(tmp_project, "filozofia")  # different topic
        applier = RecommendationApplier(project_root=str(tmp_project))
        rec = AnalysisRecommendation(
            rec_id="r1", category="new_topic", topic="muzyka",
            description="...", priority=0.7, suggested_action="fetch",
        )
        report = AnalysisReport(recommendations=[rec])
        result = applier.apply(report)
        assert result["hints_written"] == 1

    def test_registry_filter_case_insensitive(self, tmp_project):
        self._seed_registry(tmp_project, "Wnioskowanie")  # capital W in registry
        applier = RecommendationApplier(project_root=str(tmp_project))
        rec = AnalysisRecommendation(
            rec_id="r1", category="new_topic", topic="WNIOSKOWANIE",
            description="...", priority=0.7, suggested_action="fetch",
        )
        report = AnalysisReport(recommendations=[rec])
        result = applier.apply(report)
        assert result["hints_written"] == 0

    def test_review_rec_creates_no_goal_no_hint(self, tmp_project):
        # R1 (2026-05-29): a non-strategic "review" rec (not fetch/learn)
        # produces no goal and no topic hint - it becomes a no-op. These
        # review/experiment recs were abandoned noise in the goal queue.
        self._seed_registry(tmp_project, "fizyka")
        mock_store = specced(GoalStore)
        mock_store.propose = MagicMock(return_value="goal-review-ok")
        applier = RecommendationApplier(
            goal_store=mock_store, project_root=str(tmp_project),
        )
        rec = AnalysisRecommendation(
            rec_id="r1", category="knowledge_gap", topic="fizyka",
            description="needs review", priority=0.7, suggested_action="review",
        )
        report = AnalysisReport(recommendations=[rec])
        result = applier.apply(report)
        assert result["goals_created"] == []
        mock_store.propose.assert_not_called()
        assert result["hints_written"] == 0

    def test_set_dependencies(self, tmp_project):
        applier = RecommendationApplier(project_root=str(tmp_project))
        mock_store = specced(GoalStore)
        mock_wm = specced(WorldModel)
        mock_bs = specced(BulletinStore)
        applier.set_goal_store(mock_store)
        applier.set_world_model(mock_wm)
        applier.set_bulletin_store(mock_bs)
        assert applier._goal_store is mock_store
        assert applier._world_model is mock_wm
        assert applier._bulletin_store is mock_bs


# =============================================================================
# D2 (2026-04-26): Strategic recs route to bulletin instead of misroute goals
# =============================================================================

class TestRecommendationApplierStrategic:
    """Strategic K12 recs (category=strategy_change) post bulletin
    IMPROVEMENT entries instead of creating misroute LEARNING goals."""

    def _make_bulletin(self, tmp_project):
        from agent_core.bulletin import BulletinStore
        return BulletinStore(
            path=tmp_project / "meta_data" / "cognitive_bulletin.jsonl"
        )

    def test_strategy_change_posts_to_bulletin(self, tmp_project):
        bulletin = self._make_bulletin(tmp_project)
        mock_store = specced(GoalStore)
        mock_store.propose = MagicMock(return_value="goal-strategy")
        applier = RecommendationApplier(
            goal_store=mock_store,
            bulletin_store=bulletin,
            project_root=str(tmp_project),
        )
        rec = AnalysisRecommendation(
            rec_id="rec-strat-1",
            category="strategy_change",
            topic="Akcja 'self_analyze'",
            description="Skutecznosc 20%, zatrzymaj loop",
            priority=0.95,
            suggested_action="experiment",
        )
        report = AnalysisReport(report_id="sa-test-1", recommendations=[rec])

        result = applier.apply(report)

        # Strategic rec must NOT create a misroute learning goal
        assert result["goals_created"] == []
        mock_store.propose.assert_not_called()

        # Strategic rec MUST post a bulletin IMPROVEMENT entry
        assert len(result["bulletin_posted"]) == 1

        from agent_core.bulletin.bulletin_model import EntryType
        entries = bulletin.get_by_type(EntryType.IMPROVEMENT)
        assert len(entries) == 1
        e = entries[0]
        assert e.requested_by == "self_analysis"
        assert e.priority == pytest.approx(0.95)
        assert e.metadata["rec_id"] == "rec-strat-1"
        assert e.metadata["report_id"] == "sa-test-1"
        assert e.metadata["category"] == "strategy_change"
        assert e.metadata["action_hint"] == "self_analyze"

    def test_strategy_change_skips_topic_hint(self, tmp_project):
        """Strategic rec topics like 'Akcja X' are not real topics —
        topic hint must be skipped to avoid polluting fetcher queue."""
        bulletin = self._make_bulletin(tmp_project)
        applier = RecommendationApplier(
            bulletin_store=bulletin,
            project_root=str(tmp_project),
        )
        rec = AnalysisRecommendation(
            rec_id="rec-strat-2",
            category="strategy_change",
            topic="proces nauki (learn action)",
            description="Mechanizm uszkodzony",
            priority=0.9,
            suggested_action="learn",
        )
        report = AnalysisReport(report_id="sa-test-2", recommendations=[rec])

        result = applier.apply(report)
        assert result["hints_written"] == 0
        hints_path = tmp_project / "meta_data" / "topic_hints.jsonl"
        assert not hints_path.exists()

    def test_non_strategic_no_goal_writes_hint(self, tmp_project):
        """R1 (2026-05-29): knowledge_gap recs no longer create goals; the
        fetch/learn action writes a topic hint instead (drives learning)."""
        bulletin = self._make_bulletin(tmp_project)
        mock_store = specced(GoalStore)
        mock_store.propose = MagicMock(return_value="goal-kg-1")
        applier = RecommendationApplier(
            goal_store=mock_store,
            bulletin_store=bulletin,
            project_root=str(tmp_project),
        )
        rec = AnalysisRecommendation(
            rec_id="rec-kg-1",
            category="knowledge_gap",
            topic="fizyka",
            description="Low confidence",
            priority=0.9,
            suggested_action="fetch",
        )
        report = AnalysisReport(report_id="sa-test-3", recommendations=[rec])

        result = applier.apply(report)
        assert result["goals_created"] == []
        assert result["bulletin_posted"] == []
        assert result["hints_written"] == 1
        mock_store.propose.assert_not_called()

    def test_strategic_without_bulletin_drops_silently(self, tmp_project):
        """No bulletin_store wired -> strategic rec is dropped, not misrouted."""
        mock_store = specced(GoalStore)
        mock_store.propose = MagicMock(return_value="goal-x")
        applier = RecommendationApplier(
            goal_store=mock_store,
            project_root=str(tmp_project),
        )
        rec = AnalysisRecommendation(
            rec_id="rec-strat-3",
            category="strategy_change",
            topic="Akcja 'learn'",
            description="...",
            priority=0.9,
            suggested_action="experiment",
        )
        report = AnalysisReport(report_id="sa-test-4", recommendations=[rec])

        result = applier.apply(report)
        assert result["goals_created"] == []
        assert result["bulletin_posted"] == []
        mock_store.propose.assert_not_called()

    def test_mixed_recommendations_routed_correctly(self, tmp_project):
        """Mix of strategic + non-strategic: each goes to its own channel."""
        bulletin = self._make_bulletin(tmp_project)
        mock_store = specced(GoalStore)
        mock_store.propose = MagicMock(side_effect=lambda g: g.id)
        applier = RecommendationApplier(
            goal_store=mock_store,
            bulletin_store=bulletin,
            project_root=str(tmp_project),
        )
        recs = [
            AnalysisRecommendation(
                rec_id="r-strat", category="strategy_change",
                topic="Akcja 'fetch'", description="0% success",
                priority=1.0, suggested_action="experiment",
            ),
            AnalysisRecommendation(
                rec_id="r-kg", category="knowledge_gap",
                topic="biologia", description="missing content",
                priority=0.8, suggested_action="learn",
            ),
            AnalysisRecommendation(
                rec_id="r-new", category="new_topic",
                topic="logika", description="unexplored area",
                priority=0.7, suggested_action="fetch",
            ),
        ]
        report = AnalysisReport(report_id="sa-mix", recommendations=recs)
        result = applier.apply(report)

        # R1: strategic -> bulletin (1), non-strategic -> topic hints (2), no goals.
        assert len(result["bulletin_posted"]) == 1
        assert result["goals_created"] == []
        assert result["hints_written"] == 2
        mock_store.propose.assert_not_called()

    def test_extract_action_hint_quoted(self, tmp_project):
        applier = RecommendationApplier(project_root=str(tmp_project))
        assert applier._extract_action_hint("Akcja 'self_analyze'") == "self_analyze"
        assert applier._extract_action_hint("Akcja 'learn'") == "learn"

    def test_extract_action_hint_inline_word(self, tmp_project):
        applier = RecommendationApplier(project_root=str(tmp_project))
        assert applier._extract_action_hint("proces nauki (learn action)") == "learn"
        assert applier._extract_action_hint("effector_actions") == "effector"

    def test_extract_action_hint_unknown_returns_none(self, tmp_project):
        applier = RecommendationApplier(project_root=str(tmp_project))
        assert applier._extract_action_hint("trudny temat (hard_topic)") is None
        assert applier._extract_action_hint("losowy ciag tekstu") is None
        assert applier._extract_action_hint("") is None


# =============================================================================
# R2.1 (2026-04-29): hint quality filter + dedup
# =============================================================================

class TestRecommendationApplierHintFilter:
    """K12 sometimes emits internal-meta rec topics that aren't searchable on
    wikipedia (e.g. "Obsługa błędów i fallback dla akcji 'learn'"). They
    pollute the fetcher queue and never resolve. Filter rejects obvious
    internal-meta shapes before write; dedup blocks repeat hints from the
    same K12 cycle landing as multiple jsonl entries."""

    def test_searchable_simple_topic_accepted(self, tmp_project):
        from agent_core.self_analysis.recommendation_applier import (
            _is_searchable_topic,
        )
        assert _is_searchable_topic("Logika formalna") is True
        assert _is_searchable_topic("Mechanika kwantowa") is True
        assert _is_searchable_topic("fizyka") is True
        # Two-word with parens (real wiki disambiguation) — accept
        assert _is_searchable_topic("Metoda naukowa") is True

    def test_quoted_action_topic_rejected(self, tmp_project):
        from agent_core.self_analysis.recommendation_applier import (
            _is_searchable_topic,
        )
        assert _is_searchable_topic("Akcja 'learn'") is False
        assert _is_searchable_topic("proces nauki 'fetch'") is False
        assert _is_searchable_topic('Strategia "self_analyze"') is False

    def test_k12_metadata_suffix_rejected(self, tmp_project):
        from agent_core.self_analysis.recommendation_applier import (
            _is_searchable_topic,
        )
        assert _is_searchable_topic("Analiza tekstu (hard_topic)") is False
        assert _is_searchable_topic("temat trudny (easy_topic)") is False
        assert _is_searchable_topic("proces (learn action)") is False

    def test_engineering_jargon_rejected(self, tmp_project):
        from agent_core.self_analysis.recommendation_applier import (
            _is_searchable_topic,
        )
        assert _is_searchable_topic("fallback dla planera") is False
        assert _is_searchable_topic("mechanizm walidacji") is False
        assert _is_searchable_topic("Obsluga bledow w pipeline") is False
        assert _is_searchable_topic("backoff strategii") is False
        # Unicode error-handling phrase
        assert _is_searchable_topic("Obsługa błędów i fallback") is False

    def test_too_long_topic_rejected(self, tmp_project):
        from agent_core.self_analysis.recommendation_applier import (
            _is_searchable_topic,
        )
        # 6+ words = sentence, not a wiki topic
        assert _is_searchable_topic(
            "Walidacja wiedzy i kryteria weryfikacji oraz testowanie"
        ) is False

    def test_empty_or_too_short_rejected(self, tmp_project):
        from agent_core.self_analysis.recommendation_applier import (
            _is_searchable_topic,
        )
        assert _is_searchable_topic("") is False
        assert _is_searchable_topic("   ") is False
        assert _is_searchable_topic("ab") is False
        assert _is_searchable_topic(None) is False  # type: ignore[arg-type]

    def test_unsearchable_hint_filtered_during_apply(self, tmp_project):
        """Apply with an internal-meta topic should not write to jsonl."""
        applier = RecommendationApplier(project_root=str(tmp_project))
        rec = AnalysisRecommendation(
            rec_id="r-meta-1",
            category="knowledge_gap",
            topic="Obsluga bledow i fallback dla akcji 'learn'",
            description="K12 sees missing error handler",
            priority=0.9,
            suggested_action="fetch",
        )
        report = AnalysisReport(report_id="sa-meta", recommendations=[rec])
        result = applier.apply(report)
        assert result["hints_written"] == 0
        hints_path = tmp_project / "meta_data" / "topic_hints.jsonl"
        assert not hints_path.exists()

    def test_duplicate_hint_skipped(self, tmp_project):
        """Second apply with same topic + still pending should not append."""
        applier = RecommendationApplier(project_root=str(tmp_project))
        rec = AnalysisRecommendation(
            rec_id="r-dup-1",
            category="knowledge_gap",
            topic="logika formalna",
            description="first",
            priority=0.9,
            suggested_action="fetch",
        )
        report1 = AnalysisReport(report_id="sa-1", recommendations=[rec])
        result1 = applier.apply(report1)
        assert result1["hints_written"] == 1

        # Second cycle proposes the same topic — should be filtered as duplicate
        rec2 = AnalysisRecommendation(
            rec_id="r-dup-2",
            category="knowledge_gap",
            topic="Logika Formalna",  # different casing on purpose
            description="second",
            priority=0.95,
            suggested_action="fetch",
        )
        report2 = AnalysisReport(report_id="sa-2", recommendations=[rec2])
        result2 = applier.apply(report2)
        assert result2["hints_written"] == 0

        # File should still have only one hint line
        hints_path = tmp_project / "meta_data" / "topic_hints.jsonl"
        with open(hints_path) as f:
            lines = [l for l in f if l.strip()]
        assert len(lines) == 1

    def test_duplicate_consumed_does_not_block_repropose(self, tmp_project):
        """A consumed (already fetched) hint should not block re-proposal —
        K12 may re-flag a topic after the article gets retired/archived."""
        import json as _json
        hints_path = tmp_project / "meta_data" / "topic_hints.jsonl"
        # Pre-seed a CONSUMED hint
        hints_path.write_text(
            _json.dumps({
                "topic": "fizyka",
                "source": "self_analysis",
                "report_id": "sa-old",
                "priority": 0.5,
                "timestamp": time.time() - 86400,
                "consumed": True,
            }, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        applier = RecommendationApplier(project_root=str(tmp_project))
        rec = AnalysisRecommendation(
            rec_id="r-repro",
            category="knowledge_gap",
            topic="fizyka",
            description="re-propose",
            priority=0.8,
            suggested_action="fetch",
        )
        report = AnalysisReport(report_id="sa-repro", recommendations=[rec])
        result = applier.apply(report)
        assert result["hints_written"] == 1


# =============================================================================
# SelfAnalysis facade
# =============================================================================

class TestSelfAnalysisFacade:

    def test_run_analysis_no_llm(self, tmp_project):
        sa = SelfAnalysis(project_root=str(tmp_project))
        report = sa.run_analysis()
        assert report.error is not None  # No LLM configured

    def test_run_analysis_full_cycle(self, populated_project):
        response_json = json.dumps({
            "recommendations": [
                {"category": "knowledge_gap", "topic": "fizyka",
                 "description": "Low confidence", "priority": 0.9,
                 "suggested_action": "fetch"},
            ],
        })
        mock_llm = MagicMock(return_value=response_json)

        sa = SelfAnalysis(project_root=str(populated_project))
        sa.set_llm_fn(mock_llm)

        report = sa.run_analysis()
        assert report.error is None
        assert len(report.recommendations) == 1
        assert report.recommendations[0].topic == "fizyka"
        assert report.duration_ms > 0

        # Report should be persisted
        reports_path = populated_project / "meta_data" / "self_analysis_reports.jsonl"
        assert reports_path.exists()

    def test_should_analyze_cooldown(self, tmp_project):
        sa = SelfAnalysis(project_root=str(tmp_project), cooldown_sec=100)
        sa._last_analysis_ts = time.time()  # Just analyzed
        assert sa.should_analyze() is False

    def test_should_analyze_expired(self, tmp_project):
        sa = SelfAnalysis(project_root=str(tmp_project), cooldown_sec=100)
        sa._last_analysis_ts = time.time() - 3700  # > 1h and > cooldown
        assert sa.should_analyze() is True

    def test_should_analyze_needs_human(self, tmp_project):
        sa = SelfAnalysis(project_root=str(tmp_project), cooldown_sec=86400)
        sa._last_analysis_ts = time.time() - 7200  # 2h ago (> 1h min)
        assert sa.should_analyze(needs_human=True) is True

    def test_should_analyze_low_retention(self, tmp_project):
        sa = SelfAnalysis(project_root=str(tmp_project), cooldown_sec=86400)
        sa._last_analysis_ts = time.time() - 7200
        assert sa.should_analyze(retention_rate=0.2) is True

    def test_should_analyze_absolute_minimum(self, tmp_project):
        sa = SelfAnalysis(project_root=str(tmp_project), cooldown_sec=100)
        sa._last_analysis_ts = time.time() - 1800  # 30 min (< 1h min)
        assert sa.should_analyze(needs_human=True) is False  # Absolute minimum 1h

    def test_get_last_report(self, populated_project):
        sa = SelfAnalysis(project_root=str(populated_project))

        # No reports yet
        assert sa.get_last_report() is None

        # Run analysis
        sa.set_llm_fn(MagicMock(return_value='{"recommendations": []}'))
        sa.run_analysis()

        # Now should have a report
        report = sa.get_last_report()
        assert report is not None
        assert report.report_id.startswith("sa-")

    def test_get_status(self, tmp_project):
        sa = SelfAnalysis(project_root=str(tmp_project))
        status = sa.get_status()
        assert "available" in status
        assert status["available"] is False  # No LLM

    def test_run_analysis_emits_introspection_signal(self, populated_project):
        # C6 fix: K12 must feed `introspection_run` to consciousness so
        # `refleksyjna` gets reinforced beyond session_with_summary alone.
        response_json = json.dumps({"recommendations": []})
        mock_llm = MagicMock(return_value=response_json)

        sa = SelfAnalysis(project_root=str(populated_project))
        sa.set_llm_fn(mock_llm)

        consc = specced(ConsciousnessCore)
        sa.set_consciousness(consc)

        sa.run_analysis()

        consc.record_experience.assert_called_once()
        assert consc.record_experience.call_args.args[0] == "introspection_run"

        sa.set_llm_fn(MagicMock())
        status = sa.get_status()
        assert status["available"] is True

    def test_report_persistence(self, tmp_project):
        sa = SelfAnalysis(project_root=str(tmp_project))
        sa.set_llm_fn(MagicMock(return_value=json.dumps({
            "recommendations": [
                {"topic": "test", "description": "t", "priority": 0.5,
                 "suggested_action": "learn"}
            ]
        })))

        r1 = sa.run_analysis()
        r2 = sa.run_analysis()

        # Both should be persisted
        path = tmp_project / "meta_data" / "self_analysis_reports.jsonl"
        with open(path) as f:
            lines = [l for l in f if l.strip()]
        assert len(lines) == 2


# =============================================================================
# Planner integration
# =============================================================================

class TestPlannerIntegration:

    def test_action_type_self_analyze_exists(self):
        from agent_core.planner.planner_model import ActionType
        assert ActionType.SELF_ANALYZE.value == "self_analyze"

    def test_planner_state_has_self_analysis_ts(self):
        from agent_core.planner.planner_model import PlannerState
        state = PlannerState()
        assert state.last_self_analysis_ts == 0.0

        # Serialization roundtrip
        d = state.to_dict()
        assert "last_self_analysis_ts" in d
        restored = PlannerState.from_dict(d)
        assert restored.last_self_analysis_ts == 0.0

    def test_action_executor_has_self_analyze(self):
        from agent_core.planner.action_executor import ActionExecutor
        executor = ActionExecutor()
        assert hasattr(executor, '_self_analysis')
        assert executor._self_analysis is None

    def test_k7_classification(self):
        from agent_core.autonomy.action_class import classify_action, ActionClassification
        cls = classify_action("self_analyze")
        assert cls == ActionClassification.ANALYTICAL

    def test_k7_rate_limit(self):
        # 1/h od 07-07: limiter jest jedynym hamulcem nocnej rotacji
        # (dzienny 4h-cooldown w _maybe_self_analyze jej nie dotyczy).
        from agent_core.autonomy.rate_limiter import DEFAULT_RATE_LIMITS
        assert "self_analyze" in DEFAULT_RATE_LIMITS
        assert DEFAULT_RATE_LIMITS["self_analyze"] == 1

    def test_k10_safety_profile(self):
        from agent_core.action_safety.safety_classifier import get_safety_profile
        from agent_core.action_safety.safety_model import SafetyMode, EffectType
        profile = get_safety_profile("self_analyze")
        assert profile.safety_mode == SafetyMode.AUDIT_ONLY
        assert profile.effect_type == EffectType.CONFIGURATION

    def test_shared_context_has_self_analysis(self):
        from agent_core.registry.shared_context import SharedContext
        ctx = SharedContext()
        assert hasattr(ctx, 'self_analysis')
        assert ctx.self_analysis is None

    def test_executor_self_analyze_no_system(self):
        from agent_core.planner.action_executor import ActionExecutor
        from agent_core.planner.planner_model import Plan, ActionType
        executor = ActionExecutor()
        plan = Plan(
            plan_id="test",
            timestamp=time.time(),
            goal_id=None,
            goal_description="test",
            action_type=ActionType.SELF_ANALYZE,
            action_params={},
            status=PlanStatus.PENDING,
        )
        result = executor.execute(plan)
        assert result["success"] is False
        assert "No self_analysis" in result["error"]

    def test_executor_self_analyze_with_system(self, populated_project):
        from agent_core.planner.action_executor import ActionExecutor
        from agent_core.planner.planner_model import Plan, ActionType

        sa = SelfAnalysis(project_root=str(populated_project))
        sa.set_llm_fn(MagicMock(return_value=json.dumps({
            "recommendations": [
                {"topic": "fizyka", "description": "gap", "priority": 0.9,
                 "suggested_action": "fetch"}
            ]
        })))

        executor = ActionExecutor()
        executor.set_self_analysis(sa)

        plan = Plan(
            plan_id="test",
            timestamp=time.time(),
            goal_id=None,
            goal_description="K12 Self-analysis",
            action_type=ActionType.SELF_ANALYZE,
            action_params={"period_days": 7},
            status=PlanStatus.PENDING,
        )
        result = executor.execute(plan)
        assert result["success"] is True
        assert result["recommendations"] == 1


# =============================================================================
# Prior recommendations feedback loop (K12 slow-loop closure)
# =============================================================================

class TestPriorRecommendations:
    """K12 reads its own past reports back, so it stops repeating itself.

    Before this, self_analysis_reports.jsonl had grown to 1551 reports since
    2026-03-24 without a single read-back: 7263 recommendations over 1336
    topics, 'system_stability' re-recommended from March to July.
    """

    def _write_reports(self, meta, entries):
        path = meta / "self_analysis_reports.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        return path

    def _report(self, ts, topics_actions):
        return {
            "report_id": f"sa-{ts:.0f}",
            "timestamp": ts,
            "recommendations": [
                {"topic": t, "suggested_action": a} for t, a in topics_actions
            ],
        }

    def test_absent_file_is_not_an_error(self, tmp_project):
        out = StateCollector(str(tmp_project))._collect_prior_recommendations(time.time())
        assert out["window_reports"] == 0
        assert out["recurring"] == []

    def test_repeated_topic_is_reported_with_counts(self, tmp_project):
        now = time.time()
        meta = tmp_project / "meta_data"
        self._write_reports(meta, [
            self._report(now - 30 * 86400, [("system_stability", "learn")]),
            self._report(now - 10 * 86400, [("system_stability", "learn")]),
            self._report(now - 2 * 86400, [("system_stability", "experiment")]),
        ])
        out = StateCollector(str(tmp_project))._collect_prior_recommendations(now)

        assert out["window_reports"] == 3
        rec = [r for r in out["recurring"] if r["topic"] == "system stability"]
        assert len(rec) == 1, "repeated topic must surface exactly once"
        rec = rec[0]
        assert rec["times_in_window"] == 3
        assert rec["first_seen_days_ago"] == pytest.approx(30, abs=0.5)
        assert rec["last_seen_days_ago"] == pytest.approx(2, abs=0.5)
        # The action shown must be the most RECENT one, not the first.
        assert rec["last_suggested_action"] == "experiment"

    def test_one_off_topic_is_not_flagged_as_recurring(self, tmp_project):
        now = time.time()
        meta = tmp_project / "meta_data"
        self._write_reports(meta, [self._report(now - 86400, [("seen_once", "learn")])])
        out = StateCollector(str(tmp_project))._collect_prior_recommendations(now)
        assert out["recurring"] == []
        assert out["distinct_topics_in_window"] == 1

    def test_underscore_and_space_variants_count_as_one_topic(self, tmp_project):
        """'learning_velocity' and 'learning velocity' are the same finding.

        Live data had 158 vs 20 hits for that pair; counting them apart
        understated the very repetition this field exists to expose, and hid
        the more recent of the two timestamps.
        """
        now = time.time()
        meta = tmp_project / "meta_data"
        self._write_reports(meta, [
            self._report(now - 20 * 86400, [("learning_velocity", "learn")]),
            self._report(now - 3 * 86400, [("Learning Velocity", "experiment")]),
        ])
        out = StateCollector(str(tmp_project))._collect_prior_recommendations(now)

        assert out["distinct_topics_in_window"] == 1
        assert len(out["recurring"]) == 1
        rec = out["recurring"][0]
        assert rec["topic"] == "learning velocity"
        assert rec["times_in_window"] == 2
        # Merging must also correct recency, not just the count.
        assert rec["last_seen_days_ago"] == pytest.approx(3, abs=0.5)

    def test_window_is_capped_and_labelled_as_a_window(self, tmp_project):
        """Counts are window-scoped; the field names must not promise all-time."""
        now = time.time()
        meta = tmp_project / "meta_data"
        many = [
            self._report(now - (500 - i) * 3600, [("noisy_topic", "learn")])
            for i in range(500)
        ]
        self._write_reports(meta, many)
        out = StateCollector(str(tmp_project))._collect_prior_recommendations(now)

        assert out["window_reports"] == 400, "tail read must cap the window"
        assert out["recurring"][0]["times_in_window"] == 400
        assert "window_days" in out

    def test_corrupt_line_does_not_derail_the_read(self, tmp_project):
        now = time.time()
        meta = tmp_project / "meta_data"
        path = meta / "self_analysis_reports.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._report(now - 86400, [("real_topic", "learn")])) + "\n")
            f.write("{ this is not json\n")
            f.write(json.dumps(self._report(now - 3600, [("real_topic", "learn")])) + "\n")
        out = StateCollector(str(tmp_project))._collect_prior_recommendations(now)
        assert out["recurring"][0]["times_in_window"] == 2

    def test_tail_read_returns_the_last_records(self, tmp_project):
        """Reading from the end must not lose or duplicate the boundary record."""
        meta = tmp_project / "meta_data"
        path = meta / "self_analysis_reports.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for i in range(300):
                f.write(json.dumps({"n": i, "pad": "x" * 500}) + "\n")
        got = StateCollector(str(tmp_project))._tail_jsonl(path, 120)
        assert len(got) == 120
        assert [r["n"] for r in got] == list(range(180, 300))

    def test_collect_exposes_prior_recommendations(self, populated_project):
        """The field must reach the analyst, not just exist as a helper."""
        summary = StateCollector(str(populated_project)).collect()
        assert "prior_recommendations" in summary

    def test_prompt_instructs_the_analyst_what_to_do_with_history(self, populated_project):
        """History without an instruction is just more noise in the prompt."""
        summary = StateCollector(str(populated_project)).collect_with_prompt()
        prompt = summary["analysis_prompt"]
        assert "prior_recommendations" in prompt
        assert "systemic_issues" in prompt


# =============================================================================
# Systemic issues + summary: the two report sections that used to be discarded
# =============================================================================

class TestNarrativeSections:
    """The prompt asks for three sections; only one used to survive parsing.

    On a live run the discarded ones held "the recommendation loop itself is
    broken" and a summary that correctly named a 100% exam failure rate as the
    priority, while the kept section listed topics to learn.
    """

    def _json_response(self, **over):
        payload = {
            "recommendations": [
                {"category": "knowledge_gap", "topic": "synthesis",
                 "description": "stale goal", "priority": 0.8,
                 "suggested_action": "learn"},
            ],
            "systemic_issues": [
                "petla rekomendacji jest zepsuta",
                "egzaminy oblewane w 100%",
            ],
            "summary": "Maria stoi w trybie reduced przez 84% cykli.",
        }
        payload.update(over)
        return json.dumps(payload)

    def test_parse_narrative_extracts_both_sections(self):
        an = ExternalAnalyzer()
        issues, summary = an._parse_narrative(self._json_response())
        assert issues == ["petla rekomendacji jest zepsuta",
                          "egzaminy oblewane w 100%"]
        assert "reduced" in summary

    def test_parse_narrative_survives_markdown_fencing(self):
        an = ExternalAnalyzer()
        fenced = "```json\n" + self._json_response() + "\n```"
        issues, summary = an._parse_narrative(fenced)
        assert len(issues) == 2
        assert summary

    def test_freetext_yields_no_narrative(self):
        """Empty here means 'no JSON returned', NOT 'nothing is wrong'."""
        an = ExternalAnalyzer()
        assert an._parse_narrative("zwykla proza bez jsona") == ([], "")

    def test_issues_are_capped(self):
        an = ExternalAnalyzer()
        many = self._json_response(systemic_issues=[f"problem {i}" for i in range(20)])
        issues, _ = an._parse_narrative(many)
        assert len(issues) == MAX_SYSTEMIC_ISSUES

    def test_analyzer_puts_narrative_on_the_report(self):
        """End to end: a backend response must land the narrative on the report."""
        an = ExternalAnalyzer()
        an.set_nim_fn(lambda _p: self._json_response())
        report = an.analyze({"input_hash": "abc", "analysis_prompt": "x"})
        assert report.error is None
        assert len(report.recommendations) == 1
        assert len(report.systemic_issues) == 2
        assert "reduced" in report.summary

    def test_report_roundtrip_preserves_the_narrative(self):
        report = AnalysisReport(
            systemic_issues=["a", "b"],
            summary="podsumowanie",
        )
        restored = AnalysisReport.from_dict(report.to_dict())
        assert restored.systemic_issues == ["a", "b"]
        assert restored.summary == "podsumowanie"

    def test_from_dict_tolerates_reports_written_before_the_fields_existed(self):
        """5.9MB of historical reports predate these two fields."""
        restored = AnalysisReport.from_dict({"report_id": "sa-old"})
        assert restored.systemic_issues == []
        assert restored.summary == ""


class TestTelegramCardSections:

    def _report(self):
        return AnalysisReport(
            model="nemotron",
            recommendations=[
                AnalysisRecommendation(
                    rec_id=f"r{i}", category="knowledge_gap", topic=f"temat{i}",
                    description="opis", priority=0.5, suggested_action="learn",
                )
                for i in range(5)
            ],
            systemic_issues=["petla rekomendacji jest zepsuta", "egzaminy 0%"],
            summary="Maria stoi w trybie reduced.",
        )

    def test_issues_come_back_separately_from_recommendations(self):
        summary, recs, issues = format_report_for_telegram(self._report())
        assert len(issues) == 2
        assert len(recs) == 5

    def test_issues_do_not_consume_recommendation_slots(self):
        """The notifier renders only five recommendation lines.

        Folding systemic issues into that list would let a cross-cutting
        diagnosis push out concrete advice, or be pushed out by it.
        """
        _, recs, issues = format_report_for_telegram(self._report())
        assert all("petla rekomendacji" not in r for r in recs)
        assert len(recs) == 5

    def test_summary_reaches_the_card(self):
        summary, _, _ = format_report_for_telegram(self._report())
        assert "reduced" in summary

    def test_head_counts_both_sections(self):
        summary, _, _ = format_report_for_telegram(self._report())
        assert "5 rekomendacji" in summary
        assert "2 problemy ukladowe" in summary

    def test_shift_footer_is_appended_when_status_given(self):
        status = {"runs_today": 2, "spent_min": 34.0, "budget_min": 90.0}
        summary, _, _ = format_report_for_telegram(self._report(), status)
        assert "przebieg 2" in summary
        assert "34 z 90 min" in summary

    def test_no_footer_without_status(self):
        summary, _, _ = format_report_for_telegram(self._report())
        assert "zmiana:" not in summary

    def test_card_fits_the_notifier_summary_budget(self):
        """The notifier truncates the summary block at 500 chars.

        If the parts overflow, the shift footer -- appended last -- is what
        gets cut, so the pacing line would vanish exactly when the evening is
        busiest.
        """
        report = self._report()
        report.summary = "x" * 2000
        status = {"runs_today": 3, "spent_min": 88.0, "budget_min": 90.0}
        summary, _, _ = format_report_for_telegram(report, status)
        assert len(summary) <= 500
        assert "88 z 90 min" in summary

    def test_empty_narrative_degrades_to_the_old_card(self):
        report = AnalysisReport(model="qwen3:8b")
        summary, recs, issues = format_report_for_telegram(report)
        assert issues == []
        assert recs == []
        assert "0 rekomendacji" in summary

    def test_long_summary_is_cut_on_a_word_boundary(self):
        """Two truncations in a row let the crude one win.

        _parse_narrative used to cut to the display budget with a raw slice;
        the formatter's word-boundary trim then saw a string already at the
        limit and passed it through, so a live card ended "...acted upon. The
        sta" with no ellipsis. Parse-time now stores wide, display-time trims.
        """
        report = self._report()
        report.summary = ("Maria gromadzi pliki ale nie zamienia wiedzy na zdane "
                          "egzaminy oraz stoi w trybie reduced przez wiekszosc czasu. ") * 6
        summary, _, _ = format_report_for_telegram(report)
        body = summary.split("\n")[1]
        assert body.endswith("...")
        assert not body.endswith(" ...")
        # The cut must land between words, never inside one.
        assert body[:-3].rstrip() == body[:-3]
        assert len(summary) <= 500


# =============================================================================
# MODEL-08: the local analyst seat (K12 evening shift head)
# =============================================================================

class TestLocalAnalystTier:
    """The seat NIM vacates on 2026-08-18.

    Without it the cascade falls from a 550B cloud model straight to qwen3:8b,
    which is a tick-latency planner seat, not an analyst's.
    """

    _JSON = json.dumps({
        "recommendations": [{"category": "knowledge_gap", "topic": "t",
                             "description": "d", "priority": 0.5,
                             "suggested_action": "learn"}],
        "systemic_issues": ["cos jest ukladowo zle"],
        "summary": "podsumowanie",
    })

    def test_no_tag_means_the_tier_is_skipped(self, monkeypatch):
        """Empty tag = socket without a bulb: today's behaviour, not a failure."""
        monkeypatch.delenv("K12_ANALYST_MODEL", raising=False)
        an = ExternalAnalyzer()
        an.set_analyst_fn(lambda _p: self._JSON)
        assert an._analyze_with_analyst({"input_hash": "x"}) is None

    def test_tag_without_a_wired_fn_is_skipped(self, monkeypatch):
        monkeypatch.setenv("K12_ANALYST_MODEL", "qwen3:30b-a3b")
        an = ExternalAnalyzer()
        assert an._analyze_with_analyst({"input_hash": "x"}) is None

    def test_analyst_parses_all_three_sections(self, monkeypatch):
        monkeypatch.setenv("K12_ANALYST_MODEL", "qwen3:30b-a3b")
        an = ExternalAnalyzer()
        an.set_analyst_fn(lambda _p: self._JSON)
        report = an._analyze_with_analyst({"input_hash": "x", "analysis_prompt": "p"})
        assert report.error is None
        assert report.analyzer == "local_analyst"
        assert report.model == "qwen3:30b-a3b"
        assert len(report.recommendations) == 1
        assert report.systemic_issues == ["cos jest ukladowo zle"]
        assert report.summary == "podsumowanie"

    def test_cascade_prefers_nim_while_the_key_lives(self, monkeypatch):
        monkeypatch.setenv("K12_ANALYST_MODEL", "qwen3:30b-a3b")
        an = ExternalAnalyzer()
        an.set_nim_fn(lambda _p: self._JSON)
        an.set_analyst_fn(lambda _p: pytest.fail("analyst must not run while NIM answers"))
        report = an.analyze({"input_hash": "x", "analysis_prompt": "p"})
        assert report.analyzer == "nim_api"

    def test_analyst_takes_over_when_nim_fails(self, monkeypatch):
        """2026-08-18 in miniature."""
        monkeypatch.setenv("K12_ANALYST_MODEL", "qwen3:30b-a3b")

        def _dead_nim(_p):
            raise RuntimeError("401 key expired")

        an = ExternalAnalyzer()
        an.set_nim_fn(_dead_nim)
        an.set_analyst_fn(lambda _p: self._JSON)
        an.set_llm_fn(lambda _p: pytest.fail("must not demote to the planner model"))
        report = an.analyze({"input_hash": "x", "analysis_prompt": "p"})
        assert report.analyzer == "local_analyst"
        assert report.systemic_issues

    def test_analyst_failure_still_degrades_to_the_planner(self, monkeypatch):
        """The seat must never be a single point of failure for K12."""
        monkeypatch.setenv("K12_ANALYST_MODEL", "qwen3:30b-a3b")
        an = ExternalAnalyzer()
        an.set_analyst_fn(lambda _p: (_ for _ in ()).throw(RuntimeError("oom")))
        an.set_llm_fn(lambda _p: self._JSON)
        report = an.analyze({"input_hash": "x", "analysis_prompt": "p"})
        assert report.analyzer == "local_planner"
        assert len(report.recommendations) == 1


class TestAnalystRegistry:

    def test_analyst_role_is_heavy_and_cold(self):
        """18.6GB in 26GB of RAM: mutex-protected, loaded only for the shift."""
        from agent_core.llm.model_registry import (
            ModelRole, get_model, ConcurrencyClass, WarmState,
        )
        spec = get_model(ModelRole.ANALYST)
        assert spec.concurrency_class == ConcurrencyClass.HEAVY
        assert spec.warm_state == WarmState.COLD
        assert spec.block_if_heavy_active is True
        assert spec.idle_unload_s > 0, "an 18GB model must not linger in RAM"
        assert spec.fallback_role == ModelRole.PLANNER

    def test_untagged_analyst_stays_out_of_the_local_model_list(self):
        from agent_core.llm.model_registry import ModelRole, get_local_models
        roles = {s.role for s in get_local_models()}
        if not os.getenv("K12_ANALYST_MODEL", "").strip():
            assert ModelRole.ANALYST not in roles
