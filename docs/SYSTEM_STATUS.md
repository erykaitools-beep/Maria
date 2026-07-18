# M.A.R.I.A. — System Status (source of truth)

> **Why this file exists:** a single place that tells the truth about **what is
> actually live** in production versus what is only a library/experiment. It was
> created after a deep code audit (2026-05-29) that showed the docs were
> describing several versions of the system at once.
>
> **Principle (the definition of DONE since 2026-05-29):** a module is not
> "done" until it reaches `OBSERVED` — that is, until **we have seen it run in
> the logs**. "Library + tests + docs" is not the same as "works in-vivo". This
> is the mechanism that attacks the root cause of drift: *"we patch the old and
> build the new, but there is no checking."*

## Status vocabulary (5 levels)

| Status | Meaning | Evidence |
|---|---|---|
| `LIBRARY` | Code + tests exist | green suite |
| `WIRED` | Reachable from the daemon/REPL/UI (the spine imports it) | import graph |
| `OBSERVED` | **Has fired in live/archived logs** | entries in `meta_data/` or `/mnt/storage/data/logs/` |
| `OPERATOR_READY` | An operator flow exists (UI/Telegram) and is documented | command/endpoint + doc |
| `RESEARCH_ONLY` | Deliberately NOT live (frozen/experiment) | directional decision |

A status promotion requires evidence from the level above — `WIRED`→`OBSERVED` only when there are log entries, not when it "should work".

## Module map (as of 2026-05-30)

Source: the import graph from `maria.py`/`main.py`/`maria_ui.app`, live
`meta_data/`, the `maria.service` journal, a targeted self-repair drill, and
regression tests.

| Module | Status | Note / evidence |
|---|---|---|
| K1-K13 cognitive core | `OBSERVED` | rich runtime archive (decision_traces, action_audit, reflections) |
| `homeostasis` (tick 1-20) | `OBSERVED` | tick loop, `homeostasis_events` 76.7k archive |
| `planner` | `OBSERVED` | runs live, but `no_goals` often means "no executable goals right now", not an empty goal queue |
| `creative` | `OBSERVED` | `creative_events` 4160 live; generator→bulletin (R1) confirmed at 19:02 |
| `critic` | `OBSERVED` | `critique_reports` 5186 archive |
| `bulletin` | `OBSERVED` | `cognitive_bulletin` 824 (open 470, resolved 354) |
| `llm` (LLMManager + NIM + scheduler) | `OBSERVED` | 15/15 reachable; nemotron-49b EXTERNAL |
| `self_perception` (Phase 18) | `OBSERVED` | `self_state_snapshots` 49 live |
| `routing` (IntentRouter) | `WIRED` (flag-gated) | default false via env (`routing/intent_router.py:68`) |
| `conductor` (Phase 17) | `WIRED` + `OBSERVED` (market) | dispatcher wired; `market_task_queue` 92 rows; currently idle/skipping because there are no ready tasks or the dirty-worktree guard is active |
| `vision` | `WIRED` (sensor optional) | LLaVA on-demand, cortex shared with the UI |
| `orchestrator` (V3) | `WIRED` | init at `maria.py:477` |
| **`self_repair` (Phase 19)** | **`WIRED`; `OBSERVED` in a controlled drill, not naturally in-vivo** | `SystemFailureMonitor -> RepairTaskCreator -> maria_task_queue -> approval_required gate -> dispatcher` verified 2026-05-30; live is healthy/SLEEP, so a natural candidate has not yet arisen |
| `skills` | `LIBRARY` (1.0-backlog) | extractor exists (`teacher/skill_extractor`), no wiring to planner/tick; STATUS banner in `__init__.py` 2026-05-31; do not delete |
| `symbolic` (world model) | `RESEARCH_ONLY` | **Maria 2.0 — frozen 2026-05-29.** 0 imports from the spine; the flag is never read |
| `predictive` (B0/B0.1, JEPA) | `RESEARCH_ONLY` | **Maria 2.0 — frozen 2026-05-29.** 0 imports from the spine |
| `adapters` | **REMOVED 2026-05-31** | migration bridge maria_core→agent_core, 0 reachable. Removed: 1226 LoC + `test_adapters.py`; non-adapter integration tests retained in `test_homeostasis_integration.py` |
| `metacontrol` | **REMOVED 2026-05-29** | track A3: removed + `test_metacontrol.py` (273 LoC, 24 tests) |
| `agent_core/ui` | **REMOVED 2026-05-29** | track A3: removed (746 LoC, 0 tests); the Web UI is `maria_ui/` |
| `agent_core/executor` | `LEGACY` (document) | only a `TYPE_CHECKING` import in `homeostasis/core.py:40` |

