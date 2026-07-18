# M.A.R.I.A. - Complete Architecture Documentation

**Meta Analysis Recalibration Intelligence Architecture**
Version: 2026-04-07 | 383 Python files | 113,552 lines of code | 3,352 tests

> **[HISTORICAL — 2026-04-07]** This document describes the state as of April 2026 and is
> NOT current: the code now runs **20 tick phases** (April 2026 had 11; historical) and the
> test suite has grown to **7,145 collected** (up from 3,352). For current module and phase
> status see **`docs/SYSTEM_STATUS.md`**. Do not treat this file as runtime truth until it is
> regenerated.

---

## 1. What is M.A.R.I.A.?

A local, autonomous AI agent that learns on its own from text files. It runs offline on a Mini PC (AMD Ryzen 5, 32GB RAM), using Ollama (llama3.1:8b) as its primary brain and the NIM API as a learning aid.

**Key features:**
- Autonomous learning from files in input/ (no human intervention)
- Goal system with an audit trail and a PROPOSED flow (operator approves)
- 13 architectural contracts (K1-K13) forming the cognitive core
- Embedding-based semantic memory (nomic-embed-text, 768-dim)
- Telegram bridge for operator communication
- Web UI (Flask) with an 8-panel dashboard

**Hardware:** Mini PC NiPoGi, AMD Ryzen 5 7430U, 32GB RAM, 1TB SSD, 6TB HDD archive
**OS:** Ubuntu 22.04 LTS | **IP:** (local network)
**Users:** maria (application, no sudo), deployadmin (admin)

---

## 2. Directory structure

```
maria/
  maria.py                 # V3 UnifiedLauncher (daemon + Web UI, systemd)
  main.py                  # REPL mode (interactive)
  run_maria.py             # Legacy daemon (replaced by maria.py)
  run_ui.py                # Legacy Web UI (replaced by maria.py)
  maria_core/              # Legacy (old code; the live path imports it directly)
  agent_core/              # New system (K1-K13 + infrastructure)
    homeostasis/           # 1Hz loop, sensors, operating modes
    perception/            # K1: unified event format
    sandbox/               # K2: isolates learning from production
    goals/                 # K3: goal system with audit trail
    evaluation/            # K4: READ-ONLY metrics
    planner/               # K5: ReAct loop (OBSERVE->THINK->ACT->EVALUATE)
    world_model/           # K6: beliefs with confidence and evidence
    autonomy/              # K7: action classification, rate limits, escalation
    deliberation/          # K8: multi-step strategies
    meta_cognition/        # K9: reflection, assumption tracking
    action_safety/         # K10: action audit, effect validation
    experiment/            # K11: autonomous parameter tuning
    self_analysis/         # K12: analyzes its own logs with a stronger model
    creative/              # K13: strategic module, tensions, meta-goals
    teacher/               # Teacher agent (decides what to learn)
    consciousness/         # Personality, dreams, cross-session continuity
    llm/                   # LLM router, NIM, Codex, ModelScheduler
    semantic/              # Semantic Memory (nomic-embed-text, vector store)
    web_source/            # Wikipedia PL + RSS -> input/
    telegram/              # ClawBot - operator communication
    effector/              # OpenClaw - external action execution
    critic/                # Phase G: knowledge quality audit (7 dimensions)
    cross_validation/      # Phase F: multi-source validation
    bulletin/              # Learning Upgrade: audit, gap planner, expert bridge
    vision/                # Vision: sensor, preprocessing, motion, scene, cortex, LLaVA
    orchestrator/          # V3: OnboardingFlow, TaskOrchestrator, ProductShell (15 modules)
    routing/               # CapabilityRouter (dispatch instead of if/elif)
    tracing/               # Episode-based decision traceability
    storage/               # Log archival to the 6TB HDD
    introspection/         # READ-ONLY analysis of its own code (AST)
    memory/                # MemoryQuery - unified API with provenance
    adapters/              # Bridges to legacy maria_core/
    registry/              # ModuleRegistry, SharedContext, CommandDispatcher
    modules/               # REPL modules (homeostasis_module, planner_module...)
    tests/                 # 92 test files, 3,352 tests
  maria_ui/                # Web UI (Flask + SocketIO)
  input/                   # Files to learn from (web_wiki_*, web_rss_*, expert_*)
  memory/                  # knowledge_index.jsonl, longterm_memory, exam_results
  meta_data/               # JSONL logs, JSON configuration, vectors
  docs/                    # Documentation, specifications, plans
  scripts/                 # Systemd, backup, installation
  archive/                 # Old files (legacy 2026-02-01)
```

