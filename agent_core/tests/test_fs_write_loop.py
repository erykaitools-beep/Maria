"""Tests for B2 part 2: the autonomous FS_WRITE loop + criteria goal closure.

The first real effector action end-to-end: a goal with a file_exists criterion
-> planner emits FS_WRITE (flag-gated) -> handler writes the sandboxed file ->
goal closes on EXTERNAL evidence. Flag OFF -> nothing happens.
"""

from pathlib import Path

from agent_core.planner.planner_core import PlannerCore
from agent_core.planner.planner_model import ActionType, create_plan
from agent_core.goals.store import GoalStore
from agent_core.goals.goal_model import create_goal, GoalType, GoalStatus
from agent_core.routing.capability_router import CapabilityRouter
from agent_core.routing.capability_spec import DEFAULT_CAPABILITY_SPECS
from agent_core.routing.handlers import (
    make_fs_write_handler, close_goal_on_criteria, seed_first_action_goal,
)


def _planner(tmp_path, sandbox):
    p = PlannerCore(
        state_path=tmp_path / "state.json",
        decisions_path=tmp_path / "decisions.jsonl",
    )
    p._fs_sandbox_root = str(sandbox)  # point the loop at the test sandbox
    return p


def _make_goal(target, status=GoalStatus.ACTIVE):
    return create_goal(
        GoalType.USER, "first action", 0.9, status=status,
        success_criteria=[{"type": "file_exists", "path": target}],
    )


# -------------------- _maybe_fs_write: flag gating + candidate --------------------

def test_flag_off_is_noop(tmp_path):
    sandbox = tmp_path / "sb"
    p = _planner(tmp_path, sandbox)
    store = GoalStore(tmp_path / "goals.jsonl")
    store.create(_make_goal(str(sandbox / "x.txt")))
    p.set_goal_store(store)
    assert p._maybe_fs_write({}) is None  # flag default OFF -> no-op


def test_flag_on_emits_plan_and_promotes(tmp_path):
    sandbox = tmp_path / "sb"
    p = _planner(tmp_path, sandbox)
    store = GoalStore(tmp_path / "goals.jsonl")
    g = _make_goal(str(sandbox / "maria_first_action.txt"), status=GoalStatus.PENDING)
    store.create(g)
    p.set_goal_store(store)
    p.set_fs_write_enabled(True)

    plan = p._maybe_fs_write({})
    assert plan is not None
    assert plan.action_type == ActionType.FS_WRITE
    assert plan.goal_id == g.id
    assert plan.action_params["filename"] == "maria_first_action.txt"
    assert plan.action_params["sandbox_root"] == str(sandbox)
    # committing work promotes PENDING -> ACTIVE so closure can auto-achieve
    assert store.get(g.id).status == GoalStatus.ACTIVE


def test_skips_when_criterion_already_met(tmp_path):
    sandbox = tmp_path / "sb"
    sandbox.mkdir()
    target = sandbox / "done.txt"
    target.write_text("already here")
    p = _planner(tmp_path, sandbox)
    store = GoalStore(tmp_path / "goals.jsonl")
    store.create(_make_goal(str(target)))
    p.set_goal_store(store)
    p.set_fs_write_enabled(True)
    assert p._maybe_fs_write({}) is None  # criterion satisfied -> no rewrite


def test_ignores_goal_without_criteria(tmp_path):
    sandbox = tmp_path / "sb"
    p = _planner(tmp_path, sandbox)
    store = GoalStore(tmp_path / "goals.jsonl")
    store.create(create_goal(GoalType.USER, "no crit", 0.9, status=GoalStatus.ACTIVE))
    p.set_goal_store(store)
    p.set_fs_write_enabled(True)
    assert p._maybe_fs_write({}) is None


# -------------------- handler + closer --------------------

def test_handler_writes_and_closes_goal(tmp_path):
    sandbox = tmp_path / "sb"
    store = GoalStore(tmp_path / "goals.jsonl")
    target = sandbox / "proof.txt"
    g = _make_goal(str(target), status=GoalStatus.ACTIVE)
    store.create(g)

    handler = make_fs_write_handler(store)
    plan = create_plan(g.id, "first action", ActionType.FS_WRITE, {
        "filename": "proof", "content": "hi", "sandbox_root": str(sandbox),
    })
    result = handler(plan)

    assert result["success"] is True
    assert target.is_file()
    achieved = store.get(g.id)
    assert achieved.status == GoalStatus.ACHIEVED
    assert achieved.outcome["closed_by"] == "success_criteria"


