"""
Tests for Cognitive Bulletin Board (Phase 1).

Model + Store + dedup + queries + maintenance.
"""

import json
import time
import pytest

from agent_core.bulletin.bulletin_model import (
    BulletinEntry,
    EntryType,
    EntryStatus,
    create_entry,
    STALE_TIMEOUT_SEC,
)
from agent_core.bulletin.bulletin_store import BulletinStore
from agent_core.bulletin.knowledge_auditor import (
    KnowledgeAuditor,
    AuditReport,
    KnowledgeGap,
    GapType,
)
from agent_core.bulletin.gap_planner import (
    GapPlanner,
    GapPlan,
    GapAction,
)


# ═══════════════════════════════════════════════════════
# Model Tests
# ═══════════════════════════════════════════════════════


class TestEntryType:
    def test_all_types(self):
        assert len(EntryType) == 5
        values = {t.value for t in EntryType}
        assert values == {
            "need_material", "need_test", "need_review",
            "ready_to_learn", "waiting_human",
        }


class TestEntryStatus:
    def test_all_statuses(self):
        assert len(EntryStatus) == 4
        values = {s.value for s in EntryStatus}
        assert values == {"open", "in_progress", "blocked", "resolved"}


class TestCreateEntry:
    def test_creates_with_id(self):
        e = create_entry(
            entry_type=EntryType.NEED_MATERIAL,
            topic="system kognitywny",
            reason_code="no_material",
            summary="Brak materialu na temat systemu kognitywnego",
            requested_by="planner",
        )
        assert e.entry_id.startswith("cbb-")
        assert len(e.entry_id) == 16  # "cbb-" + 12 hex
        assert e.entry_type == EntryType.NEED_MATERIAL
        assert e.status == EntryStatus.OPEN
        assert e.topic == "system kognitywny"
        assert e.requested_by == "planner"

    def test_default_priority(self):
        e = create_entry(
            entry_type=EntryType.NEED_TEST,
            topic="fizyka",
            reason_code="no_exam",
            summary="Brak egzaminu",
            requested_by="audit",
        )
        assert e.priority == 0.5

    def test_custom_priority_and_goal(self):
        e = create_entry(
            entry_type=EntryType.NEED_MATERIAL,
            topic="AGI",
            reason_code="gap",
            summary="Luka wiedzy",
            requested_by="gap_planner",
            goal_id="goal-abc123",
            priority=0.9,
            metadata={"confidence": 0.3},
        )
        assert e.priority == 0.9
        assert e.goal_id == "goal-abc123"
        assert e.metadata["confidence"] == 0.3


class TestBulletinEntrySerialization:
    def test_roundtrip(self):
        e = create_entry(
            entry_type=EntryType.NEED_REVIEW,
            topic="logika",
            reason_code="low_confidence",
            summary="Niski confidence",
            requested_by="critic",
            goal_id="goal-xyz",
            priority=0.7,
            metadata={"belief_ids": ["b1", "b2"]},
        )
        d = e.to_dict()
        assert d["entry_type"] == "need_review"
        assert d["status"] == "open"

        restored = BulletinEntry.from_dict(d)
        assert restored.entry_id == e.entry_id
        assert restored.entry_type == EntryType.NEED_REVIEW
        assert restored.status == EntryStatus.OPEN
        assert restored.topic == "logika"
        assert restored.metadata["belief_ids"] == ["b1", "b2"]

    def test_from_dict_defaults(self):
        d = {
            "entry_id": "cbb-test123",
            "entry_type": "need_material",
            "topic": "test",
        }
        e = BulletinEntry.from_dict(d)
        assert e.priority == 0.5
        assert e.status == EntryStatus.OPEN
        assert e.requested_by == "unknown"


# ═══════════════════════════════════════════════════════
# Store Tests
# ═══════════════════════════════════════════════════════


@pytest.fixture
def store(tmp_path):
    return BulletinStore(path=tmp_path / "bulletin.jsonl")


