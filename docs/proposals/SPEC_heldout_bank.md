# SPEC — Held-out verification bank (Plank B4, IMPLEMENTED)

> **STATUS: IMPLEMENTED 2026-05-31** (`c449aa4` independent-exam closure + held-out bank
> 3->64 files/371 Q; closed-book retrieval `c9561e5`+`45a2e7b`). Bank lives in
> `memory/heldout_bank.jsonl`; gated by `HELDOUT_GRADER_ENABLED` (default OFF). Design
> record below. (Marked during 2026-06-05 cleanup.)
>
> **STATUS (orig): PROPOSAL, pending Eryk + Codex gate.** Local (ADR-029). Drafted
> 2026-05-31, grounded against live code by a read-only agent.
> Answers reviewer convergence on Q2 (4/4: local-different-family is not enough
> independence) with the offline-correct path all four named: a static,
> programmatically-graded held-out bank.

## Why (the convergence + the code reality)

All 4 external reviewers said qwen3-vs-llama3.1 on the **same machine** is *not*
real independence — correlated training data, shared host, no external grounding.
Their proposed fixes split between "external API grader" and "static held-out
bank." The **held-out bank wins on our constraints** because it is **pure Python,
zero LLM, zero network**:

- sidesteps the no-autonomous-external-CLI rule entirely;
- has **no timeout/silent-fallback failure mode** — the exact failure that made
  NIM-as-grader mislabel our only 3 "independent" exam rows (`f788957`;
  `FOUNDATIONS_GAP_2026-05-30.md:97-99`);
- removes the qwen3/NIM dependency from *graded* runs (the student still needs a
  local LLM only to **answer**).

It also fixes a subtler weakness: today the exam questions are **LLM-generated
from the just-read material** (`exam_agent.py:522`), so a pass can mean "I can
regurgitate the text I just read." A held-out bank tests **canonical /
un-studied** material → it measures *capability*, not recall.

## Current pipeline (grounded)

`maria_core/learning/exam_agent.py` — three steps orchestrated by `_execute_exam`
(`:495-537`):

1. **generate** `generate_exam(ctx, n, llm_fn)` (`:158-215`) → `{"exam":[{q,expected}]}`.
2. **answer** `answer_exam(ctx, questions, llm_fn)` (`:333-394`) — **student answers
   BLIND**: the prompt is built from `q['q']` only; `expected` is never shown
   (`:346`). ✅ This property is exactly what we need and it already holds.
3. **grade** `grade_exam(questions, answers, llm_fn)` (`:397-438`) — **the LLM
   grader; this is the thing we replace.** Returns `{"graded":[...], "final_score":float}`.

**The "independent grader" is not a function** — it's `grade_exam` called with a
different `llm_fn`. Model selection is **hardcoded** in
`agent_core/modules/teacher_module.py:_run_exam_wrapped` (`:130-140`):
`student_model = llama3.1:8b`, `examiner_model = "qwen3:8b"` (literal — no env/flag).

**Result schema** (`exam_agent.py:628-642`, written by
`memory_store.append_exam_result` → `memory/exam_results.jsonl`): `file, timestamp,
attempt, score, num_questions, questions, answers, grading, grader_independent,
grader_model, student_model`.

