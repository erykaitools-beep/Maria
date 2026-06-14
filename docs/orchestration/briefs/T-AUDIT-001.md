# Brief: T-AUDIT-001 — Deep multi-pass audit of M.A.R.I.A. codebase

## Context

M.A.R.I.A. (Meta Analysis Recalibration Intelligence Architecture) is a
local autonomous AI agent (Polish project, started 2025-11-14, prod
deploy 2026-02-22). Stack: Python 3.10+, Ollama + NIM cascade,
threading. Live on Mini PC, ~4-week production uptime.

**This task is a deep complement to the operator audit landed today at
`docs/audit/AUDIT_2026-05-17.md` (302 linii, hybrid format Eryk +
master).** That audit covered: inventory at high level, empirical
findings from runtime data, gap analysis to "Maria orchestrates Codex",
24h postmortem status, and 5-stage repair schedule. It identified 3
critical bugs (B1 exam, B2 validate NEW, B3 learn NEW), 6 zombie
subsystems, and a Path B plan (operator-in-loop) at 3-5 days dev.

**Your job is NOT to repeat that audit.** Your job is to go DEEP into
aspects it could not cover in the time available: code-level findings,
contract drift verified line-by-line, dead-code claims triangulated
across grep + import graph + tests, data-integrity invariants checked,
LLM call patterns examined, concurrency hazards surfaced, and findings
cross-validated across multiple angles before being reported.

Authoritative refs (read first):

- `/home/maria/maria/CLAUDE.md` — project conventions, ADR list (1-30).
- `/home/maria/maria/docs/audit/AUDIT_2026-05-17.md` — the master audit
  you complement.
- `/home/maria/maria/docs/PROGRESS_LOG.md` — operational ledger.
- `/home/maria/maria/docs/ROADMAP.md` — strategic phases.
- `/home/maria/maria/docs/CONTRACTS.md` — K1-K13 contract details.
- `/home/maria/maria/docs/ARCHITECTURE.md` — ADR table + layer diagram.
- `/home/maria/maria/meta_data/` — runtime data (1.6k events, 6.5k LLM
  calls, 239 actions, 1.1k goal entries) for empirical cross-checks.

## Goal

Produce a structured multi-pass deep audit of the M.A.R.I.A. codebase
(`agent_core/`, `maria_core/`, `maria_ui/`, top-level `maria.py` /
`main.py`). Each finding must be **triangulated** — cross-validated
across at least 2-3 independent angles before being reported as a
finding. Output: a self-contained set of markdown reports in
`docs/audit/codex_deep_2026-05-17/`, ending with a synthesis file.

**Audit is READ-ONLY.** You do not modify code, tests, or any file
outside `docs/audit/codex_deep_2026-05-17/`.

## Scope

- **In-scope (Maria repo):**
  - `/home/maria/maria/agent_core/` — primary
  - `/home/maria/maria/maria_core/` — legacy modules still active
  - `/home/maria/maria/maria_ui/` — Flask + SocketIO Web UI
  - `/home/maria/maria/maria.py`, `/home/maria/maria/main.py` — entry points
  - `/home/maria/maria/scripts/` — operator tooling
  - `/home/maria/maria/docs/` — for drift checks vs code
  - `/home/maria/maria/meta_data/` — for empirical cross-checks
    (READ ONLY — never write to meta_data)

- **Out-of-scope:**
  - `~/maria-market-agent/` — PRIVATE repo. Do NOT audit it. Not your task.
  - `/home/maria/maria/venv/` — third-party.
  - `/home/maria/.claude/` — user's Claude Code config.
  - `/home/maria/maria-coders/` — separate setup.
  - Any file under `__pycache__/`.

## Output structure (MANDATORY shape)

Create `/home/maria/maria/docs/audit/codex_deep_2026-05-17/` with:

