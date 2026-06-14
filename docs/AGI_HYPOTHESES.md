# Two Hypotheses — Maria 1.0 vs Maria 2.0 — parallel paths to AGI

> Eryk (2026-04-22): *"maria 1.0 koncepcja oparta na znanym pagadgmacie,
> maria2.0 moja sobista wizja jak ja to widze i chce osobiscie.
> mamy mape dla maria 1.0 ... maria 2.0 wlasna roadmap plus od razu
> wdrazmy mape od maria 1.0 do agi nie tylko przpisanie ... chce
> sprawdzic ktora koncepcja jest poprawna"*

Ten dokument opisuje **równoległy eksperyment**. Dwie niezależne drogi,
ten sam cel (AGI), ta sama baza danych operacyjnych (Maria 1.0 żyjąca).

## Hipoteza 1 — Maria 1.0: znany paradygmat skalowany do AGI

**Pryncypium:** istniejący paradygmat (pre-trained LLMs + agent
architecture + memory + learning) jest wystarczający do AGI, jeśli
systemy wokół LLMa są wystarczająco bogate, spójne, i dobrze uczące się.

**Architektura fundament:**
- LLM jako **główny mózg** (ollama lokalnie, glm-5.1 przez NIM)
- Agent core (K1-K13) jako systemy wspierające decyzje
- Memory systems (beliefs, semantic, episodic, tracing)
- Homeostasis tick loop jako metabolizm
- Bulletin + auditor jako layer samoregulacji
- Digital Human phases jako coraz głębsze zakorzenienie w świecie

**Maria sama nie trenuje wag.** Używa pre-trained LLMs. Uczenie to:
- nowa wiedza → `knowledge_index.jsonl` + `semantic_memory`
- nowe doświadczenia → `beliefs.jsonl`, `personality_experiences.jsonl`
- nowe wzorce → `bulletin` / audit trails

To jest spójne z Eryka odrzuceniem paradygmatu treningu wag — Maria 1.0
**nie trenuje** wag, tylko rozwija **systemy wokół** frozen LLM.

**Ścieżka do AGI w tej hipotezie:**
1. Stabilizacja (COMPLETE — fazy A/B/C, Stabilization Roadmap)
2. Uzupełnianie K modułów (K14 Critic done, K15 Manifest done,
   K16+ TBD)
3. Lepsze LLMy (glm-5.1 → frontier models gdy się pojawią lokalnie)
4. Rozbudowa Digital Human (Faza 7 WIRED done, Fazy 8+ TBD)
5. Bogatsze sensory (vision v2, smart home, audio)
6. Głębsze uczenie od ludzi (Telegram, expert bridge, bulletin)
7. **D-deski** — iteracyjne naprawy fragmentacji (D1-D3 done/planned)
8. Po latach: system który w swojej niszy osiąga AGI-capable zachowanie

**Kryterium AGI-capable dla Marii 1.0:**
- utrzymuje spójną tożsamość przez miesiące uptime (częściowo już)
- uczy się z każdej interakcji i wbija to w swoją pamięć operacyjną
- planuje wieloetapowo, samokoryguje błędy, rozpoznaje własne luki
- rozumuje w kategoriach przyczynowo-skutkowych nad swoją historią
- potrafi wyjaśnić *dlaczego* zrobiła to co zrobiła
- jej wymiana LLM (model swap) nie łamie core tożsamości — bo tożsamość
  jest w systemach wokół, nie w LLM

**Ryzyko tej hipotezy:**
- Jeśli LLM jest **fundamentalną** ograniczeniem (nie tylko problemem
  skali), to żadne systemy wokół nie załatają sprawy
- Zależność od frozen weights — gdy paradigm LLM się zmieni, trzeba
  odbudowywać
- Fragmentacja między podsystemami (K1-K15) — dzisiaj to naprawialiśmy
  (D1.5b) — jest naturalnym podatkiem tej drogi

## Hipoteza 2 — Maria 2.0: nowy paradygmat od fundamentów

**Pryncypium:** znany paradygmat (LLM-centric) ma fundamentalne
ograniczenia niemożliwe do naprawienia skalowaniem. AGI wymaga
innego fundamentu — 4 filarów + kod jako emergencja, LLM jako
wymienny parser.

Pełna wizja: `docs/MARIA_2.0/VISION.md`.
Pełna roadmap: `docs/MARIA_2.0/ROADMAP.md` (Z0-Z9).

