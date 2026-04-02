"""Tests for Goal System (Kontrakt K3)."""

import json
import time
import pytest
from pathlib import Path

from agent_core.goals.goal_model import (
    GoalType,
    GoalStatus,
    AuditEntry,
    Goal,
    create_goal,
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    MAX_ACTIVE_GOALS,
    MAX_PROPOSED_GOALS,
    PROPOSED_TIMEOUT_SECONDS,
)
from agent_core.goals.store import GoalStore


# ============================================================
# GoalModel Tests
# ============================================================

class TestGoalType:
    def test_all_types(self):
        assert GoalType.META.value == "meta"
        assert GoalType.USER.value == "user"
        assert GoalType.LEARNING.value == "learning"
        assert GoalType.MAINTENANCE.value == "maintenance"

    def test_from_value(self):
        assert GoalType("meta") == GoalType.META
        assert GoalType("learning") == GoalType.LEARNING


class TestGoalStatus:
    def test_all_statuses(self):
        assert GoalStatus.PROPOSED.value == "proposed"
        assert GoalStatus.PENDING.value == "pending"
        assert GoalStatus.ACTIVE.value == "active"
        assert GoalStatus.ACHIEVED.value == "achieved"
        assert GoalStatus.FAILED.value == "failed"
        assert GoalStatus.ABANDONED.value == "abandoned"

    def test_active_statuses(self):
        assert GoalStatus.PENDING in ACTIVE_STATUSES
        assert GoalStatus.ACTIVE in ACTIVE_STATUSES
        assert GoalStatus.PROPOSED not in ACTIVE_STATUSES
        assert GoalStatus.ACHIEVED not in ACTIVE_STATUSES

    def test_terminal_statuses(self):
        assert GoalStatus.ACHIEVED in TERMINAL_STATUSES
        assert GoalStatus.FAILED in TERMINAL_STATUSES
        assert GoalStatus.ABANDONED in TERMINAL_STATUSES
        assert GoalStatus.ACTIVE not in TERMINAL_STATUSES


class TestAuditEntry:
    def test_create(self):
        entry = AuditEntry(
            timestamp=1000.0,
            old_status=None,
            new_status="pending",
            reason="created",
            actor="system",
        )
        assert entry.old_status is None
        assert entry.new_status == "pending"
        assert entry.actor == "system"

    def test_to_dict(self):
        entry = AuditEntry(1000.0, "pending", "active", "started", "teacher")
        d = entry.to_dict()
        assert d["old_status"] == "pending"
        assert d["new_status"] == "active"
        assert d["reason"] == "started"

    def test_from_dict(self):
        d = {"timestamp": 1000.0, "old_status": "active", "new_status": "achieved",
             "reason": "progress >= 1.0", "actor": "system"}
        entry = AuditEntry.from_dict(d)
        assert entry.old_status == "active"
        assert entry.new_status == "achieved"

    def test_roundtrip(self):
        entry = AuditEntry(1000.0, None, "proposed", "auto-suggested", "consciousness")
        d = entry.to_dict()
        restored = AuditEntry.from_dict(d)
        assert restored.timestamp == entry.timestamp
        assert restored.old_status == entry.old_status
        assert restored.actor == entry.actor


