# Sesja 2026-04-08: Self-Healing Planner

## Problem
Maria utknęła na 4 dni (473 iteracji) w pętli:
- goal-meta-learn → ask_expert("logika formalna") → file already exists → FAILED → repeat
- Żaden subsystem tego nie wykrył (K12, K13, Telegram - wszystkie ślepe na zapętlenie)

## Root cause
1. CapabilityRouter handler (handlers.py) zwracał success=False dla skip reasons
2. ActionExecutor miał poprawną logikę skip, ale był dead code (router ma priorytet)
3. Planner nie miał stuck detection - powtarzał to samo w nieskończoność

## Co zrobione

### Level 1-3 (f13c166): Stuck detection + skip logic
- Fix: handlers.py skip logic (expert_material_already_exists → success=True)
- Stuck detection: 3 identical failures → 30min cooldown on goal
- Telegram alert: notify_stuck_planner()

### Learn fix (f145b2c): Review/exam = success
- _exec_learn: success = learned > 0 OR exams > 0 OR strategies > 0
- Był już naprawiony w working tree (z Telegram taska Eryka) ale nie scommitowany

### Level 4-6 (3b3916d): Self-healing
- agent_core/planner/stuck_handler.py (nowy plik)
- Level 4 Diagnoza: 8 znanych przyczyn (StuckCause enum)
- Level 5 Naprawa: switch_to_learn, reset_failures, trigger_fetch
- Level 6 Eskalacja: bogata wiadomość Telegram z diagnozą + sugestiami
- 22 nowych testów

### Data commit (8a30568): 167 plików
- claude_notes, input/expert_*, input/web_*, docs cleanup

## Stan po sesji
- 3454 testów passing
- 4 commity
- Maria zrestartowana z nowymi fixami
- Runtime meta_data/ pozostaje uncommitted (runtime state)

## Kluczowe pliki
- agent_core/planner/stuck_handler.py - NOWY: diagnoza + naprawa + eskalacja
- agent_core/planner/planner_core.py - stuck detection w _finalize_plan + _handle_stuck
- agent_core/planner/planner_model.py - stuck_history + stuck_cooldowns w PlannerState
- agent_core/routing/handlers.py - skip logic fix
- agent_core/telegram/notifier.py - notify_stuck() + notify_stuck_planner()

## Na następną sesję
- Obserwować czy Maria naprawdę się leczy (sprawdzić logi po kilku godzinach)
- Git remote (GitHub private) - nadal czeka
- Web UI polish
- Smart Home (czeka na sprzęt)
