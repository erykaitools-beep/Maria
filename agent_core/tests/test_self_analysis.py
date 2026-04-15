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
    MAX_PROPOSED_GOALS_FROM_ANALYSIS,
    _gen_id,
)
from agent_core.self_analysis.state_collector import StateCollector
from agent_core.self_analysis.external_analyzer import ExternalAnalyzer
from agent_core.self_analysis.recommendation_applier import RecommendationApplier, MAX_HINTS
from agent_core.self_analysis import SelfAnalysis
from agent_core.planner.planner_model import Plan, ActionType, PlanStatus


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

    def test_apply_with_goal_store(self, tmp_project):
        mock_store = MagicMock()
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
        assert "goal-123" in result["goals_created"]
        mock_store.propose.assert_called_once()

    def test_apply_max_goals(self, tmp_project):
        mock_store = MagicMock()
        mock_store.propose = MagicMock(side_effect=lambda **kw: f"goal-{kw['description'][:5]}")

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

        assert len(result["goals_created"]) <= MAX_PROPOSED_GOALS_FROM_ANALYSIS

    def test_apply_with_world_model(self, tmp_project):
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

    def test_set_dependencies(self, tmp_project):
        applier = RecommendationApplier(project_root=str(tmp_project))
        mock_store = MagicMock()
        mock_wm = MagicMock()
        applier.set_goal_store(mock_store)
        applier.set_world_model(mock_wm)
        assert applier._goal_store is mock_store
        assert applier._world_model is mock_wm

    def test_topic_hints_pruned_to_max(self, tmp_project):
        applier = RecommendationApplier(project_root=str(tmp_project))

        for i in range(MAX_HINTS + 25):
            rec = AnalysisRecommendation(
                rec_id=f"r{i}",
                category="knowledge_gap",
                topic=f"topic_{i}",
                description="desc",
                priority=0.5,
                suggested_action="fetch",
            )
            report = AnalysisReport(report_id=f"rep-{i}", recommendations=[rec])
            applier.apply(report)

        hints_path = tmp_project / "meta_data" / "topic_hints.jsonl"
        lines = [line for line in hints_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == MAX_HINTS
        assert all('"topic_0"' not in line for line in lines)


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
        assert cls == ActionClassification.GUARDED

    def test_k7_rate_limit(self):
        from agent_core.autonomy.rate_limiter import DEFAULT_RATE_LIMITS
        assert "self_analyze" in DEFAULT_RATE_LIMITS
        assert DEFAULT_RATE_LIMITS["self_analyze"] == 2

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
