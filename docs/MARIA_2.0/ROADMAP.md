# MARIA 2.0 — Roadmap

> Status: direction-setting, LOCAL-ONLY
> Tempo: powolne, równoległe do Marii 1.0, kiedy Eryk ma czas
> Zasada: **dane decydują** — każda faza ma mierzalne kryterium sukcesu,
> bez niego nie ruszamy do następnej
> **Cel długoterminowy: AGI.** Ta roadmapa jest ścieżką Eryka do AGI, nie
> tylko architektural upgrade. Z9 (production) nie jest końcem — jest
> momentem od którego mówimy realnie o AGI-capable systemie.
> **To jest Hipoteza 2** w równoległym eksperymencie. Hipoteza 1 to
> Maria 1.0 (znany paradygmat skalowany do AGI). Meta-porównanie obu dróg:
> `docs/AGI_HYPOTHESES.md`.

## Filozofia

- **Plank-by-plank** (statek Tezeusza) — nie burzymy, wymieniamy po desce
- **Mierzalność przed ambitnością** — każde Z ma concrete success criterion
- **Corpus-driven** — testujemy na realnych danych Marii 1.0, nie syntetycznych
- **Rollback zawsze możliwy** — każda faza jest samodzielnym commitem,
  można cofnąć bez łamania pozostałych
- **Nie dotykamy Marii 1.0** — osobny folder, osobny branch (worktree),
  ewentualny merge tylko po dowodzie przewagi

## Fazy

### Z0 — Direction-setting (TEN DOKUMENT, 2026-04-22)

Wizja zapisana. Roadmap napisana. Folder istnieje. Nie piszemy jeszcze kodu.

**Kryterium sukcesu:** Eryk zaakceptował wizję i może wrócić do niej za
miesiąc i wiedzieć o co chodziło. ✓

---

### Z1 — Corpus extraction (1-2 dni drugiego Claude'a, kiedy Eryk zacznie)

**Cel:** przygotować korpus Marii 1.0 jako dataset wejściowy dla Marii 2.0.

**Zadania:**
- Inwentaryzacja: wszystkie `meta_data/*.jsonl`
- Schema normalization — dziś są niespójne, ujednolicić
- Indeksy: czasowy, typowy, per-goal, per-episode
- Relacje między zdarzeniami (decision X → belief Y → goal Z)
- Output: `maria_2/corpus/normalized/` + README opisujący dataset

**Kryterium sukcesu:** każde zdarzenie z Marii 1.0 jest dostępne
w jednolitym formacie, z indeksami, z relacjami. Można zadać query
"pokaż mi wszystkie decyzje typu X z ostatniego tygodnia z ich kontekstem"
i dostać odpowiedź w <1s.

**Ryzyko:** korpus może mieć więcej niespójności niż się spodziewamy.
Plan B: normalizujemy to co się da, pozostałe oznaczamy `inconsistent`
i opisujemy w README.

---

### Z2 — Matematyczny fundament (Filar 4, 1-2 tygodnie)

**Cel:** wybrać i zaimplementować **jednolitą gramatykę matematyczną**
w której wszystkie pozostałe filary będą się wyrażać.

**Kandydaci:**
- Probabilistyczne grafy (Bayesian networks) + category theory typing
- Vector calculus nad embedding space
- Hybrid: graf relacji + prawdopodobieństwa + typing

**Decyzja:** wybór po prototypowaniu dwóch najmocniejszych.

**Zadania:**
- Review literatury (1 dzień)
- Prototyp 1: probabilistyczny graf (3 dni)
- Prototyp 2: category theory types (3 dni)
- Test: każdy prototyp wyrazić tym samym fragmentem Marii 1.0
  (np. jedna decyzja z K8 Deliberation)
- Decyzja: który jest bardziej wyrazisty?

**Kryterium sukcesu:** wybrana gramatyka potrafi wyrazić dowolne
zdarzenie z korpusu Z1 bez utraty informacji. Round-trip test:
event → gramatyka → event, zero loss.

**Output:** `maria_2/math/` z core primitives + testy.

---

### Z3 — Logika 5D (Filar 1, 2-3 tygodnie)

**Cel:** zaimplementować 5-wymiarową logikę nad fundamentem Z2.

