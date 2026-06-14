# SPEC — First effector primitive `FS_WRITE` + criteria goal-closer (Plank B2, IMPLEMENTED)

> **STATUS: IMPLEMENTED 2026-05-31** (`3360a20` FS_WRITE primitive + `21081ed` autonomous
> loop/criteria closure; B3 `c623782` success_criteria). OBSERVED in-vivo 16:13
> (`goal-ff5218293584` ACHIEVED — first real effector action). Behind `FS_WRITE_ENABLED`
> (default OFF). Design record below. (Marked during 2026-06-05 cleanup.)
>
> **STATUS (orig): PROPOSAL, pending Eryk + Codex gate.** Local (ADR-029). Drafted
> 2026-05-31, grounded against live code by a read-only agent.
> This is **the keystone of Option B**: the first time M.A.R.I.A. closes a real
> goal through a verified external effect — "without lying to herself."
> **Depends on B3 (goal-schema activation)** for the `success_criteria` field.

## Why (the convergence + the code reality)

4/4 reviewers: the first real effector action must come **before** knowledge
consolidation — today there are **0 effector calls** (203 `action_audit.jsonl`
rows, none real), so the entire K7/K10 action-safety machinery is **unproven in
vivo**. 3.5/4 say closing one real, externally-effected goal is the actual
keystone, not more verification.

**The real reason it's 0** (grounded): the planner **never autonomously generates
an effector/action plan.** The only `EFFECTOR` plans are born from the
operator-driven approval queue fed by the Telegram `/do` command
(`planner_core.py:552-559`; `homeostasis_module.py:2616-2694`). Authority
(`bounded`) is *not* the blocker for a safe tool — the missing **autonomous
plan-gen seam** is. That seam is the unlock.

## Design decision — a NEW `FS_WRITE` type, NOT OpenClaw

Routing the first primitive through the existing `effector` type inherits its
hardwired authority gate (`policy_rules.py:132-133`: `effector` bypasses class
gating, defers to `rule_effector_authority` → OBSERVE/ESCALATE + the `/efapprove`
queue). That keeps it human-in-the-loop, not autonomous.

Instead: a **brand-new GUARDED action type `FS_WRITE`**, executed by the
**already-sandboxed `FileManager`** (`agent_core/hands/file_manager.py`), riding
the same governance rails as `fetch` (GUARDED, rate-limited, AUDIT_ONLY). This
sidesteps the effector/authority tangle and is **equally safe** — arguably safer,
because `FileManager` enforces a dir-whitelist + filename sanitize + no-overwrite
(`file_manager.py:18,44,55-57,143-155`), whereas OpenClaw `write` runs an
unrestricted `printf > path` shell as `deployadmin` (`openclaw_client.py:251`,
**not** inherently sandboxed) and `tool_specs.validate_args` does **not** enforce
path location (`:89-116`).

## The primitive

> A goal with `success_criteria = {type: "file_exists", path: "<sandbox>/maria_first_action.txt"}`
> causes the planner to emit one `FS_WRITE` plan → K7 (GUARDED, allowed) → K10
> before-snapshot → `FileManager` writes a <1KB file to a dedicated sandbox dir →
> K10 after-validate (file exists + mtime/size) → audit row → goal-closer verifies
> the criterion → `update_progress(goal_id, 1.0)` → store auto-flips ACHIEVED.

Sandbox dir: `meta_data/fs_sandbox/` (in-repo, gitignored) — refuse any resolved
path that escapes it; reject symlinks; cap <1KB.

## Half-built assets to lean on (don't reinvent)
- `agent_core/hands/file_manager.py` — `write_note` (`:30-75`): sandboxed write,
  dir whitelist (`_SAFE_WRITE_DIRS` `:18`), no-overwrite, returns `{success,path,size}`.
- `agent_core/hands/result_validator.py:57-71` — `_validate_file_write`: already
  does `Path(path).exists()` + size check. Reuse for the K10 branch.
- `agent_core/routing/handlers/__init__.py:335-421` — `update_learning_goal`: the
  goal-closure **idiom** to mirror for a criteria-based closer.
- ⚠️ `hands/` is currently imported by `shared_context`/`workflow`/`homeostasis_module`
  but **not wired into the planner execute path** — it's a parallel stack to adopt.

## Seams to wire (condensed from 12 → the essential chain)

