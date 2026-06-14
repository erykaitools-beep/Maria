"""Concurrency / cross-instance safety for GoalStore + BulletinStore (R2 2026-05-28).

Root cause fixed: the Web UI creates its own store instance per request in the
SAME process as the daemon. The daemon's long-lived cache + compact() (full
rewrite) silently overwrote records the UI appended. Fix: class-level lock
(shared across instances in-process) + merge-from-disk before compact + atomic
temp-file writes.

The *_preserves_external_append / *_status_change tests fail on the pre-fix code
(compact rewrote only the daemon's stale cache).
"""

import threading

from agent_core.goals.store import GoalStore
from agent_core.goals.goal_model import create_goal, GoalType, GoalStatus
from agent_core.bulletin.bulletin_store import BulletinStore
from agent_core.bulletin.bulletin_model import EntryType


def _goal(gid: str, status: GoalStatus = GoalStatus.PENDING):
    return create_goal(
        goal_type=GoalType.LEARNING,
        description=f"desc {gid}",
        priority=0.5,
        status=status,
        created_by="test",
        goal_id=gid,
    )


# ---- GoalStore ----------------------------------------------------------


def test_goalstore_lock_is_shared_across_instances(tmp_path):
    a = GoalStore(tmp_path / "g.jsonl")
    b = GoalStore(tmp_path / "g.jsonl")
    assert a._io_lock is b._io_lock is GoalStore._io_lock


def test_goalstore_compact_preserves_external_append(tmp_path):
    path = tmp_path / "goals.jsonl"

    daemon = GoalStore(path)
    daemon.load()
    daemon.create(_goal("g1"))
    daemon.save()

    # Web UI: a fresh instance appends another goal.
    ui = GoalStore(path)
    ui.load()
    ui.create(_goal("g2"))
    ui.save()

    # Daemon compacts from its stale cache -> must not drop the UI's goal.
    daemon.compact()

    reloaded = GoalStore(path)
    reloaded.load()
    ids = {g.id for g in reloaded.get_all()}
    assert ids == {"g1", "g2"}


def test_goalstore_compact_preserves_external_status_change(tmp_path):
    path = tmp_path / "goals.jsonl"

    daemon = GoalStore(path)
    daemon.load()
    daemon.create(_goal("g1", status=GoalStatus.ACTIVE))
    daemon.save()

    # Web UI rejects the goal (newer updated_at).
    ui = GoalStore(path)
    ui.load()
    ui.update_status("g1", GoalStatus.ABANDONED, "user rejected", "user")
    ui.save()

    daemon.compact()

    reloaded = GoalStore(path)
    reloaded.load()
    assert reloaded.get("g1").status == GoalStatus.ABANDONED
    # merge also refreshes the daemon's own cache
    assert daemon.get("g1").status == GoalStatus.ABANDONED


def test_goalstore_concurrent_access_no_crash(tmp_path):
    store = GoalStore(tmp_path / "goals.jsonl")
    store.load()
    errors = []

    def writer(n):
        try:
            for i in range(10):
                store.create(_goal(f"g-{n}-{i}"))
        except Exception as e:  # pragma: no cover - failure path
            errors.append(e)

    def reader():
        try:
            for _ in range(50):
                store.get_active()
                store.stats()
                store.get_all()
        except Exception as e:  # pragma: no cover - failure path
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(5)]
    threads += [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent access raised: {errors}"
    assert len(store.get_all()) == 50  # 5 writers * 10, none lost


# ---- BulletinStore ------------------------------------------------------


def test_bulletinstore_lock_is_shared_across_instances(tmp_path):
    a = BulletinStore(path=tmp_path / "b.jsonl")
    b = BulletinStore(path=tmp_path / "b.jsonl")
    assert a._io_lock is b._io_lock is BulletinStore._io_lock


def test_bulletinstore_compact_preserves_external_append_atomically(tmp_path):
    path = tmp_path / "bulletin.jsonl"

    daemon = BulletinStore(path=path)
    daemon.create_and_post(EntryType.IMPROVEMENT, "topic-a", "rc", "sum a", "test")

    # Web UI instance appends a different entry.
    ui = BulletinStore(path=path)
    ui.create_and_post(EntryType.IMPROVEMENT, "topic-b", "rc", "sum b", "test")

    daemon.compact()

    reloaded = BulletinStore(path=path)
    topics = {e.topic for e in reloaded.get_open()}
    assert topics == {"topic-a", "topic-b"}
    # atomic write leaves no temp file behind
    assert not (tmp_path / "bulletin.jsonl.tmp").exists()
