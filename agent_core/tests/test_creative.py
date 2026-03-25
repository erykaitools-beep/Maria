"""Tests for Creative Module (K13).

Tests cover:
- creative_model.py: dataclasses, enums, factory methods
- creative_store.py: JSONL persistence, MERGE semantics
- strategic_context.py: context building from JSONL data
- tension_detector.py: rule-based tension detection
- reflection_workspace.py: session management, insight/goal generation
- creative_journal.py: journal entry creation
- novelty_filter.py: dedup, flood protection, broad rejection
- creative_evaluator.py: multi-dimension scoring
- goal_adapter.py: GoalStore integration
- facade.py: full reflection cycle
"""

import json
import os
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# --- Models ---

from agent_core.creative.creative_model import (
    MetaGoal, MetaGoalType, MetaGoalStatus, RiskLevel,
    DetectedTension, TensionCategory,
    CreativeInsight, ExplorationProgram, PersonalitySignal,
    PersonalityDimension, ReframeProposal, StrategicObservation,
    CreativeJournalEntry, ConversationMemoryEntry, ConversationMemoryType,
    Speaker, ReflectionSession,
)


class TestCreativeModel:
    """Test data models and factory methods."""

    def test_meta_goal_create(self):
        mg = MetaGoal.create(
            title="Explore new topics",
            goal_type=MetaGoalType.EXPLORATION_META,
            priority=0.7,
            why_now="High coverage, no new directions",
            evidence_refs=["eval:coverage=1.0"],
            expected_value="New knowledge domains",
        )
        assert mg.goal_id.startswith("mg-")
        assert mg.status == MetaGoalStatus.DRAFT
        assert mg.priority == 0.7
        assert mg.source == "creative"

    def test_meta_goal_with_status(self):
        mg = MetaGoal.create(
            title="Test", goal_type=MetaGoalType.EPISTEMIC_META,
            priority=0.5, why_now="test", evidence_refs=[], expected_value="test",
        )
        proposed = mg.with_status(MetaGoalStatus.PROPOSED)
        assert proposed.status == MetaGoalStatus.PROPOSED
        assert proposed.goal_id == mg.goal_id  # Same ID
        assert proposed.title == mg.title

    def test_meta_goal_frozen(self):
        mg = MetaGoal.create(
            title="Test", goal_type=MetaGoalType.EPISTEMIC_META,
            priority=0.5, why_now="test", evidence_refs=[], expected_value="test",
        )
        with pytest.raises(AttributeError):
            mg.title = "Changed"

    def test_detected_tension_create(self):
        t = DetectedTension.create(
            category=TensionCategory.REPETITION,
            description="System stuck in NOOP loop",
            severity=0.8,
            evidence_refs=["planner_decisions:noop=90%"],
        )
        assert t.tension_id.startswith("tension-")
        assert t.severity == 0.8
        assert not t.resolved

    def test_creative_insight_create(self):
        i = CreativeInsight.create(
            derived_from=["tension-abc"],
            statement="System needs new directions",
            confidence=0.7,
            meta_goal_candidate=True,
        )
        assert i.insight_id.startswith("insight-")
        assert i.meta_goal_candidate

    def test_exploration_program_create(self):
        ep = ExplorationProgram.create(
            title="Explore philosophy",
            question="What can Maria learn from philosophy?",
            scope="Limited to Polish Wikipedia articles",
            success_signal="3 new topics learned",
            promotion_policy="After 3 successful fetches",
        )
        assert ep.program_id.startswith("explore-")

    def test_personality_signal_capped(self):
        sig = PersonalitySignal.create(
            dimension=PersonalityDimension.EXPLORATION_VS_ORDER,
            direction="increase_exploration",
            reason="High coverage, stagnation",
            magnitude=0.5,  # Should be capped to 0.1
        )
        assert sig.magnitude == 0.1

    def test_reframe_proposal_create(self):
        rp = ReframeProposal.create(
            original_ref="goal-123",
            original_description="Learn everything",
            reframed_description="Focus on depth over breadth",
            rationale="Coverage is high but retention is dropping",
            evidence_refs=["eval:retention=0.6"],
        )
        assert rp.reframe_id.startswith("reframe-")

    def test_strategic_observation_create(self):
        obs = StrategicObservation.create(
            statement="System performs better in morning hours",
            evidence_refs=["homeostasis_events:time_analysis"],
            category="temporal_pattern",
        )
        assert obs.observation_id.startswith("obs-")

    def test_journal_entry_create(self):
        entry = CreativeJournalEntry.create(
            trigger="periodic",
            summary="Detected stagnation, proposed exploration",
            tension_ids=["t1", "t2"],
            meta_goal_ids=["mg1"],
        )
        assert entry.entry_id.startswith("journal-")
        assert len(entry.tension_ids) == 2

    def test_conversation_memory_create(self):
        mem = ConversationMemoryEntry.create(
            source_session="session-123",
            speaker=Speaker.OPERATOR,
            content="Focus on science topics",
            memory_type=ConversationMemoryType.PREFERENCE,
            importance=0.8,
        )
        assert mem.memory_id.startswith("cmem-")
        assert mem.speaker == Speaker.OPERATOR

    def test_reflection_session_bounded(self):
        session = ReflectionSession(trigger="test")
        for i in range(15):
            t = DetectedTension.create(
                category=TensionCategory.REPETITION,
                description=f"Tension {i}",
                severity=0.5,
                evidence_refs=[],
            )
            session.add_tension(t)
        assert len(session.detected_tensions) == session.MAX_TENSIONS

    def test_reflection_session_close(self):
        session = ReflectionSession(trigger="test")
        assert not session.closed
        session.close()
        assert session.closed


