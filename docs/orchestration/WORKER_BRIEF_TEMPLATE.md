# M.A.R.I.A. — Worker Brief Template

Every worker dispatch uses this shape. The worker has no session memory of the conversation between Eryk and master; the brief is the worker's entire world for the duration of the task.

A good brief is **dense, complete, and unambiguous**. If reviewing a worker patch reveals a gap, the brief was the bug, not the worker.

---

## Template

```
# Brief: T-NNN — <one-line goal>

## Context
<1–3 sentences. What this codebase is. Which subsystem this task lives in.
Pointers to authoritative files: CLAUDE.md, docs/CONTRACTS.md, the
relevant ADR(s), the file(s) being touched. Worker reads these before
starting.>

## Goal
<One sentence stating the behaviour change. Imperative form.>

## Scope
- In-scope files / directories:
  - <path/to/file.py>
  - <path/to/dir/>
- Out-of-scope (do NOT touch):
  - <path/to/something/>
  - <pattern>

## Definition of Done
- <Bullet — every line independently verifiable.>
- <Bullet.>
- <Bullet.>

## Non-goals
- <Things this task is NOT trying to do, that a reasonable worker
  might be tempted to add. Especially: refactors, formatting passes,
  comment additions, error handling for cases that cannot happen,
  feature flags.>

## Conventions
- Python 3.10+; type hints where the surrounding code uses them.
- English docstrings; comments may be Polish if matching existing style.
- No emojis (ADR-005).
- Do not add comments explaining what the code does — only why if non-obvious.
- Do not add backwards-compatibility shims unless explicitly asked.
- Do not push to GitHub.

## Tests
- Required new tests: <list, or "none" if not applicable>.
- Required existing tests still passing: <list of relevant test files /
  modules, or "full agent_core/tests/ suite">.
- Test command: <exact command the worker can run>.

## Output
- Make commits on the assigned branch (already checked out in the worktree).
- One commit per logical change preferred; squash is fine if all changes
  are tightly related.
- Commit message style: see `git log --oneline -10` for examples.
- When done, output a short summary: what changed, which tests ran, any
  surprises. Do not summarise what the code does — master reads the diff.

## Constraints from this task in particular
<Anything specific. E.g.: "Performance constraint: must not increase
tick latency by more than 5ms." or "Memory constraint: keep RSS under
1GB during this test." or "Do not regenerate the lockfile.">

## If you encounter ambiguity
- Stop. Output a numbered list of the ambiguities you found.
- Do NOT guess. Master will rewrite the brief.

## Authoritative references (read before starting)
- CLAUDE.md (project conventions)
- docs/CONTRACTS.md (only the section relevant to your task)
- ADR-XXX (the relevant ADR, if any)
- <any other file>
```

---

## Filled example: T-001

```
# Brief: T-001 — Validate Codex dispatch flow

## Context
M.A.R.I.A. is a local autonomous AI agent project. This task is part of
the orchestration system setup (see `docs/orchestration/README.md`). The
worker is being validated end-to-end with a throwaway task that exercises
the dispatch + retrieve loop without modifying production code.

## Goal
Create a single file `scratch/hello_codex.txt` containing the ASCII text
"hello from codex via T-001". Commit it on the branch
`agent/codex/T-001-dispatch-validation` already checked out in this
worktree.

## Scope
- In-scope files / directories:
  - scratch/hello_codex.txt (new file)
- Out-of-scope:
  - Anything else.

## Definition of Done
- File `scratch/hello_codex.txt` exists.
- It contains the exact ASCII text "hello from codex via T-001"
  followed by a single newline.
- One commit on `agent/codex/T-001-dispatch-validation` with message
  `chore(scratch): T-001 dispatch validation`.
- No other file modified.

## Non-goals
- Do not create a `scratch/` README or `.gitignore`.
- Do not write any Python.
- Do not run tests.

## Conventions
- No emojis. ASCII only.

## Tests
- None required.

## Output
- One commit. Output a single line "T-001 done" when complete.

## Constraints from this task in particular
- No dependencies installed. Worker may not run pip / npm / cargo.

## If you encounter ambiguity
- Stop. Output the ambiguity.

## Authoritative references
- docs/orchestration/MASTER_WORKFLOW.md §4 (Isolation)
- docs/orchestration/BRANCH_CONVENTIONS.md (Branch naming)
```

This is what a minimal brief looks like. Real briefs are denser but follow the same shape.

---

## Anti-patterns in briefs

These produce worse outcomes than no brief at all:

1. **"Use your judgement"** — workers fill ambiguity with confidence. Pick.
2. **"Make it good"** — does not survive contact with a worker.
3. **"Like the X module"** — workers will mimic surface features and miss the point. Cite the invariants, not the example.
4. **"While you're at it…"** — every "while you're at it" extends scope by 2×. Make it a separate task.
5. **Missing DoD** — without a DoD the master cannot review. If you cannot write one, the task is not ready to dispatch.
6. **Buried constraints** — anything important goes in its own section, not in a parenthetical mid-paragraph.
7. **Re-explaining the codebase from scratch** — point to authoritative files; do not paraphrase them. Paraphrases drift; pointers don't.
8. **Asking the worker to "improve" something** — define what "improved" means in terms of a measurable property.

---

## Per-worker considerations

### Codex
- Responds well to compact, structured briefs.
- Strong at small surgical changes in well-known idioms.
- Weak at: very long context, novel architectures it has not seen patterns for.
- Native 2× cross-check available; use it for high-uncertainty tasks.

### Kimi 2.6
- Profile to be established (see `AGENT_LEDGER_KIMI.md`).
- Initial guess: strong at long context, may differ from Codex on style.

Update these notes as the agent ledgers accumulate signal.

---

## Brief storage

- Short briefs (under ~30 lines): inline in the `TASK_BOARD.md` entry.
- Longer briefs: in `docs/orchestration/briefs/T-NNN.md`. The task-board entry then links to that file.
- Briefs are kept after the task closes — they are part of the project's reasoning trail.
