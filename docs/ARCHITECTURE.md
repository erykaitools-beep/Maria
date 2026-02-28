# M.A.R.I.A. - Architecture Document
> Version: 0.3 | Last updated: 2026-02-28

## 1. Overview

**M.A.R.I.A.** (Meta Analysis Recalibration Intelligence Architecture) to lokalny, autonomiczny agent AI zaprojektowany do samodzielnego uczenia sie z plikow tekstowych.

- **Backend LLM:** Ollama (llama3.1:8b)
- **Tryb pracy:** Offline-first
- **Jezyk:** Python 3.8+
- **Platforma:** Windows/Linux/Mac (cross-platform)

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

**STATUS: COMPLETE** (2026-01-28, teraz 668 tests passing)

---

## 4. Kluczowe decyzje architektoniczne

Zobacz: [DECISIONS.md](./DECISIONS.md)

---

## 5. Znane ograniczenia (Ver.4.1)

1. **Brak embeddings** - semantic_graph wspiera embeddings, ale nie sa generowane
2. ~~**Dwa systemy pamieci**~~ -> Rozwiazane przez MemoryManager
3. ~~**Brak cap na episodic_memory**~~ -> Rozwiazane przez consolidate_episodic()
4. ~~**Brak consolidation scheduler**~~ -> Rozwiazane przez epoch tasks w core.py
5. **Legacy maria_core/** - stary kod nadal istnieje, owiniety adapterami (Stage 5 cleanup pending)
6. **Brak Unified Perception** - bodźce z roznych zrodel nie trafiaja do wspolnego miejsca
7. **Brak Plannera** - Maria reaguje na komendy, nie planuje samodzielnie
8. **Brak Goal System** - Maria nie generuje wlasnych celow

Patrz: `docs/DEVELOPMENT_PLAN.md` (plan rozwoju warstw 1-3)

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
├── introspection/         # Samowiedza kodu (READ-ONLY)
│   ├── analyzer.py        # AST static analysis
│   ├── code_model.py      # Code self-model structures
│   ├── reporters.py       # Human + Technical output
│   └── scheduler.py       # Periodic analysis
├── awareness/             # Kontekst samowiedzy
│   └── context_builder.py # ContextBuilder for /awareness
├── llm/                   # LLM management + NIM routing
│   ├── router.py          # LLMRouter: chat->Ollama, nauka->NIM
│   ├── nim_client.py      # NVIDIA NIM API client (OpenAI-compatible)
│   ├── token_budget.py    # Daily/monthly token limits
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
└── tests/                 # 668 tests
    └── test_*.py          # 21 test files
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

### 6.3 Przepływ danych - Homeostasis Loop (9 faz)

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
    ├── Phase 8: AUDIT & LOG (co 60 tickow)
    │
    └── Phase 9: TEACHER AUTO-TRIGGER
        └── ACTIVE + idle >= 10min -> auto-sesja nauki (3 iteracje)
```

### 6.4 LLM Routing

```
LLMRouter
    │
    ├── think(prompt)       -> Ollama (chat, offline, fast)
    ├── _ask_once(prompt)   -> NIM if budget OK, else Ollama
    ├── analyze_task(task)  -> NIM if budget OK, else Ollama
    │
    └── TokenBudget
        ├── Daily:   100,000 tokens
        ├── Monthly: 2,000,000 tokens
        └── States: OK -> LOW (<=20%) -> DEPLETED -> fallback Ollama
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
