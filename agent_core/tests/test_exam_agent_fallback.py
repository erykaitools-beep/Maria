"""Fallback parsers for exam_agent — handle LLM responses that ignore JSON instruction.

Why: qwen3:8b sometimes returns "Oto odpowiedzi:\\n1. ...\\n2. ..." instead of JSON,
wasting 25-min exam cycles (incidents 2026-04-23 08:16 and 12:43).
"""

from maria_core.learning.exam_agent import (
    _parse_numbered_list,
    _parse_exam_answers_fallback,
    _parse_exam_grading_fallback,
)


def test_numbered_list_dot_separator():
    text = "1. answer one\n2. answer two\n3. answer three"
    assert _parse_numbered_list(text, 3) == ["answer one", "answer two", "answer three"]


def test_numbered_list_paren_separator():
    text = "1) first\n2) second"
    assert _parse_numbered_list(text, 2) == ["first", "second"]


def test_numbered_list_colon_separator():
    text = "1: alpha\n2: beta"
    assert _parse_numbered_list(text, 2) == ["alpha", "beta"]


def test_numbered_list_multiline_content():
    text = "1. line one\n   continues here\n2. line two"
    result = _parse_numbered_list(text, 2)
    assert result is not None
    assert "line one" in result[0]
    assert "continues here" in result[0]
    assert result[1] == "line two"


def test_numbered_list_count_mismatch_returns_none():
    text = "1. only one"
    assert _parse_numbered_list(text, 2) is None


def test_numbered_list_no_numbers_returns_none():
    text = "Some prose without any numbered list at all."
    assert _parse_numbered_list(text, 2) is None


def test_numbered_list_with_preamble():
    text = "Oto odpowiedzi na zadane pytania:\n\n1. First answer.\n2. Second answer.\n3. Third."
    result = _parse_numbered_list(text, 3)
    assert result == ["First answer.", "Second answer.", "Third."]


def test_exam_answers_fallback_real_log_format():
    # Reproduces the 2026-04-23 08:16 incident pattern.
    response = (
        "Oto odpowiedzi na zadane pytania:\n\n"
        "1. Pierwsza odpowiedź jest długa i zawiera kilka zdań.\n"
        "2. Druga odpowiedź jeszcze dłuższa, opisuje szczegóły.\n"
        "3. Krótka."
    )
    result = _parse_exam_answers_fallback(response, 3)
    assert result is not None
    assert len(result) == 3
    assert result[0] == {"a": "Pierwsza odpowiedź jest długa i zawiera kilka zdań."}
    assert result[2] == {"a": "Krótka."}


def test_exam_answers_fallback_returns_none_when_count_off():
    response = "1. only one"
    assert _parse_exam_answers_fallback(response, 3) is None


def test_exam_grading_fallback_with_explicit_score():
    response = "1. score: 0.8 - dobre uzasadnienie\n2. score: 0.5 - mizernie\n3. score: 1.0 - idealnie"
    result = _parse_exam_grading_fallback(response, 3)
    assert result is not None
    assert result["graded"][0]["score"] == 0.8
    assert result["graded"][1]["score"] == 0.5
    assert result["graded"][2]["score"] == 1.0
    assert result["final_score"] == round((0.8 + 0.5 + 1.0) / 3, 3)


def test_exam_grading_fallback_with_bare_score():
    response = "1. 0.7 dobre\n2. 0.9 świetne"
    result = _parse_exam_grading_fallback(response, 2)
    assert result is not None
    assert result["graded"][0]["score"] == 0.7
    assert result["final_score"] == 0.8


def test_exam_grading_fallback_no_score_returns_none():
    response = "1. tekst bez zadnej liczby\n2. tez bez liczby"
    assert _parse_exam_grading_fallback(response, 2) is None


def test_exam_grading_fallback_explanation_extracted():
    response = "1. score: 0.8 - bardzo dobre wyjaśnienie\n2. score: 0.4 - słabe"
    result = _parse_exam_grading_fallback(response, 2)
    assert result is not None
    assert "bardzo dobre wyjaśnienie" in result["graded"][0]["explanation"]
    assert "słabe" in result["graded"][1]["explanation"]


# --- 2026-05-28 fix: robust score extraction + partial grading ------------


def test_exam_grading_fallback_ignores_stray_integer_in_prose():
    # Regression: a bare "1" sits in the explanation before the real score.
    # Old regex grabbed the "1" (-> 1.0 misgrade); label/decimal must win.
    response = (
        "1. Odpowiedz w 1 zdaniu jest poprawna, score: 0.7\n"
        "2. Druga czesc, ocena: 0.3"
    )
    result = _parse_exam_grading_fallback(response, 2)
    assert result is not None
    assert result["graded"][0]["score"] == 0.7
    assert result["graded"][1]["score"] == 0.3


def test_exam_grading_fallback_recognises_ocena_label():
    response = "1. ocena: 0.4 - polowicznie\n2. ocena: 0.9 - prawie idealnie"
    result = _parse_exam_grading_fallback(response, 2)
    assert result is not None
    assert result["graded"][0]["score"] == 0.4
    assert result["graded"][1]["score"] == 0.9


def test_exam_grading_fallback_leading_bare_integer_score():
    response = "1. 1 - idealna odpowiedz\n2. 0 - calkowicie bledne"
    result = _parse_exam_grading_fallback(response, 2)
    assert result is not None
    assert result["graded"][0]["score"] == 1.0
    assert result["graded"][1]["score"] == 0.0
    assert result["final_score"] == 0.5


def test_exam_grading_fallback_skips_unscoreable_line():
    # One line has no parseable score -> skip it, grade the rest
    # (was: a single bad line returned None for the whole exam).
    response = (
        "1. score: 0.8 dobre\n"
        "2. tekst zupelnie bez liczby ani oznaczenia\n"
        "3. score: 0.6 ok"
    )
    result = _parse_exam_grading_fallback(response, 3)
    assert result is not None
    assert len(result["graded"]) == 2
    assert result["final_score"] == 0.7


def test_exam_grading_fallback_partial_count_still_grades():
    # LLM returned 2 of 3 graded lines -> average over the 2 instead of None
    # (strict count previously made this a failed-exam action).
    response = "1. score: 0.9 super\n2. score: 0.5 ok"
    result = _parse_exam_grading_fallback(response, 3)
    assert result is not None
    assert len(result["graded"]) == 2
    assert result["final_score"] == 0.7
