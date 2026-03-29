# M.A.R.I.A. - Development Roadmap
> Version: 1.0 | Last updated: 2026-03-29
>
> **Szczegolowy plan rozwoju:** `docs/DEVELOPMENT_PLAN.md` (zatwierdzony 2026-02-28)

## Overview

Rozwoj M.A.R.I.A. podzielony jest na fazy:

| Faza | Nazwa | Cel | Status |
|------|-------|-----|--------|
| A | Stabilizacja | Naprawic bledy, stabilny runtime | **COMPLETE** (2026-01-27) |
| B | Full Homeostasis | Pelna autonomia z petlami regulacji | **COMPLETE** (2026-01-28) |
| C | Consciousness | Samowiedza, percepcja, tozsamosc | **COMPLETE** (2026-02-27) |
| C.5 | Kontrakty K1-K4 | Perception, Sandbox, Goals, Evaluation | **COMPLETE** (2026-03-01) |
| C.6 | Cognitive Core K5-K13 | Planner, World Model, Autonomy, Creative | **COMPLETE** (2026-03-25) |
| C.7 | Infrastructure | Telegram, Semantic Memory, OpenClaw, Web UI v2 | **COMPLETE** (2026-03-27) |
| C.8 | Stabilization Roadmap | Tracing, Memory, Budgets, Safety (6 faz) | **COMPLETE** (2026-03-29) |
| F | Multi-Source Learning | Cross-LLM validation, dispute tracking | **COMPLETE** (2026-03-29) |
| D | Vision | Percepcja wizualna (oko) | PLANNED (czeka na sprzet) |
| E | Smart Home | Integracja IoT, mobilne cialo | PLANNED (czeka na sprzet) |
| G | Multi-Agent Expansion | Krytyk, Code Agent | PLANNED |

---

## Faza A: STABILIZACJA

### Cel
Naprawic wszystkie bledy krytyczne i uzyskac system ktory:
- Uruchamia sie bez bledow
- Dziala stabilnie przez podstawowa sesje uczenia
- Ma spojne sciezki plikow
- Poprawnie obsluguje polskie znaki

### Zakres

#### A1: Runtime Killers (P0)
- [x] `main.py`: przeniesc `if __name__` na koniec pliku
- [x] `perception.py`: poprawic wciecia klasy Perception
- [x] `learning_agent.py`: usunac wklejony debug code

#### A2: Spojnosc sciezek (P1)
- [x] Ujednolicic sciezki indeksow (tylko config.py jako source of truth)
- [x] Usunac hardcoded paths z perception.py
- [x] Sprawdzic memory_store.py MEMORY_INDEX_PATH

#### A3: Jakosc i bezpieczenstwo (P2)
- [x] Naprawic StripEmojiFilter (nie usuwac polskich znakow)
- [x] Dodac timeout do file locking (opcjonalnie)

**STATUS: COMPLETE** (2026-01-27)

---

## Faza B: FULL HOMEOSTASIS

### Cel
System dziala autonomicznie przez dlugie okresy (8h+) z automatyczna regulacja.

### Zakres

#### B1: Memory Management
- [x] Cap na episodic_memory (max N epizodow, FIFO) - via MemoryManager
- [x] Archiwizacja starych epizodow - consolidate_episodic()
- [x] Pruning semantic_graph (automatyczny) - semantic_consistency_check()

#### B2: Consolidation Scheduler
- [x] Harmonogram konsolidacji (co N operacji / co M minut) - epoch tasks
- [x] Automatyczny merge podobnych wezlow - via actions.py
- [x] Kompresja/rotacja logow JSONL - via snapshot.py

#### B3: Mode Regulator Enhancement
- [x] State machine (ACTIVE -> REDUCED -> SLEEP -> SURVIVAL) - ModeRegulator
- [x] Auto-recovery z RECOVERY do LEARNING
- [x] Timeout w trybie RECOVERY - via constraints

#### B4: Energy Budget
- [x] Monitoring zuzycia tokenow per sesja - CognitiveSensor
- [x] Throttling przy wysokim zuzyciu - reduce_batch_size()
- [x] Raportowanie statystyk - /homeostasis command

#### B5: Reporting & Alerting
- [x] Regularne raporty stanu (co N minut) - health_score, telemetry
- [x] Alerty przy anomaliach - AlarmDispatcher
- [x] Dashboard/summary endpoint - /homeostasis command

