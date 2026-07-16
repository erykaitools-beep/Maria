"""Option C (2026-07-12): heldout verification mode -- distinguishable stamp
and the closed doors.

Red-team wf_9716be07 CRITICAL #1 (gate-with-two-doors): the regular LLM examiner
also stamps grader_independent=True, so without a stricter predicate ANY exam
satisfied/overwrote a held-out verdict, and project children closed through the
progress doors (update_learning_goal + planner reconcile) that never read
success_criteria. These tests pin:

  1. heldout_verified_file_ids -- only grader_model 'heldout:*' records count;
     scan-filter semantics (a newer LLM record never shadows a held-out PASS,
     a newer held-out FAIL un-verifies).
  2. exam_independent criterion with {"grader": "heldout"} -- same in-scan
     filter; and the 2 MiB tail cap is GONE (old passes stay visible).
  3. Both progress doors: a goal with metadata verification_mode='heldout'
     advances ONLY on held-out verdicts; goals without the mode are unchanged.
"""

import json
import time

import pytest

from agent_core.goals.goal_model import Goal
from agent_core.planner.planner_model import Plan
from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
from agent_core.tests.spec_helpers import specced
from agent_core.goals.success_criteria import (
    evaluate_criterion,
    evaluate_criteria,
    heldout_verified_file_ids,
    independently_verified_file_ids,
    load_slim_exam_records,
)


def _write_results(path, records):
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _llm_rec(fid, score):
    return {"file": fid, "score": score, "grader_independent": True,
            "grader_model": "nim:dracarys-llama-3.1-70b-instruct"}


def _heldout_rec(fid, score):
    return {"file": fid, "score": score, "grader_independent": True,
            "grader_model": "heldout:static@v1"}


# --- 1. heldout_verified_file_ids ------------------------------------------------


class TestHeldoutVerifiedSet:
    def test_llm_records_do_not_count(self, tmp_path):
        p = tmp_path / "exam_results.jsonl"
        _write_results(p, [_llm_rec("a.txt", 0.9)])
        assert heldout_verified_file_ids(results_path=str(p)) == set()
        # ...while the broader bool predicate still admits them (unchanged).
        assert independently_verified_file_ids(results_path=str(p)) == {"a.txt"}

    def test_heldout_pass_counts(self, tmp_path):
        p = tmp_path / "exam_results.jsonl"
        _write_results(p, [_heldout_rec("a.txt", 0.8)])
        assert heldout_verified_file_ids(results_path=str(p)) == {"a.txt"}

    def test_newer_llm_record_does_not_shadow_heldout_pass(self, tmp_path):
        """Latest-wins applies WITHIN the heldout subset -- an LLM exam run
        after the held-out PASS must not flap the verdict (in-scan filter,
        not post-hoc on the globally-latest record)."""
        p = tmp_path / "exam_results.jsonl"
        _write_results(p, [
            _heldout_rec("a.txt", 0.8),
            _llm_rec("a.txt", 0.2),   # newer, non-heldout -> invisible here
        ])
        assert heldout_verified_file_ids(results_path=str(p)) == {"a.txt"}

    def test_newer_heldout_fail_unverifies(self, tmp_path):
        p = tmp_path / "exam_results.jsonl"
        _write_results(p, [
            _heldout_rec("a.txt", 0.8),
            _heldout_rec("a.txt", 0.2),  # newer heldout FAIL wins
        ])
        assert heldout_verified_file_ids(results_path=str(p)) == set()

    def test_shared_records_map_serves_both_predicates(self, tmp_path):
        p = tmp_path / "exam_results.jsonl"
        _write_results(p, [_llm_rec("a.txt", 0.9), _heldout_rec("b.txt", 0.9)])
        records = load_slim_exam_records(str(p))
        assert independently_verified_file_ids(exam_records=records) == {
            "a.txt", "b.txt"}
        assert heldout_verified_file_ids(exam_records=records) == {"b.txt"}


# --- 2. exam_independent criterion with grader field ------------------------------


