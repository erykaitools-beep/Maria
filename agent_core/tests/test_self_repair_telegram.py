import time
from types import SimpleNamespace

from agent_core.conductor import Conductor, TaskQueue
from agent_core.conductor.task_model import Assignee, TaskStatus, create_task
from agent_core.modules.homeostasis_telegram_commands import register_telegram_commands as _register_telegram_commands


class FakeBot:
    def __init__(self):
        self.messages = []

    def send_message(self, text, parse_mode=None):
        self.messages.append(text)
        return True


class FakeBridge:
    def __init__(self):
        self.handlers = {}
        self.bot = FakeBot()

    def register_command(self, command, handler):
        self.handlers[command] = handler


def _ctx(conductor):
    return SimpleNamespace(
        maria_conductor=conductor,
        self_perception=None,
        homeostasis_core=None,
        planner_core=None,
        knowledge_analyzer=None,
        goal_store=None,
        bulletin_store=None,
    )


def _conductor(tmp_path):
    return Conductor(queue=TaskQueue(path=tmp_path / "maria_task_queue.jsonl"))


def _repair_task(repair_kind="model_unavailable"):
    task = create_task(
        project="maria",
        phase="self_repair",
        title="Repair",
        description="",
        assignee=Assignee.CODEX,
    )
    task.artifacts = {
        "repair_kind": repair_kind,
        "repair_subject": "NIM API",
        "approval_required": True,
        "expires_at": time.time() + 86400,
    }
    return task


def _bridge_with_ctx(ctx):
    bridge = FakeBridge()
    _register_telegram_commands(bridge, ctx)
    return bridge


def test_list_repairs_empty(tmp_path):
    bridge = _bridge_with_ctx(_ctx(_conductor(tmp_path)))

    response = bridge.handlers["list_repairs"]("")

    assert response == "Brak otwartych self-repair tasks."


def test_list_repairs_shows_pending(tmp_path):
    conductor = _conductor(tmp_path)
    t1 = conductor.add_task(_repair_task("model_unavailable"))
    t2 = conductor.add_task(_repair_task("dispatcher_stuck"))
    bridge = _bridge_with_ctx(_ctx(conductor))

    response = bridge.handlers["list_repairs"]("")

    assert "Otwarte self-repair tasks (2)" in response
    assert t1.task_id in response
    assert t2.task_id in response
    assert "/approve_repair <task_id>" in response


def test_approve_repair_closes_task(tmp_path):
    # Approval = operator owns it -> task is closed (DONE), not dispatched.
    conductor = _conductor(tmp_path)
    task = conductor.add_task(_repair_task())
    bridge = _bridge_with_ctx(_ctx(conductor))

    response = bridge.handlers["approve_repair"](task.task_id)

    updated = conductor.list_tasks(project="maria")[0]
    assert updated.status == TaskStatus.DONE
    assert conductor.list_tasks(project="maria", status=TaskStatus.PENDING) == []
    assert f"Zatwierdzono i zamknieto {task.task_id}" in response
    assert bridge.bot.messages


def test_approve_repair_resolves_bulletin(tmp_path):
    from agent_core.bulletin.bulletin_store import BulletinStore
    from agent_core.bulletin.bulletin_model import EntryStatus, EntryType

    conductor = _conductor(tmp_path)
    task = conductor.add_task(_repair_task())
    bulletin = BulletinStore(path=tmp_path / "bulletin.jsonl")
    entry = bulletin.create_and_post(
        entry_type=EntryType.IMPROVEMENT,
        topic="self_repair",
        reason_code="self_repair",
        summary="Self-repair created",
        requested_by="self_repair_monitor",
        metadata={"task_id": task.task_id},
    )
    ctx = _ctx(conductor)
    ctx.bulletin_store = bulletin
    bridge = _bridge_with_ctx(ctx)

    bridge.handlers["approve_repair"](task.task_id)

    updated = bulletin.get(entry.entry_id)
    assert updated.status == EntryStatus.RESOLVED
    assert updated.metadata["close_reason"] == "operator_acknowledged"


