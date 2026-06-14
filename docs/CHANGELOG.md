# M.A.R.I.A. - Changelog
> Format: [YYYY-MM-DD] Kategoria: Opis

---

## [2026-04-10] - Sesja 33: Master Prompt + Reminders & Todos + Task Pipeline Web UI + UserProfile

### Added - Master Prompt (agent_core/llm/master_prompt.py)
- **Single source of truth dla wszystkich LLM paths** (OllamaBrain, NIM, WebUI, Claude, Codex)
- Based on `docs/MARIA_PROMPT.md`
- Replaces scattered prompt fragments w 5 miejscach

### Added - Reminders & Todos (agent_core/reminders/, 83 testow)
- Time-triggered notifications
- PL + EN time parser ("jutro o 9", "tomorrow at 9am")
- **Phase 12 w tick loop** (scheduler check)
- Recurring: DAILY/WEEKLY/MONTHLY
- REPL + Telegram + tick scheduler integration
- Persistence: `meta_data/reminders.jsonl`

### Added - UserProfile (agent_core/consciousness/, 60 testow)
- `meta_data/user_profile.json` (single file, not JSONL)
- Auto-learn z chat + ConversationMemory
- Telegram /profile, Web UI /api/user/profile

### Added - Task Pipeline in Web UI (20 testow)
- /tasks page: submit, list, detail, PDF download
- 4 API endpoints (submit, list, get, pdf)
- Auto-refresh, status badges

### Statistics
- 163 new tests, ~3935 total

---

## [2026-04-05] - Sesja 28: Vision Phase 1-4 COMPLETE + V3 Phase A-E COMPLETE (MASSIVE)

### Added - Vision Phase 1-4 (297 testow)
**Faza 1: Sensor Abstraction (123 testy)**
- models.py: Frame, VisionMode, DegradationType, SensorIssue, DiagnosticReport
- sensors/base.py, health.py (7 degradation levels), mock_sensor.py, usb_webcam.py

**Faza 2: Preprocessing (87 testow)**
- quality.py (6 metryk), degradation.py (12 typow), normalizer.py (resize, CLAHE), preprocessor.py

**Faza 3: Vision Modules (56 testow)**
- modules/base.py, motion/detector.py, scene/analyzer.py (LLaVA + stats fallback)

**Faza 4: Vision Cortex (31 testow)**
- cortex.py (adaptive modules, pipeline), percept.py (consciousness format)

### Added - V3 Orchestrator Phase A-E COMPLETE (15 modulow, 251 testow)
**Phase A Foundation (Modules 1-3, 65 testow):**
- UnifiedLauncher (maria.py) - single entry point, daemon+UI+signals
- OnboardingFlow - 5-step first-run guidance
- UserFacingSelfModel - unified self-model aggregation

**Phase B Task Pipeline (Modules 4-6, 70 testow):**
- TaskOrchestrator - submit/approve/cancel/progress, Goal lifecycle
- TaskDecomposer - keyword classification (6 categories)
- ExecutionPlanBuilder - LLM cost estimates, K7 blocked check

**Phase C Practical Intelligence (Modules 7-9, 49 testow):**
- CostEstimator - NIM tokens, local LLM calls, external calls
- TimeEstimator - seconds estimate, cold start penalties
- FreeVsPaidPlanner - LOCAL_ONLY/MIXED/PREFER_PAID strategies

**Phase D Execution Bridge (Modules 10-13, 41 testow):**
- ExecutionRouter - can_execute/execute/list_available
- ToolCapabilityRegistry - list_all/list_by_category/search
- TaskProgressTracker - goal progress, timeline
- LimitationReporter - mode/autonomy/resource/hardware limitations

**Phase E Product Hardening (Modules 14-15, 26 testow):**
- ProductShell - unified facade (do/approve/cancel/progress/who/what/limits)
- V3Module REPL - /v3 command (12 subcommands)

### Statistics
- **548 new tests** w jednej sesji (Vision 297 + V3 251)
- Vision COMPLETE, V3 COMPLETE (15/15 modulow)

---

## [2026-04-01] - Sesja 25: Learning Upgrade Phase 4-5

### Added - Phase 4: ExpertBridge (27 testow)
- Audit-aware expert queries
- Targeted prompts: "Maria wie X, potrzebuje Y"
- Cascade LLM (local -> NIM -> Claude CLI)

### Added - Phase 5: Full wiring (15 testow)
- `_exec_ask_expert` uses ExpertBridge (with legacy fallback)
- `make_ask_expert_handler` accepts expert_bridge + bulletin_store
- Homeostasis init: ExpertBridge wired z auditor + gap_planner + ask_encyclopedia LLM fn
- Bulletin NEED_MATERIAL -> resolved, save to input/

### Statistics
- 42 new tests (2761 -> 2803)
- Plan od ChatGPT: `docs/plans/plan_upgrade_nauki_maria.pdf` - wszystkie 5 faz COMPLETE

---

## [2026-03-31] - Sesja 24: Learning Upgrade Phase 1-3

