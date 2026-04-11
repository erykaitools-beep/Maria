# Sesja 2026-04-10 (wieczor) - Master Prompt + Reminders

## Co zrobione

### Master Prompt (`agent_core/llm/master_prompt.py`)
- Single source of truth - zastepuje 3 roznr hardcoded prompty
- `build_base_prompt()` - pelna tozsamosc z docs/MARIA_PROMPT.md
- `build_full_prompt(...)` - OllamaBrain (+ czas, identity, user, work, awareness, grounding)
- `build_compact_prompt(...)` - NIM / Web UI (base + czas + user)
- `build_context_brief()` - Codex/Claude (angielski brief)
- Podpiete: OllamaBrain, NIMClient, Web UI (app.py), ClaudeClient, CodexClient
- Wszystko z fallbackiem na stary prompt gdyby import zawiodl

### Reminders & Todos (`agent_core/reminders/`)
- reminder_model.py: Reminder (ONCE/DAILY/WEEKLY/MONTHLY) + Todo (priority, deadline)
- reminder_store.py: JSONL persistence (meta_data/reminders.jsonl, meta_data/todos.jsonl)
- scheduler.py: tick-based (co 30 tickow), Telegram notify, overdue alerts
- time_parser.py: PL+EN - "za 30min", "o 14:30", "jutro 9:00", "in 2h", "pojutrze 12:00"
- REPL: /remind + /todo (reminder_module.py)
- Telegram: /remind + /todo (w homeostasis_module.py)
- Phase 12 w homeostasis tick loop
- SharedContext: reminder_store, todo_store, reminder_scheduler
- 83 testy (24 master_prompt + 59 reminders)

## Architektura

```
master_prompt.py
  build_base_prompt() --> OllamaBrain, NIMClient
  build_full_prompt() --> OllamaBrain._build_system_prompt()
  build_compact_prompt() --> NIM Web UI chat
  build_context_brief() --> ClaudeClient._invoke(), CodexClient._invoke()

reminders/
  reminder_model.py --> Reminder, Todo (dataclasses)
  reminder_store.py --> ReminderStore, TodoStore (JSONL)
  scheduler.py --> ReminderScheduler (tick + Telegram)
  time_parser.py --> parse_time(), format_scheduled_time()

Wiring:
  homeostasis_module.py init() --> creates stores + scheduler
  homeostasis core.py tick() --> Phase 12: scheduler.tick()
  main.py --> registers ReminderModule (REPL)
  homeostasis_module.py --> registers Telegram /remind, /todo
```

## Uwagi
- Web UI OllamaBrain teraz NIE dostaje hardcoded prompta - bierze z master_prompt
- NIM tez uzywa master_prompt (wczesniej mial biedny 3-linijkowy prompt)
- Claude/Codex dostaja context brief jako prefix (nie maja system_prompt)
- Recurring reminders: po triggerze automatycznie tworzy nastepne (DAILY/WEEKLY/MONTHLY)
- Overdue todos: notification co godzine (cooldown)

## Co dalej (z MEMORY.md)
- Proaktywnosc: Maria inicjuje kontakt (poranny brief, alerty)
- Smart Home (czeka na sprzet)
- GitHub release
