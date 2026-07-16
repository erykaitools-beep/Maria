"""Project self-heal + supply plumbing for project sub-goals (Etap B).

Born from the 2026-07-04 corpse: the first Maria project ("funding rate od
podstaw") lost its first sub-goal within an hour -- learn was night-blocked
(dead USER bypass), the planner spun 20x creative, and the non-productive-loop
detector abandoned the operator's goal. Three pipes fixed here:

  1. _selfheal_project_children revives a detector-killed child of a live
     project (once) and backfills the topics tap;
  2. _maybe_arm_fetch accepts project sub-goals (USER type) so the B2 FETCH
     pump can supply their topic;
  3. update_learning_goal grants progress to project sub-goals, and learn
     skips as no_files when the sub-goal's topic matches no file (instead of
     learning random material off-topic).

REAL GoalStore + PlannerCore (mock stores hide missing _mark_dirty).
"""

import time

import pytest

from agent_core.bulletin.bulletin_store import BulletinStore
from agent_core.goals.store import GoalStore
from agent_core.goals.goal_model import GoalType, GoalStatus, create_goal
from agent_core.planner.planner_core import PlannerCore
from agent_core.planner.planner_model import create_plan, ActionType
from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
from agent_core.teacher.teacher_agent import TeacherAgent
from agent_core.tests.spec_helpers import specced


DETECTOR = "planner_nonproductive_detector"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # .env leaks into tests via load_dotenv() on import -- pin the default.
    monkeypatch.delenv("PROJECT_SELFHEAL_ENABLED", raising=False)


def _store(tmp_path):
    return GoalStore(tmp_path / "goals.jsonl")


def _planner(tmp_path, store):
    p = PlannerCore(
        state_path=tmp_path / "state.json",
        decisions_path=tmp_path / "decisions.jsonl",
    )
    p.set_goal_store(store)
    return p


def _project(store, deadline_offset=5 * 86400, child_status=GoalStatus.ACTIVE,
             child_topics=None):
    """Create a parent project + one child, return (parent_id, child_id)."""
    deadline = time.time() + deadline_offset
    parent_id = store.create(create_goal(
        GoalType.USER, "funding rate od podstaw", 0.55,
        status=GoalStatus.ACTIVE, deadline=deadline,
        metadata={"project": True, "subgoal_count": 1},
    ))
    meta = {"project_parent": parent_id}
    if child_topics is not None:
        meta["topics"] = child_topics
    child_id = store.create(create_goal(
        GoalType.USER, "podstawy funding rate na perpetual futures", 0.6,
        status=child_status, parent_goal_id=parent_id, deadline=deadline,
        metadata=meta,
    ))
    store.save()
    return parent_id, child_id


def _abandon(store, child_id, actor=DETECTOR):
    store.update_status(
        child_id, GoalStatus.ABANDONED,
        reason="non-productive loop: 20 consecutive creative actions",
        actor=actor,
    )
    store.save()


class TestSelfhealRevive:
    def test_detector_abandoned_child_revived(self, tmp_path):
        store = _store(tmp_path)
        parent_id, child_id = _project(store)
        _abandon(store, child_id)

        planner = _planner(tmp_path, store)
        planner._selfheal_project_children()

        child = store.get(child_id)
        assert child.status == GoalStatus.ACTIVE
        assert child.metadata["selfheal_revives"] == 1
        # topics tap backfilled from the description
        assert child.metadata["topics"] == [child.description]
        # revive actor recorded in the audit trail
        assert child.audit_trail[-1].actor == "planner_project_selfheal"

    def test_revive_survives_reload(self, tmp_path):
        store = _store(tmp_path)
        _, child_id = _project(store)
        _abandon(store, child_id)
        _planner(tmp_path, store)._selfheal_project_children()

        reloaded = GoalStore(tmp_path / "goals.jsonl")
        reloaded.load()
        assert reloaded.get(child_id).status == GoalStatus.ACTIVE
        assert reloaded.get(child_id).metadata["selfheal_revives"] == 1

    def test_revive_only_once(self, tmp_path):
        store = _store(tmp_path)
        _, child_id = _project(store)
        _abandon(store, child_id)
        planner = _planner(tmp_path, store)
        planner._selfheal_project_children()
        # dies again -> stays down
        _abandon(store, child_id)
        planner._selfheal_project_children()
        assert store.get(child_id).status == GoalStatus.ABANDONED
        assert store.get(child_id).metadata["selfheal_revives"] == 1

    def test_operator_abandon_respected(self, tmp_path):
        store = _store(tmp_path)
        _, child_id = _project(store)
        _abandon(store, child_id, actor="operator")
        _planner(tmp_path, store)._selfheal_project_children()
        assert store.get(child_id).status == GoalStatus.ABANDONED

    def test_expired_project_not_touched(self, tmp_path):
        store = _store(tmp_path)
        _, child_id = _project(store, deadline_offset=-3600)
        _abandon(store, child_id)
        _planner(tmp_path, store)._selfheal_project_children()
        assert store.get(child_id).status == GoalStatus.ABANDONED

    def test_kill_switch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PROJECT_SELFHEAL_ENABLED", "false")
        store = _store(tmp_path)
        _, child_id = _project(store)
        _abandon(store, child_id)
        _planner(tmp_path, store)._selfheal_project_children()
        assert store.get(child_id).status == GoalStatus.ABANDONED

    def test_bulletin_posted(self, tmp_path):
        store = _store(tmp_path)
        _, child_id = _project(store)
        _abandon(store, child_id)
        planner = _planner(tmp_path, store)
        bulletin = specced(BulletinStore)
        planner.set_bulletin_store(bulletin)
        planner._selfheal_project_children()
        assert bulletin.create_and_post.called
        kwargs = bulletin.create_and_post.call_args.kwargs
        assert kwargs["reason_code"] == "project_selfheal_revive"
        assert kwargs["goal_id"] == child_id

    def test_topics_backfilled_on_active_children(self, tmp_path):
        # children created before the topics tap existed get it retrofitted
        store = _store(tmp_path)
        _, child_id = _project(store)  # active, no topics
        _planner(tmp_path, store)._selfheal_project_children()
        reloaded = GoalStore(tmp_path / "goals.jsonl")
        reloaded.load()
        assert reloaded.get(child_id).metadata["topics"] == [
            "podstawy funding rate na perpetual futures"
        ]


