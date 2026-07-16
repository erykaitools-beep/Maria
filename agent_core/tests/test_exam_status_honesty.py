"""Tests for 2026-07-15 fix: the index must not call a failed exam 'completed'.

Root cause: `is_spaced = target_file_id is not None` asked "did a caller name a
file?", not "is this a repeat of material already passed?". Every production
caller names a file (teacher_module.py:487, synthesis_agent.py:788, /egzamin),
so EVERY exam took the spaced-repetition branch -- which stamps STATUS_COMPLETED
before `passed` is ever consulted.

In vivo (audit 2026-07-15): web_rss_francuski_naukowiec... scored 0.55 against a
0.6 threshold -- failed its only exam -- and sat in the index as `completed`.
The journal showed 0x [PASS] / 0x [FAIL] and only [REVIEW PASS]/[REVIEW FAIL],
i.e. the honest branches never ran.

is_spaced now means status == COMPLETED (a genuine repeat), captured before the
exam mutates anything.
"""

import json

from maria_core.learning import exam_agent


def _write_index(path, record):
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


def _write_memory(path, file_id):
    path.write_text(
        json.dumps({
            "source_file": file_id,
            "folder": "root",
            "chunk_id": f"{file_id}#chunk_0",
            "chunk_index": 0,
            "summary": "Streszczenie materialu do egzaminu.",
            "key_points": ["punkt 1", "punkt 2"],
            "tags": ["test"],
        }) + "\n",
        encoding="utf-8",
    )


def _record(status, attempts=0, scores=None):
    return {
        "id": "test_file.txt",
        "folder": "root",
        "file": "test_file.txt",
        "status": status,
        "priority": 50.0,
        "hash": "xyz",
        "created_at": "2026-07-01T00:00:00.000000Z",
        "updated_at": "2026-07-01T00:00:00.000000Z",
        "exam_attempts": attempts,
        "last_scores": scores if scores is not None else [],
        "chunks_learned": 1,
        "total_chunks": 1,
    }


def _llm_scoring(per_question_score):
    """A single fake model playing all three roles, keyed off the prompt.

    Drives the REAL generate_exam/answer_exam/grade_exam pipeline -- only the
    model is faked, so grading (incl. the 2026-07-15 mean-of-graded fix) is
    exercised for real.
    """
    def fake_llm(prompt):
        if "trybie nauczyciela" in prompt:
            return json.dumps({"exam": [
                {"q": "Q1?", "expected": "A1"},
                {"q": "Q2?", "expected": "A2"},
                {"q": "Q3?", "expected": "A3"},
            ]})
        if "trybie ucznia" in prompt:
            return json.dumps({"answers": [{"a": "a1"}, {"a": "a2"}, {"a": "a3"}]})
        if "trybie egzaminatora" in prompt:
            return json.dumps({"graded": [
                {"score": per_question_score, "explanation": "x"} for _ in range(3)
            ]})
        raise AssertionError(f"unexpected prompt role: {prompt[:60]}")
    return fake_llm


