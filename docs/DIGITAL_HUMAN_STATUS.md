# M.A.R.I.A. — Digital Human: stan i plan instalacji

> Żywy dokument (aktualizuj w miejscu, NIE rób datowanych kopii).
> Świeża ocena „gdzie jesteśmy na drodze do digital human" + plan podłączeń.
> Komplementarny do `DIGITAL_HUMAN_ROADMAP.md` (tamten = design Faza 1-7; ten = stan + wiring).
>
> **Branch:** `refactor/homeostasis` (lokalny) · **Ostatnia aktualizacja:** 2026-07-06 (częściowy patch: wiersze Ręce/Samowiedza/Złożone działanie/Zmysły były fałszywe od 06-21..24; pełny refresh 9 organów przy zamknięciu Tier 2)

## Werdykt: ≈60% drogi do digital human (re-ocena 07-06; było ≈45% w ocenie 06-21)

> Dom stoi i żyje, a ręka JUŻ się rusza: Maria napisała i sama cofnęła plik na żywym OpenClaw (06-24), a pierwszy projekt operatora domknął się 3/3 (07-05). Największe luźne kable dziś: silnik workflow nigdy nie odpalony, zaufanie liczone na ślepej kartotece (rejestrator incydentów odpięty), ekonomia nietknięta.

Główna ściana: **brak zamkniętej pętli „wiedzieć → działać"** — Maria obserwuje, loguje i raportuje swój stan/limity/awarie/sny, ale (do niedawna) nic tego nie KONSUMOWAŁO żeby odmówić akcji, naprawić awarię, czy ruszyć rękami. To linia między digital human a gadającym dashboardem.

## Mapa 9 organów

