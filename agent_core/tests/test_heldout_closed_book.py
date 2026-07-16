"""Tests for closed-book held-out exam (beta = retrieval over learned summaries).

Pure/fake: no Ollama, no embeddings. Verifies the retrieval context builder and
that _execute_heldout_exam answers closed-book (retrieval) when a semantic memory
is wired, falls back to open-book otherwise, and records the alpha control.
"""

import json
from pathlib import Path

from maria_core.learning import exam_agent


class _FakeEntry:
    def __init__(self, text, source_file, entry_id):
        self.text = text
        self.metadata = {"source_file": source_file}
        self.entry_id = entry_id


class _FakeResult:
    def __init__(self, text, source_file, entry_id, score=0.8):
        self.entry = _FakeEntry(text, source_file, entry_id)
        self.score = score


class _FakeSemMem:
    def __init__(self, default=None):
        self.default = default or []
        self.calls = []

    def search(self, query, namespace=None, top_k=10, threshold=0.3):
        self.calls.append((query, namespace))
        return self.default


def test_retrieval_context_unions_and_dedups():
    r1 = _FakeResult("chunk A chemia", "chemia.txt", "summary:chemia#0")
    r2 = _FakeResult("chunk B biologia", "biologia.txt", "summary:biologia#0")
    sm = _FakeSemMem(default=[r1, r2])
    questions = [{"q": "co bada chemia"}, {"q": "co bada biologia"}]
    ctx = exam_agent.build_context_from_retrieval(sm, questions, top_k=4)
    assert "chunk A chemia" in ctx and "chunk B biologia" in ctx
    # both questions return both chunks -> each appears exactly once (dedup)
    assert ctx.count("chunk A chemia") == 1
    # searched the 'summaries' namespace, once per question
    assert all(ns == "summaries" for _, ns in sm.calls)
    assert len(sm.calls) == 2


def test_retrieval_context_excludes_file():
    r1 = _FakeResult("chemia chunk", "chemia.txt", "summary:chemia#0")
    r2 = _FakeResult("fizyka chunk", "fizyka.txt", "summary:fizyka#0")
    sm = _FakeSemMem(default=[r1, r2])
    ctx = exam_agent.build_context_from_retrieval(sm, [{"q": "x"}], exclude_file="chemia.txt")
    assert "chemia chunk" not in ctx and "fizyka chunk" in ctx


def test_retrieval_context_none_memory_returns_empty():
    assert exam_agent.build_context_from_retrieval(None, [{"q": "x"}]) == ""


def test_retrieval_survives_search_exception():
    class _Boom:
        def search(self, *a, **k):
            raise RuntimeError("embed down")
    # must not raise; returns empty context
    assert exam_agent.build_context_from_retrieval(_Boom(), [{"q": "x"}]) == ""


def test_heldout_closed_book_uses_retrieval_not_spoonfeed(monkeypatch):
    bank = [{"file": "f.txt", "q": "Pytanie 1?", "match": "contains", "canonical": "alfa"}]
    sm = _FakeSemMem(default=[_FakeResult("kontekst alfa", "other.txt", "summary:other#0")])

    # open-book path must NOT be used in closed-book mode
    def _boom(*a, **k):
        raise AssertionError("get_memories_for_file used in closed-book mode")
    monkeypatch.setattr(exam_agent, "get_memories_for_file", _boom)

    contexts = []
    concise_flags = []

    def fake_answer_exam(context, questions, llm_fn=None, concise=False):
        contexts.append(context)
        concise_flags.append(concise)
        return [{"a": "odpowiedz alfa"} for _ in questions]
    monkeypatch.setattr(exam_agent, "answer_exam", fake_answer_exam)

    score, exam, answers, grading = exam_agent._execute_heldout_exam(
        "f.txt", None, bank, llm_fn=lambda p: "", semantic_memory=sm,
    )
    assert grading["closed_book"] is True
    assert "alpha_score" in grading
    # beta context = retrieved chunk; alpha control context = empty
    assert "kontekst alfa" in contexts[0]
    assert contexts[1] == ""
    assert len(contexts) == 2
    assert score == 1.0
    # held-out (deterministic grader) must answer concise for both beta + alpha
    assert concise_flags == [True, True]