---

## 3. Modules - detailed description

### 3.1 Homeostasis (homeostasis/)

**Purpose:** The system's main loop, health monitoring, operating-mode regulation.

**Files:**
| File | Description |
|------|------|
| core.py | HomeostasisCore - 1Hz loop with 20 tick phases (April 2026 had 11; historical - see docs/SYSTEM_STATUS.md) |
| state_model.py | Mode (ACTIVE/REDUCED/SLEEP/SURVIVAL), ResourceMetrics, SystemState |
| interpreter.py | Converts metrics into semantic state (EMA smoothing) |
| constraints.py | Threshold validation, alert generation |
| mode_regulator.py | Mode decision based on health score |
| actions.py | Generates and executes corrective actions |
| event_logger.py | Logs events to JSONL |
| time_awareness.py | Time awareness (time of day, date, day of week) |
| pulse.py | 100ms micro-corrections (optional) |
| snapshot.py | Atomic state snapshots |
| api.py | HomeostasisInterface + EventBus |

**Tick phases (1Hz):** *(historical list up to phase 11; the code now runs 20 phases plus sub-phases 8.5/9.5/9.6/9.7 — full list: docs/SYSTEM_STATUS.md)*

| Phase | What it does | Frequency |
|------|---------|---------------|
| 1 SENSE | Read 5 sensors (CPU, RAM, temp, time, cognitive) | Every tick |
| 2 INTERPRET | EMA smoothing, semantic labels | Every tick |
| 3 VALIDATE | Threshold checks, alerts | Every tick |
| 4 DECIDE MODE | ACTIVE/REDUCED/SLEEP/SURVIVAL | Every tick |
| 5 GENERATE ACTIONS | Corrective actions | Every tick |
| 6 EXECUTE ACTIONS | Signals to modules | Every tick |
| 7 UPDATE HEALTH | health_score 0.0-1.0 | Every tick |
| 8 PERCEIVE | PerceptionEvents -> PerceptionBuffer | Every tick |
| 9 AUDIT & LOG | Snapshot to JSONL | Every 60 ticks |
| 9.5 MODEL SCHEDULER | Load/unload LLM models | Every tick |
| 10 PLANNER | PlannerCore.run_cycle() (in a thread) | Every 60 ticks + events |
| 11 TELEGRAM | Operator poll, notifications | Every 30s |

**Data:** meta_data/homeostasis_events.jsonl

---

### 3.2 Perception (perception/) - K1

**Purpose:** A unified event format across all sources.

**Key classes:**
- **PerceptionEvent** - frozen dataclass: event_id, source, event_type, priority, ttl, payload
- **PerceptionSource** - enum: SENSOR, USER, LEARNING, EXAM, CONSCIOUSNESS, TEACHER, PLANNER, SYSTEM
- **PerceptionBuffer** - FIFO queue (maxlen=200), dedup, drain expired

**Pattern:** Tick Aggregator (ADR-009) - sensors + external events aggregated each tick

---

### 3.3 Sandbox (sandbox/) - K2

**Purpose:** Isolate learning from production. All learning goes through the sandbox; promote() is the only bridge.

- **SandboxManager** - create session, seed data, record changes, promote/discard
- **Transaction log** - START/COMMIT/ROLLBACK, recovery after a crash
- **Data:** meta_data/sandbox_sessions.jsonl

---

### 3.4 Goal System (goals/) - K3

**Purpose:** Explicit goals with an audit trail, instead of implicit thresholds.

- **GoalType:** META, USER, LEARNING, MAINTENANCE
- **GoalStatus:** PROPOSED -> PENDING -> ACTIVE -> ACHIEVED/FAILED/ABANDONED
- **GoalStore:** JSONL append-only, max 20 active, max 3 proposed, 72h timeout
- **Seed goals:** goal-meta-learn (autonomous learning), 3x maintenance (health, CPU, RAM)
- **Data:** meta_data/goals.jsonl

