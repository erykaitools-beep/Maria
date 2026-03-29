# M.A.R.I.A. - Architecture Document
> Version: 1.0 | Last updated: 2026-03-29

## 1. Overview

**M.A.R.I.A.** (Meta Analysis Recalibration Intelligence Architecture) to lokalny, autonomiczny agent AI zaprojektowany do samodzielnego uczenia sie z plikow tekstowych.

- **Backend LLM:** Multi-model stack (7 modeli: Ollama local + NIM cloud + embeddings)
- **Tryb pracy:** Offline-first, NIM cloud optional
- **Jezyk:** Python 3.8+
- **Platforma:** Ubuntu 22.04 (Mini PC: AMD Ryzen 5, 32GB RAM)
- **Testy:** 2448 passing
- **Cognitive Core:** K1-K13 complete, Stabilization (6 phases) complete, Faza F complete

---

## 2. Aktualna Architektura (Ver.4)

### 2.1 Diagram warstw

```
+------------------------------------------------------------------+
|                      WARSTWA WEJSCIA                              |
|  main.py (REPL)  |  run_maria.py (daemon)  |  setup_*.py          |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                    WARSTWA STEROWANIA                             |
|  orchestrator.py     |  meta_controller.py   |  resource_watchdog |
|  (cykl uczenia)      |  (maszyna stanow)     |  (RAM guard)       |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                    WARSTWA PERCEPCJI                              |
|  perception.py                                                    |
|  - skanowanie plikow .txt                                         |
|  - hashing SHA256 (wykrywanie zmian)                              |
|  - analiza struktury dokumentu                                    |
|  - obliczanie priorytetow                                         |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                    WARSTWA UCZENIA                                |
|  learning_agent.py   |  exam_agent.py      |  priority_scheduler  |
|  - chunking          |  - generowanie      |  - ocena waznosci    |
|  - wywolania LLM     |    egzaminow        |  - hard_topic retry  |
|  - ekstrakcja wiedzy |  - ocena odpowiedzi |                      |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                    WARSTWA PAMIECI                                |
|  memory_store.py     |  semantic_graph.py  |  brain_memory_*.py   |
|  (JSONL storage)     |  (graf wiedzy)      |  (integracja)        |
|                      |  - wezly + relacje  |                      |
|                      |  - cosine similarity|                      |
|                      |  - konsolidacja     |                      |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                    WARSTWA LLM                                    |
|  LLMRouter (agent_core/llm/router.py)                             |
|  - chat -> Ollama (offline, fast)                                 |
|  - nauka/analiza -> NIM API (stronger model) z fallback Ollama    |
|  - TokenBudget (100k/dzien, 2M/miesiac)                           |
|  ollama_brain.py (models/)                                        |
|  - komunikacja z Ollama API                                       |
|  - JSON retry mechanism                                           |
|  - historia rozmowy                                               |
+------------------------------------------------------------------+
```

### 2.2 Przepływ danych - Learning Cycle

```
[INPUT] Pliki .txt w /input
           |
           v
    [1] PERCEPTION
    scan_input_directory()
    - wykryj nowe/zmienione pliki
    - oblicz hash SHA256
    - zapisz do knowledge_index.jsonl
           |
           v
    [2] PRIORITY
    update_priorities()
    - heurystyki (rozmiar, struktura, keywords)
    - opcjonalnie: Ollama ocena waznosci
           |
           v
    [3] LEARNING
    learn_next_chunk()
    - wybierz plik o najwyzszym priorytecie
    - podziel na chunki (adaptive chunking)
    - dla kazdego chunka: wywolaj Ollama
    - zapisz summary/key_points/tags do memory
           |
           v
    [4] EXAM
    run_exam_if_ready()
    - gdy status == "learned"
    - wygeneruj pytania (Ollama)
    - odpowiedz na pytania (Ollama)
    - ocen odpowiedzi (Ollama)
    - score >= 60% -> "completed"
    - score < 60% && attempt < 2 -> "exam_failed"
    - score < 60% && attempt >= 2 -> "hard_topic"
           |
           v
    [5] HARD TOPIC RETRY
    reprocess_hard_topics()
    - po X ukonczonych plikach
    - przywroc hard_topic do statusu "new"
           |
           v
    [LOOP] Powtorz od kroku 1
```