class TestProjectChildFetchPump:
    def test_arm_fetch_for_project_child(self, tmp_path):
        store = _store(tmp_path)
        _, child_id = _project(store)
        planner = _planner(tmp_path, store)

        plan = create_plan(
            goal_id=child_id, goal_description="x",
            action_type=ActionType.LEARN, action_params={},
        )
        planner._maybe_arm_fetch(plan, {"skipped": True, "reason": "no_files"})

        child = store.get(child_id)
        assert child.metadata["needs_fetch"] is True
        # topic seeded from the sub-goal name
        assert child.metadata["topics"] == [child.description]

    def test_arm_fetch_without_reason_when_material_missing(self, tmp_path):
        # K8 strategies rotate actions: the threshold cycle may end on an
        # exam/creative result with NO exhaustion reason. For project children
        # the pump checks the material supply directly via the analyzer.
        store = _store(tmp_path)
        _, child_id = _project(store)
        planner = _planner(tmp_path, store)
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_files_for_topics.return_value = []
        planner.set_knowledge_analyzer(analyzer)

        plan = create_plan(
            goal_id=child_id, goal_description="x",
            action_type=ActionType.EXAM, action_params={},
        )
        planner._maybe_arm_fetch(plan, {"success": True})
        assert store.get(child_id).metadata["needs_fetch"] is True

    def test_no_arm_when_material_exists(self, tmp_path):
        store = _store(tmp_path)
        _, child_id = _project(store)
        planner = _planner(tmp_path, store)
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_files_for_topics.return_value = [("web_funding.txt", 0.9)]
        planner.set_knowledge_analyzer(analyzer)

        plan = create_plan(
            goal_id=child_id, goal_description="x",
            action_type=ActionType.EXAM, action_params={},
        )
        planner._maybe_arm_fetch(plan, {"success": True})
        assert "needs_fetch" not in store.get(child_id).metadata

    def test_no_arm_without_analyzer(self, tmp_path):
        # cannot verify starvation -> do not arm blindly
        store = _store(tmp_path)
        _, child_id = _project(store)
        planner = _planner(tmp_path, store)
        plan = create_plan(
            goal_id=child_id, goal_description="x",
            action_type=ActionType.EXAM, action_params={},
        )
        planner._maybe_arm_fetch(plan, {"success": True})
        assert "needs_fetch" not in store.get(child_id).metadata

    def test_plain_user_goal_still_excluded(self, tmp_path):
        store = _store(tmp_path)
        gid = store.create(create_goal(
            GoalType.USER, "zwykly cel", 0.6, status=GoalStatus.ACTIVE,
        ))
        store.save()
        planner = _planner(tmp_path, store)
        plan = create_plan(
            goal_id=gid, goal_description="x",
            action_type=ActionType.LEARN, action_params={},
        )
        planner._maybe_arm_fetch(plan, {"skipped": True, "reason": "no_files"})
        assert "needs_fetch" not in store.get(gid).metadata