---

### 3.5 Evaluation (evaluation/) - K4

**Purpose:** READ-ONLY observer, 5 metrics computed from JSONL logs.

**Metrics:** learning_velocity, retention_rate, knowledge_coverage, system_stability, personality_growth

- Writes ONLY to evaluation_reports.jsonl
- Frequency: every 1h
- Zero LLM, zero side effects

---

### 3.6 Planner (planner/) - K5

**Purpose:** A ReAct loop tying K1-K4 together. Rule-based, zero LLM, deterministic.

**Cycle:** GUARD -> PERCEIVE -> SELECT GOAL -> PLAN -> EXECUTE -> EMIT -> LOG

**ActionType (14):**
LEARN, EXAM, REVIEW, EVALUATE, MAINTENANCE, FETCH, EXPERIMENT, EFFECTOR, SELF_ANALYZE, CREATIVE, ASK_EXPERT, VALIDATE, CRITIQUE, NOOP

**Files:**
| File | Description |
|------|------|
| planner_core.py | Central ReAct loop, 20k lines |
| planner_guard.py | 5 gating rules (health, mode, sandbox, retention, teacher) |
| goal_selector.py | Aging factor (priority *= 1 + hours * 0.1) |
| action_executor.py | Delegates to subsystems (or CapabilityRouter) |
| planner_model.py | Plan, PlanStatus, ActionType, create_plan() |

**Action priority (in _decide_learning_action):**
1. P1: Exam (pending exams)
2. P2: Learn (new chunks to learn)
3. P3: New files (indexed "new")
4. P4: Review (retention < 0.8)
5. P5: Fetch (download from the internet)
6. P6: Ask Expert (query the LLM)
7. P7: Post NEED_MATERIAL to the bulletin board
8. Fallback: NOOP

**Data:** meta_data/planner_state.json, meta_data/planner_decisions.jsonl

---

### 3.7 World Model (world_model/) - K6

**Purpose:** A belief system with types, confidence, and evidence tracking.

- **Belief:** frozen dataclass - entity, entity_type, belief_type (FACT/OBSERVATION/HYPOTHESIS), confidence (0-1), evidence tuples
- **BeliefStore:** JSONL (MERGE semantics), cap 2000
- **BeliefBuilder:** Builds beliefs from knowledge_index, exam_results
- **WorldModelQuery:** get_knowledge_gaps(), find_beliefs_for_topic()
- **Maintenance:** decay (FACT 90d, OBSERVATION 30d, HYPOTHESIS 14d), dedup, compact, prune

**Data:** meta_data/beliefs.jsonl

---

### 3.8 Autonomy Policy (autonomy/) - K7

**Purpose:** Action classification, rate limiting, escalation.

- **Classification:** FREE (chat) / GUARDED (learn, fetch) / RESTRICTED (effector) / FORBIDDEN (delete)
- **Rate limiter:** Sliding window per ActionType (e.g. fetch 10/h, ask_expert 10/h)
- **Authority levels (Phase 5):** OBSERVE / SUGGEST / CONFIRM / BOUNDED / UNRESTRICTED
- **ApprovalQueue:** HITL for effectors (Telegram /efapprove, /efreject)
- **ToolBudgetManager:** Per-tool rate limits with exponential backoff

**Data:** meta_data/autonomy_decisions.jsonl, meta_data/authority_config.json

---

### 3.9 Deliberation (deliberation/) - K8

**Purpose:** Multi-step strategies (instead of one-off actions).

- **Strategy:** a list of steps (Step), each with success/failure conditions
- **Templates:** EXAM_PREP, KNOWLEDGE_REVIEW, ERROR_RECOVERY
- **IntentTracker:** JSONL persistence of active strategies

**Data:** meta_data/deliberation_intents.jsonl

---

### 3.10 Meta-Cognition (meta_cognition/) - K9

**Purpose:** Reflection, assumption tracking, comparing expectation vs outcome.