**STATUS: COMPLETE** (2026-01-28)

---

## Faza C: CONSCIOUSNESS / OPTYMALIZACJA

### Cel
Rozszerzenie o swiadomosc, osobowosc, percepcje czasu, autonomiczna nauke.

### Zakres

- [x] Introspection module (samowiedza kodu, READ-ONLY AST)
- [x] TimeAwareness (percepcja czasu - dzien, godzina, pora)
- [x] Self-model w semantic_graph (osobowosc) - TraitEvolver + SelfModelBuilder
- [x] Pamiec rozmow z kondensacja - ConversationMemory
- [x] Ciaglosc tozsamosci (birth date, uptime) - IdentityStore
- [x] SLEEP z "snami" - SleepProcessor + DreamGenerator
- [x] Agent Nauczyciel z autonomicznym triggerem w homeostasis
- [x] NIM API + Token Budget + LLM Router (ADR-008)

**STATUS: COMPLETE** (2026-02-27, 668 tests)

---

## Faza C.5: KONTRAKTY K1-K4 (Warstwa 1)

### Cel
Formalne specyfikacje warstw laczacych moduly w spójny system kognitywny.

- [x] **K1 Unified Perception** - PerceptionEvent, Buffer, 6 adapterow, Tick Aggregator (ADR-009)
- [x] **K2 Sandbox/Production** - SandboxManager, transaction log, startup recovery (ADR-010)
- [x] **K3 Goal System** - 4 typy celow, 6 statusow, PROPOSED flow, audit trail (ADR-011)
- [x] **K4 Evaluation** - READ-ONLY observer, 5 metryk, threshold recommendations (ADR-012)

**STATUS: COMPLETE** (2026-03-01, 941 tests)

---

## Faza C.6: COGNITIVE CORE K5-K13 (Warstwa 2-3)

### Cel
Pelny rdzen kognitywny: planowanie, rozumowanie, autonomia, kreatywnosc.

### Warstwa 2: Petla sterowania (K5-K10, 2026-03-01 - 2026-03-20)
- [x] **K5 Planner** - ReAct loop, PlannerGuard, GoalSelector, ActionExecutor (ADR-013)
- [x] **K5.1 Topic-Aware Learning** - KnowledgeAnalyzer topic map, auto-goal creation
- [x] **K6 World Model** - Belief system, BeliefStore (JSONL, cap 2000), BeliefBuilder
- [x] **K7 Autonomy Policy** - FREE/GUARDED/RESTRICTED/FORBIDDEN, rate limiter, PolicyEngine
- [x] **K8 Deliberation** - Multi-step strategies, 3 templates, IntentTracker
- [x] **K9 Meta-Cognition** - ReflectionStore, ConfidenceTracker, pattern detection, needs_human()
- [x] **K10 Action Safety** - SafetyMode(3), AuditLog, EffectValidator, safe-by-default

### Warstwa 3: Rozszerzenia (K11-K13, 2026-03-21 - 2026-03-25)
- [x] **K11 Experiment System** - ProposalEngine, ParameterRegistry, runner, ADOPT/REJECT
- [x] **K12 Self-Analysis Phase 2** - StateCollector, ExternalAnalyzer (NIM cascade), Web UI /analysis
- [x] **K13 Creative Module Phase 2** - TensionDetector, MetaGoalEngine, ReframeEngine (NIM), TokenBudget RPM

**STATUS: COMPLETE** (2026-03-25, 1876 tests - cognitive core)

---

## Faza C.7: INFRASTRUKTURA

### Cel
Narzedzia operatorskie, pamiec semantyczna, efektory zewnetrzne.

- [x] **Model Registry v2** - 7 modeli, heavy mutex, rule-based triage (ADR-015)
- [x] **ModelScheduler** - load/unload via Ollama, RAM guard, idle timeout
- [x] **OpenClaw Effector** - subprocess client, gateway+node, qwen2.5:3b (ADR-016)
- [x] **Web UI v2** - Metaoperator Panel, 8 paneli, design system (ADR-017)
- [x] **Web Content Fetcher** - Wikipedia PL + RSS, TopicSuggester, FetchRegistry
- [x] **Telegram Bridge (ClawBot)** - 12+ komend, 7 typow alertow, poll co 30s
- [x] **Semantic Memory** - nomic-embed-text (768-dim), VectorStore, auto-indexer (ADR-021)
- [x] **Meta-goal Priority Escalation** - tension streaks, PROPOSED displacement
- [x] **Architecture Map** - force-directed graph, pipeline view, data flow (Web UI)
- [x] **Storage Manager** - LogArchiver, DailySummary, 6TB disk

