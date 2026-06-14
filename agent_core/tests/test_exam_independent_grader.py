"""Keystone (2026-05-30): the exam must be graded by an INDEPENDENT model.

Before: one llm_fn wrote the questions+rubric, answered them, AND graded -- so
'retention' measured the model agreeing with itself (scores clustered 0.83-0.92,
the 0.6 promote gate trivially cleared). Now the EXAMINER (grader_llm_fn, e.g. NIM
nemotron) authors + grades while the local STUDENT (llm_fn) answers blind, and the
run records whether grading was independent.
"""

import json
from pathlib import Path

from maria_core.learning import exam_agent
from maria_core.sys.config import STATUS_LEARNED


# --- 1. _execute_exam routes examiner vs student -------------------------------

def test_execute_exam_routes_examiner_and_student(monkeypatch):
    """generate + grade go to the EXAMINER (grader_llm_fn); answer goes to the
    STUDENT (llm_fn)."""
    seen = {}
    monkeypatch.setattr(
        exam_agent, "get_memories_for_file",
        lambda fid, mp: [{"summary": "s", "key_points": ["k"]}],
    )

    def fake_generate(context, n, llm_fn=None):
        seen["generate"] = llm_fn
        return [{"q": "q1", "expected": "e1"}]

    def fake_answer(context, qs, llm_fn=None, concise=False):
        seen["answer"] = llm_fn
        return [{"a": "a1"}]

    def fake_grade(qs, ans, llm_fn=None):
        seen["grade"] = llm_fn
        return {"graded": [{"score": 0.5}], "final_score": 0.5}

    monkeypatch.setattr(exam_agent, "generate_exam", fake_generate)
    monkeypatch.setattr(exam_agent, "answer_exam", fake_answer)
    monkeypatch.setattr(exam_agent, "grade_exam", fake_grade)

    student = lambda p: "student"
    examiner = lambda p: "examiner"
    score, _, _, _ = exam_agent._execute_exam(
        "f1", Path("/tmp/x"), llm_fn=student, grader_llm_fn=examiner,
    )
    assert score == 0.5
    assert seen["generate"] is examiner   # examiner authors the test
    assert seen["answer"] is student      # student answers
    assert seen["grade"] is examiner      # examiner grades


def test_execute_exam_self_graded_fallback(monkeypatch):
    """With no independent grader, all three steps fall back to llm_fn (the old
    self-graded behaviour) -- preserved for backward compatibility."""
    seen = {}
    monkeypatch.setattr(
        exam_agent, "get_memories_for_file",
        lambda fid, mp: [{"summary": "s", "key_points": ["k"]}],
    )
    monkeypatch.setattr(exam_agent, "generate_exam",
                        lambda c, n, llm_fn=None: (seen.__setitem__("generate", llm_fn),
                                                   [{"q": "q", "expected": "e"}])[1])
    monkeypatch.setattr(exam_agent, "answer_exam",
                        lambda c, qs, llm_fn=None, concise=False: (seen.__setitem__("answer", llm_fn),
                                                    [{"a": "a"}])[1])
    monkeypatch.setattr(exam_agent, "grade_exam",
                        lambda qs, a, llm_fn=None: (seen.__setitem__("grade", llm_fn),
                                                    {"graded": [{"score": 1.0}], "final_score": 1.0})[1])

    student = lambda p: "student"
    exam_agent._execute_exam("f1", Path("/tmp/x"), llm_fn=student)  # no grader
    assert seen["generate"] is student
    assert seen["answer"] is student
    assert seen["grade"] is student


# --- 1b. Held-out static grader ----------------------------------------------


