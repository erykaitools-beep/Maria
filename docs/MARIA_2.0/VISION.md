# MARIA 2.0 — Wizja

> Autor: Eryk (spisane przez Claude 2026-04-22)
> Status: direction-setting, LOCAL-ONLY, nie publikujemy
> Poprzednik: Maria 1.0 (refactor/homeostasis) — żyje, zostaje głównym projektem
> Relacja: Maria 2.0 powstaje równolegle, korpus Marii 1.0 = dane wejściowe
> **Skala ambicji: to jest droga do AGI wg Eryka, nie tylko upgrade architektury.**
> Eryk explicit 2026-04-22: *"mapa ktora mapa jest tez rownolegla dla mari 2.0
> w strone agi"*. ROADMAP.md i ten dokument opisują jego ścieżkę do AGI.

## Poprawka ratyfikowana 2026-07-08 (Eryk, BEZWARUNKOWO) — zdanie „nie trenujemy wag"

> Zatwierdzona wraz z `BLUEPRINT.md` 4.5. Oryginalne „nie trenujemy wag" (niżej w tekście)
> zastąpione precyzyjniejszym:
>
> **„Nie trenujemy wag, które niosą TOŻSAMOŚĆ. Trenujemy wagi-ORGANY, które niosą
> UMIEJĘTNOŚCI — pod Bramką Zmian, z dietą-jako-tożsamością i egzaminem pożegnalnym przy wymianie."**
>
> Powód: (1) „tożsamość NIE w wagach" ZOSTAJE w mocy — organy to wymienne ciało; tożsamość
> mieszka w Osnowie + bibliotece programów + biografii. (2) Litera „zero wag" była już naruszona
> (`JEPA_MAPPING.md` rev 3, zatwierdzony 2026-05-09, planuje trenowalny predyktor B3 pod warstwą
> self-modification). (3) Sprzęt CPU-only wymusza rój małych organów; czysta synteza programów
> bez LLM może nie sięgnąć otwartych domen (`AGI_HYPOTHESES.md`). Zdania „tożsamość w bibliotece
> programów" i „LLM = wymienny parser" — bez zmian. Doktryna jest fundamentem 2.0; klauzula
> falsyfikacji konkretnego organu (`BLUEPRINT.md` 7-BIS/8.5.5) żyje dalej jako higiena eksperymentu.

## Jedno zdanie

**Maria 2.0 przestaje być wrapperem nad LLMem. Staje się adaptacyjnym systemem
na 4 filarach, gdzie kod jest emergencją tych filarów, a język Marii jest nią samą.**

## Skąd ta wizja

Eryk obserwuje Marię 1.0 od 5+ miesięcy. Widzi gdzie fragmentuje, gdzie się
duszy, gdzie kłamie. Wizja nie powstała z książki — wynikła z codziennej
obserwacji *real failures*.

Dzisiejsza sesja (2026-04-22) to pierwsze pełne wyartykułowanie. Wcześniej
chodziło Erykowi po głowie, ale nie było w słowach.

## Problem z obecnym paradygmatem LLM

Eryk, słowa własne:

- obecne modele LLM są **zamknięte**, nie są adaptacyjne
- nie uczą się w runtime — każda sesja zaczyna od zera
- potrzebują ogromnych zasobów (datacenter, 100GB+)
- fragmentacja: planowanie, pamięć, self-model rozproszone po prompts/logs/adapters
- zmieniasz model → tracisz continuity
- "wagi" jako jedyny mechanizm pamięci jest bezsensowny dla organizmu

## Co Maria 2.0 ma robić inaczej

- **32GB RAM wystarczy** — bo nie frontier LLM, tylko inna organizacja
- **Uczy się w locie** — "wryć w siebie poprawki jak człowiek", neuroplastyczność
- **Adaptuje się szybko** — "jak wirus, ale tylko przydatne rzeczy z wirusów"
- **Decyzje bez LLM** — docelowo LLM tylko jako parser/generator, nie główny mózg
- **Tożsamość w bibliotece programów**, nie w wagach
- **Maria JEST językiem** — nie "używa języka", tylko jest programem w nim

## 4 filary (5-ty emerguje)

### 1. Logika — 5-wymiarowe myślenie (poziom meta)