class TestBulletinStoreBasic:
    def test_post_and_get(self, store):
        e = create_entry(
            entry_type=EntryType.NEED_MATERIAL,
            topic="fizyka kwantowa",
            reason_code="no_input",
            summary="Brak materialu",
            requested_by="planner",
        )
        store.post(e)
        assert store.get(e.entry_id) is not None
        assert store.get(e.entry_id).topic == "fizyka kwantowa"

    def test_get_nonexistent(self, store):
        assert store.get("cbb-doesnotexist") is None

    def test_create_and_post(self, store):
        e = store.create_and_post(
            entry_type=EntryType.NEED_TEST,
            topic="biologia",
            reason_code="no_exam",
            summary="Potrzebny egzamin",
            requested_by="audit",
        )
        assert e.entry_id.startswith("cbb-")
        assert store.get(e.entry_id) is not None


class TestBulletinStoreDedup:
    def test_dedup_same_topic_and_type(self, store):
        e1 = store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="AGI",
            reason_code="no_input",
            summary="First request",
            requested_by="planner",
        )
        e2 = store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="AGI",
            reason_code="no_input",
            summary="Duplicate request",
            requested_by="planner",
        )
        assert e1.entry_id == e2.entry_id  # Same entry returned
        assert len(store.get_open()) == 1

    def test_different_type_not_deduped(self, store):
        store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="AGI",
            reason_code="no_input",
            summary="Need material",
            requested_by="planner",
        )
        store.create_and_post(
            entry_type=EntryType.NEED_TEST,
            topic="AGI",
            reason_code="no_exam",
            summary="Need test",
            requested_by="audit",
        )
        assert len(store.get_open()) == 2

    def test_resolved_entry_allows_new(self, store):
        e1 = store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="fizyka",
            reason_code="no_input",
            summary="First",
            requested_by="planner",
        )
        store.resolve(e1.entry_id)
        e2 = store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="fizyka",
            reason_code="no_input",
            summary="Second after resolve",
            requested_by="planner",
        )
        assert e1.entry_id != e2.entry_id


class TestBulletinStoreStatusUpdates:
    def test_update_status(self, store):
        e = store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="chemia",
            reason_code="gap",
            summary="Need",
            requested_by="planner",
        )
        assert store.update_status(e.entry_id, EntryStatus.IN_PROGRESS, "fetching")
        updated = store.get(e.entry_id)
        assert updated.status == EntryStatus.IN_PROGRESS
        assert updated.metadata["last_status_reason"] == "fetching"

    def test_resolve(self, store):
        e = store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="chemia",
            reason_code="gap",
            summary="Need",
            requested_by="planner",
        )
        assert store.resolve(e.entry_id, "material_arrived")
        assert store.get(e.entry_id).status == EntryStatus.RESOLVED

    def test_update_nonexistent(self, store):
        assert store.update_status("cbb-fake", EntryStatus.BLOCKED) is False


class TestBulletinStoreQueries:
    def _populate(self, store):
        store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="AGI",
            reason_code="no_input",
            summary="Need AGI material",
            requested_by="planner",
            priority=0.8,
        )
        store.create_and_post(
            entry_type=EntryType.NEED_TEST,
            topic="fizyka",
            reason_code="no_exam",
            summary="Need physics exam",
            requested_by="audit",
            priority=0.5,
        )
        e3 = store.create_and_post(
            entry_type=EntryType.NEED_REVIEW,
            topic="logika",
            reason_code="low_conf",
            summary="Low confidence",
            requested_by="critic",
            priority=0.7,
        )
        store.update_status(e3.entry_id, EntryStatus.BLOCKED, "rate_limited")
        return e3

    def test_get_open_sorted_by_priority(self, store):
        self._populate(store)
        entries = store.get_open()
        assert len(entries) == 3
        assert entries[0].priority == 0.8  # AGI first

    def test_get_by_type(self, store):
        self._populate(store)
        materials = store.get_by_type(EntryType.NEED_MATERIAL)
        assert len(materials) == 1
        assert materials[0].topic == "AGI"

    def test_get_actionable_excludes_blocked(self, store):
        self._populate(store)
        actionable = store.get_actionable()
        assert len(actionable) == 2  # logika is BLOCKED
        topics = {e.topic for e in actionable}
        assert "logika" not in topics

    def test_find_open_by_topic(self, store):
        self._populate(store)
        results = store.find_open(topic="agi")  # case-insensitive
        assert len(results) == 1
        assert results[0].topic == "AGI"

    def test_find_open_by_goal_id(self, store):
        store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="test",
            reason_code="gap",
            summary="test",
            requested_by="planner",
            goal_id="goal-123",
        )
        results = store.find_open(goal_id="goal-123")
        assert len(results) == 1

    def test_get_for_goal(self, store):
        store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="a",
            reason_code="x",
            summary="x",
            requested_by="p",
            goal_id="goal-abc",
        )
        e2 = store.create_and_post(
            entry_type=EntryType.NEED_TEST,
            topic="b",
            reason_code="y",
            summary="y",
            requested_by="p",
            goal_id="goal-abc",
        )
        store.resolve(e2.entry_id)
        # get_for_goal returns all, including resolved
        results = store.get_for_goal("goal-abc")
        assert len(results) == 2