def test_heldout_open_book_fallback_without_semantic_memory(monkeypatch):
    bank = [{"file": "f.txt", "q": "Pytanie?", "match": "contains", "canonical": "alfa"}]
    monkeypatch.setattr(exam_agent, "get_memories_for_file",
                        lambda fid, mp: [{"summary": "spoon fed", "key_points": []}])
    monkeypatch.setattr(exam_agent, "answer_exam",
                        lambda c, q, llm_fn=None, concise=False: [{"a": "alfa"} for _ in q])
    score, exam, answers, grading = exam_agent._execute_heldout_exam(
        "f.txt", None, bank, llm_fn=lambda p: "",
    )
    assert grading.get("closed_book") is False
    # C5 (2026-07-12): the alpha control now runs in open-book mode TOO --
    # parroting rate must be measurable exactly where parroting is easiest.
    assert "alpha_score" in grading
    assert score == 1.0


# --- C5 (2026-07-12): open-book production policy + guards + status fix --------

def _bank3(fid="f.txt"):
    return [
        {"file": fid, "q": "q1", "match": "contains", "canonical": "alfa",
         "bank_version": "v3"},
        {"file": fid, "q": "q2", "match": "contains", "canonical": "beta",
         "bank_version": "v3"},
        {"file": fid, "q": "q3", "match": "contains", "canonical": "gamma",
         "bank_version": "v3"},
    ]


def _student_factory(good=True):
    """Student echoing canonicals (context run) and blanks (alpha run)."""
    def student(prompt):
        if "alfa" in prompt or "Kontekst" in prompt and len(prompt) > 60:
            pass
        answers = (["alfa", "beta", "gamma"] if good and prompt.strip()
                   else ["nie wiem", "nie wiem", "nie wiem"])
        return json.dumps({"answers": [{"a": a} for a in answers]})
    return student


def test_open_book_heldout_records_alpha(monkeypatch):
    """C5: the alpha control (empty-context run) is scored in OPEN-BOOK mode
    too -- open-book contains-grading over a handed summary is the most
    parroting-prone configuration, so score-vs-alpha must be measurable."""
    monkeypatch.setattr(
        exam_agent, "get_memories_for_file",
        lambda fid, mp: [{"summary": "alfa beta gamma", "key_points": []}],
    )
    calls = {"n": 0}

    def student(prompt):
        calls["n"] += 1
        # Contextful run sees the summary text; the alpha run's prompt has an
        # EMPTY context block (the template itself is never empty).
        good = "alfa beta gamma" in prompt
        answers = ["alfa", "beta", "gamma"] if good else ["x", "y", "z"]
        return json.dumps({"answers": [{"a": a} for a in answers]})

    score, exam, answers, grading = exam_agent._execute_heldout_exam(
        "f.txt", Path("/tmp/x"), _bank3(), llm_fn=student,
        semantic_memory=None,  # production: open-book
    )
    assert score == 1.0
    assert grading["closed_book"] is False
    assert grading["alpha_score"] == 0.0   # measured, not None
    assert calls["n"] == 2                 # context run + alpha run


def test_closed_book_empty_retrieval_falls_back_open_book(monkeypatch):
    """C5 guard: empty retrieval (fresh file, summaries indexed only at boot)
    must not grade a blind student -- fall back to open-book, honestly
    recorded closed_book=False."""
    class EmptySemMem:
        def search(self, *a, **k):
            return []

    monkeypatch.setattr(
        exam_agent, "get_memories_for_file",
        lambda fid, mp: [{"summary": "alfa beta gamma", "key_points": []}],
    )

    def student(prompt):
        good = "alfa beta gamma" in prompt
        answers = ["alfa", "beta", "gamma"] if good else ["x", "y", "z"]
        return json.dumps({"answers": [{"a": a} for a in answers]})

    score, exam, answers, grading = exam_agent._execute_heldout_exam(
        "f.txt", Path("/tmp/x"), _bank3(), llm_fn=student,
        semantic_memory=EmptySemMem(),
    )
    assert score == 1.0                    # open-book context rescued the run
    assert grading["closed_book"] is False