class TestCriterionGraderField:
    def test_grader_heldout_ignores_llm_records(self, tmp_path):
        p = tmp_path / "exam_results.jsonl"
        _write_results(p, [_llm_rec("a.txt", 0.95)])
        crit = {"type": "exam_independent", "file": "a.txt",
                "grader": "heldout", "results_path": str(p)}
        passed, detail = evaluate_criterion(crit)
        assert passed is False
        assert "heldout:" in detail

    def test_grader_heldout_scan_filter_not_post_hoc(self, tmp_path):
        """A newer LLM record after a valid held-out PASS must not un-close the
        criterion (red-team HIGH: post-hoc filtering on the latest independent
        record would flap the goal)."""
        p = tmp_path / "exam_results.jsonl"
        _write_results(p, [
            _heldout_rec("a.txt", 0.85),
            _llm_rec("a.txt", 0.1),
        ])
        crit = {"type": "exam_independent", "file": "a.txt",
                "grader": "heldout", "results_path": str(p)}
        passed, detail = evaluate_criterion(crit)
        assert passed is True
        assert "heldout:static@v1" in detail

    def test_criterion_without_grader_unchanged(self, tmp_path):
        """No grader field -> any independent record satisfies (old behavior)."""
        p = tmp_path / "exam_results.jsonl"
        _write_results(p, [_llm_rec("a.txt", 0.7)])
        crit = {"type": "exam_independent", "file": "a.txt",
                "results_path": str(p)}
        passed, _ = evaluate_criterion(crit)
        assert passed is True

    def test_no_tail_cap_old_pass_visible(self, tmp_path):
        """The old 2 MiB tail cap hid passes older than the tail (live file is
        ~5.9 MB). Full read: a pass buried behind >2 MiB of later records is
        still found."""
        p = tmp_path / "exam_results.jsonl"
        filler = [{"file": f"junk_{i}.txt", "score": 0.0,
                   "grader_independent": False,
                   "grader_model": "x", "padding": "z" * 512}
                  for i in range(5000)]  # ~3 MB of later records
        _write_results(p, [_heldout_rec("old.txt", 0.9)] + filler)
        assert p.stat().st_size > 2 * 1024 * 1024
        crit = {"type": "exam_independent", "file": "old.txt",
                "grader": "heldout", "results_path": str(p)}
        passed, _ = evaluate_criterion(crit)
        assert passed is True

    def test_evaluate_criteria_amortized_map(self, tmp_path, monkeypatch):
        """Many exam_independent criteria on one goal trigger ONE results read
        (the map is built once and threaded through)."""
        import agent_core.goals.success_criteria as sc
        p = tmp_path / "exam_results.jsonl"
        _write_results(p, [_heldout_rec("a.txt", 0.9), _heldout_rec("b.txt", 0.9)])
        monkeypatch.setattr(
            "maria_core.sys.config.EXAM_RESULTS", p, raising=False)
        calls = {"n": 0}
        real_loader = sc.load_slim_exam_records

        def counting_loader(*a, **k):
            calls["n"] += 1
            return real_loader(*a, **k)

        monkeypatch.setattr(sc, "load_slim_exam_records", counting_loader)
        crits = [
            {"type": "exam_independent", "file": "a.txt", "grader": "heldout"},
            {"type": "exam_independent", "file": "b.txt", "grader": "heldout"},
        ]
        passed, evidence = evaluate_criteria(crits)
        assert passed is True
        assert calls["n"] == 1


# --- 3. The progress doors --------------------------------------------------------


def _snapshot(completed_ids):
    return {"files_by_status": {
        "completed": [{"id": f, "file": f} for f in completed_ids],
    }}