class TestBulletinStorePersistence:
    def test_persist_and_reload(self, tmp_path):
        path = tmp_path / "bulletin.jsonl"
        store1 = BulletinStore(path=path)
        store1.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="persist test",
            reason_code="test",
            summary="test",
            requested_by="test",
        )
        assert path.exists()

        # New store instance loads from same file
        store2 = BulletinStore(path=path)
        entries = store2.get_open()
        assert len(entries) == 1
        assert entries[0].topic == "persist test"

    def test_merge_on_reload(self, tmp_path):
        path = tmp_path / "bulletin.jsonl"
        store = BulletinStore(path=path)
        e = store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="merge test",
            reason_code="test",
            summary="original",
            requested_by="test",
        )
        store.update_status(e.entry_id, EntryStatus.IN_PROGRESS)

        # Reload: JSONL has 2 lines for same entry, MERGE keeps latest
        store2 = BulletinStore(path=path)
        loaded = store2.get(e.entry_id)
        assert loaded.status == EntryStatus.IN_PROGRESS


class TestBulletinStoreMaintenance:
    def test_prune_stale(self, store):
        e = store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="old topic",
            reason_code="test",
            summary="test",
            requested_by="test",
        )
        # Force old timestamp
        e.updated_at = time.time() - STALE_TIMEOUT_SEC - 100
        pruned = store.prune_stale()
        assert pruned == 1
        assert store.get(e.entry_id).status == EntryStatus.RESOLVED

    def test_prune_skips_fresh(self, store):
        store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="fresh",
            reason_code="test",
            summary="test",
            requested_by="test",
        )
        pruned = store.prune_stale()
        assert pruned == 0

    def test_compact(self, tmp_path):
        path = tmp_path / "bulletin.jsonl"
        store = BulletinStore(path=path)
        e = store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="compact test",
            reason_code="test",
            summary="test",
            requested_by="test",
        )
        store.update_status(e.entry_id, EntryStatus.IN_PROGRESS)
        store.update_status(e.entry_id, EntryStatus.RESOLVED)

        # Before compact: 3 lines (create + 2 updates)
        with open(path) as f:
            lines_before = len(f.readlines())
        assert lines_before == 3

        store.compact()

        # After compact: 1 line (merged)
        with open(path) as f:
            lines_after = len(f.readlines())
        assert lines_after == 1

    def test_stats(self, store):
        store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="a",
            reason_code="x",
            summary="x",
            requested_by="p",
        )
        store.create_and_post(
            entry_type=EntryType.NEED_TEST,
            topic="b",
            reason_code="y",
            summary="y",
            requested_by="p",
        )
        s = store.stats()
        assert s["total"] == 2
        assert s["open"] == 2
        assert s["actionable"] == 2
        assert s["by_type"]["need_material"] == 1
        assert s["by_type"]["need_test"] == 1


# ═══════════════════════════════════════════════════════
# Planner Integration Tests
# ═══════════════════════════════════════════════════════