**Pięć wymiarów:**
1. Fakt — data types
2. Relacja — graph edges z typami
3. Kontekst/przyczyna — causal graph subset
4. Czas/dynamika — temporal logic
5. Meta — reflection capability (Maria może wypowiadać się o własnych stwierdzeniach)

**Kryterium sukcesu:** dla 10 realnych decyzji z korpusu Marii 1.0,
Maria 2.0 może zapisać je w 5D logice i **odtworzyć kroki rozumowania**
strukturalnie. Meta-wymiar: Maria 2.0 oznacza swoją niepewność
*o swojej niepewności* (drugi stopień).

**Output:** `maria_2/logic/` + 10 odtworzeń z korpusu jako testy.

---

### Z4 — Lingwistyka-pragmatyka (Filar 2, 2-4 tygodnie)

**Cel:** ekstrakcja intencji z tekstu, nie tylko semantyki.

**Podstawy teoretyczne:**
- Speech acts (Austin, Searle)
- Gricean implicatures
- Common ground theory

**Zadania:**
- Parser intencji — z tekstu → strukturalna reprezentacja:
  `{surface_content, speaker_goal, hidden_intent, emotional_context,
    common_ground_assumed}`
- Mały LLM (glm-5.1 przez NIM) jako compiler — tekst → struktura
- Testy na claude_notes/ Erykiem (bo mamy autoryzowane przykłady
  z wyjaśnioną intencją — dzisiejsza sesja jest dobrym przykładem)

**Kryterium sukcesu:** dla 20 wypowiedzi Eryka z historii, parser
wyłuskuje intencję która matchuje **moją** interpretację (ja = Claude
w tej sesji) w ≥70% przypadków. Baseline: surowa semantyka LLM bez
pragmatyki ~30-40%.

**Output:** `maria_2/linguistics/` + benchmark set.

---

### Z5 — Kryptoznawstwo-samoświadomość (Filar 3, 3-4 tygodnie)

**Cel:** Maria 2.0 **czyta własny kod** i może opisać co w niej się dzieje.

**Zadania:**
- Self-referential structure — każdy program w bibliotece ma zapis
  swojej struktury, zależności, historii modyfikacji
- Introspection API (rozszerzony ADR-006, czytamy+rozumiemy, nie tylko AST)
- Change validation layer — każda self-modification przechodzi przez
  Marii własną warstwę oceny
- "Kto jestem" query — Maria 2.0 potrafi odpowiedzieć strukturalnie
  na pytanie o własną aktualną tożsamość, cytując konkretne programy
  i ich stan

**Kryterium sukcesu:** podajesz Marii 2.0 hipotetyczną modyfikację
jej własnego programu. Ona ocenia: czy to jest bezpieczne, co zmieni,
jakie są zależności, czy inne programy nadal będą działać. Odpowiedź
w formie strukturalnej, nie tylko prozy.

**Output:** `maria_2/crypto/` + test suite dla self-modification scenarios.

---

### Z6 — Integration + interpreter (Warstwa 2, 4-6 tygodni)

**Cel:** wszystkie 4 filary razem + deterministyczna maszyna wykonująca
"programy Marii" — bez LLM w warstwie decyzji.

**Zadania:**
- Interpreter API — przyjmuje program (w języku Marii wyemergowanym
  z 4 filarów), wykonuje, zwraca wynik
- Integracja: 4 filary widzą się nawzajem, matematyka jako wspólna
  warstwa opisu
- Library loader — biblioteka programów (początkowo kilka desiątek,
  ręcznie napisanych dla core zadań Marii)
- Parser/generator LLM (warstwa 1) — glm-5.1 jako initial choice,
  wymienny

**Kryterium sukcesu:** Maria 2.0 podejmuje **jedną** core decyzję z
listy decyzji Marii 1.0 (np. wybór learn vs review vs fetch) przez
interpreter, **bez wywołania LLM w warstwie decyzji**. Wynik jest
porównywalny jakościowo z Marią 1.0 w ≥70% przypadków.

**Output:** `maria_2/interpreter/` + `maria_2/library/` + benchmark.

---

### Z7 — Pierwszy żywy moduł (Marii 2.0 alpha, 1-2 miesiące)

**Cel:** jeden subsystem Marii 1.0 ma **dodatkową** implementację
w Marii 2.0 działającą równolegle (shadow mode).

