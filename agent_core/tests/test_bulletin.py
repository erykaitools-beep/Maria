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