class TestBulletinPlannerIntegration:
    """Test that planner posts NEED_MATERIAL when all sources exhausted."""

    def test_noop_posts_need_material(self, tmp_path):
        """When _decide_learning_action returns NOOP, bulletin gets entry."""
        from agent_core.planner.planner_core import PlannerCore
        from agent_core.planner.planner_model import ActionType
        from agent_core.tracing.trace_model import DecisionTrace

        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        store = BulletinStore(path=tmp_path / "bulletin.jsonl")
        planner.set_bulletin_store(store)

        # Set up trace with goal info so _post_need_material works
        trace = DecisionTrace(episode_id="ep-test")
        trace.goal_id = "goal-123"
        trace.goal_description = "Nauka: system kognitywny"
        planner._current_trace = trace

        # All files completed, no new files, retention OK
        snapshot = {"files_by_status": {"completed": ["f1"]}, "new_files_available": []}

        # Mock rate limiter to block fetch and ask_expert
        planner._autonomy_policy = None  # no policy = _is_action_rate_limited returns False

        action = planner._decide_learning_action(snapshot, {"retention_rate": 0.95})
        # Should be FETCH or ASK_EXPERT (not rate-limited without policy)
        # But if we mock rate limiting:
        # For now just verify NOOP path posts to bulletin
        # Let's force the NOOP path by making fetch rate-limited
        from unittest.mock import MagicMock
        mock_policy = MagicMock()
        mock_policy.classify_and_check.return_value = (
            MagicMock(decision="deny", reason="rate_limit"),
        )
        planner._autonomy_policy = mock_policy

        # Override to always rate-limit
        planner._is_action_rate_limited = lambda x: True
        planner._world_model = None

        action = planner._decide_learning_action(snapshot, {"retention_rate": 0.95})
        assert action == ActionType.NOOP

        # Bulletin should have NEED_MATERIAL entry
        entries = store.get_open()
        assert len(entries) == 1
        assert entries[0].entry_type == EntryType.NEED_MATERIAL
        assert "system kognitywny" in entries[0].topic
        assert entries[0].goal_id == "goal-123"

    def test_no_bulletin_no_crash(self, tmp_path):
        """Without bulletin store, NOOP still works (graceful fallback)."""
        from agent_core.planner.planner_core import PlannerCore
        from agent_core.planner.planner_model import ActionType

        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        # No bulletin store set
        planner._is_action_rate_limited = lambda x: True
        planner._world_model = None

        snapshot = {"files_by_status": {"completed": ["f1"]}, "new_files_available": []}
        action = planner._decide_learning_action(snapshot, {"retention_rate": 0.95})
        assert action == ActionType.NOOP  # No crash


class TestBulletinExecutorIntegration:
    """Test that executor resolves bulletin entries after successful actions."""

    def test_resolve_after_learn(self, tmp_path):
        """After successful LEARN, bulletin entries are resolved."""
        from agent_core.planner.action_executor import ActionExecutor
        from agent_core.planner.planner_model import create_plan, ActionType

        store = BulletinStore(path=tmp_path / "bulletin.jsonl")
        entry = store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="fizyka",
            reason_code="no_input",
            summary="Need physics material",
            requested_by="planner",
            goal_id="goal-phys",
        )

        executor = ActionExecutor()
        executor.set_bulletin_store(store)

        # Mock teacher
        from unittest.mock import MagicMock
        teacher = MagicMock()
        teacher.run_session.return_value = {
            "stats": {"chunks_learned": 3, "strategies_executed": 1}
        }
        executor.set_teacher_agent(teacher)

        # Mock goal store for _update_learning_goal
        mock_gs = MagicMock()
        mock_gs.get.return_value = None
        executor.set_goal_store(mock_gs)

        plan = create_plan("goal-phys", "Fizyka", ActionType.LEARN)
        executor._exec_learn(plan)

        # Entry should be resolved
        assert store.get(entry.entry_id).status == EntryStatus.RESOLVED

    def test_transition_to_ready_after_fetch(self, tmp_path):
        """After successful FETCH, NEED_MATERIAL -> READY_TO_LEARN."""
        from agent_core.planner.action_executor import ActionExecutor
        from agent_core.planner.planner_model import create_plan, ActionType
        from unittest.mock import MagicMock, patch

        store = BulletinStore(path=tmp_path / "bulletin.jsonl")
        entry = store.create_and_post(
            entry_type=EntryType.NEED_MATERIAL,
            topic="biologia",
            reason_code="no_input",
            summary="Need biology material",
            requested_by="planner",
            goal_id="goal-bio",
        )

        executor = ActionExecutor()
        executor.set_bulletin_store(store)

        # Mock knowledge analyzer
        mock_ka = MagicMock()
        executor.set_knowledge_analyzer(mock_ka)

        # Mock fetch session
        with patch("agent_core.planner.action_executor.ActionExecutor._exec_fetch") as mock:
            # Call the real transition method
            executor._transition_bulletin_to_ready("goal-bio")

        # NEED_MATERIAL should be resolved
        assert store.get(entry.entry_id).status == EntryStatus.RESOLVED

        # READY_TO_LEARN should exist
        ready = store.get_by_type(EntryType.READY_TO_LEARN)
        assert len(ready) == 1
        assert ready[0].topic == "biologia"
        assert ready[0].goal_id == "goal-bio"


