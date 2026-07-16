"""TIER 1.5 (Kronika): daily fetch cadence + B3 disarm exemption + feed-rot guard.

Reframed after the 2026-07-11 red-team (wf_f5f9aa9c) overturned the first plan:
goal-8dd9 is NOT fetch-bound (it owns a full 12/12 stamped pantry, 7 verified) --
it is exam-verification-bound, so cadence must SKIP full-pantry children and only
re-arm those still filling their pantry (goal-634f79.../goal-3a11cf... at 0/12).

The single predicate _is_cadence_fetch_goal (source_kind=='market' AND
len(market_file_ids) < provenance_target_n) gates BOTH the daily cadence re-arm
and the B3 stale-material disarm exemption, so 8dd9 falls through to LEARN/EXAM.

REAL GoalStore + PlannerCore (a MagicMock store hides the missing _mark_dirty that
would silently drop every metadata write -- the recurring bug this file guards).
Collaborators are specced() for the same reason: the 2026-07-14 sweep swapped the
bare MagicMocks here and immediately caught the TelegramNotifier.notify phantom
(see the xfail on test_alert_pings_operator_on_telegram).
"""

import time

import pytest

from agent_core.bulletin.bulletin_store import BulletinStore
from agent_core.goals.store import GoalStore
from agent_core.goals.goal_model import GoalType, GoalStatus, create_goal
from agent_core.planner.planner_core import PlannerCore, CADENCE_INTERVAL_SEC
from agent_core.planner.planner_model import create_plan, ActionType
from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
from agent_core.telegram.notifier import TelegramNotifier
from agent_core.tests.spec_helpers import specced


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # .env leaks into tests via load_dotenv() on import.
    monkeypatch.delenv("PROJECT_SELFHEAL_ENABLED", raising=False)
    monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "off")


def _store(tmp_path):
    return GoalStore(tmp_path / "goals.jsonl")


def _planner(tmp_path, store):
    p = PlannerCore(
        state_path=tmp_path / "state.json",
        decisions_path=tmp_path / "decisions.jsonl",
    )
    p.set_goal_store(store)
    return p


def _market_child(store, *, pantry_n=0, target_n=12, needs_fetch=None,
                  fetch_attempts=None, topics=None, source_kind="market",
                  deadline_offset=12 * 86400):
    """Parent project + one market child, return (parent_id, child_id)."""
    deadline = time.time() + deadline_offset
    parent_id = store.create(create_goal(
        GoalType.USER, "Kronika rynku", 0.6, status=GoalStatus.ACTIVE,
        deadline=deadline, metadata={"project": True, "subgoal_count": 1},
    ))
    meta = {
        "project_parent": parent_id,
        "provenance_target_n": target_n,
        "market_file_ids": [f"web_market_{i}.txt" for i in range(pantry_n)],
    }
    if source_kind is not None:
        meta["source_kind"] = source_kind
    if topics is not None:
        meta["topics"] = topics
    if needs_fetch is not None:
        meta["needs_fetch"] = needs_fetch
    if fetch_attempts is not None:
        meta["fetch_attempts"] = fetch_attempts
    child_id = store.create(create_goal(
        GoalType.USER, "srebro i zloto - kronika rynku", 0.6,
        status=GoalStatus.ACTIVE, parent_goal_id=parent_id, deadline=deadline,
        metadata=meta,
    ))
    store.save()
    return parent_id, child_id


