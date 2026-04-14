# Codex Task List - Maria Cleanup

> Taski do wykonania przez Codex. Kazdy task ma precyzyjny opis + pliki + testy.
> Przeczytaj WORK_INSTRUCTIONS.md i PERSISTENCE_CONTRACT.md zanim zaczniesz.

## Zasady
- Jeden commit per task
- Po kazdym tasku: `python -m pytest agent_core/tests/ --timeout=60 -x -q`
- Nie dodawaj nowych dependencies
- Nie ruszaj maria_core/ (legacy)
- Branch: refactor/homeostasis

---

## TASK 1: Dodaj compaction do GoalStore

**Plik:** `agent_core/goals/store.py`
**Problem:** goals.jsonl rosnie z kazdym updatem (MERGE semantics), nigdy nie jest compactowany.
**Co zrobic:**
1. Dodaj metode `compact()` ktora przepisuje goals.jsonl z unikalnymi rekordami (ostatni per id).
2. Wolaj `compact()` na koncu `save()` jesli plik ma > 2x wiecej linii niz unikalnych goals.
3. Wzorzec compaction: tmp file + atomic rename (patrz PERSISTENCE_CONTRACT.md sekcja B2).
**Testy:** Dodaj test w `agent_core/tests/test_goals.py`:
- `test_compact_removes_duplicates` - append 10 updates per goal, compact, verify file has 1 line per goal
- `test_compact_preserves_latest` - verify latest version survives

---

## TASK 2: Dodaj compaction do BeliefStore

**Plik:** `agent_core/world_model/belief_store.py`
**Problem:** beliefs.jsonl (238 linii, 1 unikalny belief po MERGE) - nigdy compactowany.
**Co zrobic:** Analogicznie jak Task 1 - dodaj `compact()`, wolaj po `save()` gdy linie > 2x beliefs.
**Testy:** `agent_core/tests/test_belief_store.py`:
- `test_compact_beliefs` - analogicznie jak goals

---

## TASK 3: Dodaj limity na unbounded APPEND files

**Pliki do zmiany:**
- `agent_core/web_source/fetch_registry.py` - dodaj MAX_ENTRIES = 500, prune po load
- `agent_core/self_analysis/recommendation_applier.py` - topic_hints.jsonl: dodaj MAX_HINTS = 200, prune stare

**Co zrobic:** Na poczatku `_load()` (lub analogicznej metody), jesli rekordow > MAX, obroc plik (zachowaj ostatnie MAX).
**Testy:** Po 1 tescie per plik.

---

## TASK 4: Ujednolic error handling w JSONL load

**Problem:** Kazdy store inaczej reaguje na uszkodzona linie JSONL. Niektore crashuja.
**Pliki do sprawdzenia:**
- `agent_core/goals/store.py`
- `agent_core/world_model/belief_store.py`
- `agent_core/bulletin/bulletin_store.py`
- `agent_core/reminders/reminder_store.py`

**Co zrobic:** W kazdym pliku, w petli `for line in file`, owin `json.loads()` w try/except:
```python
try:
    record = json.loads(line.strip())
except (json.JSONDecodeError, KeyError):
    logger.warning(f"Skipping corrupted JSONL line in {path}")
    continue
```
**Testy:** Dodaj test per store: wpisz smieci do JSONL, verify load nie crashuje.

---

## TASK 5: Dodaj threading.excepthook

**Problem:** Maria crashuje ~8x/dzien - unhandled exceptions w threadach (exit code 1).
**Plik:** `maria.py` (entry point)
**Co zrobic:** Na poczatku main(), dodaj:
```python
import threading
import sys

def _thread_excepthook(args):
    logger.critical(f"Unhandled exception in thread {args.thread.name}: {args.exc_value}", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

threading.excepthook = _thread_excepthook

def _sys_excepthook(exc_type, exc_value, exc_tb):
    logger.critical(f"Unhandled exception: {exc_value}", exc_info=(exc_type, exc_value, exc_tb))

sys.excepthook = _sys_excepthook
```
**Testy:** Nie trzeba (to jest crash handler, testowanie jest trudne).

---

## TASK 6: Cleanup starych JSONL - jednorazowy skrypt

**Plik:** `scripts/compact_jsonl.py` (nowy)
**Co zrobic:** Skrypt ktory:
1. Compactuje goals.jsonl (MERGE by id)
2. Compactuje beliefs.jsonl (MERGE by belief_id)
3. Compactuje web_fetch_registry.jsonl (MERGE by url)
4. Obcina critique_reports.jsonl do ostatnich 200 rekordow
5. Obcina decision_traces.jsonl do ostatnich 500 rekordow
6. Raportuje: ile linii bylo, ile zostalo, ile zaoszczedzono

**Uruchomienie:** `python scripts/compact_jsonl.py` (jednorazowe, przed restartem)
**Testy:** Nie trzeba (one-shot utility).

---

## TASK 7: GoalStore "cancelled" status

**Problem:** GoalStore loguje warning dla statusu "cancelled" bo nie jest w GoalStatus enum.
**Plik:** `agent_core/goals/goal_model.py`
**Co zrobic:** Dodaj `CANCELLED = "cancelled"` do `GoalStatus` enum.
**Testy:** Dodaj test w test_goals.py: `test_cancelled_status_in_enum`

---

*Lista bedzie rozszerzana. Zacznij od Task 1 i idz po kolei.*
