# M.A.R.I.A. - Kompletna dokumentacja architektury

**Meta Analysis Recalibration Intelligence Architecture**
Wersja: 2026-04-07 | 383 plikow Python | 113 552 linii kodu | 3352 testow

---

## 1. Czym jest M.A.R.I.A.?

Lokalny, autonomiczny agent AI do samodzielnego uczenia sie z plikow tekstowych. Dziala offline na Mini PC (AMD Ryzen 5, 32GB RAM), uzywa Ollama (llama3.1:8b) jako glowny mozg i NIM API jako wsparcie do nauki.

**Kluczowe cechy:**
- Autonomiczna nauka z plikow w input/ (bez interwencji czlowieka)
- System celow z audytem i PROPOSED flow (operator zatwierdza)
- 13 kontraktow architektonicznych (K1-K13) tworzacych cognitive core
- Embedding-based semantic memory (nomic-embed-text, 768-dim)
- Telegram bridge do komunikacji z operatorem
- Web UI (Flask) z 8-panelowym dashboardem

**Hardware:** Mini PC NiPoGi, AMD Ryzen 5 7430U, 32GB RAM, 1TB SSD, 6TB HDD archiwum
**OS:** Ubuntu 22.04 LTS | **IP:** (local network)
**Uzytkownicy:** maria (aplikacja, bez sudo), deployadmin (admin)

---

## 2. Struktura katalogow

```
maria/
  maria.py                 # V3 UnifiedLauncher (daemon + Web UI, systemd)
  main.py                  # Tryb REPL (interaktywny)
  run_maria.py             # Legacy daemon (replaced by maria.py)
  run_ui.py                # Legacy Web UI (replaced by maria.py)
  maria_core/              # Legacy (stary kod, adaptery w agent_core/adapters/)
  agent_core/              # Nowy system (K1-K13 + infrastruktura)
    homeostasis/           # Petla 1Hz, sensory, tryby pracy
    perception/            # K1: ujednolicony format zdarzen
    sandbox/               # K2: izolacja nauki od produkcji
    goals/                 # K3: system celow z audytem
    evaluation/            # K4: metryki READ-ONLY
    planner/               # K5: petla ReAct (OBSERVE->THINK->ACT->EVALUATE)
    world_model/           # K6: beliefs z confidence i evidence
    autonomy/              # K7: klasyfikacja akcji, rate limity, eskalacja
    deliberation/          # K8: strategie wielokrokowe
    meta_cognition/        # K9: refleksja, sledzenie zalozen
    action_safety/         # K10: audyt akcji, walidacja efektow
    experiment/            # K11: autonomiczny tuning parametrow
    self_analysis/         # K12: analiza wlasnych logow silniejszym modelem
    creative/              # K13: modul strategiczny, napecia, meta-cele
    teacher/               # Agent Nauczyciel (decyduje co uczyc)
    consciousness/         # Osobowosc, sny, ciaglosc miedzy sesjami
    llm/                   # Router LLM, NIM, Codex, ModelScheduler
    semantic/              # Semantic Memory (nomic-embed-text, vector store)
    web_source/            # Wikipedia PL + RSS -> input/
    telegram/              # ClawBot - komunikacja z operatorem
    effector/              # OpenClaw - wykonywanie akcji zewnetrznych
    critic/                # Faza G: audyt jakosci wiedzy (7 wymiarow)
    cross_validation/      # Faza F: walidacja wielozrodlowa
    bulletin/              # Learning Upgrade: audit, gap planner, expert bridge
    vision/                # Vision: sensor, preprocessing, motion, scene, cortex, LLaVA
    orchestrator/          # V3: OnboardingFlow, TaskOrchestrator, ProductShell (15 modulow)
    routing/               # CapabilityRouter (dispatch zamiast if/elif)
    tracing/               # Episode-based decision traceability
    storage/               # Archiwizacja logow na 6TB HDD
    introspection/         # READ-ONLY analiza wlasnego kodu (AST)
    memory/                # MemoryQuery - unified API z provenance
    adapters/              # Mosty do legacy maria_core/
    registry/              # ModuleRegistry, SharedContext, CommandDispatcher
    modules/               # Moduly REPL (homeostasis_module, planner_module...)
    tests/                 # 92 pliki testowe, 3352 testow
  maria_ui/                # Web UI (Flask + SocketIO)
  input/                   # Pliki do nauki (web_wiki_*, web_rss_*, expert_*)
  memory/                  # knowledge_index.jsonl, longterm_memory, exam_results
  meta_data/               # Logi JSONL, konfiguracja JSON, wektory
  docs/                    # Dokumentacja, specyfikacje, plany
  claude_notes/            # Notatki Claude miedzy sesjami
  scripts/                 # Systemd, backup, instalacja
  archive/                 # Stare pliki (legacy 2026-02-01)
```

