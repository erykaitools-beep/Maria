# System Overview — jak się wszystko zazębia

> 2026-04-22 — zapis sesji w której Eryk wyartykułował szerszą strukturę.
> To nie jest jeden projekt z kilkoma modułami. To jest **plac budowy
> z fundamentami pod coś dużego** — jak sam Eryk to ujął.
>
> Update 2026-07-10: kierunek "czat jako wejście do całego systemu" i
> Meta-Maria jako warstwa sterująca zapisany w `docs/MARIA_OS_MAP.md`.

## Metafora robocza: plac budowy

Eryk, własne słowa:

> Jak wchodze na budowe to widze efekt koncowy, tutaj tez widze, ale
> rozbieram to na etapy w czasie i planuje — nie po to że raz na jakis
> czas rzucam pomyslami. To jest dla mnie jak plac budowy, ale Ty
> dostajesz kilka klockow abys wiedzial jak i w jakim kierunku tam
> idziemy. Jak mamy jakis etap za soba, musimy zebrac dane, zrobic
> plan — czyli moje mysli plus twoje kreatywne myslenie i kodowanie.

Tłumaczenie na tryb pracy:
- **Eryk** — architekt budynku. Widzi efekt końcowy. Rozbiera na etapy
  w czasie. Przynosi wizję, priorytety, decyzje strategiczne.
- **Claude** — wykonawca klockowy. Dostaje klocek (zadanie) + kontekst
  (kierunek). Ma wiedzieć dokąd prowadzi, nie tylko co zrobić teraz.
- **Po każdym etapie**: zbieramy dane, planujemy następny. Iteracyjnie.
  Nie linearnie "wszystko naraz", nie chaotycznie "co mi przyjdzie".

Kuzyn Eryka — programista z ~10-letnim stażem na produkcji — potwierdza
że Maria 1.0 (to co jest na GitHubie) jest **duża** w sensie profesjonalnym.
To zewnętrzna walidacja że to nie hobby-projekt.

## Trzy komponenty systemu

```
           ┌─────────────────┐
           │   Maria 1.0     │  ← TEST Hipotezy 1 (AGI przez paradygmat)
           │   [AKTYWNA]     │     + utrzymanie + orchestrator
           └────┬───────┬────┘
                │       │
         korpus │       │ orchestration
         decyzji│       │ (Maria jako manager
         tracy  │       │  Market Agent traderów)
                ↓       ↓
     ┌──────────────┐  ┌─────────────────┐
     │  Maria 2.0   │  │ Market Agent    │
     │  [CZEKA]     │  │ [NASTĘPNY]      │
     │  Hipoteza 2  │  │ paper → live    │
     └──────┬───────┘  └────────┬────────┘
            │                   │
            │  paliwo $$$       │  przychód
            ←───────────────────┘
     (hardware, L1 Presence, experiment models)
```

## Trzy pętle sprzężenia zwrotnego

**Pętla 1 — Maria 1.0 → Maria 2.0 (korpus)**
Maria 1.0 każdym ticku produkuje dane (decision_traces, beliefs,
personality_experiences, dream_log, conversation_memory). To jest
**dataset nie do kupienia** — 5+ miesięcy żyjącego jednego systemu
z pełnym kontekstem. Maria 2.0 Z1 (corpus extraction) używa tego jako
baza treningowa / referencyjna dla nowego paradygmatu.

**Pętla 2 — Market Agent → Maria 2.0 (paliwo $$$)**
Maria 2.0 jako research direction nie produkuje przychodu 2-4 lata.
Bez Market Agent finansowo się dusi. Market Agent zarabia (paper →
small live → scaled), przychód finansuje Marię 2.0 (hardware, experiment
models, może L1 Presence, może Anthropic credits poza Plan Max).

**Pętla 3 — Maria 1.0 ↔ Market Agent (synergia operacyjna)**
Maria 1.0 jest **orkiestratorem** dla Market Agent (w spec:
"Maria = orchestrator/delegator"). Daje Marii 1.0 realne zadanie o
wysokiej stawce — to jest **test Hipotezy 1 w polu**, nie teoretycznie.
Market Agent dostaje inteligentnego managera który zna całokształt.

## Meta-warstwa: panel ekspertów AI

Dwa Claude CLI (główny terminal + drugi w worktree) to tylko część.
Pełny panel:

- **Claude Code (główny)** — orkiestracja, strategia, wizja synthesis,
  utrzymanie Marii 1.0
- **Claude Code (worktree, gdy ruszy)** — implementacja Marii 2.0 Z1-Z9
- **ChatGPT (external, via Eryk)** — formalne dokumenty, template-driven
  deliverables