# --------------------------------------------------------------------------- #
# PART 1 -- daily cadence re-arm (pantry-gated)
# --------------------------------------------------------------------------- #
class TestCadenceRearm:
    def test_rearms_burned_empty_pantry_child(self, tmp_path):
        # 634f79/3a11-like: empty pantry, one-shot cap burned -> cadence revives it.
        store = _store(tmp_path)
        _, cid = _market_child(store, pantry_n=0, needs_fetch=False,
                               fetch_attempts=3)
        planner = _planner(tmp_path, store)

        planner._maybe_rearm_cadence(store.get(cid))

        m = store.get(cid).metadata
        assert m["needs_fetch"] is True
        assert m["fetch_attempts"] == 0
        assert "last_cadence_rearm_at" in m

    def test_skips_full_pantry_child(self, tmp_path):
        # 8dd9-like: 12/12 stamped -> NOT re-armed (needs exam, not fetch).
        store = _store(tmp_path)
        _, cid = _market_child(store, pantry_n=12, target_n=12,
                               needs_fetch=False, fetch_attempts=3)
        planner = _planner(tmp_path, store)

        planner._maybe_rearm_cadence(store.get(cid))

        m = store.get(cid).metadata
        assert m["needs_fetch"] is False
        assert m["fetch_attempts"] == 3          # untouched
        assert "last_cadence_rearm_at" not in m  # never entered the re-arm

    def test_throttled_within_24h(self, tmp_path):
        # A second re-arm inside 24h is a no-op (1 re-arm/day).
        store = _store(tmp_path)
        _, cid = _market_child(store, pantry_n=2, needs_fetch=False,
                               fetch_attempts=3)
        planner = _planner(tmp_path, store)

        planner._maybe_rearm_cadence(store.get(cid))
        first_clock = store.get(cid).metadata["last_cadence_rearm_at"]
        # simulate a later fire that burned the fresh budget, then re-check soon
        c = store.get(cid)
        c.metadata["needs_fetch"] = False
        c.metadata["fetch_attempts"] = 3
        store._mark_dirty(cid)
        store.save()

        planner._maybe_rearm_cadence(store.get(cid))

        m = store.get(cid).metadata
        assert m["needs_fetch"] is False          # still throttled, not re-armed
        assert m["fetch_attempts"] == 3
        assert m["last_cadence_rearm_at"] == first_clock

    def test_rearms_again_after_24h(self, tmp_path):
        store = _store(tmp_path)
        _, cid = _market_child(store, pantry_n=2, needs_fetch=False,
                               fetch_attempts=3)
        c = store.get(cid)
        c.metadata["last_cadence_rearm_at"] = time.time() - (CADENCE_INTERVAL_SEC + 60)
        store._mark_dirty(cid)
        store.save()
        planner = _planner(tmp_path, store)

        planner._maybe_rearm_cadence(store.get(cid))

        m = store.get(cid).metadata
        assert m["needs_fetch"] is True
        assert m["fetch_attempts"] == 0

    def test_no_night_spin_when_already_armed(self, tmp_path):
        # Already armed + window-blocked: repeated ticks must NOT thrash the flag
        # or advance the clock every cycle (the night write-storm the red-team hit).
        store = _store(tmp_path)
        _, cid = _market_child(store, pantry_n=1, needs_fetch=True,
                               fetch_attempts=0)
        planner = _planner(tmp_path, store)

        planner._maybe_rearm_cadence(store.get(cid))
        clock = store.get(cid).metadata["last_cadence_rearm_at"]
        for _ in range(5):
            planner._maybe_rearm_cadence(store.get(cid))

        m = store.get(cid).metadata
        assert m["needs_fetch"] is True
        assert m["fetch_attempts"] == 0
        assert m["last_cadence_rearm_at"] == clock  # stamped once, then throttled

    def test_non_market_child_never_rearmed(self, tmp_path):
        store = _store(tmp_path)
        _, cid = _market_child(store, pantry_n=0, needs_fetch=False,
                               fetch_attempts=3, source_kind=None)
        planner = _planner(tmp_path, store)

        planner._maybe_rearm_cadence(store.get(cid))

        m = store.get(cid).metadata
        assert m["needs_fetch"] is False
        assert "last_cadence_rearm_at" not in m