def test_grade_heldout_match_modes():
    bank = [
        {"q": "Q1", "match": "contains", "canonical": "chlorofil"},
        {"q": "Q2", "match": "exact", "canonical": "ATP"},
        {"q": "Q3", "match": "regex", "pattern": r"CO2|dwutlenek węgla"},
        {"q": "Q4", "match": "numeric", "canonical": "60", "tolerance": 2},
    ]
    answers = [
        {"a": "Chlorofil pochlania swiatlo."},
        {"a": "atp"},
        {"a": "Roślina pobiera CO2."},
        {"a": "Wynik to 61,5 procent."},
    ]

    grading = exam_agent.grade_heldout(bank, answers)

    assert grading["final_score"] == 1.0
    assert [g["score"] for g in grading["graded"]] == [1.0, 1.0, 1.0, 1.0]


def test_grade_heldout_blocks_wrong_answers():
    bank = [
        {"q": "Q1", "match": "contains", "canonical": "glukoza"},
        {"q": "Q2", "match": "numeric", "canonical": "42", "tolerance": 0},
    ]
    answers = [{"a": "tlen"}, {"a": "41"}]

    grading = exam_agent.grade_heldout(bank, answers)

    assert grading["final_score"] == 0.0
    assert [g["score"] for g in grading["graded"]] == [0.0, 0.0]


def test_select_heldout_rows_by_file_and_topic():
    rows = [
        {"file": "expert_fotosynteza.txt", "q": "file"},
        {"topic": "reakcje chemiczne", "q": "topic"},
        {"topic": "astronomia", "q": "other"},
    ]

    selected_file = exam_agent.select_heldout_rows("expert_fotosynteza.txt", rows)
    selected_topic = exam_agent.select_heldout_rows("web_wiki_reakcje_chemiczne.txt", rows)

    assert [r["q"] for r in selected_file] == ["file"]
    assert [r["q"] for r in selected_topic] == ["topic"]


def test_load_heldout_bank_skips_corrupt_lines(tmp_path):
    path = tmp_path / "heldout_bank.jsonl"
    path.write_text(
        json.dumps({"topic": "x", "q": "Q?", "canonical": "A"}) + "\n"
        "not-json\n"
        "{}\n",
        encoding="utf-8",
    )

    rows = exam_agent.load_heldout_bank(path)

    assert len(rows) == 1
    assert rows[0]["q"] == "Q?"


def test_execute_heldout_exam_uses_student_and_static_grade(monkeypatch):
    monkeypatch.setattr(
        exam_agent, "get_memories_for_file",
        lambda fid, mp: [{"summary": "s", "key_points": ["k"]}],
    )
    monkeypatch.setattr(
        exam_agent,
        "generate_exam",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no generate")),
    )
    monkeypatch.setattr(
        exam_agent,
        "grade_exam",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no llm grade")),
    )

    student_calls = []

    def fake_student(prompt):
        student_calls.append(prompt)
        return json.dumps({"answers": [{"a": "chlorofil"}]})

    score, exam, answers, grading = exam_agent._execute_heldout_exam(
        "expert_fotosynteza.txt",
        Path("/tmp/memory.jsonl"),
        [{"file": "expert_fotosynteza.txt", "q": "Co pochlania swiatlo?", "canonical": "chlorofil"}],
        llm_fn=fake_student,
    )

    assert score == 1.0
    assert exam[0]["heldout"] is True
    assert answers == [{"a": "chlorofil"}]
    assert grading["final_score"] == 1.0
    assert len(student_calls) == 1


# --- 2. run_exam_if_ready records grader provenance ----------------------------