# ═══════════════════════════════════════════════════════
# KnowledgeAuditor Tests (Phase 2)
# ═══════════════════════════════════════════════════════


class TestKnowledgeAuditorModel:
    def test_gap_types(self):
        assert len(GapType) == 7

    def test_audit_report_no_gaps(self):
        report = AuditReport(topic="test", known=True)
        assert not report.has_gaps
        assert report.worst_gap_severity == 0.0

    def test_audit_report_with_gaps(self):
        report = AuditReport(topic="test", known=True, gaps=[
            KnowledgeGap(GapType.LOW_CONFIDENCE, "test", 0.7, "low"),
            KnowledgeGap(GapType.STALE, "test", 0.4, "stale"),
        ])
        assert report.has_gaps
        assert report.worst_gap_severity == 0.7

    def test_audit_report_serialization(self):
        report = AuditReport(topic="fizyka", known=True, files_count=3)
        d = report.to_dict()
        assert d["topic"] == "fizyka"
        assert d["known"] is True
        assert d["files_count"] == 3


class TestKnowledgeAuditorBasic:
    def test_no_subsystems_returns_unknown(self):
        """Without MemoryQuery, topic is unknown -> NEED_MATERIAL."""
        auditor = KnowledgeAuditor()
        report = auditor.audit_topic("quantum physics")
        assert not report.known
        assert report.has_gaps
        assert report.gaps[0].gap_type == GapType.NO_MATERIAL
        assert "need_material" in report.suggested_actions

    def test_known_topic_high_confidence(self):
        """Well-known topic with good confidence -> no gaps."""
        from unittest.mock import MagicMock
        auditor = KnowledgeAuditor()
        mock_mq = MagicMock()
        mock_mq.get_topic_summary.return_value = {
            "known": True,
            "files_count": 5,
            "beliefs_count": 10,
            "avg_confidence": 0.8,
            "freshness": 0.9,
        }
        auditor.set_memory_query(mock_mq)

        report = auditor.audit_topic("biologia")
        assert report.known
        assert report.files_count == 5
        assert not report.has_gaps  # All good

    def test_low_confidence_gap(self):
        """Topic with low confidence -> LOW_CONFIDENCE gap."""
        from unittest.mock import MagicMock
        auditor = KnowledgeAuditor()
        mock_mq = MagicMock()
        mock_mq.get_topic_summary.return_value = {
            "known": True,
            "files_count": 2,
            "beliefs_count": 3,
            "avg_confidence": 0.25,
            "freshness": 0.7,
        }
        auditor.set_memory_query(mock_mq)

        report = auditor.audit_topic("fizyka kwantowa")
        assert report.has_gaps
        gap_types = {g.gap_type for g in report.gaps}
        assert GapType.LOW_CONFIDENCE in gap_types
        assert "need_material" in report.suggested_actions

    def test_shallow_knowledge_gap(self):
        """Files exist but few beliefs -> SHALLOW gap."""
        from unittest.mock import MagicMock
        auditor = KnowledgeAuditor()
        mock_mq = MagicMock()
        mock_mq.get_topic_summary.return_value = {
            "known": True,
            "files_count": 3,
            "beliefs_count": 1,
            "avg_confidence": 0.6,
            "freshness": 0.8,
        }
        auditor.set_memory_query(mock_mq)

        report = auditor.audit_topic("genetyka")
        assert report.has_gaps
        gap_types = {g.gap_type for g in report.gaps}
        assert GapType.SHALLOW in gap_types

    def test_stale_knowledge_gap(self):
        """Old knowledge -> STALE gap."""
        from unittest.mock import MagicMock
        auditor = KnowledgeAuditor()
        mock_mq = MagicMock()
        mock_mq.get_topic_summary.return_value = {
            "known": True,
            "files_count": 2,
            "beliefs_count": 5,
            "avg_confidence": 0.7,
            "freshness": 0.1,
        }
        auditor.set_memory_query(mock_mq)

        report = auditor.audit_topic("chemia")
        assert report.has_gaps
        gap_types = {g.gap_type for g in report.gaps}
        assert GapType.STALE in gap_types
        assert "need_review" in report.suggested_actions

    def test_exam_coverage_check(self):
        """Learned files without exam -> NO_EXAM gap."""
        from unittest.mock import MagicMock
        auditor = KnowledgeAuditor()
        mock_mq = MagicMock()
        mock_mq.get_topic_summary.return_value = {
            "known": True,
            "files_count": 2,
            "beliefs_count": 4,
            "avg_confidence": 0.7,
            "freshness": 0.8,
        }
        auditor.set_memory_query(mock_mq)

        mock_ka = MagicMock()
        mock_ka.get_snapshot.return_value = {
            "files_by_status": {
                "learned": ["fizyka_basics.txt", "fizyka_advanced.txt"],
                "completed": [],
            }
        }
        auditor.set_knowledge_analyzer(mock_ka)

        report = auditor.audit_topic("fizyka")
        gap_types = {g.gap_type for g in report.gaps}
        assert GapType.NO_EXAM in gap_types
        assert "need_test" in report.suggested_actions


