"""Tests for B3: Goal.success_criteria field + pure evaluator.

Covers (a) the additive schema field round-trips + stays backward-compatible
with legacy records, and (b) the pure, side-effect-free criterion evaluator.
"""

from agent_core.goals.goal_model import Goal, GoalType, create_goal
from agent_core.goals.success_criteria import (
    evaluate_criterion,
    evaluate_criteria,
    independently_verified_file_ids,
    is_independently_verified,
)


# --------------------------------------------------------------------------
# (a) schema field: round-trip + backward compatibility
# --------------------------------------------------------------------------

def test_success_criteria_defaults_none():
    g = create_goal(GoalType.USER, "x", 0.5)
    assert g.success_criteria is None


def test_create_goal_accepts_success_criteria():
    crit = [{"type": "file_exists", "path": "/tmp/x"}]
    g = create_goal(GoalType.USER, "x", 0.5, success_criteria=crit)
    assert g.success_criteria == crit


def test_to_dict_from_dict_roundtrip():
    crit = [{"type": "file_exists", "path": "/tmp/x"}]
    g = create_goal(GoalType.USER, "x", 0.5, success_criteria=crit)
    d = g.to_dict()
    assert d["success_criteria"] == crit
    g2 = Goal.from_dict(d)
    assert g2.success_criteria == crit


def test_from_dict_backward_compat_missing_field():
    # A legacy record (any of the 1138 live goals) has no success_criteria key.
    legacy = {
        "id": "goal-legacy", "type": "learning", "description": "old",
        "priority": 0.5, "status": "abandoned", "progress": 0.0,
        "parent_goal_id": None, "created_by": "system",
        "created_at": 1.0, "updated_at": 1.0,
    }
    g = Goal.from_dict(legacy)
    assert g.success_criteria is None  # no crash; defaults None


# --------------------------------------------------------------------------
# (b) evaluator: file_exists
# --------------------------------------------------------------------------

