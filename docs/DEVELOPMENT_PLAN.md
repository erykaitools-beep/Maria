# M.A.R.I.A. - Plan Rozwoju (2026-03-08)

> Ten plan powstal z burzy mozgow opartej na analizach Groka, ChatGPT i Claude (ktory zna kod od srodka).
> Trzymamy sie tej kolejnosci. Kazdy nowy modul wchodzi naturalnie w system, a nie jest doklejony z boku.
> **2026-03-01:** Dodano Warstwe 0.5 (Kontrakty architektoniczne) - formalne specyfikacje przed implementacja.
> **2026-03-08:** Zmiana kierunku: najpierw domkniecie rdzenia kognitywnego (K6-K10), potem zmysly i efektory.

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
- [x] Web Content Fetcher (agent_core/web_source/) - gotowy, NIE podlaczony do plannera
- [ ] Multi-day test automatyki
- [ ] Analiza logow planner_decisions.jsonl
- [ ] Identyfikacja pierwszego brakujacego elementu kognitywnego
- [ ] Aktywacja Web Content Fetcher (2 kroki ponizej)

### Web Content Fetcher (zbudowany 2026-03-08, czeka na aktywacje)

Modul pozwalajacy Marii autonomicznie pobierac materialy z internetu (Wikipedia PL + RSS).
Zbudowany i przetestowany (47 testow), ale **celowo NIE podlaczony** do plannera.
Maria moze dzialac na obecnych materialach, a modul czeka gotowy do aktywacji.

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

**2 kroki do aktywacji:**
1. **`agent_core/planner/planner_model.py`** - dodac `FETCH = "fetch"` do `ActionType` enum
2. **`agent_core/planner/action_executor.py`** - dodac `_exec_fetch()` ktory wywoluje `run_fetch_session()`

---

## Warstwa 5-9: Cognitive Core (DOCELOWE, K6-K10)

**Priorytet: PRZYROSTOWO - budowane gdy praktyka pokaze ze brakuje**

> Te warstwy to docelowa architektura rdzenia kognitywnego.
> Nie budujemy ich wszystkich naraz. Kazda wchodzi wtedy, gdy obecny system
> wyraznie pokazuje ze jej brak jest waskim gardlem.
> Kolejnosc moze sie zmienic w zaleznosci od praktycznych potrzeb.

### K6: World Model / Belief System

**Cel:** Maria rozumie nie tylko zdarzenia, ale trwala strukture swiata.

**Czego brakuje w obecnym systemie:**
- encje: osoba, plik, urzadzenie, miejsce, temat, modul
- relacje miedzy encjami (semantic_graph to proto-wersja)
- rozroznienie: fakt vs obserwacja vs hipoteza vs niepewne przypuszczenie
- confidence i zrodlo wiedzy per przekonanie
- aktualizacja przekonan w czasie (belief revision)

**Kiedy budowac:** Gdy Maria dostanie nowe zrodla danych (Vision, Smart Home, nowe kanaly)
i semantic_graph przestanie wystarczac do reprezentacji wiedzy o swiecie.

**Obecne proto-elementy:** semantic_graph.py, knowledge_analyzer.py (topic mapping), exam_results (confidence per temat)

---

### K7: Autonomy Policy / Governance

**Cel:** Pelna autonomia bez polityki dzialania jest niebezpieczna i niestabilna.

**Czego brakuje w obecnym systemie:**
- klasyfikacja akcji: dozwolone autonomicznie / wymagajace potwierdzenia / zabronione
- poziomy ryzyka per typ akcji
- zasady HITL (Human-In-The-Loop) - kiedy pytac czlowieka
- warunki eskalacji
- limity operacyjne i bezpieczniki (ponad to co robi PlannerGuard)

**Kiedy budowac:** Przed Smart Home (sterowanie urzadzeniami wymaga governance).
PlannerGuard (5 gating rules) to proto-wersja - rozszerzenie gdy przestrzen akcji urosnie.

**Obecne proto-elementy:** PlannerGuard (planner_guard.py), ConstraintValidator (constraints.py)

---

### K8: Deliberation / Strategic Planning

**Cel:** Przejscie od "wybierz nastepny krok" do "prowadz proces przez wiele krokow".

**Czego brakuje w obecnym systemie:**
- plany wieloetapowe (obecny Plan = single step, ADR-013)
- dekompozycja celow na podcele
- checkpointy w dlugich procesach
- sledzenie intencji (dlaczego robimy X, nie tylko co robimy)
- repriorytetyzacja przy zmianie sytuacji

**Kiedy budowac:** Gdy przestrzen akcji urosnie poza nauke (Vision, Smart Home, Code Agent)
i single-step planner przestanie wystarczac.

**Obecne proto-elementy:** PlannerCore (single-step ReAct), GoalSelector (aging + feasibility)

---

### K9: Uncertainty / Reflection / Meta-Cognition

**Cel:** System kognitywny powinien wiedziec czego nie wie.

**Czego brakuje w obecnym systemie:**
- confidence per decyzja (nie tylko per egzamin)
- assumptions jawnie zapisane przy kazdym planie
- evidence trail (dlaczego podjeto decyzje)
- self-check po decyzji (czy skutek zgadza sie z oczekiwaniem)
- wykrywanie blednych zalozen
- "potrzebuje czlowieka, bo nie jestem pewna"

**Kiedy budowac:** Gdy K4 Evaluation przestanie wystarczac do oceny jakosci decyzji,
lub gdy Maria zacznie podejmowac decyzje z realnymi konsekwencjami (Smart Home, Code Agent).

**Obecne proto-elementy:** EvaluationObserver (5 metryk), EvaluationReport (threshold-based recommendations)

---

### K10: General Action Safety Layer

**Cel:** Uogolnienie sandbox na wszystkie typy akcji, nie tylko nauke.

**Czego brakuje w obecnym systemie:**
- tryby: simulate -> stage -> commit (dla dowolnej akcji)
- walidacja skutkow przed wykonaniem
- rollback dla akcji nie-learningowych
- action audit log (ogolny, nie tylko sandbox transaction log)
- ogolny protokol bezpieczenstwa dla nowych typow akcji

**Kiedy budowac:** Razem z pierwszym efektorem (Smart Home lub Code Agent),
bo dopiero wtedy pojawia sie akcje z realnymi konsekwencjami poza sandbox.

**Obecne proto-elementy:** SandboxManager (K2), transaction log (START/COMMIT/ROLLBACK)

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
- [ ] Cognitive Core prerequisites
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
- [ ] Cognitive Core prerequisites (K7, K10)
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
*Zatwierdzone przez: Eryk + Claude*