class TestUpdateLearningGoalDoor:
    """Door 2: post-exam progress credit must ignore LLM verdicts for
    heldout-mode goals."""

    def _goal_store(self, tmp_path):
        from agent_core.goals.store import GoalStore
        return GoalStore(tmp_path / "goals.jsonl")

    def _heldout_goal(self, gid="g-h"):
        from agent_core.goals.goal_model import Goal, GoalType, GoalStatus
        return Goal(
            id=gid, type=GoalType.USER, description="projekt #3 child",
            priority=0.6, status=GoalStatus.ACTIVE, progress=0.0,
            parent_goal_id="g-parent", created_by="operator",
            created_at=time.time(), updated_at=time.time(),
            metadata={"project_parent": "g-parent", "source_kind": "market",
                      "provenance_target_n": 2,
                      "verification_mode": "heldout",
                      "market_file_ids": ["a.txt", "b.txt"]},
        )

    def _run(self, tmp_path, monkeypatch, records):
        from agent_core.routing.handlers import update_learning_goal
        results = tmp_path / "exam_results.jsonl"
        _write_results(results, records)
        monkeypatch.setattr(
            "maria_core.sys.config.EXAM_RESULTS", results, raising=False)
        store = self._goal_store(tmp_path)
        store.create(self._heldout_goal())
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_knowledge_snapshot.return_value = _snapshot(
            ["a.txt", "b.txt"])
        plan = specced(Plan, goal_id="g-h", action_params={})
        update_learning_goal(
            plan, {"exams_passed": 1, "score": 0.9}, store, analyzer, None)
        return store.get("g-h")

    def test_llm_verified_does_not_advance_heldout_goal(
            self, tmp_path, monkeypatch):
        goal = self._run(tmp_path, monkeypatch, [
            _llm_rec("a.txt", 0.9), _llm_rec("b.txt", 0.9),
        ])
        assert goal.progress == 0.0
        assert goal.status.value == "active"

    def test_heldout_verified_advances_and_closes(self, tmp_path, monkeypatch):
        goal = self._run(tmp_path, monkeypatch, [
            _heldout_rec("a.txt", 0.9), _heldout_rec("b.txt", 0.9),
        ])
        assert goal.progress == 1.0
        assert goal.status.value == "achieved"

    def test_partial_heldout_partial_llm(self, tmp_path, monkeypatch):
        goal = self._run(tmp_path, monkeypatch, [
            _heldout_rec("a.txt", 0.9), _llm_rec("b.txt", 0.9),
        ])
        assert goal.progress == 0.5
        assert goal.status.value == "active"


class TestReconcileDoor:
    """Door 3: the planner reconcile sweep must ignore LLM verdicts for
    heldout-mode goals (and keep harvesting plain goals unchanged)."""

    def _planner(self, tmp_path, monkeypatch):
        from agent_core.planner.planner_core import PlannerCore
        for flag in ("STRATEGIC_PLANNER_DRIVES", "FS_WRITE_ENABLED",
                     "HELDOUT_GRADER_ENABLED"):
            monkeypatch.delenv(flag, raising=False)
        return PlannerCore(
            state_path=tmp_path / "planner_state.json",
            decisions_path=tmp_path / "planner_decisions.jsonl",
        )

    def _run(self, tmp_path, monkeypatch, records, goal_meta):
        from agent_core.goals.store import GoalStore
        from agent_core.goals.goal_model import Goal, GoalType, GoalStatus
        results = tmp_path / "exam_results.jsonl"
        _write_results(results, records)
        monkeypatch.setattr(
            "maria_core.sys.config.EXAM_RESULTS", results, raising=False)
        planner = self._planner(tmp_path, monkeypatch)
        store = GoalStore(tmp_path / "goals.jsonl")
        goal = Goal(
            id="g-r", type=GoalType.USER, description="projekt child",
            priority=0.6, status=GoalStatus.ACTIVE, progress=0.0,
            parent_goal_id="g-parent", created_by="operator",
            created_at=time.time(), updated_at=time.time(),
            metadata=goal_meta,
        )
        store.create(goal)
        planner.set_goal_store(store)
        analyzer = specced(KnowledgeAnalyzer)
        planner.set_knowledge_analyzer(analyzer)
        ctx = {"knowledge_snapshot": _snapshot(["a.txt", "b.txt"])}
        planner._reconcile_learning_goals(ctx)
        return store.get("g-r")

    def _meta(self, mode=None):
        meta = {"project_parent": "g-parent", "source_kind": "market",
                "provenance_target_n": 2,
                "market_file_ids": ["a.txt", "b.txt"]}
        if mode:
            meta["verification_mode"] = mode
        return meta

    def test_heldout_goal_not_harvested_on_llm_verdicts(
            self, tmp_path, monkeypatch):
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "cutover")
        goal = self._run(
            tmp_path, monkeypatch,
            [_llm_rec("a.txt", 0.9), _llm_rec("b.txt", 0.9)],
            self._meta(mode="heldout"),
        )
        assert goal.progress == 0.0
        assert goal.status.value == "active"

    def test_heldout_goal_harvested_on_heldout_verdicts(
            self, tmp_path, monkeypatch):
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "cutover")
        goal = self._run(
            tmp_path, monkeypatch,
            [_heldout_rec("a.txt", 0.9), _heldout_rec("b.txt", 0.9)],
            self._meta(mode="heldout"),
        )
        assert goal.progress == 1.0
        assert goal.status.value == "achieved"

    def test_plain_market_goal_unchanged_on_llm_verdicts(
            self, tmp_path, monkeypatch):
        """No verification_mode (live Kronika shape) -> the bool predicate keeps
        harvesting exactly as before Option C."""
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "cutover")
        goal = self._run(
            tmp_path, monkeypatch,
            [_llm_rec("a.txt", 0.9), _llm_rec("b.txt", 0.9)],
            self._meta(mode=None),
        )
        assert goal.progress == 1.0
        assert goal.status.value == "achieved"


