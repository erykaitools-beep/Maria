"""Tests for agent_core/experiment/ - K11 Experiment System (Phases 1-2)."""

import json
import time
import pytest
from pathlib import Path

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
from agent_core.experiment import parameter_registry
from agent_core.experiment.proposal_engine import ProposalEngine


# ── ParameterSpec tests ─────────────────────────────────────────


class TestParameterSpec:
    def test_frozen(self):
        spec = ParameterSpec(
            param_id="test.X", module_path="m", constant_name="X",
            current_value=10, value_type="int",
            min_value=0, max_value=100, step=5,
            risk_level=RiskLevel.LOW, impact_metric="m", description="d",
        )
        with pytest.raises(AttributeError):
            spec.current_value = 20

    def test_fields(self):
        spec = ParameterSpec(
            param_id="test.Y", module_path="mod", constant_name="Y",
            current_value=0.5, value_type="float",
            min_value=0.0, max_value=1.0, step=0.1,
            risk_level=RiskLevel.MEDIUM, impact_metric="retention_rate",
            description="Test param",
        )
        assert spec.param_id == "test.Y"
        assert spec.risk_level == RiskLevel.MEDIUM
        assert spec.step == 0.1


# ── Proposal tests ──────────────────────────────────────────────


class TestProposal:
    def test_create_proposal(self):
        p = create_proposal(
            source=ProposalSource.K4_RECOMMENDATION,
            parameter_id="config.EXAM_PASS_THRESHOLD",
            current_value=0.6,
            proposed_value=0.65,
            hypothesis="test hypothesis",
            rationale="test rationale",
            expected_outcome="test outcome",
        )
        assert p.proposal_id.startswith("prop-")
        assert p.status == ProposalStatus.DRAFT
        assert p.proposed_value == 0.65
        assert p.timestamp > 0

    def test_roundtrip(self):
        p = create_proposal(
            source=ProposalSource.K9_PATTERN,
            parameter_id="config.TARGET_CHUNK_SIZE",
            current_value=1200,
            proposed_value=1000,
            hypothesis="h", rationale="r", expected_outcome="e",
            risk_assessment="LOW",
            trigger_data={"slow_count": 5},
        )
        d = p.to_dict()
        p2 = Proposal.from_dict(d)
        assert p2.proposal_id == p.proposal_id
        assert p2.source == ProposalSource.K9_PATTERN
        assert p2.trigger_data == {"slow_count": 5}
        assert p2.risk_assessment == "LOW"

    def test_add_comment(self):
        p = create_proposal(
            source=ProposalSource.MANUAL,
            parameter_id="test.X",
            current_value=1, proposed_value=2,
            hypothesis="h", rationale="r", expected_outcome="e",
        )
        p.add_comment("Dobry pomysl", "eryk")
        assert len(p.comments) == 1
        assert p.comments[0]["text"] == "Dobry pomysl"
        assert p.comments[0]["author"] == "eryk"
        assert p.comments[0]["timestamp"] > 0

    def test_comments_persist_in_roundtrip(self):
        p = create_proposal(
            source=ProposalSource.MANUAL,
            parameter_id="test.X",
            current_value=1, proposed_value=2,
            hypothesis="h", rationale="r", expected_outcome="e",
        )
        p.add_comment("komentarz 1")
        p.add_comment("komentarz 2", "maria")
        d = p.to_dict()
        p2 = Proposal.from_dict(d)
        assert len(p2.comments) == 2
        assert p2.comments[1]["author"] == "maria"


# ── Experiment tests ────────────────────────────────────────────


class TestExperiment:
    def test_create_from_proposal(self):
        p = create_proposal(
            source=ProposalSource.K4_RECOMMENDATION,
            parameter_id="config.EXAM_PASS_THRESHOLD",
            current_value=0.6, proposed_value=0.65,
            hypothesis="h", rationale="r", expected_outcome="e",
        )
        exp = create_experiment(p)
        assert exp.experiment_id.startswith("exp-")
        assert exp.proposal_id == p.proposal_id
        assert exp.baseline_value == 0.6
        assert exp.test_value == 0.65
        assert exp.status == ExperimentStatus.PENDING

    def test_duration(self):
        exp = Experiment(
            experiment_id="exp-test", proposal_id="p", parameter_id="x",
            baseline_value=1, test_value=2,
            started_at=100.0, finished_at=200.0,
        )
        assert exp.duration_sec == 100.0

    def test_duration_none(self):
        exp = Experiment(
            experiment_id="exp-test", proposal_id="p", parameter_id="x",
            baseline_value=1, test_value=2,
        )
        assert exp.duration_sec is None

    def test_roundtrip(self):
        exp = Experiment(
            experiment_id="exp-abc", proposal_id="prop-abc",
            parameter_id="config.X", baseline_value=0.6, test_value=0.7,
            status=ExperimentStatus.COMPLETED,
            baseline_metrics={"retention_rate": 0.5},
            result_metrics={"retention_rate": 0.65},
            test_cycles=5,
        )
        d = exp.to_dict()
        exp2 = Experiment.from_dict(d)
        assert exp2.experiment_id == "exp-abc"
        assert exp2.status == ExperimentStatus.COMPLETED
        assert exp2.baseline_metrics["retention_rate"] == 0.5