---

## 3. Moduly - szczegolowy opis

### 3.1 Homeostasis (homeostasis/)

**Cel:** Petla glowna systemu, monitoring zdrowia, regulacja trybow pracy.

**Pliki:**
| Plik | Opis |
|------|------|
| core.py | HomeostasisCore - petla 1Hz z 11 fazami |
| state_model.py | Mode (ACTIVE/REDUCED/SLEEP/SURVIVAL), ResourceMetrics, SystemState |
| interpreter.py | Konwersja metryk na stan semantyczny (EMA smoothing) |
| constraints.py | Walidacja progowa, generowanie alertow |
| mode_regulator.py | Decyzja o trybie na podstawie health score |
| actions.py | Generowanie i wykonywanie akcji korekcyjnych |
| event_logger.py | Logowanie zdarzen do JSONL |
| time_awareness.py | Swiadomosc czasu (pora dnia, data, dzien tygodnia) |
| pulse.py | Micro-korekty 100ms (opcjonalne) |
| snapshot.py | Atomowe snapshoty stanu |
| api.py | HomeostasisInterface + EventBus |

**Fazy ticka (1Hz):**

| Faza | Co robi | Czestotliwosc |
|------|---------|---------------|
| 1 SENSE | Odczyt 5 sensorow (CPU, RAM, temp, czas, cognitive) | Kazdy tick |
| 2 INTERPRET | EMA smoothing, etykiety semantyczne | Kazdy tick |
| 3 VALIDATE | Sprawdzenie progow, alerty | Kazdy tick |
| 4 DECIDE MODE | ACTIVE/REDUCED/SLEEP/SURVIVAL | Kazdy tick |
| 5 GENERATE ACTIONS | Akcje korekcyjne | Kazdy tick |
| 6 EXECUTE ACTIONS | Sygnaly do modulow | Kazdy tick |
| 7 UPDATE HEALTH | health_score 0.0-1.0 | Kazdy tick |
| 8 PERCEIVE | PerceptionEvents -> PerceptionBuffer | Kazdy tick |
| 9 AUDIT & LOG | Snapshot do JSONL | Co 60 tickow |
| 9.5 MODEL SCHEDULER | Load/unload modeli LLM | Kazdy tick |
| 10 PLANNER | PlannerCore.run_cycle() (w watku) | Co 60 tickow + eventy |
| 11 TELEGRAM | Poll operatora, powiadomienia | Co 30s |

**Dane:** meta_data/homeostasis_events.jsonl

---

### 3.2 Perception (perception/) - K1

**Cel:** Ujednolicony format zdarzen z wszystkich zrodel.

**Kluczowe klasy:**
- **PerceptionEvent** - frozen dataclass: event_id, source, event_type, priority, ttl, payload
- **PerceptionSource** - enum: SENSOR, USER, LEARNING, EXAM, CONSCIOUSNESS, TEACHER, PLANNER, SYSTEM
- **PerceptionBuffer** - kolejka FIFO (maxlen=200), dedup, drain expired

**Wzorzec:** Tick Aggregator (ADR-009) - sensory + zdarzenia zewnetrzne agregowane co tick

---

### 3.3 Sandbox (sandbox/) - K2

**Cel:** Izolacja nauki od produkcji. Kazda nauka przez sandbox, promote() jako jedyny most.

- **SandboxManager** - create session, seed data, record changes, promote/discard
- **Transaction log** - START/COMMIT/ROLLBACK, recovery po crashu
- **Dane:** meta_data/sandbox_sessions.jsonl

---

### 3.4 Goal System (goals/) - K3

**Cel:** Jawne cele z audytem, zamiast niejawnych progow.