def test_run_exam_records_grader_provenance(monkeypatch, tmp_path):
    recorded = {}
    rec = {"id": "f1", "status": STATUS_LEARNED, "exam_attempts": 0,
           "last_scores": [], "priority": 10}
    monkeypatch.setattr(exam_agent, "load_index", lambda p: [rec])
    monkeypatch.setattr(exam_agent, "save_index", lambda idx, p: None)
    monkeypatch.setattr(exam_agent, "append_exam_result",
                        lambda d, p: recorded.update(d))
    monkeypatch.setattr(
        exam_agent, "_execute_exam",
        lambda fid, mp, llm_fn, grader_llm_fn=None, generator_llm_fn=None: (
            0.7, [{"q": "q", "expected": "e"}], [{"a": "a"}],
            {"graded": [{"score": 0.7}], "final_score": 0.7}),
    )

    out = exam_agent.run_exam_if_ready(
        index_path=tmp_path / "i.json", memory_path=tmp_path / "m",
        exam_path=tmp_path / "e.jsonl", target_file_id="f1",
        grader_meta={"independent": True, "grader": "nemotron-49b",
                     "student": "llama3.1:8b"},
    )
    assert out["executed"] is True
    assert recorded["grader_independent"] is True
    assert recorded["grader_model"] == "nemotron-49b"
    assert recorded["student_model"] == "llama3.1:8b"


