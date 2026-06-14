# Brief: T-SELF-003 — Phase 17 dispatcher for maria-repo + approval_required gate

## Context

M.A.R.I.A. is a local autonomous AI agent project. Phase 17 conductor
dispatcher (LIVE since 2026-05-25) dispatches PENDING tasks with
`assignee=codex` to Codex CLI autonomously. **Currently exactly ONE
dispatcher is wired**: `project="market_agent"`, workspace
`~/maria-market-agent/`. Tasks in Maria's own repo (T-LEARN-*,
T-STABILITY-*, T-SELF-*) cannot be dispatched autonomously — they
require master to invoke Codex by hand.

This task adds the **second dispatcher** for `project="maria"`,
workspace `/home/maria/maria/`, so Maria-repo tasks become eligible for
autonomous routing.

It also adds the **approval_required gate**: any task with
`task.artifacts["approval_required"] == True` is filtered out by
`Conductor.get_autonomous_next()`, regardless of project. This is the
flag set by T-SELF-002's RepairTaskCreator and flipped to False by
`/approve_repair`. Without this gate, T-SELF-002's STOP-AT-PENDING
guarantee leaks — the dispatcher would pick up self-repair tasks
before operator approves.

**Dependency:** This task is INDEPENDENT of T-SELF-001/002 functionality
(can be implemented in parallel), but the `approval_required` gate is
only meaningful AFTER T-SELF-002 ships RepairTaskCreator. Either order
of merge is safe — if T-SELF-003 lands first, the gate just filters
nothing (no tasks set the flag yet); if T-SELF-002 lands first, its
tasks are exempt from autonomous dispatch (which is the intended
behavior anyway).

Authoritative refs (read before starting):

- `CLAUDE.md` — project conventions.
- `docs/orchestration/WORKER_BRIEF_TEMPLATE.md` — brief format.
- `agent_core/conductor/conductor.py` — `Conductor.get_autonomous_next()`
  (the filtering point), `add_task`, `list_tasks`.
- `agent_core/conductor/task_queue.py` — `TaskQueue` with `path`
  constructor parameter (used to point at a different JSONL file per
  project).
- `agent_core/conductor/dispatcher.py` — `ConductorDispatcher` class.
  **Already supports `project` parameter** — does not need changes;
  only its wiring is new.
- `agent_core/conductor/task_model.py` — `Task.artifacts` dict
  (where `approval_required` lives).
- `agent_core/modules/homeostasis_module.py` lines 1509-1546 — current
  Conductor + dispatcher wiring (the pattern to extend).
- `agent_core/homeostasis/core.py` line 271 — `add_conductor_dispatcher`
  method, already supports multiple dispatchers (list).
- `docs/orchestration/briefs/T-SELF-002.md` §Locked design §3 —
  `artifacts["approval_required"]` contract.

## Goal

Wire a second ConductorDispatcher for `project="maria"`, workspace
`/home/maria/maria`, sharing the existing dispatch tick infrastructure;
add a guard in `Conductor.get_autonomous_next()` that filters out tasks
with `artifacts.get("approval_required") == True`.

## Scope

- **Repository:** `~/maria/` (Maria main, branch `refactor/homeostasis`).
- **Dispatch mode:** inline on `refactor/homeostasis`.
- **In-scope edits:**
  - `agent_core/conductor/conductor.py` — add `approval_required` filter
    in `get_autonomous_next()`. ONE-LINE addition (plus comment + test).
  - `agent_core/modules/homeostasis_module.py` — after the existing
    market_agent Conductor + dispatcher block (lines 1509-1546), add
    parallel block for `project="maria"`. Same shape, different path
    + project string + workspace.
  - `agent_core/tests/test_conductor.py` — add tests for
    `approval_required` filtering.
  - `agent_core/tests/test_conductor_dispatcher.py` — add tests for
    workspace_path resolution on maria-repo dispatcher (existing
    dispatcher tests cover market_agent project).
- **In-scope new files:** none.
- **Out-of-scope (do NOT touch):**
  - `agent_core/conductor/dispatcher.py` — already supports the
    `project` parameter. No code change needed.
  - `agent_core/self_repair/` — T-SELF-002 territory.
  - `agent_core/self_perception/` — T-SELF-001 territory.
  - Web UI.

