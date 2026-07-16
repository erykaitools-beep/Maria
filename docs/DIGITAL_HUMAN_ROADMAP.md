# M.A.R.I.A. - Digital Human Roadmap v2.0

> Roadmapa architektoniczna: od cognitive AI do personal digital human.
> Autor: Eryk (wizja) + Claude (architektura). Data: 2026-04-12 (v1.1),
> status pass 2026-07-06 (v2.0 -- wizja bez zmian, statusy urealnione).
>
> **Podzial trzech dokumentow:** ten plik = WIZJA (co budujemy i po co);
> `docs/SYSTEM_STATUS.md` + `docs/DIGITAL_HUMAN_STATUS.md` = STAN (co zyje);
> `docs/DEVELOPMENT_SEQUENCE.md` = KOLEJNOSC (co dalej -- SSoT budowy).
> Przy rozjezdzie statusow wierz STAN/KOLEJNOSC, nie tej roadmapie.

## A. Executive Vision

Maria nie jest kolejnym AI assistantem. Jest **trwalym cyfrowym bytem** ktory zyje na sprzecie operatora, zna go, rozumie kontekst jego zycia, i dziala w jego imieniu w swiecie cyfrowym - z pelna kontrola i audytem.

Roznica miedzy chatbotem a digital human: chatbot **odpowiada**. Digital human **zyje, obserwuje, planuje, dziala i raportuje** - nawet gdy nikt z nim nie rozmawia.

Maria juz to czesciowo robi (homeostasis 24/7, autonomiczna nauka, proactive contact). Roadmapa prowadzi z "cognitive AI ktora sie uczy" do "digital human ktory jest uzyteczny w codziennym zyciu operatora".

## B. Architectural Definition of "Digital Human"

Digital human w kontekscie M.A.R.I.A. to system ktory spelnia **6 warunkow jednoczesnie**:

| Warunek | Test | Maria dzis (2026-07-06) |
|---------|------|------------|
| **Ciaglosc** | Dziala 24/7, pamieta wczoraj i za miesiac | TAK (homeostasis 24/7, JSONL, warm recovery; UWAGA: restore backupu NIGDY nie testowany -- patrz F.5) |
| **Percepcja** | Wie co sie dzieje w swiecie operatora | W DUZEJ MIERZE (Telegram, Vision: ruch MOG2 + VisionMemory + PL captions, pogoda+swieta z salience w porannym briefie; NADAL brak kalendarza/maili) |
| **Rozumowanie** | Planuje, reflektuje, uczy sie z bledow | TAK (K5-K13 + Super-META E0-E4 armed) |
| **Dzialanie** | Wykonuje realne zadania w swiecie cyfrowym | CZESCIOWO, ROSNIE (FS_WRITE live 06-21, pierwszy realny write+undo na zywym OpenClaw 06-24, outbox propose armed, /wyslij pliki; silnik workflow kompletny ale NIGDY nie odpalony) |
| **Relacja** | Zna operatora gleboko, buduje zaufanie | CZESCIOWO (OperatorModel SSoT 05-30, RhythmDetector, pamiec rozmow Phase 20; ActiveLearner zbudowany-uspiony, RelationshipTracker nie istnieje) |
| **Samoswiadomosc** | Wie co umie, czego nie umie, ile kosztuje | W DUZEJ MIERZE (self_perception Phase 18 OBSERVED, CapabilityManifest + honesty tail w czacie, SelfContext; ekonomia D.7 = jedyny niezbudowany kawal) |

**Glowna luka (aktualizacja 2026-07-06):** haslo "Maria duzo mysli, malo robi"
juz nie opisuje stanu -- reka zyje, a pierwszy projekt operatora domknal sie
3/3 (07-05). Uczciwe luki dzis: (1) POLACZENIE gotowych maszyn w dostawe
(workflow nigdy nie odpalony, /wf approve bez produkcyjnych callerow),
(2) zaufanie liczone na slepej kartotece (Faza 7 wired-dormant, rejestrator
incydentow odpiety), (3) ekonomia D.7 nietknieta, (4) kalendarz+mail w
percepcji, (5) Relacja bez RelationshipTracker.