class TestCriteriaCloseGuard:
    """close_goal_on_criteria must not close a heldout project child before its
    pantry is fully criteria'd (6/12 criteria all passing is NOT done)."""

    def test_partial_criteria_do_not_close(self, tmp_path, monkeypatch):
        from agent_core.goals.store import GoalStore
        from agent_core.goals.goal_model import Goal, GoalType, GoalStatus
        from agent_core.routing.handlers import close_goal_on_criteria
        results = tmp_path / "exam_results.jsonl"
        _write_results(results, [_heldout_rec("a.txt", 0.9)])
        store = GoalStore(tmp_path / "goals.jsonl")
        goal = Goal(
            id="g-c", type=GoalType.USER, description="child",
            priority=0.6, status=GoalStatus.ACTIVE, progress=0.0,
            parent_goal_id="g-p", created_by="operator",
            created_at=time.time(), updated_at=time.time(),
            metadata={"project_parent": "g-p", "source_kind": "market",
                      "provenance_target_n": 2,
                      "verification_mode": "heldout"},
            success_criteria=[{
                "type": "exam_independent", "file": "a.txt",
                "grader": "heldout", "results_path": str(results),
            }],  # only 1 of target 2 seeded so far -- and it passes
        )
        store.create(goal)
        plan = specced(Plan, goal_id="g-c")
        close_goal_on_criteria(plan, {}, store)
        refreshed = store.get("g-c")
        assert refreshed.status.value == "active"
        assert refreshed.progress == 0.0

    def test_full_criteria_close(self, tmp_path, monkeypatch):
        from agent_core.goals.store import GoalStore
        from agent_core.goals.goal_model import Goal, GoalType, GoalStatus
        from agent_core.routing.handlers import close_goal_on_criteria
        results = tmp_path / "exam_results.jsonl"
        _write_results(results, [
            _heldout_rec("a.txt", 0.9), _heldout_rec("b.txt", 0.9)])
        store = GoalStore(tmp_path / "goals.jsonl")
        goal = Goal(
            id="g-c2", type=GoalType.USER, description="child",
            priority=0.6, status=GoalStatus.ACTIVE, progress=0.0,
            parent_goal_id="g-p", created_by="operator",
            created_at=time.time(), updated_at=time.time(),
            metadata={"project_parent": "g-p", "source_kind": "market",
                      "provenance_target_n": 2,
                      "verification_mode": "heldout"},
            success_criteria=[
                {"type": "exam_independent", "file": "a.txt",
                 "grader": "heldout", "results_path": str(results)},
                {"type": "exam_independent", "file": "b.txt",
                 "grader": "heldout", "results_path": str(results)},
            ],
        )
        store.create(goal)
        plan = specced(Plan, goal_id="g-c2")
        close_goal_on_criteria(plan, {}, store)
        refreshed = store.get("g-c2")
        assert refreshed.status.value == "achieved"