## Locked design decisions (do NOT relitigate)

1. **Two Conductors, two queues, two dispatchers.** The market_agent
   Conductor stays unchanged (default `TaskQueue` path =
   `meta_data/market_task_queue.jsonl`). A second Conductor is
   instantiated with `TaskQueue(path=Path("meta_data/maria_task_queue.jsonl"))`.
   Both Conductors are wired into `core` via the SAME
   `set_conductor` slot? **NO** — `set_conductor` accepts only one. So
   the maria conductor is stored separately on ctx as
   `ctx.maria_conductor`. Only the market_agent conductor goes into
   `core._conductor` (which drives `BuildStatus` snapshots, currently
   market-only). Both dispatchers go into `core._conductor_dispatchers`
   (list, supports many).

   **Why one BuildStatus consumer:** the existing
   `core._conductor.tick()` refreshes BuildStatus for all projects in
   its queue. With two queues, two tick() calls are needed. Solution:
   call `ctx.maria_conductor.tick()` separately, right after the
   market conductor tick in `HomeostasisCore.tick()`. ONE LINE.

2. **Maria conductor wiring path** (where added in `homeostasis_module.py`):

   ```python
   # Maria-repo conductor (T-SELF-003) — separate queue for self-repair
   # and other maria-project tasks. Independent of market_agent.
   try:
       from agent_core.conductor import Conductor
       from agent_core.conductor.task_queue import TaskQueue
       from pathlib import Path

       maria_queue_path = Path("meta_data/maria_task_queue.jsonl")
       maria_conductor = Conductor(queue=TaskQueue(path=maria_queue_path))
       ctx.maria_conductor = maria_conductor
       print("[Homeostasis] [OK] Maria conductor wired (project=maria)")
   except Exception as e:
       logger.warning(f"Maria conductor not initialized: {e}")
   ```

   Inserted IMMEDIATELY AFTER the existing `# Conductor (Phase 17 ...)`
   block (after line ~1519), BEFORE the dispatcher block.

3. **Maria dispatcher wiring** (right after the existing
   ConductorDispatcher block, ~line 1547):

   ```python
   # Maria-repo dispatcher (T-SELF-003). Workspace is the maria repo
   # itself. Tasks are seeded by self_repair (T-SELF-002) or manually
   # via Conductor.add_task. Inline mode — branch refactor/homeostasis.
   if core and getattr(ctx, 'maria_conductor', None) and getattr(ctx, 'codex_client', None):
       try:
           from agent_core.conductor.dispatcher import ConductorDispatcher
           notify = None
           if ctx.telegram_bridge and hasattr(ctx.telegram_bridge, 'bot'):
               notify = ctx.telegram_bridge.bot.send_message
           maria_dispatcher = ConductorDispatcher(
               conductor=ctx.maria_conductor,
               codex_client=ctx.codex_client,
               project="maria",
               notify_fn=notify,
           )
           core.add_conductor_dispatcher(maria_dispatcher)
           print(
               "[Homeostasis] [OK] ConductorDispatcher wired "
               "(project=maria, autonomous Codex dispatch)"
           )
       except Exception as e:
           logger.warning(f"Maria ConductorDispatcher not wired: {e}")
   ```

4. **`approval_required` filter in `Conductor.get_autonomous_next()`**:

   Current code (`agent_core/conductor/conductor.py:128-144`):
   ```python
   def get_autonomous_next(self, project: str) -> Optional[Task]:
       ready = [
           t for t in self._queue.list(project=project, status=TaskStatus.PENDING)
           if t.assignee in BUILDER_ASSIGNEES
           and self._deps_satisfied(t)
       ]
       if not ready:
           return None
       ready.sort(key=lambda x: (-x.priority, x.created_at))
       return ready[0]
   ```

   Add ONE condition:
   ```python
   def get_autonomous_next(self, project: str) -> Optional[Task]:
       ready = [
           t for t in self._queue.list(project=project, status=TaskStatus.PENDING)
           if t.assignee in BUILDER_ASSIGNEES
           and self._deps_satisfied(t)
           and not t.artifacts.get("approval_required", False)
       ]
       if not ready:
           return None
       ready.sort(key=lambda x: (-x.priority, x.created_at))
       return ready[0]
   ```

   Plus a docstring update explaining the new filter (one sentence).
   Reason: any task with `artifacts["approval_required"] == True`
   (self-repair tasks from T-SELF-002) must NOT be picked up by
   autonomous dispatch until operator approves via `/approve_repair`,
   which flips the flag to False.

