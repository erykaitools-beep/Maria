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


class TestOneShotCompletionRespectsPerpetualGoals:
    """The second door into ACHIEVED, which the progress guard does not cover.

    `update_progress` refuses to auto-achieve META/MAINTENANCE at 1.0, but
    `_complete_oneshot_goal` (critique / self_analyze / creative) calls
    `update_status(ACHIEVED)` EXPLICITLY -- walking straight past that guard.
    It does not fire on the live daemon today, because a wired CapabilityRouter
    takes those actions and action_executor is the no-router fallback; under
    goal-meta-learn alone 5 such actions ran in a single week, so the day the
    router is absent this path would ACHIEVE the always-on mission and repeat
    the 2026-06-09 outage (no active META -> FETCH pump stalls -> no_goals).
    """

    def _executor(self, store):
        from agent_core.planner.action_executor import ActionExecutor
        ex = ActionExecutor()
        ex._goal_store = store
        return ex

    def _plan(self, goal_id):
        from agent_core.planner.planner_model import create_plan, ActionType
        return create_plan(
            goal_id=goal_id,
            goal_description="x",
            action_type=ActionType.CREATIVE,
            action_params={},
        )

    def test_oneshot_does_not_achieve_the_meta_mission(self, tmp_path):
        store = _store(tmp_path)
        store.seed_if_empty()
        ex = self._executor(store)

        ex._complete_oneshot_goal(self._plan("goal-meta-learn"), {"ok": True})

        goal = store.get("goal-meta-learn")
        assert goal.status == GoalStatus.ACTIVE, (
            "one-shot completion closed the always-on mission -- this is the "
            "2026-06-09 outage")
        assert goal.progress == 0.0, "mission progress was forced to 1.0"

    def test_oneshot_does_not_achieve_maintenance(self, tmp_path):
        store = _store(tmp_path)
        store.seed_if_empty()
        ex = self._executor(store)

        ex._complete_oneshot_goal(self._plan("goal-maint-health"), {"ok": True})

        assert store.get("goal-maint-health").status == GoalStatus.ACTIVE

    def test_oneshot_still_closes_an_ordinary_goal(self, tmp_path):
        """The guard must not break what this method exists for.

        Without a one-shot close an analytical goal stays PENDING forever and
        the selector keeps re-picking it -- the loop this method was added to
        stop. Only perpetual missions are exempt.
        """
        store = _store(tmp_path)
        gid = store.create(create_goal(GoalType.USER, "jednorazowy", 0.5,
                                       status=GoalStatus.ACTIVE))
        ex = self._executor(store)

        ex._complete_oneshot_goal(self._plan(gid), {"ok": True})

        assert store.get(gid).status == GoalStatus.ACHIEVED
        assert store.get(gid).progress == 1.0


# --------------------------------------------------------------------------- #
# Mission progress counter (CONTRACTS.md:484, implemented 2026-07-22)
# --------------------------------------------------------------------------- #

class _Analyzer:
    """Minimal knowledge analyzer: only what the mission counter reads."""

    def __init__(self, completed_ids, total):
        self._completed = list(completed_ids)
        self._total = total

    def get_knowledge_snapshot(self):
        return {
            "total_files": self._total,
            "files_by_status": {
                "completed": [{"id": fid} for fid in self._completed],
            },
        }


def _verified(monkeypatch, ids):
    """Pin the independent-examiner verdicts (else the live file is read)."""
    import agent_core.goals.success_criteria as sc
    monkeypatch.setattr(
        sc, "independently_verified_file_ids", lambda *a, **k: set(ids),
    )


