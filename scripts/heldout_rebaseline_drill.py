"""Held-out exam re-baseline drill (post-audit #3).

Compares THREE answering modes on bank v2, on the SAME files, using the live
built 'summaries' index:
  - open-book : legacy -- spoon-fed this file's own learned summary
  - beta      : closed-book retrieval over ALL learned summaries (production path)
  - alpha     : empty context (bare parametric knowledge -- control)

Read-only and side-effect free: calls _execute_heldout_exam DIRECTLY, so it
writes nothing to exam_results.jsonl and never flips the live daemon's HELDOUT
flag. Run AFTER a restart has built the 'summaries' index.

Usage:
    venv/bin/python scripts/heldout_rebaseline_drill.py [file_id ...]
"""

import sys
import os
import json

# Make the project root importable regardless of cwd / invocation style.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_core.semantic import SemanticMemory
from maria_core.learning.exam_agent import (
    _execute_heldout_exam,
    select_heldout_rows,
    load_heldout_bank,
)
from maria_core.learning.llm_utils import call_ollama
from maria_core.sys.config import LONGTERM_MEMORY, OLLAMA_MODEL, HELDOUT_BANK, BASE_DIR

DEFAULT_FILES = [
    "web_wiki_chemia.txt",
    "web_wiki_biologia.txt",
    "web_wiki_fizyka.txt",
]


def _fmt(x):
    return f"{x:.3f}" if isinstance(x, (int, float)) else "  -  "


def main():
    files = sys.argv[1:] or DEFAULT_FILES

    sm = SemanticMemory(data_dir=str(BASE_DIR / "meta_data"))
    sm.initialize()
    n_sum = len(sm.store.list_ids_by_namespace("summaries")) if hasattr(sm.store, "list_ids_by_namespace") else "?"
    print(f"summaries index: {n_sum} chunks loaded\n")

    bank = load_heldout_bank(HELDOUT_BANK)
    llm_fn = lambda p: call_ollama(p, model=OLLAMA_MODEL, num_predict=2048, num_ctx=8192)

    print(f"{'file':34s} {'open-book':>9s} {'beta':>6s} {'alpha':>6s}  n  notes")
    print("-" * 78)
    for fid in files:
        rows = select_heldout_rows(fid, bank)
        if not rows:
            print(f"{fid:34s}  (no bank rows)")
            continue
        try:
            ob_score, _, _, _ = _execute_heldout_exam(
                fid, LONGTERM_MEMORY, rows, llm_fn=llm_fn, semantic_memory=None)
        except Exception as e:
            ob_score = None
            print(f"  open-book error {fid}: {e}")
        try:
            b_score, _, _, b_grading = _execute_heldout_exam(
                fid, LONGTERM_MEMORY, rows, llm_fn=llm_fn, semantic_memory=sm)
            alpha = b_grading.get("alpha_score") if isinstance(b_grading, dict) else None
            cchars = b_grading.get("context_chars") if isinstance(b_grading, dict) else None
        except Exception as e:
            b_score = alpha = cchars = None
            print(f"  beta error {fid}: {e}")
        note = f"ctx={cchars}c" if cchars is not None else ""
        print(f"{fid:34s} {_fmt(ob_score):>9s} {_fmt(b_score):>6s} {_fmt(alpha):>6s}  {len(rows):>2d}  {note}")

    print("\nInterpretacja: beta < open-book = uczciwie (juz nie przepisuje z kartki);")
    print("beta > alpha = retrieval cos dodaje ponad gole priory modelu.")


if __name__ == "__main__":
    main()
