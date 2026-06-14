# Maria Worklog

> Jeden plik prawdy. Kazda sesja ma wpis. Indeks na gorze.

## Indeks

| # | Data | Kto | Tagi | Opis |
|---|------|-----|------|------|
| 001 | 2026-04-15a | Claude+Eryk | fix, sleep, planner, cleanup | Zombie cleanup, auto-wake, sleep dreams fix, Codex start |
| 002 | 2026-04-15b | Claude+Eryk+Codex | codex, planner-v2, audit, cleanup | Codex Tasks 1-8, Planner v2 design+Phase A, system audit |

---

## 001 / 2026-04-15 / Claude+Eryk

**Commit:** `76c7817`

### Zrobione
- Zombie cleanup: ubite stare procesy ccd-cli + pytest, odzyskane 5.3GB RAM
- Fix: planner przekazuje mode+health do K7 w `_is_action_rate_limited()` (koniec creative spam w SLEEP)
- Fix: ModeRegulator auto-wake z SLEEP gdy learning window startuje (Maria spala 23h, przegapila caly dzien nauki)
- Fix: SleepProcessor uzywal nieistniejacego API BeliefStore (`get_all`->`get_current`, `maintain`->`compact`, `_mark_dirty`->`revise`) - sny teraz dzialaja
- Codex wystartowany na repo (7 taskow z CODEX_TASKS.md)

### Znalezione problemy
- Planner v2 potrzebny: retry co minute na zablokowanych akcjach, brak time-awareness, brak backoff
- Codex nie widzial docs/ bo pliki byly lokalne (nie pushnięte wczesniej)

### Analiza logow
- 14.04 00:00-18:00: critique spam 558x (stary kod przed restartem)
- 14.04 18:35-19:05: restart, normalna praca, zasnela o 19:05
- 14.04 19:05 - 15.04 18:15: SLEEP 23h (brak auto-wake, naprawione)
- SleepProcessor odpalil sie ale 0 snow (API mismatch, naprawione)

### Nastepna sesja
- Review PR od Codexa
- Sprawdzic czy auto-wake zadzialal o 9:00 Berlin
- Planner v2 design (osobna sesja)

---

## 002 / 2026-04-15b / Claude+Eryk+Codex

**Commity:** `af632c7` -> `4e8228f` (6 commitow)

### Codex Tasks (1-8 DONE)
- Task 1-2: GoalStore + BeliefStore compaction (auto po save, tmp+atomic)
- Task 3: FetchRegistry MAX_ENTRIES=500, topic_hints MAX_HINTS=200
- Task 4: Unified JSONL error handling (4 stores, per-line try/except)
- Task 5: threading.excepthook + sys.excepthook w maria.py
- Task 6: scripts/compact_jsonl.py (one-shot utility)
- Task 7: GoalStatus.CANCELLED enum
- Task 8: Store API audit - batched save() w action_executor + planner stale cleanup

### Planner v2 (ALL 3 PHASES DONE)
- Design doc: docs/PLANNER_V2_DESIGN.md (dual-loop: strategic LLM + tactical rules)
- **Phase A DONE:** TimeContext (Berlin time awareness) + action failure backoff
- **Phase B DONE:** StrategicPlanner + StrategicPlan model (qwen3:8b, 33 testow)
- **Phase C DONE:** Wiring do homeostasis + planner_core (Step 1.7, feedback loop)

### Codex Task 9 DONE
- docs/STORE_API_REFERENCE.md - publiczne API 9 store'ow

### Inne
- Zombie auto-cleanup w maria.py (stale ccd-cli + pytest na starcie)
- CLAUDE.md slim proposal (1191 -> 140 linii, do porownania z wersja Eryka)
- System audit: 47 modulow, ~4300 testow, 34 JSONL (30MB), 0 TODO/FIXME

### Nastepna sesja
- Sprawdzic auto-wake o 9:00 Berlin
- Sprawdzic czy strategic planner odpala (qwen3:8b co 30min)
- Porownac CLAUDE.md slim (Claude vs Eryk wersja)
- Aktualizacja ROADMAP + STATUS
- Brakujace testy (Codex)
