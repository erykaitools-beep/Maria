# 2026-03-19 - K7 Autonomy Policy / Governance

## Kontekst
Sesja z Erykiem. Zaczelismy od analizy logow - planner utknql w petli fetch-fail (1430 prob w 24h).
Fix: knowledge_analyzer wykrywa unindexed files, fetch success oparte na errors==0.
Commit: 3fc4f4a

Potem przeszlismy do K7.

## Diagnoza obecnego systemu
- **PlannerGuard** (5 regul): blokuje CALY planner gdy system niezdrowy
- **ConstraintValidator**: progi zasobow (RAM, CPU, temp, disk)
- **Brak klasyfikacji akcji** - wszystkie ActionTypes traktowane jednakowo
- **Brak rate limitu** - fetch mogl probowac 1430 razy bez ograniczenia
- **Brak HITL** - Maria nie moze poprosic czlowieka o pomoc

## Plan K7 (zatwierdzony przez Eryka)

### Struktura
```
agent_core/autonomy/
    __init__.py              # AutonomyPolicy facade
    action_class.py          # ActionClassification: FREE/GUARDED/RESTRICTED/FORBIDDEN
    policy_rules.py          # PolicyRule dataclass + PolicyEngine (default rules per ActionType)
    rate_limiter.py          # Per-action rate limits (max N per hour)
    escalation.py            # Escalation decisions (log/block/hitl placeholder)
```

### Klasyfikacja akcji
- **FREE** - wykonuj bez pytania: LEARN, EXAM, REVIEW, EVALUATE, NOOP
- **GUARDED** - rate limit + logowanie: FETCH, MAINTENANCE
- **RESTRICTED** - wymagaj warunkow/potwierdzenia: (przyszle: SMART_HOME, CODE_EXEC)
- **FORBIDDEN** - nigdy autonomicznie: (przyszle: DELETE_DATA, SYSTEM_MODIFY)

### Rate limiter
- Per ActionType limity na godzine
- FETCH: max 5/h (zeby nie bylo 1430 prob)
- MAINTENANCE: max 10/h
- FREE actions: bez limitu (ale z logowaniem)

### PolicyRule
- Regula: "jesli akcja X i warunek Y, to decyzja Z"
- Warunki: action_type, health_score, mode, confidence, retention
- Decyzje: ALLOW, RATE_LIMITED, BLOCK, ESCALATE

### Integracja
- Wejscie w pipeline: PlannerGuard -> **AutonomyPolicy.check()** -> ActionExecutor.execute()
- SharedContext: nowe pole `autonomy_policy`
- PlannerCore: wywolanie check() w _finalize_plan() przed execute()

### Zasady
- Zero LLM (ADR-013 kontynuacja)
- Deterministyczny, testowalny
- Backward compatible (autonomy_policy=None nie psuje nic)
- HITL jako placeholder (logowanie + blokada, pelny HITL pozniej)

### Co NIE wchodzi (na razie)
- Pelny HITL z blokowaniem i czekaniem na odpowiedz
- Action Safety K10 (simulate/stage/commit)
- Multi-step deliberation K8
