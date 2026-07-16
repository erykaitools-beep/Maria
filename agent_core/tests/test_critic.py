"""
Tests for Faza G: Critic Agent - knowledge quality gate.

Covers: critique_model, knowledge_critic (7 dimensions),
critique_applier, CriticAgent facade, and planner integration.
"""

import json
import math
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_core.tests.spec_helpers import specced
from agent_core.bulletin.bulletin_store import BulletinStore
from agent_core.bulletin.bulletin_model import BulletinEntry
from agent_core.cross_validation.dispute_log import DisputeLog
from agent_core.critic import CriticAgent
from agent_core.goals.store import GoalStore
from agent_core.goals.goal_model import Goal
from agent_core.planner.planner_model import Plan
from agent_core.world_model.belief_store import BeliefStore

from agent_core.critic.critique_model import (
    CritiqueFinding,
    CritiqueReport,
    FindingCategory,
    FindingSeverity,
    SuggestedCritiqueAction,
    GOAL_TITLE_MAP,
    MAX_FINDINGS_PER_REPORT,
    MAX_PROPOSED_GOALS_FROM_CRITIQUE,
    DEFAULT_CRITIQUE_COOLDOWN_SEC,
    COVERAGE_GRACE_PERIOD_DAYS,
    create_finding,
    _gen_id,
    _normalize_topic,
    _make_dedupe_key,
)
from agent_core.critic.knowledge_critic import KnowledgeCritic
from agent_core.critic.critique_applier import CritiqueApplier


# =============================================================================
# Helpers
# =============================================================================

def _make_belief(
    belief_id="b-001",
    entity="fizyka",
    entity_type=None,
    belief_type=None,
    content="Fizyka to nauka o przyrodzie",
    confidence=0.7,
    source=None,
    source_id="file_001",
    tags=("fizyka",),
    created_at=None,
    updated_at=None,
    revision=1,
    superseded_by=None,
    related_entities=(),
    evidence=(),
    status="active",
    retraction=None,
):
    """Create a mock belief object."""
    from enum import Enum

    class _ET(Enum):
        TOPIC = "topic"

    class _BT(Enum):
        FACT = "fact"
        OBSERVATION = "observation"
        HYPOTHESIS = "hypothesis"

    class _BS(Enum):
        LEARNING = "learning"
        EXAM = "exam"

    now = time.time()
    from agent_core.world_model.belief_model import Belief as _BeliefCls
    b = specced(_BeliefCls)
    b.belief_id = belief_id
    b.entity = entity
    b.entity_type = entity_type or _ET.TOPIC
    b.belief_type = belief_type or _BT.OBSERVATION
    b.content = content
    b.confidence = confidence
    b.source = source or _BS.LEARNING
    b.source_id = source_id
    b.tags = tags
    b.created_at = created_at or now
    b.updated_at = updated_at or now
    b.revision = revision
    b.superseded_by = superseded_by
    b.related_entities = related_entities
    b.evidence = evidence
    b.status = status
    b.retraction = retraction
    return b


def _make_belief_store(beliefs):
    """Create mock BeliefStore with given beliefs."""
    store = specced(BeliefStore, _beliefs={b.belief_id: b for b in beliefs})
    return store


def _write_exam_results(path, records):
    """Write exam results JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _write_knowledge_index(path, records):
    """Write knowledge index JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


@pytest.fixture
def tmp_project(tmp_path):
    """Temp project with meta_data/ and memory/ dirs."""
    (tmp_path / "meta_data").mkdir()
    (tmp_path / "memory").mkdir()
    return tmp_path


# =============================================================================
# A. Model tests (critique_model.py)
# =============================================================================

