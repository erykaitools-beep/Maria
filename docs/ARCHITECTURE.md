# M.A.R.I.A. - Architecture Document
> Version: 0.1 | Last updated: 2026-01-26

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
|  ollama_brain.py                                                  |
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
- [ ] Dziala stabilnie przez 8+ godzin bez crashy
- [ ] Automatycznie przechodzi w RECOVERY po problemach
- [ ] Automatycznie wraca do LEARNING po recovery
- [ ] Pamiec (RAM) pozostaje w bezpiecznych granicach
- [ ] Logi JSONL nie rosna nieograniczenie (pruning/archiwizacja)
- [ ] Graf semantyczny konsoliduje sie automatycznie
- [ ] episodic_memory ma cap i FIFO
- [ ] System raportuje swoj stan (motivation, uptime, stats)

---

## 4. Kluczowe decyzje architektoniczne

Zobacz: [DECISIONS.md](./DECISIONS.md)

---

## 5. Znane ograniczenia (Ver.4)

1. **Brak embeddings** - semantic_graph wspiera embeddings, ale nie sa generowane
2. **Dwa systemy pamieci** - JSONL i semantic_graph nie sa zsynchronizowane
3. **Brak cap na episodic_memory** - rosnie bez ograniczen
4. **Brak consolidation scheduler** - konsolidacja tylko manualna
5. **Brakujace moduly** - maria_web_learning.py, maria_api_bridge.py nie istnieja

---

*Ten dokument jest zywym dokumentem - aktualizuj go przy zmianach architektonicznych.*