# ── ExperimentReport tests ──────────────────────────────────────


class TestExperimentReport:
    def test_roundtrip(self):
        r = ExperimentReport(
            report_id="rep-abc", experiment_id="exp-abc",
            proposal_id="prop-abc", timestamp=time.time(),
            hypothesis="h", method="m",
            parameter_id="config.X", baseline_value=0.6, test_value=0.65,
            baseline_metrics={"retention_rate": 0.5},
            result_metrics={"retention_rate": 0.58},
            delta_metrics={"retention_rate": 0.08},
            test_cycles=5, duration_sec=300.0,
            conclusion="improved", recommendation="ADOPT",
            confidence=0.8,
        )
        d = r.to_dict()
        r2 = ExperimentReport.from_dict(d)
        assert r2.report_id == "rep-abc"
        assert r2.recommendation == "ADOPT"
        assert r2.delta_metrics["retention_rate"] == 0.08
        assert r2.confidence == 0.8


# ── Parameter Registry tests ────────────────────────────────────


class TestParameterRegistry:
    def test_all_params_have_bounds(self):
        for pid, spec in parameter_registry.list_parameters().items():
            assert spec.min_value < spec.max_value, f"{pid}: min >= max"
            assert spec.step > 0, f"{pid}: step <= 0"
            assert spec.min_value <= spec.current_value <= spec.max_value, \
                f"{pid}: current_value out of bounds"

    def test_get_existing(self):
        spec = parameter_registry.get_parameter("config.EXAM_PASS_THRESHOLD")
        assert spec is not None
        assert spec.current_value == 0.6
        assert spec.risk_level == RiskLevel.MEDIUM

    def test_get_missing(self):
        assert parameter_registry.get_parameter("nonexistent") is None

    def test_validate_in_bounds(self):
        assert parameter_registry.validate_value("config.EXAM_PASS_THRESHOLD", 0.7)

    def test_validate_out_of_bounds(self):
        assert not parameter_registry.validate_value("config.EXAM_PASS_THRESHOLD", 0.95)
        assert not parameter_registry.validate_value("config.EXAM_PASS_THRESHOLD", 0.3)

    def test_validate_missing_param(self):
        assert not parameter_registry.validate_value("nonexistent", 0.5)

    def test_get_by_risk(self):
        low = parameter_registry.get_by_risk(RiskLevel.LOW)
        assert len(low) >= 2
        for spec in low.values():
            assert spec.risk_level == RiskLevel.LOW

    def test_get_by_metric(self):
        retention = parameter_registry.get_by_metric("retention_rate")
        assert len(retention) >= 2
        for spec in retention.values():
            assert spec.impact_metric == "retention_rate"

    def test_registry_has_all_risk_levels(self):
        for risk in RiskLevel:
            params = parameter_registry.get_by_risk(risk)
            assert len(params) >= 1, f"No params with risk={risk.value}"


# ── ProposalEngine tests ────────────────────────────────────────


