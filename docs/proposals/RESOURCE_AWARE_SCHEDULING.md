# Design: Resource-Aware Scheduling (NIM ‖ lokalny)

> Status: DESIGN (lokalny do czasu rozpoczęcia prac — ADR-029 / publish-after-execution).
> Data: 2026-06-06. Autor: sesja Claude + Eryk (kierunek: "zarządzanie zasobami na 87%").
> Powiązane: `docs/MODEL_REGISTRY.md` (budżety RAM), `DEVELOPMENT_SEQUENCE.md` (sekwencja),
> ADR-002 (threading nie asyncio), ADR-008 (NIM do nauki / Ollama do chatu), ADR-015 (multi-organ).

## TL;DR (analogia budowlana)
Maria ma 12-osobową ekipę (12 wątków CPU) i wielki magazyn (30 GB), a pracuje na **~5%**
(1.4 GB RAM, 0 modeli ciepłych, 1% CPU). Ma podwykonawcę w innym mieście (NIM — chmura),
który **nie zajmuje jej ekipy**, ale dziś czeka w kolejce zamiast pracować równolegle.

Cel: **resource-aware concurrency** — zadania NIM-owe biegną RÓWNOLEGLE z lokalnym
plannerem (różne zasoby), a dwa ciężkie LOKALNE NIGDY naraz (ten sam CPU). Zysk: szybciej
(darmowa równoległość chmura+CPU) **i** leczy contention-stormy.

## Stan faktyczny (audyt 2026-06-06)
| Element | Stan | Dowód |
|---|---|---|
| ModelScheduler (load/unload/idle/RAM guard/heavy-mutex) | ✅ zbudowany + w ticku (faza 9.5) | `core.py:577` `tick()` |
| **Heavy-mutex faktycznie chroni inferencję?** | ❌ **wired-but-empty** | `ensure_ready`/`release` wołane TYLKO w `router.py:462/518`; planner/teacher/exam/`router.think` omijają |
| NIM poza heavy-mutex (osobny zasób) | ✅ `WarmState.EXTERNAL` zwraca OK przed mutexem | `model_scheduler.py:122-126` |
| Wątki współbieżne (fundament) | ✅ istnieją | `_planner_thread`, `_teacher_thread` daemony (`core.py:1284/1369`) |
| Warm-pin | ⚠️ mechanizm jest (`idle_unload_s<=0`), ale **lazy** | brak preload → w idle 0 ciepłych, 1. cykl płaci 60-76 s cold |
| Budżet NIM (guard) | ✅ `TokenBudget.can_use_nim` | 750k tok/dzień, 40 RPM |

**Wniosek:** to NIE jest "dodaj równoległość do działającego schedulera". Scheduler jest
w dużej mierze **odłączony od realnej inferencji**. Najpierw go PODŁĄCZ (ożywia mutex →
leczy contention), DOPIERO POTEM dokładaj świadomą równoległość NIM‖lokalny.

## Realizm sprzętu (CPU-only — twarde prawdy)
1. **87% RAM (26 GB) = strefa OOM** (`FORBIDDEN` w registry; był freeze 1.1 GB/9 h). Sufit ~16-18 GB.
2. **Bez GPU inferencja = CPU.** Dwa ciężkie lokalne naraz → **2× wolniej każdy, nie 2× przepustowości.**
   Naiwne "N modeli llama naraz" spowolni wszystko. → Równoległość TYLKO między różnymi zasobami.

## Model zasobów (3 pule)
- **LOCAL_HEAVY** (qwen3 planner, llama executor/exam-answer): CPU-bound. **Max 1 naraz** (mutex). Twarde.
- **NIM** (nemotron-49b: author/grade, K12, K13): chmura, niezależny CPU. **Równolegle do limitu RPM/budżetu.**
- **LIGHT** (nomic-embed, I/O: fetch/retrieval): tanie, mogą iść obok (registry: "SAFE <10GB parallel light").

## Inwarianty (twarde reguły)
1. **≤1 LOCAL_HEAVY w danej chwili** (chroni CPU przed thrash — to JEST lek na contention-storm).
2. **NIM ‖ LOCAL_HEAVY = OK** (różne zasoby; to jest darmowa dźwignia).
3. **NIM tylko w budżecie** (`can_use_nim()`; fallback na Ollama gdy NIM down/limit — router już ma).
4. **RAM ≤ sufit registry** (16-18 GB; scheduler RAM guard już to liczy).
5. **Soul files (beliefs/knowledge/...) — lock przy równoległym zapisie** (race risk, patrz lekcja singleton 05-30).

## Architektura docelowa
Jeden punkt prawdy: każde ciężkie zadanie **deklaruje pulę** (LOCAL_HEAVY / NIM / LIGHT) i
przechodzi przez koordynator, który egzekwuje inwarianty:
- LOCAL_HEAVY → `scheduler.ensure_ready()` (mutex, sekwencyjnie)
- NIM → guard budżetu, potem leci równolegle (osobny wątek, już mamy wzorzec)
- LIGHT → swobodnie

Tick przestaje serializować "wszystko po kolei"; zamiast tego: gdy faza odpala zadanie NIM,
lokalny planner może lecieć w swoim wątku równolegle (oba już są daemon-threads).