- **Reflector:** record_decision() BEFORE, reflect() AFTER
- **ConfidenceTracker:** Per-action confidence (exponential decay)
- **needs_human():** Signal that Maria needs the operator's help

**Data:** meta_data/reflections.jsonl

---

### 3.11 Action Safety (action_safety/) - K10

**Purpose:** Audit EVERY action, validate effects.

- **SafetyMode:** AUTO_COMMIT / AUDIT_ONLY / STAGED
- **AuditLog:** JSONL, every action with before/after state
- **EffectValidator:** capture_state() before, validate_effects() after

**Data:** meta_data/action_audit.jsonl

---

### 3.12 Experiment System (experiment/) - K11

**Purpose:** Autonomous tuning of 12 parameters (e.g. teacher_iterations, spaced_rep_factor).

- **ProposalEngine:** Scans metrics, generates change proposals
- **ExperimentRunner:** Changes a parameter (setattr), measures the result, restores it (finally)
- **ReportGenerator:** ADOPT / REJECT / INCONCLUSIVE
- **Cross-metric guard:** ADOPT is blocked if a guard metric drops >3%
- **Human gate:** Proposals require operator approval

**Data:** meta_data/experiment_reports.jsonl, meta_data/proposals.jsonl

---

### 3.13 Self-Analysis (self_analysis/) - K12

**Purpose:** Maria analyzes its own logs with a stronger model.

- **StateCollector:** Compresses 8 JSONL sources into a summary
- **ExternalAnalyzer:** Cascade: NIM API -> Claude CLI -> local qwen3:8b
- **RecommendationApplier:** Creates PROPOSED goals from recommendations
- **Trigger:** Every 24h, or K9 needs_human, or low retention

**Data:** meta_data/self_analysis_reports.jsonl

---

### 3.14 Creative Module (creative/) - K13

**Purpose:** A strategic organ - tensions, insights, meta-goals.

**20 files** - the most complex module:
- **TensionDetector:** 7 categories of tension (repetition, misalignment, over_restriction...)
- **ReflectionWorkspace:** Reflection sessions with bounded context
- **MetaGoalEngine:** Generates meta-goals via the NIM API
- **ReframeEngine:** Reframes problems
- **ExplorationEngine:** Explores new directions
- **IdentityProfile + PersonalityPolicy:** A cognitive style that influences weights
- **MemoryRetriever + MemorySummarizer:** Selective memory (semantic + keyword)
- **TokenBudget:** RPM-based gating (40 req/min)

**Data:** meta_data/creative_events.jsonl, creative_meta_goals.jsonl, creative_journal.jsonl, creative_tension_streaks.jsonl, creative_workspace_sessions.jsonl

---

### 3.15 Teacher (teacher/)

**Purpose:** Decides what and when to learn. A 6-priority engine (P1-P6).

- **KnowledgeAnalyzer:** JSONL analysis, zero LLM
- **SpacedRepetitionScheduler:** Review intervals based on results
- **TeacherAgent:** run_session(max_iterations) - the main learning loop
- **Auto-trigger:** ACTIVE + idle >= 10min -> learning session (3 iterations)

---

### 3.16 Consciousness (consciousness/)

**Purpose:** Personality, continuity, dreams.

- **TraitEvolver + TraitCatalog:** 7 personality traits with dynamic evolution
- **ConversationMemory:** Rolling context with LLM condensation
- **SleepProcessor + DreamGenerator:** Memory consolidation during SLEEP
- **IdentityStore:** Session count, uptime, birth date (2025-11-14)

**Data:** meta_data/consciousness_identity.json, personality_experiences.jsonl, dream_log.jsonl

---

### 3.17 LLM (llm/)

**Purpose:** Routing, budgeting, model lifecycle.

**Models:**
| Role | Model | RAM | State |
|------|-------|-----|------|
| MODEL-01 Planner | qwen3:8b | 5.5GB | cold (on-demand) |
| MODEL-02 Executor | llama3.1:8b | 5GB | warm (always loaded) |
| MODEL-03 Coder | qwen2.5-coder:7b | 5GB | cold |
| MODEL-04 Triage | rule-based | 0GB | instant |
| MODEL-05 Memory | nomic-embed-text | 274MB | cold |
| MODEL-06 NIM | z-ai/glm5 | 0GB (API) | remote |
| MODEL-07 Encyclopedia | Codex CLI (ChatGPT) | 0GB | remote |
| OpenClaw | qwen2.5:3b | 2GB | cold (separate instance) |