## C. Fazy Rozwoju

| # | Nazwa | Cel | Status |
|---|-------|-----|--------|
| 1 | **Operator Understanding** | Maria naprawde rozumie operatora | DONE |
| 2 | **Self-Model Maturity** | Maria uczciwie wie kim jest i co umie | DONE |
| 3 | **Operational Perception** | Maria widzi caly swiat operacyjny | DONE |
| 4 | **Digital Hands** | Maria potrafi cos ZROBIC | DONE |
| 5 | **Workflow Orchestration** | Maria prowadzi zlozone procesy | DONE |
| 6 | **Environment Adaptation** | Maria dopasowuje sie do kontekstu | DONE |
| 7 | **Trust & Autonomy Graduation** | Maria zarabia na samodzielnosc | ZBUDOWANE, WIRED-dormant (kod K20 od 04-12: TrustScorer/IncidentMemory/AutoPromotion, tick Phase 16 liczy trust na zywo ~0.80, /trust dziala; AUTO_PROMOTION_ENABLED OFF, rejestrator incydentow ODPIETY na zywej sciezce -- uzbrojenie dopiero po uczciwej kartotece, patrz G) |

### Szesc warstw koncepcyjnych (mapping na fazy):

1. **Identity / Being** -> Faza 2 (Self-Model Maturity) + cross-cutting (MasterPrompt)
2. **Perception** -> Faza 3 (Operational Perception) + istniejace K1
3. **Mind** -> Istniejace K5-K13 cognitive core
4. **Digital Body / Action Layer** -> Faza 4-5 (Digital Hands + Workflow)
5. **Relationship Layer** -> Faza 1 (Operator Understanding) + Faza 7 (Trust)
6. **Environment Layer** -> Faza 6 (Environment Adaptation)

---

### Podkategoria scalajaca: Super-META (Swiadomosc Sytuacyjna)  [E0-E4 DONE: E0/E1/E2 2026-06-26, E3/E4 2026-06-27; flagi ARMED potw. 07-04]

**Czym jest:** NIE nowa Faza ani nowy organ -- warstwa CROSS-CUTTING ktora SPAWA juz gotowe
klocki Faz 1+2+3 w jeden "kontekst sytuacyjny" konsultowany przez kazdy organ. Nie mylic z
celem META (`goal-meta-learn`): cel META = MISJA nauki; Super-META = warstwa
WIEDZY-O-SOBIE-I-SYTUACJI (brygadzista co wie co kazdy organ widzial/wie).

**Dlaczego teraz:** organy sa juz swiadome i wielo-LLM (wzrok=LLaVA->dracarys, rozmowa=Ollama/
NIM, planista=qwen3, nauka=dracarys 70b). Ale NIE dziela jednego "co teraz wiem o sytuacji".
Kawalki istnieja, rozproszone: `operator_model` (z kim), `self_perception` (co umiem),
`awareness/context_builder` (nauka/wiedza/system). Brakuje: pamieci wzroku (opis znika po
wyslaniu) + scalenia w jedno miejsce + zeby organy sie SLYSZALY.

**Efekt koncowy:** Maria jako JEDNA spojna osoba. "co widzialas?" -> pamieta. Rozmawiasz ->
wie z kim i co przed chwila zobaczyla. Wzrok, rozmowa, planista czytaja ten sam kontekst.

**Etapy (budowlanka: fundament -> spawy -> kran; kazdy flag-gated observe->cutover, commity+testy):**
- **E0 Fundament - SelfContext (agregator): [DONE 2026-06-26]** read-only obiekt scalajacy CO JUZ
  JEST -- self_perception + operator_model + context_builder + stan misji META. Zero nowych danych,
  samo scalenie. `agent_core/awareness/self_context.py` (`SelfContext.build()`/`format_for_telegram`),
  `ctx.self_context`, komenda `/selfcontext`. KAZDE zrodlo w try/except (awaria 1 organu nie psuje
  calosci). 9 testow. Widac: `/selfcontext` pokazuje cala sytuacje w jednym miejscu.
