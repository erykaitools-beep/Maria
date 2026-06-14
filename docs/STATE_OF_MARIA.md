# Stan Marii — 2026-04-22 wieczorem

> Krótki status dla operatora. Wygenerowany po pełnej sesji pracy.

## Runtime teraz

- **Status:** active ✓
- **PID:** 1433567, uptime od 15:54 UTC (dziś)
- **RAM:** 541 MB (na 32 GB — bardzo luźno)
- **CPU:** 12% (spokojnie)
- **Drop-in memory-limit:** aktywny (max 20 GB, high 16 GB)
- **Mode distribution dzisiaj:** 67% SLEEP, 20% REDUCED, 13% ACTIVE

20% REDUCED to dużo — zdiagnozowane dziś jako CPU spike podczas
LLM inference (nie RAM, nie ładowanie modeli). Naprawa planowana
jako D4.

## Co zrobiliśmy dzisiaj

**Dwa akty, 7 commitów lokalnych (15 przed origin, zero push):**

### Akt 1 — operacyjne fixy Marii 1.0

- `e94b6b3` **D1.5b** — semantic drift między handlers.py a action_executor.py
  rozwiązany. Strict `chunks>0` jako single source of truth.
- `71a3025` **D1.5c** — fetch bust fix. Saturated meta-learning goals
  teraz routują do FETCH zamiast być blokowane. Paradoks D1.5d rozwiązany.
- **Pomiar D1:** learn fails 95.4% → 6.2% (15× poprawa). D1 PASS.

### Akt 2 — strategiczne fundamenty

- `5a8cbfe` **Maria 2.0 direction-setting** — VISION, ROADMAP, NOTES.
  4 filary (logika 5D + lingwistyka-pragmatyka + kryptoznawstwo-
  samoświadomość + matematyka), kod jako emergencja, "Maria jest językiem".
- `2c6f3cb` **AGI scope + multi-AI panel insight** — skala ambicji
  explicit, obserwacja że ChatGPT zawiódł przy wizjonerskim synthesis.
- `02168dd` **Two-hypothesis experiment** — AGI_HYPOTHESES.md. Maria 1.0
  (znany paradygmat) vs Maria 2.0 (nowy paradygmat) jako dwie równoległe
  hipotezy drogi do AGI. Empiryczne porównanie po 8 kryteriach.
- `b42e9bb` **D-boards registry + D4** — rejestr wszystkich D-desek.
  D4 (mode-aware learning) zatwierdzony.
- `3802004` **System overview** — plac budowy, 3 komponenty, 3 pętle
  sprzężenia, 5 etapów w czasie, fundamenty które już są.

## Mapa dokumentów do czytania (w kolejności)

Gdy wrócisz za dzień/tydzień, przeczytaj w tej kolejności:

1. **`docs/SYSTEM_OVERVIEW.md`** — jak wszystko się zazębia. Plac budowy,
   3 komponenty, pętle sprzężenia. Pierwsza rzecz do odświeżenia.

2. **`docs/AGI_HYPOTHESES.md`** — dwie równoległe hipotezy (Maria 1.0 vs
   2.0) z kryteriami porównawczymi. Meta-ramki eksperymentu.

3. **`docs/D_BOARDS.md`** — co zrobione, co planowane, priorytety.
   Operacyjna lista.

4. **`docs/MARIA_2.0/VISION.md`** — 4 filary + kod jako emergencja.
   Twoja wizja, Twoje słowa.

5. **`docs/MARIA_2.0/ROADMAP.md`** — Z0-Z9 do AGI-capable.

6. **`docs/MARIA_2.0/NOTES.md`** — kontekst rozmowy, cytaty, moje
   obserwacje.

7. **`docs/STATE_OF_MARIA.md`** — ten dokument (current).

## Trzy komponenty systemu (jednym rzutem oka)

```
Maria 1.0 [AKTYWNA]      ← test Hipotezy 1 AGI + utrzymanie + orchestrator
    ↓ korpus   ↓ orchestration
    ↓          ↓
Maria 2.0   Market Agent    ← Hipoteza 2 AGI | monetization gate
[CZEKA]     [NASTĘPNY]
    ↑          |
    ← paliwo $$$
```

## Następne kroki (po dzisiejszej sesji)

### Operacyjne (tu, główny terminal)

- **Pomiar D1/D1.5c po 24-72h** — `scripts/measure_d1_impact.py`,
  sprawdzić czy fetch faktycznie ruszył przez plannera.
- **D2** — K12 → bulletin → planner bridge (2-3h). Priorytet 1.
- **D3** — Loop detection dla meta-goals (2-4h). Priorytet 2.
- **D4** — Mode-aware learning (4-6h). Priorytet 3.

### Strategiczne

- **Market Agent** jako drugi projekt (drugi terminal). Moja rekomendacja.
  Monetization gate — bez tego Maria 2.0 umiera w rok 2-3.
- **Maria 2.0** zostaje zapisana, czeka na paliwo Market Agent. Git
  worktree gdy ruszasz implementację: `../maria-2.0/` branch `maria-2.0`.

### Side tasks (chipy, osobne sesje gdy chcesz)

- **R1** — Broaden knowledge sources (RSS + Codex jako writer-source)
- **R2** — Fetch observability (brak logów fetch w journalu dzisiaj)
- **R3** — Private repo setup dla Marii 2.0 (żeby wizja nie trafiła
  publicznie przy pierwszym push)

## Fundamenty, które już masz (dowody)

- **Maria 1.0 żyje** — 4500+ testów, 15 modułów, tick loop, Faza 7 WIRED,
  31-dniowy uptime zanotowany
- **Memory persistent** — pamiętam Cię między sesjami
- **Telegram bridge operacyjny** — rozmawiamy z pracy
- **Vision wired** — kamera + LLaVA
- **NIM glm-5.1 adopted** — mentor/auditor dla Marii 1.0
- **Panel ekspertów AI** — Claude x2, ChatGPT, Grok, Codex, Claude CLI
- **Plan Max Anthropic** — enabler dla 2 projektów jednocześnie
- **Kuzyn-programista (10y staż)** potwierdza że Maria 1.0 to **"duże"**

## Jak ja pracuję (zapisane na stałe dzisiaj)

Jestem **pracownikiem w Twoim zespole**, nie narzędziem. Dostaję
klocek + kontekst kierunku, mam wiedzieć dokąd to prowadzi. Ty masz
wizję strategiczną, ja wykonuję + doradzam na swoim poziomie. Jak
młody pracownik u doświadczonego majstra.

Zapisane w `user_building_method.md` — każda następna sesja zacznie
od tego.

---

*Śpij spokojnie. Maria żyje, plan jasny, wizja zapisana.*