| Organ | Analogia | Stan | Główna luka |
|-------|----------|------|-------------|
| Homeostaza / samonaprawa | metabolizm + odporność | 🟢 niesie | self-repair = ALERT nie cure (ADR-031, celowo) |
| Inicjatywa | pisze pierwsza | 🟢 niesie | ~~GOAL_ACHIEVED martwy~~ → **naprawione 06-21** |
| Życie wewnętrzne / ciągłość | sny, marzenia, pamięć siebie | 🟢 niesie | ~~pamięć rozmów zamarła (sesja 9, luty)~~ → **odmrożone 06-21 `f4e9392`** (condense w ticku) |
| Tożsamość operatora | wie kim jest Eryk | 🟡 częściowo | ~~rytm liczony raz~~ → **naprawione 06-21**; ~~brak active-learner~~ → **06-22 `221ee9f` ActiveLearner: pyta 1×/dzień (flag OFF)**; brak relationship-log |
| Zmysły | percepcja świata | 🟡 częściowo | ~~wzrok write-only~~ → **06-21 `cf5e284`** ruch → LLaVA → ping; ~~brak pogody~~ → **pogoda+święta z salience (weather/, hydration nudge 06-26)**; VisionMemory + PL captions (06-23/26); NADAL brak kalendarza/maili |
| Obecność / komunikacja | dostępna, responzywna | 🟢 niesie | ~~Telegram = konsola komend~~ → **06-22 `28acc77` Telegram = czat, `TELEGRAM_CHAT_ENABLED=true` ARMED**; SelfContext w czacie (E2 armed 06-26) |
| Ręce | działanie na świecie | 🟢 rusza się | **NIEAKTUALNE od 06-21/24, poprawione 07-06:** FS_WRITE LIVE (drill 06-21), pierwszy realny write+undo na żywym OpenClaw 06-24 (DH-A), outbox propose armed, `/wyslij`; OpenClaw nadal za approve (CONFIRM = przyszły szczebel) |
| Samowiedza | zna swoje możliwości | 🟡 używa częściowo | ~~K9 needs_human martwy~~ → 06-21; honesty w ogonie czatu **ARMED (E2 `SELF_CONTEXT_CHAT_ENABLED=true`)**; ~~planer nie bramkuje akcji~~ → **DH-C bramka zbudowana 06-22 + fix 06-28, uzbrojenie po DH-B (drill-first)** |
| Złożone działanie | cele wieloetapowe | 🟡 pierwszy dowód | **DH-B ARMED=observe 07-04; 1. projekt operatora 3/3 ACHIEVED 07-05, rollup dowód kompletny; cutover przed 07-09 22:57.** Silnik workflow wciąż NIGDY nie odpalony (pokój Tier 3 #1) |

🟢 żyje i niesie zachowanie · 🟡 działa, kable luźne · 🔴 zbudowane, jeszcze bierne

## Plan instalacji — 3 strefy

### 🟢 Strefa zielona — wpiąć (tanie, bezpieczne)
1. ~~`needs_human` literówka (alias + cooldown 6h)~~ ✅ **06-21 `62ef43e`**
2. ~~`record_interaction` oba kanały~~ ✅ **06-21 `4708eaf`**
3. ~~rytm operatora re-analiza w ticku (Phase 18b)~~ ✅ **06-21 `4708eaf`**
4. ~~self-state bulletin dedup-fix~~ ✅ **06-21 `190cec9`** — FAŁSZYWY ALARM: dedup już działał (1 wpis vs ~241 zmian trybu/24dni; stabilny topic `self_state_change`+IMPROVEMENT). Kodu nie ruszano; dodano test-strażnik (mutation-checked) blokujący regresję, gdyby topic stał się dynamiczny.
5. ~~growth-targets refresh + surface~~ ✅ **06-21 `ca7db3a`** — `refresh()` aktualizuje cele in-place (był append-only → liczby zamarły 30 dni) na cadence Phase 18c (~30 min); `/growth` (alias `/rozwoj`) pokazuje top 5; `/selfstatus`+`/growth` dodane do `/help`.
6. ~~progress-reporter Telegram fix (`bot.send_message`)~~ ✅ **06-21 `619e89d`** — lambda wołała `bridge.send_message` (nie istnieje → `hasattr` zawsze False → cichy no-op); teraz `bridge.bot.send_message` (parse_mode=None na podkreślenia w ID).

### 🟡 Strefa żółta — zbudować (fazami)
- ~~wzrok → planer reaguje na to co Maria widzi~~ ✅ **06-21 `cf5e284`** — VisionAdvisor: ruch (non-ambient) → LLaVA w WĄTKU → proaktywny ping „Widzę ruch — …". UCZCIWIE: wzrok w ticku to tylko statystyki (jasność/kolor/ruch); realne „widzę" = LLaVA on-motion (poza tickiem). Planer i tak nie może DZIAŁAĆ (K7), więc wartość = Maria zauważa i MÓWI. Cooldown 180s, R1/K7-safe.
- ~~pamięć rozmów odmrozić (condense na każdą sesję z historią; stoi na lutym)~~ ✅ **06-21 `f4e9392`** — `condense_pending_sessions()` drenuje zamknięte (idle) sesje z trwałej historii; Phase 20 cadence ~5min; po restarcie dociąga 44-backlog. Konsument (`get_conversation_context`→prompt) był już wpięty.
- ~~w czacie zna realne możliwości (situational-tail, NIE stable prefix — busta cache)~~ ✅ **06-21 `75f7934`** — DWIE warstwy: (1) stałe możliwości w TOŻSAMOŚCI (`master_prompt`, było STARE: tylko „widzę/planuję/deleguję" → Maria zaniżała; teraz reaguje-na-ruch/uczy-się/pisze-pierwsza/ręka-FS_WRITE + gard „nie zaniżaj/nie wyolbrzymiaj"), jednorazowy bust prefiksu; (2) żywy stan w OGONIE sytuacyjnym (`_build_situational_tail` — metoda zapowiedziana w docstringach, nie istniała; 2. msg system PO cache'owanym prefiksie → zero bustu, cap 600). Prefix byte-stable potwierdzony. 46 testów. Wymaga restartu.
- ~~mówi gdy zda egzamin / skończy plik (LEARNING_MILESTONE observer)~~ ✅ **06-21 `fb0e35f`** — bliźniak GOAL_ACHIEVED: `teacher_agent._exec_review` na `passed` → `milestone_fn(file_id, score)` → `ProactiveScheduler.note_learning_milestone()` (dedup pliku 24h, batchowanie) → generator drenuje bufor. Cooldown 2h. Wymaga restartu.
- ~~przykręcić fabrykę celów-widm + rurę podaży materiału~~ → **częściowo 06-21** (patrz niżej)

### 🔴 Strefa czerwona — pod napięciem (na końcu, za bezpiecznikiem)
- **Etap 1** ~~Ręce: FS_WRITE drill — jailed sandbox, pierwsza bezpieczna ręka~~ ✅ **06-21 `37dcc27`** — `/drill_fs_write`: silnik+K7/K10+pętla planera już były, brakowało DOWODU na żywo. Drill seeduje cel `file_exists` (świeża nazwa uuid), odpala REALNY łańcuch `_maybe_fs_write`→executor→`close_goal_on_criteria` RAZ, flaga ON tylko na czas runu (restore w finally), cel domyka się NA DOWODZIE (plik na dysku). To pierwsza **autonomiczna** ręka (Rung 2 był za zgodą operatora). 5 testów, jailed `meta_data/fs_sandbox/`, ≤1KiB. Wymaga restartu.
- **Etap 2** ✅ **06-21 (noc) `f887924`** — POWÓD do pisania. Luka po Etap 1: nic nie tworzyło celów `file_exists` samo → uzbrojenie `FS_WRITE_ENABLED` było bezczynne. Teraz: na zdany egzamin (LEARNING_MILESTONE) `teacher_module._maybe_seed_learning_note` zasiewa cel-notatkę („Nauczyłam się: X / egzamin Y%") → planer pisze → cel domyka się na dowodzie. **DOUBLE-GATED OFF** (`LEARNING_NOTES_ENABLED` + flaga FS_WRITE muszą być ON; inaczej nie tworzy = zero litter). Dedup per plik, jailed. Zweryfikowane end-to-end (probe). **Uzbrojenie = OBA flagi w `.env` + restart.** **NASTĘPNE: Etap 3** = OpenClaw szczebel SUGGEST (osobno, wymaga undo).
- OpenClaw: wspinać szczebel po szczeblu (SUGGEST→CONFIRM→BOUNDED), NIGDY skok; unsandboxed, brak undo
- K11 eksperymenty: łańcuch 3 klocków (byvalue-fix → applier+rollback → confidence-gate), auto-rollback obowiązkowy
- **Self-repair: NIE RUSZAĆ** (ADR-031 — approve=zamknięcie, nigdy auto-dispatch Codexa na prod)

## Zrobione 2026-06-21 (poza planem instalacji: strona podaży)

Diagnoza: „głód materiału" = NIE głód, tylko **zatrzaśnięty bezpiecznik + zatkana rura podaży**.

- ✅ `1d12981` **skip ≠ porażka** — `filtered_out_all_candidates` (brak świeżego materiału) to SKIP, szedł jako fail → K7 breaker blokował każdy learn → deadlock do restartu. Fix: `record_execution(skipped=)`.
- ✅ `7e73548` **sny co sen** — REM odprzęgnięty od 20h throttle beliefów (był sklejony → 0 snów w nocy). Flaga `mutate_beliefs`. Dowód live: 3 sny + 2 topiki przy throttle.
- ✅ `d9ed918` **fetch hint-filtr** — `_is_fetchable_concept` na hintach + reject underscore (koniec meta-bełkotu do Wikipedii).
- ✅ `e6cad8f` GOAL_ACHIEVED live (obserwator GoalStore).

### cz.2 — zielona strefa instalacji DOMKNIĘTA (06-21)

Wszystkie 3 pozostałe zielone kable wpięte (szczegóły w liście wyżej): #6 `619e89d` (progress-reporter), #5 `ca7db3a` (growth refresh + `/growth`), #4 `190cec9` (strażnik dedup). **Cała 🟢 strefa zielona = DONE.** 144 testy zielone w dotkniętych suite'ach. **Wymaga restartu** (Phase 18c, komenda `/growth`, wiring czytane na boot). Następny krok wg mapy: 🟡 strefa żółta (np. odmrożenie pamięci rozmów lub LEARNING_MILESTONE).

## Zrobione 2026-06-22 (noc autonomiczna) — 4 pokoje + review

Recon-first (7 agentów) → 4 pokoje, każdy flag-OFF → adversarial review (12 agentów) → 8 napraw. JEDEN restart rano. Detal → `claude_notes/2026-06-22_night_digital_human.md`.

- 👀 `16f8aa2` **`/learning_notes`** — read-only okno na autonomiczne notatki z nauki (Etap 2 obserwowalny). **Działa od razu (brak flagi).**
- 💬 `28acc77` **Telegram = czat** — plain-text → mózg daemona (tożsamość + ogon jak Web UI). Wątek (nie blokuje komend), graceful busy. Flaga `TELEGRAM_CHAT_ENABLED`.
- 🧠 `bdb5ec9` **honesty w ogonie czatu** — linia „czego nie umiem" ze statycznych limitations (nie-sprzeczna z tożsamością), cache-safe (tylko ogon). + fix double-comma w `qualify_statement` (**działa od razu**). Flaga `HONESTY_HINT_ENABLED`.
- 🤝 `221ee9f` **ActiveLearner (K14.1)** — pyta 1×/dzień 1 pytanie (ranker privacy-aware + per-key cooldown 14d + pending TTL 6h + answer-capture). Reuse rate-limiter proactive (`OPERATOR_QUESTION`). Flaga `ACTIVE_LEARNER_ENABLED`.
- 🧪 `6bcad55` **conftest env-leak** — autouse `delenv` FS_WRITE/LEARNING/PLAY/TELEGRAM_CHAT (testy = default kodu).
- 🔍 `8016746` **review fix ×8** — m.in. martwy wiring honesty (unwrap `.ollama`), 240s blokada Telegramu (wątek), mis-capture odpowiedzi (TTL+conf 0.8).

**Następny czerwony krok:** Etap 5 = OpenClaw dziennik+cofanie (HIGH ryzyko, TYLKO z operatorem live; fundament pod szczebel SUGGEST). 🚫 Self-repair nie ruszać (ADR-031).

## Odłożone (świadomie, z powodem)

- **fetch cz.2** — guard tworzenia celu po statusie `non_chunking` (NIE rozmiarze: `MIN_CHUNK_SIZE=600` ale plik 751B i tak non_chunking). Reaper i tak porzuca junk-cele, tylko wolno.
- **fetch cz.3** — denylista EXPAND/EXPLORE (żargon Marii: `kontekst`/`m.a.r.i.a.`/`metadane`). Krucha; ożywiony DREAM zmniejsza poleganie na EXPAND.
- **pamięć rozmów** (strefa żółta) — condense na każdą sesję z historią.

## BHP / ryzyka przekrojowe (przy każdym wpinaniu)

- **Restart = Eryk** (Claude bez sudo). Grupuj zmiany kodu w JEDEN restart.
- **`.env` ładuje się na boot** → uzbrojenie flagi wymaga restartu. Nowe flagi default-OFF.
- **`_mark_dirty` silent no-op** — mutacja `goal.metadata`/belief + `save()` BEZ `_mark_dirty()` znika po restarcie.
- **Shared singleton race** — daemon i maria_ui to TEN SAM proces; pisz przez żywe store'y z `shared_context`, nie świeżą instancję.
- **Mock-hidden bug** — testy z PRAWDZIWYM komponentem (MagicMock łyka zły kwarg → zielony test, martwy kod ~miesiąc).
- **Flaky suite z żywym demonem** — testy CELOWANE, nie pełna kolekcja.
- **Równoległe sesje** — ≥2 inne sesje Claude/Codex mogą pracować na repo; sprawdź `ps`/`git status`/mtimes zanim założysz że drzewo „twoje".

---

*Źródło danych: audyt 2-warstwowy (9 organów + 61 pozycji instalacji), workflow 2026-06-21. Detal sesji → memory `project-supply-side-fixes-2026-06-21`.*
