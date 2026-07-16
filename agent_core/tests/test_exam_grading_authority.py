"""Tests for 2026-07-15 exam grading fix: the code owns final_score, not the LLM.

Production audit (1344 historical exams in memory/exam_results.jsonl):
  - 447 (33.3%) scored EXACTLY 0.83 -- the literal from the prompt's worked
    example, which the grader echoed instead of averaging.
  - 706 (52.5%) disagreed with the mean of their own graded[] list.
  - 15 of those disagreements flipped the verdict across EXAM_PASS_THRESHOLD.
  - 14 exams graded fewer answers than they asked questions.
In vivo: expert_fizyka.txt 2026-07-15 08:56 -- grader (qwen3:8b) scored 1.0 on
all 6 questions, then returned final_score 0.83.

The other two graders (_parse_exam_grading_fallback, grade_heldout) always
averaged graded[]; only the LLM path trusted the model's own number.
"""

from maria_core.learning import exam_agent
from maria_core.sys.config import EXAM_PASS_THRESHOLD

import json


_QUESTIONS = [
    {"q": "Q1?", "expected": "A1"},
    {"q": "Q2?", "expected": "A2"},
    {"q": "Q3?", "expected": "A3"},
]
_ANSWERS = [{"a": "a1"}, {"a": "a2"}, {"a": "a3"}]


def _llm_returning(payload):
    def fake_llm(prompt):
        return json.dumps(payload)
    return fake_llm


# --- 1. The echo itself ----------------------------------------------------

def test_grader_echoing_083_is_overridden_by_real_mean():
    """The expert_fizyka case: all grades 1.0 but final_score 0.83 -> 1.0 wins."""
    result = exam_agent.grade_exam(
        _QUESTIONS, _ANSWERS,
        llm_fn=_llm_returning({
            "graded": [{"score": 1.0, "explanation": "ok"}] * 3,
            "final_score": 0.83,
        }),
    )

    assert result is not None
    assert result["final_score"] == 1.0, "mean of graded[] must beat the echoed literal"


def test_echoed_083_no_longer_passes_a_failing_exam():
    """The 15 flipped verdicts: real mean 0.0 must not be reported as a pass."""
    result = exam_agent.grade_exam(
        _QUESTIONS, _ANSWERS,
        llm_fn=_llm_returning({
            "graded": [{"score": 0.0, "explanation": "wrong"}] * 3,
            "final_score": 0.83,
        }),
    )

    assert result["final_score"] == 0.0
    assert result["final_score"] < EXAM_PASS_THRESHOLD, "failing exam must read as failing"


def test_echoed_083_no_longer_fails_a_passing_exam():
    """Echo mostly UNDER-reported (0.83 vs real 0.925) -- good work must not be sunk."""
    result = exam_agent.grade_exam(
        _QUESTIONS, _ANSWERS,
        llm_fn=_llm_returning({
            "graded": [
                {"score": 1.0, "explanation": "ok"},
                {"score": 0.9, "explanation": "ok"},
                {"score": 0.9, "explanation": "ok"},
            ],
            "final_score": 0.83,
        }),
    )

    assert result["final_score"] == 0.933


# --- 2. final_score is no longer required from the model -------------------

def test_grading_works_when_model_omits_final_score():
    """Prompt no longer asks for final_score -- its absence must not kill the exam."""
    result = exam_agent.grade_exam(
        _QUESTIONS, _ANSWERS,
        llm_fn=_llm_returning({
            "graded": [{"score": 0.5, "explanation": "meh"}] * 3,
        }),
    )

    assert result is not None, "missing final_score must not fail the exam"
    assert result["final_score"] == 0.5


def test_prompt_does_not_carry_a_worked_final_score():
    """Root cause: a literal in the example is a value the model will copy."""
    captured = {}

    def fake_llm(prompt):
        captured["prompt"] = prompt
        return json.dumps({"graded": [{"score": 1.0, "explanation": "ok"}] * 3})

    exam_agent.grade_exam(_QUESTIONS, _ANSWERS, llm_fn=fake_llm)

    assert "0.83" not in captured["prompt"], "no score literal may appear in the prompt"
    assert "final_score" not in captured["prompt"], "do not ask for a number we compute"
    assert "dokładnie\n3 elementów" in captured["prompt"] or "3 element" in captured["prompt"], \
        "prompt must demand one grade per question"


# --- 3. Under/over-count grading ------------------------------------------

def test_missing_grades_count_as_zero_not_as_a_smaller_denominator():
    """14 historical exams graded fewer answers than asked; averaging only what
    came back rewards the grader for skipping the hard questions."""
    result = exam_agent.grade_exam(
        _QUESTIONS, _ANSWERS,
        llm_fn=_llm_returning({
            "graded": [{"score": 1.0, "explanation": "ok"}],  # 1 of 3
        }),
    )

    assert result["final_score"] == 0.333, "1.0 + missing + missing -> 1/3, not 1.0"
    assert len(result["graded"]) == 3


def test_surplus_grades_are_truncated():
    result = exam_agent.grade_exam(
        _QUESTIONS, _ANSWERS,
        llm_fn=_llm_returning({
            "graded": [{"score": 1.0, "explanation": "ok"}] * 5,
        }),
    )

    assert len(result["graded"]) == 3
    assert result["final_score"] == 1.0


def test_unusable_graded_falls_back_to_text_parsing():
    """graded[] present but carrying no numeric score -> text fallback, not a crash."""
    def fake_llm(prompt):
        return json.dumps({"graded": [{"explanation": "no score field"}]})

    result = exam_agent.grade_exam(_QUESTIONS, _ANSWERS, llm_fn=fake_llm)
    assert result is None, "no usable score anywhere -> None (caller bumps updated_at)"


def test_scores_are_clamped_to_unit_range():
    """A grader returning 5.0 must not manufacture a >1.0 exam score."""
    result = exam_agent.grade_exam(
        _QUESTIONS, _ANSWERS,
        llm_fn=_llm_returning({
            "graded": [{"score": 5.0, "explanation": "over"}] * 3,
        }),
    )

    assert result["final_score"] == 1.0


# --- 4. The other graders already did this -- keep them consistent ---------

def test_text_fallback_still_averages_its_own_grades():
    """Control: _parse_exam_grading_fallback was always the honest one."""
    def fake_llm(prompt):
        return "1. score: 1.0 - dobrze\n2. score: 0.0 - zle\n3. score: 0.5 - polowicznie\n"

    result = exam_agent.grade_exam(_QUESTIONS, _ANSWERS, llm_fn=fake_llm)

    assert result is not None
    assert result["final_score"] == 0.5
