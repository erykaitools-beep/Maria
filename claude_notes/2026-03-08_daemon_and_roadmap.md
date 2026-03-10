# Sesja 2026-03-08 - Zmiana kierunku + Daemon

## Co zrobiono

### 1. Zmiana kierunku rozwoju (ADR-014)
- ChatGPT zaproponowal K6-K10 (World Model, Autonomy Policy, Deliberation, Meta-Cognition, Action Safety)
- Eryk i ja ustalilismy: to architektura DOCELOWA, nie na teraz
- Zasada: budujemy przyrostowo, gdy praktyka pokaze ze brakuje
- Vision i Smart Home odlozone do domkniecia cognitive core
- Zaktualizowano: DEVELOPMENT_PLAN.md, ARCHITECTURE.md, CLAUDE.md, MEMORY.md

### 2. Nowy run_maria.py - headless daemon
- Stary run_maria.py uzywał legacy orchestrator (maria_core)
- maria.service uruchamiał main.py (REPL) ktory bez stdin sie konczyl
- Maria stała od 27 lutego (1.5 tygodnia)!
- Nowy daemon: reusuje init_brain() + register_modules() z main.py
- threading.Event.wait() zamiast time.sleep() (natychmiastowy shutdown na SIGTERM)
- Tick loop w main thread, graceful shutdown z consciousness checkpoint
- Test 15s: OK, potem deploy na systemd: OK
- Daemon dziala od 10:50, health 98%, RAM 93%, CPU <1%

### 3. Stan runtime
- 7 plikow w input/ (1 completed, 1 learning, 5 new)
- Teacher auto-trigger po 10min idle - powinien zaczac uczyc
- Planner co 60 tickow - powinien generowac planner_decisions.jsonl
- homeostasis_events.jsonl - juz sie pisze (snapshoty co 60s)

## Do sprawdzenia w nastepnej sesji
- Czy daemon nadal dziala (journalctl -u maria)
- Czy planner_decisions.jsonl sie pojawil
- Czy teacher odpalil auto-sesje nauki
- Czy sa jakies errory w logach
- Analiza decyzji plannera - co robi dobrze, co zle

## Obserwacje
- Eryk myśli strategicznie o AGI - ceni architekture docelowa nawet jesli nie budujemy teraz
- ChatGPT dobrze analizuje kierunki ale ma tendencje do over-engineeringu
- Kluczowe: "nie budujemy na zapas, ale wiemy dokad idziemy"
