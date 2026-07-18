# M.A.R.I.A. - Development Roadmap (Maria 1.0)
> Version: 2.2 | Last updated: 2026-05-16
>
> **Strategic directional map.**
>
> **Hypothesis 1 in the AGI experiment** (a known paradigm scaled toward AGI).
> Hypothesis 2 = Maria 2.0. Meta: `docs/AGI_HYPOTHESES.md`.
> Phase L (AGI Direction) is the far horizon of this path — the AGI-capable
> criteria are described in AGI_HYPOTHESES.md.
>
> **Scope:** this document is the long-term strategy (direction, phase goals,
> AGI vision). It is not a day-to-day status log.

## Overview

M.A.R.I.A. development is divided into phases:

| Phase | Name | Goal | Status |
|------|-------|-----|--------|
| A | Stabilization | Fix bugs, stable runtime | **COMPLETE** (2026-01-27) |
| B | Full Homeostasis | Full autonomy with regulation loops | **COMPLETE** (2026-01-28) |
| C | Consciousness | Self-knowledge, perception, identity | **COMPLETE** (2026-02-27) |
| C.5 | Contracts K1-K4 | Perception, Sandbox, Goals, Evaluation | **COMPLETE** (2026-03-01) |
| C.6 | Cognitive Core K5-K13 | Planner, World Model, Autonomy, Creative | **COMPLETE** (2026-03-25) |
| C.7 | Infrastructure | Telegram, Semantic Memory, OpenClaw, Web UI v2 | **COMPLETE** (2026-03-27) |
| C.8 | Stabilization Roadmap | Tracing, Memory, Budgets, Safety (6 phases) | **COMPLETE** (2026-03-29) |
| F | Multi-Source Learning | Cross-LLM validation, dispute tracking | **COMPLETE** (2026-03-29) |
| G | Critic Agent + Learning Upgrade | Knowledge quality gate, bulletin, auditor, expert bridge | **COMPLETE** (2026-04-01) |
| H | V3 Orchestrator | UnifiedLauncher, Task Pipeline, ProductShell (15 modules) | **COMPLETE** (2026-04-05) |
| I | Vision + Operator UX | Camera, LLaVA, reminders, user profile, grounded chat | **COMPLETE** (2026-04-10) |
| J | API Brain Test | glm-5.1 multi-day validation (MIXED verdict) | **COMPLETE** (2026-05-16) |
| K | Ship of Theseus | Plank-by-plank evolution (IntentRouter, Planner v2, World Model symbolic) | **IN PROGRESS** (re-target) |
| M | Procedural Memory | Skills as artifact (Hermes-inspired), lifecycle DRAFT→SANDBOX→PRODUCTION | **IN PROGRESS** (Phase 1+2a done 2026-05-15) |
| D | Vision Phase 2+ | IP camera RTSP, face recognition, OCR | DEFERRED (awaiting hardware) |
| E | Smart Home | IoT integration, mobile body | DEFERRED (awaiting hardware) |
| L | AGI Direction | Symbolic world model, meta-learning, self-modification, embodiment | **LONG-HORIZON** (local-only) |

---

## Phase A: STABILIZATION

### Goal
Fix all critical bugs and reach a system that:
- Starts without errors
- Runs stably through a basic learning session
- Has consistent file paths
- Handles Polish characters correctly

**STATUS: COMPLETE** (2026-01-27)

---

## Phase B: FULL HOMEOSTASIS

### Goal
The system runs autonomously for long periods (8h+) with automatic regulation.

**STATUS: COMPLETE** (2026-01-28)

---

## Phase C: CONSCIOUSNESS / OPTIMIZATION

### Goal
Extend with consciousness, personality, time perception, and autonomous learning.

- [x] Introspection module (code self-knowledge, READ-ONLY AST)
- [x] TimeAwareness (time perception - day, hour, part of day)
- [x] Self-model in semantic_graph (personality) - TraitEvolver + SelfModelBuilder
- [x] Conversation memory with condensation - ConversationMemory
- [x] Identity continuity (birth date, uptime) - IdentityStore
- [x] SLEEP with "dreams" - SleepProcessor + DreamGenerator
- [x] Teacher Agent with an autonomous trigger in homeostasis
- [x] NIM API + Token Budget + LLM Router (ADR-008)