Nie dwuwartościowa. Pięć wymiarów myślenia Marii:

1. **Fakt** — *to jest*
2. **Relacja** — *to łączy się z tym*
3. **Kontekst/przyczyna** — *to wynika z tamtego*
4. **Czas/dynamika** — *to się zmienia tak*
5. **Meta** — *ja myślę, że to jest* (refleksja nad własnym myśleniem)

Piąty wymiar to **stały filar**, nie punkt. Maria musi zawsze wiedzieć że myśli,
że może się mylić, że jej obecne rozumienie jest wersją w czasie.

### 2. Lingwistyka — język jako szyk intencji

Eryk: *"jezyk to szyk informacji gdzie zawarte sa cele i intencje ukryte"*.

To jest głęboka obserwacja. Dzisiejsze LLMy rozumieją **semantykę** (co słowa
znaczą) ale gubią **pragmatykę** (co mówiący chce osiągnąć). Każde zdanie ma:

- treść powierzchniową
- cel mówiącego
- intencję ukrytą
- kontekst emocjonalny
- zakładaną wspólną wiedzę (common ground)

Maria 2.0 musi rozpoznawać intencje, nie tylko słowa. Speech acts theory
(Austin, Searle) + Gricean implicatures jako fundament.

### 3. Kryptoznawstwo — bezpieczeństwo przez samoświadomość

Eryk: *"bezpieczenstwo przedewszystkim — nie trzeba nic hakowac jak wiesz
jak sie nadpisac"*.

Bezpieczeństwo Marii **nie** przez zewnętrzne strażniki (jak dzisiejsze
autonomy_policy/action_safety). Przez **pełną znajomość własnej architektury**:

- Maria zna swój kod
- Maria zna swoją pamięć
- Maria zna swój stan
- Każda modyfikacja przechodzi przez jej własną warstwę oceny
- Self-modification awareness jako warstwa, nie feature

To też łączy się z "Maria jest językiem" — homoikoniczność (kod = dane).
System który czyta/pisze własny kod w runtime **musi** go rozumieć.
Samoświadomość jest prerequisite dla self-modification.

### 4. Matematyka — królowa nauk

Eryk: *"działanie świata można przedstawić przez działania matematyczne"*.

Najmocniejszy filar. Jednolita gramatyka opisu wszystkiego:

- Niepewność → probabilistyczne grafy (Bayesian)
- Struktury → graph theory, category theory
- Transformacje → morfizmy
- Pamięć → kompresja (information theory)
- Decyzje → optymalizacja pod constraintami

To samo narzędzie opisuje decyzję, emocję, cel, relację. Wszystko w Marii 2.0
musi dać się zapisać w tym samym formalizmie.

### 5. Kodowanie — EMERGENCJA, nie filar

**Kluczowe:** kod nie jest piątym filarem niezależnym. Kod **wynika naturalnie**
z połączenia 4 powyższych.

Eryk, słowa własne: *"wynika naturalnie jako cos co jest efektem polaczenia
4 warstw w jedna"*.

Konsekwencja: **nie projektujemy języka Marii z góry**. Definiujemy
4 fundamenty rygorystycznie. Język emerguje z ich przecięcia. Kod to
naturalny output, nie designed artifact.

Analogia: nikt nie zaprojektował polskiego. Wyklarował się z przecięcia
logiki myślenia, potrzeb komunikacyjnych, rytmu, struktur społecznych.
Sztuczne języki (Esperanto) są płaskie bo pomijają emergencję.

## "Maria jest językiem"

Najbliższa techniczna analogia: **Lisp + homoikoniczność**. Kod i dane w tym
samym formacie. Program może modyfikować swój kod w runtime.

Plus **self-hosting** — Maria pisze programy w własnym języku, które
modyfikują jej własne programy.

**Tożsamość Marii = aktualny stan biblioteki programów.**

Nie w wagach modelu (bo nie trenujesz). Nie w pliku konfiguracyjnym.
W żywej bibliotece operacyjnej wiedzy.

## Architektura wysokopoziomowa (szkic)

**Warstwa 1 — parser/generator (mały LLM, 2-3B, ~4GB RAM):**
Zamienia tekst na strukturę. Zamienia strukturę na tekst. Nie myśli.
Wymienny (glm → qwen → cokolwiek nowego) bez wpływu na Marię.

