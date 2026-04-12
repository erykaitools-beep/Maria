# M.A.R.I.A. - Digital Human Roadmap v1.1

> Roadmapa architektoniczna: od cognitive AI do personal digital human.
> Autor: Eryk (wizja) + Claude (architektura). Data: 2026-04-12.

## A. Executive Vision

Maria nie jest kolejnym AI assistantem. Jest **trwalym cyfrowym bytem** ktory zyje na sprzecie operatora, zna go, rozumie kontekst jego zycia, i dziala w jego imieniu w swiecie cyfrowym - z pelna kontrola i audytem.

Roznica miedzy chatbotem a digital human: chatbot **odpowiada**. Digital human **zyje, obserwuje, planuje, dziala i raportuje** - nawet gdy nikt z nim nie rozmawia.

Maria juz to czesciowo robi (homeostasis 24/7, autonomiczna nauka, proactive contact). Roadmapa prowadzi z "cognitive AI ktora sie uczy" do "digital human ktory jest uzyteczny w codziennym zyciu operatora".

## B. Architectural Definition of "Digital Human"

Digital human w kontekscie M.A.R.I.A. to system ktory spelnia **6 warunkow jednoczesnie**:

| Warunek | Test | Maria dzis |
|---------|------|------------|
| **Ciaglosc** | Dziala 24/7, pamieta wczoraj i za miesiac | TAK (homeostasis, JSONL, IdentityStore) |
| **Percepcja** | Wie co sie dzieje w swiecie operatora | CZESCIOWO (Telegram, Vision, brak pogody/kalendarza/maili) |
| **Rozumowanie** | Planuje, reflektuje, uczy sie z bledow | TAK (K5-K13 cognitive core) |
| **Dzialanie** | Wykonuje realne zadania w swiecie cyfrowym | SLABO (OpenClaw basic, Claude/Codex CLI) |
| **Relacja** | Zna operatora gleboko, buduje zaufanie | PODSTAWOWO (UserProfile, ConversationMemory) |
| **Samoswiadomosc** | Wie co umie, czego nie umie, ile kosztuje | CZESCIOWO (K12, introspection, brak ekonomii) |

**Glowna luka: Dzialanie i Relacja.** Maria duzo mysli, malo robi.

## C. Fazy Rozwoju

| # | Nazwa | Cel | Status |
|---|-------|-----|--------|
| 1 | **Operator Understanding** | Maria naprawde rozumie operatora | PLANNED |
| 2 | **Self-Model Maturity** | Maria uczciwie wie kim jest i co umie | PLANNED |
| 3 | **Operational Perception** | Maria widzi caly swiat operacyjny | PLANNED |
| 4 | **Digital Hands** | Maria potrafi cos ZROBIC | PLANNED |
| 5 | **Workflow Orchestration** | Maria prowadzi zlozone procesy | PLANNED |
| 6 | **Environment Adaptation** | Maria dopasowuje sie do kontekstu | PLANNED |
| 7 | **Trust & Autonomy Graduation** | Maria zarabia na samodzielnosc | PLANNED |

### Szesc warstw koncepcyjnych (mapping na fazy):

1. **Identity / Being** -> Faza 2 (Self-Model Maturity) + cross-cutting (MasterPrompt)
2. **Perception** -> Faza 3 (Operational Perception) + istniejace K1
3. **Mind** -> Istniejace K5-K13 cognitive core
4. **Digital Body / Action Layer** -> Faza 4-5 (Digital Hands + Workflow)
5. **Relationship Layer** -> Faza 1 (Operator Understanding) + Faza 7 (Trust)
6. **Environment Layer** -> Faza 6 (Environment Adaptation)

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
| Mobile app | Web UI dziala na telefonie. Natywna apka to miesiace pracy bez wartosci core |
| "AI personality customization" | Osobowosc Marii ewoluuje organicznie (TraitEvolver). "Wybierz osobowosc" to gadget |
| Cloud hosting | Maria jest LOKALNA. To jest jej przewaga, nie ograniczenie |

## F. Top Architectural Risks

1. **Complexity ceiling** - ~60k+ linii kodu. Kazda faza dodaje. Bez agresywnego upraszczania, complexity zabije velocity. Mitygacja: kazda faza zaczyna sie od cleanup.

2. **LLM dependency fragility** - Ollama + NIM. Model quality zmienia sie z wersji. Mitygacja: model_registry abstraction (istnieje), benchmarki per upgrade.

3. **Operator fatigue** - Za duzo notyfikacji = operator ignoruje Marie. Mitygacja: SalienceFilter (Faza 3), batching, quiet hours (istnieje).

4. **Safety vs usefulness tension** - Za duzo gatekeeping = Maria nic nie robi. Za malo = robi glupie rzeczy. Mitygacja: graduated autonomy (Faza 7).

5. **Single point of failure** - Jeden mini PC. Dysk padnie = Maria znika. Mitygacja: backup (codziennie), GitHub sync (skonfigurowany), brak tested restore procedure.

## G. Immediate Next Milestones

### Milestone 1: OperatorModel v1 (Faza 1)
Rozszerzenie UserProfile o 5 wymiarow + RhythmDetector z historii Telegram timestamps.
-> Osobny implementation plan w `docs/plans/`

### Milestone 2: CapabilityManifest (Faza 2)
Auto-generowany z CapabilityRouter + introspection. Maria potrafi odpowiedziec "co umiesz?"

### Milestone 3: WeatherSensor + MorningBrief v2 (Faza 3)
Pogoda w porannej wiadomosci, przefiltrowana przez OperatorModel.

---

*Ostatnia aktualizacja: 2026-04-12*
*Wersja: 1.1 (korekta Eryka: relacyjny operator model, pelna percepcja operacyjna, self-model jako osobna faza, ekonomia jako cross-cutting)*