def test_heldout_fail_leaves_index_status_untouched(monkeypatch, tmp_path):
    """C5 status fix: a failed held-out drill must not stamp COMPLETED (the
    is_spaced fail branch) nor brand HARD_TOPIC -- the verdict lives in
    exam_results; the index must not lie."""
    rec = {"id": "f.txt", "status": exam_agent.STATUS_LEARNED,
           "exam_attempts": 1,  # a 2nd fail would brand HARD_TOPIC on auto path
           "last_scores": [0.2], "priority": 10}
    monkeypatch.setattr(exam_agent, "load_index", lambda p: [rec])
    monkeypatch.setattr(exam_agent, "save_index", lambda idx, p: None)
    monkeypatch.setattr(exam_agent, "append_exam_result", lambda d, p: None)
    monkeypatch.setattr(
        exam_agent, "get_memories_for_file",
        lambda fid, mp: [{"summary": "nic", "key_points": []}],
    )
    bank_path = tmp_path / "bank.jsonl"
    bank_path.write_text(
        "\n".join(json.dumps(r) for r in _bank3()) + "\n", encoding="utf-8")

    def student(prompt):
        return json.dumps({"answers": [
            {"a": "zle"}, {"a": "zle"}, {"a": "zle"}]})

    out = exam_agent.run_exam_if_ready(
        index_path=tmp_path / "i.json", memory_path=tmp_path / "m",
        exam_path=tmp_path / "e.jsonl", llm_fn=student,
        target_file_id="f.txt", use_heldout=True,
        heldout_bank_path=bank_path,
    )
    assert out["executed"] is True
    assert out["passed"] is False
    assert rec["status"] == exam_agent.STATUS_LEARNED   # untouched
    assert rec["exam_attempts"] == 2                     # attempts still count

    # ...and a PASS still promotes to COMPLETED.
    def good_student(prompt):
        answers = ["alfa", "beta", "gamma"]
        return json.dumps({"answers": [{"a": a} for a in answers]})

    rec["status"] = exam_agent.STATUS_LEARNED
    out = exam_agent.run_exam_if_ready(
        index_path=tmp_path / "i.json", memory_path=tmp_path / "m",
        exam_path=tmp_path / "e.jsonl", llm_fn=good_student,
        target_file_id="f.txt", use_heldout=True,
        heldout_bank_path=bank_path,
    )
    assert out["passed"] is True
    assert rec["status"] == exam_agent.STATUS_COMPLETED


def test_heldout_pass_skips_looping_brand(monkeypatch, tmp_path):
    """Fix A (diff-review 2026-07-12): repeated similar held-out PASS scores are
    a property of mechanical grading -- check_for_looping must not brand the
    file HARD_TOPIC (that drops it from the 'completed' bucket and silently
    wedges the heldout goal's verified/N credit)."""
    rec = {"id": "f.txt", "status": exam_agent.STATUS_LEARNED,
           "exam_attempts": 3,
           # identical history -- the looping detector's trigger shape
           "last_scores": [1.0, 1.0, 1.0], "priority": 10}
    monkeypatch.setattr(exam_agent, "load_index", lambda p: [rec])
    monkeypatch.setattr(exam_agent, "save_index", lambda idx, p: None)
    monkeypatch.setattr(exam_agent, "append_exam_result", lambda d, p: None)
    monkeypatch.setattr(
        exam_agent, "get_memories_for_file",
        lambda fid, mp: [{"summary": "alfa beta gamma", "key_points": []}],
    )
    monkeypatch.setattr(exam_agent, "check_for_looping", lambda r: True)
    bank_path = tmp_path / "bank.jsonl"
    bank_path.write_text(
        "\n".join(json.dumps(r) for r in _bank3()) + "\n", encoding="utf-8")

    def student(prompt):
        return json.dumps({"answers": [
            {"a": "alfa"}, {"a": "beta"}, {"a": "gamma"}]})

    out = exam_agent.run_exam_if_ready(
        index_path=tmp_path / "i.json", memory_path=tmp_path / "m",
        exam_path=tmp_path / "e.jsonl", llm_fn=student,
        target_file_id="f.txt", use_heldout=True,
        heldout_bank_path=bank_path,
    )
    assert out["passed"] is True
    assert rec["status"] == exam_agent.STATUS_COMPLETED  # not HARD_TOPIC