class TestGoal:
    def _make_goal(self, **kwargs):
        defaults = dict(
            id="goal-test-1",
            type=GoalType.LEARNING,
            description="Test goal",
            priority=0.7,
            status=GoalStatus.PENDING,
            progress=0.0,
            parent_goal_id=None,
            created_by="test",
            created_at=1000.0,
            updated_at=1000.0,
        )
        defaults.update(kwargs)
        return Goal(**defaults)

    def test_is_active_pending(self):
        g = self._make_goal(status=GoalStatus.PENDING)
        assert g.is_active is True

    def test_is_active_active(self):
        g = self._make_goal(status=GoalStatus.ACTIVE)
        assert g.is_active is True

    def test_is_active_achieved(self):
        g = self._make_goal(status=GoalStatus.ACHIEVED)
        assert g.is_active is False

    def test_is_terminal(self):
        g = self._make_goal(status=GoalStatus.ABANDONED)
        assert g.is_terminal is True

    def test_is_terminal_false(self):
        g = self._make_goal(status=GoalStatus.ACTIVE)
        assert g.is_terminal is False

    def test_to_dict(self):
        g = self._make_goal(metadata={"file_id": "abc"})
        d = g.to_dict()
        assert d["id"] == "goal-test-1"
        assert d["type"] == "learning"
        assert d["status"] == "pending"
        assert d["metadata"]["file_id"] == "abc"

    def test_from_dict(self):
        d = {
            "id": "goal-x", "type": "user", "description": "Learn physics",
            "priority": 0.8, "status": "active", "progress": 0.5,
            "parent_goal_id": None, "created_by": "user",
            "created_at": 1000.0, "updated_at": 2000.0,
            "audit_trail": [
                {"timestamp": 1000.0, "old_status": None, "new_status": "pending",
                 "reason": "created", "actor": "user"},
            ],
            "metadata": {"source": "repl"},
        }
        g = Goal.from_dict(d)
        assert g.type == GoalType.USER
        assert g.status == GoalStatus.ACTIVE
        assert len(g.audit_trail) == 1
        assert g.metadata["source"] == "repl"

    def test_roundtrip(self):
        g = self._make_goal(
            deadline=5000.0,
            audit_trail=[AuditEntry(1000.0, None, "pending", "created", "test")],
            metadata={"key": "value"},
        )
        d = g.to_dict()
        restored = Goal.from_dict(d)
        assert restored.id == g.id
        assert restored.type == g.type
        assert restored.deadline == g.deadline
        assert len(restored.audit_trail) == 1
        assert restored.metadata == g.metadata


class TestCreateGoal:
    def test_basic(self):
        g = create_goal(GoalType.LEARNING, "Learn something", 0.7)
        assert g.type == GoalType.LEARNING
        assert g.status == GoalStatus.PENDING
        assert g.priority == 0.7
        assert g.progress == 0.0
        assert len(g.audit_trail) == 1
        assert g.audit_trail[0].new_status == "pending"
        assert g.id.startswith("goal-")

    def test_custom_id(self):
        g = create_goal(GoalType.META, "Mission", 1.0, goal_id="goal-meta-learn")
        assert g.id == "goal-meta-learn"

    def test_priority_clamped(self):
        g = create_goal(GoalType.USER, "Over", 1.5)
        assert g.priority == 1.0

        g2 = create_goal(GoalType.USER, "Under", -0.5)
        assert g2.priority == 0.0

    def test_with_metadata(self):
        g = create_goal(
            GoalType.LEARNING, "Continue", 0.9,
            metadata={"teacher_priority": 1, "file_id": "abc"},
        )
        assert g.metadata["teacher_priority"] == 1

    def test_with_parent(self):
        g = create_goal(
            GoalType.MAINTENANCE, "RAM > 20%", 0.95,
            parent_goal_id="goal-maint-health",
        )
        assert g.parent_goal_id == "goal-maint-health"


# ============================================================
# GoalStore Tests
# ============================================================