class TestStampAppendsCriteria:
    """C6: the criterion writer at the fetch seam -- each stamped pantry file
    on a heldout-mode goal gets its exam_independent{grader:heldout} entry."""

    def _goal(self, meta, criteria=None):
        from agent_core.goals.goal_model import Goal, GoalType, GoalStatus
        return Goal(
            id="g-s", type=GoalType.USER, description="child",
            priority=0.6, status=GoalStatus.ACTIVE, progress=0.0,
            parent_goal_id="g-p", created_by="operator",
            created_at=time.time(), updated_at=time.time(),
            metadata=meta, success_criteria=criteria or [],
        )

    def _stamp(self, tmp_path, goal, files):
        from agent_core.goals.store import GoalStore
        from agent_core.routing.handlers import stamp_market_provenance
        store = GoalStore(tmp_path / "goals.jsonl")
        store.create(goal)
        plan = specced(Plan, goal_id="g-s")
        stamp_market_provenance(plan, files, store)
        return store.get("g-s")

    def test_heldout_goal_gets_criteria_per_file(self, tmp_path):
        goal = self._goal({
            "project_parent": "g-p", "source_kind": "market",
            "provenance_target_n": 3, "verification_mode": "heldout",
        })
        refreshed = self._stamp(tmp_path, goal, ["a.txt", "b.txt"])
        crits = refreshed.success_criteria
        assert len(crits) == 2
        assert all(c["type"] == "exam_independent" for c in crits)
        assert all(c["grader"] == "heldout" for c in crits)
        assert {c["file"] for c in crits} == {"a.txt", "b.txt"}
        assert all(c["min_score"] == 0.6 for c in crits)

    def test_criteria_deduped_and_capped_at_n(self, tmp_path):
        goal = self._goal(
            {"project_parent": "g-p", "source_kind": "market",
             "provenance_target_n": 2, "verification_mode": "heldout",
             "market_file_ids": ["a.txt"]},
            criteria=[{"type": "exam_independent", "file": "a.txt",
                       "grader": "heldout", "min_score": 0.6}],
        )
        refreshed = self._stamp(
            tmp_path, goal, ["a.txt", "b.txt", "c.txt", "d.txt"])
        crits = refreshed.success_criteria
        assert len(crits) == 2  # dedup a.txt, cap N=2 -> only b.txt added
        assert {c["file"] for c in crits} == {"a.txt", "b.txt"}

    def test_min_score_knob_from_metadata(self, tmp_path):
        """C7 calibration writes heldout_min_score into goal metadata; new
        criteria pick it up."""
        goal = self._goal({
            "project_parent": "g-p", "source_kind": "market",
            "provenance_target_n": 3, "verification_mode": "heldout",
            "heldout_min_score": 0.5,
        })
        refreshed = self._stamp(tmp_path, goal, ["a.txt"])
        assert refreshed.success_criteria[0]["min_score"] == 0.5

    def test_kronika_shape_gets_no_criteria(self, tmp_path):
        """Live Kronika (market, NO verification_mode): stamp keeps working,
        criteria are NOT appended -- her closure path is untouched."""
        goal = self._goal({
            "project_parent": "g-p", "source_kind": "market",
            "provenance_target_n": 12,
        })
        refreshed = self._stamp(tmp_path, goal, ["a.txt", "b.txt"])
        assert refreshed.success_criteria == []
        assert refreshed.metadata["market_file_ids"] == ["a.txt", "b.txt"]


# --- Diff-review fixes (2026-07-12) ------------------------------------------------


