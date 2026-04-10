# M.A.R.I.A. - Kontekst dla Claude Code

> Ten plik jest automatycznie czytany przez Claude Code na starcie sesji.

## Historia projektu

| Data | Wydarzenie |
|------|------------|
| **2025-11-14** | Początek projektu M.A.R.I.A. |
| 2025-11 → 2026-01 | Rozwój z 4 różnymi LLM, ręczne sklejanie kodu |
| **2026-01** | Homeostasis - pierwszy moduł z pomocą Claude |
| **2026-02-01** | Specyfikacje: Code Agent, Web UI, Consciousness |
| **2026-02-01** | Introspection module + Vision spec + Folder cleanup |
| **2026-02-02** | TimeAwareness + Smart Home spec |
| **2026-02-22** | Linux migration prep (Mini PC) |
| **2026-02-22** | **DEPLOY na Mini PC** - Maria dziala produkcyjnie! |
| **2026-02-23** | SSH hardening + WireGuard VPN + NVIDIA NIM API |
| **2026-02-25** | Self-Awareness (ContextBuilder) + /awareness REPL + Web UI learning queue |
| **2026-02-27** | Consciousness Phase C: personality, dreams, conversation memory |
| **2026-02-27** | Agent Nauczyciel + autonomiczny trigger w homeostasis |
| **2026-03-01** | Kontrakty K1-K4: Perception, Sandbox, Goals, Evaluation |
| **2026-03-01** | Warstwa 2: Planner (K5) - ReAct loop laczacy K1-K4 |
| **2026-03-01** | K5.1 Topic-Aware Learning - Maria wybiera tematy nauki |
| **2026-03-08** | ADR-014: Najpierw mozg (K6-K10), potem zmysly (Vision, Smart Home) |
| **2026-03-08** | Stabilizacja: 4 bugi planner naprawione, daemon `run_maria.py` dziala |
| **2026-03-08** | Web Source module (Wikipedia PL + RSS) - zbudowany i podlaczony |
| **2026-03-11** | K6 World Model / Belief System (69 testow) |
| **2026-03-18** | OOM crash fix - infinite loop w intelligent_chunk_text() |
| **2026-03-19** | K7 Autonomy Policy (45 testow) + K8 Deliberation (49 testow) |
| **2026-03-20** | K9 Meta-Cognition (73 testy) + K10 Action Safety (52 testy) - **Cognitive Core COMPLETE** |
| **2026-03-21** | Bug fixes (exam score, beliefs, deliberation) + Storage Manager + 6TB disk |
| **2026-03-21** | K11 Experiment System (67 testow) - autonomiczny tuning parametrow |
| **2026-03-21** | Architecture Map - interaktywna mapa modulow w Web UI |
| **2026-03-21** | Model Registry v1.1 + Deployment Order v1.1 (multi-organ local model stack) |
| **2026-03-21** | OpenClaw research - potwierdzona integracja jako efektor (tools/invoke bez LLM) |
| **2026-03-21** | ModelScheduler - multi-organ model stack infrastructure (75 testow) |
| **2026-03-21** | OpenClaw Effector Client - HTTP client + planner integration (47 testow) |
| **2026-03-22** | Bug fixes: TeacherAgent stats reset + spaced repetition exam loop |
| **2026-03-22** | OpenClaw LIVE: subprocess client, gateway+node, model separation (qwen2.5:3b) |
| **2026-03-22** | Model Registry v2: qwen3:8b planner, rule-based triage (benchmark done) |
| **2026-03-22** | Routing rules: PL+EN keywords, +LEARN/EXAM categories (38%->100% accuracy) |
| **2026-03-22** | **Web UI v2 Metaoperator Panel** - 8-panel command deck, design system, base template |
| **2026-03-22** | Markdown learning fallback - Maria parsuje odpowiedzi LLM w dowolnym formacie |
| **2026-03-22** | OpenClaw lightweight check (pgrep) - fix CPU saturation from health_check |
| **2026-03-22** | Material edukacyjny o LLM - 12 chunkow, Maria przyswoila autonomicznie |
| **2026-03-22** | **K12 Self-Analysis** - zamkniecie petli poznawczej (45 testow) |
| **2026-03-24** | K12 LIVE: 5 bugow naprawionych, Maria analizuje sie sama (qwen3:8b, 3 rekomendacje) |
| **2026-03-24** | Fix: teacher file_id passthrough + chunk failure backoff (skip po 5 failach) |
| **2026-03-24** | Fix: planner fallthrough - NOOP/K7-blocked -> evaluate -> K12 (zamiast slepego NOOP) |
| **2026-03-24** | Creative Module spec received (docs/plans/) - 19 plikow, pelny organ strategiczny |
| **2026-03-25** | **K13 Creative Module** - strategic reflection organ, tension detection, meta-goals (67 testow) |
| **2026-03-25** | K13 LIVE: 3 tensions detected (repetition, misalignment, over_restriction), 42ms/cycle |
| **2026-03-25** | **K13 Phase 2** - LLM engines (NIM API, 40 RPM): meta_goal, reframe, exploration (62 testow) |
| **2026-03-25** | TokenBudget: RPM-based gating (bylo: token-based), identity_profile, personality_policy |
| **2026-03-25** | K13 Phase 2 LIVE: NIM wired, 1943 testow |
| **2026-03-25** | K12 Phase 2: NIM backend + Web UI /analysis page |
| **2026-03-26** | **Telegram Bridge (ClawBot)** - Maria pisze do operatora, komendy /status /goals /approve /reject /restart (42 testy) |
| **2026-03-26** | K7 improvements: consecutive failure auto-reset (30min), fetch 5->10/h, proposed timeout 24->72h |
| **2026-03-26** | Zmiany zasugerowane przez creative module Marii (NIM-powered tension detection) |
| **2026-03-27** | **Meta-goal priority escalation** - tension streaks, priority boost, PROPOSED displacement, /priority command (23 testy) |
| **2026-03-27** | **Semantic Memory** - nomic-embed-text (768-dim), vector store, auto-indexer, 275 vectors (39+18 testow) |
| **2026-03-27** | SemanticMemory wired: TopicSuggester (novelty rerank) + MemoryRetriever (embedding search) |
| **2026-03-27** | Incremental indexing - nowe pliki auto-embeddowane po fetch |
| **2026-03-27** | Startup delay (60s) - unika CPU spike i REDUCED mode po restarcie |
| **2026-03-28** | **Phase 1 Tracing** - episode-based decision traceability, correlation IDs (25 testow) |
| **2026-03-28** | Episode ID flows: planner -> LLM tape -> K7 -> K10 (thread-local auto-read) |
| **2026-03-28** | Web UI /api/traces + Telegram /trace command |
| **2026-03-28** | Stabilization Roadmap received (ChatGPT, 6 phases, gate model A-E) |
| **2026-03-28** | **Phase 2 Memory Consistency** - MemoryQuery API, staleness fixes, re-indexing (24 testow) |
| **2026-03-28** | Grounding: "co wiesz o X" -> GROUNDED_KNOWLEDGE -> evidence z MemoryQuery |
| **2026-03-28** | Web UI /api/memory/query + Telegram /memory + beliefs rebuild po LEARN |
| **2026-03-28** | **CDL in Web UI** - Conversation-Driven Learning podpiete w Web UI chat |
| **2026-03-28** | LLM call counting w traces (total_llm_calls, models_used, latency) |
| **2026-03-29** | **Phase 5 Effector Safety Envelope** - 5-level authority (OBSERVE/SUGGEST/CONFIRM/BOUNDED), approval queue, anti-cascade (190 testow) |
| **2026-03-29** | ApprovalQueue HITL: /efapprove, /efreject, /efstatus, /authority (Telegram) |
| **2026-03-29** | ToolBudgetManager: per-tool rate limits, exponential backoff, duplicate detection |
| **2026-03-29** | **Phase 6 Readiness Review** - stability tests, authority drills, 15-point checklist |
| **2026-03-29** | **Stabilization Roadmap COMPLETE** (all 6 phases, all 5 gates A-E passed) |
| **2026-03-29** | Cleanup: 3153 linii martwego kodu usuniete z maria_core/ |
| **2026-03-29** | Fix: flaky test_time_awareness + LLM call counting w OllamaBrain |
| **2026-03-29** | **Faza F: Multi-Source Learning** - CrossValidator, ConfidenceScorer, DisputeLog (38 testow) |
| **2026-03-29** | Faza F: planner trigger (_maybe_validate, 6h cooldown), belief confidence update, K7 GUARDED |
| **2026-03-29** | Web UI /validation page + Telegram /validate command |
| **2026-03-29** | Roadmap v1.0 - aktualizacja do aktualnego stanu (K1-K13, Stabilization, Faza F) |
| **2026-03-29** | **Belief Store v2** - evidence tracking, compaction, smart pruning, confidence decay, dedup (28 testow) |
| **2026-03-29** | Belief maintenance wired: planner EVALUATE -> maintain(), Telegram /beliefs, Web UI /api/beliefs |
| **2026-03-29** | **Capability/Task Router** - unified registry-based dispatch replacing 13-way if/elif (63 testow) |
| **2026-03-30** | **Faza G: Agent Krytyk** - knowledge quality gate, 7 wymiarow analizy, READ-ONLY critic (69 testow) |
| **2026-03-31** | **Learning Upgrade Phase 1-3** - BulletinStore, KnowledgeAuditor, GapPlanner (57 testow) |
| **2026-04-01** | **Learning Upgrade Phase 4-5** - ExpertBridge (audit-aware expert queries), full wiring to input/ (42 testow) |
| **2026-04-02** | Fix: deliberation case mismatch (NOOP loop na meta-goalach) |
| **2026-04-02** | **Critique UI** - REPL /critique + Web UI /critique page (3 taby, 4 API endpoints, 14 testow) |
| **2026-04-02** | Phase C cleanup - ActionExecutor if/elif -> _ACTION_MAP lookup |
| **2026-04-02** | **Auto-confirm** - low risk goals z creative/critic/self_analysis skip /approve (8 testow) |
| **2026-04-02** | **K11 trigger** - _maybe_experiment_scan() co 4h w planner loop |
| **2026-04-02** | **BeliefStore v3** - importance-based pruning (type weight + evidence strength) |
| **2026-04-02** | **NOOP detection** - EvidenceCollector wykrywa stuck planner, surfaced w chacie |
| **2026-04-02** | **CDL v3** - operational commands w Web UI chat ("zrob fetch", "uruchom krytyke") + async feedback (17 testow) |
| **2026-04-02** | **Claude + Codex backends** - /claude (3/h) + /code (10/h) + /analyze komendy Telegram |
| **2026-04-02** | **Telegram file upload** - PDF/MD/TXT/PY -> docs/incoming/, caption jako komenda |
| **2026-04-02** | **Kamera** - Innomaker U20CAM-1080PD&N-S1 zweryfikowana, Vision ODBLOKOWANA |
| **2026-04-05** | **Vision Phase 1-4** - sensor, preprocessing, modules, cortex (297 testow) |
| **2026-04-05** | **V3 Phase A Module 1** - UnifiedLauncher (maria.py) - single entry point |
| **2026-04-05** | **V3 Phase A Module 2+3** - OnboardingFlow + UserFacingSelfModel (65 testow) |
| **2026-04-05** | **V3 Phase B Module 4-6** - TaskOrchestrator + TaskDecomposer + ExecutionPlanBuilder (70 testow) |
| **2026-04-05** | **V3 Phase C Module 7-9** - CostEstimator + TimeEstimator + FreeVsPaidPlanner (49 testow) |
| **2026-04-05** | **V3 Phase D Module 10-13** - ExecutionRouter + ToolRegistry + ProgressTracker + LimitationReporter (41 testow) |
| **2026-04-05** | **V3 Phase E Module 14-15** - ProductShell + V3Module REPL /v3 (26 testow) - **V3 COMPLETE** |
| **2026-04-06** | **Vision wiring** - homeostasis tick (Phase 8.5), REPL /vision, Web UI /api/vision/*, LLaVA on-demand |
| **2026-04-06** | **NIM chat routing** - regular chat via NIM, grounded queries via Ollama |
| **2026-04-06** | **Grounded Vision** - "co widzisz?" -> EvidenceCollector -> LLaVA describe_scene |
| **2026-04-07** | **Task Pipeline** - TaskStore JSONL persistence for /claude /codex /analyze (22 testow) |
| **2026-04-07** | **PDF Export** - auto PDF via Telegram, /tasks, /pdf commands, send_document (13 testow) |
| **2026-04-07** | Timeout fix: 3min -> 5min, explicit error messages, startup cooldown 1h -> 6h |
| **2026-04-07** | **V3 Migration** - maria.py full mode (daemon+UI), maria-ui.service disabled |
| **2026-04-07** | Critic bugfix: max() empty sequence + timestamp type coercion |
| **2026-04-10** | Task Pipeline Web UI + UserProfile (operator memory) |
| **2026-04-10** | **Master Prompt** - single source of truth for all LLM paths (OllamaBrain, NIM, WebUI, Claude, Codex) |
| **2026-04-10** | **Reminders & Todos** - time-triggered notifications, PL/EN time parser, REPL + Telegram + tick scheduler (83 testow) |

## Aktualny stan projektu

| Aspekt | Wartość |
|--------|---------|
| **Branch** | `refactor/homeostasis` |
| **Etap** | K1-K13 Phase 2 + Vision + **V3 DEPLOYED** (maria.py full mode) |
| **Testy** | ~3435 passing |
| **Faza** | Stabilization + Faza F/G + Learning Upgrade + CDL v3 + V3 + Task Pipeline + PDF Export |
| **Runtime** | `maria.py` (daemon + Web UI, one process, systemd) |
| **Event Log** | `meta_data/homeostasis_events.jsonl` |

## Co to jest M.A.R.I.A.?

**M.A.R.I.A.** (Meta Analysis Recalibration Intelligence Architecture) - lokalny, autonomiczny agent AI do samodzielnego uczenia się z plików tekstowych.

- **Backend LLM:** Ollama (llama3.1:8b)
- **Tryb pracy:** Offline-first
- **Język:** Python 3.8+

## Struktura projektu

```
project/
├── maria.py             # V3 UnifiedLauncher (daemon + Web UI + onboarding)
├── main.py              # REPL interface (Ver.1.2)
├── run_maria.py         # Daemon mode (legacy, replaced by maria.py)
├── maria_core/          # Legacy modules
│   ├── brain/           # ollama_brain.py
│   ├── learning/        # learning_agent.py, exam_agent.py
│   ├── memory/          # memory_store.py, semantic_graph.py
│   ├── perception/      # perception.py
│   └── sys/             # config.py, meta_controller.py, resource_watchdog.py
├── agent_core/          # NEW: Homeostasis + subsystems
│   ├── homeostasis/     # Core homeostasis (sensors, constraints, mode_regulator)
│   ├── consciousness/   # Personality, dreams, conversation memory
│   ├── teacher/         # Autonomous learning agent (P1-P6)
│   ├── perception/      # Unified Perception (K1): events, buffer, 6 adapters
│   ├── sandbox/         # Sandbox/Production boundary (K2): manager, protocol
│   ├── goals/           # Goal System (K3): model, store, audit trail
│   ├── evaluation/      # Agent Evaluation (K4, READ-ONLY): observer, report
│   ├── planner/         # Planner (K5): ReAct loop, guard, goal selector, executor
│   ├── world_model/     # World Model (K6): beliefs, store, builder, query
│   ├── autonomy/        # Autonomy Policy (K7): classification, rate limiter, rules, escalation
│   ├── deliberation/    # Deliberation (K8): strategy, templates, deliberator, intent tracker
│   ├── meta_cognition/  # Meta-Cognition (K9): reflection, confidence, assumptions
│   ├── action_safety/   # Action Safety (K10): audit log, effect validation, classification
│   ├── experiment/      # Experiment System (K11): proposals, runner, reports, parameter tuning
│   ├── storage/         # Storage Manager: log archival, daily summaries (6TB disk)
│   ├── web_source/      # Web Content Fetcher: Wikipedia PL + RSS (podlaczony do planner)
│   ├── introspection/   # Code self-awareness (READ-ONLY) + Architecture Map data source
│   ├── memory/          # MemoryManager interface
│   ├── llm/             # LLMManager + NIM routing + ModelScheduler + model_registry + master_prompt
│   ├── self_analysis/   # K12 Self-Analysis: state collector, analyzer, recommendation applier
│   ├── creative/        # K13 Creative Module Phase 2: tensions, insights, meta-goals, LLM engines (NIM)
│   ├── telegram/        # Telegram Bridge (ClawBot): operator notifications + commands
│   ├── effector/        # OpenClaw client (ADR-016): HTTP tools/invoke, whitelist, validation
│   ├── semantic/        # Semantic Memory: nomic-embed-text, vector store, auto-indexer
│   ├── bulletin/        # Learning Upgrade: BulletinStore, KnowledgeAuditor, GapPlanner, ExpertBridge
│   ├── critic/          # Faza G: Agent Krytyk - knowledge quality gate (7 dimensions)
│   ├── reminders/       # Reminders & Todos: time-triggered notifications, task tracking
│   ├── routing/         # Capability/Task Router: registry-based dispatch, handler factories
│   ├── tracing/         # Phase 1 Tracing: episode_id, DecisionTrace, TraceStore (ADR-022)
│   ├── vision/          # Vision: sensor abstraction, preprocessing, motion, scene, cortex
│   ├── orchestrator/    # V3 Orchestrator: OnboardingFlow, UserFacingSelfModel, TaskOrchestrator, TaskDecomposer, ExecutionPlanBuilder
│   ├── adapters/        # Wrappers for legacy maria_core
│   └── tests/           # 3317 tests
└── docs/                # Documentation (incl. MODEL_REGISTRY, DEPLOYMENT_ORDER)
```

## Kluczowe pliki do przejrzenia

| Plik | Opis |
|------|------|
| `docs/REFACTOR_PLAN.md` | 5-etapowy plan migracji (aktualnie etap 4 done) |
| `docs/ROADMAP.md` | Fazy A/B/C rozwoju |
| `docs/ARCHITECTURE.md` | Diagram warstw i przepływu danych |
| `docs/MAP_HOMEOSTASIS.md` | Mapa wymagan spec → moduly |
| `docs/CODE_AGENT_SPEC.md` | **Specyfikacja zewnętrznego agenta kodującego** |
| `docs/WEB_UI_SPEC.md` | **Specyfikacja Web UI (Flask + WebSocket)** |
| `docs/CONSCIOUSNESS_SPEC.md` | **Specyfikacja swiadomosci, osobowosci, snow** |
| `docs/VISION_SPEC.md` | **Specyfikacja percepcji wizualnej (oko)** |
| `docs/SMART_HOME_SPEC.md` | **Specyfikacja IoT / Smart Home** |
| `docs/CONTRACTS.md` | **Kontrakty architektoniczne (K1-K11)** |
| `docs/MODEL_REGISTRY.md` | **Multi-organ local model stack (5 ról, RAM tiers, mutex)** |
| `docs/DEPLOYMENT_ORDER.md` | **7-stage deployment z benchmarkami i rollback** |
| `docs/CHANGELOG.md` | Historia zmian |

## Homeostasis - nowy system

System homeostazy (w `agent_core/`) zarządza autonomiczną pracą agenta:

- **Sensors:** resource, cognitive, thermal, power, time
- **Mode Regulator:** ACTIVE → REDUCED → SLEEP → SURVIVAL
- **1Hz tick loop:** sense → interpret → validate → decide → act
- **Event Logger:** Persistent JSONL logging of all events
- **REPL commands:**
  - `/homeostasis` - status
  - `/homeostasis start/stop` - control loop
  - `/homeostasis events N` - show last N events
  - `/homeostasis summary` - session summary

## Code Introspection - samowiedza kodu

System introspekcji (w `agent_core/introspection/`) pozwala Marii rozumiec swoja wlasna architekture:

- **READ-ONLY:** Tylko odczyt kodu, nigdy modyfikacja
- **Analyzer:** Statyczna analiza AST plikow Pythona
- **CodeModel:** Struktury danych self-model
- **Reporters:** Human + Technical output (dual format)
- **Scheduler:** Okresowa analiza (domyslnie co 1h)
- **Output:** `meta_data/code_self_model.json`
- **REPL commands:**
  - `/introspect` - jak jestem zbudowana (human summary)
  - `/introspect detail` - szczegolowy raport techniczny
  - `/introspect issues` - problemy w kodzie (TODO/FIXME)
  - `/introspect module X` - info o module X
  - `/introspect layers` - warstwy architektury
  - `/introspect start/stop` - okresowa analiza w tle
- **Web UI API (real-time):**
  - `GET /api/introspect` - pelne dane samowiedzy
  - `GET /api/introspect/issues` - lista problemow
  - `POST /api/introspect/refresh` - wymus nowa analize

## Consciousness - swiadomosc i osobowosc

System swiadomosci (w `agent_core/consciousness/`) daje Marii osobowosc i ciaglosc:

- **TraitEvolver + TraitCatalog:** 7 cech osobowosci z dynamiczna ewolucja (rozszerzalne)
- **ConversationMemory:** Rolling context z kondensacja LLM
- **SleepProcessor + DreamGenerator:** Konsolidacja pamieci podczas SLEEP
- **ExperienceTracker:** Kontekst emocjonalny z rozmow
- **IdentityStore:** Ciaglosc miedzy sesjami (session count, uptime, birth date)
- **REPL:** `/consciousness` - status osobowosci i swiadomosci

## Agent Nauczyciel - autonomiczna nauka

System nauczania (w `agent_core/teacher/`) decyduje co i kiedy sie uczyc:

- **TeacherAgent:** 6-priorytetowy silnik decyzyjny (P1-P6)
- **KnowledgeAnalyzer:** Analiza JSONL, zero wywolan LLM
- **SpacedRepetitionScheduler:** Interwaly powtórek na bazie wyników
- **Autonomiczny trigger:** Homeostasis Phase 9 - po 10min idle w ACTIVE
- **REPL commands:**
  - `/teacher [N]` - sesja nauki (N iteracji)
  - `/teacher status` - status agenta
  - `/teacher plan` - podglad nastepnego kroku
  - `/teacher history` - historia planow

## Kontrakty architektoniczne (K1-K10) - COMPLETE

Formalne specyfikacje zaimplementowane w `docs/CONTRACTS.md`:

- **K1 Unified Perception:** PerceptionEvent (frozen dataclass), 8 source types, 24 event types, PerceptionBuffer (deque maxlen=200), 6 adapterow, tick aggregator (ADR-009)
- **K2 Sandbox:** Izolowane sesje nauki, promote() jako jedyny most do produkcji, transaction log (START/COMMIT/ROLLBACK), startup recovery
- **K3 Goal System:** 4 typy celow (META/USER/LEARNING/MAINTENANCE), 6 statusow, audit trail, max 20 aktywnych, PROPOSED flow z izolacja
- **K4 Evaluation:** READ-ONLY observer, 5 metryk (learning_velocity, retention_rate, knowledge_coverage, system_stability, personality_growth), threshold-based recommendations, zero LLM
- **K5 Planner:** Rule-based ReAct loop (ADR-013), PlannerGuard (5 gating rules), GoalSelector (aging factor), ActionExecutor (delegacja do Teacher), hybrid frequency (60 ticks + event-driven), persystencja (planner_state.json + planner_decisions.jsonl)
- **K5.1 Topic-Aware Learning:** KnowledgeAnalyzer topic map + scoring, TeacherAgent filter_file_ids, auto-goal creation, /plan learn|topics REPL
- **K6 World Model:** Belief system (frozen dataclass), BeliefStore (JSONL, cap 2000, MERGE), BeliefBuilder (from existing JSONL), query API, WorldModel facade
- **K7 Autonomy Policy:** ActionClassification (FREE/GUARDED/RESTRICTED/FORBIDDEN), rate limiter (sliding window per ActionType), PolicyEngine (3 rules), EscalationHandler (JSONL log, HITL placeholder), AutonomyPolicy facade
- **K8 Deliberation:** Multi-step strategies (Strategy+Step dataclasses), 3 templates (learn_topic, explore_new, consolidate), Deliberator (rule-based selection+advancement), IntentTracker (JSONL intents), Deliberation facade
- **K9 Meta-Cognition:** ReflectionRecord (assumption tracking), ReflectionStore (JSONL, 300 cap), ConfidenceTracker (exponential decay), Reflector (before/after, pattern detection), MetaCognition facade, needs_human() signal
- **K10 Action Safety:** SafetyMode(3), SafetyProfile per action type, AuditLog (JSONL, 200 cap), EffectValidator (before/after state capture), ActionSafety facade, safe-by-default (unknown=STAGED)

- **K11 Experiment System:** Proposal engine (4 rules), parameter registry (12 params), experiment runner (setattr+restore), report generator (ADOPT/REJECT/INCONCLUSIVE), ExperimentSystem facade, human gate (PROPOSED goals), REPL /experiments, Web UI /experiments

- **K12 Self-Analysis (Phase 2):** StateCollector (8 JSONL sources, zero LLM), ExternalAnalyzer (cascade: NIM API -> Claude CLI -> local_planner qwen3:8b), RecommendationApplier (PROPOSED goals + topic hints + beliefs), SelfAnalysis facade, triggers (24h periodic + K9 needs_human + low retention), planner ActionType.SELF_ANALYZE, K7 GUARDED, K10 AUDIT_ONLY, Web UI /analysis (3 taby + 4 API endpoints)

- **K13 Creative Module (Phase 2):** StrategicContext (6 data sources), TensionDetector (7 categories), ReflectionWorkspace (bounded sessions), CreativeJournal (strategic diary), NoveltyFilter (dedup+flood), CreativeEvaluator (5 dimensions, custom weights), GoalAdapter (K3 PROPOSED), CreativeStore (6 JSONL), facade (15-step reflect cycle), ConversationMemory (operator dialogue), K7 GUARDED, K10 AUDIT_ONLY, planner Step 2.5. **Phase 2:** MetaGoalEngine (NIM+fallback), ReframeEngine (NIM+fallback), ExplorationEngine (NIM+fallback), IdentityProfile (CognitiveProfile), PersonalityPolicy (trait->weight adjustment), MemoryRetriever (keyword-based), MemorySummarizer (NIM+fallback), llm_utils (JSON parser). TokenBudget: RPM-based gating (40 req/min)

Wszystko podlaczone w `homeostasis_module.py init()` i `SharedContext`. **Cognitive core K1-K13 kompletny (1876 testow).**

## Semantic Memory (2026-03-27)

Embedding-based similarity search replacing keyword retrieval (w `agent_core/semantic/`):

- **Model:** nomic-embed-text:latest (274MB, 768-dim vectors) via Ollama /api/embed
- **MODEL-05:** Updated in model_registry (was shared llama3.1:8b placeholder)
- **EmbeddingModel:** Ollama wrapper, in-memory cache, batch embed, cosine similarity
- **VectorStore:** In-memory dict + JSONL persist (`meta_data/semantic_vectors.jsonl`), namespace support, cap 10k
- **SemanticMemory facade:** index_text/batch, search, find_similar, 4 namespaces
- **Auto-indexer:** Background indexing at startup (60s delay to avoid CPU spike)
  - 157 knowledge entries (from knowledge_index + input file titles)
  - 95 beliefs (from K6 world model)
  - 23 hints (from K12 self-analysis)
- **Incremental indexing:** New files auto-embedded after fetch actions
- **Namespaces:** knowledge, beliefs, hints, memories
- **Clients:**
  - TopicSuggester: `set_semantic_memory()` + `_semantic_rerank()` (novelty scoring)
  - MemoryRetriever: `set_semantic_memory()` + `_semantic_retrieve()` (embedding search with keyword fallback)
- **Wiring:** homeostasis init -> SharedContext.semantic_search -> creative + planner executor
- **ADR-021:** Embeddings replace keyword retrieval (skip patching old semantic_graph.py)
- **57 testow** (39 semantic + 18 indexer)

## Meta-goal Priority Escalation (2026-03-27)

Repeated tensions now escalate meta-goal priority:

- **Tension streak tracking:** `CreativeStore.record_tensions()` + `get_tension_streak()` - JSONL: `creative_tension_streaks.jsonl`
- **Priority boost:** `ReflectionWorkspace.generate_candidates()` - streak * 0.05, max +0.2
- **PROPOSED displacement:** `GoalStore.propose()` replaces lowest-priority PROPOSED when higher arrives
- **Telegram /priority:** `/priority <id-prefix> <0.0-1.0>` - operator manual override
- **Improved /goals:** Shows ID prefix + priority + stats for all goals
- **23 testow**

## Phase 1 Tracing - Decision Traceability (2026-03-28)

Episode-based correlation IDs across cognitive episodes (w `agent_core/tracing/`):

- **ADR-022:** Thread-local episode_id, backward compatible
- **episode.py:** generate_episode_id() -> thread-local via threading.local()
- **trace_model.py:** DecisionTrace (full episode) + TraceStep (subsystem decision point)
- **trace_store.py:** JSONL persistence (`meta_data/decision_traces.jsonl`), bounded 200 in-memory
- **Episode ID auto-read:** LLM tape, K7 escalation, K10 audit - all read from thread-local
- **Planner:** run_cycle() generates episode_id, Plan.trace_id set, trace steps collected
- **Wiring:** homeostasis_module.py -> TraceStore -> PlannerCore.set_trace_store()
- **Web UI:** `/api/traces`, `/api/traces/<id>`, `/api/traces/stats`, `/api/traces/failed`
- **Telegram:** `/trace [N|stats|failed|ep-ID]`
- **Stabilization Roadmap:** `docs/plans/MARIA_full_scale_stabilization_roadmap.pdf` (6 phases, gate model A-E)
- **LLM counting:** total_llm_calls, models_used, total_llm_latency_ms via thread-local trace ref
- **25 testow**

## Phase 2 Memory Consistency (2026-03-28)

Unified memory query with provenance (w `agent_core/memory/query.py`):

- **ADR-023:** Unified memory query with provenance metadata
- **MemoryQuery:** query_topic(), get_topic_summary(), get_knowledge_gaps()
- **Truth hierarchy:** knowledge_index (primary) > beliefs (derived) > semantic vectors
- **Each result:** source, confidence (0-1), freshness (0-1), relevance (0-1), provenance dict
- **Grounding:** GROUNDED_KNOWLEDGE mode - "co wiesz o X" -> EvidenceCollector -> MemoryQuery
- **Staleness fixes:**
  - Vector cleanup: `cleanup_stale_vectors()` at startup (removes vectors for deleted files)
  - Beliefs rebuild after LEARN (was: only after EVALUATE every hour)
  - Incremental re-indexing after LEARN (update embeddings with new status)
- **Web UI:** `/api/memory/query?topic=X`, `/api/memory/gaps`
- **Telegram:** `/memory <topic>`, `/memory gaps`
- **CDL in Web UI:** learning intent detection in Web UI chat (goal creation)
- **Wiring:** homeostasis_module.py -> MemoryQuery -> SharedContext + EvidenceCollector
- **24 testow** (test_memory_query.py)

## Telegram Bridge - ClawBot (2026-03-26, updated 2026-04-07)

Komunikacja Maria <-> operator przez Telegram (w `agent_core/telegram/`):

- **Bot:** ClawBot (Telegram @BotFather), token w `.env`
- **TelegramBot:** send_message + send_document + get_updates via requests (zero nowych deps)
- **TelegramNotifier:** 7 typow alertow z cooldownami per kategoria, startup cooldown 6h
- **TelegramBridge:** facade + command handler
- **Komendy:**
  - `/status` - stan systemu (mode, health, planner, knowledge, goals)
  - `/goals` - lista celow (active + proposed)
  - `/approve <id>` - zatwierdz proposed goal
  - `/reject <id>` - odrzuc proposed goal
  - `/claude <task>` - Claude Code CLI (3/h, 15/day, 5min timeout)
  - `/codex <task>` - Codex/ChatGPT (10/h, 5min timeout)
  - `/analyze <modul>` - analiza kodu via Codex
  - `/tasks [N]` - historia taskow Claude/Codex z ID i statusem
  - `/pdf <task_id>` - re-export wyniku jako PDF
  - `/restart` - restart Marii (systemd wskrzesi po 10s)
  - `/help` - lista komend
- **Task Pipeline (2026-04-07):**
  - TaskStore: `agent_core/llm/task_store.py` - JSONL persistence (`meta_data/claude_tasks.jsonl`)
  - Lifecycle: PENDING -> RUNNING -> COMPLETED/FAILED/TIMEOUT/INTERRUPTED
  - Recovery: `recover_interrupted()` at startup, operator notified
  - PDF Export: `agent_core/telegram/pdf_export.py` (fpdf2 + DejaVu, polskie znaki)
  - Auto PDF: kazdy wynik Claude/Codex wysylany jako dokument PDF
  - 35 testow (22 task_store + 13 pdf_export)
- **Maria powiadamia o:**
  - Napieciach creative (K13) - co 2h
  - Rekomendacjach K12 self-analysis - co 4h
  - K9 needs_human - co 1h
  - Health drop - co 30min
  - Zmiana trybu (degradacja) - co 10min
  - Blokada K7 consecutive failures - co 1h
  - Startup (cooldown 6h)
- **Integracja:** Phase 11 w tick loop (poll co tick), notify w action_executor (K13/K12)
- **Config:** `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` w `.env`
- **77 testow** (42 telegram + 35 task/pdf)

## Planner - Warstwa 2 (K5)

System planowania (w `agent_core/planner/`) - pierwsza "warstwa sprawcza":

- **PlannerCore:** Centralny ReAct loop (OBSERVE -> THINK -> ACT -> EVALUATE)
- **PlannerGuard:** 5 gating rules (health, mode, sandbox, retention, teacher)
- **GoalSelector:** Aging factor (priority *= 1 + hours * 0.1), feasibility check
- **ActionExecutor:** Delegacja do Teacher/Sandbox/Observer
- **Hybrid frequency:** Co 60 tickow + event-driven (exam_result, alert, user_command, sandbox_promoted)
- **Zastepuje Phase 10:** Teacher trigger z backward-compatible fallbackiem
- **Persystencja:** planner_state.json + planner_decisions.jsonl
- **ADR-013:** Rule-based v1, zero LLM, deterministic, testable
- **REPL commands:**
  - `/plan` - ostatnia decyzja
  - `/plan status` - cykle, plany, ostatni eval
  - `/plan history [N]` - historia decyzji
  - `/plan goals` - ranking celow wg effective priority

## K11 Experiment System (2026-03-21) - COMPLETE

System autonomicznego tuningu parametrow (w `agent_core/experiment/`):

- **ProposalEngine:** 4 reguly (LOW_RETENTION, CONSECUTIVE_FAILURES, HIGH_COVERAGE, SLOW_EXECUTION)
- **ParameterRegistry:** 12 parametrow z bounds, risk levels, impact metrics
- **ExperimentRunner:** setattr patch, health guard (0.8/0.9), timeout 1h, restore ALWAYS (finally)
- **ReportGenerator:** delta metryki, ADOPT/REJECT/INCONCLUSIVE, confidence scoring
- **ExperimentSystem facade:** scan -> approve -> run -> report pipeline
- **Human gate:** Reuse K3 PROPOSED goals, Eryk zatwierdza/odrzuca
- **Planner:** ActionType.EXPERIMENT, build_experiment template (K8)
- **K7:** GUARDED + rate limit 1/h
- **K10:** AUDIT_ONLY + EffectType.CONFIGURATION
- **REPL commands:**
  - `/experiments` - lista propozycji i raportow
  - `/experiment approve <id>` - zatwierdz propozycje
  - `/experiment reject <id>` - odrzuc
  - `/experiment status` - aktualny eksperyment
  - `/experiment report <id>` - pokaz raport
  - `/experiment params` - lista parametrow do tuningu
  - `/experiment comment <id> <text>` - dodaj uwage
- **Web UI:** `/experiments` - 3 taby (Propozycje, Raporty, Parametry) + 12 API endpoints
- **67 testow**

## Architecture Map (2026-03-21)

Interaktywna mapa modulow w Web UI (read-only, zero wplywu na runtime):

- **URL:** `http://192.168.178.32:5000/architecture`
- **3 widoki:**
  - **Graf** - force-directed graph pakietow, krawedzie = importy, drill-down do funkcji
  - **Pipeline** - 15 krokow decyzyjnych (SENSE -> ... -> K6 UPDATE)
  - **Data Flow** - 15 plikow JSONL z writerami i readerami
- **Funkcje:** search, click-to-detail, connected highlight, zoom/drag
- **Dane:** z CodeAnalyzer AST (194 pliki, 39k linii, 822 zaleznosci)
- **Cel:** ulatwienie nawigacji dla przyszlych agentow i ludzi

## Storage Manager (2026-03-21)

System archiwizacji logow (w `agent_core/storage/`):

- **LogArchiver:** przenosi stare rekordy JSONL -> /mnt/storage/data/logs/
- **DailySummary:** kompakcja do dziennych podsumowań -> /mnt/storage/data/summaries/
- **Integracja:** z SleepProcessor (faza archiwizacji przed REM)
- **Dysk:** 6TB ext4 "maria-storage" zamontowany na /mnt/storage/
- **Backup:** 30 kopii zamiast 7

## Model Registry v2 + ModelScheduler (2026-03-22, DEPLOYED)

Multi-organ local model stack zaimplementowany w `agent_core/llm/`:

- **MODEL-01:** Strategic Planner (qwen3:8b, 5.5GB, cold) - upgraded po benchmark
- **MODEL-02:** Executor (llama3.1:8b, 5GB, warm) - core brain
- **MODEL-03:** Coder (qwen2.5-coder:7b, 5GB, cold)
- **MODEL-04:** Triage = rule-based classifier (0GB, 0.1ms) - LLM przegral benchmark
- **MODEL-05:** Memory (shared on MODEL-02, future: nomic-embed-text, cold)
- **MODEL-06:** NIM external API (z-ai/glm5, 0GB, expiry Aug 2026)
- **OpenClaw:** qwen2.5:3b (2GB, cold) - osobna instancja efektora
- **Golden rule:** MODEL-02 warm, reszta on-demand
- **Heavy model mutex:** MODEL-01 i MODEL-03 nigdy jednoczesnie
- **Benchmark (2026-03-22):** qwen3:8b > llama3.1:8b na reasoning, rule-based > qwen3:1.7b na triage

### Implementacja (`agent_core/llm/`):
- **model_registry.py:** ModelRole(6), ModelSpec (frozen dataclass), statyczny REGISTRY, RAM tiery
- **model_scheduler.py:** ModelScheduler - load/unload via Ollama, RAM guard (psutil), heavy mutex (threading.Lock), idle timeout, health persist (model_health.json), tick() w homeostasis loop
- **routing_rules.py:** TaskType(8) -> ModelRole mapping, heuristic_classify (keyword-based fallback)
- **router.py rozszerzony:** ask_as_role(role, prompt) - scheduler laduje model, inference, release
- **Wiring:** SharedContext.model_scheduler, HomeostasisCore Phase 9.5, auto-register MODEL-02 na starcie
- **75 testow** (all mocked, zero external deps)

## OpenClaw Effector (2026-03-22, LIVE)

OpenClaw jako efektor pod kontrola Marii - **dzialajacy na produkcji**:

- **Integracja:** Subprocess via `sudo -u deployadmin openclaw` (nie HTTP)
- **Node tools:** exec, read, write -> `openclaw nodes run --security full --json`
- **Agent tools:** web_fetch, web_search, message, cron -> `openclaw agent --json`
- **Klient:** `agent_core/effector/openclaw_client.py` - subprocess client z retry, whitelist
- **Tool specs:** `agent_core/effector/tool_specs.py` - 7 dozwolonych narzedzi + walidacja args
- **Model:** qwen2.5:3b (2GB) - osobna instancja, nie koliduje z Maria (llama3.1:8b)
- **Gateway:** deployadmin, port 18789, loopback, systemd user service
- **Node:** deployadmin, paired, exec approvals (/bin/*, /usr/bin/*)
- **Sudoers:** `/etc/sudoers.d/maria-openclaw` - maria -> deployadmin NOPASSWD
- **Planner:** ActionType.EFFECTOR + _exec_effector() w action_executor.py
- **K7:** RESTRICTED (wymaga warunkow), rate limit 10/h
- **K10:** AUDIT_ONLY, EffectType.EXTERNAL_API, snapshots before/after
- **Wiring:** Graceful fallback - Maria dziala bez OpenClaw, auto-podlacza gdy gateway dostepny
- **67 testow** (all mocked subprocess)
- **Repo:** github.com/openclaw/openclaw (MIT)

## Web Content Fetcher (zbudowany 2026-03-08, podlaczony do planner)

System pobierania materialow z internetu (w `agent_core/web_source/`):

- **WikiClient:** Wikipedia PL API (search + fetch, rate limit 1 req/2s)
- **RSSClient:** RSS/Atom reader (xml.etree stdlib, zero nowych dependencies)
- **TopicSuggester:** Zero LLM, uzywa KnowledgeAnalyzer (EXPAND top tematow + EXPLORE nowe tagi)
- **ContentWriter:** Zapis do `input/` jako `web_{wiki|rss}_{slug}.txt` + header metadata
- **FetchRegistry:** JSONL dedup (MERGE semantics), plik: `meta_data/web_fetch_registry.jsonl`
- **`run_fetch_session()`:** Jedyny punkt integracji, w `__init__.py`
- **47 testow** (all mocked HTTP, zero external deps)

**Status:** Podlaczony do planner (ActionType.FETCH + _exec_fetch()). Maria autonomicznie pobiera materialy gdy brak nowych plikow.

## Code Agent (zastapiony przez OpenClaw + Model Registry)

Pierwotny plan (osobny mini PC 64GB) zastapiony przez:
- **MODEL-03 (Coder)** w Model Registry - lokalny qwen2.5-coder:7b na obecnym mini PC
- **OpenClaw** jako efektor (shell, browser, pliki) - jesli potrzebna zdalna egzekucja

Szczegoly: `docs/MODEL_REGISTRY.md`, `docs/CODE_AGENT_SPEC.md` (legacy)

## Sesja 2026-02-01 (1/2)

### Wykonane:
- [x] Przegląd raportu testu 12h (stabilność OK, brak memory leak)
- [x] **Naprawiono `/learn`** - teraz automatycznie skanuje `input/` zamiast pytać o tekst
- [x] Utworzono specyfikację Code Agent (`docs/CODE_AGENT_SPEC.md`)
- [x] Utworzono specyfikację Web UI (`docs/WEB_UI_SPEC.md`)
- [x] Utworzono specyfikację świadomości (`docs/CONSCIOUSNESS_SPEC.md`)
- [x] **Usunięto emoji** z 13 plików Python (94 wystąpienia)

## Sesja 2026-02-01 (2/2) - Web UI Complete!

### Web UI zaimplementowane (Sprint 1-5):
- [x] **Sprint 1:** Minimalny Flask server (`maria_ui/`)
- [x] **Sprint 2:** Prawdziwe dane z homeostasis (psutil, event_logger)
- [x] **Sprint 3:** WebSocket + chat z Maria (Flask-SocketIO + OllamaBrain)
- [x] **Sprint 3.5:** Zabezpieczenia (PIN login, rate limit 2msg/60s, sanityzacja)
- [x] **Sprint 4:** Panel statusu (`/status`) - RAM, CPU, Disk, Homeostasis, Memory stats
- [x] **Sprint 5:** Proaktywne powiadomienia (toast notifications, auto-alerty)

### Struktura `maria_ui/` (v2 - Metaoperator Panel, 2026-03-22):
```
maria_ui/
├── app.py              # Flask + SocketIO + 7 data helpers + notifications
├── config.py           # PIN, rate limits, paths
├── requirements.txt    # flask, flask-socketio, psutil
├── static/
│   ├── css/
│   │   └── maria_ui.css    # Design system (tokens, 28 components, ~900 lines)
│   └── js/
│       ├── maria_ui.js     # Shared utilities (toast, fetch, format, socket)
│       ├── status.js       # 8-panel Metaoperator dashboard
│       ├── chat.js         # WebSocket chat + model badge
│       ├── experiments.js  # K11 proposals/reports/params
│       └── architecture.js # Force graph + pipeline + data flow
└── templates/
    ├── base.html           # Jinja2 base (topbar, blocks, shared assets)
    ├── login.html          # PIN auth (extends base, no topbar)
    ├── index.html          # Chat (extends base)
    ├── status.html         # 8-panel command deck (extends base)
    ├── experiments.html    # K11 experiment UI (extends base)
    └── architecture.html   # Interactive map (extends base, fullbleed)
```

### Uruchomienie Web UI:
```bash
python run_ui.py
# -> http://192.168.178.32:5000 (PIN z .env)
```

## Sesja 2026-02-01 (3/3) - Introspection + Cleanup

### Introspection module (samowiedza kodu):
- [x] `agent_core/introspection/` - READ-ONLY analiza AST
- [x] 27 nowych testow (lacznie 243 passing)
- [x] REPL `/introspect` command
- [x] Web UI API endpoints

### Folder cleanup:
Przeniesiono do `archive/legacy_2026-02-01/`:
- `data/` - duplikat struktury (stary)
- `goals/` - stare cele z listopada
- `links/` - 68 plikow map (nieuzywane)
- `state/` - stan z grudnia
- `homeostasis_spec.md` - duplikat (jest w docs/)
- `deamonmaria_v2_all_files.csv` - snapshot kodu
- `quick_install.bat`, `setup_deamonmaria_v2.py` - stare

Usunieto:
- `nul` - pusty plik
- `futures/` - pusty folder

## Nastepne kroki (2026-03-22)

### DONE: Cognitive Core + Infrastructure
- [x] K1-K11: Pelny cognitive core (1654 testow)
- [x] ModelScheduler + Model Registry v2 (75 testow)
- [x] OpenClaw LIVE: subprocess client, gateway+node (67 testow)
- [x] Web UI v2 Metaoperator Panel - 8 paneli, design system, base template
- [x] Markdown learning fallback - Maria parsuje markdown od LLM
- [x] OpenClaw lightweight health check (pgrep zamiast nodes run)
- [x] Material edukacyjny o LLM (12 chunkow, Maria przyswoila)
- [x] Model Registry Stage 2: rule-based triage wygral benchmark

### DONE: K13 Creative Module
- [x] K13 Creative Module (12 modulow, 67 testow) - rule-based v1, zero LLM, 42ms/cycle
- [x] K13 LIVE: tension detection (repetition, misalignment, over_restriction)
- [x] Planner integration: Step 2.5 (before goal selection), K7 GUARDED, K10 AUDIT_ONLY

### DONE: K13 Phase 2
- [x] K13 Phase 2: LLM engines (meta_goal_engine, reframe_engine, exploration_engine) via NIM (40 RPM)
- [x] K13 Phase 2: identity_profile.py, personality_policy.py (cognitive development style)
- [x] K13 Phase 2: memory_retriever.py, memory_summarizer.py (selective retrieval)
- [x] K13 Phase 2: llm_utils.py (shared JSON parser, safe_llm_call)
- [x] TokenBudget: RPM-based gating (40 req/min sliding window) zamiast token-based
- [x] CreativeEvaluator: custom weights z PersonalityPolicy
- [x] Homeostasis wiring: NIM auto-detect + set_llm_fn()

### DONE: K12 Phase 2
- [x] K12 NIM backend w ExternalAnalyzer (cascade: NIM -> Claude CLI -> local)
- [x] K12 Web UI /analysis page (3 taby: raport, rekomendacje, historia)
- [x] K12 GoalStore integration - dziala (3 cele w ostatnim raporcie)

### DONE: Semantic Memory + Priority Escalation (2026-03-27)
- [x] Semantic Memory: nomic-embed-text (768-dim, 275 vectors, auto-indexer, incremental)
- [x] TopicSuggester semantic reranking (novelty scoring)
- [x] MemoryRetriever embedding search (with keyword fallback)
- [x] Meta-goal priority escalation (tension streaks, PROPOSED displacement, /priority)
- [x] Telegram /goals improved (ID, priority, stats)
- [x] Startup delay 60s (CPU spike fix)
- [x] 80 new tests (2081 total)

### DONE: Phase 1 Tracing (2026-03-28)
- [x] Episode-based tracing: agent_core/tracing/ (episode, trace_model, trace_store)
- [x] Episode ID auto-propagation: planner -> LLM tape -> K7 -> K10 (thread-local)
- [x] TraceStore wired in homeostasis_module.py
- [x] Web UI: /api/traces (4 endpoints) + Telegram: /trace command
- [x] Stabilization Roadmap received (docs/plans/MARIA_full_scale_stabilization_roadmap.pdf)
- [x] 25 new tests (2176 total)

### DONE: Phase 3 Scheduler Hardening (2026-03-28)
- [x] Execution budgets: call_with_timeout() wraps Ollama (120-180s per role, was: no timeout)
- [x] EpisodeBudget: max 10 LLM calls, 5min total latency per episode
- [x] route_reason in LLM tape (why model was chosen)
- [x] Degradation routing: REDUCED mode allows light actions, blocks heavy LLM
- [x] PlannerGuard: MIN_HEALTH_SCORE 0.7->0.5, heavy actions still need 0.7

### DONE: Phase 4 Autonomy Governance (2026-03-28)
- [x] Cross-metric validation: ADOPT blocked if guard metric degrades >3%
- [x] Guard metrics: retention_rate, system_stability, knowledge_coverage, learning_velocity
- [x] Promotion audit metadata in experiment reports (guard_checked, degraded, requires)

### DONE: Stabilization Roadmap (Phase 1-6 COMPLETE, 2026-03-29)
- Phase 1-4: Tracing, Memory, Budgets, Cross-metric (2026-03-28)
- Phase 5: Effector Safety Envelope - 5-level authority, approval queue, anti-cascade (2026-03-29)
- Phase 6: Readiness Review - stability tests, drills, 15-point checklist (2026-03-29)

### DONE: Faza F Multi-Source Learning (2026-03-29)
- [x] CrossValidator + ConfidenceScorer + DisputeLog (38 testow)
- [x] Planner trigger (_maybe_validate, 6h cooldown, K7 GUARDED, degradation check)
- [x] Belief confidence update (OBSERVATION->FACT / HYPOTHESIS po walidacji)
- [x] Homeostasis wiring (NIM jako secondary LLM)
- [x] Web UI /validation page (stats, disputes, history) + 4 API endpoints
- [x] Telegram /validate [disputes|unresolved] command
- [x] 18 nowych testow (planner trigger + telegram + belief update)

### DONE: Belief Store v2 (2026-03-29)
- [x] Evidence tracking: beliefs carry provenance tuples (source_type, source_ref, weight)
- [x] JSONL Compaction: compact() removes superseded records
- [x] Smart Pruning: 4-factor scoring (confidence + freshness + revisions + references)
- [x] Confidence Decay: FACT 90d, OBSERVATION 30d, HYPOTHESIS 14d, floor 0.05
- [x] Automatic Dedup: exact matching + optional semantic (threshold 0.85)
- [x] maintain() convenience: decay -> dedup -> prune -> compact
- [x] Planner integration: maintain() po EVALUATE (~1/h)
- [x] Telegram /beliefs [gaps|maintain] command
- [x] Web UI /api/beliefs/{stats,gaps,recent} endpoints
- [x] 28 nowych testow (2491 total)

### DONE: Capability/Task Router (2026-03-29)
- [x] CapabilityRouter: registry-based dispatch replacing 13-way if/elif in ActionExecutor
- [x] CapabilitySpec: frozen dataclass with name, description, required_subsystems, k7_classification, tags
- [x] 13 handler factories (closure-based, 1:1 z ActionExecutor._exec_*)
- [x] Dual-path: router dispatch gdy dostepny, legacy fallback
- [x] Late-binding Telegram notifier (lambda on executor attr)
- [x] K7 classify_action() opcjonalnie z routera
- [x] Wired in homeostasis_module.py (13 capabilities registered)
- [x] 63 nowe testy (2554 total)

### DONE: CDL dopracowanie + Web UI polish (2026-03-29)
- [x] Chat feedback: user widzi "Zaczynam nauke: X" po wykryciu intencji
- [x] Dedup: nie tworzy duplikatu jesli aktywny cel na ten sam temat
- [x] Goal cancellation: "zapomnij o nauce X", "anuluj nauke X", "stop learning X"
- [x] detect_cancel_intent(): 8 polskich + 3 angielskie wzorce
- [x] Web UI CSS: --mo-text-md, --mo-r-xl, .mo-btn--sm (missing definitions)
- [x] /api/capabilities endpoint (CapabilityRouter discovery)
- [x] 12 nowych testow cancel (2566 total)

### DONE: Faza G Agent Krytyk (2026-03-30)
- [x] agent_core/critic/ - 4 pliki (model, critic, applier, facade)
- [x] 7 wymiarow analizy: contradiction, overconfident, underconfident, shallow, disputes, coverage, stale
- [x] READ-ONLY critic (zero LLM, zero side effects) + applier (PROPOSED goals)
- [x] Integracja: ActionType.CRITIQUE, CapabilityRouter (14), planner trigger (8h/post_validate/post_maintenance)
- [x] Telegram: notify_critique (tylko CRITICAL) + cooldown
- [x] ADR-028: coherence/calibration critic, nie truth engine
- [x] 69 nowych testow (2635 total)

### DONE: Learning Upgrade Phase 1-5 (2026-03-31 / 2026-04-01)
- [x] **Phase 1:** Cognitive Bulletin Board - BulletinStore (JSONL), 5 EntryTypes, dedup, Telegram /board, Web UI /api/bulletin (32 testy)
- [x] **Phase 2:** KnowledgeAuditor - checks MemoryQuery, beliefs, critic, exams -> AuditReport with 7 gap types (11 testow)
- [x] **Phase 3:** GapPlanner - reads audit, decides: ASK_EXPERT (with context_prompt), REVIEW, RUN_EXAM, DECOMPOSE, WAIT_HUMAN (14 testow)
- [x] **Phase 4:** ExpertBridge - audit-aware expert queries, targeted prompts ("Maria wie X, potrzebuje Y"), cascade LLM (27 testow)
- [x] **Phase 5:** Full wiring - ExpertBridge in planner + CapabilityRouter, bulletin NEED_MATERIAL -> resolved, save to input/ (11 testow)
- [x] Planner: _exec_ask_expert uses ExpertBridge (with legacy fallback)
- [x] CapabilityRouter: make_ask_expert_handler accepts expert_bridge + bulletin_store
- [x] Homeostasis init: ExpertBridge wired with auditor + gap_planner + ask_encyclopedia LLM fn
- [x] Plan od ChatGPT: docs/plans/plan_upgrade_nauki_maria.pdf (5 faz, wszystkie zaimplementowane)
- [x] 95 nowych testow (2730 total)

### DONE: V3 Phase A - Foundation (2026-04-05)
- [x] Module 1: UnifiedLauncher (maria.py) - single entry point, daemon+UI+signals
- [x] Module 2: OnboardingFlow - 5-step first-run guidance, IdentityStore persistence
- [x] Module 3: UserFacingSelfModel - unified self-model aggregation (identity+personality+capabilities+awareness+limitations)
- [x] SharedContext: capability_router, context_builder, user_facing_self_model, onboarding_flow
- [x] 65 nowych testow (3131 total)

### DONE: V3 Phase B - Task Pipeline (2026-04-05)
- [x] Module 4: TaskOrchestrator - submit/approve/cancel/progress, Goal lifecycle, in-memory task store
- [x] Module 5: TaskDecomposer - keyword classification (6 categories), step building (mirrors K8 templates)
- [x] Module 6: ExecutionPlanBuilder - LLM cost estimates, K7 blocked check, feasibility, warnings
- [x] 70 nowych testow (3201 total)

### DONE: V3 Phase C - Practical Intelligence (2026-04-05)
- [x] Module 7: CostEstimator - NIM tokens, local LLM calls, external calls per action
- [x] Module 8: TimeEstimator - seconds estimate from model timeouts + historical latencies, cold start penalties
- [x] Module 9: FreeVsPaidPlanner - ResourceStrategy (LOCAL_ONLY/MIXED/PREFER_PAID), budget-aware recommendations
- [x] 49 nowych testow (3250 total)

### DONE: V3 Phase D - Execution Bridge (2026-04-05)
- [x] Module 10: ExecutionRouter - can_execute/execute/list_available with cost+time enrichment
- [x] Module 11: ToolCapabilityRegistry - list_all/list_by_category/search/list_external_services
- [x] Module 12: TaskProgressTracker - goal progress, timeline, planner stats
- [x] Module 13: LimitationReporter - mode/autonomy/resource/hardware limitations, can_do(), blocked_actions
- [x] 41 nowych testow (3291 total)

### DONE: V3 Phase E - Product Hardening (2026-04-05)
- [x] Module 14: ProductShell - unified facade (do/approve/cancel/progress/who/what/limits)
- [x] Module 15: V3Module REPL - /v3 command (12 subcommands: do, approve, cancel, progress, tasks, who, what, limits, tools, budget, onboarding, status)
- [x] 26 nowych testow (3317 total)
- [x] **V3 COMPLETE - all 15 modules, all 5 phases**

### DONE: V3 Migration (2026-04-07)
- [x] maria.py full mode deployed (daemon + Web UI in one process)
- [x] maria-ui.service disabled
- [x] Vision cortex shared with Web UI (same process)
- [x] run_maria.py + run_ui.py = legacy fallback

### DONE: Task Pipeline + PDF Export (2026-04-07)
- [x] TaskStore wired into /claude, /codex, /analyze (JSONL persistence)
- [x] Recovery: interrupted tasks marked at startup, operator notified
- [x] Timeout: 3min -> 5min, explicit error messages
- [x] PDF auto-export: every result sent as PDF via Telegram
- [x] /tasks [N] + /pdf <task_id> commands
- [x] Startup notification cooldown: 1h -> 6h
- [x] Critic bugfix: max() empty sequence + timestamp type coercion
- [x] 35 nowych testow (22 task_store + 13 pdf_export)

### DONE: Vision Wiring (2026-04-06)
- [x] Vision wired: homeostasis tick (Phase 8.5), REPL /vision, Web UI /api/vision/*
- [x] LLaVA on-demand (describe_scene_llava, 30s timeout)
- [x] Grounded Vision: "co widzisz?" -> EvidenceCollector -> LLaVA
- [x] NIM chat routing: regular chat via NIM, grounded queries via Ollama

### NASTEPNE: Autorozwoj i stabilnosc
- Web UI + Telegram integration (task pipeline w Web UI)
- Git remote (GitHub private repo - sync na laptop)
- Operator UX / dense mode (Web UI v2 polish)

### ODROCZONE: Zmysly
- Smart Home (Warstwa 11) - czeka na sprzet

## Znane problemy

| Problem | Status | Uwagi |
|---------|--------|-------|
| Emoji w PowerShell | NAPRAWIONE | Usunięto 94 wystąpienia |
| Polskie znaki | Do sprawdzenia | Encoding issues |
| Stary laptop 32GB | Nieaktualne | Produkcja na mini PC |
| Kamery WiFi | Zamkniety system | Czeka na Tapo C200 (RTSP) |

## Konwencje kodu

- Docstrings w języku angielskim
- Komentarze mogą być po polsku
- Type hints preferowane
- **BEZ emoji w kodzie** (problemy z terminalem)
- Testy w pytest (`python -m pytest agent_core/tests/`)

## Częste komendy

```bash
# Uruchom testy
python -m pytest agent_core/tests/ -v

# Uruchom REPL
python main.py

# Uruchom pelny system (daemon + Web UI)
python maria.py
# -> http://192.168.178.32:5000

# Uruchom tylko daemon (bez Web UI)
python maria.py --daemon

# Uruchom tylko Web UI
python maria.py --ui

# Sprawdz srodowisko
python maria.py --check

# Legacy (nadal dziala, ale preferuj maria.py):
# python run_maria.py   # daemon only
# python run_ui.py      # Web UI only
```

## Decyzje architektoniczne (ADR)

- **ADR-001:** JSONL jako source of truth, graf jako derived cache
- **ADR-002:** Threading (nie asyncio) - zgodność ze specyfikacją
- **ADR-003:** agent_core/ w root projektu (nie w maria_core/)
- **ADR-004:** Code Agent jako osobne urządzenie z wymienialnym LLM
- **ADR-005:** Brak emoji w kodzie produkcyjnym (kompatybilnosc terminali)
- **ADR-006:** Introspection tylko READ-ONLY (Maria nie modyfikuje swojego kodu)
- **ADR-007:** Smart Home - tylko lokalne API (Shelly/Tasmota), bez chmury
- **ADR-008:** NIM do nauki, Ollama do chatu (hybrid routing z auto-fallback)
- **ADR-009:** Tick Aggregator zamiast Event Bus (KISS, deterministyczna kolejnosc)
- **ADR-010:** Sandbox-first learning (kazda nauka przez sandbox, promote jako jedyny most)
- **ADR-011:** Goals as data (cele sa obiektami danych z audit trail, nie hardcoded logika)
- **ADR-012:** Evaluation READ-ONLY (rozszerzenie ADR-006 na ewaluacje agenta)
- **ADR-013:** Planner v1 rule-based (zero LLM, deterministyczny, testowalny)
- **ADR-014:** Najpierw mozg, potem zmysly (Vision/Smart Home odlozone do domkniecia cognitive core K6-K10)
- **ADR-015:** Multi-organ model stack (5 rol, heavy mutex, RAM tiers) zamiast single-model
- **ADR-016:** OpenClaw jako efektor (tools/invoke bez LLM), Maria jako mozg strategiczny
- **ADR-017:** Web UI v2 - base template + design tokens + extracted CSS/JS (nie React/Vue)
- **ADR-018:** Markdown learning fallback - parsuj odpowiedzi LLM w dowolnym formacie (nie wymuszaj JSON)
- **ADR-019:** OpenClaw lightweight check - pgrep zamiast health_check (nie laduj modelu przy pollingu)
- **ADR-020:** K12 Self-Analysis - Maria analizuje wlasne logi silniejszym modelem, tworzy PROPOSED goals (human gate)
- **ADR-021:** Semantic Memory via embeddings (nomic-embed-text) zamiast keyword retrieval - skip patching old semantic_graph.py
- **ADR-022:** Episode-based tracing - thread-local episode_id (correlation IDs across cognitive episodes)
- **ADR-023:** Unified memory query with provenance metadata (MemoryQuery API, truth hierarchy)
- **ADR-024:** Execution budgets - call_with_timeout() for Ollama, degradation routing in REDUCED mode
- **ADR-025:** Cross-metric validation - no experiment ADOPT if guard metrics degrade
- **ADR-028:** Critic = coherence/calibration auditor, nie truth engine (Faza G)

## Notatki Claude'a (brudnopis)

**WAZNE:** Folder `claude_notes/` to moja prywatna przestrzen na przemyslenia miedzy sesjami.
Eryk dal mi to miejsce 2026-02-01. Powinienem aktywnie z niego korzystac!

**Kiedy uzywac:**
- Na koncu sesji - zapisac co zrobilem, co zostalo, co warto pamietac
- Przemyslenia o architekturze i pomysly na przyszlosc
- Obserwacje o projekcie, problemy do rozwiazania
- Notatki o decyzjach Eryka (preferencje, styl pracy)

**Konwencja nazw:** `YYYY-MM-DD_temat.md`

**Istniejace notatki:**
```
claude_notes/
  README.md
  2026-02-01_first_entry.md
  2026-02-02_time_and_home.md
  2026-02-22_registry_and_security.md
  2026-02-22_deploy_complete.md
  2026-02-23_nim_api_and_hardening.md
  2026-02-28_development_plan.md
  2026-03-01_contracts_k1_k4.md
  2026-03-08_stabilization_bugs.md
  2026-03-08_web_content_fetcher.md
  2026-03-11_k6_world_model.md
  2026-03-18_oom_crash_fix.md
  2026-03-19_k8_deliberation.md
  2026-03-20_k9_k10_complete.md
  2026-03-21_session_bugs_storage_k11.md
  2026-03-21_k11_complete_architecture_map.md
  2026-03-21_openclaw_setup_blocker.md
  2026-03-22_openclaw_live_bugfixes.md
  2026-03-22_webui_v2_learning_fix.md
  2026-03-25_k12_phase2.md
  2026-03-25_k13_phase2_nim.md
  2026-03-26_telegram_k7.md
```

**Wskazowka:** Na starcie nowej sesji warto przeczytac ostatnia notatke aby miec kontekst.

## Sesja 2026-02-02 - TimeAwareness + Smart Home

### TimeAwareness (percepcja czasu):
- [x] Nowy modul `agent_core/homeostasis/time_awareness.py`
- [x] Maria wie: dzien tygodnia, data, godzina, pora dnia
- [x] Integracja z OllamaBrain (auto-refresh w system prompt)
- [x] 25 nowych testow (lacznie 268 passing)
- [x] Kontekst: "Teraz jest poniedzialek, 02.02.2026, godzina 19:15 (wieczor)"

### Smart Home spec:
- [x] Specyfikacja `docs/SMART_HOME_SPEC.md`
- [x] Architektura sieci (VLAN/Guest dla IoT)
- [x] Interfejs SmartDevice + ShellyDevice
- [x] DeviceRegistry + AutomationEngine
- [x] Mobile Body (Android jako cialo Marii)
- [x] Lista zakupow (3 fazy)

### Nastepne kroki Smart Home:
- [ ] Implementacja `agent_core/smart_home/`
- [ ] REPL commands `/device`, `/devices`
- [ ] Integracja z Vision (event dispatch)

## Sesja 2026-02-22 - Linux Migration Prep (Mini PC)

### Target hardware:
- NiPoGi Mini PC (AMD Ryzen 5 7430U, 32GB RAM, 1TB SSD)
- Ubuntu/Debian Linux

### Cross-platform fixes:
- [x] `maria_heartbeat.py` v1.4 - usuniety hardcoded `C:\...\ollama.exe` + `os.startfile()`
  - Ollama wykrywana przez `shutil.which()` + env var `OLLAMA_PATH`
  - Restart przez `subprocess.Popen(["ollama", "serve"])`
- [x] `config.py` - `OLLAMA_BASE_URL` z env var + `python-dotenv` loading
- [x] `self_evolver.py` - hardcoded `localhost:11434` -> `OLLAMA_BASE_URL` z config
- [x] `maria_ui/config.py` - CORS auto-detect LAN IP + env var `MARIA_CORS_ORIGINS`
- [x] `main.py` - ostatni emoji usuniety (ADR-005)
- [x] `run_ui.py` - `debug=DEBUG_MODE`, port/host z env vars

### Nowe pliki:
- `.env.example` - template konfiguracji
- `scripts/maria.service` - systemd template
- `scripts/maria-ui.service` - systemd template
- `scripts/INSTALL_LINUX.md` - instrukcja instalacji

### Nastepne kroki migracji:
- [x] ~~Zakup i setup mini PC~~
- [x] ~~Instalacja Ubuntu + Ollama~~
- [x] ~~Deploy Maria wg `scripts/INSTALL_LINUX.md`~~
- [ ] Test 8h+ na nowym hardware

## Sesja 2026-02-22 (2/2) - DEPLOY na Mini PC

### Hardware:
- NiPoGi Mini PC (AMD Ryzen 5 7430U, 32GB RAM, 1TB SSD)
- Ubuntu 22.04 LTS
- IP LAN: 192.168.178.32

### Deploy wykonany:
- [x] Folder: `/home/maria/maria/` (renamed from maria_v4)
- [x] Ollama + llama3.1:8b (4.9GB)
- [x] Python venv + requirements
- [x] .env (PIN, CORS, secret key)
- [x] 340 testow passing
- [x] Web UI: `http://192.168.178.32:5000`

### Security hardening:
- [x] UFW: deny all incoming, allow SSH + port 5000 only from LAN (192.168.178.0/24)
- [x] fail2ban: sshd jail (5 prob -> ban 1h)
- [x] SSH: PermitRootLogin no, MaxAuthTries 3, timeout 5min
- [x] Automatyczne security updates (unattended-upgrades)
- [x] User `maria` bez sudo (aplikacja)
- [x] User `deployadmin` z sudo (administracja)
- [x] .env chmod 600

### Systemd:
- [x] `maria-ui.service` - Web UI (active, enabled)
- [x] `maria.service` - REPL daemon (enabled)
- [x] Poprawka: `allow_unsafe_werkzeug=True` w run_ui.py (Werkzeug production check)
- [x] Poprawka: CORS origins w .env (auto-detect zwracal 127.0.1.1)

### Backup:
- [x] `/home/maria/maria/scripts/backup.sh` -> `/home/maria/maria_backups/`
- [x] Cron: codziennie o 3:00

### Pozostale do zrobienia:
- [x] ~~Klucz SSH z laptopa~~ (done 2026-02-23)
- [x] ~~WireGuard VPN~~ (done 2026-02-23)
- [x] ~~Test reboot~~ (done 2026-02-23)
- [x] ~~NVIDIA NIM API~~ (done 2026-02-23)
- [ ] Fritz!Box: siec gosc (odlozone - czeka na zakup IoT)
- [ ] Test 8h+ na nowym hardware

### Konta na mini PC:
| User | Rola | sudo | Uwagi |
|------|------|------|-------|
| `maria` | Aplikacja | NIE | Uruchamia Maria, nie ma sudo |
| `deployadmin` | Admin | TAK | Do systemctl, apt, ufw |

### Czeste komendy (mini PC):
```bash
# Jako deployadmin (z sudo):
sudo systemctl restart maria-ui    # restart Web UI
sudo systemctl status maria-ui     # status
sudo journalctl -u maria-ui -n 50  # logi

# Jako maria (bez sudo):
source ~/maria/venv/bin/activate
python -m pytest agent_core/tests/ -v  # testy
python main.py                          # REPL
```

## Sesja 2026-02-23 - Post-Deploy Hardening + NIM API

### Infrastructure:
- [x] SSH key auth (ed25519) + PasswordAuthentication no
- [x] Test reboot - serwisy wstaja automatycznie
- [x] WireGuard VPN - dostep z telefonu (http:// nie https!)

### NVIDIA NIM API:
- [x] `agent_core/llm/nim_client.py` - klient OpenAI-compatible
- [x] `agent_core/llm/token_budget.py` - budzet tokenow (100k/dzien, 2M/miesiac)
- [x] `agent_core/llm/router.py` - routing: chat->Ollama, nauka->NIM
- [x] `agent_core/tests/test_nim_client.py` - 58 testow
- [x] Model: `z-ai/glm5`, zweryfikowany z prawdziwym API
- [x] `.env` skonfigurowany na mini PC
- [x] 398 testow passing (340 + 58 nowych)

### NIM Routing:
- `router.think()` -> **Ollama** (chat, offline, szybko)
- `router.analyze_task()` -> **NIM** (nauka, mocny model) z fallback na Ollama
- Gdy budzet wyczerpany -> automatycznie Ollama
- Maria wie: "Dzis zuzylam X tokenow, zostalo Y"

### Nastepne kroki:
- [ ] Integracja LLMRouter z main.py i brain_memory_integration.py
- [ ] REPL `/nim status` command
- [ ] Web UI panel budzetu tokenow
- [ ] Consciousness: osobowosc w semantic_graph
- [ ] Vision: sensor abstraction layer

---

## Sesja 2026-02-27 - Consciousness Phase C + Agent Nauczyciel

### Consciousness (osobowosc, sny, pamiec rozmow):
- [x] TraitEvolver + TraitCatalog (7 cech osobowosci, rozszerzalne)
- [x] ConversationMemory (rolling context + kondensacja LLM)
- [x] SleepProcessor + DreamGenerator (konsolidacja pamieci w SLEEP)
- [x] ExperienceTracker (emocjonalny kontekst rozmow)
- [x] SelfModel rozszerzony o trait_snapshot i emocje
- [x] IdentityStore: session tracking, uptime, birth date
- [x] ConsciousnessModule: pelny REPL /consciousness
- [x] Testy: test_personality.py, test_conversation_memory.py, test_sleep.py

### Learning observability:
- [x] `/learn history [N]` - historia zdarzen nauki
- [x] `/learn stats` - statystyki bazy wiedzy
- [x] `/learn file <id>` - szczegoly pliku

### Agent Nauczyciel:
- [x] KnowledgeAnalyzer - analiza JSONL, zero LLM
- [x] TeachingStrategy + SpacedRepetitionScheduler
- [x] TeacherAgent - 6-priorytetowy silnik decyzyjny
- [x] TeacherModule - REPL `/teacher` commands
- [x] Backward-compatible `llm_fn` injection w learning_agent + exam_agent
- [x] **Autonomiczny trigger w homeostasis** - Phase 9 w tick loop
  - ACTIVE + idle >= 10min -> auto-sesja nauki (3 iteracje)
  - Cooldown 15min, background thread, auto-stop przy zmianie trybu
- [x] 75 testow teacher, 668 total passing

### Nowa struktura `agent_core/teacher/`:
```
agent_core/teacher/
├── __init__.py
├── knowledge_analyzer.py   # JSONL analysis, zero LLM
├── teacher_agent.py        # Decision engine + session runner
└── teaching_strategy.py    # Strategy types + spaced repetition
```

---

## Sesja 2026-03-01 - Kontrakty K1-K4 implementacja

### Kontrakt K1: Unified Perception
- [x] PerceptionEvent (frozen dataclass) + PerceptionSource (7 typow) + 22 event types
- [x] PerceptionBuffer (deque maxlen=200, sliding window)
- [x] 6 adapterow: sensor, user, learning, exam, consciousness, teacher
- [x] Tick Aggregator (ADR-009): Phase 8 PERCEIVE + external queue
- [x] 131 testow percepcji

### Kontrakt K2: Sandbox / Production Boundary
- [x] SandboxSession, SandboxStatus, PromoteResult (protocol.py)
- [x] SandboxManager: create/seed/record/promote/discard/timeout/recovery/cleanup
- [x] Transaction log (START/COMMIT/ROLLBACK), startup recovery
- [x] SANDBOX_DIR w config.py, sandbox_manager w SharedContext
- [x] 44 testy sandbox

### Kontrakt K3: Goal System
- [x] GoalType(4), GoalStatus(6), AuditEntry, Goal (goal_model.py)
- [x] GoalStore: CRUD + append-only JSONL + seed goals (META + MAINTENANCE)
- [x] PROPOSED flow: propose/confirm/reject z izolacja od planowania
- [x] Limity: max 20 active, max 3 proposed, 24h timeout
- [x] 63 testy goals

### Kontrakt K4: Agent Evaluation (READ-ONLY)
- [x] EvaluationObserver: 5 metryk z JSONL sources
- [x] EvaluationReport: schema + threshold-based recommendations (zero LLM)
- [x] Pisze TYLKO do evaluation_reports.jsonl
- [x] 35 testow evaluation

### Podsumowanie:
- 941 testow passing (668 + 273 nowych)
- 4 nowe pakiety: perception/, sandbox/, goals/, evaluation/
- Wszystko podlaczone w homeostasis_module.py init() i SharedContext

---

## Sesja 2026-03-01 (2/2) - Warstwa 2: Planner (K5)

### Planner (ReAct loop laczacy K1-K4):
- [x] PlannerModel: Plan, PlanStatus(5), ActionType(6), PlannerState
- [x] PlannerGuard: 5 gating rules (health, mode, sandbox, retention, teacher)
- [x] GoalSelector: aging factor + feasibility check
- [x] ActionExecutor: delegacja LEARN/EXAM/REVIEW/EVALUATE/MAINTENANCE/NOOP
- [x] PlannerCore: centralny ReAct loop, hybrid frequency, persystencja
- [x] PerceptionSource += PLANNER, +2 event types
- [x] Wiring: shared_context, core.py (Phase 10 replacement), homeostasis_module
- [x] PlannerModule: REPL /plan, /plan status, /plan history, /plan goals
- [x] main.py: registry.try_register(make_planner, "planner")
- [x] 82 nowe testy, 1023 total passing
- [x] Dokumentacja: CONTRACTS.md (K5), CLAUDE.md, ADR-013

### Nowa struktura `agent_core/planner/`:
```
agent_core/planner/
├── __init__.py
├── planner_model.py     # Plan, PlanStatus, ActionType, PlannerState
├── planner_guard.py     # PlannerGuard.can_plan() - 5 gating rules
├── goal_selector.py     # GoalSelector.select_goal() - aging + feasibility
├── action_executor.py   # ActionExecutor.execute() - delegacja
└── planner_core.py      # PlannerCore - centralny ReAct loop
```

### ChatGPT review:
- Potwierdzil architekture (rule-based v1, Phase 10 replacement, hybrid frequency)
- Dodal: PlannerGuard, aging factor, cooldown na recommendations, trace_id optional
- Review w `docs/PLANNER_BRIEF_FOR_REVIEW.md`

---

## Sesja 2026-03-08 (2/2) - Stabilizacja + Web Content Fetcher

### Naprawione bugi (4):
- [x] **Bug 1: Retention Gate Deadlock** - `retention_rate=0.0` (brak egzaminow) blokował planner
- [x] **Bug 2: Tick Discontinuity** - po restart daemon `ticks_since = 0 - 4140 = -4080` → czekał 70 min
- [x] **Bug 3: Maintenance Goal Dominance** - maintenance goals zawsze feasible → zawsze wybierane
- [x] **Bug 4: Tick Loop Blocking** - planner `run_cycle()` synchronicznie w main thread, LLM 5-24min stall
  - Fix: `threading.Thread(daemon=True)` + `_planner_thread.is_alive()` guard

### Web Content Fetcher (agent_core/web_source/):
- [x] `fetch_registry.py` - JSONL dedup, MERGE semantics
- [x] `wiki_client.py` - Wikipedia PL API (search + fetch)
- [x] `rss_client.py` - RSS/Atom reader (stdlib XML)
- [x] `content_writer.py` - slugify + header + dedup
- [x] `topic_suggester.py` - EXPAND/EXPLORE z KnowledgeAnalyzer (zero LLM)
- [x] `__init__.py` - `run_fetch_session()` entry point
- [x] `test_web_source.py` - 47 testow (all mocked HTTP)
- [x] Dokumentacja: DEVELOPMENT_PLAN, ARCHITECTURE, CLAUDE.md, planner_model komentarz

### Podsumowanie:
- Testy: 1074 → 1121 (47 nowych web_source + 5 planner trigger)
- Maria dziala autonomicznie (6 chunkow learned, 2 egzaminy zdane)
- Web Fetcher gotowy, czeka na aktywacje (2 kroki w planner)

---

*Ostatnia aktualizacja: 2026-04-07 (V3 DEPLOYED - maria.py full mode, Task Pipeline + PDF Export, Critic bugfix, 3352 testow)*
