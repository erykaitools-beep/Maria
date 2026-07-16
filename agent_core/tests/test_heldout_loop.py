"""Tests for B4: the autonomous held-out exam loop + independent-exam closure.

The learning keystone end-to-end: a goal with an exam_independent criterion ->
planner emits EXAM for that file (flag-gated) -> handler examines it via the
held-out static grader -> goal closes ONLY on an independent verdict recorded in
exam_results.jsonl. A high but self-graded score must NOT close the goal (Q7:
no self-referential closure). Flag OFF -> nothing happens.
"""

import json
from types import SimpleNamespace

from agent_core.planner.planner_core import PlannerCore
from agent_core.planner.planner_model import ActionType, create_plan
from agent_core.goals.store import GoalStore
from agent_core.goals.goal_model import create_goal, GoalType, GoalStatus
from agent_core.routing.handlers import (
    make_exam_handler, seed_heldout_exam_goal,
)


def _planner(tmp_path):
    return PlannerCore(
        state_path=tmp_path / "state.json",
        decisions_path=tmp_path / "decisions.jsonl",
    )


def _make_exam_goal(file_id, results_path, status=GoalStatus.ACTIVE, min_score=0.6):
    return create_goal(
        GoalType.USER, f"prove {file_id}", 0.9, status=status,
        success_criteria=[{
            "type": "exam_independent", "file": file_id,
            "min_score": min_score, "results_path": str(results_path),
        }],
    )


def _write_exam_result(path, file_id, score, independent=True):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "file": file_id, "score": score, "grader_independent": independent,
            "grader_model": "heldout:static@v1" if independent else "llama3.1:8b",
            "student_model": "llama3.1:8b",
        }) + "\n")


def _fake_teacher(results_path, score, passed=None, independent=True):
    """A teacher whose _run_exam_fn writes one exam_results row and reports it."""
    if passed is None:
        passed = score >= 0.6

    def exam_fn(file_id):
        _write_exam_result(results_path, file_id, score, independent)
        return {"success": True, "passed": passed, "score": score, "file_id": file_id}

    return SimpleNamespace(_run_exam_fn=exam_fn)


# -------------------- _maybe_run_heldout_exam: flag gating + candidate --------------------

def test_heldout_flag_off_is_noop(tmp_path):
    p = _planner(tmp_path)
    store = GoalStore(tmp_path / "goals.jsonl")
    store.create(_make_exam_goal("f.txt", tmp_path / "r.jsonl"))
    p.set_goal_store(store)
    assert p._maybe_run_heldout_exam({}) is None  # flag default OFF -> no-op


def test_heldout_flag_on_emits_exam_plan_and_promotes(tmp_path):
    p = _planner(tmp_path)
    store = GoalStore(tmp_path / "goals.jsonl")
    g = _make_exam_goal(
        "web_wiki_chemia.txt", tmp_path / "r.jsonl", status=GoalStatus.PENDING)
    store.create(g)
    p.set_goal_store(store)
    p.set_heldout_enabled(True)

    plan = p._maybe_run_heldout_exam({})
    assert plan is not None
    assert plan.action_type == ActionType.EXAM
    assert plan.goal_id == g.id
    assert plan.action_params["target_file_id"] == "web_wiki_chemia.txt"
    assert plan.action_params["source"] == "heldout_drill"
    # committing work promotes PENDING -> ACTIVE so closure can auto-achieve
    assert store.get(g.id).status == GoalStatus.ACTIVE


