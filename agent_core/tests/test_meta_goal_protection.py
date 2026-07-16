"""Protect the always-on META mission from being abandoned + self-heal it.

Root cause of the 2026-06-23 throughput regression: the non-productive-loop
detector abandoned goal-meta-learn (the META mission) on 2026-06-09, which
disabled the saturation->FETCH supply pump; seed_if_empty never restored it
(store not empty), so the learner idled on no_goals once the backlog drained.

2026-07-11 addendum: the exemption alone left the LOOP alive -- selection
re-picked the protected goal and burned the next N reflections (583 completed
evaluate/24h on one Kronika child). NONPRODUCTIVE_COOLDOWN_ENABLED adds the
middle gear: armed puts the goal on the stuck_cooldowns selection filter for
30 min instead of abandoning it; observe only logs + stamps goal.metadata.

REAL GoalStore + PlannerCore (no mocks that would hide a missing _mark_dirty).
"""

import time

from agent_core.goals.store import GoalStore
from agent_core.goals.goal_model import GoalType, GoalStatus, create_goal
from agent_core.planner.planner_core import (
    PlannerCore, NONPRODUCTIVE_COOLDOWN_SEC, nonproductive_cooldown_mode,
)


def _store(tmp_path):
    return GoalStore(tmp_path / "goals.jsonl")


def _planner(tmp_path, store):
    p = PlannerCore(
        state_path=tmp_path / "state.json",
        decisions_path=tmp_path / "decisions.jsonl",
    )
    p.set_goal_store(store)
    return p


# --------------------------------------------------------------------------- #
# ensure_meta_goal (self-heal)
# --------------------------------------------------------------------------- #
class TestEnsureMetaGoal:
    def test_active_meta_unchanged(self, tmp_path):
        store = _store(tmp_path)
        store.seed_if_empty()  # creates an active META goal
        assert store.ensure_meta_goal() is False
        assert store.get("goal-meta-learn").status == GoalStatus.ACTIVE

    def test_reactivates_abandoned_meta(self, tmp_path):
        store = _store(tmp_path)
        store.seed_if_empty()
        store.update_status("goal-meta-learn", GoalStatus.ABANDONED,
                            "non-productive loop", "planner_nonproductive_detector")
        assert store.get("goal-meta-learn").status == GoalStatus.ABANDONED
        # self-heal restores the mission
        assert store.ensure_meta_goal() is True
        assert store.get("goal-meta-learn").status == GoalStatus.ACTIVE

    def test_recreates_when_missing(self, tmp_path):
        store = _store(tmp_path)
        # store has goals but NO meta mission at all
        store.create(create_goal(GoalType.LEARNING, "x", 0.5,
                                 status=GoalStatus.ACTIVE))
        assert store.ensure_meta_goal() is True
        meta = store.get("goal-meta-learn")
        assert meta is not None and meta.type == GoalType.META
        assert meta.status == GoalStatus.ACTIVE

    def test_persists_across_reload(self, tmp_path):
        path = tmp_path / "goals.jsonl"
        store = GoalStore(path)
        store.seed_if_empty()
        store.update_status("goal-meta-learn", GoalStatus.ABANDONED, "x", "system")
        store.ensure_meta_goal()
        store.save()
        reloaded = GoalStore(path)
        reloaded.load()
        assert reloaded.get("goal-meta-learn").status == GoalStatus.ACTIVE