class TestCritiqueModel:

    def test_finding_creation(self):
        f = create_finding(
            category=FindingCategory.CONTRADICTION,
            severity=FindingSeverity.CRITICAL,
            topic="fizyka",
            description="Test contradiction",
            suggested_action=SuggestedCritiqueAction.RESOLVE,
        )
        assert f.category == "contradiction"
        assert f.severity == "critical"
        assert f.topic == "fizyka"
        assert f.topic_normalized == "fizyka"
        assert f.finding_id.startswith("cf-")

    def test_finding_to_dict_from_dict(self):
        f = create_finding(
            category=FindingCategory.OVERCONFIDENT,
            severity=FindingSeverity.WARNING,
            topic="chemia",
            description="Too confident",
            suggested_action=SuggestedCritiqueAction.VERIFY,
            belief_ids=["b1", "b2"],
            evidence={"score": 0.9},
        )
        d = f.to_dict()
        restored = CritiqueFinding.from_dict(d)
        assert restored.category == f.category
        assert restored.topic == f.topic
        assert restored.belief_ids == f.belief_ids
        assert restored.evidence == f.evidence

    def test_report_creation(self):
        r = CritiqueReport()
        assert r.report_id.startswith("cr-")
        assert r.trigger == "periodic"
        assert r.findings == []
        assert r.goals_created == []

    def test_report_to_dict_from_dict(self):
        f = create_finding(
            category=FindingCategory.STALE_KNOWLEDGE,
            severity=FindingSeverity.INFO,
            topic="bio",
            description="Stale",
            suggested_action=SuggestedCritiqueAction.REFRESH,
        )
        r = CritiqueReport(
            findings=[f],
            findings_total=10,
            findings_by_category={"stale_knowledge": 5},
            findings_by_severity={"info": 5},
            suppressed_duplicates=3,
        )
        d = r.to_dict()
        restored = CritiqueReport.from_dict(d)
        assert len(restored.findings) == 1
        assert restored.findings_total == 10
        assert restored.suppressed_duplicates == 3

    def test_finding_severity_order(self):
        c = create_finding(
            category=FindingCategory.CONTRADICTION,
            severity=FindingSeverity.CRITICAL,
            topic="a", description="", suggested_action=SuggestedCritiqueAction.RESOLVE,
        )
        w = create_finding(
            category=FindingCategory.OVERCONFIDENT,
            severity=FindingSeverity.WARNING,
            topic="b", description="", suggested_action=SuggestedCritiqueAction.VERIFY,
        )
        i = create_finding(
            category=FindingCategory.COVERAGE_GAP,
            severity=FindingSeverity.INFO,
            topic="c", description="", suggested_action=SuggestedCritiqueAction.LEARN_MORE,
        )
        assert c.severity_order < w.severity_order < i.severity_order

    def test_all_categories_exist(self):
        assert len(FindingCategory) == 7

    def test_max_findings_constant(self):
        assert MAX_FINDINGS_PER_REPORT == 5

    def test_gen_id_uniqueness(self):
        ids = {_gen_id("cf") for _ in range(100)}
        assert len(ids) == 100

    def test_normalize_topic(self):
        assert _normalize_topic("Fizyka kwantowa") == "fizyka_kwantowa"
        assert _normalize_topic("  DNA  ") == "dna"

    def test_dedupe_key(self):
        key = _make_dedupe_key("contradiction", "fizyka", ("b1", "b2"))
        assert key == "contradiction:fizyka:b1:b2"
        # Sorted
        key2 = _make_dedupe_key("contradiction", "fizyka", ("b2", "b1"))
        assert key2 == "contradiction:fizyka:b1:b2"

    def test_goal_title_map_all_categories(self):
        for cat in FindingCategory:
            assert cat.value in GOAL_TITLE_MAP


# =============================================================================
# B. KnowledgeCritic tests
# =============================================================================

# B1. Contradiction detection

class TestContradictions:

    def test_no_contradictions_when_consistent(self, tmp_project):
        b1 = _make_belief(belief_id="b1", entity="fizyka", content="Fizyka bada materie", confidence=0.8)
        b2 = _make_belief(belief_id="b2", entity="chemia", content="Chemia bada reakcje", confidence=0.7)
        store = _make_belief_store([b1, b2])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, total = critic.analyze()
        contradiction_findings = [f for f in findings if f.category == "contradiction"]
        assert len(contradiction_findings) == 0

    def test_detects_negation_contradiction(self, tmp_project):
        from enum import Enum
        class BS(Enum):
            LEARNING = "learning"
            EXAM = "exam"

        b1 = _make_belief(
            belief_id="b1", entity="woda", content="Woda jest mokra i przejrzysta",
            confidence=0.8, source=BS.LEARNING, source_id="f1",
        )
        b2 = _make_belief(
            belief_id="b2", entity="woda", content="Woda nie jest mokra i przejrzysta",
            confidence=0.7, source=BS.EXAM, source_id="f2",
        )
        store = _make_belief_store([b1, b2])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        contradiction_findings = [f for f in findings if f.category == "contradiction"]
        assert len(contradiction_findings) >= 1
        assert "Negation" in contradiction_findings[0].evidence.get("reason", "")

    def test_detects_numeric_contradiction(self, tmp_project):
        from enum import Enum
        class BS(Enum):
            LEARNING = "learning"
            EXAM = "exam"

        b1 = _make_belief(
            belief_id="b1", entity="planety", content="Uklad sloneczny ma 8 planet wokol slonca",
            confidence=0.8, source=BS.LEARNING, source_id="f1",
        )
        b2 = _make_belief(
            belief_id="b2", entity="planety", content="Uklad sloneczny ma 9 planet wokol slonca",
            confidence=0.6, source=BS.EXAM, source_id="f2",
        )
        store = _make_belief_store([b1, b2])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        contradiction_findings = [f for f in findings if f.category == "contradiction"]
        assert len(contradiction_findings) >= 1

    def test_contradiction_severity_critical_when_both_high(self, tmp_project):
        from enum import Enum
        class BS(Enum):
            LEARNING = "learning"
            EXAM = "exam"

        b1 = _make_belief(
            belief_id="b1", entity="temp", content="Woda wrze w 100 stopniach",
            confidence=0.8, source=BS.LEARNING, source_id="f1",
        )
        b2 = _make_belief(
            belief_id="b2", entity="temp", content="Woda nie wrze w 100 stopniach",
            confidence=0.7, source=BS.EXAM, source_id="f2",
        )
        store = _make_belief_store([b1, b2])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        contradiction_findings = [f for f in findings if f.category == "contradiction"]
        assert len(contradiction_findings) >= 1
        assert contradiction_findings[0].severity == "critical"

    def test_no_contradiction_different_aspects(self, tmp_project):
        """Different aspects of same entity should NOT be flagged."""
        b1 = _make_belief(
            belief_id="b1", entity="francja", content="Francja lezy w Europie",
            confidence=0.8, source_id="f1",
        )
        b2 = _make_belief(
            belief_id="b2", entity="francja", content="Populacja Francji wynosi 67 milionow",
            confidence=0.7, source_id="f1",  # Same source
        )
        store = _make_belief_store([b1, b2])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        contradiction_findings = [f for f in findings if f.category == "contradiction"]
        assert len(contradiction_findings) == 0

    def test_no_contradiction_for_superseded(self, tmp_project):
        b1 = _make_belief(
            belief_id="b1", entity="fizyka", content="test",
            confidence=0.9, superseded_by="b2",
        )
        b2 = _make_belief(
            belief_id="b2", entity="fizyka", content="test updated",
            confidence=0.5,
        )
        store = _make_belief_store([b1, b2])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        # Superseded belief should be excluded from analysis
        contradiction_findings = [f for f in findings if f.category == "contradiction"]
        assert len(contradiction_findings) == 0