### Added - Phase 1: Cognitive Bulletin Board (32 testy)
- `agent_core/bulletin/bulletin_store.py` - JSONL persistence
- 5 EntryTypes: NEED_MATERIAL, QUESTION_UNANSWERED, UNUSED_CAPABILITY, etc.
- Dedup, bounded, thread-safe
- Telegram /board, Web UI /api/bulletin

### Added - Phase 2: KnowledgeAuditor (11 testow)
- Checks MemoryQuery + beliefs + critic + exams
- AuditReport z 7 gap types: weak_topic, stale_knowledge, coverage_gap, etc.

### Added - Phase 3: GapPlanner (14 testow)
- Reads audit, decides: ASK_EXPERT (with context_prompt), REVIEW, RUN_EXAM, DECOMPOSE, WAIT_HUMAN
- Priority ranking by gap severity + topic importance

### Statistics
- 57 new tests (2704 -> 2761)

---

## [2026-03-30] - Sesja 23: Faza G Agent Krytyk (Knowledge Quality Gate)

### Added - agent_core/critic/ (4 pliki, 69 testow)
- **critique_model.py** - FindingCategory(7), Severity(3), CritiqueFinding, CritiqueReport, GOAL_TITLE_MAP
- **knowledge_critic.py** - silnik analizy READ-ONLY, zero LLM, zero side effects:
  1. CONTRADICTION - negation patterns (PL+EN), numeric conflicts
  2. OVERCONFIDENT - confidence > 0.7 + no/failed exam
  3. UNDERCONFIDENT - confidence < 0.4 + passed exam
  4. SHALLOW_KNOWLEDGE - brak facts, single source
  5. UNRESOLVED_DISPUTE - >=2 high-severity z DisputeLog
  6. COVERAGE_GAP - partially/completed bez exam (3d grace)
  7. STALE_KNOWLEDGE - decayed confidence < 0.15
- **critique_applier.py** - PROPOSED goals + LLM summary
- **facade.py** - orchestration

### Added - Integration
- ActionType.CRITIQUE, CapabilityRouter (14th capability)
- Planner trigger: 8h cadence + post_validate + post_maintenance
- Telegram: notify_critique (tylko CRITICAL) + cooldown
- ADR-028: coherence/calibration critic, **nie truth engine**

### Statistics
- 69 new tests (2566 -> 2635)

---

## [2026-03-29] - Sesja 21: Faza F Multi-Source Learning + Roadmap v1.0

### Added - Faza F: Multi-Source Learning COMPLETE
- **`agent_core/cross_validation/`** - 3 nowe moduly:
  - `cross_validator.py` - porownanie wynikow z primary (Ollama) i secondary (NIM) LLM
  - `confidence_scorer.py` - rule-based scoring (Jaccard similarity, 3 wymiary, wagi)
  - `dispute_log.py` - JSONL persistence sporow (thread-safe, bounded 200)
- **Planner trigger:** `_maybe_validate()` w decision cycle (6h cooldown)
- **`PlannerState.last_validation_ts`** - backward-compatible state tracking
- **Belief confidence update** - po walidacji: OBSERVATION->FACT (>0.7), demotion HYPOTHESIS (<0.3)
- **VALIDATE w degradation check** - blokowane w REDUCED mode (heavy action)
- **World model wiring** - planner_core -> executor -> BeliefStore.revise()
- **Web UI `/validation`** - 3 taby (stats, disputes, history) + 4 API endpoints
- **Telegram `/validate`** - [disputes|unresolved] command
- K7: GUARDED, rate 5/h | K10: SafetyProfile skonfigurowany

### Added - Roadmap v1.0
- `docs/ROADMAP.md` zaktualizowany z v0.6 (2026-03-01) do v1.0
- Dodane fazy C.6 (Cognitive Core K5-K13), C.7 (Infrastructure), C.8 (Stabilization)
- Milestones M5-M10, ryzyka zaktualizowane, ADR-001 do ADR-026

### Statistics
- **2448 tests passing** (2391 + 57 nowych: 38 cross-validation + 14 planner trigger + 4 telegram + 1 belief)
- Faza F: COMPLETE

---

## [2026-03-29] - Sesja 20: Phase 5-6 Stabilization (Effector Safety + Readiness)

### Added - Phase 5: Effector Safety Envelope (ADR-026)
- **`agent_core/autonomy/authority_level.py`** - 5-level staged authority:
  - OBSERVE (default, read-only) / SUGGEST / CONFIRM / BOUNDED / UNRESTRICTED (blocked)
  - AuthorityConfig (persistent JSON), AuthorityManager (singleton)
- **`agent_core/autonomy/approval_queue.py`** - Non-blocking HITL:
  - ApprovalRequest dataclass, JSONL persistence, stale expiry (1h)
  - get_approved_ready(), expire_stale(), reject_all_pending()
- **`agent_core/autonomy/tool_budget.py`** - Per-tool rate limits:
  - ToolBudgetManager, exponential backoff (2^n * 60s), duplicate detection
- **PlanStatus.AWAITING_APPROVAL** - planner doesn't block, picks up next cycle
- **Telegram:** /efapprove, /efreject, /efstatus, /authority (4 nowe komendy)
- **Anti-cascade:** breaker w action_executor (max 3 effector failures -> disable)

