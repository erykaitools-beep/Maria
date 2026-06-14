# M.A.R.I.A. — System Status (source of truth)

> **Po co ten plik:** jedno miejsce, które mówi prawdę o tym, **co faktycznie żyje**
> w produkcji, a co jest tylko biblioteką/eksperymentem. Powstał po Codex deep
> audit v2 (2026-05-29, `docs/audits/codex_deep_2026-05-29/`), który pokazał, że
> docs opisywały kilka wersji systemu naraz.
>
> **Zasada (definicja DONE od 2026-05-29):** moduł nie jest "zrobiony", dopóki nie
> osiągnie `OBSERVED` — czyli dopóki **nie zobaczyliśmy go w logach**. "Library +
> testy + docs" to nie to samo co "działa in-vivo". To jest mechanizm na korzeń
> dryfu: *"łatamy stare i budujemy nowe, a nie ma sprawdzania"*.

## Słownik statusów (5 poziomów)

| Status | Znaczenie | Dowód |
|---|---|---|
| `LIBRARY` | Kod + testy istnieją | zielona suita |
| `WIRED` | Osiągalny z daemona/REPL/UI (spine go importuje) | import graph |
| `OBSERVED` | **Odpalił w żywych/archiwalnych logach** | wpisy w `meta_data/` lub `/mnt/storage/data/logs/` |
| `OPERATOR_READY` | Jest flow operatora (UI/Telegram) + udokumentowany | komenda/endpoint + doc |
| `RESEARCH_ONLY` | Świadomie NIE jest live (zamrożone/eksperyment) | decyzja kierunkowa |

Awans statusu wymaga dowodu z poziomu wyżej — `WIRED`→`OBSERVED` tylko gdy są wpisy w logach, nie gdy "powinno działać".

## Mapa modułów (stan 2026-05-30)

Źródło: import graph z `maria.py`/`main.py`/`maria_ui.app`, live `meta_data/`,
journal `maria.service`, punktowy drill self-repair i testy regresji.

| Moduł | Status | Notatka / dowód |
|---|---|---|
| K1-K13 cognitive core | `OBSERVED` | bogaty runtime archive (decision_traces, action_audit, reflections) |
| `homeostasis` (tick 1-19) | `OBSERVED` | tick loop, `homeostasis_events` 76.7k archive |
| `planner` | `OBSERVED` | live działa, ale `no_goals` często oznacza "brak wykonalnych celów teraz", nie pustą kolejkę celów |
| `creative` | `OBSERVED` | `creative_events` 4160 live; generator→bulletin (R1) potwierdzony 19:02 |
| `critic` | `OBSERVED` | `critique_reports` 5186 archive |
| `bulletin` | `OBSERVED` | `cognitive_bulletin` 824 (open 470, resolved 354) |
| `llm` (LLMManager + NIM + scheduler) | `OBSERVED` | 15/15 reachable; nemotron-49b EXTERNAL |
| `self_perception` (Phase 18) | `OBSERVED` | `self_state_snapshots` 49 live |
| `routing` (IntentRouter) | `WIRED` (flag-gated) | default false via env (`routing/intent_router.py:68`) |
| `conductor` (Phase 17) | `WIRED` + `OBSERVED` (market) | dispatcher wired; `market_task_queue` 92 rows; obecnie idle/skipping, bo brak gotowych zadań lub dirty-worktree guard |
| `vision` | `WIRED` (sensor optional) | LLaVA on-demand, cortex współdzielony z UI |
| `orchestrator` (V3) | `WIRED` | init w `maria.py:477` |
| **`self_repair` (Phase 19)** | **`WIRED`, `OBSERVED` w kontrolowanym drillu, nie naturalnie in-vivo** | `SystemFailureMonitor -> RepairTaskCreator -> maria_task_queue -> approval_required gate -> dispatcher` zweryfikowane 2026-05-30; live zdrowy/SLEEP, więc naturalny kandydat jeszcze nie powstał |
| `skills` | `LIBRARY` (1.0-backlog) | extractor istnieje (`teacher/skill_extractor`), brak wiring do planner/tick; STATUS banner w `__init__.py` 2026-05-31; nie kasować |
| `symbolic` (world model) | `RESEARCH_ONLY` | **Maria 2.0 — zamrożone 2026-05-29.** 0 importów ze spine; flaga nigdy nie czytana |
| `predictive` (B0/B0.1, JEPA) | `RESEARCH_ONLY` | **Maria 2.0 — zamrożone 2026-05-29.** 0 importów ze spine |
| `adapters` | **USUNIĘTY 2026-05-31** | most migracyjny maria_core→agent_core, 0 reachable. Usunięty: 1226 LoC + `test_adapters.py`; nie-adapterowe integ-testy zachowane w `test_homeostasis_integration.py` |
| `metacontrol` | **USUNIĘTY 2026-05-29** | tor A3: usunięty + `test_metacontrol.py` (273 LoC, 24 testy) |
| `agent_core/ui` | **USUNIĘTY 2026-05-29** | tor A3: usunięty (746 LoC, 0 testów); Web UI to `maria_ui/` |
| `agent_core/executor` | `LEGACY` (document) | tylko `TYPE_CHECKING` import w `homeostasis/core.py:40` |

