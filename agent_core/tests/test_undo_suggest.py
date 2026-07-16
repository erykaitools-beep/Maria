"""Tests for the autonomous effector-undo SUGGEST side (agent_core/undo_suggest).

Covers: detector (orphaned reversible action rule), suggestion_creator (gate +
STOP-AT-PENDING task + bulletin + notify + drill bypass), monitor (flag gate +
scan), expiry (PENDING/BLOCKED sweep). Mirrors the self-repair test style: real
Conductor + BulletinStore + EffectorUndoJournal, fake SelfPerception/GoalStore/
Notifier.
"""

import time

import pytest

from agent_core.bulletin.bulletin_store import BulletinStore
from agent_core.conductor import Conductor, TaskQueue
from agent_core.conductor.task_model import Assignee, TaskStatus, create_task
from agent_core.effector.undo_journal import EffectorUndoJournal
from agent_core.goals.goal_model import GoalStatus
from agent_core.undo_suggest.detector import (
    SUGGEST_COOLDOWN_SECONDS,
    detect_orphaned_reversible_actions,
)
from agent_core.undo_suggest.suggestion_creator import (
    UNDO_SUGGEST_PHASE,
    UndoSuggestionCandidate,
    UndoSuggestionCreator,
)
from agent_core.undo_suggest.monitor import UndoSuggestionMonitor
from agent_core.undo_suggest.expiry import expire_stale_undo_suggestions


# --- fakes -----------------------------------------------------------------

class FakeGoal:
    def __init__(self, status):
        self.status = status


class FakeGoalStore:
    def __init__(self, mapping=None):
        self._m = mapping or {}

    def get(self, goal_id):
        return self._m.get(goal_id)


class FakeSelfPerception:
    def __init__(self, snapshot=None, fresh=True):
        self.snapshot = snapshot or {"snapshot_id": "sps-test", "mode": "ACTIVE"}
        self.fresh = fresh
        self.snapshots_taken = 0

    def get_latest(self):
        return self.snapshot

    def is_fresh(self, max_age_seconds=300):
        return self.fresh

    def take_snapshot(self):
        self.snapshots_taken += 1
        return self.snapshot


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def send_raw(self, text, parse_mode=None):
        self.messages.append(text)
        return True


def _journal_with_orphan(tmp_path, goal_id="g1", path="/tmp/x.txt"):
    """A journal holding one RECORDED, auto-undoable write linked to goal_id.

    Recorded with an aged created_at so it clears the detector's MIN_RECORD_AGE
    guard (the action has settled, not still in its retry window)."""
    journal = EffectorUndoJournal(path=tmp_path / "undo_journal.jsonl")
    rec = journal.record_action(
        tool="write",
        args={"path": path, "content": "new"},
        read_fn=lambda p: "prior content",  # prior file existed -> restore invoke
        metadata={"goal_id": goal_id, "source": "planner"},
        now=time.time() - 300,  # older than MIN_RECORD_AGE_SECONDS (120)
    )
    return journal, rec


def _no_cooldown(_record_id):
    return False


# --- detector --------------------------------------------------------------

def test_record_action_carries_goal_metadata(tmp_path):
    """The journal threads goal_id provenance the detector needs."""
    journal, rec = _journal_with_orphan(tmp_path)
    stored = journal.get(rec.record_id)
    assert stored.metadata.get("goal_id") == "g1"
    assert stored.metadata.get("source") == "planner"
    assert stored.inverse.get("kind") == "invoke"


def test_detect_orphaned_write_failed_goal(tmp_path):
    journal, rec = _journal_with_orphan(tmp_path, goal_id="g1")
    goals = FakeGoalStore({"g1": FakeGoal(GoalStatus.FAILED)})

    candidates = detect_orphaned_reversible_actions(journal, goals, _no_cooldown)

    assert len(candidates) == 1
    c = candidates[0]
    assert c.undo_record_id == rec.record_id
    assert c.goal_id == "g1"
    assert c.evidence_summary["goal_status"] == "failed"
    assert c.evidence_summary["path"] == "/tmp/x.txt"


