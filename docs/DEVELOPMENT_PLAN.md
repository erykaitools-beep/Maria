# M.A.R.I.A. - Plan Rozwoju (2026-03-01)

> Ten plan powstal z burzy mozgow opartej na analizach Groka, ChatGPT i Claude (ktory zna kod od srodka).
> Trzymamy sie tej kolejnosci. Kazdy nowy modul wchodzi naturalnie w system, a nie jest doklejony z boku.
> **2026-03-01:** Dodano Warstwe 0.5 (Kontrakty architektoniczne) - formalne specyfikacje przed implementacja.

## Zasada naczelna

Maria ma byc **systemem kognitywnym**, nie kolekcja modulow.
To znaczy: kazdy nowy komponent musi dzialac RAZEM z reszta, nie obok.

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

**Priorytet: NASTEPNY (implementacja wg kontraktu K1)**

### Cel
Jedno miejsce gdzie trafiaja WSZYSTKIE bodźce - tekst, metryki, wyniki nauki, *pozniej* obraz, *pozniej* IoT.

### Dlaczego przed Vision
Bez tego Vision bedzie kolejnym silosem. Z Unified Perception kamera staje sie naturalnym "zmyslem" obok innych.

### Co obejmuje
- Wspolny format bodzcow (Stimulus/Percept)
- Kolejka percepcji z priorytetami
- Filtrowanie i normalizacja
- Adapter dla istniejacych sensorow (homeostasis sensors → percepts)
- Adapter dla interakcji uzytkownika (chat → percepts)
- Adapter dla wynikow nauki (learning results → percepts)
- *Pozniej:* adapter dla Vision, adapter dla Smart Home

### Status
- [ ] Specyfikacja
- [ ] Implementacja
- [ ] Testy
- [ ] Integracja z homeostasis

---

## Warstwa 2: Planner (petla dzialania)

**Priorytet: PO Unified Perception**

### Cel
Maria sama planuje i dziala, zamiast czekac na komendy.

### Co obejmuje
- Prosty ReAct loop: cel → mysl → dzialaj → obserwuj → powtorz
- Tool-use: Maria wywoluje swoje wlasne komendy w petli
- Ograniczenia bezpieczenstwa (max krokow, timeout, human approval dla ryzykownych akcji)

### Status
- [ ] Specyfikacja
- [ ] Implementacja
- [ ] Testy
- [ ] Integracja z homeostasis

---

## Warstwa 3: Goal System (cele)

**Priorytet: PO Planner**

### Cel
Maria generuje wlasne cele na podstawie swojego stanu.

### Co obejmuje
- Generator celow (na podstawie knowledge gaps, wynikow nauki, stanu systemu)
- Priorytetyzacja celow
- Dzienny plan (po SLEEP→ACTIVE)
- Raportowanie (podsumowanie dnia)

### Status
- [ ] Specyfikacja
- [ ] Implementacja
- [ ] Testy
- [ ] Integracja z Planner

---

## Warstwa 4: Vision (Faza 1-2)

**Priorytet: PO Goal System**

### Cel
Zmysl wzroku jako naturalny kanal w Unified Perception.

### Co obejmuje
- Faza 1: Sensor Abstraction Layer (kamera USB, mock sensor)
- Faza 2: Preprocessing (jakosc obrazu, normalizacja, degradacja)
- Wejscie do Unified Perception (obraz → percept)

### Szczegoly
Patrz: `docs/VISION_SPEC.md` (fazy 1-2)

### Status
- [ ] Hardware (kamera)
- [ ] Faza 1 implementacja
- [ ] Faza 2 implementacja
- [ ] Integracja z Unified Perception

---

## Warstwa 5: Vision (Faza 3-4)

**Priorytet: PO Faza 1-2**

### Co obejmuje
- Faza 3: Vision Modules (Motion, Scene, OCR, Face)
- Faza 4: Vision Cortex (integracja, attention mechanism)
- Adapter do Consciousness

### Status
- [ ] Faza 3 implementacja
- [ ] Faza 4 implementacja
- [ ] Integracja z Consciousness

---

## Warstwa 6: Smart Home (kolejny zmysl)

**Priorytet: PO Vision**

### Cel
IoT jako kolejny kanal percepcji w Unified Perception.

### Co obejmuje
- DeviceRegistry + ShellyDevice
- Smart Home → percepts (temperatura, ruch, swiatlo)
- Planner moze sterowac urzadzeniami jako "tool"

### Szczegoly
Patrz: `docs/SMART_HOME_SPEC.md`

### Status
- [ ] Hardware (Shelly devices)
- [ ] Implementacja
- [ ] Integracja z Unified Perception

---

## Diagram przepływu (docelowy)

```
Bodźce (Stimuli)
  |
  v
[Unified Perception] <-- chat, nauka, sensory, kamera, IoT
  |
  v
[Planner / ReAct Loop] <-- cele z Goal System
  |
  v
[Actions] --> /learn, /teacher, Smart Home, odpowiedz userowi
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
