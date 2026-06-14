# M.A.R.I.A. - Work Instructions v1.0

> Instrukcje pracy dla agentow pracujacych nad projektem Maria.
> Przeczytaj CALY ten plik zanim zaczniesz pracowac.
> Data: 2026-04-14.

## A. Projekt w skrocie

**M.A.R.I.A.** (Meta Analysis Recalibration Intelligence Architecture) - lokalny, autonomiczny agent AI ktory uczy sie z plikow tekstowych, dziala 24/7 na mini PC, komunikuje sie przez Telegram i Web UI.

- **Jezyk:** Python 3.10
- **LLM:** Ollama (llama3.1:8b lokal) + NIM API (z-ai/glm5 zdalny)
- **Runtime:** `maria.py` (daemon + Web UI w jednym procesie, systemd)
- **Testy:** pytest, ~4000+ testow
- **Branch:** `refactor/homeostasis`

## B. Struktura katalogow

```
/home/maria/maria/
├── maria.py                # Entry point (daemon + Web UI)
├── main.py                 # REPL (legacy, nadal dziala)
├── agent_core/             # CALY nowy kod tutaj
│   ├── homeostasis/        # Core tick loop (1Hz), sensors, mode regulator
│   ├── planner/            # K5: ReAct loop (OBSERVE->THINK->ACT->EVALUATE)
│   ├── goals/              # K3: Goal system (JSONL store, PROPOSED flow)
│   ├── autonomy/           # K7: Policy, rate limiter, approval queue, trust
│   ├── world_model/        # K6: Beliefs (JSONL store)
│   ├── deliberation/       # K8: Multi-step strategies
│   ├── meta_cognition/     # K9: Reflection, confidence
│   ├── action_safety/      # K10: Audit, effect validation
│   ├── teacher/            # Autonomous learning engine
│   ├── creative/           # K13: Tension detection, meta-goals
│   ├── critic/             # Faza G: Knowledge quality gate
│   ├── self_analysis/      # K12: Self-analysis (NIM/Claude)
│   ├── telegram/           # Telegram bot (ClawBot)
│   ├── llm/                # LLM routing, NIM, model registry
│   ├── semantic/           # Embedding search (nomic-embed-text)
│   ├── modules/            # homeostasis_module.py (wiring everything)
│   ├── registry/           # SharedContext, module registry
│   ├── tests/              # WSZYSTKIE testy tutaj
│   └── [inne moduly]/      # vision, reminders, bulletin, etc.
├── maria_core/             # Legacy modules (stary kod, nie ruszaj)
├── maria_ui/               # Web UI (Flask + SocketIO)
├── meta_data/              # Runtime data (JSONL + JSON)
├── memory/                 # Knowledge data (legacy location)
├── input/                  # Pliki do nauki (txt)
├── docs/                   # Dokumentacja
├── scripts/                # Systemd, backup, install
└── claude_notes/           # Notatki Claude miedzy sesjami
```

## C. Zespol

| Agent | Rola | Narzedzia | Kontekst |
|-------|------|-----------|----------|
| **Claude** | Architekt + complex work | Pelny dostep do kodu, testy, git | Ma pelna historie projektu (CLAUDE.md + memory) |
| **Codex** | Mechaniczne refaktoringi | Dostep do repo (GitHub) | Czyta TYLKO ten plik + PERSISTENCE_CONTRACT.md |
| **Maria** | System produkcyjny | Ollama, NIM, Telegram | Czyta swoje wlasne pliki (meta_data/, memory/) |
| **Eryk** | Operator / decydent | Telegram, SSH, laptop | Zatwierdza kierunek, przegladal wyniki |

### Zasady wspolpracy:
1. **Codex nie potrzebuje historii projektu** - dostaje konkretne taski z tym plikiem jako kontekstem
2. **Claude pisze precyzyjne prompty dla Codexa** - nie "napraw persistence" tylko "w pliku X, linia Y, dodaj Z"
3. **Maria nie modyfikuje swojego kodu** (ADR-006) - tylko czyta i pisze dane
4. **Eryk zatwierdza** przed pushem na GitHub