class TestMissionProgressCounter:
    """The mission earns a real number instead of a frozen 0.0.

    Contract CONTRACTS.md:484 promised progress=<computed from
    knowledge_coverage> and nothing ever implemented it, so the mission showed
    0.0 through 143 days of work while nothing wrote to the goal at all -- its
    updated_at froze for 29 days and every "when did this last move" consumer
    read the gap instead of the mission.
    """

    def test_progress_is_verified_fraction_not_self_graded(
        self, tmp_path, monkeypatch,
    ):
        """Four files marked completed, two actually verified -> 0.5, not 1.0.

        The self-graded 'completed' flag reads 0.963 in production where
        independent verification reads 0.606. "Read" is not "known".
        """
        from agent_core.routing.handlers import update_mission_progress
        _verified(monkeypatch, {"a.txt", "b.txt"})
        store = _store(tmp_path)
        store.seed_if_empty()
        analyzer = _Analyzer(["a.txt", "b.txt", "c.txt", "d.txt"], total=4)

        assert update_mission_progress(
            store.get("goal-meta-learn"), store, analyzer) is True
        assert store.get("goal-meta-learn").progress == 0.5

    def test_full_coverage_does_not_close_the_mission(
        self, tmp_path, monkeypatch,
    ):
        """1.0 must not trip auto-ACHIEVED -- that is the 2026-06-09 outage."""
        from agent_core.routing.handlers import update_mission_progress
        _verified(monkeypatch, {"a.txt", "b.txt"})
        store = _store(tmp_path)
        store.seed_if_empty()

        update_mission_progress(
            store.get("goal-meta-learn"), store,
            _Analyzer(["a.txt", "b.txt"], total=2))

        goal = store.get("goal-meta-learn")
        assert goal.progress == 1.0
        assert goal.status == GoalStatus.ACTIVE, (
            "coverage 1.0 closed the eternal mission")

    def test_progress_may_fall_when_the_pump_fetches_material(
        self, tmp_path, monkeypatch,
    ):
        """New material means MORE to do, so the counter legitimately drops.

        Documented here because a counter that goes backwards looks like a bug
        to the next reader -- it is the honest shape of a mission that is never
        finished. Nothing reaps the mission on a falling number.
        """
        from agent_core.routing.handlers import update_mission_progress
        _verified(monkeypatch, {"a.txt", "b.txt"})
        store = _store(tmp_path)
        store.seed_if_empty()

        update_mission_progress(
            store.get("goal-meta-learn"), store,
            _Analyzer(["a.txt", "b.txt"], total=2))
        assert store.get("goal-meta-learn").progress == 1.0

        # Pump fetched two fresh files: same verified set, bigger denominator.
        update_mission_progress(
            store.get("goal-meta-learn"), store,
            _Analyzer(["a.txt", "b.txt"], total=4))

        goal = store.get("goal-meta-learn")
        assert goal.progress == 0.5
        assert goal.status == GoalStatus.ACTIVE

    def test_write_bumps_updated_at_heartbeat(self, tmp_path, monkeypatch):
        """The write IS the heartbeat -- staleness readers ask updated_at."""
        from agent_core.routing.handlers import update_mission_progress
        _verified(monkeypatch, {"a.txt"})
        store = _store(tmp_path)
        store.seed_if_empty()
        store.get("goal-meta-learn").updated_at = time.time() - 29 * 86400
        # Pre-assert, else this test passes even if the mutation never stuck
        # and the goal was simply fresh from seeding.
        assert (time.time() - store.get("goal-meta-learn").updated_at) > 28 * 86400

        update_mission_progress(
            store.get("goal-meta-learn"), store,
            _Analyzer(["a.txt"], total=2))

        idle_days = (time.time() - store.get("goal-meta-learn").updated_at) / 86400
        assert idle_days < 0.01, f"mission still looks {idle_days:.0f} days idle"

    def test_write_is_flushed_to_disk_not_left_dirty(
        self, tmp_path, monkeypatch,
    ):
        """A fresh store reading the same file must see the new progress.

        The mission never crosses the achieved-save path in
        update_learning_goal, so without an explicit save() the record stayed
        dirty-in-memory until some unrelated handler flushed it. On 2026-07-23
        the on-disk file showed 0.0 for 26+ minutes after the counter logged
        0.606, and the external check script called a working counter
        PODEJRZANE.
        """
        from agent_core.routing.handlers import update_mission_progress
        _verified(monkeypatch, {"a.txt"})
        path = tmp_path / "goals.jsonl"
        store = GoalStore(path)
        store.seed_if_empty()
        # Flush the seed and empty the dirty-set FIRST: live daemons run with
        # a long-settled store, and a leftover dirty flag from seeding lets
        # save() write the record even if update_progress forgot _mark_dirty
        # (mutation run 2026-07-23 proved this masked exactly that bug).
        store.save()

        update_mission_progress(
            store.get("goal-meta-learn"), store, _Analyzer(["a.txt"], total=2))

        reloaded = GoalStore(path)
        reloaded.load()
        assert reloaded.get("goal-meta-learn").progress == 0.5, (
            "counter value never reached disk -- external readers see 0.0")

    def test_learning_goal_path_routes_meta_to_the_counter(
        self, tmp_path, monkeypatch,
    ):
        """The META branch actually fires on the path the planner calls.

        Both executor paths funnel into update_learning_goal, which used to
        return early for anything that is not LEARNING -- that early return is
        why the contract clause stayed unimplemented in practice.
        """
        from agent_core.routing.handlers import update_learning_goal
        _verified(monkeypatch, {"a.txt"})
        store = _store(tmp_path)
        store.seed_if_empty()

        update_learning_goal(
            _MissionPlan("goal-meta-learn"), {"success": True}, store,
            _Analyzer(["a.txt", "b.txt"], total=2), None,
        )

        assert store.get("goal-meta-learn").progress == 0.5

    def test_no_analyzer_leaves_progress_untouched(self, tmp_path):
        """No measurement -> no write. A missing analyzer must not zero it."""
        from agent_core.routing.handlers import update_mission_progress
        store = _store(tmp_path)
        store.seed_if_empty()
        store.update_progress("goal-meta-learn", 0.61)

        assert update_mission_progress(
            store.get("goal-meta-learn"), store, None) is False
        assert store.get("goal-meta-learn").progress == 0.61


class _MissionPlan:
    """Plan shaped like the planner's, for the routing entry point."""

    def __init__(self, goal_id):
        self.goal_id = goal_id
        self.action_params = {}
        self.action_type = "learn"