# B2. Overconfident

class TestOverconfident:

    def test_overconfident_no_exam(self, tmp_project):
        b = _make_belief(belief_id="b1", entity="bio", confidence=0.85, source_id="file_x")
        store = _make_belief_store([b])
        # No exam_results.jsonl at all

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        oc = [f for f in findings if f.category == "overconfident"]
        assert len(oc) == 1
        assert oc[0].evidence["exam_count"] == 0

    def test_overconfident_low_exam_score(self, tmp_project):
        b = _make_belief(belief_id="b1", entity="math", confidence=0.85, source_id="math_file")
        store = _make_belief_store([b])

        _write_exam_results(tmp_project / "memory" / "exam_results.jsonl", [
            {"file": "math_file", "score": 0.3, "timestamp": time.time()},
        ])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        oc = [f for f in findings if f.category == "overconfident"]
        assert len(oc) == 1
        assert oc[0].evidence["weighted_exam_score"] < 0.5

    def test_no_overconfident_when_exam_good(self, tmp_project):
        b = _make_belief(belief_id="b1", entity="chem", confidence=0.8, source_id="chem_file")
        store = _make_belief_store([b])

        _write_exam_results(tmp_project / "memory" / "exam_results.jsonl", [
            {"file": "chem_file", "score": 0.9, "timestamp": time.time()},
        ])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        oc = [f for f in findings if f.category == "overconfident"]
        assert len(oc) == 0

    def test_overconfident_weighted_multiple_exams(self, tmp_project):
        """Weighted score favors recent exams."""
        b = _make_belief(belief_id="b1", entity="hist", confidence=0.85, source_id="hist_file")
        store = _make_belief_store([b])

        now = time.time()
        _write_exam_results(tmp_project / "memory" / "exam_results.jsonl", [
            {"file": "hist_file", "score": 0.2, "timestamp": now - 3600},
            {"file": "hist_file", "score": 0.8, "timestamp": now},  # Recent, good
        ])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        oc = [f for f in findings if f.category == "overconfident"]
        # Weighted score should be closer to 0.8 (recent), so not overconfident
        assert len(oc) == 0

    def test_low_confidence_not_flagged(self, tmp_project):
        """Beliefs <= 0.7 should not be flagged as overconfident."""
        b = _make_belief(belief_id="b1", entity="geo", confidence=0.5, source_id="geo_file")
        store = _make_belief_store([b])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        oc = [f for f in findings if f.category == "overconfident"]
        assert len(oc) == 0


# B3. Underconfident

class TestUnderconfident:

    def test_underconfident_good_exam(self, tmp_project):
        b = _make_belief(belief_id="b1", entity="astro", confidence=0.3, source_id="astro_file")
        store = _make_belief_store([b])

        _write_exam_results(tmp_project / "memory" / "exam_results.jsonl", [
            {"file": "astro_file", "score": 0.85, "timestamp": time.time()},
        ])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        uc = [f for f in findings if f.category == "underconfident"]
        assert len(uc) == 1
        assert uc[0].confidence_delta < 0  # Negative = should be higher

    def test_no_underconfident_when_aligned(self, tmp_project):
        b = _make_belief(belief_id="b1", entity="x", confidence=0.8, source_id="xf")
        store = _make_belief_store([b])

        _write_exam_results(tmp_project / "memory" / "exam_results.jsonl", [
            {"file": "xf", "score": 0.85, "timestamp": time.time()},
        ])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        uc = [f for f in findings if f.category == "underconfident"]
        assert len(uc) == 0

    def test_underconfident_no_exam_not_flagged(self, tmp_project):
        """No exam -> can't be underconfident."""
        b = _make_belief(belief_id="b1", entity="y", confidence=0.2, source_id="yf")
        store = _make_belief_store([b])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        uc = [f for f in findings if f.category == "underconfident"]
        assert len(uc) == 0


# B4. Shallow knowledge

