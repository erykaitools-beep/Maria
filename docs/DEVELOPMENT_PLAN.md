# M.A.R.I.A. - Plan Rozwoju (2026-03-29)

> Ten plan powstal z burzy mozgow opartej na analizach Groka, ChatGPT i Claude (ktory zna kod od srodka).
> Trzymamy sie tej kolejnosci. Kazdy nowy modul wchodzi naturalnie w system, a nie jest doklejony z boku.
> **2026-03-01:** Dodano Warstwe 0.5 (Kontrakty architektoniczne) - formalne specyfikacje przed implementacja.
> **2026-03-08:** Zmiana kierunku: najpierw domkniecie rdzenia kognitywnego (K6-K10), potem zmysly i efektory.
> **2026-03-29:** Cognitive Core K1-K13 COMPLETE. Stabilization 6 phases COMPLETE. Faza F COMPLETE. 2448 testow.

## Zasada naczelna

Maria ma byc **systemem kognitywnym**, nie kolekcja modulow.
To znaczy: kazdy nowy komponent musi dzialac RAZEM z reszta, nie obok.

## Decyzja strategiczna (2026-03-08, ADR-014)

**Najpierw mozg, potem zmysly i rece.**

Vision, Smart Home i inne moduly srodowiskowe zostaja odlozone do czasu domkniecia
rdzenia kognitywnego (K6-K10), poniewaz:

- nowe zmysly bez lepszego poznania = wiecej szumu
- nowe efektory bez governance = wieksze ryzyko
- nowe moduly bez srodka strategicznego = wieksza zlozonosc bez proporcjonalnej korzysci

K6-K10 to **architektura docelowa** - budowana przyrostowo, wtedy gdy praktyka pokaze
ze danej warstwy brakuje. Nie budujemy na zapas, ale wiemy dokad idziemy.

---

## Warstwa 0: Napraw to co jest (dlug techniczny)

**Priorytet: TERAZ (przed nowa funkcjonalnoscia)**

| # | Zadanie | Opis | Status |
|---|---------|------|--------|
| 0.1 | Fix SleepProcessor bug | `homeostasis/core.py` ~L396 - przekazywano `experience_tracker` zamiast `session_id`. | [x] |
| 0.2 | Fix latency_probe import | `latency_probe.py` - usuniety martwy import, zwraca -1.0 zamiast falszywego 0.0 | [x] |
| 0.3 | Trait count: 7 vs 19 | Skorygowano dokumentacje na 7 (rzeczywista liczba). Nowe traity dodawane organicznie. | [x] |
| 0.4 | LLMRouter w main.py | Router juz byl w main.py. Naprawiono: llm_fn teraz przekazywane do learn_next_chunk() i run_exam_if_ready(). Teacher uzywa NIM przez router. | [x] |
| 0.5 | Stage 5 refaktoru | Archiwizacja legacy: agent/, logs/, output/, memory/ → `_legacy_archived/`. 668 testow OK. | [x] |
| 0.6 | Dokumentacja sync | ARCHITECTURE.md v0.3, CONSCIOUSNESS_SPEC status, ROADMAP Phase C complete, milestones | [x] |

---

## Warstwa 0.5: Kontrakty architektoniczne

**Priorytet: ZROBIONE (2026-03-01)**

Formalne specyfikacje ("konstytucja") dla nowych warstw. Kazda implementacja MUSI byc zgodna z tymi kontraktami.

| # | Kontrakt | Opis | Status |
|---|----------|------|--------|
| K1 | Unified Perception | PerceptionEvent format, 7 source types, priorytety, correlation_id, TTL, 6 adapterow | [x] |
| K2 | Sandbox / Production | Kazda nauka przez sandbox, promote() jako jedyny most, reguly promote/discard | [x] |
| K3 | Goal System | 4 typy celow (META/USER/LEARNING/MAINTENANCE), audit trail, max 20 aktywnych | [x] |
| K4 | Agent Evaluation | READ-ONLY observer, 5 metryk, format raportu JSON, zero LLM | [x] |
| D5 | Tick Aggregator (ADR-009) | Rozszerzenie tick loop zamiast event bus, deque dla external events | [x] |

