# M.A.R.I.A. — Development Sequence (SSoT for "what's next")

> **THE single source for build order.** Other docs (MEMORY, `audits/INDEX`,
> `FOUNDATIONS_GAP`, `ROADMAP`, `SYSTEM_STATUS` priorities) should LINK here, not
> duplicate a build-order. Synthesis of `audits/FOUNDATIONS_GAP_2026-05-30.md`
> (the verified gap map) + `ROADMAP.md` Faza K "Statek Teseusza" discipline,
> validated against live code.
> Local until work underway (ADR-029 / publish-after-execution).
> Last updated: 2026-06-07 (TIER 1 roof CLOSED: planks 6, 7a/7b, 9, 10 all live
> OBSERVED. Next: TIER 2 hands -- first real effector action on the world).

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

### 🔧 TIER 2 — DEPTH BEFORE BREADTH  *(in progress: hands Rung 2 OBSERVED 06-07)*
- **Hands** — first real effector call on the world. ✅ **Rung 2 OBSERVED
  2026-06-07**: Maria PROPOSES a deterministic status note, operator
  `/approve_note` writes it to `meta_data/maria_outbox/` (outside the sandbox,
  via the guarded sandbox_write engine + atomic no_overwrite). First real
  artifact: `maria_status_*.txt`. Autonomous PROPOSE behind `OUTBOX_WRITE_ENABLED`
  (OFF until armed); the write is always operator-gated. *Next rungs:* arm the
  autonomous proposer; widen artifact types; later OpenClaw read-only at CONFIRM
  (needs an undo story + authority reconciliation first -- live K7 = BOUNDED).
- **Knowledge consolidation/synthesis** — sources merge into concept maps; today
  knowledge is a flat pile that never compounds. *Stage 1 done 2026-06-10:*
  sleep consolidation real (NREM2 boost + NREM3 forgetting OBSERVED live)
  and the semantic-dedup chain wired end-to-end (entity metadata contract,
  planner + Telegram callers, threshold 0.95 calibrated on live vectors,
  `SEMANTIC_DEDUP_ENABLED` off->observe->merge rollout). *Stage 2:* the
  synthesizer itself (NIM concept maps behind the independent-exam gate).
- **Long-horizon project goals** — sub-goal trees + deadlines (today 0 project
  goals, 0 deadlines).
- **Rollback / quarantine** — retract bad knowledge (today append-only, never
  unlearns).

### 🚪 TIER 3 — NEW ROOMS (breadth, same discipline)
`skills`, `workflow`, `vision-grounding`, `voice` (north-star). Each via the
flag->observe->cutover discipline. **Deliberately last** — see module map for why
building them earlier IS a collision.

## Module map — each path, developmentally

| Module | Status today | Next safe step | Gated on |
|---|---|---|---|
| self-repair | ✅ live drill OBSERVED (06-07, cdt-4d13b) | — | done |
| proof-of-delivery | 7a outbox ✅ + 7b heartbeat ✅ OBSERVED (06-07, cdt-27ac) | — | done |
| warm recovery | ✅ OBSERVED (06-07, warm_recovery.json + boot hook live) | — | done |
| drift guard | ✅ DONE (`doc_lint.py` + test, 06-06) | — | done |
| **effector / hands** | ✅ Rung 2 OBSERVED (06-07, outbox; operator-gated write) | arm autonomous propose; widen artifacts | roof done ✅ |
| consolidation | stage 1 ✅ (06-10: real sleep OBSERVED, 1453 boosted; semantic dedup wired, flag dark) | arm `=observe`, calibrate, cutover; then stage 2: synthesize sources -> concept map | keystone (done) |
| project goals | flat single-topic | sub-goal trees + deadlines | goal-closure (done) |
| **skills** | LIBRARY (frozen) | extract from traces -> sandbox `promote()` | learning-loop real (done) + effector |
| **workflow** | wired (Faza 5) | orchestrate real actions | **hands** (no hands -> nothing to orchestrate) |
| vision-grounding | on-demand only | beliefs from camera autonomously | hardware + roof |
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
- **6c** *(deferred to Tier 2)* un-stub `_review()` so Maria can self-validate a
  diff (autonomy expansion — operator-gated is safe for now).
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