- **E1 Pamiec wzroku (1. widoczny spaw): [DONE 2026-06-26]** wzrok zapisuje co zobaczyl (ostatnie N
  opisow + czas). `agent_core/vision/vision_memory.py` (ring buffer N=10, thread-safe, persist do
  `meta_data/vision_memory.json`), zapis w `VisionAdvisor._describe_and_notify` (po tlumaczeniu PL),
  `ctx.vision_memory`, slot `vision` w SelfContext, komendy `/lastseen` + `/cowidzialas`. 14 testow.
  Widac: "co ostatnio widzialas?" -> realna odpowiedz z pamieci.
- **E2 Rozmowa konsultuje SelfContext: [DONE 2026-06-26, `7e3a2d4`, flaga `SELF_CONTEXT_CHAT_ENABLED`=true]**
  ogon promptu czatu ciagnie operator_model + ostatni opis wzroku + zdolnosci. Widac: Maria wie
  z kim mowi i co zobaczyla ("widzialam ruch 5 min temu -- to bylas Ty?").
- **E3 Organy sie slysza (cross-organ): [DONE 2026-06-27, `378a4ed`+`bfd99d1`, flaga `VISION_SUPPRESS_WHEN_PRESENT`=true]**
  wzrok pomija ping gdy wie z czatu ze operator obecny; planista publikuje focus do SelfContext.
- **E4 Super-META: petla swiadomosci: [DONE 2026-06-27, `8b8408f`, flaga `PROACTIVE_SITUATIONAL`=true]**
  proactive konsultuje pelny obraz ("teraz pracuje nad Y"). ZOSTALO (ceg. inwentarzowa): po oknie
  obserwacji flip defaultow w kodzie na ON + zdjecie linii z .env.

