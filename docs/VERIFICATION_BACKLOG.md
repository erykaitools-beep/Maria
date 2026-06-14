# Verification Backlog — rzeczy do sprawdzania raz na jakiś czas

Rzeczy, które **zbierają się w tle** albo **odzywają tylko przy awarii** —
trzeba zajrzeć, nie zakładać że działa. To jest lekarstwo na "nie ma sprawdzania".

> Ostatni przegląd: 2026-05-30. Aktualizuj tę datę przy każdym przeglądzie.

---

## 0. ROZWIĄZANE 2026-05-30: sprawca = synchroniczny poll Telegram (faza 11), SPORADYCZNY
Stoper #3 + split fazy 11 (`40b7df4`). FINALNA diagnoza (3 runy danych, nie 1 próbka):
- **Normalny tick = ~47ms.** System ZDROWY. Sense/Vision (~22-24ms) to największe normalne kawałki.
- **In-vivo run 2026-05-30 (po restarcie #5, 5 overrunów / ~800 ticków ≈ 0.6%):**
  - **4 z 5 = Telegram** `11_poll_and_respond` ≈ 3162-3181ms (ticki 601/777/985/1103, co ~150 ticków).
    `11_learn` = 0 → czas w POLLu (sieć), NIE w pętli OperatorModel.learn. Bardzo równe ~3.17s = timeout.
  - **1 z 5 = PERCEPCJA** `01_sense` = 3250ms (tick 760), Telegram=0. **Drugi, rzadszy sprawca** —
    wcześniej niewidziany. Osobne badanie → patrz sekcja "1b. Perception stall".
- **Mechanizm (Telegram):** poll co ~30s synchroniczny; większość polli szybka, ale API Telegrama
  OKRESOWO zwleka ~3s i zamraża cały tick. Fix z 2026-05-08 (timeout=0 instant-return) nie pomaga gdy
  samo API zwleka po stronie serwera (read-timeout 3s w `bot.py` HTTP (3,3)).
- **Proporcja:** ~99.4% ticków zdrowych. Realny, powtarzalny, ale RZADKI — nie pożar.
- **DODATKOWY POMIAR (`40b7df4`):** faza 11 rozbita na `11_poll_and_respond` (rozmowa z API Telegram)
  vs `11_learn` (pętla OperatorModel.learn). Po restarcie czytać który z nich = ~3s. UWAGA: fix z
  2026-05-08 (`bot.py:200` timeout=0 + HTTP (3,3)) JUŻ jest, a faza i tak 3151ms — więc albo sieć/API
  realnie zwleka mimo instant-return, albo czas jest w `respond`/notify, nie w samym pollu.
- **NAPRAWIONE 2026-05-30 (`d77e9ed`):** Telegram poll przeniesiony na krótkożyciowy wątek-w-tle
  (`_check_telegram` → `threading.Thread`, wzorzec plannera; strażnik `is_alive()` nie pozwala stackować
  gdy API zwleka). Puls tylko odpala wątek (~0ms); 3s read-timeout dzieje się poza tickiem.
  **Zweryfikowane w boju:** 9-min okno = **0 telegram-overrunów** (było co ~30s zaraz po restarcie),
  `11_telegram` **3214ms → 0.0ms**, `/status` z Telegrama odpowiedział a puls nie drgnął.
  `poll_and_respond`/bot **nietknięte** (99 testów core/telegram/escalation zielone). Diagnoza (#3) była
  poprawna: sprawca = `get_updates` HTTP read-timeout `(3,3)`, NIE long-poll ani `11_learn`.
- **Lekcja:** emit najpierw wsadziłem w `main_loop()`, ale produkcja (`maria.py run_daemon`) woła `_execute_tick()` bezpośrednio — `main_loop` to martwy kod w prod. 5 falstartów zanim próbka wyszła. "kod jest" ≠ "kod się wykonuje" — TYLKO log rozstrzyga.

## 1. Tick timing (#3) — ROZWIĄZANE (patrz wyżej), stoper zostaje jako monitoring
Stoper na fazach ticka. Zapisuje przy ticku **>2s gdy NIE-SLEEP** (od razu) LUB **baseline co 300s zegarowych** (nie tick-count — bo SLEEP robi `+=60`/sleep/return, co psuło pierwszą wersję `%300`; v2 liczy czas).

**Fix `0e7163a` (2026-05-30):** dodał `cpu_percent` + `load_avg_1m` do eventów (patrz #1b) — TO ZOSTAJE.
ALE jego druga zmiana (strażnik `not _is_sleep`, by nie flagować "celowo długich" sleep-ticków) była
MISDIAGNOZĄ: `_execute_tick` NIGDY nie śpi zamierzenie — jedyny `time.sleep` jest w `main_loop` (martwy
kod w prod; `run_daemon` woła `_execute_tick` wprost), a czekanie między tickami jest w `run_daemon`,
POZA mierzonym oknem. Sleep-tick jest normalnie ~40ms; ten 7968ms to było realne głodzenie CPU (część (b)
tego samego commita sama tak tłumaczy 7968ms — sprzeczność wewnętrzna).
**ODKRĘCONE `f546cd1` (de-blind):** `_overrun = _tick_ms > 2000` w KAŻDYM trybie. Instrument znów widzi
overruny w SLEEP. To on dał twardy dowód „przed" do fixu Telegrama `d77e9ed` (tick 3254ms,
`11_poll_and_respond` 3214ms, cpu 1% = blok sieci, nie głodzenie — wpadł w ACTIVE tuż po restarcie).

- **Sprawdź:** `grep -E "tick_overrun|tick_timing_sample" meta_data/homeostasis_events.jsonl | tail -20`
- **Kiedy:** po restarcie (wchodzi z #4) — pierwszy `tick_timing_sample` w ≤5 min; potem raz na parę dni.
- **Czego szukasz:** które `phase_ms` ma najwięcej ms; czy `unaccounted_ms` duże (= sprawca poza 4 zmierzonymi fazami → opomiarować kolejną). `mode` w evencie mówi czy próbka z ACTIVE czy SLEEP.
- **Cel:** sprawca overrunów 3.18–3.73s (audyt v2 #4) — to ACTIVE. Tick ACTIVE powinien być ~1s.
- **UWAGA:** v1 nigdy nie odpalił (138 min, 0 próbek) — `%300` przeskakiwane przez SLEEP `+=60`. Naprawione na czas-zegarowy. Po restarcie POTWIERDZIĆ że próbki realnie wychodzą.

## 1b. Perception stall (#3b) — ZDIAGNOZOWANE 2026-05-30, monitoring
Tick 760: `01_sense` = 3250ms (vs ~22ms normalnie), Telegram=0, ORAZ vision podniesione (233ms).
**Diagnoza: percepcja NIEWINNA.** Faza 1 woła 4 sensory — wszystkie nieblokujące (sprawdzony kod):
resource (`psutil.cpu_percent(interval=None)`), thermal (`/sys` read), time (trywialny), cognitive
(czyta cache `get_last_latency_ms`, nie pinguje LLM). Czyste rozliczenie (unaccounted 0.7) + vision
też wolne tym samym tickiem = **głodzenie CPU**: `perf_counter` mierzy czas ścienny, więc gdy coś
zewnętrznego (inferencja Ollamy — planer/nauka/czat) sycy rdzenie, wątek pulsu zostaje zdjęty i faza,
w której akurat jest, pokazuje sekundy. NIE bug percepcji. BARDZO rzadkie (1 próbka active na ~800+).
- **Potwierdzenie (`0e7163a`):** dodane `cpu_percent` + `load_avg_1m` do eventów tick_overrun/sample.
  Przy następnym stallu `01_sense` sprawdź czy `cpu_percent` ~100% / `load_avg_1m` >> 6 (rdzenie) =
  potwierdza głodzenie. Pierwsze Telegram-overruny już to pokazują (cpu 51-99%, load 5.6-11).
- **Sprawdź:** `grep tick_overrun meta_data/homeostasis_events.jsonl | grep 01_sense` → patrz cpu/load.
- Gdyby cpu było NISKIE przy stallu 01_sense → wtedy szukać blokady I/O w adapterze (rewizja hipotezy).

## 2. Silent degradation (#6) — odzywa się TYLKO przy błędzie
3 miejsca logują teraz zamiast połykać po cichu.

- **Sprawdź:** `journalctl -u maria | grep -E "Health-drop notification|UserProfile reload|work_context build for chat failed"`
- **Kiedy:** raz na jakiś czas / gdy coś działa dziwnie.
- **Interpretacja:** pusto = dobrze (zdrowy system). Coś jest = realny problem, który wcześniej był ukryty.

## 3. Mapa danych UI (#7) — żywa weryfikacja jednorazowa
- **Sprawdź:** strona `/architecture` (po zalogowaniu) → `data_flow` pokazuje ~41 plików, nie 16.
- **Kiedy:** raz, przy najbliższym wejściu w Web UI. Potem skreśl ten punkt.

---

## Stałe automaty (już działają)
- **Health audit cron:** co 4 dni 06:00 (`scripts/audit.py --quiet`) → Telegram tylko gdy problem.
- **Flaky suite z żywym demonem:** jeśli `pytest` daje ~100 failures — re-run (wyścig o `meta_data/*.jsonl`, nie realny błąd). Clean run = 5215 passed.

## Po restarcie demona (zawsze)
- `pgrep -f "python.*maria\.py" | wc -l` = 1 (zombie check).
- `journalctl -u maria | grep -iE "traceback|nameerror"` = pusto.
- `journalctl -u maria | grep "CapabilityRouter wired"` = nowy PID + "(14 capabilities)".
