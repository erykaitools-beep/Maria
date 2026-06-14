"""Held-out per-question sub-scoring drill (post-audit #3, firm-up step b).

The aggregate drill (heldout_rebaseline_drill.py) reports one beta/alpha number
per file, which conflates two kinds of question:
  - GENERAL: the bare model already knows it from priors (alpha=1) -> retrieval
    is irrelevant to passing.
  - DOCUMENT-SPECIFIC: priors don't cover it (alpha=0) -> retrieval is what
    decides pass/fail. This is the ONLY place beta should beat alpha.

Reporting beta-vs-alpha on the whole bank therefore hides the real signal. This
drill breaks it down per question and separates THREE independent failure modes:
  1. retrieval HIT  : does per-question search even surface the answer chunk?
  2. pooled CTX     : does the shared (max_chunks-capped) exam context keep it?
  3. student USE    : did the student actually answer with it (beta pass)?

Key metric -- retrieval LIFT = #(alpha=0 & beta=1) / #(alpha=0): of the questions
the bare model could NOT answer, how many did retrieval rescue. High = retrieval
is consistent; low = retrieval misses or the student ignores it.

Read-only and side-effect free: writes nothing, never flips the HELDOUT flag.

Usage:
    venv/bin/python scripts/heldout_subscore_drill.py [file_id ...]
"""

import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_core.semantic import SemanticMemory
from maria_core.learning.exam_agent import (
    build_context_from_retrieval,
    answer_exam,
    grade_heldout,
    select_heldout_rows,
    load_heldout_bank,
    _normalize_match_text,
    _first_number,
)
from maria_core.learning.llm_utils import call_ollama
from maria_core.sys.config import OLLAMA_MODEL, HELDOUT_BANK, BASE_DIR

DEFAULT_FILES = [
    "web_wiki_chemia.txt",
    "web_wiki_biologia.txt",
    "web_wiki_fizyka.txt",
]


def _retrieval_hit(sm, qtext, row, top_k=4, threshold=0.3) -> bool:
    """Does per-question retrieval surface a chunk containing the answer?

    Uses the bank row's match_type (regex/numeric/contains) -- the SAME way the
    grader checks a student answer. A naive substring check is wrong here because
    most canonicals are regexes ('\\bIV\\b|czwart'), which never appear literally
    -> it falsely reported ~27% hit when regex-aware matching shows ~71%.
    Measures retrieval quality independent of the pooled cap and of the student.
    """
    try:
        results = sm.search(qtext, namespace="summaries", top_k=top_k * 2, threshold=threshold)
    except Exception:
        return False
    text = " ".join(getattr(r.entry, "text", "") for r in results[:top_k])
    match_type = str(row.get("match", "contains")).lower()
    canonical = str(row.get("canonical", ""))
    pattern = str(row.get("pattern", ""))
    if match_type == "regex":
        rx = pattern or canonical
        try:
            return bool(rx) and re.search(rx, text, flags=re.IGNORECASE) is not None
        except re.error:
            return False
    if match_type == "numeric":
        expected = _first_number(canonical or pattern)
        actual = _first_number(text)
        return expected is not None and actual is not None and expected == actual
    canon = _normalize_match_text(canonical)
    return bool(canon) and canon in _normalize_match_text(text)


def _rows_to_exam(rows):
    return [
        {"q": str(r.get("q", "")), "expected": str(r.get("canonical") or r.get("pattern") or "")}
        for r in rows if r.get("q")
    ]


def main():
    files = sys.argv[1:] or DEFAULT_FILES

    sm = SemanticMemory(data_dir=str(BASE_DIR / "meta_data"))
    sm.initialize()
    n_sum = len(sm.store.list_ids_by_namespace("summaries")) if hasattr(sm.store, "list_ids_by_namespace") else "?"
    print(f"summaries index: {n_sum} chunks loaded\n")

    bank = load_heldout_bank(HELDOUT_BANK)
    llm_fn = lambda p: call_ollama(p, model=OLLAMA_MODEL, num_predict=2048, num_ctx=8192)

    tot_azero = tot_lift = tot_hit_on_azero = tot_regress = 0

    for fid in files:
        rows = select_heldout_rows(fid, bank)
        if not rows:
            print(f"{fid}: (no bank rows)\n")
            continue
        exam = _rows_to_exam(rows)

        # Beta: pooled retrieval context (production path). Alpha: empty context.
        ctx = build_context_from_retrieval(sm, exam)
        b_ans = answer_exam(ctx, exam, llm_fn=llm_fn, concise=True) or []
        a_ans = answer_exam("", exam, llm_fn=llm_fn, concise=True) or []
        b_graded = (grade_heldout(rows, b_ans) or {}).get("graded", [])
        a_graded = (grade_heldout(rows, a_ans) or {}).get("graded", [])

        print(f"FILE {fid}  (n={len(rows)}, ctx={len(ctx)}c)")
        print(f"  {'a':>2} {'b':>2} {'hit':>3}  question")
        f_azero = f_lift = f_hit = f_regress = 0
        for i, row in enumerate(rows):
            a_pass = int(a_graded[i]["score"]) if i < len(a_graded) else 0
            b_pass = int(b_graded[i]["score"]) if i < len(b_graded) else 0
            hit = _retrieval_hit(sm, exam[i]["q"], row)
            if a_pass == 0:
                f_azero += 1
                if hit:
                    f_hit += 1
                if b_pass == 1:
                    f_lift += 1
            if a_pass == 1 and b_pass == 0:
                f_regress += 1
            flag = ""
            if a_pass == 0 and b_pass == 1:
                flag = "  <- retrieval lift"
            elif a_pass == 1 and b_pass == 0:
                flag = "  <- REGRESSION"
            elif a_pass == 0 and b_pass == 0 and hit:
                flag = "  <- hit but unused"
            print(f"  {a_pass:>2} {b_pass:>2} {('Y' if hit else '.'):>3}  {exam[i]['q'][:60]}{flag}")

        lift_pct = f"{100*f_lift/f_azero:.0f}%" if f_azero else "  -"
        hit_pct = f"{100*f_hit/f_azero:.0f}%" if f_azero else "  -"
        print(f"  -> doc-specific(a=0): {f_azero}  retrieval-lift: {f_lift}/{f_azero} ({lift_pct})  "
              f"hit-on-a0: {f_hit}/{f_azero} ({hit_pct})  regressions: {f_regress}\n")

        tot_azero += f_azero
        tot_lift += f_lift
        tot_hit_on_azero += f_hit
        tot_regress += f_regress

    print("=" * 60)
    lift_pct = f"{100*tot_lift/tot_azero:.0f}%" if tot_azero else "-"
    hit_pct = f"{100*tot_hit_on_azero/tot_azero:.0f}%" if tot_azero else "-"
    print(f"TOTAL doc-specific(a=0): {tot_azero}")
    print(f"  retrieval-lift (a0->b1): {tot_lift}/{tot_azero} ({lift_pct})  "
          f"-- of what priors miss, how much retrieval rescues")
    print(f"  retrieval-hit on a=0:    {tot_hit_on_azero}/{tot_azero} ({hit_pct})  "
          f"-- how often search even surfaces the answer")
    print(f"  regressions (a1->b0):    {tot_regress}  -- retrieval distracted a known answer")
    print("\nDiag: low hit% on TEXT canonicals => retrieval/index problem (tune top_k/threshold).")
    print("      misses on NUMBERS/DATES are usually embedding limits, not tunable.")
    print("      high hit% but low lift% => student fails to use retrieved context.")


if __name__ == "__main__":
    main()