class TestGoalStoreCreate:
    def test_create_returns_id(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(GoalType.LEARNING, "Test", 0.7)
        gid = store.create(g)
        assert gid == g.id

    def test_create_and_get(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(GoalType.USER, "Physics", 0.8, created_by="user")
        store.create(g)
        retrieved = store.get(g.id)
        assert retrieved is not None
        assert retrieved.description == "Physics"

    def test_get_nonexistent(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        assert store.get("nonexistent") is None

    def test_overflow_abandons_lowest(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        # Fill up to MAX_ACTIVE_GOALS
        for i in range(MAX_ACTIVE_GOALS):
            g = create_goal(GoalType.LEARNING, f"Goal {i}", 0.5 + i * 0.01)
            store.create(g)
        assert len(store.get_active()) == MAX_ACTIVE_GOALS

        # One more should abandon the lowest
        extra = create_goal(GoalType.LEARNING, "Extra", 0.9)
        store.create(extra)
        active = store.get_active()
        assert len(active) == MAX_ACTIVE_GOALS


class TestGoalStorePropose:
    def test_propose_basic(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(GoalType.USER, "Astronomy", 0.7, created_by="consciousness")
        gid = store.propose(g)
        assert gid is not None
        assert store.get(gid).status == GoalStatus.PROPOSED

    def test_propose_max_limit(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        for i in range(MAX_PROPOSED_GOALS):
            g = create_goal(GoalType.USER, f"Proposed {i}", 0.5)
            assert store.propose(g) is not None

        # Fourth should be rejected
        overflow = create_goal(GoalType.USER, "Too many", 0.5)
        assert store.propose(overflow) is None

    def test_proposed_not_in_active(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(GoalType.USER, "Proposed", 0.7)
        store.propose(g)
        assert len(store.get_active()) == 0
        assert len(store.get_proposed()) == 1


class TestGoalStoreConfirmReject:
    def test_confirm(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(GoalType.USER, "Confirm me", 0.7)
        store.propose(g)
        assert store.confirm(g.id) is True
        assert store.get(g.id).status == GoalStatus.PENDING
        # Check audit trail
        trail = store.get(g.id).audit_trail
        assert trail[-1].reason == "user confirmed"
        assert trail[-1].actor == "user"

    def test_confirm_non_proposed(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(GoalType.USER, "Active", 0.7, status=GoalStatus.ACTIVE)
        store.create(g)
        assert store.confirm(g.id) is False

    def test_reject(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(GoalType.USER, "Reject me", 0.7)
        store.propose(g)
        assert store.reject(g.id) is True
        assert store.get(g.id).status == GoalStatus.ABANDONED

    def test_reject_non_proposed(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        assert store.reject("nonexistent") is False


class TestGoalStoreUpdateStatus:
    def test_basic(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(GoalType.LEARNING, "Test", 0.7)
        store.create(g)
        assert store.update_status(g.id, GoalStatus.ACTIVE, "started", "teacher")
        assert store.get(g.id).status == GoalStatus.ACTIVE

    def test_audit_trail(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(GoalType.LEARNING, "Test", 0.7)
        store.create(g)
        store.update_status(g.id, GoalStatus.ACTIVE, "started", "teacher")
        store.update_status(g.id, GoalStatus.FAILED, "exam failed", "teacher")

        trail = store.get(g.id).audit_trail
        assert len(trail) == 3  # created + started + failed
        assert trail[-1].old_status == "active"
        assert trail[-1].new_status == "failed"

    def test_nonexistent(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        assert store.update_status("nope", GoalStatus.ACTIVE, "x", "x") is False


class TestGoalStoreUpdateProgress:
    def test_basic(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(GoalType.LEARNING, "Test", 0.7, status=GoalStatus.ACTIVE)
        store.create(g)
        assert store.update_progress(g.id, 0.5)
        assert store.get(g.id).progress == 0.5

    def test_auto_achieved(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(GoalType.LEARNING, "Test", 0.7, status=GoalStatus.ACTIVE)
        store.create(g)
        store.update_progress(g.id, 1.0)
        assert store.get(g.id).status == GoalStatus.ACHIEVED

    def test_maintenance_never_auto_achieved(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(GoalType.MAINTENANCE, "Health", 1.0, status=GoalStatus.ACTIVE,
                        goal_id="goal-maint-health")
        store.create(g)
        store.update_progress(g.id, 1.0)
        # MAINTENANCE stays ACTIVE
        assert store.get(g.id).status == GoalStatus.ACTIVE
        assert store.get(g.id).progress == 1.0

    def test_clamped(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(GoalType.LEARNING, "Test", 0.7, status=GoalStatus.ACTIVE)
        store.create(g)
        store.update_progress(g.id, 1.5)
        assert store.get(g.id).progress == 1.0

        store.update_progress(g.id, -0.5)
        # Already achieved from 1.5, but if we ignore that:
        # Progress is clamped to 0.0

    def test_nonexistent(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        assert store.update_progress("nope", 0.5) is False


class TestGoalStoreGetActive:
    def test_empty(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        assert store.get_active() == []

    def test_filter_by_type(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        store.create(create_goal(GoalType.LEARNING, "L1", 0.7))
        store.create(create_goal(GoalType.USER, "U1", 0.8, created_by="user"))
        store.create(create_goal(GoalType.MAINTENANCE, "M1", 1.0, status=GoalStatus.ACTIVE))

        learning = store.get_active(GoalType.LEARNING)
        assert len(learning) == 1
        assert learning[0].type == GoalType.LEARNING

    def test_sorted_by_priority(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        store.create(create_goal(GoalType.LEARNING, "Low", 0.3))
        store.create(create_goal(GoalType.LEARNING, "High", 0.9))
        store.create(create_goal(GoalType.LEARNING, "Mid", 0.6))

        active = store.get_active()
        priorities = [g.priority for g in active]
        assert priorities == sorted(priorities, reverse=True)

    def test_excludes_terminal(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(GoalType.LEARNING, "Done", 0.7, status=GoalStatus.ACTIVE)
        store.create(g)
        store.update_status(g.id, GoalStatus.ACHIEVED, "done", "system")
        assert len(store.get_active()) == 0


class TestGoalStoreChildren:
    def test_get_children(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        parent = create_goal(GoalType.MAINTENANCE, "Health", 1.0,
                            status=GoalStatus.ACTIVE, goal_id="parent")
        store.create(parent)
        child1 = create_goal(GoalType.MAINTENANCE, "RAM", 0.95,
                            status=GoalStatus.ACTIVE, parent_goal_id="parent")
        child2 = create_goal(GoalType.MAINTENANCE, "CPU", 0.95,
                            status=GoalStatus.ACTIVE, parent_goal_id="parent")
        store.create(child1)
        store.create(child2)

        children = store.get_children("parent")
        assert len(children) == 2


class TestGoalStoreCleanup:
    def test_abandon_lowest(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        store.create(create_goal(GoalType.LEARNING, "High", 0.9))
        store.create(create_goal(GoalType.LEARNING, "Low", 0.3))
        store.create(create_goal(GoalType.LEARNING, "Mid", 0.6))

        abandoned_id = store.abandon_lowest()
        assert abandoned_id is not None
        goal = store.get(abandoned_id)
        assert goal.status == GoalStatus.ABANDONED
        assert goal.priority == 0.3

    def test_abandon_lowest_empty(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        assert store.abandon_lowest() is None

    def test_expire_proposed(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        # Old proposed goal (73h ago, past 72h timeout)
        old = create_goal(GoalType.USER, "Old", 0.5, created_by="consciousness")
        old.created_at = time.time() - 73 * 3600
        store.propose(old)

        # Fresh proposed goal
        fresh = create_goal(GoalType.USER, "Fresh", 0.5, created_by="consciousness")
        store.propose(fresh)

        expired = store.expire_proposed()
        assert expired == 1
        assert store.get(old.id).status == GoalStatus.ABANDONED
        assert store.get(fresh.id).status == GoalStatus.PROPOSED

    def test_reset_maintenance(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        m = create_goal(GoalType.MAINTENANCE, "Health", 1.0,
                       status=GoalStatus.ACTIVE, goal_id="maint")
        store.create(m)
        store.update_progress("maint", 0.8)
        assert store.get("maint").progress == 0.8

        count = store.reset_maintenance()
        assert count == 1
        assert store.get("maint").progress == 0.0


class TestGoalStoreSeed:
    def test_seed_creates_4_goals(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        count = store.seed_if_empty()
        assert count == 4

        # META
        meta = store.get("goal-meta-learn")
        assert meta is not None
        assert meta.type == GoalType.META
        assert meta.status == GoalStatus.ACTIVE
        assert meta.priority == 1.0

        # MAINTENANCE health
        health = store.get("goal-maint-health")
        assert health is not None
        assert health.type == GoalType.MAINTENANCE
        assert health.metadata["metric"] == "health_score"

        # MAINTENANCE sub-goals
        ram = store.get("goal-maint-ram")
        assert ram is not None
        assert ram.parent_goal_id == "goal-maint-health"

        cpu = store.get("goal-maint-cpu")
        assert cpu is not None
        assert cpu.parent_goal_id == "goal-maint-health"

    def test_seed_idempotent(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        store.seed_if_empty()
        count = store.seed_if_empty()
        assert count == 0  # Already populated


class TestGoalStorePersistence:
    def test_save_and_load(self, tmp_path):
        path = tmp_path / "goals.jsonl"
        store = GoalStore(path)
        g = create_goal(GoalType.LEARNING, "Persist me", 0.7)
        store.create(g)
        store.save()

        # Load in new store
        store2 = GoalStore(path)
        store2.load()
        restored = store2.get(g.id)
        assert restored is not None
        assert restored.description == "Persist me"
        assert restored.priority == 0.7
        assert len(restored.audit_trail) == 1

    def test_append_only(self, tmp_path):
        path = tmp_path / "goals.jsonl"
        store = GoalStore(path)
        g = create_goal(GoalType.LEARNING, "Test", 0.7, goal_id="g1")
        store.create(g)
        store.save()

        # Update and save again
        store.update_status("g1", GoalStatus.ACTIVE, "started", "teacher")
        store.save()

        # File should have 2 lines (append)
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2

        # Last record wins
        store2 = GoalStore(path)
        store2.load()
        assert store2.get("g1").status == GoalStatus.ACTIVE

    def test_load_empty_file(self, tmp_path):
        path = tmp_path / "goals.jsonl"
        path.write_text("")
        store = GoalStore(path)
        store.load()
        assert store.get_all() == []

    def test_load_nonexistent(self, tmp_path):
        store = GoalStore(tmp_path / "nonexistent.jsonl")
        store.load()  # Should not raise
        assert store.get_all() == []

    def test_load_corrupt_line(self, tmp_path):
        path = tmp_path / "goals.jsonl"
        g = create_goal(GoalType.LEARNING, "Good", 0.7, goal_id="good")
        good_line = json.dumps(g.to_dict())
        path.write_text(f"{good_line}\n{{bad json\n{good_line}\n")

        store = GoalStore(path)
        store.load()
        # Should have loaded the good line, skipped bad
        assert store.get("good") is not None

    def test_seed_then_persist(self, tmp_path):
        path = tmp_path / "goals.jsonl"
        store = GoalStore(path)
        store.seed_if_empty()
        store.save()

        store2 = GoalStore(path)
        store2.load()
        assert store2.get("goal-meta-learn") is not None
        assert store2.get("goal-maint-health") is not None
        assert store2.get("goal-maint-ram") is not None
        assert store2.get("goal-maint-cpu") is not None


class TestGoalStoreStats:
    def test_empty(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        s = store.stats()
        assert s["total"] == 0
        assert s["active"] == 0

    def test_with_goals(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        store.seed_if_empty()
        s = store.stats()
        assert s["total"] == 4
        assert s["active"] == 4
        assert s["by_type"]["meta"] == 1
        assert s["by_type"]["maintenance"] == 3


class TestGoalStoreE2E:
    """End-to-end lifecycle test."""

    def test_full_lifecycle(self, tmp_path):
        path = tmp_path / "goals.jsonl"
        store = GoalStore(path)
        store.seed_if_empty()

        # Teacher creates a learning goal
        learning = create_goal(
            GoalType.LEARNING,
            "Kontynuuj nauke: quantum.txt (3/8 chunkow)",
            0.9,
            status=GoalStatus.ACTIVE,
            created_by="teacher",
            metadata={"teacher_priority": 1, "file_id": "quantum.txt",
                      "chunks_done": 3, "chunks_total": 8},
        )
        store.create(learning)

        # Progress updates
        store.update_progress(learning.id, 0.5)
        assert store.get(learning.id).progress == 0.5

        # Complete
        store.update_progress(learning.id, 1.0)
        assert store.get(learning.id).status == GoalStatus.ACHIEVED

        # Save and reload
        store.save()
        store2 = GoalStore(path)
        store2.load()
        assert store2.get(learning.id).status == GoalStatus.ACHIEVED

    def test_proposed_confirm_flow(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")

        # Maria proposes a goal
        proposed = create_goal(
            GoalType.USER,
            "Poglebic wiedze o astronomii",
            0.7,
            created_by="consciousness",
            metadata={"source_message": "Chcialbym wiedziec wiecej o astronomii",
                      "confidence": 0.8},
        )
        gid = store.propose(proposed)
        assert gid is not None
        assert store.get(gid).status == GoalStatus.PROPOSED

        # Not in active goals (PROPOSED isolation)
        assert len(store.get_active()) == 0

        # User confirms
        store.confirm(gid)
        assert store.get(gid).status == GoalStatus.PENDING

        # Now it's in active goals
        assert len(store.get_active()) == 1

    def test_proposed_reject_flow(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        proposed = create_goal(GoalType.USER, "Nope", 0.5, created_by="consciousness")
        gid = store.propose(proposed)
        store.reject(gid)
        assert store.get(gid).status == GoalStatus.ABANDONED
        assert len(store.get_active()) == 0
        assert len(store.get_proposed()) == 0


# ============================================================
# CDL Feedback Loop: outcome + find_by_topic
# ============================================================


class TestGoalOutcome:
    def test_outcome_default_none(self):
        g = create_goal(GoalType.LEARNING, "test", 0.5)
        assert g.outcome is None

    def test_outcome_serialization(self):
        g = create_goal(GoalType.LEARNING, "Nauka: fizyka", 0.8)
        g.outcome = {"chunks_learned": 5, "final_score": 0.85}
        d = g.to_dict()
        assert d["outcome"] == {"chunks_learned": 5, "final_score": 0.85}
        restored = Goal.from_dict(d)
        assert restored.outcome["final_score"] == 0.85

    def test_outcome_backward_compat(self):
        """Old goal records without outcome load fine."""
        d = {
            "id": "goal-old", "type": "learning",
            "description": "old goal", "priority": 0.5,
            "status": "pending", "progress": 0.0,
            "created_by": "system", "created_at": 0.0, "updated_at": 0.0,
        }
        g = Goal.from_dict(d)
        assert g.outcome is None

    def test_set_outcome(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(GoalType.LEARNING, "test", 0.5)
        store.create(g)
        ok = store.set_outcome(g.id, {"score": 0.9})
        assert ok is True
        assert store.get(g.id).outcome == {"score": 0.9}

    def test_set_outcome_nonexistent(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        assert store.set_outcome("fake-id", {}) is False


class TestFindByTopic:
    def test_find_by_topic_exact(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(
            GoalType.LEARNING, "Nauka: genetyka", 0.8,
            metadata={"topic": "genetyka", "topics": ["genetyka"]},
        )
        store.create(g)
        results = store.find_by_topic("genetyka")
        assert len(results) == 1
        assert results[0].id == g.id

    def test_find_by_topic_substring(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(
            GoalType.LEARNING, "Nauka: fizyka kwantowa", 0.8,
            metadata={"topic": "fizyka kwantowa"},
        )
        store.create(g)
        results = store.find_by_topic("fizyka")
        assert len(results) == 1

    def test_find_by_topic_case_insensitive(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(
            GoalType.LEARNING, "Nauka: Python", 0.8,
            metadata={"topic": "Python"},
        )
        store.create(g)
        results = store.find_by_topic("python")
        assert len(results) == 1

    def test_find_by_topic_no_match(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(
            GoalType.LEARNING, "Nauka: fizyka", 0.8,
            metadata={"topic": "fizyka"},
        )
        store.create(g)
        results = store.find_by_topic("chemia")
        assert len(results) == 0

    def test_find_by_topic_only_learning_goals(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g1 = create_goal(GoalType.MAINTENANCE, "Maintenance fizyka", 0.5)
        g2 = create_goal(
            GoalType.LEARNING, "Nauka: fizyka", 0.8,
            metadata={"topic": "fizyka"},
        )
        store.create(g1)
        store.create(g2)
        results = store.find_by_topic("fizyka")
        assert len(results) == 1
        assert results[0].type == GoalType.LEARNING

    def test_find_by_topic_description_fallback(self, tmp_path):
        """Finds by description if no topic in metadata."""
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(GoalType.LEARNING, "Nauka: biologia", 0.8)
        store.create(g)
        results = store.find_by_topic("biologia")
        assert len(results) == 1


# ============================================================
# Auto-confirm Tests
# ============================================================

class TestGoalStoreAutoConfirm:
    def test_auto_confirm_creative_learning(self, tmp_path):
        """Creative low-risk learning goals are auto-confirmed."""
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(
            GoalType.LEARNING, "Nauka fizyki", 0.6,
            created_by="creative",
            metadata={"risk_level": "low"},
        )
        gid = store.propose(g)
        assert gid is not None
        goal = store.get(gid)
        assert goal.status == GoalStatus.PENDING
        assert goal.audit_trail[-1].reason == "auto-confirmed (low risk)"

    def test_auto_confirm_critic_meta(self, tmp_path):
        """Critic meta goals are auto-confirmed."""
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(
            GoalType.META, "Verify knowledge", 0.5,
            created_by="critic",
        )
        gid = store.propose(g)
        goal = store.get(gid)
        assert goal.status == GoalStatus.PENDING

    def test_auto_confirm_self_analysis(self, tmp_path):
        """Self-analysis goals are auto-confirmed."""
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(
            GoalType.LEARNING, "Improve retention", 0.5,
            created_by="self_analysis",
        )
        gid = store.propose(g)
        goal = store.get(gid)
        assert goal.status == GoalStatus.PENDING

    def test_no_auto_confirm_high_risk(self, tmp_path):
        """High risk goals still require approval."""
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(
            GoalType.LEARNING, "Risky experiment", 0.5,
            created_by="creative",
            metadata={"risk_level": "high"},
        )
        gid = store.propose(g)
        goal = store.get(gid)
        assert goal.status == GoalStatus.PROPOSED

    def test_no_auto_confirm_medium_risk(self, tmp_path):
        """Medium risk goals still require approval."""
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(
            GoalType.LEARNING, "Medium risk", 0.5,
            created_by="creative",
            metadata={"risk_level": "medium"},
        )
        gid = store.propose(g)
        goal = store.get(gid)
        assert goal.status == GoalStatus.PROPOSED

    def test_no_auto_confirm_unknown_source(self, tmp_path):
        """Goals from unknown sources require approval."""
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(
            GoalType.LEARNING, "From user", 0.5,
            created_by="user",
        )
        gid = store.propose(g)
        goal = store.get(gid)
        assert goal.status == GoalStatus.PROPOSED

    def test_no_auto_confirm_experiment_type(self, tmp_path):
        """Maintenance/experiment goals require approval even from safe sources."""
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(
            GoalType.MAINTENANCE, "Tune params", 0.5,
            created_by="creative",
        )
        gid = store.propose(g)
        goal = store.get(gid)
        assert goal.status == GoalStatus.PROPOSED

    def test_auto_confirm_default_risk(self, tmp_path):
        """No risk_level in metadata defaults to low (auto-confirm)."""
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(
            GoalType.LEARNING, "Default risk", 0.5,
            created_by="creative",
        )
        gid = store.propose(g)
        goal = store.get(gid)
        assert goal.status == GoalStatus.PENDING
