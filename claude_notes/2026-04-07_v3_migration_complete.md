# Sesja 2026-04-07 - V3 Migration Complete

## Status: ARCHITEKTURA DZIALA - OBSERWUJEMY

Maria dziala jako jeden proces (maria.py full mode):
- Daemon (homeostasis 1Hz tick loop)
- Web UI (Flask-SocketIO, port 5000)
- Telegram (ClawBot, polling co tick)
- Vision (USB kamera, LLaVA on-demand)
- V3 Orchestrator (15 modulow, ProductShell)

## Co zrobione dzis

### 1. Task Pipeline + PDF Export
- TaskStore podpiety do /claude, /codex, /analyze
- JSONL persistence (meta_data/claude_tasks.jsonl)
- Recovery przerwanych taskow po restarcie
- Timeout 3min -> 5min z jasnym komunikatem
- PDF automatycznie generowany i wysylany przez Telegram
- /tasks [N] - historia taskow
- /pdf <task_id> - re-export starego taska
- Startup spam cooldown: 1h -> 6h
- 35 nowych testow

### 2. V3 Migration
- maria.service juz uzywal maria.py (zmiana z wczesniejszej sesji)
- maria-ui.service zatrzymany i wylaczony (disabled)
- Jeden proces = daemon + Web UI + shared Vision cortex
- Przetestowane: Telegram, Web UI, Vision - wszystko OK

## Przetestowane na zywo
- /claude - 15s, COMPLETED, PDF wyslany
- /codex - 46s, COMPLETED, PDF wyslany
- /tasks - pokazuje historje z ID, statusem, czasem
- /status - odpowiada po restarcie
- Web UI - dziala na porcie 5000
- Vision - kamera dziala, opisy sie zgadzaja
- Restart z Telegrama - Maria wstaje w ~10s

## Architektura produkcyjna (stan na 2026-04-07)

```
maria.py (PID jeden)
  |
  +-- Daemon thread (main)
  |     +-- Homeostasis 1Hz tick loop
  |     |     Phase 1-7: sense, interpret, validate, mode, actions, health
  |     |     Phase 8: perception aggregation (K1)
  |     |     Phase 8.5: vision (USB cam + preprocessing + modules)
  |     |     Phase 9: audit log (co 60s)
  |     |     Phase 9.5: model scheduler (ollama load/unload)
  |     |     Phase 10: planner (K5 ReAct loop, co 60 tickow)
  |     |     Phase 11: telegram poll + commands
  |     |
  |     +-- Background threads (on demand):
  |           /claude, /codex -> subprocess (5min timeout)
  |           /code -> Code Agent session
  |           Creative K13 reflection
  |           K12 self-analysis
  |
  +-- Web UI thread (Flask-SocketIO)
        Port 5000, PIN auth
        Chat + grounding pipeline (co widzisz? -> LLaVA)
        Status, experiments, architecture, vision, critique
        Shared Vision cortex (same process)

Systemd:
  maria.service = maria.py (enabled, Restart=on-failure)
  maria-ui.service = DISABLED (legacy)

External:
  Ollama localhost:11434 (llama3.1:8b, qwen3:8b, llava, nomic-embed-text)
  NIM API (z-ai/glm5, 40 RPM)
  Telegram Bot API (ClawBot)
  OpenClaw (qwen2.5:3b, deployadmin)
```

## Co obserwowac
- Tick overrun (>1s) - normalne na starcie, potem powinno byc <100ms
- Critic warnings (max() empty sequence) - brak danych, nie blad
- Memory usage - 95MB po starcie, powinno byc stabilne
- Claude/Codex timeout - teraz 5min, jesli nadal timeout to problem po stronie CLI

## Nastepne kroki (gdy bedzie potrzeba)
- Git remote (GitHub private) - sync na laptop
- Web UI + Telegram integracja (task pipeline w Web UI)
- Aktualizacja dokumentacji PDF
- Smart Home (czeka na sprzet)