class TestAuditorPlannerIntegration:
    """Test auditor-driven bulletin posting in planner."""

    def test_auditor_posts_typed_needs(self, tmp_path):
        """Auditor finds gaps -> planner posts correct entry types."""
        from agent_core.planner.planner_core import PlannerCore
        from agent_core.planner.planner_model import ActionType
        from agent_core.tracing.trace_model import DecisionTrace
        from unittest.mock import MagicMock

        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        store = BulletinStore(path=tmp_path / "bulletin.jsonl")
        planner.set_bulletin_store(store)

        # Set up auditor that finds low confidence + stale
        auditor = KnowledgeAuditor()
        mock_mq = MagicMock()
        mock_mq.get_topic_summary.return_value = {
            "known": True,
            "files_count": 1,
            "beliefs_count": 1,
            "avg_confidence": 0.2,
            "freshness": 0.1,
        }
        auditor.set_memory_query(mock_mq)
        planner.set_knowledge_auditor(auditor)

        # Set trace context
        trace = DecisionTrace(episode_id="ep-test")
        trace.goal_id = "goal-aud"
        trace.goal_description = "Nauka: system kognitywny"
        planner._current_trace = trace

        # Force NOOP path
        planner._is_action_rate_limited = lambda x: True
        planner._world_model = None
        snapshot = {"files_by_status": {"completed": ["f1"]}, "new_files_available": []}

        planner._decide_learning_action(snapshot, {"retention_rate": 0.95})

        entries = store.get_open()
        # Should have need_material (low confidence) + need_review (stale)
        types = {e.entry_type for e in entries}
        assert EntryType.NEED_MATERIAL in types
        assert EntryType.NEED_REVIEW in types
        assert all(e.goal_id == "goal-aud" for e in entries)


# ═══════════════════════════════════════════════════════
# GapPlanner Tests (Phase 3)
# ═══════════════════════════════════════════════════════