### Added - Phase 6: Readiness Review
- 100-cycle marathon test z BOUNDED mode
- Authority transitions: observe->bounded->observe + cleanup
- Concurrent access: 4 threads, budget checking, approval handling
- 15-point readiness checklist - all passed
- All gates A-E passed (tracing, memory, budgets, governance, readiness)

### Statistics
- **2391 tests passing** (2201 + 190 nowych)
- **Stabilization Roadmap COMPLETE** (all 6 phases, all 5 gates)

---

## [2026-03-28] - Sesja 19: Phase 1-4 Stabilization + CDL + Traces UI

### Added - Phase 1: Decision Traceability (ADR-022)
- **`agent_core/tracing/`** - episode_id (thread-local), DecisionTrace, TraceStore (JSONL)
- Episode ID auto-propagation: planner -> LLM tape -> K7 -> K10
- Web UI: `/api/traces` (4 endpoints) + Telegram: `/trace` command

### Added - Phase 2: Memory Consistency (ADR-023)
- **`agent_core/memory/query.py`** - MemoryQuery API z provenance metadata
- Truth hierarchy: knowledge_index > beliefs > semantic vectors
- Grounding: "co wiesz o X" -> GROUNDED_KNOWLEDGE -> evidence
- Staleness fixes: vector cleanup, beliefs rebuild po LEARN, re-indexing
- Web UI: `/api/memory/query` + Telegram: `/memory`

### Added - Phase 3: Scheduler Hardening (ADR-024)
- `call_with_timeout()` wraps Ollama (120-180s per role)
- EpisodeBudget: max 10 LLM calls, 5min total latency per episode
- route_reason w LLM tape (why model was chosen)
- Degradation routing: REDUCED mode blocks heavy LLM actions

### Added - Phase 4: Autonomy Governance (ADR-025)
- Cross-metric validation: ADOPT blocked if guard metric degrades >3%
- Guard metrics: retention_rate, system_stability, knowledge_coverage, learning_velocity
- Promotion audit metadata in experiment reports

### Added - CDL in Web UI
- Conversation-Driven Learning: learning intent detection w Web UI chat
- LLM call counting w traces (total_llm_calls, models_used, latency)

### Statistics
- **2202 tests passing** (2081 + 121 nowych)

---

## [2026-03-27] - Sesja 18: Semantic Memory + Priority Escalation

### Added - Semantic Memory (ADR-021)
- **`agent_core/semantic/`** - nomic-embed-text (768-dim, 274MB) via Ollama /api/embed
- EmbeddingModel: in-memory cache, batch embed, cosine similarity
- VectorStore: in-memory + JSONL persist (`meta_data/semantic_vectors.jsonl`), cap 10k
- SemanticMemory facade: index_text/batch, search, find_similar, 4 namespaces
- Auto-indexer: 275 vectors (157 knowledge + 95 beliefs + 23 hints), startup delay 60s
- Incremental indexing: nowe pliki auto-embeddowane po fetch
- TopicSuggester: semantic reranking (novelty scoring)
- MemoryRetriever: embedding search (with keyword fallback)

### Added - Meta-goal Priority Escalation
- Tension streak tracking: `creative_tension_streaks.jsonl`
- Priority boost: streak * 0.05, max +0.2
- PROPOSED displacement: replaces lowest-priority when higher arrives
- Telegram `/priority <id-prefix> <0.0-1.0>` - operator manual override
- Improved `/goals`: shows ID prefix + priority + stats

### Statistics
- **2081 tests passing** (2009 + 57 nowych + 15 indexer)

---

## [2026-03-26] - Sesja 17: Telegram Bridge + Codex CLI + K7 Improvements

### Added - Telegram Bridge (ClawBot)
- **`agent_core/telegram/`** - bot.py, notifier.py, __init__.py (TelegramBridge facade)
- 7 typow alertow z cooldownami (creative, k12, k9, health, mode, k7, startup)
- Komendy: /status, /goals, /approve, /reject, /restart, /priority, /learn, /help
- Homeostasis Phase 11 TELEGRAM polling (co 30s)
- Notyfikacje z action_executor (K13 creative, K12 self-analysis)

### Added - Codex CLI / ChatGPT Encyclopedia
- **`agent_core/llm/codex_client.py`** - subprocess wrapper for Codex CLI
- ModelRole.ENCYCLOPEDIA (MODEL-07), router.ask_encyclopedia()
- Fallback chain: Codex -> NIM -> Ollama, rate limit 10/h

### Changed - K7 Autonomy Improvements
- Consecutive failure auto-reset (counter resets po 30min idle)
- Fetch rate limit: 5 -> 10/h
- Proposed goals timeout: 24h -> 72h

### Statistics
- **~2009 tests passing** (1943 + 42 telegram + 24 codex)

---

## [2026-03-25] - Sesja 16b: K13 Phase 2 + K12 Phase 2 (NIM Engines)