def test_detect_orphaned_write_abandoned_goal(tmp_path):
    journal, _ = _journal_with_orphan(tmp_path, goal_id="g1")
    goals = FakeGoalStore({"g1": FakeGoal(GoalStatus.ABANDONED)})
    assert len(detect_orphaned_reversible_actions(journal, goals, _no_cooldown)) == 1


def test_no_candidate_when_goal_achieved(tmp_path):
    journal, _ = _journal_with_orphan(tmp_path, goal_id="g1")
    goals = FakeGoalStore({"g1": FakeGoal(GoalStatus.ACHIEVED)})
    assert detect_orphaned_reversible_actions(journal, goals, _no_cooldown) == []


def test_no_candidate_when_goal_still_active(tmp_path):
    journal, _ = _journal_with_orphan(tmp_path, goal_id="g1")
    goals = FakeGoalStore({"g1": FakeGoal(GoalStatus.ACTIVE)})
    assert detect_orphaned_reversible_actions(journal, goals, _no_cooldown) == []


def test_no_candidate_when_goal_unknown(tmp_path):
    journal, _ = _journal_with_orphan(tmp_path, goal_id="g1")
    goals = FakeGoalStore({})  # goal not found
    assert detect_orphaned_reversible_actions(journal, goals, _no_cooldown) == []


def test_no_candidate_without_goal_link(tmp_path):
    journal = EffectorUndoJournal(path=tmp_path / "j.jsonl")
    journal.record_action(
        tool="write", args={"path": "/x"}, read_fn=lambda p: "old",
        metadata={"source": "/do"},  # no goal_id
        now=time.time() - 300,
    )
    goals = FakeGoalStore({})
    assert detect_orphaned_reversible_actions(journal, goals, _no_cooldown) == []


def test_no_candidate_for_too_young_record(tmp_path):
    """Review F5: an action still inside its retry envelope is too young to judge."""
    journal = EffectorUndoJournal(path=tmp_path / "j.jsonl")
    journal.record_action(
        tool="write", args={"path": "/x"}, read_fn=lambda p: "old",
        metadata={"goal_id": "g1"},  # created_at = now -> young
    )
    goals = FakeGoalStore({"g1": FakeGoal(GoalStatus.FAILED)})
    assert detect_orphaned_reversible_actions(journal, goals, _no_cooldown) == []


def test_no_candidate_for_noop_inverse(tmp_path):
    """A read-only action is RECORDED but its inverse is a noop -- nothing to undo."""
    journal = EffectorUndoJournal(path=tmp_path / "j.jsonl")
    journal.record_action(
        tool="read", args={"path": "/x"}, metadata={"goal_id": "g1"},
    )
    goals = FakeGoalStore({"g1": FakeGoal(GoalStatus.FAILED)})
    assert detect_orphaned_reversible_actions(journal, goals, _no_cooldown) == []


def test_no_candidate_for_irreversible(tmp_path):
    """An exec action is IRREVERSIBLE -> never offered, even for a failed goal."""
    journal = EffectorUndoJournal(path=tmp_path / "j.jsonl")
    journal.record_action(
        tool="exec", args={"argv": ["echo", "hi"]}, metadata={"goal_id": "g1"},
    )
    goals = FakeGoalStore({"g1": FakeGoal(GoalStatus.FAILED)})
    assert detect_orphaned_reversible_actions(journal, goals, _no_cooldown) == []


def test_no_candidate_when_already_undone(tmp_path):
    journal, rec = _journal_with_orphan(tmp_path, goal_id="g1")
    journal.mark_undone(rec.record_id, ok=True, detail="done")
    goals = FakeGoalStore({"g1": FakeGoal(GoalStatus.FAILED)})
    assert detect_orphaned_reversible_actions(journal, goals, _no_cooldown) == []


def test_cooldown_suppresses_candidate(tmp_path):
    journal, _ = _journal_with_orphan(tmp_path, goal_id="g1")
    goals = FakeGoalStore({"g1": FakeGoal(GoalStatus.FAILED)})
    assert detect_orphaned_reversible_actions(
        journal, goals, lambda rid: True
    ) == []