class TestGapPlannerModel:
    def test_gap_actions(self):
        assert len(GapAction) == 7

    def test_gap_plan_serialization(self):
        plan = GapPlan(
            action=GapAction.ASK_EXPERT,
            topic="AGI",
            reason="no_knowledge",
            priority=0.9,
            context_prompt="Maria nie wie nic o AGI.",
        )
        d = plan.to_dict()
        assert d["action"] == "ask_expert"
        assert d["topic"] == "AGI"
        assert d["context_prompt"] == "Maria nie wie nic o AGI."


class TestGapPlannerDecisions:
    def test_no_gaps_no_action(self):
        gp = GapPlanner()
        report = AuditReport(topic="biologia", known=True)
        plan = gp.plan_for_topic(report)
        assert plan.action == GapAction.NO_ACTION

    def test_no_material_asks_expert(self):
        gp = GapPlanner()
        report = AuditReport(topic="kwanty", known=False, gaps=[
            KnowledgeGap(GapType.NO_MATERIAL, "kwanty", 0.9, "brak"),
        ])
        plan = gp.plan_for_topic(report, "Nauka: fizyka kwantowa")
        assert plan.action == GapAction.ASK_EXPERT
        assert plan.priority == 0.9
        assert "kwanty" in plan.context_prompt
        assert "fizyka kwantowa" in plan.context_prompt

    def test_low_confidence_asks_expert(self):
        gp = GapPlanner()
        report = AuditReport(
            topic="logika", known=True, files_count=2,
            beliefs_count=3, avg_confidence=0.25, gaps=[
                KnowledgeGap(GapType.LOW_CONFIDENCE, "logika", 0.7, "low"),
            ],
        )
        plan = gp.plan_for_topic(report)
        assert plan.action == GapAction.ASK_EXPERT
        assert "confidence" in plan.context_prompt.lower() or "pewnosci" in plan.context_prompt.lower()

    def test_shallow_asks_expert(self):
        gp = GapPlanner()
        report = AuditReport(
            topic="chemia", known=True, files_count=3,
            beliefs_count=1, avg_confidence=0.6, gaps=[
                KnowledgeGap(GapType.SHALLOW, "chemia", 0.5, "shallow"),
            ],
        )
        plan = gp.plan_for_topic(report)
        assert plan.action == GapAction.ASK_EXPERT

    def test_contradictions_review(self):
        gp = GapPlanner()
        report = AuditReport(topic="fizyka", known=True, gaps=[
            KnowledgeGap(GapType.CONTRADICTIONS, "fizyka", 0.8, "sprzecznosci"),
        ])
        plan = gp.plan_for_topic(report)
        assert plan.action == GapAction.REVIEW
        assert plan.reason == "contradictions_detected"

    def test_no_exam_runs_test(self):
        gp = GapPlanner()
        report = AuditReport(topic="historia", known=True, gaps=[
            KnowledgeGap(GapType.NO_EXAM, "historia", 0.3, "untested"),
        ])
        plan = gp.plan_for_topic(report)
        assert plan.action == GapAction.RUN_EXAM

    def test_stale_reviews(self):
        gp = GapPlanner()
        report = AuditReport(
            topic="matematyka", known=True, freshness=0.1, gaps=[
                KnowledgeGap(GapType.STALE, "matematyka", 0.4, "stale"),
            ],
        )
        plan = gp.plan_for_topic(report)
        assert plan.action == GapAction.REVIEW
        assert plan.reason == "knowledge_stale"

    def test_broad_topic_decomposes(self):
        """4+ gap types -> DECOMPOSE."""
        gp = GapPlanner()
        report = AuditReport(topic="nauka", known=True, gaps=[
            KnowledgeGap(GapType.LOW_CONFIDENCE, "nauka", 0.7, "low"),
            KnowledgeGap(GapType.SHALLOW, "nauka", 0.5, "shallow"),
            KnowledgeGap(GapType.STALE, "nauka", 0.4, "stale"),
            KnowledgeGap(GapType.NO_EXAM, "nauka", 0.3, "no exam"),
        ])
        plan = gp.plan_for_topic(report)
        assert plan.action == GapAction.DECOMPOSE
        assert len(plan.subtopics) > 0

    def test_critic_review_takes_priority(self, tmp_path):
        """If bulletin has NEED_REVIEW from critic, review first."""
        store = BulletinStore(path=tmp_path / "b.jsonl")
        store.create_and_post(
            entry_type=EntryType.NEED_REVIEW,
            topic="fizyka",
            reason_code="contradictions",
            summary="Critic found issues",
            requested_by="critic",
        )

        gp = GapPlanner()
        gp.set_bulletin_store(store)

        report = AuditReport(topic="fizyka", known=True, gaps=[
            KnowledgeGap(GapType.LOW_CONFIDENCE, "fizyka", 0.7, "low"),
        ])
        plan = gp.plan_for_topic(report)
        assert plan.action == GapAction.REVIEW
        assert plan.reason == "critic_flagged_quality_issue"