## Korekta po głębokim pass 2026-05-30

Wnioski z audytu 2026-05-29 trzeba czytać przez pryzmat zmian z 2026-05-30:

- `OperatorModel` split-brain jest zasadniczo zamknięty: daemon ustawia
  `ctx.user_profile = operator_model`, Web UI brain/chat/profile idą przez
  `get_operator_model()`, a `UserProfile` zostaje jako legacy adapter/test target.
- `self_repair` nie jest już tylko "może działa": punktowy drill potwierdził pełny
  łańcuch task creation + approval gate. Brak live `maria_task_queue.jsonl` oznacza
  brak naturalnego kandydata, nie brak wiring.
- Polityka wykonalności (okna nauki + tryb `SLEEP`) bramkuje autonomię. **2026-05-31
  (#5) wykryto i naprawiono ŻYWY bug:** `PROFILE_LEARNING.auto_trigger_hours` były
  autorskie jako UTC i po przełączeniu OS TZ na Europe/Warsaw (29.05) odpalały okno
  2h za wcześnie (07-10 + 12-15 zamiast 09-11 + 14-16). Naprawione do `(9,10,14,15)`
  Berlin-pinned (`berlin_now`, ZoneInfo, DST-safe) — `9efe7cf`/`5fe75ee`/`65b1b4e`.
  To tłumaczy `no_goals` w prawdziwym oknie (uczenie startowało nocą z budżetu
  off-window). Off-window budżet rytmu (8b) + reconciliation/reaper celów (#3) już
  wdrożone; weryfikacja daytime-learning w boju czeka na poniedziałek 09:00.
- `StrategicPlanner` jest `WIRED` + podpięty do pętli taktycznej za flagą
  `STRATEGIC_PLANNER_DRIVES` (#9, 2026-05-31, default OFF). Gdy ON: `blocked_goals`
  filtruje cele, `next_action` ustawia fokus + domyka plan, `idle_strategy` steruje
  idle-fallbackiem; wszystkie bramy BHP (feasibility/okno/backoff/tryb/K7) zostają
  w rdzeniu. `OBSERVED` czeka na live drill (poniedziałek) -> potem flip default ON.

### Obecne priorytety fundamentów

> **Kolejność budowy (SSoT): `docs/DEVELOPMENT_SEQUENCE.md`.** Poniższa lista to
> źródło/rationale; #1 (okno, #5) i #3 (StrategicPlanner, #9) zamknięte, #2/#4
> żyją w TIER 1/2 tego SSoT. Aktualizuj tam, stąd linkuj.

1. Zastąpić sztywne okna nauki budżetem rytmu: weekend/wieczór powinny dopuszczać
   lekkie akcje autonomiczne (`goal_refresh`, `fetch`, `review`, self-repair drill),
   bez odpalania ciężkiego `learn/exam`.
2. Dodać `Goal Reactivation`: stare active learning/meta goals muszą przechodzić
   `revalidate -> refresh topic -> next executable action`, zamiast zalegać.
3. ~~Dokończyć most `StrategicPlan.action_queue -> PlannerCore`~~ — ZROBIONE
   2026-05-31 (#9, A+B+C za flagą `STRATEGIC_PLANNER_DRIVES`, default OFF);
   zostaje live drill + flip default po obserwacji.
4. Zrobić jeden kontrolowany live drill self-repair w `ACTIVE/REDUCED`, żeby
   produkcyjnie zobaczyć `meta_data/maria_task_queue.jsonl`, `/list_repairs`,
   `/approve_repair` i dispatch.

## Maria 2.0 — zamrożone w czasie (2026-05-29)

`symbolic` + `predictive` to nowy 4-filarowy paradygmat (symbolic world model +
predictive/JEPA, zob. `docs/AGI_HYPOTHESES.md`, `docs/MARIA_2.0/`). Decyzja Eryka:
**zawieszone w czasie, NIE skasowane.** Kod + testy zostają co do linijki. Fokus
przenosi się na dojrzewanie i weryfikację Marii 1.0 (LLM+agent+memory), bo to z
niej będą realne dane "jak to będzie działać". Wracamy do 2.0, gdy 1.0 da dane.

## Stale docs — NIE traktować jako prawdy runtime

- `docs/ARCHITECTURE.md` — kwiecień 2026, mówi 11 faz / 3352 testy. Kod robi 19 faz,
  5239 testów. Historyczny, dopóki nie zregenerowany.
- Web UI `_JSONL_DATA_FLOW` (`maria_ui/app.py:2469`) — ręczna mapa, pomija m.in.
  `self_state_snapshots`, `maria_task_queue`, `creative_events`, `cognitive_bulletin`.
  Do regeneracji ze store'ów albo zdjąć z paneli "truth".

---

*Utworzony 2026-05-29 (tor A coherence cleanup). Ten plik jest SSoT dla statusu modułów — aktualizuj przy każdej zmianie wired/observed.*