def test_heldout_skips_and_closes_when_already_proven(tmp_path):
    # A criterion ALREADY met by a recorded independent exam: no re-exam (None),
    # AND the goal is CLOSED here -- otherwise it stays ACTIVE, gets re-picked as
    # a learn target every cycle, and loops to STUCK (the live bug from the
    # 2026-05-31 re-drill: a prior 0.625 chemia pass left the new goal stuck).
    results = tmp_path / "r.jsonl"
    _write_exam_result(results, "f.txt", 0.8)  # already passed an independent exam
    p = _planner(tmp_path)
    store = GoalStore(tmp_path / "goals.jsonl")
    g = _make_exam_goal("f.txt", results)
    store.create(g)
    p.set_goal_store(store)
    p.set_heldout_enabled(True)
    assert p._maybe_run_heldout_exam({}) is None  # criterion already met -> no re-exam
    closed = store.get(g.id)
    assert closed.status == GoalStatus.ACHIEVED          # ...but CLOSED, not stuck
    assert closed.outcome["closed_by"] == "success_criteria"


def test_heldout_ignores_goal_without_criteria(tmp_path):
    p = _planner(tmp_path)
    store = GoalStore(tmp_path / "goals.jsonl")
    store.create(create_goal(GoalType.USER, "no crit", 0.9, status=GoalStatus.ACTIVE))
    p.set_goal_store(store)
    p.set_heldout_enabled(True)
    assert p._maybe_run_heldout_exam({}) is None


# -------------------- handler: examine specific file + close on independent verdict --------------------

def test_exam_handler_examines_and_closes(tmp_path):
    results = tmp_path / "exam_results.jsonl"
    store = GoalStore(tmp_path / "goals.jsonl")
    g = _make_exam_goal("web_wiki_chemia.txt", results, status=GoalStatus.ACTIVE)
    store.create(g)
    teacher = _fake_teacher(results, score=0.83)
    handler = make_exam_handler(teacher, goal_store=store)
    plan = create_plan(g.id, "prove", ActionType.EXAM, {
        "target_file_id": "web_wiki_chemia.txt", "source": "heldout_drill",
    })
    result = handler(plan)

    assert result["success"] is True
    assert result["exams_passed"] == 1
    assert result["score"] == 0.83
    closed = store.get(g.id)
    assert closed.status == GoalStatus.ACHIEVED
    assert closed.outcome["closed_by"] == "success_criteria"


def test_exam_handler_failed_exam_keeps_goal_open(tmp_path):
    results = tmp_path / "exam_results.jsonl"
    store = GoalStore(tmp_path / "goals.jsonl")
    g = _make_exam_goal("f.txt", results, min_score=0.6)
    store.create(g)
    teacher = _fake_teacher(results, score=0.30)  # ran, but failed
    handler = make_exam_handler(teacher, goal_store=store)
    plan = create_plan(g.id, "x", ActionType.EXAM, {"target_file_id": "f.txt"})
    result = handler(plan)

    assert result["success"] is True       # the exam executed...
    assert result["exams_passed"] == 0      # ...but did not pass
    assert store.get(g.id).status == GoalStatus.ACTIVE  # goal stays open


def test_exam_handler_self_graded_high_score_does_not_close(tmp_path):
    # THE Q7 GUARANTEE: a 0.99 score that was NOT independently graded must not
    # close the goal -- the closer trusts only grader_independent==True records.
    results = tmp_path / "exam_results.jsonl"
    store = GoalStore(tmp_path / "goals.jsonl")
    g = _make_exam_goal("f.txt", results)
    store.create(g)
    teacher = _fake_teacher(results, score=0.99, passed=True, independent=False)
    handler = make_exam_handler(teacher, goal_store=store)
    plan = create_plan(g.id, "x", ActionType.EXAM, {"target_file_id": "f.txt"})
    handler(plan)
    assert store.get(g.id).status == GoalStatus.ACTIVE  # self-grade cannot close


# -------------------- seed helper + full end-to-end --------------------

def test_seed_heldout_exam_goal(tmp_path):
    store = GoalStore(tmp_path / "goals.jsonl")
    gid = seed_heldout_exam_goal(store, file_id="web_wiki_chemia.txt")
    assert gid is not None
    g = store.get(gid)
    assert g.status == GoalStatus.ACTIVE
    assert g.success_criteria[0]["type"] == "exam_independent"
    assert g.success_criteria[0]["file"] == "web_wiki_chemia.txt"


