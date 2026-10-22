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
    # C5 (2026-07-12): context run + the alpha control (empty-context) --
    # the parroting-rate measurement now runs in open-book mode too.
    assert len(student_calls) == 2
    assert "alpha_score" in grading


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
    _rows = [
        {"file": "expert_fotosynteza.txt", "q": "Co pochlania swiatlo?",
         "match": "contains", "canonical": "chlorofil", "bank_version": "v1"},
        {"file": "expert_fotosynteza.txt", "q": "Gdzie zachodzi fotosynteza?",
         "match": "contains", "canonical": "chloroplast", "bank_version": "v1"},
        {"file": "expert_fotosynteza.txt", "q": "Jaki gaz jest pochlaniany?",
         "match": "contains", "canonical": "dwutlenek wegla", "bank_version": "v1"},
    ]  # C3: >= HELDOUT_MIN_BANK_ROWS, else the exam honestly falls back
    bank_path.write_text(
        "\n".join(json.dumps(r) for r in _rows) + "\n", encoding="utf-8",
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
        return json.dumps({"answers": [
            {"a": "chlorofil"}, {"a": "chloroplast"}, {"a": "dwutlenek wegla"},
        ]})

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
    # C3: the record is stamped -- a requested-but-missed heldout is visible
    # in the trust data, not bit-identical to a regular exam.
    assert recorded["heldout_fallback"] is True
    assert out["heldout_fallback"] is True


def test_teacher_module_heldout_is_per_exam_not_env(monkeypatch):
    """C8 keystone (red-team 2026-07-11 CRITICAL #2): the env flag must NOT
    flip grading globally -- with it set, a regular exam still uses the LLM
    examiner; only an explicit use_heldout=True from the EXAM handler (plan
    grader='heldout') selects the mechanical path. The old blanket read would
    have routed live Kronika reviews through the uncalibrated static grader
    the moment bank rows existed for their files."""
    from agent_core.modules.teacher_module import TeacherModule

    captured = {}

    def fake_run_exam_if_ready(**kwargs):
        captured.update(kwargs)
        return {"executed": True, "passed": True, "score": 1.0, "file_id": "f1"}

    monkeypatch.setenv("HELDOUT_GRADER_ENABLED", "true")
    monkeypatch.setattr(exam_agent, "run_exam_if_ready", fake_run_exam_if_ready)

    module = TeacherModule()

    # Regular exam: env flag armed, but grading stays LLM.
    out = module._run_exam_wrapped("f1")
    assert out["success"] is True
    assert captured["use_heldout"] is False

    # B4 drill: explicit opt-in from the handler selects held-out grading.
    captured.clear()
    out = module._run_exam_wrapped("f1", use_heldout=True)
    assert out["success"] is True
    assert captured["use_heldout"] is True
    # Independence MUST hold either way -- the examiner (NIM or fallback) is
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


# --- 3. Local examiner (author + grader): never the student, never NIM ---------

def test_grader_runs_on_examiner_never_student(monkeypatch):
    """Trust-regime keystone: grading runs on the local EXAMINER model
    (independent), NEVER the student model.

    The independence guarantee survived two backend eras (local qwen3 ->
    NIM-first -> local again 2026-08-10); this pins the invariant that outlived
    them: whatever runs the grade, it is not the model being examined.
    """
    import maria_core.learning.llm_utils as llm_utils
    from agent_core.modules import teacher_module

    calls = {}

    def fake_call_ollama(prompt, model=None, num_predict=None, num_ctx=None):
        calls["model"] = model
        calls["num_predict"] = num_predict
        return '{"graded": [{"score": 0.5}], "final_score": 0.5}'

    monkeypatch.setattr(llm_utils, "call_ollama", fake_call_ollama)

    grader = teacher_module._make_exam_grader_fn("qwen3:8b")
    out = grader("grade this")

    assert calls["model"] == "qwen3:8b"        # the examiner...
    assert calls["model"] != "llama3.1:8b"     # ...NOT the student
    assert calls["num_predict"] == 2048        # grader cap
    assert "graded" in out


def test_examiner_never_touches_nim(monkeypatch):
    """Exam author + grader stay LOCAL even with a NIM key configured
    (2026-08-10): the nemotron swap recalibrated the whole exam without a code
    change (fail 16% -> 45-58%), and NIM credits expire 2026-08-18. The exam
    must not silently return to NIM with the next working key.
    """
    import maria_core.sys.config as cfg
    import maria_core.learning.llm_utils as llm_utils
    import agent_core.llm.nim_client as nim_mod
    from agent_core.modules import teacher_module

    monkeypatch.setattr(cfg, "NVIDIA_NIM_API_KEY", "test-key", raising=False)

    constructed = {"n": 0}

    class CountingNIM:
        def __init__(self, **kw):
            constructed["n"] += 1

        def _ask_once(self, *a, **kw):
            return "{}"

    monkeypatch.setattr(nim_mod, "NIMClient", CountingNIM)

    calls = {"models": []}
    monkeypatch.setattr(
        llm_utils, "call_ollama",
        lambda prompt, model=None, num_predict=None, num_ctx=None: (
            calls["models"].append(model) or '{"exam": []}'),
    )

    author = teacher_module._make_exam_author_fn("qwen3:8b")
    grader = teacher_module._make_exam_grader_fn("qwen3:8b")
    author("write questions")
    grader("grade answers")

    assert constructed["n"] == 0               # NIM never even constructed
    assert calls["models"] == ["qwen3:8b", "qwen3:8b"]


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


# --- 5. Actual-grader provenance (C4, 2026-07-12) ------------------------------

def test_used_cell_records_local_examiner(monkeypatch):
    """The cell records the ACTUAL local backend that graded -- provenance
    stays honest now that the examiner is pinned local (2026-08-10)."""
    import maria_core.learning.llm_utils as llm_utils
    from agent_core.modules import teacher_module

    monkeypatch.setattr(llm_utils, "call_ollama",
                        lambda *a, **kw: '{"final_score": 0.5, "graded": []}')

    cell = {"backend": None}
    grader = teacher_module._make_exam_grader_fn("qwen3:8b", used_cell=cell)
    grader("grade this")
    assert cell["backend"] == "local:qwen3:8b"


def test_used_cell_records_suppressed_on_cooling(
    monkeypatch, isolated_local_compute_coordinator,
):
    """Thermal cooling blocks the examiner (returns None) and the cell says so
    -- a cooled-off grade must never look like a graded exam in provenance."""
    import maria_core.learning.llm_utils as llm_utils
    from agent_core.modules import teacher_module

    called = {"n": 0}
    monkeypatch.setattr(llm_utils, "call_ollama",
                        lambda *a, **kw: called.__setitem__("n", called["n"] + 1))

    isolated_local_compute_coordinator.enter_cooling()
    cell = {"backend": None}
    grader = teacher_module._make_exam_grader_fn("qwen3:8b", used_cell=cell)
    out = grader("grade this")

    assert out is None
    assert cell["backend"] == "local:suppressed"
    assert called["n"] == 0


def test_record_carries_actual_grader_and_author(monkeypatch, tmp_path):
    """run_exam_if_ready copies the ACTUAL backends from the cells into the
    record (grader_model/author_model), falling back to the planned label only
    when no cell was supplied (old callers stay valid)."""
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

    exam_agent.run_exam_if_ready(
        index_path=tmp_path / "i.json", memory_path=tmp_path / "m",
        exam_path=tmp_path / "e.jsonl", target_file_id="f1",
        grader_meta={
            "independent": True,
            "grader": "nim-first|qwen3:8b",
            "student": "llama3.1:8b",
            "grader_cell": {"backend": "local:qwen3:8b"},
            "author_cell": {"backend": "nim:dracarys-test-70b"},
        },
    )
    assert recorded["grader_model"] == "local:qwen3:8b"
    assert recorded["author_model"] == "nim:dracarys-test-70b"

    # Old caller without cells: planned label preserved, author unknown.
    recorded.clear()
    rec["exam_attempts"] = 0
    exam_agent.run_exam_if_ready(
        index_path=tmp_path / "i.json", memory_path=tmp_path / "m",
        exam_path=tmp_path / "e.jsonl", target_file_id="f1",
        grader_meta={"independent": True, "grader": "nemotron-49b",
                     "student": "llama3.1:8b"},
    )
    assert recorded["grader_model"] == "nemotron-49b"
    assert recorded["author_model"] is None


# --- 6. Numeric matcher for Polish market content (C10, 2026-07-12) ------------

def test_numeric_parses_space_grouped_thousands():
    """'68 250' is 68250, not 68 -- the old regex stopped at the group separator,
    a systematic false-FAIL on Polish price formats (red-team 2026-07-11)."""
    assert exam_agent._first_number("68 250") == 68250
    assert exam_agent._all_numbers("kurs 68 250,50 zl") == [68250.5]
    assert exam_agent._all_numbers("1 234 567 USD") == [1234567.0]


def test_numeric_matches_any_number_not_first():
    """Concise Polish answers open with years/dates; the canonical value may sit
    later in the sentence. ANY in-tolerance number passes, first-only failed."""
    row = {"match": "numeric", "canonical": "500000", "tolerance": 1000}
    score, detail = exam_agent._score_heldout_answer(
        row, "W 2029 roku bitcoin osiagnie 500 000 USD")
    assert score == 1.0

    # Wrong value still fails, even among multiple numbers.
    score, detail = exam_agent._score_heldout_answer(
        row, "W 2029 roku bitcoin osiagnie 700 000 USD")
    assert score == 0.0
    assert "closest" in detail


def test_numeric_multi_group_dot_thousands():
    """'1.234.567' (dot thousands) parses whole; single '0,833' stays decimal."""
    assert exam_agent._all_numbers("cena 1.234.567 oraz 0,833") == [1234567.0, 0.833]


def test_numeric_no_number_in_answer_fails():
    row = {"match": "numeric", "canonical": "42", "tolerance": 5}
    score, _ = exam_agent._score_heldout_answer(row, "nie wiem")
    assert score == 0.0


def test_numeric_date_fragments_not_parsed_as_negatives():
    """'2026-07-12' must not yield -7 and -12 (diff-review 2026-07-12): a sign
    glued to the previous digit is a separator. Standalone negatives survive."""
    assert exam_agent._all_numbers("Data publikacji: 2026-07-12") == [2026.0]
    assert exam_agent._all_numbers("spadek o -5 procent") == [-5.0]
    row = {"match": "numeric", "canonical": "-12", "tolerance": 0}
    score, _ = exam_agent._score_heldout_answer(row, "Raport z 2026-07-12")
    assert score == 0.0


# --- 7. Exam calibration prompts (2026-08-10) ----------------------------------
# The nemotron era proved the exam's difficulty lives in the PROMPTS' slack:
# the same templates produced 62-char factual questions under dracarys and
# 153-char multi-part essays under nemotron (fail 16% -> 45-58%, same student).
# These pins hold the calibration rules so a future prompt edit cannot silently
# reopen that slack.

def test_generate_prompt_pins_single_clause_questions():
    p = exam_agent.PROMPT_GENERATE_EXAM
    assert "JEDNYM poleceniem" in p          # one task per question
    assert "1-2 zdania" in p                 # short expected answer
    assert "NIE wyliczaj" in p               # expected = essence, not a checklist


def test_grade_prompt_pins_correctness_over_completeness():
    p = exam_agent.PROMPT_GRADE_EXAM
    assert "nie kompletność" in p            # grade what IS there
    assert "0.6-0.8" in p                    # concise-but-correct band
    assert "wyrozumiały dla zwięzłości" in p  # brevity is not an error


# --- 8. Staged exam pipeline (2026-08-10) --------------------------------------
# Three back-to-back heavy generations overheat past the 80C cooling latch
# (baseline 75-79C), which used to discard the whole exam mid-flight (3/3 on
# 2026-08-10). With stage_path the pipeline runs ONE heavy stage per call and
# persists state between calls -- surviving cooling gaps and daemon restarts.

def _staged_setup(monkeypatch, tmp_path, records=None):
    """Wire run_exam_if_ready mocks for staged-flow tests."""
    recorded = {}
    recs = records or [
        {"id": "f1", "status": STATUS_LEARNED, "exam_attempts": 0,
         "last_scores": [], "priority": 10},
    ]
    monkeypatch.setattr(exam_agent, "load_index", lambda p: recs)
    monkeypatch.setattr(exam_agent, "save_index", lambda idx, p: None)
    monkeypatch.setattr(exam_agent, "append_exam_result",
                        lambda d, p: recorded.update(d))
    monkeypatch.setattr(
        exam_agent, "get_memories_for_file",
        lambda fid, mp: [{"summary": "s", "key_points": ["k"]}],
    )
    monkeypatch.setattr(
        exam_agent, "generate_exam",
        lambda c, n, llm_fn=None: [{"q": "q1", "expected": "e1"}],
    )
    monkeypatch.setattr(
        exam_agent, "answer_exam",
        lambda c, qs, llm_fn=None, concise=False: [{"a": "a1"}],
    )
    monkeypatch.setattr(
        exam_agent, "grade_exam",
        lambda qs, ans, llm_fn=None: {
            "graded": [{"score": 0.9}], "final_score": 0.9},
    )
    return recs, recorded


def _run_staged(tmp_path, stage):
    return exam_agent.run_exam_if_ready(
        index_path=tmp_path / "i.jsonl", memory_path=tmp_path / "m.jsonl",
        exam_path=tmp_path / "e.jsonl", stage_path=stage,
    )


def test_staged_exam_three_calls_complete(monkeypatch, tmp_path):
    """authored -> answered -> complete across three calls; state file lives
    between calls and is gone after grading; the record lands on call 3."""
    recs, recorded = _staged_setup(monkeypatch, tmp_path)
    stage = tmp_path / "exam_stage.json"

    r1 = _run_staged(tmp_path, stage)
    assert r1["executed"] is False and r1["staged"] == "authored"
    assert json.loads(stage.read_text())["stage"] == "authored"
    assert recorded == {}                       # nothing recorded yet

    r2 = _run_staged(tmp_path, stage)
    assert r2["executed"] is False and r2["staged"] == "answered"
    assert json.loads(stage.read_text())["answers"] == [{"a": "a1"}]

    r3 = _run_staged(tmp_path, stage)
    assert r3["executed"] is True and r3["passed"] is True
    assert r3["score"] == 0.9
    assert not stage.exists()                   # state cleared
    assert recorded["file"] == "f1"
    assert recs[0]["exam_attempts"] == 1        # attempt counted ONCE, at grade


def test_staged_exam_resumes_pending_over_target(monkeypatch, tmp_path):
    """A pending staged exam resumes FIRST even when the caller targets
    another file -- one exam in flight at a time, the target waits."""
    recs, _ = _staged_setup(monkeypatch, tmp_path, records=[
        {"id": "fX", "status": STATUS_LEARNED, "exam_attempts": 0,
         "last_scores": [], "priority": 10},
        {"id": "fY", "status": STATUS_LEARNED, "exam_attempts": 0,
         "last_scores": [], "priority": 99},
    ])
    stage = tmp_path / "exam_stage.json"
    exam_agent._save_exam_stage(stage, {
        "file_id": "fX", "stage": "authored",
        "questions": [{"q": "q1", "expected": "e1"}],
        "started_at": "now", "started_ts": time_now(),
    })

    r = exam_agent.run_exam_if_ready(
        index_path=tmp_path / "i.jsonl", memory_path=tmp_path / "m.jsonl",
        exam_path=tmp_path / "e.jsonl", stage_path=stage,
        target_file_id="fY",
    )
    assert r["file_id"] == "fX"
    assert r["staged"] == "answered"


def test_staged_exam_stale_state_discarded(monkeypatch, tmp_path):
    """State older than EXAM_STAGE_MAX_AGE_H is dropped; the call starts a
    fresh stage-1 instead of resuming a fossil."""
    _staged_setup(monkeypatch, tmp_path)
    stage = tmp_path / "exam_stage.json"
    exam_agent._save_exam_stage(stage, {
        "file_id": "f1", "stage": "answered",
        "questions": [{"q": "q", "expected": "e"}], "answers": [{"a": "a"}],
        "started_at": "old",
        "started_ts": time_now() - (exam_agent.EXAM_STAGE_MAX_AGE_H + 1) * 3600,
    })

    r = _run_staged(tmp_path, stage)
    assert r["staged"] == "authored"            # fresh start, not a grade


def test_staged_exam_corrupt_state_discarded(monkeypatch, tmp_path):
    """Unparseable state file is discarded (with a fresh stage-1), never a crash."""
    _staged_setup(monkeypatch, tmp_path)
    stage = tmp_path / "exam_stage.json"
    stage.write_text("not-json{", encoding="utf-8")

    r = _run_staged(tmp_path, stage)
    assert r["staged"] == "authored"


def test_staged_exam_failed_stage_clears_state(monkeypatch, tmp_path):
    """A stage that fails (student returns nothing) clears the state so the
    next attempt starts clean, and reports a pipeline failure (executed=False,
    no staged marker)."""
    recs, _ = _staged_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(exam_agent, "answer_exam",
                        lambda c, qs, llm_fn=None, concise=False: None)
    stage = tmp_path / "exam_stage.json"
    exam_agent._save_exam_stage(stage, {
        "file_id": "f1", "stage": "authored",
        "questions": [{"q": "q", "expected": "e"}],
        "started_at": "now", "started_ts": time_now(),
    })

    r = _run_staged(tmp_path, stage)
    assert r["executed"] is False
    assert "staged" not in r
    assert not stage.exists()


def time_now():
    import time as _t
    return _t.time()


def test_exam_wrapped_thermal_defer(monkeypatch, isolated_local_compute_coordinator):
    """During active cooling _run_exam_wrapped defers with skipped=True and
    never reaches run_exam_if_ready -- no work starts on a hot CPU."""
    from agent_core.modules.teacher_module import TeacherModule

    called = {"n": 0}
    monkeypatch.setattr(
        exam_agent, "run_exam_if_ready",
        lambda **kw: called.__setitem__("n", called["n"] + 1) or {},
    )
    isolated_local_compute_coordinator.enter_cooling()

    mod = TeacherModule.__new__(TeacherModule)
    out = mod._run_exam_wrapped("f1")

    assert out["skipped"] is True and out["success"] is False
    assert called["n"] == 0


def test_staged_exam_author_provenance_survives_staging(monkeypatch, tmp_path):
    """The author runs two calls before the record is written (with fresh
    cells each call) -- its backend must be snapshotted into the staged state
    at stage 1 and land in the final record."""
    recs, recorded = _staged_setup(monkeypatch, tmp_path)
    stage = tmp_path / "exam_stage.json"

    def run(meta):
        return exam_agent.run_exam_if_ready(
            index_path=tmp_path / "i.jsonl", memory_path=tmp_path / "m.jsonl",
            exam_path=tmp_path / "e.jsonl", stage_path=stage,
            grader_meta=meta,
        )

    # Call 1: the author fn "ran" and its cell holds the actual backend.
    run({"author_cell": {"backend": "local:qwen3:8b"}})
    # Calls 2-3: fresh (empty) cells, as every real session builds new ones.
    run({"author_cell": {"backend": None}})
    r3 = run({"author_cell": {"backend": None},
              "grader_cell": {"backend": "local:qwen3:8b"}})

    assert r3["executed"] is True
    assert recorded["author_model"] == "local:qwen3:8b"
    assert recorded["grader_model"] == "local:qwen3:8b"