# --- suggestion_creator ----------------------------------------------------

def _candidate(record_id="eundo-abc12345", path="/tmp/x.txt", drill=False):
    return UndoSuggestionCandidate(
        undo_record_id=record_id,
        tool="write",
        goal_id="g1",
        summary=f"write for goal g1 (failed) -- propose undo of {path}",
        evidence_summary={
            "undo_record_id": record_id, "tool": "write", "path": path,
            "goal_id": "g1", "goal_status": "failed", "inverse_note": "restore",
            "one_line": "write /tmp/x.txt -- goal g1 failed", "drill": drill,
        },
        detected_at=time.time(),
    )


def _creator(tmp_path, fresh=True, mode="ACTIVE"):
    conductor = Conductor(queue=TaskQueue(path=tmp_path / "maria_task_queue.jsonl"))
    bulletin = BulletinStore(path=tmp_path / "bulletin.jsonl")
    notifier = FakeNotifier()
    sp = FakeSelfPerception({"snapshot_id": "sps-1", "mode": mode}, fresh=fresh)
    creator = UndoSuggestionCreator(
        conductor=conductor, bulletin_store=bulletin,
        notifier=notifier, self_perception=sp,
    )
    return creator, conductor, bulletin, notifier


def test_creator_happy_path(tmp_path):
    creator, conductor, bulletin, notifier = _creator(tmp_path)

    task_id = creator.create(_candidate(), "sps-1")

    assert task_id is not None
    task = conductor.list_tasks(project="maria")[0]
    assert task.status == TaskStatus.PENDING
    assert task.phase == UNDO_SUGGEST_PHASE
    assert task.assignee == Assignee.OPERATOR  # never a builder -> never dispatched
    assert task.artifacts["approval_required"] is True
    assert task.artifacts["undo_record_id"] == "eundo-abc12345"
    assert task.artifacts["goal_id"] == "g1"
    assert time.time() + 86000 <= task.artifacts["expires_at"] <= time.time() + 86500
    assert bulletin.get_open()
    assert notifier.messages
    assert "/approve_undo" in notifier.messages[0]


def test_creator_gate_refuses_stale_snapshot(tmp_path):
    creator, conductor, bulletin, notifier = _creator(tmp_path, fresh=False)
    assert creator.create(_candidate(), "sps-1") is None
    assert conductor.list_tasks(project="maria") == []
    assert bulletin.get_open() == []
    assert notifier.messages == []


def test_creator_gate_refuses_sleep_mode(tmp_path):
    creator, conductor, _, _ = _creator(tmp_path, mode="SLEEP")
    assert creator.create(_candidate(), "sps-1") is None
    assert conductor.list_tasks(project="maria") == []


def test_creator_gate_refuses_cooldown(tmp_path):
    creator, conductor, _, _ = _creator(tmp_path)
    existing = create_task(
        project="maria", phase=UNDO_SUGGEST_PHASE, title="Existing",
        description="", assignee=Assignee.OPERATOR,
    )
    existing.artifacts = {"undo_record_id": "eundo-abc12345"}
    conductor.add_task(existing)

    assert creator.create(_candidate(), "sps-1") is None
    assert len(conductor.list_tasks(project="maria")) == 1


def test_cooldown_open_task_blocks_past_old_window(tmp_path):
    """Review F1/F2: an OPEN proposal OLDER than the former 4h window STILL blocks a
    duplicate -- the cooldown is keyed on open/closed state, not age."""
    creator, conductor, _, _ = _creator(tmp_path)
    old = create_task(
        project="maria", phase=UNDO_SUGGEST_PHASE, title="Old open",
        description="", assignee=Assignee.OPERATOR,
    )
    old.artifacts = {"undo_record_id": "eundo-abc12345"}
    old.created_at = time.time() - 5 * 3600  # older than SUGGEST_COOLDOWN_SECONDS
    conductor.add_task(old)

    assert creator.create(_candidate(), "sps-1") is None
    assert len(conductor.list_tasks(project="maria")) == 1