class TestEarlyFetchValve:
    def test_armed_goal_plans_fetch_before_strategy(self, tmp_path):
        # needs_fetch must override K8 rotation: _create_plan_for_goal returns
        # FETCH immediately, before consulting deliberation (live 07-05 bug:
        # strategy kept proposing exam, the fallback flip never ran).
        store = _store(tmp_path)
        _, child_id = _project(store, child_topics=["funding rate"])
        child = store.get(child_id)
        child.metadata["needs_fetch"] = True
        planner = _planner(tmp_path, store)

        plan = planner._create_plan_for_goal(child, {})
        assert plan.action_type == ActionType.FETCH
        assert plan.action_params["topics"] == ["funding rate"]
        # attempt spent + flag consumed
        refreshed = store.get(child_id)
        assert refreshed.metadata["needs_fetch"] is False
        assert refreshed.metadata["fetch_attempts"] == 1


    def test_stale_arm_disarmed_when_material_arrived(self, tmp_path):
        # material landed between arm and fire (live 07-05: textbook arrived,
        # valve shot at a full pantry) -> disarm, no attempt spent, learn runs
        store = _store(tmp_path)
        _, child_id = _project(store, child_topics=["funding rate"])
        child = store.get(child_id)
        child.metadata["needs_fetch"] = True
        planner = _planner(tmp_path, store)
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_files_for_topics.return_value = [("expert_f.txt", 4.5)]
        planner.set_knowledge_analyzer(analyzer)

        plan = planner._create_plan_for_goal(child, {})
        assert plan.action_type != ActionType.FETCH
        refreshed = store.get(child_id)
        assert refreshed.metadata["needs_fetch"] is False
        assert "fetch_attempts" not in refreshed.metadata


class TestProjectChildProgress:
    def test_update_learning_goal_credits_project_child(self, tmp_path, monkeypatch):
        # The chunks-nudge self-heal credits a project child ONLY while the
        # provenance gate is inert (off/observe); at cutover it is suppressed
        # (see test_guard_non_market_project_child_gated_cutover). Pin off so the
        # leaked .env cutover does not mask the nudge path under test.
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "off")
        from agent_core.routing.handlers import update_learning_goal
        store = _store(tmp_path)
        _, child_id = _project(store, child_topics=["funding rate"])
        plan = create_plan(
            goal_id=child_id, goal_description="x",
            action_type=ActionType.LEARN, action_params={},
        )
        update_learning_goal(
            plan, {"chunks_learned": 2}, store, None, None,
        )
        assert store.get(child_id).progress > 0.0

    def test_plain_user_goal_gets_no_progress(self, tmp_path):
        from agent_core.routing.handlers import update_learning_goal
        store = _store(tmp_path)
        gid = store.create(create_goal(
            GoalType.USER, "zwykly cel", 0.6, status=GoalStatus.ACTIVE,
        ))
        store.save()
        plan = create_plan(
            goal_id=gid, goal_description="x",
            action_type=ActionType.LEARN, action_params={},
        )
        update_learning_goal(plan, {"chunks_learned": 2}, store, None, None)
        assert store.get(gid).progress == 0.0


class TestNoFilesSkip:
    def test_exec_learn_skips_when_topic_unmatched(self, tmp_path):
        from agent_core.planner.action_executor import ActionExecutor
        executor = ActionExecutor()
        teacher = specced(TeacherAgent)
        executor.set_teacher_agent(teacher)

        plan = create_plan(
            goal_id="goal-child", goal_description="x",
            action_type=ActionType.LEARN,
            action_params={"topics": ["funding rate"],
                           "resolved_file_ids": []},
            metadata={"project_child": True, "goal_type": "USER"},
        )
        result = executor._exec_learn(plan)
        assert result["skipped"] is True
        assert result["reason"] == "no_files"
        teacher.run_session.assert_not_called()

    def test_exec_exam_skips_when_topic_unmatched(self, tmp_path):
        # exam on a 0-file topic would examine random material and credit the
        # sub-goal off-topic (+0.2/pass) -- must skip as no_files like learn
        from agent_core.planner.action_executor import ActionExecutor
        executor = ActionExecutor()
        teacher = specced(TeacherAgent)
        executor.set_teacher_agent(teacher)

        plan = create_plan(
            goal_id="goal-child", goal_description="x",
            action_type=ActionType.EXAM,
            action_params={"topics": ["funding rate"],
                           "resolved_file_ids": []},
            metadata={"project_child": True, "goal_type": "USER"},
        )
        result = executor._exec_exam(plan)
        assert result["skipped"] is True
        assert result["reason"] == "no_files"
        teacher.run_session.assert_not_called()

    def test_exec_learn_unfiltered_for_non_project_goal(self, tmp_path):
        # a plain goal with an unmatched topic keeps the legacy behavior
        # (unfiltered session) -- the skip is scoped to project children
        from agent_core.planner.action_executor import ActionExecutor
        executor = ActionExecutor()
        teacher = specced(TeacherAgent)
        teacher.run_session.return_value = {"stats": {"chunks_learned": 1}}
        executor.set_teacher_agent(teacher)

        plan = create_plan(
            goal_id="goal-x", goal_description="x",
            action_type=ActionType.LEARN,
            action_params={"topics": ["cokolwiek"],
                           "resolved_file_ids": []},
            # USER bypass keeps the window gate out of the way (clock-proof)
            metadata={"goal_type": "USER"},
        )
        result = executor._exec_learn(plan)
        assert result["success"] is True
        teacher.run_session.assert_called_once()