class TestPerLaneBroadPredicate:
    """Fix E: latest-wins is tracked PER EXAMINER KIND in the broad predicate --
    shared slug-named files between a heldout project and Kronika must not
    cross-demote each other's verdicts."""

    def test_heldout_fail_does_not_erase_llm_pass(self, tmp_path):
        p = tmp_path / "exam_results.jsonl"
        _write_results(p, [
            _llm_rec("shared.txt", 0.83),      # Kronika's LLM pass
            _heldout_rec("shared.txt", 0.2),   # newer mechanical FAIL
        ])
        assert independently_verified_file_ids(
            results_path=str(p)) == {"shared.txt"}
        # ...while the strict heldout lane honestly reports the fail.
        assert heldout_verified_file_ids(results_path=str(p)) == set()

    def test_llm_fail_does_not_erase_heldout_pass(self, tmp_path):
        p = tmp_path / "exam_results.jsonl"
        _write_results(p, [
            _heldout_rec("shared.txt", 0.9),
            _llm_rec("shared.txt", 0.2),
        ])
        assert independently_verified_file_ids(
            results_path=str(p)) == {"shared.txt"}

    def test_both_lanes_failing_not_verified(self, tmp_path):
        p = tmp_path / "exam_results.jsonl"
        _write_results(p, [
            _llm_rec("shared.txt", 0.9),
            _llm_rec("shared.txt", 0.3),      # LLM lane latest: fail
            _heldout_rec("shared.txt", 0.2),  # heldout lane latest: fail
        ])
        assert independently_verified_file_ids(results_path=str(p)) == set()


class TestMinScoreKnobReachesDoors:
    """Fix HIGH: heldout_min_score must govern the PROGRESS doors, not only the
    criteria -- a calibrated bar of 0.8 with files at 0.7 must not auto-achieve."""

    def _run_door2(self, tmp_path, monkeypatch, min_score_meta, scores):
        from agent_core.goals.store import GoalStore
        from agent_core.goals.goal_model import Goal, GoalType, GoalStatus
        from agent_core.routing.handlers import update_learning_goal
        results = tmp_path / "exam_results.jsonl"
        _write_results(results, [_heldout_rec("a.txt", scores[0]),
                                 _heldout_rec("b.txt", scores[1])])
        monkeypatch.setattr(
            "maria_core.sys.config.EXAM_RESULTS", results, raising=False)
        store = GoalStore(tmp_path / "goals.jsonl")
        meta = {"project_parent": "g-p", "source_kind": "market",
                "provenance_target_n": 2, "verification_mode": "heldout",
                "market_file_ids": ["a.txt", "b.txt"]}
        meta.update(min_score_meta)
        goal = Goal(
            id="g-cal", type=GoalType.USER, description="child",
            priority=0.6, status=GoalStatus.ACTIVE, progress=0.0,
            parent_goal_id="g-p", created_by="operator",
            created_at=time.time(), updated_at=time.time(), metadata=meta,
        )
        store.create(goal)
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_knowledge_snapshot.return_value = _snapshot(
            ["a.txt", "b.txt"])
        plan = specced(Plan, goal_id="g-cal", action_params={})
        update_learning_goal(
            plan, {"exams_passed": 1, "score": 0.9}, store, analyzer, None)
        return store.get("g-cal")

    def test_calibrated_bar_blocks_door2(self, tmp_path, monkeypatch):
        goal = self._run_door2(
            tmp_path, monkeypatch, {"heldout_min_score": 0.8}, [0.7, 0.7])
        assert goal.progress == 0.0
        assert goal.status.value == "active"

    def test_calibrated_bar_passes_when_cleared(self, tmp_path, monkeypatch):
        goal = self._run_door2(
            tmp_path, monkeypatch, {"heldout_min_score": 0.8}, [0.85, 0.9])
        assert goal.progress == 1.0
        assert goal.status.value == "achieved"

    def test_calibrated_bar_blocks_reconcile_door(self, tmp_path, monkeypatch):
        from agent_core.planner.planner_core import PlannerCore
        from agent_core.goals.store import GoalStore
        from agent_core.goals.goal_model import Goal, GoalType, GoalStatus
        for flag in ("STRATEGIC_PLANNER_DRIVES", "FS_WRITE_ENABLED",
                     "HELDOUT_GRADER_ENABLED"):
            monkeypatch.delenv(flag, raising=False)
        results = tmp_path / "exam_results.jsonl"
        _write_results(results, [_heldout_rec("a.txt", 0.7),
                                 _heldout_rec("b.txt", 0.7)])
        monkeypatch.setattr(
            "maria_core.sys.config.EXAM_RESULTS", results, raising=False)
        planner = PlannerCore(
            state_path=tmp_path / "planner_state.json",
            decisions_path=tmp_path / "planner_decisions.jsonl",
        )
        store = GoalStore(tmp_path / "goals.jsonl")
        goal = Goal(
            id="g-rc", type=GoalType.USER, description="child",
            priority=0.6, status=GoalStatus.ACTIVE, progress=0.0,
            parent_goal_id="g-p", created_by="operator",
            created_at=time.time(), updated_at=time.time(),
            metadata={"project_parent": "g-p", "source_kind": "market",
                      "provenance_target_n": 2,
                      "verification_mode": "heldout",
                      "heldout_min_score": 0.8,
                      "market_file_ids": ["a.txt", "b.txt"]},
        )
        store.create(goal)
        planner.set_goal_store(store)
        planner.set_knowledge_analyzer(specced(KnowledgeAnalyzer))
        planner._reconcile_learning_goals(
            {"knowledge_snapshot": _snapshot(["a.txt", "b.txt"])})
        refreshed = store.get("g-rc")
        assert refreshed.progress == 0.0
        assert refreshed.status.value == "active"