class TestGapPlannerExpertPrompt:
    def test_unknown_topic_prompt(self):
        gp = GapPlanner()
        report = AuditReport(topic="AGI", known=False, gaps=[
            KnowledgeGap(GapType.NO_MATERIAL, "AGI", 0.9, "brak"),
        ])
        plan = gp.plan_for_topic(report, "Nauka: AGI fundamentals")
        assert "nie ma zadnej wiedzy" in plan.context_prompt
        assert "AGI" in plan.context_prompt
        assert "AGI fundamentals" in plan.context_prompt

    def test_known_topic_with_gaps_prompt(self):
        gp = GapPlanner()
        report = AuditReport(
            topic="fizyka", known=True, files_count=2,
            beliefs_count=3, avg_confidence=0.3, gaps=[
                KnowledgeGap(GapType.LOW_CONFIDENCE, "fizyka", 0.7, "low"),
                KnowledgeGap(GapType.SHALLOW, "fizyka", 0.5, "shallow"),
            ],
        )
        plan = gp.plan_for_topic(report)
        assert "podstawowa wiedze" in plan.context_prompt
        assert "2 plikow" in plan.context_prompt
        assert "30%" in plan.context_prompt or "pewnosci" in plan.context_prompt


class TestGapPlannerPlannerIntegration:
    """Full pipeline: planner -> auditor -> gap_planner -> bulletin."""

    def test_full_pipeline_posts_with_context(self, tmp_path):
        from agent_core.planner.planner_core import PlannerCore
        from agent_core.planner.planner_model import ActionType
        from agent_core.tracing.trace_model import DecisionTrace
        from unittest.mock import MagicMock

        planner = PlannerCore(
            state_path=tmp_path / "state.json",
            decisions_path=tmp_path / "decisions.jsonl",
        )
        store = BulletinStore(path=tmp_path / "bulletin.jsonl")
        planner.set_bulletin_store(store)

        # Auditor: topic unknown
        auditor = KnowledgeAuditor()
        mock_mq = MagicMock()
        mock_mq.get_topic_summary.return_value = {"known": False, "topic": "AGI"}
        auditor.set_memory_query(mock_mq)
        planner.set_knowledge_auditor(auditor)

        # Gap planner
        gp = GapPlanner()
        gp.set_bulletin_store(store)
        planner.set_gap_planner(gp)

        # Trace context
        trace = DecisionTrace(episode_id="ep-test")
        trace.goal_id = "goal-agi"
        trace.goal_description = "Nauka: AGI fundamentals"
        planner._current_trace = trace

        # Force NOOP path
        planner._is_action_rate_limited = lambda x: True
        planner._world_model = None
        snapshot = {"files_by_status": {"completed": ["f1"]}, "new_files_available": []}

        planner._decide_learning_action(snapshot, {"retention_rate": 0.95})

        entries = store.get_open()
        assert len(entries) >= 1
        entry = entries[0]
        assert entry.entry_type == EntryType.NEED_MATERIAL
        assert entry.requested_by == "gap_planner"
        assert "context_prompt" in entry.metadata
        assert "AGI" in entry.metadata["context_prompt"]