# --------------------------------------------------------------------------- #
# non-productive detector exempts META / MAINTENANCE
# --------------------------------------------------------------------------- #
class TestNonProductiveExemption:
    def test_meta_never_abandoned(self, tmp_path):
        store = _store(tmp_path)
        store.seed_if_empty()
        planner = _planner(tmp_path, store)
        # the detector would have abandoned the mission here -- it must not.
        planner._abandon_nonproductive_goal("goal-meta-learn", "creative", 20)
        assert store.get("goal-meta-learn").status == GoalStatus.ACTIVE

    def test_maintenance_never_abandoned(self, tmp_path):
        store = _store(tmp_path)
        store.seed_if_empty()  # creates goal-maint-health (MAINTENANCE)
        planner = _planner(tmp_path, store)
        planner._abandon_nonproductive_goal("goal-maint-health", "evaluate", 20)
        assert store.get("goal-maint-health").status == GoalStatus.ACTIVE

    def test_user_goal_not_abandoned(self, tmp_path):
        # 2026-07-04: a USER project subgoal (funding rate) was night-blocked
        # from learning, spun 20x creative, and the detector killed the
        # operator's goal. Operator goals are not Maria's to abandon.
        store = _store(tmp_path)
        gid = store.create(create_goal(GoalType.USER, "projekt operatora", 0.6,
                                       status=GoalStatus.ACTIVE))
        planner = _planner(tmp_path, store)
        planner._abandon_nonproductive_goal(gid, "creative", 20)
        assert store.get(gid).status == GoalStatus.ACTIVE

    def test_learning_goal_still_abandoned(self, tmp_path):
        # The exemption must NOT weaken the detector for ordinary goals.
        store = _store(tmp_path)
        gid = store.create(create_goal(GoalType.LEARNING, "spin", 0.5,
                                       status=GoalStatus.ACTIVE))
        planner = _planner(tmp_path, store)
        planner._abandon_nonproductive_goal(gid, "creative", 20)
        assert store.get(gid).status == GoalStatus.ABANDONED