### Added - K13 Creative Module Phase 2
- 8 nowych modulow w `agent_core/creative/`:
  - `meta_goal_engine.py` - NIM-powered meta-goal generation
  - `reframe_engine.py` - NIM-powered perspective reframing
  - `exploration_engine.py` - NIM-powered knowledge exploration
  - `identity_profile.py` - CognitiveProfile (developmental stage)
  - `personality_policy.py` - trait->weight adjustment for creativity
  - `memory_retriever.py` - selective memory retrieval (semantic + keyword)
  - `memory_summarizer.py` - NIM-powered memory condensation
  - `llm_utils.py` - shared JSON parser, safe_llm_call
- TokenBudget: RPM-based gating (40 req/min sliding window)
- CreativeEvaluator: custom weights z PersonalityPolicy
- Homeostasis wiring: NIM auto-detect + set_llm_fn()

### Added - K12 Self-Analysis Phase 2
- NIM backend w ExternalAnalyzer (cascade: NIM -> Claude CLI -> local qwen3:8b)
- Web UI `/analysis` page (3 taby: raport, rekomendacje, historia)
- 4 API endpoints: /api/analysis/{latest,recommendations,history,status}
- GoalStore integration: last report contained 3 goals

### Statistics
- **1943 tests passing** (1876 + 62 K13 Phase 2 + 5 misc)

---

## [2026-03-24] - Sesja 16a: K12 LIVE + Planner Bugfixes

### Fixed
- K12 LIVE: 5 bugow naprawionych (file_id passthrough, chunk failure backoff)
- Teacher: skip po 5 consecutive chunk failures (was: infinite retry)
- Planner fallthrough: NOOP/K7-blocked -> evaluate -> K12 (zamiast slepego NOOP)

### Statistics
- **~1876 tests passing**

---

## [2026-03-22] - Sesja 16: Web UI v2 Metaoperator Panel + Learning Fixes

### Added - Web UI v2 Metaoperator Panel
- **`maria_ui/templates/base.html`** - Jinja2 base template z topbar + blocks
- **`maria_ui/static/css/maria_ui.css`** - Design system: 28 komponentow, design tokens, dark premium (~900 lines)
- **`maria_ui/static/js/maria_ui.js`** - Shared utilities: toast (dedup), apiFetch, formatters, socket
- **`maria_ui/static/js/status.js`** - 8-panel Metaoperator dashboard
- **`maria_ui/static/js/chat.js`** - WebSocket chat + model badge
- **`maria_ui/static/js/experiments.js`** - K11 proposals/reports/params
- **`maria_ui/static/js/architecture.js`** - Force graph + pipeline + data flow
- 7 nowych data helperow w app.py: _get_models_data, _get_openclaw_data, _get_goals_summary, _get_cognitive_counts, _get_unified_events, _get_memory_integrity_flags, _get_homeostasis_cause, _get_traits_data
- /api/status/full rozszerzony o: models, openclaw, goals, event_stream, memory.cognitive, memory.integrity, identity.traits, homeostasis.cause

### Changed - Web UI Templates
- Wszystkie 5 templates przepisane na extends base.html
- CSS/JS extracted z inline do static/ files
- status.html: kompletny rewrite -> 8-panel command deck
- Templates: 3364 -> ~600 linii (reszta w static/)

### Added - Markdown Learning Fallback
- **`maria_core/learning/learning_agent.py`** - _parse_markdown_to_learning_dict()
  - Fallback parser: markdown -> dict gdy LLM ignoruje JSON format
  - Rozpoznaje sekcje (Streszczenie, Kluczowe punkty, Tagi, Pytania)
  - Parsuje bold, bullet points, numeracje
- extract_json_from_response() rozszerzony: markdown fences gdziekolwiek + fallback na oryginal
- format:"json" dodany do call_ollama()

### Fixed - OpenClaw Lightweight Health Check
- **`agent_core/modules/homeostasis_module.py`** - pgrep zamiast health_check() w init
- **`maria_ui/app.py`** - pgrep zamiast health_check() w status polling
- Przyczyna: health_check() ladowal qwen2.5:3b (3GB, 6 CPU cores) przy kazdym pollu/init
- Efekt: health score spadal z 83% do 60% z powodu saturacji CPU

### Added - Educational Material
- **`input/edu_modele_jezykowe_role_orkiestracja_v2.txt`** - 12 chunkow, 1500 slow
  - Modele jezykowe, role, instancje, RAM, routing, fallbacki, OpenClaw, bezpieczenstwo
  - Maria przyswoila autonomicznie w 17 minut

### Added - K12 Self-Analysis (Cognitive Loop)
- **`agent_core/self_analysis/`** - 5 nowych plikow:
  - `recommendation_model.py` - AnalysisRecommendation, AnalysisReport dataclasses
  - `state_collector.py` - zbieranie stanu z 8 JSONL files (zero LLM, ~2-4KB output)
  - `external_analyzer.py` - analiza przez silniejszy model (MVP: qwen3:8b local)
  - `recommendation_applier.py` - PROPOSED goals + topic hints + K6 beliefs
  - `__init__.py` - SelfAnalysis facade z run_analysis() + should_analyze()
