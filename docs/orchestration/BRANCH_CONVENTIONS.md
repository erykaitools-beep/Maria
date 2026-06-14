# M.A.R.I.A. — Branch and Worktree Conventions

Mechanical rules for setting up, running, and tearing down per-task worktrees in master + workers mode.

---

## 1. Layout

- **Primary repo:** `/home/maria/maria/` (production Maria runs here, do not break it).
- **Worktrees root:** `~/maria-worktrees/`
- **Worktree per task:** `~/maria-worktrees/<agent>-T-NNN-<slug>/`
- **Scratch directory** (large transient output a worker may produce that should not be committed): `~/agent-scratch/T-NNN/`

`<agent>` is `codex` or `kimi` (or a future worker name).
`<slug>` is a short kebab-case label derived from the task goal, lowercase, no spaces.

Examples:
- `~/maria-worktrees/codex-T-001-dispatch-validation/`
- `~/maria-worktrees/kimi-T-014-extract-memory-engine-spec/`

---

## 2. Branch naming

- **Parent branch (today):** `refactor/homeostasis`.
- **Worker branch:** `agent/<agent>/T-NNN-<slug>`.

Examples:
- `agent/codex/T-001-dispatch-validation`
- `agent/kimi/T-014-extract-memory-engine-spec`

Branches with the `agent/` prefix are by convention disposable — created per task, deleted after merge.

---

## 3. Setup commands (master runs these before dispatching)

From the primary repo:

```bash
# 1. Make sure the parent branch is current.
cd /home/maria/maria
git fetch origin
git checkout refactor/homeostasis
# (do not pull if there are local unpushed commits ahead of origin;
#  inspect first with `git status`)

# 2. Make sure the worktrees root exists.
mkdir -p ~/maria-worktrees

# 3. Create the worktree on a new branch.
git worktree add \
    ~/maria-worktrees/codex-T-001-dispatch-validation \
    -b agent/codex/T-001-dispatch-validation \
    refactor/homeostasis

# 4. Verify.
git worktree list
```

The worker is then dispatched with its working directory pointing at the new worktree path.

---

## 4. Worker invocation (TBD per worker)

This section will be filled during T-001 and T-002. Initial placeholders:

### Codex
```
<command master uses to hand a brief to Codex and have Codex work
inside ~/maria-worktrees/codex-T-001-dispatch-validation/>
```

### Kimi 2.6
```
<command master uses to dispatch to Kimi inside its worktree>
```

When these are validated, replace the placeholders with the actual one-liners and document any environment variables (API keys, endpoints) the master needs to set first.

---

## 5. Review commands (master runs these on the worker's worktree)

```bash
# Inspect what changed.
cd ~/maria-worktrees/codex-T-001-dispatch-validation
git status
git diff refactor/homeostasis...HEAD

# Run tests in isolation (use the project venv).
source /home/maria/maria/venv/bin/activate
python -m pytest agent_core/tests/ -x --tb=short
deactivate
```

Note: the venv is shared. If a worker accidentally `pip install`-s something, it pollutes the shared environment. Briefs forbid this (see `WORKER_BRIEF_TEMPLATE.md`).

---

## 6. Merge protocol (master only)

After review passes and DoD is met:

```bash
cd /home/maria/maria
git checkout refactor/homeostasis

# Option A: fast-forward style (preserves worker commits as-is)
git merge --ff-only agent/codex/T-001-dispatch-validation

# Option B: squash (combine all worker commits into one master-signed commit)
git merge --squash agent/codex/T-001-dispatch-validation
git commit -m "task(T-001): <one-line summary>

<longer description if needed>

Worker: codex
Branch: agent/codex/T-001-dispatch-validation

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

Default: **squash** for atomic tasks (one commit per task on the parent branch). Use fast-forward only when a worker produced multiple meaningful commits that should be preserved.

Never push from a worktree. All pushes (if any) happen from the primary checkout after Eryk authorises, per ADR-029.

---

## 7. Cleanup after merge

```bash
# Remove the worktree directory.
git worktree remove ~/maria-worktrees/codex-T-001-dispatch-validation

# Delete the local branch.
git branch -d agent/codex/T-001-dispatch-validation
# (use -D only if the merge was squashed; -d will refuse because the
#  squashed branch is not "merged" by git's strict reachability check)

# Verify.
git worktree list
git branch | grep agent/ || echo "no agent branches left"
```

If a task is rejected (worker output discarded):

```bash
git worktree remove --force ~/maria-worktrees/codex-T-001-dispatch-validation
git branch -D agent/codex/T-001-dispatch-validation
```

Log the rejection in the task board and the relevant agent ledger.

---

## 8. Concurrency rules

- Multiple worktrees may exist at the same time.
- Each worker session writes only inside its own worktree.
- The primary repo `/home/maria/maria/` is the master's working area and the production Maria checkout — workers do not touch it.
- `meta_data/` inside a worktree is empty by default (it is gitignored). If a worker for some reason writes data into its worktree's `meta_data/`, master inspects it during review but does not merge it.

---

## 9. Disk-space note

Each worktree shares the `.git/` of the primary repo (cheap), but checks out its own working tree (~145k LOC + dependencies' files). Plan for ~200–400 MB per worktree depending on what is materialised. With 2 worktrees in parallel this is negligible against the Mini PC's storage budget.

---

## 10. Failure modes

- **`git worktree add` refuses with "already checked out"** — the branch already exists on another worktree. Either reuse it or rename the new branch.
- **Stale worktrees after a crash** — `git worktree prune` cleans up references to worktree paths that no longer exist on disk.
- **Worker accidentally commits to `refactor/homeostasis`** — should be impossible since the worktree is checked out on the agent branch. If it happens, master cherry-picks the commit onto the agent branch and resets the parent branch.

---

*This file's commands are run literally. Any change to a command should be tested live before being committed here.*