Szczegoly: `docs/CONTRACTS.md`

Nowe ADR: ADR-009 (Tick Aggregator), ADR-010 (Sandbox-first), ADR-011 (Goals as data), ADR-012 (Evaluation READ-ONLY)

---

## Warstwa 1: Unified Perception (zbieracz bodzcow)

**Status: DONE (2026-03-01, Kontrakt K1)**

### Cel
Jedno miejsce gdzie trafiaja WSZYSTKIE bodźce - tekst, metryki, wyniki nauki, *pozniej* obraz, *pozniej* IoT.

### Dlaczego przed Vision
Bez tego Vision bedzie kolejnym silosem. Z Unified Perception kamera staje sie naturalnym "zmyslem" obok innych.

### Co obejmuje
- Wspolny format bodzcow (PerceptionEvent, 7 source types, 22 event types)
- PerceptionBuffer (deque maxlen=200, sliding window z priorytetami)
- 6 adapterow: sensor, user, learning, exam, consciousness, teacher
- Tick Aggregator (ADR-009): Phase 8 PERCEIVE + external queue
- *Pozniej:* adapter dla Vision, adapter dla Smart Home

### Status
- [x] Specyfikacja (Kontrakt K1 w CONTRACTS.md)
- [x] Implementacja (agent_core/perception/)
- [x] Testy (131 testow)
- [x] Integracja z homeostasis (Phase 8 PERCEIVE)

---

## Warstwa 2: Planner (petla dzialania)

**Status: DONE (2026-03-01, Kontrakt K5 + K5.1)**

### Cel
Maria sama planuje i dziala, zamiast czekac na komendy.

### Co obejmuje
- Rule-based ReAct loop (ADR-013: zero LLM w petli decyzyjnej)
- PlannerCore: co 60 tickow + event-driven (exam_result, alert, user_command, sandbox_promoted)
- PlannerGuard: 5 gating rules blokujacych planowanie gdy system nie zdrowy
- GoalSelector: aging factor (priority *= 1 + hours * 0.1, max 5x) + feasibility
- ActionExecutor: delegacja do Teacher/Sandbox/EvaluationObserver
- Plan = single step (v1, nie drzewo/graf)
- **K5.1 Topic-Aware Learning:** Maria wybiera tematy nauki
  - KnowledgeAnalyzer: tag normalization, topic-file mapping z cache 60s, scoring (exact=3, prefix=2, substring=1, filename=0.5)
  - TeacherAgent: filter_file_ids param, IDLE z idle_reason gdy filtr wycina wszystkich
  - ActionExecutor: topics → resolved_file_ids + resolution_report
  - Auto-goal creation: bezpieczne autonomiczne tworzenie celow nauki (ACTIVE mode, retention >= 0.6, cooldown 1h, max 3)
  - REPL: /plan learn <temat>, /plan topics

### Status
- [x] Specyfikacja (Kontrakt K5 w CONTRACTS.md)
- [x] Implementacja (agent_core/planner/ + rozszerzenia teacher, modules)
- [x] Testy (82 planner + 29 topic-aware = 111 testow)
- [x] Integracja z homeostasis (Phase 10 replacement z backward-compatible fallback)

---

## Warstwa 3: Goal System (cele) + Evaluation

**Status: DONE (2026-03-01, Kontrakty K3 + K4)**

### Cel
Maria generuje wlasne cele na podstawie swojego stanu. Observer mierzy postep.

### Co obejmuje
- GoalStore: CRUD + append-only JSONL (meta_data/goals.jsonl)
- 4 typy celow (META/USER/LEARNING/MAINTENANCE), 6 statusow, audit trail
- Seed goals: 1 META + 3 MAINTENANCE (auto na starcie)
- PROPOSED flow: propose/confirm/reject z izolacja od planowania
- EvaluationObserver: 5 metryk, threshold-based recommendations, READ-ONLY
- Sandbox (K2): izolowane sesje nauki, promote jako jedyny most do produkcji