**Golden rule:** MODEL-02 stays warm, the rest are on-demand. Heavy mutex: MODEL-01 and MODEL-03 never run at the same time.

**LLMRouter:** think() -> Ollama, analyze_task() -> NIM (Ollama fallback), ask_encyclopedia() -> Codex -> NIM -> Ollama

**Data:** meta_data/nim_token_usage.json, llm_tape.jsonl, model_health.json, codex_interactions.jsonl

---

### 3.18 Semantic Memory (semantic/)

**Purpose:** Embedding-based similarity search.

- **EmbeddingModel:** nomic-embed-text via Ollama, 768-dim, cosine similarity
- **VectorStore:** In-memory + JSONL persist, 4 namespaces (knowledge, beliefs, hints, memories)
- **Auto-indexer:** Background indexing at startup + incremental after fetch/learn
- **275+ vectors** indexed

**Data:** meta_data/semantic_vectors.jsonl

---

### 3.19 Web Source (web_source/)

**Purpose:** Fetching learning material from the internet.

- **WikiClient:** Wikipedia PL API (search + fetch)
- **RSSClient:** RSS/Atom (stdlib XML)
- **TopicSuggester:** EXPAND top topics + EXPLORE new tags
- **ContentWriter:** Writes to input/ as web_{wiki|rss}_{slug}.txt
- **FetchRegistry:** Dedup (MERGE semantics)

**Data:** meta_data/web_fetch_registry.jsonl, input/web_*.txt

---

### 3.20 Telegram (telegram/)

**Purpose:** Maria <-> operator communication.

**Commands:**
/status, /goals, /trace, /memory, /learn, /approve, /reject, /priority, /efapprove, /efreject, /efstatus, /authority, /board, /validate, /beliefs, /restart, /help

**Notifications:** creative tensions, K12 recommendations, K9 needs_human, health drop, mode change, K7 blocks, startup, critique (CRITICAL only)

---

### 3.21 Effector - OpenClaw (effector/)

**Purpose:** Executing external actions (shell, web, files).

- **Subprocess:** sudo -u deployadmin openclaw
- **7 allowed tools:** exec, read, write, web_fetch, web_search, message, cron
- **K7:** RESTRICTED, rate limit 10/h
- **Fallback:** Maria works without OpenClaw

---

### 3.22 Critic (critic/) - Phase G

**Purpose:** Knowledge quality audit (7 dimensions). READ-ONLY, zero LLM.

**Dimensions:** contradiction, overconfident, underconfident, shallow, disputes, coverage, stale
**Trigger:** Every 8h, or after validate/maintenance
**Output:** PROPOSED goals via CritiqueApplier (max 3)

**Data:** meta_data/critique_reports.jsonl

---

### 3.23 Cross Validation (cross_validation/) - Phase F

**Purpose:** Validating knowledge against multiple sources.

- **CrossValidator:** Compares beliefs against a second LLM (NIM)
- **ConfidenceScorer:** Validation result -> confidence update
- **DisputeLog:** Contradictions between sources

**Data:** meta_data/disputes.jsonl

---

### 3.24 Bulletin Board (bulletin/) - Learning Upgrade

**Purpose:** A board of cognitive needs. Separates the topic from the material.

**5 phases:**
1. **BulletinStore** - NEED_MATERIAL, NEED_TEST, NEED_REVIEW, READY_TO_LEARN, WAITING_HUMAN
2. **KnowledgeAuditor** - checks MemoryQuery, beliefs, critic, exams -> AuditReport with 7 gap types
3. **GapPlanner** - decides: ASK_EXPERT (with context_prompt), REVIEW, RUN_EXAM, DECOMPOSE, WAIT_HUMAN
4. **ExpertBridge** - targeted questions to the LLM ("Maria knows X, needs Y")
5. **Full wiring** - write to input/, bulletin RESOLVED, standard learn pipeline

**Data:** meta_data/cognitive_bulletin.jsonl

---

