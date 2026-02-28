# Legacy Archive - 2026-02-28

## Co tu jest

Foldery przeniesione z `maria_core/` w ramach Stage 5 cleanup (REFACTOR_PLAN.md).

| Folder | Zawartosc | Dlaczego przeniesiony |
|--------|-----------|----------------------|
| `agent/` | agent_loop.py, interpreter.py, MariaAgent.py | Zastapiony przez `agent_core/modules/` (registry-based) |
| `logs/` | Stare logi z 2025-11/12 | Produkcyjne logi sa w `<root>/logs/` (config.py: `LOGS_DIR = BASE_DIR / "logs"`) |
| `output/` | ai_alerts, ai_insights, maria_generated/ | Nieuzywane - brak referencji w kodzie |
| `memory/` | 68 plikow .txt + JSONL (stare dane nauki) | Produkcyjne dane sa w `<root>/memory/` (config.py: `MEMORY_DIR = BASE_DIR / "memory"`) |

## Weryfikacja przed przeniesieniem

- Grep po calym codebase: zero importow tych folderow w produkcyjnym kodzie
- `config.py` uzywa `BASE_DIR / "memory"` i `BASE_DIR / "logs"` (root-level, nie maria_core/)
- `agent/` importowany tylko przez `self_evolver.py` -> `heartbeat.py` (oba nieuzywane w produkcji)
- 668 testow passing po przeniesieniu

## Kiedy mozna usunac

Po 48h stabilnosci bez problemow. Jesli cos sie zepsuje - po prostu przenies foldery z powrotem:
```bash
mv maria_core/_legacy_archived/2026-02-28/agent maria_core/agent
# itd.
```

## Kto przenosil

Claude Code (sesja 2026-02-28), zatwierdzone przez Eryka.
Rada ChatGPT: archiwizacja != usuniecie, najpierw 48h test.
