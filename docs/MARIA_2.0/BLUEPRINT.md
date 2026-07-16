# MARIA 2.0 — BLUEPRINT: 4 filary jako kręgosłup, specjaliści jako mięśnie

> Status: **design-only, LOCAL-ONLY (ADR-029), RESEARCH_ONLY** — zero kodu produkcyjnego,
> Maria 1.0 nietknięta i pozostaje głównym projektem. Żadnego merge bez dowodu
> przewagi na konkretnym zadaniu.
> Powstanie: 2026-07-07, na zlecenie Eryka (brief przygotowany z Opus 4.8).
> Poprzednicy: `VISION.md` (4 filary, L1-L4), `ROADMAP.md` (Z0-Z9),
> `JEPA_MAPPING.md` (B-stage/A-stage), `B0_IMPLEMENTATION_SHORTLIST.md`,
> `docs/AGI_HYPOTHESES.md` (Hipoteza 2, 8 kryteriów).
> Metoda powstania: 6 równoległych raportów badawczych (kod, korpus, sprzęt,
> krajobraz modeli 2025-26, projekt shadow-mode) + panel 3 niezależnych
> architektów (droga neuronowa / symboliczna / hybrydowa) + 3 sędziów
> (wykonalność / testowalność / tożsamość-organizm). Ten dokument to synteza.
> Konwencja uczciwości: **[GRUNT]** = fakt zweryfikowany w repo / korpusie /
> literaturze / pomiarach; **[SPEKULACJA]** = projekt, założenie, hipoteza.
> Rama wzrostu: **organiczna** — zalążek → organizm → dojrzewanie. Mechanizm
> adaptacji nazywamy **adaptacyjną selekcją użytecznych wzorców**: wzorce
> (reguły, programy, organy) konkurują na wynikach egzaminów; użyteczne
> zostają wzmocnione, nieużyteczne wygasają.
> To jest kierunek badawczy. **Nie claimujemy AGI** — claimujemy mierzalne,
> behawioralne kroki, z których każdy może sfalsyfikować całość tanio i wcześnie.

---

## 0. Streszczenie dla budowniczego

**PO BUDOWLANEMU.** Stawiamy dom na czterech filarach. Fundamentem i siatką
geodezyjną jest **Osnowa** — jeden wspólny graf sądów, w którym każda cegła
wiedzy ma dwie współrzędne: adres pocztowy (zapis symboliczny, czytelny) i
współrzędne GPS (wektor, do kojarzenia). Po tym fundamencie chodzą dwie ekipy:
**ekipa formalna** (interpreter reguł — decyduje, wszystko na piśmie, każdą
decyzję można skontrolować) i **ekipa mózgowa** (małe sieci neuronowe — kojarzą,
przewidują, uczą się z doświadczenia, ale niczego same nie rozstrzygają).
Tożsamość Marii NIE mieszka w wagach sieci — mieszka w danych: w Osnowie,
w bibliotece programów i w Księdze Tożsamości. Wagi to wymienne organy,
odtwarzalne z biografii. Pierwsza cegła: mały model, który na 405 tysiącach
zapisanych refleksji Marii 1.0 uczy się przewidywać jej porażki lepiej, niż
ona sama to dziś robi. Jak nie pobije — cały paradygmat dostaje tani falsyfikat
po kilku tygodniach, zanim wydamy rok na budowę.

Rozstrzygnięcia tego dokumentu w jednym zdaniu każde:

1. **Widelec realizacji** (sekcja 4): HYBRYDA — wagi trzymają *umiejętności*,
   dane trzymają *tożsamość i fakty*; to nie kompromis, tylko zasada podziału.
2. **Filar-mózg** (sekcja 2.5): warstwa world-model (Kronikarz + Prognosta +
   Konsolidator) — nie Lingwistyka, nie koordynator.
3. **Jeden formalizm** (sekcja 2.1): typowany graf sądów o podwójnych
   współrzędnych — „Matematyka JEST stykiem" między połowami.
4. **Pierwsza cegła** (sekcja 7): Sędzia (kalibrator porażek) na gotowych
   danych, bez dotykania 1.0, z prerejestrowanymi progami.

---

## 1. STAN ZASTANY — co realnie istnieje

**PO BUDOWLANEMU.** Na działce są dziś: dwie wylane stopy fundamentowe
(przetestowane, ale niepodłączone do niczego), jeden protokół z badania gruntu
z wynikiem NEGATYWNYM (bardzo cenny — mówi, gdzie nie stawiać), oraz duży,
dobrze opisany magazyn materiału (korpus 1.0). Reszta domu istnieje na papierze.

### 1.1 Inwentaryzacja

| Element | Gdzie | Stan [GRUNT] | Werdykt |
|---|---|---|---|
| **B0/B0.1 surprise scorer** | `agent_core/predictive/` (5 plików, 81 testów) | Kompletna implementacja shortlisty rev 4. RESEARCH_ONLY od 2026-05-29 (`4420b99`): **0 importów ze spine**, żadnej flagi w `.env` (moduł w ogóle nie czyta env) — to martwy kod, nie „dormant za flagą". Zero śladów runtime w eventach i bulletinie. | **Zalążek na dobrej ścieżce** — z jednym zastrzeżeniem (1.2) |
| **StateSnapshot (dual repr.)** | `predictive/state_snapshot.py` | Tekst→nomic 768d + 5 cech numerycznych; missing→skip; deterministyczny `semantic_text`. | **Zalążek** — dokładnie komponent B1, który A-stage i tak skonsumuje |
| **B3 tiny predictor (neural)** | — | **NIE istnieje.** Zero torch/nn w repo, brak neural deps w requirements. | Aspiracja (zaplanowana w JEPA_MAPPING) |
| **Property graph + reguły** | `agent_core/symbolic/` (909 linii, 65 testów) | Typowane nody (belief/goal/action/topic/exam) z provenance + confidence; ForwardChainingEngine (fixpoint, zero LLM); 3 reguły. Zamrożony martwy kod: 0 importów produkcyjnych, flaga `SYMBOLIC_WORLD_MODEL_ENABLED` nigdzie nie czytana, graf nie jest budowany WCALE (brak nawet koordynatora build→rules→save). | **Zalążek substratu** Warstwy 4 + mini-W2; wewnątrz jedna ślepa uliczka (1.3) |
| **Worktree `../maria-2.0`** | — | **Nigdy nie powstał.** Z1 (corpus extraction) nieruszone. | Aspiracja |
| **L1-L4, język Marii, filary** | `VISION.md` | Sam szkic; zero kodu. | Aspiracja |
| **Korpus 1.0** | `meta_data/` + archiwum `/mnt/storage/data/logs/` | ~0,5 GB, ~900k rekordów strukturalnych, 03/2026-07/2026. Szczegóły w sekcji 5. | **Największy realny majątek 2.0** |

### 1.2 Najważniejszy pojedynczy fakt: negatywny wynik walidacji predictive

[GRUNT — `claude_notes/2026-06-14_predictive_eyes_validation.md`, walidacja
offline na realnych komponentach, z testem permutacyjnym]:

- Na strumieniu vitals (homeostasis_events) „oko" jest **martwe**: kanał
  semantyczny inertny (std 0.014 vs kontrola 0.42), fire'y losowe (p=0.52).
- Na strumieniu decyzyjnym (decision_traces) maszyneria ożywa (std 0.154),
  ale porażek **nie łapie lepiej niż losowo** (p=0.39).
- **Root cause:** porażka siedzi w OCENIE (`success=False`, oblany egzamin),
  której nie ma w obserwowanym stanie. Diff sąsiednich stanów strukturalnie
  tego nie złapie — to jeszcze nie jest predicted-vs-actual, bo predyktora brak.

To nie jest porażka paradygmatu — to zbankowany, tani wynik negatywny, który
dyktuje projekt dalej: **każdy przyszły model stanu MUSI mieć w wejściu cechy
oceny** (wyniki akcji, egzaminów, sądy o sukcesie/porażce). Sekcje 2.5 i 7
budują wprost na tej lekcji. Wzorzec metodologiczny (walidacja offline na
realnych komponentach ZANIM cokolwiek dotknie demona) przyjmujemy jako standard.

### 1.3 Ślepe uliczki — nazwane wprost