### 3.25 Routing (routing/)

**Purpose:** Registry-based dispatch instead of a 13-way if/elif.

- **CapabilityRouter:** register(name, handler, spec), dispatch(plan)
- **15 registered capabilities** (learn, exam, review, evaluate, maintenance, fetch, experiment, effector, self_analyze, creative, ask_expert, validate, critique, noop + fallback)
- **Dual-path:** Router when available, legacy fallback

---

### 3.26 Tracing (tracing/)

**Purpose:** Correlating decisions via episode_id.

- **episode_id:** Thread-local, generated at the start of each planner cycle
- **Propagation:** planner -> K7 -> K10 -> LLM tape -> audit
- **TraceStore:** JSONL, bounded 200 in-memory

**Data:** meta_data/decision_traces.jsonl

---

### 3.27 Storage (storage/)

**Purpose:** Archiving logs to the 6TB HDD.

- **LogArchiver:** Moves old records -> /mnt/storage/data/logs/
- **DailySummary:** Compaction into daily summaries
- **Trigger:** The SLEEP phase in homeostasis
- **Backup:** 30 copies, cron at 3:00

---

## 4. Data flows

### 4.1 Learning pipeline

```
input/ (.txt files)
  |
  v
[Perception] scans the directory, hashes files
  |
  v
knowledge_index.jsonl  (status: new -> learning -> complete -> examined)
  |
  v
[LearningAgent] reads the file, sends it to the LLM
  |
  v
maria_longterm_memory.jsonl  (summaries, tags, key concepts)
  |
  v
[ExamAgent] tests retention
  |
  v
exam_results.jsonl  (exam results)
  |
  v
[BeliefBuilder] builds beliefs
  |
  v
beliefs.jsonl  (FACT/OBSERVATION/HYPOTHESIS with confidence)
```

### 4.2 Planner cycle (every 60 ticks)

```
[Homeostasis] -> health_score, mode
  |
  v
[PlannerGuard] -> can it plan?
  |
  v
[GoalSelector] -> select a goal (aging factor)
  |
  v
[K8 Deliberation] -> multi-step strategy (optional)
  |
  v
[_decide_learning_action] -> P1-P7 priority
  |
  v
[K7 Autonomy] -> is the action allowed?
  |
  v
[K9 MetaCognition] -> record_decision() BEFORE
  |
  v
[K10 ActionSafety] -> capture_state() BEFORE
  |
  v
[ActionExecutor / CapabilityRouter] -> delegate to the subsystem
  |
  v
[K10] -> validate_effects() AFTER
  |
  v
[K9] -> reflect() AFTER (outcome match?)
  |
  v
planner_decisions.jsonl + decision_traces.jsonl
```

### 4.3 Fetching material (FETCH + ASK_EXPERT)

```
[Planner P5: FETCH]
  |
  v
[TopicSuggester] -> pick a topic from KnowledgeAnalyzer
  |
  v
[WikiClient / RSSClient] -> fetch the article
  |
  v
[ContentWriter] -> input/web_{wiki|rss}_{slug}.txt

[Planner P6: ASK_EXPERT]
  |
  v
[KnowledgeAuditor] -> audit knowledge on the topic
  |
  v
[GapPlanner] -> context_prompt ("Maria knows X, needs Y")
  |
  v
[ExpertBridge] -> ask_encyclopedia() (Codex -> NIM -> Ollama)
  |
  v
input/expert_{slug}.txt
  |
  v
[BulletinStore] -> NEED_MATERIAL resolved
```

### 4.4 Creative cycle

```
[K4 Evaluation] -> metrics
  |
  v
[TensionDetector] -> 7 tension categories
  |
  v
[ReflectionWorkspace] -> reflection session
  |
  v
[MetaGoalEngine / NIM] -> meta-goals
  |
  v
[GoalAdapter] -> PROPOSED goals in K3
  |
  v
[Operator /approve] -> goal activation
```

### 4.5 Tracing (episode_id)

