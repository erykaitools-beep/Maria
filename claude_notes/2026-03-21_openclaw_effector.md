# Sesja 2026-03-21 (4/4) - OpenClaw Effector Client

## Co zrobilismy

### OpenClaw Effector - klient HTTP + planner integration
- **openclaw_client.py:** OpenClawClient - invoke_tool(), health_check(), retry, stats
- **tool_specs.py:** 7 dozwolonych narzedzi (exec, web_fetch, web_search, message, read, write, cron), walidacja args, whitelist/blacklist
- **ActionType.EFFECTOR** w planner_model.py
- **K7 RESTRICTED** + rate limit 10/h
- **K10 AUDIT_ONLY** + EffectType.EXTERNAL_API + snapshots
- **_exec_effector()** w action_executor.py
- **Wiring:** homeostasis_module graceful fallback (dziala bez OpenClaw)
- **47 testow**, 1634 total passing

### Architektura:
```
Planner.run_cycle()
  -> ActionType.EFFECTOR
  -> K7 check (RESTRICTED, rate limit 10/h)
  -> K10 before_action (AUDIT_ONLY, snapshot)
  -> ActionExecutor._exec_effector(plan)
    -> OpenClawClient.invoke_tool("exec", {"command": "df -h"})
      -> POST http://127.0.0.1:18789/tools/invoke
      -> Bearer token auth
    -> {"ok": true, "result": "..."}
  -> K10 after_action (snapshot)
```

### Kluczowe decyzje:
1. Graceful degradation - OpenClaw opcjonalny, Maria dziala bez niego
2. Whitelist - tylko 7 znanych narzedzi, reszta odrzucona
3. Browser zablokowany - OpenClaw domyslnie blokuje browser przez HTTP
4. K7 RESTRICTED - planner nie wywoła efektora autonomicznie w v1

## Nastepne kroki
- Zainstalowac OpenClaw na mini PC (npm install -g openclaw)
- Skonfigurowac token w .env (OPENCLAW_GATEWAY_TOKEN)
- Restart Maria -> auto-podlaczenie efektora
- Model Registry Stage 2: benchmark MODEL-04 triage
