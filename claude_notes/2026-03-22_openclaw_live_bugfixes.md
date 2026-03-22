# Sesja 2026-03-22 - Bug fixes + OpenClaw LIVE

## Bug fixes

### Fix 1: TeacherAgent stats kumulacja
- `_stats` nigdy nie resetowane miedzy sesjami run_session()
- Planner widzial np. chunks_learned=215 ale to suma od poczatku
- Fix: reset `_stats` dict na poczatku run_session()
- Plik: agent_core/teacher/teacher_agent.py:115-125

### Fix 2: Spaced repetition petla 12ms
- Wszystkie 109 plikow completed, brak learned
- SpacedRepetition sugerowal review -> run_exam_if_ready szukal learned -> fail -> petla co minute
- Fix 2a: run_exam_if_ready() przyjmuje target_file_id (dla spaced repetition)
- Fix 2b: _run_exam_wrapped() przekazuje file_id
- Fix 2c: Completed pliki po powtorce zostaja completed (nie degraduja do exam_failed)
- Pliki: maria_core/learning/exam_agent.py, agent_core/modules/teacher_module.py

## OpenClaw LIVE

### Model separation
- `ollama pull qwen2.5:3b` - osobny model dla OpenClaw (2GB)
- Maria dalej na llama3.1:8b (5GB) - zero konfliktu
- Config: agents.defaults.model.primary = ollama/qwen2.5:3b

### Gateway + Node setup
- Gateway: juz dzialal (systemd, port 18789, deployadmin)
- Node: `openclaw node install` + `systemctl --user start openclaw-node`
- Parowanie: `openclaw devices approve <request-id>`
- Exec approvals: allowlist /bin/sh, /bin/bash, /usr/bin/*, /bin/*
- Kluczowe: `--security full` + bez `--raw` (bezposrednie komendy)

### Klient v2 - subprocess zamiast HTTP
- `/tools/invoke` HTTP API NIE DZIALA z node tools na Linux
- Node tools (exec, read, write): `openclaw nodes run --json`
- Agent tools (web_fetch, web_search): `openclaw agent --json`
- Wymagane: `sudo -u deployadmin` (maria nie ma wlasnej tozsamosci OpenClaw)
- Sudoers: `/etc/sudoers.d/maria-openclaw` - maria moze uruchamiac openclaw jako deployadmin
- 67 testow (z 47 starych przerobione + 20 nowych)

### Architektura OpenClaw
```
Maria (user maria)
  -> OpenClawClient (subprocess)
    -> sudo -u deployadmin openclaw nodes run --json -- <command>
      -> Gateway (ws://127.0.0.1:18789)
        -> Node (system.run)
          -> /bin/echo hello
```

## Testy
- 1654 passing (bylo 1634)
- +15 nowych openclaw, +5 teacher stats

## Eryk
- Przygotowal MODEL_REGISTRY_CANDIDATES_v2 - target architecture
- Przygotowal material edukacyjny o LLM dla Marii (do uzycia po benchmark)
- Decyzje: embeddingi=cold/future, triage=benchmark first, registry v2=po walidacji
- Cierpliwy przy OpenClaw debugging (ponad godzine troubleshootingu!)
