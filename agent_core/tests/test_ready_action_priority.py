"""A real admitted file task precedes reflection and closes only on evidence."""
import pytest

from agent_core.goals.goal_model import GoalStatus, GoalType, create_goal
from agent_core.goals.store import GoalStore
from agent_core.llm.work_priority import WorkPurpose, current_work_purpose
from agent_core.planner.planner_core import PlannerCore
from agent_core.planner.planner_model import ActionType
from agent_core.routing.capability_router import CapabilityRouter
from agent_core.routing.capability_spec import DEFAULT_CAPABILITY_SPECS
from agent_core.routing.handlers import make_fs_write_handler


@pytest.mark.parametrize("guard_refuses", [False, True])
def test_ready_file_task_precedes_replanning_and_reflection_but_keeps_guard(tmp_path, monkeypatch, guard_refuses):
    sandbox = tmp_path / "sandbox"
    target = sandbox / "proof.txt"
    store = GoalStore(tmp_path / "goals.jsonl")
    goal = create_goal(GoalType.USER, "Write the requested proof", 0.9,
                       success_criteria=[{"type": "file_exists", "path": str(target)}],
                       metadata={"fs_write_content": "Requested result\n"})
    store.create(goal)
    planner = PlannerCore(state_path=tmp_path / "state.json", decisions_path=tmp_path / "decisions.jsonl")
    planner.set_goal_store(store)
    planner.set_fs_write_enabled(True)
    planner._fs_sandbox_root = str(sandbox)
    if guard_refuses:
        monkeypatch.setattr(planner, "_check_guard", lambda: (False, ["test guard"]))
    monkeypatch.setattr(planner, "_strategic_replan_due", lambda: pytest.fail("replanned before a ready task"))
    monkeypatch.setattr(planner, "_maybe_creative", lambda _: pytest.fail("reflected before a ready task"))
    seen = []
    real_handler = make_fs_write_handler(store)

    def handler(plan):
        seen.append(current_work_purpose())
        return real_handler(plan)

    router = CapabilityRouter()
    router.register("fs_write", handler, DEFAULT_CAPABILITY_SPECS["fs_write"])
    planner.set_capability_router(router)
    plan = planner.run_cycle(60)
    if guard_refuses:
        assert plan is None and not target.exists() and not seen
        assert store.get(goal.id).status == GoalStatus.PENDING
    else:
        assert plan.action_type == ActionType.FS_WRITE and plan.result["success"]
        assert target.read_text() == "Requested result\n"
        closed = store.get(goal.id)
        assert closed.status == GoalStatus.ACHIEVED
        assert closed.outcome["closed_by"] == "success_criteria"
        assert closed.outcome["evidence"][0]["passed"] is True
        assert seen == [WorkPurpose.ACTION]
    assert current_work_purpose() is None