### Status
- [x] Specyfikacja (Kontrakty K2, K3, K4 w CONTRACTS.md)
- [x] Implementacja (agent_core/sandbox/, goals/, evaluation/)
- [x] Testy (44 sandbox + 63 goals + 35 evaluation = 142 testow)
- [x] Wiring w SharedContext i homeostasis_module.py

---

## Warstwa 4: Stabilizacja (TERAZ)

**Priorytet: TERAZ (2026-03-08)**

### Cel
K1-K5.1 dzialaja. Teraz trzeba je przetestowac w praktyce i zobaczyc co faktycznie brakuje.

### Co obejmuje
- Testy stabilnosci automatyki (planner + topic-aware learning)
- Obserwacja: co planner robi dobrze, co zle, gdzie brakuje kontekstu
- Zbieranie danych o tym ktore warstwy kognitywne (K6-K10) sa potrzebne PIERWSZE
- Drobne poprawki na podstawie obserwacji

### Status
- [x] Naprawione 4 bugi (retention gate, tick discontinuity, maintenance dominance, tick loop blocking)
- [x] Web Content Fetcher (agent_core/web_source/) - gotowy i podlaczony do plannera
- [x] Aktywacja Web Content Fetcher: `ActionType.FETCH` + `_exec_fetch()` wired
- [x] Identyfikacja brakujacych elementow kognitywnych -> K6, K7, K8 zaimplementowane
- [x] Multi-day test (Stabilization Roadmap Phase 6: 100-cycle marathon, 2026-03-29)
- [x] Analiza logow: Phase 1 Tracing (episode_id, DecisionTrace, TraceStore)

### Web Content Fetcher (zbudowany 2026-03-08, aktywowany 2026-03-19)

Modul pozwalajacy Marii autonomicznie pobierac materialy z internetu (Wikipedia PL + RSS).
Zbudowany i przetestowany (47 testow), **podlaczony** do plannera.

**Struktura:**
```
agent_core/web_source/
    __init__.py          # run_fetch_session() - jedyny punkt integracji
    wiki_client.py       # Wikipedia PL API (search + fetch)
    rss_client.py        # RSS/Atom reader (xml.etree, zero nowych dependencies)
    topic_suggester.py   # Wybor tematow z KnowledgeAnalyzer (zero LLM)
    content_writer.py    # Zapis .txt do input/ + dedup
    fetch_registry.py    # JSONL rejestr pobranych (MERGE semantics)
```

**Flow:** TopicSuggester (na bazie KnowledgeAnalyzer) → WikiClient/RSSClient → ContentWriter → FetchRegistry

**Aktywacja (DONE):**
1. **`agent_core/planner/planner_model.py`** - `FETCH = "fetch"` w `ActionType` enum
2. **`agent_core/planner/action_executor.py`** - `_exec_fetch()` wywoluje `run_fetch_session()`

---

## Warstwa 5-9: Cognitive Core (K6-K13 DONE)

**K6-K13: DONE (2026-03-11 - 2026-03-25)**

> Pelny rdzen kognitywny kompletny. Wszystkie 13 kontraktow (K1-K13) zaimplementowane.
> K6-K10 core + K11 Experiments + K12 Self-Analysis (NIM) + K13 Creative Module (NIM).
> Stabilization Roadmap (6 phases) COMPLETE (2026-03-29).
> Faza F Multi-Source Learning COMPLETE (2026-03-29).

### K6: World Model / Belief System

**Status: DONE (2026-03-11)**

**Cel:** Maria rozumie nie tylko zdarzenia, ale trwala strukture swiata.

**Co zaimplementowano:**
- `agent_core/world_model/` (5 plikow, 69 testow)
- `belief_model.py`: EntityType(6), BeliefType(3), BeliefSource(5), frozen Belief dataclass
- `belief_store.py`: JSONL persistence z MERGE semantics, indexes by entity/type/tag, cap 2000
- `belief_builder.py`: buduje beliefs z istniejacych JSONL (topics, files, concepts), update_from_exam
- `query.py`: topic_confidence_map, knowledge_gaps, entity_summary, world_summary
- `__init__.py`: WorldModel facade (load/build/process_exam/save)