5. **Tick integration: separate `tick()` calls for the two conductors.**
   In `agent_core/homeostasis/core.py`, find the existing Phase 17
   block (around line 617):

   ```python
   if self._conductor and self._tick_count % 180 == 0:
       try:
           self._conductor.tick()
       except Exception as e:
           logger.debug(f"Phase 17 conductor error: {e}")
   ```

   Add immediately after:
   ```python
   # T-SELF-003: also tick the maria conductor (different queue)
   if hasattr(self, '_shared_context') and getattr(self._shared_context, 'maria_conductor', None):
       if self._tick_count % 180 == 0:
           try:
               self._shared_context.maria_conductor.tick()
           except Exception as e:
               logger.debug(f"Phase 17 maria conductor error: {e}")
   ```

   The existing `_conductor_dispatchers` round-robin further down the
   tick already calls `dispatch_next()` on each dispatcher in the list,
   so adding the maria dispatcher via `add_conductor_dispatcher` is
   sufficient — no extra dispatch-loop wiring needed.

6. **Workspace path: `/home/maria/maria` (absolute).** Tasks created
   in the maria queue MUST set `artifacts["workspace_path"] =
   "/home/maria/maria"`. T-SELF-002's RepairTaskCreator already does
   this per its §3. If anyone (operator, tests, future scripts) creates
   maria-project tasks via `Conductor.add_task` without setting
   workspace_path, the dispatcher will mark them BLOCKED with
   `"missing workspace_path"` per existing dispatcher.py behavior —
   this is correct fail-loud behavior; do NOT change it.

7. **Dispatch throttling stays per-dispatcher.** Each
   ConductorDispatcher has its own `_last_dispatch_ts`. With two
   dispatchers, both will throttle at `DEFAULT_DISPATCH_INTERVAL_SEC =
   600s` (10 min) independently. This is the intended behavior — they
   can fire in alternating tick cycles, sharing the Codex rate limit
   (~10/h) gracefully.

## Definition of Done

- `Conductor.get_autonomous_next()` filters out tasks with
  `artifacts["approval_required"] == True`.
- `ctx.maria_conductor` is wired in `homeostasis_module.py` with a
  TaskQueue pointing at `meta_data/maria_task_queue.jsonl`.
- A second `ConductorDispatcher` is wired with `project="maria"`,
  added to `core._conductor_dispatchers`.
- `HomeostasisCore.tick()` calls `ctx.maria_conductor.tick()` every
  180 ticks alongside the existing `self._conductor.tick()`.
- New tests pass (see §Tests).
- Full `agent_core/tests/` suite still passes (5192 baseline +
  T-SELF-001 additions; expect ~5199+ after this task).
- `ruff check agent_core/conductor agent_core/tests/test_conductor*.py`
  clean.
- `mypy agent_core/conductor` clean.

## Tests

### Add to `agent_core/tests/test_conductor.py`:

1. **test_get_autonomous_next_skips_approval_required** — queue has
   two PENDING tasks: one with `artifacts["approval_required"]=True`,
   one without (or False). `get_autonomous_next(project)` returns the
   second task, never the first.
2. **test_get_autonomous_next_approval_flipped_becomes_eligible** —
   start with task `approval_required=True` → `get_autonomous_next`
   returns None. Update the same task with `approval_required=False`
   via `Conductor.add_task` (MERGE semantics on task_id), then
   `get_autonomous_next` returns it.
3. **test_get_autonomous_next_missing_flag_treated_as_false** — task
   has no `approval_required` key in artifacts at all (legacy or
   non-self-repair task) → eligible for dispatch (current behavior
   preserved).