class TestProposalEngine:

    def _make_engine(self, tmp_path) -> ProposalEngine:
        return ProposalEngine(proposals_path=tmp_path / "proposals.jsonl")

    def test_low_retention_triggers(self, tmp_path):
        engine = self._make_engine(tmp_path)

        # First scan - streak=1, not enough
        result1 = engine.scan(
            k4_metrics={"retention_rate": 0.45},
            k4_recommendations=[], k9_patterns={},
        )
        assert len(result1) == 0

        # Second scan - streak=2, triggers
        result2 = engine.scan(
            k4_metrics={"retention_rate": 0.50},
            k4_recommendations=[], k9_patterns={},
        )
        assert len(result2) == 1
        p = result2[0]
        assert p.parameter_id == "config.EXAM_PASS_THRESHOLD"
        assert p.proposed_value > p.current_value  # raising threshold
        assert p.source == ProposalSource.K4_RECOMMENDATION

    def test_low_retention_resets_on_good_score(self, tmp_path):
        engine = self._make_engine(tmp_path)

        engine.scan(k4_metrics={"retention_rate": 0.45},
                    k4_recommendations=[], k9_patterns={})
        # Good score resets streak
        engine.scan(k4_metrics={"retention_rate": 0.8},
                    k4_recommendations=[], k9_patterns={})
        # Another low - streak back to 1
        result = engine.scan(k4_metrics={"retention_rate": 0.45},
                             k4_recommendations=[], k9_patterns={})
        assert len(result) == 0  # streak=1, needs 2

    def test_consecutive_failures_triggers(self, tmp_path):
        engine = self._make_engine(tmp_path)

        result = engine.scan(
            k4_metrics={},
            k4_recommendations=[],
            k9_patterns={"consecutive_failures": {"exam": 4}},
        )
        assert len(result) == 1
        p = result[0]
        assert p.parameter_id == "config.EXAM_PASS_THRESHOLD"
        assert p.proposed_value < p.current_value  # lowering threshold

    def test_consecutive_failures_no_trigger_below_threshold(self, tmp_path):
        engine = self._make_engine(tmp_path)

        result = engine.scan(
            k4_metrics={},
            k4_recommendations=[],
            k9_patterns={"consecutive_failures": {"exam": 2}},
        )
        assert len(result) == 0

    def test_high_coverage_triggers(self, tmp_path):
        engine = self._make_engine(tmp_path)

        result = engine.scan(
            k4_metrics={"knowledge_coverage": 0.95, "new_files_count": 0},
            k4_recommendations=[], k9_patterns={},
        )
        assert len(result) == 1
        p = result[0]
        assert p.parameter_id == "planner.ROUTINE_INTERVAL_TICKS"

    def test_high_coverage_no_trigger_with_new_files(self, tmp_path):
        engine = self._make_engine(tmp_path)

        result = engine.scan(
            k4_metrics={"knowledge_coverage": 0.95, "new_files_count": 3},
            k4_recommendations=[], k9_patterns={},
        )
        assert len(result) == 0

    def test_slow_execution_triggers(self, tmp_path):
        engine = self._make_engine(tmp_path)

        result = engine.scan(
            k4_metrics={}, k4_recommendations=[],
            k9_patterns={"recent_lessons": [
                {"lesson_type": "slow_execution", "message": "300s"},
                {"lesson_type": "slow_execution", "message": "350s"},
                {"lesson_type": "slow_execution", "message": "400s"},
            ]},
        )
        assert len(result) == 1
        p = result[0]
        assert p.parameter_id == "config.TARGET_CHUNK_SIZE"
        assert p.proposed_value < p.current_value

    def test_cooldown_prevents_duplicate(self, tmp_path):
        engine = self._make_engine(tmp_path)

        # First trigger
        engine.scan(
            k4_metrics={}, k4_recommendations=[],
            k9_patterns={"consecutive_failures": {"exam": 5}},
        )

        # Second scan with same pattern - should be on cooldown
        result = engine.scan(
            k4_metrics={}, k4_recommendations=[],
            k9_patterns={"consecutive_failures": {"exam": 5}},
        )
        assert len(result) == 0

    def test_max_active_proposals_limit(self, tmp_path):
        engine = self._make_engine(tmp_path)
        engine._ensure_loaded()

        # Create 3 proposals manually to fill limit
        for i in range(3):
            p = create_proposal(
                source=ProposalSource.MANUAL,
                parameter_id=f"test.param_{i}",
                current_value=i, proposed_value=i + 1,
                hypothesis="h", rationale="r", expected_outcome="e",
            )
            engine._proposals.append(p)

        # Should not create more
        result = engine.scan(
            k4_metrics={}, k4_recommendations=[],
            k9_patterns={"consecutive_failures": {"exam": 5}},
        )
        assert len(result) == 0

    def test_update_status(self, tmp_path):
        engine = self._make_engine(tmp_path)

        result = engine.scan(
            k4_metrics={}, k4_recommendations=[],
            k9_patterns={"consecutive_failures": {"exam": 5}},
        )
        p = result[0]

        ok = engine.update_status(p.proposal_id, ProposalStatus.APPROVED, goal_id="goal-123")
        assert ok

        updated = engine.get_proposal(p.proposal_id)
        assert updated.status == ProposalStatus.APPROVED
        assert updated.goal_id == "goal-123"

    def test_persistence_roundtrip(self, tmp_path):
        engine1 = self._make_engine(tmp_path)
        engine1.scan(
            k4_metrics={}, k4_recommendations=[],
            k9_patterns={"consecutive_failures": {"exam": 5}},
        )

        # Load in new engine instance
        engine2 = self._make_engine(tmp_path)
        proposals = engine2.get_all_proposals()
        assert len(proposals) == 1
        assert proposals[0].parameter_id == "config.EXAM_PASS_THRESHOLD"

    def test_add_comment_persists(self, tmp_path):
        engine = self._make_engine(tmp_path)
        engine.scan(
            k4_metrics={}, k4_recommendations=[],
            k9_patterns={"consecutive_failures": {"exam": 5}},
        )
        p = engine.get_active_proposals()[0]
        engine.add_comment(p.proposal_id, "Sprawdze to jutro", "eryk")

        # Reload
        engine2 = self._make_engine(tmp_path)
        p2 = engine2.get_proposal(p.proposal_id)
        assert len(p2.comments) == 1
        assert p2.comments[0]["text"] == "Sprawdze to jutro"

    def test_get_status(self, tmp_path):
        engine = self._make_engine(tmp_path)
        engine.scan(
            k4_metrics={}, k4_recommendations=[],
            k9_patterns={"consecutive_failures": {"exam": 5}},
        )
        status = engine.get_status()
        assert status["total_proposals"] == 1
        assert status["active"] == 1
        assert status["by_status"]["draft"] == 1

    def test_no_match_returns_empty(self, tmp_path):
        engine = self._make_engine(tmp_path)
        result = engine.scan(
            k4_metrics={"retention_rate": 0.9, "knowledge_coverage": 0.5},
            k4_recommendations=[],
            k9_patterns={"consecutive_failures": {}},
        )
        assert len(result) == 0