```
generate_episode_id()  ->  "ep-{timestamp}-{random}"
  |
  v
Thread-local storage (agent_core/tracing/episode.py)
  |
  v
All subsystems read current_episode_id():
  - K7 autonomy_decisions.jsonl
  - K10 action_audit.jsonl
  - LLM llm_tape.jsonl / codex_interactions.jsonl
  - K9 reflections.jsonl
  - Planner planner_decisions.jsonl
  |
  v
decision_traces.jsonl  (full trace per episode)
  |
  v
Query: get_by_episode_id(), get_failed(), get_by_goal_id()
```

---

## 5. Data files

### 5.1 JSONL (append-only logs)

| File | Size | Writer | Frequency |
|------|---------|--------|---------------|
| planner_decisions.jsonl | 8.4 MB | planner | ~1/min |
| decision_traces.jsonl | 5.6 MB | tracing | ~1/min |
| autonomy_decisions.jsonl | 5.3 MB | K7 | ~1/min |
| action_audit.jsonl | 5.0 MB | K10 | ~1/min |
| semantic_vectors.jsonl | 3.3 MB | semantic | on index |
| reflections.jsonl | 2.3 MB | K9 | after every action |
| homeostasis_events.jsonl | 1.3 MB | homeostasis | every 60 ticks |
| maria_longterm_memory.jsonl | 1.3 MB | learning | after learning |
| exam_results.jsonl | 1.0 MB | exam | after an exam |
| dream_log.jsonl | 0.9 MB | consciousness | during SLEEP |
| teacher_plans.jsonl | 577 KB | teacher | periodically |
| codex_interactions.jsonl | 424 KB | Codex CLI | on request |
| evaluation_reports.jsonl | 424 KB | K4 | every 1h |
| personality_experiences.jsonl | 161 KB | consciousness | continuous |
| creative_events.jsonl | 124 KB | K13 | periodically |
| beliefs.jsonl | 107 KB | K6 (MERGE) | after learning/exam |
| self_analysis_reports.jsonl | 92 KB | K12 | every 24h |
| creative_meta_goals.jsonl | 91 KB | K13 (MERGE) | periodically |
| knowledge_index.jsonl | 68 KB | perception (MERGE) | on scan |
| web_fetch_registry.jsonl | 52 KB | web_source (MERGE) | on fetch |
| goals.jsonl | 17 KB | K3 (MERGE) | on change |

### 5.2 JSON (configuration)

| File | Purpose |
|------|-----|
| planner_state.json | Planner cycle state |
| consciousness_identity.json | Identity (session count, uptime) |
| model_health.json | LLM model state |
| nim_token_usage.json | NIM token budget |
| authority_config.json | Effector authority levels |
| code_self_model.json | Code introspection result |

### 5.3 Archive (/mnt/storage/)

```
/mnt/storage/
  data/
    logs/        # Moved old JSONL records
    summaries/   # Daily summaries (compacted)
  backups/       # Daily tar.gz at 3:00 (30 copies)
  vision/        # (prepared for the camera)
```

---

## 6. Architecture decisions (ADR)

| ADR | Decision |
|-----|---------|
| ADR-001 | JSONL as the source of truth, the graph as a derived cache |
| ADR-005 | No emoji in code (terminal compatibility) |
| ADR-006 | Introspection READ-ONLY (Maria does not modify code) |
| ADR-008 | NIM for learning, Ollama for chat (hybrid routing) |
| ADR-009 | Tick Aggregator instead of an Event Bus (KISS) |
| ADR-010 | Sandbox-first learning |
| ADR-013 | Planner v1 rule-based (zero LLM, deterministic) |
| ADR-015 | Multi-organ model stack (heavy mutex, RAM tiers) |
| ADR-016 | OpenClaw as the effector (tools/invoke, Maria = the brain) |
| ADR-021 | Embeddings (nomic-embed-text) instead of keyword retrieval |
| ADR-022 | Episode-based tracing (thread-local correlation IDs) |
| ADR-023 | Unified MemoryQuery with provenance metadata |
| ADR-024 | Execution budgets (timeout on Ollama) |
| ADR-025 | Cross-metric validation (ADOPT blocked if a guard metric degrades) |
| ADR-028 | Critic = coherence/calibration auditor, not a truth engine |
| ADR-029 | GitHub = a public showcase, not a live mirror of production |
| ADR-030 | Skills as artifact (Hermes-inspired procedural memory, sandbox-first promote with a human gate) |