**Integracja z Plannerem:**
- `_gather_context()` wzbogacony o world_summary + knowledge_gaps (top 5)
- `_finalize_plan()` rewizja beliefs po egzaminie (pass: +0.1 conf + FACT, fail: -0.15)
- `_auto_create_learning_goal()` preferuje temat z najnizszym confidence (K6-aware)
- GoalSelector: opcjonalny parametr world_summary (backward compatible)

**Obecne proto-elementy (nadal uzywane):** semantic_graph.py, knowledge_analyzer.py (topic mapping), exam_results (confidence per temat)

---

### K7: Autonomy Policy / Governance

**Status: DONE (2026-03-19)**

**Cel:** Pelna autonomia bez polityki dzialania jest niebezpieczna i niestabilna.

**Co zaimplementowano:**
- `agent_core/autonomy/` (5 plikow, 45 testow)
- `action_class.py`: ActionClassification (FREE/GUARDED/RESTRICTED/FORBIDDEN), default mapping per ActionType
- `rate_limiter.py`: Sliding-window rate limiter per action type (fetch: 5/h, maintenance: 10/h)
- `policy_rules.py`: PolicyEngine (rule chain), 3 built-in rules (consecutive_failure_breaker, degraded_mode_restrict, restricted_actions_block)
- `escalation.py`: EscalationHandler (JSONL logging, HITL placeholder)
- `__init__.py`: AutonomyPolicy facade (check + record_execution)

**Integracja z Plannerem:**
- Pipeline: PlannerGuard.can_plan() -> AutonomyPolicy.check() -> ActionExecutor.execute()
- `_finalize_plan()`: K7 check przed execute(), blokuje jesli policy nie pozwala
- `record_execution()`: sledzi consecutive failures + rate limit po kazdej akcji
- Backward compatible: autonomy_policy=None nie psuje nic

**Kluczowe zabezpieczenia:**
- Consecutive failure breaker: blokuje po 3 porazach z rzedu (zapobiega petlom jak fetch-fail 1430x)
- Rate limiter: max 5 fetch/h, max 10 maintenance/h
- Mode restrict: GUARDED actions blokowane w REDUCED/SLEEP
- Safe-by-default: nieznane akcje = RESTRICTED (wymagaja potwierdzenia)

**HITL:** Placeholder - logowanie + blokada. Pelny HITL (Web UI prompt) w przyszlosci.

**Obecne proto-elementy (nadal uzywane):** PlannerGuard (planner_guard.py), ConstraintValidator (constraints.py)

---

### K8: Deliberation / Strategic Planning

**Status: DONE (2026-03-19)**

**Cel:** Przejscie od "wybierz nastepny krok" do "prowadz proces przez wiele krokow".

**Co zaimplementowano:**
- `agent_core/deliberation/` (5 plikow, 49 testow)
- `strategy.py`: Step + Strategy dataclasses (StepStatus, StepOutcome, StrategyStatus enums)
- `strategy_templates.py`: 3 szablony (learn_topic, explore_new, consolidate) + TEMPLATE_REGISTRY
- `deliberator.py`: Rule-based selection + advancement + fallback/retry + abandon
- `intent_tracker.py`: IntentTracker (JSONL persistence, bounded 500 records)
- `__init__.py`: Deliberation facade

**Integracja z Plannerem:**
- Pipeline: PlannerCore._create_plan_for_goal() -> _consult_deliberation() -> get_next_action()
- Jesli aktywna strategia -> uzyj nastepny krok z wieloetapowego planu
- Jesli brak strategii -> fallback na _decide_learning_action() (stare zachowanie)
- Po execute: report_step_outcome() -> advance/retry/fallback/abandon strategy
- Plan.metadata przechowuje strategy_id i step_order
- Backward compatible: deliberation=None nie psuje nic