- **GoalType:** META, USER, LEARNING, MAINTENANCE
- **GoalStatus:** PROPOSED -> PENDING -> ACTIVE -> ACHIEVED/FAILED/ABANDONED
- **GoalStore:** JSONL append-only, max 20 active, max 3 proposed, 72h timeout
- **Seed goals:** goal-meta-learn (nauka autonomiczna), 3x maintenance (health, CPU, RAM)
- **Dane:** meta_data/goals.jsonl

---

### 3.5 Evaluation (evaluation/) - K4

**Cel:** READ-ONLY observer, 5 metryk z logow JSONL.

**Metryki:** learning_velocity, retention_rate, knowledge_coverage, system_stability, personality_growth

- Pisze TYLKO do evaluation_reports.jsonl
- Czestotliwosc: co 1h
- Zero LLM, zero side effects

---

### 3.6 Planner (planner/) - K5

**Cel:** ReAct loop laczacy K1-K4. Rule-based, zero LLM, deterministyczny.

**Cykl:** GUARD -> PERCEIVE -> SELECT GOAL -> PLAN -> EXECUTE -> EMIT -> LOG

**ActionType (14):**
LEARN, EXAM, REVIEW, EVALUATE, MAINTENANCE, FETCH, EXPERIMENT, EFFECTOR, SELF_ANALYZE, CREATIVE, ASK_EXPERT, VALIDATE, CRITIQUE, NOOP

**Pliki:**
| Plik | Opis |
|------|------|
| planner_core.py | Centralny ReAct loop, 20k linii |
| planner_guard.py | 5 regul gating (health, mode, sandbox, retention, teacher) |
| goal_selector.py | Aging factor (priority *= 1 + hours * 0.1) |
| action_executor.py | Delegacja do subsystemow (lub CapabilityRouter) |
| planner_model.py | Plan, PlanStatus, ActionType, create_plan() |

**Priorytet akcji (w _decide_learning_action):**
1. P1: Egzamin (pending exams)
2. P2: Nauka (new chunks to learn)
3. P3: Nowe pliki (indexed "new")
4. P4: Review (retention < 0.8)
5. P5: Fetch (pobierz z internetu)
6. P6: Ask Expert (pytaj LLM)
7. P7: Post NEED_MATERIAL na bulletin board
8. Fallback: NOOP

**Dane:** meta_data/planner_state.json, meta_data/planner_decisions.jsonl

---

### 3.7 World Model (world_model/) - K6

**Cel:** System beliefs z typami, confidence, evidence tracking.

- **Belief:** frozen dataclass - entity, entity_type, belief_type (FACT/OBSERVATION/HYPOTHESIS), confidence (0-1), evidence tuples
- **BeliefStore:** JSONL (MERGE semantics), cap 2000
- **BeliefBuilder:** Buduje beliefs z knowledge_index, exam_results
- **WorldModelQuery:** get_knowledge_gaps(), find_beliefs_for_topic()
- **Maintenance:** decay (FACT 90d, OBSERVATION 30d, HYPOTHESIS 14d), dedup, compact, prune

**Dane:** meta_data/beliefs.jsonl

---

### 3.8 Autonomy Policy (autonomy/) - K7

**Cel:** Klasyfikacja akcji, rate limiting, eskalacja.

- **Klasyfikacja:** FREE (chat) / GUARDED (learn, fetch) / RESTRICTED (effector) / FORBIDDEN (delete)
- **Rate limiter:** Sliding window per ActionType (np. fetch 10/h, ask_expert 10/h)
- **Authority levels (Phase 5):** OBSERVE / SUGGEST / CONFIRM / BOUNDED / UNRESTRICTED
- **ApprovalQueue:** HITL dla efektorow (Telegram /efapprove, /efreject)
- **ToolBudgetManager:** Per-tool rate limits z exponential backoff

**Dane:** meta_data/autonomy_decisions.jsonl, meta_data/authority_config.json

---

### 3.9 Deliberation (deliberation/) - K8

**Cel:** Strategie wielokrokowe (zamiast jednorazowych akcji).

- **Strategy:** lista krokow (Step), kazdy z warunkami sukcesu/failure
- **Templates:** EXAM_PREP, KNOWLEDGE_REVIEW, ERROR_RECOVERY
- **IntentTracker:** JSONL persistence aktywnych strategii

**Dane:** meta_data/deliberation_intents.jsonl

---

### 3.10 Meta-Cognition (meta_cognition/) - K9

**Cel:** Refleksja, sledzenie zalozen, porownanie oczekiwania vs wynik.