## D. Konwencje kodu

### D1. Jezyk
- Docstrings: **angielski**
- Komentarze: moga byc po polsku
- Nazwy zmiennych/klas: angielski
- Type hints: preferowane
- **BEZ emoji w kodzie** (ADR-005)

### D2. Testy
```bash
# Aktywuj venv
source venv/bin/activate

# Wszystkie testy
python -m pytest agent_core/tests/ -v

# Konkretny plik
python -m pytest agent_core/tests/test_planner.py -v

# Konkretny test
python -m pytest agent_core/tests/test_planner.py::TestGoalSelector -v

# Z timeoutem (60s per test)
python -m pytest agent_core/tests/ --timeout=60
```

- Kazdy nowy modul MUSI miec testy w `agent_core/tests/test_{nazwa}.py`
- Testy sa mockowane (zero external deps, zero LLM, zero sieci)
- Uzyj `tmp_path` fixture dla plikow tymczasowych
- **Nie pushuj jesli testy nie przechodza**

### D3. Import
```python
# Prawidlowy import wewnatrz agent_core:
from agent_core.goals.store import GoalStore
from agent_core.planner.planner_model import Plan, ActionType

# NIE uzywaj relative imports:
# from .store import GoalStore  # ZLE
```

### D4. Nowy modul - checklist
- [ ] Katalog: `agent_core/{nazwa}/`
- [ ] `__init__.py` z publicznym API
- [ ] Testy: `agent_core/tests/test_{nazwa}.py`
- [ ] Persistence: wg `PERSISTENCE_CONTRACT.md`
- [ ] Wiring: wpis w `agent_core/modules/homeostasis_module.py`
- [ ] SharedContext: pole w `agent_core/registry/shared_context.py`
- [ ] Dokumentacja: wpis w `CLAUDE.md` (sekcja odpowiednia)

### D5. Persystencja - OBOWIAZKOWE
Przeczytaj `docs/PERSISTENCE_CONTRACT.md` zanim dotkniesz jakiegokolwiek pliku w `meta_data/`.

Krotko:
- **MERGE store** (goals, beliefs, reminders) -> wolaj `save()` po KAZDEJ mutacji
- **APPEND store** (logi, traces) -> append natychmiast, thread-safe
- **OVERWRITE** (state JSON) -> atomic write (tmp + rename)
- **Nowy plik** -> dodaj do katalogu w PERSISTENCE_CONTRACT.md

## E. Git workflow

### E1. Branch
- Pracujemy na `refactor/homeostasis`
- NIE tworzymy feature branches (za maly zespol)
- Commit po kazdym ukonczonym tasku

### E2. Commit message
```
<type>: <opis po angielsku> (<kontekst>)

Przyklady:
fix: critique spam loop - add rate limit 1/h (K7)
feat: Faza 7 Trust wiring (homeostasis Phase 16)
refactor: GoalStore save() after propose() (persistence fix)
```

Typy: `feat`, `fix`, `refactor`, `test`, `docs`, `security`, `chore`

### E3. Push
- **NIGDY nie pushuj automatycznie** - zapytaj Eryka
- GitHub repo jest publiczne - nie pushuj: kluczy API, tokenow, .env, prywatnych danych
- Push dopiero po weryfikacji na produkcji

## F. Architektura decyzyjna