- Planner: ActionType.SELF_ANALYZE, _exec_self_analyze(), _maybe_self_analyze() trigger
- PlannerState.last_self_analysis_ts dla cooldown (24h periodic + event-driven)
- K7: GUARDED classification, rate limit 2/hour
- K10: AUDIT_ONLY, EffectType.CONFIGURATION
- SharedContext.self_analysis field
- Homeostasis module wiring z LLM function injection
- 45 nowych testow

### Stats
- 1699 testow passing (zero regresji)
- ADR-017 (Web UI v2), ADR-018 (markdown fallback), ADR-019 (lightweight OpenClaw), ADR-020 (K12 Self-Analysis)

---

## [2026-03-01] - Sesja 14: Kontrakty K1-K4 implementacja

### Added - Warstwa 1: Unified Perception (Kontrakt K1)
- **`agent_core/perception/event.py`** - PerceptionEvent (frozen dataclass), PerceptionSource (7 typow), EVENT_TYPE_DEFAULTS (22 typy), create_event() factory
- **`agent_core/perception/buffer.py`** - PerceptionBuffer (deque maxlen=200, sliding window)
- **`agent_core/perception/adapters/`** - 6 adapterow:
  - SensorAdapter (resource, cognitive, thermal, power, time)
  - UserAdapter (message, command)
  - LearningAdapter (chunk learned, file scan, sandbox promoted/discarded)
  - ExamAdapter (exam result)
  - ConsciousnessAdapter (trait emerged/faded, dream, sleep cycle)
  - TeacherAdapter (decision, session complete)
- **Tick Aggregator (ADR-009):** Phase 8 PERCEIVE w tick loop, thread-safe external queue (deque maxlen=50)
- 131 testow percepcji

### Added - Kontrakt K2: Sandbox / Production Boundary
- **`agent_core/sandbox/protocol.py`** - SandboxStatus, SandboxSession, PromoteResult
- **`agent_core/sandbox/manager.py`** - SandboxManager:
  - create/seed/record/promote/discard/timeout/recovery/cleanup
  - Transaction log (START/COMMIT/ROLLBACK) w promote_log.jsonl
  - Startup recovery: auto-DISCARD osieroconych sesji
- **`maria_core/sys/config.py`** - SANDBOX_DIR = meta_data/sandbox
- 44 testy sandbox

### Added - Kontrakt K3: Goal System
- **`agent_core/goals/goal_model.py`** - GoalType(4), GoalStatus(6), AuditEntry, Goal, create_goal()
- **`agent_core/goals/store.py`** - GoalStore:
  - CRUD + append-only JSONL persistence (meta_data/goals.jsonl)
  - Seed goals: META (1) + MAINTENANCE (3)
  - PROPOSED flow: propose/confirm/reject z izolacja od planowania
  - Limity: max 20 active, max 3 proposed, 24h timeout, overflow auto-abandon
- 63 testy goals

### Added - Kontrakt K4: Agent Evaluation (READ-ONLY)
- **`agent_core/evaluation/observer.py`** - EvaluationObserver:
  - 5 metryk: learning_velocity, retention_rate, knowledge_coverage, system_stability, personality_growth
  - Threshold-based recommendations (pure logic, zero LLM)
  - Pisze TYLKO do evaluation_reports.jsonl
- **`agent_core/evaluation/report.py`** - EvaluationReport schema
- 35 testow evaluation

### Changed
- **`agent_core/registry/shared_context.py`** - Dodano: perception_buffer, sandbox_manager, goal_store, evaluation_observer
- **`agent_core/homeostasis/core.py`** - Phase 8 PERCEIVE + external queue (ADR-009)
- **`agent_core/modules/homeostasis_module.py`** - Wiring K1-K4 w init()

### Statistics
- **941 tests passing** (668 previous + 273 new)
- 4 nowe pakiety: perception/, sandbox/, goals/, evaluation/
- 20+ nowych plikow

---

## [2026-02-28] - Sesja 13: Warstwa 0 (bugs) + Stage 5 Cleanup

### Fixed
- **SleepProcessor bug** - przekazywano experience_tracker zamiast session_id
- **latency_probe.py** - usuniety martwy import, zwraca -1.0 zamiast falszywego 0.0
- **Trait count** - skorygowano 19 -> 7 w dokumentacji
- **LLMRouter** - llm_fn teraz przekazywane do learn_next_chunk() i run_exam_if_ready()

### Changed
- **Stage 5 cleanup** - archiwizacja: agent/, logs/, output/, memory/ -> maria_core/_legacy_archived/
- **Dokumentacja sync** - ARCHITECTURE.md v0.3, CONSCIOUSNESS_SPEC, ROADMAP Phase C

### Statistics
- **668 tests passing** (zero regresji)

---

## [2026-02-27] - Sesja 12: Consciousness Phase C + Agent Nauczyciel

### Added - Consciousness (`agent_core/consciousness/`)
- **TraitEvolver + TraitCatalog** - 7 cech osobowosci z dynamiczna ewolucja
- **ConversationMemory** - Rolling context + kondensacja LLM
- **SleepProcessor + DreamGenerator** - Konsolidacja pamieci podczas SLEEP
- **ExperienceTracker** - Kontekst emocjonalny z rozmow
- **IdentityStore** - Ciaglosc miedzy sesjami (session count, uptime, birth date)

