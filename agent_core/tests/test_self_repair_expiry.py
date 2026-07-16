import time

from agent_core.bulletin.bulletin_model import EntryStatus, EntryType
from agent_core.bulletin.bulletin_store import BulletinStore
from agent_core.conductor import Conductor, TaskQueue
from agent_core.conductor.task_model import Assignee, TaskStatus, create_task
from agent_core.self_repair.expiry import expire_stale_repair_tasks


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def send_raw(self, text, parse_mode=None):
        self.messages.append(text)
        return True


def _conductor(tmp_path):
    return Conductor(queue=TaskQueue(path=tmp_path / "maria_task_queue.jsonl"))


def _repair_task(expires_at):
    task = create_task(
        project="maria",
        phase="self_repair",
        title="Repair",
        description="",
        assignee=Assignee.CODEX,
    )
    task.artifacts = {
        "repair_kind": "action_failure_storm",
        "approval_required": True,
        "expires_at": expires_at,
    }
    return task


def test_expiry_cancels_old_tasks(tmp_path):
    now = time.time()
    conductor = _conductor(tmp_path)
    task = conductor.add_task(_repair_task(now - 3600))

    expired = expire_stale_repair_tasks(conductor, None, None, now=now)

    assert expired == [task.task_id]
    updated = conductor.list_tasks(project="maria")[0]
    assert updated.status == TaskStatus.CANCELLED
    assert "expired_no_response" in updated.notes


def test_expiry_skips_fresh_tasks(tmp_path):
    now = time.time()
    conductor = _conductor(tmp_path)
    task = conductor.add_task(_repair_task(now + 23 * 3600))

    expired = expire_stale_repair_tasks(conductor, None, None, now=now)

    assert expired == []
    updated = conductor.list_tasks(project="maria")[0]
    assert updated.task_id == task.task_id
    assert updated.status == TaskStatus.PENDING


def test_expiry_cleans_stuck_in_progress_tasks(tmp_path):
    # Audit 2026-06-16 #18: a self_repair task stuck IN_PROGRESS past the grace
    # (e.g. daemon killed mid-flight) has no other reaper -> expiry cleans it.
    now = time.time()
    conductor = _conductor(tmp_path)
    task = _repair_task(now + 23 * 3600)  # fresh expiry; irrelevant here
    task.status = TaskStatus.IN_PROGRESS
    task.updated_at = now - (3 * 3600)  # 3h stale > 2h grace
    conductor.add_task(task)

    cleaned = expire_stale_repair_tasks(conductor, None, None, now=now)

    assert task.task_id in cleaned
    updated = conductor.list_tasks(project="maria")[0]
    assert updated.status == TaskStatus.CANCELLED
    assert "in_progress self-repair stuck" in updated.notes


def test_expiry_skips_recent_in_progress_tasks(tmp_path):
    # A recently-active IN_PROGRESS task is within grace -> left alone.
    now = time.time()
    conductor = _conductor(tmp_path)
    task = _repair_task(now + 23 * 3600)
    task.status = TaskStatus.IN_PROGRESS
    task.updated_at = now - 60  # 1 min ago
    conductor.add_task(task)

    cleaned = expire_stale_repair_tasks(conductor, None, None, now=now)

    assert task.task_id not in cleaned
    updated = conductor.list_tasks(project="maria")[0]
    assert updated.status == TaskStatus.IN_PROGRESS


def test_expiry_closes_bulletin(tmp_path):
    now = time.time()
    conductor = _conductor(tmp_path)
    task = conductor.add_task(_repair_task(now - 1))
    bulletin = BulletinStore(path=tmp_path / "bulletin.jsonl")
    entry = bulletin.create_and_post(
        entry_type=EntryType.IMPROVEMENT,
        topic="self_repair_action_failure_storm",
        reason_code="self_repair_action_failure_storm",
        summary="Self-repair created",
        requested_by="self_repair_monitor",
        metadata={"task_id": task.task_id},
    )

    expire_stale_repair_tasks(conductor, bulletin, None, now=now)

    updated = bulletin.get(entry.entry_id)
    assert updated.status == EntryStatus.RESOLVED
    assert updated.metadata["close_reason"] == "task_expired"


def test_expiry_cleans_blocked_tasks(tmp_path):
    # An approved-then-blocked self-repair task (dirty-workspace dead-end) must
    # be cleaned immediately -- even with a fresh expires_at -- so it does not
    # zombie in the queue. The old sweep only looked at PENDING.
    now = time.time()
    conductor = _conductor(tmp_path)
    task = conductor.add_task(_repair_task(now + 23 * 3600))  # fresh expiry
    conductor.mark_blocked(task.task_id, "workspace not clean")

    cleaned = expire_stale_repair_tasks(conductor, None, None, now=now)

    assert cleaned == [task.task_id]
    updated = conductor.list_tasks(project="maria")[0]
    assert updated.status == TaskStatus.CANCELLED
    assert "blocked self-repair" in updated.notes


def test_expiry_blocked_closes_bulletin_with_reason(tmp_path):
    now = time.time()
    conductor = _conductor(tmp_path)
    task = conductor.add_task(_repair_task(now + 23 * 3600))
    conductor.mark_blocked(task.task_id, "workspace not clean")
    bulletin = BulletinStore(path=tmp_path / "bulletin.jsonl")
    entry = bulletin.create_and_post(
        entry_type=EntryType.IMPROVEMENT,
        topic="self_repair_action_failure_storm",
        reason_code="self_repair_action_failure_storm",
        summary="Self-repair created",
        requested_by="self_repair_monitor",
        metadata={"task_id": task.task_id},
    )

    expire_stale_repair_tasks(conductor, bulletin, None, now=now)

    updated = bulletin.get(entry.entry_id)
    assert updated.status == EntryStatus.RESOLVED
    assert updated.metadata["close_reason"] == "task_blocked_cleanup"


def test_expiry_combined_notification(tmp_path):
    now = time.time()
    conductor = _conductor(tmp_path)
    tasks = [conductor.add_task(_repair_task(now - i - 1)) for i in range(3)]
    notifier = FakeNotifier()

    expired = expire_stale_repair_tasks(conductor, None, notifier, now=now)

    assert expired == [task.task_id for task in tasks]
    assert len(notifier.messages) == 1
    for task in tasks:
        assert task.task_id in notifier.messages[0]