### F1. Tick loop (1Hz)
```
HomeostasisCore.tick()
├── Phase 8:   PERCEIVE (sensors -> PerceptionBuffer)
├── Phase 8.5: VISION (camera frame -> motion/scene)
├── Phase 9:   IDLE TRIGGER (auto-learn po 10min idle)
├── Phase 9.5: MODEL SCHEDULER (load/unload Ollama models)
├── Phase 9.7: LOG ARCHIVAL (rotate old JSONL to /mnt/storage)
├── Phase 10:  PLANNER (goal select -> plan -> execute -> evaluate)
├── Phase 11:  TELEGRAM (poll updates, handle commands)
├── Phase 12:  REMINDERS (check scheduled notifications)
├── Phase 13:  PROACTIVE (morning brief, contact)
├── Phase 14:  WORKFLOW (advance active workflows)
├── Phase 15:  ENVIRONMENT (mode detection)
└── Phase 16:  AUTO-PROMOTION (Faza 7 trust check)
```

### F2. Planner flow (Phase 10)
```
PlannerGuard.can_plan()  # health, mode, sandbox check
    -> Creative check (independent cooldown)
    -> GoalSelector.select_ranked()  # aging priority
    -> _create_plan_for_goal()  # K8 deliberation or fallback
    -> K7 rate limit check
    -> ActionExecutor.execute()  # delegate to Teacher/Sandbox/etc.
    -> Evaluate result
    -> GoalStore.save() + TraceStore.record()
```

### F3. Learning pipeline
```
Outside learning window: creative -> self_analyze -> critique -> evaluate -> validate -> NOOP
Inside learning window:  learn -> exam -> review -> fetch -> ask_expert -> NOOP

Learning windows (Berlin time): 9-11, 14-16 (Mon-Fri)
USER goals bypass windows.
```

## G. Kluczowe pliki do przejrzenia

Jesli chcesz zrozumiec jak Maria dziala, przeczytaj w tej kolejnosci:

1. `agent_core/homeostasis/core.py` - tick loop (linie 300-530)
2. `agent_core/planner/planner_core.py` - planner flow (linie 270-450)
3. `agent_core/planner/action_executor.py` - co Maria robi (execute)
4. `agent_core/modules/homeostasis_module.py` - wiring (init, linie 1-1340)
5. `agent_core/registry/shared_context.py` - wspoldzielony kontekst
6. `docs/PERSISTENCE_CONTRACT.md` - jak dane sa zapisywane

## H. Kontrakty architektoniczne (K1-K20)

Kazdy podsystem ma formalny kontrakt w `docs/CONTRACTS.md`. Kluczowe:

- **K3 Goals:** max 20 active, max 3 proposed, PROPOSED -> PENDING -> ACTIVE
- **K7 Autonomy:** FREE/GUARDED/RESTRICTED/FORBIDDEN + rate limits per action
- **K10 Safety:** AUDIT_ONLY (READ-ONLY audit), safe-by-default
- **K12 Self-Analysis:** NIM API -> goals + beliefs + hints
- **K13 Creative:** tension detection -> meta-goals -> GoalStore

## I. Czego NIE robic

1. **Nie ruszaj `maria_core/`** - legacy, backward compatibility
2. **Nie dodawaj nowych dependencies** bez konsultacji z Erykiem
3. **Nie usuwaj testow** - nawet jesli "przeszkadzaja"
4. **Nie zmieniaj formatu JSONL** istniejacych plikow bez migracji
5. **Nie dodawaj emoji** do kodu (ADR-005)
6. **Nie pushuj na GitHub** bez zgody operatora
7. **Nie twórz feature branches** - commituj na `refactor/homeostasis`

## J. Troubleshooting

### Maria nie startuje
```bash
sudo journalctl -u maria.service -n 50 --no-pager
# Czeste: Ollama nie dziala, brak modelu, brak .env
```

### Testy nie przechodza
```bash
# Sprawdz czy venv aktywny
which python  # powinien byc /home/maria/maria/venv/bin/python

# Uruchom konkretny test z verbose
python -m pytest agent_core/tests/test_planner.py -v --tb=long -x
```

### Dane znikaja po restarcie
- Sprawdz czy store wola `save()` po mutacji
- Sprawdz `PERSISTENCE_CONTRACT.md` sekcja B2 (MERGE stores)

---

*Wersja 1.0 - 2026-04-14*