# --- Store ---

from agent_core.creative.creative_store import CreativeStore


class TestCreativeStore:
    """Test JSONL persistence."""

    def test_save_and_load_journal(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        entry = CreativeJournalEntry.create(
            trigger="test", summary="Test entry",
        )
        store.save_journal_entry(entry)
        loaded = store.load_journal()
        assert len(loaded) == 1
        assert loaded[0]["entry_id"] == entry.entry_id

    def test_save_and_load_meta_goal(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        mg = MetaGoal.create(
            title="Test goal", goal_type=MetaGoalType.EXPLORATION_META,
            priority=0.5, why_now="test", evidence_refs=["e1"],
            expected_value="test",
        )
        store.save_meta_goal(mg)
        loaded = store.load_meta_goals()
        assert len(loaded) == 1
        assert loaded[0]["title"] == "Test goal"

    def test_meta_goal_merge_semantics(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        mg = MetaGoal.create(
            title="Original", goal_type=MetaGoalType.EXPLORATION_META,
            priority=0.5, why_now="test", evidence_refs=[],
            expected_value="test",
        )
        store.save_meta_goal(mg)

        updated = mg.with_status(MetaGoalStatus.ACCEPTED)
        store.save_meta_goal(updated)

        # Reload (fresh cache)
        store._meta_goals = None
        loaded = store.load_meta_goals()
        assert len(loaded) == 1  # MERGE: same ID
        assert loaded[0]["status"] == "accepted"

    def test_save_conversation_memory(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        mem = ConversationMemoryEntry.create(
            source_session="s1", speaker=Speaker.OPERATOR,
            content="Focus on math", memory_type=ConversationMemoryType.PREFERENCE,
            importance=0.9,
        )
        store.save_conversation_memory(mem)
        loaded = store.load_conversation_memories()
        assert len(loaded) == 1

    def test_get_recent_meta_goals(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        # Old goal
        old_mg = MetaGoal(
            goal_id="mg-old", title="Old", goal_type=MetaGoalType.EPISTEMIC_META,
            status=MetaGoalStatus.ACCEPTED, priority=0.5, why_now="old",
            evidence_refs=[], expected_value="old", risk_level=RiskLevel.LOW,
            created_ts=time.time() - 100000,  # >24h ago
        )
        store.save_meta_goal(old_mg)

        # Recent goal
        recent_mg = MetaGoal.create(
            title="Recent", goal_type=MetaGoalType.EXPLORATION_META,
            priority=0.7, why_now="recent", evidence_refs=["e1"],
            expected_value="recent",
        )
        store.save_meta_goal(recent_mg)

        recent = store.get_recent_meta_goals(hours=24.0)
        assert len(recent) == 1
        assert recent[0]["title"] == "Recent"

    def test_save_workspace_session(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        session = ReflectionSession(trigger="test")
        session.add_tension(DetectedTension.create(
            TensionCategory.STAGNATION, "test", 0.5, [],
        ))
        store.save_workspace_session(session)
        loaded = store.load_workspace_sessions()
        assert len(loaded) == 1
        assert loaded[0]["tension_count"] == 1

    def test_log_event(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        store.log_event("creative.test", {"key": "value"})
        events = store.load_events()
        assert len(events) == 1
        assert events[0]["event"] == "creative.test"

    def test_save_personality_signal(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        sig = PersonalitySignal.create(
            PersonalityDimension.DEPTH_VS_BREADTH,
            "increase_breadth", "test", 0.05,
        )
        store.save_personality_signal(sig)
        loaded = store.load_personality_signals()
        assert len(loaded) == 1

    def test_get_memories_by_importance(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        for imp in [0.3, 0.5, 0.9]:
            mem = ConversationMemoryEntry.create(
                "s1", Speaker.OPERATOR, f"imp={imp}",
                ConversationMemoryType.PREFERENCE, imp,
            )
            store.save_conversation_memory(mem)

        high = store.get_memories_by_importance(0.7)
        assert len(high) == 1
        assert high[0]["importance"] == 0.9


# --- Strategic Context ---

from agent_core.creative.strategic_context import StrategicContext


class TestStrategicContext:
    """Test context building."""

    def _setup_files(self, tmp_path):
        """Create minimal JSONL files for context building."""
        meta = tmp_path / "meta_data"
        meta.mkdir()
        memory = tmp_path / "memory"
        memory.mkdir()

        # planner_decisions.jsonl with NOOPs
        decisions = meta / "planner_decisions.jsonl"
        now = time.time()
        with open(decisions, "w") as f:
            for i in range(20):
                f.write(json.dumps({
                    "timestamp": now - 100 + i,
                    "action_type": "noop",
                    "status": "completed",
                }) + "\n")
            f.write(json.dumps({
                "timestamp": now - 50,
                "action_type": "learn",
                "status": "failed",
            }) + "\n")

        # knowledge_index.jsonl
        index = memory / "knowledge_index.jsonl"
        with open(index, "w") as f:
            for i in range(10):
                f.write(json.dumps({
                    "id": f"file_{i}.txt",
                    "status": "completed",
                }) + "\n")

        return str(meta), str(memory)

    def test_build_context(self, tmp_path):
        meta, memory = self._setup_files(tmp_path)
        ctx = StrategicContext(meta, memory)
        result = ctx.build(period_hours=24.0)

        assert "action_pattern" in result
        assert "learning_state" in result
        assert "goal_state" in result
        assert result["action_pattern"]["total"] == 21

    def test_noop_ratio_calculated(self, tmp_path):
        meta, memory = self._setup_files(tmp_path)
        ctx = StrategicContext(meta, memory)
        result = ctx.build(period_hours=24.0)

        ratio = result["action_pattern"]["noop_ratio"]
        assert ratio > 0.9  # 20/21 NOOPs

    def test_learning_coverage(self, tmp_path):
        meta, memory = self._setup_files(tmp_path)
        ctx = StrategicContext(meta, memory)
        result = ctx.build()

        assert result["learning_state"]["total_files"] == 10
        assert result["learning_state"]["completed"] == 10
        assert result["learning_state"]["coverage"] == 1.0

    def test_empty_data(self, tmp_path):
        meta = tmp_path / "meta_data"
        meta.mkdir()
        memory = tmp_path / "memory"
        memory.mkdir()
        ctx = StrategicContext(str(meta), str(memory))
        result = ctx.build()

        assert result["action_pattern"]["total"] == 0
        assert result["learning_state"]["total_files"] == 0


# --- Tension Detector ---

from agent_core.creative.tension_detector import TensionDetector


class TestTensionDetector:
    """Test rule-based tension detection."""

    def test_detect_repetition(self):
        detector = TensionDetector()
        context = {
            "action_pattern": {"noop_ratio": 0.9, "total": 100, "distribution": {"noop": 90}},
            "learning_state": {"coverage": 0.5},
            "goal_state": {"active": 1, "stale_goals": []},
            "recent_meta_goals": [],
            "period_hours": 24,
        }
        tensions = detector.detect(context)
        categories = [t.category for t in tensions]
        assert TensionCategory.REPETITION in categories

    def test_detect_under_exploration(self):
        detector = TensionDetector()
        context = {
            "action_pattern": {"noop_ratio": 0.5, "total": 50, "failed_ratio": 0,
                               "distribution": {"noop": 25, "fetch": 10}},
            "learning_state": {"coverage": 0.95, "retention_rate": 0.9},
            "goal_state": {"active": 1, "stale_goals": []},
            "recent_meta_goals": [],
            "period_hours": 24,
        }
        tensions = detector.detect(context)
        categories = [t.category for t in tensions]
        assert TensionCategory.UNDER_EXPLORATION in categories

    def test_detect_stagnation(self):
        detector = TensionDetector()
        context = {
            "action_pattern": {"noop_ratio": 0.3, "total": 50, "failed_ratio": 0,
                               "distribution": {}},
            "learning_state": {"coverage": 0.5, "learning_velocity": 0.0,
                               "retention_rate": 0.9},
            "goal_state": {"active": 1, "stale_goals": []},
            "recent_meta_goals": [],
            "period_hours": 24,
        }
        tensions = detector.detect(context)
        categories = [t.category for t in tensions]
        assert TensionCategory.STAGNATION in categories

    def test_detect_epistemic_gap(self):
        detector = TensionDetector()
        context = {
            "action_pattern": {"noop_ratio": 0.3, "total": 50, "failed_ratio": 0,
                               "distribution": {}},
            "learning_state": {"coverage": 0.5, "retention_rate": 0.5},
            "goal_state": {"active": 1, "stale_goals": []},
            "recent_meta_goals": [],
            "period_hours": 24,
        }
        tensions = detector.detect(context)
        categories = [t.category for t in tensions]
        assert TensionCategory.EPISTEMIC_GAP in categories

    def test_detect_misalignment(self):
        detector = TensionDetector()
        context = {
            "action_pattern": {"noop_ratio": 0.3, "total": 50, "failed_ratio": 0,
                               "distribution": {}},
            "learning_state": {"coverage": 0.5},
            "goal_state": {"active": 3, "stale_goals": ["goal1", "goal2"]},
            "recent_meta_goals": [],
            "period_hours": 24,
        }
        tensions = detector.detect(context)
        categories = [t.category for t in tensions]
        assert TensionCategory.MISALIGNMENT in categories

    def test_detect_fragile_coordination(self):
        detector = TensionDetector()
        context = {
            "action_pattern": {"noop_ratio": 0.3, "total": 20, "failed_ratio": 0.4,
                               "distribution": {}},
            "learning_state": {"coverage": 0.5},
            "goal_state": {"active": 1, "stale_goals": []},
            "recent_meta_goals": [],
            "period_hours": 24,
        }
        tensions = detector.detect(context)
        categories = [t.category for t in tensions]
        assert TensionCategory.FRAGILE_COORDINATION in categories

    def test_no_tensions_healthy_system(self):
        detector = TensionDetector()
        context = {
            "action_pattern": {"noop_ratio": 0.3, "total": 50, "failed_ratio": 0.05,
                               "distribution": {"learn": 20, "noop": 15}},
            "learning_state": {"coverage": 0.5, "learning_velocity": 0.5,
                               "retention_rate": 0.9},
            "goal_state": {"active": 2, "stale_goals": []},
            "recent_meta_goals": [],
            "period_hours": 24,
        }
        tensions = detector.detect(context)
        assert len(tensions) == 0

    def test_sorted_by_severity(self):
        detector = TensionDetector()
        context = {
            "action_pattern": {"noop_ratio": 0.95, "total": 100, "failed_ratio": 0.4,
                               "distribution": {"noop": 95}},
            "learning_state": {"coverage": 0.95, "retention_rate": 0.5},
            "goal_state": {"active": 3, "stale_goals": ["g1", "g2"]},
            "recent_meta_goals": [],
            "period_hours": 24,
        }
        tensions = detector.detect(context)
        assert len(tensions) > 1
        severities = [t.severity for t in tensions]
        assert severities == sorted(severities, reverse=True)


# --- Reflection Workspace ---

from agent_core.creative.reflection_workspace import ReflectionWorkspaceManager


class TestReflectionWorkspace:
    """Test reflection session management."""

    def test_create_session(self):
        mgr = ReflectionWorkspaceManager()
        session = mgr.create_session("periodic", "Test reflection")
        assert session.trigger == "periodic"
        assert not session.closed

    def test_form_insights(self):
        mgr = ReflectionWorkspaceManager()
        session = mgr.create_session("test")
        session.add_tension(DetectedTension.create(
            TensionCategory.REPETITION, "Stuck in NOOP", 0.8, ["ref1"],
        ))
        session.add_tension(DetectedTension.create(
            TensionCategory.STAGNATION, "No progress", 0.6, ["ref2"],
        ))

        insights = mgr.form_insights(session)
        assert len(insights) == 2
        assert any(i.meta_goal_candidate for i in insights)

    def test_form_insights_filters_low_severity(self):
        mgr = ReflectionWorkspaceManager()
        session = mgr.create_session("test")
        session.add_tension(DetectedTension.create(
            TensionCategory.REPETITION, "Minor", 0.3, [],
        ))
        insights = mgr.form_insights(session)
        assert len(insights) == 0

    def test_generate_candidates(self):
        mgr = ReflectionWorkspaceManager()
        session = mgr.create_session("test")
        t = DetectedTension.create(
            TensionCategory.UNDER_EXPLORATION, "Need new topics", 0.8, ["ref1"],
        )
        session.add_tension(t)
        mgr.form_insights(session)

        context = {"learning_state": {"coverage": 0.95}}
        candidates = mgr.generate_candidates(session, context)
        assert len(candidates) >= 1
        assert candidates[0].goal_type == MetaGoalType.EXPLORATION_META


# --- Novelty Filter ---

from agent_core.creative.novelty_filter import NoveltyFilter


class TestNoveltyFilter:
    """Test dedup and flood protection."""

    def test_accept_novel_goal(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        nf = NoveltyFilter(store)

        mg = MetaGoal.create(
            title="Explore new science topics in depth",
            goal_type=MetaGoalType.EXPLORATION_META,
            priority=0.7, why_now="test", evidence_refs=["e1"],
            expected_value="test",
        )
        accepted, rejected = nf.filter([mg])
        assert len(accepted) == 1
        assert len(rejected) == 0

    def test_reject_exact_duplicate(self, tmp_path):
        store = CreativeStore(str(tmp_path))

        # Save existing meta-goal
        existing = MetaGoal.create(
            title="Explore new science topics",
            goal_type=MetaGoalType.EXPLORATION_META,
            priority=0.5, why_now="old", evidence_refs=["e1"],
            expected_value="old",
        )
        store.save_meta_goal(existing)

        nf = NoveltyFilter(store)
        duplicate = MetaGoal.create(
            title="Explore new science topics",  # Same title
            goal_type=MetaGoalType.EXPLORATION_META,
            priority=0.7, why_now="new", evidence_refs=["e2"],
            expected_value="new",
        )
        accepted, rejected = nf.filter([duplicate])
        assert len(accepted) == 0
        assert len(rejected) == 1

    def test_reject_no_evidence(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        nf = NoveltyFilter(store)

        mg = MetaGoal.create(
            title="Some strategic direction without evidence",
            goal_type=MetaGoalType.EPISTEMIC_META,
            priority=0.5, why_now="no reason", evidence_refs=[],
            expected_value="test",
        )
        accepted, rejected = nf.filter([mg])
        assert len(accepted) == 0

    def test_flood_protection(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        nf = NoveltyFilter(store)

        goals = []
        for i in range(5):
            mg = MetaGoal.create(
                title=f"Unique strategic goal number {i} with details",
                goal_type=MetaGoalType(list(MetaGoalType)[i % len(list(MetaGoalType))].value),
                priority=0.6, why_now=f"reason {i}",
                evidence_refs=[f"e{i}"], expected_value=f"value {i}",
            )
            goals.append(mg)

        accepted, rejected = nf.filter(goals)
        assert len(accepted) <= 3  # MAX_PROPOSALS_PER_PERIOD

    def test_reject_overly_broad(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        nf = NoveltyFilter(store)

        mg = MetaGoal.create(
            title="rozwoj",  # Too generic
            goal_type=MetaGoalType.CAPABILITY_META,
            priority=0.5, why_now="test", evidence_refs=["e1"],
            expected_value="test",
        )
        accepted, rejected = nf.filter([mg])
        assert len(accepted) == 0


# --- Creative Evaluator ---

from agent_core.creative.creative_evaluator import CreativeEvaluator, PROMOTION_THRESHOLD


class TestCreativeEvaluator:
    """Test multi-dimension scoring."""

    def test_evaluate_basic(self):
        evaluator = CreativeEvaluator()
        mg = MetaGoal.create(
            title="Explore interdisciplinary topics",
            goal_type=MetaGoalType.EXPLORATION_META,
            priority=0.7, why_now="test", evidence_refs=["e1"],
            expected_value="test",
        )
        result = evaluator.evaluate(mg)
        assert "final_score" in result
        assert "promoted" in result
        assert result["final_score"] > 0

    def test_high_coverage_boost(self):
        evaluator = CreativeEvaluator()
        mg = MetaGoal.create(
            title="Explore new domains",
            goal_type=MetaGoalType.EXPLORATION_META,
            priority=0.6, why_now="test", evidence_refs=["e1"],
            expected_value="test",
        )
        context = {"learning_state": {"coverage": 0.95}}
        result = evaluator.evaluate(mg, context)
        assert result["strategic_value"] > 0.6  # Boosted

    def test_batch_sorted_by_score(self):
        evaluator = CreativeEvaluator()
        goals = [
            MetaGoal.create(
                title=f"Goal with priority {p}",
                goal_type=MetaGoalType.EXPLORATION_META,
                priority=p, why_now="test", evidence_refs=["e1"],
                expected_value="test",
            )
            for p in [0.3, 0.9, 0.6]
        ]
        results = evaluator.evaluate_batch(goals)
        scores = [r["final_score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_operator_dependent_low_feasibility(self):
        evaluator = CreativeEvaluator()
        mg = MetaGoal.create(
            title="Request architecture change from operator",
            goal_type=MetaGoalType.ARCHITECTURAL_META,
            priority=0.7, why_now="test", evidence_refs=["e1"],
            expected_value="test",
        )
        result = evaluator.evaluate(mg)
        assert result["feasibility"] < 0.5


# --- Goal Adapter ---

from agent_core.creative.goal_adapter import GoalAdapter


class TestGoalAdapter:
    """Test GoalStore integration."""

    def test_adapt_with_no_store(self):
        adapter = GoalAdapter(goal_store=None)
        mg = MetaGoal.create(
            title="Test", goal_type=MetaGoalType.EXPLORATION_META,
            priority=0.5, why_now="test", evidence_refs=["e1"],
            expected_value="test",
        )
        result = adapter.adapt_and_propose(mg)
        assert result is None

    def test_adapt_with_mock_store(self):
        mock_store = MagicMock()
        mock_store.propose.return_value = "goal-123"

        adapter = GoalAdapter(goal_store=mock_store)
        mg = MetaGoal.create(
            title="Test strategic goal",
            goal_type=MetaGoalType.EXPLORATION_META,
            priority=0.7, why_now="test reason", evidence_refs=["e1"],
            expected_value="new knowledge",
        )
        result = adapter.adapt_and_propose(mg)
        assert result == "goal-123"
        mock_store.propose.assert_called_once()

    def test_adapt_store_full(self):
        mock_store = MagicMock()
        mock_store.propose.return_value = None  # At limit

        adapter = GoalAdapter(goal_store=mock_store)
        mg = MetaGoal.create(
            title="Test", goal_type=MetaGoalType.EXPLORATION_META,
            priority=0.5, why_now="test", evidence_refs=["e1"],
            expected_value="test",
        )
        result = adapter.adapt_and_propose(mg)
        assert result is None

    def test_adapt_batch(self):
        mock_store = MagicMock()
        mock_store.propose.side_effect = ["id-1", None, "id-3"]

        adapter = GoalAdapter(goal_store=mock_store)
        goals = [
            MetaGoal.create(
                title=f"Goal {i}", goal_type=MetaGoalType.EXPLORATION_META,
                priority=0.5, why_now="test", evidence_refs=["e1"],
                expected_value="test",
            )
            for i in range(3)
        ]
        result = adapter.adapt_batch(goals)
        assert result["proposed"] == 2
        assert result["rejected"] == 1


# --- Journal ---

from agent_core.creative.creative_journal import CreativeJournal


class TestCreativeJournal:
    """Test journal entry creation."""

    def test_create_from_session(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        journal = CreativeJournal(store)

        session = ReflectionSession(trigger="periodic")
        session.add_tension(DetectedTension.create(
            TensionCategory.REPETITION, "Test", 0.7, [],
        ))
        entry = journal.create_entry_from_session(session)

        assert entry.trigger == "periodic"
        assert "repetition" in entry.summary.lower()

    def test_auto_summarize(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        journal = CreativeJournal(store)

        session = ReflectionSession(trigger="test")
        session.add_tension(DetectedTension.create(
            TensionCategory.STAGNATION, "No progress", 0.6, [],
        ))
        session.insights.append(CreativeInsight.create(
            ["t1"], "Insight", 0.7,
        ))
        entry = journal.create_entry_from_session(session)
        assert "stagnation" in entry.summary.lower()
        assert "1 wnioskow" in entry.summary


# --- Conversation Memory ---

from agent_core.creative.conversation_memory import CreativeConversationMemory


class TestConversationMemory:
    """Test operator-dialogue memory."""

    def test_record_and_retrieve(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        mem = CreativeConversationMemory(store)

        mem.record(
            "session-1", Speaker.OPERATOR, "Focus on science topics",
            ConversationMemoryType.PREFERENCE, 0.8,
        )
        results = mem.retrieve_relevant(["science", "topics"])
        assert len(results) == 1

    def test_retrieve_filters_low_importance(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        mem = CreativeConversationMemory(store)

        mem.record(
            "s1", Speaker.OPERATOR, "Maybe try math",
            ConversationMemoryType.PREFERENCE, 0.1,  # Low importance
        )
        results = mem.retrieve_relevant(["math"], min_importance=0.5)
        assert len(results) == 0

    def test_get_operator_preferences(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        mem = CreativeConversationMemory(store)

        mem.record("s1", Speaker.OPERATOR, "Pref 1",
                   ConversationMemoryType.PREFERENCE, 0.8)
        mem.record("s1", Speaker.OPERATOR, "Decision 1",
                   ConversationMemoryType.DECISION, 0.7)

        prefs = mem.get_operator_preferences()
        assert len(prefs) == 1


# --- Facade (full cycle) ---

from agent_core.creative.facade import CreativeModule


class TestCreativeModuleFacade:
    """Test full reflection cycle."""

    def _create_module_with_data(self, tmp_path):
        """Create module with planner data showing NOOP loop."""
        meta = tmp_path / "meta_data"
        meta.mkdir()
        memory = tmp_path / "memory"
        memory.mkdir()

        # Create planner_decisions showing NOOP loop
        decisions = meta / "planner_decisions.jsonl"
        now = time.time()
        with open(decisions, "w") as f:
            for i in range(50):
                f.write(json.dumps({
                    "timestamp": now - 3000 + i * 60,
                    "action_type": "noop",
                    "status": "completed",
                }) + "\n")

        # Knowledge index - all completed
        index = memory / "knowledge_index.jsonl"
        with open(index, "w") as f:
            for i in range(10):
                f.write(json.dumps({
                    "id": f"file_{i}.txt",
                    "status": "completed",
                }) + "\n")

        mock_store = MagicMock()
        mock_store.propose.return_value = "goal-creative-1"

        module = CreativeModule(
            data_dir=str(meta),
            memory_dir=str(memory),
            goal_store=mock_store,
        )
        return module

    def test_reflect_with_tensions(self, tmp_path):
        module = self._create_module_with_data(tmp_path)
        result = module.reflect(trigger="test")

        assert result["success"]
        assert result["tensions"] > 0
        assert result["insights"] > 0
        assert "duration_ms" in result

    def test_reflect_produces_meta_goals(self, tmp_path):
        module = self._create_module_with_data(tmp_path)
        result = module.reflect(trigger="test")

        # Should propose at least 1 meta-goal (NOOP loop = REPETITION tension)
        assert result["meta_goals_proposed"] > 0 or result["meta_goals_promoted"] > 0

    def test_should_reflect_cooldown(self, tmp_path):
        module = self._create_module_with_data(tmp_path)
        assert module.should_reflect()

        module.reflect(trigger="test")
        assert not module.should_reflect()  # Cooldown active

    def test_get_status(self, tmp_path):
        module = self._create_module_with_data(tmp_path)
        status = module.get_status()

        assert "total_reflections" in status
        assert "can_reflect" in status
        assert status["can_reflect"]

    def test_reflect_no_tensions_skips(self, tmp_path):
        """Healthy system = no tensions = quick exit."""
        meta = tmp_path / "meta_data"
        meta.mkdir()
        memory = tmp_path / "memory"
        memory.mkdir()

        # Few actions, good mix
        decisions = meta / "planner_decisions.jsonl"
        now = time.time()
        with open(decisions, "w") as f:
            for i in range(5):
                f.write(json.dumps({
                    "timestamp": now - 100 + i,
                    "action_type": "learn",
                    "status": "completed",
                }) + "\n")

        module = CreativeModule(str(meta), str(memory))
        result = module.reflect()

        assert result["success"]
        assert result["tensions"] == 0
        assert result["meta_goals_proposed"] == 0

    def test_journal_written_after_reflection(self, tmp_path):
        module = self._create_module_with_data(tmp_path)
        module.reflect(trigger="test")

        # Check journal file exists and has entry
        journal_path = tmp_path / "meta_data" / "creative_journal.jsonl"
        assert journal_path.exists()
        entries = []
        with open(journal_path) as f:
            for line in f:
                entries.append(json.loads(line))
        assert len(entries) >= 1

    def test_workspace_session_saved(self, tmp_path):
        module = self._create_module_with_data(tmp_path)
        module.reflect(trigger="test")

        ws_path = tmp_path / "meta_data" / "creative_workspace_sessions.jsonl"
        assert ws_path.exists()


# --- Planner integration ---


class TestPlannerCreativeIntegration:
    """Test Creative wiring in planner."""

    def test_action_type_creative_exists(self):
        from agent_core.planner.planner_model import ActionType
        assert ActionType.CREATIVE.value == "creative"

    def test_k7_classification(self):
        from agent_core.autonomy.action_class import classify_action, ActionClassification
        cls = classify_action("creative")
        assert cls == ActionClassification.GUARDED

    def test_k10_safety_profile(self):
        from agent_core.action_safety.safety_classifier import get_safety_profile
        from agent_core.action_safety.safety_model import SafetyMode
        profile = get_safety_profile("creative")
        assert profile.safety_mode == SafetyMode.AUDIT_ONLY

    def test_executor_creative_dispatch(self):
        from agent_core.planner.action_executor import ActionExecutor
        from agent_core.planner.planner_model import ActionType, create_plan

        mock_creative = MagicMock()
        mock_creative.reflect.return_value = {
            "success": True, "tensions": 2, "meta_goals_promoted": 1,
        }

        executor = ActionExecutor()
        executor.set_creative_module(mock_creative)

        plan = create_plan(
            goal_id=None,
            goal_description="K13 Creative reflection",
            action_type=ActionType.CREATIVE,
            action_params={"trigger": "planner_idle"},
        )
        result = executor.execute(plan)
        assert result["success"]
        mock_creative.reflect.assert_called_once_with(trigger="planner_idle")
