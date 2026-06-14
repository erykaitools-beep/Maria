# DEVELOPMENT_SEQUENCE — Option B (IMPLEMENTED 2026-05-31)

> **STATUS: IMPLEMENTED 2026-05-31.** Planks B2/B3/B4 shipped (`3360a20`+`21081ed` FS_WRITE,
> `c623782` success_criteria, `c449aa4` independent-exam + held-out bank). The active
> build-order SSoT remains `docs/DEVELOPMENT_SEQUENCE.md`; this file is kept as the design
> record. (Marked during 2026-06-05 cleanup — was lingering as "pending".) Original below.
>
> **STATUS (orig): PROPOSAL.** Reorder of `docs/DEVELOPMENT_SEQUENCE.md` after 4 external
> adversarial reviews (DeepSeek / Grok / Gemini / ChatGPT 5.5) of the 2026-05-31
> state report (`meta_data/MARIA_state_report_2026-05-31.pdf`; answers in
> `docs/incoming/Odpowiedzi na dokument z 31.05.2026.pdf`).
> Local until gated (ADR-029). If Eryk + Codex approve, this cuts over the real SSoT.
> Drafted 2026-05-31. Grounded against live code (file:line) by 3 read-only agents.

## What changed, in one paragraph

Four external models, independently, said our sequence was **inverted**: we were
about to perfect the *roof* (self-repair drill → proof-of-delivery → warm
recovery) before proving the house can do **one real thing in the world**. 3.5/4
say the true keystone is: **"can Maria close ONE real goal through a verified
external effect, without lying to herself?"** So Option B:

- pulls **hands** (first real effector action) + **goal-schema repair** UP into Tier 1;
- reframes verification as a pure-Python **held-out bank** (4/4: qwen3-vs-llama3.1
  on the same machine is *not* enough independence);
- keeps the **two cheap roof items everyone still wants** (proof-of-delivery
  outbox, cold-boot marker);
- **defers full warm crash recovery [L]** (3/4 said premature).

## Guardrail upgrade — Q7, the blind spot all 4 audits missed

The reviewers' deepest convergence (Q7): the system can make every *internal*
number look perfect while remaining a closed, self-referential loop with **no
external, un-gameable source of truth**. Grok + ChatGPT both noted our existing
rule "DONE = OBSERVED in logs" is *better* than "written + tested" but **still
self-generated** — logs only prove software emitted events, not that the right
external thing happened.

**Guardrail #4 is upgraded:**

> **DONE = externally-checkable evidence** — a held-out-bank result, a K10
> effect-validated *real* state change, or an external checker — **not a log line
> we wrote ourselves.** (This is exactly what planks B2 + B4 build.)

The other 4 guardrails are unchanged (ONE source of truth; one plank at a time;
flag → alongside → observe → cutover; kill-or-freeze, zero orphans).

---

## 🏗️ NEW TIER 1 — prove ONE real closed loop

These planks **interlock into a single slice**: the `FS_WRITE` primitive (B2)
closes a goal whose `success_criteria = {type: file_exists}` (B3), validated by a
real K10 file-exists check (B2) — the complete observe → act → verify → close
loop the reviewers demanded. The held-out bank (B4) is the verification upgrade
running alongside; proof-of-delivery (B1) is the observability spine that lets us
*trust* "it happened."

| Plank | Effort | What | Flag | OBSERVED = | Depends on |
|---|---|---|---|---|---|
| **B3** Goal-schema activation | S→M | Activate the already-dead `deadline` + `parent_goal_id`; add `success_criteria`. Backward-compatible (loose-merge `from_dict`). | none (additive schema) | a goal carries a machine-checkable `success_criteria` that the planner reads | — |
| **B2** First effector primitive `FS_WRITE` + criteria goal-closer | M | THE keystone. New **GUARDED** action type via the sandboxed `FileManager` (NOT OpenClaw); K10 file-exists validator; **autonomous plan-gen seam** in the planner; closes a `success_criteria` goal. | `FS_WRITE_ENABLED` (default off) | one goal goes ACTIVE→ACHIEVED via a real file written + K10-validated + audited | **B3** |
| **B1** Proof-of-delivery outbox | S | Every `bot.send_message` appends `meta_data/telegram_outbox.jsonl` (ts, text, ok, attempts). (= old plank 7a.) | none (additive) | the escalation channel is auditable | — |
| **B4** Held-out verification bank | M | Pure-Python static grader: read-only Q→canonical-answer file, exact/regex/assert match, **zero LLM**. Reframes the old keystone. | `HELDOUT_GRADER_ENABLED` (default off) | exams graded with `grader_model="heldout:static@v1"` + 0 LLM | — |
| **B5** Cold-boot / dirty-shutdown marker | S | Boot-time detection + log of what was lost. **NOT** full warm recovery. | none | boot log carries explicit `cold_boot` / `dirty_shutdown_detected` | — |
| (keep) **Drift guard** | S | `scripts/doc_lint.py` in the suite — docs↔code parity. Low risk, high leverage; catches the 3-way effector-class drift below. | none | suite fails when a doc and the code disagree | — |
| (keep) **Self-repair live drill** | S | `/drill_repair` through the real `RepairTaskCreator`. Demoted from #1 — but now we have real actions/goals worth repairing. | command-gated (master) | a real `maria_task_queue.jsonl` row dispatched | restart |

