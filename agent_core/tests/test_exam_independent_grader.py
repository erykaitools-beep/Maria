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


# --- 5. Actual-grader provenance (C4, 2026-07-12) ------------------------------

def test_used_cell_records_local_fallback(monkeypatch):
    """When NIM fails, the cell records the LOCAL fallback backend -- the
    NIM-vs-fallback split used to be invisible behind the constant label."""
    import maria_core.sys.config as cfg
    import maria_core.learning.llm_utils as llm_utils
    import agent_core.llm.nim_client as nim_mod
    from agent_core.modules import teacher_module

    monkeypatch.setattr(cfg, "NVIDIA_NIM_API_KEY", "test-key", raising=False)

    class FailingNIM:
        def __init__(self, **kw):
            self.model = kw.get("model")

        def _ask_once(self, *a, **kw):
            raise RuntimeError("NIM down")

    monkeypatch.setattr(nim_mod, "NIMClient", FailingNIM)
    monkeypatch.setattr(llm_utils, "call_ollama",
                        lambda *a, **kw: '{"final_score": 0.5, "graded": []}')

    cell = {"backend": None}
    grader = teacher_module._make_exam_grader_fn("qwen3:8b", used_cell=cell)
    grader("grade this")
    assert cell["backend"] == "local:qwen3:8b"


def test_used_cell_records_nim_success(monkeypatch):
    """When NIM answers, the cell records nim:<model> -- the REAL grader, which
    on the live box is dracarys (a Llama-3.1 finetune, same lineage as the
    student), not the 'different family' the old constant label implied."""
    import maria_core.sys.config as cfg
    import agent_core.llm.nim_client as nim_mod
    from agent_core.modules import teacher_module

    monkeypatch.setattr(cfg, "NVIDIA_NIM_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(cfg, "NVIDIA_NIM_MODEL", "dracarys-test-70b", raising=False)

    class OkNIM:
        def __init__(self, **kw):
            self.model = kw.get("model")

        def _ask_once(self, *a, **kw):
            return '{"final_score": 1.0, "graded": []}'

    monkeypatch.setattr(nim_mod, "NIMClient", OkNIM)

    cell = {"backend": None}
    grader = teacher_module._make_exam_grader_fn("qwen3:8b", used_cell=cell)
    grader("grade this")
    assert cell["backend"] == "nim:dracarys-test-70b"


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