| # | Seam | File:line | Change |
|---|---|---|---|
| 1 | New `ActionType.FS_WRITE` | `planner/planner_model.py:24-39` | add `FS_WRITE = "fs_write"` |
| 2 | K7 class (the table policy reads) | `autonomy/action_class.py:37-53` | `"fs_write": GUARDED` |
| 3 | K7 class (registry, keep in sync) | `routing/capability_spec.py:33+` | `CapabilitySpec("fs_write", k7_classification="guarded", required_subsystems=("file_manager",))` |
| 4 | K10 safety profile | `action_safety/safety_classifier.py:25-74` | `"fs_write": (AUDIT_ONLY, REVERSIBLE, FILESYSTEM, before=True, after=True)` — **required**, else defaults STAGED = won't execute |
| 5 | K10 file-exists validator | `action_safety/effect_validator.py` ~`:155` | new `if action_type=="fs_write"` branch: stat `result["path"]` exists+mtime/size (reuse `result_validator.py:57-71`); stash before-mtime in `StateSnapshot.custom` (`safety_model.py:64`) |
| 6 | Sandbox dir + containment | new constant | `meta_data/fs_sandbox/`, symlink-reject + prefix-contain (mirror `file_manager.py:157-170`) |
| 7 | Executor handler | `planner/action_executor.py` `_ACTION_MAP` `:164-176` | `_exec_fs_write(plan)` → sandboxed `FileManager` → `{success,path,size}` |
| 8 | Capability-router dispatch | `routing/capability_router.py` + handlers | register `fs_write` so `dispatch()` routes it (executor prefers router, `action_executor.py:186-187`) |
| 9 | Subsystem wiring | `modules/homeostasis_module.py` ~`:418-445` | construct a sandbox-scoped `FileManager`, inject into executor/router |
| **10** | **Autonomous plan-gen (the missing seam)** | `planner/planner_core.py` near `_maybe_creative` `:592-596` | `_maybe_fs_write(ctx)`: for an ACTIVE goal with unsatisfied `success_criteria.type=="file_exists"`, emit `create_plan(..., FS_WRITE, {path, content})` → flows through existing `_finalize_plan` `:2256` (K7 `:2315` + K10 `:2450,:2499`) |
| 11 | Criteria goal-closer | `routing/handlers/__init__.py` (mirror `update_learning_goal`) | after successful `fs_write`, verify `goal.metadata["success_criteria"]`, call `goal_store.update_progress(goal_id, 1.0)` → auto-ACHIEVED (`store.py:409-415`) |
| 12 | Seed the test goal | `goals/store.py` create path | ACTIVE goal, `metadata={"success_criteria":{"type":"file_exists","path":"meta_data/fs_sandbox/maria_first_action.txt"}}` |

## Flag + rollout
`FS_WRITE_ENABLED` (env, default **off**). off → `_maybe_fs_write` is a no-op (no
autonomous plan generated); on → the loop above runs. Flag → alongside → observe
→ cutover. Behavior identical to today while off.

## OBSERVED (externally-checkable DONE)
- `action_audit.jsonl` gets its **first** real entry: `action_type="fs_write"`,
  `success=true`, `validation` passing, with a `before_state`/`after_state` showing
  the file went from absent → present;
- the file physically exists in `meta_data/fs_sandbox/` with the expected content;
- the seeded goal transitions ACTIVE → ACHIEVED with a traceable action/episode id;
- **with the flag off**, none of the above happens (no autonomous effector plan).

## Safety constraints
- **REVERSIBLE + AUDIT_ONLY + GUARDED** — delete-the-file rollback; execute+log
  with before/after; rate-limited via `ActionRateLimiter`. The consecutive-failure
  breaker (`policy_rules.py:63-81`, threshold 3) + 30-min decay guard runaway loops
  (cf. the historical 1430-fetch incident).
- **Sandbox containment** (ADR-010): one dedicated dir, symlink-reject,
  path-prefix-contain, <1KB. `FileManager` is the sandboxed writer; do **not** use
  OpenClaw `write` for the autonomous path.
- **Three-way effector-class drift** to flag for the drift-guard regardless:
  `action_class.py:46` GUARDED vs `capability_spec.py:90-94` restricted vs
  CLAUDE.md/ADR-016 RESTRICTED.
- **K7 RESTRICTED default stays** for unknown actions (`action_class.py:76-77`) —
  `FS_WRITE` is explicitly GUARDED, nothing else loosens.

## Files
- `agent_core/planner/planner_model.py` (new type), `planner_core.py` (seam #10),
  `action_executor.py` (handler).
- `agent_core/autonomy/action_class.py` + `routing/capability_spec.py` (K7).
- `agent_core/action_safety/safety_classifier.py` + `effect_validator.py` (K10).
- `agent_core/hands/file_manager.py` + `result_validator.py` (reuse).
- `agent_core/routing/handlers/__init__.py` (criteria closer) + `capability_router.py`.
- `agent_core/goals/store.py` (seed goal); **depends on B3** for `success_criteria`.