```
docs/audit/codex_deep_2026-05-17/
├── README.md                — index, methodology, run log, summary counts
├── 00_SYNTHESIS.md          — final prioritized findings (write LAST)
├── 01_architecture/
│   ├── findings.md
│   ├── evidence.md
│   └── cross_check.md
├── 02_dead_code/
│   ├── findings.md
│   ├── evidence.md
│   └── cross_check.md
├── 03_test_coverage/
│   ├── findings.md
│   ├── evidence.md
│   └── cross_check.md
├── 04_error_handling/
│   ├── findings.md
│   ├── evidence.md
│   └── cross_check.md
├── 05_data_integrity/
│   ├── findings.md
│   ├── evidence.md
│   └── cross_check.md
├── 06_llm_patterns/
│   ├── findings.md
│   ├── evidence.md
│   └── cross_check.md
├── 07_concurrency/
│   ├── findings.md
│   ├── evidence.md
│   └── cross_check.md
├── 08_security/
│   ├── findings.md
│   ├── evidence.md
│   └── cross_check.md
└── 09_documentation_drift/
    ├── findings.md
    ├── evidence.md
    └── cross_check.md
```

Each category folder has three files:
- `findings.md` — list of findings, each with ID (e.g. `ARCH-01`),
  priority tag, one-line summary, and detail paragraph.
- `evidence.md` — file/line citations + code excerpts + grep results
  backing each finding ID.
- `cross_check.md` — for each finding, what triangulation was applied
  (which 2-3 angles confirmed the finding). Also list any "AMBIGUOUS"
  cases here.

## Multi-pass methodology

Process the audit in **5 sequential passes**. Each pass advances all
categories; later passes verify earlier passes' claims from new angles.

### Pass 1 — Surface scan

For each category, do the cheap obvious checks first. Build initial
findings list. Don't worry about cross-validation yet.

- Category 01 Architecture: import graph (high-fanin modules, circular
  imports), ADR vs `ctx.X` wiring (e.g. ADR-004 says code_agent
  "superseded by MODEL-03 + OpenClaw" — check if real).
- Category 02 Dead code: `grep -r "ctx.NAME\b"` for each `ctx.NAME =`
  in `agent_core/modules/homeostasis_module.py`; flag NAMEs with 0
  downstream references.
- Category 03 Test coverage: list `agent_core/**/*.py` source files
  without a matching `test_*.py`; check `agent_core/tests/` for
  obviously-thin test files (<50 LoC, no asserts beyond trivial).
- Category 04 Error handling: `grep -rn "except Exception:\|except:"`
  bare-except patterns; `grep -rn "pass$\|continue$" -A 1 -B 3` after
  except blocks (silent swallow).
- Category 05 Data integrity: `grep -rn "open(\\|jsonl_path\\|write\\(" ` —
  any append without fsync? Any non-atomic rewrite of JSONL?
- Category 06 LLM patterns: `grep -rn "model=\\|call_with_timeout\\|set_llm_fn"` —
  cascade hygiene, timeout coverage, retry policy.
- Category 07 Concurrency: `grep -rn "Thread\\|Lock\\|threading\\|asyncio"` —
  threading model per ADR-002. Look for shared state without locks.