**Templates (v1):**
- `learn_topic`: LEARN -> EXAM -> (fail?) REVIEW -> EXAM
- `explore_new`: FETCH -> LEARN -> EXAM
- `consolidate`: REVIEW -> EXAM -> EVALUATE

**Limity:** max 10 active strategies, max 5 per goal, 3x abandoned = skip template, 500 intents

**Rozszerzalnosc (v2 path):** lista->DAG, enum->expressions, rule-based->LLM, advisory->primary

**Obecne proto-elementy (nadal uzywane):** PlannerCore (single-step ReAct fallback), GoalSelector (aging + feasibility)

---

### K9: Meta-Cognition / Reflection

**Status: DONE (2026-03-20)**

**Cel:** System kognitywny powinien wiedziec czego nie wie.

**Co zaimplementowano:**
- `agent_core/meta_cognition/` (5 plikow, 73 testy)
- `reflection_model.py`: ReflectionRecord, Assumption, OutcomeMatch, Lesson dataclasses
- `reflection_store.py`: JSONL persistence (meta_data/reflections.jsonl), bounded 300 records
- `confidence_tracker.py`: Per-action/topic confidence z exponential decay, "need human" signal
- `reflector.py`: Before/after reflection, assumption tracking, pattern detection (slow exec, repeated failure)
- `__init__.py`: MetaCognition facade (record_decision/reflect/get_confidence/needs_human/get_status)

**Integracja z Plannerem:**
- Pipeline: K9 record_decision() przed execute, K9 reflect() po execute
- Assumptions zapisywane z kazdym planem, weryfikowane po wykonaniu
- Confidence per action_type spada po failure, rosnie po success
- `needs_human()`: sygnalizuje gdy confidence < 0.3 lub 3+ consecutive failures
- Backward compatible: meta_cognition=None nie psuje nic

**Obecne proto-elementy (nadal uzywane):** EvaluationObserver (K4, 5 metryk agregatowych)

---

### K10: Action Safety Layer

**Status: DONE (2026-03-20)**

**Cel:** Uogolnienie sandbox na wszystkie typy akcji + unified audit log.

**Co zaimplementowano:**
- `agent_core/action_safety/` (5 plikow, 52 testy)
- `safety_model.py`: SafetyMode(3), Reversibility(3), EffectType(6), ValidationResult(3), StateSnapshot, SafetyProfile, ActionRecord
- `safety_classifier.py`: Per-action-type classification (7 known + safe-by-default for unknown = STAGED)
- `audit_log.py`: JSONL persistence (meta_data/action_audit.jsonl), bounded 200 in-memory
- `effect_validator.py`: Before/after state capture + validation (health drop, file count, goal explosion)
- `__init__.py`: ActionSafety facade (before_action/after_action/is_staged/get_audit_stats/get_status)

**Klasyfikacja akcji:**
| ActionType | SafetyMode | Reversibility | EffectType | Snapshots |
|-----------|------------|---------------|------------|-----------|
| learn/exam/review | AUTO_COMMIT | REVERSIBLE | KNOWLEDGE | No (K2 handles) |
| evaluate/noop | AUTO_COMMIT | REVERSIBLE | NONE | No |
| maintenance | AUDIT_ONLY | REVERSIBLE | GOAL_STATE | Yes |
| fetch | AUDIT_ONLY | PARTIAL | FILESYSTEM | Yes |
| unknown | STAGED | IRREVERSIBLE | EXTERNAL_API | Yes |

**Integracja z Plannerem:**
- Pipeline: K10 before_action() -> execute -> K10 after_action()
- STAGED actions blocked (placeholder for HITL)
- Effect validation: health drop >0.3 = UNEXPECTED, fetch file decrease = UNEXPECTED
- Backward compatible: action_safety=None nie psuje nic

**Obecne proto-elementy (nadal uzywane):** SandboxManager (K2, learning-specific isolation)

---

## Warstwa 10: Vision

**Priorytet: PO domknieciu potrzebnych warstw Cognitive Core**