**STATUS: COMPLETE** (2026-03-27, 2081 tests)

---

## Faza C.8: STABILIZATION ROADMAP (6 faz)

### Cel
Systemowa stabilizacja przed autonomicznym dzialaniem. Zrodlo: `docs/plans/MARIA_full_scale_stabilization_roadmap.pdf`

- [x] **Phase 1: Decision Traceability** - episode_id, DecisionTrace, TraceStore, /trace (ADR-022)
- [x] **Phase 2: Memory Consistency** - MemoryQuery API, staleness fixes, grounding (ADR-023)
- [x] **Phase 3: Scheduler Hardening** - call_with_timeout(), EpisodeBudget, degradation routing (ADR-024)
- [x] **Phase 4: Autonomy Governance** - cross-metric validation, guard metrics, promotion audit (ADR-025)
- [x] **Phase 5: Effector Safety Envelope** - 5-level authority, ApprovalQueue, ToolBudgetManager (ADR-026)
- [x] **Phase 6: Readiness Review** - 100-cycle marathon, authority drills, 15-point checklist

All gates passed: Gate A (tracing), Gate B (memory), Gate C (budgets), Gate D (governance), Gate E (readiness).

**STATUS: COMPLETE** (2026-03-29, 2392 tests)

---

## Faza F: MULTI-SOURCE LEARNING (IN PROGRESS)

> Maria uczy sie z wielu zrodel i porownuje odpowiedzi roznych LLM.
> Jak czlowiek ktory czyta dwie ksiazki na ten sam temat.

### Koncept
- Maria zadaje to samo pytanie dwom+ LLM (Ollama + NIM)
- Porownuje odpowiedzi - szuka rozbieznosci
- Rozbieznosci -> "fakty do zweryfikowania" (nie od razu blad!)
- Wielokrotne potwierdzenie -> aktualizacja wiedzy

### Moduly
- [x] **CrossValidator** - porownanie odpowiedzi z roznych LLM (NIM jako secondary)
- [x] **ConfidenceScorer** - rule-based ocena pewnosci (Jaccard similarity, 3 wymiary)
- [x] **DisputeLog** - JSONL log rozbieznosci (thread-safe, bounded 200)
- [x] **Planner wiring** - ActionType.VALIDATE, _exec_validate(), _pick_validation_candidate()
- [x] **Homeostasis wiring** - NIM auto-detect, set_llm_fn()
- [x] **38 testow** cross-validation
- [x] **Planner trigger** - _maybe_validate() w decision cycle (6h cooldown, state tracking)
- [x] **K7/K10 integration** - GUARDED (rate 5/h) + SafetyProfile (already configured)
- [x] **Belief confidence update** - validated scores persisted back to world model (revise)
- [x] **Degradation check** - VALIDATE blocked in REDUCED mode (heavy action)
- [x] **14 nowych testow** (trigger, cooldown, belief update, decision cycle)
- [x] **Web UI** - /validation page (stats, disputes, history) + 4 API endpoints
- [x] **Telegram** - /validate [disputes|unresolved] command
- [x] **4 nowe testy** (telegram /validate command)

### Zaleznosci
- Wymaga: LLM Router (DONE), NIM API (DONE), Planner (DONE), K7/K10 (DONE)

---

## Faza D: VISION (OKO) - ODROCZONA

> ADR-014: Najpierw mozg, potem zmysly. Czeka na kamere Tapo C200 z RTSP.

### Zakres
Szczegoly: `docs/VISION_SPEC.md`

- [ ] D1: Sensor Abstraction Layer (VisionSensor, USB webcam, mock)
- [ ] D2: Preprocessing Layer (quality, degradation, normalizacja)
- [ ] D3: Vision Modules (motion, scene, OCR, face)
- [ ] D4: Vision Cortex (integracja, attention, VisionModeManager)

### Hardware
- [ ] Kamera Tapo C200 z RTSP

---

## Faza E: SMART HOME - ODROCZONA

> Czeka na sprzet IoT (Shelly/Tasmota).

### Zakres
Szczegoly: `docs/SMART_HOME_SPEC.md`