def test_approve_repair_unknown_id(tmp_path):
    conductor = _conductor(tmp_path)
    bridge = _bridge_with_ctx(_ctx(conductor))

    response = bridge.handlers["approve_repair"]("cdt-xxx")

    assert response == "Nie znaleziono PENDING self-repair task: cdt-xxx"


# ----------------------------------------------------------------------------
# /drill_repair (Plank 6 live drill)
# ----------------------------------------------------------------------------

def _drill_ctx(tmp_path, self_perception=None):
    from agent_core.bulletin.bulletin_store import BulletinStore
    from agent_core.self_repair.task_creator import RepairTaskCreator

    class _Board:
        def __init__(self):
            self.calls = []

        def append_repair_entry(self, **kwargs):
            self.calls.append(kwargs)
            return True

    class _Notifier:
        def __init__(self):
            self.messages = []

        def send_raw(self, text, parse_mode=None):
            self.messages.append(text)
            return True

    conductor = _conductor(tmp_path)
    creator = RepairTaskCreator(
        conductor=conductor,
        bulletin_store=BulletinStore(path=tmp_path / "bulletin.jsonl"),
        task_board_writer=_Board(),
        notifier=_Notifier(),
        self_perception=self_perception,
    )
    ctx = _ctx(conductor)
    ctx.repair_task_creator = creator
    return ctx, conductor


def test_drill_repair_force_creates_task(tmp_path):
    """/drill_repair force runs the real creation chain -> a drill task lands."""
    ctx, conductor = _drill_ctx(tmp_path)
    bridge = _bridge_with_ctx(ctx)

    response = bridge.handlers["drill_repair"]("force")

    assert "Drill OK" in response
    tasks = conductor.list_tasks(project="maria")
    assert len(tasks) == 1
    assert tasks[0].artifacts["drill"] is True
    assert tasks[0].artifacts["approval_required"] is True  # never auto-dispatches


def test_drill_repair_gate_refuses_without_force(tmp_path):
    """Without force the gate applies (here: no snapshot) -> reported, no task."""
    ctx, conductor = _drill_ctx(tmp_path)  # self_perception=None -> gate refuses
    bridge = _bridge_with_ctx(ctx)

    response = bridge.handlers["drill_repair"]("")

    assert "ODMOWIONY" in response
    assert conductor.list_tasks(project="maria") == []


def test_drill_repair_no_creator(tmp_path):
    """Graceful message when the self-repair module is not wired."""
    bridge = _bridge_with_ctx(_ctx(_conductor(tmp_path)))  # ctx has no creator

    response = bridge.handlers["drill_repair"]("force")

    assert "nie wired" in response


# ----------------------------------------------------------------------------
# /drill_heartbeat (Plank 7b live drill)
# ----------------------------------------------------------------------------

def test_drill_heartbeat_force_creates_thread_unhealthy_task(tmp_path):
    """/drill_heartbeat force runs the REAL heartbeat path -> a thread_unhealthy
    drill task lands (proves detect_thread_unhealthy -> creator end to end)."""
    ctx, conductor = _drill_ctx(tmp_path)
    bridge = _bridge_with_ctx(ctx)

    response = bridge.handlers["drill_heartbeat"]("force")

    assert "Heartbeat drill OK" in response
    tasks = conductor.list_tasks(project="maria")
    assert len(tasks) == 1
    assert tasks[0].artifacts["repair_kind"] == "thread_unhealthy"
    assert tasks[0].artifacts["drill"] is True  # evidence drill flag -> task drill
    assert tasks[0].artifacts["approval_required"] is True  # never auto-dispatches


def test_drill_heartbeat_gate_refuses_without_force(tmp_path):
    """Without force the gate applies (here: no snapshot) -> reported, no task."""
    ctx, conductor = _drill_ctx(tmp_path)  # self_perception=None -> gate refuses
    bridge = _bridge_with_ctx(ctx)

    response = bridge.handlers["drill_heartbeat"]("")

    assert "ODMOWIONY" in response
    assert conductor.list_tasks(project="maria") == []


def test_drill_heartbeat_no_creator(tmp_path):
    """Graceful message when the self-repair module is not wired."""
    bridge = _bridge_with_ctx(_ctx(_conductor(tmp_path)))  # ctx has no creator

    response = bridge.handlers["drill_heartbeat"]("force")

    assert "nie wired" in response