### Cel
Zmysl wzroku jako naturalny kanal w Unified Perception.

### Wymagania wstepne
- K7 (Autonomy Policy) - governance dla nowego zrodla danych
- K6 (World Model) - miejsce na reprezentacje tego co Maria widzi

### Co obejmuje
- Faza 1: Sensor Abstraction Layer (kamera USB/WiFi, mock sensor)
- Faza 2: Preprocessing (jakosc obrazu, normalizacja, degradacja)
- Faza 3: Vision Modules (Motion, Scene, OCR, Face)
- Faza 4: Vision Cortex (integracja, attention mechanism)
- Adapter do Unified Perception + Consciousness

### Szczegoly
Patrz: `docs/VISION_SPEC.md`

### Status
- [x] Cognitive Core prerequisites (K6, K7 DONE)
- [ ] Faza 1-2 implementacja
- [ ] Faza 3-4 implementacja
- [ ] Integracja z Unified Perception + Consciousness

---

## Warstwa 11: Smart Home

**Priorytet: PO Vision**

### Cel
IoT jako kolejny kanal percepcji i pierwszy efektor w swiecie fizycznym.

### Wymagania wstepne
- K7 (Autonomy Policy) - KONIECZNE przed sterowaniem urzadzeniami
- K10 (Action Safety) - simulate/stage/commit dla akcji fizycznych
- K6 (World Model) - reprezentacja urzadzen, pomieszczen, stanow

### Co obejmuje
- DeviceRegistry + ShellyDevice
- Smart Home → percepts (temperatura, ruch, swiatlo)
- Planner moze sterowac urzadzeniami jako "tool" (przez Action Safety Layer)

### Szczegoly
Patrz: `docs/SMART_HOME_SPEC.md`

### Status
- [x] Cognitive Core prerequisites (K6, K7, K10 DONE)
- [ ] Hardware (Shelly devices)
- [ ] Implementacja
- [ ] Integracja z Unified Perception + Action Safety

---

## Diagram przeplywu (docelowy)

```
Bodźce (Stimuli)
  |
  v
[Unified Perception] <-- chat, nauka, sensory, kamera, IoT
  |
  v
[World Model (K6)] <-- aktualizacja przekonan, encje, relacje
  |
  v
[Deliberation (K8)] <-- cele z Goal System, plany wieloetapowe
  |
  v
[Planner / ReAct Loop] <-- taktyczne decyzje, single-step execution
  |
  v
[Autonomy Policy (K7)] <-- czy wolno? HITL check
  |
  v
[Action Safety (K10)] <-- simulate -> stage -> commit
  |
  v
[Actions] --> /learn, /teacher, Smart Home, Code Agent, odpowiedz userowi
  |
  v
[Meta-Cognition (K9)] <-- czy skutek zgadza sie z oczekiwaniem?
  |
  v
[Homeostasis] --> monitoruje, reguluje tryby
  |
  v
[Consciousness] --> osobowosc, pamiec, sny
```

---

## Notatki

### NIM API - modele
Klucz API moze obslugiwac inne modele niz glm5. Do sprawdzenia:
- Jakie modele sa dostepne przez `integrate.api.nvidia.com/v1/models`
- Czy warto testowac inne (np. nemotron, mistral)
- Obecna konfiguracja: `.env` -> `NVIDIA_NIM_MODEL=z-ai/glm5`

### Analiza zewnetrzna (Grok, ChatGPT)
Najlepsze dane wejsciowe dla zewnetrznych LLM:
1. PDF z podsumowaniem projektu (juz mamy)
2. Wynik testow (`pytest --tb=short`)
3. Drzewo plikow (`tree -L 3`)
4. Fragment kluczowego kodu (np. homeostasis tick loop)
5. Metryki runtime (RAM, CPU, uptime)

---

*Utworzono: 2026-02-28*
*Ostatnia aktualizacja: 2026-03-29 (K1-K13 + Stabilization + Faza F COMPLETE, 2448 testow)*
*Zatwierdzone przez: Eryk + Claude*