### Added - Agent Nauczyciel (`agent_core/teacher/`)
- **TeacherAgent** - 6-priorytetowy silnik decyzyjny (P1-P6)
- **KnowledgeAnalyzer** - Analiza JSONL, zero LLM
- **SpacedRepetitionScheduler** - Interwaly powtórek na bazie wynikow
- **Autonomiczny trigger** - Homeostasis Phase 9: ACTIVE + idle >= 10min -> auto-sesja nauki

### Statistics
- **668 tests passing** (75 teacher tests + consciousness tests)

---

## [2026-02-23] - Sesja 11: Post-Deploy Hardening + NVIDIA NIM API

### Infrastructure
- **SSH key auth:** Klucz ed25519 z laptopa, PasswordAuthentication wylaczone
- **Reboot test:** Wszystkie serwisy (ollama, maria-ui) wstaja automatycznie
- **WireGuard VPN:** Dostep do Marii z telefonu przez Fritz!Box VPN

### Added - NVIDIA NIM API (`agent_core/llm/`)
- **`nim_client.py`** - Klient NVIDIA NIM API (OpenAI-compatible)
  - Retry z exponential backoff (rate limits)
  - Token usage tracking per call
  - Health check i availability detection
- **`token_budget.py`** - Zarzadzanie budzetem tokenow
  - Limity dzienne (100k) i miesieczne (2M)
  - Persistence w `meta_data/nim_token_usage.json`
  - Status: OK / LOW / DEPLETED
  - Raport po polsku ("Dzis zuzylam X tokenow...")
- **`router.py`** - LLM Router (NIM vs Ollama)
  - `think()` -> Ollama (chat, offline, szybko)
  - `analyze_task()` -> NIM (nauka, mocny model) z fallback na Ollama
  - Automatyczne przelaczanie gdy budzet wyczerpany
- **`agent_core/tests/test_nim_client.py`** - 58 testow (mock-based)

### Changed
- **`.env.example`** - Dodano sekcje NVIDIA NIM (API key, model, limity)
- **`maria_core/sys/config.py`** - Nowe env vars NIM
- **`agent_core/llm/__init__.py`** - Eksporty NIMClient, TokenBudget, LLMRouter

### Configuration
```
NVIDIA_NIM_API_KEY=nvapi-...
NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_NIM_MODEL=z-ai/glm5
NIM_DAILY_TOKEN_LIMIT=100000
NIM_MONTHLY_TOKEN_LIMIT=2000000
```

### Statistics
- **398 tests passing** (340 previous + 58 new)
- NIM API verified: model z-ai/glm5, latency ~2-5s (po cold start)
- 3 nowe pliki, 3 zmodyfikowane

---

## [2026-02-22] - Sesja 10: Linux Migration Prep (Mini PC)

### Changed
- **`maria_core/sys/config.py`** - Dodano `python-dotenv` loading + `OLLAMA_BASE_URL` z env var
- **`maria_core/sys/maria_heartbeat.py`** (v1.3 -> v1.4):
  - Usuniety hardcoded `C:\Users\eras-\...\ollama.exe`
  - `os.startfile()` (Windows-only) -> `subprocess.Popen()` (cross-platform)
  - Ollama wykrywana przez `shutil.which("ollama")` + env var `OLLAMA_PATH`
  - Health check uzywa `OLLAMA_BASE_URL` z config
- **`maria_core/sys/self_evolver.py`** - hardcoded `localhost:11434` -> `OLLAMA_BASE_URL` z config
- **`maria_ui/config.py`** - CORS auto-wykrywa LAN IP + env var `MARIA_CORS_ORIGINS`
- **`main.py`** - Ostatni emoji (linia 104) usuniety (ADR-005)
- **`run_ui.py`** - `debug=True` -> `debug=DEBUG_MODE`, port/host z env vars

### Added
- **`.env.example`** - Template konfiguracji (OLLAMA_BASE_URL, MARIA_PIN, porty)
- **`scripts/maria.service`** - Systemd template dla REPL
- **`scripts/maria-ui.service`** - Systemd template dla Web UI
- **`scripts/INSTALL_LINUX.md`** - Instrukcja instalacji na Linux
- **`python-dotenv`** w `maria_core/requirements.txt`

### Target Hardware
- NiPoGi Mini PC (AMD Ryzen 5 7430U, 32GB RAM, 1TB SSD)
- Ubuntu/Debian Linux

### Statistics
- **268 tests passing** (zero regresji)
- 7 plikow zmodyfikowanych, 4 nowe pliki

---

## [2026-02-01] - Sesja 6 & 7: Emoji Cleanup + Web UI Complete

### Added - Web UI (`maria_ui/`)
- **Sprint 1:** Minimalny Flask server z podstawowa struktura
- **Sprint 2:** Integracja z homeostasis (psutil, event_logger)
- **Sprint 3:** WebSocket chat z OllamaBrain
- **Sprint 3.5:** Zabezpieczenia:
  - PIN login (domyslnie: 1234)
  - Rate limiting (2 msg / 60s)
  - Input sanitization (XSS protection)
  - Session management