def test_end_to_end_heldout_loop(tmp_path):
    """seed-style goal -> planner emits EXAM -> handler examines -> goal ACHIEVED
    on the recorded independent verdict."""
    results = tmp_path / "exam_results.jsonl"
    store = GoalStore(tmp_path / "goals.jsonl")
    g = _make_exam_goal(
        "web_wiki_chemia.txt", results, status=GoalStatus.PENDING)
    store.create(g)

    p = _planner(tmp_path)
    p.set_goal_store(store)
    p.set_heldout_enabled(True)

    plan = p._maybe_run_heldout_exam({})
    assert plan is not None and plan.goal_id == g.id

    teacher = _fake_teacher(results, score=0.83)
    handler = make_exam_handler(teacher, goal_store=store)
    result = handler(plan)

    assert result["success"] is True
    closed = store.get(g.id)
    assert closed.status == GoalStatus.ACHIEVED              # goal closed...
    assert closed.outcome["closed_by"] == "success_criteria"  # ...on evidence
    assert closed.outcome["evidence"][0]["passed"] is True
    assert "heldout:static@v1" in closed.outcome["evidence"][0]["detail"]


# -------------------- runtime toggle + Telegram /heldout command --------------------

def test_set_heldout_enabled_runtime_toggle(tmp_path):
    p = _planner(tmp_path)
    p.set_heldout_enabled(True)
    assert p._heldout_enabled is True
    p.set_heldout_enabled(False)
    assert p._heldout_enabled is False


def test_heldout_telegram_command(tmp_path, monkeypatch):
    monkeypatch.setenv("HELDOUT_GRADER_ENABLED", "0")  # baseline, auto-restored
    from agent_core.modules.homeostasis_telegram_commands import register_telegram_commands as _register_telegram_commands

    class FakeBridge:
        def __init__(self):
            self.handlers = {}

        def register_command(self, command, handler):
            self.handlers[command] = handler

    p = _planner(tmp_path)
    store = GoalStore(tmp_path / "goals.jsonl")
    p.set_goal_store(store)
    ctx = SimpleNamespace(
        maria_conductor=None, self_perception=None, homeostasis_core=None,
        planner_core=p, knowledge_analyzer=None, goal_store=store,
        bulletin_store=None,
    )
    bridge = FakeBridge()
    _register_telegram_commands(bridge, ctx)
    cmd = bridge.handlers["heldout"]

    assert "planner=OFF" in cmd("")              # default status
    assert "ON" in cmd("on")                     # enable
    assert p._heldout_enabled is True
    assert "ACTIVE" in cmd("seed")               # create demo goal
    assert len(store.get_active()) == 1
    assert "exam_independent" in cmd("")         # status shows the open criterion goal
    assert "OFF" in cmd("off")                   # disable
    assert p._heldout_enabled is False


# -------------------- C8 (2026-07-12): per-exam grader scoping --------------------

def _stub_bank_coverage(monkeypatch, file_id, rows=3):
    """B4's coverage peek reads the LIVE default bank; stub it for tests."""
    import maria_core.learning.exam_agent as ea
    fake = [{"file": file_id, "q": f"q{i}", "match": "contains",
             "canonical": f"odp{i}", "bank_version": "v3"} for i in range(rows)]
    monkeypatch.setattr(ea, "load_heldout_bank", lambda *a, **k: fake)