class TestHeldoutOwnershipGateIndependent:
    """Fix B: a heldout goal owns EXACTLY market_file_ids under EVERY gate mode
    -- token-match cross-crediting between siblings is impossible."""

    def test_gate_off_still_provenance_only(self, monkeypatch):
        from agent_core.routing.handlers import resolve_goal_files
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "off")
        goal = specced(Goal, metadata={
            "project_parent": "g-p", "source_kind": "market",
            "verification_mode": "heldout",
            "market_file_ids": ["mine.txt"],
            "topics": ["srebro zloto BTC"]})
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_files_for_topics.return_value = [
            ("siblings_file.txt", 1.0)]
        assert resolve_goal_files(goal, None, analyzer) == ["mine.txt"]

    def test_gate_off_empty_pantry_owns_nothing(self, monkeypatch):
        from agent_core.routing.handlers import resolve_goal_files
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "off")
        goal = specced(Goal, metadata={
            "project_parent": "g-p", "source_kind": "market",
            "verification_mode": "heldout",
            "topics": ["srebro"]})
        analyzer = specced(KnowledgeAnalyzer)
        analyzer.get_files_for_topics.return_value = [("junk.txt", 1.0)]
        assert resolve_goal_files(goal, None, analyzer) == []


class TestOneShotExemption:
    """Fix D: a one-shot action (critique/self_analyze/creative) must never
    ACHIEVE a heldout goal, under ANY gate mode."""

    def test_oneshot_cannot_close_heldout_goal(self, tmp_path, monkeypatch):
        from agent_core.planner.action_executor import ActionExecutor
        from agent_core.goals.store import GoalStore
        from agent_core.goals.goal_model import Goal, GoalType, GoalStatus
        monkeypatch.setenv("KRONIKA_PROVENANCE_GATE", "off")
        store = GoalStore(tmp_path / "goals.jsonl")
        goal = Goal(
            id="g-os", type=GoalType.USER, description="child",
            priority=0.6, status=GoalStatus.ACTIVE, progress=0.0,
            parent_goal_id="g-p", created_by="operator",
            created_at=time.time(), updated_at=time.time(),
            metadata={"project_parent": "g-p", "source_kind": "market",
                      "verification_mode": "heldout"},
        )
        store.create(goal)
        executor = ActionExecutor.__new__(ActionExecutor)
        executor._goal_store = store
        plan = specced(Plan, goal_id="g-os")
        executor._complete_oneshot_goal(plan, {"done": True})
        refreshed = store.get("g-os")
        assert refreshed.status.value == "active"
        assert refreshed.progress == 0.0