def test_file_exists_true(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hi")
    ok, ev = evaluate_criterion({"type": "file_exists", "path": str(f)})
    assert ok is True
    assert "present" in ev


def test_file_exists_false(tmp_path):
    ok, ev = evaluate_criterion(
        {"type": "file_exists", "path": str(tmp_path / "nope.txt")})
    assert ok is False
    assert "not found" in ev


def test_file_exists_missing_path():
    ok, ev = evaluate_criterion({"type": "file_exists"})
    assert ok is False
    assert "missing 'path'" in ev


def test_file_exists_sandbox_contained(tmp_path):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    f = sandbox / "in.txt"
    f.write_text("x")
    ok, ev = evaluate_criterion(
        {"type": "file_exists", "path": str(f)}, sandbox_root=str(sandbox))
    assert ok is True


def test_file_exists_sandbox_escape(tmp_path):
    # A path outside the sandbox root is rejected even though it exists.
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    ok, ev = evaluate_criterion(
        {"type": "file_exists", "path": str(outside)}, sandbox_root=str(sandbox))
    assert ok is False
    assert "escapes sandbox" in ev


def test_file_exists_symlink_rejected(tmp_path):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    target = sandbox / "real.txt"
    target.write_text("x")
    link = sandbox / "link.txt"
    link.symlink_to(target)
    ok, ev = evaluate_criterion(
        {"type": "file_exists", "path": str(link)}, sandbox_root=str(sandbox))
    assert ok is False
    assert "symlink" in ev


# --------------------------------------------------------------------------
# (b) evaluator: regex_in_log
# --------------------------------------------------------------------------

def test_regex_in_log_match(tmp_path):
    log = tmp_path / "log.jsonl"
    log.write_text('{"event":"first_action_ok"}\n')
    ok, ev = evaluate_criterion(
        {"type": "regex_in_log", "path": str(log), "pattern": "first_action_ok"})
    assert ok is True
    assert "matched" in ev


def test_regex_in_log_no_match(tmp_path):
    log = tmp_path / "log.jsonl"
    log.write_text('{"event":"something_else"}\n')
    ok, ev = evaluate_criterion(
        {"type": "regex_in_log", "path": str(log), "pattern": "first_action_ok"})
    assert ok is False


def test_regex_in_log_missing_file(tmp_path):
    ok, ev = evaluate_criterion(
        {"type": "regex_in_log", "path": str(tmp_path / "nope.log"), "pattern": "x"})
    assert ok is False
    assert "not found" in ev


def test_regex_in_log_bad_pattern(tmp_path):
    log = tmp_path / "log.txt"
    log.write_text("x")
    ok, ev = evaluate_criterion(
        {"type": "regex_in_log", "path": str(log), "pattern": "("})
    assert ok is False
    assert "bad pattern" in ev


# --------------------------------------------------------------------------
# (b) evaluator: exam_passed (delegated) + edge cases
# --------------------------------------------------------------------------

def test_exam_passed_no_checker():
    ok, ev = evaluate_criterion({"type": "exam_passed", "goal_id": "g1"})
    assert ok is False
    assert "no exam_checker" in ev


def test_exam_passed_with_checker():
    ok, ev = evaluate_criterion({"type": "exam_passed"}, exam_checker=lambda c: True)
    assert ok is True


def test_exam_passed_checker_raises_is_safe():
    def boom(_):
        raise RuntimeError("nope")
    ok, ev = evaluate_criterion({"type": "exam_passed"}, exam_checker=boom)
    assert ok is False
    assert "raised" in ev


def test_unknown_type():
    ok, ev = evaluate_criterion({"type": "teleport"})
    assert ok is False
    assert "unknown criterion type" in ev


# --------------------------------------------------------------------------
# (b) evaluator: exam_independent (B4 keystone) -- reads exam_results.jsonl,
# trusts ONLY entries graded by a non-student examiner (grader_independent).
# --------------------------------------------------------------------------

import json as _json


def _write_results(path, *records):
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(_json.dumps(rec) + "\n")


def _exam(file, score, independent=True, grader="heldout:static@v1"):
    return {
        "file": file, "timestamp": "2026-05-31T20:00:00", "score": score,
        "grader_independent": independent, "grader_model": grader,
        "student_model": "llama3.1:8b",
    }


def test_exam_independent_missing_file():
    ok, ev = evaluate_criterion({"type": "exam_independent", "min_score": 0.6})
    assert ok is False
    assert "missing 'file'" in ev


def test_exam_independent_results_not_found(tmp_path):
    ok, ev = evaluate_criterion({
        "type": "exam_independent", "file": "x.txt",
        "results_path": str(tmp_path / "nope.jsonl"),
    })
    assert ok is False
    assert "not found" in ev


def test_exam_independent_pass(tmp_path):
    res = tmp_path / "exam_results.jsonl"
    _write_results(res, _exam("web_wiki_chemia.txt", 0.83))
    ok, ev = evaluate_criterion({
        "type": "exam_independent", "file": "web_wiki_chemia.txt",
        "min_score": 0.6, "results_path": str(res),
    })
    assert ok is True
    assert "0.83" in ev and "heldout:static@v1" in ev


def test_exam_independent_below_threshold(tmp_path):
    res = tmp_path / "exam_results.jsonl"
    _write_results(res, _exam("web_wiki_chemia.txt", 0.4))
    ok, ev = evaluate_criterion({
        "type": "exam_independent", "file": "web_wiki_chemia.txt",
        "min_score": 0.6, "results_path": str(res),
    })
    assert ok is False
    assert "0.40 < 0.6" in ev


def test_exam_independent_ignores_self_graded(tmp_path):
    # A high score that was NOT independently graded must not close the goal.
    res = tmp_path / "exam_results.jsonl"
    _write_results(res, _exam("f.txt", 0.99, independent=False, grader="llama3.1:8b"))
    ok, ev = evaluate_criterion({
        "type": "exam_independent", "file": "f.txt", "results_path": str(res),
    })
    assert ok is False
    assert "no independent exam" in ev


def test_exam_independent_no_record_for_file(tmp_path):
    res = tmp_path / "exam_results.jsonl"
    _write_results(res, _exam("other.txt", 0.9))
    ok, ev = evaluate_criterion({
        "type": "exam_independent", "file": "wanted.txt", "results_path": str(res),
    })
    assert ok is False
    assert "no independent exam" in ev


def test_exam_independent_latest_wins_fresh_fail(tmp_path):
    # Old pass, newer independent fail -> goal must NOT be closed (last wins).
    res = tmp_path / "exam_results.jsonl"
    _write_results(
        res,
        _exam("f.txt", 0.9),   # earlier pass
        _exam("f.txt", 0.3),   # latest = fail
    )
    ok, ev = evaluate_criterion({
        "type": "exam_independent", "file": "f.txt", "results_path": str(res),
    })
    assert ok is False
    assert "0.30" in ev


def test_exam_independent_latest_wins_fresh_pass(tmp_path):
    res = tmp_path / "exam_results.jsonl"
    _write_results(
        res,
        _exam("f.txt", 0.3),   # earlier fail
        _exam("f.txt", 0.8),   # latest = pass
    )
    ok, _ = evaluate_criterion({
        "type": "exam_independent", "file": "f.txt", "results_path": str(res),
    })
    assert ok is True


def test_exam_independent_default_min_score(tmp_path):
    # No min_score given -> defaults to 0.6 (EXAM_PASS_THRESHOLD mirror).
    res = tmp_path / "exam_results.jsonl"
    _write_results(res, _exam("f.txt", 0.6))
    ok, _ = evaluate_criterion({
        "type": "exam_independent", "file": "f.txt", "results_path": str(res),
    })
    assert ok is True


def test_exam_independent_non_numeric_score(tmp_path):
    res = tmp_path / "exam_results.jsonl"
    _write_results(res, {
        "file": "f.txt", "score": "n/a", "grader_independent": True,
        "grader_model": "heldout:static@v1",
    })
    ok, ev = evaluate_criterion({
        "type": "exam_independent", "file": "f.txt", "results_path": str(res),
    })
    assert ok is False
    assert "non-numeric" in ev


def test_exam_independent_in_combinator(tmp_path):
    # AND with file_exists: both must hold.
    res = tmp_path / "exam_results.jsonl"
    _write_results(res, _exam("f.txt", 0.7))
    f = tmp_path / "marker.txt"
    f.write_text("x")
    crits = [
        {"type": "file_exists", "path": str(f)},
        {"type": "exam_independent", "file": "f.txt", "results_path": str(res)},
    ]
    ok, evidence = evaluate_criteria(crits)
    assert ok is True
    assert len(evidence) == 2 and all(e["passed"] for e in evidence)


def test_not_a_dict():
    ok, ev = evaluate_criterion("nope")
    assert ok is False


# --------------------------------------------------------------------------
# (b) combinator: AND semantics + empty guard
# --------------------------------------------------------------------------

def test_evaluate_criteria_all_pass(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    crits = [
        {"type": "file_exists", "path": str(f)},
        {"type": "regex_in_log", "path": str(f), "pattern": "x"},
    ]
    ok, evidence = evaluate_criteria(crits)
    assert ok is True
    assert len(evidence) == 2
    assert all(e["passed"] for e in evidence)


def test_evaluate_criteria_one_fails(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    crits = [
        {"type": "file_exists", "path": str(f)},
        {"type": "file_exists", "path": str(tmp_path / "missing")},
    ]
    ok, evidence = evaluate_criteria(crits)
    assert ok is False
    assert evidence[0]["passed"] is True
    assert evidence[1]["passed"] is False


def test_evaluate_criteria_empty_never_achieves():
    ok, _ = evaluate_criteria([])
    assert ok is False
    ok2, _ = evaluate_criteria(None)
    assert ok2 is False


# --------------------------------------------------------------------------
# (c) the shared trust predicate -- independently_verified_file_ids /
# is_independently_verified. Single source of truth consumed by the learning
# closer (reconciliation / update_learning_goal) AND the belief + index trust
# gates, so none of them trust a self-graded 'completed' status (audit
# 2026-06-01, #1-#3). A passing SELF-graded score must never qualify a file.
# --------------------------------------------------------------------------

def test_verified_ids_ignores_self_graded(tmp_path):
    res = tmp_path / "exam_results.jsonl"
    _write_results(
        res,
        _exam("indep.txt", 0.7),                                          # independent pass
        _exam("self.txt", 0.99, independent=False, grader="llama3.1:8b"),  # self-graded
    )
    assert independently_verified_file_ids(results_path=str(res)) == {"indep.txt"}


def test_verified_ids_threshold(tmp_path):
    res = tmp_path / "exam_results.jsonl"
    _write_results(res, _exam("low.txt", 0.4), _exam("ok.txt", 0.6))
    got = independently_verified_file_ids(min_score=0.6, results_path=str(res))
    assert got == {"ok.txt"}


def test_verified_ids_latest_independent_wins(tmp_path):
    # An old independent pass + a fresh independent fail -> NOT verified.
    res = tmp_path / "exam_results.jsonl"
    _write_results(res, _exam("f.txt", 0.9), _exam("f.txt", 0.3))
    assert independently_verified_file_ids(results_path=str(res)) == set()


def test_verified_ids_missing_file_is_empty():
    assert independently_verified_file_ids(results_path="/nonexistent/x.jsonl") == set()


def test_is_independently_verified_single(tmp_path):
    res = tmp_path / "exam_results.jsonl"
    _write_results(
        res,
        _exam("yes.txt", 0.8),
        _exam("no.txt", 0.95, independent=False, grader="llama3.1:8b"),
    )
    assert is_independently_verified("yes.txt", results_path=str(res)) is True
    assert is_independently_verified("no.txt", results_path=str(res)) is False
    assert is_independently_verified("", results_path=str(res)) is False
