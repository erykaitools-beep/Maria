# M.A.R.I.A. — Master Workflow

The constitution of the master + workers mode. This document is binding for every session that uses worker agents. Update it explicitly when rules change; do not let drift happen silently.

---

## 1. Roles

### 1.1 Human (Eryk)
- Sets direction and project priorities.
- Approves architectural changes, scope changes, security-relevant work.
- Resolves ambiguity the master cannot resolve alone.
- Sign-off on anything that leaves the local machine (push to GitHub, send externally, publish).
- Free to interrupt the master at any time.

### 1.2 Master agent (Claude Opus)
- Decomposes Eryk-level direction into atomic tasks with explicit DoD.
- Writes briefs that workers can act on with zero prior session context.
- Sets up worktrees and dispatches briefs to workers.
- Monitors workers; pulls early when a worker is going off the rails.
- Reviews every worker output: diff, tests, hallucination check, DoD compliance.
- Performs cross-check comparison when applicable.
- Merges accepted work into the parent branch.
- Updates the task board and the agent ledgers.
- Reports back to Eryk in concise increments.
- Uses its own subagents (Explore, Plan, general-purpose) freely as part of its work — these are master-internal tools, not workers.

### 1.3 Worker agents
- Receive a self-contained brief and a worktree.
- Produce code changes / tests / docs on their branch.
- Do not call other workers.
- Do not push to GitHub.
- Do not modify ADRs or `CLAUDE.md` unless the brief explicitly says so.

Today's worker roster:
- **Codex** — CLI-based, OpenAI Codex. Rate: 10/h, 300s per call. Native 2× cross-check feature available.
- **Kimi 2.6** — to be validated as worker (see `TASK_BOARD.md` T-002).

---

## 2. The pipeline

```
+-------------------+
| Eryk + master     |   (Polish conversation)
|  talk, set scope  |
+---------+---------+
          |
          v
+-------------------+
| Master            |
|  decomposes into  |
|  T-NNN tasks      |
+---------+---------+
          |
          v
+-------------------+
| Master writes     |
|  brief(s) +       |
|  sets up worktree |
+---------+---------+
          |
          v
+-------------------+   parallel up to 2
| Worker(s) execute |   (cross-check: same brief, 2 workers)
+---------+---------+
          |
          v
+-------------------+
| Master reviews,   |
|  tests, merges,   |
|  updates ledgers  |
+---------+---------+
          |
          v
+-------------------+
| Master reports    |
|  back to Eryk     |
+-------------------+
```

Loop runs until the chunk of work Eryk and master mapped out is done.

---

## 3. Task-map generation (the master's primary craft)

A good task map is the difference between fast progress and idle workers. The master's job is to **maximise worker throughput** and **maximise output quality** simultaneously. These are the rules:

### 3.1 Atomicity
- Default to atomic tasks: one file or one tight group of files; one clearly-stated behaviour change; one DoD line.
- Macro tasks only if the master has a dense, opinionated brief covering structure, names, tests, and explicit non-goals.

### 3.2 Independence
- Two tasks dispatched in parallel must touch different code areas.
- If two tasks share a file, sequence them — never parallel.
- Common shared surfaces: `agent_core/homeostasis/`, `meta_data/`, `CLAUDE.md`, `docs/CONTRACTS.md`. Touch one at a time.

### 3.3 Pipelining
When a workstream has natural stages (spec → impl → test), pipeline rather than serialise:
- Worker A drafts a spec from a master-written brief.
- Master reviews the spec quickly, hands it to Worker B with an impl brief.
- Worker C writes tests against the spec while B implements.

### 3.4 Dependencies
- Each task on the board declares dependencies by task ID.
- Master does not dispatch a task whose dependencies are unresolved.
- Long dependency chains are a smell — refactor the map.

### 3.5 Idle-time minimisation
- Master always has at least one task "ready to dispatch" in the pipeline so a worker is never waiting for a brief.
- When a worker is mid-run, master uses that time to write the next brief or review another patch — never sits idle watching.

### 3.6 Anti-patterns
- "Just refactor this module" — too open, will hallucinate scope.
- "Do everything you think is needed for X" — workers fill ambiguity with confidence; master pays in review.
- "Fix all the bugs in directory Y" — workers will invent bugs.
- Multi-day single brief — break it down.
- Tasks the master does not understand well enough to review — finish understanding first; do not delegate confusion.

---

## 4. Isolation

### 4.1 Worktrees
Each worker session runs inside a dedicated git worktree at `~/maria-worktrees/<agent>-T-NNN-<slug>/`. See `BRANCH_CONVENTIONS.md` for setup commands.

### 4.2 Filesystem
Workers must not write outside their worktree except to `~/agent-scratch/T-NNN/` for any large output the master will inspect. Anything in `meta_data/` from a worker is suspect — Maria's runtime data lives in the production checkout, not in worktrees.

### 4.3 Network
Workers may call cloud LLMs (token-flat billing). Workers must not push to GitHub. Workers must not call external APIs beyond their LLM provider unless the brief authorises it.

### 4.4 Process
A worker session is a discrete CLI invocation. When the brief is delivered and the patch retrieved, the session ends. No long-lived worker processes that span multiple tasks.

---

## 5. Cross-check protocol

Use when the task has any of these properties:
- New architecture or design surface.
- Security-relevant changes.
- High hallucination risk (e.g. anything depending on package API the master is unsure about).
- Ambiguous brief that the master could not tighten further.