- **Sprint 4:** Full status dashboard (`/status`):
  - System metrics (RAM, CPU, Disk, Uptime)
  - Homeostasis (mode, health score, alerts)
  - Brain stats (model, history, API calls)
  - Memory stats (semantic graph, knowledge index)
  - Events list (last 10)
- **Sprint 5:** Proaktywne powiadomienia:
  - Toast notifications (prawy gorny rog)
  - Auto-alerty przy zmianie trybu homeostasis
  - Auto-alerty przy CRITICAL/ALERT severity
  - Powiadomienia w chacie jako system messages
  - Background monitor thread (5s interval)

### New Files
```
maria_ui/
├── __init__.py
├── app.py              # 755 lines - Flask + SocketIO + notifications
├── config.py           # Centralized configuration
├── requirements.txt    # flask, flask-socketio, psutil, simple-websocket
└── templates/
    ├── login.html      # PIN authentication page
    ├── index.html      # Chat interface v0.5
    └── status.html     # Full dashboard
run_ui.py               # Entry point for Web UI
```

### Fixed
- **Emoji cleanup:** Usunieto 94 wystapienia emoji z 13 plikow Python
  - Zamieniono na tekst ASCII: [OK], [WARN], [ERROR], [INFO], etc.
  - Naprawiono problemy z PowerShell encoding
- **Chat history persistence:** Wiadomosci nie znikaja przy nawigacji miedzy stronami