**Zalezy od:** Faza 1, 2, 3 (DONE). Istnieje: operator_model, self_perception, context_builder,
vision. Nowe: vision-memory (E1), SelfContext agregator (E0), wiring w organy (E2-E4).
**Ryzyka (per cross-cutting D):** budzet kontekstu (E2/E4 trzymac krotko, nie rozdac promptow);
nie dublowac `context_builder` (rozszerzyc, nie zastapic); dane operatora LOKALNE (privacy #5).
**Mapping na 6 warstw:** scala warstwe 1 (Identity) + 2 (Perception) + 5 (Relationship).

---

### FAZA 1: Operator Understanding

*"Maria naprawde mnie rozumie"*

**Cel:** Maria buduje relacyjno-operacyjny model operatora - nie jako kartoteke danych, ale jako zywe rozumienie osoby z ktora wspolpracuje.

**5 wymiarow modelu operatora:**

| Wymiar | Przyklady | Zrodlo |
|--------|-----------|--------|
| **Durable Facts** | imie, zawod, miasto, sprzet, jezyki | rozmowy + jawne podanie |
| **Operational Preferences** | kiedy chce notyfikacje, jaki ton, ile szczeg., co go irytuje | feedback loop z rozmow |
| **Day Rhythm / Routine** | wstaje ~7, praca 9-17, piatek = krotszy, weekend = wolne | pattern detection z historii kontaktow |
| **Current Context / Load** | "dzis mam deadline", "jestem chory", "jade na urlop" | jawne + inference z rozmow |
| **Privacy Boundaries** | czego NIE pytac, czego NIE logowac, co jest tabu | jawne ustawienie + eskalacja przy watpliwosci |

**Co musi powstac:**
- **OperatorModel** - rozszerzenie UserProfile o 5 wymiarow, structured + freeform, z confidence per fakt
- **RelationshipTracker** - Maria pamieta kontekst relacji: od kiedy sie znamy, co wspolnie zrobilismy, czego sie o operatorze nauczyla
- **ActiveLearner** - Maria zadaje max 1 pytanie dziennie (Telegram), naturalnie w kontekscie rozmowy, nie ankieta
- **RhythmDetector** - analiza historii Telegram timestamps + rozmow -> wzorce dnia/tygodnia
- **ContextInference** - "operator nie odpowiada od 10h w dzien roboczy = prawdopodobnie zajety, nie wysylaj" vs "weekend = normalnie milczy"
- **PrivacyGuard** - operator jawnie definiuje granice, Maria NIGDY ich nie przekracza

**Capability contracts:**
- K14: OperatorModel - 5-dimensional operator understanding with confidence scoring
- K14.1: ActiveLearner - contextual questioning (max 1/day, natural, not survey-like)
- K14.2: RhythmDetector - temporal pattern extraction from interaction history
- K14.3: PrivacyGuard - hard boundaries, operator-defined, non-overridable

**Dependencies:** UserProfile (istnieje), ConversationMemory (istnieje), TimeAwareness (istnieje), Proactive Contact (istnieje)

**Ryzyko:** Uncanny valley - Maria wie "za duzo" a operator czuje sie niekomfortowo. Mitygacja: transparency (Maria mowi SKAD wie), privacy boundaries, operator moze wymazac dowolny fakt.

**Kryterium ukonczenia:** Maria generuje "Operator Brief" (wewnetrzny dokument) ktory operator czyta i mowi "tak, to trafne". Plus: poranna wiadomosc jest spersonalizowana pod rytm dnia.

**Fake progress:** 50 pol w formularzu profilu. Model musi rosnac organicznie z rozmow i obserwacji, nie z ankiety onboardingowej.

---

### FAZA 2: Self-Model Maturity

*"Maria uczciwie wie kim jest"*

**Cel:** Maria utrzymuje prawdziwa, aktualna reprezentacje siebie - co umie, czego nie umie, jaki jest jej stan, jakie ma ograniczenia - i komunikuje to operatorowi uczciwie.

**Co musi powstac:**
- **CapabilityManifest** - lista tego co Maria REALNIE potrafi robic (nie co jest w kodzie, ale co dziala i bylo przetestowane)
- **LimitationRegistry** - jawna lista ograniczen
- **ConfidenceMap** - per-capability confidence
- **StateReporter** - na zadanie lub proaktywnie
- **HonestyProtocol** - Maria NIGDY nie twierdzi ze cos umie jesli tego nie przetestowala
- **GrowthAwareness** - Maria identyfikuje swoje braki jako cele rozwoju

**Capability contracts:**
- K15: SelfModel - maintained manifest of capabilities, limitations, and confidence levels
- K15.1: StateReporter - structured self-status on demand and proactive
- K15.2: HonestyProtocol - no overclaiming, explicit uncertainty, "I don't know" as valid
- K15.3: GrowthAwareness - limitations as identified growth targets with cost/benefit

**Dependencies:** Introspection (istnieje), UserFacingSelfModel (istnieje, V3), K12 Self-Analysis (istnieje), K4 Evaluation (istnieje)

**Ryzyko:** Self-model drift - Maria twierdzi ze cos umie bo kiedys umiala, ale code changed. Mitygacja: periodic capability probing.

**Kryterium ukonczenia:** Operator pyta "co umiesz?" i dostaje uczciwa, konkretna odpowiedz z confidence levels.

**Fake progress:** Piekny dashboard "Maria capabilities" ktory jest statyczny i recznie pisany. Manifest musi byc auto-generowany i auto-weryfikowany.

---

### FAZA 3: Operational Perception

*"Maria widzi caly swiat operacyjny"*

**Cel:** Maria postrzega nie tylko swoj wewnetrzny stan, ale pelny kontekst operacyjny.

**4 kanaly percepcji:**

| Kanal | Przyklady | Priorytet |
|-------|-----------|-----------|
| **External World** | pogoda, pora roku, dni wolne, zdarzenia lokalne | wysoki |
| **Local System** | logi systemd, uslugi, cron, siec (rozszerzenie istniejacego) | sredni |
| **Files / Tasks / Workspace** | pliki w input/, stan taskow, zmiany w docs/ | wysoki |
| **Messages / Calendar** | Telegram history, przyszlosc: iCal, email headers | niski |

**Co musi powstac:**
- **ExternalSensors** - zunifikowany interfejs: WeatherSensor, CalendarSensor, HolidaySensor
- **SystemSensor v2** - "czy maria.service miala restart?", "czy Ollama odpowiada?", "ile miejsca na storage?"
- **WorkspaceSensor** - obserwuje input/, docs/, meta_data/
- **PerceptionFusion** - laczy kanaly w spojny obraz
- **SalienceFilter** - co jest WARTE uwagi operatora? Default = nie mow.

**Capability contracts:**
- K16: OperationalPerception - unified multi-channel perception with salience filtering
- K16.1: ExternalSensors - weather, calendar, holidays (pluggable)
- K16.2: WorkspaceSensor - file/task/log change detection
- K16.3: SalienceFilter - "worth telling?" decision based on OperatorModel (Faza 1)

**Dependencies:** Faza 1 (OperatorModel potrzebny do SalienceFilter), K1 Unified Perception (istnieje)

**Ryzyko:** Information overload. Mitygacja: SalienceFilter obowiazkowy.

**Kryterium ukonczenia:** Poranna wiadomosc uwzglednia pogode + kontekst operatora.

**Fake progress:** 10 API bez SalienceFilter. 100 danych bez filtra = spam gorszy niz brak danych.

---

### FAZA 4: Digital Hands

*"Maria potrafi cos ZROBIC"*

**Cel:** Maria wykonuje realne zadania cyfrowe - nie tylko mysli i mowi, ale dziala.

**Co musi powstac:**
- **ActionRegistry v2** - rozszerzenie CapabilityRouter o akcje zewnetrzne: file ops, web research, email draft, notatki
- **TaskExecutor** - wielokrokowe zadania z checkpointami
- **ResultValidator** - Maria sprawdza czy akcja sie udala
- **SelfRepair** - Maria wykrywa wlasne bledy i probuje je naprawic (via Claude/Codex + OpenClaw). Korzysta z Self-Model (Faza 2) - wie CO jest zepsute.
- **ExecutionJournal** - pelny audit trail kazdej akcji w swiecie

**Capability contracts:**
- K17: ActionExecution - reliable multi-step task execution with validation
- K17.1: SelfRepair - detect failure + attempt fix + escalate if can't
- K17.2: ExecutionAudit - every action logged, reversible where possible

**Dependencies:** OpenClaw (istnieje), Claude/Codex CLI (istnieje), K7 Autonomy (istnieje), K10 Safety (istnieje), Effector Safety Envelope (istnieje), Faza 2 (Self-Model dla SelfRepair)

**Ryzyko:** Bezpieczenstwo. Zasada: OBSERVE -> SUGGEST -> CONFIRM -> BOUNDED.

**Kryterium ukonczenia:** Maria potrafi wykonac 3-krokowe zadanie z pelnym auditem.

**Fake progress:** "Universal tool framework" zamiast 5 konkretnych, dzialajacych narzedzi.

---

### FAZA 5: Workflow Orchestration

*"Maria prowadzi zlozone procesy"*

**Co musi powstac:**
- **WorkflowEngine** - definiowalne sekwencje akcji z warunkami, branching, retry
- **DelegationManager** - Maria deleguje pod-zadania do odpowiednich narzedzi
- **ProgressReporter** - operator dostaje update'y w trakcie
- **InterruptHandler** - operator moze w kazdej chwili zatrzymac, zmienic, cofnac

**Capability contracts:**
- K18: WorkflowExecution - multi-step process with checkpoints and rollback
- K18.1: DelegationProtocol - which tool/model for which subtask

**Dependencies:** Faza 4 (Digital Hands musza dzialac solidnie), K8 Deliberation (istnieje)

**Ryzyko:** Over-engineering. Start prosty: linearne sekwencje. Branching dopiero gdy potrzebny.

**Kryterium ukonczenia:** Maria prowadzi powtarzalny workflow bez interwencji.

**Fake progress:** Visual workflow editor. Maria to nie Zapier. Workflow kodem/konfiguracja.

---

### FAZA 6: Environment Adaptation

*"Maria dopasowuje sie do kontekstu"*

**Co musi powstac:**
- **EnvironmentProfile** - definicja trybu (home/operator/creator/business) z roznymi priorytetami, toolami, tonem
- **AdapterLayer** - pluggable adaptery per tryb
- **ModeSwitch** - Maria rozpoznaje kontekst lub operator przelacza recznie
- **CoreStability** - K1-K13 + identity NIE ZMIENIA SIE miedzy trybami. Zmienia sie tylko warstwa narzedzi i priorytetow.

**Capability contracts:**
- K19: EnvironmentAdapter - pluggable context layer over stable core
- K19.1: ModeDetection - auto-detect or manual switch

**Dependencies:** Faza 1-5 (core musi byc stabilny i uniwersalny)

**Ryzyko:** Rozmycie tozsamosci. Tryb zmienia CO robi, nie KIM jest.

**Kryterium ukonczenia:** Maria dziala w 2 roznych trybach z roznymi narzedziami ale spojna osobowoscia.

**Fake progress:** 6 trybow na papierze. Zaczac od 1 ktory dziala.

---

### FAZA 7: Trust & Autonomy Graduation

*"Maria zarabia na coraz wiecej samodzielnosci"*

**Co musi powstac:**
- **TrustScore** - obliczany z historii: ile zadan poprawnych, ile poprawek, ile reject
- **AutoPromotion** - gdy TrustScore > threshold, Maria proponuje awans uprawnien
- **IncidentMemory** - Maria pamieta swoje bledy i unika ich powtorzenia
- **AutonomyDashboard** - operator widzi co Maria moze robic sama, co wymaga approval

**Capability contracts:**
- K20: TrustGraduation - earned autonomy based on track record
- K20.1: IncidentLearning - structured failure memory

**Dependencies:** Faza 3-5 (musi byc co mierzyc), K7 Autonomy (istnieje), Approval Queue (istnieje)

**Kryterium ukonczenia:** Maria sama zaproponowala awans z OBSERVE do SUGGEST w jednej kategorii, operator zatwierdzil, Maria dziala na nowym poziomie bez regresji przez 7 dni.

**Fake progress:** Automatyczne dawanie uprawnien bez track record. Trust musi byc ZAROBIONY.

---

## D. Cross-cutting Requirements

Rzeczy ktore musza dzialac **w kazdej fazie**:

1. **Audytowalnosc** - kazda decyzja, akcja, zmiana stanu logowana w JSONL. Istnieje (K10, tracing). Rozszerzac.
2. **Operator control** - kill switch zawsze dziala. Operator > Maria. Zawsze.
3. **Graceful degradation** - brak internetu = Maria dziala lokalnie. Brak NIM = Ollama fallback. Juz zaimplementowane.
4. **Backward compatibility** - nowa faza nie lamie poprzedniej. Testy regresyjne obowiazkowe.
5. **Privacy by design** - dane operatora lokalne. Zaden external API nie dostaje profilu operatora.
6. **Resource awareness** - Maria nie moze zjesc 100% CPU/RAM. Homeostasis mode regulator juz to pilnuje.
7. **Economic Self-Awareness (parallel layer)**
   - CostTracker - ile Maria kosztuje miesiecznie (prad, NIM API, sprzet amortyzacja)
   - ValueLog - co Maria zrobila pozytecznego (zadania, alerty, oszczednosci czasu)
   - ResourceBudget - ile tokenow NIM zostalo, ile storage, ile RAM
   - GrowthCostEstimate - "wiecej RAM = ~400 PLN, efekt: moge ladowac 2 modele jednoczesnie"
   - Wdrazane przyrostowo: CostTracker w Fazie 3, ValueLog w Fazie 4, GrowthCostEstimate w Fazie 2
   - Komunikowane w weekly review, nie osobny dashboard
8. **Tozsamosc spojna** - Maria jest ta sama Maria w REPL, Telegramie, Web UI. MasterPrompt jest single source of truth.

## E. What NOT to Build Too Early

| Pulapka | Dlaczego nie teraz |
|---------|-------------------|
| Voice / TTS / STT | Dekoracja. Telegram + Web UI wystarczaja. Voice gdy core dziala |
| Multi-user | Maria jest PERSONAL digital human. Jeden operator. Multi-user to inny produkt |
| Plugin marketplace | Over-engineering. Maria ma AdapterLayer, nie App Store |
| Mobile app | ZREWIDOWANE 06-17: natywna apka Flutter POWSTALA (token auth + Skrzynka approve-flow). Kwietniowa ocena byla bledna, bo nie przewidziala potrzeby natywnego approve-flow -- lekcja: "pulapka" moze dojrzec do narzedzia, gdy pojawi sie core-wartosc (tu: zatwierdzanie akcji Marii z kieszeni) |
| "AI personality customization" | Osobowosc Marii ewoluuje organicznie (TraitEvolver). "Wybierz osobowosc" to gadget |
| Cloud hosting | Maria jest LOKALNA. To jest jej przewaga, nie ograniczenie |

## F. Top Architectural Risks

1. **Complexity ceiling** - ~205k linii py (stan 07-06; w kwietniu bylo ~60k). Kazda faza dodaje. Bez agresywnego upraszczania, complexity zabije velocity. Mitygacja: kazda faza zaczyna sie od cleanup.

2. **LLM dependency fragility** - Ollama + NIM. Model quality zmienia sie z wersji. Mitygacja: model_registry abstraction (istnieje), benchmarki per upgrade.

3. **Operator fatigue** - Za duzo notyfikacji = operator ignoruje Marie. Mitygacja: SalienceFilter (Faza 3), batching, quiet hours (istnieje).

4. **Safety vs usefulness tension** - Za duzo gatekeeping = Maria nic nie robi. Za malo = robi glupie rzeczy. Mitygacja: graduated autonomy (Faza 7).

5. **Single point of failure** - Jeden mini PC. Dysk padnie = Maria znika. Mitygacja: backup cron 03:00 (codziennie). UWAGA (korekta 07-06): GitHub NIE jest backupem zywego systemu -- origin niesie TYLKO sanityzowany snapshot `main` (ADR-029). **DRILL RESTORE WYKONANY 2026-07-06 (PASS)**: backup zdrowy (146k linii JSONL, 0 uszkodzonych), wykryte dziury zalatane (backup.sh rozszerzony o git bundle = kod+471 lokalnych commitow, market-agent, notatki, crontab, systemd unit), repo wskrzeszone z bundla HEAD-identycznie. Procedura: `docs/RESTORE.md`. Zostalo: nawyk kopii USB na wypadek utraty CALEGO PC (dwa dyski chronia tylko przed padem jednego).

## G. Tor wykonawczy (po-kwietniowy) i dalsza droga

Kwietniowe "Immediate Next Milestones" (OperatorModel v1, CapabilityManifest,
WeatherSensor+MorningBrief) sa dawno DONE (OperatorModel SSoT 05-30; K15
`operator/capability_manifest.py`; `weather/` + poranny brief + hydration
nudge). Ponizej rzeczywisty tor po-kwietniowy i uzgodniona dalsza droga
(sesja planistyczna 2026-07-06: 13-agentowe rozpoznanie -> 3 warianty ->
adwersaryjna weryfikacja; Eryk zatwierdzil kolejnosc).

### Drabina DH -- szczeble wykonane

| Szczebel | Status |
|----------|--------|
| **DH-A odwracalnosc** (undo journal+execute) | LIVE na zywym OpenClaw 06-24/25 (Maria napisala i sama cofnela plik); undo-suggest armed-uspiony |
| **Super-META E0-E4** (swiadomosc sytuacyjna) | DONE + flagi ARMED (06-26/27); zostal flip defaultow po oknie obserwacji |
| **DH-B drzewa projektow** (rollup+deadline) | built 06-22, ARMED=observe 07-04; 1. projekt operatora 3/3 ACHIEVED 07-05; dowod rollup KOMPLETNY (282+ poprawnych decyzji observe). ODKRYCIE 07-06: flaga deadline byla MARTWYM KABLEM na zywym demonie (czytana tylko przez porzucone entrypointy) -- naprawione (`f6ba962`). REAP: rekomendacja trwale OFF (flaga binarna bez observe, nie oszczedza celow USER) |
| **DH-C bramka zdolnosci** | built 06-22 + fix sygnalow 06-28; cisza observe = zdrowa (16/16 dostepnych; 702 przedfixowe bloki w archiwum /mnt/storage) |

### Dalsza droga (uzgodnione 2026-07-06: Warsztat -> Kartoteka -> Tasma)

1. **Zamkniecie TIER 2** -- ROLLUP=cutover PRZED 2026-07-09 22:57 (pierwsze
   samodzielne domkniecie projektu + proaktywny ping "cel osiagniety");
   DEADLINE=cutover dopiero po zywych liniach `[DEADLINE/observe]`
   (oczekiwane ~07-08 wieczor na projekcie funding po naprawie kabla);
   projekt #2 przez `/project` jako drugi punkt danych.
2. **DH-C arming** -- `/drill_capability` (drill MUSI wymusic zaplanowanie
   wylaczonej akcji, inaczej nic nie pokaze) + alarm manifestu w migawce
   Phase 18, potem `CAPABILITY_GATE_ENABLED=1`.
3. **WARSZTAT** (pokoj Tier 3 #1: workflow, wylacznie kran operatora) --
   kontrakt granic na papierze (K8=nauka, workflow=dostawa); pierwszy
   przebieg w historii (`/wf start`, zero kodu -- silnik NIGDY nie odpalil);
   pierwszy lancuch rak `note_pipeline` (zapisz -> sprawdz -> zamelduj);
   zawory: `/wf approve` (dzis zero callerow = zakleszczenie krokow z
   aprobata) + parytet K7 (dzis workflow omija bramki plannera). STOP przed
   autonomia.
4. **KARTOTEKA** (Faza 7 uczciwie) -- ozywic rejestrator incydentow
   (odpiety: `record_incident` za early-returnem CapabilityRouter w
   `action_executor.py`), naprawic podwojne liczenie resolve, tydzien
   obserwacji `/trust` (spadek = sukces pomiaru, nie regresja),
   `[AVOID/observe]`; dolozyc widocznosc dowodow REKI w TrustScorer (dzis
   czyta tylko cele/approvals -- dowod efektorowy nie wchodzi do formuly).
   Awans OBSERVE->SUGGEST dopiero po >=10 zajournalowanych akcjach reki.
5. **TASMA** (dostawa) -- projekt konczy sie PLIKIEM w Telegramie;
   `WORKFLOW_AUTOCREATE` przez flag->observe->cutover; autonomia NA KONCU,
   na zarobionych dowodach (krytyk: bez punktow 3+4 to autonomia na kredyt).

### Zaprawa (miedzy deskami, nie osobne deski)

- ~~**Drill RESTORE backupu** (F.5)~~ -- **DONE 2026-07-06 (PASS)**: dusza
  zdrowa, dziury zalatane (kod+git/market/notatki/config w backupie od dzis),
  procedura w `docs/RESTORE.md`. Nastepny drill ~kwartalnie.
- Notatnik rozumowania: dedup + rotacja + `/myslenie podsumowanie`; synteza
  wzorcow DOPIERO na czystym korpusie (do 07-06 korpus = 99.6% monokultura
  nocnej petli creative; kran zakrecony `0039116`).
- Decyzje flag uspionych z Erykiem: `ACTIVE_LEARNER_ENABLED`,
  `HONESTY_HINT_ENABLED`, `SELF_DEV_JOURNAL_ENABLED` -- uzbroic albo wpisac
  "celowo OFF" w reference-env-flags.
- Swiadomie ODLOZONE (zapisane, nie zgubione): ekonomia D.7 (re-scope przy
  monetization gate), kalendarz+mail w percepcji, RelationshipTracker,
  vision-grounding (czeka na sprzet), voice (north-star), autonomiczny
  producent drzew podcelow (wymaga swiezego przegladu kolizji z K8).

Szczegolowy backlog i kolejnosc -> `docs/DEVELOPMENT_SEQUENCE.md`.

---

*Ostatnia aktualizacja: 2026-07-06*
*Wersja: 2.0 (status pass: statusy urealnione po 13-agentowym audycie; wizja
i architektura v1.1 nietkniete. v1.1: 2026-04-12, korekta Eryka -- relacyjny
operator model, pelna percepcja operacyjna, self-model jako osobna faza,
ekonomia jako cross-cutting)*