### 2.3 Statusy pliku (lifecycle)

```
    [new] --learn--> [learning] --all chunks done--> [learned]
                                                        |
                         +------------------------------+
                         |
                         v
                    [EXAM] --pass--> [completed]
                         |
                         +--fail(1)--> [exam_failed] --relearn--> [learning]
                         |
                         +--fail(2)--> [hard_topic] --cooldown--> [new]
```

### 2.4 Komponenty pamięci

| Komponent | Format | Przeznaczenie |
|-----------|--------|---------------|
| knowledge_index.jsonl | JSONL | Indeks plikow: status, priorytet, hash |
| maria_longterm_memory.jsonl | JSONL | Nauczone chunki: summary, key_points, tags |
| exam_results.jsonl | JSONL | Historia egzaminow |
| semantic_graph.json | JSON | Graf wiedzy (wezly + relacje) |
| meta_controller.json | JSON | Stan meta-kontrolera |

---

## 3. Docelowa Architektura: "Full Homeostasis"

### 3.1 Koncepcja

System dziala jak organizm z homeostaza - utrzymuje rownowage poprzez petle zwrotne i regulatory. Cel: **stabilna, dlugoterminowa praca bez interwencji czlowieka** (multi-hour/multi-day runs).

### 3.2 Petle regulacji

```
+------------------------------------------------------------------+
|                    HOMEOSTATIC LOOPS                              |
+------------------------------------------------------------------+

[1] ENERGY/ATTENTION BUDGET
    +-> Monitor: zuzycie tokenow, czas odpowiedzi Ollama, RAM
    +-> Regulator: throttling, batch size adjustment
    +-> Threshold: max tokens/session, max RAM %

[2] MODE REGULATOR
    +-> Stany: LEARNING | TESTING | RECOVERY | SLEEP | DEMO
    +-> Przejscia oparte na:
        - motivation_score (nagrody - kary)
        - crash_streak
        - pora dnia (optional)
        - emergency_stop file
    +-> Auto-recovery po traumie

[3] MEMORY GATING
    +-> Co trafia gdzie:
        - episodic_memory: krotkoterminowe epizody (capped, FIFO)
        - semantic_graph: trwale fakty i relacje
        - JSONL files: persistence layer
    +-> Kryteria: confidence, importance, access_count

[4] CONSOLIDATION SCHEDULER
    +-> Harmonogram: co N epizodow / co M minut / przy idle
    +-> Operacje:
        - merge podobnych wezlow w grafie
        - prune low-importance nodes
        - archiwizacja starych epizodow
        - kompresja logow

[5] SAFETY STOP
    +-> resource_watchdog: RAM >= 90% -> os._exit(1)
    +-> EMERGENCY_STOP file: natychmiastowy shutdown
    +-> crash_streak >= 3 -> trauma -> RECOVERY mode
    +-> motivation_score < -15 -> RECOVERY mode
```

### 3.3 Diagram docelowy

```
                     +------------------+
                     |  ORCHESTRATOR    |
                     |  (main loop)     |
                     +--------+---------+
                              |
          +-------------------+-------------------+
          |                   |                   |
          v                   v                   v
   +-------------+    +---------------+    +-------------+
   | PERCEPTION  |    | LEARNING      |    | MEMORY      |
   | - file scan |    | - chunking    |    | - gating    |
   | - priority  |    | - LLM calls   |    | - consolid. |
   +------+------+    | - exams       |    +------+------+
          |           +-------+-------+           |
          |                   |                   |
          +-------------------+-------------------+
                              |
                     +--------v---------+
                     |  META CONTROLLER |
                     |  - mode FSM      |
                     |  - reward/penalty|
                     |  - trauma detect |
                     +--------+---------+
                              |
          +-------------------+-------------------+
          |                   |                   |
          v                   v                   v
   +-------------+    +---------------+    +-------------+
   | WATCHDOG    |    | CONSOLIDATOR  |    | REPORTER    |
   | - RAM limit |    | - graph merge |    | - logs      |
   | - emergency |    | - pruning     |    | - alerts    |
   +-------------+    +---------------+    +-------------+
```