- **Reflector:** record_decision() BEFORE, reflect() AFTER
- **ConfidenceTracker:** Per-action confidence (exponential decay)
- **needs_human():** Sygnal ze Maria potrzebuje pomocy operatora

**Dane:** meta_data/reflections.jsonl

---

### 3.11 Action Safety (action_safety/) - K10

**Cel:** Audyt KAZDEJ akcji, walidacja efektow.

- **SafetyMode:** AUTO_COMMIT / AUDIT_ONLY / STAGED
- **AuditLog:** JSONL, kazda akcja z before/after state
- **EffectValidator:** capture_state() before, validate_effects() after

**Dane:** meta_data/action_audit.jsonl

---

### 3.12 Experiment System (experiment/) - K11

**Cel:** Autonomiczny tuning 12 parametrow (np. teacher_iterations, spaced_rep_factor).

- **ProposalEngine:** Skanuje metryki, generuje propozycje zmian
- **ExperimentRunner:** Zmienia parametr (setattr), mierzy wynik, przywraca (finally)
- **ReportGenerator:** ADOPT / REJECT / INCONCLUSIVE
- **Cross-metric guard:** ADOPT zablokowany jesli guard metric spada >3%
- **Human gate:** Propozycje wymagaja zatwierdzenia operatora

**Dane:** meta_data/experiment_reports.jsonl, meta_data/proposals.jsonl

---

### 3.13 Self-Analysis (self_analysis/) - K12

**Cel:** Maria analizuje wlasne logi silniejszym modelem.

- **StateCollector:** Kompresuje 8 zrodel JSONL do summary
- **ExternalAnalyzer:** Cascade: NIM API -> Claude CLI -> local qwen3:8b
- **RecommendationApplier:** Tworzy PROPOSED goals z rekomendacji
- **Trigger:** Co 24h, lub K9 needs_human, lub low retention

**Dane:** meta_data/self_analysis_reports.jsonl

---

### 3.14 Creative Module (creative/) - K13

**Cel:** Organ strategiczny - napecia, insights, meta-cele.

**20 plikow** - najzlozoniejszy modul:
- **TensionDetector:** 7 kategorii napiec (repetition, misalignment, over_restriction...)
- **ReflectionWorkspace:** Sesje refleksji z bounded context
- **MetaGoalEngine:** Generuje meta-cele z NIM API
- **ReframeEngine:** Przeramowanie problemow
- **ExplorationEngine:** Eksploracja nowych kierunkow
- **IdentityProfile + PersonalityPolicy:** Styl kognitywny wplywajacy na wagi
- **MemoryRetriever + MemorySummarizer:** Selektywna pamiec (semantic + keyword)
- **TokenBudget:** RPM-based gating (40 req/min)

**Dane:** meta_data/creative_events.jsonl, creative_meta_goals.jsonl, creative_journal.jsonl, creative_tension_streaks.jsonl, creative_workspace_sessions.jsonl

---

### 3.15 Teacher (teacher/)

**Cel:** Decyduje co i kiedy uczyc. 6-priorytetowy silnik (P1-P6).

- **KnowledgeAnalyzer:** Analiza JSONL, zero LLM
- **SpacedRepetitionScheduler:** Interwaly powtork na bazie wynikow
- **TeacherAgent:** run_session(max_iterations) - glowna petla nauki
- **Auto-trigger:** ACTIVE + idle >= 10min -> sesja nauki (3 iteracje)

---

### 3.16 Consciousness (consciousness/)

**Cel:** Osobowosc, ciaglosc, sny.

- **TraitEvolver + TraitCatalog:** 7 cech osobowosci z dynamiczna ewolucja
- **ConversationMemory:** Rolling context z kondensacja LLM
- **SleepProcessor + DreamGenerator:** Konsolidacja pamieci w SLEEP
- **IdentityStore:** Session count, uptime, birth date (2025-11-14)

**Dane:** meta_data/consciousness_identity.json, personality_experiences.jsonl, dream_log.jsonl

---

### 3.17 LLM (llm/)

**Cel:** Routing, budzet, lifecycle modeli.