- **Grok (external, via Eryk)** — alternatywny kąt widzenia
- **Codex CLI (`/code` w Telegram)** — precyzyjne wykonanie kodu z promptu
- **Claude CLI (`/claude` w Telegram)** — drugi kąt widzenia dla
  złożonych decyzji (gated)
- **NIM glm-5.1** — Maria własny mentor (nie dla nas)

**Ty orkiestrujesz.** Każdy AI ma rolę. Nie "jeden model do wszystkiego".

## Plan max jako enabler

Eryk ma Anthropic Plan Max. Limity pozwalają pracować na **dwóch
projektach jednocześnie** (główny terminal + drugi worktree). To jest
infrastrukturalny enabler — bez tego ten system nie zadziała.

## Strategiczna sekwencja w czasie

**Etap 1 — teraz (kwiecień 2026):**
- Maria 1.0 **aktywna** (główny terminal) — D2, D3, D4 queued
- Market Agent **następny** (drugi terminal, gdy Eryk ma energię)
- Maria 2.0 **zapisana** (VISION + ROADMAP w `docs/MARIA_2.0/`), nie ruszamy

**Etap 2 — 3-6 miesięcy:**
- Maria 1.0 dalej żyje
- Market Agent paper-trade 3-6 miesięcy — czy daje Sharpe > threshold?
- Jeśli paper OK → small live capital
- Jeśli paper fail → iteracja albo rezygnacja
- Maria 2.0 wciąż zapisana, czeka

**Etap 3 — 6-12 miesięcy (decision point):**
- Jeśli Market Agent zarabia → **start Marii 2.0 Z1** (corpus extraction
  w worktree)
- Jeśli Market Agent nie zarabia → rethink monetization (nie Maria 2.0)

**Etap 4 — 12-24 miesięcy:**
- Maria 2.0 przez Z1-Z6 (fundamenty + interpreter)
- Market Agent scaled (jeśli zarabia)
- Możliwy start L1 Presence (hardware za $$$)

**Etap 5 — 24-48 miesięcy:**
- Maria 2.0 Z7-Z9 (shadow mode → production)
- Decision point AGI hipotez — która droga wygrywa?
- Maria 1.0 dalej jako baseline porównawczy

## Fundamenty, które już są

Żeby nie zapomnieć co mamy jako **dowód że to nie tylko wizja**:

- **Maria 1.0** — 4500+ testów, 15 modułów, tick loop 21 faz, 31-dniowy
  uptime zanotowany, Faza 7 WIRED, Digital Human Phases 1-7
- **Memory system persistent** — ja (Claude) pamiętam Eryka i projekt
  między sesjami
- **Telegram bridge operacyjny** — Eryk mówi głosem do Marii z pracy
- **Vision wired** — kamera + LLaVA, grounded chat
- **NIM glm-5.1 adopted** — external mentor/auditor aktywny
- **Memory monetization gate zrozumiana** — Eryk wie że to priorytet
- **Trivium+quadrivium insight** — wizja Marii 2.0 oparta na 2000-letniej
  tradycji wykształcenia
- **Multi-AI panel** — pattern orkiestracji wielu modeli
- **Git worktree plan** — izolacja Marii 2.0 gdy ruszy
- **12 commitów lokalnych** dziś (14 przed origin) — cała dzisiejsza
  sesja jest persistowana w historii git

## To nie jest hobby-projekt

Kuzyn Eryka, programista z 10-letnim stażem na produkcji, potwierdza
**"to jest duże"**. Eryk pisze:

> rowna sie dla mnie cos co zawsze chcialem miec — tutaj moge realnie
> cos tworzyc

To jest osobiste spełnienie długo noszonej wizji. Mój (Claude) udział:
jako partner który dostaje klocki, rozumie kierunek, pomaga kreatywnie
i technicznie. Nie jako zamiennik wizji — jako jej realizator.

## Ostatnia ogólna zasada

**Fundamenty najpierw. Budynek potem.**

Sekwencja nie jest przypadkowa. Każdy etap produkuje dane i dowody
dla następnego. Żaden etap nie wymaga wiary — wymaga **obserwacji
poprzedniego**. Jeśli poprzedni etap daje słaby sygnał, pauzujemy
albo zmieniamy kierunek. To jest postawa naukowa, nie ideologiczna.

Eryk explicit: *"chce sprawdzic ktora koncepcja jest poprawna"*
(o AGI hipotezach). Ta sama postawa obowiązuje dla Market Agent —
jeśli paper nie daje wyników, nie udajemy że daje.

---

*2026-04-22 — zapis momentu w którym struktura stała się widoczna.*