Procedure:
1. Master dispatches the same brief to two workers (or to Codex's native 2× mode).
2. Both produce patches on different branches.
3. Master diffs the two outputs.
4. If they agree on substance → pick the cleaner one.
5. If they disagree → master investigates the disagreement before merging anything. Often the disagreement reveals a gap in the brief.
6. Log the comparison in the relevant `AGENT_LEDGER_*.md`.

Cross-check is **not** the default — it doubles cost and time. Use it deliberately.

---

## 6. Quality gates

A worker patch is **accepted** only after every check passes:

1. **Diff scope.** Patch only touches files within the brief's declared scope.
2. **No spurious files.** No unrelated formatting changes, no rogue dependencies added.
3. **Tests pass locally** in the worktree (`python -m pytest agent_core/tests/` or the relevant subset, depending on what was touched).
4. **DoD met.** Every line of DoD verifiable.
5. **No hallucinated symbols.** Master skims imports and function calls; nothing fictional.
6. **Conventions respected.** No emojis (ADR-005), English docstrings, type hints where master would expect them, no comments explaining the obvious.

If any check fails:
- Small fix → master patches it and notes in the ledger.
- Significant gap → re-dispatch with a tightened brief, or hand to a different worker, or pull the work to master.

---

## 7. Eskalation to Eryk

Master pings Eryk before acting when:

- The task touches an ADR or would require a new ADR.
- The task changes how Maria boots, ticks, or talks to the operator.
- The task changes the LLM routing or cost profile (token-flat exempt).
- The task touches `LICENSE`, `CLAUDE.md`, `docs/MODEL_REGISTRY.md`, or `docs/SECURITY.md`.
- The task involves anything visible outside the machine (push, email, Telegram broadcast to non-Eryk chats, external API calls).
- The master ran into a conflict it cannot resolve.
- The scope grew during execution and now looks different than what Eryk agreed to.

When Eryk and master are actively in conversation, the bar drops — most decisions are made together inline. Eskalation rules apply primarily when the master is working ahead of Eryk between conversations.

---

## 8. Failure modes

### 8.1 Worker hallucinates
- Symptoms: imports that do not exist, calls to functions with wrong signature, references to files that are not there, invented APIs.
- Response: discard the patch silently (no merge). Try cross-check with the other worker. If both hallucinate, master pulls the work itself.
- Always log the hallucination pattern in the ledger.

### 8.2 Worker exceeds scope
- Symptoms: patch touches files outside the brief; unrelated refactors; "while I was at it" additions.
- Response: master extracts only the in-scope changes; discards the rest. Log the pattern; tighten next brief from this worker.

### 8.3 Worker stalls
- Symptoms: long-running session with no output progress, repeated CLI errors.
- Response: kill the session, hand the brief to the other worker, log the stall context.

### 8.4 Tests fail in the worktree
- Master reads the failure, decides:
  - Trivial fix → fix in the worktree, log as "minor cleanup".
  - Non-trivial → re-dispatch with the failure message included in the new brief.
- Never merge with failing tests, even if the master "knows it's unrelated".

### 8.5 Merge conflicts at master integration
- Resolve in the worktree, never on the parent branch directly.
- If conflict is deep, pause the merging worker's task and re-plan the map.

### 8.6 Worker disagrees with the brief
- A worker pointing out a flaw in the brief is **valuable signal**, not insubordination.
- Master rewrites the brief and dispatches again.
- If the disagreement is right, log it as a strength in that worker's ledger.

---

## 9. Monitoring workers

**Open question for the first real session** (decide tomorrow):

- (a) Master watches the worker's stream live and reacts in real time.
- (b) Master starts the worker in the background, works on something else, returns when notified.
- (c) Master polls periodically.

Initial default until validated: **(b)** for non-cross-check tasks (saves master's attention for review), **(a)** for cross-check (live diff is more useful than after-the-fact diff).

---

## 10. Ledger discipline

The agent ledgers are the master's long-term memory about each worker.

Write to a ledger after every task involving the worker, even if uneventful. Format defined in `AGENT_LEDGER_CODEX.md` / `AGENT_LEDGER_KIMI.md`.

Things worth logging:
- A hallucination, with the trigger context.
- A surprising strength — "Codex picked up an unstated invariant correctly".
- A consistent failure mode — "Kimi rephrases function names if not pinned".
- A timing surprise — "task took 4× expected; cause: ..."
- A successful cross-check disagreement that revealed a real gap.

Things not worth logging:
- "Worked as expected." Default state — no entry needed.

The ledger is the input to "which worker for which task" decisions. Without it, master is guessing.

---

## 11. Session protocol for master + workers mode

Start of session:
- Master reads `TASK_BOARD.md` and the recent entries in `AGENT_LEDGER_*.md`.
- Eryk and master sync on direction (Polish, conversational).
- Master proposes a task map for the session (1–N tasks, IDs, target workers, DoD).
- Eryk approves or revises the map.

Mid-session:
- Master executes the map: brief → dispatch → review → merge → log.
- Master reports in tight increments — one line per landed task, longer note when something surprises.

End of session:
- Master updates `TASK_BOARD.md` (close completed, leave in-flight clearly marked).
- Master appends to ledgers.
- Master writes a `claude_notes/YYYY-MM-DD_<theme>.md` summary.
- Commit locally; push only if Eryk authorises (per ADR-029).

---

## 12. Evolving this document

When a rule here turns out to be wrong, change it and add a one-liner to `claude_notes/` explaining why. Do not let the workflow ossify around a rule the master no longer follows in practice — that creates a credibility gap.

When a new worker (e.g. another local-AI model, a hosted Anthropic agent, a Codex variant) joins, add a section under §1.3 and create a new `AGENT_LEDGER_<name>.md`.