**Modele:**
| Rola | Model | RAM | Stan |
|------|-------|-----|------|
| MODEL-01 Planner | qwen3:8b | 5.5GB | cold (on-demand) |
| MODEL-02 Executor | llama3.1:8b | 5GB | warm (always loaded) |
| MODEL-03 Coder | qwen2.5-coder:7b | 5GB | cold |
| MODEL-04 Triage | rule-based | 0GB | instant |
| MODEL-05 Memory | nomic-embed-text | 274MB | cold |
| MODEL-06 NIM | z-ai/glm5 | 0GB (API) | remote |
| MODEL-07 Encyclopedia | Codex CLI (ChatGPT) | 0GB | remote |
| OpenClaw | qwen2.5:3b | 2GB | cold (osobna instancja) |

**Golden rule:** MODEL-02 warm, reszta on-demand. Heavy mutex: MODEL-01 i MODEL-03 nigdy jednoczesnie.

**LLMRouter:** think() -> Ollama, analyze_task() -> NIM (fallback Ollama), ask_encyclopedia() -> Codex -> NIM -> Ollama

**Dane:** meta_data/nim_token_usage.json, llm_tape.jsonl, model_health.json, codex_interactions.jsonl

---

### 3.18 Semantic Memory (semantic/)

**Cel:** Embedding-based similarity search.

- **EmbeddingModel:** nomic-embed-text via Ollama, 768-dim, cosine similarity
- **VectorStore:** In-memory + JSONL persist, 4 namespaces (knowledge, beliefs, hints, memories)
- **Auto-indexer:** Background indexing at startup + incremental after fetch/learn
- **275+ vectors** zaindexowanych

**Dane:** meta_data/semantic_vectors.jsonl

---

### 3.19 Web Source (web_source/)

**Cel:** Pobieranie materialow edukacyjnych z internetu.

- **WikiClient:** Wikipedia PL API (search + fetch)
- **RSSClient:** RSS/Atom (stdlib XML)
- **TopicSuggester:** EXPAND top tematow + EXPLORE nowe tagi
- **ContentWriter:** Zapis do input/ jako web_{wiki|rss}_{slug}.txt
- **FetchRegistry:** Dedup (MERGE semantics)

**Dane:** meta_data/web_fetch_registry.jsonl, input/web_*.txt

---

### 3.20 Telegram (telegram/)

**Cel:** Komunikacja Maria <-> operator.

**Komendy:**
/status, /goals, /trace, /memory, /learn, /approve, /reject, /priority, /efapprove, /efreject, /efstatus, /authority, /board, /validate, /beliefs, /restart, /help

**Powiadomienia:** creative tensions, K12 recommendations, K9 needs_human, health drop, mode change, K7 blocks, startup, critique (CRITICAL only)

---

### 3.21 Effector - OpenClaw (effector/)

**Cel:** Wykonywanie akcji zewnetrznych (shell, web, pliki).

- **Subprocess:** sudo -u deployadmin openclaw
- **7 dozwolonych narzedzi:** exec, read, write, web_fetch, web_search, message, cron
- **K7:** RESTRICTED, rate limit 10/h
- **Fallback:** Maria dziala bez OpenClaw

---

### 3.22 Critic (critic/) - Faza G

**Cel:** Audyt jakosci wiedzy (7 wymiarow). READ-ONLY, zero LLM.

**Wymiary:** contradiction, overconfident, underconfident, shallow, disputes, coverage, stale
**Trigger:** Co 8h, lub po validate/maintenance
**Wynik:** PROPOSED goals z CritiqueApplier (max 3)

**Dane:** meta_data/critique_reports.jsonl

---

### 3.23 Cross Validation (cross_validation/) - Faza F

**Cel:** Walidacja wiedzy wieloma zrodlami.

- **CrossValidator:** Porownuje beliefs z drugim LLM (NIM)
- **ConfidenceScorer:** Wynik walidacji -> confidence update
- **DisputeLog:** Sprzecznosci miedzy zrodlami

**Dane:** meta_data/disputes.jsonl

---

### 3.24 Bulletin Board (bulletin/) - Learning Upgrade

**Cel:** Tablica potrzeb poznawczych. Oddziela temat od materialu.

**5 faz:**
1. **BulletinStore** - NEED_MATERIAL, NEED_TEST, NEED_REVIEW, READY_TO_LEARN, WAITING_HUMAN
2. **KnowledgeAuditor** - sprawdza MemoryQuery, beliefs, critic, exams -> AuditReport z 7 typami luk
3. **GapPlanner** - decyduje: ASK_EXPERT (z context_prompt), REVIEW, RUN_EXAM, DECOMPOSE, WAIT_HUMAN
4. **ExpertBridge** - celowane pytania do LLM ("Maria wie X, potrzebuje Y")
5. **Full wiring** - zapis do input/, bulletin RESOLVED, standard learn pipeline