### 3.4 Definition of Done: Full Homeostasis

System spelnia "Full Homeostasis" gdy:
- [x] Dziala stabilnie przez 8+ godzin bez crashy
- [x] Automatycznie przechodzi w RECOVERY po problemach
- [x] Automatycznie wraca do LEARNING po recovery
- [x] Pamiec (RAM) pozostaje w bezpiecznych granicach
- [x] Logi JSONL nie rosna nieograniczenie (pruning/archiwizacja)
- [x] Graf semantyczny konsoliduje sie automatycznie
- [x] episodic_memory ma cap i FIFO
- [x] System raportuje swoj stan (motivation, uptime, stats)

**STATUS: COMPLETE** (2026-01-28)

---

## 4. Kluczowe decyzje architektoniczne

Zobacz: [DECISIONS.md](./DECISIONS.md)

---

## 5. Znane ograniczenia (Ver.5.0)

1. **Legacy maria_core/** - stary kod owiniety adapterami, archiwizacja done
2. **Vision/Smart Home** - odroczone (ADR-014), czekaja na sprzet (Tapo C200, Shelly)
3. **NIM API expiry** - z-ai/glm5 wygasa Aug 2026, wymaga odnowienia lub alternatywy

### Rozwiazane ograniczenia:
- ~~Brak embeddings~~ -> Semantic Memory (nomic-embed-text, 768-dim, ADR-021)
- ~~Brak Unified Perception~~ -> K1 PerceptionEvent + Buffer + 6 adapterow
- ~~Brak Plannera~~ -> K5 PlannerCore + 13 action types
- ~~Brak Goal System~~ -> K3 GoalStore + audit trail
- ~~Brak World Model~~ -> K6 BeliefStore + BeliefBuilder
- ~~Brak Autonomy Policy~~ -> K7 + Phase 5 authority levels
- ~~Brak Deliberation~~ -> K8 strategy templates
- ~~Brak Meta-Cognition~~ -> K9 reflection + confidence
- ~~Brak Action Safety~~ -> K10 audit + effect validation
- ~~Brak Cross-Validation~~ -> Faza F CrossValidator + belief update
- ~~Brak Effector Safety~~ -> Phase 5 approval queue + tool budgets

**Cognitive Core K1-K13: COMPLETE (2448 tests)**
**Stabilization Roadmap (6 phases): COMPLETE**
**Faza F Multi-Source Learning: COMPLETE**

---

## 6. Nowa Architektura: agent_core/ (Ver.4.1)

### 6.1 Struktura agent_core/

```
agent_core/
├── homeostasis/           # System homeostazy (9-fazowy tick loop)
│   ├── sensors/           # Sensory (resource, cognitive, thermal, power, time)
│   ├── state_model.py     # Dataclasses: ResourceMetrics, CognitiveMetrics
│   ├── interpreter.py     # Raw -> semantic state conversion
│   ├── constraints.py     # ConstraintValidator, thresholds
│   ├── mode_regulator.py  # Mode enum, ModeRegulator
│   ├── actions.py         # CorrectiveActionGenerator, AlarmDispatcher
│   ├── core.py            # HomeostasisCore (1Hz tick, 9 phases)
│   ├── pulse.py           # HomeostasisPulseThread (100ms)
│   ├── api.py             # HomeostasisInterface, EventBus
│   ├── snapshot.py        # Snapshot protocol, recovery
│   ├── time_awareness.py  # TimeAwareness (dzien, godzina, pora dnia)
│   └── event_logger.py    # Persistent JSONL event logging
├── consciousness/         # Osobowosc, pamiec, sny
│   ├── core.py            # ConsciousnessCore (orchestrator)
│   ├── trait_catalog.py   # 7 cech osobowosci (rozszerzalne)
│   ├── trait_evolver.py   # Deterministic trait evolution
│   ├── self_model.py      # SelfModelBuilder (semantic graph nodes)
│   ├── identity_store.py  # Persistent identity (birth date, sessions)
│   ├── conversation_memory.py # Rolling context + LLM condensation
│   ├── experience_tracker.py  # Event recording for personality
│   ├── sleep_processor.py # NREM1-3 + REM phases
│   ├── dream_generator.py # Rule-based creative linking
│   └── human_state.py     # Human-readable state formatting
├── teacher/               # Autonomiczny agent nauczyciel
│   ├── teacher_agent.py   # 6-priority decision engine (P1-P6)
│   ├── knowledge_analyzer.py # JSONL analysis, zero LLM calls
│   └── teaching_strategy.py  # Strategy types + spaced repetition
├── perception/            # Unified Perception (Kontrakt K1)
│   ├── event.py           # PerceptionEvent, PerceptionSource, EVENT_TYPE_DEFAULTS
│   ├── buffer.py          # PerceptionBuffer (deque maxlen=200)
│   └── adapters/          # 6 adapterow (sensor, user, learning, exam, consciousness, teacher)
├── sandbox/               # Sandbox / Production Boundary (Kontrakt K2)
│   ├── protocol.py        # SandboxSession, SandboxStatus, PromoteResult
│   └── manager.py         # SandboxManager (create/promote/discard/cleanup)
├── goals/                 # Goal System (Kontrakt K3)
│   ├── goal_model.py      # GoalType, GoalStatus, AuditEntry, Goal
│   └── store.py           # GoalStore (CRUD + append-only JSONL persistence)
├── evaluation/            # Agent Evaluation (Kontrakt K4, READ-ONLY)
│   ├── observer.py        # EvaluationObserver (5 metryk, zero LLM)
│   └── report.py          # EvaluationReport schema
├── planner/               # Planner - ReAct Loop (Kontrakt K5, Warstwa 2)
│   ├── planner_core.py    # Central ReAct loop (co 60 tickow + event-driven)
│   ├── planner_model.py   # Plan, PlanStatus, ActionType, PlannerState
│   ├── planner_guard.py   # 5 gating rules
│   ├── goal_selector.py   # Aging factor + feasibility ranking
│   └── action_executor.py # Delegacja do Teacher/Sandbox/Evaluation
├── world_model/           # World Model / Belief System (Kontrakt K6)
│   ├── belief_model.py    # Belief (frozen), EntityType, BeliefType, BeliefSource
│   ├── belief_store.py    # BeliefStore (JSONL, MERGE, cap 2000)
│   ├── belief_builder.py  # Buduje beliefs z JSONL (zero LLM, idempotent)
│   └── query.py           # WorldModelQuery (topic confidence, gaps, summaries)
├── autonomy/              # Autonomy Policy / Governance (Kontrakt K7 + Phase 5)
│   ├── action_class.py    # ActionClassification (FREE/GUARDED/RESTRICTED/FORBIDDEN)
│   ├── rate_limiter.py    # Sliding-window rate limiter per ActionType
│   ├── policy_rules.py    # PolicyEngine + rules (incl. effector_authority)
│   ├── escalation.py      # EscalationHandler (JSONL log)
│   ├── authority_level.py # Phase 5: 5-level authority (OBSERVE->BOUNDED)
│   ├── approval_queue.py  # Phase 5: Non-blocking HITL approval queue
│   └── tool_budget.py     # Phase 5: Per-tool rate limits, backoff
├── deliberation/          # Deliberation / Strategic Planning (Kontrakt K8)
│   ├── strategy.py        # Strategy + Step dataclasses
│   ├── strategy_templates.py # 3 szablony + TEMPLATE_REGISTRY
│   ├── deliberator.py     # Rule-based selection + advancement
│   └── intent_tracker.py  # IntentTracker (JSONL, bounded 500)
├── meta_cognition/        # Meta-Cognition (Kontrakt K9)
│   ├── reflection_model.py # ReflectionRecord, assumption tracking
│   ├── reflection_store.py # ReflectionStore (JSONL, 300 cap)
│   ├── confidence_tracker.py # ConfidenceTracker (exponential decay)
│   └── reflector.py       # Reflector (before/after, pattern detection, needs_human)
├── action_safety/         # Action Safety (Kontrakt K10)
│   ├── safety_classifier.py # SafetyMode(3), SafetyProfile per action type
│   ├── audit_log.py       # AuditLog (JSONL, 200 cap)
│   └── effect_validator.py # Before/after state capture, effect validation
├── experiment/            # Experiment System (Kontrakt K11)
│   ├── proposal_engine.py # 4 rules (LOW_RETENTION, FAILURES, COVERAGE, SLOW)
│   ├── parameter_registry.py # 12 tunable parameters + bounds
│   ├── experiment_runner.py # setattr patch, health guard, timeout 1h
│   └── report_generator.py # ADOPT/REJECT/INCONCLUSIVE + confidence
├── self_analysis/         # K12 Self-Analysis (Phase 2: NIM cascade)
│   ├── state_collector.py # 8 JSONL sources, zero LLM
│   ├── external_analyzer.py # Cascade: NIM -> Claude CLI -> local qwen3:8b
│   └── recommendation_applier.py # PROPOSED goals + topic hints + beliefs
├── creative/              # K13 Creative Module (Phase 2: NIM engines)
│   ├── tension_detector.py # 7 tension categories
│   ├── reflection_workspace.py # Bounded sessions, candidate generation
│   ├── creative_journal.py # Strategic diary
│   ├── meta_goal_engine.py # NIM-powered meta-goal generation
│   ├── reframe_engine.py  # NIM-powered perspective reframing
│   ├── exploration_engine.py # NIM-powered knowledge exploration
│   ├── identity_profile.py # CognitiveProfile, developmental stage
│   └── personality_policy.py # Trait->weight adjustment
├── telegram/              # Telegram Bridge (ClawBot)
│   ├── bot.py             # TelegramBot (HTTP API, send/receive)
│   └── notifier.py        # 7 alert types with cooldowns
├── effector/              # OpenClaw Effector (ADR-016)
│   ├── openclaw_client.py # Subprocess client (sudo deployadmin)
│   └── tool_specs.py      # 7 whitelisted tools + validation
├── semantic/              # Semantic Memory (ADR-021, nomic-embed-text)
│   ├── embedding_model.py # Ollama /api/embed wrapper, cache
│   ├── vector_store.py    # In-memory + JSONL, 4 namespaces, cap 10k
│   └── indexer.py         # Auto-indexer (knowledge, beliefs, hints)
├── tracing/               # Decision Tracing (Phase 1, ADR-022)
│   ├── episode.py         # Thread-local episode_id
│   ├── trace_model.py     # DecisionTrace + TraceStep
│   └── trace_store.py     # JSONL persistence, bounded 200
├── cross_validation/      # Multi-Source Learning (Faza F, ADR-027)
│   ├── cross_validator.py # Compare primary (Ollama) vs secondary (NIM)
│   ├── confidence_scorer.py # Rule-based scoring (Jaccard, 3 dimensions)
│   └── dispute_log.py     # JSONL dispute persistence
├── storage/               # Storage Manager (6TB disk)
│   ├── log_archiver.py    # JSONL -> /mnt/storage/data/logs/
│   └── daily_summary.py   # Compaction -> /mnt/storage/data/summaries/
├── web_source/            # Web Content Fetcher (podlaczony do plannera)
│   ├── __init__.py        # run_fetch_session() - jedyny punkt integracji
│   ├── wiki_client.py     # Wikipedia PL API (search + fetch)
│   ├── rss_client.py      # RSS/Atom reader (xml.etree, zero nowych deps)
│   ├── topic_suggester.py # Wybor tematow z KnowledgeAnalyzer (zero LLM)
│   ├── content_writer.py  # Zapis .txt do input/ + dedup + slugify
│   └── fetch_registry.py  # JSONL rejestr pobranych (MERGE semantics)
├── introspection/         # Samowiedza kodu (READ-ONLY)
│   ├── analyzer.py        # AST static analysis
│   ├── code_model.py      # Code self-model structures
│   ├── reporters.py       # Human + Technical output
│   └── scheduler.py       # Periodic analysis
├── awareness/             # Kontekst samowiedzy
│   └── context_builder.py # ContextBuilder for /awareness
├── llm/                   # LLM management + multi-model stack
│   ├── router.py          # LLMRouter: chat->Ollama, nauka->NIM, ask_as_role()
│   ├── nim_client.py      # NVIDIA NIM API client (OpenAI-compatible)
│   ├── token_budget.py    # RPM-based gating (40 req/min)
│   ├── model_registry.py  # 7 models: ModelRole, ModelSpec, REGISTRY
│   ├── model_scheduler.py # Load/unload via Ollama, RAM guard, heavy mutex
│   ├── routing_rules.py   # TaskType -> ModelRole, heuristic_classify
│   ├── execution_budget.py # Phase 3: call_with_timeout, EpisodeBudget
│   ├── codex_client.py    # ChatGPT/Codex CLI wrapper (MODEL-07)
│   ├── latency_probe.py   # Non-blocking latency measurement
│   └── manager.py         # LLMManager interface
├── memory/
│   ├── manager.py         # MemoryManager (unified interface)
│   ├── episodic_store.py  # Episodic memory
│   ├── semantic_store.py  # Semantic memory
│   └── snapshot_backend.py
├── metacontrol/
│   └── controller.py      # MetaController interface
├── executor/
│   └── module_executor.py # ModuleExecutor (signal dispatch)
├── registry/              # Plug-in module system
│   ├── module_registry.py # ModuleRegistry
│   ├── command_dispatcher.py # Command routing
│   ├── shared_context.py  # SharedContext (DI container)
│   └── base_module.py     # MariaModule base class
├── modules/               # REPL command modules (plug-in)
│   ├── core_module.py     # /exit, /help
│   ├── homeostasis_module.py  # /homeostasis
│   ├── consciousness_module.py # /consciousness
│   ├── teacher_module.py  # /teacher
│   ├── learning_module.py # /learn
│   ├── introspection_module.py # /introspect
│   ├── awareness_module.py # /awareness
│   ├── nim_module.py      # /nim
│   ├── planner_module.py # /plan (Warstwa 2)
│   ├── knowledge_module.py # /knowledge
│   └── query_module.py    # /query
├── adapters/              # Legacy code wrappers
│   ├── memory_adapter.py
│   ├── semantic_adapter.py
│   ├── resource_adapter.py
│   └── brain_adapter.py
├── ui/
│   ├── telemetry_api.py   # Read-only dashboard
│   └── operator_controls.py
└── tests/                 # 2448 tests
    └── test_*.py          # 40+ test files
```

### 6.2 Integracja z main.py

```
main.py (Ver.2.0 - Registry-based)
    │
    ├── init_brain()
    │   ├── OllamaBrain (llama3.1:8b)
    │   ├── LLMRouter (NIM + Ollama hybrid)
    │   ├── IdentityStore (persistent identity)
    │   ├── ConversationMemory (rolling context)
    │   └── ConsciousnessCore (personality, dreams)
    │
    ├── ModuleRegistry (plug-in system)
    │   ├── core, homeostasis, consciousness
    │   ├── teacher, learning, knowledge, query
    │   ├── introspection, awareness, nim
    │   └── CommandDispatcher (routes /commands)
    │
    ├── REPL loop
    │   ├── /commands -> dispatcher
    │   ├── text -> perception (BrainMemoryLoop)
    │   └── Mode Gating:
    │       ├── SURVIVAL -> Block perception
    │       ├── SLEEP    -> Wake on interaction
    │       ├── REDUCED  -> Warning, continue
    │       └── ACTIVE   -> Normal operation
    │
    └── Cleanup
        ├── ConversationMemory.condense_session()
        └── ConsciousnessCore.checkpoint()
```

### 6.3 Przepływ danych - Homeostasis Loop (12 faz)

```
[1Hz Tick] ──────────────────────────────────────────────────────────
    │
    ├── Phase 1: SENSE
    │   ├── ResourceSensor (RAM, CPU, disk)
    │   ├── CognitiveSensor (latency, coherence)
    │   ├── ThermalSensor (temperature)
    │   ├── PowerSensor (uptime)
    │   └── TimeSensor (idle, session)
    │
    ├── Phase 2: INTERPRET
    │   └── StateInterpreter.process_metrics()
    │
    ├── Phase 3: VALIDATE
    │   └── ConstraintValidator + CRITICAL alarms
    │
    ├── Phase 4: DECIDE MODE
    │   └── ModeRegulator.decide_mode()
    │
    ├── Phase 5: GENERATE CORRECTIVE ACTIONS
    │
    ├── Phase 6: EXECUTE CORRECTIVE ACTIONS
    │
    ├── Phase 7: UPDATE HEALTH SCORE
    │
    ├── Phase 8: PERCEIVE (K1, ADR-009)
    │   ├── Aggregate sensor events -> PerceptionBuffer
    │   └── Drain external queue (REPL, teacher, etc.)
    │
    ├── Phase 9: TEACHER TRIGGER (idle >= 10min -> auto-learn)
    │
    ├── Phase 9.5: MODEL SCHEDULER (load/unload models, RAM guard)
    │
    ├── Phase 10: PLANNER (K5-K13 cognitive core)
    │   ├── PlannerCore.run_cycle() (co 60 tickow + event-driven)
    │   ├── Guard -> Approval Queue (Phase 5) -> Creative (K13)
    │   ├── GoalSelector -> Plan -> K7 AutonomyPolicy -> K9 Meta-Cognition
    │   ├── K10 ActionSafety -> ActionExecutor (13 action types)
    │   ├── Actions: LEARN/EXAM/REVIEW/FETCH/VALIDATE/CREATIVE/
    │   │   SELF_ANALYZE/EXPERIMENT/EFFECTOR/ASK_EXPERT/EVALUATE/NOOP
    │   ├── Deliberation (K8): multi-step strategies
    │   ├── WorldModel (K6): belief context + cross-validation feedback
    │   └── Trace: episode_id -> DecisionTrace -> TraceStore
    │
    ├── Phase 11: TELEGRAM (poll co 30s, operator commands)
    │
    └── Phase 12: AUDIT & LOG (co 60 tickow)
```

### 6.4 LLM Multi-Model Stack

```
ModelScheduler (heavy mutex, RAM guard)
    │
    ├── MODEL-01: qwen3:8b (Strategic Planner, 5.5GB, cold)
    ├── MODEL-02: llama3.1:8b (Executor/Brain, 5GB, warm=always loaded)
    ├── MODEL-03: qwen2.5-coder:7b (Coder, 5GB, cold)
    ├── MODEL-04: Rule-based triage (0GB, 0.1ms, keyword classifier)
    ├── MODEL-05: nomic-embed-text (Embeddings, 274MB, cold)
    ├── MODEL-06: NIM z-ai/glm5 (Cloud API, 40 RPM, expiry Aug 2026)
    ├── MODEL-07: Codex CLI (ChatGPT, 10 calls/h, subprocess)
    └── OpenClaw: qwen2.5:3b (Effector, 2GB, separate instance)

LLMRouter
    ├── think(prompt)          -> MODEL-02 Ollama (chat, fast)
    ├── analyze_task(task)     -> MODEL-06 NIM, fallback MODEL-02
    ├── ask_as_role(role, p)   -> ModelScheduler load/inference/release
    ├── ask_encyclopedia(q)    -> MODEL-07 Codex, fallback NIM, fallback Ollama
    │
    └── TokenBudget (RPM-based: 40 req/min sliding window)

ExecutionBudget (Phase 3, ADR-024)
    ├── call_with_timeout() wraps Ollama (120-180s per role)
    ├── EpisodeBudget: max 10 LLM calls, 5min latency per episode
    └── Degradation: REDUCED mode blocks heavy LLM actions
```

### 6.5 Consciousness Flow

```
ExperienceTracker                 TraitEvolver
    │ record("learning_completed")    │ evolve()
    │ record("conversation_turn")     │ (at checkpoint)
    v                                 v
[Session Buffer] ──────────> [Trait Scores 0.0-1.0]
                                      │
                              SelfModelBuilder
                                      │
                              [semantic_graph nodes]

SleepProcessor (when ACTIVE -> SLEEP)
    │
    ├── NREM1: gather stats
    ├── NREM2: boost edge weights (access_count >= 2)
    ├── NREM3: mark stale nodes (>48h, importance < 0.2)
    └── REM:   DreamGenerator (creative linking)
               └── dream_log.jsonl
```

---

*Ten dokument jest zywym dokumentem - aktualizuj go przy zmianach architektonicznych.*
*Ostatnia aktualizacja: 2026-03-29 (K1-K13 complete, Stabilization 6 phases, Faza F, 2448 tests)*