4. **test_two_conductors_isolated** — two `Conductor` instances with
   different `TaskQueue(path=...)`. Add task to one, query the other
   → empty. Add to both → each sees only its own tasks.

### Add to `agent_core/tests/test_conductor_dispatcher.py`:

5. **test_dispatcher_with_maria_project** — instantiate
   `ConductorDispatcher(project="maria", ...)`, queue has a maria task
   with `workspace_path="/tmp/fake_maria_workspace"` (use tmp_path),
   dispatch fires `CodexClient.ask` with `cwd=tmp_path`.
6. **test_two_dispatchers_independent_throttling** — two dispatchers
   for two projects, each with `interval_sec=60`, fire them at
   `now=0`, then at `now=30` (each is throttled to 60s). At `now=70`,
   each fires again. The throttle is per-dispatcher, not global.

Test commands:
```bash
cd /home/maria/maria && python -m pytest agent_core/tests/test_conductor.py agent_core/tests/test_conductor_dispatcher.py -v
```

Full suite:
```bash
cd /home/maria/maria && python -m pytest agent_core/tests/ -q
```

## Non-goals

- Do NOT add new dispatcher behavior beyond the `approval_required`
  filter. The filter lives in `Conductor.get_autonomous_next`, not in
  the dispatcher.
- Do NOT modify `Task` dataclass.
- Do NOT add a config-file flag for enabling/disabling the maria
  dispatcher. It's wired unconditionally if `codex_client` + Conductor
  init both succeed (mirrors market_agent dispatcher).
- Do NOT add a worktree mode — inline only per TASK_BOARD §Dispatch
  mode comment (2026-05-16).
- Do NOT add cross-project task migration / promotion. Each queue is
  isolated.
- Do NOT touch the existing market_agent dispatcher behavior or path.
  Strict additive change.

## Conventions

- Python 3.10+.
- Type hints required.
- English docstrings; comments may be Polish.
- No emojis (ADR-005).
- No backwards-compatibility shims.
- Do not push to GitHub.

## Constraints from this task in particular

- **One filter line** in `get_autonomous_next` — no logic refactor.
  The list comprehension stays a list comprehension; just one more
  `and` condition + a docstring sentence.
- **No state leaks between conductors** — confirm test #4 isolates
  fully. If you find the existing TaskQueue accidentally shares state
  via module-level globals or singletons, surface it as an ambiguity
  (it should not, but verify).
- **Print statements are OK in the wiring path** (`print("[Homeostasis]
  [OK] ...")`) — they mirror the existing print convention in
  `homeostasis_module.py` for init messages. The logger.warning for
  failure path is also already the convention.

## If you encounter ambiguity

- Stop. Output a numbered list of the ambiguities.
- Do NOT guess. Master will rewrite the brief.
- Especially: if `Conductor` or `TaskQueue` have shared state that
  makes two-instance isolation problematic, or if
  `add_conductor_dispatcher` has constraints not visible in the call
  signature — surface it.

## Output

- Inline commits on `refactor/homeostasis`.
- 2 logical commits preferred:
  1. `feat(conductor): approval_required filter in get_autonomous_next`
  2. `feat(homeostasis): maria-project conductor + dispatcher wiring`
  3. (optional) `test(conductor): approval flag + isolation + maria dispatcher`
- When done, output short summary: files changed, test count, any
  surprises.

## Authoritative references (must read before starting)

- `CLAUDE.md`
- `docs/orchestration/WORKER_BRIEF_TEMPLATE.md`
- `agent_core/conductor/conductor.py` (lines 128-154 — `get_autonomous_next`)
- `agent_core/conductor/dispatcher.py` (`project` parameter, workspace
  handling)
- `agent_core/conductor/task_queue.py` (`path` constructor param)
- `agent_core/modules/homeostasis_module.py` lines 1509-1546 (current
  market dispatcher wiring — the pattern to extend)
- `agent_core/homeostasis/core.py` lines 173-280 (conductor wiring
  slots) and ~617 (tick block to extend)
- `docs/orchestration/briefs/T-SELF-002.md` §Locked design §3 (the
  `approval_required` artifact contract)