**Dane:** meta_data/cognitive_bulletin.jsonl

---

### 3.25 Routing (routing/)

**Cel:** Registry-based dispatch zamiast 13-way if/elif.

- **CapabilityRouter:** register(name, handler, spec), dispatch(plan)
- **15 zarejestrowanych capabilities** (learn, exam, review, evaluate, maintenance, fetch, experiment, effector, self_analyze, creative, ask_expert, validate, critique, noop + fallback)
- **Dual-path:** Router gdy dostepny, legacy fallback

---

### 3.26 Tracing (tracing/)

**Cel:** Korelacja decyzji przez episode_id.

- **episode_id:** Thread-local, generowany na poczatku kazdego cyklu plannera
- **Propagacja:** planner -> K7 -> K10 -> LLM tape -> audit
- **TraceStore:** JSONL, bounded 200 in-memory

**Dane:** meta_data/decision_traces.jsonl

---

### 3.27 Storage (storage/)

**Cel:** Archiwizacja logow na 6TB HDD.

- **LogArchiver:** Przenosi stare rekordy -> /mnt/storage/data/logs/
- **DailySummary:** Kompakcja do dziennych podsumowanm
- **Trigger:** Faza SLEEP w homeostasis
- **Backup:** 30 kopii, cron o 3:00

---

## 4. Przeplywy danych

### 4.1 Pipeline nauki

```
input/ (pliki .txt)
  |
  v
[Perception] skanuje katalog, hash plikow
  |
  v
knowledge_index.jsonl  (status: new -> learning -> complete -> examined)
  |
  v
[LearningAgent] czyta plik, wysyla do LLM
  |
  v
maria_longterm_memory.jsonl  (podsumowania, tagi, kluczowe pojecia)
  |
  v
[ExamAgent] testuje retencje
  |
  v
exam_results.jsonl  (wyniki egzaminow)
  |
  v
[BeliefBuilder] buduje beliefs
  |
  v
beliefs.jsonl  (FACT/OBSERVATION/HYPOTHESIS z confidence)
```

### 4.2 Cykl plannera (co 60 tickow)

```
[Homeostasis] -> health_score, mode
  |
  v
[PlannerGuard] -> czy mozna planowac?
  |
  v
[GoalSelector] -> wybierz cel (aging factor)
  |
  v
[K8 Deliberation] -> strategia wielokrokowa (opcjonalnie)
  |
  v
[_decide_learning_action] -> P1-P7 priorytet
  |
  v
[K7 Autonomy] -> czy akcja dozwolona?
  |
  v
[K9 MetaCognition] -> record_decision() BEFORE
  |
  v
[K10 ActionSafety] -> capture_state() BEFORE
  |
  v
[ActionExecutor / CapabilityRouter] -> delegacja do subsystemu
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

### 4.3 Pobieranie materialow (FETCH + ASK_EXPERT)

```
[Planner P5: FETCH]
  |
  v
[TopicSuggester] -> wybierz temat z KnowledgeAnalyzer
  |
  v
[WikiClient / RSSClient] -> pobierz artykul
  |
  v
[ContentWriter] -> input/web_{wiki|rss}_{slug}.txt

[Planner P6: ASK_EXPERT]
  |
  v
[KnowledgeAuditor] -> audit wiedzy na temat
  |
  v
[GapPlanner] -> context_prompt ("Maria wie X, potrzebuje Y")
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

### 4.4 Cykl kreatywny

```
[K4 Evaluation] -> metryki
  |
  v
[TensionDetector] -> 7 kategorii napiec
  |
  v
[ReflectionWorkspace] -> sesja refleksji
  |
  v
[MetaGoalEngine / NIM] -> meta-cele
  |
  v
[GoalAdapter] -> PROPOSED goals w K3
  |
  v
[Operator /approve] -> aktywacja celu
```

### 4.5 Tracing (episode_id)