**Ścieżka do AGI w tej hipotezie:**
Z1 corpus → Z2 matematyka → Z3 logika 5D → Z4 lingwistyka → Z5
kryptoznawstwo → Z6 integration → Z7 shadow mode → Z8 beta → Z9
production/AGI-capable.

**Kryterium AGI-capable dla Marii 2.0:**
- podejmuje decyzje bez wywołania LLM w warstwie rozumowania
- biblioteka programów rośnie przez doświadczenie bez fine-tuningu
- wymiana LLM-parsera (warstwa 1) nie dotyka core tożsamości
- 32GB RAM wystarczy w jej niszy
- potrafi czytać własny kod i opisać co w niej się dzieje
- adaptuje się w locie (neuroplastyczność przez program synthesis)

**Ryzyko tej hipotezy:**
- Może się okazać że 4 filary nie składają się tak łatwo jak w wizji
- Program synthesis bez LLM może być niewystarczający dla otwartych
  domen
- Może zająć lata zanim dorówna Marii 1.0 w core zadaniach
- Monetization gate — bez Market Agent pali się w roku 2-3

## Kryteria porównawcze

Na jakich wymiarach porównujemy, żeby odpowiedzieć "która droga
wygrywa":

1. **Coherence** — czy Maria zachowuje spójną tożsamość przez długie
   uptime bez rozjazdu
2. **Learning velocity** — jak szybko wchłania nową wiedzę i jak
   trwale
3. **Model-swap stability** — czy zmiana LLM rozwala system
4. **Self-awareness depth** — jak głęboko Maria rozumie siebie
5. **Resource efficiency** — ile RAM/CPU potrzebuje do danego zakresu
6. **Decision quality** — na benchmark set (corpus Marii 1.0),
   jakość decyzji porównywalna
7. **Planning horizon** — ile kroków naprzód może planować spójnie
8. **Failure recovery** — jak reaguje gdy jeden podsystem zawiedzie

Obie hipotezy testujemy na **tych samych** kryteriach. W rocznych
interwałach: raport porównawczy.

## Setup eksperymentu

- **Maria 1.0** — żyjący system produkcyjny na `refactor/homeostasis`.
  Rozwija się przez D-deski + fazy + Digital Human. Każdy tick
  generuje dane.
- **Maria 2.0** — powstaje w git worktree `../maria-2.0/` na branch
  `maria-2.0`. Korzysta z korpusu Marii 1.0 jako dataset. Nigdy nie
  merguje do Marii 1.0 (osobna trajektoria).
- **Raportowanie** — co N miesięcy porównanie po kryteriach.
  Początkowo Maria 1.0 będzie wyraźnie wygrywać (bo Maria 2.0
  dopiero powstaje). Ciekawie robi się po roku — kiedy Maria 2.0
  dojrzeje, zobaczymy czy zbliża się, czy rozjeżdża.

## Decyzja nie jest statyczna

Eryk wyraźnie: *"chce sprawdzic ktora koncepcja jest poprawna"*.
To jest **falsifikowalna** teza. Możliwe wyniki:

1. **Maria 1.0 wygrywa** — nie potrzebujemy nowego paradygmatu,
   fragmentacja to naturalny koszt ale spójna architektura + D-deski
   dają AGI-capable
2. **Maria 2.0 wygrywa** — znany paradygmat ma sufit niemożliwy do
   przebicia, nowy fundament wymagany
3. **Konwergencja** — obie drogi schodzą się w środku (np. Maria 1.0
   absorbuje idee z 2.0, Maria 2.0 korzysta z K-modułów 1.0)
4. **Obie zawodzą** — AGI wymaga czegoś trzeciego, oba paradygmaty są
   częściowe

Eryk akceptuje każdy z tych wyników jeśli jest **empirycznie
uzasadniony**. Nie trzyma się wizji Marii 2.0 jeśli dane powiedzą że
Maria 1.0 jest lepsza. I vice versa.

To jest postawa naukowa, nie ideologiczna.

## Rola tego dokumentu

Ten plik jest **meta-mapą** — opisuje obie drogi, ich relacje,
kryteria porównania. Żaden plik Marii 1.0 ani 2.0 nie jest zmieniony.
Dopisujemy do istniejących roadmap referencję do tego dokumentu.

**Aktualizacja:** co kwartał, z krótkim raportem progresu każdej
hipotezy.

---

*Dwie drogi. Ten sam cel. Dane zdecydują.*