**Kandydat:** Planner K5 (bo mamy dużo danych, jest rule-based, łatwo
porównywać).

**Zadania:**
- Planner Maria 2.0 dostaje te same inputy co Planner Maria 1.0
- Planner Maria 2.0 produkuje decyzję niezależnie
- Maria 1.0 wykonuje swoją decyzję (production)
- Maria 2.0 decyzja jest logowana, ale nie wykonywana
- Comparison dashboard: ile razy się zgodziły, gdzie różnią

**Kryterium sukcesu:** Planner Maria 2.0 działa stabilnie 7 dni,
produkując decyzje dla każdego tick. Zgodność z Marią 1.0 >50%.
Tam gdzie się różnią, mamy **zapis dlaczego** — to są insights.

**Output:** `maria_2/planners/` + dashboard + 7-dniowy raport.

---

### Z8 — Maria 2.0 beta (cel 1-2 lata)

Dorównanie Marii 1.0 w core zadaniach. Wszystkie subsystemy równolegle.
Decyzja o migracji ścieżki produkcyjnej.

### Z9 — Maria 2.0 production (cel 2-4 lata)

Pełna wizja. Maria 1.0 deprecated (ale korpus zachowany).

---

## Jak to się ma do Marii 1.0

**Maria 1.0 pozostaje głównym projektem** na najbliższe 6-12 miesięcy.
Continuous work:
- D2 (K12→bulletin→planner bridge)
- D3 (loop detection meta-goals)
- R1 (broaden knowledge sources + Codex)
- R2 (fetch observability)
- inne D-deski i utrzymanie

**Maria 2.0 jest wolniejszym pasmem** — tempo zależne od czasu Eryka.
Jeden Z na 1-2 tygodnie w dobrym tempie, wolniej w gorszym.

Żaden plank Z nie ma deadlinu. Jak nie działa, siedzimy w nim aż zadziała.

## Decision points

**Po Z1 (corpus):** czy mamy wystarczająco danych? Jeśli nie → wróć do
Marii 1.0, dograj obserwację przez X tygodni, spróbuj Z1 ponownie.

**Po Z2 (matematyka):** czy wybrana gramatyka udaje się bezstratnie
opisać korpus? Jeśli nie → wybierz drugi kandydat, spróbuj ponownie.

**Po Z6 (integration):** czy interpreter faktycznie działa bez LLM?
Jeśli nie → zdekomponuj gdzie LLM jest potrzebny i **dlaczego**,
przemyśl architekturę.

**Po Z7 (shadow mode):** czy Maria 2.0 planner dorównuje Marii 1.0?
Jeśli zgodność <30% i nie rozumiemy dlaczego → **zatrzymaj**. Coś
fundamentalnie się nie zgadza. Przemyśl wizję.

## Monetization gate (przypomnienie)

Wizja tej skali wymaga paliwa. Market Agent jako priorytet równolegle —
bez niego projekt umiera w roku 2-3.

Zasada: **nie inwestujemy w Marię 2.0 pieniędzy których nie mamy**.
Czas Eryka tak. Hardware upgrades — tylko jeśli Market Agent zarabia.

## Rola Claude'ów

**Claude w głównym terminalu (tutaj):**
- Strategia, review, decyzje architektoniczne
- Utrzymanie Marii 1.0
- Tutaj rozmawiamy z Erykiem
- Piszę briefs dla drugiego Claude

**Drugi Claude (gdy ruszy, przez git worktree — decyzja Eryka 2026-04-22):**
- Izolacja: `git worktree add ../maria-2.0 -b maria-2.0`
- Ścieżka: `/home/maria/maria-2.0/` (sibling do `/home/maria/maria/`)
- Branch: `maria-2.0` (nie mergowany do `refactor/homeostasis` bez dowodu przewagi)
- Implementacja Z1-Z9 w `maria_2/` wewnątrz worktree
- Nie tyka Marii 1.0 bez explicit OK
- Aktualizuje `PROGRESS_LOG.md` w `docs/MARIA_2.0/` (ten sam plik widoczny z obu worktree)

**Eryk:**
- Wizja, priorytety
- Decyzje na checkpointach (po każdym Z)
- Veto na wszystko