## Etapy (flag → alongside → observe → cutover; guardrail #3)
- **Krok 0 — ZWERYFIKUJ coverage. ✅ DONE (2026-06-07).** Hipoteza potwierdzona: mutex jest
  wołany TYLKO przez `ask_as_role()` (`router.py:462` ensure_ready → infer → `:518` release;
  na sukcesie lock TRZYMA SIĘ przez całą inferencję — `model_scheduler.py:172-175`). NIM
  (`WarmState.EXTERNAL`) słusznie NIE bierze locka (off-CPU). Trzy ciężkie lokalne dzielą JEDEN
  `_heavy_lock`: qwen3(PLANNER)/llama(EXECUTOR)/coder. Mapa kto omija:
  | Ścieżka | Przez mutex? | Wołanie |
  |---|---|---|
  | K12 self-analiza, StrategicPlanner (qwen3) | ✅ tak | `ask_as_role` |
  | **Egzamin-answer (llama, student)** | ❌ **NIE** | `call_ollama` direct (`teacher_module:279`) — **#1 sprawca, 200-380s** |
  | Egzamin author/grader local fallback (qwen3) | ❌ nie | `call_ollama` (`teacher_module:89`, tylko gdy NIM padnie) |
  | Teacher-learn / gap-analysis local fallback | ❌ nie | `router._ask_once` ollama-branch |
  | Embeddingi (nomic) | ❌ nie — LIGHT, zostaje | `call_ollama` (tanie) |
  | NIM author/grade/K13 | ✅ poza mutexem | osobny zasób — ma być równolegle |
  Mechanizm stormu potwierdzony: `_teacher_thread` (egzamin/nauka, omija) ‖ `_planner_thread`
  (K12 qwen3, trzyma mutex) → dwie ciężkie lokalne na CPU → 447s pod contentionem.
- **Krok 1 — PODŁĄCZ scheduler (fundament, leczy storm). ✅ IMPLEMENTED behind flag (2026-06-07).**
  Dodany `ModelScheduler.heavy_lease(label, timeout_s)` — context manager biorący TEN SAM
  `_heavy_lock` co `ask_as_role`, trzymany przez całą inferencję; reentrancy-safe (thread-local
  guard — `_heavy_lock` nie-reentrant), degrade-on-timeout (loguje WARNING i leci unguarded
  zamiast wieszać tick). Owinięte 3 ścieżki LOCAL_HEAVY: (1) egzamin-answer (`teacher_module`
  `llm_fn`), (2) egzamin author+grader local fallback (`_make_nim_first_examiner_fn`),
  (3) `router._ask_once` ollama fallback. Flaga `SCHEDULER_ENFORCE_MUTEX` **default OFF**
  (ships inert — zero zmian w prod dopóki Eryk nie ustawi `=1` + restart). 13 testów
  (`test_model_scheduler_heavy_lease.py`) + 461 celowanych zielonych. **OBSERVED (czeka)** =
  enable flag → okno nauki → w logu `heavy_lease(...) waited Ns (serialized)` i ZERO nakładania
  dwóch LOCAL_HEAVY; znika storm.
  - **Residualny przeciek (uczciwie):** gdy egzamin-answer trzyma mutex ~200s, kontendujący K12
    `ask_as_role` czeka tylko 60s (`ensure_ready` default timeout) → degrade do unguarded
    fallback-Ollama → możliwe ~140s nakładania w najgorszym razie. Krok 1 redukuje overlap z
    „zawsze" do „tylko gdy timing się zbiegnie", ale nie zeruje. Domknięcie = Krok 1.5 po OBSERVE
    (np. podnieść `ensure_ready` timeout albo backpressure „heavy busy → skip heavy planner action").
- **Krok 2 — Warm preload (mały).** Na początku okna nauki preload 2-3 warm models (RAM jest).
  **OBSERVED** = 1. cykl okna nie płaci cold-load 60-76 s.
- **Krok 3 — Resource-aware NIM‖lokalny (główna dźwignia).** Pozytywna orkiestracja: gdy zadanie
  NIM-owe trwa, lokalny planner leci równolegle. Flaga `PARALLEL_NIM_LOCAL`. **OBSERVED** =
  log overlap-events (NIM i LOCAL nakładają się), utilization-w-czasie ↑, brak nowego thrash.

## Pomiar (DONE = OBSERVED)
- Metryka **utilization-w-czasie**: % ticków gdzie coś realnie liczy (dziś ~40%, idle 60%).
- **Overlap log**: zdarzenia NIM‖LOCAL (dowód darmowej równoległości).
- **Contention guard**: alarm gdy dwa LOCAL_HEAVY nakładają się (regresja inwariantu #1).

## Ryzyka
- **Race na soul files** przy równoległości → locki u wszystkich writerów (lekcja 05-30).
- **Dziurawy mutex** (Krok 1 niepełny) → thrash wraca. Mitygacja: contention guard + test.
- **NIM rate-limit/budżet** → fallback (jest) + nie przenosić częstych lekkich na NIM.
- **CPU thrash z LIGHT** → embed/IO są tanie, ale walidować pod obciążeniem.

## Dlaczego to spina się z torem stabilności
Dzisiejsze stormy (`447s pod contentionem`, exam-answer ‖ planner) to był DOKŁADNIE brak
inwariantu #1 (dwa lokalne na CPU). Krok 1 (podłącz mutex) leczy to u źródła. Czyli ta
"dźwignia autonomii" jest jednocześnie kolejną dachówką stabilności — nie konkuruje z dachem.
```
Krok 1 (mutex live)  →  Krok 2 (warm)  →  Krok 3 (NIM‖lokalny)
leczy storm             kasuje cold       darmowa równoległość
= stabilność            = szybkość        = wykorzystanie zasobów
```