- Category 08 Security: `grep -rn "subprocess\\|os\\.system\\|eval\\|exec\\("`
  — shell injection surface. `grep -rn "secret\\|password\\|api_key"`
  in code (NOT in `.env` — that's data). Check `.gitignore` covers
  secrets paths.
- Category 09 Doc drift: For each ADR in `docs/ARCHITECTURE.md`, find
  the code that implements it (or claims to). Flag ADRs whose code
  is dead or behaves differently than the ADR text.

### Pass 2 — Triangulation

For each finding from Pass 1, apply a second angle of evidence:

- "0 ctx refs" findings (dead code): also check test files, scripts,
  Telegram command handlers, and any `getattr(ctx, 'NAME', None)`
  patterns that use dynamic lookup (so grep-by-literal misses them).
- "No tests for X" findings: check if X is exercised indirectly by
  integration tests; only confirm "untested" if neither direct nor
  indirect test exists.
- "Silent except" findings: check if the except block logs (logger
  call) or stores the error somewhere (still bad, but a different
  category).
- "Non-atomic JSONL rewrite" findings: check actual writer (some use
  tmp + os.replace; others use direct overwrite — only flag the
  latter).
- ADR drift findings: read the ADR text fully, not the table summary.

A finding survives Pass 2 only if Pass 2 evidence confirms it.
Otherwise downgrade or drop.

### Pass 3 — Empirical cross-check vs runtime data

For each surviving finding, check whether `meta_data/` runtime data
corroborates or contradicts it:

- Dead-code claim: does any entry in `meta_data/*.jsonl` reference
  this module / class / function? Use `grep -l NAME meta_data/*.jsonl`.
- Untested-path claim: does runtime data show this path is exercised
  in production? (If it's exercised and untested, that's HIGHER
  priority than untested-and-dead.)
- Error-swallow claim: do we see traces of swallowed errors in
  `meta_data/homeostasis_events.jsonl` or `decision_traces.jsonl`?
- LLM-cascade claim: does `meta_data/llm_tape.jsonl` show fallbacks
  happening? Latency distributions?
- Concurrency claim: does any data file show signs of race-condition
  damage (out-of-order timestamps, duplicate IDs)?

Findings that pass Pass 3 are PROMOTED to higher confidence.
Findings that runtime data contradicts get DOWNGRADED or marked
AMBIGUOUS.

### Pass 4 — Adversarial review

For each Pass-3-promoted finding, deliberately try to argue against
it. Read the surrounding code with fresh eyes; look for context that
makes the finding wrong.

- Is the "dead code" actually a Telegram command handler called via
  bridge dispatch table?
- Is the "untested path" actually unreachable in practice (and so
  testing would be pointless)?
- Is the "silent except" actually a documented escape hatch for a
  specific known-noisy failure mode?

If a finding survives adversarial review with arguments documented,
its priority STAYS or INCREASES. If it falls, mark as AMBIGUOUS or
WITHDRAWN in cross_check.md with reason.

### Pass 5 — Synthesis

Write `00_SYNTHESIS.md` containing:

1. **Methodology recap** (one paragraph).
2. **Counts table** — findings per category by priority.
3. **Top 10 CRITICAL findings** — ranked, each with one-paragraph
   description and the cross-check trail (Pass 1/2/3/4 evidence).
4. **Top 10 HIGH findings.**
5. **Contradictions** — any cases where two findings disagreed
   (e.g. dead-code claim from Cat 02 vs ADR-vs-reality claim from
   Cat 09 said the same module is "intentionally dormant").
6. **AMBIGUOUS items** — findings that need a master/operator
   decision because pass 4 could not resolve them. Each AMBIGUOUS
   item must end with a precise question for the operator.
7. **Cross-reference with `docs/audit/AUDIT_2026-05-17.md`** —
   confirm or extend each of B1, B2, B3, B4 from the master audit.
   If your deep audit finds NEW critical bugs not in B1-B4, flag
   them as B5+ at the top of synthesis.
8. **Suggested order of master attention** — given the master will
   read this synthesis, what should be looked at first to make the
   best use of the master's time?

`00_SYNTHESIS.md` is written LAST, after all category folders are
complete.

## Cross-validation rules (apply everywhere)

Each finding entry in `findings.md` must include:

- **ID** — `CAT-NN` (e.g. `ARCH-01`, `DEAD-03`, `TEST-12`).
- **Priority** — CRITICAL / HIGH / MED / LOW / AMBIGUOUS.
- **One-line summary** (≤120 chars).
- **Detail** — 2-5 paragraphs.
- **Citations** — at least one `file_path:line_number` per claim of
  fact.
- **Triangulated by** — at least 2 of the following angles named
  explicitly:
  - `grep_usages` (and the regex you used)
  - `test_file_presence` (path to relevant test file or "none found")
  - `import_graph` (modules that import this)
  - `runtime_data` (`meta_data/*.jsonl` reference + count)
  - `git_blame` (last touch + commit message; only when relevant)
  - `adr_text` (ADR number + paragraph)

A finding without `Triangulated by` ≥ 2 angles is invalid — either
add a second angle or drop the finding.

If you cannot triangulate but the finding feels strong, mark it
AMBIGUOUS and write the precise question for the operator in
cross_check.md.

## Non-goals

- Do NOT modify code, tests, or any file outside
  `docs/audit/codex_deep_2026-05-17/`. **The only writeable target
  is that folder.**
- Do NOT propose fixes inline. Findings only. Fix planning is
  master's job.
- Do NOT duplicate findings from `docs/audit/AUDIT_2026-05-17.md`
  verbatim. Reference them by ID (e.g. "extends master audit B2")
  and ADD depth / new angles.
- Do NOT audit `~/maria-market-agent/`. PRIVATE separate repo.
- Do NOT make recommendations on strategic direction (Path A vs B
  already decided in master audit).
- Do NOT generate "improvements" that are subjective taste calls
  (naming, formatting, micro-refactor preferences). Focus on
  objective findings: broken contracts, dead code, untested paths,
  swallowed errors, data corruption hazards, security gaps,
  contract drift.
- Do NOT make claims about market-agent or third-party libraries.
- Do NOT exceed the output folder shape above. Subdirectories beyond
  those 9 categories + `README.md` + `00_SYNTHESIS.md` are
  forbidden.

## Conventions

- All output files are markdown. No code files generated.
- Citations use `file_path:line_number` format (e.g.
  `agent_core/modules/homeostasis_module.py:1509`).
- Polish or English text — match the surrounding repo style. CLAUDE.md
  is Polish; CONTRACTS.md mixes Polish + English; ADR list is English.
  Either is fine, but be consistent within a file.
- No emojis (ADR-005 applies to docs too).
- `findings.md` files: max 200 lines each. Split into
  `findings_part2.md` etc. if needed.
- `evidence.md` files: code excerpts wrapped in fenced code blocks
  with language hint (` ```python `).
- `cross_check.md` files: one section per finding ID.
- ALL files end with a single trailing newline.

## Tests command

There is nothing for you to run except read-only exploration. The audit
is reported via the markdown files. The operator will spot-check your
citations by running `grep` and reading the cited lines themselves.

## Output workflow

- Make commits as you progress through passes. Suggested cadence:
  one commit per Pass × Category cluster (e.g. "audit pass 1 cat 1-3",
  "audit pass 1 cat 4-6", etc.) or one big commit at the end if scope
  feels tight.
- Final commit: `00_SYNTHESIS.md` + `README.md` updates.
- Commit message style — match `git log --oneline -10` in the Maria
  repo:
  - `docs(audit): codex deep pass 1 cat 01-03 (arch/dead/tests)`
  - `docs(audit): codex deep pass 2 triangulation`
  - `docs(audit): codex deep synthesis + top findings`

## Constraints from this task in particular

- **Run in `/home/maria/maria/`, NOT in `~/maria-market-agent/`.** First
  command to run: `cd /home/maria/maria && git status && git log --oneline -5`.
- The current branch is `refactor/homeostasis`. Stay on it.
- Do NOT push to GitHub. ADR-029 + operator preference.
- Do NOT modify `meta_data/` files. READ ONLY there.
- Do NOT clobber the existing `docs/audit/AUDIT_2026-05-17.md`. Your
  output is a separate subfolder `docs/audit/codex_deep_2026-05-17/`.
- Rate limit awareness: Codex CLI has 10 calls/hour and 300s per call.
  Break each pass into manageable chunks if needed; the audit is not
  time-pressured.
- Cross-check rules are strict. A finding without triangulation does
  not appear in `findings.md` — it goes to `cross_check.md` as
  AMBIGUOUS with a precise operator question.
- Synthesis (`00_SYNTHESIS.md`) is the operator-facing document. It
  must be skimmable: tables, ranked lists, no walls of prose.

## Cross-check support: 2× native option

This task is high-stakes (the master will plan repairs based on your
findings). You have Codex CLI's native 2× cross-check available. Use
it for any finding marked CRITICAL where the cross-validation chain
relies on one weak angle. Document use of native cross-check in
`cross_check.md` under the finding (note "native_cross_check: 2x
both confirmed" or "native_cross_check: 1/2 confirmed, downgraded").

## If you encounter ambiguity

- Stop. Output a numbered list of the ambiguities you found.
- Do NOT guess. Master will clarify or rewrite the brief.

## Authoritative references (re-listed for convenience)

- `/home/maria/maria/CLAUDE.md`
- `/home/maria/maria/docs/audit/AUDIT_2026-05-17.md` (the master audit you complement)
- `/home/maria/maria/docs/PROGRESS_LOG.md`
- `/home/maria/maria/docs/ROADMAP.md`
- `/home/maria/maria/docs/CONTRACTS.md`
- `/home/maria/maria/docs/ARCHITECTURE.md`
- `/home/maria/maria/meta_data/` (runtime data for Pass 3 empirical checks)
- `/home/maria/maria/agent_core/` (primary code target)
- `/home/maria/maria/maria_core/` (legacy modules)
- `/home/maria/maria/maria_ui/` (Web UI)
- `/home/maria/maria/maria.py` + `main.py` (entry points)