```
generate_episode_id()  ->  "ep-{timestamp}-{random}"
  |
  v
Thread-local storage (agent_core/tracing/episode.py)
  |
  v
Wszystkie subsystemy czytaja current_episode_id():
  - K7 autonomy_decisions.jsonl
  - K10 action_audit.jsonl
  - LLM llm_tape.jsonl / codex_interactions.jsonl
  - K9 reflections.jsonl
  - Planner planner_decisions.jsonl
  |
  v
decision_traces.jsonl  (pelny trace per episode)
  |
  v
Query: get_by_episode_id(), get_failed(), get_by_goal_id()
```

---

## 5. Pliki danych

### 5.1 JSONL (append-only logi)

| Plik | Rozmiar | Writer | Czestotliwosc |
|------|---------|--------|---------------|
| planner_decisions.jsonl | 8.4 MB | planner | ~1/min |
| decision_traces.jsonl | 5.6 MB | tracing | ~1/min |
| autonomy_decisions.jsonl | 5.3 MB | K7 | ~1/min |
| action_audit.jsonl | 5.0 MB | K10 | ~1/min |
| semantic_vectors.jsonl | 3.3 MB | semantic | on index |
| reflections.jsonl | 2.3 MB | K9 | po kazdej akcji |
| homeostasis_events.jsonl | 1.3 MB | homeostasis | co 60 tickow |
| maria_longterm_memory.jsonl | 1.3 MB | learning | po nauce |
| exam_results.jsonl | 1.0 MB | exam | po egzaminie |
| dream_log.jsonl | 0.9 MB | consciousness | w SLEEP |
| teacher_plans.jsonl | 577 KB | teacher | periodycznie |
| codex_interactions.jsonl | 424 KB | Codex CLI | na zapytanie |
| evaluation_reports.jsonl | 424 KB | K4 | co 1h |
| personality_experiences.jsonl | 161 KB | consciousness | ciagnle |
| creative_events.jsonl | 124 KB | K13 | periodycznie |
| beliefs.jsonl | 107 KB | K6 (MERGE) | po nauce/egzaminie |
| self_analysis_reports.jsonl | 92 KB | K12 | co 24h |
| creative_meta_goals.jsonl | 91 KB | K13 (MERGE) | periodycznie |
| knowledge_index.jsonl | 68 KB | perception (MERGE) | na scan |
| web_fetch_registry.jsonl | 52 KB | web_source (MERGE) | na fetch |
| goals.jsonl | 17 KB | K3 (MERGE) | na zmiane |

### 5.2 JSON (konfiguracja)

| Plik | Cel |
|------|-----|
| planner_state.json | Stan cyklu plannera |
| consciousness_identity.json | Tozsamosc (session count, uptime) |
| model_health.json | Stan modeli LLM |
| nim_token_usage.json | Budzet tokenow NIM |
| authority_config.json | Poziomy uprawnien efektora |
| code_self_model.json | Wynik introspekcji kodu |

### 5.3 Archiwum (/mnt/storage/)

```
/mnt/storage/
  data/
    logs/        # Przeniesione stare rekordy JSONL
    summaries/   # Dzienne podsumowania (compacted)
  backups/       # Codzienne tar.gz o 3:00 (30 kopii)
  vision/        # (przygotowane na kamere)
```

---

## 6. Decyzje architektoniczne (ADR)

| ADR | Decyzja |
|-----|---------|
| ADR-001 | JSONL jako source of truth, graf jako derived cache |
| ADR-005 | Brak emoji w kodzie (kompatybilnosc terminali) |
| ADR-006 | Introspection READ-ONLY (Maria nie modyfikuje kodu) |
| ADR-008 | NIM do nauki, Ollama do chatu (hybrid routing) |
| ADR-009 | Tick Aggregator zamiast Event Bus (KISS) |
| ADR-010 | Sandbox-first learning |
| ADR-013 | Planner v1 rule-based (zero LLM, deterministyczny) |
| ADR-015 | Multi-organ model stack (heavy mutex, RAM tiers) |
| ADR-016 | OpenClaw jako efektor (tools/invoke, Maria = mozg) |
| ADR-021 | Embeddings (nomic-embed-text) zamiast keyword retrieval |
| ADR-022 | Episode-based tracing (thread-local correlation IDs) |
| ADR-023 | Unified MemoryQuery z provenance metadata |
| ADR-024 | Execution budgets (timeout na Ollama) |
| ADR-025 | Cross-metric validation (ADOPT blocked jesli guard degrades) |
| ADR-028 | Critic = coherence/calibration auditor, nie truth engine |