### API Endpoints
| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/` | GET | Yes | Chat interface |
| `/login` | GET/POST | No | PIN login |
| `/logout` | GET | No | Clear session |
| `/status` | GET | Yes | Status dashboard |
| `/api/status` | GET | Yes | Basic status JSON |
| `/api/status/full` | GET | Yes | Full metrics JSON |
| `/api/chat/history` | GET | Yes | UI chat history |
| `/api/notify/test` | POST | Yes | Send test notification |
| `/api/notify/send` | POST | Yes | Send custom notification |
| `/api/health` | GET | No | Health check |

### WebSocket Events
| Event | Direction | Description |
|-------|-----------|-------------|
| `connect` | Client->Server | Initiate connection |
| `connected` | Server->Client | Connection confirmed |
| `chat_message` | Client->Server | User sends message |
| `chat_response` | Server->Client | Maria's response |
| `chat_status` | Server->Client | Thinking indicator |
| `clear_history` | Client->Server | Clear conversation |
| `history_cleared` | Server->Client | Confirmation |
| `proactive_notification` | Server->Client | Auto-alerts |

### Configuration (`maria_ui/config.py`)
```python
UI_PIN = "1234"                    # Login PIN
RATE_LIMIT_MESSAGES = 2            # Max messages per window
RATE_LIMIT_WINDOW_SEC = 60         # Window duration
MAX_MESSAGE_LENGTH = 2000          # Max chars per message
MAX_HISTORY_MESSAGES = 20          # Brain history limit
DEBUG_MODE = False                 # Production mode
```

---

## [2026-01-31] - Sesja 5: Event Logger (Lab Reports)

### Added
- `agent_core/homeostasis/event_logger.py` - Persistent event logging system
  - Logs mode transitions with full trigger context (constraint, value, threshold)
  - Logs alerts with severity and values
  - Logs state snapshots periodically
  - Duration tracking for each mode
  - Thread-safe buffered writes to JSONL
- `/homeostasis events N` - Show last N events from log
- `/homeostasis summary` - Show session summary (uptime, mode changes, alerts)
- `agent_core/tests/test_event_logger.py` - 16 tests for event logger

### Changed
- `HomeostasisCore` now integrates with EventLogger
- `AlarmDispatcher` now logs alerts to JSONL
- Event log file: `meta_data/homeostasis_events.jsonl`

### Statistics
- **216 tests passing** (200 previous + 16 new)

### Event Log Format (Lab Report style)
```jsonl
{"ts": 1706700000, "event_type": "mode_change", "from_mode": "active", "to_mode": "reduced", "trigger": {"constraint": "ram_low", "value": 18.5, "threshold": 20}, "metrics": {...}, "duration_in_prev_mode_sec": 3600}
{"ts": 1706700060, "event_type": "alert", "severity": "WARNING", "message": "RAM below 30%", "value": 28.5, "threshold": 30}
```

---

## [2026-01-28] - Sesja 4: Etap 3 + Etap 4 Complete

### Added
- `agent_core/tests/test_integration_legacy.py` - 26 integration tests with real legacy modules
- `/homeostasis` REPL command (status/start/stop)
- Mode gating in main.py for learning cycle protection
- Version 1.2 of main.py with full homeostasis integration

### Fixed
- `ResourceWatchdogAdapter`: Fixed `ram_percent` → `memory_pressure` (ResourceMetrics property)
- Integration tests API mismatches:
  - `get_latency_ms()` → `get_last_latency_ms()`
  - `is_loaded()` → `is_minimized()`
  - `_tick()` → `_execute_tick()`
  - `_state` → `state`
  - `current_hour` → `hour_of_day`

### Integration Tests Results
| Test Class | Tests | Status |
|------------|-------|--------|
| TestMemoryStoreAdapterLegacy | 5 | PASSED |
| TestSemanticGraphAdapterLegacy | 6 | PASSED |
| TestResourceWatchdogAdapterLegacy | 3 | PASSED |
| TestBrainMemoryAdapterLegacy | 5 | PASSED |
| TestFullIntegration | 5 | PASSED |
| TestPerformance | 2 | PASSED |

### Statistics
- **200 tests passing** (174 unit + 26 integration)
- All 4 adapters verified with real legacy modules
- HomeostasisCore tick latency < 200ms

### Commits
- `3d85d04` - Etap 3: Integration tests with real legacy modules
- `4ec6e28` - Etap 4: Homeostasis integration in main.py with REPL commands

---

## [2026-01-27] - Sesja 3: Etap 1 + Etap 2 Complete

### Added
- `agent_core/` directory structure (Etap 1)
- All homeostasis modules with full implementations
- 174 unit tests covering all modules
- 4 adapters wrapping legacy maria_core modules

### Commits
- `5186afb` - Etap 1: agent_core/ skeleton structure with full implementations
- `9c24a55` - Etap 2: Create adapters wrapping legacy maria_core

---

## [2026-01-26] - Sesja 2: Mapowanie Homeostazy + Resolved Questions

### Added
- `docs/MAP_HOMEOSTASIS.md` - pelna mapa wymagan spec → moduly docelowe (~83 wymagania)
- `docs/REFACTOR_PLAN.md` - 5-etapowy plan migracji do architektury agent_core/

### Updated
- `docs/DECISIONS.md` - zaktualizowano do v0.2:
  - ADR-004 zmieniony na ACCEPTED (JSONL = source of truth)
  - Q-001 do Q-005 resolved z odpowiedziami od wlasciciela
  - Wszystkie open questions zamkniete

### Decisions Recorded
- Q-001: archive/ oznaczony jako deprecated, nie uzywany
- Q-002: main.py i run_maria.py dzialaja ALTERNATYWNIE (nie rownolegle)
- Q-003: max_iterations=0 to celowe (infinite loop), zmienic na None dla czytelnosci
- Q-004: maria_web_learning.py i maria_api_bridge.py to future features, nie implementowac teraz
- Q-005 → ADR-004: JSONL = source of truth, graf = derived cache

### Statistics from MAP_HOMEOSTASIS.md
- ~65 wymagan oznaczonych jako `missing`
- ~8 wymagan `partial`
- ~10 wymagan `adapter` (wrap existing code)
- Szacowany naklad: 10-12 sesji roboczych

---

## [2026-01-26] - Sesja 1: Inicjalizacja dokumentacji + Stabilizacja P0

### Added
- `docs/WORKFLOW.md` - zasady pracy zespolowej i sesyjnej
- `docs/ARCHITECTURE.md` - opis aktualnej i docelowej architektury
- `docs/ROADMAP.md` - fazy rozwoju (A: Stabilizacja, B: Homeostasis, C: Optymalizacja)
- `docs/STABILIZATION_PLAN.md` - szczegolowa checklista bugow do naprawy
- `docs/DECISIONS.md` - ADR + open questions
- `docs/CHANGELOG.md` - ten plik
- `docs/SESSION_LOG.md` - dziennik pracy

### Discovered
- 8 bugow zidentyfikowanych (3x P0, 3x P1, 2x P2)
- 5 open questions do wyjasnienia z wlascicielem

### Fixed (5 bugow naprawionych)
- **BUG-001** `main.py`: Usunieto przedwczesne `if __name__` i konfliktowy import
- **BUG-002** `perception.py`: Poprawiono wciecia klasy Perception (metody sa teraz w klasie)
- **BUG-003** `learning_agent.py`: Usunieto przypadkowo wklejony debug code z learn_chunk()
- **BUG-004** `perception.py`: Zamieniono hardcoded sciezki na KNOWLEDGE_INDEX z config
- **BUG-006** `orchestrator.py`: StripEmojiFilter teraz usuwa tylko emoji, zachowuje polskie znaki

### Verified
- Wszystkie krytyczne importy dzialaja poprawnie
- Zainstalowano brakujace zaleznosci (requests, psutil, ollama)

---

## [Pre-2026] - Historia przed dokumentacja

> Uwaga: Ponizsze to rekonstrukcja na podstawie analizy kodu. Daty przybliozone.

### ~2025-11-30
- Utworzenie projektu DEAMONMARIA V2 (prekursor M.A.R.I.A.)
- Podstawowa struktura: perception, learning, exam, memory
- Konfiguracja Ollama

### ~2025-12-07
- Dodanie semantic_graph.py
- Rozbudowa meta_controller.py
- Dodanie resource_watchdog.py

### ~2025-12-08
- main.py - rozszerzony REPL z wieloma komendami
- brain_memory_integration.py

> Start wlasciwego projektu M.A.R.I.A.: 2025-11-14. Powyzsze daty rekonstrukcja z kodu.

---

*Aktualizuj ten plik przy kazdej znaczacej zmianie.*