def test_run_exam_uses_heldout_when_bank_matches(monkeypatch, tmp_path):
    recorded = {}
    rec = {"id": "expert_fotosynteza.txt", "status": STATUS_LEARNED,
           "exam_attempts": 0, "last_scores": [], "priority": 10}
    bank_path = tmp_path / "heldout_bank.jsonl"
    bank_path.write_text(
        json.dumps({
            "file": "expert_fotosynteza.txt",
            "q": "Co pochlania swiatlo?",
            "match": "contains",
            "canonical": "chlorofil",
            "bank_version": "v1",
        }) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(exam_agent, "load_index", lambda p: [rec])
    monkeypatch.setattr(exam_agent, "save_index", lambda idx, p: None)
    monkeypatch.setattr(exam_agent, "append_exam_result",
                        lambda d, p: recorded.update(d))
    monkeypatch.setattr(
        exam_agent, "get_memories_for_file",
        lambda fid, mp: [{"summary": "s", "key_points": ["k"]}],
    )

    def student(prompt):
        return json.dumps({"answers": [{"a": "chlorofil"}]})

    out = exam_agent.run_exam_if_ready(
        index_path=tmp_path / "i.json",
        memory_path=tmp_path / "m.jsonl",
        exam_path=tmp_path / "e.jsonl",
        llm_fn=student,
        target_file_id="expert_fotosynteza.txt",
        grader_meta={"student": "llama3.1:8b", "grader": "qwen3:8b", "independent": True},
        use_heldout=True,
        heldout_bank_path=bank_path,
    )

    assert out["executed"] is True
    assert out["passed"] is True
    assert recorded["grader_independent"] is True
    assert recorded["grader_model"] == exam_agent.HELDOUT_GRADER_MODEL
    assert recorded["student_model"] == "llama3.1:8b"
    assert recorded["questions"][0]["heldout"] is True


def test_run_exam_falls_back_when_no_heldout_rows(monkeypatch, tmp_path):
    recorded = {}
    rec = {"id": "f1", "status": STATUS_LEARNED, "exam_attempts": 0,
           "last_scores": [], "priority": 10}
    monkeypatch.setattr(exam_agent, "load_index", lambda p: [rec])
    monkeypatch.setattr(exam_agent, "save_index", lambda idx, p: None)
    monkeypatch.setattr(exam_agent, "append_exam_result",
                        lambda d, p: recorded.update(d))
    monkeypatch.setattr(
        exam_agent,
        "_execute_exam",
        lambda fid, mp, llm_fn, grader_llm_fn=None, generator_llm_fn=None: (
            0.7, [{"q": "q", "expected": "e"}], [{"a": "a"}],
            {"graded": [{"score": 0.7}], "final_score": 0.7}),
    )

    out = exam_agent.run_exam_if_ready(
        index_path=tmp_path / "i.json",
        memory_path=tmp_path / "m",
        exam_path=tmp_path / "e.jsonl",
        target_file_id="f1",
        grader_meta={"independent": True, "grader": "qwen3:8b", "student": "llama3.1:8b"},
        use_heldout=True,
        heldout_bank_path=tmp_path / "missing.jsonl",
    )

    assert out["executed"] is True
    assert recorded["grader_model"] == "qwen3:8b"


def test_teacher_module_passes_heldout_flag(monkeypatch):
    from agent_core.modules.teacher_module import TeacherModule

    captured = {}

    def fake_run_exam_if_ready(**kwargs):
        captured.update(kwargs)
        return {"executed": True, "passed": True, "score": 1.0, "file_id": "f1"}

    monkeypatch.setenv("HELDOUT_GRADER_ENABLED", "true")
    monkeypatch.setattr(exam_agent, "run_exam_if_ready", fake_run_exam_if_ready)

    module = TeacherModule()
    out = module._run_exam_wrapped("f1")

    assert out["success"] is True
    assert captured["use_heldout"] is True
    # Grader is now NIM-first with a qwen3-local fallback; the exact label may
    # change, but independence MUST hold -- the examiner (NIM or fallback) is
    # never the llama student.
    gm = captured["grader_meta"]
    assert gm["independent"] is True
    assert gm["grader"] != gm["student"]
    assert "qwen3:8b" in gm["grader"] or "llama3.1:8b" in gm["grader"]


def test_run_exam_provenance_defaults_non_independent(monkeypatch, tmp_path):
    """No grader_meta -> recorded as NOT independent (honest default)."""
    recorded = {}
    rec = {"id": "f1", "status": STATUS_LEARNED, "exam_attempts": 0,
           "last_scores": [], "priority": 10}
    monkeypatch.setattr(exam_agent, "load_index", lambda p: [rec])
    monkeypatch.setattr(exam_agent, "save_index", lambda idx, p: None)
    monkeypatch.setattr(exam_agent, "append_exam_result",
                        lambda d, p: recorded.update(d))
    monkeypatch.setattr(
        exam_agent, "_execute_exam",
        lambda fid, mp, llm_fn, grader_llm_fn=None, generator_llm_fn=None: (
            0.9, [{"q": "q", "expected": "e"}], [{"a": "a"}],
            {"graded": [{"score": 0.9}], "final_score": 0.9}),
    )
    exam_agent.run_exam_if_ready(
        index_path=tmp_path / "i.json", memory_path=tmp_path / "m",
        exam_path=tmp_path / "e.jsonl", target_file_id="f1",
    )
    assert recorded["grader_independent"] is False
    assert recorded["grader_model"] is None


# --- 3. NIM-first examiner (author + grader): honest fallback ------------------

def test_nim_grader_falls_back_to_qwen3_never_student(monkeypatch):
    """Trust-regime keystone (2026-06-06): when NIM grading fails, the grader
    falls back to the LOCAL qwen3 examiner (independent), NEVER the student model.

    The old local-only grader existed precisely because a naive NIM grader timed
    out and the ROUTER silently fell back to the student -> hidden self-grade
    flagged 'independent'. This test pins the explicit, never-student fallback.
    """
    import maria_core.sys.config as cfg
    import maria_core.learning.llm_utils as llm_utils
    import agent_core.llm.nim_client as nim_mod
    from agent_core.modules import teacher_module

    monkeypatch.setattr(cfg, "NVIDIA_NIM_API_KEY", "test-key", raising=False)

    class FailingNIM:
        def __init__(self, **kw):
            pass

        def _ask_once(self, *a, **kw):
            raise RuntimeError("NIM down")

    monkeypatch.setattr(nim_mod, "NIMClient", FailingNIM)

    calls = {}

    def fake_call_ollama(prompt, model=None, num_predict=None, num_ctx=None):
        calls["model"] = model
        calls["num_predict"] = num_predict
        return '{"graded": [{"score": 0.5}], "final_score": 0.5}'

    monkeypatch.setattr(llm_utils, "call_ollama", fake_call_ollama)

    grader = teacher_module._make_exam_grader_fn("qwen3:8b")
    out = grader("grade this")

    assert calls["model"] == "qwen3:8b"        # fell back to the examiner...
    assert calls["model"] != "llama3.1:8b"     # ...NOT the student
    assert calls["num_predict"] == 2048        # grader fallback cap
    assert "graded" in out


def test_examiner_timeouts_grader_longer_than_author(monkeypatch):
    """The grader gets a longer NIM timeout (240s) than the author (120s): a
    full 6-question rubric measured ~170s, and the author's 120s would cut it
    off mid-grade -- the exact pitfall that kept grading local until now.
    """
    import maria_core.sys.config as cfg
    import agent_core.llm.nim_client as nim_mod
    from agent_core.modules import teacher_module

    monkeypatch.setattr(cfg, "NVIDIA_NIM_API_KEY", "test-key", raising=False)

    seen = {"timeouts": []}

    class CapturingNIM:
        def __init__(self, **kw):
            seen["timeouts"].append(kw.get("timeout"))

        def _ask_once(self, *a, **kw):
            return "{}"

    monkeypatch.setattr(nim_mod, "NIMClient", CapturingNIM)

    teacher_module._make_exam_author_fn("qwen3:8b")
    teacher_module._make_exam_grader_fn("qwen3:8b")

    assert seen["timeouts"] == [120, 240]


# --- 4. Context cap (answer input-bound fix, 2026-06-06) -----------------------

def test_build_context_cap_samples_evenly():
    """A large file's context is capped by EVEN sampling -- representative
    coverage of the whole file, not just the start -- so the open-book exam
    prompt-eval stays under the CPU timeout (the 2nd storm root)."""
    import re
    mems = [{"summary": "Chunk tresc " + "x" * 200, "key_points": ["a", "b"]}
            for _ in range(100)]
    full = exam_agent.build_context_from_memories(mems)
    capped = exam_agent.build_context_from_memories(mems, max_chars=10000)
    assert len(full) > 10000
    assert len(capped) <= int(10000 * 1.15)        # ~cap, margin on chunk boundary
    nums = sorted(int(m) for m in re.findall(r"Chunk (\d+):", capped))
    assert 1 < len(nums) < 100                       # a sample, not the whole file
    assert nums[0] <= 3 and nums[-1] >= 90           # spread across the file


def test_build_context_small_is_unchanged():
    """Context under the cap is returned whole (no sampling for small files)."""
    mems = [{"summary": "krotkie", "key_points": ["a"]} for _ in range(3)]
    assert (exam_agent.build_context_from_memories(mems)
            == exam_agent.build_context_from_memories(mems, max_chars=10000))


def test_build_context_no_cap_returns_full():
    """No max_chars -> full context (back-compat for callers that don't cap)."""
    mems = [{"summary": "x" * 5000, "key_points": []} for _ in range(10)]
    assert len(exam_agent.build_context_from_memories(mems)) > 10000


def test_execute_exam_answers_concise(monkeypatch):
    """The regular exam answers CONCISE (2026-06-06): verbose output ran ~180s on
    CPU, pushing a single answer to ~381s (the 2nd storm root). Concise keeps it
    ~207s; the LLM grader still scores fact correctness."""
    seen = {}
    monkeypatch.setattr(exam_agent, "get_memories_for_file",
                        lambda fid, mp: [{"summary": "s", "key_points": ["k"]}])
    monkeypatch.setattr(exam_agent, "generate_exam",
                        lambda c, n, llm_fn=None: [{"q": "q", "expected": "e"}])

    def fake_answer(context, qs, llm_fn=None, concise=False):
        seen["concise"] = concise
        return [{"a": "a"}]

    monkeypatch.setattr(exam_agent, "answer_exam", fake_answer)
    monkeypatch.setattr(exam_agent, "grade_exam",
                        lambda qs, a, llm_fn=None: {"graded": [{"score": 1.0}],
                                                    "final_score": 1.0})

    exam_agent._execute_exam("f1", Path("/tmp/x"), llm_fn=lambda p: "s")
    assert seen["concise"] is True