# --------------------------------------------------------------------------- #
# PART 2 -- B3 stale-material disarm exemption
# --------------------------------------------------------------------------- #
class TestDisarmExemption:
    def test_market_below_pantry_not_disarmed_emits_fetch(self, tmp_path):
        # Reactivated market child WITH loose token-match material must still FETCH
        # (its material is not the stamped provenance the gate credits).
        store = _store(tmp_path)
        _, cid = _market_child(store, pantry_n=3, needs_fetch=True,
                               topics=["cena zlota"])
        planner = _planner(tmp_path, store)
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_files_for_topics.return_value = [("web_gold.txt", 0.9)]
        planner.set_knowledge_analyzer(analyzer)

        plan = planner._create_plan_for_goal(store.get(cid), {})

        assert plan.action_type == ActionType.FETCH
        refreshed = store.get(cid)
        assert refreshed.metadata["needs_fetch"] is False   # consumed by fire
        assert refreshed.metadata["fetch_attempts"] == 1

    def test_market_full_pantry_still_disarms(self, tmp_path):
        # A full-pantry market child that somehow got armed is NOT exempt -> disarm
        # so it falls through to LEARN/EXAM instead of fetching a useless 13th file.
        store = _store(tmp_path)
        _, cid = _market_child(store, pantry_n=12, target_n=12,
                               needs_fetch=True, topics=["cena zlota"])
        planner = _planner(tmp_path, store)
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_files_for_topics.return_value = [("web_gold.txt", 0.9)]
        planner.set_knowledge_analyzer(analyzer)

        plan = planner._create_plan_for_goal(store.get(cid), {})

        assert plan.action_type != ActionType.FETCH
        refreshed = store.get(cid)
        assert refreshed.metadata["needs_fetch"] is False
        assert "fetch_attempts" not in refreshed.metadata   # disarmed, none spent

    def test_non_market_child_still_disarms(self, tmp_path):
        # Regression guard for the 07-05 fix: a plain project child with material
        # still disarms (my B3 predicate keys on source_kind, not project_parent).
        store = _store(tmp_path)
        _, cid = _market_child(store, pantry_n=1, needs_fetch=True,
                               topics=["funding rate"], source_kind=None)
        planner = _planner(tmp_path, store)
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_files_for_topics.return_value = [("expert_f.txt", 4.5)]
        planner.set_knowledge_analyzer(analyzer)

        plan = planner._create_plan_for_goal(store.get(cid), {})

        assert plan.action_type != ActionType.FETCH
        refreshed = store.get(cid)
        assert refreshed.metadata["needs_fetch"] is False
        assert "fetch_attempts" not in refreshed.metadata

    def test_maybe_arm_fetch_exempts_market_below_pantry(self, tmp_path):
        # _maybe_arm_fetch material-check exemption (the second B3 site).
        store = _store(tmp_path)
        _, cid = _market_child(store, pantry_n=2, topics=["cena srebra"])
        planner = _planner(tmp_path, store)
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_files_for_topics.return_value = [("web_silver.txt", 0.8)]
        planner.set_knowledge_analyzer(analyzer)

        plan = create_plan(goal_id=cid, goal_description="x",
                           action_type=ActionType.EXAM, action_params={})
        planner._maybe_arm_fetch(plan, {"success": True})

        assert store.get(cid).metadata.get("needs_fetch") is True