**Trust gate (#2, `68d865c`):** consumers ingest only `status=="completed"`, set on
exam pass (`EXAM_PASS_THRESHOLD=0.6`, `config.py:94`). Gates:
`belief_builder.py:170-179`, `indexer.py:85-96`. Goal closure keys on the same
`completed` set (`handlers/__init__.py:313-393`).

**There is NO existing held-out / question-bank / answer-key structure** anywhere
(grep-confirmed; it was explicitly deferred to "v2" at `FOUNDATIONS_GAP:95`).

## Design — smallest change that keeps the contract

The load-bearing invariant: **the result dict shape** (`final_score` float +
`graded` list) plus the trust gate are **score/status-driven, not grader-driven**.
A static grader that emits the same shape needs **zero downstream changes**.

### B4.1 — the bank file
`memory/heldout_bank.jsonl` (read-only; `memory/` is knowledge-truth, per CLAUDE.md).
One row per question:
```json
{"topic": "fotosynteza", "q": "...", "match": "exact|regex|contains|numeric",
 "canonical": "...", "pattern": "...", "tolerance": 0.0, "bank_version": "v1"}
```
Questions must be **authored about canonical material the student does NOT just
re-read** — curated by Eryk (or seeded once, reviewed). Start small (e.g. 20–50 Qs
across the live `expert_*` topics) and grow.

### B4.2 — pure-Python grader
New `grade_heldout(bank_rows, answers) -> {"graded":[...], "final_score":float}` in
`exam_agent.py` (sibling of `grade_exam`):
- normalize whitespace/case; per-question 0/1 by `match`:
  `exact` (==), `contains` (substring), `regex` (`re.search`), `numeric`
  (parse + `abs(a-b) <= tolerance`);
- `final_score = mean(scores)`; **same dict shape** as `grade_exam`.

### B4.3 — the run path
New `_execute_heldout_exam(topic|file_id)` in `exam_agent.py` that:
1. loads the bank rows for the topic (read-only);
2. calls the **unchanged** `answer_exam(ctx, bank_questions, llm_fn=student)`
   (student still answers blind via local Ollama);
3. grades with `grade_heldout` (no LLM);
4. returns the **same** `(final_score, exam, answers, grading)` tuple `_execute_exam`
   returns at `:537` → status update (`:540-576`), result write (`:628-642`),
   trust gate, goal closure **all untouched**.

### B4.4 — provenance (the `f788957` lesson)
Set `grader_meta = {"independent": True, "grader": "heldout:static@v1",
"student": OLLAMA_MODEL}` at the construction site (`teacher_module.py:136-140`),
so `exam_results.jsonl` cleanly distinguishes **3 grader regimes**: legacy
self-graded (`None`), qwen3 independent, held-out static. `grader_independent`
must reflect what *actually* graded — never what was intended.

### B4.5 — flag + rollout
Caller-side toggle in `teacher_module._run_exam_wrapped`, env
`HELDOUT_GRADER_ENABLED` (default **off**), pattern = `STRATEGIC_PLANNER_DRIVES`.
off → today's qwen3 path; on → held-out path for topics that have a bank, qwen3
fallback for topics that don't. Flag → alongside → observe → cutover.

## OBSERVED (externally-checkable DONE)
- `exam_results.jsonl` shows rows with `grader_model="heldout:static@v1"`,
  `grader_independent=true`, and **0 LLM calls** in the grade step (logged);
- a student answer that is *wrong vs the canonical key* scores 0 and **blocks**
  the file from `completed` → not ingested into beliefs/index (the gate bites);
- agreement-rate sample: run N exams through both qwen3 and the bank; log
  disagreement rate (a high one is itself a finding about the local grader).

## Constraints / gotchas
- **Daemon runs stale code** (pre-`f788957`); B4 only goes live after a `/restart`.
- **Don't reuse `generate_exam`** for bank runs — questions come from the bank,
  not the LLM (that's the whole point).
- **Keep the result-tuple shape** exactly — `last_scores`/looping detection
  (`exam_agent.py:441-461`) and the schema both depend on it.
- Static bank tests only what's curated — it's a **floor on rigor, not full
  coverage**; grow the bank as topics are added. Log coverage gaps (no silent caps).

## Files
- `maria_core/learning/exam_agent.py` — `_execute_heldout_exam` + `grade_heldout` (new); pipeline at `:495-537`.
- `agent_core/modules/teacher_module.py:130-150` — flag + grader selection (the hardcoded seam).
- `memory/heldout_bank.jsonl` — the bank (new, read-only).
- Trust gate (unchanged, for reference): `belief_builder.py:170-179`, `indexer.py:85-96`, `handlers/__init__.py:313-393`.
