# M.A.R.I.A. — Master + Workers Orchestration

This folder is the operating manual for the **master + workers** working mode in M.A.R.I.A. development.

**Roles:**
- **Human (Eryk)** — direction, gates, sign-off, architectural decisions.
- **Master agent (Claude Opus, in conversation with Eryk)** — task-map design, brief writing, dispatch, monitoring, review, integration, ledger keeping.
- **Worker agents (Codex, Kimi 2.6, future)** — atomic execution against self-contained briefs.

Workers do not talk to each other. All coordination goes through the master.

---

## Why this exists

A single human in the loop + a single agent does not scale once the work splits across many independent kawałki. The master + workers pattern lets us:

1. Keep Eryk's attention on direction and gates, not on every micro-decision.
2. Run multiple workers on different parts of the codebase in parallel — without git or model-mutex contention.
3. Use cross-check (multiple agents on the same brief, master compares) for high-uncertainty tasks.
4. Accumulate per-agent reliability data so the master picks the right worker for each kind of work.

The bottleneck of this design is the **quality of the task map and the briefs** — that is the master's primary craft, not the workers'.

---

## Contents

| File | Purpose | Owner |
|---|---|---|
| `README.md` | This file — index + decisions + tomorrow action | Master |
| `MASTER_WORKFLOW.md` | The constitution: pipeline, roles, gates, failure modes, task-map generation | Master |
| `TASK_BOARD.md` | Live board of in-flight tasks with IDs, status, ownership, branch | Master, updated every session |
| `WORKER_BRIEF_TEMPLATE.md` | The shape of every brief sent to a worker; filled example included | Master |
| `AGENT_LEDGER_CODEX.md` | Append-only journal of Codex's strengths, weaknesses, surprises | Master |
| `AGENT_LEDGER_KIMI.md` | Same for Kimi 2.6 | Master |
| `BRANCH_CONVENTIONS.md` | Worktree paths, branch naming, merge protocol | Master |

---

## Decisions taken (2026-05-11)

| Topic | Decision |
|---|---|
| Isolation | Worktrees per worker — each has its own working tree |
| Worktree filesystem location | `~/maria-worktrees/<agent>-<task-id>/` (outside the repo) |
| Branch naming | `agent/<agent>/T-NNN-<slug>` |
| Task ID format | `T-NNN` ascending, zero-padded to 3 digits |
| Task granularity | Default atomic; macro only when master has a dense brief |
| Parallelism | Up to 2 workers in parallel on different code areas; cross-check (same brief, two workers) for high-uncertainty work |
| Worker LLM stack | Cloud (token-flat billing); Ollama reserved for Maria production runtime |
| Maria production | Stays live during orchestration sessions — no pause needed |
| Quality gate | Every worker patch passes local tests before merge (start conservative) |
| Document language | English in this folder (so workers read it cleanly); Polish in conversation between Eryk and master |
| Eryk escalation triggers | Architecture changes (unless they are the topic), security, scope creep, blocking conflict |
| Master autonomy | Master uses its own subagents (Explore/Plan/general-purpose) freely; these are the master's tools, not a delegation layer |

These decisions are revisable. When changed, update `MASTER_WORKFLOW.md` and the relevant section here.

---

## The minimal working loop

What happens in a single master + worker iteration, in order:

1. **Eryk + master talk.** Map out direction, identify next chunk of work.
2. **Master decomposes** into atomic tasks. Each gets a `T-NNN` ID, a one-line goal, a DoD, dependencies, and a target worker (or `cross-check` if both).
3. **Master writes a brief** for each task using `WORKER_BRIEF_TEMPLATE.md`. Brief is self-contained — worker has no session memory of this conversation.
4. **Master sets up the worktree** following `BRANCH_CONVENTIONS.md`. Worker works there.
5. **Master dispatches** the brief to the worker (Codex / Kimi). If cross-check, dispatch to both.
6. **Master monitors** progress (output streaming, periodic checks). For long tasks, master works on other tasks in parallel.
7. **Worker delivers** a patch / commit on its branch.
8. **Master reviews:** diff, runs tests in worktree, sanity checks for hallucinations, checks against DoD.
9. **If cross-check:** master compares the two outputs, picks the better one or merges insights.
10. **Master merges** the chosen patch into the parent branch (`refactor/homeostasis` today). Runs full local test suite.
11. **Master updates** `TASK_BOARD.md` (status → done) and `AGENT_LEDGER_<X>.md` (any observation worth keeping).
12. **Master reports back** to Eryk: what landed, what surprised, what is next.

Eryk can interrupt at any step — that is the "human in the loop" mode. Default is master proceeds; Eryk pings when needed.

---

## What is NOT yet validated

These need a real run before this workflow is trusted:

- **Codex dispatch flow.** How exactly does the master hand a brief to a Codex CLI session and retrieve the patch? First task on the board: `T-001`.
- **Kimi 2.6 dispatch flow.** Where Kimi 2.6 lives (Moonshot API? local? bridge?), how briefs are delivered, how outputs are retrieved. First task on the board: `T-002`.
- **Worktree workflow under load.** Running two worktrees concurrently, both running pytest, both writing to `meta_data/` — needs at least one validation pass.
- **Cross-check protocol.** Whether two identical briefs to Codex give meaningfully different outputs (Codex has a native 2× compare feature; we want to use it).
- **Per-agent ledger drift.** Whether the ledger accumulates real signal or just noise after the first few sessions.

These are the day-one tasks on the board.

---

## Action list for tomorrow (2026-05-12)

In priority order:

1. **Read every file in this folder.** Mark anything that does not match the conversation we had.
2. **Set up the first worktree manually.** Together, command by command. Validates `BRANCH_CONVENTIONS.md`.
3. **Run T-001 (Codex dispatch validation).** Send a tiny throwaway task to Codex through the agreed flow. Goal: a working dispatch + retrieve pattern, not a real fix.
4. **Run T-002 (Kimi 2.6 dispatch validation).** Same exercise with Kimi.
5. **Decide on monitoring.** When a worker is running, does the master watch the stream, sleep on it, or poll? Add the decision to `MASTER_WORKFLOW.md` under "Monitoring".
6. **Pick the first real task.** Something small, low-risk, where a hallucination is easy to detect. Pull it from the existing roadmap (e.g. a stale-doc cleanup).
7. **Run the first real task end-to-end.** Master + worker + review + merge + ledger. Retro in 30 minutes.

Time budget: ~2–3 focused hours. Goal: by end of day the loop has run once for real.

---

## Pointers into the rest of the repo

- `CLAUDE.md` — project overview, conventions, ADRs.
- `docs/ARCHITECTURE.md`, `docs/CONTRACTS.md`, `docs/ROADMAP.md` — primary context for any worker touching M.A.R.I.A. internals.
- `claude_notes/` — session notes; the master writes one at the end of every session.

---

*This folder is the master's working space. It is updated every session. The structure is stable; the contents are live.*
