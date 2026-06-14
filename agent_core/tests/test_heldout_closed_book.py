"""Tests for closed-book held-out exam (beta = retrieval over learned summaries).

Pure/fake: no Ollama, no embeddings. Verifies the retrieval context builder and
that _execute_heldout_exam answers closed-book (retrieval) when a semantic memory
is wired, falls back to open-book otherwise, and records the alpha control.
"""

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
    assert "alpha_score" not in grading  # no alpha control in open-book mode
    assert score == 1.0