# --------------------------------------------------------------------------- #
# NONPRODUCTIVE_COOLDOWN_ENABLED: off / observe / armed middle gear
# --------------------------------------------------------------------------- #
class TestNonProductiveCooldown:
    def _user_goal(self, store):
        return store.create(create_goal(GoalType.USER, "projekt operatora", 0.6,
                                        status=GoalStatus.ACTIVE))

    def test_mode_parser(self):
        assert nonproductive_cooldown_mode(None) == "off"
        assert nonproductive_cooldown_mode("") == "off"
        assert nonproductive_cooldown_mode("nonsense") == "off"
        assert nonproductive_cooldown_mode("observe") == "observe"
        for v in ("armed", "on", "1", "true", "yes", "cutover", " ARMED "):
            assert nonproductive_cooldown_mode(v) == "armed"

    def test_default_off_keeps_legacy_behavior(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NONPRODUCTIVE_COOLDOWN_ENABLED", raising=False)
        store = _store(tmp_path)
        gid = self._user_goal(store)
        planner = _planner(tmp_path, store)
        planner._abandon_nonproductive_goal(gid, "evaluate", 20)
        assert store.get(gid).status == GoalStatus.ACTIVE
        assert gid not in planner._state.stuck_cooldowns
        assert "nonproductive_cooldown_observed" not in store.get(gid).metadata

    def test_observe_stamps_metadata_no_cooldown(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NONPRODUCTIVE_COOLDOWN_ENABLED", "observe")
        store = _store(tmp_path)
        gid = self._user_goal(store)
        planner = _planner(tmp_path, store)
        planner._abandon_nonproductive_goal(gid, "evaluate", 20)
        planner._abandon_nonproductive_goal(gid, "evaluate", 20)
        goal = store.get(gid)
        assert goal.status == GoalStatus.ACTIVE
        assert gid not in planner._state.stuck_cooldowns
        assert goal.metadata["nonproductive_cooldown_observed"] == 2
        assert goal.metadata["nonproductive_cooldown_last_ts"] > 0
        # evidence must survive a store reload (_mark_dirty actually fired)
        store.save()
        reloaded = GoalStore(tmp_path / "goals.jsonl")
        reloaded.load()
        assert (reloaded.get(gid).metadata["nonproductive_cooldown_observed"]
                == 2)

    def test_armed_cools_user_goal_without_abandoning(self, tmp_path,
                                                      monkeypatch):
        monkeypatch.setenv("NONPRODUCTIVE_COOLDOWN_ENABLED", "armed")
        store = _store(tmp_path)
        gid = self._user_goal(store)
        planner = _planner(tmp_path, store)
        before = time.time()
        planner._abandon_nonproductive_goal(gid, "evaluate", 20)
        assert store.get(gid).status == GoalStatus.ACTIVE
        until = planner._state.stuck_cooldowns.get(gid)
        assert until is not None
        assert (before + NONPRODUCTIVE_COOLDOWN_SEC - 5
                <= until
                <= time.time() + NONPRODUCTIVE_COOLDOWN_SEC + 5)

    def test_armed_cools_meta_and_maintenance(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NONPRODUCTIVE_COOLDOWN_ENABLED", "armed")
        store = _store(tmp_path)
        store.seed_if_empty()
        planner = _planner(tmp_path, store)
        planner._abandon_nonproductive_goal("goal-meta-learn", "creative", 20)
        planner._abandon_nonproductive_goal("goal-maint-health", "evaluate", 20)
        assert store.get("goal-meta-learn").status == GoalStatus.ACTIVE
        assert store.get("goal-maint-health").status == GoalStatus.ACTIVE
        assert "goal-meta-learn" in planner._state.stuck_cooldowns
        assert "goal-maint-health" in planner._state.stuck_cooldowns

    def test_armed_learning_goal_still_abandoned(self, tmp_path, monkeypatch):
        # The middle gear is for PROTECTED goals only -- Maria's own LEARNING
        # goals keep the stronger remedy (abandon), exactly as before.
        monkeypatch.setenv("NONPRODUCTIVE_COOLDOWN_ENABLED", "armed")
        store = _store(tmp_path)
        gid = store.create(create_goal(GoalType.LEARNING, "spin", 0.5,
                                       status=GoalStatus.ACTIVE))
        planner = _planner(tmp_path, store)
        planner._abandon_nonproductive_goal(gid, "creative", 20)
        assert store.get(gid).status == GoalStatus.ABANDONED
        assert gid not in planner._state.stuck_cooldowns

    def test_armed_cooled_goal_skipped_by_ranking(self, tmp_path, monkeypatch):
        # End-to-end through the REAL selection filter: after the cooldown
        # fires, _select_ranked_goals must rotate to the sibling goal.
        monkeypatch.setenv("NONPRODUCTIVE_COOLDOWN_ENABLED", "armed")
        store = _store(tmp_path)
        looping = self._user_goal(store)
        sibling = store.create(create_goal(GoalType.USER, "drugi podcel", 0.6,
                                           status=GoalStatus.ACTIVE))
        planner = _planner(tmp_path, store)
        context = {"active_goals": store.get_active()}
        ranked_before = [g.id for g in planner._select_ranked_goals(context)]
        assert looping in ranked_before and sibling in ranked_before
        planner._abandon_nonproductive_goal(looping, "evaluate", 20)
        context = {"active_goals": store.get_active()}
        ranked_after = [g.id for g in planner._select_ranked_goals(context)]
        assert looping not in ranked_after
        assert sibling in ranked_after


class TestMetaNeverAutoAchieves:
    """META is a perpetual mission -- progress 1.0 must NOT terminate it (that
    stalled the saturation->FETCH supply pump until the next boot)."""

    def test_meta_stays_active_at_full_progress(self, tmp_path):
        store = _store(tmp_path)
        store.seed_if_empty()
        store.update_progress("goal-meta-learn", 1.0)
        assert store.get("goal-meta-learn").status == GoalStatus.ACTIVE
        assert store.get("goal-meta-learn").progress == 1.0

    def test_maintenance_stays_active_at_full_progress(self, tmp_path):
        store = _store(tmp_path)
        store.seed_if_empty()
        store.update_progress("goal-maint-health", 1.0)
        assert store.get("goal-maint-health").status == GoalStatus.ACTIVE

    def test_learning_goal_still_auto_achieves(self, tmp_path):
        # The exemption must NOT change ordinary learning goals.
        store = _store(tmp_path)
        gid = store.create(create_goal(GoalType.LEARNING, "topic", 0.5,
                                       status=GoalStatus.ACTIVE))
        store.update_progress(gid, 1.0)
        assert store.get(gid).status == GoalStatus.ACHIEVED