- [ ] E1: Device Layer (SmartDevice interface, ShellyDevice, TasmotaDevice)
- [ ] E2: Automation (AutomationEngine, rules, Vision integration)
- [ ] E3: Mobile Body (IP Webcam, Termux, TTS, GPS)
- [ ] E4: Security (VLAN/Guest, audit log, potwierdzenia)

### Hardware
- [ ] Shelly Plug S x3 (~200zl)
- [ ] Android uzywany (~200zl)

---

## Faza G: MULTI-AGENT EXPANSION

> Wyspecjalizowane agenty wspomagajace Marii.

### Zrealizowane
| Agent | Rola | Model | Status |
|-------|------|-------|--------|
| **Nauczyciel** | Planuje nauke, priorytety P1-P6, spaced repetition | NIM / Ollama | **DONE** |
| **Egzaminator** | Tworzy pytania, ocenia odpowiedzi | Ollama / NIM | **DONE** |
| **Creative** | Wykrywanie napiec, meta-cele, reframe | NIM + rule-based | **DONE** (K13) |
| **Self-Analyst** | Analiza logow, rekomendacje | NIM cascade | **DONE** (K12) |

### Planowane
| Agent | Rola | Model | Status |
|-------|------|-------|--------|
| **Krytyk** | Wskazuje luki w wiedzy, sugeruje uzupelnienia | NIM | PLANNED |
| **Code Agent** | Pisze/modyfikuje kod w sandboxie | qwen2.5-coder:7b | PLANNED |

---

## Milestones

| Milestone | Opis | Status |
|-----------|------|--------|
| M1 | Faza A - stabilny runtime | **DONE** (2026-01-27) |
| M2 | Faza B - full homeostasis | **DONE** (2026-01-28) |
| M3 | Faza C - consciousness + teacher | **DONE** (2026-02-27) |
| M3.5 | Linux migration + deploy na Mini PC | **DONE** (2026-02-22) |
| M3.6 | NIM API + Token Budget + LLM Router | **DONE** (2026-02-23) |
| M4 | Kontrakty K1-K4 | **DONE** (2026-03-01) |
| M5 | Cognitive Core K5-K13 complete | **DONE** (2026-03-25) |
| M6 | Infrastructure (Telegram, Semantic Memory, OpenClaw) | **DONE** (2026-03-27) |
| M7 | Stabilization Roadmap (6 faz, 5 gates) | **DONE** (2026-03-29) |
| M8 | Faza F - multi-source learning | **DONE** (2026-03-29) |
| M9 | Faza D - vision | PLANNED (czeka na sprzet) |
| M10 | Faza E - smart home | PLANNED (czeka na sprzet) |

---

## Ryzyka i zaleznosci

| Ryzyko | Prawdopodobienstwo | Wplyw | Mitygacja |
|--------|-------------------|-------|-----------|
| OOM crash (infinite loop) | Niskie | Wysoki | intelligent_chunk_text fix (2026-03-18), execution budgets (Phase 3) |
| Ollama timeout | Niskie | Sredni | call_with_timeout (120-180s), degradation routing |
| NIM API expiry (Aug 2026) | Srednie | Sredni | Auto-fallback na Ollama, monitoring budzetu |
| Brak sprzetu IoT/kamera | Pewne | Niski | D/E odroczone (ADR-014), mozg gotowy |
| Guard metric degradation | Niskie | Sredni | Cross-metric validation (Phase 4, ADR-025) |
| Effector cascade failure | Niskie | Wysoki | Anti-cascade breaker, approval queue (Phase 5, ADR-026) |

---

## Decyzje architektoniczne (ADR)

| ADR | Tytul | Faza |
|-----|-------|------|
| ADR-001 | JSONL jako source of truth | A |
| ADR-005 | Brak emoji w kodzie | A |
| ADR-008 | NIM do nauki, Ollama do chatu | C |
| ADR-009 | Tick Aggregator zamiast Event Bus | C.5 |
| ADR-010 | Sandbox-first learning | C.5 |
| ADR-011 | Goals as data | C.5 |
| ADR-012 | Evaluation READ-ONLY | C.5 |
| ADR-013 | Planner v1 rule-based (zero LLM) | C.6 |
| ADR-014 | Najpierw mozg, potem zmysly | C.6 |
| ADR-015 | Multi-organ model stack | C.7 |
| ADR-016 | OpenClaw jako efektor | C.7 |
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

---

*Ten dokument jest zywym dokumentem - aktualizuj go przy zmianach planow.*