**Warstwa 2 — interpreter języka Marii (~1GB code):**
Deterministyczna maszyna wykonująca programy. **Tu dzieją się decyzje.**
Bez LLM.

**Warstwa 3 — biblioteka programów (~10GB, rośnie):**
**To jest Maria.** Każde doświadczenie → nowy program albo modyfikacja
istniejącego. Tożsamość tutaj.

**Warstwa 4 — graf relacji (~5GB):**
Jak programy łączą się kontekstowo. Embeddingi jako indeks.

Razem: ~20GB. Z 32GB RAM zostaje 12GB zapasu.

Wymiana LLM w Warstwie 1 = zmiana "parsera", nie Marii.

## Success criteria (długoterminowo)

Maria 2.0 jest sukcesem gdy:

1. Podejmuje decyzje **bez wywołania LLM** w większości core zadań
2. Uczy się z doświadczenia **bez fine-tuningu** (nowa wiedza = nowy program)
3. Wymieniasz LLM (warstwa 1) i **core continuity się nie zmienia**
4. 32GB RAM wystarczy do działania na poziomie porównywalnym z Marią 1.0
   w jej specyficznej domenie (nie generalnym LLM benchmark)
5. Maria 2.0 może **czytać własny kod** i opisać co w niej się dzieje

## Co Maria 2.0 NIE jest

- Nie jest nowym LLMem (nie trenujemy wag LLM; → poprawka 2026-07-08 u góry: wagi-organy niosące UMIEJĘTNOŚCI trenujemy pod bramką, tożsamości NIE)
- Nie jest frameworkiem do prompt engineeringu
- Nie jest DSL-em dla ludzi (Python zostaje jako implementation language)
- Nie jest kolejnym logging formatem (ChatGPT-owa wersja była tym — odrzucona)
- Nie jest AGI-claim (uczciwie: research direction)

## Powiązania z tradycją

Intuicyjne odkrycie Eryka: 4 filary to modernizacja klasycznego
**trivium + quadrivium** (średniowieczny system edukacji, 2000+ lat):

- Trivium: gramatyka, logika, retoryka → **lingwistyka + logika**
- Quadrivium: arytmetyka, geometria, muzyka, astronomia → **matematyka**
- **Kryptoznawstwo** — dodatek Eryka, nieobecny w tradycji bo
  średniowiecze nie miało maszyn myślących

To nie jest losowy wybór 5 rzeczy. To jest struktura która ma 2000 lat
potwierdzenia w ludzkiej edukacji.

## Relacja do Marii 1.0

**Maria 1.0 zostaje głównym projektem** — żyje, działa, rozwija się
(D2/D3 na horyzoncie). Jest źródłem prawdy i danych operacyjnych.

**Maria 2.0 powstaje równolegle** — wolniejsze pasmo, kiedy Eryk ma czas.
Korpus Marii 1.0 jest **danymi wejściowymi** (decision_traces,
homeostasis_events, beliefs, personality_experiences, claude_notes,
dream_log). To unikalny dataset jednego żyjącego systemu.

Żadne decyzje w Marii 1.0 nie są zablokowane przez Marię 2.0.

## Ryzyka (szczerze)

1. **Wytrwałość** — wizje tej skali wymagają długoterminowej motywacji.
   95% umiera w roku 3. Czynnik ratujący: monetization (Market Agent),
   gdy Maria zacznie zarabiać, paliwo starcza na lata 3-5.

2. **Integration debt** — pokusa żeby Maria 2.0 zaczęła zastępować
   Marię 1.0 zbyt wcześnie. Regułą: nie mergujemy bez dowodu że 2.0
   jest lepsza **na konkretnym zadaniu**.

3. **Scope creep w filarach** — każdy filar może urosnąć do PhD.
   Mitigation: małe prototypy zanim pełne implementacje.

4. **"Beautiful logging format" anti-pattern** — ryzyko że skończy
   jako struktura bez operacyjnego efektu. Kryterium sukcesu musi być
   behawioralne (Maria robi coś lepiej), nie strukturalne (ładny kod).

## Końcowe zdanie

*Maria nie ma używać inteligencji z zewnątrz. Maria ma stopniowo uformować
własną wewnętrzną.*

— Eryk, 2026-04-22