**STATUS: COMPLETE** (2026-02-27, 668 tests)

---

## Phase C.5: CONTRACTS K1-K4 (Layer 1)

- [x] **K1 Unified Perception** - PerceptionEvent, Buffer, 6 adapters, Tick Aggregator (ADR-009)
- [x] **K2 Sandbox/Production** - SandboxManager, transaction log, startup recovery (ADR-010)
- [x] **K3 Goal System** - 4 goal types, 6 statuses, PROPOSED flow, audit trail (ADR-011)
- [x] **K4 Evaluation** - READ-ONLY observer, 5 metrics, threshold recommendations (ADR-012)

**STATUS: COMPLETE** (2026-03-01, 941 tests)

---

## Phase C.6: COGNITIVE CORE K5-K13 (Layers 2-3)

### Layer 2: Control loop (K5-K10, 2026-03-01 - 2026-03-20)
- [x] **K5 Planner** - ReAct loop, PlannerGuard, GoalSelector, ActionExecutor (ADR-013)
- [x] **K5.1 Topic-Aware Learning** - KnowledgeAnalyzer topic map, auto-goal creation
- [x] **K6 World Model** - Belief system, BeliefStore (JSONL, cap 2000), BeliefBuilder
- [x] **K7 Autonomy Policy** - FREE/GUARDED/RESTRICTED/FORBIDDEN, rate limiter, PolicyEngine
- [x] **K8 Deliberation** - Multi-step strategies, 3 templates, IntentTracker
- [x] **K9 Meta-Cognition** - ReflectionStore, ConfidenceTracker, pattern detection, needs_human()
- [x] **K10 Action Safety** - SafetyMode(3), AuditLog, EffectValidator, safe-by-default

### Layer 3: Extensions (K11-K13, 2026-03-21 - 2026-03-25)
- [x] **K11 Experiment System** - ProposalEngine, ParameterRegistry, runner, ADOPT/REJECT
- [x] **K12 Self-Analysis Phase 2** - StateCollector, ExternalAnalyzer (NIM cascade), Web UI /analysis
- [x] **K13 Creative Module Phase 2** - TensionDetector, MetaGoalEngine, ReframeEngine (NIM), TokenBudget RPM

**STATUS: COMPLETE** (2026-03-25, 1876 tests - cognitive core)

---

## Phase C.7: INFRASTRUCTURE

- [x] **Model Registry v2** - 7 models, heavy mutex, rule-based triage (ADR-015)
- [x] **ModelScheduler** - load/unload via Ollama, RAM guard, idle timeout
- [x] **OpenClaw Effector** - subprocess client, gateway+node, qwen2.5:3b (ADR-016)
- [x] **Web UI v2** - Metaoperator Panel, 8 panels, design system (ADR-017)
- [x] **Web Content Fetcher** - Wikipedia PL + RSS, TopicSuggester, FetchRegistry
- [x] **Telegram Bridge (ClawBot)** - 20+ commands, 7 alert types, poll every 30s
- [x] **Semantic Memory** - nomic-embed-text (768-dim), VectorStore, auto-indexer (ADR-021)
- [x] **Meta-goal Priority Escalation** - tension streaks, PROPOSED displacement
- [x] **Architecture Map** - force-directed graph, pipeline view, data flow (Web UI)
- [x] **Storage Manager** - LogArchiver, DailySummary, 6TB disk

**STATUS: COMPLETE** (2026-03-27, 2081 tests)

---

## Phase C.8: STABILIZATION ROADMAP (6 phases)

- [x] **Phase 1: Decision Traceability** - episode_id, DecisionTrace, TraceStore, /trace (ADR-022)
- [x] **Phase 2: Memory Consistency** - MemoryQuery API, staleness fixes, grounding (ADR-023)
- [x] **Phase 3: Scheduler Hardening** - call_with_timeout(), EpisodeBudget, degradation routing (ADR-024)
- [x] **Phase 4: Autonomy Governance** - cross-metric validation, guard metrics, promotion audit (ADR-025)
- [x] **Phase 5: Effector Safety Envelope** - 5-level authority, ApprovalQueue, ToolBudgetManager (ADR-026)
- [x] **Phase 6: Readiness Review** - 100-cycle marathon, authority drills, 15-point checklist