---

## 7. Architectural contracts

| Contract | Module | Tests | Description |
|----------|-------|-------|------|
| K1 | perception | 131 | Unified PerceptionEvent |
| K2 | sandbox | 44 | Learning isolation, promote() |
| K3 | goals | 63 | Goal system with audit trail |
| K4 | evaluation | 35 | READ-ONLY metrics |
| K5 | planner | 82 | ReAct loop |
| K6 | world_model | 69 | Beliefs with confidence |
| K7 | autonomy | 45 | Action classification, rate limits |
| K8 | deliberation | 49 | Multi-step strategies |
| K9 | meta_cognition | 73 | Reflection |
| K10 | action_safety | 52 | Action audit |
| K11 | experiment | 67 | Parameter tuning |
| K12 | self_analysis | 45 | Analysis with a stronger model |
| K13 | creative | 129 | Strategic organ |
| Phase F | cross_validation | 38 | Multi-source validation |
| Phase G | critic | 69 | Knowledge quality audit |

**Total (2026-04-07 snapshot):** 3,352 tests across 92 test files. The suite has since grown to **7,145 collected** (`pytest agent_core/tests/ --collect-only -q`) — see `docs/SYSTEM_STATUS.md`.

---

## 8. Run modes

### Daemon (run_maria.py)
```bash
sudo systemctl start maria    # Start
sudo systemctl status maria   # Status
sudo journalctl -u maria -n 50 # Logs
```
- Headless, 1Hz loop, planner every 60s
- Systemd revives it after a crash (RestartSec=10)

### REPL (main.py)
```bash
source venv/bin/activate
python main.py
```
- Interactive; commands /homeostasis, /plan, /teacher, /introspect...

### Web UI (run_ui.py)
```bash
sudo systemctl start maria-ui
# -> http://localhost:5000 (PIN auth)
```
- 8-panel dashboard, chat with Maria, architecture, experiments

---

## 9. Key REPL commands

| Command | Description |
|---------|------|
| /homeostasis | System status (mode, health, sensors) |
| /homeostasis start/stop | Loop control |
| /plan | Last decision |
| /plan status | Cycles, plans, eval |
| /plan goals | Goal ranking |
| /teacher | Learning session |
| /teacher status | Agent state |
| /learn | Automatic learning from input/ |
| /learn stats | Knowledge base statistics |
| /introspect | How Maria sees its own architecture |
| /consciousness | Personality and consciousness |
| /experiments | Proposals and reports |

---

## 10. External dependencies

| Dependency | Version | Purpose |
|-----------|--------|-----|
| Ollama | latest | Local LLMs (llama3.1:8b, qwen3:8b, nomic-embed-text) |
| Flask | 3.x | Web UI |
| Flask-SocketIO | 5.x | WebSocket chat |
| psutil | 5.x | System metrics |
| requests | 2.x | NIM API, Wikipedia, RSS |
| python-dotenv | 1.x | .env configuration |
| pytest | 9.x | Tests |

**Zero new deps:** RSS (stdlib xml.etree), Telegram (requests), Wikipedia (requests)

---

## 11. History and milestones

| Date | Event |
|------|------------|
| 2025-11-14 | Project started |
| 2026-01 | Homeostasis - the first module |
| 2026-02-22 | Deploy to the Mini PC |
| 2026-03-01 | K1-K5 (core contracts) |
| 2026-03-20 | K6-K10 (cognitive core COMPLETE) |
| 2026-03-22 | OpenClaw LIVE, Model Registry v2 |
| 2026-03-25 | K13 Creative Phase 2 (NIM-powered) |
| 2026-03-27 | Semantic Memory (nomic-embed-text) |
| 2026-03-29 | Stabilization Roadmap COMPLETE (6 phases) |
| 2026-03-29 | Phase F + Belief Store v2 + CapabilityRouter |
| 2026-03-30 | Phase G Critic Agent |
| 2026-04-01 | Learning Upgrade COMPLETE (5 phases) |

---

*Generated: 2026-04-01 by Claude Code*
*Project: https://github.com/erykaitools-beep/Maria*
*License: AGPL-3.0*