class TestShallowKnowledge:

    def test_detects_hypothesis_only(self, tmp_project):
        from enum import Enum
        class BT(Enum):
            HYPOTHESIS = "hypothesis"

        b1 = _make_belief(belief_id="b1", entity="x", tags=("nanotechnologia",), belief_type=BT.HYPOTHESIS, confidence=0.4)
        b2 = _make_belief(belief_id="b2", entity="y", tags=("nanotechnologia",), belief_type=BT.HYPOTHESIS, confidence=0.3)
        store = _make_belief_store([b1, b2])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        shallow = [f for f in findings if f.category == "shallow_knowledge"]
        assert len(shallow) >= 1
        assert "no facts" in shallow[0].evidence.get("reasons", [""])[0]

    def test_no_finding_when_facts_present(self, tmp_project):
        from enum import Enum
        class BT(Enum):
            FACT = "fact"
            OBSERVATION = "observation"

        b1 = _make_belief(belief_id="b1", entity="x", tags=("fizyka",), belief_type=BT.FACT, confidence=0.9, source_id="f1")
        b2 = _make_belief(belief_id="b2", entity="y", tags=("fizyka",), belief_type=BT.OBSERVATION, confidence=0.6, source_id="f2")
        store = _make_belief_store([b1, b2])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        shallow = [f for f in findings if f.category == "shallow_knowledge"]
        assert len(shallow) == 0

    def test_detects_single_source(self, tmp_project):
        from enum import Enum
        class BT(Enum):
            FACT = "fact"

        b1 = _make_belief(belief_id="b1", entity="x", tags=("topic_a",), belief_type=BT.FACT, confidence=0.8, source_id="same_file")
        b2 = _make_belief(belief_id="b2", entity="y", tags=("topic_a",), belief_type=BT.FACT, confidence=0.7, source_id="same_file")
        store = _make_belief_store([b1, b2])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        shallow = [f for f in findings if f.category == "shallow_knowledge"]
        assert len(shallow) >= 1
        assert "single source" in str(shallow[0].evidence.get("reasons", []))

    def test_detects_expert_monoculture_as_single_source(self, tmp_project):
        """Cross-source WYDMUSZKA in the critic (audit 2026-06-16): facts backed
        ONLY by expert_*.txt files are one LLM voice, but each keypoint yields a
        distinct source_id (concept:expert_X#chunk_0:0). Raw counting made
        len(sources)>1, so the single-source branch was DEAD for every expert
        monoculture -- the safety net meant to catch exactly this was blind.
        Logical-source counting collapses expert_* to one, so it now fires."""
        from enum import Enum
        class BT(Enum):
            FACT = "fact"

        b1 = _make_belief(belief_id="b1", entity="x", tags=("entropia",),
                          belief_type=BT.FACT, confidence=0.8,
                          source_id="concept:expert_fizyka.txt#chunk_0:0")
        b2 = _make_belief(belief_id="b2", entity="y", tags=("entropia",),
                          belief_type=BT.FACT, confidence=0.7,
                          source_id="concept:expert_chemia.txt#chunk_2:1")
        store = _make_belief_store([b1, b2])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        shallow = [f for f in findings if f.category == "shallow_knowledge"]
        assert len(shallow) >= 1, "expert monoculture must be flagged shallow"
        assert "single source" in str(shallow[0].evidence.get("reasons", []))

    def test_shallow_requires_min_beliefs(self, tmp_project):
        from enum import Enum
        class BT(Enum):
            HYPOTHESIS = "hypothesis"

        b1 = _make_belief(belief_id="b1", entity="x", tags=("rare_topic",), belief_type=BT.HYPOTHESIS)
        store = _make_belief_store([b1])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        shallow = [f for f in findings if f.category == "shallow_knowledge"]
        assert len(shallow) == 0  # Only 1 belief, below threshold


# B5. Unresolved disputes