def _run(tmp_path, record, score):
    index_path = tmp_path / "knowledge_index.jsonl"
    memory_path = tmp_path / "memories.jsonl"
    exam_path = tmp_path / "exam_results.jsonl"
    _write_index(index_path, record)
    _write_memory(memory_path, "test_file.txt")

    result = exam_agent.run_exam_if_ready(
        index_path=index_path,
        memory_path=memory_path,
        exam_path=exam_path,
        llm_fn=_llm_scoring(score),
        target_file_id="test_file.txt",
    )
    saved = json.loads(index_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    return result, saved


# --- The bug itself: a failed first exam must not read as 'completed' ------

def test_failed_first_exam_is_not_stamped_completed(tmp_path):
    """The francuski_naukowiec case: LEARNED file fails its only exam."""
    result, saved = _run(tmp_path, _record("learned"), score=0.0)

    assert result["executed"] is True
    assert result["passed"] is False
    assert saved["status"] == "exam_failed", \
        "a failed first exam must get a second chance, not a completion stamp"


def test_passed_first_exam_completes(tmp_path):
    result, saved = _run(tmp_path, _record("learned"), score=1.0)

    assert result["passed"] is True
    assert saved["status"] == "completed"


def test_second_failure_brands_hard_topic(tmp_path):
    """Honest escalation: the branch that was unreachable in production."""
    result, saved = _run(tmp_path, _record("exam_failed", attempts=1, scores=[0.1]), score=0.0)

    assert result["passed"] is False
    assert saved["status"] == "hard_topic"


# --- The rule that was RIGHT and must survive ------------------------------

def test_failed_repeat_of_completed_material_keeps_completed(tmp_path):
    """Spaced repetition is a genuine concept: a shaky rerun of already-passed
    material must not unlearn it. This branch stays -- it was only reached for
    the wrong reason."""
    result, saved = _run(
        tmp_path, _record("completed", attempts=2, scores=[0.9, 0.85]), score=0.0
    )

    assert result["passed"] is False
    assert saved["status"] == "completed", "a repeat must not demote passed material"


def test_passed_repeat_stays_completed(tmp_path):
    result, saved = _run(
        tmp_path, _record("completed", attempts=2, scores=[0.9, 0.85]), score=1.0
    )

    assert saved["status"] == "completed"


# --- is_spaced must key off status, not off "was a file named?" -----------

def test_named_file_alone_does_not_make_it_a_repeat(tmp_path):
    """Production ALWAYS names a file; that must not by itself mean 'repeat'."""
    _, saved = _run(tmp_path, _record("learned"), score=0.0)
    assert saved["status"] != "completed"

    # Same call shape, same named file -- only the prior status differs.
    _, saved_repeat = _run(
        tmp_path, _record("completed", attempts=1, scores=[0.9]), score=0.0
    )
    assert saved_repeat["status"] == "completed"


# --- Looping detection: stuck means FAILING, not just repetitive -----------
#
# All 3 files ever branded hard_topic had PASSED every exam. The grader echoed
# 0.83 from its prompt, so "3 identical scores" was the normal case for good
# work. Fixed at the source (grade_exam), gated here as second line of defence.


def test_repeated_passing_scores_are_not_looping():
    """expert_interpretacja.txt: [0.83, 0.83, 0.83] -> branded HARD TOPIC."""
    record = {"id": "expert_interpretacja.txt", "last_scores": [0.83, 0.83, 0.83]}
    assert exam_agent.check_for_looping(record) is False, \
        "passing the same exam three times is mastery, not a loop"


def test_repeated_failing_scores_are_looping():
    """The real signal the gate exists for: retried, still failing."""
    record = {"id": "stuck.txt", "last_scores": [0.3, 0.3, 0.3]}
    assert exam_agent.check_for_looping(record) is True


def test_borderline_repeat_just_under_threshold_is_looping():
    record = {"id": "almost.txt", "last_scores": [0.59, 0.59, 0.59]}
    assert exam_agent.check_for_looping(record) is True


def test_borderline_repeat_at_threshold_is_not_looping():
    record = {"id": "just_passing.txt", "last_scores": [0.6, 0.6, 0.6]}
    assert exam_agent.check_for_looping(record) is False


def test_improving_scores_are_not_looping():
    record = {"id": "improving.txt", "last_scores": [0.1, 0.4, 0.55]}
    assert exam_agent.check_for_looping(record) is False


def test_passing_file_with_repeated_scores_keeps_completed(tmp_path):
    """End-to-end: the mastery case must survive the whole pipeline."""
    _, saved = _run(
        tmp_path, _record("completed", attempts=3, scores=[0.83, 0.83]), score=0.83
    )
    assert saved["last_scores"][-3:] == [0.83, 0.83, 0.83]
    assert saved["status"] == "completed", "three passes must not brand hard_topic"