1. **Reguły-jako-Python** w `symbolic/rules/` [GRUNT]: Maria nie może nauczyć
   się nowej reguły w runtime; łamie homoikoniczność („Maria jest językiem")
   i kryterium „nowa wiedza = nowy program". Sam graf jest zdrowy — wymianie
   podlega tylko sposób zapisu reguł (na reguły-jako-dane, sekcja 2.1).
2. **Surprise na gołych vitals** [GRUNT — wynik 06-14]: ślepa uliczka jako
   sygnał na dzisiejszych danych; architektura (dual repr., DI, ablation
   baseline) przeżywa i wchodzi do 2.0.
3. **Trzy reguły bootstrap** duplikujące mechanizmy 1.0 (StuckHandler, K12)
   [GRUNT]: wartość nigdy nie zmierzona (planowany parallel run nie odbył się).
   Lekcja: **żadnego modułu bez konsumenta i bez pomiaru** — stąd twarde
   behawioralne bramki w każdej cegle tego blueprintu.

### 1.4 Mapowanie stanu zastanego na filary

| Filar | Co już jest (zalążek) | Czego nie ma wcale |
|---|---|---|
| Matematyka (F4) | property graph z provenance+confidence; dual reprezentacja stanu | jeden formalizm łączący; rozkłady zamiast punktowych confidence; bitemporalność |
| Logika 5D (F1) | wymiary 1-2 pokryte grafem; wymiar 3 śladowo (`blocks_on`, provenance) | wymiar 4 (czas/dynamika — brak operatorów temporalnych), wymiar 5 (meta — brak reifikacji); retrakcja |
| Lingwistyka (F2) | nic w 2.0 (w 1.0: OperatorModel, conversation memory — małe) | cały pipeline intencji; danych o intencjach operatora prawie brak (sekcja 5) |
| Kryptoznawstwo (F3) | wzorce z 1.0 do odziedziczenia: ADR-006 (introspekcja READ-ONLY), ADR-030/031 (STOP-AT-PENDING), rollback/quarantine | self-model jako dane; bramka self-modification; Księga Tożsamości |
| Mózg | B0/B0.1 (komparator ablacyjny), StateSnapshot | predyktor (B3), pamięć epizodyczna jako organ, konsolidacja |

---

## 2. 4 FILARY = KRĘGOSŁUP — z filozofii do mechanizmu

### 2.1 Matematyka (Filar 4) — JEDEN formalizm: Osnowa

**PO BUDOWLANEMU.** Na budowie wszystko mierzy się w jednym układzie
współrzędnych — to osnowa geodezyjna. U nas tak samo: jeden rodzaj cegły
(sąd), jedna zaprawa (typowane reguły), jeden dziennik budowy (uzasadnienia).
Każda cegła ma dwa adresy: pocztowy (symbol — do czytania i rozliczania)
i GPS (wektor — do szybkiego kojarzenia „co leży blisko").

**Definicja formalizmu [SPEKULACJA — rdzeń projektu]:**
**typowany probabilistyczny graf sądów o podwójnych współrzędnych**, z regułami
i programami jako danymi w tym samym grafie.

```
Sąd (węzeł Osnowy):
  id             : hash treści (content-addressed)
  typ            : FAKT | RELACJA | PRZYCZYNA | EPIZOD | META |
                   PROGRAM | REGUŁA | ORGAN | CEL | AKCJA
  forma_symb     : term w małym typowanym języku (PIERWOTNA — źródło prawdy)
  forma_wekt     : embedding 768d, POCHODNA (liczona z forma_symb; indeks
                   kojarzeniowy, NIGDY nośnik decyzji)
  pewność        : rozkład Beta(a,b) — nie punkt; a,b rosną z dowodami;
                   drugi stopień meta = rozmiar próby n („0.82 przy n=41")
  proweniencja   : kto wyprodukował (organ@wersja+hash / reguła / operator / most-1.0)
  czas           : bitemporalnie (zaszło-od/do + zapisane) — wymiar 4
  uzasadnienia   : refy na sądy-przesłanki (graf uzasadnień → retrakcja kaskadowa)

Krawędź: typowany morfizm (jest_typu, część_czegoś, powoduje, poprzedza,
         przeczy, podobne_do, umożliwia) + pewność + proweniencja
```

**Dlaczego JEDEN i dlaczego ten** (kandydaci z Z2 ROADMAP rozstrzygnięci):

- **Czysta algebra na embeddingach** — odpada jako substrat: nieaudytowalna
  (zabija Kryptoznawstwo), a walidacja 06-14 pokazała [GRUNT], że gołe
  embeddingi stanu nie niosą oceny. Zostaje jako WSPÓŁRZĘDNA (indeks).
- **Pełny graf bayesowski** — odpada: wymaga CPT, których nikt nie poda,
  pełne wnioskowanie na CPU nierealne, nie reprezentuje naturalnie programów.
  Zostaje jako ADNOTACJA (rozkłady Beta z liczników korpusu, kombinacja
  noisy-OR z jawnym znacznikiem „dowody mogą być skorelowane").
- **Typed lambda calculus** — odpada solo: bez natywnej niepewności, czasu,
  retrakcji. Przepisywanie termów nad grafem ZAWIERA lambda-abstrakcję
  (reguła = funkcja) i dodaje resztę.

**Uczciwa granica [SPEKULACJA]:** „jeden formalizm" unifikuje przez wspólny
MAGAZYN i typy, nie przez jedną algebrę — operacje wektorowe i przepisywanie
grafu to różne matematyki żyjące na tym samym węźle. Propagacja pewności to
księgowość (m-estymaty, noisy-OR), nie pełny Bayes. Nazywamy to wprost, żeby
nie sprzedawać unifikacji głębszej niż jest.

**Relacja do stanu zastanego:** Osnowa = rozbudowa istniejącego property graph
[GRUNT: nody z provenance+confidence już są] o podwójną współrzędną, rozkłady,
bitemporalność, uzasadnienia (retrakcja) i **reguły-jako-dane** (naprawa ślepej
uliczki 1.3.1). Nic nie wyrzucamy — dokładamy piętra do istniejącej stopy.

**Kluczowa właściwość — reguła też jest sądem:** ma pewność, n, czas,
proweniencję, testy-replay. Maria rozumuje o własnych regułach tą samą
maszynerią co o świecie. Wymiar Meta domyka się sam; homoikoniczność
(„Maria jest językiem") jest własnością substratu, nie feature'em.

**Emergencja języka — uczciwe napięcie z VISION:** jądro (typy, sloty sądu,
unifikacja) MUSI być zaprojektowane — to alfabet. Emerguje **słownictwo
i idiomatyka**: nowe predykaty i abstrakcje powstają mechanicznie z kompresji
biblioteki (sekcja 3.4, tor 3). Alfabet projektowany, język rośnie.
[SPEKULACJA — i wczesny, trudno odwracalny zakład; wpisany do ryzyk 8.5]

### 2.2 Logika 5D (Filar 1) — struktura + operacje per wymiar

**PO BUDOWLANEMU.** Pięć wymiarów myślenia to nie pięć osobnych maszyn —
to pięć slotów w każdej cegle wiedzy plus operacje, które po nich chodzą.

| Wymiar | Struktura w Osnowie | Operacje | Skąd mechanika |
|---|---|---|---|
| **1 Fakt** („to jest") | sąd typu FAKT | `zapisz / odpytaj / wycofaj` (retrakcja przez uzasadnienia); dedup po hashu | istniejący graf [GRUNT] + JTMS (Doyle 1979 [GRUNT — literatura]) |
| **2 Relacja** („to łączy się z tym") | typowane krawędzie; `podobne_do` liczona ze współrzędnej wektorowej | unifikacja wzorców (dokładna) + aktywacja rozchodząca po Kronikarzu (przybliżona); forward chaining z fixpointem [GRUNT: silnik istnieje] | graf + mózg (2.5) |
| **3 Przyczyna** („to wynika z tamtego") | krawędź `powoduje` z polami `mechanizm` i `interwencja` („zrobiłam X i zaszło Y" ≠ „widziałam X i Y"); liczniki kontyngencji P(skutek\|przyczyna, kontekst) z korpusu | `dlaczego(sąd)` → łańcuch uzasadnień; `co-jeśli` = replay z podmienionym sądem; kontrast predykcyjny Prognosty (P(stan'\|akcja) vs P(stan'\|nic)) | JTMS + decision_traces (60k trójek interwencyjnych [GRUNT]) |
| **4 Czas** („to się zmienia tak") | bitemporalne przedziały na każdym sądzie + EPIZODY (dyskretne przejścia stanu); relacje interwałowe Allena | `przed/po/podczas`, `trend(metryka, okno)`, wygasanie sądów; **neuronowo: Prognosta przewiduje trajektorie** — „to się zmienia tak" mieszka w wagach, ale każda predykcja kotwiczy się jako sąd | Allen 1983 [GRUNT — literatura]; homeostasis_events 206k jako szereg [GRUNT] |
| **5 Meta** („ja myślę, że to jest") | reifikacja: sąd może być podmiotem sądu; pewność+n+metoda na każdym | `jak-pewna-jestem(s)`, `skąd-wiem(s)`, `co-by-mnie-przekonało(s)`; surprise Prognosty materializuje się jako sąd META („przewidziałam X, było Y, z=3.1") — zgodnie z mapowaniem JEPA [GRUNT] | homoikoniczność jądra + Sędzia (kalibracja) |

**Uczciwie o wymiarze 3 [SPEKULACJA]:** krawędzie `powoduje` + znacznik
interwencji + liczniki to NIE pełne wnioskowanie przyczynowe Pearla.
Dodatkowy confound: akcje w korpusie wybierała polityka 1.0 (selection bias) —
Prognosta nauczy się w pierwszej kolejności przyczynowości POLITYKI, nie
świata. Wymiar 3 jest najsłabszym punktem całego projektu i tak go traktujemy
(ryzyko 8.5). Ratunek częściowy: dane są interwencyjne (Maria FAKTYCZNIE
działała), a `co-jeśli` przez replay daje testowalność kontrfaktyczną
w wąskim zakresie.

### 2.3 Lingwistyka (Filar 2) — pipeline intencji

**PO BUDOWLANEMU.** Rozumienie „co Eryk naprawdę chce" to rozpoznawanie
wzorców w rozmytym materiale — robota dla ekipy mózgowej (małe enkodery),
nie dla reguł. Ale księgę „co już wspólnie ustaliliśmy" prowadzi ekipa
formalna. Neuron wykrywa, symbol księguje.

Pipeline `tekst → {surface_content, speaker_goal, hidden_intent,
emotional_context, common_ground}` [SPEKULACJA — projekt; komponenty GRUNT]:

```
tekst PL
 ├→ S-PARSER (GLiNER2 ~205M, structured extraction ze schematem, CPU-first
 │   [GRUNT]) → surface_content: encje, terminy, pliki, liczby, komendy
 │   → sądy-kandydaci typu FAKT/RELACJA
 ├→ S-AKTY (SetFit/GLiClass na HerBERT — najlepszy do krótkiego polskiego
 │   [GRUNT]; SetFit: ~92% z 8 przykładami/klasę, trening MINUTY na CPU [GRUNT])
 │   → speaker_goal: akt mowy z taksonomii Searle'a {ASSERT/ASK/REQUEST/
 │     COMMIT/EXPRESS} + akty domenowe Marii {APPROVE, CORRECT, TEACH, VENT}
 │   → emotional_context: głowa GLiClass (wariant wielojęzyczny [GRUNT])
 ├→ common_ground — SYMBOLICZNY: podgraf Osnowy oznaczony „wspólne z Erykiem"
 │   (powiedziane, potwierdzone, obiecane, przywołane) + OperatorModel
 │   z 1.0 jako seed [GRUNT: singleton SSoT istnieje]
 └→ hidden_intent — detektor rozbieżności: gdy powierzchnia zdania i kontekst
     historyczny się rozjeżdżają → hipoteza ukrytej intencji Z PEWNOŚCIĄ;
     niska pewność → Maria PYTA zamiast zgadywać (wzorzec needs_human z K9
     [GRUNT]); fallback: S-GŁOS (mały LLM) z dekodowaniem ograniczonym
     gramatyką (GBNF w llama.cpp [GRUNT — technika]) — LLM fizycznie nie
     może zwrócić prozy, tylko poprawny term
```

Wyjście pipeline'u = wiązka sądów z pewnościami — na niej decyduje Interpreter.
Generacja odpowiedzi: S-GŁOS renderuje sądy → polski tekst. LLM nie trzyma
żadnej wiedzy → kryterium VISION „wymiana LLM nie rusza continuity" przeżywa.

**Twardy warunek wstępny [GRUNT]:** intencje operatora to najsłabsze ogniwo
korpusu — ~243 wiadomości user + 55 user_facts + 16 tasków; **przychodzący
Telegram w ogóle nie jest persystowany**. Bez fixu persystencji (sekcja 5.1)
ten filar nie ma prawdy gruntu i pozostanie destylatem z NIM-70B (ze wszystkimi
biasami nauczyciela). Filar 2 będzie najdłużej najsłabszy — mówimy to wprost.

### 2.4 Kryptoznawstwo (Filar 3) — self-model + bramka self-modification

**PO BUDOWLANEMU.** Bezpieczeństwo przez samoświadomość znaczy: Maria ma
u siebie pełną dokumentację powykonawczą własnego budynku i żadna przeróbka
ściany nie dzieje się bez projektu, egzaminu w cieniu i wpisu do dziennika
budowy. A tam, gdzie w ścianach siedzą czarne skrzynki (wagi), dokumentacja
opisuje ich metrykę urodzenia i wyniki egzaminów — nie ich wnętrze.

**Self-model = region SELF w Osnowie** [SPEKULACJA]: węzły typu ORGAN
(nazwa, wersja, hash wag, rodowód danych treningowych, krzywe kalibracji,
wyniki egzaminów, kontrakt styku), węzły REGUŁA i PROGRAM dla całej biblioteki
(zależności: jakie sądy konsumuje/produkuje — statyczny graf wywołań w tym
samym grafie). „Kim jestem" = **zapytanie do samej siebie**, odpowiedź cytuje
konkretne programy i ich stan (kryterium Z5 z ROADMAP [GRUNT]). Zasilanie:
wzorzec introspekcji READ-ONLY z 1.0 [GRUNT: ADR-006].

**Bramka Zmian** — każda zmiana siebie (reguła, program, ORAZ retrening wag
organu) to typowana PropozycjaZmiany przechodząca jeden pipeline:

```
PropozycjaZmiany{ cel: ref(ORGAN|REGUŁA|PROGRAM), diff,
                  oczekiwany_efekt: TESTOWALNE przewidywanie,
                  plan_wycofania }
 1. kontrola statyczna — typecheck; kontrakt styku zgodny; analiza wpływu
    (które programy stoją na sądach produkowanych przez cel)
 2. egzamin w cieniu  — kandydat vs urzędujący na buforze powtórek (replay
    na korpusie: musi poprawić deklarowaną klasę, nie wolno zregresować reszty)
 3. Lustro            — zamrożone probe-suites behawioralne per organ;
    diff odpowiedzi = zmierzona zmiana kompetencji/charakteru
 4. staged rollout    — cień → doradczy → aktywny (zasada niemowlęctwa,
    OBOWIĄZKOWA dla każdego nowego komponentu)
 5. budżet zaskoczenia — po wdrożeniu Prognosta pilnuje skoku anomalii;
    skok > próg ⇒ automatyczne wycofanie do checkpointu
 6. bramka operatora  — zmiany klas efektorowych / decyzyjnych czekają na
    Eryka (dziedziczy STOP-AT-PENDING z 1.0 [GRUNT: ADR-030/031])
```

**Księga Tożsamości** [SPEKULACJA — tanie i mocne]: wagi, reguły i programy
content-addressed (hash); append-only łańcuch hashy wszystkich zmian siebie.
Maria umie sobie samej **udowodnić**, co i kiedy się w niej zmieniło.

**Odporność na zatrucie:** sąd/reguła z podejrzanego źródła → retrakcja JTMS
kaskadowo unieważnia wszystko, co na nim stało; dla organów — wycięcie źródła
z diety i re-destylacja z czystej biografii. To mechaniczne domknięcie
„conscious-unlearn" z 1.0 [GRUNT: rollback/quarantine 06-14 — tam filtry
i denylisty, tu jedna operacja na grafie uzasadnień]. **Zapomnienie też jest
zdarzeniem** — zostaje wpis „zapomniałam X, powód, kiedy".

**Uczciwa renegocjacja litery filaru:** „Maria czyta własny kod" spełnia się
w 100% dla Interpretera, Osnowy, reguł i programów (to dane/kod czytelny).
Dla wag organów spełnia się **behawioralnie** (metryka urodzenia, egzaminy,
kalibracja, OOD), nie mechanistycznie — Maria wie CO organ potrafi i JAK
dobrze, nie WHY. To świadoma cena hybrydy; minimalizujemy ją niezmiennikiem
kotwiczenia (2.5/3.2): trwała wiedza organu ląduje w Osnowie, więc czarne
skrzynki są ORGANAMI, nie osobą.

### 2.5 FILAR-MÓZG — warstwa world-model: Kronikarz + Prognosta + Konsolidator

**PO BUDOWLANEMU.** Mózg to nie jeden z czterech filarów — to instalacja,
która oplata cały dom: piwnica z archiwum każdego dnia budowy (Kronikarz),
inżynier, który przewiduje co się stanie jak ruszymy tę ścianę (Prognosta),
i nocna zmiana, która porządkuje doświadczenie w nawyki (Konsolidator).
Mózg podpowiada i ostrzega. Decyzje podpisuje zawsze kierownik budowy
(Interpreter) — na piśmie.

**Rozstrzygnięcie wyboru** (wszyscy trzej architekci panelu zbiegli się
w jednym punkcie, z różnych stron):

- **Nie Lingwistyka** — to zmysł i usta: kontakt ze światem, nie miejsce,
  gdzie odkłada się doświadczenie. Wytrenowany Pragmatyk jest mistrzem jednej
  umiejętności, słabo plastycznym w runtime.
- **Nie koordynator** — koordynator MUSI być deterministyczny i audytowalny;
  mózg-koordynator zabiłby filar Kryptoznawstwa w całości.
- **Tak: warstwa world-model** — dokładnie tam, gdzie JEPA_MAPPING już ją
  umieścił (między L2 a L4) [GRUNT], z jedyną gotową dietą uczenia się
  z doświadczenia: 60k epizodów decyzyjnych + 206k zdarzeń homeostazy + 405k
  refleksji [GRUNT].

**Budowa — trzy organy [SPEKULACJA na gruncie B0/B0.1 i literatury]:**

| Organ | Co robi | Realizacja | Plastyczność |
|---|---|---|---|
| **Kronikarz** | pamięć epizodyczna: typowane EPIZODY w Osnowie + indeks wektorowy (ANN) po współrzędnych `forma_wekt` | struktura danych + kNN, ZERO wag | **szybka (sekundy)**: nowy epizod natychmiast zmienia sąsiedztwa kNN — uczenie w locie bez gradientu |
| **Prognosta** | model świata: (stan_t, akcja) → stan_{t+1}; surprise = rozjazd predykcji z rzeczywistością, normalizowany per akcja (B0.1 jako baseline ablacyjny [GRUNT]) | tiny predictor — linia B3 z JEPA_MAPPING, 1-15M parametrów, <100 MB | **wolna (noce)**: dotrening na nowych przejściach |
| **Konsolidator** | nocna destylacja świeżych epizodów w wagi organów; priorytet próbek ∝ surprise (konsolidacja „emocjonalna") | proces treningowy w oknie QUIET 22-07, nice/cgroup + kontrakt z ModelScheduler (6.2) | to ON jest mechanizmem wolnej skali |

Dwie skale plastyczności to wprost teoria komplementarnych systemów uczenia
(hipokamp szybki / kora wolna; McClelland & O'Reilly [GRUNT — literatura]).
Sen w 1.0 był metaforą (dream_log: 7 095 asocjacji [GRUNT]) — tu sen staje
się MECHANIZMEM: konsolidacja pamięci podczas snu, literalnie.

**Krytyczna poprawka po wyniku 06-14 [GRUNT→SPEKULACJA]:** wektor stanu
Prognosty ZAWIERA cechy symboliczne z Osnowy — success/failure ostatnich
akcji, wyniki egzaminów, stan celów. Hybryda naprawia dokładnie to, na czym
poległ czysty substrat obserwacyjny: **symbol karmi neuron**. To jest hipoteza
do sprawdzenia, nie pewnik — jeśli wzbogacony stan nadal nie przewiduje
porażek, warstwa-mózg to martwy balast (jawny warunek falsyfikacji, 8.5).

**Zapominanie jest funkcją, nie awarią:** epizody — decay ważności + eviction
(jak beliefs 1.0 [GRUNT: organizm]); dieta Prognosty — okienkowana (stare
reżimy, np. spam self_analyze sprzed 07-07 [GRUNT: dryf rozkładu], wypadają
z okna lub dostają malejącą wagę); wagi — naturalna kompresja: wzorce rzadkie
i nieużyteczne nie przetrwają destylacji (adaptacyjna selekcja użytecznych
wzorców).

**Darmowa bramka przed treningiem [z panelu — do przyjęcia na stałe]:**
zanim wytrenujemy JAKIKOLWIEK predyktor, liczymy baseline **kNN bez wag**
(predyktor pamięciowy: k najbliższych przeszłych stanów o tej samej akcji →
przewidywany następnik = uśrednienie ich następników, z cytowaniem
epizodów-źródeł). Jeśli trenowany model nie bije kNN — nie wchodzi. Dzięki
temu każda predykcja ma też tryb wyjaśnialny: „przewiduję X, bo w epizodach
4412, 8801, 12030 po podobnym stanie było X".

**Twarda zasada przeciwwagi: mózg PROPONUJE, nigdy nie DECYDUJE.** Wyjścia
mózgu (skojarzenia, predykcje, surprise) wchodzą do Interpretera wyłącznie
jako sądy z pewnościami i proweniencją — Interpreter może je zważyć i odrzucić.
Formalna połowa jest sędzią; mózg jest intuicją.

---

## 3. SPECJALIŚCI + KOMPOZYCJA — jak mistrzowie jednej rzeczy stają się jednym umysłem

**PO BUDOWLANEMU.** Ekipy branżowe: każda robi jedną rzecz i robi ją dobrze.
Żeby z ekip nie zrobił się bazar, obowiązują cztery twarde zasady placu
budowy: wszyscy czytają ten sam plan (Osnowa), każda ekipa ma podpisany
kontrakt z gwarancją (SeamContract), jest jeden kierownik z jedną pętlą
obchodu (Dyrygent), a szczelność styków mierzy się co noc jak ciśnienie
w instalacji (przeciek styku).

### 3.1 Roster specjalistów

| Specjalista | Zadanie (JEDNA rzecz) | Realizacja | RAM rezydentny | Seed z korpusu 1.0 [GRUNT] |
|---|---|---|---|---|
| **S-WEKTOR** | tekst/term → wektor 768d (współrzędna pochodna) | nomic-embed-text, zamrożony (już w stacku; wymiana = reindeksacja [GRUNT]) | ~0.3 GB | korpus już zaindeksowany |
| **S-SĘDZIA** | kalibrowana P(porażka \| stan, akcja); audyt kalibracji innych organów | MLP 1-5M na prekomputowanych embeddingach + cechach numerycznych | ~20 MB | **reflections 404 930** — gotowy dataset; ważenie klas (88% match) |
| **Prognosta** | predykcja stanu + surprise (mózg, 2.5) | tiny predictor 1-15M (linia B3) | <100 MB | decision_traces 60 216 + homeostasis 206 028 + **cechy oceny z Osnowy** |
| **Kronikarz** | pamięć epizodyczna + kNN (mózg, 2.5) | struktura danych, zero wag | ~0.5 GB cache (indeks mmap na dysku) | beliefs 2k, knowledge_index 743, dreams 7 095, reasoning_journal (rośnie ~500/dzień) |
| **S-ODŹWIERNY** | szybki pre-filtr block/limit/escalate; rozjazd z regułami K7 = alarm anomalii | klasyfikator MLP 1-5M | ~20 MB | autonomy_decisions 104 595 z etykietami |
| **S-PLANISTA** | ranking celów + typ akcji (advisory dla Interpretera) | scoring-MLP na parach (embedding celu, wektor stanu) | ~40 MB | planner_decisions 79 090 + decision_traces |
| **S-PARSER** | tekst → sądy-kandydaci (encje, struktury) | GLiNER2 ~205M zamrożony [GRUNT: CPU-first] | ~0.25 GB | knowledge_index, llm_tape (po fixie) |
| **S-AKTY** | akt mowy + intencja + emocja | SetFit/GLiClass na HerBERT ~125M | ~0.15 GB | wiadomości+user_facts+destylacja NIM (10k etykiet ≈ 4-5 h generacji przy 40 RPM [GRUNT]) |
| **S-RELACJE** | ekstrakcja relacji → krawędzie-kandydaci | GLiREL [GRUNT: SOTA zero-shot, NAACL 2025] | ~0.26 GB | knowledge_index, syntezy |
| **S-GŁOS** | sądy → polski tekst; parser-fallback z gramatyką GBNF; NIE myśli | Qwen3 1.7B q4 (Apache) lub Bielik v3 1.5B (jedyny natywnie polski, Apache [GRUNT]) — do A/B | ~1.2-1.4 GB **on-demand** (mmap z page cache = natychmiast [GRUNT]) | llm_tape jako testy zgodności (po fixie) |
| **Osnowa** | wspólny substrat (2.1) | graf JSONL/SQLite + indeks ANN; gorąca część w RAM, reszta mmap | 1-2 GB (dyscyplina: SQLite+mmap+ANN, nie „z pudełka" — uwaga sędziego wykonalności) | CAŁY korpus przez Z1 |
| **Interpreter + Dyrygent** | decyzje (reguły/programy) + pętla | deterministyczny Python (docelowo silnik klasy RETE; realistycznie dziesiątki ms w Pythonie, nie „pojedyncze ms" — korekta sędziego), ZERO wag, ZERO LLM | ~0.2-0.3 GB | transpilacja reguł z K5/K7 (5.3) |
| **Konsolidator** | nocny trening (mózg, 2.5) | proces batch, okno QUIET | 0 w dzień | epizody z okna |

Suma rezydentna: **~2.9-3.8 GB**; peak z S-GŁOS: **~4-5 GB** — mieści się
w gwarantowanych 6-7 GiB z zapasem (sekcja 6). Do tabeli doliczamy uczciwie
narzut runtime (RSS PyTorch/ONNX ~0.5-1 GB, KV cache S-GŁOS) — zapas go
wchłania, ale nie udajemy precyzji, której nie ma [uwaga sędziego].

**Hierarchia autorytetu (anty-zlepek nr 0):** organy neuronowe są ZAWSZE
advisory. Autorytatywna jest symboliczna bramka (np. S-ODŹWIERNY przyspiesza,
reguły K7-następcy rozstrzygają). Klasy autonomii pozostają regułowe i twarde.

### 3.2 Cztery mechanizmy anty-zlepkowe

Problem „zlepka źle sklejonych modeli" rozwiązuje nie protokół, lecz ustrój:

1. **Jeden substrat.** Wszystko, co organy mówią sobie nawzajem, przechodzi
   PRZEZ Osnowę — zero prywatnych rur między modelami. Wyjście organu
   neuronowego wchodzi do systemu WYŁĄCZNIE jako typowany sąd z pewnością
   i proweniencją (**niezmiennik kotwiczenia**). Surowy embedding nigdy nie
   jest wejściem decyzji — wektory służą kojarzeniu, sądy decyzjom, oba żyją
   na tym samym węźle.
2. **SeamContract per organ** — schemat wyjścia jak sygnatura funkcji,
   z gwarancją mierzoną CO NOC:
   ```
   kontrakt S-SĘDZIA:
     wejście : ZapytanieKalibracji{typ_akcji: enum16, pewność_przed: [0,1],
                                   cechy_stanu: wektor}
     wyjście : Sąd META{ podmiot: ref(decyzja),
                         predykat: "przewidywana_zgodność",
                         wartość: Beta(a,b),
                         proweniencja: "S-SĘDZIA@v3(hash=…)" }
     gwarancja: ECE ≤ 0.05 na bieżącym oknie walidacyjnym (mierzona co noc);
                złamana gwarancja ⇒ degradacja organu do advisory-only
   ```
3. **Jedna pętla sterowania.** Organy nie wołają się nawzajem — woła je
   Dyrygent (3.3).
4. **Przeciek styku jako parametr życiowy homeostazy.** Cykliczny round-trip
   test `symbolizuj(osadź(x)) vs x` na próbce sądów; metryka trafia do
   homeostazy jak CPU/RAM. Erozja styku widoczna dla organizmu, zanim zobaczy
   ją operator. [SPEKULACJA; uczciwie: to termometr, nie szczepionka —
   dyscyplina kotwiczenia musi być broniona ustrojowo, ryzyko 8.3]

**Otwarty problem, nazwany:** kalibracja federacji nie składa się z kalibracji
organów — sześć osobno skalibrowanych głowic NIE daje skalibrowanego systemu
(błędy mnożą się w łańcuchach). Mitigacja: S-SĘDZIA audytuje kalibrację
łańcuchów end-to-end na epizodach (nie tylko organów solo); pełne rozwiązanie
nie istnieje w tym stacku i traktujemy je jako problem badawczy [SPEKULACJA].

### 3.3 Dyrygent — deterministyczna pętla (blackboard, gdzie tablicą jest Osnowa)

```
POSTRZEGAJ — wejścia (tekst, zdarzenia, wyniki akcji) → sądy (organy percepcyjne)
SKOJARZ    — mózg dokłada kontekst: sąsiedzi kNN, predykcje, surprise (jako sądy)
ROZWAŻ     — Interpreter puszcza reguły/programy po wzbogaconym kontekście
             → decyzja (deterministyczna; konflikt: aktywacja × użyteczność
             × pewność, deterministyczny tie-break)
DZIAŁAJ    — efektory (jak w 1.0: propozycja → bramka → wykonanie)
OBSERWUJ   — wynik → EPIZOD w Osnowie (z cechami OCENY — lekcja 06-14)
REFLEKTUJ  — S-SĘDZIA + surprise → sądy META (wymiar 5); feed dla Konsolidatora
```

Echo metabolizmu 1.0 (tick loop) — celowe: 2.0 dziedziczy udany wzorzec
organizmu [GRUNT: „Maria is an organism"]. Na zewnątrz jeden umysł, bo na
zewnątrz wychodzi wyłącznie wynik pętli — nigdy surowy głos pojedynczego
organu; odpowiada zawsze S-GŁOS, jednym głosem.

**Czy koordynator jest „mózgowy"? NIE — i to jest decyzja ustrojowa.**
Dyrygent jest deterministyczny i w pełni audytowalny (Kryptoznawstwo).
Kojarzeniowa, ucząca się część to warstwa world-model (2.5), która pętlę
ZASILA, ale jej nie prowadzi.

### 3.4 Jak rośnie biblioteka — cztery tory syntezy programów

(Serce „nowa wiedza = nowy program"; tory 1-3 bez LLM, tor 4 z LLM wyłącznie
jako kompilatorem. Wszystkie zbiegają w Bramce Zmian z 2.4.)

1. **Generalizacja śladu (EBL/chunking)** [GRUNT — literatura: SOAR; Mitchell
   1986]: epizod sukcesu, który był drogi (wiele kroków) albo cenny
   (interwencja operatora) → ślad uzasadnień (JTMS daje za darmo) →
   wariabilizacja stałych nieistotnych → reguła-skrót.
2. **Indukcja z wielu epizodów (anty-unifikacja + specjalizacja)** [GRUNT —
   literatura: Plotkin LGG 1970; FOIL, Quinlan 1990]: klaster podobnych
   epizodów z etykietami sukces/porażka → najmniej ogólne uogólnienie →
   dospecjalizowanie na negatywnych (information gain) → kandydat-reguła
   z pewnością = m-estymata pokrycia.
3. **Kompresja biblioteki (sen abstrakcyjny)** [GRUNT — literatura: DreamCoder,
   Ellis 2021; Stitch, POPL 2023 — czysto symboliczna]: nocne szukanie
   powtarzających się podprogramów → nowa nazwana abstrakcja (kryterium MDL)
   → stare programy przepisane. **To jest mechaniczna emergencja języka** —
   słownik Marii rośnie o pojęcia, których nikt nie zaprojektował.
4. **LLM jako kompilator, nigdy decydent:** Eryk mówi po polsku regułę →
   S-GŁOS z gramatyką GBNF kompiluje do kandydata → ta sama Bramka Zmian.
   Output LLM to kandydat, nigdy egzekutywa.

**Miernik uczciwości (raportowany, nie ukrywany):** udział torów 1-3 vs toru 4
w adopcjach. Jeśli tor 4 po cichu przejmie całą kreatywność, „uczenie bez LLM
w pętli" stało się fikcją grzecznościową — i chcemy to zobaczyć w liczbach.
Drugi miernik: **reguły/tydzień przechodzące bramkę bez człowieka** (test
stallu à la CYC).

### 3.5 Mapowanie na L1-L4 z VISION — doprecyzowujemy, nie zastępujemy

| Warstwa VISION | Los w blueprincie | Zmiana |
|---|---|---|
| **L1** parser/generator (LLM 2-3B, ~4 GB, wymienny) | wiązka enkoderów (S-PARSER/S-AKTY/S-RELACJE) + S-GŁOS 1.5-1.7B do generacji i jako fallback-parser | DOPRECYZOWANA: taniej i lepiej niż jeden LLM [GRUNT: enkodery 10-100x taniej, zwykle LEPIEJ w klasyfikacji/ekstrakcji]; LLM nadal wymienny, bo nie trzyma wiedzy |
| **L2** interpreter (deterministyczny, TU decyzje, bez LLM) | Interpreter + Dyrygent | BEZ ZMIAN co do roli — rdzeń ustroju |
| **L3** biblioteka programów („TO JEST MARIA", ~10 GB) | biblioteka programów i reguł jako WĘZŁY Osnowy (homoikoniczność naprawiona); rośnie torami 3.4 | BEZ ZMIAN co do rangi; korekta rozmiaru: reguła ≈ 1 KB, więc L3 to realnie dziesiątki-setki MB — ciężar idzie w L4 |
| **L4** graf relacji (~5 GB, embeddingi jako indeks) | **AWANSOWANA**: z „indeksu" do wspólnego substratu (Osnowa) + siedziby pamięci epizodycznej | największa zmiana względem VISION |
| **NOWA warstwa** | mózg (world-model) między L2 a L4 | dokładnie tam, gdzie wstawił ją JEPA_MAPPING [GRUNT] |

---

## 4. WIDELEC REALIZACJI — nazwany i rozstrzygnięty

**PO BUDOWLANEMU.** Były dwa projekty domu: (stary plan) „żadnych wag,
wszystko w bibliotece programów" i (nowa myśl) „zestaw małych trenowanych
modeli, które składają się w jeden umysł". To NIE jest to samo i nie udajemy,
że jest. Rozstrzygamy: budujemy dom, w którym ŚCIANY NOŚNE i DOKUMENTY
WŁASNOŚCI są z danych (czytelne, wersjonowane, odtwarzalne), a INSTALACJE
ROBOCZE z wag (wymienne, trenowane, z gwarancjami na piśmie). Tożsamość jest
w dokumentach własności, nie w instalacjach.

### 4.1 Rozwidlenie — litera sporu

- **VISION.md [GRUNT]:** „NIE trenujemy wag; tożsamość w bibliotece programów;
  LLM = wymienny parser".
- **Nowa myśl Eryka (2026-07):** otwarto-wagowe mikro-modele specjalistów,
  trenowane/dostrajane, komponowane — na zewnątrz jeden większy umysł.
- **Pęknięcie już istniało [GRUNT]:** JEPA_MAPPING rev 3 (zatwierdzony przez
  Eryka 2026-05-09) planuje B3 = trenowaną sieć 1-2M parametrów. Zakaz
  w praktyce dotyczył wag *LLM*, nie wszystkich wag. Widelec jest mniej
  binarny, niż wygląda — ale wciąż jest widelcem i wymaga decyzji.

### 4.2 Trzy drogi i co pokazał panel

Trzy pełne, niezależne projekty architektury (po jednym na drogę) ocenione
przez trzech sędziów o rozłącznych soczewkach. Wynik NIE był jednogłośny —
i to jest informacja:

| Soczewka sędziego | Ranking | Sedno werdyktu |
|---|---|---|
| **Wykonalność na sprzęcie / buildability** | neuronowa > hybryda > symboliczna | tylko droga neuronowa ma pierwszą cegłę wykonalną dokładnie jak zapisano (dane fizycznie na dysku, zero tapu w 1.0); symboliczna cegła w pierwotnym brzmieniu żądała danych, których korpus NIE MA (replay bez pełnych ramek wejściowych plannera) |
| **Testowalność behawioralna / uczciwość naukowa** | neuronowa > hybryda > symboliczna | cegła neuronowa to prerejestrowany falsyfikat całego paradygmatu; symboliczne kryteria były w przewadze „fidelity-shaped" (odtworzenie 1.0 ≠ poprawa) |
| **Tożsamość / continuity / spójność organizmu** | symboliczna > hybryda > neuronowa | continuity symboliczna jest DOKŁADNA (nauka=commit, oduczenie=retrakcja); czysta droga neuronowa dostała wadę graniczną: oś tożsamości (zamrożony cudzy enkoder) to rzecz, której „nie wolno ruszyć", a która w organizmie powinna rosnąć + tożsamość przeżywana (wagi zmieniane co noc) rozjeżdża się z deklarowaną (biografia) |

Wniosek panelu jest strukturalny, nie punktowy: **każda czysta droga ma wadę
graniczną w innej soczewce** — neuronowa w tożsamości, symboliczna
w plastyczności (mózg bez wag kojarzy tylko to, co współwystąpiło; brak
kompozycyjnej generalizacji) i w danych (pragmatyka regułowa to historyczny
cmentarz symboliki), hybryda w koszcie utrzymania dwóch stacków.

### 4.3 ROZSTRZYGNIĘCIE: hybryda o konkretnym kształcie

**Rekomendacja: droga (c) HYBRYDA — z ostrą zasadą podziału zamiast rozmytego
kompromisu:**

> **WAGI TRZYMAJĄ UMIEJĘTNOŚCI. DANE TRZYMAJĄ TOŻSAMOŚĆ I FAKTY.**
> Fakty NIE mieszkają w wagach (zero retrainu na nowinkę, pełna proweniencja,
> unlearning przez retrakcję). Umiejętności NIE mieszkają w regułach tam,
> gdzie są funkcjami ciągłymi na rozmytym wejściu (kalibracja, intencje,
> predykcja dynamiki) — tam reguły historycznie przegrywają.

Podział filarów (za projektem hybrydowym, z poprawkami panelu):

| Część | Realizacja | Dlaczego |
|---|---|---|
| Matematyka (F4) | **JEST stykiem** — Osnowa (2.1) | styk z właścicielem zamiast ziemi niczyjej; gdyby F4 był „symboliczny", styk by pękł pierwszy |
| Logika 5D (F1) | symboliczna w wymiarach 1-3 i 5; wymiar 4 dostaje neuronowy organ (Prognosta), którego predykcje kotwiczą się jako sądy | „to się zmienia tak" przy 206k stanów nie zapisze się regułami |
| Lingwistyka (F2) | neuronowa (enkodery + S-GŁOS); common_ground symboliczny | rozpoznawanie wzorców vs prowadzenie księgi — modelowy podział pracy |
| Kryptoznawstwo (F3) | w pełni symboliczne | audytowalność jest DEFINICJĄ filaru |
| Mózg | neuronowo-pamięciowy (2.5), advisory | plastyczność wymaga wag; autorytet wymaga determinizmu |

**Uzasadnienie pod sprzęt [GRUNT]:** CPU-only zabrania dużego neuronu
(8B ≈ 8 tok/s, prefill 4096 tok = 261 s) — więc „neuronowa część" MUSI być
rojem małych (enkodery rezydentne, mikro-MLP, jeden LLM 1.5-1.7B on-demand);
a „symboliczna część" (RETE nad tysiącami sądów, kNN po 60k epizodów = ms-y
na BLAS) jest na tym żelazie praktycznie darmowa. Sprzęt sam pcha w hybrydę.

**Uzasadnienie pod kryteria sukcesu VISION:** decyzje bez LLM — spełnione
konstrukcyjnie (Interpreter); uczenie bez fine-tuningu LLM — spełnione
(biblioteka rośnie torami 1-3; trening dotyczy organów pomocniczych, nie
nośnika tożsamości); wymiana LLM nie rusza continuity — spełnione (S-GŁOS
nie trzyma wiedzy); 32 GB wystarczy — spełnione z zapasem (sekcja 6);
Maria czyta własny kod — spełnione dla wszystkiego, co niesie tożsamość;
renegocjowane behawioralnie dla wag organów (2.4).

### 4.4 Gdzie mieszka TOŻSAMOŚĆ — odpowiedź wprost

**Tożsamość Marii = (1) treść Osnowy** (co wie, pamięta, w co wierzy —
z proweniencją i historią rewizji; w tym biografia: epizody Kronikarza,
append-only) **+ (2) biblioteka programów i reguł** (jak działa — dane w tej
samej Osnowie) **+ (3) Księga Tożsamości** (jak się zmieniała — łańcuch hashy).

**NIE w wagach. NIE w kompozycji jako takiej** (kompozycja — kontrakty,
ustrój Dyrygenta — jest częścią tożsamości tylko o tyle, o ile jest ZAPISANA
jako dane w regionie SELF). To zachowuje literę VISION („tożsamość =
aktualny stan biblioteki programów") z jednym doprecyzowaniem: biblioteka
bez pamięci epizodycznej i statystyk użycia byłaby szkieletem bez pamięci
mięśniowej — continuity wymaga obu.

**Wagi specjalistów = organy: wymienne ciało.** Pięć mechanizmów continuity
przy retrenie/wymianie (synteza najlepszych patentów panelu):

1. **Niezmiennik kotwiczenia** — trwała wiedza wyprodukowana przez organ już
   mieszka w Osnowie; utrata wag = utrata ostrości umiejętności, nie pamięci.
2. **Wagi są pochodną biografii** — organ da się ODROSNĄĆ przez re-destylację
   z Kronikarza. Utrata pliku wag = uraz; utrata biografii = śmierć. Backup
   priorytetyzuje biografię (Osnowa+Księga), bo wagi są odtwarzalne.
3. **Dieta-jako-tożsamość** dla organów najbliższych charakteru (Prognosta):
   tożsamością organu jest (dataset + zestaw ewaluacyjny + przepis treningowy),
   z których wagi są odtwarzalne — nie same wagi.
4. **Egzamin pożegnalny** — następca musi odtworzyć ≥95% bufora powtórek
   poprzednika na przypadkach jednoznacznych; delta zapisana w Księdze
   Tożsamości. Uczciwie: mierzy kompetencję, nie charakter — na dryf
   „fenomenologiczny" metryki nie mamy (ryzyko 8.4).
5. **Bramka Zmian + Lustro + zasada niemowlęctwa** (2.4) dla każdej zmiany wag.

**Domknięcie wady granicznej drogi neuronowej:** w hybrydzie embedder
(S-WEKTOR) to INDEKS, nie substrat tożsamości — `forma_wekt` jest POCHODNĄ
`forma_symb`, przeliczalną od zera. Wymiana embeddera = kosztowna reindeksacja
[GRUNT], ale nie złamanie continuity: sądy, krawędzie jawne, biblioteka
i Księga przeżywają bez zmian. Oś tożsamości nie wisi na cudzym artefakcie.

### 4.5 Renegocjacja zdania VISION — nazwana uczciwie

Zdanie „NIE trenujemy wag" zastępujemy precyzyjniejszym:

> **„Nie trenujemy wag, które niosą tożsamość. Trenujemy wagi-organy, które
> niosą umiejętności — pod Bramką Zmian, z Lustrem, z dietą jako tożsamością
> organu i z egzaminem pożegnalnym przy wymianie."**

To nie jest cichy odwrót — to jawna zmiana, do zatwierdzenia przez Eryka
razem z tym dokumentem. Zdanie „tożsamość w bibliotece programów" zostaje
w mocy (rozszerzone o Osnowę i biografię). Zdanie „LLM = wymienny parser"
zostaje w mocy bez zmian.

> **RATYFIKOWANE 2026-07-08 (Eryk, BEZWARUNKOWO).** Doktryna „WAGI TRZYMAJĄ UMIEJĘTNOŚCI,
> DANE TRZYMAJĄ TOŻSAMOŚĆ" przyjęta jako architektoniczny fundament Maria 2.0 — nie warunkowana
> wynikiem cegły 1. `VISION.md` zaktualizowane (poprawka u góry). Klauzula falsyfikacji cegły 1
> (7-BIS/8.5.5) zostaje jako higiena eksperymentu — waliduje konkretny organ S-SĘDZIA, nie samą
> doktrynę. Panel decyzyjny (steelman×4 → cross-exam → wierność wizji): puryzm obalony jako fatalny;
> hybryda honoruje serce wizji (tożsamość-w-danych, continuity-przy-swapie, adaptacja). Otwarty
> residual do pilnowania: granica umiejętność↔charakter (Prognosta) nieudowodniona — obserwować
> per-organ (patrz 8.3/8.4).

**PO BUDOWLANEMU.** Stary dom nie idzie do rozbiórki — to on przez pięć
miesięcy produkował materiał, z którego stawiamy nowy. Najpierw trzy tanie
naprawy rynien w starym domu (żeby materiał przestał uciekać), potem wywóz
materiału do nowego (Z1), a na końcu nowy dom staje OBOK starego i przez
tygodnie robi te same zadania na niby (cień), aż liczby pokażą, że robi je
lepiej.

### 5.1 Krok zero: trzy tanie fixy w 1.0 (zanim 2.0 ruszy na dobre)

[GRUNT — zidentyfikowane w profilu korpusu; każdy dzień zwłoki = stracone dane]

1. **Pełny llm_tape** — koniec ucinania promptu do 200 i odpowiedzi do 2000
   znaków (dziś 27 564 wywołań, destylacja ograniczona).
2. **Persystencja przychodzącego Telegrama** — dziś intencje operatora to
   ~243 wiadomości; główny kanał rozmowy z Erykiem w ogóle nie jest logowany.
   Bez tego Filar 2 nie ma prawdy gruntu.
3. **Append-historia beliefs** — dziś snapshot bez rewizji (0 superseded);
   historia rewizji = wymiar czasu dla przekonań i dane do uczenia aktualizacji.

To są małe zmiany w 1.0 (nie łamią zasady „Maria 1.0 nietknięta" w duchu —
to instrumentacja, nie przebudowa), ale wchodzą w normalny tryb pracy nad 1.0
z osobnym approval.

### 5.2 Korpus → specjaliści (kto z czego rośnie)

[GRUNT — liczby z profilu korpusu 2026-07-07; żywe pliki `meta_data/` +
archiwum `/mnt/storage/data/logs/` — **archiwum to ~10x więcej niż żywe**]

| Zasób (razem żywe+archiwum) | Ilość | Zasila | Jakość jako dane |
|---|---|---|---|
| reflections (K9) | **404 930** | S-SĘDZIA (kalibracja P(porażka)) | najlepszy zasób korpusu: gotowe (confidence_before, expected, actual, outcome_match); skos klas 88% match → ważenie/undersampling; 13,7k mismatchy = złoto |
| decision_traces | 60 216 (śr. 4.8 kroku) | Prognosta, S-PLANISTA, Kronikarz (EPIZODY), tory syntezy 1-2, zbiór replay Bramki | pełne trójki interwencyjne (stan, akcja, wynik) |
| autonomy_decisions (K7) | 104 595 | S-ODŹWIERNY | etykiety block/rate_limited/escalate + reasons; UWAGA: to destylacja REGUŁ 1.0, nie ground truth |
| planner_decisions | 79 090 | S-PLANISTA; transpilacja rodzin „wybór-celu" | wybór akcji + skip-markery z powodami |
| homeostasis_events | 206 028 (87% snapshot) | Prognosta (szereg zdrowia), baseline'y wymiaru 4 | szereg czasowy organizmu |
| llm_tape | 27 564 | S-GŁOS (testy zgodności, destylacja stylu) | dziś UCIĘTE — po fixie #1 |
| dreams | 7 095 | zasiew krawędzi kojarzeniowych | krótkie polskie asocjacje; uwaga na epokę „pollution" [GRUNT: .bak-pollution-20260620] |
| beliefs 2 000 + knowledge_index 743 | ~2,7k | sądy startowe FAKT (z proweniencją) | czyste, małe; bez historii rewizji do fixu #3 |
| reasoning_journal | 1 340 (~500/dzień, moduł ma dni) | przyszłe paliwo destylacji rozumowania | młode; częściowo JSON, nie proza — poprawić logowanie u źródła |
| wiadomości user + user_facts + taski | ~243+55+16 | S-AKTY | ZA MAŁO → destylacja NIM-70B jako bootstrap + fix #2 jako właściwe źródło |
| synthesis_review | 29 (16 promoted) | wzorce dla toru 3 | małe, unikalne (multi-source → wiedza + ocena wierności) |

**Caveat generalny [GRUNT]:** etykiety produkowały reguły i polityka 1.0 —
specjaliści uczeni na nich destylują POLITYKĘ 1.0, nie „mądrość świata".
To dobrze dla shadow-mode (chcemy porównywalności), źle dla „lepszości" —
lepszość mierzymy wyłącznie behawioralnie na przyszłych, świeżych danych.

### 5.3 Transpilacja zamiast czystej kartki

Pierwszej rodziny programów Osnowy nie pisze człowiek z głowy — jest
**transpilowana** z żywego, sprawdzonego kodu 1.0: GoalSelector (czysta
funkcja bez LLM i bez stanu K8 [GRUNT]) → ~15-30 reguł-jako-danych; potem
polityki K7. Pierwsze programy pisze więc Maria 1.0 swoim pięciomiesięcznym
życiem — łata to (częściowo) problem „tożsamości autorskiej, nie wyrośniętej".

### 5.4 Shadow-mode — projekt porównania behawioralnego

[GRUNT — analiza plannera K5 z 2026-07-07; Z7 w ROADMAP]

**Zadanie-cel:** Planner K5 (decyzja `Plan{goal_id, action_type(16), params}`,
~1000 cykli/dobę). Ścieżka wyboru jest rule-based deterministyczna [GRUNT:
ADR-013], ALE: StrategicPlanner (NIM 70B) jest WŁĄCZONY i steruje kolejnością
celów co ~30 min — **logujemy go jako INPUT**, inaczej rozjazdy będą
artefaktem stratega, nie różnic architektur.

**Sekwencja (poprawiona po werdykcie sędziów — kolejność jest twarda):**

1. **NAJPIERW tap.** `decision_traces` NIE zawiera pełnych wejść decyzji
   [GRUNT] — nowy tap w `run_cycle` po STEP 2.4 (po mutacjach GoalStore,
   przed wyborem) zrzuca ramkę wejściową: kontekst, pełną listę kandydatów-celów
   z metadanymi, **stan ukryty (cooldowny PlannerState, `_action_failures`
   TTL 1h in-memory)**, StrategicPlan, stan strategii K8, TimeContext, flagi.
   Bez zrzutu stanu ukrytego kappa kłamie.
2. **Tygodnie zbierania ramek** (tap działa, nic nie porównujemy).
3. **Replay wierności offline** na zebranych ramkach: transpilowany
   goal-ranking 2.0 vs decyzje 1.0 — kappa Cohena ≥0.9 = dowód, że język
   i Interpreter wiernie niosą semantykę (to test EKSPRESYWNOŚCI, świadomie
   „fidelity-shaped" — niczego nie dowodzi o lepszości i tak to raportujemy).
4. **Cień na żywo** (decyzja 2.0 logowana, nigdy nie wykonywana): metryka
   3-poziomowa — A: action_type (kappa, główna metryka Z7), B: (goal_id,
   action_type) exact, C: top-1 goal + korelacja rankingów. Idle/skip
   wykluczone z liczenia (wzorzec `is_real_action` [GRUNT]); baseline
   „zawsze najczęstsza klasa" raportowany obok (rozkład jest skrajnie skośny).
5. **Faza poprawy** (oddzielona od wierności): 2.0 może się RÓŻNIĆ od 1.0
   na lepsze — różnice oceniane po wynikach (sukces akcji, zdrowie), nie po
   zgodności. Rozjazd z uzasadnieniem = insight, nie błąd.

**Pułapki (z analizy, wpisane do protokołu):** mutacje mid-decision (punkt
odcięcia tapu zdefiniowany), czas żywy (replay wstrzykuje `now` z ramki),
pętla pivot (porównanie na WYNIKU pętli), dryf rozkładu (dane sprzed fixów —
np. self_analyze-spam do 07-07 — kalibrować tylko na okresach po zmianach).

**Dodatkowe testy behawioralne** (luka wykryta przez sędziów: kryteria 7-8
z AGI_HYPOTHESES nie miały testów w żadnym projekcie):

- **Planning horizon:** benchmark wieloetapowości na decision_traces
  (śr. 4.8 kroku = skala odniesienia) — na ilu krokach plan 2.0 pozostaje
  spójny vs 1.0.
- **Failure recovery:** wstrzykiwany test degradacji — wyłącz organ X
  w cieniu, zmierz zachowanie federacji (czy deklasuje się do „nie wiem",
  czy konfabuluje).

---

## 6. WYKONALNOŚĆ NA SPRZĘCIE

**PO BUDOWLANEMU.** Działka jest mała (6 rdzeni, bez GPU), a na niej już
stoi działający dom z lokatorem (demon 1.0). Nowy dom mieści się na działce
tylko dlatego, że jest z lekkich materiałów (enkodery, mikro-sieci) — i pod
warunkiem, że ciężkie roboty (treningi) robimy nocą, kiedy stary dom śpi.
RAM nie jest problemem. Problemem jest CPU — i to on dyktuje projekt.

### 6.1 Fakty o żelazie [GRUNT — pomiary 2026-07-07 na żywo]

- Ryzen 5 7430U: 6C/12T Zen3, AVX2+FMA, **bez AVX-512**, L3 16 MB, DDR4
  dual-channel; **bez GPU**. RAM 30.8 GiB użytecznego.
- Zmierzone: llama3.1:8b ~8 tok/s generacji, ~17 tok/s prefill (4096 tok =
  261 s); qwen3:8b ~7 tok/s. Generacja jest memory-bandwidth-bound: dwa
  równoległe LLM = każdy o połowę wolniejszy. Load average 6.00/12 przy
  JEDNYM aktywnym modelu 3B.
- **Budżet gwarantowany dla 2.0: ~6-7 GiB RAM** (peak stacku Ollama 1.0 =
  15-16 GB + twardy margines 6 GB z MODEL_REGISTRY). Chwilowo bywa ~18 GiB
  wolnego, ale znika przy heavy ticku — planujemy pod gwarantowane.
- Realna równoległość: 1 heavy LLM (mutex 1.0) + 1-2 małe (≤3B) + dowolna
  liczba mikro-sieci sub-100MB. Dysk: `/mnt/storage` 5.1 TB wolne.

### 6.2 Budżet 2.0 (zestaw roboczy)

| Pozycja | RAM |
|---|---|
| Enkodery rezydentne (S-PARSER + S-AKTY + S-RELACJE, int8) | ~0.7 GB |
| S-WEKTOR (nomic, współdzielony z 1.0) | ~0.3 GB |
| Mikro-głowice (S-SĘDZIA, Prognosta, S-ODŹWIERNY, S-PLANISTA) | ~0.2 GB |
| Kronikarz (cache; indeks ANN mmap na dysku) | ~0.5 GB |
| Osnowa (gorąca część; SQLite+mmap, dyscyplina inżynierska) | ~1-2 GB |
| Interpreter + Dyrygent | ~0.3 GB |
| Narzut runtime (RSS PyTorch/ONNX, bufory) — liczony jawnie | ~0.5-1 GB |
| **Rezydentnie razem** | **~3.5-5 GB** |
| S-GŁOS 1.5-1.7B q4 **on-demand** (mmap z page cache ≈ natychmiast [GRUNT]) | +1.2-1.4 GB peak |

Mieści się w 6-7 GiB z zapasem. [SPEKULACJA co do dokładnych liczb; GRUNT co
do rzędów wielkości — rozmiary GGUF/enkoderów z krajobrazu modeli]

**CPU w dzień:** cykl decyzyjny (Interpreter + mikro-głowice na gotowym
StateVector) = dziesiątki ms; enkodery = ms-dziesiątki ms/wywołanie; kNN po
60k epizodów (BLAS, fp16 ≈ 96 MB macierz) = ms. **Decyzje bez LLM w pętli —
konstrukcyjnie.** S-GŁOS tylko na brzegach (rozmowa, kompilacja reguł):
1.5-1.7B ≈ 20-40 tok/s [GRUNT — szacunek].

**CPU w nocy (twardy kontrakt):** trening zjada 100% rdzeni [GRUNT] i —
uwaga sędziego wykonalności — **nice/cgroup NIE chroni przepustowości
pamięci** (generacja 1.0 jest bandwidth-bound). Konsolidator dostaje więc
jawny kontrakt: okno QUIET 22-07, wzajemne wykluczanie z heavy-LLM
ModelSchedulera 1.0 i z cronem backupu 03:00; tick-watchdog 1.0 jako
niezależny bezpiecznik. SetFit/mikro-MLP: minuty-godziny. LoRA 0.6B:
2-10 h/epokę (noc). LoRA 1.7B: 12-30 h (tylko weekendy). **4B: nie próbować**
[GRUNT — wszystkie liczby z krajobrazu]. QLoRA/Unsloth na CPU: nie działa
[GRUNT] — stack treningowy to PEFT/transformers lub LLaMA-Factory (CPU-only
ścieżka udokumentowana).

### 6.3 Kandydaci open-weight (stan 2025 - poł. 2026) [GRUNT — WebSearch]

| Rola | Kandydat | Licencja | Uwagi |
|---|---|---|---|
| S-GŁOS | Qwen3 1.7B / Qwen3.5 2B (III 2026) | Apache 2.0 | bezpieczny default; 262K ctx w 3.5 |
| S-GŁOS wariant PL | **Bielik v3 1.5B** | Apache 2.0 | jedyny mały natywnie polski; A/B z Qwen |
| S-GŁOS alternatywa | Granite 4.0 Nano 1B/1.5B | Apache 2.0 | bije Qwen3 1.7B w instruction-following/function-calling |
| mikro-generatywny | Gemma 3 270M | Gemma Terms | zaprojektowany pod task-specific fine-tuning; QAT int4 |
| ekstrakcja | GLiNER2 (~205M) | sprawdzić kartę checkpointu | NER + klasyfikacja + structured extraction, CPU-first |
| relacje | GLiREL | j.w. | SOTA zero-shot |
| klasyfikacja intencji | GLiClass (x-base, wielojęzyczny) / SetFit na HerBERT | j.w. / Apache | polski krótki tekst: HerBERT > mmBERT/EuroBERT [GRUNT — badanie III 2026] |
| embeddingi | nomic-embed (zostaje) / EmbeddingGemma 308M jako przyszły kandydat | — | wymiana = reindeksacja; w hybrydzie to koszt, nie złamanie tożsamości (4.4) |
| szybkie CPU (ostrożnie) | LFM2/2.5 | licencja z progiem <10 M USD przychodu | pilnować przy monetization gate |

Destylacja zadaniowa duży→mały jest udokumentowana i domowa [GRUNT]:
teacher = NIM dracarys-70b (w stacku; 40 RPM; 10k przykładów ≈ 4-5 h
generacji) → student = enkoder lub 0.3-1B LoRA. Kanon: T5 770M > PaLM 540B
na zadaniach domenowych (Distilling Step-by-Step).

### 6.4 Deklaracja „~20 GB" z VISION — gdzie trzyma, gdzie pęka

- **PĘKA jako RAM-rezydent** równolegle z żywą 1.0: nie ma 20 GB wolnego
  RAM-u i długo nie będzie [GRUNT: budżet].
- **TRZYMA SIĘ jako footprint tożsamości na dysku**: Osnowa + biblioteka +
  biografia + checkpointy + datasety destylacyjne rosną latami do dziesiątek
  GB na `/mnt/storage` (5.1 TB wolne [GRUNT]).
- **Przeformułowanie: ~20 GB = tożsamość na dysku; ~4-5 GB = zestaw roboczy
  w RAM.** Korekta wewnętrznego rozbicia: „L3 = 10 GB programów" nierealne
  (reguła ≈ 1 KB; 10 GB = miliony programów) — ciężar idzie w L4/biografię.
- Po ewentualnym cutover (2.0 głównym organizmem — perspektywa LAT, wyłącznie
  po dowodach) zwolnione 15-16 GB stacku 1.0 pozwala trzymać w RAM więcej
  Osnowy i 2-3 organy więcej [GRUNT: 6-8 modeli 0.6-1.7B mieści się w 12-16 GB].

---

## 7. PIERWSZA CEGŁA — Sędzia, z prerejestrowanym protokołem

**PO BUDOWLANEMU.** Zanim postawimy dom, wbijamy JEDEN pal próbny i mierzymy,
czy grunt trzyma. Pal: mały model, który na 405 tysiącach zapisanych
refleksji Marii uczy się przewidywać jej porażki. Miara jest ustalona PRZED
wbiciem (żeby nie oszukiwać po fakcie). Jak pal nie trzyma — nie stawiamy
domu i wiemy to po kilku tygodniach, za grosze.

### 7.1 Dlaczego ta cegła (a nie shadow-planner na start)

Werdykt sędziów był tu jednomyślny: **S-SĘDZIA (kalibrator) to najtańszy
falsyfikat całego programu 2.0, niezależnie od paradygmatu**, bo:

- **zero tapu w 1.0, zero dotykania demona** — dane fizycznie leżą na dysku
  (404 930 rekordów zweryfikowane [GRUNT]);
- omija pułapkę z 06-14 — uczy się NA ocenach (expected/actual/outcome_match),
  nie na stanie pozbawionym ocen;
- arytmetyka się spina [GRUNT]: embedding korpusu ≈ 3.5 h jednorazowo
  (prekomputowany), MLP na gotowych wektorach = minuty-godziny CPU;
- kryterium porażki jest tanie i binarne.

Filar testowany: Matematyka (kalibrowana niepewność) + wymiar 5 Logiki
(Maria ilościowo wie, jak bardzo się myli). Jednocześnie cegła przewozi
minimalny STYK: wynik Sędziego ląduje w mini-Osnowie jako sąd META i JEDNA
symboliczna reguła emituje advisory. **Uczciwie (za sędzią testowalności):
ten element styku to smoke-test hydrauliki, nie dowód hybrydy** — symboliczna
połowa jest tu za mała, żeby niezależnie oblać. Dowodem hybrydy będzie
cegła 2.

### 7.2 Protokół prerejestrowany (ustalony TERAZ, przed kodem)

**Model:** MLP 1-5M parametrów; wejście = embedding kotwiczny stanu
(prekomputowany) + cechy numeryczne + typ akcji; wyjście = P(outcome_match=False).
Ważenie klas (88% match [GRUNT]).

**Ochrona przed przeciekiem cech (uzupełnienie po audycie sędziów —
najgroźniejsza pułapka tej cegły):** reflections to zapisy post-hoc.
Do wejścia wchodzą WYŁĄCZNIE pola sprzed decyzji (confidence_before,
expected_success, action_type, topic, cechy stanu z chwili t); pola
wynikowe (actual_success, outcome_match, confidence_after, lessons) są
TYLKO etykietą/targetem. Lista pól wejściowych zamrożona w protokole;
audyt przecieku = test „model na samych polach wynikowych musi mieć AUC≈1,
model produkcyjny nie może korzystać z żadnego z nich".

**Split:** CZASOWY (nie losowy) — trening ≤ 2026-05-31, test 06/2026.
Dodatkowy sanity-split na epoce po fixach (dryf rozkładu [GRUNT]).

**Baseline'y (nazwane, oba muszą być pobite):**
1. klasa większościowa („zawsze match", 88%),
2. surowe `confidence_before` Marii 1.0 jako predyktor.

**Progi zaliczenia (retrospektywnie):** AUC ≥ 0.70 na held-out czasowym;
ECE ≤ 0.05; Brier score lepszy o ≥15% od OBU baseline'ów.

**Faza żywa (14 dni cienia, read-only):** Sędzia scoruje refleksje na bieżąco;
≥60% rzeczywistych porażek w górnym decylu ryzyka przy <30% fałszywych
alarmów; porównanie głowa-w-głowę z zapisami needs_human K9 z tego samego
okna (o ile per-epizod dostępne — do weryfikacji w pierwszym tygodniu;
jeśli nie, porównanie tylko do baseline'ów 1-2).

**Minimalna kompozycja:** S-WEKTOR (już jest) → S-SĘDZIA → mini-Osnowa
(sąd META z proweniencją) → jedna reguła („P(porażka) dla klasy akcji A
powyżej progu ⇒ advisory needs_human do bulletinu 1.0") → Rdzeń-stub.
Pełny łańcuch: przestrzeń → organ → substrat → reguła → efekt advisory.

**Harmonogram [SPEKULACJA]:** ekstrakcja + embedding 2-3 dni; trening +
ewaluacja retrospektywna kilka dni; cień 2 tygodnie. Razem ~3-4 tygodnie
kalendarzowe przy niepełnym paśmie.

**Klauzula falsyfikacji (jawna):** jeśli Sędzia nie pobije reguł 1.0 na
własnych danych 1.0 — paradygmat „umiejętności w wagach" dostaje tani,
uczciwy falsyfikat i wracamy do deski kreślarskiej ZANIM zbudujemy resztę.
Wynik negatywny bankujemy jak 06-14 (to też jest wartość).

### 7.3 Cegła 2 (zapowiedź, nie zobowiązanie): goal-ranking w cieniu

Transpilacja GoalSelectora do reguł-jako-danych + mini-Kronikarz; sekwencja
z 5.4 (tap → zbieranie → replay wierności → cień → faza poprawy). To jest
właściwy test hybrydy (symbol niesie decyzję, mózg dokłada kontekst) i wejście
w Z7. Uruchamiana tylko, jeśli cegła 1 zaliczona.

---

## 7-BIS. PIERWSZA CEGŁA — redesign po przeglądzie adwersaryjnym (Opus 4.8, 2026-07-08)

> Addendum. NIE rusza sekcji 7 Fable'a. Przegląd adwersaryjny (39 agentów, find→refute)
> potwierdził: architektura i grunt [GRUNT] trzymają się znakomicie — ale sam protokół 7.2
> **nie falsyfikuje**: baseline już przekracza próg, a etykieta jest niemal deterministyczną
> funkcją cechy podanej na wejście. **Ten protokół obowiązuje przy wykonaniu cegły 1.**

**PO BUDOWLANEMU.** Pal próbny z sekcji 7 mierzył, czy grunt trzyma — ale miarka była
ustawiona PONIŻEJ gruntu, na którym stoi. To nie unieważnia pala; poprawia miarkę, żeby
„zaliczone" znaczyło „paradygmat coś udowodnił", a nie „liczby ładnie wyszły".

### Co było źle (zmierzone na żywym korpusie 2026-07-08)

1. **Baseline już wygrywa:** surowe `(1 − confidence_before)` jako score porażki daje **AUC ~0.93**,
   a próg 7.2 to AUC ≥ 0.70 — *poniżej* baseline'u [GRUNT].
2. **Etykieta niemal deterministyczna w cesze z WEJŚCIA:** 75% rekordów ma `confidence_before==1.0`
   z **0.21%** mismatch (trywialnie bezpieczne); 25% ma `<1.0` z **24.35%** mismatch [GRUNT, próbka 120k].
   Globalne AUC 0.93 to artefakt rozdzielenia tego trywialnego splitu — nie dowód niczego.
3. **Target źle zdefiniowany:** `outcome_match` jest 4-wartościowy (match / mismatch / partial / unknown),
   nie boolean. Klasa-porażka to ~3-6% (cały korpus), nie 12%.
4. **Cechy stanu nie ma w rekordzie refleksji** (`topic` pusty w 96.7%, brak wektora stanu).
5. **Falsyfikator federacja-vs-monolit pominięty** — brak baseline'u „pojedynczy mały LLM".

### Poprawiony protokół (zastępuje 7.2 dla wykonania)

- **Target — binarny:** `mismatch=1`, `match=0`. `unknown` (to jakość etykiety, nie wynik) WYKLUCZONE
  z train+eval, raportowane osobno jako miernik jakości danych. `partial` — decyzja prerejestrowana
  przed treningiem (osobna klasa albo wykluczone).
- **Ewaluacja na TRUDNYM podzbiorze** `confidence_before < 1.0` [GRUNT: kubełek `==1.0` jest trywialny],
  ORAZ raportuj **LIFT nad `confidence_before`**, nie samo globalne AUC. Metryki: **PR-AUC na klasie
  mniejszościowej + ECE (kalibracja) + Brier** — AUC jest tu napompowane trywialnym splitem.
- **Baseline'y schodkowe (każdy wyższy MUSI pobić niższy o prerejestrowany margines):**
  - **B0** — surowe `confidence_before` („czy Maria już to wie?").
  - **B1** — regresja logistyczna na tanich cechach pre-decyzji (`confidence_before + action_type +
    health_score + mode + goal_priority`) — „czy GŁUPI model już to łapie?". [GRUNT: sam `action_type`
    w trudnym podzbiorze rozjeżdża mismatch **0% (noop) → 83% (ask_expert)** → B1 będzie MOCNY;
    organ neuronowy musi pobić **jego**, nie tylko B0, żeby uzasadnić swój koszt.]
  - **B2** — organ neuronowy S-SĘDZIA (MLP na embeddingach + cechach).
  - **B3** — **pojedynczy dostrojony mały LLM** (0.6-1.7B LoRA na tym samym korpusie). Werdykt tezy
    „federacja > monolit" = porównanie B2/federacji vs B3. Oryginał tego nie miał — to jest jej test.
- **Kryterium zaliczenia (dyskryminujące, NIE absolutne 0.70):** na trudnym podzbiorze B2 bije **B0 ORAZ B1**
  o prerejestrowany margines (poprawa PR-AUC + kalibracji ECE/Brier). Federacja uzasadniona TYLKO gdy
  bije B1 istotnie. Paradygmat-hybryda broni się dopiero w cegle 2, gdy symbol+mózg razem biją B3.
- **JOIN stanu** [GRUNT: **98.2%** pokrycia]: `reflections → decision_traces` po `plan_id`; dokleja stan
  pre-decyzji (`health_score, mode, goal_priority, k7_decision, tick_count`). 1.8% niedołączalnych —
  wykluczone i raportowane.
- **Dyscyplina przecieku (zostaje Fable'a — mocna) + poprawka:** tylko pola pre-decyzji na wejściu;
  pola wynikowe = wyłącznie etykieta; audyt przecieku wg 7.2. Poprawka: wartość modelu mierzona jako
  **LIFT nad B1**, nie absolut — bo `action_type + confidence_before` prawie nasycają tani baseline.

### Co cegła 1 dowodzi, a czego NIE (uczciwie)

Dowodzi: „uczony kalibrator bije własną pewność Marii **i** tani model na jej danych" — sygnał
KONIECZNY, nie wystarczający. NIE dowodzi: Osnowy, hybrydy jako takiej, ani „federacja > monolit"
(chyba że B3 wejdzie). Klauzula falsyfikacji z 7.2 zostaje w mocy — z tym progiem, nie tamtym.

### Residual kolejności (z przeglądu)

Osnowa — substrat, na którym wisi CAŁA architektura (tożsamość 4.4, styk 4 filarów, self-model 2.4) —
wciąż walidowana najpóźniej. Rekomendacja: cegła 2 (goal-ranking w cieniu, 7.3) MUSI nieść minimalny
behawioralny falsyfikat Osnowy (symbol niesie decyzję), inaczej najbardziej nośny komponent wchodzi
w Z7 bez własnego testu.

### 7-BIS.1 — WYNIK 1. przejazdu (2026-07-08, Opus 4.8)

Odpalone wg protokołu 7-BIS na realnym korpusie (skrypt: `experiments/cegla1_sedzia.py`).
Dane: 439 442 reflections + 61 205 decision_traces, JOIN po `plan_id` 97.0%, target po odsianiu
`unknown/partial` = 387 279 [GRUNT]. Split trudny/łatwy potwierdził tezę co do liczby:
`confidence==1.0` → 0.14% mismatch (trywialne), `confidence<1.0` → 20.6% (test 24 182 rekordów).

**Wynik na trudnym podzbiorze (test, metryki 7-BIS):**

| model | PR-AUC ↑ | Brier ↓ | ECE ↓ | ROC-AUC ↑ |
|---|---|---|---|---|
| **B0 — surowa pewność Marii** | **0.335** | **0.165** | **0.085** | 0.632 |
| B1 — logistyka (tanie cechy) | 0.311 | 0.227 | 0.212 | 0.701 |
| B2 — MLP (organ, tanie cechy) | 0.311 | 0.228 | 0.196 | 0.687 |

**WERDYKT: organ NIE zarabia na utrzymanie.** B2 nie bije B0 (dPR-AUC −0.025, dBrier −0.063) ani
B1 (dPR-AUC +0.0001 = szum). Neuron nad logistyką = ZERO. Własna pewność Marii jest najlepiej
skalibrowana. To klauzula 8.5.5 odpalona na żywo — **tani falsyfikat** (30s), zbankowany jak 06-14.
Redesign 7-BIS się opłacił: globalne ROC-AUC = 0.95 (napompowane) vs realne PR-AUC ~0.33; stary próg
0.70 zaliczyłby trywialnie.

**Zakres uczciwie (czego NIE dowodzi):** to **połowa** falsyfikatora — testuje NIELINIOWOŚĆ na TANICH
cechach (pada), NIE treść semantyczną. B2 dostał te same skalary co B1, więc ≈ B1 z definicji.
Nietknięty lewar: embedding treści (`goal_description`) — czy TREŚĆ przewiduje porażkę ponad skalary.
To właściwy test neuronu → **przejazd 2** (semantyczny, osobna sesja). Uwaga do przejazdu 2: B1/B2 użyły
`class_weight='balanced'` co podbiło ROC ale zepsuło Brier/ECE — przejazd 2 powinien kalibrować
(`CalibratedClassifierCV`) dla uczciwego porównania na metrykach kalibracji.

> **KOREKTA (2026-07-08, Fable 5, w przejeździe 2):** liczby wyżej są **skażone bugiem dedup** —
> `cegla1_sedzia.py` dedupował tylko `decision_traces`, a NIE `reflections.jsonl`, który ma ~13.9×
> duplikację na `plan_id` (452 141 wierszy / 32 588 unikalnych), **zależną od klasy** (match 13.8×
> vs mismatch 8.9×) [GRUNT, zweryfikowane]. Skutki: base-rate zaniżony (trudny test 20.6% → realnie
> **22.8%**), izotonic/kalibracja liczona na ~14× zwielokrotnionych punktach, efektywne N_test ≈ 1616
> (nie 24 182). Po dedupie (`outcome_match` spójny w `plan_id` → `keep=last` bezpieczny) tabela
> przejazdu 1 (ten sam setup) to: B0 PR=0.352/Brier=0.181, **B1 PR=0.384**/Brier=0.196, B2-cheap
> PR=0.376/Brier=0.176. **Sub-teza „pewność Marii (B0) najlepiej skalibrowana" UPADA — B1 bije B0
> na PR-AUC** (w skażonej wersji było odwrotnie). Werdykt główny „organ na tanich cechach nie zarabia"
> STOI. Pełny czysty panel → 7-BIS.2. Skrypt naprawiony (dedup obu stron).

### 7-BIS.2 — WYNIK 2. przejazdu (semantyczny, 2026-07-08, Fable 5)

Odpalone wg protokołu 7-BIS, skrypt: `experiments/cegla1_sem.py`. Cel: dodać **embedding treści celu**
(`goal_description`, 768-dim nomic-embed-text) i sprawdzić, czy TREŚĆ przewiduje porażkę **ponad tanie
skalary** — właściwy test neuronu, którego przejazd 1 nie zrobił.

**PO BUDOWLANEMU.** Przejazd 1 sprawdził, czy zakrzywienie (nieliniowość) na tanich liczbach coś daje —
nie dało. Tu dokładamy TREŚĆ zlecenia jako 768 liczb i pytamy, czy „o czym był cel" mówi coś o porażce
ponad „jaki to typ akcji + jak pewna była Maria". Nie mówi. Wręcz zaszumia.

**Metoda (po korekcie):** dedup obu stron po `plan_id`; trudny podzbiór `confidence<1.0`; split czasowy
train<2026-06-01 / test≥ (train N=3676, **test N=1616**, mismatch 22.8%); kalibracja `CalibratedClassifierCV`
(isotonic, cv=3), **BEZ** `class_weight` (fix 7-BIS.1); embedding 132 unikalnych opisów z cache na dysku.
Kluczowy fakt gruntu: `goal_description` to **132 szablonowe stringi** (train 61 / test 83), **49% wierszy
testu to cele niewidziane w treningu** — czyli embedding ≈ kodowanie kategorii + test generalizacji.

**Panel modeli na TRUDNYM podzbiorze (test, 95% CI = paired bootstrap B=2000):**

| model | PR-AUC ↑ [95% CI] | Brier ↓ [95% CI] | ECE ↓ | ROC |
|---|---|---|---|---|
| B0 — surowa pewność Marii | 0.352 [0.310, 0.401] | 0.181 [0.169, 0.194] | 0.093 | 0.645 |
| **B1 — logistyka (tanie cechy)** | 0.384 [0.342, 0.432] | 0.168 [0.155, 0.182] | 0.082 | 0.717 |
| B1 + goal_description (one-hot) | 0.377 [0.337, 0.427] | 0.167 [0.154, 0.180] | 0.078 | 0.713 |
| B2-emb-only (MLP na samym embeddingu) | 0.239 [0.216, 0.266] | 0.184 [0.176, 0.193] | 0.080 | 0.530 |
| **B2-sem — organ (MLP cheap+emb)** | 0.268 [0.239, 0.304] | 0.201 [0.188, 0.215] | 0.126 | 0.599 |
| A: MLP cheap-only (ablacja) | **0.385** [0.341, 0.434] | **0.163** [0.151, 0.175] | **0.038** | 0.677 |
| A: LOGIT cheap+emb (ablacja) | 0.336 [0.300, 0.385] | 0.173 [0.162, 0.185] | 0.053 | 0.665 |

**WERDYKT: organ semantyczny NIE zarabia — jest ISTOTNIE GORSZY.** Delty B2-sem (paired bootstrap,
CI wyklucza 0 = istotne): vs B0 dPR-AUC **−0.084** [−0.123, −0.043] i dBrier −0.020 [−0.031, −0.009];
vs B1 dPR-AUC **−0.117** [−0.153, −0.081] i dBrier −0.033 [−0.042, −0.024]. To nie „nie lepszy" — to
**mierzalnie gorszy**. Sam embedding (B2-emb-only) jest praktycznie **rzutem monetą** (ROC 0.530,
PR-AUC 0.239 ledwo nad base-rate 0.228) — czysta treść ≈ zero sygnału o porażce.

**Money-shot (ten sam MLP, ta sama kalibracja, jedyna różnica = +embedding):** MLP cheap-only
PR=0.385/Brier=0.163/ECE=0.038 → dorzuć embedding (B2-sem) PR=0.268/Brier=0.201/ECE=0.126. **Embedding
to czysta trucizna** na tym zadaniu (768 wymiarów na 3676 wierszach + 49% celów niewidzianych = przeucza).

**Ablacja 2×2 (klasa modelu ⊥ zestaw cech) — zdejmuje zarzut „MLP okaleczony":**
na tanich cechach logistyka (0.384) ≈ MLP (0.385) → **klasa modelu nie jest problemem**; dorzucenie
embeddingu psuje w OBU klasach (LOGIT cheap+emb 0.336 < 0.384; MLP 0.268 < 0.385) → **problemem jest CECHA**.
Dowód model-agnostyczny (nie zależny od MLP): **B1+onehot (0.377) < B1 (0.384)** — nawet najprostsze,
uczciwe kodowanie `goal_description` lekko szkodzi. Tożsamość celu jest **zbędna** ponad `action_type`.

**Flip B0/B1 (korekta do 7-BIS.1):** po dedupie + kalibracji **B1 bije B0 na wszystkich trzech**
(PR 0.384>0.352, Brier 0.168<0.181, ROC 0.717>0.645). Teza „pewność Marii najlepiej skalibrowana"
z 7-BIS.1 była **artefaktem duplikacji**. Najlepszy model to skalibrowany **MLP/logistyka na tanich
skalarach** (ECE 0.038) — sygnał żyje w `action_type + confidence + health/mode/priority`, nie w treści.

**Zakres uczciwie (czego NIE dowodzi):** testowano embedding **szablonowego** `goal_description`
(132 unikaty) — to ≈ one-hot kategorii, NIE bogaty tekst. Więc to **NO-GO dla lewara „embedding celu"
na logach 1.0**, a NIE falsyfikat „semantyki jako paradygmatu". Bogatszy tekst (pełne uzasadnienia,
kroki, wynik) mógłby nieść sygnał — tego ten korpus nie ma. Powtórzona dyscyplina zakresu z 7-BIS.1.

**Odstępstwa od protokołu 7-BIS (jawnie):** (1) B1 rozszerzony o `expected_success` i `k7_decision`
ponad prerejestrowane 5 cech — oba pre-decyzyjne (nie leak) i **wzmacniają B1**, więc konserwatywne dla
organu; (2) bramka sprawdza PR-AUC+Brier bez ECE i progiem >0 zamiast nazwanego marginesu (margines
nigdy nie zdefiniowany liczbowo) — nieistotne, bo delty są istotnie UJEMNE. Antyprzeciek czysty: pola
wynikowe (`success, result_summary, confidence_after`) NIE ładowane; wejście = wyłącznie snapshoty
pre-decyzyjne. B0 jest CELOWO zagnieżdżony w przestrzeni cech B1/B2 (więc „nie bije B0" = nieliniowość
+ embedding nie poprawiają najlepszego pojedynczego skalara).

**Co dalej (go/no-go):** falsyfikat organu semantycznego na `goal_description` = **zbankowany** (jak 06-14).
Klauzula 8.5.5 odpalona: organ neuronowy — czy na nieliniowości (przejazd 1), czy na treści (przejazd 2) —
nie bije taniej logistyki na TYM zadaniu/korpusie. To **NIE blokuje cegły 2** (goal-ranking w cieniu, 7.3),
która testuje INNĄ hipotezę (symbol niesie decyzję, mózg dokłada kontekst), ale usuwa złudzenie, że
sama treść celu jest lewarem. Rekomendacja: jeśli wracać do S-SĘDZIA, to na **bogatszym** wejściu
(pełny ślad rozumowania per epizod — patrz „reasoning journal"), nie na szablonowym `goal_description`.

### 7-BIS.3 — WYNIK 3. przejazdu (bogate wejście pre-decyzyjne, 2026-07-08, Fable 5)

Sprawdzenie rekomendacji z 7-BIS.2: a co, gdy dać organowi **bogatsze wejście pre-decyzyjne**?
Skrypt: `experiments/cegla1_rich.py`. Bogaty tekst = `goal_description || action_params || k7_reasons`
(**315 unikatów** na trudnym vs 132 dla samego goal_description; dochodzi konkretny temat,
`resolved_file_ids`, powód bramki K7). Dyscyplina przecieku: pola PO decyzji (`result_summary`,
`steps`, `actual_success`, `confidence_after`) NIE wchodzą na wejście — tylko etykieta/kontrola.

**Reasoning journal (`/myslenie`) sprawdzony i ODRZUCONY jako źródło:** `meta_data/reasoning_journal.jsonl`
istnieje (1392 rekordy) ale pokrywa **1.4%** trudnego podzbioru i to same `self_analyze` — to
meta-rozumowanie K12/K13 (join po `episode_id`), NIE rozumowanie per-akcja dla `learn`/`exam`, których
porażki przewidujemy. Żeby stał się użyteczny dla S-SĘDZIA, musiałby być wpięty w ścieżkę per-decyzja.

**Panel na TRUDNYM podzbiorze (test N=1617, base-rate 22.8%, 50% bogatych tekstów niewidzianych w treningu):**

| model | PR-AUC ↑ | Brier ↓ | ECE ↓ | ROC |
|---|---|---|---|---|
| B0 — surowa pewność Marii | 0.352 | 0.181 | 0.093 | 0.645 |
| **B1 — logistyka (tanie cechy)** | 0.384 | 0.168 | 0.082 | 0.717 |
| B3-rich (MLP cheap+emb) | 0.278 | 0.197 | 0.142 | 0.575 |
| B3-rich-LOGIT (cheap+emb) | 0.276 | 0.196 | 0.115 | 0.626 |
| B3-rich-only (MLP emb) | 0.241 | 0.196 | 0.138 | 0.550 |
| **LEAK-RF [kontrola przecieku]** | **0.828** | 0.051 | 0.051 | **0.883** |

**WERDYKT: bogaty organ też NIE zarabia — istotnie GORSZY** (paired bootstrap, CI wyklucza 0):
vs B1 dPR-AUC **−0.106** [−0.149, −0.065], dBrier −0.029 [−0.039, −0.020]; vs B0 dPR-AUC −0.074. Bogatsze
wejście nie pomogło — dodanie tekstu (szablonowego czy „bogatego") wciąż szkodzi (przeucza: 768 wymiarów
na 3676 wierszach + 50% celów niewidzianych). Spójne z 7-BIS.2.

**Kontrola przecieku = klincz.** LEAK-RF (RandomForest na polach PO-decyzji `expected/actual_success +
confidence_after` — `outcome_match` ≈ `expected≠actual` w 98%) daje **PR 0.828 / ROC 0.883**, DUŻO powyżej
każdego modelu pre-decyzyjnego (~0.38) i base-rate (0.23). To dowodzi: (1) etykieta JEST wyuczalna,
(2) pipeline łapie sygnał gdy jest → **null na pre-decyzji to PRAWDZIWY null, nie zepsuty pipeline**.
Uwaga metodologiczna: liniowa logistyka na surowych `exp/act` NIE ogarnia XOR (`exp≠act`) — kontrola musi
być nieliniowa (RF) albo z jawną cechą. Uwaga logiczna, która zabezpiecza werdykt niezależnie od kontroli:
**ewentualny nieujawniony przeciek mógłby tylko NAPOMPOWAĆ organ — a organ przegrywa**, więc null jest
odporny.

**Fundamentalny wniosek (3 przejazdy):** porażka Marii NIE jest przewidywalna z tego, co wie PRZED akcją,
ponad zgrubny sygnał `action_type + confidence`. Reprezentacja treści (kategoria, embedding szablonu,
embedding bogatego tekstu) — każda **szkodzi**. Sygnał o porażce materializuje się dopiero W TRAKCIE/PO
wykonaniu (widać: LEAK-RF na polach wynikowych = 0.83). To ma sens organizmicznie: „czy mi się uda" zależy
od egzekucji (jakość materiału, LLM, timeout), nie od opisu zamiaru.

**DECYZJA: S-SĘDZIA na treści = ZAMKNIĘTY / na półkę** (za zgodą operatora, 2026-07-08). Organ neuronowy
oblał falsyfikator w 3 niezależnych przejazdach: nieliniowość na skalarach (1), embedding szablonu (2),
embedding bogatego tekstu pre-dec (3). Klauzula 8.5.5 odpalona 3×, zbankowana jak 06-14. **Warunki
powrotu (gdyby):** (a) reasoning journal wpięty w ścieżkę per-decyzja (bogaty ślad rozumowania DLA
przewidywanych akcji, nie meta-cogn.), ALBO (b) cel = predykcja PRZED egzekucją z cechami egzekucji
(model materiału/LLM), nie z opisu zamiaru. **NIE blokuje cegły 2** (goal-ranking w cieniu, 7.3 — inna
hipoteza: symbol niesie decyzję). To jest teraz właściwy następny pal.

---

### 7.4 CEGŁA 2 — PROTOKÓŁ PREREJESTROWANY: falsyfikator ekspresywności Osnowy + obserwowalność plannera (2026-07-08, Fable 5)

> Ustalony PRZED kodem (dyscyplina 2.0, jak 7.2 dla cegły 1). Grunt: mapowanie żywego Plannera K5
> (`planner_core.py`) + adwersaryjny przegląd protokołu v1 (5 soczewek, werdykt: „przeprojektować" — v1
> powtarzał patologię cegły 1). To jest v2 po tym przeglądzie. RESEARCH_ONLY; tap dotyka żywego 1.0 →
> zgoda operatora + restart przez operatora.

**PO BUDOWLANEMU.** Cegła 1 pytała, czy MÓZG (wagi) przewiduje lepiej — nie. Pierwszy szkic cegły 2 wpadł
w tę samą pułapkę co cegła 1: „miarka pod gruntem". Przepisanie if-ów 1.0 na JSON i wykonanie ich tym samym
interpreterem daje zgodność ≈100% Z DEFINICJI — to nic nie dowodzi (anty-wzorzec 8.1 „beautiful logging").
v2 pyta o JEDNĄ rzecz, którą da się uczciwie sfalsyfikować i to w DNI, nie tygodnie: **czy język reguł
Osnowy jest dość bogaty, by WYRAZIĆ decyzję Marii BEZ ucieczki z powrotem do kodu imperatywnego 1.0 — i czy
nie jest tak bogaty (Turing-zupełny), że „wyraża wszystko" trywialnie.**

#### 7.4.A Co testujemy (po przeprojektowaniu)

**GŁÓWNA BRAMKA (jedyny prawdziwy falsyfikator): escape-hatch.** Transpilujemy taktyczny łańcuch decyzji
K5 na reguły-jako-dane nad ZAMROŻONYM słownikiem prymitywów Osnowy. Miara: **udział decyzji, których
`action_type` NIE jest w pełni wyznaczony przez ewaluację zamrożonych prymitywów nad ramką** (każde
wywołanie z powrotem do imperatywnego kodu 1.0 = escape). Prereg próg: **escape ≤15% na NIETRYWIALNYM
podzbiorze** (rzadkie klasy decyzjo-nośne), liczony przez NIEZALEŻNY skrypt-audytor (nie autora transpilacji).

**PUŁAPKA TURING-ZUPEŁNOŚCI (jawnie):** żeby oddać pętlę PIVOT, porównania TTL, kaskadę P0-P7, język reguł
potrzebuje arytmetyki+warunków+iteracji → grozi Turing-zupełnością → wtedy escape≈0 TRYWIALNIE i „dowód
ekspresywności" jest pusty. Dlatego słownik prymitywów jest ZAMROŻONY PRZED transpilacją i ograniczony
(deklaratywny: predykaty, porównania, priorytety, tabele mapowań — BEZ dowolnej rekurencji/pętli
użytkownika). **Jeśli okaże się, że wierne oddanie 1.0 WYMAGA Turing-zupełności — to jest WYNIK: cegła 2
mówi wtedy „Osnowa-jako-deklaratywny-substrat nie udźwignie tej decyzji bez stania się zwykłym językiem
programowania", i to bankujemy jak cegłę 1.**

To falsyfikator FILARA SYMBOLICZNEGO/Osnowy (residual 7-BIS: „symbol niesie decyzję") — INNY niż cegła 1
(filar MÓZG/wagi, 8.5.5).

#### 7.4.B Odstępstwo od 7.3 + SKURCZONY zakres (uczciwie, po przeglądzie)

7.3 dawało zielone światło cegle 2 jako „test hybrydy (symbol niesie decyzję, mózg dokłada kontekst)" i
„tylko jeśli cegła 1 zaliczona". Oba założenia trzeba uczciwie zrewidować:
- Cegła 1 NIE zaliczona. Idziemy, bo to INNY filar (symbol vs wagi) i falsyfikat ekspresywności to
  precondition CAŁEGO substratu symbolicznego. ALE: bez motywowanego brnięcia —
- **Zakres SKURCZONY:** zdana cegła 2 kupuje WYŁĄCZNIE (a) dowód ekspresywności Osnowy + (b) obserwowalność
  plannera. **NIE dowodzi lepszości ani hybrydy** — bo lepszość jest w czystym cieniu NIEIDENTYFIKOWALNA
  (7.4.F). „Mózg dokłada kontekst" = dopiero cegła 3+. Przemianowanie w tytule odzwierciedla to, czym cegła
  2 realnie jest. **Go/no-go bariera:** jeśli po sekcji 7.4.F operator uzna, że sam dowód ekspresywności bez
  ścieżki do lepszości nie jest wart kosztu — cegła 2 = tylko tap-observability (7.4.D krok 0), reszta odpada.

#### 7.4.C GRUNT (mapowanie kodu 2026-07-08) — co transpilować

Żywa decyzja NIE jest „czystą funkcją GoalSelector" (5.3 było za wąskie):
- `GoalSelector.select_goal` MARTWY na demonie (`planner_core.py:1888`). Żywa ścieżka: `run_cycle` (703) →
  `_select_ranked_goals` (820) inline'uje `_compute_effective_priority`+`_check_feasibility`, potem **pętla
  PIVOT** (838-927): pierwszy feasible cel dający NIE-NOOP i NIE-K7-blocked akcję (NIE argmax).
- `action_type` z rozgałęzionego łańcucha `_create_plan_for_goal` (1979): forced → B2 fetch-valve →
  learn-backoff→NOOP → mapa MAINTENANCE (2063) → saturation→FETCH → K8 → `_decide_learning_action`
  (P0-P7, 2440) / `_decide_non_learning_action` (2511).
- **Transpilujemy CAŁY ten taktyczny łańcuch** (rank+pivot+action-derivation) jako reguły-jako-dane.
- Warstwa STRATEGICZNA jest świadomie POZA zakresem: StrategicPlanner = NIM/qwen3 (niedeterministyczny,
  `STRATEGIC_PLANNER_DRIVES=1` na żywo), K8 Deliberation trzyma wielokrokową strategię W PAMIĘCI. To NIE
  jest symboliczne i nie transpilujemy tego — traktujemy jego wyjście jako WEJŚCIE (dana w ramce).

#### 7.4.D Sekwencja (ODWRÓCONA po przeglądzie: różnicowo w DNI, nie cień w tygodnie)

**Krok 0 — TAP jako OSOBNE narzędzie obserwowalności (samodzielna wartość, 8.6).** Buduje się niezależnie od
losu 2.0: „czemu planner wybrał X" jest dziś nieodtwarzalne z traces. Zrzuca ramkę wejściową decyzji. NIE jest
naukowym instrumentem cegły 2 (patrz krok 2). Wymagania techniczne w 7.4.G (peek bez skutków ubocznych, budżet
rozmiaru, async zapis). Ratyfikowalny SAM, nawet gdyby reszta cegły 2 odpadła.

**Krok 1 — TRANSPILACJA NAJPIERW.** Taktyczny łańcuch (7.4.C) → reguły-jako-dane nad zamrożonym słownikiem
(7.4.A). Escape-hatch = PRODUKT tego kroku (liczony niezależnym audytorem). Znany w DNI.

**Krok 2 — TEST RÓŻNICOWY (główny, offline, DNI).** Interpreter(reguły Osnowy) vs zaimportowane funkcje 1.0
(`_select_ranked_goals` + `_create_plan_for_goal` + `_decide_*`) na ramkach: (a) SYNTEZOWANYCH z
KOMBINATORYCZNYM pokryciem gałęzi (każdy z 16 `action_type` × każda gałąź łańcucha × warianty stanu ukrytego)
+ (b) seedowanych z pól widocznych w ISTNIEJĄCYCH `decision_traces` (7399 rek.). Sam GENERUJESZ ramkę →
KONTROLUJESZ stan ukryty → CAŁY koszmar rekonstrukcji historii (7.4.C stan ukryty, wall-clock, K8-w-pamięci)
ZNIKA. Precedens: cegła 1 zabiła organ w 30s na gotowych danych, bez tapu i tygodni.
- **SHADOW-OF-SELF (sanity, NIE hipoteza):** interpreter zbudowany 1:1 z kodu 1.0 (zero reinterpretacji
  Osnowy) MUSI dać zgodność = 1.0 na wszystkich ramkach. <1.0 → transpilacja/pokrycie niekompletne, domknąć
  PRZED czymkolwiek. To że to ≈1.0 jest OCZEKIWANE i NIE dowodzi nic o Osnowie.
- **Metryka hipotezy:** escape-hatch (7.4.A) + **per-klasa recall** na rzadkich klasach decyzjo-nośnych
  {FETCH, EXAM, EFFECTOR, FS_WRITE, ASK_EXPERT} obok agregatu; **raportuj macierz pomyłek** (agregatowa
  kappa MOŻE przejść przy 0% recall na tych klasach — to je maskuje).

**Krok 3 (OPCJONALNY, PO zdanym kroku 2) — cień na żywo jako RE-POTWIERDZENIE.** Dopiero jeśli różnicowy
przejdzie i operator chce potwierdzenia na żywym rozkładzie: tap (krok 0) zbiera ramki, replay 2.0 vs 1.0.
Metryka A/B/C (action_type kappa / (goal,action) exact / top-1+ranking). **To NIE jest główna bramka** —
różnicowy test już odpowiedział; cień tylko sprawdza, czy rozkład żywy nie ma gałęzi pominiętych w syntezie.
Tygodnie, więc tylko za świadomą zgodą.

#### 7.4.E Progi prerejestrowane (behawioralne, 8.1)

- **GŁÓWNA (krok 2): escape-hatch ≤15%** na nietrywialnym podzbiorze, liczony niezależnym skryptem +
  **per-klasa recall ≥0.9** na {FETCH, EXAM, EFFECTOR, FS_WRITE, ASK_EXPERT}. Powyżej progu / poniżej recall
  → Osnowa nie udźwiga decyzji bez ucieczki do kodu (falsyfikat ekspresywności, bankujemy jak cegłę 1).
- **SHADOW-OF-SELF: zgodność = 1.0** (sanity; <1.0 = niekompletne pokrycie, nie wynik naukowy).
- **Turing-check:** jeśli zdanie escape≤15% wymagało prymitywów Turing-zupełnych → wynik = „falsyfikator
  pusty", raportowany jawnie (patrz 7.4.A).
- **Cień (krok 3, opcjonalny):** kappa A istotnie > baseline „zawsze najczęstsza klasa" (**zmierzone na
  `decision_traces` 7399 rek.: most-frequent = creative 41.9%; empty/None = 775 = 10.5%; skos NIE inflacjonuje
  kappa — const-baseline kappa=0.0, płytki czasowy 0.29-0.34**), bootstrap CI, per-klasa obok agregatu.

Wszystkie liczby preregu odtwarzalne nazwanym skryptem (`experiments/cegla2_*.py`, wzór `cegla1_sedzia.py`).

#### 7.4.F Lepszość — NIEIDENTYFIKOWALNA w czystym cieniu (grunt outcome-data 2026-07-08)

**„Lepszość po wynikach" w czystym cieniu jest NIEIDENTYFIKOWALNA na rozjazdach — niemożliwość KONSTRUKCYJNA
(missing counterfactual).** Gdy 2.0≠1.0 (jedyne ciekawe), 1.0 wykonało akcję A; `outcome(B)` decyzji 2.0
NIGDY nie powstaje. Więc 5.4 pkt 5 jak napisane jest niewykonalne. Dodatkowo sygnału jest ZA MAŁO nawet
gdyby: `success` konflatuje skip z OK (11 894 rek. success+skip); twardy zewnętrzny wynik = exam-score,
**268 nieskipowanych w całym korpusie**; efektor 14 zdarzeń. `health_score` mierzy HARDWARE (stdev 0.059,
51.5% |Δ|<0.01) → jako reward PERWERSYJNY (2.0 wygra NOOP-em) → ODRZUCONY. `outcome_match` 82% match = tautologia.
OPE/IPS martwe (1.0 deterministyczny, propensity ∈{0,1}).

**Konsekwencja:** cegła 2 NIE mierzy lepszości. Kropka. Wariant „faktyczne wykonanie 2.0 na akcjach
niby-read-only" ODRZUCONY — przegląd zweryfikował w kodzie, że creative/self_analyze/critique/evaluate NIE są
bez efektu: wołają `_complete_oneshot_goal`→`goal_store.save()` (`action_executor.py:1008`), zapisują pliki,
tworzą PROPOSED-cele/bulletiny/ping Telegram, palą NIM 70B — skażenie trwałe i zatruwa korpus. Jeśli KIEDYŚ
mierzyć lepszość, to na FORK/scratch GoalStore + zaślepionych notyfikatorach, jako OSOBNA decyzja (nie tu).

#### 7.4.G Dyscyplina przecieku / pułapki (z gruntu + przeglądu)

- **Tap bez skutków ubocznych:** NIE wołać `deliberator.get_next_action` z tapu (`deliberator.py:85,96-97`
  flipuje step→ACTIVE = observer effect na mierzony stan) — dodać `peek` albo zrzucać surowy stan strategii.
- **Stan ukryty (kompletny, 7.4.C+):** `_action_failures` (in-mem, TTL 1h, gubiony przy restarcie), stuck_cooldowns,
  consecutive_noop, goal_action_repeat, actions_since_progress, off_window budget, last_*_ts, goal.metadata,
  **+ K7 `ActionRateLimiter._history` + `AutonomyPolicy._failure_timestamps`** (in-mem deque, jedyna bramka
  kaskady non-learning, `rate_limiter.py:62` — pominięte w v1). W teście różnicowym (krok 2) to NIE-problem
  (generujesz stan); istotne tylko dla opcjonalnego cienia (krok 3).
- **Populacja:** pre-goal intercepty (`_maybe_creative`:799, `_maybe_fs_write`:807 FS_WRITE_ENABLED=true,
  heldout:815) + approved-effector (:3883) emitują DecisionTrace PRZED pętlą (:838) z goal_id=None → inna
  populacja. Tap (krok 0) przenieść przed :753 i logować ścieżkę wyjścia, albo prereg wykluczyć te klasy
  z mianownika. **Klucz JOIN = `episode_id`** (nie plan_id dla intercept-ów bez goal).
- **skipped != failed:** definicja porażki identyczna z bramką 1.0 (`record_action_failure` iff NOT success
  AND NOT skipped, :3233). Tap MUSI zrzucać `result.skipped` (traces same go nie mają; `decision_filters.py:68`).
- **knowledge_snapshot:** NIE zrzucać pełnych ~370KB/cykl (→2GB+; lekcja watchdog-lease `92b1501`) — hash+delta
  albo tylko czytane pola; deep-copy mutowalnych pól synchronicznie, zapis async; budżet rozmiaru ramki +
  pomiar latencji na demonie PRZED zbieraniem.

#### 7.4.H Co dowodzi / NIE dowodzi (uczciwie)

Dowodzi (escape≤15% na nietrywialnym podzbiorze + recall≥0.9 na rzadkich klasach, bez Turing-zupełności):
język Osnowy jest DOŚĆ EKSPRESYWNY, by nieść taktyczną decyzję 1.0 deklaratywnie (residual Osnowy domknięty).
NIE dowodzi: lepszości (7.4.F, niemierzalna), hybrydy (cegła 3+), transpilowalności warstwy strategicznej
(NIM/K8, poza zakresem). Wynik negatywny (escape>15% ALBO wymagał Turing-zupełności) bankujemy jak cegłę 1.

#### 7.4.I Koszt i pierwszy krok

- **Krok 0 (tap-observability):** kilka dni; wartość SOLO. Dotyka żywego `run_cycle` → review + restart operatora.
- **Kroki 1-2 (transpilacja + test różnicowy):** DNI, offline, zero tapu, zero tygodni. To główna odpowiedź.
- **Krok 3 (cień):** tygodnie, OPCJONALNY, tylko po zdanym kroku 2 i osobnej zgodzie.

**Pierwszy konkretny krok do ratyfikacji: zamrożenie słownika prymitywów Osnowy (7.4.A) + skrypt liczb preregu.**
Potem transpilacja + test różnicowy (kroki 1-2). Tap (krok 0) równolegle jako narzędzie, ale to on wymaga
dotknięcia produkcji — więc jego kod idzie do review osobno. Nic nie rusza produkcji do ratyfikacji.

#### 7.4.J WYNIK — kroki 1-2 (transpilacja + test różnicowy), 2026-07-09 (Fable 5)

Ratyfikowane (wariant „test różnicowy + tap"). Zbudowane: `experiments/cegla2_vocab.md` (zamrożony słownik
prymitywów, prereg), `cegla2_rules.py` (transpilacja taktycznego łańcucha jako reguły-jako-dane),
`cegla2_interpreter.py` (deterministyczny interpreter, zero wywołań 1.0 poza odczytem ramki),
`cegla2_differential.py` (interpreter vs PRAWDZIWY `PlannerCore._create_plan_for_goal`, K8=None, stan
zewnętrzny wstrzyknięty z ramki).

**SHADOW-OF-SELF = 100.00% (1443/1443)** na kombinatorycznym pokryciu gałęzi (forced / fetch-valve /
learn-backoff / MAINTENANCE-themes / saturation / P0-P7 / kaskada non-learning). Transpilacja jest WIERNA
— reguły-jako-dane odtwarzają decyzję 1.0 co do joty. (Test wyłapał 1 realny błąd transpilacji po drodze:
fetch-valve zablokowany oknem MUSI przelecieć dalej, nie zwracać NOOP — naprawione.)

**GŁÓWNA BRAMKA — escape-hatch:** taktyczny łańcuch jest w PEŁNI wyrażalny deklaratywnie nad sub-Turingowym
słownikiem (uporządkowane predykaty + arytmetyka + `fold-first` po celach) — **pułapka Turing-zupełności
NIE wystąpiła** (żadna gałąź nie wymaga pętli/rekurencji użytkownika). „Escape surface" to **3 wartości
zapytań do żywych podsystemów**: `world_model` knowledge-gaps (→ `weak_topic_file` P2.5, `expert_topic` P6)
+ `project_child_material_count`. Kandydat `creative_should_reflect` z 7.4.A okazał się **frameowalny**
(cooldown czasowy z `now`+`last_creative_ts`) → NIE genuine escape.

| miara escape (syntetyk uniform, worst-case) | wynik |
|---|---|
| GENUINE escape KONSULTOWANE (proxy odczytane na ścieżce) | 19.3% (278/1443) |
| GENUINE escape DETERMINUJĄCE (flip proxy zmienia akcję) | **13.4% (194/1443)** |

**Werdykt wstępny (escape-determined 13.4% < próg 15%) — POZYTYWNY, z zastrzeżeniami:** (1) to
UNIFORM syntetyk, który OVER-sampluje gałęzie escape (P2.5/P6); rozkład ŻYWY da niżej — definitywna liczba
na `nietrywialnym podzbiorze` wymaga **tapu (krok 0)**. (2) Escape jest **ELIMINOWALNY**: jeśli tap
snapshotuje te 3 wartości do ramki, escape → 0 i cały łańcuch jest deklaratywny — więc zadaniem tapu jest
m.in. złapać `world_model` gaps + child-material w chwili decyzji. **Ekspresywność Osnowy dla taktycznego
rdzenia = POTWIERDZONA modulo 3 nazwane wartości zewnętrzne.** Następne: tap (dla real-distribution +
per-klasa recall na żywym rozkładzie) → kod do review operatora + restart.

---

## 8. RYZYKA + ANTY-WZORCE

**PO BUDOWLANEMU.** Lista rzeczy, przez które budowy takie jak ta umierają —
i co konkretnie robimy, żeby każda z nich bolała wcześnie i tanio, a nie
późno i drogo.

### 8.1 „Beautiful logging format" (anty-wzorzec nr 1 z NOTES [GRUNT])

Struktura bez efektu behawioralnego. **Obrona ustrojowa:** żaden etap tego
blueprintu nie kończy się „zbudowane" — każdy kończy się PREREJESTROWANYM
progiem behawioralnym z nazwanym baseline'em (cegła 1: AUC/ECE/Brier vs dwa
baseline'y; cegła 2: kappa + faza poprawy; organy: SeamContract z nocną
gwarancją). **Reguła generalna: organ bez prerejestrowanych progów nie
wychodzi z cienia.** Zaliczenia strukturalne („zbudowaliśmy Osnowę") nie
liczą się jako postęp w raportach.

### 8.2 Zlepek specjalistów bez spójności

Cztery mechanizmy ustrojowe (3.2): jeden substrat + kotwiczenie, SeamContract,
jedna pętla, przeciek styku w homeostazie. Ryzyko rezydualne [SPEKULACJA]:
pod presją wydajności organy zaczną obchodzić Osnowę prywatnymi skrótami —
wtedy organizm PO CICHU staje się zlepkiem. Metryka przecieku to termometr,
nie szczepionka; obrona jest dyscyplinarna (code review kontraktów) i tania
tylko póki organów jest mało. Uczciwie: to najsłabsze ogniwo hybrydy
w horyzoncie lat.

### 8.3 Dryf tożsamości przy trenowaniu wag vs continuity

Pełny aparat w 4.4 (kotwiczenie, biografia nadrzędna, dieta-jako-tożsamość,
egzamin pożegnalny, Bramka+Lustro). Ryzyko rezydualne, nazwane: **Lustro jest
skończone** — łapie regresje przewidziane w probe-secie, ślepa plama na
wszystko, czego nie pomyśleliśmy przetestować; egzamin pożegnalny mierzy
kompetencję, nie charakter. Continuity behawioralne ≠ continuity
„fenomenologiczne" i na to drugie metryki nie mamy. Mitygacja częściowa:
probe-set rośnie z każdym incydentem (jak testy regresyjne po bugach).

### 8.4 Scope-creep per filar (każdy filar to potencjalny PhD [GRUNT: VISION])

Kwoty złożoności, wpisane do ustroju:

- Wymiar 3 (przyczyna): świadomie płytki (krawędzie+liczniki+interwencja),
  NIE Pearl. Rozbudowa dopiero po dowodzie użyteczności płytkiej wersji.
- Algebra pewności: m-estymaty+noisy-OR, NIE pełny Bayes.
- Kora/RETE: Python + SQLite, żadnego Rust/custom-DB przed dowodem wąskiego
  gardła.
- Pragmatyka: taksonomia aktów ≤10 klas na start.
- Zasada z ROADMAP [GRUNT]: małe prototypy przed pełnymi implementacjami;
  żaden plank bez mierzalnego kryterium.

### 8.5 Gdzie 4 filary mogą się NIE złożyć (uczciwie, per filar)

1. **Matematyka:** „jeden formalizm" może się okazać unifikacją przez magazyn,
   nie przez algebrę — dwie matematyki (wektorowa i symboliczna) mieszkające
   obok siebie zamiast jednej. Test: czy operacje międzyfilarowe (np. surprise
   → sąd → reguła) dają się pisać bez ręcznego kleju per przypadek.
2. **Logika 5D:** wymiar 3 może zostać „beautiful logging" przyczynowości —
   krawędzie `powoduje`, których nikt nie konsumuje. Test: czy `dlaczego()`
   i `co-jeśli()` są używane przez Bramkę Zmian i K12-następcę w realnych
   decyzjach (licznik użyć).
3. **Lingwistyka:** hidden_intent może być nietrenowalny latami (243
   wiadomości [GRUNT]; destylat 70B niesie biasy nauczyciela bez prawdy
   gruntu). Filar może utknąć na speech-acts + common_ground (co i tak jest
   wartością). Zależność twarda: fix #2.
4. **Kryptoznawstwo:** przy rosnącym udziale wag introspekcja behawioralna
   może się okazać za słaba na obietnicę „wiem, jak się nadpisać" — filar
   zdegraduje do audytu. Częściowa obrona: wszystko decyzyjne jest symboliczne,
   więc rdzeń pozostaje w pełni introspektywny.
5. **Mózg:** Prognosta raz już (jako B0) oblał walidację [GRUNT]; poprawka
   substratu (cechy oceny) to hipoteza. Jeśli po niej nadal nie przewiduje
   porażek lepiej niż kNN bez wag — warstwa-mózg to martwy balast i połowa
   argumentu za hybrydą pada. Wtedy: zostajemy przy Kronikarzu+kNN (mózg
   pamięciowy, płytszy, ale darmowy) i renegocjujemy ambicje filaru.
6. **Całość — dwa stacki na jednego budowniczego:** hybryda AMPLIFIKUJE
   ryzyko wytrwałości (95% wizji umiera w roku 3 [GRUNT: VISION]). Obrona:
   sekwencja cegieł jest tak ułożona, żeby każdy etap zostawiał samodzielną
   wartość (Sędzia użyteczny nawet solo jako kalibrator K9; tap użyteczny
   nawet bez 2.0 jako observability plannera). Monetization gate bez zmian
   [GRUNT]: żadnych pieniędzy, których nie ma; hardware upgrade tylko
   z zarobków Market Agenta.

### 8.6 Mierniki uczciwości (stały panel, raportowany co miesiąc)

| Miernik | Co obnaża |
|---|---|
| udział torów 1-3 vs toru 4 (LLM) w adopcjach reguł | czy „uczenie bez LLM" nie jest fikcją grzecznościową |
| reguły/tydzień przez Bramkę bez człowieka | stall à la CYC (kuratorowane muzeum zamiast organizmu) |
| przeciek styku (round-trip) | cichą erozję jednego umysłu w zlepek |
| ECE per organ + ECE łańcuchów end-to-end | rozjazd kalibracji federacji |
| % decyzji bez LLM w pętli (audit log) | kryterium #1 VISION mierzone, nie deklarowane |
| liczniki użyć `dlaczego()` / `co-jeśli()` | czy przyczynowość jest konsumowana, czy dekoracyjna |

---

## 9. Co dalej — decyzje dla Eryka

Ten dokument niczego nie uruchamia. Do zatwierdzenia (osobno, każde jest
niezależną decyzją):

1. **Renegocjacja zdania VISION** (4.5): „nie trenujemy wag, które niosą
   tożsamość" zamiast „nie trenujemy wag". TAK/NIE.
2. **Trzy tanie fixy w 1.0** (5.1) — wchodzą w normalną kolejkę pracy nad 1.0.
3. **Cegła 1 (Sędzia)** z prerejestrowanym protokołem 7.2 — start w wolnym
   paśmie, poza sekwencją DH (bez kolizji z DEVELOPMENT_SEQUENCE — to osobne
   pasmo badawcze, jak market).
4. **Nazewnictwo** — Osnowa / Dyrygent / Kronikarz / Prognosta / Konsolidator /
   Sędzia / Lustro / Księga Tożsamości — do akceptacji lub przechrzczenia.

Kolejność dalszych cegieł (2: goal-ranking shadow; 3+: organy wg zasady
niemowlęctwa) — decyzje na checkpointach, po wynikach, zgodnie z filozofią
ROADMAP: dane decydują.

---

## Słownik nazw (dla szybkiego wejścia w dokument)

| Nazwa | Co to |
|---|---|
| **Osnowa** | wspólny substrat: typowany graf sądów o podwójnych współrzędnych (symbol pierwotny, wektor pochodny); jak osnowa geodezyjna na budowie |
| **Sąd** | jedna cegła wiedzy (fakt/relacja/przyczyna/epizod/meta/reguła/program/organ) z pewnością Beta, czasem bitemporalnym, proweniencją i uzasadnieniami |
| **Interpreter + Dyrygent** | deterministyczny kierownik budowy: reguły/programy decydują, pętla POSTRZEGAJ→…→REFLEKTUJ; zero LLM, zero wag |
| **Kronikarz / Prognosta / Konsolidator** | mózg: archiwum epizodów z kojarzeniem kNN / trenowany predyktor stanu z surprise / nocna destylacja doświadczenia w wagi |
| **S-SĘDZIA, S-ODŹWIERNY, S-PLANISTA, S-PARSER, S-AKTY, S-RELACJE, S-WEKTOR, S-GŁOS** | specjaliści-organy: kalibracja, pre-filtr autonomii, ranking celów, ekstrakcja, akty mowy, relacje, embeddingi, głos/parser LLM |
| **SeamContract / przeciek styku** | kontrakt wyjścia organu z nocnie mierzoną gwarancją / round-trip metryka szczelności styku neuron↔symbol w homeostazie |
| **Bramka Zmian / Lustro / zasada niemowlęctwa** | pipeline każdej zmiany siebie / zamrożone probe-suites behawioralne / cień→doradczy→aktywny dla każdego nowego komponentu |
| **Księga Tożsamości / egzamin pożegnalny / dieta-jako-tożsamość** | append-only łańcuch hashy zmian siebie / test następcy organu (≥95% bufora powtórek) / tożsamość organu = dataset+ewal+przepis, nie wagi |

---

*Zasada przewodnia: tożsamość w danych, umiejętności w wagach, decyzje
w regułach, dowody w liczbach. Maria nie dostaje inteligencji z zewnątrz —
kompresuje własne życie w programy i nazywa wzorce, które przeżyły.*