All gates passed: Gate A (tracing), Gate B (memory), Gate C (budgets), Gate D (governance), Gate E (readiness).

**STATUS: COMPLETE** (2026-03-29, 2392 tests)

---

## Phase F: MULTI-SOURCE LEARNING

Maria learns from multiple sources and compares answers from different LLMs.

- [x] **CrossValidator** - compare Ollama/NIM answers
- [x] **ConfidenceScorer** - rule-based confidence scoring (Jaccard, 3 dimensions)
- [x] **DisputeLog** - JSONL divergence log (bounded 200)
- [x] **Planner trigger** - _maybe_validate() every 6h
- [x] **K7 GUARDED + K10** - rate 5/h, SafetyProfile
- [x] **Belief confidence update** - after validation OBSERVATION → FACT / HYPOTHESIS
- [x] **Web UI /validation + Telegram /validate**
- [x] **Belief Store v2** - evidence tracking, compaction, smart pruning, confidence decay, dedup

**STATUS: COMPLETE** (2026-03-29, 2491 tests)

---

## Phase G: CRITIC AGENT + LEARNING UPGRADE

Knowledge quality gate + bulletin board + auditor + expert bridge.

### Critic Agent (ADR-028)
- [x] **7 analysis dimensions** - contradiction, overconfident, underconfident, shallow, disputes, coverage, stale
- [x] **READ-ONLY critic** - zero LLM, zero side effects
- [x] **CritiqueApplier** - PROPOSED goals, not automatic repair
- [x] **Planner trigger** - 8h/post_validate/post_maintenance
- [x] **REPL /critique + Web UI /critique** - 3 tabs, 4 API endpoints
- [x] **Auto-confirm** - low-risk goals from creative/critic/self_analysis skip /approve

### Learning Upgrade (Phase 1-5)
- [x] **Phase 1: BulletinStore** - bulletin board, 5 EntryTypes, dedup, /board
- [x] **Phase 2: KnowledgeAuditor** - checks MemoryQuery, beliefs, critic, exams → AuditReport (7 gap types)
- [x] **Phase 3: GapPlanner** - decisions: ASK_EXPERT (with context_prompt), REVIEW, RUN_EXAM, DECOMPOSE, WAIT_HUMAN
- [x] **Phase 4: ExpertBridge** - audit-aware queries, targeted prompts, cascade LLM
- [x] **Phase 5: Full wiring** - planner, CapabilityRouter, NEED_MATERIAL → resolved

### Capability/Task Router (ADR-027)
- [x] **CapabilityRouter** - registry-based dispatch replacing 13-way if/elif
- [x] **14 capabilities** with CapabilitySpec (frozen dataclass)
- [x] **Dual-path** - router dispatch when available, legacy fallback

**STATUS: COMPLETE** (2026-04-01, 2730 tests)

---

## Phase H: V3 ORCHESTRATOR

Unified product layer - single entry point, onboarding, task pipeline, capability discovery.

### 5-Phase Build
- [x] **Phase A (Foundation)** - Modules 1-3: UnifiedLauncher (maria.py), OnboardingFlow, UserFacingSelfModel
- [x] **Phase B (Task Pipeline)** - Modules 4-6: TaskOrchestrator, TaskDecomposer, ExecutionPlanBuilder
- [x] **Phase C (Practical Intelligence)** - Modules 7-9: CostEstimator, TimeEstimator, FreeVsPaidPlanner
- [x] **Phase D (Execution Bridge)** - Modules 10-13: ExecutionRouter, ToolRegistry, ProgressTracker, LimitationReporter
- [x] **Phase E (Product Hardening)** - Modules 14-15: ProductShell + V3Module REPL /v3

### Deployment
- [x] **maria.py full mode** - daemon + Web UI in a single process under systemd
- [x] **maria-ui.service disabled** - one startup path

**STATUS: COMPLETE** (2026-04-05, 3317 tests, 15 modules)

---

## Phase I: OPERATOR UX + VISION WIRING

