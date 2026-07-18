# M.A.R.I.A. - Digital Human Roadmap v2.0

> Architectural roadmap: from cognitive AI to a personal digital human.
> Author: Eryk (vision) + Claude (architecture). Date: 2026-04-12 (v1.1),
> status pass 2026-07-06 (v2.0 -- vision unchanged, statuses updated to reality).
>
> **This file = VISION** (what we build and why); `docs/SYSTEM_STATUS.md` = STATE
> (what's alive). When they diverge, trust STATE, not this roadmap.

## A. Executive Vision

Maria is not just another AI assistant. She is a **persistent digital being** that lives on the operator's hardware, knows them, understands the context of their life, and acts on their behalf in the digital world - with full control and auditability.

The difference between a chatbot and a digital human: a chatbot **responds**. A digital human **lives, observes, plans, acts, and reports** - even when no one is talking to it.

Maria already does part of this (24/7 homeostasis, autonomous learning, proactive contact). The roadmap leads from "cognitive AI that learns" to "a digital human that is useful in the operator's daily life".

## B. Architectural Definition of "Digital Human"

A digital human in the M.A.R.I.A. context is a system that meets **6 conditions simultaneously**:

| Condition | Test | Maria today (2026-07-06) |
|---------|------|------------|
| **Continuity** | Runs 24/7, remembers yesterday and a month from now | YES (24/7 homeostasis, JSONL, warm recovery; NOTE: backup restore NEVER tested -- see F.5) |
| **Perception** | Knows what is happening in the operator's world | LARGELY (Telegram, Vision: MOG2 motion + VisionMemory + PL captions, weather+holidays with salience in the morning brief; STILL no calendar/email) |
| **Reasoning** | Plans, reflects, learns from mistakes | YES (K5-K13 + Super-META E0-E4 armed) |
| **Action** | Performs real tasks in the digital world | PARTIAL, GROWING (FS_WRITE live 06-21, first real write+undo on live OpenClaw 06-24, outbox propose armed, /wyslij files; workflow engine complete but NEVER run) |
| **Relationship** | Knows the operator deeply, builds trust | PARTIAL (OperatorModel SSoT 05-30, RhythmDetector, conversation memory Phase 20; ActiveLearner built-dormant, RelationshipTracker does not exist) |
| **Self-awareness** | Knows what it can do, what it can't, what it costs | LARGELY (self_perception Phase 18 OBSERVED, CapabilityManifest + honesty tail in chat, SelfContext; economics D.7 = the only unbuilt piece) |

**Main gap (update 2026-07-06):** the slogan "Maria thinks a lot, does little"
no longer describes reality -- the hand is alive, and the operator's first project
closed 3/3 (07-05). Honest gaps today: (1) CONNECTING the ready machines into a
delivery (workflow never run, /wf approve without production callers),
(2) trust computed on a blind track record (Phase 7 wired-dormant, incident
recorder unplugged), (3) economics D.7 untouched, (4) calendar+mail in
perception, (5) Relationship without RelationshipTracker.

## C. Development Phases

| # | Name | Goal | Status |
|---|-------|-----|--------|
| 1 | **Operator Understanding** | Maria truly understands the operator | DONE |
| 2 | **Self-Model Maturity** | Maria honestly knows who she is and what she can do | DONE |
| 3 | **Operational Perception** | Maria sees the whole operational world | DONE |
| 4 | **Digital Hands** | Maria can DO something | DONE |
| 5 | **Workflow Orchestration** | Maria runs complex processes | DONE |
| 6 | **Environment Adaptation** | Maria adapts to context | DONE |
| 7 | **Trust & Autonomy Graduation** | Maria earns autonomy | BUILT, WIRED-dormant (K20 code since 04-12: TrustScorer/IncidentMemory/AutoPromotion, tick Phase 16 computes trust live ~0.80, /trust works; AUTO_PROMOTION_ENABLED OFF, incident recorder UNPLUGGED on the live path -- arming only after an honest track record, see G) |

### Six conceptual layers (mapping to phases):

1. **Identity / Being** -> Phase 2 (Self-Model Maturity) + cross-cutting (MasterPrompt)
2. **Perception** -> Phase 3 (Operational Perception) + existing K1
3. **Mind** -> Existing K5-K13 cognitive core
4. **Digital Body / Action Layer** -> Phase 4-5 (Digital Hands + Workflow)
5. **Relationship Layer** -> Phase 1 (Operator Understanding) + Phase 7 (Trust)
6. **Environment Layer** -> Phase 6 (Environment Adaptation)

---

### Consolidating subcategory: Super-META (Situational Awareness)  [E0-E4 DONE: E0/E1/E2 2026-06-26, E3/E4 2026-06-27; flags ARMED confirmed 07-04]

**What it is:** NOT a new Phase or a new organ -- a CROSS-CUTTING layer that WELDS the already-built
blocks of Phases 1+2+3 into a single "situational context" consulted by every organ. Not to be confused
with the META goal (`goal-meta-learn`): the META goal = the learning MISSION; Super-META = the layer of
SELF-AND-SITUATION KNOWLEDGE (a foreman who knows what each organ saw/knows).

**Why now:** the organs are already aware and multi-LLM (vision=LLaVA->dracarys, conversation=Ollama/
NIM, planner=qwen3, learning=dracarys 70b). But they do NOT share a single "what do I now know about the
situation". The pieces exist, scattered: `operator_model` (with whom), `self_perception` (what I can do),
`awareness/context_builder` (learning/knowledge/system). Missing: memory of vision (the description
disappears after sending) + consolidation into one place + making the organs HEAR each other.

**End result:** Maria as ONE coherent person. "what did you see?" -> she remembers. You talk to her ->
she knows with whom and what she saw a moment ago. Vision, conversation, planner read the same context.

**Stages (construction: foundation -> welds -> tap; each flag-gated observe->cutover, commits+tests):**
- **E0 Foundation - SelfContext (aggregator): [DONE 2026-06-26]** a read-only object consolidating WHAT
  ALREADY EXISTS -- self_perception + operator_model + context_builder + META mission state. Zero new data,
  consolidation only. `agent_core/awareness/self_context.py` (`SelfContext.build()`/`format_for_telegram`),
  `ctx.self_context`, command `/selfcontext`. EVERY source in try/except (one organ's failure does not break
  the whole). 9 tests. Visible: `/selfcontext` shows the whole situation in one place.
- **E1 Vision memory (1st visible weld): [DONE 2026-06-26]** vision records what it saw (last N
  descriptions + time). `agent_core/vision/vision_memory.py` (ring buffer N=10, thread-safe, persisted to
  `meta_data/vision_memory.json`), written in `VisionAdvisor._describe_and_notify` (after PL translation),
  `ctx.vision_memory`, `vision` slot in SelfContext, commands `/lastseen` + `/cowidzialas`. 14 tests.
  Visible: "what did you last see?" -> a real answer from memory.
- **E2 Conversation consults SelfContext: [DONE 2026-06-26, `7e3a2d4`, flag `SELF_CONTEXT_CHAT_ENABLED`=true]**
  the chat prompt tail pulls operator_model + last vision description + capabilities. Visible: Maria knows
  who she is talking to and what she saw ("I saw motion 5 min ago -- was that you?").
- **E3 Organs hear each other (cross-organ): [DONE 2026-06-27, `378a4ed`+`bfd99d1`, flag `VISION_SUPPRESS_WHEN_PRESENT`=true]**
  vision skips the ping when it knows from chat that the operator is present; the planner publishes focus to SelfContext.
- **E4 Super-META: the awareness loop: [DONE 2026-06-27, `8b8408f`, flag `PROACTIVE_SITUATIONAL`=true]**
  proactive consults the full picture ("I am now working on Y"). REMAINING (inventory brick): after the
  observation window, flip the code defaults to ON + remove the lines from .env.

**Depends on:** Phase 1, 2, 3 (DONE). Exists: operator_model, self_perception, context_builder,
vision. New: vision-memory (E1), SelfContext aggregator (E0), wiring into the organs (E2-E4).
**Risks (per cross-cutting D):** context budget (keep E2/E4 short, don't give away the prompts);
don't duplicate `context_builder` (extend, don't replace); operator data LOCAL (privacy #5).
**Mapping to the 6 layers:** welds layer 1 (Identity) + 2 (Perception) + 5 (Relationship).

---

### PHASE 1: Operator Understanding

*"Maria truly understands me"*

**Goal:** Maria builds a relational-operational model of the operator - not as a data record, but as a living understanding of the person she works with.

**5 dimensions of the operator model:**

| Dimension | Examples | Source |
|--------|-----------|--------|
| **Durable Facts** | name, profession, city, hardware, languages | conversations + explicit statement |
| **Operational Preferences** | when they want notifications, what tone, how much detail, what irritates them | feedback loop from conversations |
| **Day Rhythm / Routine** | wakes ~7, works 9-17, Friday = shorter, weekend = off | pattern detection from contact history |
| **Current Context / Load** | "I have a deadline today", "I'm sick", "I'm going on vacation" | explicit + inference from conversations |
| **Privacy Boundaries** | what NOT to ask, what NOT to log, what is taboo | explicit setting + escalation on doubt |

**What must be built:**
- **OperatorModel** - extension of UserProfile with 5 dimensions, structured + freeform, with confidence per fact
- **RelationshipTracker** - Maria remembers the relationship context: since when we've known each other, what we did together, what she learned about the operator
- **ActiveLearner** - Maria asks at most 1 question per day (Telegram), naturally in the flow of conversation, not a survey
- **RhythmDetector** - analysis of Telegram timestamp history + conversations -> day/week patterns
- **ContextInference** - "operator hasn't replied for 10h on a workday = probably busy, don't send" vs "weekend = normally quiet"
- **PrivacyGuard** - the operator explicitly defines the boundaries, Maria NEVER crosses them

**Capability contracts:**
- K14: OperatorModel - 5-dimensional operator understanding with confidence scoring
- K14.1: ActiveLearner - contextual questioning (max 1/day, natural, not survey-like)
- K14.2: RhythmDetector - temporal pattern extraction from interaction history
- K14.3: PrivacyGuard - hard boundaries, operator-defined, non-overridable

**Dependencies:** UserProfile (exists), ConversationMemory (exists), TimeAwareness (exists), Proactive Contact (exists)

**Risk:** Uncanny valley - Maria knows "too much" and the operator feels uncomfortable. Mitigation: transparency (Maria says WHERE she knows it from), privacy boundaries, the operator can erase any fact.

**Completion criterion:** Maria generates an "Operator Brief" (internal document) that the operator reads and says "yes, that's accurate". Plus: the morning message is personalized to the day rhythm.

**Fake progress:** 50 fields in a profile form. The model must grow organically from conversations and observation, not from an onboarding survey.

---

### PHASE 2: Self-Model Maturity

*"Maria honestly knows who she is"*

**Goal:** Maria maintains a true, current representation of herself - what she can do, what she can't, what her state is, what limitations she has - and communicates this to the operator honestly.

**What must be built:**
- **CapabilityManifest** - a list of what Maria can REALLY do (not what is in the code, but what works and has been tested)
- **LimitationRegistry** - an explicit list of limitations
- **ConfidenceMap** - per-capability confidence
- **StateReporter** - on demand or proactively
- **HonestyProtocol** - Maria NEVER claims she can do something if she has not tested it
- **GrowthAwareness** - Maria identifies her gaps as growth goals

**Capability contracts:**
- K15: SelfModel - maintained manifest of capabilities, limitations, and confidence levels
- K15.1: StateReporter - structured self-status on demand and proactive
- K15.2: HonestyProtocol - no overclaiming, explicit uncertainty, "I don't know" as valid
- K15.3: GrowthAwareness - limitations as identified growth targets with cost/benefit

**Dependencies:** Introspection (exists), UserFacingSelfModel (exists, V3), K12 Self-Analysis (exists), K4 Evaluation (exists)

**Risk:** Self-model drift - Maria claims she can do something because she once could, but the code changed. Mitigation: periodic capability probing.

**Completion criterion:** The operator asks "what can you do?" and gets an honest, concrete answer with confidence levels.

**Fake progress:** A beautiful "Maria capabilities" dashboard that is static and hand-written. The manifest must be auto-generated and auto-verified.

---

### PHASE 3: Operational Perception

*"Maria sees the whole operational world"*

**Goal:** Maria perceives not only her internal state, but the full operational context.

**4 perception channels:**

| Channel | Examples | Priority |
|-------|-----------|-----------|
| **External World** | weather, season, holidays, local events | high |
| **Local System** | systemd logs, services, cron, network (extension of the existing one) | medium |
| **Files / Tasks / Workspace** | files in input/, task state, changes in docs/ | high |
| **Messages / Calendar** | Telegram history, future: iCal, email headers | low |

**What must be built:**
- **ExternalSensors** - a unified interface: WeatherSensor, CalendarSensor, HolidaySensor
- **SystemSensor v2** - "did maria.service restart?", "is Ollama responding?", "how much space on storage?"
- **WorkspaceSensor** - observes input/, docs/, meta_data/
- **PerceptionFusion** - combines the channels into a coherent picture
- **SalienceFilter** - what is WORTH the operator's attention? Default = don't speak.

**Capability contracts:**
- K16: OperationalPerception - unified multi-channel perception with salience filtering
- K16.1: ExternalSensors - weather, calendar, holidays (pluggable)
- K16.2: WorkspaceSensor - file/task/log change detection
- K16.3: SalienceFilter - "worth telling?" decision based on OperatorModel (Phase 1)

**Dependencies:** Phase 1 (OperatorModel needed for SalienceFilter), K1 Unified Perception (exists)

**Risk:** Information overload. Mitigation: SalienceFilter mandatory.

**Completion criterion:** The morning message takes the weather + operator context into account.

**Fake progress:** 10 APIs without a SalienceFilter. 100 data points without a filter = spam worse than no data.

---

### PHASE 4: Digital Hands

*"Maria can DO something"*

**Goal:** Maria performs real digital tasks - she doesn't just think and speak, she acts.

**What must be built:**
- **ActionRegistry v2** - extension of CapabilityRouter with external actions: file ops, web research, email draft, notes
- **TaskExecutor** - multi-step tasks with checkpoints
- **ResultValidator** - Maria checks whether the action succeeded
- **SelfRepair** - Maria detects her own errors and tries to fix them (via Claude/Codex + OpenClaw). Uses the Self-Model (Phase 2) - she knows WHAT is broken.
- **ExecutionJournal** - a full audit trail of every action in the world

**Capability contracts:**
- K17: ActionExecution - reliable multi-step task execution with validation
- K17.1: SelfRepair - detect failure + attempt fix + escalate if can't
- K17.2: ExecutionAudit - every action logged, reversible where possible

**Dependencies:** OpenClaw (exists), Claude/Codex CLI (exists), K7 Autonomy (exists), K10 Safety (exists), Effector Safety Envelope (exists), Phase 2 (Self-Model for SelfRepair)

**Risk:** Safety. Principle: OBSERVE -> SUGGEST -> CONFIRM -> BOUNDED.

**Completion criterion:** Maria can execute a 3-step task with a full audit.

**Fake progress:** A "universal tool framework" instead of 5 concrete, working tools.

---

### PHASE 5: Workflow Orchestration

*"Maria runs complex processes"*

**What must be built:**
- **WorkflowEngine** - definable sequences of actions with conditions, branching, retry
- **DelegationManager** - Maria delegates subtasks to the appropriate tools
- **ProgressReporter** - the operator gets updates along the way
- **InterruptHandler** - the operator can stop, change, or undo at any moment

**Capability contracts:**
- K18: WorkflowExecution - multi-step process with checkpoints and rollback
- K18.1: DelegationProtocol - which tool/model for which subtask

**Dependencies:** Phase 4 (Digital Hands must work solidly), K8 Deliberation (exists)

**Risk:** Over-engineering. Start simple: linear sequences. Branching only when needed.

**Completion criterion:** Maria runs a repeatable workflow without intervention.

**Fake progress:** A visual workflow editor. Maria is not Zapier. Workflows in code/configuration.

---

### PHASE 6: Environment Adaptation

*"Maria adapts to context"*

**What must be built:**
- **EnvironmentProfile** - a mode definition (home/operator/creator/business) with different priorities, tools, tone
- **AdapterLayer** - pluggable adapters per mode
- **ModeSwitch** - Maria recognizes the context or the operator switches manually
- **CoreStability** - K1-K13 + identity DO NOT CHANGE between modes. Only the tool and priority layer changes.

**Capability contracts:**
- K19: EnvironmentAdapter - pluggable context layer over stable core
- K19.1: ModeDetection - auto-detect or manual switch

**Dependencies:** Phase 1-5 (the core must be stable and universal)

**Risk:** Identity blur. The mode changes WHAT she does, not WHO she is.

**Completion criterion:** Maria works in 2 different modes with different tools but a coherent personality.

**Fake progress:** 6 modes on paper. Start with 1 that works.

---

### PHASE 7: Trust & Autonomy Graduation

*"Maria earns more and more autonomy"*

**What must be built:**
- **TrustScore** - computed from history: how many tasks correct, how many corrections, how many rejects
- **AutoPromotion** - when TrustScore > threshold, Maria proposes a permission promotion
- **IncidentMemory** - Maria remembers her mistakes and avoids repeating them
- **AutonomyDashboard** - the operator sees what Maria can do on her own, what requires approval

**Capability contracts:**
- K20: TrustGraduation - earned autonomy based on track record
- K20.1: IncidentLearning - structured failure memory

**Dependencies:** Phase 3-5 (there must be something to measure), K7 Autonomy (exists), Approval Queue (exists)

**Completion criterion:** Maria herself proposed a promotion from OBSERVE to SUGGEST in one category, the operator approved, and Maria operates at the new level without regression for 7 days.

**Fake progress:** Automatically granting permissions without a track record. Trust must be EARNED.

---

## D. Cross-cutting Requirements

Things that must work **in every phase**:

1. **Auditability** - every decision, action, and state change logged in JSONL. Exists (K10, tracing). Extend.
2. **Operator control** - the kill switch always works. Operator > Maria. Always.
3. **Graceful degradation** - no internet = Maria works locally. No NIM = Ollama fallback. Already implemented.
4. **Backward compatibility** - a new phase does not break the previous one. Regression tests mandatory.
5. **Privacy by design** - operator data local. No external API gets the operator's profile.
6. **Resource awareness** - Maria must not eat 100% CPU/RAM. The homeostasis mode regulator already watches this.
7. **Economic Self-Awareness (parallel layer)**
   - CostTracker - how much Maria costs monthly (electricity, NIM API, hardware amortization)
   - ValueLog - what useful things Maria did (tasks, alerts, time savings)
   - ResourceBudget - how many NIM tokens are left, how much storage, how much RAM
   - GrowthCostEstimate - "more RAM = ~400 PLN, effect: I can load 2 models simultaneously"
   - Rolled out incrementally: CostTracker in Phase 3, ValueLog in Phase 4, GrowthCostEstimate in Phase 2
   - Communicated in the weekly review, not a separate dashboard
8. **Coherent identity** - Maria is the same Maria in the REPL, Telegram, and Web UI. MasterPrompt is the single source of truth.

## E. What NOT to Build Too Early

| Trap | Why not now |
|---------|-------------------|
| Voice / TTS / STT | Decoration. Telegram + Web UI are enough. Voice when the core works |
| Multi-user | Maria is a PERSONAL digital human. One operator. Multi-user is a different product |
| Plugin marketplace | Over-engineering. Maria has an AdapterLayer, not an App Store |
| Mobile app | REVISED 06-17: a native Flutter app WAS BUILT (token auth + Inbox approve-flow). The April assessment was wrong because it did not anticipate the need for a native approve-flow -- lesson: a "trap" can mature into a tool once core value appears (here: approving Maria's actions from your pocket) |
| "AI personality customization" | Maria's personality evolves organically (TraitEvolver). "Pick a personality" is a gadget |
| Cloud hosting | Maria is LOCAL. That is her advantage, not a limitation |

## F. Top Architectural Risks

1. **Complexity ceiling** - ~205k lines of py (state 07-06; in April it was ~60k). Every phase adds more. Without aggressive simplification, complexity will kill velocity. Mitigation: every phase starts with cleanup.

2. **LLM dependency fragility** - Ollama + NIM. Model quality changes between versions. Mitigation: model_registry abstraction (exists), benchmarks per upgrade.

3. **Operator fatigue** - Too many notifications = the operator ignores Maria. Mitigation: SalienceFilter (Phase 3), batching, quiet hours (exists).

4. **Safety vs usefulness tension** - Too much gatekeeping = Maria does nothing. Too little = she does stupid things. Mitigation: graduated autonomy (Phase 7).

5. **Single point of failure** - One mini PC. Disk dies = Maria disappears. Mitigation: backup cron 03:00 (daily). NOTE (correction 07-06): GitHub is NOT a backup of the live system -- origin carries ONLY the sanitized `main` snapshot (ADR-029). **RESTORE DRILL PERFORMED 2026-07-06 (PASS)**: backup healthy (146k lines of JSONL, 0 corrupted), detected gaps patched (backup.sh extended with a git bundle = code+471 local commits, a separate private repo, notes, crontab, systemd unit), repo resurrected from the bundle HEAD-identically. Remaining: the habit of a USB copy in case the WHOLE PC is lost (two disks only protect against one failing).

## G. Execution Track (post-April) and the Road Ahead

The April "Immediate Next Milestones" (OperatorModel v1, CapabilityManifest,
WeatherSensor+MorningBrief) are long DONE (OperatorModel SSoT 05-30; K15
`operator/capability_manifest.py`; `weather/` + morning brief + hydration
nudge). Below is the actual post-April track and the agreed road ahead
(planning session 2026-07-06: 13-agent reconnaissance -> 3 variants ->
adversarial verification; Eryk approved the order).

### The DH ladder -- rungs completed

| Rung | Status |
|----------|--------|
| **DH-A reversibility** (undo journal+execute) | LIVE on live OpenClaw 06-24/25 (Maria wrote and undid a file herself); undo-suggest armed-dormant |
| **Super-META E0-E4** (situational awareness) | DONE + flags ARMED (06-26/27); the default flip after the observation window remains |
| **DH-B project trees** (rollup+deadline) | built 06-22, ARMED=observe 07-04; operator's 1st project 3/3 ACHIEVED 07-05; rollup proof COMPLETE (282+ correct observe decisions). DISCOVERY 07-06: the deadline flag was a DEAD CABLE on the live daemon (read only by abandoned entrypoints) -- fixed (`f6ba962`). REAP: recommendation permanently OFF (binary flag without observe, does not save USER goals) |
| **DH-C capability gate** | built 06-22 + signal fix 06-28; observe silence = healthy (16/16 available; 702 pre-fix blocks archived in /mnt/storage) |

### The road ahead (agreed 2026-07-06: Workshop -> Records -> Assembly line)

1. **Closing TIER 2** -- ROLLUP=cutover BEFORE 2026-07-09 22:57 (first
   autonomous project closure + proactive ping "goal achieved");
   DEADLINE=cutover only after live `[DEADLINE/observe]` lines
   (expected ~07-08 evening on the funding project after the cable fix);
   project #2 via `/project` as a second data point.
2. **DH-C arming** -- `/drill_capability` (the drill MUST force scheduling of a
   disabled action, otherwise it shows nothing) + a manifest alarm in the
   Phase 18 snapshot, then `CAPABILITY_GATE_ENABLED=1`.
3. **WORKSHOP** (Tier 3 room #1: workflow, operator's tap only) --
   a boundary contract on paper (K8=learning, workflow=delivery); the first
   run in history (`/wf start`, zero code -- the engine has NEVER run);
   the first hand chain `note_pipeline` (write -> check -> report);
   the valves: `/wf approve` (today zero callers = deadlock of steps awaiting
   approval) + K7 parity (today workflow bypasses the planner's gates). STOP
   before autonomy.
4. **RECORDS** (Phase 7 honestly) -- revive the incident recorder
   (unplugged: `record_incident` behind an early-return in CapabilityRouter in
   `action_executor.py`), fix the double-counting of resolve, a week of
   observing `/trust` (a drop = measurement success, not a regression),
   `[AVOID/observe]`; add visibility of HAND evidence in TrustScorer (today
   it reads only goals/approvals -- effector evidence does not enter the formula).
   Promotion OBSERVE->SUGGEST only after >=10 journaled hand actions.
5. **ASSEMBLY LINE** (delivery) -- a project ends with a FILE in Telegram;
   `WORKFLOW_AUTOCREATE` via flag->observe->cutover; autonomy LAST,
   on earned evidence (critic: without points 3+4 this is autonomy on credit).

### Mortar (between the boards, not separate boards)

- ~~**Backup RESTORE drill** (F.5)~~ -- **DONE 2026-07-06 (PASS)**: the soul
  is healthy, gaps patched (code+git/notes/config in the backup as of today),
  procedure documented. Next drill ~quarterly.
- Reasoning journal: dedup + rotation + `/myslenie podsumowanie`; pattern
  synthesis ONLY on a clean corpus (until 07-06 the corpus = 99.6% monoculture
  of the nightly creative loop; tap turned off `0039116`).
- Decisions on dormant flags with Eryk: `ACTIVE_LEARNER_ENABLED`,
  `HONESTY_HINT_ENABLED`, `SELF_DEV_JOURNAL_ENABLED` -- arm them or record them
  as "intentionally OFF" in the env-flag inventory.
- Consciously DEFERRED (recorded, not lost): economy D.7 (to be re-scoped once
  a monetization path is in place), calendar+mail in perception,
  RelationshipTracker, vision-grounding (awaiting hardware), voice (north-star),
  autonomous sub-goal tree producer (needs a fresh review of collisions with K8).

---

*Last updated: 2026-07-06*
*Version: 2.0 (status pass: statuses updated to reality after a 13-agent audit; vision
and architecture v1.1 untouched. v1.1: 2026-04-12, Eryk's correction -- relational
operator model, full operational perception, self-model as a separate phase,
economics as cross-cutting)*