**Suggested order:** B3 → B2 (the keystone slice) ‖ B1 ‖ B5 ‖ drift-guard (all
independent, small) → B4 (verification track) → self-repair drill.

### DEFERRED out of Tier 1
- **Full warm crash recovery [L]** (old plank 9) → backlog. 3/4 reviewers: building
  a safety net for state that barely exists ("safety net for an empty trapeze").
  **Revisit gate (reviewers' own):** after ≥1 goal closed via effector **and**
  ≥10 real effector actions logged. B5 covers the cheap 80% (detect + log) without
  the [L] recover-and-resume logic.

---

## 🔧 TIER 2 — DEPTH (after the loop closes)
- **More effector primitives** (3–5 atomic, full K7/K10 audit) — Grok + Gemini's
  "missing earlier slice."
- **Knowledge consolidation / synthesis** — NOW grounded in real action outcomes
  (Q4 4/4: consolidation comes *after* hands, else it's "clustering abstractions").
- **Rollback / quarantine** of bad knowledge.
- **Long-horizon project goals** — now the schema supports sub-goal trees (B3).

## 🚪 TIER 3 — BREADTH (unchanged, deliberately last)
- **Passive workflow traces** (ChatGPT's safe early slice — observe-only
  `workflow_trace.jsonl`, no execution). Candidate to pull to the Tier 2/3 boundary.
- **Read-only skills** (DeepSeek's slice — `semantic_search`, `log_tail`,
  `system_check`, `mutates_state:false`).
- **Active workflow → autonomous skills → vision-grounding → voice** (north-star).

---

## Where Option B FILTERS the reviewers (our constraints they couldn't see)

- **"Grade every exam with an external model"** (DeepSeek/Grok) → conflicts with
  offline-first + NIM 750k/day budget + the no-autonomous-external-CLI rule **and**
  the NIM-timeout failure that *already* mislabeled our 3 "independent" rows. → The
  **held-out bank (zero LLM)** is the offline-correct core; external NIM stays an
  **audit-sample only**, never the daily grader.
- **"Auto-approve self-repair after 30 min with no human veto"** (DeepSeek) →
  directly contradicts our deliberate **STOP-AT-PENDING master gate** (ADR-030). A
  values call (unattended resilience vs human-in-the-loop), **not adopted by
  default** — flagged for Eryk.
- **"Minimal warm-recovery gate now"** (ChatGPT, the one Q6 dissent) → we take the
  cheap read-only half as **B5** (detect + log), without the [L] resume logic.
- **DeepSeek "operator-bus-factor / dead-man's timer"** (Q7) → real, but it's a
  *deployment-resilience* concern, not a learning-loop blocker; parked next to the
  warm-recovery backlog, revisit with B5.

## Honest status corrections — live code vs. our own report

These came out of grounding Option B and should be true regardless of the gate:

1. **The keystone qwen3 grader has graded ZERO exams in vivo.** The 3
   `grader_independent=true` rows used **NIM nemotron** (artifact of the daemon
   running commit `69bbe8f` before the `f788957` restart). Even our "DONE"
   keystone is **not yet OBSERVED** — the held-out bank (B4) is what finally makes
   it externally checkable. (`exam_agent.py`, `teacher_module.py:130-140`,
   `FOUNDATIONS_GAP_2026-05-30.md:97-99`.)
2. **Goal fields `deadline` and `parent_goal_id` already exist but are dead** —
   0 production readers (`goal_model.py:89,93`; `CONTRACTS.md:629` "Brak
   enforcement deadline"). B3 **activates**, it does not add them.
3. **Effector is classified GUARDED, not RESTRICTED** (`action_class.py:46`) —
   3-way drift with `capability_spec.py:90-94` (restricted) and CLAUDE.md/ADR-016
   (RESTRICTED). The drift-guard plank should catch this class of lie.
4. **The structural reason for 0 effector calls:** the planner *never*
   autonomously emits an effector/action plan — only the operator `/do` queue does
   (`planner_core.py:552-559`). B2's autonomous plan-gen seam is the real unlock.

## Source docs
- `docs/incoming/Odpowiedzi na dokument z 31.05.2026.pdf` — the 4 adversarial reviews.
- `docs/proposals/SPEC_heldout_bank.md` — B4 spec (code-grounded).
- `docs/proposals/SPEC_first_effector_primitive.md` — B2 spec (code-grounded).
- `docs/DEVELOPMENT_SEQUENCE.md` — the current SSoT this proposal would replace.
- `docs/audits/FOUNDATIONS_GAP_2026-05-30.md` — the verified gap map.