## Correction after the deep pass on 2026-05-30

The conclusions from the 2026-05-29 audit must be read through the lens of the 2026-05-30 changes:

- The `OperatorModel` split-brain is essentially closed: the daemon sets
  `ctx.user_profile = operator_model`, the Web UI brain/chat/profile paths go
  through `get_operator_model()`, and `UserProfile` remains as a legacy
  adapter/test target.
- `self_repair` is no longer just "might work": a targeted drill confirmed the
  full chain of task creation + approval gate. The absence of a live
  `maria_task_queue.jsonl` means there is no natural candidate, not a lack of
  wiring.
- The feasibility policy (learning windows + `SLEEP` mode) gates autonomy.
  **On 2026-05-31 (#5) a LIVE bug was found and fixed:**
  `PROFILE_LEARNING.auto_trigger_hours` were authored as UTC, and after the OS
  timezone was switched to Europe/Warsaw (05-29) they fired the window 2h too
  early (07-10 + 12-15 instead of 09-11 + 14-16). Fixed to `(9,10,14,15)`
  Berlin-pinned (`berlin_now`, ZoneInfo, DST-safe) — `9efe7cf`/`5fe75ee`/`65b1b4e`.
  This explains `no_goals` during the real window (learning started at night on
  the off-window budget). The off-window rhythm budget (8b) + goal
  reconciliation/reaper (#3) are already deployed; in-the-field verification of
  daytime learning is pending for Monday 09:00.
- `StrategicPlanner` is `WIRED` and connected to the tactical loop behind the
  `STRATEGIC_PLANNER_DRIVES` flag (#9, 2026-05-31, default OFF). When ON:
  `blocked_goals` filters goals, `next_action` sets focus + closes out the plan,
  `idle_strategy` drives the idle fallback; all the safety gates
  (feasibility/window/backoff/mode/K7) stay in the core. `OBSERVED` is pending a
  live drill (Monday) -> then the default flips to ON.

### Current foundation priorities

> The list below captures the current foundation priorities and their rationale.
> #1 (window, #5) and #3 (StrategicPlanner, #9) are closed; #2 and #4 are in progress.

1. Replace the rigid learning windows with a rhythm budget: weekends/evenings
   should allow light autonomous actions (`goal_refresh`, `fetch`, `review`,
   self-repair drill) without triggering heavy `learn/exam`.
2. Add `Goal Reactivation`: old active learning/meta goals must go through
   `revalidate -> refresh topic -> next executable action` instead of piling up.
3. ~~Finish the `StrategicPlan.action_queue -> PlannerCore` bridge~~ — DONE
   2026-05-31 (#9, A+B+C behind the `STRATEGIC_PLANNER_DRIVES` flag, default
   OFF); the live drill + default flip remain, pending observation.
4. Run one controlled live self-repair drill in `ACTIVE/REDUCED` to see
   `meta_data/maria_task_queue.jsonl`, `/list_repairs`, `/approve_repair`, and
   dispatch in production.

## Maria 2.0 — frozen in time (2026-05-29)

`symbolic` + `predictive` are the new 4-pillar paradigm (symbolic world model +
predictive/JEPA; see `docs/AGI_HYPOTHESES.md`). The decision: **suspended in
time, NOT deleted.** The code + tests stay line-for-line. Focus shifts to
maturing and verifying Maria 1.0 (LLM+agent+memory), because that is where the
real data on "how this will actually work" will come from. We return to 2.0 once
1.0 provides data.

## Stale docs — do NOT treat as runtime truth

- `docs/ARCHITECTURE.md` — April 2026; claims 11 phases / 3352 tests. The code
  actually runs 20 phases (Phase 20 = conversation condense, 06-21) and 7,145
  collected tests. Historical until regenerated.
- Web UI `_JSONL_DATA_FLOW` (`maria_ui/app.py:2469`) — a manual map that omits,
  among others, `self_state_snapshots`, `maria_task_queue`, `creative_events`,
  `cognitive_bulletin`. Regenerate it from the stores or drop it from the
  "truth" panels.

---

*Created 2026-05-29 (track A coherence cleanup). This file is the SSoT for module status — update it on every wired/observed change.*
