# 2026-03-08 - Stabilizacja K1-K5.1: 4 bugi naprawione

## Kontekst
Maria stala od 27 lutego. Nowy `run_maria.py` (headless daemon) zostal napisany
i wdrozony. Po uruchomieniu okazalo sie ze planner wykonal 1/60 planow - reszta to NOOP.

## Znalezione i naprawione bugi

### Bug 1: Retention Gate Deadlock (`planner_guard.py`)
- `retention_rate=0.0` (brak egzaminow) < `MIN_RETENTION_RATE=0.5` -> blokada
- Blad logiczny: 0.0 znaczy "brak danych" a nie "zla retencja"
- Fix: `retention_rate > 0.0 and retention_rate < MIN_RETENTION_RATE`

### Bug 2: Tick Discontinuity (`planner_core.py`)
- Po restart daemon tick=0, ale planner_state.json ma last_cycle_tick=4140
- `ticks_since = 0 - 4140 = -4080` < 60 -> should_run=False (czeka 70 min!)
- Fix: `if ticks_since < 0 or ticks_since >= ROUTINE_INTERVAL_TICKS`

### Bug 3: Maintenance Goal Dominance (`goal_selector.py` + `action_executor.py`)
- Maintenance goals zawsze feasible -> zawsze wybierane nad META/LEARNING
- Fix w selector: `progress >= 1.0` -> not feasible (metric OK)
- Fix w executor: compute progress dla WSZYSTKICH metryk (health, cpu, ram)

### Bug 4: Tick Loop Blocking (`core.py`)
- Planner uruchamial `run_cycle()` synchronicznie w main thread
- Sesje nauki (Ollama 317s, NIM 623s) zamrazaly cala petle homeostazy
- Ironicznie: stary teacher auto-trigger juz to robil w background thread!
- Fix: `_start_planner_cycle()` z `threading.Thread(daemon=True)`
- 5 nowych testow w test_teacher.py::TestPlannerTrigger

## Wyniki po fixach
- Maria nauczyla sie 6 chunkow autonomicznie
- 1 egzamin zdany (100%)
- Pipeline: evaluate -> maintenance (satisfied) -> learn -> exam -> learn -> learn
- Testy: 1067 -> 1074 (7 nowych testow)

## Pliki zmienione
- `agent_core/planner/planner_guard.py` - retention gate
- `agent_core/planner/planner_core.py` - tick discontinuity
- `agent_core/planner/goal_selector.py` - maintenance feasibility
- `agent_core/planner/action_executor.py` - all-metrics maintenance
- `agent_core/homeostasis/core.py` - background thread for planner
- `agent_core/tests/test_planner.py` - 2 nowe testy
- `agent_core/tests/test_teacher.py` - 5 nowych testow (TestPlannerTrigger)

## Co dalej
- Sprawdzic daemon za godzine - czy tick loop dziala plynnie
- Obserwowac planner_decisions.jsonl - czy nauka kontynuuje
- NIM timeout (120s * 3 retries) nadal moze byc problemem, ale nie blokuje tick loop
- Rozwazyc redukcje NIM timeout do 30s lub przejscie na Ollama-only dla egzaminow