---

## 7. Kontrakty architektoniczne

| Kontrakt | Modul | Testy | Opis |
|----------|-------|-------|------|
| K1 | perception | 131 | Ujednolicony PerceptionEvent |
| K2 | sandbox | 44 | Izolacja nauki, promote() |
| K3 | goals | 63 | System celow z audytem |
| K4 | evaluation | 35 | Metryki READ-ONLY |
| K5 | planner | 82 | ReAct loop |
| K6 | world_model | 69 | Beliefs z confidence |
| K7 | autonomy | 45 | Klasyfikacja akcji, rate limity |
| K8 | deliberation | 49 | Strategie wielokrokowe |
| K9 | meta_cognition | 73 | Refleksja |
| K10 | action_safety | 52 | Audyt akcji |
| K11 | experiment | 67 | Tuning parametrow |
| K12 | self_analysis | 45 | Analiza silniejszym modelem |
| K13 | creative | 129 | Organ strategiczny |
| Faza F | cross_validation | 38 | Walidacja wielozrodlowa |
| Faza G | critic | 69 | Audyt jakosci wiedzy |

**Lacznie:** 3352 testow (92 pliki testowe)

---

## 8. Tryby uruchomienia

### Daemon (run_maria.py)
```bash
sudo systemctl start maria    # Start
sudo systemctl status maria   # Status
sudo journalctl -u maria -n 50 # Logi
```
- Bezglosny, petla 1Hz, planner co 60s
- Systemd wskrzesi po crashu (RestartSec=10)

### REPL (main.py)
```bash
source venv/bin/activate
python main.py
```
- Interaktywny, komendy /homeostasis, /plan, /teacher, /introspect...

### Web UI (run_ui.py)
```bash
sudo systemctl start maria-ui
# -> http://localhost:5000 (PIN auth)
```
- 8-panelowy dashboard, chat z Maria, architektura, eksperymenty

---

## 9. Kluczowe komendy REPL

| Komenda | Opis |
|---------|------|
| /homeostasis | Status systemu (mode, health, sensory) |
| /homeostasis start/stop | Kontrola petli |
| /plan | Ostatnia decyzja |
| /plan status | Cykle, plany, eval |
| /plan goals | Ranking celow |
| /teacher | Sesja nauki |
| /teacher status | Stan agenta |
| /learn | Automatyczna nauka z input/ |
| /learn stats | Statystyki bazy wiedzy |
| /introspect | Jak Maria widzi swoja architekture |
| /consciousness | Osobowosc i swiadomosc |
| /experiments | Propozycje i raporty |

---

## 10. Zaleznosci zewnetrzne

| Zaleznosc | Wersja | Cel |
|-----------|--------|-----|
| Ollama | latest | Lokalne LLM (llama3.1:8b, qwen3:8b, nomic-embed-text) |
| Flask | 3.x | Web UI |
| Flask-SocketIO | 5.x | WebSocket chat |
| psutil | 5.x | Metryki systemu |
| requests | 2.x | NIM API, Wikipedia, RSS |
| python-dotenv | 1.x | Konfiguracja .env |
| pytest | 9.x | Testy |

**Zero nowych deps:** RSS (stdlib xml.etree), Telegram (requests), Wikipedia (requests)

---

## 11. Historia i kamienie milowe

| Data | Wydarzenie |
|------|------------|
| 2025-11-14 | Poczatek projektu |
| 2026-01 | Homeostasis - pierwszy modul |
| 2026-02-22 | Deploy na Mini PC |
| 2026-03-01 | K1-K5 (core kontrakty) |
| 2026-03-20 | K6-K10 (cognitive core COMPLETE) |
| 2026-03-22 | OpenClaw LIVE, Model Registry v2 |
| 2026-03-25 | K13 Creative Phase 2 (NIM-powered) |
| 2026-03-27 | Semantic Memory (nomic-embed-text) |
| 2026-03-29 | Stabilization Roadmap COMPLETE (6 faz) |
| 2026-03-29 | Faza F + Belief Store v2 + CapabilityRouter |
| 2026-03-30 | Faza G Agent Krytyk |
| 2026-04-01 | Learning Upgrade COMPLETE (5 faz) |

---

*Wygenerowano: 2026-04-01 przez Claude Code*
*Projekt: github.com (prywatne repo)*
*License: AGPL-3.0*