def test_cooldown_recent_terminal_blocks(tmp_path):
    """A just-closed proposal holds a short back-off (no instant re-nag)."""
    creator, conductor, _, _ = _creator(tmp_path)
    cancelled = create_task(
        project="maria", phase=UNDO_SUGGEST_PHASE, title="Recent",
        description="", assignee=Assignee.OPERATOR,
    )
    cancelled.artifacts = {"undo_record_id": "eundo-abc12345"}
    cancelled.status = TaskStatus.CANCELLED
    cancelled.completed_at = time.time()  # just closed
    conductor.add_task(cancelled)

    assert creator.create(_candidate(), "sps-1") is None


def test_cooldown_old_terminal_allows_fresh(tmp_path):
    """An OLD terminal (DONE/CANCELLED) proposal does NOT block a fresh proposal
    if the action genuinely recurs after the back-off elapses."""
    creator, conductor, _, _ = _creator(tmp_path)
    done = create_task(
        project="maria", phase=UNDO_SUGGEST_PHASE, title="Old done",
        description="", assignee=Assignee.OPERATOR,
    )
    done.artifacts = {"undo_record_id": "eundo-abc12345"}
    done.status = TaskStatus.DONE
    done.completed_at = time.time() - SUGGEST_COOLDOWN_SECONDS - 1
    conductor.add_task(done)

    assert creator.create(_candidate(), "sps-1") is not None


def test_creator_bypass_gate_drill(tmp_path):
    """bypass_gate (drill) creates despite a stale snapshot; still approval-gated."""
    creator, conductor, bulletin, notifier = _creator(tmp_path, fresh=False)
    assert creator.create(_candidate(drill=True), "drill") is None
    task_id = creator.create(_candidate(drill=True), "drill", bypass_gate=True)
    assert task_id is not None
    task = conductor.list_tasks(project="maria")[0]
    assert task.artifacts["approval_required"] is True
    assert task.artifacts["drill"] is True
    assert bulletin.get_open()
    assert notifier.messages


# --- monitor ---------------------------------------------------------------

def test_monitor_flag_off_is_noop(tmp_path, monkeypatch):
    monkeypatch.delenv("EFFECTOR_UNDO_SUGGEST_ENABLED", raising=False)
    journal, _ = _journal_with_orphan(tmp_path, goal_id="g1")
    goals = FakeGoalStore({"g1": FakeGoal(GoalStatus.FAILED)})
    creator, conductor, _, _ = _creator(tmp_path)
    monitor = UndoSuggestionMonitor(
        FakeSelfPerception(), conductor, journal, goals, creator
    )
    assert monitor.scan_and_create() == []
    assert conductor.list_tasks(project="maria") == []


def test_monitor_flag_on_creates_suggestion(tmp_path, monkeypatch):
    monkeypatch.setenv("EFFECTOR_UNDO_SUGGEST_ENABLED", "true")
    journal, rec = _journal_with_orphan(tmp_path, goal_id="g1")
    goals = FakeGoalStore({"g1": FakeGoal(GoalStatus.FAILED)})
    creator, conductor, _, notifier = _creator(tmp_path)
    sp = FakeSelfPerception({"snapshot_id": "sps-1", "mode": "ACTIVE"}, fresh=True)
    monitor = UndoSuggestionMonitor(sp, conductor, journal, goals, creator)

    created = monitor.scan_and_create()

    assert len(created) == 1
    task = conductor.list_tasks(project="maria")[0]
    assert task.artifacts["undo_record_id"] == rec.record_id
    assert sp.snapshots_taken == 1  # on-demand refresh fired (candidate present)