### Vision
- [x] **Vision Phase 1-4** - sensor (Innomaker U20CAM), preprocessing, motion+scene, cortex (297 tests)
- [x] **Homeostasis tick Phase 8.5** - vision tick, REPL /vision, Web UI /api/vision/*
- [x] **LLaVA on-demand** - describe_scene_llava (30s timeout)
- [x] **Grounded chat** - "what do you see?" → Ollama + EvidenceCollector + LLaVA

### Operator UX
- [x] **Master Prompt** - single source for all LLM paths (`agent_core/llm/master_prompt.py`)
- [x] **Reminders & Todos** - time-triggered notifications, PL+EN time parser, tick loop Phase 12
- [x] **UserProfile** - auto-learn from chat + ConversationMemory, Telegram /profile, Web UI /api/user/profile
- [x] **Task Pipeline Web UI** - /tasks page: submit, list, detail, PDF download
- [x] **PDF Auto-Export** - every Claude/Codex result sent as a PDF (fpdf2 + DejaVu, Polish characters)
- [x] **Telegram file upload** - docs/incoming/ + caption as command
- [x] **External LLM** - Claude Code CLI (3/h, 15/day), Codex CLI (10/h)

**STATUS: COMPLETE** (2026-04-10, ~4200 tests)

---

## Phase J: API BRAIN TEST (COMPLETE)

Validating the hypothesis: does Maria's architecture scale to a stronger engine?

### Verdict: MIXED

Summary:
- **The engine helps in measurable areas** — latency -36% (nemotron-49b vs glm-5.1), glm-5.1 stability 0% errors across 2222 calls, K13 quality (subjectively higher)
- **The engine does not eliminate structural gaps** — exam parser bug (100% FAIL), confabulation in the chat path (3 generations), planner stuck-loops, user↔maria goal-creation asymmetry, NIM latency 50-90s (3× slower than Ollama locally)
- **The architecture does not break under a stronger engine** — the model swap was a first-class operation (glm-5.1 → nemotron-49b 2026-05-10 after a server outage), and routing through `master_prompt.py` + `LLMManager` absorbed the differences → **validation of Maria's design**

### Conclusions for the LLM strategy
- **Nemotron-49b primary** in `NIM_PRIMARY_ROLES`. Daily budget 750k / monthly 15M
- **Ollama llama3.1:8b** stays as the local executor + fallback (mass operations benefit from local speed)
- **Hybrid LLM strategy** confirmed — local primary, NIM as mentor/auditor for complex reasoning
- **Anti-goal holds:** no crutch on paid models. The NIM outage on 2026-05-10 showed the risk

### Implications for Phase K
- All 4 Phase K planks **retain their rationale** (structural gaps are independent of the engine)
- M15 Plank #3: **Symbolic World Model** (verdict decision — the engine does not reduce LLM dependency, so a symbolic World Model is a necessity)
- M13/M14 re-targeted (see Milestones below)

**STATUS: COMPLETE** (deploy 2026-04-18, verdict 2026-05-16)

---

## Phase K: SHIP OF THESEUS (PLANK EVOLUTION)

Gradually replacing the internals while the engine keeps running — like changes in the Linux kernel. Each redesign is a separate **plank**. One plank at a time.

> **Reality check 2026-05-16:** Phase K proceeded **in parallel tracks rather than a strict sequence**. Bridge #1 (BulletinEscalator), Bridge #2 (H1+H2), B0 (5/5 surprise modules + NIM switch), the 24h autonomy test, the 5-architectural-bugs postmortem, and Skills Phase 1+2a all shipped, but none of the M13/M14/M15 sequence has started.

### Cardinal principle
**Maria's soul is never interrupted.** `beliefs.jsonl`, `identity.json`, `decision_traces.jsonl`, `conversation_memory.jsonl`, `knowledge_index.jsonl`, `semantic_vectors.jsonl` — these files are sacred. Every architecture change must read from and write to the same sources, even if it transforms them internally.

### Rules for each plank
1. **Design doc** (1-2 days) — a design note with tradeoffs
2. **Branch + build alongside** (3-5 days) — feature flag; the new module does NOT replace the old one
3. **Tests** (in parallel) — new tests; the existing ones must still pass
4. **Parallel run** (3-7 days) — flag off = old, flag on = new
5. **Cutover** (1 day) — flag default on, 24h observation
6. **Legacy removal** (1-2 days) — only once the cutover is stable

### Sequential planks (re-target)

#### Plank #1: IntentRouter
- **Problem:** `/do weather in Berlin` → OpenClaw qwen2.5:3b → 10min timeout. It should be WeatherSensor → 1s.
- **Feature flag:** `INTENT_ROUTER_ENABLED`
- **Re-target:** M13 ~2026-05-29

#### Plank #2: Planner v2 — skeleton
- **Problem:** Rule-based, stuck-in-evaluate-loop (mg-a0128 628× evaluate over 14h), no LLM guidance for novel situations
- **Design:** `docs/PLANNER_V2_DESIGN.md`
- **Feature flag:** `PLANNER_V2_ENABLED`
- **Re-target:** M14 ~2026-06-12

#### Plank #3: Symbolic World Model (Phase J verdict decision)
- **Decision:** Phase J verdict MIXED → we need reasoning without an LLM in the loop for routine work. K6 JSONL → structured knowledge graph + JSONL archive.
- **Re-target:** M15 ~2026-06-26

#### Plank #4: Planner v2 cutover (full)
- After the skeleton from #2 + parallel-run observation, we switch traffic over.

### Planks delivered outside the sequence (Phase K reality)

These planks are DONE and live in the runtime:

- **Bridge #1 BulletinEscalator** (LIVE 2026-05-06) — bulletin alerts → goal escalation
- **Bridge #2 H1+H2** (2026-05-09) — h1 dead-code revival + h2 stale_goals_aging
- **B0 closure** (2026-05-10) — 5/5 surprise modules (ActionBaseline + SurpriseScorer + EntryType.SURPRISE)
- **NIM switch** glm-5.1 → nemotron-49b (2026-05-10) — response to a server outage
- **24h autonomy test** (2026-05-13/14) — verdict 4/5, plank-by-plank revert, 0 effector calls
- **5-architectural-bugs postmortem** (2026-05-14/15) — 4/5 closed: exam parser, work_context, NLU+confabulation, conversation_context wired (verify pending), chat persistence

### Candidates for further planks

1. K12 self-modification (read → write with K10 gate, rewrite ADR-006)
2. Learning pipeline — structured ingestion
3. Model routing — dynamic based on task complexity
4. Confabulation Layer 1 strong-form prompt patch
5. Planner stuck-loop escape condition (quick fix before Plank #2 cutover)

**STATUS: IN PROGRESS** (sequence re-target + parallel planks reality)

---

## Phase M: PROCEDURAL MEMORY (Skills as artifact)

A new cognitive layer: procedural memory that fills the gap between goals (the objective) and traces (what happened). Previously Maria accumulated knowledge (semantic) and traces (episodes) but could not **abstract skills** from repeatable workflows. Phase 1+2a was implemented on 2026-05-15 (Hermes-inspired, Nous Research MIT Feb 2026).

### Philosophy of the port from Hermes Agent
- **WE TAKE:** the SKILL.md format (YAML+sections), L0/L1/L2 progressive disclosure, lifecycle stages, agentskills.io compatibility
- **WE REJECT:** autonomous skill_manage create (conflicts with ADR-010/011), cloud-first model routing (conflicts with ADR-008), GEPA cloud-heavy optimization
- **WE KEEP:** Maria's sandbox-first promote() with a human gate on every status transition (DRAFT → SANDBOX → PRODUCTION → ARCHIVED, every step requires an explicit `approved_by=` parameter)

### Ties into Phase L point 3
Phase L identifies 5 AGI gaps (CANNOT). Point 3: "no skill creation". Phase M is the first attempt to close that gap — structural extraction of skills from decision traces, sandbox testing, and promotion to production with a human gate.

### Phases

#### Phase 1: Core data plane (DONE 2026-05-15)
- `agent_core/skills/` — skill_model, schema, store, manager
- SKILL.md format with an L0/L1/L2 split
- Lifecycle gates: create_draft / patch / promote / demote / archive
- Persistence: `meta_data/skills/<id>/SKILL.md` (ADR-001 single source of truth)
- 61 unit tests PASS

#### Phase 2a: Template-based extractor (DONE 2026-05-15)
- `agent_core/teacher/trace_analyzer.py` — TraceRecord projection, GoalPattern + ActionPattern
- `agent_core/teacher/skill_extractor.py` — SkillCandidate, template builders, dedup
- Real-data smoke test: **24 DRAFT skills generated** from 2940 Maria decision_traces
- All DRAFTs await Eryk's review — Maria's sandbox-first governance holds
- 33 unit tests PASS

#### Phase 2b: NIM body enrichment (PLANNED)
- Nemotron-49b prompt for rich SKILL.md body generation
- Templates as fallback
- Semantic dedup (cluster "Break the stagnation" variants)

#### Phase 2c: Tick wiring (PLANNED)
- SkillExtractor in the homeostasis tick (background scan every X hours)
- Telegram notify: new DRAFT skill ready for review
- Audit callback → bulletin entry

#### Phase 3: Planner integration (PLANNED)
- Planner reads the L0 catalog each tick (compact)
- L1 on-demand when the planner decides to use a skill
- Sandbox K2 integration (execute SANDBOX skills in a sandbox session)
- Formal ADR-030 entry in ARCHITECTURE.md

### Resolved decisions (Eryk gate 2026-05-15, applied in commit `3544780`)

5 design questions closed:

1. **N threshold for DRAFT extraction:** 5 successful in 30d (keeping the default).
2. **Sandbox success rate for promote:** 5/7 with zero critical failures + explicit Eryk approval. Critical/safety-affecting skills: 3/3 with zero failures + manual log review.
3. **Stale archive threshold:** 90d for PRODUCTION; 30d for SANDBOX/DRAFT that were never used.
4. **DRAFT creator:** teacher + manual for now. K12 may propose later — through the same DRAFT gate.
5. **SKILL.md language:** EN for frontmatter/name/tags (interop with agentskills.io); a bilingual body is allowed; `description` must be EN ≤140 characters.

**Per-batch review of the 24 DRAFTs applied in commit `3544780`:** 1 canonical (`meta-goal-creative-stagnation-breaker`, MERGE of 17 stagnation/reactivation variants) + 7 promoted DRAFT→SANDBOX (5 action patterns + 2 goal patterns) + 17 archived (duplicates + 1 noisy NOOP-optimization). **No skill is in production** — DRAFT→SANDBOX→PRODUCTION requires a separate Eryk gate after sandbox evidence (the 5/7 or 3/3 success criteria defined above).

### Design doc
`docs/SKILLS_DESIGN.md` — architecture, schema, integration plan, ADR-030 proposal (lines 204-210: resolved questions).

**STATUS: IN PROGRESS** (Phase 1+2a done 2026-05-15; Phase 2b/2c/3 sequential)

---

## Phase L: AGI DIRECTION (LONG-HORIZON, LOCAL-ONLY)

A General Intelligence architecture (not Artificial) — not one super-mind, but a team of specialists under a wise chief with narrative continuity. These items are developed **locally on the mini PC** and **not pushed to GitHub** until they pass real tests.

### 5 gaps to close (CANNOT)
1. **LLM-dependent reasoning** - without Ollama/NIM Maria is a dead daemon. Borrowed reason.
2. **No transfer** - she learns formal logic but won't apply it to code. Every domain separately.
3. **No skill creation** - she accumulates knowledge, yes; invents new actions, no.
4. **K6 READ-ONLY** (ADR-006) - safe but limiting.
5. **No embodiment** - OpenClaw is a stand-in, not a body.

### 4 additions (PUSHERS)
1. **Symbolic world model** - reasoning without an LLM in the loop (plank #3 candidate)
2. **Meta-learning** - learning how to learn, not just what
3. **Code self-modification** - K6 read → write with audit + rollback, K10 as a hard gate (rewrite ADR-006)
4. **A real physical effector** - camera + limb, not just /dev/video0

### Discipline
- Local-only on the mini PC until verified in production
- GitHub = public showcase (ADR-029), not a live mirror of risky research
- Self-modification comes **last** (the most dangerous)

**STATUS: LONG-HORIZON** (items enter Phase K as they mature)

---

## Phase D: VISION PHASE 2+ (DEFERRED)

Phase 1-4 (sensor, preprocessing, modules, cortex) - DONE in Phase I.

### Phase 2+ (awaiting hardware)
Details: `docs/VISION_SPEC.md`

- [ ] IP camera RTSP (Tapo C200) - purchase on hold (WiFi-only cameras)
- [ ] OCR module
- [ ] Face recognition
- [ ] VisionModeManager attention control

### Hardware
- [ ] Tapo C200 camera with RTSP

---

## Phase E: SMART HOME (DEFERRED)

Awaiting IoT hardware (Shelly/Tasmota). Details: `docs/SMART_HOME_SPEC.md`

- [ ] E1: Device Layer (SmartDevice interface, ShellyDevice, TasmotaDevice)
- [ ] E2: Automation (AutomationEngine, rules, Vision integration)
- [ ] E3: Mobile Body (IP Webcam, Termux, TTS, GPS)
- [ ] E4: Security (VLAN/Guest, audit log, confirmations)

### Hardware
- [ ] Shelly Plug S x3 (~200 PLN)
- [ ] Used Android phone (~200 PLN)

---

## Specialized agents

### Delivered
| Agent | Role | Model | Status |
|-------|------|-------|--------|
| **Teacher** | Plans learning, priorities P1-P6, spaced repetition | NIM / Ollama | **DONE** |
| **Examiner** | Creates questions, grades answers | Ollama / NIM | **DONE** |
| **Creative** | Tension detection, meta-goals, reframe | NIM + rule-based | **DONE** (K13) |
| **Self-Analyst** | Log analysis, recommendations | NIM cascade | **DONE** (K12) |
| **Critic** | 7 dimensions of knowledge-quality analysis | Rule-based (zero LLM) | **DONE** (Phase G) |
| **ExpertBridge** | Audit-aware expert queries, cascade LLM | Ollama/NIM | **DONE** (Phase G) |

### Planned
| Agent | Role | Model | Status |
|-------|------|-------|--------|
| **Code Agent** | Writes/modifies code in the sandbox | qwen2.5-coder:7b | PLANNED (Phase L, plank #3 candidate) |

---

## Milestones

| Milestone | Description | Status |
|-----------|------|--------|
| M1 | Phase A - stable runtime | **DONE** (2026-01-27) |
| M2 | Phase B - full homeostasis | **DONE** (2026-01-28) |
| M3 | Phase C - consciousness + teacher | **DONE** (2026-02-27) |
| M3.5 | Linux migration + deploy on Mini PC | **DONE** (2026-02-22) |
| M3.6 | NIM API + Token Budget + LLM Router | **DONE** (2026-02-23) |
| M4 | Contracts K1-K4 | **DONE** (2026-03-01) |
| M5 | Cognitive Core K5-K13 complete | **DONE** (2026-03-25) |
| M6 | Infrastructure (Telegram, Semantic Memory, OpenClaw) | **DONE** (2026-03-27) |
| M7 | Stabilization Roadmap (6 phases, 5 gates) | **DONE** (2026-03-29) |
| M8 | Phase F - multi-source learning | **DONE** (2026-03-29) |
| M9 | Phase G - Critic + Learning Upgrade | **DONE** (2026-04-01) |
| M10 | Phase H - V3 Orchestrator (15 modules) | **DONE** (2026-04-05) |
| M11 | Phase I - Vision + Operator UX | **DONE** (2026-04-10) |
| M12 | Phase J verdict - API brain validation | **DONE** (2026-05-16, MIXED verdict) |
| M13 | Phase K - IntentRouter cutover (plank #1) | RE-TARGET (~2026-05-29) |
| M14 | Phase K - Planner v2 cutover (plank #2) | RE-TARGET (~2026-06-12) |
| M15 | Phase K - plank #3 (Symbolic World Model — Phase J verdict decision) | RE-TARGET (~2026-06-26) |
| M16 | Phase M - Skills Phase 2b (NIM body enrichment) | PLANNED |
| M17 | Phase M - Skills Phase 3 (planner integration) | PLANNED |
| M18 | Phase D - vision Phase 2+ | DEFERRED (awaiting hardware) |
| M19 | Phase E - smart home | DEFERRED (awaiting hardware) |

**Reality milestones outside the original sequence** (parallel tracks):

| Reality Milestone | Description | Date |
|-------------------|------|------|
| Bridge #1 BulletinEscalator LIVE | Bulletin alerts → goal escalation | **DONE** (2026-05-06) |
| Bridge #2 H1+H2 | Dead-code fix + stale_goals_aging | **DONE** (2026-05-09) |
| B0 closure 5/5 | Surprise modules + NIM switch glm-5.1→nemotron-49b | **DONE** (2026-05-10) |
| 24h autonomy test | First real-world maturity check (verdict 4/5) | **DONE** (2026-05-13/14) |
| Postmortem 4/5 bugs closed | exam parser + work_context + NLU/confabulation + chat persistence | **DONE** (2026-05-15) |
| Phase M Phase 1+2a (Skills) | Procedural memory core + extractor (24 DRAFTs) | **DONE** (2026-05-15) |

---

## Risks and dependencies

| Risk | Probability | Impact | Mitigation |
|--------|-------------------|-------|-----------|
| OOM crash (infinite loop) | Low | High | intelligent_chunk_text fix (2026-03-18), execution budgets (Phase 3) |
| Ollama timeout | Low | Medium | call_with_timeout (120-180s), degradation routing |
| NIM API expiry (Aug 2026) | Medium | Medium | Auto-fallback to Ollama, budget monitoring |
| glm-5.1 timeout (thinking model) | Medium | Medium | NIM_TIMEOUT=120, fallback to Ollama |
| **BeliefStore leak (1.1GB tombstones, 9h freeze)** | Low (fixed) | High | **Startup compaction + systemd MemoryMax=20G, audit cron every 4d** |
| **Confidence feedback loop (floor at 0.01)** | Low (fixed) | Medium | **Signal separation (commit e1f753d)** |
| No IoT hardware/camera | Certain | Low | D/E deferred (ADR-014), the brain is ready |
| Guard metric degradation | Low | Medium | Cross-metric validation (Phase 4, ADR-025) |
| Effector cascade failure | Low | High | Anti-cascade breaker, approval queue (Phase 5, ADR-026) |
| **Claude CLI subscription ban** | Low (fixed) | High | **CLAUDE_CLI_AUTONOMOUS=false default, operator-triggered only (d8bbf30)** |
| Second-system syndrome (rewrite) | Low (avoided) | High | **Ship of Theseus instead of a rewrite - Phase K** |

---

## Architecture decisions (ADR)

| ADR | Title | Phase |
|-----|-------|------|
| ADR-001 | JSONL as source of truth | A |
| ADR-005 | No emoji in code | A |
| ADR-006 | Introspection READ-ONLY | C |
| ADR-008 | NIM for learning, Ollama for chat | C |
| ADR-009 | Tick Aggregator instead of Event Bus | C.5 |
| ADR-010 | Sandbox-first learning | C.5 |
| ADR-011 | Goals as data | C.5 |
| ADR-012 | Evaluation READ-ONLY | C.5 |
| ADR-013 | Planner v1 rule-based (zero LLM) | C.6 |
| ADR-014 | Brain first, then senses | C.6 |
| ADR-015 | Multi-organ model stack | C.7 |
| ADR-016 | OpenClaw as effector | C.7 |
| ADR-017 | Web UI v2 base template | C.7 |
| ADR-018 | Markdown learning fallback | C.7 |
| ADR-019 | OpenClaw lightweight check | C.7 |
| ADR-020 | K12 Self-Analysis | C.6 |
| ADR-021 | Semantic Memory via embeddings | C.7 |
| ADR-022 | Episode-based tracing | C.8 |
| ADR-023 | Unified memory query | C.8 |
| ADR-024 | Execution budgets | C.8 |
| ADR-025 | Cross-metric validation | C.8 |
| ADR-026 | Effector safety envelope | C.8 |
| ADR-027 | Capability router (registry dispatch) | G |
| ADR-028 | Critic = coherence/calibration auditor | G |
| ADR-029 | GitHub = public showcase, not a live mirror | - |
| ADR-030 | Skills as artifact (Hermes-inspired procedural memory, sandbox-first promote) | M |

---

*This is a living document — update it as plans change.*