# --------------------------------------------------------------------------- #
# PART 3 -- feed-rot guard
# --------------------------------------------------------------------------- #
class TestFeedRot:
    def _fetch_plan(self, cid):
        return create_plan(goal_id=cid, goal_description="x",
                           action_type=ActionType.FETCH, action_params={})

    def test_window_skip_not_counted(self, tmp_path):
        # skipped != failed: a window skip carries no articles_fetched key.
        store = _store(tmp_path)
        _, cid = _market_child(store, pantry_n=1)
        planner = _planner(tmp_path, store)

        planner._track_feed_rot(
            self._fetch_plan(cid),
            {"success": False, "skipped": True, "reason": "outside_learning_window"},
        )

        assert "barren_rounds" not in store.get(cid).metadata

    def test_barren_run_counted(self, tmp_path):
        store = _store(tmp_path)
        _, cid = _market_child(store, pantry_n=1)
        planner = _planner(tmp_path, store)

        planner._track_feed_rot(
            self._fetch_plan(cid),
            {"success": False, "skipped": True, "articles_fetched": 0, "errors": 0},
        )

        assert store.get(cid).metadata["barren_rounds"] == 1

    def test_error_run_not_counted(self, tmp_path):
        store = _store(tmp_path)
        _, cid = _market_child(store, pantry_n=1)
        planner = _planner(tmp_path, store)

        planner._track_feed_rot(
            self._fetch_plan(cid),
            {"success": False, "articles_fetched": 0, "errors": 2},
        )

        assert "barren_rounds" not in store.get(cid).metadata

    def test_productive_resets_counter(self, tmp_path):
        store = _store(tmp_path)
        _, cid = _market_child(store, pantry_n=1)
        c = store.get(cid)
        c.metadata["barren_rounds"] = 2
        store._mark_dirty(cid)
        store.save()
        planner = _planner(tmp_path, store)

        planner._track_feed_rot(
            self._fetch_plan(cid),
            {"success": True, "articles_fetched": 2, "errors": 0},
        )

        assert store.get(cid).metadata["barren_rounds"] == 0

    def test_alert_fires_exactly_once_at_threshold(self, tmp_path):
        store = _store(tmp_path)
        _, cid = _market_child(store, pantry_n=1)
        planner = _planner(tmp_path, store)
        bulletin = specced(BulletinStore)
        notifier = specced(TelegramNotifier)
        planner.set_bulletin_store(bulletin)
        planner.set_telegram_notifier(notifier)

        barren = {"success": False, "skipped": True, "articles_fetched": 0,
                  "errors": 0}
        for _ in range(5):
            planner._track_feed_rot(self._fetch_plan(cid), barren)

        assert bulletin.create_and_post.call_count == 1
        assert store.get(cid).metadata["barren_rounds"] == 5
        # bulletin call used keyword args (positional would misbind goal_id)
        _, kwargs = bulletin.create_and_post.call_args
        assert kwargs["reason_code"] == "feed_rot"
        assert kwargs["topic"] == "Kronika feed-rot"
        assert kwargs["goal_id"] == cid

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "MOCK-HIDDEN BUG (revealed by specced() 2026-07-14): "
            "planner_core._alert_feed_rot:4631 calls _telegram_notifier.notify("
            "'feed_rot', text), but TelegramNotifier has NO notify() method -- "
            "only notify_*() variants. Production wires the REAL TelegramNotifier "
            "(homeostasis_module:1297 -> telegram/__init__:37), so every feed-rot "
            "ping raises AttributeError, swallowed by the surrounding "
            "'except Exception: logger.debug(...)'. The operator has never been "
            "pinged about a dead market feed. Same phantom at planner_core:1189 "
            "(learning_complete harvest, 'except Exception: pass'). The old bare "
            "MagicMock auto-created .notify and made this assertion pass. "
            "Fix is a production decision (Eryk) -- not made in this sweep."
        ),
    )
    def test_alert_pings_operator_on_telegram(self, tmp_path):
        store = _store(tmp_path)
        _, cid = _market_child(store, pantry_n=1)
        planner = _planner(tmp_path, store)
        notifier = specced(TelegramNotifier)
        planner.set_telegram_notifier(notifier)

        barren = {"success": False, "skipped": True, "articles_fetched": 0,
                  "errors": 0}
        for _ in range(5):
            planner._track_feed_rot(self._fetch_plan(cid), barren)

        # A real TelegramNotifier has no .notify -- the ping never leaves.
        assert notifier.notify.call_count == 1

    def test_non_market_goal_never_alerts(self, tmp_path):
        store = _store(tmp_path)
        _, cid = _market_child(store, pantry_n=1, source_kind=None)
        planner = _planner(tmp_path, store)
        bulletin = specced(BulletinStore)
        planner.set_bulletin_store(bulletin)

        barren = {"success": False, "skipped": True, "articles_fetched": 0,
                  "errors": 0}
        for _ in range(4):
            planner._track_feed_rot(self._fetch_plan(cid), barren)

        assert "barren_rounds" not in store.get(cid).metadata
        assert bulletin.create_and_post.call_count == 0
