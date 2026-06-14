"""Tests for 2026-05-22 exam pipeline fix.

Incident: spaced-repetition for expert_genetyka.txt looped 63 times in one
learning window with 0% success. Root causes:
  1. call_ollama had no num_predict cap → 12-question exam JSON truncated
     mid-string ("Unterminated string starting at char 4770").
  2. extract_json_from_response markdown fallback returned a learning-shaped dict
     ({summary, key_points, tags, questions}) for any non-empty text, tricking
     exam_agent into "Brak pola 'exam' (fallback nie zadzialal)".
  3. run_exam_if_ready did not update target on pipeline failure, so spaced-
     repetition scheduler (sorts by updated_at ASC) kept re-picking the same file.
"""

import json

from maria_core.learning import exam_agent, llm_utils
from maria_core.learning.llm_utils import (
    _parse_markdown_to_learning_dict,
    extract_json_from_response,
)


# --- 1. num_predict cap in Ollama payload ----------------------------------

def test_call_ollama_payload_caps_output_tokens(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"response": ""}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return FakeResp()

    monkeypatch.setattr(llm_utils.requests, "post", fake_post)
    llm_utils.call_ollama("test prompt")

    opts = captured["payload"]["options"]
    assert "num_predict" in opts, "num_predict must be set to prevent JSON truncation"
    assert opts["num_predict"] >= 1024


# --- 2. expected_keys gates markdown fallback ------------------------------

def _learning_shaped_text():
    return (
        "Streszczenie: dłuższy tekst opisujący temat tak żeby parser miał z czym pracować "
        "(potrzeba minimum pięćdziesięciu znaków przed pierwszą sekcją bullet pointów).\n"
        "Kluczowe punkty:\n"
        "- punkt pierwszy\n"
        "- punkt drugi\n"
    )


def test_markdown_fallback_returns_none_when_expected_keys_missing():
    # exam caller declares expected_keys={'exam'} — learning dict must not pass.
    result = _parse_markdown_to_learning_dict(_learning_shaped_text(), expected_keys={'exam'})
    assert result is None


def test_markdown_fallback_returns_dict_when_expected_keys_match():
    result = _parse_markdown_to_learning_dict(_learning_shaped_text(), expected_keys={'summary'})
    assert result is not None
    assert 'summary' in result


def test_markdown_fallback_default_preserves_backcompat():
    # No expected_keys → behaviour unchanged from pre-fix (learning callers stay green).
    result = _parse_markdown_to_learning_dict(_learning_shaped_text())
    assert result is not None
    assert 'summary' in result


def test_extract_json_blocks_learning_fallback_for_exam():
    text = (
        "Oto egzamin: pytania o genetyce.\n\n"
        "Streszczenie genetyki: nauka o dziedziczności i zmienności organizmów. "
        "DNA jest nośnikiem informacji genetycznej.\n"
        "Kluczowe punkty:\n"
        "- DNA składa się z czterech zasad: A, T, G, C\n"
        "- Replikacja DNA jest semikonserwatywna\n"
    )
    assert extract_json_from_response(text, expected_keys={'exam'}) is None


def test_extract_json_returns_real_json_with_expected_keys():
    text = '{"exam": [{"q": "What is DNA?", "expected": "Nucleic acid."}]}'
    result = extract_json_from_response(text, expected_keys={'exam'})
    assert result == {"exam": [{"q": "What is DNA?", "expected": "Nucleic acid."}]}


def test_extract_json_truncated_unterminated_string_is_rejected():
    # Reproduces the in-vivo failure (char 4770 line 41 "Unterminated string"):
    # JSON parser fails AND markdown fallback is gated by expected_keys → return None.
    truncated = (
        '{"exam": [{"q": "Pytanie 1?", "expected": "odpowiedź jedna"},'
        ' {"q": "Pytanie 2?", "expected": "odpowiedź dwa która nigdy się nie kończy bo string został'
    )
    assert extract_json_from_response(truncated, expected_keys={'exam'}) is None