def test_b4_plan_carries_grader_from_criterion(tmp_path, monkeypatch):
    """A criterion with grader='heldout' travels into the emitted plan's
    action_params -- mechanical grading is opted into PER EXAM, never by the
    global env flag (red-team CRITICAL #2: the blanket read would have flipped
    live Kronika reviews to the uncalibrated static grader)."""
    _stub_bank_coverage(monkeypatch, "web_rss_x.txt")
    results = tmp_path / "exam_results.jsonl"
    store = GoalStore(tmp_path / "goals.jsonl")
    g = create_goal(
        GoalType.USER, "projekt #3 child", 0.9, status=GoalStatus.ACTIVE,
        success_criteria=[{
            "type": "exam_independent", "file": "web_rss_x.txt",
            "grader": "heldout", "min_score": 0.6,
            "results_path": str(results),
        }],
    )
    store.create(g)
    p = _planner(tmp_path)
    p.set_goal_store(store)
    p.set_heldout_enabled(True)

    plan = p._maybe_run_heldout_exam({})
    assert plan is not None
    assert plan.action_params["grader"] == "heldout"
    assert plan.action_params["target_file_id"] == "web_rss_x.txt"


def test_b4_plan_without_grader_field_stays_unscoped(tmp_path):
    """Legacy criterion (no grader field) -> plan has no grader param -> the
    handler calls the exam fn positionally (old fakes/signatures stay valid)."""
    results = tmp_path / "exam_results.jsonl"
    store = GoalStore(tmp_path / "goals.jsonl")
    g = _make_exam_goal("web_wiki_chemia.txt", results)
    store.create(g)
    p = _planner(tmp_path)
    p.set_goal_store(store)
    p.set_heldout_enabled(True)

    plan = p._maybe_run_heldout_exam({})
    assert plan is not None
    assert "grader" not in plan.action_params


def test_exam_handler_passes_heldout_optin(tmp_path):
    """plan grader='heldout' -> handler calls exam fn with use_heldout=True."""
    results = tmp_path / "exam_results.jsonl"
    store = GoalStore(tmp_path / "goals.jsonl")
    g = _make_exam_goal("f.txt", results)
    store.create(g)
    seen = {}

    def exam_fn(file_id, use_heldout=False):
        seen["use_heldout"] = use_heldout
        _write_exam_result(results, file_id, 0.83)
        return {"success": True, "passed": True, "score": 0.83,
                "file_id": file_id}

    teacher = SimpleNamespace(_run_exam_fn=exam_fn)
    handler = make_exam_handler(teacher, goal_store=store)
    plan = create_plan(g.id, "x", ActionType.EXAM, {
        "target_file_id": "f.txt", "grader": "heldout",
    })
    result = handler(plan)
    assert result["success"] is True
    assert seen["use_heldout"] is True

    # No grader param -> positional call, use_heldout stays default False.
    seen.clear()
    plan2 = create_plan(g.id, "x", ActionType.EXAM, {"target_file_id": "f.txt"})
    handler(plan2)
    assert seen["use_heldout"] is False


def test_b4_partial_pantry_not_closed_drills_unmet(tmp_path):
    """Heldout child with target N=2 and only 1 seeded+passing criterion: B4
    must NOT close it (early-close guard) -- and since the only criterion is
    already met, there is nothing to drill this cycle."""
    results = tmp_path / "exam_results.jsonl"
    _write_exam_result(results, "a.txt", 0.9)  # heldout pass on record
    store = GoalStore(tmp_path / "goals.jsonl")
    g = create_goal(
        GoalType.USER, "projekt child", 0.9, status=GoalStatus.ACTIVE,
        success_criteria=[{
            "type": "exam_independent", "file": "a.txt", "grader": "heldout",
            "min_score": 0.6, "results_path": str(results),
        }],
        metadata={"project_parent": "g-p", "source_kind": "market",
                  "provenance_target_n": 2, "verification_mode": "heldout"},
    )
    store.create(g)
    p = _planner(tmp_path)
    p.set_goal_store(store)
    p.set_heldout_enabled(True)

    plan = p._maybe_run_heldout_exam({})
    assert plan is None
    refreshed = store.get(g.id)
    assert refreshed.status == GoalStatus.ACTIVE  # NOT closed at 1/2


