import time

from agent_core.bulletin.bulletin_store import BulletinStore
from agent_core.conductor import Conductor, TaskQueue
from agent_core.conductor.task_model import Assignee, TaskStatus, create_task
from agent_core.self_repair.detectors import RepairCandidate
from agent_core.self_repair.task_creator import RepairTaskCreator


class FakeSelfPerception:
    def __init__(self, snapshot, fresh=True):
        self.snapshot = snapshot
        self.fresh = fresh

    def get_latest(self):
        return self.snapshot

    def is_fresh(self, max_age_seconds=300):
        return self.fresh


class FakeBoard:
    def __init__(self):
        self.calls = []

    def append_repair_entry(self, **kwargs):
        self.calls.append(kwargs)
        return True


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def send_raw(self, text, parse_mode=None):
        self.messages.append(text)
        return True


def _snapshot(mode="ACTIVE", nim_status="available"):
    return {
        "snapshot_id": "sps-test",
        "timestamp": time.time(),
        "mode": mode,
        "external_services": [
            {"name": "NVIDIA NIM API", "status": nim_status},
        ],
    }


def _candidate(kind="action_failure_storm"):
    return RepairCandidate(
        repair_kind=kind,
        summary="Action failure storm: 5/12 failed",
        evidence_summary={"one_line": "5/12 failed", "subject": "learn"},
        detected_at=time.time(),
    )


def _creator(tmp_path, snapshot=None, fresh=True):
    conductor = Conductor(queue=TaskQueue(path=tmp_path / "maria_task_queue.jsonl"))
    bulletin = BulletinStore(path=tmp_path / "bulletin.jsonl")
    board = FakeBoard()
    notifier = FakeNotifier()
    creator = RepairTaskCreator(
        conductor=conductor,
        bulletin_store=bulletin,
        task_board_writer=board,
        notifier=notifier,
        self_perception=FakeSelfPerception(snapshot or _snapshot(), fresh=fresh),
    )
    return creator, conductor, bulletin, board, notifier


def test_create_task_happy_path(tmp_path):
    creator, conductor, bulletin, board, notifier = _creator(tmp_path)

    task_id = creator.create(_candidate(), "sps-test")

    assert task_id is not None
    task = conductor.list_tasks(project="maria")[0]
    assert task.status == TaskStatus.PENDING
    assert task.assignee == Assignee.CODEX
    assert task.artifacts["approval_required"] is True
    assert bulletin.get_open()
    assert board.calls
    assert notifier.messages


def test_gate_refuses_stale_snapshot(tmp_path):
    creator, conductor, bulletin, board, notifier = _creator(tmp_path, fresh=False)

    assert creator.create(_candidate(), "sps-test") is None
    assert conductor.list_tasks(project="maria") == []
    assert bulletin.get_open() == []
    assert board.calls == []
    assert notifier.messages == []


def test_gate_refuses_survival_mode(tmp_path):
    creator, conductor, _, _, _ = _creator(
        tmp_path,
        snapshot=_snapshot(mode="SURVIVAL"),
    )

    assert creator.create(_candidate(), "sps-test") is None
    assert conductor.list_tasks(project="maria") == []


def test_gate_refuses_nim_down_for_nim_repair(tmp_path):
    creator, conductor, _, _, _ = _creator(
        tmp_path,
        snapshot=_snapshot(nim_status="unavailable"),
    )

    assert creator.create(_candidate(kind="model_unavailable"), "sps-test") is None
    assert conductor.list_tasks(project="maria") == []


def test_gate_refuses_cooldown(tmp_path):
    creator, conductor, _, _, _ = _creator(tmp_path)
    existing = create_task(
        project="maria",
        phase="self_repair",
        title="Existing",
        description="",
        assignee=Assignee.CODEX,
    )
    existing.artifacts = {"repair_kind": "action_failure_storm"}
    conductor.add_task(existing)

    assert creator.create(_candidate(), "sps-test") is None
    assert len(conductor.list_tasks(project="maria")) == 1