def test_extract_json_default_keeps_learning_fallback():
    result = extract_json_from_response(_learning_shaped_text())
    assert result is not None
    assert 'summary' in result


# --- 3. run_exam_if_ready loop guard --------------------------------------

def _write_index(path, record):
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


def _write_memory(path, file_id):
    path.write_text(
        json.dumps({
            "source_file": file_id,
            "folder": "root",
            "chunk_id": f"{file_id}#chunk_0",
            "chunk_index": 0,
            "summary": "Krótkie streszczenie.",
            "key_points": ["punkt 1", "punkt 2"],
            "tags": ["test"],
        }) + "\n",
        encoding="utf-8",
    )


def test_run_exam_failure_bumps_updated_at(tmp_path, monkeypatch):
    """When generate_exam fails, target.updated_at must be bumped so spaced-
    repetition scheduler (sorts by updated_at ASC) does not re-pick same file."""
    index_path = tmp_path / "knowledge_index.jsonl"
    memory_path = tmp_path / "memories.jsonl"
    exam_path = tmp_path / "exam_results.jsonl"

    orig_updated = "2026-05-01T00:00:00.000000Z"
    record = {
        "id": "test_file.txt",
        "folder": "root",
        "file": "test_file.txt",
        "status": "completed",
        "priority": 50.0,
        "hash": "xyz",
        "created_at": orig_updated,
        "updated_at": orig_updated,
        "exam_attempts": 3,
        "last_scores": [0.8, 0.85, 0.9],
        "chunks_learned": 1,
        "total_chunks": 1,
    }
    _write_index(index_path, record)
    _write_memory(memory_path, "test_file.txt")

    monkeypatch.setattr(exam_agent, "generate_exam", lambda *a, **kw: None)

    result = exam_agent.run_exam_if_ready(
        index_path=index_path,
        memory_path=memory_path,
        exam_path=exam_path,
        target_file_id="test_file.txt",
    )

    assert result["executed"] is False
    saved = json.loads(index_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert saved["updated_at"] != orig_updated, "updated_at must be bumped on pipeline failure"


def test_run_exam_failure_preserves_other_fields(tmp_path, monkeypatch):
    """Loop guard must only touch updated_at — exam_attempts, last_scores, status stay."""
    index_path = tmp_path / "knowledge_index.jsonl"
    memory_path = tmp_path / "memories.jsonl"
    exam_path = tmp_path / "exam_results.jsonl"

    record = {
        "id": "test_file.txt",
        "folder": "root",
        "file": "test_file.txt",
        "status": "completed",
        "priority": 50.0,
        "hash": "xyz",
        "created_at": "2026-05-01T00:00:00.000000Z",
        "updated_at": "2026-05-01T00:00:00.000000Z",
        "exam_attempts": 3,
        "last_scores": [0.8, 0.85, 0.9],
        "chunks_learned": 1,
        "total_chunks": 1,
    }
    _write_index(index_path, record)
    _write_memory(memory_path, "test_file.txt")

    monkeypatch.setattr(exam_agent, "generate_exam", lambda *a, **kw: None)

    exam_agent.run_exam_if_ready(
        index_path=index_path,
        memory_path=memory_path,
        exam_path=exam_path,
        target_file_id="test_file.txt",
    )

    saved = json.loads(index_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert saved["status"] == "completed"
    assert saved["exam_attempts"] == 3
    assert saved["last_scores"] == [0.8, 0.85, 0.9]


# --- 4. answer_exam lenient count handling (2026-05-23 fix) ---------------
#
# Pre-fix: answer_exam used strict `len(answers) != len(questions) -> return None`,
# which meant a single dropped answer (LLM decided 2 was good enough for 3 questions)
# killed the entire exam. Spaced-repetition then re-picked the same file forever.
#
# Post-fix: prompt enforces explicit count + answer_exam pads under-count with empty
# strings (scores 0 in grade_exam — truthful) and truncates over-count.


_THREE_QUESTIONS = [
    {"q": "Q1?", "expected": "A1"},
    {"q": "Q2?", "expected": "A2"},
    {"q": "Q3?", "expected": "A3"},
]


def test_answer_exam_prompt_includes_explicit_count():
    """Prompt must tell LLM the exact required answer count, not leave it implicit."""
    captured = {}

    def fake_llm(prompt):
        captured["prompt"] = prompt
        return json.dumps({"answers": [{"a": "x"}, {"a": "y"}, {"a": "z"}]})

    exam_agent.answer_exam("ctx", _THREE_QUESTIONS, llm_fn=fake_llm)

    prompt = captured["prompt"]
    assert "DOKŁADNIE na 3 pytań" in prompt, "prompt must demand exactly N answers"
    assert "Pytania (3)" in prompt, "prompt must show count alongside questions"
    assert "dokładnie 3 elementów" in prompt, "prompt must reinforce count in JSON spec"


def test_answer_exam_pads_under_count_with_empty():
    """LLM returns N-1 answers → pad to N with empty strings (graceful degradation)."""
    def fake_llm(prompt):
        return json.dumps({"answers": [{"a": "first"}, {"a": "second"}]})

    result = exam_agent.answer_exam("ctx", _THREE_QUESTIONS, llm_fn=fake_llm)

    assert result is not None, "under-count must not kill the exam"
    assert len(result) == 3
    assert result[0] == {"a": "first"}
    assert result[1] == {"a": "second"}
    assert result[2] == {"a": ""}, "missing slot padded with empty answer"


def test_answer_exam_truncates_over_count():
    """LLM hallucinates extra answers → truncate to N (defensive)."""
    def fake_llm(prompt):
        return json.dumps({
            "answers": [
                {"a": "a1"}, {"a": "a2"}, {"a": "a3"},
                {"a": "extra1"}, {"a": "extra2"},
            ]
        })

    result = exam_agent.answer_exam("ctx", _THREE_QUESTIONS, llm_fn=fake_llm)

    assert result is not None
    assert len(result) == 3
    assert [r["a"] for r in result] == ["a1", "a2", "a3"]


def test_answer_exam_exact_count_passes_through_unchanged():
    """Control: N answers must not be touched by padding/truncate paths."""
    payload = [{"a": "alpha"}, {"a": "beta"}, {"a": "gamma"}]

    def fake_llm(prompt):
        return json.dumps({"answers": payload})

    result = exam_agent.answer_exam("ctx", _THREE_QUESTIONS, llm_fn=fake_llm)

    assert result == payload


def test_answer_exam_concise_selects_short_prompt():
    """Held-out (concise=True) uses the one-fact prompt; default keeps 2-6 sentences.

    The held-out grader is deterministic, so essays just waste tokens (and time
    out on CPU). concise=True must switch templates; default must be unchanged.
    """
    captured = {}

    def fake_llm(prompt):
        captured["prompt"] = prompt
        return json.dumps({"answers": [{"a": "x"}, {"a": "y"}, {"a": "z"}]})

    exam_agent.answer_exam("ctx", _THREE_QUESTIONS, llm_fn=fake_llm, concise=True)
    assert "BARDZO KRÓTKO" in captured["prompt"]
    assert "2–6 zdań" not in captured["prompt"]

    exam_agent.answer_exam("ctx", _THREE_QUESTIONS, llm_fn=fake_llm, concise=False)
    assert "2–6 zdań" in captured["prompt"]
    assert "BARDZO KRÓTKO" not in captured["prompt"]


def test_answer_exam_rejects_non_list_answers_field():
    """Defensive: if LLM returns 'answers' as a string/dict (not list), still return None."""
    def fake_llm(prompt):
        return json.dumps({"answers": "this is not a list"})

    result = exam_agent.answer_exam("ctx", _THREE_QUESTIONS, llm_fn=fake_llm)
    assert result is None
