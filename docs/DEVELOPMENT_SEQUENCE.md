# M.A.R.I.A. — Development Sequence (SSoT for "what's next")

> **THE single source for build order.** Other docs (MEMORY, `audits/INDEX`,
> `FOUNDATIONS_GAP`, `ROADMAP`, `SYSTEM_STATUS` priorities) should LINK here, not
> duplicate a build-order. Synthesis of `audits/FOUNDATIONS_GAP_2026-05-30.md`
> (the verified gap map) + `ROADMAP.md` Faza K "Statek Teseusza" discipline,
> validated against live code.
> Local until work underway (ADR-029 / publish-after-execution).
> Last updated: 2026-07-06 (planning session, 13-agent recon: DH-B rollup
> evidence COMPLETE (282+ correct observe decisions on the funding project,
> 3/3 achieved 07-05); GOAL_DEADLINE_ENABLED turned out to be a DEAD WIRE on
> the live daemon — read only by abandoned entrypoints — fixed `f6ba962`;
> creative night-loop faucet closed `0039116`. TIER 2 closes with: ROLLUP
> cutover (**DONE 07-09 19:54 — clean: one `[ROLLUP/cutover] achieved` line
> then silence, `closed_by=rollup` written to goals.jsonl, new PID 202729,
> zero boot errors**) + DEADLINE cutover after live observe lines (STILL OPEN
> — awaits project #2, i.e. a deadline goal that rollup does NOT close; the
> funding parent got closed by rollup so it can't be the DEADLINE=cutover proof).
> Next after Tier 2: DH-C arming (drill-first), then TIER 3 room #1:
> **workflow** (order amended 07-06, Eryk ack — see Tier 3), skills after).

## Why this doc exists

Every audit (4 of them) found the SAME root defect: parallel "deski" built at
once + docs drifting from code -> split-brain, dead code, loops wired-but-empty.
It was never a lack of rules — it was not holding to them in sequence. This doc
is the sequence, with the rules as guardrails. **One brick at a time.**

## 5 anti-collision guardrails (BHP budowy)

1. **ONE source of truth.** Soul files (`beliefs`, `knowledge_index`,
   `identity`, `decision_traces`, `semantic_vectors`, `conversation_memory`) are
   sacred; every module reads/writes the SAME files (Statek Teseusza zasada
   kardynalna). -> kills split-brain.
2. **One plank at a time.** Finished before the next starts. No parallel sprawl
   (that sprawl is exactly what the audits caught).
3. **Flag -> alongside -> observe -> cutover.** New never replaces old big-bang:
   feature flag off=old, on=new, observe in vivo, then remove legacy. Proven:
   `/strategic` (#9), `INTENT_ROUTER_ENABLED`.
4. **DONE = OBSERVED in logs**, not "written + tested". (5-status vocab in
   `SYSTEM_STATUS.md`: LIBRARY / WIRED / OBSERVED / OPERATOR_READY / RESEARCH_ONLY.)
5. **Kill or freeze — zero orphans.** Every module carries a status banner; dead
   code is removed, not-yet-wired code is frozen LIBRARY with a banner.

## The sequence (3 tiers — depth before breadth)

### DONE — foundation keystones (2026-05-30..31)
`FOUNDATIONS_GAP` build-order items 1-5 + 8, all shipped this week:
independent examiner (**keystone** — exam no longer self-graded), sandbox
consumer-gate ("read != trusted"), goal-closure loop (#3, first autonomous
completions ever), durable fetch->learn handoff (#4), learning-window TZ SSoT
(#5), StrategicPlanner wire-in behind flag (#9). Plus: dead-code cleanup
(adapters/skills), Telegram master-chat auth gate.

### 🏠 TIER 1 — FINISH THE ROOF (outer corrective loop)  ✅ CLOSED 2026-06-07
The organism can think + learn (inner loop); it could not yet reliably
**recover, prove delivery, or wake warm** -- now it can: all four planks (6,
7a/7b, 9, 10) are live OBSERVED. Items 6, 7, 9, 10 from the gap map -> planks
below. **Next: TIER 2 hands** (first real effector action on the world).

### 🔧 TIER 2 — DEPTH BEFORE BREADTH  *(3 of 4 planks done; last plank armed =observe 07-04)*
- **Hands** ✅ far past Rung 2: outbox autonomous-propose ARMED
  (`OUTBOX_WRITE_ENABLED`, 06-08); B2 FS_WRITE effector LIVE (RED drill 06-21,
  `FS_WRITE_ENABLED` + `LEARNING_NOTES_ENABLED`); undo journal + execute LIVE
  on real OpenClaw (DH-A live rung 06-24/25, Maria wrote AND reverted a file);
  UNDO-SUGGEST armed observe-first (06-25); K7 authority reconciled (06-01..07).
  *Remaining rungs (post-Tier-2):* widen artifact types; OpenClaw at CONFIRM.
- **Knowledge consolidation/synthesis** ✅ Stage 1 (06-10: real sleep
  consolidation + semantic dedup) AND Stage 2 (06-13/14: synthesizer live,
  first synthesis 82.5%, local-qwen3 faithfulness gate fail-closed,
  `SYNTH_ENABLED` + `CONCEPT_TRUST_GATE=armed`, autonomous topic picker).
- **Long-horizon project goals** — DH-B built 2026-06-22 (`parent_goal_id`
  rollup STEP 2.35 + deadline urgency + `/project` operator kran, ~96 tests,
  schema-guard always-on) but dormant 2 weeks. **ARMED 2026-07-04:
  `GOAL_ROLLUP_ENABLED=observe` + `GOAL_DEADLINE_ENABLED=observe`.**
  ROLLUP evidence COMPLETE 07-05/06: first operator project 3/3 achieved,
  282+ correct `[ROLLUP/observe] all_children_achieved` decisions, zero
  mutation. DEADLINE was a congenital DEAD WIRE on the daemon (flag read
  only in select_goal/rank_goals, neither reachable from the live ranked
  path since the 03-31 rewrite — wrong-component-tested) — **fixed
  `f6ba962` 07-06**: dmode read in `_select_ranked_goals`, scorer reads the
  flag itself when a caller forgets, log dedup per 0.1-multiplier step.
  Cutover plan: **ROLLUP=cutover BEFORE 07-09 22:57** (else the parent
  lingers ACTIVE forever; expect one proactive GOAL_ACHIEVED ping — that IS
  the demo); DEADLINE=cutover only after live `[DEADLINE/observe]` lines
  (~07-08 evening on the funding parent, or project #2). **REAP:
  recommendation permanently OFF** (binary flag with no observe mode, USER
  goals NOT exempt; rollup's ANY_FAIL path covers failures) — Eryk decision
  to record at cutover. **This is the plank that closes TIER 2.**
- **Rollback / quarantine** ✅ shipped 2026-06-14 (conscious-unlearn: in-place
  status-flip + carry-forward + visibility filter + build denylist + blocking
  lock + vector evict + replay-on-boot; /quarantine //retract /forget_source).

### 🚪 TIER 3 — NEW ROOMS (breadth, same discipline)
`workflow`, `skills`, `vision-grounding`, `voice` (north-star). Each via the
flag->observe->cutover discipline. **Deliberately last** — see module map for why
building them earlier IS a collision.

> **Room order amended 2026-07-06 (Eryk ack): workflow BEFORE skills.**
> Evidence: (a) workflow's blocking premise "nothing to orchestrate" flipped
> when hands went live 06-21/24 (FS_WRITE + undo + outbox all armed);
> (b) workflow is the standing guardrail-4 violation — WIRED, tick Phase 14
> advancing an EMPTY store every minute, engine never ran once
> (`workflows.jsonl` never existed), `/wf approve` has zero production
> callers (requires_approval steps deadlock), DelegationManager bypasses
> K7 — the room opens by OBSERVING never-run code, then adding valves;
> (c) skills' fuel (decision_traces) was poisoned by the creative night
> loop until `0039116` — extractor dry-run gave 4/4 junk; it needs weeks of
> clean traces, which the faucet fix now accumulates as a side effect.
> Programme arc after Tier 2 (planning session 07-06): **Warsztat**
> (workflow room, operator-kran only, STOP before autonomy) -> **Kartoteka**
> (Faza 7 honest ledger: revive incident recorder, dedup, /trust week,
> effector evidence into TrustScorer) -> **Tasma** (delivery + autonomy
> last, on earned evidence). Details: DIGITAL_HUMAN_ROADMAP.md section G.

## Module map — each path, developmentally

| Module | Status today | Next safe step | Gated on |
|---|---|---|---|
| self-repair | ✅ live drill OBSERVED (06-07); ADR-031 approve=close; expiry sweeps BLOCKED | — | done |
| proof-of-delivery | 7a outbox ✅ + 7b heartbeat ✅ OBSERVED (06-07) | — | done |
| warm recovery | ✅ OBSERVED (06-07 + real boots since) | — | done |
| drift guard | ✅ DONE (`doc_lint.py` + test, 06-06) | — | done |
| **effector / hands** | ✅ FS_WRITE LIVE + undo journal/execute LIVE (06-21..25); outbox propose armed | widen artifacts; OpenClaw at CONFIRM | Tier-2 close |
| consolidation | ✅ stage 1 + 2 LIVE (synthesis armed 06-14, trust-gate, topic picker) | observe quality over weeks | done |
| **project goals** | built 06-22; ARMED =observe 07-04; rollup evidence COMPLETE 07-05; deadline dead-wire fixed `f6ba962` | ROLLUP cutover przed 07-09 22:57 -> DEADLINE cutover po zywym observe; REAP rekomendacja: trwale OFF | **closes TIER 2** |
| rollback/quarantine | ✅ shipped 06-14 (conscious-unlearn) | — | done |
| capability gate (DH-C) | built 06-22, signal-honesty fix 06-28 (`1e322af`); observe silence = healthy (16/16; 702 pre-fix blocks archived on /mnt/storage) | `/drill_capability` (must FORCE-plan the nulled action) + manifest alarm in Phase 18 snapshot -> arm `CAPABILITY_GATE_ENABLED=1` | DH-B plank |
| **workflow** | wired (Faza 5) but NEVER ran once; `/wf approve` zero callers; DelegationManager bypasses K7 | room #1 (07-06 amendment): boundary one-pager -> first-ever `/wf start` -> note_pipeline -> valves (/wf approve + K7 parity); operator-kran only | TIER 2 closed |
| **skills** | LIBRARY (frozen); 8 stale 05-15 sandbox drafts = latent trap (archive them); extractor dry-run 4/4 junk on poisoned traces | room #2: extract from CLEAN traces (post-`0039116`) -> sandbox `promote()` | workflow room + weeks of clean traces |
| vision-grounding | motion-triggered (MOG2 06-21) + VisionMemory ring + PL captions | beliefs from camera autonomously | hardware + Tier 3 |
| voice (north-star) | missing | "one file of truth, works everywhere" | Tier 3 |

> **On `skills` + `workflow` (the collision question):** both sit in Tier 3 on
> purpose. `skills` MUST pass through sandbox-`promote()` (autonomous
> skill-create collides with ADR-010/011 — the roadmap already rejects it), so it
> needs the now-real learning loop AND hands to extract from. `workflow` has
> nothing to orchestrate until the effector makes real actions. Building either
> now recreates exactly the "wired-but-empty" defect the audits found.

---

## TIER 1 — planks (concrete, flag-gated)

Order: drift-guard first (low-risk, it IS guardrail-as-code) -> self-repair drill
(restart-gated) -> proof-of-delivery -> warm recovery (biggest, last).
🔒 = needs the Monday restart to verify in vivo.

### 10. Drift guard — docs-from-code  ✅ DONE 2026-06-06 *(pull forward: low risk, high leverage)*
Drift is the most persistent recurring defect across all 4 audits. Make it
impossible to reintroduce silently.
- **SHIPPED:** `scripts/doc_lint.py` (3 checks: tick-phase count docs==code,
  stale code paths in living docs, module-tree↔filesystem) +
  `agent_core/tests/test_doc_lint.py` (10 tests, auto-run in suite). First run
  caught 3 real drifts now fixed (10b): CONTRACTS.md "9 faz", SYSTEM_OVERVIEW.md
  "15 faz", and 15 undocumented agent_core modules in the CLAUDE.md tree.
- **10a** `scripts/doc_lint.py` — assert tick-phase-count(docs == code), module
  list(docs == filesystem), no doc refs to deleted dirs. Auto-run in the suite
  (mirror `scripts/ui_lint.py` + `test_ui_lint.py`).
- **10b** One-time regen of remaining stale docs (CLAUDE.md "17 faz" -> 19,
  `core.py` docstring, any straggler).
- Flag: none (a guard, not a behavior change). Gated on: nothing. **OBSERVED** =
  suite fails if a doc and the code disagree.

### 6. Self-repair — first live drill  ✅ DONE+OBSERVED 2026-06-07
Chain is built + drill-green in harness; it had **never fired on a real failure**
(no `maria_task_queue.jsonl` in production). Now proven in vivo: `/drill_repair
force` -> cdt-4d13b5baaf55 (drill, approval_required) -> bulletin -> TASK_BOARD
-> Telegram -> `/approve_repair` -> DONE + bulletin RESOLVED, **0 Codex dispatch**
(ADR-031). 0x live -> 1x full cycle.
- **6a** `/drill_repair` master command — injects a synthetic detector hit
  through the REAL `RepairTaskCreator` path (creates a real queue row,
  `approval_required=True`, tagged `drill=true`). Safe + repeatable; no real
  outage needed. Master-only (Telegram gate now enforced). Tests.
- **6b** 🔒 Run in vivo: `/drill_repair` -> `/list_repairs` -> `/approve_repair`
  -> observe `project=maria` dispatch. **OBSERVED** = a real queue row dispatched.
- **6c** ~~un-stub `_review()`~~ **DELETED 2026-07-06**: the stub is
  unlocatable at HEAD (grep clean in conductor/self_repair; only an
  IMPLEMENTED legacy `_review` in code_agent) and the premise — Maria
  self-validates a Codex diff before dispatch — was superseded by ADR-031
  (approve = close, zero Codex-on-prod dispatch).
- Flag: command-gated (master). Gated on: restart for 6b.

### 7. Proof-of-delivery + heartbeat
The safety-critical escalation channel (Telegram) is fire-and-forget and
unobservable; "I stopped pulsing" is undetectable.
- **7a** Durable outbox — every `bot.send_message` appends to
  `meta_data/telegram_outbox.jsonl` (ts, text, ok, attempts). Additive
  observability, no flag. **OBSERVED** = escalation channel is auditable.
- **7b** Heartbeat watchdog  ✅ DONE+OBSERVED 2026-06-07. The out-of-loop
  `TickWatchdog` only catches a frozen MAIN loop; this fills the gap it cannot
  see — a worker thread that dies (persistent) or wedges (transient) while the
  tick keeps pulsing. Phase 19 gained a 4th detector `detect_thread_unhealthy`
  reading `HomeostasisCore.get_thread_health()` (persistent dead / transient
  alive >30min). Flag `HEARTBEAT_DETECTOR_ENABLED` (parallel-run, **OFF** by
  default — arm via `.env` + restart for autonomous 10-min scans). Surfaces via
  the normal repair-task path (ADR-031 alert, never auto-fix). Live-proven:
  `/drill_heartbeat force` -> cdt-27ac4aa8c2d8 (thread_unhealthy, drill,
  approval_required) -> bulletin cbb-eac3 -> TASK_BOARD -> Telegram ->
  `/approve_repair` -> DONE + RESOLVED, 0 Codex. 15 tests.
  - *Residual (after OBSERVE):* persistent-but-wedged (alive, internal loop
    stuck) needs per-loop beats; a tighter telegram-poll wedge threshold than
    the uniform 30 min. Defer unless OBSERVE shows need.

### 9. Warm crash recovery  ✅ DONE+OBSERVED 2026-06-07 *(largest — last)*
Daemon woke COLD (snapshot/recover library orphaned, `_trigger_snapshot` a
no-op). Built NEW -- the orphan `homeostasis/snapshot.py` serialized the wrong
shape (memory hashes, no plan), so it was deliberately NOT resurrected. Touches
boot + soul files -> built understand-first + adversarially reviewed (2
workflows, 9 agents; all 5 real findings fixed).
- **9a** `agent_core/homeostasis/recovery.py` persists mode(HINT) + active goal
  IDs + the in-flight StrategicPlan to `meta_data/warm_recovery.json` atomically
  (tmp+fsync+os.replace); wired into `_trigger_snapshot` + a periodic tick write.
- **9b** Boot hook in `maria.py run_daemon` (before first tick) resumes a fresh,
  non-expired plan; mode is HINT-only (tick 1 re-derives from sensors -> no
  crash-loop); goals stay in goals.jsonl (IDs only). `restore_plan` reseeds
  `_last_plan_ts` so the resumed plan is not replanned away under DRIVES.
- **9c (Layer 1)** `identity_store._save` made atomic (was in-place overwrite
  -> whole-file corruption on a crash mid-write). Always-on. *Deferred to
  post-OBSERVE: per-append fsync batching + belief/vector compact dir-fsync.*
- Flag: `WARM_RECOVERY_ENABLED` (armed 06-07). Gated on: 6 + 7 done.
  **OBSERVED**: warm_recovery.json materializes live (mode + 5 goal IDs), boot
  hook logs + does not break startup, identity atomic (no .tmp). Read-resume
  primed (file exists -> next restart reads it).

---

## Source docs (this is a synthesis, not a competitor)
- `docs/audits/FOUNDATIONS_GAP_2026-05-30.md` — verified gap map (MAMY / PO POŁOWIE / NIE MAMY) + the build-order this sequence follows.
- `docs/ROADMAP.md` — Faza K "Statek Teseusza" plank discipline + cardinal rule.
- `docs/SYSTEM_STATUS.md` — per-module status (SSoT for **status**; this doc is SSoT for **order**).
- `docs/audits/INDEX.md` — audit catalog + open work items.