def test_b4_no_bank_coverage_skips_with_cooldown(tmp_path, monkeypatch):
    """C3: a grader:heldout criterion with too few bank rows must NOT emit an
    EXAM (the fallback LLM record can never satisfy it -> burn loop); the goal
    gets a cooldown so B4 stops re-scanning it every cycle."""
    _stub_bank_coverage(monkeypatch, "web_rss_x.txt", rows=1)  # below minimum
    results = tmp_path / "exam_results.jsonl"
    store = GoalStore(tmp_path / "goals.jsonl")
    g = create_goal(
        GoalType.USER, "projekt child", 0.9, status=GoalStatus.ACTIVE,
        success_criteria=[{
            "type": "exam_independent", "file": "web_rss_x.txt",
            "grader": "heldout", "min_score": 0.6,
            "results_path": str(results),
        }],
    )
    store.create(g)
    p = _planner(tmp_path)
    p.set_goal_store(store)
    p.set_heldout_enabled(True)

    plan = p._maybe_run_heldout_exam({})
    assert plan is None
    # B4's OWN cooldown map, NOT the global selection filter: parking the goal
    # in stuck_cooldowns would also block its cadence FETCH -- the very thing
    # that fills the pantry (diff-review 2026-07-12).
    assert p._b4_cooldowns.get(g.id, 0) > 0
    assert g.id not in p._state.stuck_cooldowns

    # Cooldown respected on the next scan even with coverage now present.
    _stub_bank_coverage(monkeypatch, "web_rss_x.txt", rows=3)
    assert p._maybe_run_heldout_exam({}) is None


def test_b4_legacy_criterion_skips_bank_peek(tmp_path, monkeypatch):
    """No grader field -> the LLM examiner can satisfy the criterion, so the
    bank peek must not block emission (legacy /heldout seed keeps working)."""
    _stub_bank_coverage(monkeypatch, "other.txt", rows=0)  # empty bank
    results = tmp_path / "exam_results.jsonl"
    store = GoalStore(tmp_path / "goals.jsonl")
    g = _make_exam_goal("web_wiki_chemia.txt", results)
    store.create(g)
    p = _planner(tmp_path)
    p.set_goal_store(store)
    p.set_heldout_enabled(True)

    plan = p._maybe_run_heldout_exam({})
    assert plan is not None
    assert plan.action_params["target_file_id"] == "web_wiki_chemia.txt"


def test_b4_starved_file_does_not_block_covered_siblings(tmp_path, monkeypatch):
    """One uncoverable file (source gone, bank empty) must not starve the
    goal's OTHER unmet-but-covered files: B4 walks the unmet list and drills
    the first drillable one (diff-review 2026-07-12)."""
    import maria_core.learning.exam_agent as ea
    monkeypatch.delenv("HELDOUT_BANK_AUTHOR_ENABLED", raising=False)
    # Bank covers ONLY file b -- file a is permanently uncoverable.
    fake_bank = [
        {"file": "web_rss_b.txt", "q": f"q{i}", "match": "contains",
         "canonical": f"odp{i}", "bank_version": "v3"} for i in range(3)
    ]
    monkeypatch.setattr(ea, "load_heldout_bank", lambda *a, **k: fake_bank)

    results = tmp_path / "exam_results.jsonl"
    store = GoalStore(tmp_path / "goals.jsonl")
    g = create_goal(
        GoalType.USER, "projekt child", 0.9, status=GoalStatus.ACTIVE,
        success_criteria=[
            {"type": "exam_independent", "file": "web_rss_a.txt",
             "grader": "heldout", "min_score": 0.6,
             "results_path": str(results)},
            {"type": "exam_independent", "file": "web_rss_b.txt",
             "grader": "heldout", "min_score": 0.6,
             "results_path": str(results)},
        ],
    )
    store.create(g)
    p = _planner(tmp_path)
    p.set_goal_store(store)
    p.set_heldout_enabled(True)

    plan = p._maybe_run_heldout_exam({})
    assert plan is not None
    assert plan.action_params["target_file_id"] == "web_rss_b.txt"