class TestUnresolvedDisputes:

    def test_detects_high_severity_unresolved(self, tmp_project):
        dispute_log = specced(DisputeLog)
        dispute_log.get_unresolved.return_value = [
            {"file_id": "file_a", "severity": "high", "resolved": False},
            {"file_id": "file_a", "severity": "high", "resolved": False},
            {"file_id": "file_a", "severity": "medium", "resolved": False},
        ]
        dispute_log.get_stats.return_value = {}
        dispute_log.get_recent.return_value = []

        critic = KnowledgeCritic(dispute_log=dispute_log, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        disputes = [f for f in findings if f.category == "unresolved_dispute"]
        assert len(disputes) >= 1
        assert disputes[0].severity == "critical"

    def test_no_finding_when_resolved(self, tmp_project):
        dispute_log = specced(DisputeLog)
        dispute_log.get_unresolved.return_value = []
        dispute_log.get_stats.return_value = {}
        dispute_log.get_recent.return_value = []

        critic = KnowledgeCritic(dispute_log=dispute_log, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        disputes = [f for f in findings if f.category == "unresolved_dispute"]
        assert len(disputes) == 0

    def test_no_finding_without_dispute_log(self, tmp_project):
        critic = KnowledgeCritic(dispute_log=None, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        disputes = [f for f in findings if f.category == "unresolved_dispute"]
        assert len(disputes) == 0

    def test_dispute_medium_severity_warning(self, tmp_project):
        dispute_log = specced(DisputeLog)
        dispute_log.get_unresolved.return_value = [
            {"file_id": "file_b", "severity": "medium", "resolved": False},
            {"file_id": "file_b", "severity": "medium", "resolved": False},
        ]
        dispute_log.get_stats.return_value = {}
        dispute_log.get_recent.return_value = []

        critic = KnowledgeCritic(dispute_log=dispute_log, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        disputes = [f for f in findings if f.category == "unresolved_dispute"]
        assert len(disputes) >= 1
        assert disputes[0].severity == "warning"


# B6. Coverage gaps

class TestCoverageGaps:

    def test_detects_partially_learned(self, tmp_project):
        old_time = time.time() - (COVERAGE_GRACE_PERIOD_DAYS + 1) * 86400
        _write_knowledge_index(tmp_project / "memory" / "knowledge_index.jsonl", [
            {
                "id": "file_partial",
                "status": "partial",
                "chunks_learned": 3,
                "total_chunks": 10,
                "timestamp": old_time,
            },
        ])

        critic = KnowledgeCritic(project_root=str(tmp_project))
        findings, _ = critic.analyze()
        gaps = [f for f in findings if f.category == "coverage_gap"]
        assert len(gaps) == 1
        assert "3/10" in gaps[0].description

    def test_detects_completed_without_exam(self, tmp_project):
        old_time = time.time() - (COVERAGE_GRACE_PERIOD_DAYS + 1) * 86400
        _write_knowledge_index(tmp_project / "memory" / "knowledge_index.jsonl", [
            {
                "id": "file_noexam",
                "status": "completed",
                "chunks_learned": 5,
                "total_chunks": 5,
                "timestamp": old_time,
            },
        ])

        critic = KnowledgeCritic(project_root=str(tmp_project))
        findings, _ = critic.analyze()
        gaps = [f for f in findings if f.category == "coverage_gap"]
        assert len(gaps) == 1
        assert "no exam" in gaps[0].description.lower()

    def test_no_gap_fresh_file(self, tmp_project):
        """Files within grace period should NOT be flagged."""
        _write_knowledge_index(tmp_project / "memory" / "knowledge_index.jsonl", [
            {
                "id": "file_fresh",
                "status": "partial",
                "chunks_learned": 2,
                "total_chunks": 10,
                "timestamp": time.time(),  # Fresh
            },
        ])

        critic = KnowledgeCritic(project_root=str(tmp_project))
        findings, _ = critic.analyze()
        gaps = [f for f in findings if f.category == "coverage_gap"]
        assert len(gaps) == 0

    def test_no_gap_fully_completed_with_exam(self, tmp_project):
        old_time = time.time() - (COVERAGE_GRACE_PERIOD_DAYS + 1) * 86400
        _write_knowledge_index(tmp_project / "memory" / "knowledge_index.jsonl", [
            {
                "id": "file_done",
                "status": "completed",
                "chunks_learned": 5,
                "total_chunks": 5,
                "timestamp": old_time,
            },
        ])
        _write_exam_results(tmp_project / "memory" / "exam_results.jsonl", [
            {"file": "file_done", "score": 0.9, "timestamp": time.time()},
        ])

        critic = KnowledgeCritic(project_root=str(tmp_project))
        findings, _ = critic.analyze()
        gaps = [f for f in findings if f.category == "coverage_gap"]
        assert len(gaps) == 0

    def test_handles_missing_knowledge_index(self, tmp_project):
        critic = KnowledgeCritic(project_root=str(tmp_project))
        findings, _ = critic.analyze()
        gaps = [f for f in findings if f.category == "coverage_gap"]
        assert len(gaps) == 0


# B7. Stale knowledge

class TestStaleKnowledge:

    def test_detects_near_floor_confidence(self, tmp_project):
        # Hypothesis with old updated_at -> should decay to near floor
        old_time = time.time() - 60 * 86400  # 60 days old
        from enum import Enum
        class BT(Enum):
            HYPOTHESIS = "hypothesis"

        b = _make_belief(
            belief_id="b1", entity="old_topic", confidence=0.5,
            belief_type=BT.HYPOTHESIS, updated_at=old_time,
        )
        store = _make_belief_store([b])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        stale = [f for f in findings if f.category == "stale_knowledge"]
        assert len(stale) >= 1

    def test_no_staleness_for_recent(self, tmp_project):
        from enum import Enum
        class BT(Enum):
            FACT = "fact"

        b = _make_belief(
            belief_id="b1", entity="fresh_topic", confidence=0.8,
            belief_type=BT.FACT, updated_at=time.time(),
        )
        store = _make_belief_store([b])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        stale = [f for f in findings if f.category == "stale_knowledge"]
        assert len(stale) == 0

    def test_hypothesis_decays_faster(self, tmp_project):
        from enum import Enum
        class BT(Enum):
            HYPOTHESIS = "hypothesis"
            FACT = "fact"

        old_time = time.time() - 30 * 86400  # 30 days
        b_hyp = _make_belief(
            belief_id="b1", entity="topic_hyp", confidence=0.5,
            belief_type=BT.HYPOTHESIS, updated_at=old_time,
        )
        b_fact = _make_belief(
            belief_id="b2", entity="topic_fact", confidence=0.5,
            belief_type=BT.FACT, updated_at=old_time,
        )

        critic = KnowledgeCritic(project_root=str(tmp_project))

        # Hypothesis: half_life=14d, 30 days -> 0.5 * 0.5^(30/14) = ~0.12
        decay_hyp = critic._compute_decayed_confidence(b_hyp, time.time())
        # Fact: half_life=90d, 30 days -> 0.5 * 0.5^(30/90) = ~0.40
        decay_fact = critic._compute_decayed_confidence(b_fact, time.time())

        assert decay_hyp < decay_fact

    def test_staleness_metadata(self, tmp_project):
        from enum import Enum
        class BT(Enum):
            HYPOTHESIS = "hypothesis"

        old_time = time.time() - 60 * 86400
        b = _make_belief(
            belief_id="b1", entity="meta_topic", confidence=0.5,
            belief_type=BT.HYPOTHESIS, updated_at=old_time,
        )
        store = _make_belief_store([b])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        stale = [f for f in findings if f.category == "stale_knowledge"]
        assert len(stale) >= 1
        assert stale[0].metadata.get("volatility_hint") == "volatile"


# B8. Integration / sorting

class TestAnalyzeIntegration:

    def test_returns_max_5_findings(self, tmp_project):
        """Even with many issues, cap to MAX_FINDINGS_PER_REPORT."""
        beliefs = []
        for i in range(10):
            beliefs.append(_make_belief(
                belief_id=f"b{i}", entity=f"topic_{i}",
                confidence=0.9, source_id=f"file_{i}",
            ))
        store = _make_belief_store(beliefs)
        # No exams -> 10 overconfident findings

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, total = critic.analyze()
        assert len(findings) <= MAX_FINDINGS_PER_REPORT
        assert total >= 10

    def test_sorts_by_severity(self, tmp_project):
        from enum import Enum
        class BS(Enum):
            LEARNING = "learning"
            EXAM = "exam"
        class BT(Enum):
            OBSERVATION = "observation"

        # Create contradiction (CRITICAL) + overconfident (WARNING)
        b1 = _make_belief(
            belief_id="b1", entity="test_ent",
            content="Woda jest mokra i czysta",
            confidence=0.8, source=BS.LEARNING, source_id="f1",
            belief_type=BT.OBSERVATION,
        )
        b2 = _make_belief(
            belief_id="b2", entity="test_ent",
            content="Woda nie jest mokra i czysta",
            confidence=0.7, source=BS.EXAM, source_id="f2",
            belief_type=BT.OBSERVATION,
        )
        b3 = _make_belief(
            belief_id="b3", entity="other",
            confidence=0.9, source_id="no_exam_file",
            belief_type=BT.OBSERVATION,
        )
        store = _make_belief_store([b1, b2, b3])

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()

        if len(findings) >= 2:
            # First finding should be CRITICAL (contradiction), then WARNING
            assert findings[0].severity_order <= findings[1].severity_order

    def test_analyze_empty_data(self, tmp_project):
        critic = KnowledgeCritic(project_root=str(tmp_project))
        findings, total = critic.analyze()
        assert findings == []
        assert total == 0

    def test_dedup_by_dedupe_key(self, tmp_project):
        """Duplicate findings with same dedupe_key should be suppressed."""
        # Two beliefs about same entity, same conditions -> should produce
        # at most one finding per dedupe_key
        beliefs = []
        for i in range(3):
            beliefs.append(_make_belief(
                belief_id=f"b{i}", entity="same_topic",
                confidence=0.9, source_id="same_file",
            ))
        store = _make_belief_store(beliefs)

        critic = KnowledgeCritic(belief_store=store, project_root=str(tmp_project))
        findings, _ = critic.analyze()
        # All overconfident findings for "same_topic" with same belief_ids
        # should be deduped
        oc = [f for f in findings if f.category == "overconfident"]
        # Should not have more than 3 (one per belief)
        assert len(oc) <= 3


# =============================================================================
# C. CritiqueApplier tests
# =============================================================================

class TestCritiqueApplier:

    def test_posts_advisory_for_critical(self):
        finding = create_finding(
            category=FindingCategory.CONTRADICTION,
            severity=FindingSeverity.CRITICAL,
            topic="fizyka",
            description="Test",
            suggested_action=SuggestedCritiqueAction.RESOLVE,
        )
        report = CritiqueReport(findings=[finding])

        bulletin = specced(BulletinStore)
        bulletin.create_and_post.return_value = specced(BulletinEntry, entry_id="be-crit-1")

        applier = CritiqueApplier(bulletin_store=bulletin)
        result = applier.apply(report)

        assert result["bulletin_posted"] == ["be-crit-1"]
        assert result["goals_created"] == []
        bulletin.create_and_post.assert_called_once()

    def test_respects_max_goals_limit(self):
        findings = []
        for i in range(6):
            findings.append(create_finding(
                category=FindingCategory.CONTRADICTION,
                severity=FindingSeverity.CRITICAL,
                topic=f"topic_{i}",
                description=f"Problem {i}",
                suggested_action=SuggestedCritiqueAction.RESOLVE,
            ))
        report = CritiqueReport(findings=findings)

        bulletin = specced(BulletinStore)
        bulletin.create_and_post.side_effect = (
            lambda **kw: specced(BulletinEntry, entry_id=f"be-{kw['topic']}")
        )

        applier = CritiqueApplier(bulletin_store=bulletin)
        result = applier.apply(report)

        assert len(result["bulletin_posted"]) <= MAX_PROPOSED_GOALS_FROM_CRITIQUE

    def test_info_does_not_post_advisory(self):
        finding = create_finding(
            category=FindingCategory.COVERAGE_GAP,
            severity=FindingSeverity.INFO,
            topic="test",
            description="Coverage gap",
            suggested_action=SuggestedCritiqueAction.LEARN_MORE,
        )
        report = CritiqueReport(findings=[finding])

        bulletin = specced(BulletinStore)
        applier = CritiqueApplier(bulletin_store=bulletin)
        result = applier.apply(report)

        assert result["bulletin_posted"] == []
        bulletin.create_and_post.assert_not_called()

    def test_dedup_delegated_to_bulletin(self):
        # R1 (2026-05-29): the applier no longer does goal-store idempotency.
        # It always calls create_and_post; BulletinStore dedups by topic+type.
        # A goal_store full of "existing" goals must NOT suppress the advisory.
        finding = create_finding(
            category=FindingCategory.OVERCONFIDENT,
            severity=FindingSeverity.WARNING,
            topic="math",
            description="Too confident",
            suggested_action=SuggestedCritiqueAction.VERIFY,
        )
        report = CritiqueReport(findings=[finding])

        existing_goal = specced(Goal, metadata={
            "source": "critic",
            "dedupe_key": finding.dedupe_key,
        })
        goal_store = specced(GoalStore)
        goal_store.get_active.return_value = []
        goal_store.get_proposed.return_value = [existing_goal]

        bulletin = specced(BulletinStore)
        bulletin.create_and_post.return_value = specced(BulletinEntry, entry_id="be-w1")

        applier = CritiqueApplier(goal_store=goal_store, bulletin_store=bulletin)
        result = applier.apply(report)

        assert result["bulletin_posted"] == ["be-w1"]
        bulletin.create_and_post.assert_called_once()

    def test_llm_summary_called_when_set(self):
        finding = create_finding(
            category=FindingCategory.STALE_KNOWLEDGE,
            severity=FindingSeverity.WARNING,
            topic="bio",
            description="Stale",
            suggested_action=SuggestedCritiqueAction.REFRESH,
        )
        report = CritiqueReport(findings=[finding])

        llm_fn = MagicMock(return_value="Podsumowanie: wiedza jest stara.")
        goal_store = specced(GoalStore)
        goal_store.get_active.return_value = []
        goal_store.get_proposed.return_value = []
        goal_store.propose.return_value = "g1"

        applier = CritiqueApplier(goal_store=goal_store, llm_fn=llm_fn)
        result = applier.apply(report)

        assert result["llm_summary_ok"] is True
        assert report.llm_summary is not None
        llm_fn.assert_called_once()

    def test_llm_summary_failure_does_not_break(self):
        finding = create_finding(
            category=FindingCategory.CONTRADICTION,
            severity=FindingSeverity.CRITICAL,
            topic="x",
            description="Problem",
            suggested_action=SuggestedCritiqueAction.RESOLVE,
        )
        report = CritiqueReport(findings=[finding])

        llm_fn = MagicMock(side_effect=Exception("LLM down"))
        bulletin = specced(BulletinStore)
        bulletin.create_and_post.return_value = specced(BulletinEntry, entry_id="be-1")

        applier = CritiqueApplier(bulletin_store=bulletin, llm_fn=llm_fn)
        result = applier.apply(report)

        # Advisory should still be posted despite LLM failure
        assert len(result["bulletin_posted"]) == 1
        assert result["llm_summary_ok"] is False

    def test_handles_bulletin_store_none(self):
        finding = create_finding(
            category=FindingCategory.CONTRADICTION,
            severity=FindingSeverity.CRITICAL,
            topic="x",
            description="Problem",
            suggested_action=SuggestedCritiqueAction.RESOLVE,
        )
        report = CritiqueReport(findings=[finding])

        applier = CritiqueApplier(bulletin_store=None)
        result = applier.apply(report)

        assert result["bulletin_posted"] == []
        assert result["goals_created"] == []

    def test_warning_posts_advisory(self):
        finding = create_finding(
            category=FindingCategory.SHALLOW_KNOWLEDGE,
            severity=FindingSeverity.WARNING,
            topic="nano",
            description="Shallow",
            suggested_action=SuggestedCritiqueAction.LEARN_MORE,
        )
        report = CritiqueReport(findings=[finding])

        bulletin = specced(BulletinStore)
        bulletin.create_and_post.return_value = specced(BulletinEntry, entry_id="be-nano")

        applier = CritiqueApplier(bulletin_store=bulletin)
        result = applier.apply(report)

        assert result["bulletin_posted"] == ["be-nano"]
        bulletin.create_and_post.assert_called_once()


# =============================================================================
# D. CriticAgent facade tests
# =============================================================================

class TestCriticAgentFacade:

    def test_run_critique_returns_report(self, tmp_project):
        store = _make_belief_store([
            _make_belief(belief_id="b1", entity="x", confidence=0.9),
        ])
        agent = CriticAgent(project_root=str(tmp_project))
        agent.set_belief_store(store)

        report = agent.run_critique()
        assert isinstance(report, CritiqueReport)
        assert report.report_id.startswith("cr-")

    def test_should_critique_periodic_cooldown(self, tmp_project):
        agent = CriticAgent(project_root=str(tmp_project), cooldown_sec=100)
        # Just created, last_critique_ts = 0 -> cooldown expired
        assert agent.should_critique() is True

    def test_should_critique_min_cooldown_1h(self, tmp_project):
        agent = CriticAgent(project_root=str(tmp_project))
        agent._last_critique_ts = time.time() - 1800  # 30 min ago
        assert agent.should_critique() is False

    def test_should_critique_post_validation_trigger(self, tmp_project):
        agent = CriticAgent(project_root=str(tmp_project))
        agent._last_critique_ts = time.time() - 7200  # 2h ago
        assert agent.should_critique(post_validation=True) is True

    def test_should_critique_post_maintenance_trigger(self, tmp_project):
        agent = CriticAgent(project_root=str(tmp_project))
        agent._last_critique_ts = time.time() - 7200
        assert agent.should_critique(post_maintenance=True) is True

    def test_persists_report_to_jsonl(self, tmp_project):
        store = _make_belief_store([])
        agent = CriticAgent(project_root=str(tmp_project))
        agent.set_belief_store(store)

        agent.run_critique()

        reports_path = tmp_project / "meta_data" / "critique_reports.jsonl"
        assert reports_path.exists()
        with open(reports_path) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["report_id"].startswith("cr-")

    def test_get_last_report_reads_jsonl(self, tmp_project):
        store = _make_belief_store([])
        agent = CriticAgent(project_root=str(tmp_project))
        agent.set_belief_store(store)

        agent.run_critique(trigger="manual")

        last = agent.get_last_report()
        assert last is not None
        assert last.trigger == "manual"

    def test_get_status_dict(self, tmp_project):
        agent = CriticAgent(project_root=str(tmp_project))
        status = agent.get_status()
        assert "available" in status
        assert "last_critique_ts" in status
        assert status["available"] is False  # No belief_store

    def test_run_critique_with_no_belief_store(self, tmp_project):
        agent = CriticAgent(project_root=str(tmp_project))
        report = agent.run_critique()
        assert report.findings == []
        assert report.error is None

    def test_facade_wires_dependencies(self, tmp_project):
        store = specced(BeliefStore, _beliefs={})
        dispute_log = specced(DisputeLog)
        goal_store = specced(GoalStore)
        llm_fn = MagicMock()

        agent = CriticAgent(project_root=str(tmp_project))
        agent.set_belief_store(store)
        agent.set_dispute_log(dispute_log)
        agent.set_goal_store(goal_store)
        agent.set_llm_fn(llm_fn)

        assert agent._belief_store is store
        assert agent._dispute_log is dispute_log
        assert agent._applier._goal_store is goal_store
        assert agent._applier._llm_fn is llm_fn


# =============================================================================
# E. Integration tests
# =============================================================================

class TestIntegration:

    def test_action_type_critique_exists(self):
        from agent_core.planner.planner_model import ActionType
        assert hasattr(ActionType, "CRITIQUE")
        assert ActionType.CRITIQUE.value == "critique"

    def test_capability_spec_critique(self):
        from agent_core.routing.capability_spec import DEFAULT_CAPABILITY_SPECS
        assert "critique" in DEFAULT_CAPABILITY_SPECS
        spec = DEFAULT_CAPABILITY_SPECS["critique"]
        assert spec.k7_classification == "guarded"
        assert "critic_agent" in spec.required_subsystems

    def test_planner_state_has_last_critique_ts(self):
        from agent_core.planner.planner_model import PlannerState
        state = PlannerState()
        assert hasattr(state, "last_critique_ts")
        assert state.last_critique_ts == 0.0

        # Roundtrip
        d = state.to_dict()
        assert "last_critique_ts" in d
        restored = PlannerState.from_dict(d)
        assert restored.last_critique_ts == 0.0

    def test_make_critique_handler_success(self):
        from agent_core.routing.handlers import make_critique_handler

        critic = specced(CriticAgent)
        report = CritiqueReport(findings=[])
        critic.run_critique.return_value = report

        handler = make_critique_handler(critic)
        plan = specced(Plan, action_params={"trigger": "test"})

        result = handler(plan)
        assert result["success"] is True
        critic.run_critique.assert_called_once()

    def test_make_critique_handler_no_critic(self):
        from agent_core.routing.handlers import make_critique_handler

        handler = make_critique_handler(None)
        plan = specced(Plan, action_params={})

        result = handler(plan)
        assert result["success"] is False
        assert "No critic_agent" in result["error"]