def test_monitor_flag_on_healthy_noop(tmp_path, monkeypatch):
    """Flag on but goal achieved -> no candidate -> no snapshot churn, no task."""
    monkeypatch.setenv("EFFECTOR_UNDO_SUGGEST_ENABLED", "1")
    journal, _ = _journal_with_orphan(tmp_path, goal_id="g1")
    goals = FakeGoalStore({"g1": FakeGoal(GoalStatus.ACHIEVED)})
    creator, conductor, _, _ = _creator(tmp_path)
    sp = FakeSelfPerception()
    monitor = UndoSuggestionMonitor(sp, conductor, journal, goals, creator)

    assert monitor.scan_and_create() == []
    assert sp.snapshots_taken == 0  # nothing fired -> no refresh
    assert conductor.list_tasks(project="maria") == []


def test_monitor_cooldown_lookup_blocks_duplicate(tmp_path, monkeypatch):
    monkeypatch.setenv("EFFECTOR_UNDO_SUGGEST_ENABLED", "on")
    journal, rec = _journal_with_orphan(tmp_path, goal_id="g1")
    goals = FakeGoalStore({"g1": FakeGoal(GoalStatus.FAILED)})
    creator, conductor, _, _ = _creator(tmp_path)
    sp = FakeSelfPerception({"snapshot_id": "sps-1", "mode": "ACTIVE"}, fresh=True)
    monitor = UndoSuggestionMonitor(sp, conductor, journal, goals, creator)

    first = monitor.scan_and_create()
    assert len(first) == 1
    # Second scan: the open proposal holds the cooldown -> no duplicate.
    second = monitor.scan_and_create()
    assert second == []
    assert len(conductor.list_tasks(project="maria")) == 1


def test_monitor_no_duplicate_after_old_cooldown_window(tmp_path, monkeypatch):
    """Review F1/F2 end-to-end: a still-PENDING proposal aged past the former 4h
    window gets NO duplicate on the next scan (cooldown holds while open)."""
    monkeypatch.setenv("EFFECTOR_UNDO_SUGGEST_ENABLED", "1")
    journal, _ = _journal_with_orphan(tmp_path, goal_id="g1")
    goals = FakeGoalStore({"g1": FakeGoal(GoalStatus.FAILED)})
    creator, conductor, _, _ = _creator(tmp_path)
    sp = FakeSelfPerception({"snapshot_id": "sps-1", "mode": "ACTIVE"}, fresh=True)
    monitor = UndoSuggestionMonitor(sp, conductor, journal, goals, creator)

    assert len(monitor.scan_and_create()) == 1
    # Age the still-PENDING proposal well past the former 4h cooldown window.
    task = conductor.get_pending_undo_suggestions()[0]
    task.created_at = time.time() - 5 * 3600
    conductor.add_task(task)

    assert monitor.scan_and_create() == []
    assert len(conductor.get_pending_undo_suggestions()) == 1


def test_monitor_sleep_no_snapshot_churn(tmp_path, monkeypatch):
    """Review F7: a standing orphan in SLEEP must NOT force a snapshot every scan."""
    monkeypatch.setenv("EFFECTOR_UNDO_SUGGEST_ENABLED", "1")
    journal, _ = _journal_with_orphan(tmp_path, goal_id="g1")
    goals = FakeGoalStore({"g1": FakeGoal(GoalStatus.FAILED)})
    creator, conductor, _, _ = _creator(tmp_path)
    sp = FakeSelfPerception({"snapshot_id": "sps-1", "mode": "SLEEP"}, fresh=True)
    monitor = UndoSuggestionMonitor(sp, conductor, journal, goals, creator)

    assert monitor.scan_and_create() == []
    assert sp.snapshots_taken == 0  # mode gate upstream of refresh -> no churn
    assert conductor.list_tasks(project="maria") == []


# --- expiry ----------------------------------------------------------------

def _open_undo_task(conductor, record_id="eundo-xyz", expires_at=None, status=None):
    task = create_task(
        project="maria", phase=UNDO_SUGGEST_PHASE, title="Undo suggestion",
        description="", assignee=Assignee.OPERATOR,
    )
    task.artifacts = {
        "undo_record_id": record_id,
        "approval_required": True,
        "expires_at": expires_at if expires_at is not None else time.time() + 86400,
    }
    if status is not None:
        task.status = status
    conductor.add_task(task)
    return task