def test_task_artifacts_complete(tmp_path):
    creator, conductor, _, _, _ = _creator(tmp_path)
    before = time.time()

    task_id = creator.create(_candidate(), "sps-test")

    task = conductor.list_tasks(project="maria")[0]
    assert task_id == task.task_id
    artifacts = task.artifacts
    assert artifacts["repair_kind"] == "action_failure_storm"
    assert artifacts["evidence_summary"]["one_line"] == "5/12 failed"
    assert artifacts["created_by"] == "maria_self_diagnosis"
    assert artifacts["snapshot_id"] == "sps-test"
    assert artifacts["workspace_path"] == "/home/maria/maria"
    assert artifacts["approval_required"] is True
    assert before + 86400 <= artifacts["expires_at"] <= time.time() + 86400


def test_task_board_echo(tmp_path):
    creator, conductor, _, board, _ = _creator(tmp_path)

    task_id = creator.create(_candidate(), "sps-test")

    task = conductor.list_tasks(project="maria")[0]
    assert board.calls == [
        {
            "task_id": task_id,
            "title": task.title,
            "repair_kind": "action_failure_storm",
            "evidence_summary": {"one_line": "5/12 failed", "subject": "learn"},
            "expires_at": task.artifacts["expires_at"],
        }
    ]


# ----------------------------------------------------------------------------
# Live drill (Plank 6): bypass_gate + drill marker
# ----------------------------------------------------------------------------

def _drill_candidate():
    return RepairCandidate(
        repair_kind="drill",
        summary="DRILL - synthetic self-repair live test",
        evidence_summary={"drill": True, "subject": "drill"},
        detected_at=time.time(),
    )


def test_bypass_gate_creates_despite_stale_snapshot(tmp_path):
    """The drill (bypass_gate) creates a task even when the gate would refuse."""
    creator, conductor, bulletin, board, notifier = _creator(tmp_path, fresh=False)

    # Without bypass: gate refuses (stale snapshot) -> None.
    assert creator.create(_drill_candidate(), "drill") is None
    # With bypass: the full chain runs anyway.
    task_id = creator.create(_drill_candidate(), "drill", bypass_gate=True)
    assert task_id is not None
    task = conductor.list_tasks(project="maria")[0]
    assert task.status == TaskStatus.PENDING
    assert task.artifacts["approval_required"] is True  # still gated for dispatch
    assert bulletin.get_open()
    assert board.calls
    assert notifier.messages


def test_bypass_gate_creates_despite_survival_mode(tmp_path):
    """bypass_gate ignores the mode gate (drill works in SLEEP/SURVIVAL)."""
    creator, conductor, _, _, _ = _creator(
        tmp_path, snapshot=_snapshot(mode="SURVIVAL")
    )
    assert creator.create(_drill_candidate(), "drill") is None
    task_id = creator.create(_drill_candidate(), "drill", bypass_gate=True)
    assert task_id is not None
    assert len(conductor.list_tasks(project="maria")) == 1


def test_drill_candidate_marks_artifact(tmp_path):
    """A drill candidate flags artifacts['drill']=True for downstream clarity."""
    creator, conductor, _, _, _ = _creator(tmp_path)
    creator.create(_drill_candidate(), "drill", bypass_gate=True)
    task = conductor.list_tasks(project="maria")[0]
    assert task.artifacts["drill"] is True
    assert task.artifacts["repair_kind"] == "drill"


def test_real_candidate_not_marked_drill(tmp_path):
    """A genuine repair candidate is NOT flagged as a drill."""
    creator, conductor, _, _, _ = _creator(tmp_path)
    creator.create(_candidate(), "sps-test")
    task = conductor.list_tasks(project="maria")[0]
    assert task.artifacts["drill"] is False


def test_bypass_gate_default_false_still_gated(tmp_path):
    """Default (bypass_gate=False) preserves the gate -- no accidental bypass."""
    creator, conductor, _, _, _ = _creator(tmp_path, fresh=False)
    assert creator.create(_candidate(), "sps-test") is None
    assert conductor.list_tasks(project="maria") == []