def test_closer_does_not_close_when_unmet(tmp_path):
    sandbox = tmp_path / "sb"
    sandbox.mkdir()
    store = GoalStore(tmp_path / "goals.jsonl")
    g = _make_goal(str(sandbox / "missing.txt"), status=GoalStatus.ACTIVE)
    store.create(g)
    plan = create_plan(g.id, "x", ActionType.FS_WRITE, {})
    close_goal_on_criteria(plan, {"success": True}, store, sandbox_root=str(sandbox))
    # criterion file never written -> goal stays ACTIVE (no false close)
    assert store.get(g.id).status == GoalStatus.ACTIVE


# -------------------- seed helper + full end-to-end via router --------------------

def test_seed_first_action_goal(tmp_path):
    store = GoalStore(tmp_path / "goals.jsonl")
    gid = seed_first_action_goal(store, base_dir=str(tmp_path))
    assert gid is not None
    g = store.get(gid)
    assert g.status == GoalStatus.ACTIVE
    assert g.success_criteria[0]["type"] == "file_exists"
    assert "fs_sandbox" in g.success_criteria[0]["path"]


def test_end_to_end_loop_via_router(tmp_path):
    """seed -> planner emits FS_WRITE -> router handler writes -> goal ACHIEVED."""
    sandbox = tmp_path / "meta_data" / "fs_sandbox"
    store = GoalStore(tmp_path / "goals.jsonl")
    gid = seed_first_action_goal(store, base_dir=str(tmp_path))

    p = _planner(tmp_path, sandbox)
    p.set_goal_store(store)
    p.set_fs_write_enabled(True)

    plan = p._maybe_fs_write({})
    assert plan is not None and plan.goal_id == gid

    router = CapabilityRouter()
    router.register("fs_write", make_fs_write_handler(store),
                    DEFAULT_CAPABILITY_SPECS["fs_write"])
    result = router.dispatch(plan)

    assert result["success"] is True
    assert Path(result["path"]).is_file()           # a real file now exists
    closed = store.get(gid)
    assert closed.status == GoalStatus.ACHIEVED       # goal closed...
    assert closed.outcome["closed_by"] == "success_criteria"  # ...on external evidence
    assert closed.outcome["evidence"][0]["passed"] is True


# -------------------- runtime toggle + Telegram /fs_write command --------------------

def test_set_fs_write_enabled_runtime_toggle(tmp_path):
    p = _planner(tmp_path, tmp_path / "sb")
    assert p._fs_write_enabled is False  # env default OFF
    p.set_fs_write_enabled(True)
    assert p._fs_write_enabled is True
    p.set_fs_write_enabled(False)
    assert p._fs_write_enabled is False


def test_fs_write_telegram_command(tmp_path):
    from types import SimpleNamespace
    from agent_core.modules.homeostasis_telegram_commands import register_telegram_commands as _register_telegram_commands

    class FakeBridge:
        def __init__(self):
            self.handlers = {}

        def register_command(self, command, handler):
            self.handlers[command] = handler

    p = _planner(tmp_path, tmp_path / "sb")
    store = GoalStore(tmp_path / "goals.jsonl")
    p.set_goal_store(store)
    ctx = SimpleNamespace(
        maria_conductor=None, self_perception=None, homeostasis_core=None,
        planner_core=p, knowledge_analyzer=None, goal_store=store,
        bulletin_store=None,
    )
    bridge = FakeBridge()
    _register_telegram_commands(bridge, ctx)
    cmd = bridge.handlers["fs_write"]

    assert "OFF" in cmd("")                  # default status
    assert "ON" in cmd("on")                 # enable
    assert p._fs_write_enabled is True
    assert "ACTIVE" in cmd("seed")           # create demo goal
    assert len(store.get_active()) == 1
    assert "file_exists" in cmd("")          # status shows the open criterion goal
    assert "OFF" in cmd("off")               # disable
    assert p._fs_write_enabled is False