def test_expiry_cancels_stale_pending(tmp_path):
    conductor = Conductor(queue=TaskQueue(path=tmp_path / "q.jsonl"))
    bulletin = BulletinStore(path=tmp_path / "b.jsonl")
    notifier = FakeNotifier()
    task = _open_undo_task(conductor, expires_at=time.time() - 10)

    expired = expire_stale_undo_suggestions(conductor, bulletin, notifier)

    assert task.task_id in expired
    refreshed = conductor.list_tasks(project="maria")[0]
    assert refreshed.status == TaskStatus.CANCELLED


def test_expiry_keeps_fresh_pending(tmp_path):
    conductor = Conductor(queue=TaskQueue(path=tmp_path / "q.jsonl"))
    bulletin = BulletinStore(path=tmp_path / "b.jsonl")
    _open_undo_task(conductor, expires_at=time.time() + 86400)

    assert expire_stale_undo_suggestions(conductor, bulletin, FakeNotifier()) == []
    assert conductor.list_tasks(project="maria")[0].status == TaskStatus.PENDING


def test_expiry_cleans_blocked(tmp_path):
    """A BLOCKED suggestion (failed inverse on approve) is cleaned immediately."""
    conductor = Conductor(queue=TaskQueue(path=tmp_path / "q.jsonl"))
    bulletin = BulletinStore(path=tmp_path / "b.jsonl")
    task = _open_undo_task(conductor, status=TaskStatus.BLOCKED)

    cleaned = expire_stale_undo_suggestions(conductor, bulletin, FakeNotifier())

    assert task.task_id in cleaned
    assert conductor.list_tasks(project="maria")[0].status == TaskStatus.CANCELLED


def test_expiry_ignores_other_phases(tmp_path):
    """Expiry must not touch self-repair or build tasks."""
    conductor = Conductor(queue=TaskQueue(path=tmp_path / "q.jsonl"))
    bulletin = BulletinStore(path=tmp_path / "b.jsonl")
    other = create_task(
        project="maria", phase="self_repair", title="Repair",
        description="", assignee=Assignee.CODEX,
    )
    other.artifacts = {"expires_at": time.time() - 10, "approval_required": True}
    conductor.add_task(other)

    assert expire_stale_undo_suggestions(conductor, bulletin, FakeNotifier()) == []
    assert conductor.list_tasks(project="maria")[0].status == TaskStatus.PENDING


# --- conductor STOP-AT-PENDING guard (defense in depth) --------------------

def test_conductor_never_dispatches_undo_suggestion(tmp_path):
    """phase 'effector_undo' is structurally excluded from autonomous dispatch,
    even with a builder assignee AND approval_required explicitly False -- the
    belt that backs up the approval_required + OPERATOR-assignee locks."""
    conductor = Conductor(queue=TaskQueue(path=tmp_path / "q.jsonl"))
    task = create_task(
        project="maria", phase=UNDO_SUGGEST_PHASE, title="Undo",
        description="", assignee=Assignee.CODEX,  # deliberately a builder
    )
    task.artifacts = {"approval_required": False, "undo_record_id": "eundo-x"}
    conductor.add_task(task)

    assert conductor.get_autonomous_next("maria") is None


def test_conductor_get_pending_undo_suggestions(tmp_path):
    conductor = Conductor(queue=TaskQueue(path=tmp_path / "q.jsonl"))
    undo = create_task(
        project="maria", phase=UNDO_SUGGEST_PHASE, title="Undo",
        description="", assignee=Assignee.OPERATOR,
    )
    undo.artifacts = {"undo_record_id": "eundo-x", "approval_required": True}
    conductor.add_task(undo)
    repair = create_task(
        project="maria", phase="self_repair", title="Repair",
        description="", assignee=Assignee.CODEX,
    )
    conductor.add_task(repair)

    pending = conductor.get_pending_undo_suggestions()
    assert len(pending) == 1
    assert pending[0].phase == UNDO_SUGGEST_PHASE
